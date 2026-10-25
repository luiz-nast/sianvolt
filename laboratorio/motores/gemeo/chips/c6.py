"""c6.py: o ESP32-C6 (o da SuperMini) como o gêmeo enxerga.

DS = ESP32-C6 Series Datasheet v1.5, https://documentation.espressif.com/esp32-c6_datasheet_en.pdf
     (linhas de ~/.cache/sianvolt/lab/placas/ds_c6.txt)
"""
from .comum import *  # noqa: F401,F403

NOME, CURTO = "ESP32-C6", "C6"
# SEM MEDIDA (não há emulador do C6): o heap do C3 medido, por baixo (o C6 tem 512 KB de SRAM, o C3 400 KB);
# 2 timers de hardware como o C3 (2 grupos de 1 timer)
HEAP_LIVRE, HEAP_FONTE, TIMERS = 164448, "estimado: o do C3", 2
# MPC machine_pin.h (CONFIG_IDF_TARGET_ESP32C6): 0-11 e 14-23; o 12 e o 13 só sem a USB Serial/JTAG,
# que o ESP32_GENERIC_C6 usa pro REPL (DS linha 1245: GPIO12/13 = USB Serial/JTAG)
EXISTEM = set(range(0, 12)) | set(range(14, 24))
SO_ENTRADA = set()
FLASH = set()   # DS linha 1257: GPIO24-30 são da flash, e o MicroPython nem aceita esses números
PSRAM, PSRAM_TXT = set(), ""
# DS Seção 3 (linha 1603), Tabela 3-1 (linha 1637) e Tabela 3-3 (linha 1707)
BOOT = {4: (None, None, "MTMS: só muda o tempo do SDIO escravo; por dentro fica solto"),
        5: (None, None, "MTDI: só muda o tempo do SDIO escravo; por dentro fica solto"),
        8: (1, None, "em 0 não dá pra gravar pelo USB, porque o modo de gravação pede GPIO8 = 1; por dentro fica solto"),
        9: (1, 1, "em 0 o C6 entra no modo de gravação e não roda o programa"),
        15: (None, None, "escolhe a fonte do JTAG se o eFuse mandar; por dentro fica solto")}
SERIAL = {16: "o TX da UART0 (REPL)", 17: "o RX da UART0 (REPL)"}   # DS linha 1249: GPIO16/17 = UART0
# DS linhas 1160-1166: ADC1 = GPIO0-6; o C6 não tem ADC2
ADC1 = set(range(0, 7))
ADC2 = set()
# DS Tabela 5-6 (linha 3639): faixa útil de cada atenuação: 0-1000, 0-1300, 0-1900, 0-3300 mV
ATTEN_FAIXA = {0: (0.0, 1.0), 1: (0.0, 1.3), 2: (0.0, 1.9), 3: (0.0, 3.3)}
ATTEN_FUNDO = {0: 1.0, 1: 1.3, 2: 1.9, 3: 3.3}   # SUPOSIÇÃO: o valor cru 4095 no topo da faixa
# MPC machine_i2c.h: I2C(0) scl=18 sda=19; o C6 só tem um I2C de alto desempenho
I2C_PADRAO = {0: (18, 19)}
