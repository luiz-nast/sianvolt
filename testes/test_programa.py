"""o programa da placa no gêmeo (programa.py): pinos.py, a cópia pro laboratório, o programa.json e o confere.json"""
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

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
# o mesmo divisor do LDR com um LED no GPIO25 (pino 8) pelo R3 de 130 Ω: uma luz noturna pequena
LUZ = LDR + """peca R3 resistor_axial 12 54 130
peca D1 led_5mm 4 44
liga U1.8 R3.1
liga R3.2 D1.1
liga D1.2 GND
"""
# o LDR ligado do lado errado: 3V3 → LDR → GPIO34 → 22 kΩ → GND (no claro a tensão SOBE)
LUZ_TROCADA = LUZ.replace("liga U1.16 R1.1\nliga R1.2 U1.4\nliga U1.4 LDR1.1\nliga LDR1.2 GND\n",
                          "liga U1.16 LDR1.2\nliga LDR1.1 U1.4\nliga U1.4 R1.2\nliga R1.1 GND\n")
# a luz noturna em 3 s: acende devagar quando escurece e apaga quando clareia (os limites do placas/luz_noturna)
MINI_LUZ = """from machine import ADC, PWM, Pin
import time
from pinos import D1, LDR1
olho = ADC(Pin(LDR1), atten=ADC.ATTN_11DB)
luz = PWM(Pin(D1), freq=1000, duty_u16=0)
escuro, brilho = False, 0.0
for i in range(150):
    mv = olho.read_uv() // 1000
    if not escuro and mv > 1205:
        escuro = True
        print("escureceu", mv)
    elif escuro and mv < 827:
        escuro = False
        print("clareou", mv)
    alvo = 0.6 if escuro else 0.0
    brilho = min(alvo, brilho + 0.06) if brilho < alvo else max(alvo, brilho - 0.06)
    luz.duty_u16(int(brilho * brilho * 65535))
    time.sleep_ms(20)
"""
ROTEIRO_LUZ = {"tempo": 3, "entradas": [{"t": 0, "luz": "LDR1", "lux": 100}, {"t": 1, "luz": "LDR1", "lux": 1},
                                        {"t": 2, "luz": "LDR1", "lux": 100}],
               "confere": [{"t": 0.9, "pwm": "GPIO25", "duty": [0, 0]}, {"serial": "escureceu", "desde": 1, "ate": 1.1},
                           {"t": 1.9, "pwm": "GPIO25", "duty": [0.35, 0.37]},
                           {"serial": "clareou", "desde": 2, "ate": 2.1}, {"t": 2.9, "pwm": "GPIO25", "duty": [0, 0]}]}
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

    def test_evento_led_com_os_numeros(self):
        """o laboratório novo manda o brilho como número (o evento 'led'): ele vale, sem o arredondamento do texto"""
        pasta = self.placa((DADOS / "pisca.txt").read_text())
        led = dict(ref="D1", i_med=0.005926, i_max=0.005926, luz=0.5926, aceso=True, queima=False,
                   texto="D1 aceso, 5,9 mA, luz 59% do anúncio")
        linhas = [self.evento(0, "led", **dict(led, i_med=0.0, i_max=0.0, luz=0.0, aceso=False, texto="D1 apagado")),
                  self.evento(5, "led", **led), self.evento(6, "led", **dict(led, i_med=0.035, queima=True)),
                  self.evento(7, "aviso", texto="D1 aceso, 5,9 mA, luz 59% do anúncio", codigo="led"),
                  self.evento(8, "led", ref="D1", texto="D1 brilha de um jeito novo")]
        p = programa.normalizar(linhas, pasta)
        self.assertEqual(p["leds"]["D1"], [[0, 0.0, 0.0, False], [5, 0.5926, 5.926, False], [6, 0.5926, 35.0, True]])
        self.assertEqual(p["avisos"], [[8, "led", "D1 brilha de um jeito novo"]])   # sem os números, o texto não some
        self.assertNotIn([7, "led", "D1 aceso, 5,9 mA, luz 59% do anúncio"], p["avisos"])   # com os números, o texto sobra

    def test_led_apagado_com_numeros(self):
        """o LED aceso só pelo pull-up (35 µA, 0,35% da luz): o gêmeo diz apagado (aceso False), então ele entra com
        0 e 0, como no texto, e ninguém conta como aceso. Sem o aceso (um laboratório de outro formato), vale o texto"""
        pasta = self.placa((DADOS / "pisca.txt").read_text())
        fio = dict(ref="D1", i_med=3.5e-05, i_max=3.5e-05, luz=0.0035, aceso=False, queima=False, texto="D1 apagado")
        p = programa.normalizar([self.evento(0.005, "led", **fio)], pasta)
        self.assertEqual(p["leds"]["D1"], [[0.005, 0.0, 0.0, False]])
        self.assertFalse(programa.aceso(p, "D1", 1000))
        sem = {k: v for k, v in fio.items() if k != "aceso"}
        p = programa.normalizar([self.evento(1, "led", **sem), self.evento(2, "led", **dict(
            sem, i_med=0.005926, luz=0.5926, texto="D1 aceso, 5,9 mA, luz 59% do anúncio"))], pasta)
        self.assertEqual((p["leds"]["D1"], p["avisos"]), ([[1, 0.0, 0.0, False], [2, 0.59, 5.9, False]], []))

    def test_aviso_de_texto_que_nao_entendo_nao_some(self):
        pasta = self.placa((DADOS / "pisca.txt").read_text())
        p = programa.normalizar([self.evento(6, "aviso", texto="D1 brilha de um jeito novo", codigo="led")], pasta)
        self.assertEqual((p["leds"], p["avisos"]), ({}, [[6, "led", "D1 brilha de um jeito novo"]]))

    def test_luz_em_lux_pega_os_volts_do_gemeo(self):
        """a luz que foi em lux: os volts de entradas.luz são os que o gêmeo pôs no pino do LDR naquela hora"""
        pasta = self.placa(LDR, pecas=["C10081"])
        entradas = {"apertos": [], "luz": [{"ref": "LDR1", "t": 0.0, "lux": 100, "volts": None, "origem": "roteiro"},
                                           {"ref": "LDR1", "t": 1500.0, "lux": 1, "volts": None, "origem": "app"}]}
        linhas = [self.evento(0, "luz", ref="LDR1", lux=100.0, origem="roteiro"),
                  self.evento(0, "adc", pino="GPIO34", volts=0.3763, origem="circuito"),
                  self.evento(1500, "luz", ref="LDR1", lux=1.0, origem="roteiro"),
                  self.evento(1500, "adc", pino="GPIO34", volts=2.3751, origem="circuito", nome="POT")]
        p = programa.normalizar(linhas, pasta, entradas=entradas)
        self.assertEqual([x["volts"] for x in p["entradas"]["luz"]], [0.3763, 2.3751])
        self.assertEqual(p["pinos"]["GPIO34"]["volts"], [[0, 0.3763], [1500, 2.3751]])
        self.assertTrue(any("entra em lux no LDR" in x for x in p["pendentes"]))
        antigo = programa.normalizar([], pasta, entradas={"apertos": [], "luz": [dict(entradas["luz"][0], volts=0.3763)]})
        self.assertTrue(any("entra como volts no pino do LDR" in x for x in antigo["pendentes"]))
        # a luz foi em lux, mas a rodada parou antes de ela mudar: o pendente continua o do lux, e os volts ficam None
        quebrou = programa.normalizar([self.evento(0, "erro", texto="ValueError: quebrei")], pasta, entradas={
            "apertos": [], "luz": [dict(x) for x in entradas["luz"]]})
        self.assertEqual([x["volts"] for x in quebrou["entradas"]["luz"]], [None, None])
        self.assertTrue(any("entra em lux no LDR" in x for x in quebrou["pendentes"]))
        self.assertFalse(any("entra como volts" in x for x in quebrou["pendentes"]))

    def test_aviso_do_ldr_sem_luz_em_texto_de_gente(self):
        """o laboratório avisa o LDR que começa sem luz com a dica do roteiro dele (um JSON): no programa.json vira
        texto pro Luiz, com o nome do bloco e o lugar onde a luz muda (o app no livre, o roteiro.json no teste)"""
        pasta = self.placa(LDR, pecas=["C10081"])
        lab = ('LDR1 começa com 10 lux (o LDR do meio: 12,6 kΩ); o roteiro muda a luz com {"t": 5, "luz": "LDR1", '
               '"lux": 1}')
        livre = programa.normalizar([self.evento(0, "aviso", texto=lab, codigo="luz")], pasta, livre=True)
        self.assertEqual(livre["avisos"], [[0, "luz", "LDR1 (olho de luz) começa com 10 lux (o LDR do meio: 12,6 kΩ) "
                                                      "e fica assim até o app mudar a luz dele"]])
        teste = programa.normalizar([self.evento(0, "aviso", texto=lab, codigo="luz")], pasta)
        self.assertTrue(teste["avisos"][0][2].endswith("até uma luz do codigo/roteiro.json mudar"))
        outro = programa.normalizar([self.evento(0, "aviso", texto="um aviso de luz novo", codigo="luz")], pasta)
        self.assertEqual(outro["avisos"], [[0, "luz", "um aviso de luz novo"]])   # o que não entendo vai como veio

    def test_luz_padrao_vira_aviso_com_a_tensao(self):
        """a luz padrão que o preparar mandou (o LDR que ninguém acendeu em 0 s) ganha o aviso que o gêmeo dava, com a
        tensão que ele pôs no pino; sem ela (a rodada parou antes), o aviso fica sem a tensão"""
        pasta = self.placa(LDR, pecas=["C10081"])
        luz = [{"ref": "LDR1", "t": 0.0, "lux": 10, "volts": None, "origem": "padrão"},
               {"ref": "LDR1", "t": 900.0, "lux": 1, "volts": None, "origem": "app"}]
        linhas = [self.evento(0, "aviso", texto="rodando no MicroPython", codigo="gemeo"),
                  self.evento(0, "adc", pino="GPIO34", volts=1.2047, origem="circuito"),
                  self.evento(5, "aviso", texto="outro aviso", codigo="pull"),
                  self.evento(900, "adc", pino="GPIO34", volts=2.3751, origem="circuito")]
        p = programa.normalizar(linhas, pasta, livre=True, entradas={"apertos": [], "luz": [dict(x) for x in luz]})
        self.assertEqual(p["pinos"]["GPIO34"]["volts"], [[0, 1.2047], [900, 2.3751]])
        self.assertEqual([x["volts"] for x in p["entradas"]["luz"]], [1.2047, 2.3751])
        self.assertEqual([a[1] for a in p["avisos"]], ["gemeo", "luz", "pull"], "o da luz fica em 0 s, na ordem")
        self.assertEqual(p["avisos"][1], [0.0, "luz", "LDR1 (olho de luz) começa com 10 lux (o padrão: o ponto da tabela "
                                                      "do datasheet; com o LDR do meio, 1,205 V no GPIO34) e fica assim "
                                                      "até o app mudar a luz dele"])
        teste = programa.normalizar([], pasta, entradas={"apertos": [], "luz": [dict(luz[0])]})
        self.assertEqual(teste["avisos"], [[0.0, "luz", "LDR1 (olho de luz) começa com 10 lux (o padrão: o ponto da "
                                                        "tabela do datasheet; com o LDR do meio) e fica assim até uma luz "
                                                        "do codigo/roteiro.json mudar"]])

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

    def test_conferencia_da_serial_com_desde(self):
        """o 'desde' da conferência 'serial' (a linha tem que sair depois dele) entra no texto, como o laboratório escreve"""
        pasta = self.placa((DADOS / "pisca.txt").read_text())
        confere = [{"serial": "clareou", "desde": 15, "ate": 15.5}, {"serial": "x", "desde": 1}, {"serial": "y", "ate": 2}]
        conf = self.evento(2000, "conferencias", ok=2, falhas=["serial com 'x' depois de 1,000 s: nada depois de 1,000 s "
                                                               "(a última linha saiu em 0,500 s)"])
        p = programa.normalizar([conf], pasta, confere=confere)
        self.assertEqual(p["conferencias"]["ok"], ["serial com 'clareou' depois de 15,000 s até 15,500 s",
                                                   "serial com 'y' até 2,000 s"])

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


