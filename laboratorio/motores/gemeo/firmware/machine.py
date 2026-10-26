# machine.py do gêmeo: a mesma cara do machine do MicroPython no ESP32/C3/S3/C6 (Pin, PWM, ADC, I2C, SoftI2C, Timer,
# Signal, WDT, UART), mas quem responde é o motor do gêmeo. Roda igual no CPython e no MicroPython.
from _ponte import rpc, registrar, dormir_ate, inteiro

PWRON_RESET = 1
HARD_RESET = 2
WDT_RESET = 3
DEEPSLEEP_RESET = 4
SOFT_RESET = 5


def _gpio(p):
    if isinstance(p, Pin):
        return p._id
    if isinstance(p, Signal):
        return p._pin._id
    return int(p)


class Pin:
    IN = 1
    OUT = 3
    OPEN_DRAIN = 7
    PULL_DOWN = 1
    PULL_UP = 2
    IRQ_RISING = 1
    IRQ_FALLING = 2
    WAKE_LOW = 4
    WAKE_HIGH = 5
    DRIVE_0 = 0
    DRIVE_1 = 1
    DRIVE_2 = 2
    DRIVE_3 = 3

    def __init__(self, id, mode=-1, pull=-1, value=None, drive=None, hold=None):
        self._id = int(id)
        self.init(mode, pull, value=value, drive=drive)

    def init(self, mode=-1, pull=-1, value=None, drive=None, hold=None):
        rpc("pino_init", self._id, None if mode == -1 else mode,
            None if pull == -1 else (0 if pull is None else pull), value, drive)

    def value(self, x=None):
        if x is None:
            return rpc("pino_le", self._id)
        rpc("pino_escreve", self._id, 1 if x else 0)

    def __call__(self, x=None):
        return self.value(x)

    def on(self):
        rpc("pino_escreve", self._id, 1)

    def off(self):
        rpc("pino_escreve", self._id, 0)

    def toggle(self):
        rpc("pino_escreve", self._id, 0 if rpc("pino_le", self._id) else 1)

    def irq(self, handler=None, trigger=3, wake=None, hard=False):
        cb = registrar(handler, self) if handler else None
        rpc("pino_irq", self._id, trigger, cb)

    def __repr__(self):
        return "Pin(%d)" % self._id


class Signal:
    def __init__(self, pin, *args, **kw):
        invert = kw.pop("invert", False)
        self._pin = pin if isinstance(pin, Pin) else Pin(pin, *args, **kw)
        self._inv = 1 if invert else 0

    def value(self, x=None):
        if x is None:
            return self._pin.value() ^ self._inv
        self._pin.value((1 if x else 0) ^ self._inv)

    def on(self):
        self.value(1)

    def off(self):
        self.value(0)


_PWM_FREQ_MAX = 40000000   # check_freq_ranges(self, freq, 40000000) no machine_pwm.c


def _faixa(ok, texto):
    if not ok:
        raise ValueError(texto)


