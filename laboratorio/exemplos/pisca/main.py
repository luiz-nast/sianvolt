# pisca: o LED fica meio segundo aceso e meio segundo apagado, pra sempre
from placa import *          # PINO_LED e os outros pinos da placa escolhida
from machine import Pin
import time

led = Pin(PINO_LED, Pin.OUT)

while True:
    led.value(1)             # acende
    time.sleep_ms(500)
    led.value(0)             # apaga
    time.sleep_ms(500)