def sem_comentario(entradas):
    """as entradas do roteiro.json sem o '_' (o comentário que o preparar escreve pra quem abrir a cópia)"""
    return [{k: v for k, v in x.items() if k != "_"} for x in entradas]


class Preparar(Temporarias):
    def ldr(self, roteiro=None, gemeo="", **k):
        arquivos = {"codigo/main.py": "print('oi')\n", "codigo/outro.py": "X = 1\n", "codigo/notas.txt": "não vai"}
        if roteiro is not None:
            arquivos["codigo/roteiro.json"] = roteiro
        if gemeo:
            arquivos["codigo/gemeo.roteiro"] = gemeo
        return self.placa(LDR, pecas=["C10081"], arquivos=arquivos, **k)

    def test_luz_vira_volts_no_laboratorio_antigo(self):
        """o laboratório que não conhece a luz (lux=False): ela vira a tensão do divisor no GPIO do LDR, pela nossa
        conta, e nunca uma linha de lux"""
        pasta = self.ldr({"tempo": 3, "entradas": [{"t": 0, "luz": "LDR1", "lux": 100, "_": "quarto aceso"}],
                          "confere": [{"serial": "oi"}]}, gemeo="# só comentário\n")
        copia, usadas = programa.preparar(pasta, {"luz": [{"ref": "LDR1", "t": 2, "lux": 1}]}, lux=False)
        rot = json.loads((copia / "roteiro.json").read_text())
        e = catalogo.conferido("C10081")["eletrica"]
        um, cem = (circuito.divisor_do_ldr(e, 22000, 3.3, lux) for lux in (1, 100))
        v100, v1 = rot["entradas"]
        self.assertEqual((v100["t"], v100["pino"], v1["t"], v1["pino"]), (0, "GPIO34", 2, "GPIO34"))
        self.assertAlmostEqual(v1["volts"], um, delta=1e-3)
        self.assertAlmostEqual(v100["volts"], cem, delta=1e-3)
        self.assertEqual(rot["confere"], [{"serial": "oi"}])
        self.assertNotIn("lux", (copia / "gemeo.roteiro").read_text().lower())
        self.assertNotIn("lux", json.dumps([{k: v for k, v in x.items() if k != "_"} for x in rot["entradas"]]))
        self.assertEqual(usadas["luz"], [{"ref": "LDR1", "t": 0.0, "lux": 100, "volts": v100["volts"], "origem": "roteiro"},
                                         {"ref": "LDR1", "t": 2000.0, "lux": 1, "volts": v1["volts"], "origem": "app"}])
        self.assertEqual(sorted(a.name for a in copia.iterdir()), ["gemeo.roteiro", "main.py", "outro.py", "roteiro.json"])
        self.assertEqual(copia.parent, pasta.resolve() / "saida" / "programa")
        self.assertRegex(copia.name, r"^sianvolt_esp32_[0-9a-f]{8}$")

    def test_luz_vai_em_lux_no_laboratorio_novo(self):
        """o laboratório que conhece a luz (lux=True): ela vai em lux pro roteiro.json, e os volts ficam pro gêmeo"""
        pasta = self.ldr({"tempo": 3, "entradas": [{"t": 0, "luz": "LDR1", "lux": 100, "_": "quarto aceso"},
                                                   {"t": 0.5, "serial": "oi\n"}]})
        copia, usadas = programa.preparar(pasta, {"luz": [{"ref": "LDR1", "t": 2, "lux": 1}]}, lux=True)
        rot = json.loads((copia / "roteiro.json").read_text())
        self.assertEqual([{k: v for k, v in x.items() if k != "_"} for x in rot["entradas"]],
                         [{"t": 0.5, "serial": "oi\n"}, {"t": 0.0, "luz": "LDR1", "lux": 100},
                          {"t": 2.0, "luz": "LDR1", "lux": 1}])
        self.assertFalse(any("volts" in x for x in rot["entradas"]))
        self.assertEqual(usadas["luz"], [{"ref": "LDR1", "t": 0.0, "lux": 100, "volts": None, "origem": "roteiro"},
                                         {"ref": "LDR1", "t": 2000.0, "lux": 1, "volts": None, "origem": "app"}])
        pasta = self.ldr({"entradas": [{"t": 1, "luz": "SW1", "lux": 1}]})
        with self.assertRaisesRegex(ValueError, "^SW1 não é um olho de luz ligado num GPIO do ESP32$"):
            programa.preparar(pasta, lux=True)
        solto = self.placa(LDR.replace("liga U1.4 LDR1.1\n", ""), "solto", pecas=["C10081"],
                           arquivos={"codigo/main.py": "print('oi')\n"})   # o LDR que não liga no ESP32
        with self.assertRaisesRegex(ValueError, "LDR1 não é um olho de luz ligado num GPIO"):
            programa.preparar(solto, {"luz": [{"ref": "LDR1", "t": 1, "lux": 1}]}, lux=True)

    def test_livre_so_com_o_que_veio_do_app(self):
        """no livre (o ▶ do app) só valem as entradas do app: os apertos do gemeo.roteiro e as entradas do roteiro.json
        da placa ficam de fora (o I2C e o wifi, que são o mundo em volta, ficam); sem nada do app, a placa roda sozinha"""
        gemeo = ("# os apertos do roteiro de teste\n1 s aperta SW1\n1,2 s solta SW1\nde 2 s a 2,5 s aperta SW1\n"
                 "em 3 s GPIO14 = 0\ni2c 0x48 0x00 = 0x19\n4 s i2c 0x48 0x00 = 0x1E\nwifi falha\n")
        pasta = self.ldr({"tempo": 6, "entradas": [{"t": 0, "luz": "LDR1", "lux": 100}, {"t": 1, "serial": "oi\n"},
                                                   {"t": 2, "pino": "GPIO14", "valor": 0}],
                          "confere": [{"serial": "oi"}]}, gemeo=gemeo)
        volts = programa.volts_da_luz(programa.modelo_da_placa(pasta), "LDR1", circuito.LUX_PADRAO)[1]
        for lux in (True, False):
            with self.subTest(lux=lux):   # do roteiro.json, nada: o LDR fica só com a luz padrão, como sem o roteiro
                padrao = {"ref": "LDR1", "t": 0.0, "lux": circuito.LUX_PADRAO, "volts": None if lux else round(volts, 4),
                          "origem": programa.PADRAO}
                copia, usadas = programa.preparar(pasta, livre=True, lux=lux)
                rot = json.loads((copia / "roteiro.json").read_text())
                self.assertEqual((rot["tempo"], sem_comentario(rot["entradas"])),
                                 (6, [{"t": 0.0, "luz": "LDR1", "lux": circuito.LUX_PADRAO} if lux else
                                      {"t": 0.0, "pino": "GPIO34", "volts": round(volts, 4)}]))
                ambiente = (copia / "gemeo.roteiro").read_text()
                self.assertEqual(ambiente, "# os apertos do roteiro de teste\ni2c 0x48 0x00 = 0x19\n"
                                           "4 s i2c 0x48 0x00 = 0x1E\nwifi falha\n")
                self.assertEqual(usadas, {"apertos": [], "luz": [padrao]})
                copia, usadas = programa.preparar(pasta, {"apertos": [{"ref": "SW1", "de": 0.5, "ate": 0.7}]},
                                                  livre=True, lux=lux)
                self.assertEqual(usadas, {"apertos": [{"ref": "SW1", "de": 500.0, "ate": 700.0, "origem": "app"}],
                                          "luz": [padrao]})
                self.assertEqual([x for x in (copia / "gemeo.roteiro").read_text().splitlines() if "aperta" in x],
                                 ["de 0,5 s a 0,7 s aperta SW1   # do app"])
        copia, usadas = programa.preparar(pasta, lux=True)   # fora do livre, o roteiro de teste continua inteiro
        self.assertEqual([a["de"] for a in usadas["apertos"]], [1000.0, 2000.0])
        self.assertEqual(len(json.loads((copia / "roteiro.json").read_text())["entradas"]), 3)
        self.assertIn("em 3 s GPIO14 = 0", (copia / "gemeo.roteiro").read_text())

    def test_luz_padrao_so_no_ldr_sem_luz_em_0_s(self):
        """o LDR ligado num GPIO que ninguém acende em 0 s ganha a luz padrão (a do circuito.LUX_PADRAO, que o gêmeo
        já usava calado): dita no roteiro, o gêmeo diz a tensão do pino desde 0 s. Com luz em 0 s (do roteiro.json
        ou do app), nada muda; o LDR solto e a placa sem LDR não ganham nada"""
        def luzes(pasta, entradas=None, **k):
            copia, usadas = programa.preparar(pasta, entradas, lux=True, **k)
            rot = sem_comentario(json.loads((copia / "roteiro.json").read_text())["entradas"])
            return [(x["t"], x["origem"]) for x in usadas["luz"]], [(x["t"], x["lux"]) for x in rot if "luz" in x]
        com_0 = self.ldr({"tempo": 3, "entradas": [{"t": 0, "luz": "LDR1", "lux": 100}]})
        self.assertEqual(luzes(com_0), ([(0.0, "roteiro")], [(0, 100)]))
        self.assertEqual(luzes(com_0, livre=True), ([(0.0, "padrão")], [(0.0, 10)]), "no livre o roteiro.json não vale")
        self.assertEqual(luzes(com_0, {"luz": [{"ref": "LDR1", "t": 0, "lux": 1}]}, livre=True), ([(0.0, "app")], [(0, 1)]))
        self.assertEqual(luzes(com_0, {"luz": [{"ref": "LDR1", "t": 2, "lux": 1}]}, livre=True),
                         ([(2000.0, "app"), (0.0, "padrão")], [(2, 1), (0.0, 10)]))
        sem_0 = self.ldr({"tempo": 3, "entradas": [{"t": 1, "luz": "LDR1", "lux": 100}]})
        self.assertEqual(luzes(sem_0), ([(1000.0, "roteiro"), (0.0, "padrão")], [(1, 100), (0.0, 10)]))
        solto = self.placa(LDR.replace("liga U1.4 LDR1.1\n", ""), "solto", pecas=["C10081"],
                           arquivos={"codigo/main.py": "print('oi')\n"})
        self.assertEqual(luzes(solto), ([], []), "o LDR que não liga no ESP32: o programa não lê, nada de luz padrão")
        sem_ldr = self.placa(BOA, "boa", arquivos={"codigo/main.py": "print('oi')\n"})
        self.assertEqual(luzes(sem_ldr), ([], []))

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
        copia, _ = programa.preparar(pasta, isolada=True, lux=True)
        self.assertEqual(copia.name, f"{programa.nome_da_copia(pasta)}_{os.getpid()}")
        self.assertEqual(sem_comentario(json.loads((copia / "roteiro.json").read_text())["entradas"]),
                         [{"t": 0.0, "luz": "LDR1", "lux": circuito.LUX_PADRAO}], "só a luz padrão do LDR")

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
        ok, txt = self.um({"tipo": "leds_da_serial", "regex": r"deu (\d)", "mapa": {"2": ["D1", "D7"]}})
        self.assertFalse(ok)   # a face que a serial disse e o mapa não tem: falha, não passa calada
        self.assertIn("em 2,500 s a serial disse 'deu 1', e a face '1' não está no mapa", txt)

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
        # a conta é do ÚLTIMO evento antes da linha: o 'já!' de 3000 ms, e não o primeiro, de 1000 ms
        prog = prog_de_ensaio()
        prog["serial"].append([3400.0, "J2 ganhou em 400 ms"])
        r = programa.conferir(prog, {"confere": [item]})
        self.assertEqual(r["falhas"], [])
        # o pino escrito em 1 de novo não subiu outra vez: não é evento novo
        prog["pinos"]["GPIO25"]["nivel"].insert(2, [1200.0, 1])
        self.assertEqual(programa.instantes(prog, "GPIO25 sobe"), [1000.0, 3000.0])
        self.assertEqual(programa.conferir(prog, {"confere": [item]})["falhas"], [])

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
        ok, txt = self.um({**item, "min": 0.1, "max": 0.2})   # acima do max também falha (0,36 > 0,2)
        self.assertFalse(ok)
        self.assertIn("em 3,000 s o duty era 0,36", txt)

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


