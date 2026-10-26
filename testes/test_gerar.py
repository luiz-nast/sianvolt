"""o gerador (gerar.py): o que o placa.txt aceita e recusa, as nets, e o formato dos arquivos de fábrica"""
import inspect
import json
import math
import re
import shutil
import tempfile
import unittest
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

from apoio import PLACAS, modelo
import geometria
import gerar
from biblioteca import BIBLIOTECA
from letras import tracos

LANTERNA = (PLACAS / "lanterna" / "placa.txt").read_text()
# o DevKit de verdade com o LED no GPIO32 (U1.6); R1 e D1 embaixo da fileira de baixo, longe da antena
DEVKIT = """placa 70 45
furos cantos 3.2
peca U1 devkit_esp32_30 37 24
peca R1 resistor_axial 24.84 5 220
peca D1 led_5mm 14 5
liga U1.6 R1.2
liga R1.1 D1.1
liga D1.2 GND
"""


def longe_da_zona(trilhas, vias, z):
    """a menor distância (mm) de uma trilha ou via até o retângulo z = (x0, y0, x1, y1); negativa = entrou nele"""
    ret = (("ret", *z), 0)
    d = [geometria.distancia((("seg", (t["x1"], t["y1"]), (t["x2"], t["y2"])), t["largura"] / 2), ret) for t in trilhas]
    d += [geometria.distancia((("seg", (v["x"], v["y"]), (v["x"], v["y"])), v["d"] / 2), ret) for v in vias]
    return min(d)


def riscos(gerber):
    """os pedaços de linha de um Gerber: {(x1, y1, x2, y2)} em milionésimos de mm"""
    return set(re.findall(r"^X(-?\d+)Y(-?\d+)D02\*\nX(-?\d+)Y(-?\d+)D01\*$", gerber, re.M))


def no_gerber(a, b):
    return tuple(str(round(v * 1e6)) for v in (*a, *b))


class LeOTxt(unittest.TestCase):
    def erro(self, texto, trecho, linha=None):
        with self.assertRaises(gerar.ErroTxt) as c:
            gerar.ler(texto)
        self.assertIn(trecho, c.exception.msg)
        if linha:
            self.assertEqual(c.exception.linha, linha)

    def test_comando_desconhecido_diz_a_linha(self):
        self.erro("placa 10 10\npeça R1 resistor 1 1", "comando desconhecido", 2)

    def test_quantidade_de_valores(self):
        self.erro("placa 10", "espera 2 valores")
        self.erro("placa 10 10\npeca R1 resistor 1", "espera 4 ou 5 valores")
        self.erro("placa 10 10\nliga R1.1", "espera 2 valores")

    def test_sem_placa(self):
        self.erro("peca R1 resistor 1 1", "falta a linha 'placa")

    def test_ref_repetida_e_nome_ruim(self):
        self.erro("placa 10 10\npeca R1 resistor 1 1\npeca R1 resistor 2 2", "já existe na linha 2", 3)
        self.erro("placa 10 10\npeca 1R resistor 1 1", "não serve de nome")
        self.erro("placa 10 10\npeca R-1 resistor 1 1", "não serve de nome")
        self.erro("placa 10 10\nliga R1.1.2 GND", "devia ser REF.PINO")

    def test_numero_e_valor(self):
        self.erro("placa dez 10", "devia ser um número")
        self.erro("placa 10 10\npeca R1 resistor 1 1 abc", "devia ser um valor")
        self.erro("placa 10 10\npeca R1 resistor 1 1 0", "maior que zero")
        for txt, ohms in (("100", 100), ("4.7k", 4700), ("10k", 10000), ("1M", 1e6), ("220R", 220), ("330Ω", 330)):
            self.assertAlmostEqual(gerar.valor(txt, 1), ohms, msg=txt)

    def test_comentario_e_linha_vazia(self):
        lido = gerar.ler("# só comentário\n\nplaca 10 10   # fim de linha\n")
        self.assertEqual(lido["placa"]["w"], 10)


