# erro dentro do callback: na placa o traceback sai na serial e o programa segue
from placa import *
from machine import Pin
import time
botao = Pin(PINO_BOTAO, Pin.IN, Pin.PULL_UP)
def apertou(p):
    raise RuntimeError("erro dentro da interrupcao")
botao.irq(trigger=Pin.IRQ_FALLING, handler=apertou)
n = 0
while True:
    n += 1
    if n % 50 == 0:
        print("vivo", n)
    time.sleep_ms(10)
