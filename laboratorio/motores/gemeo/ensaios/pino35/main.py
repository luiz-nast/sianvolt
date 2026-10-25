# Pin(35, Pin.OUT) na esp32: o 35 é só entrada (DS linha 3360); o MicroPython de verdade dá ValueError
from machine import Pin
Pin(35, Pin.OUT)
