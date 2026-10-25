# biblioteca: cada tipo de peca e onde ficam os pinos, em mm, a partir do centro da peca
#
# pinos: {numero: (dx, dy, pad)} ou (dx, dy, pad, net) quando o pino ja nasce numa net (ex: GND)
#        pad = diametro (redondo) ou (largura, altura) (retangulo)
# furo:  diametro do furo passante de cada pino; None = peca de superficie (SMD)
# corpo: (largura, altura) do contorno da peca, pra desenhar; redondo: True se o corpo for redondo
# juntos: pares de pinos ligados por dentro da peca (ex: os dois pinos de cada lado do botao)
# nomes:  como a bancada chama cada pino pra gente ("+", "−", "A", "B", "lado 1"); sem isso mostra o numero
# eletrica: o que o simulador precisa saber (circuito.py e o painel da bancada); sem isso a peca nao liga no papel
# compra: o que comprar; extras: coisas que a peca pede e nao vem com ela (a pilha do suporte)
# fonte: datasheet de onde vieram os numeros
#        None = valores de EXEMPLO, nao mandar pra fabrica (trocar no marco 7)

def fileira(primeiro, quantos, x0, passo, y, pad):
    """pinos em linha reta, numerados a partir de `primeiro`"""
    return {str(primeiro + i): (round(x0 + i * passo, 3), y, pad) for i in range(quantos)}


BIBLIOTECA = {
    "resistor": {
        "nome": "Resistor",
        "nomes": {"1": "lado 1", "2": "lado 2"},
        "explica": "Fica no caminho da corrente e limita quanto passa. Sem ele, um LED ligado direto no pino queima.",
        "fonte": None,
        "furo": None,
        "corpo": (3.2, 1.8),
        "pinos": {"1": (-1.0, 0, (1.2, 1.4)), "2": (1.0, 0, (1.2, 1.4))},
    },
    "led": {
        "nome": "LED",
        "nomes": {"1": "+", "2": "−"},
        "explica": "Acende quando a corrente passa por ele. Tem lado certo: entra pelo + (a perna comprida) e sai pelo −.",
        "fonte": None,
        "furo": None,
        "corpo": (3.2, 1.8),
        "pinos": {"1": (-1.0, 0, (1.2, 1.4)), "2": (1.0, 0, (1.2, 1.4))},
    },
    "botao": {
        "nome": "Botão",
        "nomes": {"1": "A", "2": "A", "3": "B", "4": "B"},
        "explica": "Quando você aperta, ele junta os dois lados do circuito. Tem o lado A (dois pinos) e o lado B (os outros dois).",
        "fonte": None,
        "furo": 1.0,
        "corpo": (6.0, 6.0),
        "pinos": {"1": (-3.25, 2.25, 1.8), "2": (3.25, 2.25, 1.8),
                  "3": (-3.25, -2.25, 1.8), "4": (3.25, -2.25, 1.8)},
        "juntos": [("1", "2"), ("3", "4")],
    },
    "buzzer": {
        "nome": "Buzzer",
        "nomes": {"1": "+", "2": "−"},
        "explica": "Faz som quando recebe sinal. Tem lado certo: o + e o −.",
        "fonte": None,
        "furo": 0.9,
        "corpo": (12.0, 12.0),
        "redondo": True,
        "pinos": {"1": (-3.8, 0, 1.7), "2": (3.8, 0, 1.7)},
    },
    "esp32_devkit": {
        "nome": "Módulo ESP32 DevKit",
        "explica": "A plaquinha pronta com o ESP32. Ela encaixa nesses furos e é o cérebro do circuito.",
        "fonte": None,
        "furo": 1.0,
        "corpo": (51.0, 28.0),
        # 2 fileiras de 15, passo 2,54 mm; 1-15 embaixo (esq -> dir), 16-30 em cima (dir -> esq)
        "pinos": {
            **fileira(1, 15, -17.78, 2.54, -12.7, 1.7),
            **fileira(16, 15, 17.78, -2.54, 12.7, 1.7),
        },
    },
}

