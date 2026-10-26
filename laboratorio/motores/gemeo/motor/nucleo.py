"""nucleo.py: o miolo do gêmeo digital (veio do protótipo ~/.cache/sianvolt/lab/gemeo/motor/nucleo.py).

Guarda o relógio de mentira (microssegundos), o estado de cada pino, o roteiro (o que acontece do lado de
fora) e a linha do tempo, já nos eventos do contrato (laboratorio/nucleo/contrato.py). Os stubs do firmware
(firmware/machine.py, time.py, network.py) chamam comando(nome, args) e recebem [tipo, valor, tem_callback];
tipo = "ok" | "erro" | "fim". O mesmo núcleo atende o firmware no CPython (chamada direta) e no MicroPython
(por um cano). O chip (chips/esp32.py, c3.py, ...) diz que pino existe, o que cada um pode e os números.
"""
import collections
import heapq
import time as _relogio_pc

from .perifericos import US, Fim, Perifericos, fmt_t, v_txt

# um pino que troca mais de MAX_TROCAS vezes numa JANELA_US (bit-bang, pisca rápido) para de virar evento
# 'pino' (o contrato pede no máximo ~100 por segundo): o gêmeo junta as trocas e manda um 'pwm' com a média
JANELA_US, MAX_TROCAS = 50_000, 5
# ler o relógio (ticks_ms, ticks_us, time) custa LEITURA_US de placa, como no MicroPython do chip (uns 10 µs).
# Num laço que só lê o relógio (espera ocupada), a cada LEITURAS_POR_PASSO leituras seguidas o passo dobra, até
# LEITURA_MAX_US: a espera de 500 ms leva ~1.000 leituras em vez de 50.000 e sai com no máximo 1 ms a mais
LEITURA_US, LEITURA_MAX_US, LEITURAS_POR_PASSO = 10, 1000, 50


