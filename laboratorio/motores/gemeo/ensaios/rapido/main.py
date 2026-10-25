# liga e desliga o LED sem sleep (bit-bang): na placa dá uns 50 mil trocas por segundo
from placa import *
from machine import Pin
import time
led = Pin(PINO_LED, Pin.OUT)
for i in range(300):            # 0,3 s piscando devagar: cada troca aparece
    led.value(i % 2)
    time.sleep_ms(1)
while True:                     # depois, o mais rápido que der
    led.value(1)
    led.value(0)
    led.value(0)
