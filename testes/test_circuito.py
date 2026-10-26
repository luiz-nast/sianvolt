"""o simulador (circuito.py): contas que dá pra fazer à mão, e leis que valem pra qualquer circuito (sorteado)"""
import random
import unittest

from apoio import CHAVE, LED, PILHA, RESISTOR, peca
import circuito


def resolver(pecas, ajustes=None):
    return circuito.resolver({"pecas": pecas}, ajustes)


# o ESP32 montado à mão (sem depender do tipo da biblioteca): os números da decisão 'Modelo elétrico do ESP32'
MCU = {"modelo": "mcu", "vdd": 3.3,
       "r_pino": 30,       # Pin.DRIVE_2, MicroPython quickref (estimativa, não é datasheet), igual ao gêmeo
       "r_pull": 45000,    # pull-up de dentro, ESP32 datasheet v5.3, Tabela 5-3
       "r_3v3": 0.05}      # suposição do gêmeo (laboratorio/motores/gemeo/chips/comum.py), pendente
# LDR GL5528 (C10081), datasheet JCHL GL55: 8–20 kΩ a 10 lux, gama 0,65 (p. 1), erro do gama ± 0,1 (p. 2), escuro 1 MΩ
LDR = {"modelo": "ldr", "r10_min": 8000, "r10_max": 20000, "gama": 0.65, "gama_tol": 0.1, "r_escuro": 1e6}
PIEZO = {"modelo": "piezo"}           # em corrente contínua não importa a capacitância
CAPACITOR = {"modelo": "capacitor"}


def mcu(nets, eletrica=MCU, ref="U1"):
    """peça mcu à mão, no estilo do apoio.peca: nets = {nome do pino: net}; os pinos são numerados na ordem"""
    return {"ref": ref, "eletrica": eletrica, "valor": None,
            "pinos": [{"n": str(k), "nome": nome, "net": net} for k, (nome, net) in enumerate(nets.items(), 1)]}


def com_esp32(pecas, estado, ajustes=None, vdd=None):
    return circuito.resolver(circuito.com_pinos({"pecas": pecas}, estado, vdd), ajustes)


def sortear_com_esp32(rnd):
    """circuito sorteado com o ESP32 no lugar da pilha: (modelo, estado dos pinos, vdd, ajustes)"""
    nets = ["GND", "N3V3"] + [f"N{i}" for i in range(1, rnd.randint(2, 6))]
    pinos = {"GND": "GND", "3V3": rnd.choice(["N3V3", None])}
    for g in rnd.sample(["GPIO4", "GPIO13", "GPIO14", "GPIO25", "GPIO32", "GPIO34"], rnd.randint(1, 4)):
        pinos[g] = rnd.choice(nets + [None])
    sem_r_3v3 = {k: v for k, v in MCU.items() if k != "r_3v3"}   # com o 3V3 solto, o r_3v3 não faz falta
    pecas = [mcu(pinos, MCU if pinos["3V3"] or rnd.random() < 0.5 else sem_r_3v3)]
    if rnd.random() < 0.4:   # outro GND, às vezes noutra net: o terra é o GND de nome menor, nos dois lados
        pecas[0]["pinos"].append({"n": str(len(pinos) + 1), "nome": "GND", "net": rnd.choice(["AGND", "GND", "N1", None])})
    for i in range(rnd.randint(2, 9)):
        a, b = rnd.sample(nets, 2)
        s = rnd.random()
        if s < 0.2:
            led = LED if rnd.random() < 0.5 else {**LED, "mais": "2", "menos": "1"}
            pecas.append(peca(f"D{i}", led, {"1": a, "2": b}))
        elif s < 0.3:
            pecas.append(peca(f"SW{i}", CHAVE, {"1": a, "2": a, "3": b, "4": b}))
        elif s < 0.45:
            pecas.append(peca(f"LDR{i}", LDR, {"1": a, "2": b}))
        elif s < 0.55:
            pecas.append(peca(f"BZ{i}", PIEZO, {"1": a, "2": b}))
        elif s < 0.62:
            pecas.append(peca(f"C{i}", CAPACITOR, {"1": a, "2": b}))
        else:
            pecas.append(peca(f"R{i}", RESISTOR, {"1": a, "2": b}, valor=rnd.choice([10, 220, 1000, 22000])))
    refs = [p["ref"] for p in pecas]
    estado = {g: rnd.choice([1, 0, "pullup", None, True, False]) for g in pinos if g.startswith("GPIO")}
    aj = {"chave": {r: rnd.random() < 0.6 for r in refs if r.startswith("SW")},
          "ldr": {r: circuito.ohms_do_ldr(LDR, rnd.choice([None, 0.5, 1, 10, 23, 100]), rnd.choice(["min", "meio", "max"]))
                  for r in refs if r.startswith("LDR") and rnd.random() < 0.7},   # o resto fica em 10 lux
          "piezo": {r: rnd.random() < 0.5 for r in refs if r.startswith("BZ")}}
    return {"pecas": pecas}, estado, rnd.choice([None, 3.201, 3.399]), aj   # vdd_min e vdd_max do AMS1117 (decisão)


