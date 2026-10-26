"""o programa da placa no gêmeo (programa.py): pinos.py, a cópia pro laboratório, o programa.json e o confere.json"""
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from apoio import apagar
import catalogo
import circuito
import programa

DADOS = Path(__file__).resolve().parent / "dados"
TEM_LAB = programa.tem_laboratorio()

# U1 em (40, 32): a fileira de baixo (1-15) fica em y 19,3 e a de cima (16-30) em y 44,7.
# Pino 6 = GPIO32, 11 = GPIO14, 14 = GND, 4 = GPIO34, 16 = 3V3. O 220 Ω e o led_5mm são só de ensaio
BOA = """placa 80 56
furos cantos 3.2
peca U1 devkit_esp32_30 40 32
peca R1 resistor_axial 28 9 220
peca D1 led_5mm 18 9
peca R2 resistor_axial 52 9 1k
peca SW1 botao_6x6 66 9
liga U1.6 R1.2
liga R1.1 D1.1
liga D1.2 GND
liga U1.11 R2.1
liga R2.2 SW1.1
liga SW1.3 GND
"""
# 3V3 → 22 kΩ → GPIO34 → LDR → GND (o divisor da luz noturna) e um botão no GPIO14
LDR = """placa 80 64
furos cantos 3.2
peca U1 devkit_esp32_30 40 32
peca R1 resistor_axial 64 54 22k
peca LDR1 C10081 26 9
peca R2 resistor_axial 52 9 1k
peca SW1 botao_6x6 66 9
liga U1.16 R1.1
liga R1.2 U1.4
liga U1.4 LDR1.1
liga LDR1.2 GND
liga U1.11 R2.1
liga R2.2 SW1.1
liga SW1.3 GND
"""
# pisca o D1 (no pino que o pinos.py disser) e escreve na serial
PISCA = """from machine import Pin
import time
from pinos import D1
led = Pin(D1, Pin.OUT)
for i in range(4):
    led.value(1)
    print("acendeu")
    time.sleep_ms(250)
    led.value(0)
    print("apagou")
    time.sleep_ms(250)
"""


def peca_da_loja(codigo):
    """pecas/<codigo>.json mínimo: a elétrica, os nomes e a fonte são os conferidos do catálogo (T3);
    o desenho (2 furos a 5,08 mm) é só pro teste"""
    c = catalogo.conferido(codigo)
    pad = {"forma": "C", "d": 1.6}
    return {"nome": f"peça {codigo}", "explica": "peça de teste", "fonte": c["fonte"], "corpo": [6.0, 3.0],
            "pinos": {"1": {"x": -2.54, "y": 0, "pad": pad, "furo": 0.8}, "2": {"x": 2.54, "y": 0, "pad": pad, "furo": 0.8}},
            "nomes": c["nomes"], "eletrica": c["eletrica"], "pendente": []}


def placa_temp(texto, nome="esp32", arquivos=None, pecas=()):
    """placa numa pasta temporária: arquivos = {"codigo/main.py": texto, ...}; pecas = códigos do catálogo"""
    pasta = Path(tempfile.mkdtemp(prefix="sianvolt-teste-")) / nome
    (pasta / "pecas").mkdir(parents=True)
    (pasta / "placa.txt").write_text(texto)
    for codigo in pecas:
        (pasta / "pecas" / f"{codigo}.json").write_text(json.dumps(peca_da_loja(codigo), ensure_ascii=False))
    for arq, conteudo in (arquivos or {}).items():
        (pasta / arq).parent.mkdir(parents=True, exist_ok=True)
        (pasta / arq).write_text(conteudo if isinstance(conteudo, str) else json.dumps(conteudo, ensure_ascii=False))
    return pasta


class Temporarias(unittest.TestCase):
    def placa(self, *a, **k):
        pasta = placa_temp(*a, **k)
        self.addCleanup(apagar, pasta)
        return pasta