# pecas reais: pinos, pads e furos do footprint oficial do KiCad (kicad-footprints, master de 2026-10-23),
# conferidos contra o datasheet do fabricante por uma segunda pesquisa independente
KICAD = "https://gitlab.com/kicad/libraries/kicad-footprints/-/raw/master/"
BIBLIOTECA.update({
    "resistor_axial": {
        "nome": "Resistor 1/4 W (axial)",
        "explica": "Freia a corrente: quanto mais ohms, menos corrente passa. É o cilindrinho com faixas coloridas que dizem o valor. "
                   "Fica deitado, com as perninhas dobradas nos furos. Não tem lado certo.",
        "fonte": "Yageo CFR-25 https://cdn.sparkfun.com/assets/a/9/3/0/e/yageo-cfr_datasheet.pdf; "
                 + KICAD + "Resistor_THT.pretty/R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal.kicad_mod",
        "furo": 0.8,
        "corpo": (6.3, 2.5),
        "pinos": {"1": (-5.08, 0, 1.6), "2": (5.08, 0, 1.6)},
        "nomes": {"1": "lado 1", "2": "lado 2"},
        "eletrica": {"modelo": "resistor", "potencia_max": 0.25},   # Yageo CFR-25: 1/4 W a 70 °C
        "compra": "Yageo CFR-25 (ou qualquer resistor de 1/4 W com o valor certo)",
    },
    "led_5mm": {
        "nome": "LED vermelho 5 mm",
        "explica": "Uma luzinha que só acende com a corrente no sentido certo: entra pelo + (a perna comprida) "
                   "e sai pelo − (a perna curta, do lado chato; na placa é o pad quadrado). Sempre com um resistor na frente.",
        "fonte": "Kingbright WP7113ID https://www.kingbrightusa.com/images/catalog/SPEC/WP7113ID.pdf; "
                 + KICAD + "LED_THT.pretty/LED_D5.0mm.kicad_mod (nosso 1 = pad 2 do KiCad, nosso 2 = pad 1)",
        "furo": 0.9,
        "corpo": (5.8, 5.8),
        "redondo": True,
        "pinos": {"1": (1.27, 0, 1.8), "2": (-1.27, 0, (1.8, 1.8))},
        "nomes": {"1": "+", "2": "−"},
        # Kingbright WP7113ID: VF 1,9 V típica (2,3 máx) medida a 10 mA; IF máxima contínua 30 mA.
        # r_s = inclinação estimada entre esses dois pontos: (2,3 − 1,9) / (0,030 − 0,010) = 20 Ω
        "eletrica": {"modelo": "led", "vf": 1.9, "vf_max": 2.3, "i_teste": 0.010, "i_max": 0.030, "r_s": 20},
        "compra": "Kingbright WP7113ID (ou qualquer LED vermelho de 5 mm)",
    },
    "botao_6x6": {
        "nome": "Botão 6×6 mm",
        "explica": "Apertou, liga; soltou, desliga. Tem o lado A (dois pinos, ligados por dentro) e o lado B (os outros dois). "
                   "Só faz alguma coisa se cada lado for pra um lugar diferente.",
        "fonte": "Omron B3F-1000 https://omronfs.omron.com/en_US/ecb/products/pdf/en-b3f.pdf; "
                 + KICAD + "Button_Switch_THT.pretty/SW_PUSH_6mm.kicad_mod",
        "furo": 1.1,
        "corpo": (6.0, 6.0),
        "pinos": {"1": (-3.25, 2.25, 2.0), "2": (3.25, 2.25, 2.0),
                  "3": (-3.25, -2.25, 2.0), "4": (3.25, -2.25, 2.0)},
        "juntos": [("1", "2"), ("3", "4")],
        "nomes": {"1": "A", "2": "A", "3": "B", "4": "B"},
        "eletrica": {"modelo": "chave", "lados": [["1", "2"], ["3", "4"]], "i_max": 0.050},   # Omron B3F: 1 a 50 mA
        "compra": "Omron B3F-1000 (ou botão tátil 6×6 mm de 4 pinos)",
    },
    "pilha_cr2032": {
        "nome": "Suporte de pilha CR2032",
        "explica": "Segura uma pilha moeda CR2032 de 3 V. O + fica na aba (pad quadrado); "
                   "o −, embaixo da pilha, é o GND da placa, o 0 V de referência.",
        "fonte": "Keystone 103 https://www.keyelco.com/userAssets/file/M65p3.pdf; "
                 + KICAD + "Battery.pretty/BatteryHolder_Keystone_103_1x20mm.kicad_mod",
        "furo": 1.5,
        "corpo": (28.7, 22.8),
        "pinos": {"1": (-12.25, 0, (3.0, 3.0), "VBAT"), "2": (8.24, 0, 3.0, "GND")},
        "nomes": {"1": "+", "2": "−"},
        # Energizer CR2032 (https://data.energizer.com/pdfs/cr2032.pdf): 3,0 V nominal, 235 mAh até 2,0 V.
        # v_max 3,3 = pilha nova, so o limite do painel: o datasheet da a nominal e o corte, nao o valor nova
        "eletrica": {"modelo": "pilha", "mais": "1", "menos": "2", "v": 3.0, "v_min": 2.0, "v_max": 3.3, "mah": 235},
        "compra": "Keystone 103",
        "extras": ["Pilha CR2032 de 3 V"],
    },
})