class ContasAMao(unittest.TestCase):
    def serie(self, v=3.0, ohms=100.0, led=LED, pilha=PILHA, invertido=False):
        a, k = ("N2", "GND") if not invertido else ("GND", "N2")
        return resolver([peca("BT1", pilha, {"1": "N1", "2": "GND"}),
                         peca("R1", RESISTOR, {"1": "N1", "2": "N2"}, valor=ohms),
                         peca("D1", led, {"1": a, "2": k})], {"pilha": {"BT1": v}})

    def test_lanterninha_da_conta_do_papel(self):
        # I = (pilha − joelho) / (R + r_s + a resistência mínima da pilha); joelho = vf − r_s·i_teste = 1,9 − 0,2 = 1,7 V
        s = self.serie()
        esperado = (3.0 - 1.7) / (100 + 20 + circuito.R_PILHA)
        self.assertAlmostEqual(s["pecas"]["D1"]["i"], esperado, delta=1e-6)
        self.assertAlmostEqual(s["pecas"]["R1"]["i"], esperado, delta=1e-6)
        self.assertAlmostEqual(s["pecas"]["R1"]["p"], esperado ** 2 * 100, delta=1e-7)
        self.assertTrue(s["pecas"]["D1"]["acende"])
        self.assertFalse(s["pecas"]["D1"]["queima"])

    def test_resistencia_interna_da_pilha_entra_na_conta(self):
        s = self.serie(pilha={**PILHA, "r_interna": 10})
        self.assertAlmostEqual(s["pecas"]["D1"]["i"], (3.0 - 1.7) / (100 + 20 + 10), delta=1e-6)

    def test_pilha_abaixo_do_joelho_nao_acende(self):
        s = self.serie(v=1.6)
        self.assertEqual(s["pecas"]["D1"]["i"], 0.0)
        self.assertFalse(s["pecas"]["D1"]["acende"])

    def test_led_ao_contrario_nao_passa_corrente(self):
        s = self.serie(invertido=True)
        self.assertEqual(s["pecas"]["D1"]["i"], 0.0)
        self.assertAlmostEqual(s["pecas"]["R1"]["i"], 0.0, delta=1e-6)

    def test_resistor_pequeno_queima_o_led(self):
        s = self.serie(v=3.3, ohms=10)
        self.assertTrue(s["pecas"]["D1"]["queima"])

    def test_led_da_loja_com_mais_e_menos_trocados(self):
        led = {**LED, "mais": "2", "menos": "1"}   # como o C779439: pino 2 é o +
        s = resolver([peca("BT1", PILHA, {"1": "N1", "2": "GND"}), peca("R1", RESISTOR, {"1": "N1", "2": "N2"}, valor=100),
                      peca("D1", led, {"2": "N2", "1": "GND"})])
        self.assertGreater(s["pecas"]["D1"]["i"], 0.01)

    def test_chave_solta_abre_e_apertada_fecha(self):
        pecas = [peca("BT1", PILHA, {"1": "N1", "2": "GND"}), peca("SW1", CHAVE, {"1": "N1", "2": "N1", "3": "N2", "4": "N2"}),
                 peca("R1", RESISTOR, {"1": "N2", "2": "N3"}, valor=100), peca("D1", LED, {"1": "N3", "2": "GND"})]
        self.assertEqual(resolver(pecas, {"chave": {"SW1": False}})["pecas"]["D1"]["i"], 0.0)
        self.assertGreater(resolver(pecas, {"chave": {"SW1": True}})["pecas"]["D1"]["i"], 0.01)

    def test_pino_sem_net_nao_quebra(self):
        s = resolver([peca("BT1", PILHA, {"1": "N1", "2": "GND"}), peca("R1", RESISTOR, {"1": "N1", "2": None}, valor=100)])
        self.assertEqual(s["pecas"]["R1"]["i"], 0.0)

    def test_duas_pilhas_em_paralelo(self):
        s = resolver([peca("BT1", PILHA, {"1": "N1", "2": "GND"}), peca("BT2", PILHA, {"1": "N1", "2": "GND"}),
                      peca("R1", RESISTOR, {"1": "N1", "2": "GND"}, valor=300)])
        self.assertAlmostEqual(s["pecas"]["BT1"]["i"] + s["pecas"]["BT2"]["i"], 3.0 / 300, delta=1e-6)

    def test_sem_pilha_nao_tem_o_que_ligar(self):
        self.assertIsNone(resolver([peca("R1", RESISTOR, {"1": "N1", "2": "GND"}, valor=100)]))