class PWM:
    # As regras do MicroPython 1.29 nas ESP (ports/esp32/machine_pwm.c), com as mesmas mensagens: todo número é int
    # (float dá TypeError "can't convert float to int"); freq de 1 Hz a 40 MHz, duty_u16 de 0 a 65535 (65535 é
    # ligado direto), duty de 0 a 1023 e duty_ns até o período, senão ValueError. No init, -1 (ou um duty negativo)
    # é "não mexe", e o duty_u16 ganha do duty_ns, que ganha do duty; sem freq, vale a do canal que o pino já tem
    # ou 5 kHz. O duty_ns no PWM(...) novo dá RuntimeError "PWM is inactive" (o 1.29 confere com a freq de um canal
    # que ainda não existe), e depois do deinit() todo método também.
    def __init__(self, dest, freq=-1, duty=-1, duty_u16=-1, duty_ns=-1, invert=False):
        self._id = _gpio(dest)
        self._freq = None                     # None = sem canal (antes do 1º init e depois do deinit)
        self._escala, self._valor = None, 0   # o duty como foi pedido: "u16", "u10" ou "ns" (o machine_pwm.c
        self._inv = False                     # guarda assim: o duty_ns muda de fração quando a freq muda)
        self.init(freq=freq, duty=duty, duty_u16=duty_u16, duty_ns=duty_ns, invert=invert)

    def _ativo(self):
        if self._freq is None:
            raise RuntimeError("PWM is inactive")

    def _ns_max(self):   # duty_to_ns(MAX_16_DUTY): o período em ns
        return (65536 * 1000000000 + self._freq * 32768) // (self._freq * 65536)

    def _u16(self, freq=None):
        """o duty em 16 bits (65535 = ligado direto) a partir da escala em que ele foi pedido"""
        if self._escala == "ns":   # ns_to_duty
            d = (self._valor * 65536 * (freq or self._freq) + 500000000) // 1000000000
            return min(65535, 1 if self._valor > 0 and d == 0 else d)
        if self._escala == "u10":   # duty << 6, e o 1023 vira ligado direto
            return 65535 if self._valor == 1023 else self._valor << 6
        return self._valor

    def init(self, freq=-1, duty=-1, duty_u16=-1, duty_ns=-1, invert=None):
        freq, duty, duty_u16, duty_ns = inteiro(freq), inteiro(duty), inteiro(duty_u16), inteiro(duty_ns)
        if freq != -1:
            _faixa(0 < freq <= _PWM_FREQ_MAX, "frequency must be from 1Hz to 40MHz")
        if duty_u16 >= 0:
            _faixa(duty_u16 <= 65535, "duty_u16 must be from 0 to 65536")
            escala = ("u16", duty_u16)
        elif duty_ns >= 0:
            self._ativo()
            _faixa(duty_ns <= self._ns_max(), "duty_ns must be from 0 to %d ns" % self._ns_max())
            escala = ("ns", duty_ns)
        elif duty >= 0:
            _faixa(duty <= 1023, "duty must be from 0 to 1023")
            escala = ("u10", duty)
        else:
            escala = (self._escala, self._valor) if self._escala else ("u16", 32768)   # PWM_DUTY: a metade
        if invert is not None:
            self._inv = bool(invert)
        self._escala, self._valor = escala
        nova = freq if freq != -1 else self._freq
        self._freq = rpc("pwm_init", self._id, nova, self._eletrico(nova))   # sem freq: o motor diz qual ficou

    def _eletrico(self, freq=None):
        u = self._u16(freq)
        return 65535 - u if self._inv else u

    def deinit(self):
        rpc("pwm_deinit", self._id)
        self._freq, self._escala, self._valor, self._inv = None, None, 0, False

    def freq(self, *f):
        if not f:
            self._ativo()
            return self._freq
        f = inteiro(f[0])
        self._ativo()
        _faixa(0 < f <= _PWM_FREQ_MAX, "frequency must be from 1Hz to 40MHz")
        mudou, self._freq = f != self._freq, f
        rpc("pwm_freq", self._id, f)   # sempre, como antes: o custo no relógio do gêmeo fica o mesmo
        if mudou and self._escala == "ns":   # o duty em ns é outra fração do período novo
            rpc("pwm_duty", self._id, self._eletrico())

    def duty_u16(self, *d):
        if not d:
            self._ativo()
            return self._u16()
        d = inteiro(d[0])
        _faixa(0 <= d <= 65535, "duty_u16 must be from 0 to 65536")
        self._ativo()
        self._escala, self._valor = "u16", d
        rpc("pwm_duty", self._id, self._eletrico())

    def duty(self, *d):
        if not d:
            self._ativo()
            return self._u16() >> 6
        d = inteiro(d[0])
        _faixa(0 <= d <= 1023, "duty must be from 0 to 1023")
        self._ativo()
        self._escala, self._valor = "u10", d
        rpc("pwm_duty", self._id, self._eletrico())

    def duty_ns(self, *ns):
        if not ns:
            self._ativo()
            return (self._u16() * 1000000000 + self._freq * 32768) // (self._freq * 65536)   # duty_to_ns
        ns = inteiro(ns[0])
        self._ativo()
        _faixa(0 <= ns <= self._ns_max(), "duty_ns must be from 0 to %d ns" % self._ns_max())
        self._escala, self._valor = "ns", ns
        rpc("pwm_duty", self._id, self._eletrico())


class ADC:
    ATTN_0DB = 0
    ATTN_2_5DB = 1
    ATTN_6DB = 2
    ATTN_11DB = 3
    WIDTH_9BIT = 9
    WIDTH_10BIT = 10
    WIDTH_11BIT = 11
    WIDTH_12BIT = 12

    def __init__(self, pin, atten=None):
        self._id = _gpio(pin)
        self._bits = 12
        rpc("adc_init", self._id, atten)

    def init(self, atten=None):
        if atten is not None:
            rpc("adc_atten", self._id, atten)

    def atten(self, a):
        rpc("adc_atten", self._id, a)

    def width(self, bits):
        self._bits = bits

    def read_u16(self):
        return rpc("adc_le", self._id, "u16")

    def read(self):
        return rpc("adc_le", self._id, "cru") >> (12 - self._bits)

    def read_uv(self):
        return rpc("adc_le", self._id, "uv")