# pinos que ja nascem numa net (EXEMPLO: confirmar no datasheet do DevKit escolhido)
for n, net in {"14": "GND", "17": "GND"}.items():
    dx, dy, pad = BIBLIOTECA["esp32_devkit"]["pinos"][n]
    BIBLIOTECA["esp32_devkit"]["pinos"][n] = (dx, dy, pad, net)


# ---------- o DevKit de 30 pinos de verdade (pesquisa de 2026-10-25) ----------
# DOIT ESP32 DevKit V1 (o da RoboCore), encaixado em 2 barras fêmea 1x15 soldadas na placa.
# Vista de cima (componentes do DevKit pra cima), antena à esquerda (x negativo), USB à direita, y pra cima;
# origem = centro da placa do DevKit. 1-15 embaixo (EN no 1, VIN no 15), 16-30 em cima (3V3 no 16, D23 no 30).
# As fileiras não ficam no meio do comprimento: da borda da antena ao 1º pino são 6,03 mm e do último pino à
# borda do USB, 10,21 mm; por isso os pinos andam (6,03 − 10,21) / 2 = −2,09 mm em x.
# Fileiras a ±12,70 (25,40 mm entre elas), passo 2,54. Furo 1,0 (EasyEDA da barra hanxia C41417327; o datasheet
# dela pede 1,02) e pad 1,7 (EasyEDA da Hong Cheng C22373901). O EN é quadrado: marca o lado da antena.
# O "esp32_devkit" lá de cima não muda: o laboratório usa ele.
# Nas fontes da elétrica, "linha" é a linha do texto do PDF (pdftotext -layout), como no laboratório.
DS_ESP32 = "Espressif ESP32 Series Datasheet v5.3 https://documentation.espressif.com/esp32_datasheet_en.pdf"
WROOM = "Espressif ESP32-WROOM-32 Datasheet v3.8 https://documentation.espressif.com/esp32-wroom-32_datasheet_en.pdf"
AMS1117 = "Advanced Monolithic Systems AMS1117 http://www.advanced-monolithic.com/pdf/ds1117.pdf"
MPQ = "MicroPython quickref ESP32 https://docs.micropython.org/en/latest/esp32/quickref.html"
FOTO = "o regulador é o AMS1117 3.3 (lido na foto do DevKit da RoboCore https://www.robocore.net/wifi/esp32-wifi-bluetooth)"
MISCHIANTI = ("desenho 1:1 do DOIT ESP32 DevKit V1 (Fritzing, Renzo Mischianti) "
              "https://mischianti.org/wp-content/uploads/2021/10/DOIT-ESP32-DevKit-v1.svg")
GEMEO = "laboratorio/motores/gemeo/chips/"
FAIXA_3V3 = (AMS1117 + ": AMS1117-3.3, Output Voltage com VIN = 4,8 V, 3,201 a 3,399 V (p. 2, linha 87), na linha em "
             "negrito, que vale em toda a faixa de temperatura (p. 3, linha 169); sem carga (IOUT = 0, p. 2, linha 70): "
             "as regulações de carga (até 25 mV, p. 3, linha 127) e de linha (até 10 mV, p. 2, linha 101) não estão somadas")
