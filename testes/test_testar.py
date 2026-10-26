"""a bateria de 7 etapas (testar.py) de ponta a ponta: a placa boa passa, e cada defeito para na etapa certa.
No fim, as placas com o ESP32 (DevKit de 30 pinos), montadas pelo teste numa pasta temporária, e a placa de teste
testes/placas/esp32, que tem programa: a 8ª etapa roda ele no gêmeo do laboratório"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

from apoio import PLACAS, RAIZ, apagar, copia
import catalogo
import circuito
import geometria
import gerar
import programa
import testar


def rodar(troca=None, requisitos=None):
    pasta = copia(troca=troca)
    if requisitos is not None:
        (pasta / "requisitos.md").write_text(requisitos)
    try:
        estado = testar.rodar(pasta, "teste")
        salvo = json.loads((pasta / "testes.json").read_text())
        zip_ = (pasta / "saida" / "fabrica.zip")
        return estado, salvo, zipfile.ZipFile(zip_).namelist() if zip_.exists() else None
    finally:
        apagar(pasta)


def parou(estado):
    falha = next((e for e in estado["etapas"] if e["estado"] == "falhou"), None)
    return (estado["etapas"].index(falha) + 1, falha) if falha else (None, None)


class PlacaBoa(unittest.TestCase):
    def test_passa_inteira_e_gera_o_zip(self):
        estado, salvo, zip_ = rodar()
        estados = [e["estado"] for e in estado["etapas"]]
        if not _tem_gerbonara():
            self.skipTest("gerbonara só no .venv")
        self.assertEqual(estados, ["ok"] * 7, [(e["nome"], e["detalhe"]) for e in estado["etapas"]])
        self.assertEqual(estado["requisitos"], {"R1": "ok", "R2": "ok", "R3": "ok"})
        self.assertIn("11 mA", estado["etapas"][3]["detalhe"])
        self.assertEqual(len(zip_), 8)
        self.assertFalse(salvo["rodando"], "o testes.json nunca fica 'rodando'")
        self.assertEqual(salvo["versao"], 1)


def _tem_gerbonara():
    try:
        import gerbonara  # noqa: F401
        return True
    except ImportError:
        return False


class CadaDefeitoNaSuaEtapa(unittest.TestCase):
    def confere(self, etapa, trecho, troca=None, requisitos=None, rotulo=None):
        estado, salvo, zip_ = rodar(troca, requisitos)
        n, falha = parou(estado)
        self.assertEqual(n, etapa, [(e["nome"], e["estado"], e["detalhe"]) for e in estado["etapas"]])
        self.assertIn(trecho, falha["detalhe"])
        if rotulo:
            self.assertIn(rotulo, falha.get("rotulos", {}).values())
        self.assertIsNone(zip_, "com falha não sai fabrica.zip")
        self.assertTrue(all(e["estado"] == "nao_rodou" for e in estado["etapas"][n:]))
        self.assertFalse(salvo["rodando"])
        return falha

    def test_erro_de_digitacao_para_na_1_com_a_linha(self):
        falha = self.confere(1, "comando desconhecido", {"liga D1.2 GND": "ligar D1.2 GND"})
        self.assertEqual(falha["codigo"], "ligar D1.2 GND")

    def test_peca_que_nao_existe_para_na_2(self):
        self.confere(2, "não existe na biblioteca", {"led_5mm": "led_9mm"})

    def test_peca_sem_ligacao_para_na_3(self):
        self.confere(3, "sem ligação", {"liga R1.2 D1.1\nliga D1.2 GND\n": ""}, rotulo="sem ligação")

    def test_pino_solto_para_na_3(self):
        self.confere(3, "pino solto", {"liga D1.2 GND\n": ""}, rotulo="pino solto")

    def test_peca_em_cima_de_outra_para_na_3(self):
        self.confere(3, "em cima de", {"D1 led_5mm 43 7": "D1 led_5mm 43 15"}, rotulo="uma em cima da outra")

    def test_pinos_de_pecas_diferentes_encostados_dao_curto_na_3(self):
        # dois resistores ponta com ponta: os corpos longe, nenhum pad embaixo de corpo, mas o R1.2 em cima do R2.1.
        # (o pad do LED fica dentro do corpo dele: LED com pino encostado em outro pino já cai no 'furo coberto')
        estado, _ = rodar_placa("placa 40 20\npeca R1 resistor_axial 10 10 100\npeca R2 resistor_axial 20.5 10 100\n"
                                "liga R1.1 R2.1\nliga R1.2 R2.2\n")
        n, falha = parou(estado)
        self.assertEqual(n, 3, [(e["nome"], e["detalhe"]) for e in estado["etapas"]])
        self.assertTrue(falha["detalhe"].startswith("curto: R1.2 encosta em R2.1"), falha["detalhe"])

    def test_peca_fora_da_placa_para_na_3(self):
        self.confere(3, "sai da placa", {"R1 resistor_axial 43 15": "R1 resistor_axial 47.7 15"}, rotulo="fora da placa")

    def test_pino_em_cima_do_furo_de_fixacao_para_na_3(self):
        self.confere(3, "em cima do furo de fixação", {"R1 resistor_axial 43 15": "R1 resistor_axial 43.5 4.6"}, rotulo="em cima do furo")

    def test_led_queima_para_na_4(self):
        self.confere(4, "queima", {"43 15 100": "43 15 10"}, rotulo="queima")

    def test_peca_na_borda_para_na_5(self):
        self.confere(5, "da borda", {"R1 resistor_axial 43 15": "R1 resistor_axial 46 15"}, rotulo="perto da borda")

    def test_requisito_quebrado_aparece_sem_parar_a_rodada(self):
        req = "# Objetivo: x\n## R1 Botão dos dois lados\npecas: SW1\nverifica: separado BT1.1 SW1.1\n"
        estado, _, _ = rodar(requisitos=req)
        self.assertEqual(estado["requisitos"], {"R1": "falha"})
        self.assertEqual(estado["objetivo"]["itens"][0]["motivo"], "em curto")

    def test_requisito_com_checagem_inventada(self):
        estado, _, _ = rodar(requisitos="# Objetivo: x\n## R1 a\nverifica: brilha_muito D1\n")
        self.assertIn("checagem desconhecida", estado["objetivo"]["erro"])

    def test_erro_inesperado_nao_trava_o_testes_json(self):
        original = testar.regras_fabrica
        testar.regras_fabrica = lambda ctx: 1 / 0
        try:
            # rodar() usa a lista de funções montada na hora, então troca dentro do módulo
            estado, salvo, _ = rodar()
        finally:
            testar.regras_fabrica = original
        n, falha = parou(estado)
        self.assertEqual(n, 5)
        self.assertIn("erro inesperado", falha["detalhe"])
        self.assertFalse(salvo["rodando"])


# ---------- placas com o ESP32 ----------
# U1 em (40, 32): a fileira de baixo (1-15) fica em y 19,3 e a de cima (16-30) em y 44,7. As peças ficam do lado
# da fileira que usam (senão a trilha atravessa o DevKit). Pino 6 = GPIO32, 11 = GPIO14, 14 = GND, 16 = 3V3.
BASE = "placa 80 56\nfuros cantos 3.2\npeca U1 devkit_esp32_30 40 32\n"
BOA = BASE + """peca R1 resistor_axial 28 9 220
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
# 3V3 → 22 kΩ → GPIO34 → LDR → GND (o divisor da luz noturna)
LDR = """placa 80 64
furos cantos 3.2
peca U1 devkit_esp32_30 40 32
peca R1 resistor_axial 64 54 22k
peca LDR1 C10081 26 9
liga U1.16 R1.1
liga R1.2 U1.4
liga U1.4 LDR1.1
liga LDR1.2 GND
"""
REQ_PINO = "# Objetivo: x\n## R1 O ESP32 aguenta\npecas: U1\nverifica: pino_seguro U1\n"
REQ_LDR = "# Objetivo: luz\n## R1 O ADC lê a luz\npecas: LDR1 R1\nverifica: adc_na_faixa LDR1 10 23\nverifica: pino_seguro U1\n"
# um resistor na ponta da antena: o corpo fica fora do DevKit, mas o pad 2 (e a trilha dele) entram na zona
ANTENA = BOA.replace("placa 80 56", "placa 80 60") + """peca R3 resistor_axial 10.8 32 1k
peca D3 led_5mm 4.5 44
liga U1.30 R3.2
liga R3.1 D3.1
liga D3.2 GND
"""


def peca_da_loja(codigo, eletrica=None):
    """pecas/<codigo>.json mínimo: a elétrica, os nomes e a fonte são os conferidos do catálogo (T3);
    o desenho (2 furos a 5,08 mm) é só pro teste. eletrica = outra no lugar da conferida"""
    c = catalogo.conferido(codigo)
    pad = {"forma": "C", "d": 1.6}
    return {"nome": f"peça {codigo}", "explica": "peça de teste", "fonte": c["fonte"], "corpo": [6.0, 3.0],
            "pinos": {"1": {"x": -2.54, "y": 0, "pad": pad, "furo": 0.8}, "2": {"x": 2.54, "y": 0, "pad": pad, "furo": 0.8}},
            "nomes": c["nomes"], "eletrica": eletrica or c["eletrica"], "pendente": []}


def placa_temp(texto, pecas=(), requisitos=None):
    """pecas = os códigos do catálogo, ou {código: eletrica trocada}"""
    pasta = Path(tempfile.mkdtemp(prefix="sianvolt-teste-")) / "esp32"
    (pasta / "pecas").mkdir(parents=True)
    (pasta / "placa.txt").write_text(texto)
    for codigo, eletrica in (pecas if isinstance(pecas, dict) else dict.fromkeys(pecas)).items():
        (pasta / "pecas" / f"{codigo}.json").write_text(json.dumps(peca_da_loja(codigo, eletrica), ensure_ascii=False))
    if requisitos:
        (pasta / "requisitos.md").write_text(requisitos)
    return pasta


