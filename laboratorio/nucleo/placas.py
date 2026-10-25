"""placas.py: as 5 mini placas do laboratório + o Pico de reserva.

Os apelidos (LED, BOTAO, ...) são o que os exemplos usam; aqui eles viram pino físico. Conferidos nos
datasheets (texto em ~/.cache/sianvolt/lab/placas/ds_*.txt; a linha citada é desse texto): nenhum é pino
só-entrada usado como saída, nenhum é pino de boot (strapping), e o POT fica no ADC1 (o ADC2 é do Wi-Fi).
Preço, loja, link e visto NÃO moram aqui: são lidos de ferramenta/catalogo/placa_desenvolvimento.json
(ou do arquivo em LAB_CATALOGO), pelas ofertas (modelo ou código da peça no catálogo).
"""
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

CATALOGO = Path(__file__).resolve().parents[2] / "ferramenta" / "catalogo" / "placa_desenvolvimento.json"
APELIDOS = ("LED", "BOTAO", "POT", "PWM", "VERMELHO", "AMARELO", "VERDE")


@dataclass
class Placa:
    id: str
    nome: str          # curto, ASCII: vira NOME no placa.py/placa.h
    chip: str
    tensao: float      # nível lógico dos pinos (V)
    adc_max: int
    vref_mv: int
    resumo: str        # o papel em poucas palavras (tabela)
    papel: str
    apelidos: dict     # apelido -> pino físico
    pinos: frozenset   # pinos físicos que existem na placa
    motores: dict      # linguagem -> motores em ordem de preferência
    nao_testa: tuple   # o que só a placa de verdade mostra
    fontes: tuple
    ofertas: tuple     # modelo (ou código) da peça no catálogo
    porta_serial: str = "uart0"
    reserva: bool = False
    adc_max_arduino: int = 0   # o maior valor do analogRead() do core Arduino, se for diferente de adc_max
    radio: str = ""            # o rádio do chip, em poucas palavras (datasheet)
    dormindo: str = ""         # consumo dormindo (deep sleep) do chip, do datasheet; a placa inteira gasta mais
    pino_max_v: float = 0.0    # a tensão máxima num pino (0 = tensao + 0,3 V: ESP32 DS Tabela 5-3, VIH máx VDD + 0,3)
    def fisico(self, nome, padrao=KeyError):
        """apelido ou pino em qualquer grafia ('LED', 'GPIO2', 'IO2', '2', 'd13', 'A0') -> nome físico"""
        s = str(nome).strip().upper()
        if s in self.apelidos:
            return self.apelidos[s]
        m = re.fullmatch(r"(GPIO|GP|IO|D|A|)(\d+)", s)
        if m:
            letra, n = m.group(1), int(m.group(2))
            if self.id == "nano":
                p = "A%d" % n if letra == "A" else ("A%d" % (n - 14) if n >= 14 else "D%d" % n)
            else:
                p = ("GP%d" if self.id == "pico" else "GPIO%d") % n
                p = p if letra in ("", "GPIO", "GP", "IO") else None
            if p in self.pinos:
                return p
        if padrao is not KeyError:
            return padrao
        raise ValueError("a placa %s não tem o pino '%s' (apelidos: %s)" % (self.id, nome, ", ".join(self.apelidos)))

    def apelidos_do(self, pino):
        return [a for a, p in self.apelidos.items() if p == pino]

    def numero(self, pino):
        """número do pino pro MicroPython/Arduino: GPIO23 -> 23, GP25 -> 25, D13 -> 13, A0 -> 'A0'"""
        return pino if pino.startswith("A") else int(re.sub(r"\D", "", pino))


def _gpio(*faixas):
    return frozenset("GPIO%d" % n for f in faixas for n in (f if isinstance(f, range) else [f]))


ESP_PADRAO = ("Wi-Fi, Bluetooth e o rádio", "o ADC de verdade (ruído, variação de chip pra chip)",
              "o tempo de CPU exato", "a tensão e a corrente reais nos pinos")