LAB_ANTIGO = {   # o que um laboratório sem L1 e L2 tem (o de antes da rodada 6), só o que o recursos_do_lab lê
    "lab.py": "",
    "nucleo/__init__.py": "",
    "nucleo/contrato.py": "TIPOS = {'pino': {}, 'aviso': {}, 'fim': {}}\n",
    "nucleo/roteiro.py": ("from .contrato import TIPOS\n\n\ndef validar(dados):\n    for e in dados.get('entradas', []):\n"
                          "        if set(e) - {'t', 'pino', 'valor', 'volts', 'serial'}:\n"
                          "            raise ValueError('não conheço')\n    return dados\n"),
    "motores/gemeo/motor/roteiro.py": ("class Roteiro:\n    def __init__(self, fim_us, entradas=(), extra=''):\n"
                                       "        self.eventos = [(e['t_ms'], {'tipo': 'externo', 'gpio': e['pino']}) "
                                       "for e in entradas]\n")}


class ApagarSoACopia(unittest.TestCase):
    """o apagar dos testes apaga o mkdtemp da cópia, e nunca a pasta temporária do sistema: o lab() daqui passava o
    mkdtemp no lugar da cópia, e o apagar (que sobe um nível) apagava o TMPDIR inteiro (o /tmp, sem TMPDIR)"""

    def test_nao_apaga_a_pasta_temporaria(self):
        caixa = Path(tempfile.mkdtemp(prefix="sianvolt-caixa-"))   # o 'TMPDIR' do teste: se a trava falhar, só ela vai
        self.addCleanup(shutil.rmtree, caixa, True)
        (caixa / "de_outro_programa.txt").write_text("não é dos testes")
        with mock.patch.object(tempfile, "tempdir", str(caixa)):
            pasta = Path(tempfile.mkdtemp(prefix="sianvolt-teste-"))
            for errado in (pasta, caixa / "solta"):   # o mkdtemp no lugar da cópia; algo direto no TMPDIR
                with self.subTest(errado=errado.name), self.assertRaisesRegex(ValueError, "não é um mkdtemp dos testes"):
                    apagar(errado)
            self.assertTrue((caixa / "de_outro_programa.txt").is_file() and pasta.is_dir())
            apagar(pasta / "laboratorio")   # a cópia: vai o mkdtemp dela, e só ele
        self.assertFalse(pasta.exists())
        self.assertTrue((caixa / "de_outro_programa.txt").is_file())