class Normalizar(Temporarias):
    """a linha do tempo do lab.py -> programa.json, offline (as saídas de verdade estão em testes/dados/)"""

    def ler(self, nome, projeto=None):
        pasta = self.placa((DADOS / f"{nome}.txt").read_text(), nome, {"projeto.json": projeto} if projeto else None)
        return programa.normalizar((DADOS / f"saida_{nome}.jsonl").read_text().splitlines(), pasta)

    def test_pisca(self):
        p = self.ler("pisca")
        d1 = p["leds"]["D1"]
        self.assertEqual(d1[0], [0.0, 0.0, 0.0, False])                       # apagado no começo
        self.assertEqual(d1[1], [0.015, 0.59, 5.9, False])                    # t em ms, luz, mA, queima
        apaga = next(x for x in d1 if x[0] > 1 and x[1] == 0)
        self.assertAlmostEqual(apaga[0], 500.719)
        self.assertIn([0.015, "acendeu"], p["serial"])
        self.assertEqual((p["tempo_ms"], p["codigo"], p["erro"], p["livre"]), (2000.0, 0, None, False))
        g2 = p["pinos"]["GPIO2"]
        self.assertEqual((g2["quem"], g2["nome"]), ("D1", "LED"))             # do NOSSO placa.txt
        self.assertEqual(g2["modo"], [[0.005, "saida"]])
        self.assertEqual(g2["nivel"][:3], [[0.005, 0], [0.015, 1], [500.719, 0]])
        self.assertFalse([a for a in p["avisos"] if a[1] == "led"])          # o brilho foi todo pro leds
        self.assertEqual(p["conferencias"], {"ok": [], "falhas": []})
        self.assertIn("D1: o datasheet não tem a curva de brilho; a luz é a corrente ÷ a corrente de teste (uma reta)",
                      p["pendentes"])
        self.assertTrue(any(x.startswith("U1: ") for x in p["pendentes"]))   # os pendentes do 3V3 do DevKit

    def test_mistura_pwm_botao_e_nome_de_gente(self):
        proj = {"objetivo": "ensaio", "blocos": [{"ref": "D1", "bloco": "led", "pino": "GPIO23", "nome": "LED do botão"},
                                                 {"ref": "SW1", "bloco": "botao", "pino": "GPIO4", "nome": "botão grande"}]}
        p = self.ler("mistura", proj)
        self.assertIn([100.245, 0.06, 0.6, False], p["leds"]["D2"])         # meia luz: a corrente média
        self.assertIn([1004.694, 0.59, 5.9, False], p["leds"]["D2"])
        self.assertEqual(p["pinos"]["GPIO2"]["pwm"][1], [100.245, 0.1, 1000.0])
        self.assertEqual((p["pinos"]["GPIO23"]["quem"], p["pinos"]["GPIO23"]["nome"]), ("D1", "LED do botão"))
        self.assertEqual((p["pinos"]["GPIO4"]["quem"], p["pinos"]["GPIO4"]["nome"]), ("SW1", "botão grande"))
        self.assertEqual((p["pinos"]["GPIO2"]["quem"], p["pinos"]["GPIO2"]["nome"]), ("D2", "LED"))
        self.assertEqual(p["pinos"]["GPIO4"]["modo"], [[0.01, "pullup"]])
        self.assertEqual(p["serial"][0], [300.665, "botao 0 300 ms"])
        self.assertEqual((p["tempo_ms"], p["codigo"]), (1105.241, 0))
        self.assertEqual(list(p["pinos"]), ["GPIO2", "GPIO4", "GPIO23"])      # em ordem de número

    def evento(self, t, tipo, **campos):
        return json.dumps({"t_ms": t, "tipo": tipo, **campos}, ensure_ascii=False)

    def test_queima_mesmo_com_o_aviso_que_nao_repete(self):
        """o gêmeo avisa 'QUEIMA' uma vez só por texto: o LED que acende de novo com a mesma corrente queima de novo"""
        pasta = self.placa((DADOS / "pisca.txt").read_text())
        forte = "D1 aceso, 35,2 mA, luz 100% do anúncio"
        linhas = [self.evento(0, "aviso", texto="D1 apagado", codigo="led"),
                  self.evento(1, "aviso", texto=forte, codigo="led"),
                  self.evento(1, "aviso", texto="D1 QUEIMA: passa 35,2 mA, acima do máximo do datasheet", codigo="queima"),
                  self.evento(2, "aviso", texto="D1 apagado", codigo="led"),
                  self.evento(3, "aviso", texto=forte, codigo="led"),
                  self.evento(4, "aviso", texto="D1 aceso, 5,9 mA, luz 59% do anúncio", codigo="led")]
        p = programa.normalizar(linhas, pasta)
        self.assertEqual([x[3] for x in p["leds"]["D1"]], [False, True, False, True, False])
        self.assertIn([1, "queima", "D1 QUEIMA: passa 35,2 mA, acima do máximo do datasheet"], p["avisos"])

    def test_campos_numericos_valem_mais_que_o_texto(self):
        pasta = self.placa((DADOS / "pisca.txt").read_text())
        linhas = [self.evento(5, "aviso", texto="qualquer coisa", codigo="led", ref="D1", luz=0.42, i_med=0.0071,
                              i_max=0.0071, queima=False),
                  self.evento(6, "aviso", texto="D1 brilha de um jeito novo", codigo="led")]
        p = programa.normalizar(linhas, pasta)
        self.assertEqual(p["leds"]["D1"], [[5, 0.42, 7.1, False]])
        self.assertIn([6, "led", "D1 brilha de um jeito novo"], p["avisos"])  # texto que não entendo não some

    def test_erro_com_a_linha_do_main(self):
        pasta = self.placa((DADOS / "pisca.txt").read_text())
        tb = 'Traceback (most recent call last):\n  File "main.py", line 5, in <module>\nValueError: pin can only be input'
        fim = dict(estado="erro", motor="gemeo", placa="esp32", alvo="esp32", tempo_placa_ms=100.3, tempo_pc_s=0.1, ram_mb=3)
        p = programa.normalizar([self.evento(100.3, "erro", texto=tb), self.evento(100.3, "fim", **fim)], pasta)
        self.assertEqual(p["erro"], {"t": 100.3, "texto": tb, "linha": 5})
        self.assertEqual((p["codigo"], p["tempo_ms"]), (1, 100.3))

    def test_conferencias_do_laboratorio_casam_com_o_roteiro(self):
        """o lab.py só manda o texto das que falharam; as que passaram saem da descrição do roteiro"""
        pasta = self.placa((DADOS / "pisca.txt").read_text())
        confere = [{"t": 0.1, "pino": "GPIO2", "valor": 1}, {"t": 0.6, "pino": "GPIO2", "valor": 1},
                   {"serial": "acendeu", "ate": 0.5}, {"t": 0.3, "pwm": "GPIO2", "duty": [0.2, 0.3]},
                   {"trocas": "GPIO2", "min": 4}, {"estado": "tempo"}]
        conf = self.evento(2000, "conferencias", ok=4, falhas=["GPIO2 = 1 em 0,600 s: viu 0",
                                                               "GPIO2 em 0,300 s com duty entre 0,2 e 0,3: viu 1"])
        fim = self.evento(2000, "fim", estado="tempo", motor="gemeo", placa="esp32", alvo="esp32", tempo_placa_ms=2000,
                          tempo_pc_s=0.1, ram_mb=3)
        p = programa.normalizar([fim, conf], pasta, confere=confere)
        self.assertEqual(p["conferencias"]["falhas"], ["GPIO2 = 1 em 0,600 s: viu 0",
                                                       "GPIO2 em 0,300 s com duty entre 0,2 e 0,3: viu 1"])
        self.assertEqual(p["conferencias"]["ok"], ["GPIO2 = 1 em 0,100 s", "serial com 'acendeu' até 0,500 s",
                                                   "trocas de GPIO2 entre 4 e ∞", "estado tempo"])
        self.assertEqual(p["codigo"], 4)   # sem o código do lab.py: o que ele daria
        self.assertEqual(programa.normalizar([conf], pasta)["codigo"], 3)   # sem o 'fim', o laboratório diz 'travou'

    def test_conferencias_que_nao_casam_ficam_na_conta(self):
        pasta = self.placa((DADOS / "pisca.txt").read_text())
        conf = self.evento(1, "conferencias", ok=2, falhas=["um texto que nenhum item do roteiro escreveria"])
        p = programa.normalizar([conf], pasta, confere=[{"serial": "a"}, {"serial": "b"}, {"serial": "c"}])
        self.assertEqual(len(p["conferencias"]["ok"]), 2)
        self.assertEqual(p["conferencias"]["falhas"], ["um texto que nenhum item do roteiro escreveria"])


