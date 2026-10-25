"""o catálogo inteiro (ferramenta/catalogo/): formato, categorias, peças, lojas e as regras do código"""
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from apoio import RAIZ
from biblioteca import BIBLIOTECA
import catalogo

PASTA = RAIZ / "ferramenta" / "catalogo"
ARQUIVOS = sorted(PASTA.glob("*.json"))
MONTAGENS = {"furo", "superfície", "módulo", "fio", "não informado"}
SITUACOES = {"ok", "sem estoque", "sumiu"}
CAMPOS_PECA = ("nome", "marca", "modelo", "pacote", "montagem", "atributos", "loja", "link", "preco", "moeda", "visto", "situacao")
NA_LANTERNINHA = {"C5365915": "pilha", "C393938": "botao", "C119310": "resistor", "C779439": "led"}
NOS_PROJETOS_ESP32 = {"C779439": "led", "C779441": "led", "C779440": "led", "C779443": "led", "C7433012": "led",
                      "C10081": "sensor_luz", "C128650": "buzzer_passivo", "C119354": "resistor", "C713997": "resistor",
                      "C41417327": "conector_header_femea", "C22373901": "conector_header_femea",
                      "robocore:esp32-wifi-bluetooth": "placa_desenvolvimento"}
PRECISA = {"led": ("vf", "vf_max", "i_teste", "i_max", "r_s", "brilho", "cor"),
           "pilha": ("mais", "menos", "v", "v_min", "v_max", "mah"),
           "chave": ("lados",), "resistor": ("potencia_max",),
           "ldr": ("r10_min", "r10_max", "gama", "gama_tol", "r_escuro", "p_max", "v_max"),
           "piezo": ("c", "c_tol", "v_max_op"), "capacitor": ("c", "v_max")}
COM_URL = ("led", "ldr", "piezo", "capacitor")   # conferido destes modelos: a fonte diz o link e a página
CORES_LED = set(catalogo.CORES.values()) | {"branco quente", "branco frio"}   # a 'cor' da eletrica, em português


def eletricas(modelo):
    """(codigo, peça, eletrica) de cada peça conferida com esse modelo elétrico"""
    for codigo, e in catalogo.ler()["pecas"].items():
        el = (e.get("conferido") or {}).get("eletrica")
        if el and el["modelo"] == modelo:
            yield codigo, e, el


