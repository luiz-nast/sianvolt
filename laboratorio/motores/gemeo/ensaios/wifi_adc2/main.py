import network, time
from machine import ADC, Pin
w = network.WLAN(network.STA_IF)
w.active(True)
w.connect("casa", "senha")
t0 = time.ticks_ms()
while not w.isconnected():
    time.sleep_ms(100)
print("conectou em", time.ticks_diff(time.ticks_ms(), t0), "ms, ip", w.ifconfig()[0])
adc = ADC(Pin(25))            # ADC2: o Wi-Fi usa
try:
    adc.read_u16()
except OSError as e:
    print("ADC2 com Wi-Fi ligado:", e)
try:
    import urequests
except ImportError as e:
    print("sem rede de verdade:", e)