def rodar_placa(texto, pecas=(), requisitos=None):
    """as 7 etapas numa placa temporária: (estado, fabrica.zip existe?)"""
    pasta = placa_temp(texto, pecas, requisitos)
    try:
        return testar.rodar(pasta, "teste"), (pasta / "saida" / "fabrica.zip").exists()
    finally:
        apagar(pasta)


def etapa4(texto, pecas=(), requisitos=None, nomes=None, sem=()):
    """monta a placa e roda só a etapa 4: (ctx, detalhe ou a exceção). nomes = {pino: nome novo} no U1
    (ex.: um DevKit que tivesse o GPIO6 pra fora); sem = campos que somem da elétrica do U1 (um número pendente)"""
    pasta = placa_temp(texto, pecas, requisitos)
    try:
        bib = gerar.biblioteca(pasta)
        modelo = gerar.montar(gerar.ler(texto), bib)
        u = next(p for p in modelo["pecas"] if p["ref"] == "U1")
        u["eletrica"] = {k: v for k, v in u["eletrica"].items() if k not in sem}
        for q in u["pinos"]:
            q["nome"] = (nomes or {}).get(q["n"], q["nome"])
        ctx = {"pasta": pasta, "bib": bib, "modelo": modelo}
        try:
            return ctx, testar.liga_circuito(ctx)
        except (testar.Falhou, testar.Pulou) as e:
            return ctx, e
    finally:
        apagar(pasta)


