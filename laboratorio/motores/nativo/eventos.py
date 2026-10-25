"""eventos.py: a linha do tempo do firmware nativo ({"t": us, "ev": ...}) vira eventos do contrato.

Também confere as regras de pino da placa: pino que a placa não tem, saída num pino só-entrada, pino da
flash e pino de boot (perfis de chip do gêmeo, motores/gemeo/chips/, tirados dos datasheets), e junta em
"pwm" um pino que troca rápido demais sem parar (mais de 20 vezes em 100 ms), pra não inundar a linha do
tempo; um repique de botão (poucas trocas juntas) fica como está.
"""
import importlib
import json
import math
import re
from collections import defaultdict

MODOS = {"INPUT": "entrada", "OUTPUT": "saida", "OUTPUT_OPEN_DRAIN": "saida", "INPUT_PULLUP": "pullup",
         "INPUT_PULLDOWN": "pulldown", "ANALOG": "adc", "PWM": "pwm"}
SAIDAS = {"saida", "pwm"}
JANELA_MS, BLOCO_MS, DENSO = 10.0, 100.0, 20   # média por janela de 10 ms onde o bloco de 100 ms tem > 20 trocas
SINAIS = {11: "SIGSEGV: mexeu numa memória que não podia (ponteiro ou vetor fora do lugar)",
          6: "SIGABRT: abort() (assert, ou o C++ desistiu)", 8: "SIGFPE: conta inválida (divisão inteira por zero)",
          7: "SIGBUS: acesso à memória desalinhado", 4: "SIGILL: instrução inválida", 15: "SIGTERM: desligado"}


def nome_pino(n, sabor):
    """número do Arduino -> nome físico: 23 -> GPIO23 (esp32); 13 -> D13, 14 -> A0 (uno)"""
    if sabor == "uno":
        return "A%d" % (n - 14) if 14 <= n <= 21 else "D%d" % n
    return "GPIO%d" % n


def numero(pino):
    """nome físico -> número do Arduino: GPIO4 -> 4, D2 -> 2, A0 -> 14"""
    m = re.fullmatch(r"(GPIO|GP|D|A)?(\d+)", str(pino))
    if not m:
        raise ValueError("pino que o nativo não entende: %r" % (pino,))
    return int(m.group(2)) + (14 if m.group(1) == "A" else 0)


def argumentos(entradas):
    """entradas do Pedido -> argumentos do firmware (--entrada, --serial)"""
    args = []
    for e in entradas:
        ms = "%.3f" % e["t_ms"]
        if "serial" in e:
            args += ["--serial", ms, e["serial"]]
        elif "volts" in e:
            args += ["--entrada", "%s %d %dmV" % (ms, numero(e["pino"]), round(e["volts"] * 1000))]
        else:
            args += ["--entrada", "%s %d %d" % (ms, numero(e["pino"]), 1 if e["valor"] else 0)]
    return args


def perfil(placa):
    """o perfil de chip do gêmeo (SO_ENTRADA, FLASH, BOOT...) ou None (Nano, ou gêmeo ausente)"""
    if placa.id not in ("esp32", "c3", "s3", "c6"):
        return None
    try:
        return importlib.import_module("motores.gemeo.chips." + placa.id)
    except Exception:
        return None


class Regras:
    """avisa uma vez cada pino errado; diz quais pinos não mexem de verdade (saída em pino só-entrada)"""

    def __init__(self, placa):
        self.placa, self.chip, self.ditos, self.mudos = placa, perfil(placa), set(), set()

    def _uma(self, chave, t, texto, codigo):
        if chave in self.ditos:
            return []
        self.ditos.add(chave)
        return [{"t_ms": t, "tipo": "aviso", "texto": texto, "codigo": codigo}]

    def ver(self, t, n, pino, modo=None):
        """os avisos de um pino que o firmware configurou (modo) ou usou (modo None)"""
        p, c, saida = self.placa, self.chip, []
        if pino not in p.pinos:
            saida += self._uma(("existe", pino), t, "a %s não tem o %s exposto: o programa usa um pino que não "
                               "existe na placa" % (p.nome, pino), "pino")
        if c is None:
            return saida
        fonte = " (%s)" % c.DS.split(",")[0] if getattr(c, "DS", None) else ""
        if modo in SAIDAS and n in c.SO_ENTRADA:
            self.mudos.add(pino)
            saida += self._uma(("entrada", pino), t, "%s é só entrada no %s%s: na placa o pinMode(OUTPUT) falha e o "
                               "pino não mexe (aqui também não)" % (pino, c.CURTO, fonte), "so_entrada")
        if n in c.FLASH:
            saida += self._uma(("flash", pino), t, "%s é da flash no %s%s: mexer nele trava a placa" % (
                pino, c.CURTO, fonte), "flash")
        if n in c.BOOT and modo in SAIDAS:
            saida += self._uma(("boot", pino), t, "%s é pino de boot no %s%s: %s" % (pino, c.CURTO, fonte,
                                                                                   c.BOOT[n][2]), "boot")
        if modo == "adc" and n not in (c.ADC1 | c.ADC2):
            saida += self._uma(("adc", pino), t, "%s não tem ADC no %s%s: na placa o analogRead dá 0 (aqui lê o "
                               "roteiro)" % (pino, c.CURTO, fonte), "adc")
        return saida