class Monta(unittest.TestCase):
    def test_lanterninha(self):
        m = modelo(LANTERNA)
        self.assertEqual([p["ref"] for p in m["pecas"]], ["BT1", "SW1", "R1", "D1"])
        nets = {f"{p['ref']}.{q['n']}": q["net"] for p in m["pecas"] for q in p["pinos"]}
        self.assertEqual(nets["BT1.1"], "VBAT")
        self.assertEqual(nets["BT1.2"], "GND")
        self.assertEqual(nets["D1.2"], "GND")
        self.assertEqual(nets["SW1.1"], nets["SW1.2"], "lado A do botão é um só por dentro")
        self.assertEqual(nets["SW1.3"], nets["R1.1"])
        self.assertNotEqual(nets["SW1.1"], nets["SW1.3"])
        self.assertEqual(len(m["trilhas"]), 4)
        self.assertTrue(m["simulacao"]["pode"])
        self.assertTrue(m["fabrica"]["pronta"])

    def test_tipo_que_nao_existe(self):
        with self.assertRaises(gerar.ErroTxt) as c:
            modelo("placa 10 10\npeca R1 resistor_de_ouro 1 1")
        self.assertEqual(c.exception.onde, ["R1"])

    def test_pino_que_nao_existe(self):
        with self.assertRaises(gerar.ErroTxt) as c:
            modelo(LANTERNA + "\nliga R1.9 GND")
        self.assertIn("não tem pino 9", c.exception.msg)

    def test_curto_entre_nets_com_nome(self):
        with self.assertRaises(gerar.ErroTxt) as c:
            modelo(LANTERNA + "\nliga BT1.1 GND")
        self.assertIn("curto", c.exception.msg)

    def test_nome_automatico_nao_pisa_no_do_luiz(self):
        m = modelo(LANTERNA + "\nliga SW1.4 N1")   # o Luiz chamou uma net de N1
        nomes = {q["net"] for p in m["pecas"] for q in p["pinos"] if q["net"]}
        self.assertIn("N1", nomes)
        self.assertEqual(len([n for n in nomes if n.startswith("N")]), len({n for n in nomes if n.startswith("N")}))

    def test_resistor_sem_valor_nao_simula(self):
        m = modelo(LANTERNA.replace("43 15 100", "43 15"))
        self.assertFalse(m["simulacao"]["pode"])
        self.assertEqual(m["simulacao"]["sem_valor"], ["R1"])

    def test_peca_de_exemplo_trava_a_fabrica(self):
        m = modelo("placa 30 20\npeca R1 resistor 10 10 100\npeca D1 led 20 10\nliga R1.2 D1.1")
        self.assertFalse(m["fabrica"]["pronta"])
        self.assertEqual(sorted(m["fabrica"]["falta_datasheet"]), ["D1", "R1"])


