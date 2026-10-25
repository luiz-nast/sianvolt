# termômetro I2C (registrador no estilo LM75 no endereço 0x48): acende o LED acima de 28 °C
from placa import *
from machine import Pin, I2C
import time

i2c = I2C(0)                 # sem scl/sda: os pinos padrão do chip
led = Pin(PINO_LED, Pin.OUT)
print("no barramento:", [hex(a) for a in i2c.scan()])
while True:
    d = i2c.readfrom_mem(0x48, 0x00, 2)
    temp = ((d[0] << 8 | d[1]) >> 7) * 0.5
    led.value(1 if temp > 28 else 0)
    print("temperatura", temp)
    time.sleep(1)
