# pwm: o LED liga e desliga 1000 vezes por segundo; o que muda é quanto tempo fica ligado
# 25% ligado por 1 s (fraquinho), 75% por 1 s (forte), e repete
from placa import *
from machine import Pin, PWM
import time

pwm = PWM(Pin(PINO_PWM), freq=1000, duty_u16=16384)   # 16384 de 65536 = 25%

while True:
    time.sleep(1)
    pwm.duty_u16(49152)      # 75%
    time.sleep(1)
    pwm.duty_u16(16384)      # volta pros 25%