class ArquivosDeFabrica(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saida = Path(tempfile.mkdtemp(prefix="sianvolt-gerber-"))
        cls.m = modelo(LANTERNA)
        cls.nomes = gerar.escrever(cls.m, cls.saida)

    def test_os_8_arquivos_no_padrao_do_kicad(self):
        self.assertEqual(sorted(self.nomes), sorted([
            "placa-Edge_Cuts.gbr", "placa-F_Cu.gbr", "placa-B_Cu.gbr", "placa-F_Mask.gbr", "placa-B_Mask.gbr",
            "placa-F_Silkscreen.gbr", "placa-PTH.drl", "placa-NPTH.drl"]))

    def test_gerber_bem_formado(self):
        for nome in self.nomes:
            if not nome.endswith(".gbr"):
                continue
            t = (self.saida / nome).read_text()
            self.assertIn("%FSLAX46Y46*%", t, nome)
            self.assertIn("%MOMM*%", t, nome)
            self.assertTrue(t.rstrip().endswith("M02*"), nome)
            definidas = set(re.findall(r"%ADD(\d+)", t))
            usadas = set(re.findall(r"^D(\d+)\*$", t, re.M))
            self.assertTrue(usadas <= definidas, f"{nome}: abertura usada sem definir {usadas - definidas}")
            self.assertTrue(all(int(d) >= 10 for d in definidas), nome)
            for x, y in re.findall(r"X(-?\d+)Y(-?\d+)D0[123]", t):
                self.assertTrue(0 <= int(x) <= 52e6 and 0 <= int(y) <= 34e6, f"{nome}: ponto fora da placa")
        self.assertIn("Negative", (self.saida / "placa-F_Mask.gbr").read_text())

    def test_excellon_bem_formado(self):
        for nome in ("placa-PTH.drl", "placa-NPTH.drl"):
            linhas = (self.saida / nome).read_text().split("\n")
            self.assertEqual(linhas[0], "M48")
            self.assertIn("METRIC,TZ", linhas)
            self.assertLess(linhas.index("G90"), linhas.index("%"), "G90 tem que vir antes do %")
            self.assertEqual([l for l in linhas if l][-1], "M30")
        pth = (self.saida / "placa-PTH.drl").read_text()
        self.assertEqual(len(re.findall(r"^X", pth, re.M)), sum(len(p["pinos"]) for p in self.m["pecas"]))

    def test_gerbonara_le_sem_aviso(self):
        try:
            from gerbonara import LayerStack
        except ImportError:
            self.skipTest("gerbonara só no .venv")
        import testar
        with warnings.catch_warnings(record=True) as avisos:
            warnings.simplefilter("always")
            LayerStack.open_dir(self.saida, autoguess=False, overrides=testar.MAPA_GERBER)
        self.assertEqual(avisos, [])


class Roteador(unittest.TestCase):
    """o caminho das trilhas: reta quando dá, desvio (L, Z) ou troca de camada por via quando não dá"""

    def pino(self, x, y, net, furo=0.8, d=1.6):
        return {"x": x, "y": y, "net": net, "furo": furo, "pad": {"forma": "C", "d": d}}

    def folga_minima(self, trilhas, vias, pinos):
        import geometria
        menor = 99
        for t in trilhas:
            c = (("seg", (t["x1"], t["y1"]), (t["x2"], t["y2"])), t["largura"] / 2)
            for nome, p in pinos.items():
                if p["net"] != t["net"] and (p["furo"] or t["lado"] == "cima"):
                    menor = min(menor, geometria.distancia(c, geometria.do_pad(p["x"], p["y"], p["pad"])))
        return menor

    def test_lanterninha_continua_reta_e_em_cima(self):
        m = modelo(LANTERNA)
        self.assertEqual([(t["de"], t["ate"], t["lado"]) for t in m["trilhas"]],
                         [("BT1.1", "SW1.1", "cima"), ("SW1.3", "R1.1", "cima"), ("R1.2", "D1.1", "cima"), ("D1.2", "BT1.2", "cima")])
        self.assertEqual(m["vias"], [])

    def test_pad_de_furo_no_caminho_faz_desviar(self):
        pinos = {"A.1": self.pino(5, 10, "N1"), "B.1": self.pino(25, 10, "N1"), "X.1": self.pino(15, 10, "N2", d=2)}
        trilhas, vias = gerar.rotear([("A.1", "B.1", 1)], pinos, [], 30, 20)
        self.assertGreater(len(trilhas), 1)
        self.assertGreaterEqual(self.folga_minima(trilhas, vias, pinos), gerar.FOLGA_ROTA - 1e-9)
        self.assertEqual((trilhas[0]["x1"], trilhas[0]["y1"]), (5, 10))
        self.assertEqual((trilhas[-1]["x2"], trilhas[-1]["y2"]), (25, 10))

    def test_pad_de_superficie_no_caminho_passa_por_baixo(self):
        pinos = {"A.1": self.pino(5, 10, "N1"), "B.1": self.pino(25, 10, "N1"), "X.1": self.pino(15, 10, "N2", furo=None, d=2)}
        trilhas, vias = gerar.rotear([("A.1", "B.1", 1)], pinos, [], 30, 20)
        self.assertEqual([(t["lado"], t["y1"], t["y2"]) for t in trilhas], [("baixo", 10, 10)], "reta por baixo, sem via")

    def test_ponta_de_superficie_nao_comeca_embaixo(self):
        pinos = {"A.1": self.pino(5, 10, "N1", furo=None), "B.1": self.pino(25, 10, "N1"), "X.1": self.pino(15, 10, "N2", furo=None, d=2)}
        trilhas, vias = gerar.rotear([("A.1", "B.1", 1)], pinos, [], 30, 20)
        self.assertEqual(trilhas[0]["lado"], "cima")
        self.assertGreaterEqual(self.folga_minima(trilhas, vias, pinos), gerar.FOLGA_ROTA - 1e-9)
        for v in vias:
            self.assertGreaterEqual(math.dist((v["x"], v["y"]), (15, 10)), 1 + gerar.VIA_PAD / 2)

    def test_parede_sem_saida_fica_a_reta(self):
        pinos = {"A.1": self.pino(5, 10, "N1"), "B.1": self.pino(25, 10, "N1")}
        for i, y in enumerate(range(0, 21)):   # uma parede de pads de outra net de cima a baixo
            pinos[f"X.{i}"] = self.pino(15, y, "N2", d=1.4)
        trilhas, _, falhas = gerar.rotear_uma_vez([("A.1", "B.1", 1)], pinos, [], 30, 20)
        self.assertEqual(len(falhas), 1)
        self.assertEqual([(t["x1"], t["x2"], t["lado"]) for t in trilhas], [(5, 25, "cima")])

    def test_parede_de_superficie_faz_trocar_de_lado_e_o_gerber_mostra(self):
        # A e B são de superfície (só têm cobre em cima) e uma parede de pads de superfície fecha o lado de cima inteiro:
        # o único caminho é descer por uma via, passar por baixo da parede e subir por outra
        linhas = ["placa 30 20", "peca A resistor 5 10", "peca B resistor 25 10", "liga A.2 B.1"]
        linhas += [f"peca W{i} resistor 15 {1.5 + 1.6 * i:.1f}" for i in range(11)]
        m = modelo("\n".join(linhas))
        self.assertEqual(len(m["vias"]), 2)
        self.assertEqual([t["lado"] for t in m["trilhas"]][0], "cima")
        self.assertEqual([t["lado"] for t in m["trilhas"]][-1], "cima")
        self.assertIn("baixo", [t["lado"] for t in m["trilhas"]])
        import testar
        self.assertEqual(testar.pares_perto(m, testar.ESPACO_MIN), [], "nada perto demais em nenhuma camada")
        saida = Path(tempfile.mkdtemp(prefix="sianvolt-via-"))
        gerar.escrever(m, saida)
        embaixo = (saida / "placa-B_Cu.gbr").read_text()
        self.assertGreaterEqual(embaixo.count("D01*"), sum(1 for t in m["trilhas"] if t["lado"] == "baixo"))
        furos = (saida / "placa-PTH.drl").read_text()
        for v in m["vias"]:
            self.assertIn(f"X{v['x']:.3f}Y{v['y']:.3f}", furos)
            self.assertIn(f"X{round(v['x'] * 1e6)}Y{round(v['y'] * 1e6)}D03", embaixo)
            self.assertNotIn(f"X{round(v['x'] * 1e6)}Y{round(v['y'] * 1e6)}D03", (saida / "placa-F_Mask.gbr").read_text(),
                             "via fica coberta pela máscara")
        try:
            from gerbonara import LayerStack
            import warnings
            with warnings.catch_warnings(record=True) as avisos:
                warnings.simplefilter("always")
                LayerStack.open_dir(saida, autoguess=False, overrides=testar.MAPA_GERBER)
            self.assertEqual(avisos, [])
        except ImportError:
            pass


class Antena(unittest.TestCase):
    """a zona da antena do DevKit é proibida pro roteador: nenhuma trilha (nas duas camadas) nem via entra nela"""
    ZONA = (15, 10, 25, 30)

    def pino(self, x, y, net, d=1.6):
        return {"x": x, "y": y, "net": net, "furo": 0.8, "pad": {"forma": "C", "d": d}}

    def test_antena_no_meio_do_caminho_faz_dar_a_volta(self):
        pinos = {"A.1": self.pino(5, 20, "N1"), "B.1": self.pino(35, 20, "N1")}
        sem, _ = gerar.rotear([("A.1", "B.1", 1)], pinos, [], 40, 40)
        self.assertLess(longe_da_zona(sem, [], self.ZONA), 0, "sem a zona, a reta passaria por cima da antena")
        trilhas, vias, falhas = gerar.rotear_uma_vez([("A.1", "B.1", 1)], pinos, [], 40, 40, [self.ZONA])
        self.assertEqual(falhas, [], "tem lugar pra dar a volta")
        self.assertGreaterEqual(longe_da_zona(trilhas, vias, self.ZONA), gerar.FOLGA_ROTA - 1e-9)
        self.assertEqual((trilhas[0]["x1"], trilhas[0]["y1"]), (5, 20))
        self.assertEqual((trilhas[-1]["x2"], trilhas[-1]["y2"]), (35, 20))
        for t, u in zip(trilhas, trilhas[1:]):   # um caminho só, sem buraco
            self.assertEqual((t["x2"], t["y2"]), (u["x1"], u["y1"]))
        self.assertEqual(gerar.rotear([("A.1", "B.1", 1)], pinos, [], 40, 40, proibidas=[self.ZONA]), (trilhas, vias))

    def test_so_cabia_pela_antena_falha_sem_entrar_nela(self):
        # paredes de pads de outra net em cima e embaixo da zona: o único caminho livre seria pela antena
        pinos = {"A.1": self.pino(5, 20, "N1"), "B.1": self.pino(35, 20, "N1")}
        for i, y in enumerate([*range(0, 8), *range(33, 41)]):
            pinos[f"X.{i}"] = self.pino(20, y, "N2", d=1.4)
        zona = (15, 8, 25, 32)
        trilhas, vias, falhas = gerar.rotear_uma_vez([("A.1", "B.1", 1)], pinos, [], 40, 40, [zona])
        self.assertEqual(len(falhas), 1)
        self.assertGreaterEqual(longe_da_zona(trilhas, vias, zona), gerar.FOLGA_ROTA - 1e-9, "mesmo falhando, fica fora da antena")
        parede = [geometria.do_pad(p["x"], p["y"], p["pad"]) for n, p in pinos.items() if n.startswith("X.")]
        encosta = min(geometria.distancia((("seg", (t["x1"], t["y1"]), (t["x2"], t["y2"])), t["largura"] / 2), c)
                      for t in trilhas for c in parede)
        self.assertLess(encosta, 0, "a falha aparece como curto na etapa 3")

    def test_ponta_fora_da_placa_falha_sem_entrar_na_antena(self):
        # o pad de A ficou fora da placa: nenhum caminho passa, e o que sobra no desenho não pode ser a reta pela antena
        pinos = {"A.1": self.pino(-0.05, 20, "N1"), "B.1": self.pino(35, 20, "N1")}
        reta = [{"x1": -0.05, "y1": 20, "x2": 35, "y2": 20, "largura": gerar.TRILHA}]
        self.assertLess(longe_da_zona(reta, [], self.ZONA), 0, "o teste só vale se a reta cruzar a antena")
        trilhas, vias, falhas = gerar.rotear_uma_vez([("A.1", "B.1", 1)], pinos, [], 40, 40, [self.ZONA])
        self.assertEqual(len(falhas), 1)
        self.assertGreaterEqual(longe_da_zona(trilhas, vias, self.ZONA), gerar.FOLGA_ROTA - 1e-9)

    def test_falha_prefere_ficar_na_placa(self):
        # a zona vai quase até a borda de cima e uma parede fecha o caminho de baixo: nada passa. Por cima da zona
        # é mais curto, mas sai da placa (y 40,2); o desenho fica com o de baixo, dentro da placa (a etapa 3 acusa o curto)
        zona = (15, 10, 25, 39.5)
        pinos = {"A.1": self.pino(5, 30, "N1"), "B.1": self.pino(35, 30, "N1")}
        pinos.update({f"X.{i}": self.pino(20, i, "N2", d=1.4) for i in range(10)})
        trilhas, vias, falhas = gerar.rotear_uma_vez([("A.1", "B.1", 1)], pinos, [], 40, 40, [zona])
        self.assertEqual(len(falhas), 1)
        self.assertTrue(all(0 <= v <= 40 for t in trilhas for v in (t["y1"], t["y2"])), "dentro da placa")
        self.assertGreaterEqual(longe_da_zona(trilhas, vias, zona), gerar.FOLGA_ROTA - 1e-9)

    def test_via_tambem_fica_longe_da_zona(self):
        # A e B de superfície logo acima da zona, com uma parede de superfície entre eles: desce por via, passa por
        # baixo e sobe. Em y 30,5 a trilha caberia (0,35 mm da zona), mas a via, mais larga, ficaria a 0,1 mm
        pinos = {"A.1": {**self.pino(19, 32, "N1"), "furo": None}, "B.1": {**self.pino(21.6, 32, "N1"), "furo": None}}
        pinos.update({f"X.{i}": {**self.pino(20.3, i, "N2", d=1.4), "furo": None} for i in range(41)})
        trilhas, vias, falhas = gerar.rotear_uma_vez([("A.1", "B.1", 1)], pinos, [], 40, 40, [self.ZONA])
        self.assertEqual(falhas, [])
        self.assertEqual(len(vias), 2)
        self.assertGreaterEqual(longe_da_zona([], vias, self.ZONA), gerar.FOLGA_ROTA - 1e-9)

    def test_sem_zona_a_falha_continua_a_reta(self):
        pinos = {"A.1": self.pino(-0.05, 20, "N1"), "B.1": self.pino(35, 20, "N1")}
        trilhas, vias, falhas = gerar.rotear_uma_vez([("A.1", "B.1", 1)], pinos, [], 40, 40)
        self.assertEqual(len(falhas), 1)
        self.assertEqual([(t["x1"], t["y1"], t["x2"], t["y2"], t["lado"]) for t in trilhas], [(-0.05, 20, 35, 20, "cima")])

    def test_peca_encostada_na_antena_liga_sem_entrar(self):
        # A a 0,1 mm da zona (menos que a FOLGA_ROTA): a ligação não falha, e a trilha não chega mais perto que A
        pinos = {"A.1": self.pino(14.75, 20, "N1"), "B.1": self.pino(35, 20, "N1")}
        trilhas, vias, falhas = gerar.rotear_uma_vez([("A.1", "B.1", 1)], pinos, [], 40, 40, [self.ZONA])
        self.assertEqual(falhas, [])
        self.assertAlmostEqual(longe_da_zona(trilhas, vias, self.ZONA), 0.25 - gerar.TRILHA / 2, places=6)

    def test_peca_dentro_da_antena_liga_sem_falhar(self):
        # A dentro da zona: a zona não vale pra essa ligação (a etapa 3 avisa da peça na antena), mas as outras continuam
        # sem poder entrar, e via nunca entra
        pinos = {"A.1": self.pino(16, 20, "N1"), "B.1": self.pino(35, 20, "N1"),
                 "C.1": self.pino(5, 15, "N2"), "D.1": self.pino(35, 15, "N2")}
        trilhas, vias, falhas = gerar.rotear_uma_vez([("A.1", "B.1", 1), ("C.1", "D.1", 2)], pinos, [], 40, 40, [self.ZONA])
        self.assertEqual(falhas, [])
        outra = [t for t in trilhas if t["net"] == "N2"]
        self.assertGreaterEqual(longe_da_zona(outra, [], self.ZONA), gerar.FOLGA_ROTA - 1e-9)
        for v in vias:
            self.assertGreaterEqual(longe_da_zona([], [v], self.ZONA), gerar.FOLGA_ROTA - 1e-9)

    def test_resistor_dentro_da_antena_do_devkit_liga_sem_curto(self):
        m = modelo("placa 80 50\npeca U1 devkit_esp32_30 45 25\npeca R1 resistor_axial 27 25 220\n"
                   "liga R1.2 U1.30\nliga R1.1 GND")
        x0, y0, x1, y1 = gerar.zona(m["pecas"][0], "antena")
        r1 = {q["n"]: q for q in m["pecas"][1]["pinos"]}
        self.assertTrue(x0 < r1["1"]["x"] < x1 and y0 < r1["1"]["y"] < y1, "R1.1 dentro da antena")
        import testar
        self.assertEqual(testar.pares_perto(m, 0), [], "nenhum curto: a etapa 3 só avisa da antena")
        self.assertEqual(testar.nets_partidas(m, BIBLIOTECA), {})

    def test_devkit_na_placa_desvia_da_antena(self):
        # R1 do lado da antena ligado no D23 (U1.30): a reta de R1.2 até o pino passaria pela antena
        m = modelo("placa 80 50\npeca U1 devkit_esp32_30 45 25\npeca R1 resistor_axial 9 25 220\n"
                   "liga R1.2 U1.30\nliga R1.1 GND")
        u1 = m["pecas"][0]
        antena = gerar.zona(u1, "antena")
        self.assertEqual(antena, (19.1, 16.0, 25.91, 34.0))
        pinos = {f"{p['ref']}.{q['n']}": q for p in m["pecas"] for q in p["pinos"]}
        reta = [{"x1": pinos["R1.2"]["x"], "y1": pinos["R1.2"]["y"], "x2": pinos["U1.30"]["x"], "y2": pinos["U1.30"]["y"], "largura": gerar.TRILHA}]
        self.assertLess(longe_da_zona(reta, [], antena), 0, "o teste só vale se a reta cruzar a antena")
        self.assertGreaterEqual(longe_da_zona(m["trilhas"], m["vias"], antena), gerar.FOLGA_ROTA - 1e-9)
        import testar
        self.assertEqual(testar.pares_perto(m, 0), [], "nenhum curto")
        self.assertEqual(testar.nets_partidas(m, BIBLIOTECA), {})

    def test_zona_do_modelo_lido_do_json(self):
        m = json.loads(json.dumps(modelo(DEVKIT)))   # como a bancada e o testes.json veem: tupla vira lista
        self.assertEqual(gerar.zona(m["pecas"][0], "antena"), (11.1, 15.0, 17.91, 33.0))
        self.assertEqual(gerar.zona(m["pecas"][0], "usb"), (57.6, 19.55, 64.3, 28.45))
        self.assertIsNone(gerar.zona(m["pecas"][1], "antena"))


class ComODevKit(unittest.TestCase):
    """o DevKit de 30 pinos (devkit_esp32_30) na placa: simulação, fábrica, campos do tipo, serigrafia e a folha 1:1"""

    @classmethod
    def setUpClass(cls):
        cls.saida = Path(tempfile.mkdtemp(prefix="sianvolt-devkit-"))
        cls.m = modelo(DEVKIT)
        cls.u1 = cls.m["pecas"][0]
        cls.nomes = gerar.escrever(cls.m, cls.saida)
        cls.silk = (cls.saida / "placa-F_Silkscreen.gbr").read_text()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.saida, ignore_errors=True)

    def test_liga_no_papel_e_vai_pra_fabrica(self):
        self.assertEqual(self.m["simulacao"], {"pode": True, "falta_modelo": [], "sem_valor": [], "soltos": []})
        self.assertEqual(self.m["fabrica"], {"pronta": True, "falta_datasheet": [], "falta_conferir": []})
        self.assertEqual(sum(1 for q in self.u1["pinos"] if q["net"] is None), 27, "só o GPIO32 e os 2 GND têm net")

    def test_pino_solto_das_outras_pecas_continua_travando(self):
        m = modelo(DEVKIT.replace("liga R1.1 D1.1\n", "liga D1.1 U1.7\n"))   # R1.1 ficou sem nada
        self.assertFalse(m["simulacao"]["pode"])
        self.assertEqual(m["simulacao"]["soltos"], ["R1"])

    def test_campos_do_tipo_vao_pra_peca(self):
        tipo = BIBLIOTECA["devkit_esp32_30"]
        for campo in ("serigrafia", "cuidados", "zonas", "confira", "acompanha"):
            self.assertEqual(self.u1[campo], tipo[campo], campo)
        self.assertEqual(self.u1["cuidados"]["15"], "VIN: não soldar")
        for p in self.m["pecas"][1:]:   # o tipo não tem: a peça não ganha a chave
            self.assertFalse(set(gerar.DO_TIPO) & set(p), p["ref"])
        lido = json.loads((self.saida / "modelo.json").read_text())
        self.assertEqual(lido["pecas"][0]["acompanha"][0]["codigo"], "C41417327")

    def test_serigrafia_tem_o_contorno(self):
        tem = riscos(self.silk)
        borda = gerar.borda(self.u1)
        self.assertEqual(borda[0], (37 - 25.9, 24 - 14.1))
        for a, b in zip(borda, borda[1:]):
            self.assertIn(no_gerber(a, b), tem, f"lado do corpo {a} → {b}")
        x0, y0, x1, y1 = gerar.zona(self.u1, "antena")
        for a, b in (((x1, y0), (x1, y1)), ((x1, y1), (x0, y1))):
            self.assertIn(no_gerber(a, b), tem, "o retângulo da antena")

    def test_serigrafia_tem_os_textos(self):
        textos = {t[0]: t for t in gerar.textos_da_peca(self.u1)}
        self.assertEqual(set(textos), {"ANTENA", "USB", "VIN NAO SOLDAR"})
        self.assertEqual(gerar.so_letras("VIN: não soldar"), "VIN NAO SOLDAR")
        tem = riscos(self.silk)
        for texto, x, y, em_pe in textos.values():
            for pontos in gerar.texto_na_placa(texto, x, y, em_pe):
                for a, b in zip(pontos, pontos[1:] or pontos):
                    self.assertIn(no_gerber(a, b), tem, texto)
        # 'USB' deitado, letra por letra com a fonte da serigrafia, no meio da parte do USB em cima do corpo
        _, x, y, em_pe = textos["USB"]
        self.assertFalse(em_pe)
        self.assertAlmostEqual(x, 37 + (20.6 + 25.9) / 2)
        for pontos in tracos("USB", x, y - gerar.LETRA / 2, gerar.LETRA):
            self.assertIn(no_gerber(pontos[0], pontos[1]), tem)
        # 'ANTENA' em pé dentro da zona da antena; o aviso do VIN começa do lado do pino 15
        _, x, y, em_pe = textos["ANTENA"]
        x0, y0, x1, y1 = gerar.zona(self.u1, "antena")
        self.assertTrue(em_pe and x0 < x < x1 and y0 < y < y1)
        vin = next(q for q in self.u1["pinos"] if q["n"] == "15")
        _, x, y, em_pe = textos["VIN NAO SOLDAR"]
        self.assertTrue(em_pe)
        self.assertAlmostEqual(y - gerar.comprimento("VIN NAO SOLDAR") / 2, vin["y"] - gerar.LETRA / 2, places=3)
        self.assertTrue(0 < x - vin["x"] < 2, "do lado do pino")

    def test_texto_nao_encosta_em_pad_nem_sai_do_corpo(self):
        w, h = self.m["placa"]["w"], self.m["placa"]["h"]
        pads = [geometria.do_pad(q["x"], q["y"], q["pad"]) for p in self.m["pecas"] for q in p["pinos"]]
        corpo = (37 - 25.9, 24 - 14.1, 37 + 25.9, 24 + 14.1)
        for texto, x, y, em_pe in gerar.textos_da_peca(self.u1):
            for pontos in gerar.texto_na_placa(texto, x, y, em_pe):
                for a, b in zip(pontos, pontos[1:] or pontos):
                    risco = (("seg", a, b), gerar.LETRA_LINHA / 2)
                    self.assertGreaterEqual(min(geometria.distancia(risco, c) for c in pads), gerar.SILK_PAD, texto)
                    self.assertTrue(all(corpo[0] < v[0] < corpo[2] and corpo[1] < v[1] < corpo[3] for v in (a, b)), texto)
                    self.assertTrue(all(0 < v[0] < w and 0 < v[1] < h for v in (a, b)))

    def test_lanterna_nao_ganha_texto_nem_zona(self):
        m = modelo(LANTERNA)
        self.assertEqual([t for p in m["pecas"] for t in gerar.textos_da_peca(p)], [])
        self.assertEqual([gerar.zona(p, "antena") for p in m["pecas"]], [None] * 4)

    def test_devkit_rente_a_borda_ainda_tem_o_contorno(self):
        # o USB na borda da direita (como os projetos pedem): o pedaço de fora da placa some, o resto fica
        m = modelo("placa 56 40\npeca U1 devkit_esp32_30 30.1 20")
        compridos = [(a, b) for g, a, b in gerar.tracos_da_serigrafia(m)
                     if g == gerar.SILK and abs(a[1] - b[1]) < 1e-9 and abs(a[0] - b[0]) > 50]
        self.assertEqual(sorted(round(a[1], 3) for a, b in compridos), [5.9, 34.1], "os lados de cima e de baixo do corpo")
        for g, a, b in gerar.tracos_da_serigrafia(m):
            self.assertTrue(all(g / 2 - 1e-9 <= v[0] <= 56 - g / 2 + 1e-9 for v in (a, b)), "nada fora da placa")

    def test_antena_passando_da_borda_escreve_so_na_placa(self):
        # a ponta da antena pra fora da placa (o que a Espressif prefere): 'ANTENA' vai pra parte que ficou na placa,
        # inteiro; se essa parte não cabe nem a letra em pé, fica sem o texto (e sem pedaço de letra)
        for x, tem in ((21.9, True), (19.9, False)):   # a borda do DevKit 4 mm e 6 mm pra fora da placa
            m = modelo(f"placa 60 40\npeca U1 devkit_esp32_30 {x} 20")
            u1 = m["pecas"][0]
            textos = {t[0]: t for t in gerar.textos_da_peca(u1, (60, 40))}
            self.assertEqual("ANTENA" in textos, tem, x)
            self.assertEqual(set(textos) - {"ANTENA"}, {"USB", "VIN NAO SOLDAR"})
            if tem:
                _, tx, ty, em_pe = textos["ANTENA"]
                x1 = gerar.zona(u1, "antena")[2]
                for pontos in gerar.texto_na_placa("ANTENA", tx, ty, em_pe):
                    self.assertTrue(all(gerar.LETRA_LINHA / 2 <= v[0] <= x1 - gerar.LETRA_LINHA / 2 for v in pontos))
            letras = [(a, b) for g, a, b in gerar.tracos_da_serigrafia(m) if g == gerar.LETRA_LINHA and max(a[0], b[0]) < 3]
            self.assertEqual(bool(letras), tem, "pedaço de letra perto da borda só quando o texto cabe inteiro")
        self.assertEqual(len(gerar.textos_da_peca(u1)), 3, "sem a placa, conta a zona inteira em cima do corpo")

    def test_gerbonara_le_a_serigrafia_sem_aviso(self):
        try:
            from gerbonara import LayerStack
        except ImportError:
            self.skipTest("gerbonara só no .venv")
        import testar
        with warnings.catch_warnings(record=True) as avisos:
            warnings.simplefilter("always")
            LayerStack.open_dir(self.saida, autoguess=False, overrides=testar.MAPA_GERBER)
        self.assertEqual(avisos, [])

    def test_folha_pra_imprimir_em_tamanho_real(self):
        self.assertNotIn(gerar.FOLHA, self.nomes, "a folha não vai no fabrica.zip")
        self.assertEqual(len(self.nomes), 8)
        texto = (self.saida / gerar.FOLHA).read_text(encoding="utf-8")
        self.assertIn("imprima em 100%, sem ajustar à página; meça a régua antes", texto)
        svg = ET.fromstring(texto.encode())
        ns = {"s": "http://www.w3.org/2000/svg"}
        largura, altura = svg.get("width"), svg.get("height")
        self.assertTrue(largura.endswith("mm") and altura.endswith("mm"))
        self.assertEqual([float(largura[:-2]), float(altura[:-2])], [float(v) for v in svg.get("viewBox").split()[2:]],
                         "1 unidade do desenho = 1 mm: imprime em tamanho real")
        placa = svg.find(".//s:rect[@id='placa']", ns)
        self.assertEqual((float(placa.get("width")), float(placa.get("height"))), (70, 45), "a placa com as medidas dela")
        regua = svg.find(".//s:g[@id='regua']", ns).findall("s:line", ns)
        self.assertEqual(float(regua[0].get("x2")) - float(regua[0].get("x1")), gerar.REGUA)
        self.assertEqual(gerar.REGUA, 50)
        self.assertEqual(len(regua), 1 + 51, "a linha e um traço por mm, de 0 a 50")
        x0 = float(placa.get("x"))
        furos = [(float(c.get("cx")) - x0, float(c.get("cy"))) for c in svg.findall(".//s:circle[@stroke='#000']", ns)]
        esperados = gerar.furos_com_cobre(self.m) + self.m["furos"]
        self.assertEqual(len(furos), len(esperados), "todo furo da placa, com e sem cobre")
        y_placa = float(placa.get("y")) + 45   # o y do SVG cresce pra baixo
        for f, (x, y) in zip(esperados, furos):
            self.assertAlmostEqual(x, f["x"], places=3)
            self.assertAlmostEqual(y_placa - y, f["y"], places=3)
        self.assertGreater(len(svg.findall(".//s:path", ns)), 0, "a serigrafia")

    def test_toda_placa_ganha_a_folha(self):
        saida = Path(tempfile.mkdtemp(prefix="sianvolt-folha-"))
        try:
            nomes = gerar.escrever(modelo(LANTERNA), saida)
            self.assertTrue((saida / gerar.FOLHA).exists())
            self.assertEqual(len(nomes), 8)
            svg = ET.fromstring((saida / gerar.FOLHA).read_bytes())
            self.assertEqual(svg.get("width"), "120mm", "a placa de 52 mm cabe; a folha tem a frase de 100 mm e a margem")
        finally:
            shutil.rmtree(saida, ignore_errors=True)