class Esp32NaEtapa4(unittest.TestCase):
    def reprova(self, texto, trecho, rotulo=None, **kw):
        ctx, r = etapa4(texto, **kw)
        self.assertIsInstance(r, testar.Falhou, r)
        self.assertIn(trecho, r.detalhe)
        if rotulo:
            self.assertIn(rotulo, r.rotulos.get("U1", ""), r.rotulos)
        return ctx, r

    def test_placa_boa_liga_com_o_led_aceso(self):
        ctx, r = etapa4(BOA)
        self.assertIsInstance(r, str, r)
        self.assertIn("D1: 5,9 mA com o vf típico (pelo menos 4,4 mA com o vf máximo; o vf mínimo do LED está pendente", r)
        self.assertIn("SW1 apertado: o GPIO14 (D14) fica em 0,07 V (até 0,82 V o pino lê 0)", r)   # 3,3 · 1k / (45k + 1k)
        self.assertIn("botão com o pull-up de dentro: GPIO14 (D14)", r)
        self.assertIn("3V3 de 3,201 a 3,399 V: vale com VIN ≥ 4,8 V", r)
        self.assertTrue(ctx["sim"]["nominal"]["pecas"]["D1"]["acende"])
        self.assertFalse(ctx["sim"]["nova"]["pecas"]["D1"]["queima"])
        # GPIO32 em 1 → 220 Ω → LED (joelho 1,7 V, r_s 20): (3,3 − 1,7) / (30 + 220 + 20); no pior caso, com 3,399 V
        self.assertAlmostEqual(ctx["sim"]["nominal"]["pecas"]["D1"]["i"], 1.6 / 270, delta=1e-7)
        self.assertAlmostEqual(ctx["sim"]["nova"]["pecas"]["D1"]["i"], 1.699 / 270, delta=1e-7)
        self.assertTrue(ctx["sim"]["esp32"]["seguro"])
        self.assertEqual(ctx["sim"]["esp32"]["estado"], {"GPIO32": 1, "GPIO14": "pullup"})
        # o regulador entrega o que sai dos pinos: o LED no pior caso mais o pull-up de dentro com o botão apertado
        self.assertAlmostEqual(ctx["sim"]["esp32"]["soma"], 1.699 / 270 + 3.399 / 46000, delta=1e-6)
        self.assertIn("o 3V3 entrega até 6,4 mA (o orçamento é 500 mA)", r)
        self.assertIn("pior caso: cada saída em 1 e em 0, botões apertados e 3V3 em 3,399 V ·", r)   # o led_5mm não tem vf_min
        self.assertIn("esquentam no pior caso: R1 9 mW, R2 0 mW (cada um aguenta 250 mW)", r)

    def test_cada_saida_em_1_e_em_0(self):
        # LED entre dois pinos: com os dois em 1 ou os dois em 0 não acende; com um em 1 e o outro em 0, acende
        ctx, r = etapa4(BOA.replace("liga D1.2 GND", "liga D1.2 U1.7"))
        self.assertIsInstance(r, str, r)
        self.assertTrue(ctx["sim"]["nominal"]["pecas"]["D1"]["acende"])
        self.assertGreater(ctx["sim"]["esp32"]["pinos"]["GPIO33"], 0.005, "o GPIO33 afunda a corrente do LED")

    def test_botao_que_le_0_com_folga_nao_avisa(self):
        # 10 kΩ: apertado, 3,3 · 10k / (45k + 10k) = 0,60 V, abaixo de 0,25 × 3,3 V (o VIL é fração do 3V3)
        ctx, r = etapa4(BOA.replace("52 9 1k", "52 9 10k"))
        self.assertIn("SW1 apertado: o GPIO14 (D14) fica em 0,60 V (até 0,82 V o pino lê 0)", r)
        self.assertNotIn("aviso", ctx)

    def test_22_ohms_passa_da_forca_do_pino(self):
        ctx, r = self.reprova(BOA.replace("28 9 220", "28 9 22"), "a força padrão do pino é ~20 mA", "pino")
        self.assertIn("pino", r.rotulos["D1"])
        self.assertFalse(ctx["sim"]["esp32"]["seguro"])

    def test_led_no_gpio34_so_entra(self):
        ctx, r = self.reprova(BOA.replace("liga U1.6 R1.2", "liga U1.4 R1.2"), "GPIO34 (D34) só entra", "só entra")
        self.assertFalse(ctx["sim"]["esp32"]["seguro"], "regra quebrada: o pino_seguro dá False")
        # os pinos livres pra trocar: sem os de boot, flash, serial, psram e só entrada, e sem o 14, que já tem o botão
        self.assertIn("(pinos livres: GPIO 4, 13, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33)", r.detalhe)

    def test_gpio6_e_da_flash(self):
        self.reprova(BOA, "GPIO6 (D32) é da flash", "flash", nomes={"6": "GPIO6"})

    def test_saida_na_serial_e_no_boot(self):
        self.reprova(BOA.replace("liga U1.6 R1.2", "liga U1.28 R1.2"), "GPIO1 (TX0) é a serial do PC", "serial")
        self.reprova(BOA.replace("liga U1.6 R1.2", "liga U1.19 R1.2"), "GPIO2 (D2) é pino de boot", "boot")

    def test_botao_no_gpio35_sem_pull_up(self):
        self.reprova(BOA.replace("liga U1.11 R2.1", "liga U1.5 R2.1"), "GPIO35 (D35) não tem pull-up de dentro", "pull-up")

    def test_botao_no_gpio35_com_pull_up_de_fora_passa(self):
        texto = BOA.replace("liga U1.11 R2.1", "liga U1.5 R2.1") + "peca R3 resistor_axial 60 50 10k\nliga U1.16 R3.1\nliga R3.2 U1.5\n"
        ctx, r = etapa4(texto)
        self.assertIsInstance(r, str, r)
        self.assertIn("botão com pull-up de fora: GPIO35 (D35)", r)
        self.assertNotIn("GPIO35", ctx["sim"]["esp32"]["estado"], "o GPIO35 não tem pull-up de dentro pra ligar")

    def test_botao_no_gpio35_com_pull_down_de_fora_passa(self):
        # o botão vai pro 3V3 e um resistor segura o pino no GND: o pino nunca fica solto
        texto = BASE + """peca R2 resistor_axial 52 9 10k
peca SW1 botao_6x6 66 9
liga U1.5 SW1.1
liga SW1.3 U1.16
liga U1.5 R2.1
liga R2.2 GND
"""
        ctx, r = etapa4(texto)
        self.assertIsInstance(r, str, r)
        self.assertIn("botão com pull-down de fora: GPIO35 (D35)", r)
        self.assertEqual(ctx["sim"]["esp32"]["estado"], {})

    def test_botao_com_resistor_grande_nao_le_0(self):
        # 22 kΩ no lugar de 1 kΩ: apertado, o pino fica em 3,3 · 22k / (45k + 22k) = 1,08 V, acima de 0,25 · 3,3 V
        ctx, r = etapa4(BOA.replace("52 9 1k", "52 9 22k"))
        self.assertIsInstance(r, str, r)   # só aviso: o pino não corre risco
        self.assertIn("aviso: SW1 apertado: o GPIO14 (D14) fica em 1,08 V (até 0,82 V o pino lê 0): o programa pode não ver", r)
        self.assertEqual(ctx["aviso"]["rotulos"]["SW1"], "botão não lê 0")

    def test_dois_gpios_ligados_um_no_outro_avisa(self):
        ctx, r = etapa4(BOA + "liga U1.7 U1.8\n")
        self.assertIsInstance(r, str, r)
        self.assertIn("aviso: GPIO33 (D33) e GPIO25 (D25) estão ligados um no outro", r)
        self.assertEqual(ctx["aviso"]["rotulos"]["U1"], "pinos juntos")

    def test_led_da_loja_mostra_a_faixa_do_vf(self):
        # C779439 com 130 Ω (o Dado): o + dele é o pino 2. 'até' = o LED de vf mínimo, com o pino em 1
        texto = (BOA.replace("peca D1 led_5mm", "peca D1 C779439").replace("28 9 220", "28 9 130")
                 .replace("liga R1.1 D1.1\nliga D1.2 GND", "liga R1.1 D1.2\nliga D1.1 GND"))
        ctx, r = etapa4(texto, ["C779439"])
        e = catalogo.conferido("C779439")["eletrica"]
        ate = (3.3 - (e["vf_min"] - e["r_s"] * e["i_teste"])) / (30 + 130 + e["r_s"])
        de = (3.3 - (e["vf_max"] - e["r_s"] * e["i_teste"])) / (30 + 130 + e["r_s"])
        self.assertRegex(r, rf"D1: até {testar.ma(ate)} mA ≈ \d+% do anúncio \(de {testar.ma(de)} a {testar.ma(ate)} mA com 3,3 V")
        self.assertEqual(testar.ma(ate), "9,0")

    def test_vin_usado(self):
        _, r = self.reprova(BOA.replace("liga U1.11 R2.1", "liga U1.15 R2.1"), "VIN usado: não sei ligar no papel", "VIN")
        self.assertIn("(o VIN, U1.15, está ligado em R2;", r.detalhe)   # a peça, não o nome de máquina da net
        self.assertEqual(r.rotulos["R2"], "VIN usado")

    def test_gpio16_so_avisa_da_psram(self):
        ctx, r = etapa4(BOA.replace("liga U1.6 R1.2", "liga U1.21 R1.2"))
        self.assertIsInstance(r, str, r)
        self.assertIn("aviso: GPIO16 (RX2): nos módulos WROVER esse pino é da memória extra; o WROOM-32 deste DevKit não "
                      "tem essa memória, então funciona", r)
        self.assertEqual(ctx["aviso"]["rotulos"]["U1"], "psram")

    def test_botao_num_pino_de_boot_so_avisa(self):
        # botão pro GND com o pull-up de dentro: o de dentro só liga depois do boot, então é só aviso
        ctx, r = etapa4(BOA.replace("liga U1.11 R2.1", "liga U1.19 R2.1"))
        self.assertIsInstance(r, str, r)
        self.assertIn("aviso: GPIO2 (D2) é pino de boot (LED azul da placa): o ESP32 lê esse pino na hora de ligar", r)
        self.assertIn("troque de pino (pinos livres: GPIO 4, 13, 14, 18,", r)
        self.assertTrue(testar.checar("pino_seguro U1", ctx["modelo"], ctx["sim"]), "aviso não conta no pino_seguro")

    def test_pino_de_boot_puxado_pro_3v3_reprova(self):
        # GPIO12 = MTDI: em 0 ao ligar (WROOM-32 v3.8, nota da Figura 6); o 10k pro 3V3 deixa ele em 1
        texto = BOA.replace("liga U1.11 R2.1", "liga U1.12 R2.1") + "peca R3 resistor_axial 60 50 10k\nliga U1.16 R3.1\nliga R3.2 U1.12\n"
        ctx, r = self.reprova(texto, "U1 GPIO12 (D12) tem que estar em 0 quando o ESP32 liga, e ele está puxado pro 3V3 por R3")
        self.assertEqual(r.rotulos, {"U1": "pino de boot", "R3": "pino de boot"})
        self.assertFalse(ctx["sim"]["esp32"]["seguro"])
        # direto no 3V3 também
        self.reprova(BASE + "liga U1.12 U1.16\n", "GPIO12 (D12) tem que estar em 0 quando o ESP32 liga, e ele está direto no 3V3")
        # o botão pro 3V3 (pull-down de fora) só deixa em 1 apertado: aviso, pra não segurar apertado ao ligar
        texto = BASE + "peca R2 resistor_axial 52 9 10k\npeca SW1 botao_6x6 66 9\nliga U1.19 SW1.1\nliga SW1.3 U1.16\nliga U1.19 R2.1\nliga R2.2 GND\n"
        ctx, r = etapa4(texto)
        self.assertIsInstance(r, str, r)
        self.assertIn("aviso: GPIO2 (D2) tem que estar em 0 quando o ESP32 liga (em 1, o ESP32 não entra no modo de gravar "
                      "o programa): não segure SW1 apertado na hora de ligar", r)

    def test_pull_up_de_fora_depois_do_resistor_do_botao(self):
        # GPIO35 → 1k → botão → GND, e o 10k do 3V3 entra entre o 1k e o botão: solto, o pino fica em 1 por 11k
        texto = BOA.replace("liga U1.11 R2.1", "liga U1.5 R2.1") + "peca R3 resistor_axial 60 50 10k\nliga U1.16 R3.1\nliga R3.2 SW1.1\n"
        ctx, r = etapa4(texto)
        self.assertIsInstance(r, str, r)
        self.assertIn("botão com pull-up de fora: GPIO35 (D35)", r)
        self.assertIn("SW1 apertado: o GPIO35 (D35) fica em 0,00 V", r)

    def test_gpio_direto_na_energia_diz_onde(self):
        ctx, r = etapa4(BOA + "liga U1.13 U1.14\n")
        self.assertIn("aviso: GPIO13 (D13) está ligado direto no GND: nunca use como saída (seria um curto)", r)

    def test_led_que_so_queima_no_pior_caso(self):
        # 3V3 → 35 Ω → LED → GND: 1,6 / 55 = 29 mA com 3,3 V (passa) e 1,699 / 55 = 31 mA com 3,399 V (queima, limite 30)
        texto = BOA + "peca R3 resistor_axial 60 50 35\npeca D3 led_5mm 70 50\nliga U1.16 R3.1\nliga R3.2 D3.1\nliga D3.2 GND\n"
        ctx, r = self.reprova(texto, "D3 queima: até 31 mA no pior caso, o limite é 30 mA")
        self.assertFalse(ctx["sim"]["nominal"]["pecas"]["D3"]["queima"])

    def test_botao_acima_do_limite_dele(self):
        # 3V3 → 56 Ω → botão → GND: 3,399 / 56 = 61 mA no pior caso, o botao_6x6 aguenta 50 mA
        texto = BOA + "peca R3 resistor_axial 60 50 56\npeca SW3 botao_6x6 72 50\nliga U1.16 R3.1\nliga R3.2 SW3.1\nliga SW3.3 GND\n"
        _, r = self.reprova(texto, "SW3 passa 61 mA no pior caso, o limite dele é 50 mA")
        self.assertEqual(r.rotulos["SW3"], "corrente alta")

    def test_botao_em_curto_do_3v3(self):
        # sem resistor, a corrente só pararia no r_3v3 do gêmeo (suposição): vira 'curto', sem número
        _, r = self.reprova(BOA + "peca SW3 botao_6x6 72 50\nliga U1.16 SW3.1\nliga SW3.3 GND\n",
                            "curto: com SW3 apertado, o 3V3 do U1 vai direto pro GND", "curto")
        self.assertNotIn("mA", r.detalhe)
        self.assertEqual(r.rotulos["SW3"], "curto")

    def test_numero_pendente_que_a_conta_nao_pede(self):
        # sem esses números a conta fecha, mas o pino_seguro não pode dizer True: fica em '?' (None), à vista
        for campo, trecho in (("i_pino", "a força padrão do pino está pendente"), ("orcamento_3v3", "o orçamento está pendente"),
                              ("vdd_max", "3V3 em 3,3 V (a tensão máxima do 3V3 está pendente: o pior caso usa o 3V3 do meio)")):
            ctx, r = etapa4(BOA, sem=[campo])
            self.assertIsInstance(r, str, r)
            self.assertIn(trecho, r)
            self.assertIn("falta conferir no datasheet:", r)
            self.assertIsNone(testar.checar("pino_seguro U1", ctx["modelo"], ctx["sim"]), campo)
        _, r = etapa4(BOA.replace("28 9 220", "28 9 22"), sem=["orcamento_3v3"])
        self.assertIsInstance(r, testar.Falhou, "o que já passou do limite reprova mesmo com outro número pendente")

    def test_led_no_3v3_queima(self):
        texto = BOA + "peca R3 resistor_axial 60 50 10\npeca D3 led_5mm 70 50\nliga U1.16 R3.1\nliga R3.2 D3.1\nliga D3.2 GND\n"
        _, r = self.reprova(texto, "D3 queima")
        self.assertEqual(r.rotulos["D3"], "queima")

    def test_3v3_acima_do_orcamento(self):
        ctx, r = self.reprova(BOA + "peca R3 resistor_axial 60 50 4.7\nliga U1.16 R3.1\nliga R3.2 GND\n", "acima do orçamento de 500 mA")
        self.assertEqual(r.rotulos["U1"], "3V3 no limite")
        self.assertFalse(ctx["sim"]["esp32"]["seguro"], "estourou o orçamento: o pino_seguro dá False")
        self.assertEqual(r.rotulos["R3"], "esquenta")

    def test_piezo_mostra_o_pico(self):
        texto = BOA + "peca R3 resistor_axial 60 50 1k\npeca BZ1 C128650 70 50\nliga U1.9 R3.1\nliga R3.2 BZ1.1\nliga BZ1.2 GND\n"
        ctx, r = etapa4(texto, ["C128650"])
        self.assertIsInstance(r, str, r)
        self.assertIn("BZ1: pico de 3,2 mA na borda do apito", r)   # 3,3 / (1000 + 30)
        self.assertIn("saída: GPIO32 (D32), GPIO26 (D26)", r)

    def test_dois_esp32_pula(self):
        _, r = etapa4(BOA + "peca U2 devkit_esp32_30 40 80\nliga U2.6 R1.2\n")
        self.assertIsInstance(r, testar.Pulou)


