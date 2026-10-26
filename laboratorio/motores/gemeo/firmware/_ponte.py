# _ponte.py: o cano entre o firmware e o motor do gêmeo.
# Escrito pra rodar igual no CPython e no MicroPython (sem f-string, sem typing, sem **dict).
# No CPython o gêmeo troca _canal por uma chamada direta ao motor; no MicroPython vai por dois canos (fds).
import sys
try:
    import json
except ImportError:
    import ujson as json


class FimDaSimulacao(BaseException):
    pass


_print = print   # o print de verdade (o _rodar.py troca o builtins.print pelo print_gemeo)
_canal = None
_bloquear = None
_cano = [None, None]
_cbs = {}
_prox = [0]
_em_cb = [False]
_fins = [0]
_ERROS = {"ValueError": ValueError, "TypeError": TypeError, "RuntimeError": RuntimeError,
          "NotImplementedError": NotImplementedError}


def inteiro(x):
    """o número inteiro que o MicroPython do chip pede (mp_obj_get_int, py/obj.c): int e bool passam; float, texto e
    None dão TypeError ("can't convert float to int"), como na placa; um int que não cabe nos 32 bits das ESP dá
    OverflowError. Pra sleep_ms, sleep_us, ticks_add e o PWM aceitarem só o que a placa aceita"""
    if x is True or x is False:   # no MicroPython o bool não é int pro isinstance, mas o chip aceita
        return 1 if x else 0
    if not isinstance(x, int):
        para_int = None if isinstance(x, float) else getattr(type(x), "__int__", None)
        if para_int is None:
            raise TypeError("can't convert %s to int" % type(x).__name__)
        x = para_int(x)
    if not -0x80000000 <= x <= 0x7FFFFFFF:
        raise OverflowError("overflow converting long int to machine word")
    return int(x)


def flutuante(x):
    """o número de ponto flutuante que o MicroPython do chip pede (mp_obj_get_float): int, bool e float passam; o
    resto dá TypeError ("can't convert str to float"). Pra time.sleep"""
    if x is True or x is False or isinstance(x, (int, float)):
        return x
    raise TypeError("can't convert %s to float" % type(x).__name__)


def _pelo_cano(nome, args):
    if _cano[0] is None:
        import os
        fds = os.getenv("GEMEO_FDS").split(",")
        _cano[0] = open("/dev/fd/" + fds[0], "r")
        _cano[1] = open("/dev/fd/" + fds[1], "w")
    _cano[1].write(json.dumps([nome, args]) + "\n")
    try:
        _cano[1].flush()
    except (AttributeError, OSError):   # no MicroPython o flush de um cano dá EINVAL (fsync); a escrita já foi
        pass
    return json.loads(_cano[0].readline())


def rpc(nome, *args):
    r = (_canal or _pelo_cano)(nome, list(args))
    if r[0] == "ok":
        if r[2] and not _em_cb[0]:
            atender()
        return r[1]
    if r[0] == "fim":
        _fins[0] += 1
        if _fins[0] > 50 and _bloquear is not None:   # um "except:" pelado engole o fim: no CPython o gêmeo
            _bloquear()                                # para esta thread aqui (no MicroPython, mata o processo)
        raise FimDaSimulacao(r[1])
    tipo, msg = r[1]
    if tipo == "OSError":
        raise OSError(msg)
    raise _ERROS.get(tipo, RuntimeError)(msg)


def registrar(func, obj):
    _prox[0] += 1
    _cbs[_prox[0]] = [func, obj]
    return _prox[0]


def _rodar_cb(cb):
    func, obj = _cbs[cb[0]]
    _em_cb[0] = True
    try:
        func(obj)
    except Exception as e:   # no ESP32 o erro dentro do callback só aparece na serial; o programa segue
        rpc("erro_cb", _texto_erro(e))
    finally:
        _em_cb[0] = False
        rpc("cb_fim")


def _texto_erro(e):
    """o traceback com número de linha, como a placa mostra"""
    try:
        import io
        s = io.StringIO()
        sys.print_exception(e, s)
        return s.getvalue()
    except Exception:
        return "%s: %s\n" % (type(e).__name__, e)


def atender():
    while True:
        cb = rpc("dormir", -1)
        if cb is None:
            return
        _rodar_cb(cb)


def dormir_ate(alvo):
    while True:
        cb = rpc("dormir", alvo)
        if cb is None:
            return
        _rodar_cb(cb)


_poll = [None]


def entrada_pronta():
    """tem texto da serial esperando pra ser lido?"""
    if _canal is not None:   # CPython: o texto mora no gêmeo
        return rpc("entrada_pronta")
    if _poll[0] is None:     # MicroPython do PC: o sys.stdin é um cano de verdade que o gêmeo enche
        import uselect
        _poll[0] = uselect.poll()
        _poll[0].register(sys.stdin, uselect.POLLIN)
    return bool(_poll[0].poll(0))


def esperar_entrada(timeout_ms):
    """espera texto na serial até timeout_ms de placa (-1 = sem limite), andando o relógio do gêmeo; True se chegou"""
    if entrada_pronta():
        return True
    if timeout_ms == 0:
        return False
    alvo = -1 if timeout_ms < 0 else rpc("agora_us", 0) + int(timeout_ms) * 1000
    while True:
        cb, no_alvo = rpc("espera_entrada", alvo)
        if cb is not None:
            _rodar_cb(cb)
        if entrada_pronta():
            return True
        if no_alvo:
            return False


def programa_acabou():
    rpc("programa_acabou")
    dormir_ate(1 << 62)


def print_gemeo(*args, **kw):
    arq = kw.get("file")
    if arq is not None and arq is not sys.stdout:
        return _print(*args, **kw)
    sep, fim = kw.get("sep", " "), kw.get("end", "\n")
    rpc("print", (" " if sep is None else sep).join([str(a) for a in args]) + ("\n" if fim is None else fim))
