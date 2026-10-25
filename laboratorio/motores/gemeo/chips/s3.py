"""s3.py: o ESP32-S3 (o da DevKitC-1 N8R2, a do preço; a N16R8 só muda a PSRAM) como o gêmeo enxerga.

DS = ESP32-S3 Series Datasheet v2.2, https://documentation.espressif.com/esp32-s3_datasheet_en.pdf
     (linhas de ~/.cache/sianvolt/lab/placas/ds_s3.txt)
"""
from .comum import *  # noqa: F401,F403

NOME, CURTO = "ESP32-S3", "S3"
# SEM MEDIDA (o qemu não sobe o S3): a N8R2 tem 2 MB de PSRAM, que o MicroPython ESP32_GENERIC_S3 usa como heap;
# 4 timers de hardware (2 grupos de 2)
HEAP_LIVRE, HEAP_FONTE, TIMERS = 2 * 1024 * 1024, "estimado: a PSRAM de 2 MB da N8R2", 4
# MPC machine_pin.h (ESP32S3, firmware ESP32_GENERIC_S3 com PSRAM quad): 0-21 e 33-48; o 26 sai por causa da
# PSRAM. No firmware SPIRAM_OCT (N16R8) o 33-37 também sai (aqui vira aviso)
EXISTEM = set(range(0, 22)) | set(range(33, 49))
SO_ENTRADA = set()
# DS linhas 1312-1313: GPIO26-32 = SPI0/1 da flash e da PSRAM
FLASH = set(range(26, 33))
# DS linhas 1305-1307: GPIO33-37 são a PSRAM no modo de 8 linhas (octal, como na N16R8)
PSRAM, PSRAM_TXT = set(range(33, 38)), "PSRAM octal das versões R8, como a N16R8"
# a placa do laboratório é a N8R2 (PSRAM quad, nos pinos da flash): lá os 33-37 ficam livres
PSRAM_AVISO = ("GPIO%d é da PSRAM octal nas S3 R8 (N16R8, N8R8): na N8R2 do laboratório (PSRAM quad) ele está livre; "
               "se a sua placa for R8, não use")
# DS Seção 3 (linha 1590), Tabela 3-1 (linha 1625), 3-3 (linha 1695) e 3-4 (linha 1732)
BOOT = {0: (1, 1, "em 0 o S3 entra no modo de gravação e não roda o programa"),
        3: (None, None, "escolhe a fonte do JTAG se o eFuse mandar; por dentro fica solto"),
        45: (0, 0, "em 1 a flash recebe 1,8 V e a flash de 3,3 V do módulo não liga"),
        46: (0, 0, "em 1, junto com GPIO0 em 0, o boot fica numa combinação inválida")}
# DS linhas 1299 e 1303: GPIO19/20 = USB, GPIO43/44 = UART0
SERIAL = {19: "o USB D- (REPL pelo USB)", 20: "o USB D+ (REPL pelo USB)",
          43: "o TX da UART0 (REPL)", 44: "o RX da UART0 (REPL)"}
# DS Tabela 2-8 (linhas 1195-1218): ADC1 = GPIO1-10, ADC2 = GPIO11-20
ADC1 = set(range(1, 11))
ADC2 = set(range(11, 21))
ADC2_WIFI = True   # DS linha 3364: "ADC2_CH... analog functions ... cannot be used with Wi-Fi simultaneously"
# DS Tabela 5-6 (linha 3746): faixa útil de cada atenuação: 0-850, 0-1100, 0-1600, 0-2900 mV
ATTEN_FAIXA = {0: (0.0, 0.85), 1: (0.0, 1.1), 2: (0.0, 1.6), 3: (0.0, 2.9)}
ATTEN_FUNDO = {0: 0.85, 1: 1.1, 2: 1.6, 3: 2.9}   # SUPOSIÇÃO: o valor cru 4095 no topo da faixa
# MPC boards/ESP32_GENERIC_S3/mpconfigboard.h e machine_i2c.h: I2C(0) e I2C(1) em scl=9 sda=8
I2C_PADRAO = {0: (9, 8), 1: (9, 8)}