class ComOESP32(unittest.TestCase):
    """o ESP32 vira pilhas de mentira (com_pinos): ~terra, ~3V3 e um ~GPIOn por pino; o resolver não muda"""

    def led_no_gpio32(self, estado, led=LED, vdd=None):
        mais, menos = led.get("mais", "1"), led.get("menos", "2")
        return com_esp32([mcu({"GND": "GND", "3V3": "N3V3", "GPIO32": "N1"}),
                          peca("R1", RESISTOR, {"1": "N1", "2": "N2"}, valor=220),
                          peca("D1", led, {mais: "N2", menos: "GND"})], {"GPIO32": estado}, vdd=vdd)

    def test_gpio_em_1_acende_o_led_com_a_conta_do_gemeo(self):
        # (3,3 − 1,7) ÷ (30 + 220 + 20) = 5,93 mA: a conta do mapa e do gêmeo, com o led_5mm da biblioteca
        s = self.led_no_gpio32(1)
        self.assertAlmostEqual(s["pecas"]["D1"]["i"] * 1000, 5.93, delta=0.01)
        self.assertAlmostEqual(s["pecas"]["D1"]["i"], (3.3 - 1.7) / (30 + 220 + 20), delta=1e-6)
        self.assertAlmostEqual(s["pecas"]["~GPIO32"]["i"], s["pecas"]["D1"]["i"], delta=1e-7, msg="o pino dá a corrente do LED")
        self.assertTrue(s["pecas"]["D1"]["acende"])

    def test_led_C779439_no_gpio_em_1(self):
        # o aceite da T2 no plano dizia 5,93 mA com o C779439, mas 5,93 é a conta do led_5mm (o teste de cima);
        # o C779439 do catálogo tem o joelho mais alto e dá (3,3 − 1,90) ÷ 253,5 = 5,52 mA
        import catalogo
        led = catalogo.conferido("C779439")["eletrica"]   # vf 1,97, r_s 3,5, i_teste 20 mA: joelho 1,90 V
        s = self.led_no_gpio32(1, led)
        esperado = (3.3 - circuito.joelho(led)) / (30 + 220 + led["r_s"])
        self.assertAlmostEqual(s["pecas"]["D1"]["i"], esperado, delta=1e-6)
        self.assertAlmostEqual(s["pecas"]["D1"]["i"] * 1000, 5.52, delta=0.01)

    def test_true_e_false_valem_1_e_0(self):
        self.assertEqual(self.led_no_gpio32(True), self.led_no_gpio32(1))
        self.assertEqual(self.led_no_gpio32(False), self.led_no_gpio32(0))

    def test_gpio_em_0_ou_solto_nao_acende(self):
        for estado in (0, None, False):
            s = self.led_no_gpio32(estado)
            self.assertEqual(s["pecas"]["D1"]["i"], 0.0, estado)
            self.assertFalse(s["pecas"]["D1"]["acende"])
        self.assertNotIn("~GPIO32", self.led_no_gpio32(None)["pecas"], "solto não vira pilha")

    def test_vdd_do_3v3_muda_o_pino(self):
        s = self.led_no_gpio32(1, vdd=3.399)   # o vdd_max do AMS1117
        self.assertAlmostEqual(s["pecas"]["D1"]["i"], (3.399 - 1.7) / (30 + 220 + 20), delta=1e-6)

    def test_pullup_contra_a_chave_apertada(self):
        pecas = [mcu({"GND": "GND", "GPIO14": "N1"}), peca("SW1", CHAVE, {"1": "N1", "2": "N1", "3": "GND", "4": "GND"})]
        s = com_esp32(pecas, {"GPIO14": "pullup"}, {"chave": {"SW1": True}})
        self.assertAlmostEqual(s["pecas"]["~GPIO14"]["i"], 3.3 / 45000, delta=1e-9)
        self.assertAlmostEqual(s["pecas"]["SW1"]["i"], 3.3 / 45000, delta=1e-9)
        solta = com_esp32(pecas, {"GPIO14": "pullup"}, {"chave": {"SW1": False}})
        self.assertAlmostEqual(solta["nets"]["N1"], 3.3, delta=1e-3, msg="solta, o pull-up segura o pino em 3,3 V")

    def test_botao_com_1k_o_pino_ainda_le_zero(self):
        # a decisão 'Botões': GPIO → 1 kΩ → botão → GND; apertado, o pino lê 3,3 × 1000 ÷ 46000 = 0,07 V
        pecas = [mcu({"GND": "GND", "GPIO14": "N1"}), peca("R1", RESISTOR, {"1": "N1", "2": "N2"}, valor=1000),
                 peca("SW1", CHAVE, {"1": "N2", "2": "N2", "3": "GND", "4": "GND"})]
        s = com_esp32(pecas, {"GPIO14": "pullup"}, {"chave": {"SW1": True}})
        self.assertAlmostEqual(s["nets"]["N1"], 3.3 * 1000 / 46000, delta=1e-4)
        curto = com_esp32(pecas, {"GPIO14": 1}, {"chave": {"SW1": True}})   # o pino virou saída em 1 por engano
        self.assertAlmostEqual(curto["pecas"]["~GPIO14"]["i"], 3.3 / 1030, delta=1e-6, msg="no máximo 3,2 mA, não é curto")

    def test_3v3_tem_a_resistencia_da_eletrica(self):
        pecas = [mcu({"GND": "GND", "3V3": "N1"}), peca("R1", RESISTOR, {"1": "N1", "2": "N2"}, valor=220),
                 peca("D1", LED, {"1": "N2", "2": "GND"})]
        s = com_esp32(pecas, {})
        self.assertAlmostEqual(s["pecas"]["D1"]["i"], (3.3 - 1.7) / (0.05 + 220 + 20), delta=1e-6)
        for vazio in (None, "pendente", 0, -1, True):   # pendente recusa: nada de trocar calado pela R_PILHA
            with self.assertRaises(ValueError, msg=vazio):
                com_esp32([mcu({"GND": "GND", "3V3": "N1"}, {**MCU, "r_3v3": vazio})] + pecas[1:], {})
        sem = {k: v for k, v in MCU.items() if k != "r_3v3"}
        with self.assertRaises(ValueError):
            com_esp32([mcu({"GND": "GND", "3V3": "N1"}, sem)] + pecas[1:], {})
        solto = com_esp32([mcu({"GND": "GND", "3V3": None, "GPIO32": "N1"}, sem)] + pecas[1:], {"GPIO32": 1})
        self.assertGreater(solto["pecas"]["D1"]["i"], 0, "com o 3V3 solto, o r_3v3 não faz falta")

    def test_terra_e_o_gnd_do_chip_e_o_vin_nao_entra(self):
        m = circuito.com_pinos({"pecas": [mcu({"GND": "G0", "3V3": "N1", "VIN": "N5", "EN": "N6", "GPIO32": "N2"})]},
                               {"GPIO32": 1})
        self.assertEqual([p["ref"] for p in m["pecas"][:3]], ["~terra", "~3V3", "~GPIO32"])
        self.assertEqual(m["pecas"][0]["pinos"][1]["net"], "G0")
        self.assertFalse(any(p["ref"] in ("~VIN", "~EN") for p in m["pecas"]))
        m["pecas"].append(peca("D1", LED, {"1": "N5", "2": "G0"}))   # LED no VIN: sem fonte nenhuma
        self.assertEqual(circuito.resolver(m)["pecas"]["D1"]["i"], 0.0)

    def test_estado_que_nao_existe_avisa(self):
        with self.assertRaises(ValueError):
            circuito.com_pinos({"pecas": [mcu({"GND": "GND", "GPIO32": "N1"})]}, {"GPIO32": "alto"})

    def test_so_gpio_entra_no_estado(self):
        # o 3V3 e o GND já entram sozinhos, e o VIN não é modelado: no estado, viraria uma fonte que não existe
        m = {"pecas": [mcu({"GND": "GND", "3V3": "N3", "VIN": "N5", "GPIO32": "N1"})]}
        for nome in ("VIN", "3V3", "GND", "EN", "gpio32", "GPIO", "IO32"):
            with self.assertRaises(ValueError, msg=nome):
                circuito.com_pinos(m, {nome: 1})
        self.assertEqual(len(circuito.com_pinos(m, {"GPIO32": 1, "GPIO99": 1})["pecas"]), 4, "GPIO fora da placa: solto")

    def test_numero_pendente_recusa_em_vez_de_inventar(self):
        pecas = [peca("R1", RESISTOR, {"1": "N1", "2": "N2"}, valor=220), peca("D1", LED, {"1": "N2", "2": "GND"})]
        for falta, nivel in (("r_pino", 1), ("r_pino", 0), ("r_pull", "pullup"), ("vdd", 1), ("vdd", None),
                             ("r_3v3", None)):
            for vazio in (None, "pendente", 0, -1, True):
                e = {**MCU, falta: vazio}
                with self.assertRaises(ValueError, msg=(falta, vazio)):
                    com_esp32([mcu({"GND": "GND", "3V3": "N3", "GPIO32": "N1"}, e)] + pecas, {"GPIO32": nivel})
        sem_pull = {k: v for k, v in MCU.items() if k != "r_pull"}
        s = com_esp32([mcu({"GND": "GND", "GPIO32": "N1"}, sem_pull)] + pecas, {"GPIO32": 1})
        self.assertGreater(s["pecas"]["D1"]["i"], 0, "o r_pull só faz falta no pullup")
        for vdd in (0, -3.3, "3.3"):
            with self.assertRaises(ValueError, msg=vdd):
                com_esp32([mcu({"GND": "GND", "GPIO32": "N1"})] + pecas, {"GPIO32": 1}, vdd=vdd)

    def test_frase_de_pendente_e_de_gente(self):
        # a etapa 4 e o painel mostram a frase pro Luiz: a ref da peça e o nome de gente, sem o nome do campo
        pecas = [mcu({"GND": "GND", "3V3": "N3", "GPIO32": "N1"}, {**MCU, "r_pino": "pendente"}),
                 peca("R1", RESISTOR, {"1": "N1", "2": "GND"}, valor=220)]
        with self.assertRaises(ValueError) as erro:
            com_esp32(pecas, {"GPIO32": 1})
        self.assertEqual(str(erro.exception), "U1: falta conferir a resistência do pino no datasheet")
        pecas = [mcu({"GND": "GND", "3V3": "N3"}), peca("LDR2", {**LDR, "gama": None}, {"1": "N3", "2": "GND"})]
        with self.assertRaises(ValueError) as erro:
            com_esp32(pecas, {})
        self.assertEqual(str(erro.exception), "LDR2: falta conferir quanto a resistência cai com a luz (gama) no datasheet")
        with self.assertRaises(ValueError) as erro:
            circuito.com_pinos({"pecas": [mcu({"GND": "GND", "GPIO32": "N1"})]}, {"GPIO32": "1"})
        self.assertIn("o estado '1' não existe", str(erro.exception))
        for campo in circuito.NOME_DO_CAMPO:
            with self.assertRaises(ValueError) as erro:
                circuito._da_eletrica({}, campo, "X1")
            self.assertNotRegex(str(erro.exception), r"vdd|r_|r10_", "o nome do campo (r_pino, r10_min...) não aparece")

    def test_mcu_e_modelo_desconhecido_sao_ignorados(self):
        base = [peca("BT1", PILHA, {"1": "N1", "2": "GND"}), peca("R1", RESISTOR, {"1": "N1", "2": "N2"}, valor=100),
                peca("D1", LED, {"1": "N2", "2": "GND"})]
        estranhos = [mcu({"GND": "GND", "3V3": "N1", "GPIO32": "N2"}), peca("X1", {"modelo": "foguete"}, {"1": "N1", "2": "GND"})]
        self.assertEqual(resolver(base + estranhos)["pecas"]["D1"], resolver(base)["pecas"]["D1"])
        self.assertIsNone(resolver(estranhos), "sem pilha (nem com_pinos), não tem o que ligar")
        sem_mcu = {"pecas": base[1:]}
        self.assertIs(circuito.com_pinos(sem_mcu, {"GPIO32": 1}), sem_mcu, "sem mcu, o modelo volta como está")


