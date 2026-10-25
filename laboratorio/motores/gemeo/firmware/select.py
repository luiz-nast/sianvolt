# select.py do gêmeo: o select.poll() e o select.select() do MicroPython, com a espera no relógio de placa.
# O texto que o roteiro manda pela serial chega no sys.stdin na hora de placa certa; esperar por ele (poll com
# tempo, ou sem) anda o relógio do gêmeo até o texto chegar ou o tempo acabar, como na placa. Só o sys.stdin
# (a serial) fica pronto pra ler; pra escrever (POLLOUT) tudo fica pronto na hora.
import sys
from _ponte import esperar_entrada
try:
    import uselect as _real   # MicroPython do PC: o select de verdade (pras constantes)
except ImportError:
    _real = None
if getattr(_real, "_GEMEO", False):   # CPython: 'uselect' cai neste mesmo arquivo
    _real = None
_GEMEO = True
POLLIN = getattr(_real, "POLLIN", 1)
POLLOUT = getattr(_real, "POLLOUT", 4)
POLLERR = getattr(_real, "POLLERR", 8)
POLLHUP = getattr(_real, "POLLHUP", 16)


def _serial(o):
    return o is sys.stdin or o is getattr(sys.stdin, "buffer", None) or o == 0


class _Poll:
    def __init__(self):
        self._objs = []   # [objeto, máscara]

    def register(self, obj, eventmask=POLLIN | POLLOUT):
        for item in self._objs:
            if item[0] is obj:
                item[1] = eventmask
                return
        self._objs.append([obj, eventmask])

    def modify(self, obj, eventmask):
        for item in self._objs:
            if item[0] is obj:
                item[1] = eventmask
                return
        raise OSError(2)   # ENOENT, como o MicroPython

    def unregister(self, obj):
        self._objs = [i for i in self._objs if i[0] is not obj]

    def _prontos(self):
        saida = []
        for obj, mascara in self._objs:
            ev = mascara & POLLOUT
            if mascara & POLLIN and _serial(obj) and esperar_entrada(0):
                ev |= POLLIN
            if ev:
                saida.append((obj, ev))
        return saida

    def poll(self, timeout=-1):
        prontos = self._prontos()
        if prontos or timeout == 0:
            return prontos
        quer_serial = any(m & POLLIN and _serial(o) for o, m in self._objs)
        if quer_serial:
            esperar_entrada(-1 if timeout is None or timeout < 0 else timeout)
        else:   # nada que possa chegar: só o tempo passa
            import time
            if timeout is None or timeout < 0:
                esperar_entrada(-1)   # na placa fica parado pra sempre
            else:
                time.sleep_ms(timeout)
        return self._prontos()

    def ipoll(self, timeout=-1, flags=0):
        return iter(self.poll(timeout))


def poll():
    return _Poll()


def select(rlist, wlist, xlist, timeout=None):
    p = _Poll()
    for o in rlist:
        p.register(o, POLLIN)
    for o in wlist:
        p.register(o, POLLOUT)
    ms = -1 if timeout is None else int(timeout * 1000)
    prontos = p.poll(ms)
    return ([o for o, e in prontos if e & POLLIN], [o for o, e in prontos if e & POLLOUT], [])
