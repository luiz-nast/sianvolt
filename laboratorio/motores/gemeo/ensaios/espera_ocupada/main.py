# espera ocupada: muito tutorial espera olhando o relógio em vez de sleep; ler o relógio custa tempo de placa
from placa import *
from machine import Pin
import time
led = Pin(PINO_LED, Pin.OUT)
while True:
    led.value(1 - led.value())
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < 500:
        pass
