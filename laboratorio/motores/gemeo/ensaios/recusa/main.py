# o que o MicroPython 1.29 do chip recusa, o gêmeo recusa igual (extmod/modtime.c e ports/esp32/machine_pwm.c):
# float onde a placa quer int, duty e freq fora da faixa, ticks_add longe demais. Cada linha é "nome: ok" ou
# "nome: Tipo: mensagem"; o testa.py confere no gêmeo e, com o qemu instalado, compara com o chip emulado.
# As linhas "valor ..." são só do gêmeo (no qemu o prelúdio lembra o duty pedido, não o que o LEDC fez).
import time
from machine import Pin, PWM


def tenta(nome, f):
    try:
        f()
        print("%s: ok" % nome)
    except Exception as e:
        print("%s: %s: %s" % (nome, type(e).__name__, e))


tenta("sleep_ms(1.5)", lambda: time.sleep_ms(1.5))
tenta("sleep_ms(True)", lambda: time.sleep_ms(True))
tenta("sleep_us(2.5)", lambda: time.sleep_us(2.5))
tenta("sleep('1')", lambda: time.sleep("1"))
tenta("sleep_ms(2**31)", lambda: time.sleep_ms(2 ** 31))
tenta("ticks_add(0, 2**29)", lambda: time.ticks_add(0, 2 ** 29))
tenta("ticks_add(0, -(2**29))", lambda: time.ticks_add(0, -(2 ** 29)))
tenta("ticks_add(0, 2**29 - 1)", lambda: time.ticks_add(0, 2 ** 29 - 1))
tenta("ticks_add(0, 1.5)", lambda: time.ticks_add(0, 1.5))
tenta("PWM(duty_u16=70000)", lambda: PWM(Pin(23), freq=1000, duty_u16=70000))
tenta("PWM(freq=0)", lambda: PWM(Pin(23), freq=0))
tenta("PWM(freq=1000.0)", lambda: PWM(Pin(23), freq=1000.0))
tenta("PWM(duty=1024)", lambda: PWM(Pin(23), duty=1024))
tenta("PWM(duty_ns=500000)", lambda: PWM(Pin(23), freq=1000, duty_ns=500000))
luz = PWM(Pin(23), freq=1000, duty_u16=0)
tenta("duty_u16(65535)", lambda: luz.duty_u16(65535))
tenta("duty_u16(65536)", lambda: luz.duty_u16(65536))
tenta("duty_u16(-1)", lambda: luz.duty_u16(-1))
tenta("duty_u16(1.5)", lambda: luz.duty_u16(1.5))
tenta("duty(1024)", lambda: luz.duty(1024))
tenta("duty_ns(1000001)", lambda: luz.duty_ns(1000001))
tenta("freq(0)", lambda: luz.freq(0))
tenta("freq(1047.5)", lambda: luz.freq(1047.5))
tenta("freq(40000001)", lambda: luz.freq(40000001))
tenta("init(freq=0)", lambda: luz.init(freq=0))
tenta("init(duty_u16=-7)", lambda: luz.init(duty_u16=-7))
luz.duty(512)
print("valor duty(512) -> duty_u16 %d" % luz.duty_u16())
luz.duty_ns(250000)
luz.freq(2000)
print("valor duty_ns(250000) e freq(2000) -> duty_u16 %d" % luz.duty_u16())
luz.deinit()
outra = PWM(Pin(23))   # sem freq nem duty: no qemu o prelúdio não tem o que lembrar, e quem responde é o chip
outra.deinit()
tenta("freq() depois do deinit", lambda: outra.freq())
tenta("duty_u16(100) depois do deinit", lambda: outra.duty_u16(100))
print("fim")