def converter(linhas, placa, sabor, porta, detalhe=False):
    """-> (eventos do contrato, final) com final = {"estado", "t_ms", "sinal", "parado", ...}"""
    regras, eventos, final = Regras(placa), [], {"estado": None, "t_ms": 0.0}
    tons = {}   # pino -> hora em que o tone() com duração acaba
    nivel, inicial = {}, set()   # o último nível de cada pino; os que só têm o 0 do pinMode(OUTPUT)
    for linha in linhas:
        try:
            e = json.loads(linha)
        except ValueError:
            continue   # a última linha pode ter ficado pela metade (o processo foi desligado)
        t, ev = round(e.get("t", 0) / 1000, 3), e.get("ev")
        final["t_ms"] = max(final["t_ms"], t)
        n = e.get("pino")
        pino = nome_pino(n, sabor) if isinstance(n, int) else None
        if pino in tons and tons[pino] <= t:   # o tone() com duração acabou antes deste evento
            eventos.append({"t_ms": tons.pop(pino), "tipo": "pwm", "pino": pino, "duty": 0.0, "freq_hz": None})
        if ev == "modo":
            modo = MODOS.get(e["modo"])
            if modo:
                eventos += regras.ver(t, n, pino, modo)
                if pino in regras.mudos and modo in SAIDAS:   # pino só-entrada: na placa o pinMode falha
                    continue
                eventos.append({"t_ms": t, "tipo": "modo", "pino": pino, "modo": modo})
                if modo == "saida" and pino not in nivel:   # como nos outros motores: a saída começa em 0
                    nivel[pino] = 0
                    inicial.add(pino)
                    eventos.append({"t_ms": t, "tipo": "pino", "pino": pino, "valor": 0, "origem": "firmware"})
        elif ev == "escreve" and pino not in regras.mudos:
            eventos += regras.ver(t, n, pino)
            if pino in inicial:
                inicial.discard(pino)
                if e["v"] == 0:   # o digitalWrite(LOW) logo depois: o 0 já está na linha do tempo
                    continue
            nivel[pino] = e["v"]
            eventos.append({"t_ms": t, "tipo": "pino", "pino": pino, "valor": e["v"], "origem": "firmware"})
        elif ev == "pwm" and pino not in regras.mudos:
            eventos.append({"t_ms": t, "tipo": "pwm", "pino": pino, "duty": min(1.0, max(0.0, e["duty"])),
                            "freq_hz": e.get("freq") or None})
        elif ev == "tom":
            ligado = e["freq"] > 0
            eventos.append({"t_ms": t, "tipo": "pwm", "pino": pino, "duty": 0.5 if ligado else 0.0,
                            "freq_hz": float(e["freq"]) if ligado else None})
            tons.pop(pino, None)
            if ligado and e.get("dur_ms"):
                tons[pino] = round(t + e["dur_ms"], 3)
        elif ev == "serial":
            eventos.append({"t_ms": t, "tipo": "serial", "dir": "tx", "texto": e["texto"], "porta": porta})
        elif ev in ("aviso", "marca"):
            eventos.append({"t_ms": t, "tipo": "aviso", "texto": e["texto"], "codigo": e.get("codigo") or ev})
        elif ev == "solto":
            eventos.append({"t_ms": t, "tipo": "aviso", "codigo": "flutuando", "texto": (
                "%s está em INPUT sem pull-up e sem nada no roteiro: na placa ele fica no ar e lê qualquer coisa; "
                "aqui lê 0 (use INPUT_PULLUP ou ponha o pino no roteiro)" % pino)})
        elif ev == "cheio":
            eventos.append({"t_ms": t, "tipo": "aviso", "codigo": "eventos", "texto": (
                "mais de %d eventos: parei de contar os pinos aqui (laço mexendo em pino sem delay?)" % e["max"])})
        elif ev == "reinicia":
            final.update(estado="travou", reinicia=True)
            eventos.append({"t_ms": t, "tipo": "aviso", "codigo": "reinicia", "texto": (
                "ESP.restart(): na placa ela reinicia e o programa começa de novo; aqui a rodada acaba")})
        elif ev == "sinal":
            final.update(sinal=e["n"], ram_kb=e.get("ram_kb"))
        elif ev == "parado":
            final.update(estado="travou", parado=e.get("pc_s"), ram_kb=e.get("ram_kb"))
        elif ev == "fim":
            final.update(fim=True, ram_kb=e.get("ram_kb"))
        elif detalhe and ev in ("isr", "interrupcao", "inicio"):
            eventos.append({"t_ms": t, "tipo": "aviso", "codigo": "nativo_detalhe",
                            "texto": "nativo: %s" % json.dumps({k: v for k, v in e.items() if k != "t"},
                                                               ensure_ascii=False)})
    for pino, t in tons.items():
        if t <= final["t_ms"]:
            eventos.append({"t_ms": t, "tipo": "pwm", "pino": pino, "duty": 0.0, "freq_hz": None})
    return agrupar(eventos, final["t_ms"]), final