class Pinos(Temporarias):
    def test_pinos_py(self):
        proj = {"objetivo": "x", "blocos": [{"ref": "D1", "bloco": "led", "pino": "GPIO32", "nome": "LED A"}]}
        pasta = self.placa(BOA, arquivos={"projeto.json": proj})
        self.assertEqual(programa.pinos(pasta), {"D1": 32, "SW1": 14})
        txt = (pasta / "codigo" / "pinos.py").read_text()
        self.assertIn("gerado pelo Sianvolt, não edite", txt)
        self.assertIn("D1 = 32  # LED A, U1 pino 6, D32, pelo R1\n", txt)   # o nome de gente vem do projeto.json
        self.assertIn("SW1 = 14  # botão, U1 pino 11, D14, pelo R2\n", txt)  # um nome por botão (são 4 pinos)
        self.assertNotIn("R1 =", txt)
        self.assertFalse((pasta / "codigo" / "placa.py").exists())           # placa.py é do laboratório
        compile(txt, "pinos.py", "exec")
        antes = (pasta / "codigo" / "pinos.py").stat().st_mtime_ns
        programa.pinos(pasta)
        self.assertEqual((pasta / "codigo" / "pinos.py").stat().st_mtime_ns, antes)   # sem mudança, não reescreve

    def test_ldr_direto_e_o_resistor_do_divisor_fora(self):
        pasta = self.placa(LDR, pecas=["C10081"])
        self.assertEqual(programa.pinos(pasta), {"LDR1": 34, "SW1": 14})
        self.assertIn("LDR1 = 34  # olho de luz, U1 pino 4, D34\n", (pasta / "codigo" / "pinos.py").read_text())

    def test_peca_em_dois_gpios_e_gpio_na_energia(self):
        # SW1 entre o GPIO14 (por R2) e o GPIO33; o GPIO27 direto no GND; um pull-down (R3) do GPIO13 pro GND:
        # o GND não leva adiante, senão o D1 (que tem o − no GND) apareceria no GPIO13
        txt = BOA + "peca R3 resistor_axial 40 52 10k\nliga U1.7 SW1.3\nliga U1.10 GND\nliga U1.13 R3.1\nliga R3.2 GND\n"
        pasta = self.placa(txt.replace("liga SW1.3 GND\n", ""))
        nomes = programa.pinos(pasta)
        self.assertEqual(nomes, {"D1": 32, "SW1_3": 33, "SW1_1": 14})   # direto primeiro, depois pelo resistor
        self.assertNotIn(27, nomes.values())
        self.assertNotIn(13, nomes.values())

    def test_sem_esp32(self):
        pasta = self.placa("placa 30 20\npeca R1 resistor_axial 15 10 220\n")
        with self.assertRaisesRegex(ValueError, "não tem o ESP32"):
            programa.pinos(pasta)


