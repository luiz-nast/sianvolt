"""roteiro.py: o que acontece do lado de fora da placa, como o gêmeo entende.

Vem de dois lugares:
  1) as entradas do Pedido (o roteiro.json do contrato, já com pino físico e t_ms): nível ou tensão num pino,
     ou texto na serial (chega no sys.stdin na hora de placa);
  2) opcional, um arquivo gemeo.roteiro na pasta do programa, pro que o contrato não tem (formato do protótipo):
        i2c 0x48 0x00 = 0x19 0x80      aparelho I2C de mentira: endereço, registrador, bytes (no tempo 0)
        2 s i2c 0x48 0x00 = 0x1E 0x00  ... o aparelho muda de valor em 2 s
        wifi falha                     Wi-Fi de faz de conta: ok (padrão, conecta em 1,5 s) ou falha
        de 1,0 s a 1,5 s aperta SW1    chave do circuito (--circuito) apertada nesse intervalo
        2 s aperta SW1 / 2,5 s solta SW1
        0 s GPIO34 = 1,65 V / 1 s GPIO4 = 0 / 3 s GPIO4 solto
     Vírgula ou ponto no decimal; s, ms ou us. As conferências ficam no roteiro.json (o lab.py confere).
"""
import re

US = 1_000_000
_T = r"(\d+(?:[.,]\d+)?)\s*(s|ms|us|µs)"


def tempo(txt):
    m = re.fullmatch(_T, txt.strip())
    if not m:
        raise ValueError("'%s' devia ser um tempo como 1,5 s ou 200 ms" % txt)
    return round(float(m.group(1).replace(",", ".")) * {"s": US, "ms": 1000, "us": 1, "µs": 1}[m.group(2)])


def _gpio(nome):
    m = re.fullmatch(r"(?:GPIO|IO)?(\d+)", nome.strip().upper())
    if not m:
        raise ValueError("pino '%s' não é GPIOn" % nome)
    return int(m.group(1))


class Roteiro:
    def __init__(self, fim_us, entradas=(), extra=""):
        self.fim_us = int(fim_us)
        self.eventos = []   # (t_us, acao)
        self.i2c = {}       # endereço -> {registrador: [bytes]} no tempo 0
        self.wifi = "ok"
        for e in entradas:
            t = round(e["t_ms"] * 1000)
            if "serial" in e:   # texto que chega na serial da placa (o sys.stdin do MicroPython)
                self.eventos.append((t, {"tipo": "serial", "texto": e["serial"]}))
            elif "volts" in e:
                self.eventos.append((t, {"tipo": "externo", "gpio": _gpio(e["pino"]), "sinal": ("volts", e["volts"])}))
            else:
                self.eventos.append((t, {"tipo": "externo", "gpio": _gpio(e["pino"]), "sinal": ("nivel", e["valor"])}))
        for n, linha in enumerate(extra.splitlines(), 1):
            s = linha.split("#")[0].strip()
            if s:
                try:
                    self._linha(s)
                except ValueError as e:
                    raise ValueError("gemeo.roteiro, linha %d (%s): %s" % (n, s, e)) from None
        self.eventos.sort(key=lambda e: e[0])

    def _linha(self, s):
        p = s.split()
        if p[0] in ("fim", "placa", "confere") or " confere " in s:
            raise ValueError("isso agora mora no roteiro.json (tempo, confere) ou no --circuito (placa)")
        if p[0] == "wifi":
            if len(p) != 2 or p[1] not in ("ok", "falha"):
                raise ValueError("wifi espera ok ou falha")
            self.wifi = p[1]
            return
        if p[0] == "i2c":
            addr, reg, resto = self._i2c(p[1:])
            self.i2c.setdefault(addr, {})[reg] = resto
            return
        m = re.match(r"de\s+%s\s+a\s+%s\s+aperta\s+(\S+)$" % (_T, _T), s)
        if m:
            t1, t2 = tempo(m.group(1) + " " + m.group(2)), tempo(m.group(3) + " " + m.group(4))
            self.eventos.append((t1, self._acao(["aperta", m.group(5)])))
            self.eventos.append((t2, self._acao(["solta", m.group(5)])))
            return
        m = re.match(r"%s\s+(.*)$" % _T, s)
        if not m:
            raise ValueError("não entendi a linha")
        self.eventos.append((tempo(m.group(1) + " " + m.group(2)), self._acao(m.group(3).split())))

    @staticmethod
    def _i2c(p):
        if len(p) < 4 or p[2] != "=":
            raise ValueError("i2c espera: endereço registrador = bytes")
        return int(p[0], 0), int(p[1], 0), [int(b, 0) for b in p[3:]]

    def _acao(self, p):
        if p[0] in ("aperta", "solta") and len(p) == 2:
            if p[1].upper().startswith("GPIO"):   # um botão imaginário entre o pino e o GND
                return {"tipo": "externo", "gpio": _gpio(p[1]), "sinal": ("nivel", 0) if p[0] == "aperta" else None}
            return {"tipo": "chave", "ref": p[1], "apertada": p[0] == "aperta"}
        if p[0].upper().startswith("GPIO"):
            g = _gpio(p[0])
            if len(p) == 2 and p[1] in ("solto", "livre"):
                return {"tipo": "externo", "gpio": g, "sinal": None}
            if len(p) >= 3 and p[1] == "=":
                txt = "".join(p[2:]).upper()
                if txt.endswith("V"):
                    return {"tipo": "externo", "gpio": g, "sinal": ("volts", float(txt[:-1].replace(",", ".")))}
                return {"tipo": "externo", "gpio": g, "sinal": ("nivel", int(txt))}
        if p[0] == "i2c":
            addr, reg, resto = self._i2c(p[1:])
            return {"tipo": "i2c", "addr": addr, "reg": reg, "bytes": resto}
        raise ValueError("não entendi '%s'" % " ".join(p))
