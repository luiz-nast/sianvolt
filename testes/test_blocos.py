"""blocos.py: números da loja, a conta do brilho e o projeto (perguntas, carrinho, placa.txt)"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from apoio import LED, PILHA, apagar, copia
from biblioteca import BIBLIOTECA
import blocos
import catalogo
import circuito
import gerar
import loja

LED_LOJA = {**LED, "vf": 1.97, "r_s": 3.5, "i_teste": 0.020,
            "brilho": [[0.001, 0], [0.005, 0.32], [0.010, 0.60], [0.015, 0.83], [0.020, 1.0], [0.025, 1.2], [0.030, 1.36]]}
CR2032 = {**PILHA, "r_interna": 10}
DEVKIT = BIBLIOTECA["devkit_esp32_30"]["eletrica"]
CATALOGO = catalogo.ler()   # só lendo: nenhum teste daqui grava em ferramenta/catalogo/
ROBOCORE = "robocore:esp32-wifi-bluetooth"


def eletrica(codigo):
    return CATALOGO["pecas"][codigo]["conferido"]["eletrica"]


def tipo_do_catalogo(codigo, bloco):
    """o pecas/C*.json de uma peça do catálogo, sem rede (o desenho fica de fora: o estado não usa)"""
    e = CATALOGO["pecas"][codigo]
    tipo = {"nome": e.get("apelido") or e["nome"], "bloco": bloco, "pendente": [],
            "eletrica": (e.get("conferido") or {}).get("eletrica"),
            "loja": {"codigo": codigo, "tamanho": e.get("tamanho", ""),
                     **{k: e.get(k) for k in ("modelo", "marca", "pacote", "preco", "minimo", "estoque", "datasheet", "link", "atributos")}}}
    if bloco == "resistor":
        tipo["valor"] = blocos.numero_com_unidade(e["atributos"]["Resistance"], "Ω")
        tipo["eletrica"] = tipo["eletrica"] or {"modelo": "resistor",
                                                "potencia_max": blocos.numero_com_unidade(e["atributos"]["Power(Watts)"], "W")}
    return tipo


def projeto_esp32(blocos_proj, perguntas):
    """placa temporária com projeto.json, pecas/ e um placa.txt com cada peça escolhida (o DevKit pelo tipo)"""
    pasta = Path(tempfile.mkdtemp(prefix="sianvolt-teste-")) / "esp32"
    (pasta / "pecas").mkdir(parents=True)
    linhas = ["placa 80 50"]
    for i, b in enumerate(blocos_proj):
        codigo = b.get("peca")
        if not codigo:
            continue
        if ":" in codigo:
            linhas.append(f"peca {b['ref']} {CATALOGO['pecas'][codigo]['tipo']} 40 25")
        else:
            (pasta / "pecas" / f"{codigo}.json").write_text(json.dumps(tipo_do_catalogo(codigo, b["bloco"]), ensure_ascii=False))
            linhas.append(f"peca {b['ref']} {codigo} {5 + 6 * i} 5")
    (pasta / "placa.txt").write_text("\n".join(linhas) + "\n")
    (pasta / "projeto.json").write_text(json.dumps({"objetivo": "ensaio", "frase": "", "perguntas": perguntas,
                                                    "blocos": blocos_proj}, ensure_ascii=False))
    return pasta


def item(est, ref):
    return next(b for b in est["blocos"] if b["ref"] == ref)


def pergunta(est, pid):
    return next(q for q in est["perguntas"] if q["id"] == pid)


class NumerosDaLoja(unittest.TestCase):
    def test_numero_com_unidade(self):
        casos = [("100Ω", "Ω", 100), ("4.7kΩ", "Ω", 4700), ("1MΩ", "Ω", 1e6), ("250mW", "W", 0.25), ("1W", "W", 1),
                 ("20mA", "A", 0.02), ("100nF", "F", 1e-7), ("abc", "Ω", None), (None, "Ω", None)]
        for txt, u, esperado in casos:
            v = blocos.numero_com_unidade(txt, u)
            if esperado is None:
                self.assertIsNone(v, txt)
            else:
                self.assertAlmostEqual(v, esperado, msg=txt)

    def test_ohms_txt(self):
        for o, txt in ((0, "0 Ω (jumper)"), (2.2, "2,2 Ω"), (240, "240 Ω"), (4700, "4,7 kΩ"), (1e6, "1 MΩ"), (None, "?")):
            self.assertEqual(blocos.ohms_txt(o), txt)

    def test_valor_comercial_mais_perto(self):
        for pedido, e24 in ((253, 240), (131, 130), (41.5, 43), (1000, 1000), (11.6, 12), (95, 91)):
            self.assertEqual(blocos.mais_perto(pedido), e24)

    def test_tamanho_do_pacote(self):
        self.assertEqual(blocos.tamanho("Plugin,D2.3xL6.5mm"), "corpo de 6,5 × 2,3 mm")
        self.assertEqual(blocos.tamanho("Plugin-4P,6x6mm"), "6 × 6 mm")
        self.assertEqual(blocos.tamanho("Plugin,D=5mm"), "5 mm de diâmetro")
        self.assertEqual(blocos.tamanho("-"), "")


class PecaDaLoja(unittest.TestCase):
    def test_led_importado_fica_com_o_menos_no_pad_quadrado(self):
        """o EasyEDA de alguns LEDs traz os dois pads redondos; o app ensina 'o − é o pad quadrado', então o import
        deixa o − (o K do símbolo) quadrado, do mesmo tamanho, e diz isso na fonte"""
        d = {"codigo": "C1", "atributos": {"Illumination Color": "Yellow"}, "pacote": "Plugin,D=5mm", "marca": "X",
             "modelo": "Y", "preco": 0.05, "minimo": 1, "estoque": 100, "datasheet": "https://x/ds.pdf", "link": "https://x"}
        des = {"corpo": [5.8, 5.8], "silk": [], "pacote": "LED-TH_BD5.0", "simbolo": {"1": "K", "2": "A"},
               "pads": [{"n": "1", "x": -1.27, "y": 0, "w": 1.8, "h": 1.8, "forma": "C", "furo": 1.0},
                        {"n": "2", "x": 1.27, "y": 0, "w": 1.8, "h": 1.8, "forma": "C", "furo": 1.0}]}
        tipo = blocos.tipo_da_loja("led", d, des)
        self.assertEqual(tipo["nomes"], {"1": "−", "2": "+"})
        self.assertEqual(tipo["pinos"]["1"]["pad"], {"forma": "R", "w": 1.8, "h": 1.8})
        self.assertEqual(tipo["pinos"]["2"]["pad"], {"forma": "C", "d": 1.8}, "o + continua redondo")
        self.assertIn("o − virou pad quadrado", tipo["fonte"])


class ContaDoBrilho(unittest.TestCase):
    def test_curva_ida_e_volta(self):
        for fracao in (0.1, 0.25, 0.5, 0.75, 1.0, 1.3):
            i = blocos.corrente_do_brilho(LED_LOJA, fracao)
            self.assertAlmostEqual(blocos.brilho_da_corrente(LED_LOJA, i), fracao, places=6)
        self.assertEqual(blocos.brilho_da_corrente(LED_LOJA, 0.0005), 0)
        self.assertEqual(blocos.brilho_da_corrente(LED_LOJA, 0.050), 1.36, "acima da curva não inventa")
        self.assertIsNone(blocos.corrente_do_brilho(LED, 0.5), "LED sem curva não tem conta")

    def test_nivel_mais_perto(self):
        self.assertEqual(blocos.nivel_do_brilho(0.27), "fraca")
        self.assertEqual(blocos.nivel_do_brilho(0.40), "media")
        self.assertEqual(blocos.nivel_do_brilho(0.80), "forte")

    def test_lanterninha_fraca_media_forte(self):
        esperado = {"fraca": 240, "media": 120, "forte": 43}
        for nivel, ohms in esperado.items():
            c = blocos.conta_do_freio(CR2032, LED_LOJA, blocos.PERGUNTAS["brilho"]["opcoes"][nivel]["fracao"])
            self.assertEqual(c["padrao"], ohms, nivel)
            self.assertEqual(blocos.nivel_do_brilho(c["brilho"]), nivel, f"{nivel}: o resistor de loja ainda dá o nível pedido")
            i = (CR2032["v"] - c["joelho"]) / (c["padrao"] + LED_LOJA["r_s"] + 10)
            self.assertAlmostEqual(c["i_padrao"], i)

    def test_pilha_fraca_demais(self):
        c = blocos.conta_do_freio({**CR2032, "v": 1.5}, LED_LOJA, 0.5)
        self.assertTrue(c["impossivel"])


class Projeto(unittest.TestCase):
    def setUp(self):
        self.pasta = copia()
        (self.pasta / "projeto.json").write_text(json.dumps({
            "objetivo": "teste", "perguntas": {},
            "blocos": [{"ref": "BT1", "bloco": "pilha"}, {"ref": "R1", "bloco": "resistor"}, {"ref": "D1", "bloco": "led"}]}))

    def tearDown(self):
        apagar(self.pasta)

    def test_responder_valida(self):
        blocos.responder(self.pasta, "brilho", "media")
        self.assertEqual(blocos.ler_projeto(self.pasta)["perguntas"]["brilho"]["resposta"], "media")
        with self.assertRaises(ValueError):
            blocos.responder(self.pasta, "brilho", "cegante")
        with self.assertRaises(ValueError):
            blocos.responder(self.pasta, "volume", "alto")

    def test_estado_sem_pecas_pede_o_que_falta(self):
        e = blocos.estado(self.pasta)
        self.assertFalse(e["pronto"])
        conta = next(b for b in e["blocos"] if b["ref"] == "R1")["conta"]
        self.assertIn("responder quanta luz você quer", conta["falta"])

    def test_trocar_no_txt_so_mexe_na_linha_certa(self):
        antes = (self.pasta / "placa.txt").read_text()
        self.assertTrue(blocos.trocar_no_txt(self.pasta, "R1", "C119310", "Resistor 240 Ω"))
        depois = (self.pasta / "placa.txt").read_text()
        self.assertIn("peca R1 C119310 43 15   # Resistor 240 Ω, escolhido no carrinho", depois)
        self.assertEqual([l for l in antes.splitlines() if "R1 " not in l or not l.startswith("peca")],
                         [l for l in depois.splitlines() if "R1 " not in l or not l.startswith("peca")])
        self.assertFalse(blocos.trocar_no_txt(self.pasta, "R9", "C1", "x"), "ref que não está na placa")

    def test_tipos_no_txt(self):
        self.assertEqual(blocos.tipos_no_txt(self.pasta)["D1"], "led_5mm")


class ContaComOCerebro(unittest.TestCase):
    """o pino do DevKit no lugar da pilha: 3,3 V com 30 Ω por dentro (a elétrica do devkit_esp32_30)"""

    def test_led_vermelho_no_pino_fraca_media_forte(self):
        esperado = {"fraca": (300, False), "media": (130, False), "forte": (36, True)}
        for nivel, (ohms, passa) in esperado.items():
            c = blocos.conta_do_led(DEVKIT, eletrica("C779439"), blocos.PERGUNTAS["brilho"]["opcoes"][nivel]["fracao"])
            self.assertEqual(c["padrao"], ohms, nivel)
            self.assertIs(c["passa_do_pino"], passa, f"{nivel}: só a forte passa da força padrão do pino (~20 mA)")
            self.assertEqual((c["v"], c["r_interna"], c["fonte"]), (DEVKIT["vdd"], DEVKIT["r_pino"], "pino"))
            self.assertEqual(blocos.nivel_do_brilho(c["brilho"]), nivel)

    def test_faixa_vai_do_vf_max_ao_vf_min(self):
        led = eletrica("C779439")
        c = blocos.conta_do_led(DEVKIT, led, 0.5)
        resto = 130 + led["r_s"] + DEVKIT["r_pino"]
        self.assertAlmostEqual(c["faixa"]["de"], (3.3 - (led["vf_max"] - led["r_s"] * led["i_teste"])) / resto)
        self.assertAlmostEqual(c["faixa"]["ate"], (3.3 - (led["vf_min"] - led["r_s"] * led["i_teste"])) / resto)
        self.assertEqual(round(c["faixa"]["ate"] * 1000, 1), 9.0, "pino 3,3 V → 130 Ω → até 9,0 mA")
        self.assertTrue(c["faixa"]["de"] < c["i_padrao"] < c["faixa"]["ate"])
        self.assertEqual(c["pior"]["v"], DEVKIT["vdd_max"], "o pior caso é com o 3V3 no máximo")
        self.assertGreater(c["pior"]["i"], c["faixa"]["ate"])
        self.assertIn("i_pino", c["fontes"])

    def test_pior_caso_do_led_com_o_vf_minimo(self):
        """o pior caso do LED é o 3V3 no máximo E o LED que menos segura (o vf mínimo), e não o vf típico"""
        led = eletrica("C779439")
        c = blocos.conta_do_led(DEVKIT, led, 0.5)
        resto = c["padrao"] + led["r_s"] + DEVKIT["r_pino"]
        self.assertAlmostEqual(c["pior"]["i"], (DEVKIT["vdd_max"] - (led["vf_min"] - led["r_s"] * led["i_teste"])) / resto)

    def test_verde_forte_e_impossivel(self):
        c = blocos.conta_do_led(DEVKIT, eletrica("C779443"), 1.0)
        self.assertTrue(c["impossivel"])
        self.assertEqual(blocos.conta_do_led(DEVKIT, eletrica("C779443"), 0.5)["padrao"], 36)

    def test_divisor_do_ldr_com_22k(self):
        c = blocos.conta_do_divisor(eletrica("C10081"), 22000, DEVKIT)
        linha = {x["lux"]: x for x in c["linhas"]}
        self.assertEqual(sorted(linha), [0, 1, 10, 100])
        dez = linha[10]["cantos"]
        self.assertTrue(dez["min"]["na_faixa"] and dez["max"]["na_faixa"], "10 lux cai na faixa boa nos dois cantos")
        self.assertFalse(linha[0]["na_faixa"], "o escuro fica fora da faixa boa do ADC")
        self.assertTrue(linha[0]["escuro"])
        self.assertGreater(linha[0]["cantos"]["meio"]["v"], DEVKIT["adc_max"])
        for lux, x in linha.items():   # a conta é a do circuito.py, sem cópia
            for canto, v in x["cantos"].items():
                self.assertEqual(v["v"], circuito.divisor_do_ldr(eletrica("C10081"), 22000, 3.3, lux, canto))
        meio = {lux: round(x["cantos"]["meio"]["v"], 2) for lux, x in linha.items() if lux}
        self.assertEqual(meio, {1: 2.38, 10: 1.2, 100: 0.38}, "os volts do LDR do meio que a decisão do divisor usa")
        self.assertEqual((c["bate"], c["padrao"]), (True, 22000))

    def test_divisor_com_10k_nao_serve(self):
        """o motivo da decisão do divisor: com 10 kΩ, o LDR do meio em 1 lux passa da faixa boa do ADC"""
        c = blocos.conta_do_divisor(eletrica("C10081"), 10000, DEVKIT)
        um = next(x for x in c["linhas"] if x["lux"] == 1)["cantos"]["meio"]
        self.assertGreater(um["v"], DEVKIT["adc_max"])
        self.assertTrue(next(x for x in c["linhas"] if x["lux"] == 10)["na_faixa"], "em 10 lux até daria")
        self.assertEqual((c["bate"], c["padrao"], c["r_fixo"]), (False, 22000, 10000), "a conta é a do resistor do carrinho")
        sem = blocos.conta_do_divisor(eletrica("C10081"), None, DEVKIT)
        self.assertEqual((sem["r_fixo"], sem["padrao"]), (22000, 22000), "sem resistor no carrinho, a conta é a do sugerido")
        self.assertNotIn("bate", sem)

    def test_divisor_olha_os_cantos_em_10_lux(self):
        """um LDR com a faixa larga demais: o do meio é o mesmo do C10081 (√(1k·160k) = √(8k·20k)), mas em 10 lux o
        canto de 1 kΩ dá menos que a faixa boa"""
        largo = {**eletrica("C10081"), "r10_min": 1000.0, "r10_max": 160000.0}
        c = blocos.conta_do_divisor(largo, 22000, DEVKIT)
        dez = next(x for x in c["linhas"] if x["lux"] == 10)
        self.assertTrue(all(x["cantos"]["meio"]["na_faixa"] for x in c["linhas"] if x["lux"]))
        self.assertLess(dez["cantos"]["min"]["v"], DEVKIT["adc_min"])
        self.assertFalse(c["bate"])

    def test_divisor_nas_pontas_do_3v3(self):
        """a faixa boa vale com o 3V3 de vdd_min a vdd_max, como na etapa 4: com 20 kΩ o LDR do meio em 1 lux fica dentro
        no 3V3 do meio e passa no vdd_max"""
        ldr = eletrica("C10081")
        c = blocos.conta_do_divisor(ldr, 22000, DEVKIT)
        for x in c["linhas"]:
            for canto, v in x["cantos"].items():
                self.assertEqual(v["v_de"], circuito.divisor_do_ldr(ldr, 22000, DEVKIT["vdd_min"], x["lux"], canto))
                self.assertEqual(v["v_ate"], circuito.divisor_do_ldr(ldr, 22000, DEVKIT["vdd_max"], x["lux"], canto))
        self.assertEqual((c["vdd_de"], c["vdd_ate"]), (DEVKIT["vdd_min"], DEVKIT["vdd_max"]))
        self.assertEqual(c["faixa"], {"de": 22000, "ate": 56000}, "os resistores de loja que servem pro C10081")
        vinte = blocos.conta_do_divisor(ldr, 20000, DEVKIT)
        um = next(x for x in vinte["linhas"] if x["lux"] == 1)["cantos"]["meio"]
        self.assertTrue(um["v"] <= DEVKIT["adc_max"] < um["v_ate"])
        self.assertFalse(um["na_faixa"])
        self.assertEqual((vinte["bate"], vinte["padrao"]), (False, 22000))
        sem_min = {k: v for k, v in DEVKIT.items() if k != "vdd_min"}
        self.assertEqual(blocos.conta_do_divisor(ldr, 22000, sem_min)["pendentes"],
                         ["a tensão mínima do 3V3 do cérebro está pendente: a faixa do olho de luz usa o 3V3 do meio"])

    def test_divisor_sugere_um_que_serve_pra_outro_ldr(self):
        """um LDR em que os 22 kΩ não servem: o sugerido sai da faixa dos que servem, e a conta sem resistor é a dele"""
        outro = {**eletrica("C10081"), "r10_min": 2000.0, "r10_max": 5000.0, "gama": 0.5}
        sem = blocos.conta_do_divisor(outro, None, DEVKIT)
        de, ate = sem["faixa"]["de"], sem["faixa"]["ate"]
        self.assertTrue(de <= sem["padrao"] <= ate and sem["padrao"] != 22000 and ate < 22000)
        self.assertEqual(sem["r_fixo"], sem["padrao"], "sem resistor no carrinho, a tabela é a do sugerido")
        self.assertTrue(blocos.serve_no_divisor(sem["linhas"]))
        for r in blocos.valores_e24():   # a faixa é exatamente a dos que passam na regra
            self.assertEqual(blocos.conta_do_divisor(outro, r, DEVKIT)["bate"], de <= r <= ate, r)
        com_22k = blocos.conta_do_divisor(outro, 22000, DEVKIT)
        self.assertEqual((com_22k["bate"], com_22k["padrao"]), (False, sem["padrao"]))
        olho = [{"ref": "U1", "bloco": "cerebro"}, {"ref": "LDR1", "bloco": "ldr"}, {"ref": "R1", "bloco": "resistor", "para": "LDR1"}]
        c = blocos.conta_do_resistor({"blocos": olho}, olho[2], {"U1": {"eletrica": DEVKIT}, "LDR1": {"eletrica": outro},
                                                                "R1": {"valor": 22000}}, {})
        self.assertIn("não servem pra esse LDR", c["origem"])
        self.assertIn("refaça essa conta", c["aviso"])

    def test_divisor_que_nenhum_resistor_salva(self):
        largo = {**eletrica("C10081"), "r10_min": 10.0, "r10_max": 1e7}
        c = blocos.conta_do_divisor(largo, 22000, DEVKIT)
        self.assertEqual((c["impossivel"], c["padrao"], c["faixa"], c["bate"]), (True, None, None, False))
        self.assertIn("troque o LDR", c["aviso"])
        olho = [{"ref": "U1", "bloco": "cerebro"}, {"ref": "LDR1", "bloco": "ldr"}, {"ref": "R1", "bloco": "resistor", "para": "LDR1"}]
        c = blocos.conta_do_resistor({"blocos": olho}, olho[2], {"U1": {"eletrica": DEVKIT}, "LDR1": {"eletrica": largo},
                                                                "R1": None}, {})
        self.assertEqual((c["padrao"], c["origem"]), (None, None))
        self.assertIn("troque o LDR", c["aviso"])

    def test_resistor_do_piezo(self):
        piezo = eletrica("C128650")
        c = blocos.conta_do_piezo(piezo, 1000, DEVKIT)
        self.assertTrue(c["bate"])
        self.assertAlmostEqual(c["pico"], 3.3 / 1030)   # a borda do apito: o piezo vira fio
        self.assertFalse(c["passa_do_pino"])
        c = blocos.conta_do_piezo(piezo, 220, DEVKIT)
        self.assertEqual((c["bate"], c["padrao"]), (False, 1000), "a Murata pede de 1 a 2 kΩ")
        self.assertNotIn("bate", blocos.conta_do_piezo(piezo, None, DEVKIT), "sem resistor no carrinho não tem o que bater")

    def test_piezo_no_pior_caso_com_o_3v3_no_maximo(self):
        # 136 Ω: 3,3 / 166 = 19,9 mA no 3V3 do meio, mas 3,399 / 166 = 20,5 mA no pior caso (passa da força do pino)
        c = blocos.conta_do_piezo(eletrica("C128650"), 136, DEVKIT)
        self.assertAlmostEqual(c["pior"]["i"], DEVKIT["vdd_max"] / (136 + DEVKIT["r_pino"]))
        self.assertEqual(c["pior"]["v"], DEVKIT["vdd_max"])
        self.assertTrue(c["passa_do_pino"])

    def test_resistor_do_botao(self):
        c = blocos.conta_do_botao(1000, DEVKIT, "GPIO14")
        self.assertTrue(c["le_zero"] and c["bate"] and not c["passa_do_pino"])
        self.assertAlmostEqual(c["v_apertado"], 3.3 * 1000 / 46000)   # apertado, o pino lê ~0,07 V
        self.assertAlmostEqual(c["vil"], 0.25 * 3.3)
        self.assertAlmostEqual(c["curto"]["i"], DEVKIT["vdd_max"] / 1030)   # pino virado em saída: ~3,3 mA
        cem = blocos.conta_do_botao(100, DEVKIT, "GPIO14")
        self.assertFalse(cem["bate"], "100 Ω: pino em 1 com o botão apertado passa de 20 mA")
        self.assertTrue(cem["passa_do_pino"])
        self.assertAlmostEqual(cem["curto"]["i"], DEVKIT["vdd_max"] / 130)
        self.assertFalse(blocos.conta_do_botao(22000, DEVKIT, "GPIO14")["le_zero"], "22 kΩ: apertado ele não lê 0")
        self.assertIn("pull-up", blocos.conta_do_botao(1000, DEVKIT, "GPIO34")["falta"][0])

    def test_numero_pendente_do_cerebro_vira_falta_e_nao_chute(self):
        proj = {"perguntas": {"brilho": {"resposta": "media"}},
                "blocos": [{"ref": "U1", "bloco": "cerebro"}, {"ref": "D1", "bloco": "led"}, {"ref": "R1", "bloco": "resistor", "led": "D1"}]}
        tipos = {"U1": {"eletrica": {**DEVKIT, "r_pino": "pendente"}}, "D1": {"eletrica": eletrica("C779439")}, "R1": None}
        falta = blocos.conta_do_resistor(proj, proj["blocos"][2], tipos, {})["falta"]
        self.assertEqual(falta, ["a resistência do pino do cérebro está pendente: sem esse número não dá pra fazer a conta"],
                         "nome de gente, não o nome de máquina (r_pino)")
        tipos["U1"] = {"eletrica": DEVKIT}
        for brilho in ({}, {"resposta": "cegante"}):   # sem resposta (ou uma que não existe) não tem conta
            falta = blocos.conta_do_resistor({**proj, "perguntas": {"brilho": brilho}}, proj["blocos"][2], tipos, {})["falta"]
            self.assertEqual(falta, ["responder quanta luz você quer no D1"])
        sem_max = {k: v for k, v in DEVKIT.items() if k != "vdd_max"}
        c = blocos.conta_do_led(sem_max, eletrica("C779439"), 0.5)
        self.assertEqual(c["pior"]["v"], DEVKIT["vdd"])
        self.assertIn("a tensão máxima do 3V3 do cérebro está pendente: o pior caso usa o 3V3 do meio", c["pendentes"],
                      "o pior caso sem o vdd_max fica à vista")
        sem_vf = {**eletrica("C779439"), "vf_min": "pendente"}   # texto no lugar do número: sem a ponta, sem chute
        c = blocos.conta_do_led(DEVKIT, sem_vf, 0.5)
        self.assertIsNone(c["faixa"]["ate"])
        self.assertEqual(c["pior"]["vf"], sem_vf["vf"], "sem o vf mínimo, o pior caso usa o típico e diz isso")
        self.assertIn("a tensão mais baixa do LED aceso está pendente: a faixa de corrente fica sem essa ponta", c["pendentes"])

    def test_origem_diz_so_o_que_vale_pro_carrinho(self):
        """o '1 kΩ é o mesmo do som' só aparece com o som no projeto e com 1 kΩ nele; o divisor só cita a decisão dos 22 kΩ
        quando a conta é com 22 kΩ"""
        botao = [{"ref": "U1", "bloco": "cerebro"}, {"ref": "SW1", "bloco": "botao", "pino": "GPIO14"},
                 {"ref": "R1", "bloco": "resistor", "para": "SW1"}]
        tipos = {"U1": {"eletrica": DEVKIT}, "SW1": {}, "R1": {"valor": 1000}}
        sem_som = blocos.conta_do_resistor({"blocos": botao}, botao[2], tipos, {})["origem"]
        self.assertNotIn("som", sem_som, "o Dado não tem som")
        self.assertIn("de 140 Ω a 15 kΩ", sem_som)
        com_som = botao + [{"ref": "BZ1", "bloco": "buzzer"}, {"ref": "R2", "bloco": "resistor", "para": "BZ1"}]
        self.assertNotIn("som", blocos.conta_do_resistor({"blocos": com_som}, botao[2], {**tipos, "R2": None}, {})["origem"],
                         "o som ainda sem resistor no carrinho")
        origem = blocos.conta_do_resistor({"blocos": com_som}, botao[2], {**tipos, "R2": {"valor": 1000}}, {})["origem"]
        self.assertIn("o mesmo resistor do som (R2)", origem)
        dois_k = blocos.conta_do_resistor({"blocos": botao}, botao[2], {**tipos, "R1": {"valor": 2200}}, {})
        self.assertEqual((dois_k["bate"], dois_k["padrao"]), (True, 2200))
        self.assertNotIn("1 kΩ", dois_k["origem"])

        olho = [{"ref": "U1", "bloco": "cerebro"}, {"ref": "LDR1", "bloco": "ldr"}, {"ref": "R1", "bloco": "resistor", "para": "LDR1"}]
        tipos = {"U1": {"eletrica": DEVKIT}, "LDR1": {"eletrica": eletrica("C10081")}, "R1": {"valor": 22000}}
        c = blocos.conta_do_resistor({"blocos": olho}, olho[2], tipos, {})
        self.assertIn("Divisor da luz noturna", c["origem"])
        self.assertNotIn("aviso", c)
        c = blocos.conta_do_resistor({"blocos": olho}, olho[2], {**tipos, "R1": {"valor": 47000}}, {})
        self.assertEqual((c["bate"], c["padrao"]), (True, 47000), "47 kΩ também passa na regra da conta")
        self.assertNotIn("Divisor da luz noturna", c["origem"], "a decisão é dos 22 kΩ, não dos 47 kΩ")
        self.assertIn("47 kΩ do carrinho", c["origem"])
        self.assertIn("refaça essa conta", c["aviso"], "os limites do programa foram calculados com 22 kΩ")

    def test_numero_pendente_da_peca_vira_falta_e_nao_quebra(self):
        """LDR, piezo e LED com um número 'pendente' (ou sem ele): a conta diz o que falta, sem exceção e sem chute"""
        olho = [{"ref": "U1", "bloco": "cerebro"}, {"ref": "LDR1", "bloco": "ldr"}, {"ref": "R1", "bloco": "resistor", "para": "LDR1"}]
        tipos = {"U1": {"eletrica": DEVKIT}, "R1": {"valor": 22000}}
        ldr = eletrica("C10081")
        for campo, valor, nome in (("r10_max", "pendente", "a resistência máxima em 10 lux"),
                                   ("gama_tol", "pendente", "quanto o gama pode variar"), ("r_escuro", None, "a resistência no escuro")):
            com = {k: v for k, v in {**ldr, campo: valor}.items() if v is not None}   # None = sem a chave
            c = blocos.conta_do_resistor({"blocos": olho}, olho[2], {**tipos, "LDR1": {"eletrica": com}}, {})
            self.assertEqual(c, {"falta": [f"falta conferir {nome} do LDR1 no datasheet"]}, campo)
        som = [{"ref": "U1", "bloco": "cerebro"}, {"ref": "BZ1", "bloco": "buzzer"}, {"ref": "R1", "bloco": "resistor", "para": "BZ1"}]
        for r_serie in ("pendente", [2000, 1000], [1000]):
            piezo = {**eletrica("C128650"), "r_serie": r_serie}
            c = blocos.conta_do_resistor({"blocos": som}, som[2], {**tipos, "BZ1": {"eletrica": piezo}}, {})
            self.assertEqual(c, {"falta": ["falta conferir o resistor em série que o fabricante pede do BZ1 no datasheet"]}, r_serie)
        luz = [{"ref": "U1", "bloco": "cerebro"}, {"ref": "D1", "bloco": "led"}, {"ref": "R1", "bloco": "resistor", "led": "D1"}]
        led = {**eletrica("C779439"), "vf": "pendente"}
        c = blocos.conta_do_resistor({"blocos": luz, "perguntas": {"brilho": {"resposta": "media"}}}, luz[2],
                                     {**tipos, "D1": {"eletrica": led}}, {})
        self.assertEqual(c, {"falta": ["falta conferir a tensão do LED aceso do D1 no datasheet"]})


class ProjetoComCerebro(unittest.TestCase):
    def tearDown(self):
        apagar(self.pasta)

    def test_verde_forte_impossivel_e_pronto_so_depois_do_ajuste_por_led(self):
        self.pasta = projeto_esp32([
            {"ref": "U1", "bloco": "cerebro", "peca": ROBOCORE},
            {"ref": "D1", "bloco": "led", "peca": "C779443", "pino": "GPIO25", "nome": "já!"},
            {"ref": "R1", "bloco": "resistor", "peca": "C120020", "led": "D1"}],   # 36 Ω
            {"brilho": {"resposta": "forte", "quem": "Luiz"}, "cor": {"por_led": {"D1": {"resposta": "verde", "quem": "Luiz"}}}})
        e = blocos.estado(self.pasta)
        self.assertTrue(item(e, "R1")["conta"]["impossivel"])
        self.assertTrue(pergunta(e, "brilho")["por_led"][0]["impossivel"], "impossível neste LED")
        self.assertFalse(e["pronto"])
        blocos.responder(self.pasta, "brilho", "media", quem="sugestão do Claude", ref="D1")
        e = blocos.estado(self.pasta)
        conta = item(e, "R1")["conta"]
        self.assertNotIn("impossivel", conta)
        self.assertEqual((conta["padrao"], conta["bate"], conta["resposta"], conta["resposta_do_led"]), (36, True, "media", True))
        brilho = pergunta(e, "brilho")
        self.assertEqual((brilho["resposta"], brilho["por_led"][0]["quem"]), ("forte", "sugestão do Claude"), "o geral fica")
        self.assertTrue(e["pronto"])
        blocos.responder(self.pasta, "brilho", "fraca")   # mudar o geral não apaga o ajuste do LED
        self.assertEqual(blocos.ler_projeto(self.pasta)["perguntas"]["brilho"]["por_led"]["D1"]["resposta"], "media")

    def test_carrinho_com_o_devkit(self):
        self.pasta = projeto_esp32([
            {"ref": "U1", "bloco": "cerebro", "peca": ROBOCORE},
            {"ref": "D1", "bloco": "led", "peca": "C779439", "pino": "GPIO32", "nome": "LED A", "duty_max": 0.36,
             "origem": "main.py: BRILHO_MAX²"},
            {"ref": "R1", "bloco": "resistor", "peca": "C3482538", "led": "D1"},   # 130 Ω
            {"ref": "SW1", "bloco": "botao", "peca": "C393938", "pino": "GPIO14", "nome": "rolar"},
            {"ref": "R2", "bloco": "resistor", "peca": "C713997", "para": "SW1", "origem": "decisão Botões"},
            {"ref": "BZ1", "bloco": "buzzer", "peca": "C128650", "pino": "GPIO26"},
            {"ref": "R3", "bloco": "resistor", "peca": "C713997", "para": "BZ1"},
            {"ref": "LDR1", "bloco": "ldr", "peca": "C10081", "pino": "GPIO34"},
            {"ref": "R4", "bloco": "resistor", "peca": "C119354", "para": "LDR1"}],
            {"brilho": {"resposta": "media", "quem": "sugestão do Claude"}})
        e = blocos.estado(self.pasta)
        u1, robocore = item(e, "U1"), CATALOGO["pecas"][ROBOCORE]
        self.assertTrue(u1["na_placa"], "no placa.txt o U1 é o tipo da biblioteca")
        self.assertEqual((u1["peca"]["preco"], u1["peca"]["moeda"], u1["peca"]["tipo"]), (robocore["preco"], "BRL", "devkit_esp32_30"))
        barras = u1["acompanha"][0]
        self.assertEqual((barras["codigo"], barras["qtd"], barras["moeda"]), ("C41417327", 2, "USD"))
        self.assertAlmostEqual(barras["subtotal"], 2 * CATALOGO["pecas"]["C41417327"]["preco"])
        self.assertEqual(barras["alternativa_peca"]["codigo"], "C22373901")
        self.assertEqual(u1["confira"], BIBLIOTECA["devkit_esp32_30"]["confira"])
        self.assertTrue(any("porta USB" in t for t in u1["peca"]["avisos"]), "os pendentes do DevKit ficam à vista")
        self.assertIn({"ref": "U1", "texto": DEVKIT["pendentes"][0]}, e["pendentes"])
        # com cérebro, o "por quê" fala do pino, não da pilha, e o resistor diz a quem ele serve
        textos = {b["ref"]: b["por_que"] for b in e["blocos"]}
        self.assertNotIn("pilha", textos["SW1"])
        self.assertIn("brilho", textos["R1"])
        self.assertIn("curto", textos["R2"])
        self.assertIn("piezo", textos["R3"])
        self.assertIn("divisor", textos["R4"])
        usd = sum(CATALOGO["pecas"][c]["preco"] for c in ("C779439", "C3482538", "C393938", "C713997", "C128650", "C713997",
                                                          "C10081", "C119354")) + barras["subtotal"]
        self.assertEqual(e["totais"], {"BRL": robocore["preco"], "USD": round(usd, 4)})
        self.assertEqual(e["total"], e["totais"]["USD"], "o total de sempre continua um número em US$")
        d1 = item(e, "D1")
        self.assertEqual((d1["apelido"], d1["pino"], d1["no_cerebro"]["serigrafia"], d1["no_cerebro"]["pino"]), ("LED A", "GPIO32", "D32", "6"))
        self.assertEqual(item(e, "LDR1")["no_cerebro"]["cuidado"], "só entrada")
        r1 = item(e, "R1")["conta"]
        self.assertEqual((r1["padrao"], r1["bate"], r1["led"]), (130, True, "D1"))
        self.assertAlmostEqual(r1["luz_media"], r1["brilho"] * 0.36)
        self.assertEqual(r1["duty_origem"], "main.py: BRILHO_MAX²")
        self.assertEqual((item(e, "R2")["conta"]["tipo"], item(e, "R2")["conta"]["origem"]), ("botao", "decisão Botões"))
        self.assertTrue(item(e, "R2")["conta"]["bate"] and item(e, "R3")["conta"]["bate"])
        self.assertEqual((item(e, "R3")["conta"]["tipo"], item(e, "R3")["conta"]["para"]), ("piezo", "BZ1"))
        r4 = item(e, "R4")["conta"]
        self.assertEqual((r4["tipo"], r4["r_fixo"], r4["bate"], r4["para"]), ("divisor", 22000, True, "LDR1"))
        self.assertIn("Divisor da luz noturna", r4["origem"])
        brilho = pergunta(e, "brilho")
        self.assertFalse(any("pilha" in o["explica"] for o in brilho["opcoes"]), "com o cérebro não tem pilha")
        self.assertEqual([o["id"] for o in brilho["opcoes"]], ["fraca", "media", "forte"])
        self.assertFalse(e["pronto"], "falta responder a cor do D1")
        blocos.responder(self.pasta, "cor", "amarelo", ref="D1")
        self.assertFalse(blocos.estado(self.pasta)["pronto"], "pediu amarelo e o LED do carrinho é vermelho")
        blocos.responder(self.pasta, "cor", "vermelho", ref="D1")
        self.assertTrue(blocos.estado(self.pasta)["pronto"])

    def test_led_forte_que_passa_do_pino_avisa_e_segura(self):
        self.pasta = projeto_esp32([
            {"ref": "U1", "bloco": "cerebro", "peca": ROBOCORE}, {"ref": "D1", "bloco": "led", "peca": "C779439"},
            {"ref": "R1", "bloco": "resistor", "peca": "C120020", "led": "D1"}],   # 36 Ω: o da conta da forte
            {"brilho": {"resposta": "forte", "quem": "Luiz"}, "cor": {"por_led": {"D1": {"resposta": "vermelho", "quem": "Luiz"}}}})
        e = blocos.estado(self.pasta)
        conta = item(e, "R1")["conta"]
        self.assertEqual((conta["padrao"], conta["bate"], conta["passa_do_pino"]), (36, True, True))
        self.assertIn("a etapa 4 reprova", conta["aviso"])
        self.assertIn("o ajuste de cada LED", conta["aviso"])
        self.assertFalse(e["pronto"], "a etapa 4 reprovaria: o carrinho não fica pronto")

    def test_pendentes_da_conta_ficam_a_vista(self):
        self.pasta = projeto_esp32([
            {"ref": "U1", "bloco": "cerebro", "peca": ROBOCORE}, {"ref": "D1", "bloco": "led", "peca": "C779439"},
            {"ref": "R1", "bloco": "resistor", "peca": "C3482538", "led": "D1"}],
            {"brilho": {"resposta": "media", "quem": "Luiz"}, "cor": {"por_led": {"D1": {"resposta": "vermelho", "quem": "Luiz"}}}})
        arq = self.pasta / "pecas" / "C779439.json"
        tipo = json.loads(arq.read_text())
        tipo["eletrica"]["vf_min"] = "pendente"
        arq.write_text(json.dumps(tipo, ensure_ascii=False))
        e = blocos.estado(self.pasta)
        self.assertIn({"ref": "R1", "texto": "a tensão mais baixa do LED aceso está pendente: a faixa de corrente fica sem essa ponta"},
                      e["pendentes"])
        self.assertTrue(e["pronto"], "o pendente fica à vista, mas a conta sai com o vf típico")

    def test_um_resistor_por_led(self):
        self.pasta = projeto_esp32([
            {"ref": "U1", "bloco": "cerebro", "peca": ROBOCORE}, {"ref": "D1", "bloco": "led", "peca": "C779439"},
            {"ref": "R1", "bloco": "resistor", "peca": "C3482538", "led": "D1"},
            {"ref": "R2", "bloco": "resistor", "peca": "C3482538", "led": "D1"}],
            {"brilho": {"resposta": "media", "quem": "Luiz"}, "cor": {"por_led": {"D1": {"resposta": "vermelho", "quem": "Luiz"}}}})
        e = blocos.estado(self.pasta)
        for ref in ("R1", "R2"):
            self.assertEqual(item(e, ref)["conta"], {"falta": ["o D1 está com 2 resistores no projeto.json (R1, R2): é um só pra ele"]})
        self.assertFalse(e["pronto"])

    def test_cerebro_que_nao_esta_no_catalogo(self):
        self.pasta = projeto_esp32([{"ref": "U1", "bloco": "cerebro"}, {"ref": "D1", "bloco": "led", "peca": "C779439"},
                                    {"ref": "R1", "bloco": "resistor", "led": "D1"}], {"brilho": {"resposta": "media", "quem": "Luiz"}})
        proj = blocos.ler_projeto(self.pasta)
        proj["blocos"][0]["peca"] = "robocore:nao-existe"
        blocos.salvar_projeto(self.pasta, proj)
        e = blocos.estado(self.pasta)
        self.assertEqual((item(e, "U1")["peca"], item(e, "U1")["na_placa"]), (None, False))
        self.assertEqual(item(e, "R1")["conta"]["falta"], ["escolher o cérebro (o DevKit)"])
        self.assertFalse(e["pronto"])

    def test_pergunta_cor_por_led(self):
        self.pasta = projeto_esp32([
            {"ref": "U1", "bloco": "cerebro", "peca": ROBOCORE},
            {"ref": "D1", "bloco": "led", "peca": "C779441"}, {"ref": "R1", "bloco": "resistor", "led": "D1"}],
            {"brilho": {"resposta": "media", "quem": "Luiz"}})
        cor = pergunta(blocos.estado(self.pasta), "cor")
        ids = [o["id"] for o in cor["opcoes"]]
        self.assertTrue({"vermelho", "amarelo", "verde", "branco quente"} <= set(ids), "as cores dos LEDs do catálogo")
        self.assertIn("C7433012", next(o for o in cor["opcoes"] if o["id"] == "branco quente")["conferidos"])
        self.assertFalse(cor["respondida"])
        with self.assertRaises(ValueError):
            blocos.responder(self.pasta, "cor", "amarelo")   # a cor é de um LED
        with self.assertRaises(ValueError):
            blocos.responder(self.pasta, "cor", "amarelo", ref="R1")
        with self.assertRaises(ValueError):
            blocos.responder(self.pasta, "cor", "roxo", ref="D1")
        blocos.responder(self.pasta, "cor", "branco quente", quem="Luiz", ref="D1")
        cor = pergunta(blocos.estado(self.pasta), "cor")["por_led"][0]
        self.assertEqual((cor["resposta"], cor["quem"], cor["da_peca"], cor["bate"]), ("branco quente", "Luiz", "amarelo", False))

    def test_opcoes_dos_blocos_novos_sem_rede(self):
        self.pasta = projeto_esp32([
            {"ref": "U1", "bloco": "cerebro", "peca": ROBOCORE}, {"ref": "LDR1", "bloco": "ldr"},
            {"ref": "BZ1", "bloco": "buzzer"}, {"ref": "R1", "bloco": "resistor", "peca": "C713997", "para": "BZ1"},
            {"ref": "D1", "bloco": "led"}, {"ref": "C1", "bloco": "capacitor", "para": "LDR1"}, {"ref": "C2", "bloco": "capacitor"}],
            {"cor": {"por_led": {"D1": {"resposta": "amarelo", "quem": "Luiz"}}}})
        pedir, salvar = loja.pedir, catalogo.salvar

        def nada(*_a, **_k):
            raise AssertionError("o catálogo já tem: não era pra ir na loja nem gravar")
        loja.pedir, catalogo.salvar = nada, nada
        try:
            o = blocos.opcoes(self.pasta, "U1")
            self.assertTrue(o["itens"] and all(i.get("tipo") in BIBLIOTECA for i in o["itens"]), "só placa com tipo")
            self.assertTrue(o["itens"][0]["escolhida"])
            self.assertEqual({i["categoria_loja"] for i in blocos.opcoes(self.pasta, "LDR1")["itens"]}, {"Photoresistors"})
            self.assertEqual({i["atributos"]["Technology"] for i in blocos.opcoes(self.pasta, "BZ1")["itens"]}, {"Piezoelectric"})
            do_som = blocos.opcoes(self.pasta, "R1")
            self.assertEqual((do_som["alvo"], do_som["alvo_txt"]), (1000, "1 kΩ"), "o resistor do piezo sai da conta dele")
            amarelos = blocos.opcoes(self.pasta, "D1")
            self.assertEqual(amarelos["cor"], "amarelo")
            self.assertTrue({"C779441", "C779440"} <= {i["codigo"] for i in amarelos["itens"]})
            do_olho = blocos.opcoes(self.pasta, "C1")
            self.assertEqual((do_olho["alvo"], do_olho["alvo_txt"]), (blocos.C_DO_LDR, "100 nF"))
            self.assertTrue(do_olho["itens"] and {i["atributos"]["Capacitance"] for i in do_olho["itens"]} == {"100nF"},
                            "o capacitor colado no olho de luz é o de 100 nF")
            solto = blocos.opcoes(self.pasta, "C2")
            self.assertIsNone(solto["alvo"], "sem 'para' o valor não foi decidido: a lista tem todos")
            self.assertGreater(len(solto["itens"]), len(do_olho["itens"]))
        finally:
            loja.pedir, catalogo.salvar = pedir, salvar

    def test_divisor_com_o_resistor_errado_nao_fica_pronto(self):
        self.pasta = projeto_esp32([
            {"ref": "U1", "bloco": "cerebro", "peca": ROBOCORE}, {"ref": "LDR1", "bloco": "ldr", "peca": "C10081", "pino": "GPIO34"},
            {"ref": "R1", "bloco": "resistor", "peca": "C713997", "para": "LDR1"}], {})   # 1 kΩ no lugar do 22 kΩ
        e = blocos.estado(self.pasta)
        conta = item(e, "R1")["conta"]
        self.assertEqual((conta["r_fixo"], conta["bate"], conta["padrao"]), (1000, False, 22000))
        self.assertFalse(e["pronto"])

    def test_opcoes_do_divisor_antes_de_escolher_e_busca_da_cor(self):
        self.pasta = projeto_esp32([
            {"ref": "U1", "bloco": "cerebro", "peca": ROBOCORE}, {"ref": "LDR1", "bloco": "ldr", "peca": "C10081"},
            {"ref": "R1", "bloco": "resistor", "para": "LDR1"}, {"ref": "D1", "bloco": "led"}],
            {"cor": {"por_led": {"D1": {"resposta": "verde", "quem": "Luiz"}}}})
        conta = item(blocos.estado(self.pasta), "R1")["conta"]
        self.assertEqual((conta["r_fixo"], conta["padrao"], "bate" in conta), (22000, 22000, False), "a conta do sugerido")
        buscar, salvar, buscas = loja.buscar, catalogo.salvar, []
        try:   # os dublês entram dentro do try: se uma conta falhar, o finally devolve os de verdade
            loja.buscar = lambda texto, *_a, **_k: buscas.append(texto) or []
            catalogo.salvar = lambda *_a, **_k: None
            o = blocos.opcoes(self.pasta, "R1")   # sem peça no R1: a lista sai do sugerido, sem pedir pra escolher antes
            self.assertEqual(o["alvo"], 22000)
            self.assertTrue(o["itens"] and all(i["atributos"]["Resistance"] == "22kΩ" for i in o["itens"]))
            self.assertEqual(blocos.opcoes(self.pasta, "D1", online=True)["cor"], "verde")
            self.assertEqual(buscas[-1], "LED 5mm green", "verde é Green na loja (não Emerald Green)")
        finally:
            loja.buscar, catalogo.salvar = buscar, salvar


class SemCerebro(unittest.TestCase):
    def setUp(self):
        self.pasta = copia()
        (self.pasta / "pecas").mkdir()
        tipos = {"C5365915": ("pilha", {**CR2032, "i_testada": 0.0068}), "C779439": ("led", LED_LOJA), "C119310": ("resistor", None)}
        for codigo, (bloco, el) in tipos.items():
            tipo = tipo_do_catalogo(codigo, bloco)
            tipo["eletrica"] = el or tipo["eletrica"]
            (self.pasta / "pecas" / f"{codigo}.json").write_text(json.dumps(tipo, ensure_ascii=False))
        (self.pasta / "placa.txt").write_text((self.pasta / "placa.txt").read_text().replace("R1 resistor_axial", "R1 C119310")
                                              .replace("D1 led_5mm", "D1 C779439").replace("BT1 pilha_cr2032", "BT1 C5365915"))
        self.blocos = [{"ref": "BT1", "bloco": "pilha", "peca": "C5365915"}, {"ref": "R1", "bloco": "resistor", "peca": "C119310"},
                       {"ref": "D1", "bloco": "led", "peca": "C779439"}]

    def tearDown(self):
        apagar(self.pasta)

    def escrever(self, blocos_proj):
        (self.pasta / "projeto.json").write_text(json.dumps({"objetivo": "lanterninha", "frase": "f", "blocos": blocos_proj,
                                                             "perguntas": {"brilho": {"resposta": "fraca", "quem": "Luiz"}}}))

    def test_lanterninha_tem_as_mesmas_chaves_e_mais_totais(self):
        self.escrever(self.blocos)
        e = blocos.estado(self.pasta)
        self.assertEqual(set(e), {"objetivo", "frase", "perguntas", "blocos", "total", "totais", "pronto"})
        self.assertEqual(set(pergunta(e, "brilho")), {"id", "texto", "resposta", "quem", "opcoes"})
        self.assertEqual([q["id"] for q in e["perguntas"]], ["brilho"], "sem cérebro não tem a pergunta da cor")
        for b in e["blocos"]:
            self.assertEqual(set(b) - {"conta"}, {"ref", "bloco", "nome", "funcao", "por_que", "quem", "peca", "na_placa"}, b["ref"])
        conta = item(e, "R1")["conta"]
        self.assertEqual(set(conta), {"i", "ohms", "padrao", "i_padrao", "joelho", "brilho", "r_interna", "r_s", "v",
                                      "resposta", "i_testada", "mah", "bate"})
        self.assertEqual(conta["padrao"], 240)
        self.assertEqual(e["totais"], {"BRL": 0.0, "USD": e["total"]})
        self.assertEqual([o["explica"] for o in pergunta(e, "brilho")["opcoes"]],
                         [o["explica"] for o in blocos.PERGUNTAS["brilho"]["opcoes"].values()], "o texto da pilha fica")

    def test_ajuste_por_led_vale_na_conta_da_lanterninha(self):
        self.escrever(self.blocos)   # o geral é fraca
        blocos.responder(self.pasta, "brilho", "forte", quem="Luiz", ref="D1")
        e = blocos.estado(self.pasta)
        self.assertEqual((item(e, "R1")["conta"]["padrao"], item(e, "R1")["conta"]["resposta"]), (43, "forte"))
        self.assertEqual(pergunta(e, "brilho")["por_led"][0]["resposta"], "forte", "o que a conta usa é o que aparece")

    def test_resposta_que_nao_existe_pede_pra_responder(self):
        """projeto.json editado à mão com um brilho que não existe: a conta pede a resposta, sem quebrar o estado"""
        self.escrever(self.blocos)
        proj = blocos.ler_projeto(self.pasta)
        proj["perguntas"]["brilho"]["resposta"] = "cegante"
        blocos.salvar_projeto(self.pasta, proj)
        e = blocos.estado(self.pasta)
        self.assertEqual(item(e, "R1")["conta"], {"falta": ["responder quanta luz você quer"]})
        self.assertFalse(e["pronto"])

    def test_pilha_sem_forca_pede_menos_luz_onde_da_pra_pedir(self):
        """sem cérebro, a pergunta só mostra o ajuste de cada LED se o projeto já tem um: senão, o aviso manda pra geral"""
        arq = self.pasta / "pecas" / "C5365915.json"
        tipo = json.loads(arq.read_text())
        tipo["eletrica"]["v"] = 1.5
        arq.write_text(json.dumps(tipo, ensure_ascii=False))
        self.escrever(self.blocos)
        conta = item(blocos.estado(self.pasta), "R1")["conta"]
        self.assertTrue(conta["impossivel"])
        self.assertIn("peça menos luz na pergunta 'Quanta luz você quer?'", conta["aviso"])
        self.assertNotIn("ajuste de cada LED", conta["aviso"])
        blocos.responder(self.pasta, "brilho", "media", ref="D1")
        e = blocos.estado(self.pasta)
        self.assertIn("o ajuste de cada LED", item(e, "R1")["conta"]["aviso"])
        self.assertIn("por_led", pergunta(e, "brilho"), "e o ajuste aparece na pergunta")

    def test_resistor_com_led_e_pilha_faz_a_conta_da_lanterninha(self):
        self.escrever(self.blocos)
        classica = item(blocos.estado(self.pasta), "R1")["conta"]
        self.escrever([{**b, "led": "D1"} if b["ref"] == "R1" else b for b in self.blocos])
        com_led = item(blocos.estado(self.pasta), "R1")["conta"]
        self.assertEqual({k: v for k, v in com_led.items() if k not in ("led", "resposta_do_led")}, classica)
        self.escrever([{**b, "led": "BT1"} if b["ref"] == "R1" else b for b in self.blocos])
        self.assertIn("BT1", item(blocos.estado(self.pasta), "R1")["conta"]["falta"][0], "o 'led' tem que ser um LED")


def placa_de_ensaio(blocos_proj, txt=None):
    """placa temporária com projeto.json e (se txt) um placa.txt; o pecas/ fica pro escolher"""
    pasta = Path(tempfile.mkdtemp(prefix="sianvolt-teste-")) / "ensaio"
    pasta.mkdir()
    if txt is not None:
        (pasta / "placa.txt").write_text(txt)
    (pasta / "projeto.json").write_text(json.dumps({"objetivo": "ensaio", "frase": "", "perguntas": {}, "blocos": blocos_proj},
                                                   ensure_ascii=False))
    return pasta


# um LED da loja num resistor da biblioteca; o D10 (outro LED, só no txt) não pode mudar quando o D1 vira
TXT_DO_LED = """placa 60 30
peca R1 resistor_axial 10 10 130
peca D1 {led} 25 10
peca D10 led_5mm 40 10
liga R1.2 D1.2    # o + do LED
liga D1.1 GND   # o − é o D1.1 (o D10.1 é outro LED)
liga R1.1 D10.1
liga D10.2 GND
"""
BLOCOS_DO_LED = [{"ref": "R1", "bloco": "resistor", "led": "D1"}, {"ref": "D1", "bloco": "led"}]


def ligas_de(pasta):
    return [l for l in (pasta / "placa.txt").read_text().splitlines() if l.startswith("liga")]


class Escolher(unittest.TestCase):
    """o escolher sem rede: a loja de verdade nunca é chamada e nada é gravado no catálogo
    (o desenho do EasyEDA é um de 2 furos feito à mão; o símbolo dele, os nomes A/K dos pinos, muda por teste).
    O catálogo do teste é uma cópia do ferramenta/catalogo/: outro programa gravando no de verdade (um loja.importar)
    não derruba o teste, e o que o escolher gravasse apareceria na cópia"""

    def setUp(self):
        self.guardado = (loja.importar, loja.ficha, loja.desenho, loja.pagina, loja.pedir, catalogo.salvar, catalogo.PASTA)
        catalogo.PASTA = Path(tempfile.mkdtemp(prefix="sianvolt-teste-")) / "catalogo"
        shutil.copytree(self.guardado[-1], catalogo.PASTA)
        self.catalogo_antes = {arq.name: arq.read_bytes() for arq in catalogo.PASTA.glob("*.json")}
        self.importados, self.simbolo, self.fichas, self.pasta = [], {}, {}, None

        def sem_rede(*_a, **_k):
            raise AssertionError("o teste não vai na loja nem grava no catálogo")

        def pedir(url, *_a, **_k):   # só a resposta do EasyEDA (o desenho dela é o loja.desenho daqui)
            if url.startswith("https://easyeda.com/"):
                return "{}"
            sem_rede()

        def importar(codigo, bloco, pasta):   # o caminho de sempre (atualizar_catalogo=True), sem rede
            self.importados.append(codigo)
            return blocos.importar_sem_catalogo(codigo, bloco, pasta)[0]
        loja.importar, loja.pedir, catalogo.salvar = importar, pedir, sem_rede
        loja.ficha = lambda codigo, validade=None: dict(self.fichas[codigo])
        loja.desenho = lambda codigo: {"pacote": "teste", "silk": [], "corpo": [5.8, 5.0], "simbolo": dict(self.simbolo),
                                       "pads": [{"n": n, "x": x, "y": 0.0, "w": 1.6, "h": 1.6, "furo": 0.8, "forma": "C"}
                                                for n, x in (("1", -1.27), ("2", 1.27))]}
        loja.pagina = lambda codigo: {"foto": None, "pdf": None}

    def tearDown(self):
        depois = {arq.name: arq.read_bytes() for arq in catalogo.PASTA.glob("*.json")}
        apagar(catalogo.PASTA)
        (loja.importar, loja.ficha, loja.desenho, loja.pagina, loja.pedir, catalogo.salvar, catalogo.PASTA) = self.guardado
        if self.pasta:
            apagar(self.pasta)
        self.assertEqual(depois, self.catalogo_antes, "nada muda no catálogo")

    def ficha_de(self, codigo, novo):
        """a ficha da loja de uma peça que o catálogo não tem: a de uma que ele tem, com outro código"""
        e = CATALOGO["pecas"][codigo]
        self.fichas[novo] = {"codigo": novo, "categoria": e["categoria_loja"],
                             **{k: e[k] for k in ("modelo", "marca", "pacote", "descricao", "estoque", "preco",
                                                  "minimo", "datasheet", "link", "atributos")}}

    def placa_com_led(self, codigo):
        """o D1 já com esse LED na placa: o pecas/ dele vem do catálogo, sem gravar nele"""
        self.pasta = placa_de_ensaio(BLOCOS_DO_LED, TXT_DO_LED.format(led=codigo))
        blocos.importar_sem_catalogo(codigo, "led", self.pasta)
        return self.pasta

    def test_cerebro_de_loja_brasileira_vai_pelo_tipo(self):
        self.pasta = placa_de_ensaio([{"ref": "U1", "bloco": "cerebro"}], "placa 80 50\npeca U1 esp32_devkit 40 25\n")
        r = blocos.escolher(self.pasta, "U1", ROBOCORE)
        self.assertEqual(self.importados, [], "loja brasileira não passa pelo loja.importar")
        self.assertIn("peca U1 devkit_esp32_30 40 25   # ", (self.pasta / "placa.txt").read_text())
        self.assertEqual((r["na_placa"], r["no_txt"], r["pendente"], r["ligas"]), (True, "devkit_esp32_30", [], []))
        self.assertIn("no placa.txt é o devkit_esp32_30", r["frase"])
        self.assertFalse((self.pasta / "pecas").exists(), "o desenho vem da biblioteca: nada em pecas/")
        u1 = blocos.bloco_do_ref(blocos.ler_projeto(self.pasta), "U1")
        self.assertEqual((u1["peca"], u1["quem"]), (ROBOCORE, "Luiz"))
        e = blocos.estado(self.pasta)
        self.assertTrue(item(e, "U1")["na_placa"], "o na_placa compara pelo tipo da biblioteca")
        self.assertEqual(item(e, "U1")["peca"]["tipo"], "devkit_esp32_30")
        barras = 2 * CATALOGO["pecas"]["C41417327"]["preco"]   # as 2 barras fêmea hanxia, da LCSC
        self.assertEqual(e["totais"], {"BRL": 42.9, "USD": round(barras, 4)})
        self.assertEqual(blocos.escolher(self.pasta, "U1", ROBOCORE, atualizar_catalogo=False)["na_placa"], True,
                         "de novo, e sem atualizar o catálogo: o mesmo")

    def test_cerebro_so_sai_do_catalogo_com_tipo(self):
        self.pasta = placa_de_ensaio([{"ref": "U1", "bloco": "cerebro"}, {"ref": "D1", "bloco": "led"}],
                                     "placa 80 50\npeca U1 esp32_devkit 40 25\npeca D1 led_5mm 5 5\n")
        gravado = lambda: ((self.pasta / "placa.txt").read_text(), blocos.ler_projeto(self.pasta))
        antes = gravado()
        for ref, codigo, trecho in (("U1", "C10081", "não vem da LCSC"), ("U1", "robocore:nao-existe", "não está no catálogo"),
                                    ("D1", ROBOCORE, "não serve pro bloco LED"), ("X9", ROBOCORE, "não é um bloco")):
            with self.assertRaises(ValueError, msg=codigo) as erro:
                blocos.escolher(self.pasta, ref, codigo, atualizar_catalogo=False)
            self.assertIn(trecho, str(erro.exception))
        proj = blocos.ler_projeto(self.pasta)
        proj["blocos"].append({"ref": "Q1", "bloco": "transistor"})   # projeto.json editado à mão
        blocos.salvar_projeto(self.pasta, proj)
        with self.assertRaises(ValueError):
            blocos.escolher(self.pasta, "Q1", "C10081", atualizar_catalogo=False)
        proj["blocos"].pop()
        blocos.salvar_projeto(self.pasta, proj)
        led_sem_tipo = {**CATALOGO["pecas"]["C779441"], "loja": "Baú", "tipo": "nao_existe"}   # um LED de loja brasileira
        with self.assertRaises(ValueError) as erro:
            blocos.peca_de_outra_loja("bau:led", "led", {"pecas": {"bau:led": led_sem_tipo}})
        self.assertIn("tipo da biblioteca", str(erro.exception))
        self.assertEqual(gravado(), antes, "o erro não grava nada")
        self.assertEqual(self.importados, [])

    def test_led_com_o_mais_em_outro_pino_vira_as_ligas(self):
        """TUOZHAN C779441: + no pino 2; TONYU C7433012: + no pino 1"""
        self.placa_com_led("C779441")
        antes = ligas_de(self.pasta)
        r = blocos.escolher(self.pasta, "D1", "C7433012", atualizar_catalogo=False)
        self.assertEqual(ligas_de(self.pasta), ["liga R1.2 D1.1    # o + do LED",
                                                "liga D1.2 GND   # o − é o D1.2 (o D10.1 é outro LED)",
                                                "liga R1.1 D10.1", "liga D10.2 GND"],
                         "o D10 fica; o comentário que fala do pino do D1 vira junto e continua certo")
        self.assertEqual(r["ligas"], [{"antes": "liga R1.2 D1.2", "depois": "liga R1.2 D1.1"},
                                      {"antes": "liga D1.1 GND", "depois": "liga D1.2 GND"}])
        self.assertIn("no desenho do LED novo o + fica no outro furo: virei as 2 ligações do D1", r["frase"])
        self.assertIn("trocou o D1 por LED branco 5 mm (quente ou frio? o datasheet se contradiz), código C7433012, "
                      "no carrinho", r["frase"], "sem parêntese em dobro")
        self.assertNotIn("avisos", r, "os dois LEDs têm o + e o − conferidos")
        # o + continua no resistor e o − no GND, pelo que foi conferido no datasheet
        mais, menos = blocos.polos_do_led(blocos.carregar_pecas(self.pasta)["C7433012"])
        ligas = {(l["de"], l["ate"]) for l in gerar.ler((self.pasta / "placa.txt").read_text())["ligas"]}
        self.assertTrue({("R1.2", f"D1.{mais}"), (f"D1.{menos}", "GND")} <= ligas)
        volta = blocos.escolher(self.pasta, "D1", "C779441", atualizar_catalogo=False)
        self.assertEqual(ligas_de(self.pasta), antes, "e de volta pro amarelo, as ligas voltam")
        self.assertEqual(len(volta["ligas"]), 2)

    def test_led_com_o_mais_no_mesmo_pino_nao_mexe(self):
        self.placa_com_led("C779439")
        antes = (self.pasta / "placa.txt").read_text().splitlines()
        r = blocos.escolher(self.pasta, "D1", "C779441", atualizar_catalogo=False)
        depois = (self.pasta / "placa.txt").read_text().splitlines()
        self.assertEqual([l for l in depois if not l.startswith("peca D1 ")], [l for l in antes if not l.startswith("peca D1 ")])
        self.assertIn("peca D1 C779441 25 10   # LED amarelo 5 mm, escolhido no carrinho", depois)
        self.assertEqual((r["ligas"], "avisos" in r, r["na_placa"]), ([], False, True))
        self.assertEqual(blocos.escolher(self.pasta, "D1", "C779441", atualizar_catalogo=False)["ligas"], [], "o mesmo LED de novo")

    def test_do_led_da_biblioteca_pro_da_loja_monta_virado_certo(self):
        """a lanterninha de teste usa o led_5mm (+ no 1); o C779439 tem o + no 2. Montada, a placa liga o + no resistor"""
        self.pasta = copia()
        (self.pasta / "projeto.json").write_text(json.dumps({"objetivo": "teste", "perguntas": {}, "blocos": [
            {"ref": "BT1", "bloco": "pilha"}, {"ref": "R1", "bloco": "resistor"}, {"ref": "D1", "bloco": "led"}]}))
        r = blocos.escolher(self.pasta, "D1", "C779439", atualizar_catalogo=False)
        self.assertEqual([x["depois"] for x in r["ligas"]], ["liga R1.2 D1.2", "liga D1.1 GND"])
        modelo = gerar.montar(gerar.ler((self.pasta / "placa.txt").read_text()), gerar.biblioteca(self.pasta))
        net = {(p["ref"], q["n"]): q["net"] for p in modelo["pecas"] for q in p["pinos"]}
        self.assertEqual(net[("D1", "2")], net[("R1", "2")], "o + do C779439 (pino 2) no resistor")
        self.assertEqual(net[("D1", "1")], "GND")

    def test_led_sem_o_mais_conferido(self):
        """um LED que o catálogo não tem: a ficha vem da loja (aqui, uma cópia da do C779441) e o + sai do símbolo"""
        self.placa_com_led("C779441")
        self.ficha_de("C779441", "C900000003")
        self.simbolo = {"1": "A", "2": "K"}   # A = +: o + no pino 1
        r = blocos.escolher(self.pasta, "D1", "C900000003", atualizar_catalogo=False)
        self.assertTrue(r["pendente"], "sem conferido: falta ler o datasheet")
        self.assertEqual([x["depois"] for x in r["ligas"]], ["liga R1.2 D1.1", "liga D1.2 GND"])
        self.assertTrue(any("não foram conferidos no datasheet" in a for a in r["avisos"]))
        self.assertTrue(any("não está no catálogo" in a for a in r["avisos"]))
        self.simbolo = {"1": "", "2": ""}   # o desenho não diz qual é o +: não vira nada e avisa
        blocos.escolher(self.pasta, "D1", "C779441", atualizar_catalogo=False)   # volta (o + no 2, conferido)
        antes = ligas_de(self.pasta)
        self.fichas["C900000004"] = {**self.fichas["C900000003"], "codigo": "C900000004"}
        r = blocos.escolher(self.pasta, "D1", "C900000004", atualizar_catalogo=False)
        self.assertEqual((ligas_de(self.pasta), r["ligas"]), (antes, []))
        self.assertTrue(any("não sei qual furo é o + do LED novo (LED amarelo 5 mm, código C900000004)" in a
                            for a in r["avisos"]), r["avisos"])

    def test_sem_atualizar_catalogo_a_peca_sai_do_conferido(self):
        proj = [{"ref": "D1", "bloco": "led"}, {"ref": "LDR1", "bloco": "ldr"}, {"ref": "BZ1", "bloco": "buzzer"},
                {"ref": "R1", "bloco": "resistor", "para": "LDR1"}, {"ref": "R2", "bloco": "resistor", "para": "BZ1"}]
        provisorio = lambda b: "led_5mm" if b["bloco"] == "led" else "resistor_axial"   # o tipo de antes da loja
        self.pasta = placa_de_ensaio(proj, "placa 60 40\n" + "".join(f"peca {b['ref']} {provisorio(b)} {5 + 9 * i} 5\n"
                                                                      for i, b in enumerate(proj)))
        for ref, codigo in (("D1", "C7433012"), ("LDR1", "C10081"), ("BZ1", "C128650"), ("R1", "C119354"), ("R2", "C713997")):
            r = blocos.escolher(self.pasta, ref, codigo, quem="sugestão do Claude", atualizar_catalogo=False)
            self.assertTrue(r["na_placa"], codigo)
            tipo, e = blocos.carregar_pecas(self.pasta)[codigo], CATALOGO["pecas"][codigo]
            self.assertEqual(tipo["eletrica"], e["conferido"]["eletrica"], f"{codigo}: a elétrica é a conferida")
            self.assertEqual((tipo["loja"]["preco"], tipo["loja"]["estoque"]), (e["preco"], e["estoque"]), codigo)
            self.assertEqual(tipo["pendente"], [], codigo)
            self.assertEqual(tipo["nome"], e.get("apelido") or e["nome"], f"{codigo}: o nome é o mesmo do catálogo")
        self.assertEqual(self.importados, [], "atualizar_catalogo=False não chama o loja.importar")
        pecas = blocos.carregar_pecas(self.pasta)
        self.assertEqual(pecas["C7433012"]["nome"], CATALOGO["pecas"]["C7433012"]["apelido"], "a loja não diz a cor: vale o apelido")
        self.assertEqual((pecas["C119354"]["valor"], pecas["C713997"]["valor"]), (22000, 1000))
        self.assertEqual(blocos.bloco_do_ref(blocos.ler_projeto(self.pasta), "R1")["quem"], "sugestão do Claude")
        self.assertIn("peca R1 C119354 32 5   # Resistor 22 kΩ, 250 mW, escolhido no carrinho", (self.pasta / "placa.txt").read_text())

    def test_ficha_do_catalogo_da_o_nome_do_catalogo(self):
        """a ficha montada do catálogo é a da loja: o nome que sai dela é o mesmo que o catálogo guardou"""
        bloco_de = {cid: bloco for bloco, cid in blocos.CATEGORIA.items()}
        pecas = [(c, e) for c, e in CATALOGO["pecas"].items()
                 if e["categoria"] in bloco_de and e.get("loja", "LCSC") == "LCSC" and not e.get("apelido")]
        self.assertGreater(len({e["categoria"] for _, e in pecas}), 5)
        self.assertIn("C5134", dict(pecas), "um fototransistor: o nome dele sai da categoria da loja")
        for codigo, e in pecas:
            self.assertEqual(blocos.nome_da_loja(bloco_de[e["categoria"]], blocos.ficha_do_catalogo(codigo, e)), e["nome"], codigo)

    def test_peca_sem_estoque_no_catalogo_avisa(self):
        self.placa_com_led("C779441")
        ler = catalogo.ler

        def sem_estoque():
            cat = ler()
            cat["pecas"]["C779443"] = {**cat["pecas"]["C779443"], "situacao": "sem estoque"}
            return cat
        catalogo.ler = sem_estoque
        try:
            r = blocos.escolher(self.pasta, "D1", "C779443", atualizar_catalogo=False)
        finally:
            catalogo.ler = ler
        self.assertTrue(any("'sem estoque'" in a for a in r["avisos"]), r.get("avisos"))

    def test_sem_o_desenho_no_cache_nao_grava_nada(self):
        self.placa_com_led("C779441")
        gravado = lambda: ((self.pasta / "placa.txt").read_text(), blocos.ler_projeto(self.pasta),
                           sorted(a.name for a in (self.pasta / "pecas").iterdir()))
        antes = gravado()

        def sem_internet(url, *_a, **_k):
            raise loja.SemLoja("a loja não respondeu (sem rede)")

        def sem_desenho(codigo):   # o EasyEDA respondeu, mas sem o desenho
            raise loja.SemLoja(f"o EasyEDA não tem o desenho de {codigo}")
        loja.pedir = sem_internet
        with self.assertRaises(loja.SemLoja) as erro:
            blocos.escolher(self.pasta, "D1", "C7433012", atualizar_catalogo=False)
        self.assertIn("o desenho do C7433012 (EasyEDA) ainda não está no cache da loja: precisa de internet uma vez",
                      str(erro.exception))
        self.assertEqual(gravado(), antes)
        loja.pedir, loja.desenho = (lambda url, *_a, **_k: '{"success": false}'), sem_desenho
        with self.assertRaises(loja.SemLoja) as erro:
            blocos.escolher(self.pasta, "D1", "C7433012", atualizar_catalogo=False)
        self.assertEqual(str(erro.exception), "o EasyEDA não tem o desenho de C7433012", "a internet não resolve: não pede ela")
        self.assertEqual(gravado(), antes)

    def test_atualizar_catalogo_e_o_caminho_de_sempre(self):
        self.placa_com_led("C779441")
        r = blocos.escolher(self.pasta, "D1", "C7433012")
        self.assertEqual(self.importados, ["C7433012"], "o padrão continua o loja.importar")
        self.assertEqual(len(r["ligas"]), 2, "e a troca do + vale também")

    def test_quem_e_um_nome_e_o_catalogo_vai_pelo_nome(self):
        """escolher(p, ref, codigo, False) seria quem=False e iria pro loja.importar: para antes de gravar"""
        self.placa_com_led("C779441")
        gravado = lambda: ((self.pasta / "placa.txt").read_text(), blocos.ler_projeto(self.pasta))
        antes = gravado()
        with self.assertRaises(TypeError) as erro:
            blocos.escolher(self.pasta, "D1", "C779439", False)
        self.assertIn("atualizar_catalogo=False", str(erro.exception))
        with self.assertRaises(TypeError):
            blocos.escolher(self.pasta, "D1", "C779439", "Luiz", False)   # o atualizar_catalogo só vai pelo nome
        self.assertEqual((gravado(), self.importados), (antes, []))

    def test_peca_da_lcsc_de_outra_categoria_nao_entra(self):
        """um LDR ou um resistor no bloco do LED: nem pelo catálogo, nem pela loja (a peça que o catálogo não tem)"""
        self.placa_com_led("C779441")
        gravado = lambda: ((self.pasta / "placa.txt").read_text(), blocos.ler_projeto(self.pasta),
                           sorted(a.name for a in (self.pasta / "pecas").iterdir()))
        antes = gravado()
        self.ficha_de("C10081", "C900000005")   # um LDR que o catálogo não tem
        casos = {"C10081": "(LDR (fotorresistor) 8kΩ~20kΩ) não serve pro bloco LED: no catálogo ele está em Sensor de luz",
                 "C119310": "(Resistor 240 Ω, 250 mW) não serve pro bloco LED: no catálogo ele está em Resistor",
                 "C900000005": f"não serve pro bloco LED: na loja ele está em {CATALOGO['pecas']['C10081']['categoria_loja']}"}
        for codigo, trecho in casos.items():
            for atualizar in (True, False):
                with self.assertRaises(ValueError, msg=(codigo, atualizar)) as erro:
                    blocos.escolher(self.pasta, "D1", codigo, atualizar_catalogo=atualizar)
                self.assertIn(trecho, str(erro.exception))
        self.assertEqual((gravado(), self.importados), (antes, []), "o erro vem antes de gravar e do loja.importar")
        with self.assertRaises(ValueError):
            blocos.importar_sem_catalogo("C10081", "led", self.pasta)
        self.assertEqual(gravado(), antes)

    def test_led_sem_ligacao_nao_avisa_do_mais(self):
        """o + do LED de antes ninguém conhece: só avisa quando tem ligação do LED pra conferir"""
        self.pasta = placa_de_ensaio(BLOCOS_DO_LED, "placa 60 30\npeca D1 C999999 25 10\n")
        self.assertNotIn("avisos", blocos.escolher(self.pasta, "D1", "C779441", atualizar_catalogo=False))
        self.pasta.joinpath("placa.txt").write_text("placa 60 30\npeca D1 C999999 25 10\nliga D1.2 GND\n")
        r = blocos.escolher(self.pasta, "D1", "C779439", atualizar_catalogo=False)
        self.assertEqual(r["avisos"], ["não sei qual furo é o + do LED de antes (C999999): as ligações do D1 ficaram "
                                       "como estavam; confira o + e o − delas antes de fabricar"])

    def test_cerebro_com_outra_numeracao_avisa(self):
        """o esp32_devkit antigo não dá nome aos furos; no devkit_esp32_30 o furo 2 é o GPIO36 (só entrada)"""
        txt = "placa 80 50\npeca U1 esp32_devkit 40 25\npeca R1 resistor_axial 10 10 130\n" \
              "liga U1.11 R1.1\nliga R1.2 GND\nliga U1.2 GND\n"
        self.pasta = placa_de_ensaio([{"ref": "U1", "bloco": "cerebro"}, {"ref": "R1", "bloco": "resistor"}], txt)
        r = blocos.escolher(self.pasta, "U1", ROBOCORE)
        self.assertEqual(ligas_de(self.pasta), ["liga U1.11 R1.1", "liga R1.2 GND", "liga U1.2 GND"], "não adivinha")
        self.assertEqual(len(r["avisos"]), 1)
        self.assertIn("as ligações do U1 ficaram como estavam: U1.2 agora é o GPIO36, U1.11 agora é o GPIO14. Confira",
                      r["avisos"][0])
        self.assertNotIn("avisos", blocos.escolher(self.pasta, "U1", ROBOCORE), "a mesma peça: nada muda")

    def test_carrinho_antes_do_placa_txt(self):
        self.pasta = placa_de_ensaio(BLOCOS_DO_LED)
        self.assertFalse(blocos.trocar_no_txt(self.pasta, "D1", "C779441", "x"))
        r = blocos.escolher(self.pasta, "D1", "C779441", atualizar_catalogo=False)
        self.assertEqual((r["na_placa"], r["ligas"]), (False, []))
        self.assertFalse((self.pasta / "placa.txt").exists(), "o desenho é depois: o escolher não cria o placa.txt")
        self.assertTrue((self.pasta / "pecas" / "C779441.json").exists())


if __name__ == "__main__":
    unittest.main()
