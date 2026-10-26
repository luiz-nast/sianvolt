"""os blocos do projeto e o catálogo: cada bloco tira a peça de uma categoria (ldr -> sensor_luz), e o nome bom
que a categoria dá nunca é trocado pelo nome genérico do bloco ("Olho de luz")"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from apoio import apagar, copia
import blocos
import catalogo
import loja

CATEGORIAS = ("sensor_luz", "buzzer_passivo", "resistor", "esp32")   # as que os testes daqui gravam (numa cópia)


def da_loja(e, codigo):
    """a peça do catálogo como a busca da loja devolve (loja.item)"""
    return {"codigo": codigo, "categoria": e["categoria_loja"],
            **{k: e[k] for k in ("modelo", "marca", "pacote", "descricao", "estoque", "preco", "minimo", "datasheet", "link", "atributos")}}


class Mapa(unittest.TestCase):
    def test_cada_bloco_tem_uma_categoria_que_existe(self):
        cat = catalogo.ler()
        self.assertEqual(set(blocos.CATEGORIA), set(blocos.BLOCOS))
        for bloco, cid in blocos.CATEGORIA.items():
            self.assertIn(cid, cat["categorias"], bloco)
            self.assertEqual(catalogo.categoria_de(bloco), cid)
        self.assertEqual((blocos.CATEGORIA["cerebro"], blocos.CATEGORIA["ldr"], blocos.CATEGORIA["buzzer"]),
                         ("placa_desenvolvimento", "sensor_luz", "buzzer_passivo"))
        self.assertEqual(catalogo.categoria_de("esp32"), "esp32", "categoria que não é bloco fica como está")
        self.assertNotIn("esp32", blocos.BLOCOS, "o bloco do ESP32 é o 'cerebro': 'esp32' é a categoria dos módulos")

    def test_nome_na_categoria_esp32_nao_muda(self):
        cat = catalogo.ler()
        pecas = [(c, e) for c, e in cat["pecas"].items() if e["categoria"] == "esp32"]
        self.assertGreater(len(pecas), 10)
        for codigo, e in pecas:
            como_loja = {**e, "codigo": codigo, "categoria": e["categoria_loja"]}
            self.assertEqual(catalogo.nome_da_peca(cat, "esp32", como_loja), e["nome"], codigo)
        self.assertEqual(catalogo.recalcular(cat, "esp32"), 0)

    def test_nome_da_loja_do_ldr_e_do_som_e_o_da_categoria(self):
        cat = catalogo.ler()
        for bloco, codigo, nome in (("ldr", "C10081", "LDR (fotorresistor) 8kΩ~20kΩ"),
                                    ("buzzer", "C128650", "Buzzer passivo 12.6mm, 4kHz")):
            item = da_loja(cat["pecas"][codigo], codigo)
            self.assertEqual(blocos.nome_da_loja(bloco, item), nome)
            self.assertEqual(catalogo.nome_da_peca(cat, bloco, item), nome, "o bloco vira a categoria dele")
            self.assertNotEqual(nome, blocos.BLOCOS[bloco]["nome"])


class NoCatalogo(unittest.TestCase):
    """grava numa cópia de algumas categorias: o catálogo de verdade não muda"""

    def setUp(self):
        self.original = catalogo.PASTA
        self.copia = Path(tempfile.mkdtemp(prefix="sianvolt-catalogo-"))
        for cid in CATEGORIAS:
            shutil.copy(self.original / f"{cid}.json", self.copia)
        catalogo.PASTA = self.copia
        self.cat = catalogo.ler()

    def tearDown(self):
        catalogo.PASTA = self.original
        shutil.rmtree(self.copia, ignore_errors=True)

    def test_adicionar_o_ldr_pelo_bloco_mantem_o_nome_bom(self):
        velha = json.loads(json.dumps(self.cat["pecas"]["C10081"]))
        item = da_loja(velha, "C10081")
        for categoria in ("ldr", "sensor_luz"):   # pelo nome do bloco ou da categoria, dá no mesmo
            self.assertEqual(catalogo.adicionar(self.cat, categoria, [item]), 0, "não é peça nova")
            e = self.cat["pecas"]["C10081"]
            self.assertEqual((e["categoria"], e["nome"]), ("sensor_luz", "LDR (fotorresistor) 8kΩ~20kΩ"), categoria)
            self.assertEqual(e["conferido"], velha["conferido"], "o conferido fica")
        catalogo.salvar(self.cat, [catalogo.categoria_de("ldr")])
        self.assertFalse((self.copia / "ldr.json").exists())
        self.assertEqual(catalogo.ler()["pecas"]["C10081"]["nome"], "LDR (fotorresistor) 8kΩ~20kΩ")

    def test_peca_nova_numa_categoria_que_existe_e_gravada(self):
        nova = {**da_loja(self.cat["pecas"]["C10081"], "C10081"), "codigo": "C900000001"}
        self.assertEqual(catalogo.adicionar(self.cat, "ldr", [nova]), 1)
        catalogo.salvar(self.cat, [self.cat["pecas"]["C900000001"]["categoria"]])
        e = catalogo.ler()["pecas"]["C900000001"]
        self.assertEqual((e["categoria"], e["nome"]), ("sensor_luz", "LDR (fotorresistor) 8kΩ~20kΩ"))
        with self.assertRaises(ValueError):   # o salvar não gravaria: a peça sumiria calada
            catalogo.adicionar(self.cat, "nao_existe", [nova])

    def test_quem_ja_esta_numa_categoria_fica_nela(self):
        nova = {**da_loja(self.cat["pecas"]["C10081"], "C10081")}
        catalogo.adicionar(self.cat, "esp32", [nova])
        e = self.cat["pecas"]["C10081"]
        self.assertEqual((e["categoria"], e["nome"]), ("sensor_luz", "LDR (fotorresistor) 8kΩ~20kΩ"),
                         "o nome sai das regras da categoria onde a peça mora")

    def test_nome_generico_nao_passa_por_cima_de_nome_bom(self):
        codigo = next(c for c, e in self.cat["pecas"].items() if e["categoria"] == "resistor" and e["nome"].startswith("Resistor "))
        bom = self.cat["pecas"][codigo]["nome"]
        sem_valor = da_loja(self.cat["pecas"][codigo], codigo)
        sem_valor["atributos"] = {k: v for k, v in sem_valor["atributos"].items() if k != "Resistance"}
        self.assertEqual(blocos.nome_da_loja("resistor", sem_valor), "Resistor", "a loja não disse o valor")
        catalogo.adicionar(self.cat, "resistor", [sem_valor])
        self.assertEqual(self.cat["pecas"][codigo]["nome"], bom)


class Importar(unittest.TestCase):
    """loja.importar sem rede: a ficha e o desenho saem do catálogo (numa cópia) e de um desenho à mão"""

    def setUp(self):
        self.original, self.guardado = catalogo.PASTA, (loja.ficha, loja.desenho, loja.pagina, loja.pedir)
        self.copia = Path(tempfile.mkdtemp(prefix="sianvolt-catalogo-"))
        for cid in CATEGORIAS:
            shutil.copy(self.original / f"{cid}.json", self.copia)
        catalogo.PASTA = self.copia
        cat = catalogo.ler()
        lcsc = {c: da_loja(e, c) for c, e in cat["pecas"].items() if e.get("loja", "LCSC") == "LCSC"}
        lcsc["C900000002"] = {**lcsc["C10081"], "codigo": "C900000002"}   # um LDR que o catálogo ainda não tem

        def sem_rede(*_a, **_k):
            raise AssertionError("o teste não vai na loja")
        loja.ficha = lambda codigo, validade=None: dict(lcsc[codigo])
        loja.desenho = lambda codigo: {"pacote": "teste", "silk": [], "corpo": [5.4, 4.6], "simbolo": {},
                                       "pads": [{"n": n, "x": x, "y": 0.0, "w": 1.6, "h": 1.6, "furo": 0.8, "forma": "C"}
                                                for n, x in (("1", -1.7), ("2", 1.7))]}
        loja.pagina = lambda codigo: {"foto": None, "pdf": None}
        loja.pedir = sem_rede
        self.pasta = copia()

    def tearDown(self):
        catalogo.PASTA = self.original
        loja.ficha, loja.desenho, loja.pagina, loja.pedir = self.guardado
        shutil.rmtree(self.copia, ignore_errors=True)
        apagar(self.pasta)

    def test_importar_o_ldr_conferido(self):
        tipo = loja.importar("C10081", "ldr", self.pasta)
        self.assertEqual((tipo["nome"], tipo["bloco"], tipo["pendente"]), ("LDR (fotorresistor) 8kΩ~20kΩ", "ldr", []))
        self.assertEqual(tipo["eletrica"]["modelo"], "ldr")
        self.assertEqual(json.loads((self.pasta / "pecas" / "C10081.json").read_text())["nome"], tipo["nome"])
        e = catalogo.ler()["pecas"]["C10081"]
        self.assertEqual((e["categoria"], e["nome"], e["tamanho"]), ("sensor_luz", "LDR (fotorresistor) 8kΩ~20kΩ", "5,1 × 4,3 mm"),
                         "a medida que a loja diz fica (a do desenho só quando ela não diz)")
        self.assertFalse((self.copia / "ldr.json").exists())

    def test_importar_um_ldr_novo_grava_na_categoria(self):
        tipo = loja.importar("C900000002", "ldr", self.pasta)
        self.assertTrue(tipo["pendente"], "sem conferido: falta ler o datasheet")
        self.assertEqual(tipo["nomes"], {"1": "lado 1", "2": "lado 2"})
        self.assertEqual(catalogo.ler()["pecas"]["C900000002"]["categoria"], "sensor_luz")

    def test_importar_o_som(self):
        tipo = loja.importar("C128650", "buzzer", self.pasta)
        self.assertEqual((tipo["nome"], tipo["eletrica"]["modelo"]), ("Buzzer passivo 12.6mm, 4kHz", "piezo"))
        self.assertEqual(catalogo.ler()["pecas"]["C128650"]["categoria"], "buzzer_passivo")

    def test_so_importa_pra_placa_que_existe(self):
        antes = catalogo.ler()["pecas"].keys()
        sem_placa = self.copia / "nao_e_placa"
        with self.assertRaises(loja.SemLoja) as erro:
            loja.importar("C900000002", "ldr", sem_placa)
        self.assertIn("falta o placa.txt", str(erro.exception))
        self.assertFalse(sem_placa.exists(), "não cria a pasta")
        self.assertEqual(catalogo.ler()["pecas"].keys(), antes, "não grava no catálogo")

    def test_o_cerebro_nao_vem_da_lcsc(self):
        with self.assertRaises(loja.SemLoja) as erro:
            loja.importar("C10081", "cerebro", self.pasta)
        self.assertIn("robocore", str(erro.exception))


if __name__ == "__main__":
    unittest.main()
