from machine import Pin
import time
Pin(13, Pin.OUT).on()          # LED sem resistor
botao = Pin(4, Pin.IN)         # esqueceu o PULL_UP
print("botão:", botao.value())
time.sleep(1)
print("botão:", botao.value())
x = Pin(35, Pin.OUT)           # 35 é só entrada: o ESP32 de verdade dá ValueError