class LdrPiezoECapacitor(unittest.TestCase):
    def test_ldr_do_meio_em_10_lux(self):
        self.assertEqual(round(circuito.ohms_do_ldr(LDR, 10)), 12649)   # √(8000 × 20000)
        self.assertEqual(circuito.ohms_do_ldr(LDR, 10, "min"), 8000)
        self.assertEqual(circuito.ohms_do_ldr(LDR, 10, "max"), 20000)

    def test_ldr_no_escuro(self):
        for lux in (0, None):
            for canto in ("min", "meio", "max"):
                self.assertEqual(circuito.ohms_do_ldr(LDR, lux, canto), 1e6)
        self.assertEqual(circuito.ohms_do_ldr(LDR, 0.001, "max"), 1e6, "nunca passa do r_escuro")

    def test_cantos_vao_pro_lado_do_menor_e_do_maior(self):
        # acima de 10 lux o gama maior baixa a resistência; abaixo de 10 lux, sobe
        self.assertAlmostEqual(circuito.ohms_do_ldr(LDR, 100, "min"), 8000 * 10 ** -0.75, delta=1e-6)
        self.assertAlmostEqual(circuito.ohms_do_ldr(LDR, 100, "max"), 20000 * 10 ** -0.55, delta=1e-6)
        self.assertAlmostEqual(circuito.ohms_do_ldr(LDR, 1, "min"), 8000 * 10 ** 0.55, delta=1e-6)
        self.assertAlmostEqual(circuito.ohms_do_ldr(LDR, 1, "max"), 20000 * 10 ** 0.75, delta=1e-6)
        for lux in (0.5, 1, 2, 5, 10, 23, 50, 100, 200):
            r = [circuito.ohms_do_ldr(LDR, lux, c) for c in ("min", "meio", "max")]
            self.assertLessEqual(r[0], r[1], lux)
            self.assertLessEqual(r[1], r[2], lux)
        with self.assertRaises(ValueError):
            circuito.ohms_do_ldr(LDR, 10, "tipico")

    def test_canto_e_lux_que_nao_existem_recusam_ate_no_escuro(self):
        for lux in (None, 0, 10):
            with self.assertRaises(ValueError, msg=lux):
                circuito.ohms_do_ldr(LDR, lux, "tipico")
        for lux in ("10", "0", True, False, -1, -0.5, float("nan"), [10]):   # o valor cru de um <input> é texto
            with self.assertRaises(ValueError, msg=lux):
                circuito.ohms_do_ldr(LDR, lux)
            with self.assertRaises(ValueError, msg=lux):
                circuito.divisor_do_ldr(LDR, 22000, 3.3, lux)
        self.assertEqual(circuito.ohms_do_ldr(LDR, 10.0), circuito.ohms_do_ldr(LDR, 10))

    def test_divisor_da_luz_noturna(self):
        # 3V3 → 22 kΩ → GPIO34 → LDR → GND: 2,37 V em 1 lux, 1,20 V em 10, 0,83 V em 23 e 0,38 V em 100 (LDR do meio)
        for lux, volts in ((1, 2.37), (10, 1.20), (23, 0.83), (100, 0.38)):
            self.assertAlmostEqual(circuito.divisor_do_ldr(LDR, 22000, 3.3, lux, "meio"), volts, delta=0.01, msg=lux)
        self.assertAlmostEqual(circuito.divisor_do_ldr(LDR, 22000, 3.3, 0), 3.3 * 1e6 / 1.022e6, delta=1e-9)

    def test_ldr_pendente_ou_ajuste_sem_sentido_recusa(self):
        for falta in ("r10_min", "r10_max", "gama", "r_escuro"):
            with self.assertRaises(ValueError, msg=falta):
                circuito.ohms_do_ldr({**LDR, falta: None}, 10)
        self.assertAlmostEqual(circuito.ohms_do_ldr({**LDR, "gama_tol": None}, 100, "min"), 8000 * 10 ** -0.65, delta=1e-6,
                               msg="sem gama_tol, o canto usa só o gama")
        pecas = [mcu({"GND": "GND", "3V3": "N1"}), peca("LDR1", LDR, {"1": "N1", "2": "GND"})]
        for ohms in (0, -100, "1k"):
            with self.assertRaises(ValueError, msg=ohms):
                com_esp32(pecas, {}, {"ldr": {"LDR1": ohms}})

    def test_ldr_do_catalogo(self):
        import catalogo
        e = (catalogo.conferido("C10081") or {}).get("eletrica")
        if not e:
            self.skipTest("o C10081 ainda não está conferido no catálogo")
        self.assertAlmostEqual(circuito.divisor_do_ldr(e, 22000, 3.3, 10, "meio"), 1.20, delta=0.01)
        for lux in (None, 1, 10, 100):
            for canto in ("min", "meio", "max"):
                self.assertEqual(circuito.ohms_do_ldr(e, lux, canto), circuito.ohms_do_ldr(LDR, lux, canto), (lux, canto))

    def test_divisor_e_o_circuito_dao_o_mesmo(self):
        pecas = [mcu({"GND": "GND", "3V3": "N1", "GPIO34": "N2"}), peca("R1", RESISTOR, {"1": "N1", "2": "N2"}, valor=22000),
                 peca("LDR1", LDR, {"1": "N2", "2": "GND"})]
        for lux in (None, 1, 10, 100):
            s = com_esp32(pecas, {}, {"ldr": {"LDR1": circuito.ohms_do_ldr(LDR, lux)}})
            self.assertAlmostEqual(s["nets"]["N2"], circuito.divisor_do_ldr(LDR, 22000, 3.3, lux), delta=1e-4, msg=lux)
        sem_ajuste = com_esp32(pecas, {})
        self.assertEqual(sem_ajuste["pecas"]["LDR1"]["ohms"], circuito.ohms_do_ldr(LDR, circuito.LUX_PADRAO))

    def test_piezo_aberto_e_na_borda_vira_fio(self):
        pecas = [mcu({"GND": "GND", "GPIO25": "N1"}), peca("R1", RESISTOR, {"1": "N1", "2": "N2"}, valor=1000),
                 peca("BZ1", PIEZO, {"1": "N2", "2": "GND"})]
        self.assertEqual(com_esp32(pecas, {"GPIO25": 1})["pecas"]["BZ1"]["i"], 0.0)
        s = com_esp32(pecas, {"GPIO25": 1}, {"piezo": {"BZ1": True}})
        self.assertAlmostEqual(s["pecas"]["BZ1"]["i"] * 1000, 3.2, delta=0.01)   # 3,3 ÷ (1000 + 30)
        self.assertTrue(s["pecas"]["BZ1"]["fio"])

    def test_capacitor_nao_passa_corrente(self):
        pecas = [mcu({"GND": "GND", "3V3": "N1"}), peca("R1", RESISTOR, {"1": "N1", "2": "N2"}, valor=22000),
                 peca("C1", CAPACITOR, {"1": "N2", "2": "GND"})]
        s = com_esp32(pecas, {})
        self.assertEqual(s["pecas"]["C1"]["i"], 0.0)
        self.assertAlmostEqual(s["pecas"]["R1"]["i"], 0.0, delta=1e-8)   # só o vazamento do GMIN
        self.assertAlmostEqual(s["nets"]["N2"], 3.3, delta=1e-3)


