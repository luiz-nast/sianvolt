"""a bateria de 7 etapas (testar.py) de ponta a ponta: a placa boa passa, e cada defeito para na etapa certa.
No fim, as placas com o ESP32 (DevKit de 30 pinos), montadas pelo teste numa pasta temporária"""
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from apoio import RAIZ, apagar, copia
import catalogo
import circuito
import gerar
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
        # o LED do lado do resistor, sem os corpos se tocarem, mas o pino − do LED em cima do lado 2 do resistor
        self.confere(3, "curto", {"D1 led_5mm 43 7": "D1 led_5mm 49.3 15"})

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


if __name__ == "__main__":
    unittest.main()