class Assinaturas(unittest.TestCase):
    """o laboratório importa ler, montar e biblioteca: nem a assinatura nem o formato da volta mudam"""

    def test_assinaturas(self):
        self.assertEqual(str(inspect.signature(gerar.ler)), "(texto)")
        self.assertEqual(str(inspect.signature(gerar.biblioteca)), "(pasta=None)")
        params = inspect.signature(gerar.montar).parameters
        self.assertEqual(list(params), ["lido", "bib"])
        self.assertIs(params["bib"].default, BIBLIOTECA)

    def test_o_que_volta(self):
        lido = gerar.ler(DEVKIT)
        self.assertEqual(set(lido), {"placa", "furos", "pecas", "ligas", "linhas"})
        m = gerar.montar(lido, gerar.biblioteca())
        self.assertEqual(set(m), {"placa", "pecas", "trilhas", "vias", "furos", "fabrica", "simulacao", "compras", "linhas"})
        antes = {"ref", "tipo", "x", "y", "valor", "valor_txt", "linha", "nome", "explica", "exemplo", "pendente", "bloco",
                 "corpo", "desenho", "juntos", "eletrica", "compra", "loja", "pinos"}
        self.assertEqual(set(m["pecas"][1]), antes, "peça sem campo novo no tipo fica igual")
        self.assertEqual(set(m["pecas"][0]) - antes, set(gerar.DO_TIPO), "o DevKit só ganha os campos do tipo")
        self.assertEqual(gerar.biblioteca(), BIBLIOTECA)


