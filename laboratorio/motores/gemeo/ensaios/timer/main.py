# pisca por Timer: o programa acaba na hora, mas o Timer segue (como no REPL da placa)
from placa import *
from machine import Pin, Timer
led = Pin(PINO_LED, Pin.OUT)
Timer(0).init(period=250, mode=Timer.PERIODIC, callback=lambda t: led.value(not led.value()))
