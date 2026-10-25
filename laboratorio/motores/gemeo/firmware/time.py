# time.py do gêmeo: o relógio é de mentira. sleep não espera de verdade, só anda o relógio do motor.
# Ler o relógio (ticks_*, time) custa um pouco de tempo de placa, como no chip: assim um laço que espera
# olhando o relógio (while ticks_diff(ticks_ms(), t0) < 500: pass) anda. O sleep lê de graça: fica exato.
from _ponte import rpc, dormir_ate

_P = 1 << 30   # os ticks do MicroPython dão a volta em 2**30


def sleep(s):
    dormir_ate(rpc("agora_us", 0) + int(s * 1000000))


def sleep_ms(ms):
    dormir_ate(rpc("agora_us", 0) + int(ms) * 1000)


def sleep_us(us):
    dormir_ate(rpc("agora_us", 0) + int(us))


def ticks_us():
    return rpc("agora_us") & (_P - 1)


def ticks_ms():
    return (rpc("agora_us") // 1000) & (_P - 1)


def ticks_cpu():
    return ticks_us()


def ticks_add(t, delta):
    return (t + delta) & (_P - 1)


def ticks_diff(a, b):
    return ((a - b + _P // 2) & (_P - 1)) - _P // 2


def time():
    return rpc("agora_us") // 1000000


def time_ns():
    return rpc("agora_us") * 1000


def localtime(s=None):
    return tuple(rpc("localtime", time() if s is None else int(s)))


gmtime = localtime
