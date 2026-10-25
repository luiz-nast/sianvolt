"""eletrica.py: liga os pinos do gêmeo no simulador do Sianvolt (ferramenta/circuito.py), sem mudar uma linha dele.
(veio do protótipo ~/.cache/sianvolt/lab/gemeo/motor/eletrica.py; agora o chip é um parâmetro)

A ideia: o circuito.py já sabe resolver "pilha" = fonte de tensão com uma resistência em série (Norton).
Um pino do ESP32 é exatamente isso:
  - saída em 1:     fonte de 3,3 V com a resistência do driver (30 Ω no DRIVE_2) até o GND
  - saída em 0:     fonte de 0 V com a mesma resistência (o pino "puxa" a net pro GND)
  - entrada c/ pull: fonte de 3,3 V (pull-up) ou 0 V (pull-down) com 45 kΩ (os 4 chips: datasheet, RPU/RPD)
  - entrada sem pull, ADC: nada (alta impedância); o gêmeo só lê a tensão da net
  - PWM: resolve com o pino em 1 e em 0 e faz a média pesada pelo duty (o LED pisca rápido demais pro olho:
         a luz média é duty × luz ligada; a média da TENSÃO não serve, porque o LED não é linear)
  - os pinos 3V3 e VIN do DevKit: fontes de 3,3 V e 5 V; os GND são o terra
Então o gêmeo monta, a cada mudança, umas "pilhas de mentira" no lugar do chip e chama circuito.resolver.
O chip vem do circuito: a peça esp32_devkit (pinagem do DevKit de 30 pinos, só com o chip esp32) ou qualquer
peça com pinos chamados GPIOn/IOn.
"""
import re
import sys
from pathlib import Path

FERRAMENTA = Path(__file__).resolve().parents[4] / "ferramenta"   # laboratorio/motores/gemeo/motor -> sianvolt
R_TESTE = 10e6   # pra descobrir se uma entrada está flutuando: puxa de leve pra cima e pra baixo


def _sianvolt():
    if str(FERRAMENTA) not in sys.path:
        sys.path.insert(0, str(FERRAMENTA))
    import blocos
    import circuito
    import gerar
    return gerar, circuito, blocos


def funcao_do_pino(nome):
    """'GPIO2', 'IO2', 'D2', 'G2' -> 2; '3V3', '3.3V' -> '3V3'; 'VIN', '5V' -> 'VIN'; 'GND' -> 'GND'"""
    if not nome:
        return None
    n = nome.strip().upper().replace(" ", "")
    m = re.fullmatch(r"(?:GPIO|IO|D|G|P)(\d+)", n)
    if m:
        return int(m.group(1))
    if n in ("3V3", "3.3V", "3,3V", "+3V3", "VCC"):
        return "3V3"
    if n in ("VIN", "5V", "+5V", "VBUS"):
        return "VIN"
    if n.startswith("GND"):
        return "GND"
    return None


def _fonte(ref, net_mais, net_menos, volts, ohms):
    return {"ref": ref, "eletrica": {"modelo": "pilha", "mais": "1", "menos": "2", "v": volts, "r_interna": ohms},
            "pinos": [{"n": "1", "net": net_mais}, {"n": "2", "net": net_menos}]}