class Esp32ComLdr(unittest.TestCase):
    def test_volts_por_lux_e_adc_na_faixa(self):
        ctx, r = etapa4(LDR, ["C10081"], REQ_LDR)
        self.assertIsInstance(r, str, r)
        for trecho in ("LDR1 no GPIO34 (D34): escuro 3,23 V", "1 lux 2,38 V", "10 lux 1,20 V", "23 lux 0,83 V", "100 lux 0,38 V",
                       "a faixa boa do ADC é 0,15 a 2,45 V, fora dela: escuro, 1 lux"):
            self.assertIn(trecho, r)
        m, sim = ctx["modelo"], ctx["sim"]
        self.assertTrue(testar.checar("adc_na_faixa LDR1 10 23", m, sim))
        self.assertTrue(testar.checar("adc_na_faixa LDR1", m, sim), "sem lux, 10 lux")
        self.assertFalse(testar.checar("adc_na_faixa LDR1 1", m, sim), "1 lux no canto max passa de 2,45 V")
        self.assertTrue(testar.checar("pino_seguro U1", m, sim))
        self.assertIsNone(testar.checar("adc_na_faixa LDR1 10", m, None), "sem a etapa 4 não dá pra saber")

    def test_pior_caso_com_100_lux_no_canto_que_mais_puxa(self):
        # o pior caso põe o LDR no escuro e em 100 lux no canto 'min' (a menor resistência): o R1 passa o máximo
        ctx, _ = etapa4(LDR, ["C10081"])
        e = catalogo.conferido("C10081")["eletrica"]
        i = 3.399 / (22000 + 0.05 + circuito.ohms_do_ldr(e, 100, "min"))   # 0,05 Ω = o r_3v3 do gêmeo
        self.assertAlmostEqual(ctx["sim"]["nova"]["pecas"]["R1"]["i"], i, delta=1e-7)
        self.assertAlmostEqual(ctx["sim"]["nova"]["pecas"]["LDR1"]["i"], i, delta=1e-7)

    def test_faixa_nos_cantos_do_ldr_e_do_3v3(self):
        ctx, _ = etapa4(LDR, ["C10081"])
        e = catalogo.conferido("C10081")["eletrica"]
        for lux in (1, 10, 100):
            vs = [circuito.divisor_do_ldr(e, 22000, v, lux, c) for c in ("min", "max") for v in (3.201, 3.399)]
            lo, hi = testar.faixa_do_ldr(ctx["modelo"], ctx["sim"]["esp32"], "LDR1", lux)
            self.assertAlmostEqual(lo, min(vs), delta=1e-3)
            self.assertAlmostEqual(hi, max(vs), delta=1e-3)

    def test_divisor_alimentado_por_um_gpio(self):
        # o 22k sai do GPIO32 (economiza corrente): quem lê é o GPIO34, colado no LDR; o GPIO32 é uma saída
        ctx, r = etapa4(LDR.replace("liga U1.16 R1.1", "liga U1.6 R1.1"), ["C10081"], REQ_LDR)
        self.assertIsInstance(r, str, r)
        info = ctx["sim"]["esp32"]
        self.assertEqual(info["ldr"]["LDR1"][0], "GPIO34")
        self.assertEqual(info["estado"], {"GPIO32": 1})
        self.assertIn("U1: leitura de tensão (ADC): GPIO34 (D34); saída: GPIO32 (D32)", r)
        self.assertIn("LDR1 no GPIO34 (D34): escuro 3,23 V", r)
        self.assertTrue(testar.checar("adc_na_faixa LDR1 10 23", ctx["modelo"], ctx["sim"]))

    def test_segundo_gpio_lendo_o_divisor_por_um_resistor(self):
        # o divisor já vem do 3V3: o GPIO35, que chega nele por 1 kΩ, também lê (não é quem alimenta); o ADC do LDR1
        # fica no GPIO34, que está colado nele
        ctx, r = etapa4(LDR + "peca R9 resistor_axial 64 44 1k\nliga U1.5 R9.1\nliga R9.2 U1.4\n", ["C10081"])
        self.assertIsInstance(r, str, r)
        self.assertIn("leitura de tensão (ADC): GPIO34 (D34), GPIO35 (D35)", r)
        self.assertEqual(ctx["sim"]["esp32"]["ldr"]["LDR1"][0], "GPIO34")

    def test_lux_zero_e_lux_com_virgula(self):
        req = "# x\n## R1 a\npecas: LDR1\nverifica: adc_na_faixa LDR1 0 1,5\n"
        ctx, r = etapa4(LDR, ["C10081"], req)
        frase = next(f for f in r.split(" · ") if f.startswith("LDR1"))
        self.assertEqual(frase.count("escuro"), 2, frase)   # uma na lista de volts e outra no 'fora dela'
        self.assertIn("1,5 lux", frase)
        self.assertIn("fora dela: escuro, 1 lux, 1,5 lux", frase)
        self.assertFalse(testar.checar("adc_na_faixa LDR1 1,5", ctx["modelo"], ctx["sim"]))
        self.assertEqual(testar.ler_requisitos(req)["itens"][0]["verifica"][0]["texto"], "adc_na_faixa LDR1 0 1,5")

    def test_a_mesma_conta_do_divisor(self):
        ctx, _ = etapa4(LDR, ["C10081"])
        info, e = ctx["sim"]["esp32"], catalogo.conferido("C10081")["eletrica"]
        for lux in (1, 10, 23, 100):
            for canto in ("min", "meio", "max"):
                for vdd in (3.201, 3.3, 3.399):
                    self.assertAlmostEqual(testar.volts_no_ldr(ctx["modelo"], info, "LDR1", lux, canto, vdd),
                                           circuito.divisor_do_ldr(e, 22000, vdd, lux, canto), delta=1e-3)

    def test_ldr_depois_de_um_resistor(self):
        texto = LDR.replace("liga U1.4 LDR1.1", "peca R9 resistor_axial 64 44 1k\nliga U1.4 R9.1\nliga R9.2 LDR1.1")
        ctx, r = etapa4(texto, ["C10081"], REQ_LDR)
        self.assertIn("LDR1 no GPIO34 (D34): escuro", r)
        self.assertEqual(ctx["sim"]["esp32"]["ldr"]["LDR1"][0], "GPIO34")
        self.assertTrue(testar.checar("adc_na_faixa LDR1 10 23", ctx["modelo"], ctx["sim"]))

    def test_numero_pendente_pula_sem_inventar(self):
        sem_gama = {k: v for k, v in catalogo.conferido("C10081")["eletrica"].items() if k != "gama"}
        _, r = etapa4(LDR, {"C10081": sem_gama})
        self.assertIsInstance(r, testar.Pulou, r)
        self.assertIn("LDR1: falta conferir quanto a resistência cai com a luz (gama)", str(r))
        # mas a regra do pino vale sem a conta: LED no GPIO35 reprova mesmo assim
        led = "peca R2 resistor_axial 20 50 220\npeca D1 led_5mm 10 50\nliga U1.5 R2.1\nliga R2.2 D1.1\nliga D1.2 GND\n"
        _, r = etapa4(LDR + led, {"C10081": sem_gama})
        self.assertIsInstance(r, testar.Falhou, r)
        self.assertIn("GPIO35 (D35) só entra", r.detalhe)

    def test_ldr_fora_do_adc1(self):
        ctx, r = etapa4(LDR.replace("U1.4", "U1.11"), ["C10081"])
        self.assertIn("GPIO14 (D14) não é do ADC1", r)
        self.assertFalse(testar.checar("adc_na_faixa LDR1 10", ctx["modelo"], ctx["sim"]))

    def test_requisito_com_lux_errado(self):
        for linha, erro in (("adc_na_faixa", "espera 1 ou mais valores"), ("adc_na_faixa LDR1 dez", "devia ser os lux"),
                            ("adc_na_faixa LDR1 inf", "devia ser os lux"), ("adc_na_faixa LDR1 -1", "devia ser os lux")):
            with self.assertRaises(gerar.ErroTxt) as e:
                testar.ler_requisitos(f"# x\n## R1 a\nverifica: {linha}\n")
            self.assertIn(erro, e.exception.msg)


class Esp32DePontaAPonta(unittest.TestCase):
    def setUp(self):
        if not _tem_gerbonara():
            self.skipTest("gerbonara só no .venv")

    def test_placa_boa_passa_e_gera_o_zip(self):
        estado, zip_ = rodar_placa(BOA, requisitos=REQ_PINO)
        self.assertEqual([e["estado"] for e in estado["etapas"]], ["ok"] * 7, [(e["nome"], e["detalhe"]) for e in estado["etapas"]])
        self.assertIn("D1: 5,9 mA", estado["etapas"][3]["detalhe"])
        self.assertIn("ainda a conferir: U1: porta USB, queda do SS14, r_3v3", estado["etapas"][1]["detalhe"])
        self.assertEqual(estado["requisitos"], {"R1": "ok"})
        self.assertTrue(zip_)

    def test_22_ohms_para_na_4(self):
        estado, zip_ = rodar_placa(BOA.replace("28 9 220", "28 9 22"), requisitos=REQ_PINO)
        n, falha = parou(estado)
        self.assertEqual(n, 4)
        self.assertEqual(falha["rotulos"]["U1"], "puxa demais do pino")
        self.assertEqual(estado["requisitos"], {"R1": "falha"})
        self.assertEqual(estado["objetivo"]["itens"][0]["motivo"], "pino do ESP32 em risco")
        self.assertFalse(zip_)

    def test_ldr_com_os_requisitos(self):
        estado, zip_ = rodar_placa(LDR, ["C10081"], REQ_LDR)
        self.assertEqual([e["estado"] for e in estado["etapas"]], ["ok"] * 7, [(e["nome"], e["detalhe"]) for e in estado["etapas"]])
        self.assertEqual(estado["requisitos"], {"R1": "ok"})

    def test_antena_so_avisa_na_3(self):
        estado, zip_ = rodar_placa(ANTENA)
        self.assertEqual([e["estado"] for e in estado["etapas"]], ["ok"] * 7, [(e["nome"], e["detalhe"]) for e in estado["etapas"]])
        e3 = estado["etapas"][2]
        self.assertIn("na zona da antena do U1", e3["aviso"])
        self.assertIn("aviso:", e3["detalhe"])
        self.assertEqual(e3["rotulos"], {"R3": "na antena"})
        self.assertNotIn("aviso", estado["etapas"][3], "a 4 não tem aviso nessa placa")
        self.assertTrue(zip_, "aviso não segura a fábrica")


