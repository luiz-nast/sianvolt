# botao: o LED acende enquanto o botão está apertado
# o botão liga o pino no GND: solto = 1 (pull-up interno), apertado = 0
from placa import *
from machine import Pin
import time

led = Pin(PINO_LED, Pin.OUT)
botao = Pin(PINO_BOTAO, Pin.IN, Pin.PULL_UP)
led.value(0)
antes = 1

while True:
    agora = botao.value()
    if agora != antes:       # só fala quando muda
        print("apertou" if agora == 0 else "soltou")
        antes = agora
    led.value(1 - agora)     # apertado (0) acende, solto (1) apaga
    time.sleep_ms(10)        # olha o botão 100 vezes por segundo
