# semaforo: verde 2 s, amarelo 0,5 s, vermelho 2 s, e repete
from placa import *          # PINO_VERDE, PINO_AMARELO, PINO_VERMELHO
from machine import Pin
import time

verde = Pin(PINO_VERDE, Pin.OUT)
amarelo = Pin(PINO_AMARELO, Pin.OUT)
vermelho = Pin(PINO_VERMELHO, Pin.OUT)


def so_acende(luz, segundos):
    for p in (verde, amarelo, vermelho):
        p.value(1 if p is luz else 0)   # a escolhida acende, as outras apagam
    time.sleep(segundos)


while True:
    so_acende(verde, 2)
    so_acende(amarelo, 0.5)
    so_acende(vermelho, 2)
