# na S3 o GPIO35 é da PSRAM octal (N16R8): funciona no firmware genérico, mas é perigoso
from machine import Pin
import time
p = Pin(35, Pin.OUT)
p.value(1)
time.sleep(0.1)
