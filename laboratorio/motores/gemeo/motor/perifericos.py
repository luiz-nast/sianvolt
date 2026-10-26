"""perifericos.py: o que o firmware enxerga do chip (Pin, PWM, ADC, I2C, Timer, WDT, Wi-Fi, serial) e a parte
elétrica dos pinos. É a metade 'hardware' do Nucleo (nucleo.py herda daqui); veio do protótipo do gêmeo.

Cada c_<nome> atende uma chamada rpc("<nome>", ...) dos stubs em firmware/. ValueError/OSError viram a mesma
exceção no firmware, com a mesma mensagem do MicroPython de verdade quando dá.
"""
import time as _relogio_pc

US = 1_000_000
# quanto tempo de placa cada coisa gasta (estimativa; o código Python em si não gasta tempo no gêmeo)
CUSTO_US = {"pino_init": 5, "pino_escreve": 10, "pino_le": 10, "pwm_init": 20, "pwm_duty": 5, "pwm_freq": 10,
            "adc_init": 20, "adc_le": 40, "i2c_init": 20}
US_POR_CARACTERE = {"uart0": 10 * US / 115200, "usb": 1.0}   # 115200 baud = 10 bits por caractere; USB é rápido
ATTEN = ["0 dB", "2,5 dB", "6 dB", "11 dB"]


class Fim(Exception):
    """a simulação acabou: motivo (texto) e estado do contrato (acabou, tempo, erro, travou)"""

    def __init__(self, motivo, estado):
        super().__init__(motivo)
        self.estado = estado


def fmt_t(us):
    return ("%.3f s" % (us / US)).replace(".", ",")


def ma(i):
    return ("%.1f" % (i * 1000)).replace(".", ",")


def v_txt(v):
    return ("%.2f V" % v).replace(".", ",")