class AntenaNaEtapa3(unittest.TestCase):
    def modelo(self):
        pasta = placa_temp(BOA)
        try:
            return gerar.montar(gerar.ler(BOA), gerar.biblioteca(pasta))
        finally:
            apagar(pasta)

    def test_placa_boa_nao_tem_nada_na_antena(self):
        self.assertEqual(testar.na_antena(self.modelo()), [])

    def test_trilha_e_via_que_cruzam_a_antena(self):
        m = self.modelo()   # a zona: x de 14,1 a 20,91 e y de 23 a 41 (U1 em 40, 32)
        m["trilhas"].append({"de": "R1.1", "ate": "D1.1", "x1": 8, "y1": 30, "x2": 26, "y2": 30, "largura": 0.3,
                             "net": "N9", "lado": "baixo"})
        m["vias"].append({"x": 17, "y": 25, "d": 0.8, "furo": 0.4, "net": "N9", "de": "R1.1", "ate": "D1.1"})
        self.assertEqual(testar.na_antena(m), [("trilha R1.1 → D1.1", "U1"), ("via R1.1 → D1.1", "U1")])

    def test_pad_de_outra_peca_na_antena(self):
        m = self.modelo()
        pino = next(q for q in next(p for p in m["pecas"] if p["ref"] == "R1")["pinos"] if q["n"] == "1")
        pino.update(x=17, y=32)   # só o pad, sem trilha nem via
        self.assertEqual(testar.na_antena(m), [("R1.1", "U1")])


# o R3 do lado direito do DevKit: o corpo fica fora, mas o furo do lado 1 fica embaixo da borda dele (longe da antena)
FURO_NO_DEVKIT = BOA + """peca R3 resistor_axial 69.2 22 1k
peca D3 led_5mm 72 30
liga U1.13 R3.1
liga R3.2 D3.1
liga D3.2 GND
"""


def pino_de(m, nome):
    ref, n = nome.split(".")
    return next(q for p in m["pecas"] if p["ref"] == ref for q in p["pinos"] if q["n"] == n)


class FuroEmbaixoDeOutraPeca(unittest.TestCase):
    def test_furo_do_resistor_embaixo_do_led_para_na_3(self):
        # o LED da lanterninha logo embaixo do lado 2 do resistor: a aba do LED cobre o furo, sem corpo com corpo
        troca = {"D1 led_5mm 43 7": "D1 led_5mm 48.5 11.5"}
        m = gerar.montar(gerar.ler((PLACAS / "lanterna" / "placa.txt").read_text().replace(*next(iter(troca.items())))))
        self.assertEqual(testar.corpos_encostados(m), [], "os corpos não se encostam")
        self.assertEqual(testar.pads_embaixo(m), [("R1.2", "D1")])
        estado, _, zip_ = rodar(troca)
        n, falha = parou(estado)
        self.assertEqual(n, 3, [(e["nome"], e["detalhe"]) for e in estado["etapas"]])
        self.assertEqual(falha["detalhe"], "o furo do R1.2 fica embaixo do LED D1: não dá pra soldar")
        self.assertEqual(falha["rotulos"], {"R1": "furo coberto", "D1": "em cima de um furo"})
        self.assertIsNone(zip_)

    def test_o_mesmo_furo_embaixo_do_devkit_passa(self):
        if not _tem_gerbonara():
            self.skipTest("gerbonara só no .venv")
        estado, zip_ = rodar_placa(FURO_NO_DEVKIT)
        self.assertEqual([e["estado"] for e in estado["etapas"]], ["ok"] * 7, [(e["nome"], e["detalhe"]) for e in estado["etapas"]])
        self.assertNotIn("aviso", estado["etapas"][2], "fora da antena: nem aviso")
        self.assertTrue(zip_)
        # o furo está mesmo embaixo do corpo do DevKit: é a barra fêmea (no alto) que deixa passar
        m = gerar.montar(gerar.ler(FURO_NO_DEVKIT))
        u1, furo = m["pecas"][0], pino_de(m, "R3.1")
        self.assertTrue(testar.no_alto(u1))
        self.assertTrue(testar.entra_no_corpo(geometria.do_pad(furo["x"], furo["y"], furo["pad"]), gerar.corpo_na_placa(u1), 0.05))
        self.assertEqual(testar.pads_embaixo(m), [])
        u1["eletrica"] = None   # o mesmo corpo deitado na placa: aí pega
        self.assertEqual(testar.pads_embaixo(m), [("R3.1", "U1")])

    def test_a_folga_e_a_mesma_do_corpo_com_corpo(self):
        # o LED descendo em cima do lado 2 do resistor (48,08; 15): a aba do LED tem raio 2,9 e o pad, 0,8
        lanterna = (PLACAS / "lanterna" / "placa.txt").read_text()
        for y, cobre in ((11.1, []), (11.33, []), (11.4, [("R1.2", "D1")])):   # 0,2 mm longe, 0,03 e 0,1 mm dentro
            m = gerar.montar(gerar.ler(lanterna.replace("D1 led_5mm 43 7", f"D1 led_5mm 48.08 {y}")))
            self.assertEqual(testar.pads_embaixo(m), cobre, y)

    def test_placas_de_teste_nao_tem_furo_coberto(self):
        for texto in ((PLACAS / "lanterna" / "placa.txt").read_text(), BOA, LDR, ANTENA):
            pasta = placa_temp(texto, ["C10081"])
            try:
                self.assertEqual(testar.pads_embaixo(gerar.montar(gerar.ler(texto), gerar.biblioteca(pasta))), [], texto)
            finally:
                apagar(pasta)

    def test_quanto_o_pad_entra_no_corpo(self):
        circ, ret = ("circ", 0, 0, 2.9), ("ret", -3, -1, 3, 1)
        redondo = {"forma": "C", "d": 1.6}
        entra = testar.entra_no_corpo
        self.assertTrue(entra(geometria.do_pad(3.6, 0, redondo), circ, 0.05), "entra 0,1 mm na aba do LED")
        self.assertFalse(entra(geometria.do_pad(3.66, 0, redondo), circ, 0.05), "0,04 mm: dentro da folga")
        self.assertTrue(entra(geometria.do_pad(3.7, 0, redondo), ret, 0.05))
        self.assertFalse(entra(geometria.do_pad(3.76, 0, redondo), ret, 0.05))
        self.assertTrue(entra(geometria.do_pad(0, 0, redondo), ret, 0.05), "inteiro embaixo do corpo")
        quadrado = {"forma": "R", "w": 1.6, "h": 1.6}
        self.assertTrue(entra(geometria.do_pad(3.7, 0, quadrado), ret, 0.05))
        self.assertFalse(entra(geometria.do_pad(3.76, 0, quadrado), ret, 0.05))
        self.assertTrue(entra(geometria.do_pad(3.6, 0, quadrado), circ, 0.05))
        oblongo = {"forma": "O", "w": 2.4, "h": 1.6}   # o meio de 3,7 a 4,5 com raio 0,8
        self.assertTrue(entra(geometria.do_pad(4.1, 0, oblongo), ret, 0.05))
        self.assertFalse(entra(geometria.do_pad(4.16, 0, oblongo), ret, 0.05))
        self.assertTrue(entra(geometria.do_pad(4.0, 0, oblongo), circ, 0.05))


# três resistores um em cima do outro numa placa estreita: o nome do R2 não tem lado livre
APERTADO = "placa 14 30\npeca R1 resistor_axial 7 20 130\npeca R2 resistor_axial 7 17.05 130\npeca R3 resistor_axial 7 14.1 130\n"


class NomeSemLugarNaEtapa5(unittest.TestCase):
    def test_sem_lado_livre_avisa(self):
        ctx = {"modelo": gerar.montar(gerar.ler(APERTADO))}
        detalhe = testar.regras_fabrica(ctx)
        self.assertEqual(ctx["aviso"]["rotulos"], {"R2": "nome escondido"})
        self.assertEqual(ctx["aviso"]["texto"], "o nome do R2 fica embaixo do R1 (nenhum lado em volta da peça ficou livre: "
                                                "afaste o que está perto pra ler o nome)")
        self.assertEqual(detalhe, "trilha, espaço, furo, anel, borda, máscara e serigrafia (JLCPCB) · aviso: " + ctx["aviso"]["texto"])

    def test_de_ponta_a_ponta_o_aviso_fica_na_5(self):
        # o R2 cercado: o R1 em cima, o R3 embaixo e, dos lados, os pads do Ra e do Rb. Só resistores: a 4 pula
        if not _tem_gerbonara():
            self.skipTest("gerbonara só no .venv")
        texto = """placa 60 40
peca Ra resistor_axial 17.42 20 130
peca R2 resistor_axial 30 20 130
peca Rb resistor_axial 42.58 20 130
peca R1 resistor_axial 30 22.95 130
peca R3 resistor_axial 30 17.05 130
liga Ra.2 R2.1
liga R2.2 Rb.1
liga Rb.2 R1.2
liga R1.1 R3.1
liga R3.2 Ra.1
"""
        estado, zip_ = rodar_placa(texto)
        self.assertEqual([e["estado"] for e in estado["etapas"]], ["ok", "ok", "ok", "pulou", "ok", "ok", "ok"],
                         [(e["nome"], e["detalhe"]) for e in estado["etapas"]])
        e5 = estado["etapas"][4]
        self.assertTrue(e5["aviso"].startswith("o nome do R2 fica embaixo do R1 ("), e5["aviso"])
        self.assertEqual(e5["rotulos"], {"R2": "nome escondido"})
        self.assertTrue(zip_, "aviso não segura a fábrica")

    def test_com_lado_livre_nao_avisa(self):
        # a escada do dado: o nome do R4 e do R1 saem de cima e acham lugar
        escada = "placa 40 30\npeca R2 resistor_axial 20 20 130\npeca R4 resistor_axial 21.25 17.05 130\npeca R1 resistor_axial 22.5 14.1 130\n"
        for texto in (escada, (PLACAS / "lanterna" / "placa.txt").read_text(), BOA):
            ctx = {"modelo": gerar.montar(gerar.ler(texto))}
            testar.regras_fabrica(ctx)
            self.assertNotIn("aviso", ctx, texto)

    def test_nome_em_cima_do_nome_de_outra_peca(self):
        # o R1 encosta na borda de cima e o nome dele vai pra baixo, no vão até o R2; o R2 não tem lado livre (o R3
        # embaixo, os lados fora da placa) e o nome dele fica em cima, no mesmo vão
        texto = APERTADO.replace("7 20 130", "7 28 130").replace("7 17.05 130", "7 23.6 130").replace("7 14.1 130", "7 20.65 130")
        ctx = {"modelo": gerar.montar(gerar.ler(texto))}
        testar.regras_fabrica(ctx)
        self.assertEqual(ctx["aviso"]["rotulos"], {"R2": "nome escondido"})
        self.assertTrue(ctx["aviso"]["texto"].startswith("o nome do R2 fica em cima do nome do R1 ("), ctx["aviso"]["texto"])

    def test_frase_de_cada_coisa_que_o_nome_cobre(self):
        m = gerar.montar(gerar.ler(BOA))
        r1 = m["pecas"][1]
        pad = pino_de(m, "R1.1")
        r1["nome_pos"] = dict(r1["nome_pos"], x=pad["x"], y=pad["y"])
        self.assertEqual(testar.nomes_sem_lugar(m), [("R1", "nome cortado", "o nome do R1 passa em cima do pad R1.1")])
        r1["nome_pos"] = dict(r1["nome_pos"], x=0.5, y=30)
        self.assertEqual(testar.nomes_sem_lugar(m), [("R1", "nome cortado", "o nome do R1 sai da placa")])
        r1["nome_pos"] = dict(r1["nome_pos"], x=40, y=30)
        self.assertEqual(testar.nomes_sem_lugar(m), [("R1", "nome escondido", "o nome do R1 fica embaixo do U1")])


