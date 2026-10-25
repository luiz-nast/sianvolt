"""esp32.py: o ESP32 clássico do DevKit como o gêmeo enxerga (o chip é o D0WD-V3 no módulo WROOM-32E ou o
D0WDQ6 no WROOM-32: os mesmos pinos e as mesmas regras).

DS = ESP32 Series Datasheet v5.3, https://documentation.espressif.com/esp32_datasheet_en.pdf
     (linhas de ~/.cache/sianvolt/lab/placas/ds_esp32.txt)
"""
from .comum import *  # noqa: F401,F403

NOME, CURTO = "ESP32 (D0WD-V3 no WROOM-32E, D0WDQ6 no WROOM-32)", "ESP32"
# medido no motor qemu (MicroPython 1.29.0 ESP32_GENERIC) em 2026-10-25: gc.mem_free() = 151840 no começo,
# MemoryError num bytearray de 100 KB (o heap da placa é dividido) e "Timer(4) doesn't exist, there are only
# 4 hardware timers"
HEAP_LIVRE, HEAP_FONTE, TIMERS = 151840, "medido no qemu", 4
# MPC machine_pin.h (CONFIG_IDF_TARGET_ESP32): o que o MicroPython 1.29 aceita; MPQ: "0-19, 21-23, 25-27, 32-39"
EXISTEM = set(range(0, 20)) | {21, 22, 23, 25, 26, 27} | set(range(32, 40))
# DS linha 3360: "GPIO pins 34-39 are input-only. These pins do not feature an output driver or internal pull"
SO_ENTRADA = set(range(34, 40))
# DS linhas 717-727: GPIO6-11 ligados à flash SPI do módulo (SD_CLK, SD_DATA0-3, SD_CMD)
FLASH = {6, 7, 8, 9, 10, 11}
PSRAM, PSRAM_TXT = {16, 17}, "módulos WROVER"   # MPQ: 16 e 17 são da PSRAM no WROVER
# DS Seção 3, linhas 1100-1119, e Tabela 3-1 (linha 1133): gpio -> (nível pra rodar, pull de dentro, por quê)
BOOT = {0: (1, 1, "em 0 o ESP32 entra no modo de gravação e não roda o programa"),
        2: (0, 0, "em 1, junto com GPIO0 em 0, o ESP32 não entra no modo de gravação"),
        5: (1, 1, "em 0 muda o tempo do SDIO escravo"),
        12: (0, 0, "MTDI: em 1 a flash recebe 1,8 V e o módulo de 3,3 V (WROOM) não liga"),
        15: (1, 1, "MTDO: em 0 o ESP32 não manda o log de boot pela serial")}
SERIAL = {1: "o TX da serial (REPL)", 3: "o RX da serial (REPL)"}   # MPQ: "Pins 1 and 3 are REPL UART TX and RX"
# DS Tabela 4-6 (linhas 2527-2545): ADC1 = GPIO32-39, ADC2 = GPIO0, 2, 4, 12-15, 25-27
ADC1 = set(range(32, 40))
ADC2 = {0, 2, 4, 12, 13, 14, 15, 25, 26, 27}
ADC2_WIFI = True   # MPQ: "ADC block 2 is also used by WiFi"; com o Wi-Fi ligado a leitura dá erro
# MPQ: faixa quase linear de cada atenuação: 0 dB 100-950 mV, 2,5 dB 100-1250, 6 dB 150-1750, 11 dB 150-2450
ATTEN_FAIXA = {0: (0.10, 0.95), 1: (0.10, 1.25), 2: (0.15, 1.75), 3: (0.15, 2.45)}
# fundo de escala do valor cru (4095): SUPOSIÇÃO, uma reta que passa pela faixa linear; o chip de verdade
# varia ±6% (DS linha 2434) e tem DNL ±7 / INL ±12 LSB (DS Tabela 4-3, linha 2401)
ATTEN_FUNDO = {0: 1.1, 1: 1.5, 2: 2.2, 3: 3.9}
# MPC machine_i2c.h: I2C(0) scl=18 sda=19; I2C(1) scl=25 sda=26
I2C_PADRAO = {0: (18, 19), 1: (25, 26)}

# Pinagem do DevKit de 30 pinos da biblioteca do Sianvolt (esp32_devkit): 1-15 numa fileira, 16-30 na outra.
# SUPOSIÇÃO a conferir com a placa comprada: igual ao "DOIT ESP32 DevKit V1" de 30 pinos, que bate com a
# biblioteca (GND nos pinos 14 e 17). Pino físico -> "GPIOn", "3V3", "VIN", "GND", "EN".
DEVKIT = {
    "1": "EN", "2": "GPIO36", "3": "GPIO39", "4": "GPIO34", "5": "GPIO35", "6": "GPIO32", "7": "GPIO33",
    "8": "GPIO25", "9": "GPIO26", "10": "GPIO27", "11": "GPIO14", "12": "GPIO12", "13": "GPIO13", "14": "GND",
    "15": "VIN",
    "16": "3V3", "17": "GND", "18": "GPIO15", "19": "GPIO2", "20": "GPIO4", "21": "GPIO16", "22": "GPIO17",
    "23": "GPIO5", "24": "GPIO18", "25": "GPIO19", "26": "GPIO21", "27": "GPIO3", "28": "GPIO1", "29": "GPIO22",
    "30": "GPIO23",
}
