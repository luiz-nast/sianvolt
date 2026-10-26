# luz: o LDR1 do circuito (circuito_ldr/placa_ldr.txt) num divisor com 22 kΩ no GPIO34. A luz vem do roteiro em lux
# (o roteiro.json começa em 100 lux; o gemeo.roteiro escurece em 1 s e clareia em 2 s) e o gêmeo põe o LDR no
# circuito: o ADC lê o divisor de verdade. No escuro a tensão sobe e o LED do GPIO23 acende
from machine import ADC, Pin
import time

olho = ADC(Pin(34), atten=ADC.ATTN_11DB)
led = Pin(23, Pin.OUT)
antes = None
while True:
    mv = olho.read_uv() // 1000
    if mv != antes:
        print("mv", mv)
        antes = mv
    led.value(1 if mv > 1500 else 0)
    time.sleep_ms(100)