class Preparar(Temporarias):
    def ldr(self, roteiro=None, gemeo="", **k):
        arquivos = {"codigo/main.py": "print('oi')\n", "codigo/outro.py": "X = 1\n", "codigo/notas.txt": "não vai"}
        if roteiro is not None:
            arquivos["codigo/roteiro.json"] = roteiro
        if gemeo:
            arquivos["codigo/gemeo.roteiro"] = gemeo
        return self.placa(LDR, pecas=["C10081"], arquivos=arquivos, **k)

    def test_luz_vira_volts_e_nunca_linha_de_lux(self):
        pasta = self.ldr({"tempo": 3, "entradas": [{"t": 0, "luz": "LDR1", "lux": 100, "_": "quarto aceso"}],
                          "confere": [{"serial": "oi"}]}, gemeo="# só comentário\n")
        copia, usadas = programa.preparar(pasta, {"luz": [{"ref": "LDR1", "t": 2, "lux": 1}]}, livre=True)
        rot = json.loads((copia / "roteiro.json").read_text())
        e = catalogo.conferido("C10081")["eletrica"]
        um, cem = (circuito.divisor_do_ldr(e, 22000, 3.3, lux) for lux in (1, 100))
        v100, v1 = rot["entradas"]
        self.assertEqual((v100["t"], v100["pino"], v1["t"], v1["pino"]), (0, "GPIO34", 2, "GPIO34"))
        self.assertAlmostEqual(v1["volts"], um, delta=1e-3)
        self.assertAlmostEqual(v100["volts"], cem, delta=1e-3)
        self.assertNotIn("confere", rot)                                    # o livre roda sem conferências
        self.assertNotIn("lux", (copia / "gemeo.roteiro").read_text().lower())
        self.assertNotIn("lux", json.dumps([{k: v for k, v in x.items() if k != "_"} for x in rot["entradas"]]))
        self.assertEqual(usadas["luz"], [{"ref": "LDR1", "t": 0.0, "lux": 100, "volts": v100["volts"], "origem": "roteiro"},
                                         {"ref": "LDR1", "t": 2000.0, "lux": 1, "volts": v1["volts"], "origem": "app"}])
        self.assertEqual(sorted(a.name for a in copia.iterdir()), ["gemeo.roteiro", "main.py", "outro.py", "roteiro.json"])
        self.assertEqual(copia.parent, pasta.resolve() / "saida" / "programa")
        self.assertRegex(copia.name, r"^sianvolt_esp32_[0-9a-f]{8}$")

    def test_apertos_do_app_no_fim_do_gemeo_roteiro(self):
        pasta = self.ldr({"tempo": 3, "confere": [{"serial": "oi"}]}, gemeo="de 0,5 s a 1 s aperta SW1\n")
        copia, usadas = programa.preparar(pasta, {"apertos": [{"ref": "SW1", "de": 12, "ate": 12.25}]})
        linhas = (copia / "gemeo.roteiro").read_text().splitlines()
        self.assertEqual(linhas[0], "de 0,5 s a 1 s aperta SW1")
        self.assertTrue(linhas[-1].startswith("de 12 s a 12,25 s aperta SW1"))
        rot = json.loads((copia / "roteiro.json").read_text())
        self.assertEqual(rot["tempo"], 13.25)                    # o aperto acontece antes do fim da rodada
        self.assertEqual(rot["confere"], [{"serial": "oi"}])     # fora do livre, a conferência fica
        self.assertEqual(usadas["apertos"], [{"ref": "SW1", "de": 500.0, "ate": 1000.0, "origem": "roteiro"},
                                             {"ref": "SW1", "de": 12000.0, "ate": 12250.0, "origem": "app"}])
        self.assertEqual((pasta / "codigo" / "gemeo.roteiro").read_text(), "de 0,5 s a 1 s aperta SW1\n")   # a placa não muda

    def test_tempos_do_app_no_ms(self):
        """o gemeo.roteiro enxerga até o ms: o aperto que viraria 0 ms não passa, e o programa.json guarda o tempo
        que o gêmeo usou (e não o que veio)"""
        pasta = self.ldr()
        with self.assertRaisesRegex(ValueError, "SW1 tem que soltar pelo menos 1 ms depois de apertar"):
            programa.preparar(pasta, {"apertos": [{"ref": "SW1", "de": 1.0001, "ate": 1.0004}]}, livre=True)
        copia, usadas = programa.preparar(pasta, {"apertos": [{"ref": "SW1", "de": 1.0004, "ate": 1.0016}],
                                                  "luz": [{"ref": "LDR1", "t": 2.0004, "lux": 1}]}, livre=True)
        self.assertEqual((copia / "gemeo.roteiro").read_text(), "de 1 s a 1,002 s aperta SW1   # do app\n")
        self.assertEqual(usadas["apertos"], [{"ref": "SW1", "de": 1000.0, "ate": 1002.0, "origem": "app"}])
        self.assertEqual((usadas["luz"][0]["t"], json.loads((copia / "roteiro.json").read_text())["entradas"][0]["t"]),
                         (2000.0, 2.0))

    def test_copia_isolada_tem_o_pid(self):
        pasta = self.ldr()
        copia, _ = programa.preparar(pasta, isolada=True)
        self.assertEqual(copia.name, f"{programa.nome_da_copia(pasta)}_{os.getpid()}")
        self.assertEqual(json.loads((copia / "roteiro.json").read_text()), {"entradas": []})

    def test_o_que_nao_entra(self):
        pasta = self.ldr(gemeo="em 5 s LDR1 = 1 lux\n")
        with self.assertRaisesRegex(ValueError, "gemeo.roteiro, linha 1: a luz vai no roteiro.json"):
            programa.preparar(pasta)
        pasta = self.ldr({"entradas": [{"t": 1, "luz": "R1", "lux": 1}]})
        with self.assertRaisesRegex(ValueError, "R1 não é um olho de luz"):
            programa.preparar(pasta)
        pasta = self.placa(LDR, pecas=["C10081"])
        with self.assertRaisesRegex(ValueError, "falta o codigo/main.py"):
            programa.preparar(pasta)

    def test_entradas_do_app_conferidas(self):
        pasta = self.ldr()
        ruins = {"aperto em quem não é botão": {"apertos": [{"ref": "R1", "de": 1, "ate": 2}]},
                 "luz em quem não é LDR": {"luz": [{"ref": "SW1", "t": 1, "lux": 1}]},
                 "tempo 999": {"apertos": [{"ref": "SW1", "de": 1, "ate": 999}]},
                 "tempo negativo": {"luz": [{"ref": "LDR1", "t": -1, "lux": 1}]},
                 "solta antes": {"apertos": [{"ref": "SW1", "de": 2, "ate": 1}]},
                 "lux negativo": {"luz": [{"ref": "LDR1", "t": 1, "lux": -5}]},
                 "lux texto": {"luz": [{"ref": "LDR1", "t": 1, "lux": "10"}]},
                 "tempo infinito": {"luz": [{"ref": "LDR1", "t": float("inf"), "lux": 1}]},
                 "campo a mais": {"apertos": [{"ref": "SW1", "de": 1, "ate": 2, "x": 1}]},
                 "chave a mais": {"apertos": [], "rm": "-rf"},
                 "não é lista": {"apertos": {"ref": "SW1"}},
                 "51 entradas": {"apertos": [{"ref": "SW1", "de": 1, "ate": 2}] * 51}}
        for nome, entradas in ruins.items():
            with self.subTest(nome), self.assertRaises(ValueError):
                programa.validar_entradas(pasta, entradas)
        boas = {"apertos": [{"ref": "SW1", "de": 0, "ate": 60}] * 25, "luz": [{"ref": "LDR1", "t": 60, "lux": 0}] * 25}
        self.assertEqual(len(programa.validar_entradas(pasta, boas)["apertos"]), 25)