PLACAS = {p.id: p for p in [
    Placa("esp32", "ESP32 DevKit", "ESP32 (2 núcleos Xtensa LX6, 240 MHz, 520 KB SRAM, 4 MB flash); o chip muda com o "
          "módulo: ESP32-D0WDQ6 no WROOM-32 (o da oferta mais barata), ESP32-D0WD-V3 no WROOM-32E",
          3.3, 4095, 3300, "a de todo dia",
          "A de todo dia: a que mais tem oferta no Brasil, mais tutorial e a mais bem emulada; já é a da placa "
          "de estudo. Cuidados: 3,3 V (5 V queima), analógico com Wi-Fi só no ADC1 (GPIO32-39), GPIO34-39 só "
          "entrada, driver CH340/CP2102. A oferta mais barata (RoboCore) usa o módulo ESP32-WROOM-32, que a "
          "Espressif marca NRND (não recomendado pra projeto novo; datasheet v3.8): serve pra aprender e testar; "
          "na placa final, use o WROOM-32E.",
          # ds_esp32.txt: boot = GPIO0, 2, 5, 12 (MTDI) e 15 (MTDO), linhas 1105-1119 e Tabela 3-1 (1133);
          # só entrada = GPIO34-39, linha 3360; flash do módulo = GPIO6-11, linhas 717-727
          {"LED": "GPIO23",        # linha 732, I/O. O LED da DOIT DevKit é o GPIO2, que é pino de boot
           "BOTAO": "GPIO4",       # linha 712, I/O
           "POT": "GPIO34",        # linha 690, ADC1_CH6 (só entrada, usado como entrada)
           "PWM": "GPIO23",
           "VERMELHO": "GPIO25",   # linha 694
           "AMARELO": "GPIO26",    # linha 700
           "VERDE": "GPIO27"},     # linha 701
          _gpio(range(0, 20), 21, 22, 23, 25, 26, 27, range(32, 40)),
          {"micropython": ["gemeo", "qemu"], "arduino": ["nativo"]},
          ESP_PADRAO + ("Bluetooth Classic",),
          ("https://documentation.espressif.com/esp32_datasheet_en.pdf",
           "https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp32-devkitc/user_guide.html",
           "https://docs.micropython.org/en/latest/esp32/quickref.html",
           "https://www.robocore.net/wifi/esp32-wifi-bluetooth",
           "https://documentation.espressif.com/esp32-wroom-32_datasheet_en.pdf"),
          ("ESP32 Wi-Fi + Bluetooth", "ESP32 30 pinos", "ESP32 30 pinos USB-C", "ESP32s 38 pinos",
           "ESP32-WROOM-32D 38 pinos USB-C", "ESP32-WROOM-32E 38 pinos", "ESP32-WROOM-32D DevKitC V4"),
          # ds_esp32.txt linha 4 ("Wi-Fi + Bluetooth + Bluetooth LE") e 1746 (802.11 b/g/n); linha 227 (10 µA)
          radio="Wi-Fi 4 (802.11 b/g/n), Bluetooth clássico e BLE", dormindo="10 µA"),
    Placa("c3", "ESP32-C3 SuperMini", "ESP32-C3 (1 núcleo RISC-V, 160 MHz, 400 KB SRAM, 4 MB flash no chip)",
          3.3, 4095, 3300, "a barata e pequena",
          "A barata e pequena: a placa com Wi-Fi mais barata do catálogo, melhor em tudo que a D1 Mini "
          "(ESP8266). Cuidados: alguns lotes de SuperMini (AliExpress) têm o cristal perto demais da antena e o "
          "Wi-Fi quase não pega (fórum Arduino, abaixo): se não conectar nem perto do roteador, desconfie da placa; "
          "sem Bluetooth clássico; GPIO2/8/9 são de boot.",
          # ds_c3.txt: boot = GPIO2, GPIO8 e GPIO9, linha 1396; ADC1 = GPIO0-4, linhas 1059-1063
          {"LED": "GPIO3",         # linha 1062, ADC1_CH3 usado como saída. O LED azul da SuperMini é o GPIO8 (boot)
           "BOTAO": "GPIO4",       # linha 995 (MTMS: JTAG, não é de boot)
           "POT": "GPIO1",         # linha 1060, ADC1_CH1
           "PWM": "GPIO3",
           "VERMELHO": "GPIO5",    # linha 996
           "AMARELO": "GPIO6",     # linha 997
           "VERDE": "GPIO7"},      # linha 998
          _gpio(range(0, 11), 20, 21),   # os 13 da SuperMini: espboards.dev (abaixo)
          {"micropython": ["gemeo", "qemu"], "arduino": ["nativo"]},
          ESP_PADRAO + ("o USB nativo (a serial USB do C3)",),
          ("https://documentation.espressif.com/esp32-c3_datasheet_en.pdf",
           "https://www.espboards.dev/esp32/esp32-c3-super-mini/",
           "https://forum.arduino.cc/t/esp32-c3-super-mini-wifi-test-not-working-solved/1440107"),
          ("ESP32-C3",), porta_serial="usb",
          # ds_c3.txt linha 5 ("Wi-Fi (802.11b/g/n) and Bluetooth 5 (LE)") e 243 (5 µA)
          radio="Wi-Fi 4 (802.11 b/g/n) e BLE 5 (sem Bluetooth clássico)", dormindo="5 µA"),
    Placa("s3", "ESP32-S3 DevKitC-1", "ESP32-S3 (2 núcleos Xtensa LX7, 240 MHz, 512 KB SRAM); a N8R2 do preço: "
          "módulo ESP32-S3-WROOM-1, 8 MB de flash e 2 MB de PSRAM quad", 3.3, 4095, 3300, "a potente",
          "A potente: tela, câmera, áudio, IA (PSRAM), vira teclado/mouse/pendrive pelo USB OTG. Cuidados: o "
          "preço muda muito com a versão (N8R2: 8 MB de flash e 2 MB de PSRAM quad; N16R8: 16 MB e 8 MB de PSRAM "
          "octal) e entre lojas; na N16R8 e nas outras R8 os GPIO35-37 ficam presos à PSRAM octal, na N8R2 ficam "
          "livres.",
          # ds_s3.txt: boot = GPIO0, 3, 45 e 46, linhas 1596-1613 e Tabela 1627-1631; ADC1 = GPIO1-10, 1199-1208
          {"LED": "GPIO2",         # linha 785 (ADC1_CH1, linha 1346, usado como saída)
           "BOTAO": "GPIO4",       # linha 787
           "POT": "GPIO1",         # linha 1345, ADC1_CH0
           "PWM": "GPIO2",
           "VERMELHO": "GPIO5",    # linha 788
           "AMARELO": "GPIO6",     # linha 789
           "VERDE": "GPIO7"},      # linha 790
          _gpio(range(0, 22), range(35, 49)),   # pinagem da DevKitC-1 (user guide v1.1)
          {"micropython": ["gemeo"], "arduino": ["nativo"]},
          ESP_PADRAO + ("a PSRAM", "o USB OTG", "as instruções vetoriais (IA)"),
          ("https://documentation.espressif.com/esp32-s3_datasheet_en.pdf",
           "https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.1.html",
           "https://www.usinainfo.com.br/esp32/esp32-s3-devkitc-1-n8r2-8mb-flash-com-wifi-e-bluetooth-com-usb-c-8679.html"),
          # só a N8R2: a ficha (chip, PSRAM, heap do gêmeo) é dela. A N16R8 do catálogo (Baú) é outra placa
          ("ESP32-S3-DevKitC-1 N8R2",),
          # ds_s3.txt linha 5 ("Wi-Fi (IEEE 802.11b/g/n) and Bluetooth 5 (LE)") e 270 (7 µA)
          radio="Wi-Fi 4 (802.11 b/g/n) e BLE 5 (sem Bluetooth clássico)", dormindo="7 µA"),
    Placa("c6", "ESP32-C6 SuperMini", "ESP32-C6 (RISC-V 160 MHz + núcleo LP 20 MHz, 512 KB SRAM, 4 MB flash)",
          3.3, 4095, 3300, "a de bateria e casa conectada",
          "A de bateria e da casa conectada. Não é o chip dormindo que ganha (o C6 dorme com 7 µA, o C3 com 5 µA): "
          "é o rádio. O Wi-Fi 6 tem o TWT (o aparelho combina com o roteador quando acordar e o rádio dorme no "
          "meio), e o C6 fala Zigbee e Thread (Matter), redes feitas pra sensor de bateria. Pra bateria de verdade, "
          "a placa final leva o módulo ESP32-C6-MINI-1 com regulador de baixo consumo.",
          # ds_c6.txt: boot = MTMS (GPIO4), MTDI (GPIO5), GPIO8, GPIO9 e GPIO15, linhas 1609-1624 e 979-980;
          # ADC1 = GPIO0-6, linhas 1160-1166; USB = GPIO12/13, linhas 1167-1168
          {"LED": "GPIO2",         # linha 1162 (ADC1_CH2 usado como saída). O LED da SuperMini é o GPIO15 (boot)
           "BOTAO": "GPIO3",       # linha 1163
           "POT": "GPIO1",         # linha 1161, ADC1_CH1
           "PWM": "GPIO2",
           "VERMELHO": "GPIO18",   # linha 999
           "AMARELO": "GPIO19",    # linha 1000
           "VERDE": "GPIO20"},     # linha 1001
          _gpio(range(0, 24)),     # a SuperMini expõe 0-7, 9, 12-23: espboards.dev (abaixo)
          {"micropython": ["gemeo", "qemu"], "arduino": ["nativo"]},
          ESP_PADRAO + ("Wi-Fi 6, Zigbee e Thread", "o núcleo LP", "o consumo dormindo"),
          ("https://documentation.espressif.com/esp32-c6_datasheet_en.pdf",
           "https://www.espboards.dev/esp32/esp32-c6-super-mini/",
           "https://wiki.seeedstudio.com/xiao_esp32c6_getting_started/"),
          ("ESP32-C6 Super Mini",), porta_serial="usb",
          # ds_c6.txt linha 5 (Wi-Fi 6, Bluetooth 5 LE, Zigbee e Thread), 144 (TWT) e 210 (7 µA)
          radio="Wi-Fi 6 (802.11ax, com TWT), BLE 5, Zigbee e Thread", dormindo="7 µA"),
    Placa("nano", "Arduino Nano V3", "ATmega328P (AVR 8 bits, 16 MHz, 2 KB SRAM, 32 KB flash)",
          5.0, 1023, 5000, "a pra aprender (e a mais fiel)",
          "A pra aprender e a mais fiel no emulador: a mais barata, 5 V (liga direto em módulo de 5 V), "
          "emulação instrução por instrução do ATmega328P, 100% local. Sem rádio. Cuidado: a oferta da RoboCore "
          "diz 'ATMega328P ou ATmega328PB'; o emulador é do 328P, e o 328PB tem periféricos a mais e outra "
          "assinatura (a fidelidade depende de qual chip vier).",
          # ds_328p.txt (pinagem, linhas 81-140; texto do datasheet Automotive 7810, a mesma pinagem do DS40002061B)
          # + pinagem do Nano em docs.arduino.cc; o AVR não tem pino de boot
          {"LED": "D13",           # PB5 (linha 95); o LED da placa
           "BOTAO": "D2",          # PD2/INT0 (linha 82)
           "POT": "A0",            # PC0/ADC0 (linha 89)
           "PWM": "D9",            # PB1/OC1A, timer 1 (linha 106)
           "VERMELHO": "D10", "AMARELO": "D11", "VERDE": "D12"},   # PB2-PB4
          frozenset(["D%d" % n for n in range(14)] + ["A%d" % n for n in range(8)]),
          {"arduino": ["simavr", "avr8js", "nativo"]},
          ("a tensão real nos pinos", "pino flutuando (o emulador lê 0)", "o ADC de verdade"),
          ("https://ww1.microchip.com/downloads/aemDocuments/documents/MCU08/ProductDocuments/DataSheets/"
           "ATmega48A-PA-88A-PA-168A-PA-328-P-DS-DS40002061B.pdf",
           "https://docs.arduino.cc/hardware/nano/", "https://store.arduino.cc/products/arduino-nano",
           "https://www.robocore.net/placa-arduino/placa-nano-v3-com-cabo-usb-para-arduino"),
          ("Nano V3",),
          # DS40002061B: "Power-down Mode: 0.1µA" (1,8 V, 25 °C) e "Voltage on any Pin except RESET ... -0.5V to
          # VCC+0.5V" (Absolute Maximum Ratings)
          radio="nenhum", dormindo="0,1 µA (1,8 V; a 5 V gasta mais)", pino_max_v=5.5),
    Placa("pico", "Raspberry Pi Pico", "RP2040 (2 núcleos Cortex-M0+, 133 MHz, 264 KB SRAM, 2 MB flash)",
          3.3, 4095, 3300, "reserva fora do top 5",
          "Reserva fora do top 5: barata, MicroPython e Arduino, emulada no rp2040js. Sem rádio (o Pico W "
          "não é emulado).",
          # ds_pico.txt: GPIO23/24/29 são da placa e GPIO25 é o LED, linhas 296-310; ADC = GPIO26-29, linha 353.
          # O RP2040 não tem pino de boot (o BOOTSEL fica na flash)
          {"LED": "GP25",          # linha 305, "Connected to user LED"
           "BOTAO": "GP15", "POT": "GP26",   # GPIO26-29 são os analógicos (linha 353)
           "PWM": "GP16", "VERMELHO": "GP18", "AMARELO": "GP19", "VERDE": "GP20"},
          frozenset("GP%d" % n for n in list(range(23)) + [25, 26, 27, 28]),
          {"micropython": ["rp2040js"], "arduino": ["rp2040js"]},
          ("a flash (o sistema de arquivos dá ENODEV)", "o Pico W e o Wi-Fi", "o tempo de CPU exato"),
          ("https://pip-assets.raspberrypi.com/categories/610-raspberry-pi-pico/documents/RP-008307-DS-2-pico-datasheet.pdf",),
          ("Raspberry Pi Pico",), porta_serial="usb", reserva=True,
          # ds_pico.txt linhas 618-626: a placa inteira em DORMANT gasta 0,8 mA a 25 °C (média)
          radio="nenhum (o Pico W tem Wi-Fi)", dormindo="0,8 mA (a placa inteira)",
          # arduino-pico 6.3.1, cores/rp2040/wiring_analog.cpp linha 126: "static uint8_t _readBits = 10;" (o
          # analogRead() devolve 0 a 1023 até alguém chamar analogReadResolution(12))
          adc_max_arduino=1023),
]}


def _catalogo():
    arq = Path(os.environ.get("LAB_CATALOGO") or CATALOGO)
    try:
        return json.loads(arq.read_text(encoding="utf-8"))["pecas"]
    except (OSError, ValueError, KeyError):
        return None


def ofertas(placa, pecas=None):
    """ofertas em reais com estoque, da mais barata pra mais cara: [{loja, preco, link, visto, nome}]"""
    pecas = _catalogo() if pecas is None else pecas
    if pecas is None:
        return None
    saida = []
    for codigo, p in pecas.items():
        if codigo not in placa.ofertas and p.get("modelo") not in placa.ofertas:
            continue
        for o in [p] + list(p.get("outras_lojas") or []):
            sem = o.get("situacao") == "sem estoque" or o.get("estoque") == 0
            if o.get("moeda") == "BRL" and isinstance(o.get("preco"), (int, float)) and not sem:
                saida.append({"loja": o.get("loja"), "preco": o["preco"], "link": o.get("link"),
                              "visto": o.get("visto"), "nome": p.get("nome"), "codigo": codigo})
    return sorted(saida, key=lambda o: o["preco"])
