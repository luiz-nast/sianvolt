"""o simulador existe em duas línguas (circuito.py e simular() no app); elas têm que dar o mesmo número"""
import json
import random
import re
import shutil
import subprocess
import unittest

from apoio import LED, PILHA, RAIZ, RESISTOR, CHAVE, peca
import circuito
from test_circuito import LDR, MCU, mcu, sortear_com_esp32

NODE = shutil.which("node")


def js_do_app():
    """o pedaço do index.html com o simulador (de 'const GMIN' até antes de 'const mA')"""
    html = (RAIZ / "bancada" / "index.html").read_text()
    return html[html.index("const GMIN"):html.index("const mA =")]


def sortear(rnd):
    nets = ["GND"] + [f"N{i}" for i in range(1, rnd.randint(2, 6))]
    pilha = {**PILHA, "r_interna": rnd.choice([0, 5, 12])}
    pecas = [peca("BT1", pilha, {"1": nets[1], "2": "GND"})]
    for i in range(rnd.randint(2, 9)):
        a, b = rnd.sample(nets, 2)
        sorteio = rnd.random()
        if sorteio < 0.25:
            led = LED if rnd.random() < 0.5 else {**LED, "mais": "2", "menos": "1"}
            pecas.append(peca(f"D{i}", led, {"1": a, "2": b}))
        elif sorteio < 0.35:
            pecas.append(peca(f"SW{i}", CHAVE, {"1": a, "2": a, "3": b, "4": b}))
        else:
            pecas.append(peca(f"R{i}", RESISTOR, {"1": a, "2": b}, valor=rnd.choice([10, 47, 100, 220, 1000, 4700])))
    aj = {"pilha": {"BT1": rnd.uniform(1.5, 3.3)}, "resistor": {},
          "chave": {p["ref"]: rnd.random() < 0.6 for p in pecas if p["ref"].startswith("SW")}}
    return {"pecas": pecas}, aj


def no_node(programa, entrada):
    """roda o trecho do simulador + programa no node; entrada vai em JSON pelo stdin, a saída volta em JSON"""
    r = subprocess.run([NODE, "-e", js_do_app() + "\nconst entrada = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
                        + programa], input=json.dumps(entrada), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "precisa do node (brew install node)")
