"""c3.py: o ESP32-C3 (o da SuperMini) como o gêmeo enxerga.

DS = ESP32-C3 Series Datasheet v2.4, https://documentation.espressif.com/esp32-c3_datasheet_en.pdf
     (linhas de ~/.cache/sianvolt/lab/placas/ds_c3.txt)
"""
from .comum import *  # noqa: F401,F403

NOME, CURTO = "ESP32-C3", "C3"
# medido no motor qemu (MicroPython 1.29.0 ESP32_GENERIC_C3) em 2026-10-25: gc.mem_free() = 164448 no começo e
# "Timer(2) doesn't exist, there are only 2 hardware timers"
HEAP_LIVRE, HEAP_FONTE, TIMERS = 164448, "medido no qemu", 2
# MPC machine_pin.h (CONFIG_IDF_TARGET_ESP32C3): 0-13, 20, 21; o 18 e o 19 só sem a USB Serial/JTAG,
# e o ESP32_GENERIC_C3 usa a USB Serial/JTAG pro REPL (DS linhas 1065-1066: GPIO18/19 = USB_D-/D+)
EXISTEM = set(range(0, 14)) | {20, 21}
SO_ENTRADA = set()   # o C3 não tem pino só de entrada
# DS linhas 1149-1156: GPIO11 é o VDD_SPI (alimenta a flash) e GPIO12-17 são o SPI da flash no chip
FLASH = {11, 12, 13}
PSRAM, PSRAM_TXT = set(), ""
# DS Seção 3 (linha 1394), Tabela 3-1 (linha 1412) e Tabela 3-3 (linha 1479): gpio -> (nível, pull, por quê)
BOOT = {2: (1, None, "a Espressif manda deixar em 1 por causa de ruído (Tabela 3-3, nota 2); por dentro fica solto"),
        8: (1, None, "em 0 não dá pra gravar pelo USB, porque o modo de gravação pede GPIO8 = 1; por dentro fica solto"),
        9: (1, 1, "em 0 o C3 entra no modo de gravação e não roda o programa")}
# DS linha 1147: GPIO20/21 = UART0 (o ESP32_GENERIC_C3 também põe o REPL na UART0: MPC mpconfigboard.h)
SERIAL = {20: "o RX da UART0 (REPL)", 21: "o TX da UART0 (REPL)"}
# DS linhas 1059-1064: ADC1 = GPIO0-4, ADC2 = GPIO5
ADC1 = set(range(0, 5))
ADC2 = {5}
# DS 4.2.2.1 (linhas 2631-2634): "ADC2 of some chip revisions is not operable". SUPOSIÇÃO: com o Wi-Fi ligado o ADC2
# dá erro como no ESP32 e no S3 (o datasheet do C3 não fala de Wi-Fi)
ADC2_WIFI = True
# DS Tabela 5-6 (linha 3003): faixa útil de cada atenuação: 0-750, 0-1050, 0-1300, 0-2500 mV
ATTEN_FAIXA = {0: (0.0, 0.75), 1: (0.0, 1.05), 2: (0.0, 1.3), 3: (0.0, 2.5)}
ATTEN_FUNDO = {0: 0.75, 1: 1.05, 2: 1.3, 3: 2.5}   # SUPOSIÇÃO: o valor cru 4095 no topo da faixa
# MPC machine_i2c.h: I2C(0) scl=9 sda=8 (dois pinos de boot!); o C3 só tem um I2C
I2C_PADRAO = {0: (9, 8)}
