# GPIO34 como saída na esp32: só entrada (DS linha 3360)
from machine import Pin
led = Pin(34, Pin.OUT)
led.value(1)