class BrilhoDeCadaLed(unittest.TestCase):
    def test_o_ajuste_do_led_vale_mais_que_a_resposta_geral(self):
        # 20 mA nessa curva dá o brilho do anúncio (1,0): 'forte'
        led = {"brilho": [[0.001, 0], [0.005, 0.32], [0.010, 0.60], [0.020, 1.0]]}
        m = {"pecas": [{"ref": r, "pinos": [{"n": "1", "net": "x"}], "eletrica": led} for r in ("D1", "D2")]}
        sim = {"nominal": {"pecas": {r: {"i": 0.020, "acende": True} for r in ("D1", "D2")}}}
        proj = {"perguntas": {"brilho": {"resposta": "fraca", "por_led": {"D1": {"resposta": "forte"}}}}}
        self.assertTrue(testar.checar("brilho D1", m, sim, proj), "o D1 pediu forte")
        self.assertFalse(testar.checar("brilho D2", m, sim, proj), "o D2 segue a resposta geral (fraca)")
        self.assertIsNone(testar.checar("brilho D1", m, sim, {}), "sem resposta não dá pra saber")


class SaidaDoTestar(unittest.TestCase):
    def roda(self, texto):
        pasta = placa_temp(texto)
        try:
            return subprocess.run([sys.executable, str(RAIZ / "ferramenta" / "testar.py"), str(pasta)],
                                  capture_output=True, text=True, timeout=180)
        finally:
            apagar(pasta)

    def test_etapa_pulada_sai_com_0(self):
        if not _tem_gerbonara():
            self.skipTest("gerbonara só no .venv")
        r = self.roda(BOA.replace("peca D1 led_5mm", "peca D1 led"))   # o 'led' de exemplo não tem modelo elétrico
        self.assertIn("· 4. Liga o circuito: não dá pra ligar no papel ainda · sem modelo elétrico: D1", r.stdout)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_falha_sai_com_1(self):
        r = self.roda(BOA.replace("28 9 220", "28 9 22"))
        self.assertIn("✗ 4. Liga o circuito", r.stdout)
        self.assertEqual(r.returncode, 1)


# ---------- a 8ª etapa: o programa da placa no gêmeo (testes/placas/esp32) ----------
TEM_LAB = programa.tem_laboratorio()   # o laboratorio/ e o MicroPython do PC não vêm no clone limpo
ESP32_OK = ["ok"] * 8


def esp32(main=None, confere=None, roteiro=None, troca=None):
    """cópia da placa de teste do ESP32; main = {"texto velho": "texto novo"} no main.py; confere/roteiro = o
    json novo; troca = no placa.txt"""
    pasta = copia("esp32", troca)
    cod = pasta / "codigo"
    if main:
        txt = (cod / "main.py").read_text()
        for velho, novo in main.items():
            assert velho in txt, velho
            txt = txt.replace(velho, novo)
        (cod / "main.py").write_text(txt)
    for nome, dado in (("confere.json", confere), ("roteiro.json", roteiro)):
        if dado is not None:
            (cod / nome).write_text(json.dumps(dado, ensure_ascii=False))
    return pasta


def rodar_esp32(**kw):
    """as 8 etapas numa cópia: (estado, a 8ª etapa, fabrica.zip existe?)"""
    pasta = esp32(**kw)
    try:
        estado = testar.rodar(pasta, "teste")
        return estado, estado["etapas"][-1], (pasta / "saida" / "fabrica.zip").exists()
    finally:
        apagar(pasta)


def so_a_8(**kw):
    """só a etapa 8 (quando a 4 reprovaria antes): o detalhe ou a exceção, e o ctx"""
    pasta = esp32(**kw)
    ctx = {"pasta": pasta}
    try:
        return testar.roda_programa(ctx), ctx
    except (testar.Falhou, testar.Pulou) as e:
        return e, ctx
    finally:
        apagar(pasta)


ROTEIRO = json.loads((PLACAS / "esp32" / "codigo" / "roteiro.json").read_text())


class PlacaDeTesteDoEsp32(unittest.TestCase):
    def test_so_tem_o_que_vai_pro_git(self):
        """ela vai pro git: nada do que o testar e o programa geram (rodar nela de verdade sujaria o repositório)"""
        pasta = PLACAS / "esp32"
        arquivos = sorted(str(a.relative_to(pasta)) for a in pasta.rglob("*") if a.is_file())
        self.assertEqual([a for a in arquivos if not a.startswith("pecas/")],
                         ["codigo/confere.json", "codigo/gemeo.roteiro", "codigo/main.py", "codigo/roteiro.json",
                          "placa.txt", "projeto.json", "requisitos.md"])
        self.assertEqual([a for a in arquivos if a.startswith("pecas/")],
                         ["pecas/C10081.json", "pecas/C128650.json", "pecas/C393938.json", "pecas/C779439.json"])

    def test_a_copia_tem_o_pid_no_nome(self):
        pasta = copia("esp32")
        try:
            self.assertIn(f"sianvolt-teste-{os.getpid()}-", pasta.parent.name)
            self.assertEqual(testar.etapas_da(pasta)[0], testar.ETAPAS + [testar.ETAPA_PROGRAMA])
        finally:
            apagar(pasta)
        self.assertEqual(testar.etapas_da(PLACAS / "lanterna")[0], testar.ETAPAS, "sem programa, 7 etapas")