class Eletrica:
    def __init__(self, arquivo_placa, chip):
        self.chip = chip
        gerar, self.circuito, self.blocos = _sianvolt()
        arq = Path(arquivo_placa)
        lido = gerar.ler(arq.read_text())
        self.modelo = gerar.montar(lido, gerar.biblioteca(arq.parent))
        mcus = [p for p in self.modelo["pecas"] if p["tipo"] == "esp32_devkit"
                or any(isinstance(funcao_do_pino(q["nome"]), int) for q in p["pinos"])]
        if not mcus:
            raise ValueError("não achei o chip no circuito (peça esp32_devkit ou com pinos GPIOn)")
        self.mcu = mcus[0]
        if self.mcu["tipo"] == "esp32_devkit" and chip.DEVKIT is None:
            raise ValueError("o circuito tem um ESP32 DevKit (%s), mas a placa escolhida é o %s"
                             % (self.mcu["ref"], chip.CURTO))
        self.gpio_net, self.alim, gnds = {}, {}, set()
        for q in self.mcu["pinos"]:
            f = chip.DEVKIT.get(q["n"]) if self.mcu["tipo"] == "esp32_devkit" else q["nome"]
            f = funcao_do_pino(f)
            if q["net"] is None or f is None:
                continue
            if isinstance(f, int):
                self.gpio_net[f] = q["net"]
            elif f == "GND":
                gnds.add(q["net"])
            else:
                self.alim[f] = q["net"]
        self.gnd = sorted(gnds)[0] if gnds else "GND"
        self.pecas = [p for p in self.modelo["pecas"] if p.get("eletrica")]
        self.leds = [p for p in self.pecas if p["eletrica"]["modelo"] == "led"]
        self.chaves = [p["ref"] for p in self.pecas if p["eletrica"]["modelo"] == "chave"]
        self.ignoradas = [p["ref"] for p in self.modelo["pecas"] if not p.get("eletrica") and p is not self.mcu]
        self._cache = {}
        self.resolucoes = 0

    # --- uma resolução: o ESP32 vira pilhas de mentira ---
    def _resolver_um(self, fixos, chaves):
        """fixos: {gpio: (volts, ohms)}; devolve o resultado do circuito.resolver"""
        chave = (tuple(sorted(fixos.items())), tuple(sorted(chaves.items())))
        if chave in self._cache:
            return self._cache[chave]
        chip = self.chip
        virt = [_fonte("~terra", self.gnd, self.gnd, 0.0, 1e9)]   # garante que o terra é o GND do chip
        if "3V3" in self.alim:
            virt.append(_fonte("~3V3", self.alim["3V3"], self.gnd, chip.VDD, chip.R_3V3))
        if "VIN" in self.alim:
            virt.append(_fonte("~VIN", self.alim["VIN"], self.gnd, chip.V_VIN, chip.R_VIN))
        for gpio, (volts, ohms) in fixos.items():
            if gpio in self.gpio_net:
                virt.append(_fonte("~GPIO%d" % gpio, self.gpio_net[gpio], self.gnd, volts, ohms))
        ajustes = {"chave": {ref: bool(v) for ref, v in chaves.items()}}
        r = self.circuito.resolver({"pecas": virt + self.modelo["pecas"]}, ajustes)
        self.resolucoes += 1
        if len(self._cache) > 5000:
            self._cache.clear()
        self._cache[chave] = r
        return r

    def _combinacoes(self, estado):
        """estado: {gpio: ("v", volts, ohms) | ("pwm", duty, ohms)} -> [(peso, fixos)]"""
        chip = self.chip
        fixos = {g: (e[1], e[2]) for g, e in estado.items() if e[0] == "v"}
        pwm = [(g, e[1], e[2]) for g, e in estado.items() if e[0] == "pwm" and g in self.gpio_net]
        combos = [(1.0, fixos)]
        for g, duty, ohms in pwm:
            novo = []
            for peso, f in combos:
                if duty > 0:
                    novo.append((peso * duty, {**f, g: (chip.VDD, ohms)}))
                if duty < 1:
                    novo.append((peso * (1 - duty), {**f, g: (0.0, ohms)}))
            combos = novo
        return combos

    def foto(self, estado, chaves):
        """o circuito agora: tensão de cada net (média), cada LED (corrente média, luz) e a corrente de cada pino"""
        combos = self._combinacoes(estado)
        nets, leds, pinos = {}, {}, {}
        for peso, fixos in combos:
            r = self._resolver_um(fixos, chaves)
            for net, v in r["nets"].items():
                nets[net] = nets.get(net, 0.0) + peso * v
            for p in self.leds:
                ref, e = p["ref"], p["eletrica"]
                i = r["pecas"][ref]["i"]
                d = leds.setdefault(ref, {"i_med": 0.0, "i_max": 0.0, "luz": 0.0, "queima": False, "tempo_aceso": 0.0})
                d["i_med"] += peso * i
                d["i_max"] = max(d["i_max"], i)
                d["queima"] = d["queima"] or r["pecas"][ref]["queima"]
                if r["pecas"][ref]["acende"]:
                    d["tempo_aceso"] += peso
                b = self.blocos.brilho_da_corrente(e, i) if i > 0 else 0.0
                d["luz"] += peso * (b if b is not None else i / e["i_teste"])
            for gpio in fixos:
                ref = "~GPIO%d" % gpio
                if ref in r["pecas"]:
                    i = r["pecas"][ref]["i"]   # + = o pino fornece corrente, − = o pino engole
                    if gpio not in pinos or abs(i) > abs(pinos[gpio]):
                        pinos[gpio] = i
        return {"nets": nets, "leds": leds, "pinos": pinos, "pwm": len(combos) > 1}

    def tensao(self, gpio, estado, chaves):
        """tensão média da net do pino; None se o pino não está ligado em nada"""
        if gpio not in self.gpio_net:
            return None
        return self.foto(estado, chaves)["nets"].get(self.gpio_net[gpio], 0.0)

    def tensao_entrada(self, gpio, estado, chaves):
        """(volts, flutuando): puxa a entrada de leve (10 MΩ) pra cima e pra baixo; se a tensão muda muito,
        ninguém está segurando a net e a leitura do chip de verdade seria imprevisível"""
        chip = self.chip
        if gpio not in self.gpio_net:
            return None, True
        net = self.gpio_net[gpio]
        base = {g: e for g, e in estado.items() if g != gpio}
        cima = self.foto({**base, gpio: ("v", chip.VDD, R_TESTE)}, chaves)["nets"].get(net, 0.0)
        baixo = self.foto({**base, gpio: ("v", 0.0, R_TESTE)}, chaves)["nets"].get(net, 0.0)
        if gpio in estado:   # o pull do próprio pino conta
            v = self.foto(estado, chaves)["nets"].get(net, 0.0)
            return v, False
        return (cima + baixo) / 2, abs(cima - baixo) > 1.0
