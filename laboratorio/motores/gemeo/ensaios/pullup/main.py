# pullup: o pino do LED (GPIO23) ficou como ENTRADA com pull-up, o erro de quem esqueceu o Pin.OUT. Passa um
# fiozinho de corrente pelo pull-up de dentro (45 kΩ) e pelo LED: o evento 'led' tem os números (dezenas de µA,
# menos de 1% da luz), mas o LED está apagado pra todo mundo (aceso False, como o texto)
from machine import Pin
import time

p = Pin(23, Pin.IN, Pin.PULL_UP)
time.sleep(1)
print("fim")