FAIXA_ADC = (DS_ESP32 + ", Tabela 4-4 (p. 44, linha 2446): com 11 dB (atten = 3), faixa efetiva de 150 a 2450 mV e "
             "erro de ±60 mV depois da calibração; sem calibrar, ±6% de chip pra chip (p. 44, linha 2434)")

BIBLIOTECA["devkit_esp32_30"] = {
    "nome": "ESP32 DevKit V1 (30 pinos)",
    "explica": "A plaquinha pronta com o ESP32 (o cérebro). Ela não é soldada: encaixa em duas barras fêmea de 15 furos "
               "que você solda na nossa placa. A antena fica de um lado e o USB do outro; o USB dá a energia e o programa. "
               "O furo quadrado é o EN, do lado da antena.",
    "fonte": "esquema do DOIT ESP32 DevKit V1 "
             "https://embedded-systems-design.github.io/overview-of-the-esp32-devkit-doit-v1/SchematicsforESP32.pdf; "
             + MISCHIANTI + "; medidas com a placa na mão (noiasca, vanepp) https://forum.fritzing.org/t/doit-esp32-devkit-v1/6158; "
             "footprint da comunidade (só a distância entre fileiras) https://github.com/syauqibilfaqih/ESP32-DevKit-V1-DOIT; "
             "barra hanxia HX PM2.54-1x15P ZC (LCSC C41417327) "
             "https://datasheet.lcsc.com/datasheet/pdf/9091321e760df662e48ff489ff8e1b24.pdf?productCode=C41417327; "
             "desenho do EasyEDA das barras C41417327 e C22373901 (loja.desenho, 2026-10-25); "
             "fotos da RoboCore https://www.robocore.net/wifi/esp32-wifi-bluetooth e da Usinainfo, medidas por pixel",
    "furo": 1.0,
    "corpo": (51.8, 28.2),
    "pinos": {
        **fileira(1, 15, -19.87, 2.54, -12.7, 1.7),
        **fileira(16, 15, 15.69, -2.54, 12.7, 1.7),
        "1": (-19.87, -12.7, (1.7, 1.7)),   # EN quadrado
        "14": (13.15, -12.7, 1.7, "GND"),   # os dois GND são ligados por dentro do DevKit (esquema do DOIT)
        "17": (13.15, 12.7, 1.7, "GND"),
    },
    "juntos": [("14", "17")],
    # nomes de máquina: o gêmeo e a etapa 4 acham os GPIOs por eles; o que está escrito no DevKit fica na serigrafia
    "nomes": {"1": "EN", "2": "GPIO36", "3": "GPIO39", "4": "GPIO34", "5": "GPIO35", "6": "GPIO32", "7": "GPIO33",
              "8": "GPIO25", "9": "GPIO26", "10": "GPIO27", "11": "GPIO14", "12": "GPIO12", "13": "GPIO13", "14": "GND",
              "15": "VIN", "16": "3V3", "17": "GND", "18": "GPIO15", "19": "GPIO2", "20": "GPIO4", "21": "GPIO16",
              "22": "GPIO17", "23": "GPIO5", "24": "GPIO18", "25": "GPIO19", "26": "GPIO21", "27": "GPIO3", "28": "GPIO1",
              "29": "GPIO22", "30": "GPIO23"},
    "serigrafia": {"1": "EN", "2": "VP", "3": "VN", "4": "D34", "5": "D35", "6": "D32", "7": "D33", "8": "D25",
                   "9": "D26", "10": "D27", "11": "D14", "12": "D12", "13": "D13", "14": "GND", "15": "VIN", "16": "3V3",
                   "17": "GND", "18": "D15", "19": "D2", "20": "D4", "21": "RX2", "22": "TX2", "23": "D5", "24": "D18",
                   "25": "D19", "26": "D21", "27": "RX0", "28": "TX0", "29": "D22", "30": "D23"},
    # o aviso de cada pino pra gente (as listas com a fonte estão na elétrica)
    "cuidados": {"2": "só entrada", "3": "só entrada", "4": "só entrada", "5": "só entrada",
                 "12": "cuidado no boot", "15": "VIN: não soldar", "18": "cuidado no boot",
                 "19": "LED azul da placa; cuidado no boot", "23": "cuidado no boot",
                 "27": "serial do PC", "28": "serial do PC"},
    # áreas da peça em mm a partir do centro dela, como os pinos: (de, até)
    "zonas": {
        "antena": {"x": (-25.9, -19.09), "y": (-9.0, 9.0),
                   "pede": "nada de cobre largo nem peça alta embaixo ou na frente da antena; o melhor é a ponta dela na borda da placa",
                   "fonte": "da borda do DevKit até o fim da área da antena: o módulo começa 0,87 mm depois da borda (" + MISCHIANTI
                            + "); área da antena 5,94 mm e largura do módulo 18,00 mm (" + WROOM + ", Figura 8); o pedido é "
                            "a recomendação da Espressif pra antena de placa (WROOM, Seção 10.2)"},
        "usb": {"x": (20.6, 27.3), "y": (-4.45, 4.45),
                "pede": "a ponta do USB livre pro cabo entrar: de preferência na borda da placa",
                "fonte": "o conector começa a 46,5 mm da borda da antena (" + MISCHIANTI + "); nas fotos da RoboCore e da "
                         "Usinainfo ele passa de 0,7 a 1,4 mm da borda e tem até 8,9 mm de largura (USB-C)"},
    },
    # o que vem junto no carrinho e não entra no placa.txt (peça em cima de peça nos mesmos furos falharia na etapa 3)
    "acompanha": [{"codigo": "C41417327", "qtd": 2, "alternativa": "C22373901",
                   "nome": "Barra fêmea 1×15, passo 2,54 mm, 8,5 mm de altura (hanxia HX PM2.54-1x15P ZC)"}],
    "confira": [
        "Com o DevKit na mão, meça com a régua do centro do pino EN ao centro do pino D23 (atravessando a placa): "
        "tem que dar 25,4 mm. Se der 22,86 mm, é a versão estreita e não encaixa.",
        "Imprima a placa em tamanho real (1:1, 100%, sem ajustar à página) e espete o DevKit no papel antes de pedir a placa.",
        "Depois de soldar as barras, procure ponte de solda entre pinos vizinhos: lupa do celular e o multímetro na continuidade.",
    ],
    "compra": "RoboCore ESP32 - WiFi + Bluetooth (DOIT ESP32 DevKit V1, 30 pinos) https://www.robocore.net/wifi/esp32-wifi-bluetooth; "
              "não serve o de 38 pinos nem o de fileiras a 22,86 mm",
    # o pino em 1 é uma pilha de vdd com r_pino por dentro (a "pilha de mentira" do gêmeo); o VIN não é modelado
    "eletrica": {
        "modelo": "mcu",
        "vdd": 3.3, "vdd_min": 3.201, "vdd_max": 3.399,
        "condicao_3v3": "vale com VIN ≥ 4,8 V e com o AMS1117 original; a queda do SS14 e a tensão da porta USB estão pendentes",
        "r_pino": 30, "i_pino": 0.020,
        "r_pull": 45000, "vil": 0.25,      # vil é fração do vdd: abaixo de 0,25 × vdd o pino lê 0
        "i_soma_max": 1.1,                 # máximo absoluto: o chip sobrevive, não é pra usar
        "orcamento_3v3": 0.5,              # 1 A do AMS1117 − 0,5 A reservados pro módulo
        "r_3v3": 0.05,
        "adc_min": 0.15, "adc_max": 2.45,  # a faixa boa do ADC com 11 dB
        "so_entrada": [f"GPIO{n}" for n in range(34, 40)],
        "boot": ["GPIO0", "GPIO2", "GPIO5", "GPIO12", "GPIO15"],
        "flash": [f"GPIO{n}" for n in range(6, 12)],
        "serial": ["GPIO1", "GPIO3"],
        "psram": ["GPIO16", "GPIO17"],
        "adc1": [f"GPIO{n}" for n in range(32, 40)],
        # uma ou mais fontes por campo
        "fontes": {
            "vdd": [AMS1117 + ": AMS1117-3.3, saída típica 3,300 V (p. 2, linhas 86-87)",
                    WROOM + ": VDD33 típico 3,3 V (Tabela 13, p. 26)", FOTO],
            "vdd_min": [FAIXA_3V3, FOTO],
            "vdd_max": [FAIXA_3V3, FOTO],
            "r_pino": [MPQ + ": 'Pin.DRIVE_2: 20mA / 30 ohm (default strength if not configured)'; estimativa do MicroPython, "
                       "não é datasheet (o mesmo número do gêmeo, " + GEMEO + "comum.py:15-17)"],
            "i_pino": [DS_ESP32 + ", Apêndice A, nota 8 da Tabela IO_MUX (p. 62, linhas 3419-3426): força padrão do pino "
                       "~20 mA (drive 2, o padrão); é a força padrão, não é limite de dano"],
            "r_pull": [DS_ESP32 + ", Tabela 5-3 (p. 52, linha 2902): pull-up e pull-down de dentro 45 kΩ típicos"],
            "vil": [DS_ESP32 + ", Tabela 5-3 (p. 52, linha 2880): VIL máximo = 0,25 × VDD"],
            "i_soma_max": [WROOM + ", Tabela 12 (p. 26, linha 1326): Cumulative IO output current 1.100 mA; máximo absoluto "
                           "(o chip sobrevive, não é pra usar)"],
            "orcamento_3v3": [AMS1117 + ": 'Output Current of 1A' (p. 1, linha 9)",
                              WROOM + ", Tabela 13 (p. 26, linha 1343): a fonte do módulo tem que entregar pelo menos 0,5 A; "
                              "sobra 1 − 0,5 = 0,5 A pro resto"],
            "r_3v3": ["suposição do gêmeo, pendente: R_3V3 = 0,05 Ω em " + GEMEO + "comum.py:31-32 "
                      "('SUPOSIÇÃO, sem datasheet da placa')"],
            "adc_min": [FAIXA_ADC, MPQ + ": 'ADC.ATTN_11DB: 11dB attenuation (150mV - 2450mV)'"],
            "adc_max": [FAIXA_ADC, MPQ + ": 'ADC.ATTN_11DB: 11dB attenuation (150mV - 2450mV)'"],
            "so_entrada": [DS_ESP32 + ", Tabela 6-1, nota 2 (p. 61, linha 3360): GPIO34 a 39 só entram, sem driver de saída "
                           "e sem pull-up/pull-down de dentro"],
            "boot": [DS_ESP32 + ", Seção 3 e Tabela 3-1 (p. 22, linhas 1100-1140): pinos de boot GPIO0, GPIO2, MTDI (GPIO12), "
                     "MTDO (GPIO15) e GPIO5"],
            "flash": [WROOM + ", nota 2 da tabela de pinos (p. 10, linha 426): GPIO6 a GPIO11 ligados à flash do módulo"],
            "serial": [WROOM + ", tabela de pinos (p. 9, linhas 412-413): TXD0 = GPIO1 e RXD0 = GPIO3",
                       MPQ + ": 'Pins 1 and 3 are REPL UART TX and RX respectively'"],
            "psram": [DS_ESP32 + ", Tabela 2-6 e notas 2 e 3 (p. 21, linhas 1059-1083): GPIO16 = CE# e GPIO17 = SCLK da "
                      "PSRAM de fora (módulos WROVER); o WROOM-32 do DevKit não tem PSRAM, por isso é só aviso"],
            "adc1": [DS_ESP32 + ", Tabela 4-6 (p. 46, linhas 2527-2534) e tabela de pinos (p. 14, linhas 683-693): "
                     "ADC1_CH0 a CH7 = GPIO36, 37, 38, 39, 32, 33, 34 e 35"],
        },
        # o que falta conferir (fica aqui dentro: o 'pendente' da peça seguraria a fábrica)
        "pendentes": [
            "porta USB: quanto a porta USB do computador entrega (falta a especificação do USB 2.0)",
            "queda do SS14: o VIN é o 5 V do USB menos a queda do diodo SS14 (falta o datasheet do SS14); "
            "sem ela não dá pra provar o VIN ≥ 4,8 V que a faixa do 3V3 pede",
            "r_3v3: a resistência do 3V3 (0,05 Ω) é suposição do gêmeo, sem datasheet da placa",
        ],
    },
}