class MesmaConta(unittest.TestCase):
    def mesmo_resultado(self, k, s_py, s_js):
        self.assertEqual(set(s_py["pecas"]), set(s_js["pecas"]), f"caso {k}")
        for ref, p_py in s_py["pecas"].items():
            p_js = s_js["pecas"][ref]
            for campo in ("i", "p", "v", "ohms"):
                if campo in p_py:
                    self.assertAlmostEqual(p_py[campo], p_js[campo], delta=1e-9 + 1e-7 * abs(p_py[campo]),
                                           msg=f"caso {k}, {ref}.{campo}")
            for campo in ("acende", "queima", "forte", "apertada", "fio"):
                if campo in p_py:
                    self.assertEqual(p_py[campo], p_js[campo], f"caso {k}, {ref}.{campo}")
        for net, v in s_py["nets"].items():
            self.assertAlmostEqual(v, s_js["nets"][net], delta=1e-9 + 1e-7 * abs(v), msg=f"caso {k}, net {net}")

    def test_300_circuitos_sorteados(self):
        rnd = random.Random(7)
        casos = [sortear(rnd) for _ in range(300)]
        js = no_node("console.log(JSON.stringify(entrada.map(([m, aj]) => simular(m, aj))));", casos)
        for k, ((m, aj), s_js) in enumerate(zip(casos, js)):
            self.mesmo_resultado(k, circuito.resolver(m, aj), s_js)

    def test_300_circuitos_com_esp32(self):
        """o ESP32 (comPinos, com True e False no estado), o LDR com e sem ajuste, o piezo aberto e como fio, e o
        capacitor. Cada caso roda também com o ajuste do jeito que o app guarda ({pilha, resistor, chave}, sem 'ldr'
        nem 'piezo'): o simular completa o que falta, como o resolver"""
        rnd = random.Random(8)
        casos = [sortear_com_esp32(rnd) for _ in range(300)]
        modelos = [p["eletrica"]["modelo"] for m, *_ in casos for p in m["pecas"]]
        for modelo in ("mcu", "led", "chave", "ldr", "piezo", "capacitor", "resistor"):
            self.assertGreater(modelos.count(modelo), 20, modelo)
        self.assertTrue({True, False} <= {fio for *_, aj in casos for fio in aj["piezo"].values()})
        self.assertGreater(sum(len(aj["ldr"]) for *_, aj in casos), 20)
        self.assertTrue({True, False} <= {v for _, estado, *_ in casos for v in estado.values() if isinstance(v, bool)})
        js = no_node("console.log(JSON.stringify(entrada.map(([m, estado, vdd, aj]) => [simular(comPinos(m, estado, vdd), aj), "
                     "simular(comPinos(m, estado, vdd), { pilha: {}, resistor: {}, chave: aj.chave })])));", casos)
        for k, ((m, estado, vdd, aj), (s_js, s_app)) in enumerate(zip(casos, js)):
            completo = circuito.com_pinos(m, estado, vdd)
            self.mesmo_resultado(k, circuito.resolver(completo, aj), s_js)
            self.mesmo_resultado(k, circuito.resolver(completo, {"chave": aj["chave"]}), s_app)

    def test_ldr_e_divisor_iguais(self):
        rnd = random.Random(9)
        casos = []
        for _ in range(300):
            e = {**LDR, "r10_min": rnd.choice([2000, 8000, 10000]), "gama": rnd.uniform(0.5, 0.9)}
            e["r10_max"] = e["r10_min"] * rnd.uniform(1, 3)
            if rnd.random() < 0.2:
                del e["gama_tol"]
            casos.append([e, rnd.choice([4700, 10000, 22000]), rnd.uniform(3.0, 3.4),
                          rnd.choice([None, 0, 0.001, 0.5, 1, 10, 23, 100, rnd.uniform(0.1, 1000)]), rnd.choice(["min", "meio", "max"])])
        js = no_node("console.log(JSON.stringify(entrada.map(([e, r, vdd, lux, canto]) => "
                     "[ohmsDoLdr(e, lux, canto), divisorDoLdr(e, r, vdd, lux, canto)])));", casos)
        for (e, r, vdd, lux, canto), (ohms_js, volts_js) in zip(casos, js):
            self.assertAlmostEqual(circuito.ohms_do_ldr(e, lux, canto), ohms_js, delta=1e-12 * ohms_js, msg=(lux, canto))
            self.assertAlmostEqual(circuito.divisor_do_ldr(e, r, vdd, lux, canto), volts_js, delta=1e-12, msg=(lux, canto))

    def test_mesmos_erros(self):
        """o que um lado recusa, o outro também, com a mesma frase: estado e canto que não existem, pino que não é GPIO,
        número pendente na eletrica (o r_3v3 também), lux que não é número e LDR de 0 Ω (o primeiro caso é o bom, que
        passa); sem mcu, os dois devolvem o modelo"""
        G = {"GND": "GND", "3V3": "N3", "VIN": "N5", "GPIO32": "N1"}
        led = [peca("R1", RESISTOR, {"1": "N1", "2": "N2"}, valor=220), peca("D1", LED, {"1": "N2", "2": "GND"})]
        ldr = peca("LDR1", LDR, {"1": "N3", "2": "GND"})

        def sem(campo):
            return {k: v for k, v in MCU.items() if k != campo}
        pinos = [   # (modelo, estado, vdd, ajustes)
            ({"pecas": [mcu(G), ldr] + led}, {"GPIO32": 1}, None, {"ldr": {"LDR1": 5000}}),
            ({"pecas": [mcu(G)] + led}, {"GPIO32": "alto"}, None, {}),
            ({"pecas": [mcu(G)] + led}, {"VIN": 1}, None, {}),
            ({"pecas": [mcu(G)] + led}, {"3V3": 0}, None, {}),
            ({"pecas": [mcu(G)] + led}, {"GND": 1}, None, {}),
            ({"pecas": [mcu(G, sem("r_pino"))] + led}, {"GPIO32": 1}, None, {}),
            ({"pecas": [mcu(G, sem("r_pull"))] + led}, {"GPIO32": "pullup"}, None, {}),
            ({"pecas": [mcu(G, sem("vdd"))] + led}, {"GPIO32": 1}, None, {}),
            ({"pecas": [mcu(G, {**MCU, "r_pino": "pendente"})] + led}, {"GPIO32": 0}, None, {}),
            ({"pecas": [mcu(G)] + led}, {"GPIO32": 1}, 0, {}),
            ({"pecas": [mcu(G), ldr]}, {}, None, {"ldr": {"LDR1": 0}}),
            ({"pecas": [mcu(G), peca("LDR1", {**LDR, "r10_min": None}, {"1": "N3", "2": "GND"})]}, {}, None, {}),
            ({"pecas": [mcu(G)] + led}, {"GPIO32": "1"}, None, {}),
            ({"pecas": [mcu(G)] + led}, {"GPIO32": 1}, "3.3", {}),
            ({"pecas": [mcu(G), ldr]}, {}, None, {"ldr": {"LDR1": "1k"}}),
        ] + [({"pecas": [mcu(G, e)] + led}, {"GPIO32": 1}, None, {})   # o r_3v3 pendente, com o 3V3 ligado
             for e in (sem("r_3v3"), {**MCU, "r_3v3": "pendente"}, {**MCU, "r_3v3": 0}, {**MCU, "r_3v3": -1})]
        ldrs = [(LDR, 10, "tipico"), ({**LDR, "gama": None}, 10, "meio"), ({**LDR, "r_escuro": None}, 0, "meio"),
                (LDR, 0, "tipico"), (LDR, None, "tipico"), (LDR, "10", "meio"), (LDR, -1, "meio"), (LDR, True, "min")]
        js = no_node("""const tenta = f => { try { f(); return 'passou'; } catch (err) { return err.message; } };
console.log(JSON.stringify([entrada.pinos.map(([m, estado, vdd, aj]) => tenta(() => simular(comPinos(m, estado, vdd), aj))),
  entrada.ldrs.map(([e, lux, canto]) => tenta(() => ohmsDoLdr(e, lux, canto))), comPinos({ pecas: [] }, { GPIO32: 1 }).pecas.length]));""",
                     {"pinos": pinos, "ldrs": ldrs})

        def frase(f):   # a frase do erro, como o JS (o repr do Python escreve True; o JS, true)
            try:
                f()
            except ValueError as err:
                return str(err).replace("True", "true")
            return "passou"
        py = [[frase(lambda: circuito.resolver(circuito.com_pinos(m, estado, vdd), aj)) for m, estado, vdd, aj in pinos],
              [frase(lambda: circuito.ohms_do_ldr(e, lux, canto)) for e, lux, canto in ldrs], 0]
        self.assertEqual(py[0][0], "passou")
        self.assertNotIn("passou", py[0][1:] + py[1])
        self.assertEqual(py, js)
        self.assertEqual(len(circuito.com_pinos({"pecas": []}, {"GPIO32": 1})["pecas"]), 0)

    def test_motivo_de_nao_ligar_com_esp32(self):
        """o ▶ Ligar: placa com ESP32 liga, crua ou já com comPinos; sem pilha nem ESP32 não; número pendente diz qual"""
        G = {"GND": "GND", "3V3": "N3", "GPIO32": "N1"}
        led = [peca("R1", RESISTOR, {"1": "N1", "2": "N2"}, valor=220), peca("D1", LED, {"1": "N2", "2": "GND"})]
        casos = [   # (peças, o motivo esperado)
            ([mcu(G)] + led, None),
            ([peca("BT1", PILHA, {"1": "N1", "2": "GND"})] + led, None),
            (led, "sem pilha nem ESP32 na placa, nada pra ligar"),
            ([mcu(G, {**MCU, "r_pino": None})] + led, "U1: falta conferir a resistência do pino no datasheet"),
            ([mcu(G, {**MCU, "r_pull": "pendente"})] + led, "U1: falta conferir o pull-up de dentro no datasheet"),
            ([mcu({"GND": "GND", "3V3": "N3"}, {**MCU, "r_pino": None})] + led, None),   # sem GPIO ligado, sem r_pino
            ([mcu(G, {**MCU, "vdd": None})] + led, "U1: falta conferir a tensão do 3V3 no datasheet"),
            ([mcu(G, {**MCU, "r_3v3": None})] + led, "U1: falta conferir a resistência do 3V3 no datasheet"),
        ]
        js = no_node("console.log(JSON.stringify(entrada.map(pecas => motivoSemSimulacao({ simulacao: { pode: true }, pecas }))));",
                     [pecas for pecas, _ in casos])
        self.assertEqual(js, [motivo for _, motivo in casos])
        ja = no_node("const m = { simulacao: { pode: true }, pecas: entrada };"
                     "console.log(JSON.stringify([motivoSemSimulacao(comPinos(m, {})), motivoSemSimulacao(comPinos(m, { GPIO32: 1 }))]));",
                     casos[0][0])
        self.assertEqual(ja, [None, None], "já com comPinos, também liga")

    def test_resolver_linear_igual_ate_o_ultimo_bit(self):
        """o resolverLinear tira da linha inteira (j de 0), como o Python: o mesmo número até o último bit.
        Com j = c (o jeito antigo do app), as sobras das colunas já zeradas mudam a diagonal no fim"""
        rnd = random.Random(10)
        casos = []
        for _ in range(200):
            n = rnd.randint(2, 8)
            A = [[circuito.GMIN if i == j else 0.0 for j in range(n)] for i in range(n)]
            for _ in range(rnd.randint(n, 3 * n)):   # condutâncias entre nets, do jeito que o resolver monta (n = o terra)
                a, b = rnd.sample(range(n + 1), 2)
                g = 1 / rnd.choice([circuito.R_CHAVE, 3.5, 20, 30, 220, 1000, 22000, 45000, 1e6])
                for x, y in ((a, b), (b, a)):
                    if x < n:
                        A[x][x] += g
                        if y < n:
                            A[x][y] -= g
            casos.append([A, [rnd.uniform(-1, 1) / rnd.choice([1, 30, 1000]) for _ in range(n)]])
        js = no_node("console.log(JSON.stringify(entrada.map(([A, b]) => resolverLinear(A, b))));", casos)
        for k, ((A, b), x_js) in enumerate(zip(casos, js)):
            self.assertEqual(circuito.resolver_linear(A, b), x_js, k)

    def test_brilho_igual_nas_duas(self):
        import blocos
        led = {"brilho": [[0.001, 0], [0.005, 0.32], [0.010, 0.60], [0.020, 1.0], [0.030, 1.36]]}
        correntes = [0, 0.0005, 0.001, 0.003, 0.0075, 0.012, 0.02, 0.025, 0.05]
        programa = js_do_app() + f"\nconsole.log(JSON.stringify({json.dumps(correntes)}.map(i => brilhoDaCorrente({json.dumps(led)}, i))));"
        r = subprocess.run([NODE, "-e", programa], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr[-1000:])
        for i, b_js in zip(correntes, json.loads(r.stdout)):
            self.assertAlmostEqual(blocos.brilho_da_corrente(led, i), b_js, places=9, msg=str(i))


if __name__ == "__main__":
    unittest.main()
