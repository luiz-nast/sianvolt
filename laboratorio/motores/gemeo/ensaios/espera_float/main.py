# a espera que cresce 25% a cada passo, como a do dado: 40 * 1.25 é float, e o sleep_ms da placa só aceita int
import time

espera = 40
for passo in range(3):
    espera = espera * 1.25
    print("passo", passo, "espera", espera)
    time.sleep_ms(espera)   # na placa: TypeError: can't convert float to int (o certo: time.sleep_ms(int(espera)))