class Formato(unittest.TestCase):
    def test_cada_arquivo_e_uma_categoria_valida(self):
        self.assertGreater(len(ARQUIVOS), 50)
        for arq in ARQUIVOS:
            d = json.loads(arq.read_text())
            self.assertEqual(d["categoria"], arq.stem, arq.name)
            self.assertRegex(d["categoria"], r"^[a-z0-9_]+$")
            self.assertIn(d["grupo"], catalogo.GRUPOS, arq.name)
            for campo in ("nome", "explica"):
                self.assertTrue(d.get(campo), f"{arq.name}: falta {campo}")
            self.assertLess(len(d["explica"]), 900, f"{arq.name}: explica comprido demais pro Luiz")
            self.assertTrue(set(d) <= set(catalogo.CAMPOS_SPEC) | {"pecas"}, f"{arq.name}: campo estranho {set(d) - set(catalogo.CAMPOS_SPEC)}")
            for s in d.get("sementes", []):
                self.assertTrue(s.get("busca"), arq.name)

    def test_codigo_nao_aparece_em_duas_categorias(self):
        visto = {}
        for arq in ARQUIVOS:
            for codigo in json.loads(arq.read_text()).get("pecas", {}):
                self.assertNotIn(codigo, visto, f"{codigo} em {arq.stem} e em {visto.get(codigo)}")
                visto[codigo] = arq.stem

    def test_cada_peca_tem_o_que_o_app_mostra(self):
        cat = catalogo.ler()
        for codigo, e in cat["pecas"].items():
            onde = f"{e['categoria']}/{codigo}"
            for campo in CAMPOS_PECA:
                self.assertIn(campo, e, f"{onde}: falta {campo}")
            self.assertIn(e["montagem"], MONTAGENS, onde)
            self.assertIn(e["situacao"], SITUACOES, onde)
            self.assertIn(e["moeda"], ("USD", "BRL"), onde)
            self.assertRegex(e["link"], r"^https://\S+$", f"{onde}: link")
            self.assertRegex(e["visto"], r"^\d{4}-\d{2}-\d{2}$", onde)
            self.assertTrue(e["preco"] is None or e["preco"] > 0, onde)
            self.assertTrue(e.get("apelido") or e["nome"], onde)
            if e["loja"] == "LCSC":
                self.assertRegex(codigo, r"^C\d+$", onde)
                self.assertEqual(e["moeda"], "USD", onde)
            else:
                self.assertIn(":", codigo, f"{onde}: peça de outra loja tem chave loja:pedaço")
                self.assertTrue(e.get("foto", "").startswith("https://") or not e.get("foto"), onde)
            for oferta in e.get("outras_lojas", []):
                self.assertRegex(oferta.get("link", ""), r"^https://", f"{onde}: outra loja sem link")

    def test_codigo_barrado_nao_esta_na_categoria(self):
        cat = catalogo.ler()
        for cid, spec in cat["categorias"].items():
            for codigo in spec.get("filtro", {}).get("fora", []):
                e = cat["pecas"].get(codigo)
                self.assertFalse(e and e["categoria"] == cid, f"{codigo} está barrado em {cid} mas continua lá")

    def test_conferido_tem_o_que_o_simulador_precisa(self):
        for codigo, e in catalogo.ler()["pecas"].items():
            el = (e.get("conferido") or {}).get("eletrica")
            if el:
                self.assertIn(el["modelo"], PRECISA, f"{codigo}: modelo elétrico '{el['modelo']}' desconhecido")
                for campo in PRECISA[el["modelo"]]:
                    self.assertIn(campo, el, f"{codigo}: conferido sem {campo}")
                self.assertTrue(e["conferido"].get("fonte"), f"{codigo}: conferido sem fonte")
                pendentes = el.get("pendentes", [])
                self.assertTrue(isinstance(pendentes, list) and all(isinstance(p, str) and p for p in pendentes), codigo)
                if el["modelo"] in COM_URL:
                    self.assertRegex(e["conferido"]["fonte"], r"https://\S+", f"{codigo}: a fonte não tem o link")
                    self.assertRegex(e["conferido"]["fonte"], r"\bp\. \d", f"{codigo}: a fonte não diz a página")

    def test_led_conferido(self):
        """o brilho sai do 0 e sobe com a corrente; 1,0 na corrente de teste; o + e o − batem com os nomes"""
        leds = list(eletricas("led"))
        self.assertGreaterEqual(len(leds), 5)
        for codigo, e, el in leds:
            b = el["brilho"]
            self.assertEqual(b[0][1], 0, f"{codigo}: o primeiro ponto do brilho tem que ter brilho 0")
            self.assertTrue(all(i1 < i2 and l1 <= l2 for (i1, l1), (i2, l2) in zip(b, b[1:])), f"{codigo}: a curva não cresce")
            self.assertIn([el["i_teste"], 1.0], b, f"{codigo}: o brilho 1,0 é o da corrente de teste")
            self.assertGreater(el["i_max"], el["i_teste"], codigo)
            if "vf_min" in el:
                self.assertTrue(el["vf_min"] <= el["vf"] <= el["vf_max"], f"{codigo}: vf fora de vf_min..vf_max")
            else:
                self.assertTrue(any("vf_min" in p for p in el.get("pendentes", [])), f"{codigo}: sem vf_min e sem pendente")
            cor = el.get("cor")
            self.assertIn(cor, CORES_LED, f"{codigo}: cor '{cor}' (em português, como no catalogo.CORES)")
            da_loja = catalogo.CORES.get(e["atributos"].get("Illumination Color"))
            if da_loja:
                self.assertTrue(cor.startswith(da_loja), f"{codigo}: a loja diz {da_loja}, a eletrica diz {cor}")
            self.assertIn("nomes", e["conferido"], f"{codigo}: conferido sem os nomes dos pinos")
            nomes = e["conferido"]["nomes"]   # a numeração muda de um modelo pro outro
            self.assertNotEqual(el["mais"], el["menos"], codigo)
            self.assertEqual((nomes.get(el["mais"]), nomes.get(el["menos"])), ("+", "−"), f"{codigo}: + e − trocados")

    def test_ldr_e_piezo_conferidos(self):
        ldrs, piezos = list(eletricas("ldr")), list(eletricas("piezo"))
        self.assertTrue(ldrs and piezos)
        for codigo, _, el in ldrs:
            self.assertLess(el["r10_min"], el["r10_max"], codigo)
            self.assertTrue(0 < el["gama_tol"] < el["gama"], codigo)
            self.assertGreater(el["r_escuro"], el["r10_max"], codigo)
            if "ponto_1lux" in el:   # não é do datasheet da peça: diz de onde veio
                p = el["ponto_1lux"]
                self.assertLess(p["r_min"], p["r_max"], codigo)
                self.assertRegex(p["fonte"], r"https://\S+", codigo)
        for codigo, _, el in piezos:
            self.assertTrue(1e-10 < el["c"] < 1e-6, f"{codigo}: c em farads (5,5 nF = 5.5e-09), não {el['c']}")
            self.assertTrue(0 < el["c_tol"] < 1, codigo)
            self.assertGreater(el["v_max_op"], 0, codigo)

    def test_tipo_da_biblioteca(self):
        """peça com 'tipo' entra na placa por um tipo da biblioteca, e não pelo desenho da loja"""
        for codigo, e in catalogo.ler()["pecas"].items():
            if "tipo" in e:
                self.assertIn(e["tipo"], BIBLIOTECA, f"{codigo}: o tipo '{e['tipo']}' não existe na biblioteca")
                self.assertTrue((e.get("conferido") or {}).get("fonte"), f"{codigo}: tem tipo, mas não foi conferida")


