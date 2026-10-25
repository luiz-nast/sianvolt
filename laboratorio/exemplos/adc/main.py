# adc: lê o potenciômetro a cada 200 ms, mostra a tensão e acende o LED acima de 1500 mV
from placa import *          # PINO_POT, PINO_LED, VREF_MV
from machine import ADC, Pin
import time

pot = ADC(Pin(PINO_POT))     # no ESP32 já vem com atenuação de 11 dB (lê até ~3 V)
led = Pin(PINO_LED, Pin.OUT)
led.value(0)


def milivolts():
    if hasattr(pot, "read_uv"):                   # ESP32: já sai calibrado, em microvolts
        return pot.read_uv() // 1000
    return pot.read_u16() * VREF_MV // 65535      # Pico: 0 a 65535 = 0 a VREF_MV


while True:
    mv = milivolts()
    print("pot=" + str(mv) + " mV")
    led.value(1 if mv > 1500 else 0)
    time.sleep_ms(200)
