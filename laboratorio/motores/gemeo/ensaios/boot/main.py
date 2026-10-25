# o roteiro segura o GPIO0 (botão BOOT) em 0 quando a placa liga: o ESP32 entraria no modo de gravação
from machine import Pin
import time
b = Pin(0, Pin.IN, Pin.PULL_UP)
time.sleep(0.5)
print("GPIO0 =", b.value())
