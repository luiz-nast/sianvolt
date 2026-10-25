# preludio.py: roda no MicroPython do ESP32 emulado ANTES do programa (o motor qemu manda pelo raw REPL).
# Não é importado no PC. O GPIO do QEMU da Espressif é um esboço (escrever some, ler dá sempre 0) e o
# ADC derruba o chip; por isso, só dentro do emulador:
#   - Pin com modo (IN/OUT/OPEN_DRAIN) ou com roteiro vira um Pin de faz de conta: escreve no pino de
#     verdade (o motor vê no trace) e lê o roteiro, o pull-up/pull-down ou o último valor escrito;
#   - ADC é de faz de conta: lê os volts do roteiro (0 a 3,3 V lineares, 12 bits);
#   - PWM lembra o que foi pedido (o QEMU devolve 0, e no C3 ler de volta derruba o chip);
#   - PWM, I2C, SPI, UART, Signal e bitstream aceitam o Pin de faz de conta;
#   - irq de pino do roteiro dispara por um Timer(-1) (virtual, não ocupa os do programa) na hora da troca;
#   - os módulos que o programa importa já vêm carregados (o sistema de arquivos do ESP32 no QEMU é lento);
#   - network.WLAN é de mentira: ligar dá OSError (o rádio não é emulado; o de verdade trava o chip).
# Marcas pro motor (machine.mem32 em GPIO_BT_SELECT, que o QEMU descarta): 0x53 cc pp aa
#   cc 1 = começo do programa (t = 0), 2 = fim, 3 = modo do pino pp (aa 1 entrada, 2 pullup, 3 pulldown,
#   4 adc), 5 = ADC de faz de conta no pino pp, 6 = o programa tentou ligar o Wi-Fi.
def _sv_instala(D):
    import machine, time
    M, E, V, AD, T = D["M"], D["E"], D["V"], D["ADC"], D["T"]   # T: pino da placa -> pino do chip emulado
    De = {c: p for p, c in T.items()}
    T0 = [time.ticks_ms()]

    def marca(c, p=0, a=0):
        machine.mem32[M] = 0x53000000 | (c << 16) | ((p & 0xFF) << 8) | (a & 0xFF)

    def agora():
        return time.ticks_diff(time.ticks_ms(), T0[0])

    def no_roteiro(lista, padrao):
        t, v = agora(), padrao
        for ms, x in lista:
            if t < ms:
                break
            v = x
        return v

    Real = machine.Pin
    vigiados, relogio = [], [None]

    def real(x):
        return x._p if isinstance(x, Pin) else x

    def numero(x):   # 23, Pin de faz de conta ou Pin(23) de verdade -> 23
        if isinstance(x, int):
            return x
        if isinstance(x, Pin):
            return x._id
        n = int(str(x).split("(")[1].split(")")[0].split(",")[0])
        return De.get(n, n)

    def proximo():
        t, prox = agora(), None
        for p in vigiados:
            for ms, _ in E[p._id]:
                if ms > t:
                    prox = ms if prox is None or ms < prox else prox
                    break
        if prox is not None:
            if relogio[0] is None:
                relogio[0] = machine.Timer(-1)
            relogio[0].init(period=max(1, prox - t), mode=machine.Timer.ONE_SHOT, callback=dispara)

    def dispara(_):
        for p in vigiados:
            v, (h, trig, antes) = p._le(), p._irq
            if v != antes:
                p._irq = (h, trig, v)
                if h and ((v and trig & Real.IRQ_RISING) or (not v and trig & Real.IRQ_FALLING)):
                    try:
                        h(p)
                    except Exception as e:   # como a placa: o traceback sai na serial e o programa segue
                        import sys
                        sys.print_exception(e)
        proximo()

    class Pin:
        def __new__(cls, id, *a, **k):
            if not (a or k) and id not in E:
                return Real(T.get(id, id))   # Pin(n) sem modo: o de verdade (PWM, ADC, I2C, OneWire...)
            o = object.__new__(cls)
            o._id, o._p, o._modo, o._pull, o._v, o._irq = id, Real(T.get(id, id)), None, None, 0, None
            if a or k:
                o.init(*a, **k)
            return o

        def init(self, *a, **k):
            self._p.init(*a, **k)
            if len(a) > 0 or "mode" in k:
                self._modo = a[0] if a else k["mode"]
            pull = a[1] if len(a) > 1 else k.get("pull", -1)
            if pull != -1:
                self._pull = pull
            if k.get("value") is not None:
                self._v = 1 if k["value"] else 0
            if self._modo == Real.IN:
                marca(3, self._id, 2 if self._pull == Real.PULL_UP else 3 if self._pull == Real.PULL_DOWN else 1)

        def _le(self):
            ext, pull = E.get(self._id), 1 if self._pull == Real.PULL_UP else 0
            if self._modo == Real.OUT:
                return self._v
            if self._modo == Real.OPEN_DRAIN and self._v == 0:
                return 0
            return no_roteiro(ext, pull) if ext else pull

        def value(self, *a):
            if not a:
                return self._le()
            self._v = 1 if a[0] else 0
            self._p.value(self._v)

        def __call__(self, *a):
            return self.value(*a)

        def on(self):
            self.value(1)

        def off(self):
            self.value(0)

        def toggle(self):
            self.value(1 - self._v)

        def mode(self, *a):
            if a:
                return self.init(a[0])
            return self._modo

        def pull(self, *a):
            if a:
                return self.init(self._modo, a[0])
            return self._pull

        def irq(self, handler=None, trigger=3, **k):
            if self._id not in E:
                return self._p.irq(handler, trigger, **k)
            self._irq = (handler, trigger, self._le())
            if self not in vigiados:
                vigiados.append(self)
            proximo()

        def __getattr__(self, n):
            return getattr(self._p, n)

        def __repr__(self):
            return "Pin(%d)" % self._id

    class ADC:
        def __init__(self, pin, *a, atten=3, **k):
            n = numero(pin)
            if n not in AD:
                raise ValueError("invalid pin")
            self._n, self._at, self._bits = n, atten, 12
            marca(3, n, 4)
            marca(5, n)

        def _volts(self):
            return min(max(no_roteiro(V.get(self._n, []), 0.0), 0.0), 3.3)

        def read_uv(self):
            return int(self._volts() * 1000000)

        def read_u16(self):
            return int(self._volts() / 3.3 * 65535 + 0.5)

        def read(self):
            return int(self._volts() / 3.3 * ((1 << self._bits) - 1) + 0.5)

        def atten(self, a):
            self._at = a

        def width(self, b):
            self._bits = b

        def init(self, *a, atten=None, **k):
            if atten is not None:
                self._at = atten

        def __repr__(self):
            return "ADC(Pin(%d), atten=%d) de faz de conta" % (self._n, self._at)

    RealPWM = machine.PWM

    class PWM:
        def __init__(self, dest, *a, **k):
            self._w, self._d, self._pino = RealPWM(real(dest), *a, **k), dict(k), numero(dest)

        def _pede(self, nome, a):
            if a:
                self._d[nome] = a[0]
                if nome == "duty_u16":
                    self._d.pop("duty", None)
                    self._d.pop("duty_ns", None)
                return getattr(self._w, nome)(a[0])
            if nome in self._d:
                return self._d[nome]
            if nome == "duty_u16" and "duty" in self._d:
                return self._d["duty"] * 65535 // 1023
            return getattr(self._w, nome)()

        def freq(self, *a):
            return self._pede("freq", a)

        def duty_u16(self, *a):
            return self._pede("duty_u16", a)

        def duty(self, *a):
            return self._pede("duty", a)

        def duty_ns(self, *a):
            return self._pede("duty_ns", a)

        def init(self, *a, **k):
            self._d.update(k)
            return self._w.init(*a, **k)

        def deinit(self):
            return self._w.deinit()

        def __repr__(self):
            return "PWM(Pin(%s), freq=%s, duty_u16=%s)" % (self._pino, self._d.get("freq", "?"),
                                                          self._d.get("duty_u16", "?"))

    def aceita_pin(nome):
        R = getattr(machine, nome, None)
        if R is None:
            return

        class Classe:
            def __new__(cls, *a, **k):
                return R(*[real(x) for x in a], **{c: real(v) for c, v in k.items()})
        for n in dir(R):
            if n[:1].isupper():
                setattr(Classe, n, getattr(R, n))
        setattr(machine, nome, Classe)

    class Signal:
        def __init__(self, pin, *a, invert=False, **k):
            if not hasattr(pin, "value"):
                pin = Pin(pin, *a, **k)
            elif a or k:
                pin.init(*a, **k)
            self._p, self._inv = pin, 1 if invert else 0

        def value(self, *a):
            if a:
                return self._p.value((1 if a[0] else 0) ^ self._inv)
            return self._p.value() ^ self._inv

        def __call__(self, *a):
            return self.value(*a)

        def on(self):
            self.value(1)

        def off(self):
            self.value(0)

    for n in dir(Real):   # constantes (IN, OUT, PULL_UP...) e o Pin.board
        if not n.startswith("_") and not hasattr(Pin, n):
            setattr(Pin, n, getattr(Real, n))
    for n in dir(machine.ADC):
        if n[:1].isupper():
            setattr(ADC, n, getattr(machine.ADC, n))
    for n in dir(RealPWM):
        if n[:1].isupper():
            setattr(PWM, n, getattr(RealPWM, n))
    for nome in ("I2C", "SoftI2C", "SPI", "SoftSPI", "UART"):
        aceita_pin(nome)
    for nome in ("bitstream", "time_pulse_us"):
        f = getattr(machine, nome, None)
        if f:
            setattr(machine, nome, (lambda f: lambda pin, *a: f(real(pin), *a))(f))
    machine.Pin, machine.ADC, machine.PWM, machine.Signal = Pin, ADC, PWM, Signal

    def sem_wifi():   # no QEMU o WLAN().active(True) trava (C3) ou derruba (ESP32) o chip: vira OSError
        import network, sys
        R = network.WLAN

        class WLAN:
            def __init__(self, *a, **k):
                pass

            def active(self, *a):
                if a and a[0]:
                    marca(6)
                    raise OSError("o QEMU não tem Wi-Fi (o rádio não é emulado)")
                return False

            def connect(self, *a, **k):
                marca(6)
                raise OSError("o QEMU não tem Wi-Fi (o rádio não é emulado)")

            def scan(self):
                return self.connect()

            def isconnected(self):
                return False

            def status(self, *a):
                return 0

            def disconnect(self):
                pass

            def ifconfig(self, *a):
                return ("0.0.0.0",) * 4

            def config(self, *a, **k):
                return None
        for n in dir(R):
            if n[:1].isupper():
                setattr(WLAN, n, getattr(R, n))

        class Rede:   # o módulo network é só leitura: entra um igual, com o WLAN trocado
            pass
        rede = Rede()
        for n in dir(network):
            if not n.startswith("__"):
                setattr(rede, n, getattr(network, n))
        rede.WLAN = WLAN
        sys.modules["network"] = rede

    def roda(nome, modulos=()):
        import gc, sys
        with open(nome) as f:
            codigo = compile(f.read(), nome, "exec")
        # carrega antes do t = 0 o que o programa importa: no ESP32 do QEMU cada acesso ao sistema de
        # arquivos leva ~100 ms (e 'import time' procura time.py antes do módulo embutido)
        for m in modulos:
            try:
                mod = __import__(m)
                if "." not in m:
                    sys.modules[m] = mod
            except Exception:
                pass   # o erro aparece de novo, na hora certa, dentro do programa
        if "network" in sys.modules:
            sem_wifi()
        gc.collect()
        T0[0] = time.ticks_ms()
        marca(1)
        try:
            exec(codigo, {"__name__": "__main__", "__file__": nome})
        except SystemExit:
            pass
        finally:
            marca(2)
    return roda