@unittest.skipUnless(TEM_LAB and _tem_gerbonara(), "sem o laboratório e o MicroPython do PC (ou sem o gerbonara)")
class ProgramaNaEtapa8(unittest.TestCase):
    def test_placa_de_teste_passa_nas_8(self):
        pasta = esp32()
        try:
            estado = testar.rodar(pasta, "teste")
            self.assertEqual([e["estado"] for e in estado["etapas"]], ESP32_OK,
                             [(e["nome"], e["detalhe"]) for e in estado["etapas"]])
            self.assertEqual(estado["etapas"][7]["nome"], "Roda o programa")
            self.assertEqual(estado["etapas"][7]["detalhe"], "rodou 3 s de placa: D1 acendeu; 13 de 13 conferências ok")
            self.assertEqual(estado["requisitos"], {"R1": "ok", "R2": "ok", "R3": "ok", "R4": "ok"})
            self.assertEqual(json.loads((pasta / "testes.json").read_text())["requisitos"], estado["requisitos"])
            self.assertTrue((pasta / "saida" / "fabrica.zip").exists())
            prog = json.loads((pasta / "saida" / "programa.json").read_text())
            self.assertEqual((prog["codigo"], prog["erro"], prog["conferencias"]["falhas"]), (0, None, []))
            self.assertIn("sorteou", " ".join(t for _, t in prog["serial"]))
            pinos = (pasta / "codigo" / "pinos.py").read_text()
            for linha in ("BZ1 = 26", "D1 = 32", "LDR1 = 34", "SW1 = 14"):
                self.assertIn(linha, pinos)
            self.assertFalse(programa.ocupada(pasta), "a trava foi solta")
            vaga = programa.LAB.parent / "build" / programa.LAB_PLACA / "gemeo" / programa.nome_da_copia(pasta)
            self.assertFalse(vaga.exists(), "a cópia não deixa vaga no laboratorio/build/ (o nome dela não volta)")
        finally:
            apagar(pasta)

    def test_erro_de_sintaxe_mostra_a_linha_do_main(self):
        linhas = (PLACAS / "esp32" / "codigo" / "main.py").read_text().splitlines()
        n = linhas.index('print("pronto")') + 2   # a linha nova vem logo depois
        estado, e8, zip_ = rodar_esp32(main={'print("pronto")\n': 'print("pronto")\nx = = 1\n'})
        self.assertEqual([e["estado"] for e in estado["etapas"]], ["ok"] * 7 + ["falhou"])
        self.assertIn(f"erro na linha {n} do main.py, em 0,000 s: SyntaxError", e8["detalhe"])
        self.assertEqual(e8["codigo"], "x = = 1")
        self.assertEqual(e8["rotulos"]["U1"], "erro no programa")
        self.assertFalse(zip_, "com falha não sai fabrica.zip")
        self.assertEqual(estado["requisitos"], {"R1": "ok", "R2": "ok", "R3": "falha", "R4": "falha"})
        self.assertEqual(e8["requisitos"], ["R3", "R4"], "erro no programa não põe o ESP32 em risco (o R1 fica de fora)")

    def test_conferencia_impossivel_lista_a_falha(self):
        impossivel = {"confere": [{"tipo": "pwm_freq", "pino": "GPIO26", "hz": 1000, "folga": 50, "depois_de": "GPIO32 sobe"}]}
        estado, e8, zip_ = rodar_esp32(confere=impossivel)
        self.assertEqual(e8["estado"], "falhou")
        self.assertIn("a conferência falhou: GPIO26 em 1000 Hz (± 50) depois de cada 'GPIO32 sobe': em 0,504 s ligou em "
                      "4000 Hz · rodou 3 s de placa: D1 acendeu; 9 de 10 conferências ok", e8["detalhe"])
        self.assertEqual(e8["rotulos"], {"U1": "conferência", "BZ1": "conferência"},
                         "o D1 do 'GPIO32 sobe' não tem defeito: só o pino da conferência")
        self.assertFalse(zip_)
        self.assertEqual(estado["requisitos"]["R3"], "falha")
        self.assertEqual(estado["requisitos"]["R4"], "ok", "o LED acendeu mesmo assim")

    def test_conferencia_do_roteiro_que_falha(self):
        # código 4 do lab.py: o roteiro.json do laboratório confere um nível que não acontece
        estado, e8, _ = rodar_esp32(roteiro={**ROTEIRO, "confere": [{"t": 0.8, "pino": "GPIO32", "valor": 0}]})
        self.assertEqual(e8["detalhe"], "a conferência falhou: GPIO32 = 0 em 0,800 s: viu 1 · rodou 3 s de placa: D1 "
                                        "acendeu; 4 de 5 conferências ok")
        self.assertEqual(e8["rotulos"], {"U1": "conferência", "D1": "conferência"})
        self.assertEqual(estado["requisitos"]["R3"], "falha")

    def test_adc_fora_da_faixa_so_avisa(self):
        escuro = {**ROTEIRO, "entradas": [{"t": 0, "luz": "LDR1", "lux": 0}]}   # 3,23 V, acima dos 2,45 V
        estado, e8, zip_ = rodar_esp32(roteiro=escuro)
        self.assertEqual([e["estado"] for e in estado["etapas"]], ESP32_OK)
        self.assertIn("ADC no GPIO34 lê 3,23 V, fora da faixa boa", e8["aviso"])
        self.assertIn(" · aviso: ADC no GPIO34 lê 3,23 V", e8["detalhe"])
        self.assertEqual(e8["rotulos"], {"U1": "ADC fora da faixa", "LDR1": "ADC fora da faixa"})
        self.assertTrue(zip_, "aviso não segura a fábrica")

    def test_botao_flutuando_reprova(self):
        estado, e8, _ = rodar_esp32(main={"Pin(SW1, Pin.IN, Pin.PULL_UP)": "Pin(SW1, Pin.IN)"})
        self.assertEqual(e8["estado"], "falhou")
        self.assertIn("GPIO14 está flutuando", e8["detalhe"])
        self.assertEqual((e8["rotulos"]["U1"], e8["rotulos"]["SW1"]), ("flutuando", "flutuando"))
        self.assertEqual(estado["requisitos"]["R4"], "falha", "sem o pull-up, o botão nunca lê apertado")

    def test_programa_que_trava(self):
        _, e8, _ = rodar_esp32(main={"    time.sleep_ms(5)\n": "    while agora == 0:\n        pass\n    time.sleep_ms(5)\n"})
        self.assertEqual(e8["estado"], "falhou")
        self.assertTrue(e8["detalhe"].startswith("o programa travou: ficou preso num laço que não espera nem mexe em "
                                                 "nada (como while True: pass, sem sleep); na placa ele ficaria preso aí"),
                        e8["detalhe"])
        self.assertNotIn("qemu", e8["detalhe"], "o texto do lab fala de motores: o Luiz lê o nosso")
        self.assertIn("conferências falharam (estão no saida/programa.json) · parou em 0,5", e8["detalhe"])
        self.assertEqual(e8["rotulos"], {"U1": "travou"})

    def test_reset_para_e_diz_por_que(self):
        # o roteiro da placa confere 'estado tempo': o lab.py sai com 4, e a frase é a do reset (não a conferência crua)
        sorteou = '            print("sorteou %d" % random.randint(1, 6))\n'
        estado, e8, zip_ = rodar_esp32(main={sorteou: sorteou + "            import machine\n            machine.reset()\n"})
        self.assertEqual(e8["estado"], "falhou")
        self.assertTrue(e8["detalhe"].startswith("o programa reiniciou o ESP32 (machine.reset()): na placa ele recomeça "
                                                 "do zero, e o gêmeo para aí · "), e8["detalhe"])
        self.assertIn(" · parou em ", e8["detalhe"])
        self.assertNotIn("estado tempo", e8["detalhe"])
        self.assertEqual(e8["rotulos"], {"U1": "reiniciou"})
        self.assertFalse(zip_)
        self.assertEqual(estado["requisitos"]["R3"], "falha")

    def test_wdt_sem_conferir_o_estado(self):
        # sem 'estado' no roteiro, o lab.py sai com 3 e o motivo só está no aviso 'wdt'
        sem_estado = {**ROTEIRO, "confere": [c for c in ROTEIRO["confere"] if "estado" not in c]}
        _, e8, _ = rodar_esp32(roteiro=sem_estado, main={'print("pronto")\n': 'print("pronto")\nfrom machine import WDT\n'
                                                                          'cao = WDT(timeout=1000)\n'})
        self.assertTrue(e8["detalhe"].startswith("o cão de guarda (WDT) reiniciou o ESP32: o programa ficou 1000 ms "
                                                 "sem chamar o feed() dele"), e8["detalhe"])
        self.assertNotIn("não explicou", e8["detalhe"])
        self.assertEqual(e8["rotulos"], {"U1": "reiniciou"})

    def test_sys_exit_no_comeco(self):
        _, e8, _ = rodar_esp32(main={'print("pronto")\n': 'print("pronto")\nimport sys\nsys.exit()\n'})
        self.assertEqual(e8["estado"], "falhou")
        self.assertIn("s de placa, antes dos 3 s do roteiro: o main.py chegou no fim (ou chamou sys.exit()), e o resto "
                      "do roteiro não aconteceu · ", e8["detalhe"])
        self.assertEqual(e8["rotulos"], {"U1": "acabou cedo"})

    def test_pino_da_flash_reprova(self):
        # a etapa 4 não vê: o pino 6 não está no circuito, só no programa. O gêmeo segue, o ESP32 de verdade trava
        _, e8, zip_ = rodar_esp32(main={'print("pronto")\n': 'print("pronto")\nPin(6, Pin.OUT).on()\n'})
        self.assertEqual(e8["estado"], "falhou")
        self.assertIn("GPIO6 é da memória flash: mexer nele trava o ESP32 de verdade", e8["detalhe"])
        self.assertEqual(e8["rotulos"], {"U1": "pino da memória flash"})
        self.assertFalse(zip_)

    def test_pino_da_serial_e_da_psram_avisam(self):
        _, e8, zip_ = rodar_esp32(main={'print("pronto")\n': 'print("pronto")\nPin(1, Pin.OUT).on()\n'
                                                               'Pin(17, Pin.OUT).on()\n'})
        self.assertEqual(e8["estado"], "ok")
        self.assertIn("GPIO1 é o TX da serial", e8["aviso"])
        self.assertIn("GPIO17 é da PSRAM", e8["aviso"])
        self.assertEqual(e8["rotulos"], {"U1": "pino da serial"}, "o ESP32 fica com o rótulo do primeiro aviso")
        self.assertTrue(zip_, "aviso não segura a fábrica")

    def test_roteiro_errado_nem_roda(self):
        # código 2 do programa.py: falha (não pula), e o programa_acende fica em '?'
        estado, e8, _ = rodar_esp32(roteiro={**ROTEIRO, "entradas": [{"t": 0, "luz": "SW1", "lux": 1}]})
        self.assertEqual(e8["detalhe"], "o programa não rodou: SW1 não é um olho de luz ligado num GPIO do ESP32")
        self.assertEqual(estado["requisitos"]["R4"], "?")
        self.assertEqual(estado["objetivo"]["itens"][3]["motivo"], "o programa não rodou no gêmeo")

    def test_led_queimando_e_pino_acima_da_forca(self):
        # 10 Ω: a etapa 4 já reprovaria; aqui é a 8 sozinha, com o que o gêmeo avisa
        r, ctx = so_a_8(troca={"peca R1 resistor_axial 14.25 17 130": "peca R1 resistor_axial 14.25 17 10"})
        self.assertIsInstance(r, testar.Falhou, r)
        self.assertIn("D1 QUEIMA: passa", r.detalhe)
        self.assertIn("GPIO32 fornece", r.detalhe)
        self.assertEqual(r.rotulos, {"D1": "queima", "U1": "corrente alta"})
        self.assertEqual(ctx["programa"], {"ok": False, "acesos": ["D1"]})

    def test_pino_de_boot_no_lugar_errado(self):
        # o botão no GPIO12 com um 10k pro 3V3: o gêmeo vê o MTDI em 1 quando o ESP32 liga
        troca = {"liga U1.11 R2.1": "liga U1.12 R2.1\npeca R9 resistor_axial 30 58 10k\nliga U1.16 R9.1\nliga R9.2 U1.12"}
        r, _ = so_a_8(troca=troca, main={"from pinos import BZ1, D1, LDR1, SW1": "from pinos import BZ1, D1, LDR1\nSW1 = 12"})
        self.assertIsInstance(r, testar.Falhou, r)
        self.assertIn("GPIO12 é pino de boot", r.detalhe)
        self.assertEqual(r.rotulos["U1"], "pino de boot")


