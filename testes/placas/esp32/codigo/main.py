# Placa de teste do Sianvolt (testes/placas/esp32): o programa que a etapa 8 roda no gêmeo do laboratório.
# Apertou o botão: o LED acende e o piezo apita. Soltou: apaga, cala e sorteia um número de 1 a 6. A semente do
# sorteio é o relógio na hora da soltura: na placa de verdade sai diferente a cada vez; no gêmeo, sempre igual.
# A cada meio segundo ele lê a luz no olho de luz (o divisor do GPIO34) e escreve na serial.
from machine import ADC, PWM, Pin
import random
import time

from pinos import BZ1, D1, LDR1, SW1   # o pinos.py sai do placa.txt (o Sianvolt gera): D1 = 32, SW1 = 14...

APITO_HZ = 4000     # a nota em que o datasheet do piezo (Murata) mede o som
LER_LUZ_MS = 500

led = Pin(D1, Pin.OUT, value=0)
botao = Pin(SW1, Pin.IN, Pin.PULL_UP)            # solto = 1, apertado = 0
som = PWM(Pin(BZ1), freq=APITO_HZ, duty_u16=0)   # duty 0 = calado
olho = ADC(Pin(LDR1))
olho.atten(ADC.ATTN_11DB)                         # a faixa boa vai de 0,15 a 2,45 V

print("pronto")
antes = botao.value()
apertou = time.ticks_ms()
leu = time.ticks_add(time.ticks_ms(), -LER_LUZ_MS)
while True:
    agora = botao.value()
    if agora != antes:
        antes = agora
        if agora == 0:
            led.on()
            som.duty_u16(32768)                   # metade do tempo ligado: o apito mais alto
            apertou = time.ticks_ms()
            print("LED aceso")
        else:
            led.off()
            som.duty_u16(0)
            print("LED apagado: segurou %d ms" % time.ticks_diff(time.ticks_ms(), apertou))
            random.seed(time.ticks_us())
            print("sorteou %d" % random.randint(1, 6))
    if time.ticks_diff(time.ticks_ms(), leu) >= LER_LUZ_MS:
        leu = time.ticks_ms()
        print("luz: %d mV" % (olho.read_uv() // 1000))
    time.sleep_ms(5)