class Perifericos:
    # ---------- elétrica ----------
    def _estado_eletrico(self):
        c, est = self.chip, {}
        for g, p in self.pinos.items():
            r = c.DRIVE[p.get("drive", c.DRIVE_PADRAO)][0]
            modo = p["modo"]
            if modo == "saida":
                est[g] = ("v", c.VDD if p["valor"] else 0.0, r)
            elif modo == "od" and not p["valor"]:
                est[g] = ("v", 0.0, r)
            elif modo == "pwm":
                est[g] = ("pwm", p["duty"] / 65535, r)
            elif modo in ("entrada", "od") and p.get("pull") and g not in c.SO_ENTRADA:
                est[g] = ("v", c.VDD if p["pull"] == c.PULL_UP else 0.0, c.R_PULL)
        for g, s in self.externo.items():   # sinal de fora: uma fonte forte no pino
            est[g] = ("v", s[1] if s[0] == "volts" else c.VDD * s[1], 1.0)
        return est

    def _observar(self):
        """depois de qualquer mudança: o que acontece no circuito (LEDs, corrente dos pinos) e nas entradas com irq"""
        self.versao += 1
        self._cache_nivel = {}
        if self.el:
            f = self.el.foto(self._estado_eletrico(), self.chaves, self.luz)
            for ref, d in f["leds"].items():
                aceso = d["luz"] >= 0.01 or d["tempo_aceso"] > 0   # abaixo de 1% e nunca com 1 mA: apagado
                if not aceso:
                    txt = "%s apagado" % ref
                else:
                    meia = f["pwm"] and d["tempo_aceso"] < 0.999
                    txt = "%s %s, %s mA%s, luz %d%% do anúncio" % (
                        ref, "meia luz" if meia else "aceso", ma(d["i_med"]),
                        " na média (%s mA quando liga)" % ma(d["i_max"]) if meia else "", round(d["luz"] * 100))
                # o brilho como número (A e fração do anúncio): cada mudança do LED vira um evento 'led'. O
                # arredondamento (1 µA, 0,01% da luz) só tira as mudanças que nenhum número mostraria. 'aceso' é a
                # regra do texto: o LED de 35 µA (aceso só pelo pull-up) tem números, mas é 'apagado' pra todo mundo
                led = {"ref": ref, "i_med": round(max(d["i_med"], 0.0), 6), "i_max": round(d["i_max"], 6),
                       "luz": round(max(d["luz"], 0.0), 4), "aceso": aceso, "queima": bool(d["queima"]), "texto": txt}
                if self.leds.get(ref) != led:
                    self.leds[ref] = led
                    self.ev("led", **led)
                if d["queima"]:
                    self.aviso("%s QUEIMA: passa %s mA, acima do máximo do datasheet" % (ref, ma(d["i_max"])), "queima")
            for g, i in f["pinos"].items():
                if g in self.externo:
                    continue
                drive = self.pinos.get(g, {}).get("drive", self.chip.DRIVE_PADRAO)
                if abs(i) > self.chip.DRIVE[drive][1]:
                    self.aviso("GPIO%d %s %s mA, acima dos %s mA seguros desse pino (DRIVE_%d)" % (
                        g, "fornece" if i > 0 else "engole", ma(abs(i)), ma(self.chip.DRIVE[drive][1]), drive),
                        "corrente")
        for g, p in self.pinos.items():
            if p.get("irq"):
                n = self._nivel(g, silencioso=True)
                antes = self.niveis.get(g, n)
                self.niveis[g] = n
                gatilho, cb = p["irq"]
                if (n > antes and gatilho & self.chip.IRQ_RISING) or (n < antes and gatilho & self.chip.IRQ_FALLING):
                    self.pendentes.append([cb, ["pino", g]])

    def _nivel(self, g, silencioso=False):
        """o que o chip leria no pino agora: 0 ou 1 (guardado até o próximo estado mudar: laço que só lê é rápido)"""
        chave = (g, self.versao)
        if chave not in self._cache_nivel:
            av = []
            self._cache_nivel[chave] = (self._nivel_calc(g, av), av)
        nivel, av = self._cache_nivel[chave]
        if not silencioso:
            for a in av:
                self.aviso(a, "entrada")
        return nivel

    def _nivel_calc(self, g, av):
        c, p = self.chip, self.pinos.get(g, {})
        if g in self.externo:
            s = self.externo[g]
            return s[1] if s[0] == "nivel" else self._limiar(g, s[1], av)
        if p.get("modo") == "saida":
            return p["valor"]
        if self.el and g in self.el.gpio_net:
            v, flutua = self.el.tensao_entrada(g, self._estado_eletrico(), self.chaves, self.luz)
            if flutua:
                av.append("GPIO%d está flutuando (nada segura a tensão: falta pull-up/pull-down ou o botão está solto"
                          " sem resistor): no %s de verdade a leitura sai aleatória; o gêmeo lê 0" % (g, c.CURTO))
                return 0
            return self._limiar(g, v, av)
        if p.get("pull") and g not in c.SO_ENTRADA:
            return 1 if p["pull"] == c.PULL_UP else 0
        av.append("GPIO%d lido sem nada ligado e sem pull: no %s de verdade sai aleatório; o gêmeo lê 0" % (g, c.CURTO))
        return 0

    def _limiar(self, g, v, av):
        c = self.chip
        if v >= c.VIH:
            return 1
        if v <= c.VIL:
            return 0
        av.append("GPIO%d recebe %s, entre %s e %s: nem 0 nem 1 garantido (datasheet)" % (
            g, v_txt(v), v_txt(c.VIL), v_txt(c.VIH)))
        return 1 if v > c.VDD / 2 else 0

    def _volts(self, g):
        if g in self.externo:
            s = self.externo[g]
            return s[1] if s[0] == "volts" else self.chip.VDD * s[1]
        if self.el and g in self.el.gpio_net:
            return self.el.tensao(g, self._estado_eletrico(), self.chaves, self.luz)
        self.aviso("ADC no GPIO%d sem circuito e sem tensão no roteiro: lê 0 V" % g, "adc")
        return 0.0

    # ---------- Pin ----------
    def c_pino_init(self, g, modo, pull, valor, drive):
        c = self.chip
        self.custo(CUSTO_US["pino_init"])
        self._conferir(g, saida=modo in (c.PIN_OUT, c.PIN_OPEN_DRAIN), pull=pull)
        p = self._pino(g)
        if modo is not None:
            p["modo"] = {c.PIN_IN: "entrada", c.PIN_OUT: "saida", c.PIN_OPEN_DRAIN: "od"}.get(modo)
            if p["modo"] is None:
                raise ValueError("modo de pino desconhecido: %r" % modo)
        if pull is not None:
            p["pull"] = pull or None
        if drive is not None:
            if drive not in c.DRIVE:
                raise ValueError("drive tem que ser 0 a 3")
            p["drive"] = drive
        if valor is not None:
            p["valor"] = 1 if valor else 0
        if p["modo"] in ("saida", "od"):
            self._modo(g, "saida")
            self._nivel_saida(g)
        elif p["modo"] == "entrada":
            self._modo(g, {c.PULL_UP: "pullup", c.PULL_DOWN: "pulldown"}.get(p["pull"], "entrada"))
        self._observar()

    def c_pino_escreve(self, g, v):
        self.custo(CUSTO_US["pino_escreve"])
        p = self._pino(g)
        v = 1 if v else 0
        if p["modo"] not in ("saida", "od"):   # dá pra escrever num pino de entrada: vale quando virar saída
            p["valor"] = v
            return
        if p["valor"] != v:
            p["valor"] = v
            self._nivel_saida(g)
            self._observar()

    def c_pino_le(self, g):
        self.custo(CUSTO_US["pino_le"])
        return self._nivel(g)

    def c_pino_irq(self, g, gatilho, cb):
        p = self.pinos.setdefault(g, {"modo": "entrada", "valor": 0, "pull": None, "drive": self.chip.DRIVE_PADRAO})
        p["irq"] = (gatilho, cb) if cb is not None else None
        self.niveis[g] = self._nivel(g, silencioso=True)

    # ---------- PWM ----------
    def c_pwm_init(self, g, freq, duty_u16):
        self.custo(CUSTO_US["pwm_init"])
        self._conferir(g, saida=True)
        p = self._pino(g)
        p.update(modo="pwm", freq=freq or p.get("freq") or self.chip.PWM_FREQ,
                 duty=duty_u16 if duty_u16 is not None else p.get("duty", self.chip.PWM_DUTY_U16))
        self.emitido.pop(("nivel", g), None)   # depois do PWM, o próximo nível sempre vira evento
        self.janelas.pop(g, None)
        self._modo(g, "pwm")
        self._pwm_mudou(g)

    def c_pwm_freq(self, g, freq):
        self.custo(CUSTO_US["pwm_freq"])
        if not 1 <= freq <= 40_000_000:
            raise ValueError("freq tem que ser de 1 Hz a 40 MHz")
        self.pinos[g]["freq"] = freq
        self._pwm_mudou(g)

    def c_pwm_duty(self, g, duty_u16):
        self.custo(CUSTO_US["pwm_duty"])
        self.pinos[g]["duty"] = max(0, min(65535, int(duty_u16)))
        self._pwm_mudou(g)

    def c_pwm_deinit(self, g):
        p = self.pinos.get(g)
        if p:
            p.update(modo="saida", valor=0)
            self._modo(g, "saida")
            self._nivel_saida(g)
            self._observar()

    def _pwm_mudou(self, g):
        p = self.pinos[g]
        f, d = p["freq"], round(p["duty"] / 65535, 4)
        if self.emitido.get(("pwm", g)) != (d, f):
            self.emitido[("pwm", g)] = (d, f)
            self.ev("pwm", pino="GPIO%d" % g, duty=d, freq_hz=float(f))
        if f < 100 and d not in (0, 1):
            self.aviso("PWM de %d Hz no GPIO%d: o olho vê piscar (abaixo de ~100 Hz); o gêmeo só mostra a média"
                       % (f, g), "pwm")
        self._observar()

    # ---------- ADC ----------
    def c_adc_init(self, g, atten):
        c = self.chip
        self.custo(CUSTO_US["adc_init"])
        if g not in c.ADC1 | c.ADC2:
            raise ValueError("invalid pin")
        self._conferir(g)
        p = self._pino(g)
        p.update(modo="adc", atten=c.ATTEN_PADRAO if atten is None else atten)
        self.versao += 1
        self._cache_nivel = {}
        self._modo(g, "adc")
        if g in c.ADC2 and c.CURTO == "C3":
            self.aviso("GPIO%d é o ADC2 do C3, que não funciona em algumas revisões do chip (datasheet 4.2.2.1)"
                       % g, "adc")

    def c_adc_atten(self, g, atten):
        if atten not in self.chip.ATTEN_FAIXA:
            raise ValueError("invalid attenuation")
        self.pinos[g]["atten"] = atten

    def c_adc_le(self, g, como):
        c = self.chip
        self.custo(CUSTO_US["adc_le"])
        if g in c.ADC2 and c.ADC2_WIFI and self.wlan["ativa"]:
            # MPQ/datasheet: o Wi-Fi usa o ADC2; no MicroPython de verdade a leitura dá erro
            self.aviso("ADC2 (GPIO%d) lido com o Wi-Fi ligado: o Wi-Fi usa o ADC2 e a leitura dá erro; use um pino "
                       "do ADC1" % g, "adc2_wifi")
            raise OSError("ESP_ERR_TIMEOUT")
        a = self.pinos[g].get("atten", c.ATTEN_PADRAO)
        v = self._volts(g)
        lo, hi = c.ATTEN_FAIXA[a]
        if not lo <= v <= hi:
            self.aviso("ADC no GPIO%d lê %s, fora da faixa boa da atenuação %s (%s a %s): no %s de verdade o "
                       "valor sai torto" % (g, v_txt(v), ATTEN[a], v_txt(lo), v_txt(hi), c.CURTO), "adc")
        if v > c.VDD + 0.3:
            self.aviso("GPIO%d recebe %s: acima do máximo de %s, queima o %s" % (g, v_txt(v), v_txt(c.VDD + 0.3),
                                                                              c.CURTO), "queima")
        cru = max(0, min(4095, round(v / c.ATTEN_FUNDO[a] * 4095)))
        if como == "uv":
            return round(max(lo, min(v, c.ATTEN_FUNDO[a], c.VDD)) * 1000) * 1000
        if como == "u16":
            return (cru << 4) | (cru >> 8)   # como o MicroPython estica 12 bits pra 16 (machine_adc.c)
        return cru

    # ---------- I2C ----------
    def c_i2c_init(self, bus, scl, sda, freq):
        self.custo(CUSTO_US["i2c_init"])
        if not str(bus).startswith("soft"):
            if bus not in self.chip.I2C_PADRAO:
                raise ValueError("I2C(%s) doesn't exist" % bus)
            pscl, psda = self.chip.I2C_PADRAO[bus]
            scl, sda = pscl if scl is None else scl, psda if sda is None else sda
        for g in (scl, sda):
            self._conferir(g, saida=True)
        self.i2c_bus[bus] = {"scl": scl, "sda": sda, "freq": freq}

    def _i2c_custo(self, bus, nbytes):
        f = self.i2c_bus.get(bus, {}).get("freq", 400_000)
        self.custo(max(1, round((nbytes + 1) * 9 * US / f)))

    def _i2c_aparelho(self, addr):
        if addr not in self.i2c_mem:
            raise OSError(19)   # ENODEV: ninguém respondeu nesse endereço (igual ao chip)
        return self.i2c_mem[addr]

    def c_i2c_scan(self, bus):
        self._i2c_custo(bus, 112)
        return sorted(self.i2c_mem)

    def c_i2c_escreve(self, bus, addr, dados):
        self._i2c_custo(bus, len(dados))
        m = self._i2c_aparelho(addr)
        if dados:
            reg = dados[0]
            self.i2c_ptr[addr] = reg
            if len(dados) > 1:
                m[reg:reg + len(dados) - 1] = bytes(dados[1:])
        return len(dados)

    def c_i2c_le(self, bus, addr, n):
        self._i2c_custo(bus, n)
        m = self._i2c_aparelho(addr)
        reg = self.i2c_ptr.get(addr, 0)
        return list(m[reg:reg + n])

    def c_i2c_le_mem(self, bus, addr, reg, n):
        self._i2c_custo(bus, n + 1)
        return list(self._i2c_aparelho(addr)[reg:reg + n])

    def c_i2c_escreve_mem(self, bus, addr, reg, dados):
        self._i2c_custo(bus, len(dados) + 1)
        self._i2c_aparelho(addr)[reg:reg + len(dados)] = bytes(dados)

    # ---------- Timer e WDT ----------
    def c_timer_existe(self, tid):
        n = getattr(self.chip, "TIMERS", 4)
        if not 0 <= tid < n:   # a mesma mensagem do MicroPython 1.29 (ports/esp32/machine_timer.c)
            raise ValueError("Timer(%d) doesn't exist, there are only %d hardware timers" % (tid, n))

    def c_timer_init(self, tid, periodo_us, periodico, cb):
        tm = self.timers.setdefault(tid, {"geracao": 0})
        tm.update(periodo=max(1, periodo_us), periodico=periodico, cb=cb, ativo=True, geracao=tm["geracao"] + 1)
        self._agendar(self.t + tm["periodo"], "timer", (tid, tm["geracao"]))

    def c_timer_deinit(self, tid):
        if tid in self.timers:
            self.timers[tid]["ativo"] = False

    def c_wdt_init(self, ms):
        self.wdt = {"timeout": ms * 1000, "ultimo": self.t}
        self._agendar(self.t + ms * 1000, "wdt", None)

    def c_wdt_feed(self):
        self.wdt["ultimo"] = self.t

    def _ev_wdt(self, _):
        w = self.wdt
        if self.t - w["ultimo"] >= w["timeout"]:
            self.aviso("o WDT não foi alimentado em %d ms: o %s reinicia (o gêmeo para aqui)"
                       % (w["timeout"] // 1000, self.chip.CURTO), "wdt")
            raise Fim("o WDT reiniciou o %s em %s" % (self.chip.CURTO, fmt_t(self.t)), "travou")
        self._agendar(w["ultimo"] + w["timeout"], "wdt", None)

    # ---------- Wi-Fi de faz de conta ----------
    def c_wlan_ativa(self, v):
        if v is not None and bool(v) != self.wlan["ativa"]:
            self.wlan["ativa"] = bool(v)
            if v:
                self.aviso("Wi-Fi de faz de conta ligado: nada sai pela rede; conecta (ou falha) em 1,5 s", "rede")
        return self.wlan["ativa"]

    def c_wlan_conecta(self, ssid):
        if not self.wlan["ativa"]:
            raise OSError("Wifi Not Started")
        self.wlan.update(ssid=ssid, conectando_em=self.t, conectado=False)
        self._agendar(self.t + int(1.5 * US), "wifi", None)

    def c_wlan_conectado(self):
        return bool(self.wlan.get("conectado"))

    # ---------- serial e o resto ----------
    def c_print(self, texto):
        self.escreve_serial(texto)
        self.custo(round(len(texto) * US_POR_CARACTERE.get(self.porta, 1.0)))

    def c_uart_escreve(self, uid, dados):
        texto = bytes(dados).decode("utf-8", "replace")
        self.escreve_serial(texto, "uart%s" % uid)
        self.custo(round(len(dados) * US_POR_CARACTERE["uart0"]))

    @staticmethod
    def _so_do_programa(texto):
        """o traceback sem os quadros dos stubs do gêmeo (no CPython, sem a linha de código que vem embaixo)"""
        saida, pula = [], False
        for ln in texto.splitlines():
            if "/gemeo/firmware/" in ln or "/gemeo/motor/" in ln:
                pula = True
                continue
            if pula and ln.startswith("    "):
                continue
            pula = False
            saida.append(ln)
        return "\n".join(saida).strip()

    def c_erro(self, texto):
        texto = self._so_do_programa(texto)
        self._fechar_serial()
        self.ev("erro", texto=texto or "erro")
        raise Fim("o programa deu erro em %s" % fmt_t(self.t), "erro")

    def c_erro_cb(self, texto):
        """erro dentro de um callback (Pin.irq, Timer): na placa a mensagem sai na serial e o programa segue"""
        self._fechar_serial()
        self.ev("erro", texto="erro dentro de um callback (Pin.irq ou Timer); na placa o traceback sai na serial e "
                              "o programa segue rodando:\n" + (self._so_do_programa(texto) or "erro"))

    def c_custo(self, us):
        self.custo(us)

    def c_localtime(self, segundos):
        t = _relogio_pc.gmtime(segundos + 946684800)   # o ESP32 conta a partir de 2000-01-01
        return [t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec, t.tm_wday, t.tm_yday]

    def c_reset(self, como):
        self.aviso("machine.%s(): na placa o %s reinicia e o programa recomeça; o gêmeo para aqui"
                   % (como, self.chip.CURTO), "reset")
        raise Fim("o programa chamou machine.%s() em %s" % (como, fmt_t(self.t)), "travou")

    def c_dormir_fundo(self, ms, como):
        if como == "deepsleep":
            self.aviso("deepsleep(%s ms): na placa o %s dorme e reinicia ao acordar; o gêmeo para aqui"
                       % (ms, self.chip.CURTO), "sono")
            raise Fim("deepsleep em %s" % fmt_t(self.t), "acabou")
        alvo = self.t + ms * 1000
        self._processar_ate(alvo)
        self.t = min(alvo, self.fim)
        if self.t >= self.fim:
            self._acabou_o_tempo()