class Etapa8SemOLaboratorio(unittest.TestCase):
    """o que não precisa do laboratório: pular, a trava e as checagens do programa"""

    def trocar(self, **funcoes):
        for nome, f in funcoes.items():
            self.addCleanup(setattr, programa, nome, getattr(programa, nome))
            setattr(programa, nome, f)

    def test_sem_laboratorio_pula_e_gera_o_pinos(self):
        self.trocar(tem_laboratorio=lambda: False)
        pasta, ctx = esp32(), {}
        try:
            ctx["pasta"] = pasta
            with self.assertRaises(testar.Pulou) as r:
                testar.roda_programa(ctx)
            self.assertIn("o laboratório não está nesta máquina", str(r.exception))
            self.assertIn("SW1 = 14  # botão, U1 pino 11, D14, pelo R2", (pasta / "codigo" / "pinos.py").read_text())
            self.assertNotIn("programa", ctx, "sem a etapa 8, programa_ok e programa_acende ficam em '?'")
        finally:
            apagar(pasta)

    def test_codigo_5_pula(self):
        def indisponivel(pasta, *a, **k):
            prog = programa.normalizar([], pasta, programa.INDISPONIVEL)
            prog["avisos"].append([0.0, "indisponivel", "falta o motor gemeo"])
            return prog
        self.trocar(tem_laboratorio=lambda: True, rodar=indisponivel)
        r, ctx = so_a_8()
        self.assertIsInstance(r, testar.Pulou)
        self.assertEqual(str(r), "o programa não rodou no papel: falta o motor gemeo")

    def test_codigo_de_falha_sem_explicacao_falha(self):
        """só o código 0 passa e só o 5 pula: o 4 sem nenhuma conferência na lista falha do mesmo jeito"""
        self.trocar(tem_laboratorio=lambda: True, rodar=lambda p, *a, **k: {**programa.normalizar([], p, 4),
                                                                              "tempo_ms": 3000.0})
        r, ctx = so_a_8()
        self.assertIsInstance(r, testar.Falhou, r)
        self.assertIn("o laboratório saiu com o código 4 sem dizer o que falhou", r.detalhe)
        self.assertEqual(r.rotulos, {"U1": "não rodou"})
        self.assertFalse(ctx["programa"]["ok"])

    def test_espera_a_trava_da_placa(self):
        """o app (ou um terminal) rodando o programa da placa: a etapa 8 espera ele acabar, não atropela"""
        pasta, quando, segura = esp32(), [], threading.Event()

        def rodar(p, *a, **k):
            quando.append(time.monotonic())
            return {**programa.normalizar([], p, 0), "tempo_ms": 3000.0}   # os 3 s do roteiro da placa

        def outra_rodada():
            with programa.trava(pasta):
                segura.set()
                time.sleep(0.6)
        self.trocar(tem_laboratorio=lambda: True, rodar=rodar)
        try:
            outra = threading.Thread(target=outra_rodada)
            outra.start()
            segura.wait(5)
            inicio = time.monotonic()
            detalhe = testar.roda_programa({"pasta": pasta})
            outra.join()
        finally:
            apagar(pasta)
        self.assertGreater(quando[0] - inicio, 0.4, "esperou a outra rodada soltar a trava")
        self.assertEqual(detalhe, "rodou 3 s de placa: nenhum LED no circuito; nenhuma conferência (o roteiro.json e "
                                  "o confere.json não conferem nada)")

    def test_acabou_cedo_com_codigo_0_so_avisa(self):
        """o roteiro sem 'estado': o lab.py sai com 0 e a etapa passa, mas diz que o resto do roteiro não rodou"""
        self.trocar(tem_laboratorio=lambda: True,
                    rodar=lambda p, *a, **k: {**programa.normalizar([], p, 0), "tempo_ms": 1.0})
        pasta = esp32()
        ctx = {"pasta": pasta}
        try:
            detalhe = testar.roda_programa(ctx)
        finally:
            apagar(pasta)
        self.assertIn("aviso: o programa acabou em 0,001 s de placa, antes dos 3 s do roteiro", detalhe)
        self.assertEqual(ctx["aviso"]["rotulos"], {"U1": "acabou cedo"})
        self.assertTrue(ctx["programa"]["ok"])

    def test_travou_em_portugues_de_gente(self):
        limite = "travou: o programa passou do limite de 60,0 s de PC sem chegar no fim do tempo de placa"
        self.assertEqual(testar.travou_de_gente(limite), "o programa travou: passou de 60,0 s no PC sem chegar no "
                                                         "fim do roteiro (um laço que não acaba ou uma conta lenta "
                                                         "demais)")
        self.assertEqual(testar.travou_de_gente("travou: outra coisa"), "o programa travou: outra coisa")

    def test_requisitos_da_etapa_do_programa(self):
        """o erro no programa marca o ESP32, mas o 'ESP32 aguenta' (ok) não entra: entram os que o programa derrubou"""
        itens = [{"id": "R1", "pecas": ["U1", "D1"], "status": "ok", "verifica": [{"texto": "pino_seguro U1"}]},
                 {"id": "R3", "pecas": ["U1"], "status": "falha", "verifica": [{"texto": "programa_ok"}]},
                 {"id": "R4", "pecas": ["D1", "SW1"], "status": "falha", "verifica": [{"texto": "programa_acende D1"}]},
                 {"id": "R5", "pecas": ["BZ1"], "status": "?", "verifica": [{"texto": "acende BZ1"}]}]
        self.assertEqual(testar.requisitos_da({"nome": testar.ETAPA_PROGRAMA, "onde": ["U1"]}, itens), ["R3", "R4"])
        self.assertEqual(testar.requisitos_da({"nome": testar.ETAPA_PROGRAMA, "onde": ["U1", "BZ1"]}, itens),
                         ["R3", "R4", "R5"])
        self.assertEqual(testar.requisitos_da({"nome": "Liga o circuito", "onde": ["U1"]}, itens), ["R1", "R3"],
                         "nas outras etapas, os que citam a peça marcada")

    def test_programa_acende_com_a_peca_errada_diz_por_que(self):
        """erro de digitação no requisitos.md: o '?' diz a peça, e não 'o programa não rodou'"""
        pasta = copia("esp32")
        try:
            (pasta / "requisitos.md").write_text("# Objetivo: x\n## R1 a\npecas: D1\nverifica: programa_acende D9\n"
                                                 "## R2 b\npecas: SW1\nverifica: programa_acende SW1\n"
                                                 "## R3 c\npecas: D1\nverifica: programa_acende D1\n")
            m = {"pecas": [{"ref": "D1", "pinos": [], "eletrica": {"modelo": "led"}},
                           {"ref": "SW1", "pinos": [], "eletrica": {"modelo": "chave"}}]}
            rodou = testar.avaliar_requisitos(pasta, m, None, {"ok": True, "acesos": ["D1"]})
            nao_rodou = testar.avaliar_requisitos(pasta, m, None, None)
        finally:
            apagar(pasta)
        self.assertEqual([(i["status"], i["motivo"]) for i in rodou["itens"]],
                         [("?", "D9 não está no placa.txt"),
                          ("?", "SW1 não é LED: o programa_acende só confere LED"), ("ok", "ok")])
        self.assertEqual(nao_rodou["itens"][2]["motivo"], "o programa não rodou no gêmeo")

    def test_checagens_do_programa(self):
        m = {"pecas": [{"ref": "D1", "pinos": [], "eletrica": {"modelo": "led"}},
                       {"ref": "SW1", "pinos": [], "eletrica": {"modelo": "chave"}}]}
        rodou = {"ok": True, "acesos": ["D1"]}
        self.assertTrue(testar.checar("programa_ok", m, None, None, rodou))
        self.assertFalse(testar.checar("programa_ok", m, None, None, {"ok": False, "acesos": []}))
        self.assertIsNone(testar.checar("programa_ok", m, None, None, None), "sem a etapa 8: '?'")
        self.assertTrue(testar.checar("programa_acende D1", m, None, None, rodou))
        self.assertFalse(testar.checar("programa_acende D1", m, None, None, {"ok": True, "acesos": []}))
        self.assertIsNone(testar.checar("programa_acende SW1", m, None, None, rodou), "SW1 não é LED")
        self.assertIsNone(testar.checar("programa_acende D1", m, None, None, {"ok": False, "acesos": None}),
                          "o programa nem rodou")
        for linha, erro in (("programa_ok D1", "não leva valores"), ("programa_acende", "espera 1 valores")):
            with self.assertRaises(gerar.ErroTxt) as e:
                testar.ler_requisitos(f"# x\n## R1 a\nverifica: {linha}\n")
            self.assertIn(erro, e.exception.msg)

    def test_lanterna_com_checagem_do_programa_fica_em_interrogacao(self):
        if not _tem_gerbonara():
            self.skipTest("gerbonara só no .venv")
        estado, _, _ = rodar(requisitos="# Objetivo: x\n## R1 o programa\npecas: D1\nverifica: programa_ok\n")
        self.assertEqual(len(estado["etapas"]), 7)
        self.assertEqual(estado["requisitos"], {"R1": "?"})
        self.assertEqual(estado["objetivo"]["itens"][0]["motivo"], "o programa não rodou no gêmeo")

    def test_sem_laboratorio_a_linha_de_comando_sai_com_0(self):
        """o clone limpo: as 7 etapas passam, a 8ª pula, a fábrica sai e o testar.py sai com 0"""
        if not _tem_gerbonara():
            self.skipTest("gerbonara só no .venv")
        pasta = copia("esp32")
        try:
            r = subprocess.run([sys.executable, str(RAIZ / "ferramenta" / "testar.py"), str(pasta)], capture_output=True,
                               text=True, timeout=180, env={**os.environ, "LAB_FERRAMENTAS": str(pasta / "sem_ferramentas")})
            self.assertIn("· 8. Roda o programa: o laboratório não está nesta máquina", r.stdout)
            self.assertEqual(r.stdout.count("✓"), 7, r.stdout)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue((pasta / "saida" / "fabrica.zip").exists())
            self.assertIn("D1 = 32", (pasta / "codigo" / "pinos.py").read_text())
        finally:
            apagar(pasta)


if __name__ == "__main__":
    unittest.main()