class AsPecasDasPlacas(unittest.TestCase):
    def test_lanterninha_continua_no_lugar(self):
        cat = catalogo.ler()
        for codigo, categoria in NA_LANTERNINHA.items():
            self.assertEqual(cat["pecas"][codigo]["categoria"], categoria, codigo)
        for codigo in ("C5365915", "C393938", "C779439"):
            self.assertTrue(cat["pecas"][codigo].get("conferido"), f"{codigo} perdeu o conferido")

    def test_pecas_dos_projetos_esp32_conferidas(self):
        cat = catalogo.ler()
        for codigo, categoria in NOS_PROJETOS_ESP32.items():
            self.assertEqual(cat["pecas"][codigo]["categoria"], categoria, codigo)
            fonte = (cat["pecas"][codigo].get("conferido") or {}).get("fonte")
            self.assertTrue(fonte, f"{codigo} sem conferido")
            self.assertRegex(fonte, r"https://\S+", f"{codigo}: a fonte do conferido não tem o link")
        self.assertEqual(catalogo.conferido("C10081")["eletrica"]["modelo"], "ldr")
        self.assertIn("Senba C125626", catalogo.conferido("C10081")["eletrica"]["ponto_1lux"]["fonte"])
        self.assertEqual(catalogo.conferido("C128650")["eletrica"]["r_serie"], [1000, 2000])   # a nota da Murata
        branco = cat["pecas"]["C7433012"]   # a loja não diz que é de furo nem a cor em português
        self.assertEqual((branco["montagem"], branco["conferido"]["eletrica"]["mais"]), ("furo", "1"))
        pendentes = branco["conferido"]["eletrica"]["pendentes"]   # a cor e as curvas da p. 5 ficam em dúvida
        self.assertTrue(any("cor" in p for p in pendentes) and any("p. 5" in p and "vf" in p for p in pendentes), pendentes)

    def test_devkit_da_robocore(self):
        e = catalogo.ler()["pecas"]["robocore:esp32-wifi-bluetooth"]
        self.assertEqual(e["tipo"], "devkit_esp32_30")
        self.assertEqual((e["loja"], e["moeda"]), ("RoboCore", "BRL"))
        self.assertGreater(e["preco"], 0)
        self.assertTrue(e["link"].startswith("https://www.robocore.net/") and e["foto"].startswith("https://"))
        self.assertIn("https://www.robocore.net/wifi/esp32-wifi-bluetooth", e["conferido"]["fonte"])