def agrupar(eventos, fim_ms, janela=JANELA_MS, maximo=2):
    """onde o pino troca mais de DENSO vezes em BLOCO_MS, cada janela de 10 ms com mais de 'maximo' trocas vira
    um 'pwm' (a média da janela); o resto segue como 'pino'"""
    por_pino = defaultdict(list)
    for e in eventos:
        if e["tipo"] == "pino":
            por_pino[e["pino"]].append(e)
    rapidos = {p for p, evs in por_pino.items() if len(evs) > DENSO and _densos(evs)}
    if not rapidos:
        return eventos
    saida = [e for e in eventos if not (e["tipo"] == "pino" and e["pino"] in rapidos)]
    for p in rapidos:
        saida += _medias(por_pino[p], fim_ms, janela, maximo)
    saida.sort(key=lambda e: e["t_ms"])
    return saida


def _densos(evs):
    """os blocos de 100 ms em que o pino troca mais de DENSO vezes"""
    conta = defaultdict(int)
    for e in evs:
        conta[math.floor(e["t_ms"] / BLOCO_MS)] += 1
    return {b for b, n in conta.items() if n > DENSO}


def _medias(evs, fim_ms, janela, maximo):
    grupos = defaultdict(list)
    for e in evs:
        grupos[math.floor(e["t_ms"] / janela)].append(e)
    saida, nivel, ultimo_duty, antes, densos = [], 0, None, None, _densos(evs)
    pino = evs[0]["pino"]

    def acalma(k):   # a rajada acabou na janela k-1: o pino fica parado no último nível
        if ultimo_duty is not None and k * janela < fim_ms:
            saida.append({"t_ms": round(k * janela, 3), "tipo": "pino", "pino": pino, "valor": nivel,
                          "origem": "firmware"})
        return None

    for k in sorted(grupos):
        g, t0 = grupos[k], k * janela
        if antes is not None and k != antes + 1:
            ultimo_duty = acalma(antes + 1)
        antes = k
        if len(g) <= maximo or math.floor(t0 / BLOCO_MS) not in densos:   # janela calma: as trocas como estão
            ultimo_duty = acalma(k)
            saida += g
            nivel = g[-1]["valor"]
            continue
        alto, t, v = 0.0, t0, nivel
        for e in g:
            if v:
                alto += e["t_ms"] - t
            t, v = e["t_ms"], e["valor"]
        if v:
            alto += t0 + janela - t
        duty = round(alto / janela, 4)
        if ultimo_duty is None or abs(duty - ultimo_duty) > 0.01:
            saida.append({"t_ms": round(t0, 3), "tipo": "pwm", "pino": pino, "duty": min(1.0, max(0.0, duty)),
                          "freq_hz": round(len(g) / 2 / (janela / 1000), 1)})
            ultimo_duty = duty
        nivel = v
    if antes is not None:
        acalma(antes + 1)
    return saida