class LeisComCircuitoSorteado(unittest.TestCase):
    """200 circuitos sorteados: a corrente que entra numa net sai dela, e a pilha entrega o que as peças gastam"""

    def sortear(self, rnd):
        nets = ["GND"] + [f"N{i}" for i in range(1, rnd.randint(2, 6))]
        pecas = [peca("BT1", {**PILHA, "r_interna": rnd.choice([0, 5, 12])}, {"1": nets[1], "2": "GND"})]
        for i in range(rnd.randint(2, 9)):
            a, b = rnd.sample(nets, 2)
            if rnd.random() < 0.3:
                pecas.append(peca(f"D{i}", LED, {"1": a, "2": b}))
            else:
                pecas.append(peca(f"R{i}", RESISTOR, {"1": a, "2": b}, valor=rnd.choice([47, 100, 220, 1000, 4700])))
        return pecas, rnd.uniform(2.0, 3.3)

    def test_kirchhoff_e_energia(self):
        rnd = random.Random(2026)
        for _ in range(200):
            pecas, v = self.sortear(rnd)
            s = resolver(pecas, {"pilha": {"BT1": v}})
            soma = {}
            for p in pecas:
                for pino in p["pinos"]:
                    soma[pino["net"]] = soma.get(pino["net"], 0) + s["entra"].get(f"{p['ref']}.{pino['n']}", 0)
            for net, i in soma.items():
                self.assertAlmostEqual(i, 0, delta=1e-5, msg=f"net {net} não fecha: {i}")
            entregue = s["pecas"]["BT1"]["i"] * s["pecas"]["BT1"]["v"]
            gasto = sum(r.get("p", 0) for r in s["pecas"].values())
            gasto += sum(r["i"] * r["v"] for ref, r in s["pecas"].items() if ref.startswith("D"))
            gasto += s["pecas"]["BT1"]["i"] ** 2 * circuito.r_pilha(pecas[0]["eletrica"])
            self.assertAlmostEqual(entregue, gasto, delta=1e-4 + 1e-3 * abs(entregue))
            for ref, r in s["pecas"].items():
                if ref.startswith("D"):
                    self.assertGreaterEqual(r["i"], 0, "LED não conduz ao contrário")

    def test_kirchhoff_e_energia_com_o_esp32(self):
        """200 circuitos com o ESP32, LDR, piezo e capacitor: as pilhas de mentira entregam o que as peças gastam"""
        rnd = random.Random(2027)
        for _ in range(200):
            m, estado, vdd, aj = sortear_com_esp32(rnd)
            completo = circuito.com_pinos(m, estado, vdd)
            s = circuito.resolver(completo, aj)
            soma = {}
            for p in completo["pecas"]:
                lados = p["eletrica"].get("lados") if p["eletrica"]["modelo"] == "chave" else None
                for pino in p["pinos"]:
                    if lados and pino["n"] not in (lados[0][0], lados[1][0]):
                        continue   # a chave repete a corrente nos dois pinos de cada lado: conta um por lado
                    soma[pino["net"]] = soma.get(pino["net"], 0) + s["entra"].get(f"{p['ref']}.{pino['n']}", 0)
            for net, i in soma.items():
                if net is not None:
                    self.assertAlmostEqual(i, 0, delta=1e-5, msg=f"net {net} não fecha: {i}")
            entregue = gasto = 0.0
            for p in completo["pecas"]:
                r, e = s["pecas"].get(p["ref"]), p["eletrica"]
                if e["modelo"] == "pilha":
                    entregue += r["i"] * r["v"]
                    gasto += r["i"] ** 2 * circuito.r_pilha(e)
                elif e["modelo"] in ("resistor", "ldr"):
                    gasto += r["p"]
                elif e["modelo"] == "led":
                    gasto += r["i"] * r["v"]
                elif e["modelo"] in ("chave", "piezo"):
                    gasto += r["i"] ** 2 * circuito.R_CHAVE
                elif e["modelo"] == "capacitor":
                    self.assertEqual(r["i"], 0.0)
            self.assertAlmostEqual(entregue, gasto, delta=1e-4 + 1e-3 * abs(entregue))


if __name__ == "__main__":
    unittest.main()