def prog_de_ensaio():
    """um programa.json à mão: o dado mostrou a face 2 (D1 e D7), o 'já!' (GPIO25) subiu em 1000 ms e o buzzer
    (GPIO26) apitou em 4 kHz; a serial diz o tempo de reação; o GPIO27 sobe de 0 a 0,36 em PWM"""
    def pino(**k):
        return {"quem": None, "nome": None, "modo": [], "nivel": [], "pwm": [], "volts": [], **k}
    return {"tempo_ms": 5000.0, "serial": [[900.0, "deu 2"], [1387.6, "J1 ganhou em 387 ms"], [2500.0, "deu 1"]],
            "leds": {"D1": [[0, 0.0, 0.0, False], [800.0, 0.59, 5.9, False], [2400.0, 0.0, 0.0, False]],
                     "D7": [[0, 0.0, 0.0, False], [800.0, 0.59, 5.9, False], [2400.0, 0.0, 0.0, False]],
                     "D4": [[0, 0.0, 0.0, False], [2400.0, 0.59, 5.9, False]]},
            "pinos": {"GPIO25": pino(nivel=[[0.005, 0], [1000.0, 1], [1387.0, 0], [3000.0, 1]]),
                      "GPIO26": pino(pwm=[[0.03, 0.0, 4000.0], [1000.015, 0.5, 4000.0], [1150.0, 0.0, 4000.0],
                                          [1388.0, 0.5, 1047.0], [1500.0, 0.0, 1047.0], [3000.02, 0.5, 4000.0]]),
                      "GPIO27": pino(pwm=[[0.03, 0.0, 1000.0], [2000.0, 0.1, 1000.0], [3000.0, 0.36, 1000.0]])}}