class I2C:
    # sem scl/sda, o motor usa os pinos padrão do chip (no ESP32: I2C(0) scl=18 sda=19; no C3/S3: scl=9 sda=8)
    def __init__(self, id=0, scl=None, sda=None, freq=400000, timeout=50000):
        self._bus = id
        rpc("i2c_init", self._bus, None if scl is None else _gpio(scl), None if sda is None else _gpio(sda), int(freq))

    def scan(self):
        return rpc("i2c_scan", self._bus)

    def writeto(self, addr, buf, stop=True):
        return rpc("i2c_escreve", self._bus, addr, list(buf))

    def writevto(self, addr, vector, stop=True):
        dados = []
        for b in vector:
            dados.extend(list(b))
        return rpc("i2c_escreve", self._bus, addr, dados)

    def readfrom(self, addr, nbytes, stop=True):
        return bytes(rpc("i2c_le", self._bus, addr, nbytes))

    def readfrom_into(self, addr, buf, stop=True):
        d = rpc("i2c_le", self._bus, addr, len(buf))
        for i in range(len(buf)):
            buf[i] = d[i]

    def readfrom_mem(self, addr, memaddr, nbytes, addrsize=8):
        return bytes(rpc("i2c_le_mem", self._bus, addr, memaddr, nbytes))

    def readfrom_mem_into(self, addr, memaddr, buf, addrsize=8):
        d = rpc("i2c_le_mem", self._bus, addr, memaddr, len(buf))
        for i in range(len(buf)):
            buf[i] = d[i]

    def writeto_mem(self, addr, memaddr, buf, addrsize=8):
        rpc("i2c_escreve_mem", self._bus, addr, memaddr, list(buf))


class SoftI2C(I2C):
    def __init__(self, scl, sda, freq=400000, timeout=50000):
        self._bus = "soft-%d-%d" % (_gpio(scl), _gpio(sda))
        rpc("i2c_init", self._bus, _gpio(scl), _gpio(sda), int(freq))


class Timer:
    ONE_SHOT = 0
    PERIODIC = 1
    _virtuais = [0]

    def __init__(self, id=-1, **kw):
        if id == -1:
            Timer._virtuais[0] += 1
            self._key = "v%d" % Timer._virtuais[0]
        else:
            rpc("timer_existe", id)   # ValueError como o MicroPython: Timer(7) não existe no ESP32
            self._key = str(id)
        if kw:
            self.init(**kw)

    def init(self, mode=PERIODIC, period=-1, freq=-1, callback=None, tick_hz=1000):
        if freq > 0:
            periodo_us = int(1000000 / freq)
        else:
            periodo_us = int(period) * 1000000 // tick_hz
        cb = registrar(callback, self) if callback else None
        rpc("timer_init", self._key, periodo_us, mode == Timer.PERIODIC, cb)

    def deinit(self):
        rpc("timer_deinit", self._key)


class WDT:
    def __init__(self, id=0, timeout=5000):
        rpc("wdt_init", int(timeout))

    def feed(self):
        rpc("wdt_feed")


class UART:
    def __init__(self, id, baudrate=115200, **kw):
        self._id = id

    def init(self, *a, **kw):
        pass

    def write(self, buf):
        rpc("uart_escreve", self._id, list(buf.encode() if isinstance(buf, str) else bytes(buf)))
        return len(buf)

    def any(self):
        return 0

    def read(self, n=-1):
        return None

    def readline(self):
        return None


def freq(hz=None):
    if hz is None:
        return 160000000


def unique_id():
    return b"\x24\x0a\xc4\x00\x00\x01"


def reset():
    rpc("reset", "reset")


def soft_reset():
    rpc("reset", "soft_reset")


def reset_cause():
    return PWRON_RESET


def idle():
    rpc("custo", 1000)   # idle espera a próxima interrupção; aqui anda 1 ms


def lightsleep(ms=None):
    rpc("dormir_fundo", 10 ** 9 if ms is None else int(ms), "lightsleep")


def deepsleep(ms=None):
    rpc("dormir_fundo", 10 ** 9 if ms is None else int(ms), "deepsleep")


def disable_irq():
    return 0


def enable_irq(state=0):
    pass


def time_pulse_us(pin, level, timeout_us=1000000):
    raise NotImplementedError("o gêmeo ainda não mede pulso (time_pulse_us)")