class RecursosDoLab(Temporarias):
    """o programa.py pergunta pro laboratório o que ele sabe (sem supor): o brilho em número e a luz em lux"""

    def lab(self, arquivos):
        pasta = Path(tempfile.mkdtemp(prefix="sianvolt-teste-")) / "laboratorio"
        self.addCleanup(apagar, pasta)   # o apagar sobe um nível sozinho: apaga a pasta do mkdtemp, não o TMPDIR
        for nome, texto in arquivos.items():
            (pasta / nome).parent.mkdir(parents=True, exist_ok=True)
            (pasta / nome).write_text(texto)
        return pasta / "lab.py"

    def com_lab(self, lab):
        with mock.patch.object(programa, "LAB", lab):
            return programa.recursos_do_lab()

    def test_laboratorio_antigo_e_nenhum(self):
        antigo = self.lab(LAB_ANTIGO)
        self.assertEqual(self.com_lab(antigo), frozenset())
        self.assertFalse(list(antigo.parent.rglob("*.pyc")))   # e nada de .pyc escrito no laboratório
        self.assertEqual(self.com_lab(Path(self.lab({})).parent / "nao_tem" / "lab.py"), frozenset())
        meio = dict(LAB_ANTIGO, **{"nucleo/contrato.py": "TIPOS = {'pino': {}, 'led': {}}\n"})   # só o L1
        self.assertEqual(self.com_lab(self.lab(meio)), frozenset({"led"}))
        quebrado = dict(LAB_ANTIGO, **{"nucleo/roteiro.py": "isto não é python ("})
        self.assertEqual(self.com_lab(self.lab(quebrado)), frozenset())

    def test_le_de_novo_quando_o_laboratorio_muda(self):
        lab = self.lab(LAB_ANTIGO)
        self.assertEqual(self.com_lab(lab), frozenset())
        contrato = lab.parent / "nucleo" / "contrato.py"
        contrato.write_text("TIPOS = {'led': {}}\n")
        os.utime(contrato, ns=(contrato.stat().st_atime_ns, contrato.stat().st_mtime_ns + 10**9))
        self.assertEqual(self.com_lab(lab), frozenset({"led"}))

    def test_varias_threads_ao_mesmo_tempo(self):
        """o app é um ThreadingHTTPServer: perguntas juntas recebem a mesma resposta, o sys.dont_write_bytecode volta
        como estava e nada de .pyc no laboratório (o sys.modules e o dont_write_bytecode são do processo inteiro)"""
        lab = self.lab(dict(LAB_ANTIGO, **{"nucleo/contrato.py": "TIPOS = {'pino': {}, 'led': {}}\n"}))   # só o L1
        self.addCleanup(programa._RECURSOS.clear)
        respostas, barreira = [], threading.Barrier(6)

        def pergunta():
            barreira.wait()
            respostas.append(programa.recursos_do_lab())
        with mock.patch.object(programa, "LAB", lab), mock.patch.object(sys, "dont_write_bytecode", False):
            for _ in range(25):
                programa._RECURSOS.clear()   # cada rodada pergunta de novo, as 6 juntas
                linhas = [threading.Thread(target=pergunta) for _ in range(6)]
                for x in linhas:
                    x.start()
                for x in linhas:
                    x.join()
                self.assertFalse(sys.dont_write_bytecode)
        self.assertEqual(set(respostas), {frozenset({"led"})})
        self.assertEqual(len(respostas), 150)
        self.assertFalse(list(lab.parent.rglob("*.pyc")))

    @unittest.skipUnless(programa.LAB.is_file(), "sem o laboratorio/ (o clone limpo não tem)")
    def test_o_laboratorio_daqui(self):
        self.assertEqual(programa.recursos_do_lab(), frozenset({"led", "luz"}))


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

    def test_livre_sem_os_apertos_da_placa(self):
        """o ▶ do app (livre) sem entradas: a placa roda sozinha, sem os apertos do roteiro de teste; com um aperto do
        app, só ele. Fora do livre, o roteiro de teste aperta como sempre"""
        main = ("from machine import Pin\nimport time\nfrom pinos import SW1\nb = Pin(SW1, Pin.IN, Pin.PULL_UP)\n"
                "antes = 1\nfor i in range(150):\n    v = b.value()\n    if v != antes:\n        print('botao', v)\n"
                "        antes = v\n    time.sleep_ms(10)\n")
        pasta = self.placa(BOA, arquivos={"codigo/main.py": main, "codigo/gemeo.roteiro": "de 0,2 s a 0,3 s aperta SW1\n",
                                          "codigo/roteiro.json": {"tempo": 1.5, "entradas": [{"t": 1, "serial": "oi\n"}]}})
        sozinha = programa.rodar(pasta, livre=True, isolada=True)
        self.assertEqual((sozinha["codigo"], sozinha["serial"]), (0, []))
        self.assertEqual(sozinha["entradas"], {"apertos": [], "luz": []})
        app = programa.rodar(pasta, {"apertos": [{"ref": "SW1", "de": 0.5, "ate": 0.7}]}, livre=True, isolada=True)
        self.assertEqual([txt for _, txt in app["serial"]], ["botao 0", "botao 1"])
        self.assertAlmostEqual(app["serial"][0][0], 500, delta=15)
        self.assertEqual(app["entradas"]["apertos"], [{"ref": "SW1", "de": 500.0, "ate": 700.0, "origem": "app"}])
        teste = programa.rodar(pasta, isolada=True)
        self.assertAlmostEqual(teste["serial"][0][0], 200, delta=15)
        self.assertEqual(teste["entradas"]["apertos"], [{"ref": "SW1", "de": 200.0, "ate": 300.0, "origem": "roteiro"}])

    def test_luz_no_divisor(self):
        main = "from machine import ADC, Pin\nimport time\nfrom pinos import LDR1\nadc = ADC(Pin(LDR1))\n" \
               "adc.atten(ADC.ATTN_11DB)\nfor i in range(4):\n    print('mv', adc.read_uv() // 1000)\n    time.sleep_ms(500)\n"
        pasta = self.placa(LDR, pecas=["C10081"], arquivos={"codigo/main.py": main,
                                                             "codigo/roteiro.json": {"tempo": 2}})
        p = programa.rodar(pasta, {"luz": [{"ref": "LDR1", "t": 0.75, "lux": 1}]}, livre=True, isolada=True)
        self.assertEqual(p["codigo"], 0, p)
        do_app, padrao = (next(x for x in p["entradas"]["luz"] if x["origem"] == o) for o in ("app", programa.PADRAO))
        # antes da luz do app, o LDR está na luz padrão (10 lux): o pino tem tensão desde 0 s, e não '?' até 0,75 s
        self.assertEqual((padrao["t"], padrao["lux"]), (0.0, circuito.LUX_PADRAO))
        self.assertEqual(p["pinos"]["GPIO34"]["volts"], [[0.0, padrao["volts"]], [750.0, do_app["volts"]]])
        conta = circuito.divisor_do_ldr(catalogo.conferido("C10081")["eletrica"], 22000, 3.3, circuito.LUX_PADRAO)
        self.assertAlmostEqual(padrao["volts"], conta, delta=0.001)   # o gêmeo leu o divisor de verdade
        lidos = [int(txt.split()[1]) for _, txt in p["serial"]]
        self.assertAlmostEqual(lidos[0] / 1000, padrao["volts"], delta=0.01)   # a serial e o pino contam o mesmo
        self.assertAlmostEqual(lidos[-1] / 1000, do_app["volts"], delta=0.01)
        self.assertIn([0.0, "luz", f"LDR1 (olho de luz) começa com 10 lux (o padrão: o ponto da tabela do datasheet; "
                                   f"com o LDR do meio, {programa.num(padrao['volts'], 3)} V no GPIO34) e fica assim até o "
                                   "app mudar a luz dele"], p["avisos"])