class Conferir(unittest.TestCase):
    def confere(self, *itens):
        return programa.conferir(prog_de_ensaio(), {"confere": list(itens)})

    def um(self, item):
        r = self.confere(item)
        self.assertEqual(len(r["ok"]) + len(r["falhas"]), 1)
        return bool(r["ok"]), (r["ok"] or r["falhas"])[0]

    def test_leds_da_serial(self):
        mapa = {"1": ["D4"], "2": ["D1", "D7"]}
        self.assertTrue(self.um({"tipo": "leds_da_serial", "regex": r"deu (\d)", "mapa": mapa})[0])
        ok, txt = self.um({"tipo": "leds_da_serial", "regex": r"deu (\d)", "mapa": {"1": ["D1"], "2": ["D1", "D7"], "x": ["D4"]}})
        self.assertFalse(ok)
        self.assertIn("em 2,500 s a serial disse 'deu 1' e os acesos são D4 (a face 1 é D1)", txt)
        self.assertFalse(self.um({"tipo": "leds_da_serial", "regex": r"saiu (\d)", "mapa": mapa})[0])
        ok, txt = self.um({"tipo": "leds_da_serial", "regex": r"deu (\d)", "mapa": {**mapa, "3": ["D9"]}})
        self.assertIn("D9 não aparece no programa", txt)
        ok, txt = self.um({"tipo": "leds_da_serial", "regex": r"deu (\d)", "mapa": {"1": ["D4"], "2": ["D1"], "x": ["D7"]}})
        self.assertFalse(ok)   # LED aceso a mais também é erro
        self.assertIn("os acesos são D1, D7 (a face 2 é D1)", txt)

    def test_pwm_freq(self):
        ok, txt = self.um({"tipo": "pwm_freq", "pino": "GPIO26", "hz": 4000, "folga": 50, "depois_de": "GPIO25 sobe"})
        self.assertTrue(ok, txt)
        self.assertIn("viu 2 vezes", txt)
        ok, txt = self.um({"tipo": "pwm_freq", "pino": "GPIO26", "hz": 1047, "folga": 5, "depois_de": "GPIO25 sobe"})
        self.assertFalse(ok)
        self.assertIn("em 1,000 s ligou em 4000 Hz", txt)
        self.assertTrue(self.um({"tipo": "pwm_freq", "pino": "GPIO26", "hz": 1047, "folga": 5, "depois_de": 1.2})[0])
        self.assertFalse(self.um({"tipo": "pwm_freq", "pino": "GPIO26", "hz": 4000, "folga": 50, "depois_de": "GPIO4 sobe"})[0])
        ligado_antes = {"tipo": "pwm_freq", "pino": "GPIO27", "hz": 1000, "folga": 1, "depois_de": 4.0}
        self.assertTrue(self.um(ligado_antes)[0])   # o PWM que já estava ligado no instante conta
        prog = prog_de_ensaio()
        prog["pinos"]["GPIO26"]["pwm"][-1][2] = 1047.0   # no segundo 'já!' o apito sai na nota errada
        r = programa.conferir(prog, [{"tipo": "pwm_freq", "pino": "GPIO26", "hz": 4000, "folga": 50, "depois_de": "GPIO25 sobe"}])
        self.assertEqual(len(r["falhas"]), 1)
        self.assertIn("em 3,000 s ligou em 1047 Hz", r["falhas"][0])

    def test_serial_menos_evento(self):
        item = {"tipo": "serial_menos_evento", "regex_ms": r"ganhou em (\d+) ms", "evento": "GPIO25 sobe", "folga_ms": 2}
        self.assertTrue(self.um(item)[0])                                       # 1387,6 − 1000 = 387,6 ms
        ok, txt = self.um({**item, "folga_ms": 0.1})
        self.assertFalse(ok)
        self.assertIn("a serial diz 387 ms e o relógio da placa, 387,6 ms", txt)
        self.assertFalse(self.um({**item, "evento": "GPIO25 desce"})[0])         # desceu 0,6 ms antes da linha
        self.assertFalse(self.um({**item, "regex_ms": r"perdeu em (\d+) ms"})[0])
        ok, txt = self.um({**item, "regex_ms": r"(J\d) ganhou"})
        self.assertFalse(ok)
        self.assertIn("em 'J1 ganhou em 387 ms' o grupo da regex não é um número", txt)

    def test_duty_entre(self):
        item = {"tipo": "duty_entre", "pino": "GPIO27", "de_t": 3, "ate_t": 5, "min": 0.35, "max": 0.37}
        ok, txt = self.um(item)
        self.assertTrue(ok, txt)
        ok, txt = self.um({**item, "de_t": 2.5})
        self.assertFalse(ok)
        self.assertIn("em 2,500 s o duty era 0,1", txt)
        self.assertIn("não deu pra ver", self.um({**item, "ate_t": 6})[1])
        self.assertTrue(self.um({"tipo": "duty_entre", "pino": "GPIO25", "de_t": 1.0, "ate_t": 1.3, "min": 1, "max": 1})[0])
        self.assertFalse(self.um({"tipo": "duty_entre", "pino": "GPIO25", "de_t": 1.0, "ate_t": 1.4, "min": 1, "max": 1})[0])

    def test_confere_errado(self):
        ruins = [{"tipo": "outro"}, {"tipo": "duty_entre", "pino": "GPIO27"},
                 {"tipo": "pwm_freq", "pino": "GPIO26", "hz": 4000, "folga": 50, "depois_de": "quando o já subir"},
                 {"tipo": "leds_da_serial", "regex": r"deu \d", "mapa": {"1": ["D1"]}},
                 {"tipo": "leds_da_serial", "regex": "deu (", "mapa": {"1": ["D1"]}},
                 {"tipo": "serial_menos_evento", "regex_ms": r"(\d+)", "evento": "GPIO25 sobe", "folga_ms": -1},
                 {"tipo": "duty_entre", "pino": "25", "de_t": 1, "ate_t": 2, "min": 0, "max": 1},
                 {"tipo": "duty_entre", "pino": "GPIO25", "de_t": 2, "ate_t": 1, "min": 0, "max": 1},
                 {"tipo": "pwm_freq", "pino": "GPIO26", "hz": 4000, "folga": 50, "a_mais": 1}]
        for c in ruins:
            with self.subTest(c), self.assertRaises(ValueError):
                self.confere(c)
        self.assertEqual(self.confere({"tipo": "duty_entre", "pino": "GPIO27", "de_t": 3, "ate_t": 5, "min": 0.3,
                                       "max": 0.4, "_": "comentário"})["falhas"], [])
        # a chave de cima errada ou a mais não passa calada como zero conferências
        for dados in ({"confer": [{"tipo": "duty_entre"}]}, {"confere": [], "a_mais": 1}, {}, {"confere": {}}, None):
            with self.subTest(dados), self.assertRaisesRegex(ValueError, r'o confere.json é \{"confere"'):
                programa.conferir(prog_de_ensaio(), dados)
        self.assertEqual(programa.conferir(prog_de_ensaio(), {"_": "comentário", "confere": []}), {"ok": [], "falhas": []})


