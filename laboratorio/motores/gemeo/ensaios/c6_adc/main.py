# no C6 o ADC só existe no GPIO0-6 (ADC1); o GPIO7 dá ValueError
from machine import ADC, Pin
ADC(Pin(7))
