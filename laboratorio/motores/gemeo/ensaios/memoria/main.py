# o heap é o da placa: 2 MB não cabem no ESP32 sem PSRAM; Timer(7) não existe (só 4 timers de hardware)
import gc
from machine import Timer
gc.collect()
print("livre:", gc.mem_free())
try:
    Timer(7)
except ValueError as e:
    print("Timer:", e)
b = bytearray(2_000_000)