def lab_antigo(rodar_lab):
    """o rodar_lab como o laboratório antigo respondia: o brilho dos LEDs só no texto do aviso 'led', uma vez por
    texto (o texto do evento 'led' é o mesmo de antes)"""
    def rodar(copia, placa_txt):
        linhas, codigo, problema = rodar_lab(copia, placa_txt)
        saida, visto = [], {}
        for x in linhas:
            ev = json.loads(x)
            if ev["tipo"] == "led":
                if visto.get(ev["ref"]) == ev["texto"]:
                    continue
                visto[ev["ref"]] = ev["texto"]
                ev = {"t_ms": ev["t_ms"], "tipo": "aviso", "texto": ev["texto"], "codigo": "led"}
            saida.append(json.dumps(ev, ensure_ascii=False))
        return saida, codigo, problema
    return rodar


@unittest.skipUnless(TEM_LAB, "sem o laboratório e o MicroPython do PC (laboratorio/ não está no clone limpo)")
class DoisCaminhos(Temporarias):
    """a luz pelo gêmeo (lux, o brilho em número) e pelo caminho antigo (volts por fora, o brilho no texto) contam a
    mesma história no programa.json"""

    def pelos_dois(self, pasta, **k):
        """-> (programa.json pelo caminho antigo, pelo novo)"""
        with mock.patch.object(programa, "recursos_do_lab", lambda: frozenset()), \
                mock.patch.object(programa, "rodar_lab", lab_antigo(programa.rodar_lab)):
            antigo = programa.rodar(pasta, isolada=True, **k)
        self.assertEqual(programa.recursos_do_lab(), frozenset({"led", "luz"}))
        return antigo, programa.rodar(pasta, isolada=True, **k)

    def mesmas_decisoes(self, a, b):
        """o mesmo código e as mesmas conferências; a serial, os modos, os níveis e o PWM iguais nos mesmos instantes
        (± 1 ms); os volts no pino do LDR iguais (± 1 mV); e cada LED com a mesma luz e corrente em todo instante
        dos dois (o texto antigo arredonda em 1% e 0,1 mA), aceso ou apagado igual (menos o 'meia luz' que o texto
        antigo arredonda pra 0% e 0,0 mA: no caminho antigo ele some, e o gêmeo diz que está aceso)"""
        self.assertEqual((a["codigo"], a["erro"], a["tempo_ms"], a["conferencias"]),
                         (b["codigo"], b["erro"], b["tempo_ms"], b["conferencias"]))

        def iguais(x, y, folga):
            self.assertEqual(len(x), len(y), (x, y))
            for p, q in zip(x, y):
                self.assertAlmostEqual(p[0], q[0], delta=1)
                for u, v in zip(p[1:], q[1:]):
                    if isinstance(u, (int, float)) and isinstance(v, (int, float)):
                        self.assertAlmostEqual(u, v, delta=folga)
                    else:
                        self.assertEqual(u, v)
        iguais(a["serial"], b["serial"], 0)
        self.assertEqual(list(a["pinos"]), list(b["pinos"]))
        for g in a["pinos"]:
            self.assertEqual((a["pinos"][g]["quem"], a["pinos"][g]["nome"]), (b["pinos"][g]["quem"], b["pinos"][g]["nome"]))
            for k in ("modo", "nivel", "pwm"):
                iguais(a["pinos"][g][k], b["pinos"][g][k], 0)
            iguais(a["pinos"][g]["volts"], b["pinos"][g]["volts"], 0.001)
        self.assertEqual(sorted(a["leds"]), sorted(b["leds"]))
        for ref in a["leds"]:
            for t in sorted({x[0] for x in a["leds"][ref] + b["leds"][ref]}):
                x, y = programa.no_instante(a["leds"][ref], t), programa.no_instante(b["leds"][ref], t)
                self.assertAlmostEqual(x[1], y[1], delta=0.0051, msg=f"luz do {ref} em {t} ms")
                self.assertAlmostEqual(x[2], y[2], delta=0.051, msg=f"corrente do {ref} em {t} ms")
                self.assertEqual(x[3], y[3])
                if programa.aceso(a, ref, t) != programa.aceso(b, ref, t):   # só o arredondamento do texto antigo:
                    # 'D1 meia luz, 0,0 mA na média (...), luz 0% do anúncio' vira 0 e 0, e o gêmeo diz aceso. O
                    # normalizar guarda o mA em 3 casas: os 0,0499 mA que o texto diz 0,0 chegam aqui como 0,05
                    self.assertTrue(programa.aceso(b, ref, t) and y[1] <= 0.005 and y[2] <= 0.05, f"{ref} em {t} ms")
        iguais([[x["t"], x["ref"], x["lux"], x["volts"], x["origem"]] for x in a["entradas"]["luz"]],
               [[x["t"], x["ref"], x["lux"], x["volts"], x["origem"]] for x in b["entradas"]["luz"]], 0.001)

    def test_luz_noturna_pequena(self):
        pasta = self.placa(LUZ, pecas=["C10081"], arquivos={"codigo/main.py": MINI_LUZ, "codigo/roteiro.json": ROTEIRO_LUZ})
        antigo, novo = self.pelos_dois(pasta, entradas={"luz": [{"ref": "LDR1", "t": 2.5, "lux": 15}]})
        self.mesmas_decisoes(antigo, novo)
        self.assertEqual((novo["codigo"], len(novo["conferencias"]["ok"]), novo["conferencias"]["falhas"]), (0, 5, []))
        self.assertIn("serial com 'escureceu' depois de 1,000 s até 1,100 s", novo["conferencias"]["ok"])
        e = catalogo.conferido("C10081")["eletrica"]
        conta = [circuito.divisor_do_ldr(e, 22000, 3.3, lux) for lux in (100, 1, 100, 15)]
        volts = novo["pinos"]["GPIO34"]["volts"]
        self.assertEqual([t for t, _ in volts], [0.0, 1000.0, 2000.0, 2500.0])
        for (_, v), c in zip(volts, conta):   # o gêmeo leu o divisor de verdade: a conta à mão, ± 1 mV
            self.assertAlmostEqual(v, c, delta=0.001)
        self.assertEqual([x["volts"] for x in novo["entradas"]["luz"]], [v for _, v in volts])
        self.assertEqual([txt for _, txt in novo["serial"]], ["escureceu 2375", "clareou 376"])
        luzes = [x[1] for x in novo["leds"]["D1"]]
        self.assertTrue(any(round(x, 2) != x for x in luzes))   # a luz do gêmeo em número, e não o 59% do texto
        self.assertTrue(all(round(x[1], 2) == x[1] for x in antigo["leds"]["D1"]))
        self.assertTrue(any("entra em lux" in x for x in novo["pendentes"]))
        self.assertTrue(any("entra como volts" in x for x in antigo["pendentes"]))

    @unittest.skipUnless((programa.RAIZ / "placas" / "luz_noturna" / "codigo" / "main.py").is_file(),
                         "sem a placas/luz_noturna (ela fica só na máquina do Luiz)")
    def test_luz_noturna_de_verdade(self):
        """a placa da luz noturna inteira (46 s de quarto, botão e vela), numa cópia"""
        de = programa.RAIZ / "placas" / "luz_noturna"
        pasta = self.placa((de / "placa.txt").read_text(), "luz_noturna")
        shutil.rmtree(pasta / "pecas")
        for nome in ("pecas", "codigo"):
            shutil.copytree(de / nome, pasta / nome)
        shutil.copy(de / "projeto.json", pasta / "projeto.json")
        antigo, novo = self.pelos_dois(pasta)
        self.mesmas_decisoes(antigo, novo)
        self.assertEqual((novo["codigo"], novo["conferencias"]["falhas"]), (0, []))
        self.assertGreater(len(novo["conferencias"]["ok"]), 20)

    def test_led_aceso_so_pelo_pullup(self):
        """o pino do LED que ficou como entrada com pull-up (o erro de quem esqueceu o Pin.OUT): passa um fiozinho de
        corrente (o evento 'led' tem os números), o gêmeo diz 'D1 apagado', e pelos dois caminhos o D1 não acendeu"""
        main = "from machine import Pin\nimport time\nfrom pinos import D1\nPin(D1, Pin.IN, Pin.PULL_UP)\ntime.sleep(1)\n"
        pasta = self.placa(LUZ, pecas=["C10081"], arquivos={"codigo/main.py": main, "codigo/roteiro.json": {"tempo": 1.5}})
        vistos, rodar_lab = [], programa.rodar_lab

        def espia(*a):
            linhas, codigo, problema = rodar_lab(*a)
            vistos.extend(json.loads(x) for x in linhas)
            return linhas, codigo, problema
        with mock.patch.object(programa, "rodar_lab", espia):
            antigo, novo = self.pelos_dois(pasta)
        self.mesmas_decisoes(antigo, novo)
        fio = [e for e in vistos if e["tipo"] == "led" and e["luz"] > 0]
        self.assertTrue(fio and all(not e["aceso"] and e["texto"] == "D1 apagado" and e["i_med"] < 0.0001 for e in fio))
        for p in (antigo, novo):
            self.assertTrue(all(x[1:3] == [0.0, 0.0] for x in p["leds"]["D1"]), p["leds"])
            self.assertFalse(any(programa.aceso(p, "D1", x[0]) for x in p["leds"]["D1"]))

    def test_ldr_ligado_errado_aparece(self):
        """com a luz em lux o pino lê o divisor de verdade: o LDR do lado errado lê o contrário e as conferências
        pegam (no rodar, que é a etapa 8)"""
        pasta = self.placa(LUZ_TROCADA, pecas=["C10081"], arquivos={"codigo/main.py": MINI_LUZ,
                                                                     "codigo/roteiro.json": ROTEIRO_LUZ})
        novo = programa.rodar(pasta, isolada=True)
        self.assertEqual(novo["codigo"], 4)
        self.assertEqual(len(novo["conferencias"]["falhas"]), 4)
        self.assertGreater(novo["pinos"]["GPIO34"]["volts"][0][1], 2.5)   # 100 lux: o pino lê alto, como no escuro
        self.assertEqual(novo["serial"][0][1].split()[0], "escureceu")    # e a luz acende com o quarto aceso

    def test_divisor_ligado_num_gpio(self):
        """o divisor alimentado por um GPIO que o programa liga (economiza o LDR quando não lê): a conta de fora põe
        todo GPIO solto e não vê o divisor ligado, então o caminho antigo erra uma placa certa; o gêmeo acerta"""
        main = MINI_LUZ.replace("from pinos import D1, LDR1\n", "from pinos import D1, LDR1\nPin(27, Pin.OUT, value=1)\n")
        pasta = self.placa(LUZ.replace("liga U1.16 R1.1\n", "liga U1.10 R1.1\n"), pecas=["C10081"],
                           arquivos={"codigo/main.py": main, "codigo/roteiro.json": ROTEIRO_LUZ})
        antigo, novo = self.pelos_dois(pasta)
        self.assertEqual((novo["codigo"], novo["conferencias"]["falhas"]), (0, []))
        self.assertAlmostEqual(novo["pinos"]["GPIO34"]["volts"][1][1], 2.375, delta=0.01)   # 1 lux, pelo GPIO27 em 1
        self.assertEqual((antigo["codigo"], antigo["serial"]), (4, []))   # a conta de fora deu ~0 V: nunca escureceu
        self.assertLess(antigo["entradas"]["luz"][1]["volts"], 0.01)


if __name__ == "__main__":
    unittest.main()