class Regras(unittest.TestCase):
    def test_montagem_pelos_pacotes(self):
        casos = {"Plugin,D=5mm": "furo", "DIP-8": "furo", "PDIP-28": "furo", "TO-92": "furo", "TO-220F": "furo", "DO-41": "furo",
                 "HC-49S": "furo", "插件,D9xL4mm": "furo", "SIP-3-2.5mm": "furo", "KBP": "furo", "TO-39-4": "furo",
                 "SOIC-8": "superfície", "TO-252": "superfície", "HC-49S-SMD": "superfície", "DO-214AC": "superfície",
                 "DBS": "superfície", "0805": "superfície", "-": "não informado"}
        for pacote, esperado in casos.items():
            self.assertEqual(catalogo.montagem({"pacote": pacote, "categoria": "x", "atributos": {}}), esperado, pacote)
        self.assertEqual(catalogo.montagem({"pacote": "-", "categoria": "Development Boards & Kits", "atributos": {}}), "módulo")
        self.assertEqual(catalogo.montagem({"pacote": "-", "categoria": "Thyristors (SCR)/Modules", "atributos": {}}), "não informado")
        self.assertEqual(catalogo.montagem({"pacote": "x", "categoria": "Housings (Wire To Board)", "atributos": {}}), "fio")
        self.assertEqual(catalogo.montagem({"pacote": "-", "categoria": "x", "atributos": {}, "montagem_manual": "furo"}), "furo")

    def test_atributo_com_dois_nomes(self):
        self.assertEqual(catalogo.atributo({"type": "-", "Type": "NPN"}, "type|Type"), "NPN")
        self.assertIsNone(catalogo.atributo({}, "a|b"))

    def test_nome_em_lista_de_modelos_e_traducao(self):
        cat = {"categorias": {"x": {"nome": "Coisa", "nome_peca": ["{A} {B}", "{@categoria_loja} {@modelo}"],
                                    "traducoes": {"Timers": "Timer"}}}}
        self.assertEqual(catalogo.nome_da_peca(cat, "x", {"atributos": {"A": "1", "B": "Right Angle"}, "categoria": "", "modelo": "M"}),
                         "1 a 90°")
        self.assertEqual(catalogo.nome_da_peca(cat, "x", {"atributos": {"A": "1"}, "categoria": "Timers", "modelo": "NE555"}),
                         "Timer NE555")
        self.assertEqual(catalogo.nome_da_peca(cat, "x", {"atributos": {}, "categoria": "", "modelo": "Z1"}), "Coisa Z1")

    def test_filtro(self):
        cat = {"categorias": {"x": {"filtro": {"montagem": ["furo"], "estoque_minimo": 50, "fora": ["C2"],
                                               "pacotes_fora": ["SMD"], "valores_fora": {"T": ["ruim"]}}}}}
        base = {"codigo": "C1", "pacote": "Plugin", "categoria": "", "atributos": {}, "estoque": 100}
        self.assertTrue(catalogo.serve(cat, "x", base))
        self.assertFalse(catalogo.serve(cat, "x", {**base, "estoque": 10}))
        self.assertFalse(catalogo.serve(cat, "x", {**base, "codigo": "C2"}))
        self.assertFalse(catalogo.serve(cat, "x", {**base, "pacote": "Plugin SMD"}))
        self.assertFalse(catalogo.serve(cat, "x", {**base, "atributos": {"T": "ruim"}}))
        self.assertFalse(catalogo.serve(cat, "x", {**base, "pacote": "SOIC-8"}))

    def test_recalcular_nao_muda_nada_num_catalogo_ja_recalculado(self):
        cat = catalogo.ler()
        antes = {c: json.dumps(e, sort_keys=True) for c, e in cat["pecas"].items()}
        catalogo.recalcular(cat)
        mudou = [c for c, e in cat["pecas"].items() if json.dumps(e, sort_keys=True) != antes[c]]
        self.assertEqual(mudou[:10], [], f"{len(mudou)} peças estão diferentes do que as regras de agora dão")

    def test_salvar_e_ler_de_volta_e_igual(self):
        """salva numa pasta de fora: regravar o catálogo de verdade perderia o que outro processo escrevesse no meio"""
        cat, original = catalogo.ler(), catalogo.PASTA
        copia = Path(tempfile.mkdtemp(prefix="sianvolt-catalogo-"))
        catalogo.PASTA = copia
        try:
            nomes = sorted(original.glob("*.json"))[:5]
            catalogo.salvar(cat, [arq.stem for arq in nomes])
            for arq in nomes:
                self.assertEqual((copia / arq.name).read_text(), arq.read_text(), f"{arq.name} mudou só de ler e salvar")
        finally:
            catalogo.PASTA = original
            shutil.rmtree(copia, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