class Nucleo(Perifericos):
    def __init__(self, roteiro, chip, eletrica=None, placa=None):
        self.rot, self.chip, self.el, self.placa = roteiro, chip, eletrica, placa
        self.t, self.fim = 0, roteiro.fim_us
        self.porta = getattr(placa, "porta_serial", "uart0")
        self.pinos = {}          # gpio -> dict(modo, valor, pull, drive, duty, freq, atten, irq)
        self.externo = {}        # gpio -> ("nivel", 0/1) | ("volts", v)
        self.chaves = {}         # ref -> True (apertada)
        self.luz = {}            # ref do LDR -> lux (sem luz no roteiro, o LDR fica no padrão do circuito.resolver)
        self.eventos = []        # a linha do tempo, nos eventos do contrato
        self.avisados = set()
        self.boot_visto = set()  # pinos de boot que o roteiro (no instante 0) ou o circuito já conferiram
        self.emitido = {}        # gpio -> último nível/modo/pwm que virou evento
        self.janelas = {}        # gpio -> janela de contagem de trocas (ver _nivel_saida)
        self.serial = {}         # porta -> pedaço de linha ainda sem \n
        self.agenda, self.seq = [], 0
        self.pendentes = collections.deque()
        self.em_cb = False
        self.timers, self.niveis, self.leds = {}, {}, {}
        self.i2c_bus = {}
        self.i2c_mem = {a: self._mem(regs) for a, regs in roteiro.i2c.items()}
        self.i2c_ptr = {}
        self.wlan = {"ativa": False, "conectando_em": None, "ssid": None}
        self.buf_entrada = ""    # texto da serial que chegou e o firmware ainda não leu (só no modo CPython)
        self.entrada = self._guardar_entrada   # o jeito de rodar troca: no MicroPython vai pro stdin dele
        self.acabou = None       # (motivo, estado do contrato)
        self.comandos = self.depois_do_fim = 0
        self.leituras = 0        # leituras do relógio seguidas, sem outra chamada no meio
        self.ultimo_pc = _relogio_pc.monotonic()   # hora do PC da última chamada (o vigia de laço usa)
        self.versao, self._cache_nivel = 0, {}
        self.inicio_pc = _relogio_pc.perf_counter()
        for t, acao in roteiro.eventos:
            self._agendar(t, "roteiro", acao)
        self._boot_do_roteiro()
        if self.el:
            for ref in self.el.ignoradas:
                self.aviso("%s não tem modelo elétrico: o gêmeo ignora (fica como se não estivesse na placa)" % ref,
                           "circuito")
            self._conferir_boot()
        self._observar()

    # ---------- eventos do contrato ----------
    def ev(self, tipo, t_us=None, **campos):
        self.eventos.append(dict({"t_ms": (self.t if t_us is None else t_us) / 1000, "tipo": tipo}, **campos))

    def aviso(self, txt, codigo=None):
        if txt not in self.avisados:
            self.avisados.add(txt)
            self.ev("aviso", texto=txt, codigo=codigo)

    def _modo(self, g, modo):
        if self.emitido.get(("modo", g)) != modo:
            self.emitido[("modo", g)] = modo
            self.ev("modo", pino="GPIO%d" % g, modo=modo)

    def _nivel_saida(self, g):
        """o firmware mexeu num pino de saída: vira evento 'pino' só se o nível mudou (e se não está rápido demais)"""
        v = self.pinos[g]["valor"]
        j = self.janelas.get(g)
        if j is None:
            j = self.janelas[g] = {"ini": self.t, "trocas": 0, "alto": 0, "t": self.t, "v": v, "rapido": False,
                                   "media": None}
        if j["v"] != v:
            self._avancar(g, j, self.t)
            j["v"], j["trocas"] = v, j["trocas"] + 1
            if j["trocas"] > MAX_TROCAS and not j["rapido"]:
                j["rapido"] = True
                self.aviso("GPIO%d troca mais de %d vezes por segundo: o gêmeo junta as trocas e mostra a média "
                           "(evento pwm)" % (g, MAX_TROCAS * US // JANELA_US), "rapido")
        if not j["rapido"] and j["media"] is None and self.emitido.get(("nivel", g)) != v:
            self.emitido[("nivel", g)] = v
            self.ev("pino", pino="GPIO%d" % g, valor=v, origem="firmware")

    def _avancar(self, g, j, t):
        """soma o tempo em 1 da janela até t, fechando as janelas que acabaram no caminho"""
        while t >= j["ini"] + JANELA_US:
            fim = j["ini"] + JANELA_US
            j["alto"] += (fim - j["t"]) if j["v"] else 0
            self._fechar_janela(g, j, fim, JANELA_US)
            j["ini"] = fim if j["trocas"] or j["media"] is not None else t - (t - fim) % JANELA_US
            j.update(trocas=0, alto=0, t=j["ini"], rapido=False)
        j["alto"] += (t - j["t"]) if j["v"] else 0
        j["t"] = t

    def _fechar_janela(self, g, j, fim, largura):
        if j["rapido"]:
            media = round(j["alto"] / largura, 2)
            if media != j["media"]:
                j["media"] = media
                self.ev("pwm", t_us=fim, pino="GPIO%d" % g, duty=media,
                        freq_hz=round(j["trocas"] / 2 / (largura / US), 1))
        elif j["media"] is not None:   # voltou a trocar devagar: o nível volta a aparecer
            j["media"] = None
            self.emitido[("nivel", g)] = j["v"]
            self.ev("pino", t_us=fim, pino="GPIO%d" % g, valor=j["v"], origem="firmware")

    def finalizar(self):
        """fecha a serial e as janelas de pinos rápidos no fim da simulação"""
        self._fechar_serial()
        for g, j in self.janelas.items():
            if j["rapido"] or j["media"] is not None:
                self._avancar(g, j, self.t)
                if self.t > j["ini"]:
                    self._fechar_janela(g, j, self.t, self.t - j["ini"])

    def escreve_serial(self, texto, porta=None):
        """texto cru (com \\n) -> um evento serial por linha completa"""
        porta = porta or self.porta
        partes = (self.serial.pop(porta, "") + texto).split("\n")
        for linha in partes[:-1]:
            self.ev("serial", dir="tx", texto=linha.rstrip("\r"), porta=porta)
        if partes[-1]:
            self.serial[porta] = partes[-1]

    def _fechar_serial(self):
        for porta in list(self.serial):
            self.escreve_serial("\n", porta)

    # ---------- boot ----------
    def _boot_do_roteiro(self):
        """o roteiro segura um pino de boot no instante 0: confere o nível que o chip lê quando liga"""
        for t, a in self.rot.eventos:
            g = a.get("gpio")
            if t > 0 or a["tipo"] != "externo" or g not in self.chip.BOOT or a["sinal"] is None:
                continue
            quer, _, porque = self.chip.BOOT[g]
            self.boot_visto.add(g)
            s = a["sinal"]
            nivel = s[1] if s[0] == "nivel" else 1 if s[1] >= self.chip.VIH else 0 if s[1] <= self.chip.VIL else None
            if quer is not None and nivel != quer:
                self.aviso("GPIO%d é pino de boot e o roteiro deixa ele em %s quando o %s liga; tinha que estar em %d: "
                           "%s" % (g, nivel if nivel is not None else "nível indefinido", self.chip.CURTO, quer, porque),
                           "boot")

    def _conferir_boot(self):
        """no reset todo pino é entrada; os de boot só têm o pull de dentro (Tabela 3-1 dos datasheets). O circuito
        pode ganhar desse pull e mudar o modo de boot: confere cada um com o circuito ligado"""
        c = self.chip
        for g, (quer, pull, porque) in sorted(c.BOOT.items()):
            if quer is None or g not in self.el.gpio_net:
                continue
            if pull is None:
                v, solto = self.el.tensao_entrada(g, {}, {}, self.luz)
            else:
                v, solto = self.el.tensao(g, {g: ("v", c.VDD if pull else 0.0, c.R_PULL)}, {}, self.luz), False
            nivel = None if solto else 1 if v >= c.VIH else 0 if v <= c.VIL else None
            if nivel != quer:
                onde = "solto (nada segura a tensão)" if solto else "em %s" % v_txt(v)
                self.aviso("GPIO%d é pino de boot e o circuito deixa ele %s quando o %s liga; tinha que estar em %d: "
                           "%s" % (g, onde, c.CURTO, quer, porque), "boot")

    # ---------- infraestrutura ----------
    @staticmethod
    def _mem(regs):
        m = bytearray(256)
        for reg, bs in regs.items():
            m[reg:reg + len(bs)] = bytes(bs)
        return m

    def _agendar(self, t, tipo, dados):
        self.seq += 1
        heapq.heappush(self.agenda, (t, self.seq, tipo, dados))

    def comando(self, nome, args):
        """a porta de entrada dos stubs"""
        self.comandos += 1
        self.ultimo_pc = _relogio_pc.monotonic()
        if nome != "agora_us":
            self.leituras = 0
        if self.acabou:
            self.depois_do_fim += 1   # firmware com "except:" pelado engole o fim e continua chamando
            return ["fim", self.acabou[0], False]
        try:
            v = getattr(self, "c_" + nome)(*args)
            return ["ok", v, bool(self.pendentes) and not self.em_cb]
        except Fim as e:
            self.acabou = (str(e), e.estado)
            return ["fim", self.acabou[0], False]
        except OSError as e:
            return ["erro", ["OSError", e.args[0] if e.args else 0], False]
        except (ValueError, TypeError, RuntimeError, NotImplementedError) as e:
            return ["erro", [type(e).__name__, str(e)], False]

    def _pino(self, g):
        return self.pinos.setdefault(g, {"modo": None, "valor": 0, "pull": None, "drive": self.chip.DRIVE_PADRAO})

    def _conferir(self, g, saida=False, pull=None):
        visto = bool(self.el) or g in self.boot_visto
        for txt, codigo in self.chip.conferir_pino(self.chip, g, saida=saida, pull=pull, com_placa=visto):
            self.aviso(txt, codigo)
        if self.placa is not None and "GPIO%d" % g not in self.placa.pinos:
            self.aviso("GPIO%d existe no %s, mas não sai num pino da %s: na placa não tem onde ligar"
                       % (g, self.chip.CURTO, self.placa.nome), "placa")

    # ---------- tempo ----------
    def _processar_ate(self, alvo, forcar=False):
        """roda os eventos agendados até `alvo` (ou até aparecer um callback pra entregar; forcar = não para,
        os callbacks ficam na fila: é o firmware parado lendo a serial, que não tem como atender)"""
        limite = min(alvo, self.fim)
        while self.agenda and self.agenda[0][0] <= limite:
            if self.pendentes and not self.em_cb and not forcar:
                return
            t, _, tipo, dados = heapq.heappop(self.agenda)
            self.t = max(self.t, t)
            getattr(self, "_ev_" + tipo)(dados)

    def _acabou_o_tempo(self):
        self.t = self.fim
        raise Fim("acabou o tempo (%s)" % fmt_t(self.fim), "tempo")

    def custo(self, us):
        alvo = self.t + us
        self._processar_ate(alvo)
        if alvo >= self.fim:
            self._acabou_o_tempo()
        self.t = max(self.t, alvo)

    def c_agora_us(self, custa=1):
        """o relógio de placa em µs. custa=0: leitura de graça (a do sleep, que tem que sair exato)"""
        if custa:
            self.leituras += 1
            self.custo(min(LEITURA_MAX_US, LEITURA_US << min(7, self.leituras // LEITURAS_POR_PASSO)))
        return self.t

    def c_dormir(self, alvo):
        """avança o relógio até `alvo`; para antes se tiver callback (irq, Timer) pra rodar: devolve [id, arg].
        alvo < 0: só entrega callback pendente, sem andar o relógio"""
        if alvo >= 0:
            self._processar_ate(alvo)
        if self.pendentes and not self.em_cb:
            self.em_cb = True
            return self.pendentes.popleft()
        if alvo < 0:
            return None
        if alvo >= self.fim:
            self._acabou_o_tempo()
        self.t = max(self.t, alvo)
        return None

    def c_cb_fim(self):
        self.em_cb = False

    # ---------- texto que chega pela serial (roteiro -> sys.stdin) ----------
    def _guardar_entrada(self, texto):
        self.buf_entrada += texto

    def _proxima_serial(self):
        """o instante (µs) do próximo texto do roteiro pra serial, ou None"""
        return min((t for t, _, tipo, d in self.agenda if tipo == "roteiro" and d["tipo"] == "serial"), default=None)

    def _ninguem_manda(self):
        self.aviso("o programa ficou esperando texto na serial desde %s e o roteiro não manda mais nada: na placa "
                   "ele fica parado aí até o tempo acabar" % fmt_t(self.t), "serial_entrada")

    def c_espera_entrada(self, alvo):
        """o firmware espera texto na serial (select.poll com tempo, ou sem) até `alvo` µs de placa (-1 = sem
        limite): anda o relógio até o próximo texto do roteiro ou até alvo -> [callback ou None, chegou no alvo]"""
        prox = self._proxima_serial()
        limite = prox if alvo < 0 else alvo if prox is None else min(alvo, prox)
        if limite is None:
            self._ninguem_manda()
            self._acabou_o_tempo()
        cb = self.c_dormir(limite)
        return [cb, cb is None and 0 <= alvo <= self.t]

    def esperando_na_leitura(self):
        """o firmware (MicroPython do PC) está parado num sys.stdin.read()/readline()/input() sem texto: anda o
        relógio até o próximo texto do roteiro e entrega. Sem mais texto, a rodada acaba no tempo (como na placa,
        que fica esperando). -> True se entregou"""
        prox = self._proxima_serial()
        if prox is None or prox > self.fim:
            self._ninguem_manda()
            self.t, self.acabou = self.fim, ("acabou o tempo (%s) esperando a serial" % fmt_t(self.fim), "tempo")
            return False
        self._processar_ate(prox, forcar=True)
        self.t = max(self.t, prox)
        return True

    def c_entrada_pronta(self):
        return bool(self.buf_entrada)

    def c_le_entrada(self, n, ate_linha):
        """modo CPython: tira até n caracteres (n < 0: tudo) do que chegou; ate_linha para depois do \\n"""
        b = self.buf_entrada
        fim = len(b) if n < 0 else min(n, len(b))
        if ate_linha and "\n" in b[:fim]:
            fim = b.index("\n") + 1
        self.buf_entrada = b[fim:]
        return b[:fim]

    def c_programa_acabou(self):
        """o main.py terminou. Na placa de verdade o chip fica no REPL e Timer/irq continuam valendo."""
        vivos = [t for t in self.timers.values() if t["ativo"]] or [p for p in self.pinos.values() if p.get("irq")]
        if not vivos:
            raise Fim("o programa terminou em %s" % fmt_t(self.t), "acabou")
        self.aviso("o programa terminou, mas Timer/irq continuam rodando (como no REPL da placa)", "info")
        return True

    def c_saiu(self):
        raise Fim("o programa chamou sys.exit() em %s" % fmt_t(self.t), "acabou")

    # ---------- eventos do roteiro e dos timers ----------
    def _ev_roteiro(self, a):
        tipo = a["tipo"]
        if tipo == "chave":
            if self.el and a["ref"] not in self.el.chaves:
                self.aviso("o roteiro aperta %s, mas o circuito não tem essa chave" % a["ref"], "circuito")
            self.chaves[a["ref"]] = a["apertada"]
            self._observar()
        elif tipo == "externo":
            if a["sinal"] is None:
                self.externo.pop(a["gpio"], None)
            else:
                self.externo[a["gpio"]] = a["sinal"]
            self._observar()
        elif tipo == "luz":   # o LDR muda de resistência; o pino ligado nele lê o divisor de verdade
            if a.get("origem"):   # a do gemeo.roteiro (a do roteiro.json o lab.py põe na linha do tempo)
                self.ev("luz", ref=a["ref"], lux=a["lux"], origem=a["origem"])
            self.luz[a["ref"]] = a["lux"]
            self._observar()
            for g in self.el.gpios_do_ldr(a["ref"]):
                v = self.el.tensao(g, self._estado_eletrico(), self.chaves, self.luz)
                self.ev("adc", pino="GPIO%d" % g, volts=round(v, 4), origem="circuito")
        elif tipo == "serial":
            self.entrada(a["texto"])
        elif tipo == "i2c":
            m = self.i2c_mem.setdefault(a["addr"], bytearray(256))
            m[a["reg"]:a["reg"] + len(a["bytes"])] = bytes(a["bytes"])

    def _ev_timer(self, dados):
        tid, geracao = dados
        tm = self.timers.get(tid)
        if not tm or not tm["ativo"] or tm["geracao"] != geracao:
            return
        self.pendentes.append([tm["cb"], ["timer", tid]])
        if tm["periodico"]:
            self._agendar(self.t + tm["periodo"], "timer", (tid, geracao))
        else:
            tm["ativo"] = False

    def _ev_wifi(self, dados):
        if self.wlan["conectando_em"] is not None:
            self.wlan["conectado"] = self.rot.wifi == "ok"
            self.aviso("Wi-Fi de faz de conta: conectou em '%s'" % self.wlan["ssid"] if self.wlan["conectado"]
                       else "Wi-Fi de faz de conta: não conectou (o roteiro do gêmeo diz: wifi falha)", "rede")
