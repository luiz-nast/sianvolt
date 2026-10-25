# ola: diz olá pela serial a cada meio segundo, contando as vezes
from placa import *          # NOME = o nome da placa, ex.: "ESP32 DevKit"
import time

vez = 1
while True:
    print(str(vez) + ": olá do " + NOME)   # sai assim: "1: olá do ESP32 DevKit"
    vez += 1
    time.sleep_ms(500)