class SemLaboratorio(Temporarias):
    def test_sem_lab_e_codigo_5(self):
        pasta = self.placa(BOA, arquivos={"codigo/main.py": PISCA})
        lab, programa.LAB = programa.LAB, pasta / "nao_tem" / "lab.py"
        try:
            p = programa.rodar(pasta, isolada=True)
        finally:
            programa.LAB = lab
        self.assertEqual(p["codigo"], 5)
        self.assertEqual(p["avisos"][-1][1], "indisponivel")
        self.assertEqual(json.loads((pasta / "saida" / "programa.json").read_text())["codigo"], 5)
        self.assertEqual(list((pasta / "saida" / "programa").iterdir()), [])   # a cópia isolada foi apagada

    def test_erro_antes_do_lab_vai_pro_arquivo(self):
        pasta = self.placa(BOA, arquivos={"codigo/main.py": PISCA, "codigo/roteiro.json": "{isto não é json"})
        p = programa.rodar(pasta, livre=True)
        self.assertEqual(p["codigo"], 2)
        self.assertIn("roteiro.json não é JSON válido", p["erro"]["texto"])
        self.assertTrue((pasta / "saida" / "programa_livre.json").is_file())

    def test_trava_por_placa(self):
        pasta = self.placa(BOA, arquivos={"codigo/main.py": PISCA})
        (pasta / "saida").mkdir()
        outro = subprocess.Popen([sys.executable, "-c", "import fcntl, sys, time; f = open(sys.argv[1], 'a'); "
                                  "fcntl.flock(f, fcntl.LOCK_EX); print('ok', flush=True); time.sleep(30)",
                                  str(pasta / "saida" / ".rodando")], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(outro.stdout.readline().strip(), "ok")
            self.assertTrue(programa.ocupada(pasta))
            with self.assertRaises(programa.Ocupada):
                programa.rodar(pasta, esperar=False)
        finally:
            outro.kill()
            outro.wait()
            outro.stdout.close()
        self.assertFalse(programa.ocupada(pasta))
        with programa.trava(pasta) as t, programa.trava(pasta) as t2:   # a mesma thread pode segurar duas vezes
            self.assertTrue(t and t2)
            self.assertFalse(programa.ocupada(pasta))

    def test_ocupada_de_varias_threads(self):
        """o app olha de várias threads ao mesmo tempo: uma não pode ver a espiada da outra como uma rodada; e a
        rodada de outra thread conta como rodada"""
        pasta = self.placa(BOA)
        (pasta / "saida").mkdir()
        (pasta / "saida" / ".rodando").touch()
        vistas = []

        def olhar():
            vistas.extend([programa.ocupada(pasta) for _ in range(100)])
        threads = [threading.Thread(target=olhar) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual((len(vistas), vistas.count(True)), (600, 0))
        pegou, solta = threading.Event(), threading.Event()

        def rodada():
            with programa.trava(pasta):
                pegou.set()
                solta.wait(10)
        outra = threading.Thread(target=rodada)
        outra.start()
        try:
            self.assertTrue(pegou.wait(10))
            self.assertTrue(programa.ocupada(pasta))
        finally:
            solta.set()
            outra.join()
        self.assertFalse(programa.ocupada(pasta))

    def test_lab_parado_pelo_sistema_e_travou(self):
        """o lab.py morto por um sinal (falta de memória, kill) vira código 3, e não um código que ninguém conhece"""
        pasta = self.placa(BOA, arquivos={"codigo/main.py": PISCA, "lab_que_morre.py":
                                          "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n"})
        lab, programa.LAB = programa.LAB, pasta / "lab_que_morre.py"
        try:
            p = programa.rodar(pasta, isolada=True)
        finally:
            programa.LAB = lab
        self.assertEqual(p["codigo"], 3)
        self.assertEqual(p["erro"]["texto"], "o laboratório foi parado pelo sistema (sinal 9) antes de acabar")

    def test_vaga_do_lab_apagada(self):
        """a cópia de nome único deixava uma vaga (pasta + .trava) no build/ do laboratório a cada rodada: sai, menos
        a que outra rodada está usando e a que não é nossa"""
        pasta = self.placa(BOA)
        obra = pasta / "lab" / "build" / "esp32" / "gemeo"
        nome = programa.nome_da_copia(pasta, isolada=True)
        for n in (nome, f"{nome}~2", f"{nome}~3", "pisca"):
            (obra / n / n).mkdir(parents=True)
            (obra / f"{n}.trava").touch()
        lab, programa.LAB = programa.LAB, pasta / "lab" / "lab.py"
        try:
            with open(obra / f"{nome}~3.trava", "a") as f:   # outra rodada está na ~3
                fcntl.flock(f, fcntl.LOCK_EX)
                programa.apagar_vaga(nome)
            programa.apagar_vaga("pisca")
        finally:
            programa.LAB = lab
        self.assertEqual(sorted(x.name for x in obra.iterdir()), ["pisca", "pisca.trava", f"{nome}~3", f"{nome}~3.trava"])


@unittest.skipUnless(TEM_LAB, "sem o laboratório e o MicroPython do PC (laboratorio/ não está no clone limpo)")
class ComLaboratorio(Temporarias):
    def test_pisca_no_gemeo(self):
        roteiro = {"tempo": 2, "confere": [{"t": 0.1, "pino": "GPIO32", "valor": 1}, {"serial": "apagou", "ate": 0.5}]}
        confere = {"confere": [{"tipo": "duty_entre", "pino": "GPIO32", "de_t": 0.3, "ate_t": 0.45, "min": 0, "max": 0},
                               {"tipo": "leds_da_serial", "regex": "(acendeu|apagou)",
                                "mapa": {"acendeu": ["D1"], "apagou": []}}]}
        pasta = self.placa(BOA, arquivos={"codigo/main.py": PISCA, "codigo/roteiro.json": roteiro,
                                          "codigo/confere.json": confere})
        vistas, rodar_lab = [], programa.rodar_lab

        def espia(copia, *a):
            vistas.append((copia, sorted(x.name for x in copia.iterdir())))
            return rodar_lab(copia, *a)
        programa.rodar_lab = espia
        try:
            p = programa.rodar(pasta, isolada=True)
        finally:
            programa.rodar_lab = rodar_lab
        self.assertEqual(p["codigo"], 0, p)
        self.assertEqual(p["conferencias"]["falhas"], [])
        self.assertEqual(len(p["conferencias"]["ok"]), 4)
        self.assertTrue(any(x[1] > 0 for x in p["leds"]["D1"]))                     # o D1 acendeu
        self.assertEqual(p["pinos"]["GPIO32"]["quem"], "D1")
        self.assertIn("acendeu", [txt for _, txt in p["serial"]])
        self.assertEqual(json.loads((pasta / "saida" / "programa.json").read_text())["codigo"], 0)
        copia, arquivos = vistas[0]
        self.assertEqual(copia.name, f"sianvolt_esp32_{programa.nome_da_copia(pasta)[-8:]}_{os.getpid()}")
        self.assertEqual(arquivos, ["gemeo.roteiro", "main.py", "pinos.py", "roteiro.json"])
        self.assertFalse(copia.exists())                                             # apagada no fim
        vaga = programa.LAB.parent / "build" / "esp32" / "gemeo" / copia.name
        self.assertFalse(vaga.exists() or vaga.with_name(copia.name + ".trava").exists())   # e a vaga do lab.py também
        self.assertFalse(programa.ocupada(pasta))

    def test_confere_json_que_falha(self):
        """a conferência impossível do confere.json fica nas falhas (o código continua o do lab.py); confere.json
        errado também vira falha, e a linha do tempo continua valendo"""
        confere = {"confere": [{"tipo": "duty_entre", "pino": "GPIO32", "de_t": 0.3, "ate_t": 0.45, "min": 1, "max": 1}]}
        pasta = self.placa(BOA, arquivos={"codigo/main.py": PISCA, "codigo/roteiro.json": {"tempo": 1},
                                          "codigo/confere.json": confere})
        p = programa.rodar(pasta, isolada=True)
        self.assertEqual((p["codigo"], p["conferencias"]["ok"]), (0, []))
        self.assertEqual(p["conferencias"]["falhas"],
                         ["GPIO32 de 0,300 s a 0,450 s com duty entre 1 e 1: em 0,300 s o duty era 0"])
        (pasta / "codigo" / "confere.json").write_text('{"confere": [{"tipo": "fase_da_lua"}]}')
        p = programa.rodar(pasta, isolada=True)
        self.assertEqual(p["conferencias"]["falhas"], ["codigo/confere.json: confere 1: o tipo é um de leds_da_serial, "
                                                       "pwm_freq, serial_menos_evento, duty_entre"])
        self.assertIn("acendeu", [txt for _, txt in p["serial"]])
        self.assertFalse(programa.rodar(pasta, livre=True, isolada=True)["conferencias"]["falhas"])   # o livre não confere

    def test_passou_do_limite(self):
        """o lab.py que passa do LIMITE_S é parado (com o MicroPython junto) e a rodada vira código 3"""
        pasta = self.placa(BOA, arquivos={"codigo/main.py": "x = 0\nwhile True:\n    x += 1\n",
                                          "codigo/roteiro.json": {"tempo": 600}})
        limite, programa.LIMITE_S = programa.LIMITE_S, 1
        try:
            p = programa.rodar(pasta, isolada=True)
        finally:
            programa.LIMITE_S = limite
        self.assertEqual((p["codigo"], p["erro"]["texto"]), (3, "o laboratório passou de 1 s e foi parado"))
        self.assertFalse(programa.ocupada(pasta))

    def test_livre_com_aperto_do_app(self):
        main = ("from machine import Pin\nimport time\nfrom pinos import SW1\nb = Pin(SW1, Pin.IN, Pin.PULL_UP)\n"
                "antes = 1\nfor i in range(150):\n    v = b.value()\n    if v != antes:\n        print('botao', v)\n"
                "        antes = v\n    time.sleep_ms(10)\n")
        pasta = self.placa(BOA, arquivos={"codigo/main.py": main, "codigo/roteiro.json": {"confere": [{"serial": "nunca"}]}})
        p = programa.rodar(pasta, {"apertos": [{"ref": "SW1", "de": 0.5, "ate": 0.7}]}, livre=True, isolada=True)
        self.assertEqual((p["codigo"], p["livre"], p["conferencias"]), (0, True, {"ok": [], "falhas": []}))
        apertou = next(t for t, txt in p["serial"] if txt == "botao 0")
        self.assertAlmostEqual(apertou, 500, delta=15)
        self.assertEqual(p["entradas"]["apertos"], [{"ref": "SW1", "de": 500.0, "ate": 700.0, "origem": "app"}])
        self.assertTrue((pasta / "saida" / "programa_livre.json").is_file())
        self.assertFalse((pasta / "saida" / "programa.json").exists())

    def test_luz_no_divisor(self):
        main = "from machine import ADC, Pin\nimport time\nfrom pinos import LDR1\nadc = ADC(Pin(LDR1))\n" \
               "adc.atten(ADC.ATTN_11DB)\nfor i in range(4):\n    print('mv', adc.read_uv() // 1000)\n    time.sleep_ms(500)\n"
        pasta = self.placa(LDR, pecas=["C10081"], arquivos={"codigo/main.py": main,
                                                             "codigo/roteiro.json": {"tempo": 2}})
        p = programa.rodar(pasta, {"luz": [{"ref": "LDR1", "t": 0.75, "lux": 1}]}, livre=True, isolada=True)
        self.assertEqual(p["codigo"], 0, p)
        volts = p["entradas"]["luz"][0]["volts"]
        self.assertEqual(p["pinos"]["GPIO34"]["volts"], [[750.0, volts]])
        lidos = [int(txt.split()[1]) for _, txt in p["serial"]]
        self.assertAlmostEqual(lidos[-1] / 1000, volts, delta=0.01)


if __name__ == "__main__":
    unittest.main()