class Versoes(unittest.TestCase):
    def test_frases_do_que_mudou(self):
        self.assertEqual(gerar.o_que_mudou(None, LANTERNA), "primeira versão")
        self.assertEqual(gerar.o_que_mudou(LANTERNA, LANTERNA + "\n# oi"), "só comentários")
        self.assertIn("moveu R1", gerar.o_que_mudou(LANTERNA, LANTERNA.replace("R1 resistor_axial 43 15", "R1 resistor_axial 40 15")))
        self.assertIn("trocou R1 pra 220 Ω", gerar.o_que_mudou(LANTERNA, LANTERNA.replace("43 15 100", "43 15 220")))
        self.assertIn("tirou o valor de R1", gerar.o_que_mudou(LANTERNA, LANTERNA.replace("43 15 100", "43 15")))
        self.assertIn("adicionou R2", gerar.o_que_mudou(LANTERNA, LANTERNA + "\npeca R2 resistor_axial 10 5 1k"))
        self.assertIn("desligou", gerar.o_que_mudou(LANTERNA, LANTERNA.replace("liga D1.2 GND\n", "")))
        self.assertEqual(gerar.o_que_mudou(LANTERNA, LANTERNA.replace("liga R1.2 D1.1", "liga D1.1 R1.2")), "só comentários",
                         "liga A B é o mesmo que liga B A")


if __name__ == "__main__":
    unittest.main()
