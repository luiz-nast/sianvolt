# no C3 o GPIO18/19 são o USB do REPL: o MicroPython ESP32_GENERIC_C3 nem aceita o número
from machine import Pin
Pin(18, Pin.OUT)
