"""o DevKit de 30 pinos na biblioteca (devkit_esp32_30): o desenho, os nomes, e todo número da elétrica com fonte"""
import importlib
import re
import sys
import types
import unittest

from apoio import RAIZ, modelo
from biblioteca import BIBLIOTECA

T = BIBLIOTECA["devkit_esp32_30"]
E = T["eletrica"]
CHIPS = RAIZ / "laboratorio" / "motores" / "gemeo" / "chips"


def numeros(e):
    return {k: v for k, v in e.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


class Desenho(unittest.TestCase):
    def test_corpo_furo_e_pads(self):
        self.assertEqual(T["corpo"], (51.8, 28.2))
        self.assertEqual(T["furo"], 1.0)
        self.assertEqual(T["pinos"]["1"], (-19.87, -12.7, (1.7, 1.7)))   # o EN quadrado marca o lado da antena
        for n, (dx, dy, pad, *net) in T["pinos"].items():
            if n != "1":
                self.assertEqual(pad, 1.7, n)

    def test_duas_fileiras_de_15_a_25_4_mm(self):
        p = T["pinos"]
        self.assertEqual(list(p), [str(n) for n in range(1, 31)])
        for n in range(1, 16):
            dx, dy = p[str(n)][:2]
            self.assertAlmostEqual(dx, -19.87 + (n - 1) * 2.54, places=6)
            self.assertEqual(dy, -12.7)
            dx2, dy2 = p[str(31 - n)][:2]   # o do outro lado: 1 e 30 (EN e D23), 15 e 16 (VIN e 3V3)
            self.assertAlmostEqual(dx2, dx, places=6)
            self.assertAlmostEqual(dy2 - dy, 25.4, places=6)

    def test_pinos_andam_2_09_pro_lado_da_antena(self):
        xs = [v[0] for v in T["pinos"].values()]
        self.assertAlmostEqual((min(xs) + max(xs)) / 2, -2.09, places=6)

    def test_gnd_14_e_17_juntos(self):
        self.assertEqual(T["pinos"]["14"][3], "GND")
        self.assertEqual(T["pinos"]["17"][3], "GND")
        self.assertEqual([v[3] for n, v in T["pinos"].items() if len(v) > 3], ["GND", "GND"])
        self.assertEqual(T["juntos"], [("14", "17")])

    def test_nomes_de_maquina_e_serigrafia(self):
        nomes, seri = T["nomes"], T["serigrafia"]
        self.assertEqual(set(nomes), set(T["pinos"]))
        self.assertEqual(set(seri), set(T["pinos"]))
        for n, nome in nomes.items():
            self.assertRegex(nome, r"^(GPIO\d+|3V3|GND|VIN|EN)$", n)
        self.assertEqual(sum(nome.startswith("GPIO") for nome in nomes.values()), 25)
        self.assertEqual(len(set(nomes.values())), 29)   # só o GND se repete
        esperado = {"1": ("EN", "EN"), "2": ("GPIO36", "VP"), "6": ("GPIO32", "D32"), "15": ("VIN", "VIN"),
                    "16": ("3V3", "3V3"), "21": ("GPIO16", "RX2"), "28": ("GPIO1", "TX0"), "30": ("GPIO23", "D23")}
        for n, (maquina, escrito) in esperado.items():
            self.assertEqual((nomes[n], seri[n]), (maquina, escrito), n)

    def test_cuidados_batem_com_as_listas_da_eletrica(self):
        c = T["cuidados"]
        self.assertEqual(c["15"], "VIN: não soldar")
        self.assertIn("LED azul da placa", c["19"])
        for n, nome in T["nomes"].items():
            if nome in E["so_entrada"]:
                self.assertIn("só entrada", c.get(n, ""), n)
            if nome in E["boot"]:
                self.assertIn("cuidado no boot", c.get(n, ""), n)
            if nome in E["serial"]:
                self.assertIn("serial do PC", c.get(n, ""), n)
        self.assertTrue(set(c) <= set(T["pinos"]))

    def test_zonas_na_ponta_da_antena_e_do_usb(self):
        w, h = T["corpo"]
        antena, usb = T["zonas"]["antena"], T["zonas"]["usb"]
        self.assertEqual(antena["x"][0], -w / 2)                  # começa na borda do DevKit
        self.assertLess(antena["y"][1], 12.7 - 1.7 / 2)           # e passa entre as duas fileiras de pads
        self.assertGreater(antena["y"][0], -12.7 + 1.7 / 2)
        self.assertGreater(usb["x"][1], w / 2)                    # o USB passa da borda
        for z in (antena, usb):
            self.assertLess(z["x"][0], z["x"][1])
            self.assertLess(z["y"][0], z["y"][1])
            self.assertTrue(z["fonte"] and z["pede"])
        for dx, dy, *_ in T["pinos"].values():   # nenhum furo dentro da antena
            self.assertFalse(antena["x"][0] <= dx <= antena["x"][1] and antena["y"][0] <= dy <= antena["y"][1])

    def test_acompanha_confira_compra_e_fonte(self):
        self.assertEqual(len(T["acompanha"]), 1)
        barra = T["acompanha"][0]
        self.assertEqual((barra["codigo"], barra["qtd"]), ("C41417327", 2))
        self.assertTrue(barra["nome"])
        confira = " ".join(T["confira"])
        for trecho in ("EN", "D23", "25,4 mm", "1:1", "ponte de solda"):
            self.assertIn(trecho, confira)
        self.assertIn("https://www.robocore.net/wifi/esp32-wifi-bluetooth", T["compra"])
        self.assertIn("https://mischianti.org/", T["fonte"])
        self.assertIn("C41417327", T["fonte"])

    def test_pendente_so_dentro_da_eletrica(self):
        # o 'pendente' da peça seguraria a fábrica; o que falta conferir da elétrica fica em eletrica['pendentes']
        self.assertNotIn("pendente", T)
        m = modelo("placa 70 40\npeca U1 devkit_esp32_30 35 20\n")
        u1 = m["pecas"][0]
        self.assertEqual(u1["pendente"], [])
        self.assertFalse(u1["exemplo"])
        self.assertTrue(m["fabrica"]["pronta"])
        self.assertEqual({p["n"]: p["net"] for p in u1["pinos"] if p["net"]}, {"14": "GND", "17": "GND"})
        self.assertEqual({p["n"]: p["nome"] for p in u1["pinos"]}, T["nomes"])

    def test_tipos_antigos_continuam_iguais(self):
        velho = BIBLIOTECA["esp32_devkit"]
        self.assertEqual(velho["corpo"], (51.0, 28.0))
        self.assertIsNone(velho["fonte"])
        self.assertEqual(velho["pinos"]["1"], (-17.78, -12.7, 1.7))
        self.assertNotIn("eletrica", velho)


class Eletrica(unittest.TestCase):
    def test_todo_numero_tem_fonte_ou_pendente(self):
        fontes, pendentes = E["fontes"], E["pendentes"]
        self.assertGreaterEqual(len(numeros(E)), 12)
        for k in numeros(E):
            tem_fonte = bool(fontes.get(k)) and all(isinstance(f, str) and f.strip() for f in fontes[k])
            self.assertTrue(tem_fonte or any(p.startswith(k) for p in pendentes), f"{k} sem fonte nem pendente")
        for k, lista in fontes.items():   # nenhuma fonte de campo que não existe
            self.assertIn(k, E, k)
            self.assertIsInstance(lista, list, k)

    def test_toda_fonte_de_numero_diz_de_onde(self):
        # datasheet com página, ou o que é suposição dito com todas as letras
        for k in numeros(E):
            for f in E["fontes"][k]:
                self.assertTrue(re.search(r"https?://", f) or "suposição" in f, f"{k}: {f}")
            texto = " ".join(E["fontes"][k])
            self.assertTrue(re.search(r"p\. \d+", texto) or "suposição" in texto or "não é datasheet" in texto, k)

    def test_orcamento_do_3v3_com_duas_fontes(self):
        self.assertEqual(E["orcamento_3v3"], 0.5)
        a, b = E["fontes"]["orcamento_3v3"]
        self.assertIn("ds1117.pdf", a)
        self.assertIn("1A", a)
        self.assertIn("esp32-wroom-32_datasheet", b)
        self.assertIn("Tabela 13", b)

    def test_faixa_do_3v3_do_ams1117(self):
        self.assertEqual((E["vdd_min"], E["vdd"], E["vdd_max"]), (3.201, 3.3, 3.399))
        for k in ("vdd_min", "vdd_max"):
            texto = " ".join(E["fontes"][k])
            for trecho in ("ds1117.pdf", "p. 2", "linha 87", "VIN = 4,8 V"):
                self.assertIn(trecho, texto, k)
        self.assertIn("VIN ≥ 4,8 V", E["condicao_3v3"])
        self.assertIn("AMS1117 original", E["condicao_3v3"])
        pendentes = " ".join(E["pendentes"])
        self.assertIn("porta USB", pendentes)
        self.assertIn("SS14", pendentes)

    def test_cada_limite_com_o_significado_certo(self):
        self.assertEqual((E["r_pino"], E["i_pino"]), (30, 0.020))
        self.assertIn("não é datasheet", " ".join(E["fontes"]["r_pino"]))
        self.assertIn("força padrão", " ".join(E["fontes"]["i_pino"]))
        self.assertIn("nota 8", " ".join(E["fontes"]["i_pino"]))
        self.assertEqual(E["i_soma_max"], 1.1)
        self.assertIn("máximo absoluto", " ".join(E["fontes"]["i_soma_max"]))
        self.assertEqual((E["r_pull"], E["vil"]), (45000, 0.25))
        self.assertIn("Tabela 5-3", " ".join(E["fontes"]["r_pull"] + E["fontes"]["vil"]))
        self.assertEqual((E["adc_min"], E["adc_max"]), (0.15, 2.45))
        self.assertIn("Tabela 4-4", " ".join(E["fontes"]["adc_min"]))

    def test_r_3v3_e_suposicao_do_gemeo_pendente(self):
        texto = " ".join(E["fontes"]["r_3v3"])
        self.assertIn("suposição do gêmeo", texto)
        self.assertIn("pendente", texto)
        self.assertTrue(any(p.startswith("r_3v3") for p in E["pendentes"]))

    def test_listas_de_pinos(self):
        self.assertEqual(E["modelo"], "mcu")
        self.assertEqual(E["psram"], ["GPIO16", "GPIO17"])
        self.assertEqual(E["serial"], ["GPIO1", "GPIO3"])
        self.assertTrue({"GPIO34", "GPIO35", "GPIO36", "GPIO39"} <= set(E["so_entrada"]))
        self.assertTrue({"GPIO12", "GPIO15", "GPIO2", "GPIO5"} <= set(E["boot"]))
        self.assertIn("GPIO34", E["adc1"])
        for lista in ("so_entrada", "boot", "flash", "serial", "psram", "adc1"):
            self.assertTrue(E["fontes"].get(lista), lista)
            for g in E[lista]:
                self.assertRegex(g, r"^GPIO\d+$", lista)
        no_devkit = set(T["nomes"].values())
        self.assertFalse(set(E["flash"]) & no_devkit)   # os da flash nem saem no DevKit


def chip_do_gemeo():
    """o comum.py e o esp32.py do gêmeo, só lendo: sem pôr o laboratório no sys.path e sem escrever .pyc lá"""
    nome = "_chips_do_gemeo"
    if nome not in sys.modules:
        pacote = types.ModuleType(nome)
        pacote.__path__ = [str(CHIPS)]
        sys.modules[nome] = pacote
    antes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        return importlib.import_module(nome + ".comum"), importlib.import_module(nome + ".esp32")
    finally:
        sys.dont_write_bytecode = antes


def gpios(ns):
    return {f"GPIO{n}" for n in ns}


@unittest.skipUnless((CHIPS / "comum.py").is_file(), "precisa do laboratorio/ (ainda fora do git)")
class MesmosNumerosDoGemeo(unittest.TestCase):
    """os números do chip moram em dois lugares (a biblioteca e o gêmeo): têm que bater"""

    def test_vdd_pull_up_e_drive_2(self):
        comum, _ = chip_do_gemeo()
        self.assertEqual(comum.VDD, E["vdd"])
        self.assertEqual(comum.R_PULL, E["r_pull"])
        self.assertEqual(comum.DRIVE_PADRAO, 2)
        self.assertEqual(comum.DRIVE[2], (E["r_pino"], E["i_pino"]))
        self.assertAlmostEqual(comum.VIL, E["vil"] * E["vdd"])
        self.assertEqual(comum.R_3V3, E["r_3v3"])

    def test_mesma_pinagem_e_mesmas_listas(self):
        _, esp32 = chip_do_gemeo()
        self.assertEqual(esp32.DEVKIT, T["nomes"])
        self.assertEqual(gpios(esp32.SO_ENTRADA), set(E["so_entrada"]))
        self.assertEqual(gpios(esp32.BOOT), set(E["boot"]))
        self.assertEqual(gpios(esp32.FLASH), set(E["flash"]))
        self.assertEqual(gpios(esp32.SERIAL), set(E["serial"]))
        self.assertEqual(gpios(esp32.PSRAM), set(E["psram"]))
        self.assertEqual(gpios(esp32.ADC1), set(E["adc1"]))
        self.assertEqual(esp32.ATTEN_FAIXA[3], (E["adc_min"], E["adc_max"]))


if __name__ == "__main__":
    unittest.main()
