"""rodar.py: os dois jeitos de rodar o firmware no gêmeo (veio do protótipo ~/.cache/sianvolt/lab/gemeo/motor/rodar.py).

- micropython(): o firmware roda no MicroPython de verdade (port unix 1.29.0, em .ferramentas/micropython-unix),
             com os machine.py/time.py/network.py de firmware/; cada chamada vai por um cano até o núcleo.
             Fiel na linguagem (sintaxe, int, bibliotecas). Um processo filho por rodada, sempre desligado no fim.
- cpython(): o firmware roda dentro deste Python, numa thread, com os mesmos stubs (chamada direta).
             Sem nada pra instalar; a linguagem é a do CPython (aceita coisa que o MicroPython não aceita).
Nos dois: um laço que fica SILENCIO_S de PC sem chamar o gêmeo (while True: pass) vira 'travou', um
'except:' pelado que engole o fim da simulação não prende o gêmeo, e o texto que o roteiro manda pela serial
chega no sys.stdin na hora de placa (no MicroPython, por um cano de verdade no stdin dele).
"""
import builtins
import codecs
import ctypes
import json
import os
import platform
import select
import subprocess
import sys
import threading
import time
import traceback
import types
from pathlib import Path

FIRMWARE = Path(__file__).resolve().parent.parent / "firmware"
BLOQUEADOS = FIRMWARE / "bloqueados"
STUBS = {"machine", "time", "network", "_ponte", "select"}
ALIAS = {"utime": "time", "umachine": "machine", "unetwork": "network", "usys": "sys", "uselect": "select"}
SEM_GEMEO = {p.stem for p in BLOQUEADOS.glob("*.py")}
ENGOLIU = "o firmware engoliu o fim da simulação com um 'except:' pelado; o gêmeo %s"
# o firmware que fica esse tanto de PC sem chamar o gêmeo (pino, relógio, sleep, serial) travou: no PC o
# MicroPython roda umas 30x mais rápido que no chip, então na placa ele ficaria aí bem mais que o --tempo
SILENCIO_S = 3.0
# parado num read() do stdin há esse tanto de PC: está esperando texto da serial
LENDO_S = 0.05
READ = {"x86_64": "0", "amd64": "0", "aarch64": "63", "arm64": "63"}.get(platform.machine().lower())


class Travou(BaseException):
    pass


def _s(x):
    return ("%.1f" % x).replace(".", ",")


def _travou(nucleo, parado_s, limite=False):
    if limite:
        nucleo.acabou = ("travou: passou do limite de %s s de PC" % _s(parado_s), "travou")
        nucleo.aviso("travou: o programa passou do limite de %s s de PC sem chegar no fim do tempo de placa"
                     % _s(parado_s), "travou")
        return
    nucleo.acabou = ("travou: %s s de PC sem chamar o gêmeo em %s de placa" % (_s(parado_s), fmt_t(nucleo.t)),
                     "travou")
    nucleo.aviso("travou: o programa ficou %s s de PC sem chamar sleep, pino, relógio nem serial (um laço só de "
                 "conta, como while True: pass?); na placa ele ficaria preso aí. Só os motores de relógio virtual "
                 "(gemeo, nativo) percebem isso: no qemu o mesmo programa roda até o fim do tempo" % _s(parado_s),
                 "travou")


def fmt_t(us):
    return ("%.3f s" % (us / 1e6)).replace(".", ",")


def _lendo_stdin(pid):
    """o processo está parado num read() do fd 0 (sys.stdin.read/readline, input)?"""
    try:
        campos = Path("/proc/%d/syscall" % pid).read_text().split()
    except OSError:
        return False
    return READ is not None and len(campos) > 1 and campos[0] == READ and campos[1] == "0x0"


class _Saida:
    """sys.stdout do firmware no CPython: o que ele escreve sai pela serial do gêmeo"""

    def __init__(self, mods):
        self.mods = mods

    def write(self, s):
        self.mods["_ponte"].rpc("print", str(s))
        return len(s)

    def flush(self):
        pass


class _Entrada:
    """sys.stdin do firmware no CPython: o texto que o roteiro manda pela serial, na hora de placa"""

    def __init__(self, mods):
        self.mods = mods

    def _le(self, n, ate_linha):
        ponte, saida = self.mods["_ponte"], ""
        while n < 0 or len(saida) < n:
            ponte.esperar_entrada(-1)   # anda o relógio até chegar texto (ou a simulação acabar)
            saida += ponte.rpc("le_entrada", n - len(saida) if n >= 0 else -1, ate_linha)
            if ate_linha and saida.endswith("\n") or n < 0 and not ate_linha:
                break
        return saida

    def read(self, n=-1):
        return self._le(n, False)

    def readline(self):
        return self._le(-1, True)

    def fileno(self):
        return 0

    def input(self, prompt=""):
        if prompt:
            self.mods["_ponte"].rpc("print", str(prompt))
        linha = self.readline()
        self.mods["_ponte"].rpc("print", linha.rstrip("\r\n") + "\n")   # o input() da placa ecoa o que chega
        return linha.rstrip("\r\n")


def cpython(prog, nucleo, limite_real_s):
    prog = Path(prog).resolve()
    mods = {}

    def carregar(nome, caminho, rotulo=None):
        m = types.ModuleType(nome)
        m.__file__ = str(caminho)
        m.__dict__["__builtins__"] = bi
        mods[nome] = m
        exec(compile(caminho.read_text(encoding="utf-8"), rotulo or str(caminho), "exec"), m.__dict__)
        if nome == "_ponte":
            m._canal = nucleo.comando
        return m

    def importar(nome, globais=None, locais=None, fromlist=(), nivel=0):
        raiz = ALIAS.get(nome.split(".")[0], nome.split(".")[0])
        if raiz in mods:
            return mods[raiz]
        if raiz in STUBS:
            return carregar(raiz, FIRMWARE / (raiz + ".py"))
        if raiz == "micropython":
            return carregar(raiz, FIRMWARE / "cpython" / "micropython.py")
        if raiz == "sys":
            return falso_sys
        local = prog.parent / (raiz + ".py")
        if nivel == 0 and local.exists():   # módulo do Luiz, da pasta do programa
            return carregar(raiz, local, local.name)
        if raiz in SEM_GEMEO:
            raise ImportError("no module named '%s' (o gêmeo ainda não simula isso)" % nome)
        return builtins.__import__(nome, globais, locais, fromlist, nivel)

    # o sys que o firmware vê: platform 'esp32' e stdout/stderr na serial do gêmeo
    falso_sys = types.ModuleType("sys")
    falso_sys.__dict__.update({k: getattr(sys, k) for k in ("argv", "maxsize", "byteorder", "modules", "path",
                                                              "version", "version_info", "implementation", "exit")})
    falso_sys.platform, falso_sys.stdin = "esp32", _Entrada(mods)
    falso_sys.stdout = falso_sys.stderr = _Saida(mods)
    falso_sys.print_exception = lambda e, f=None: (f or falso_sys.stdout).write("".join(traceback.format_exception(e)))
    bi = dict(builtins.__dict__)
    bi["__import__"] = importar
    ponte = importar("_ponte")
    bi["print"], bi["input"] = ponte.print_gemeo, falso_sys.stdin.input

    # o firmware roda numa thread; esta espera no máximo limite_real_s
    pronto = threading.Event()
    ponte._bloquear = lambda: (pronto.set(), threading.Event().wait())
    g = {"__name__": "__main__", "__file__": prog.name, "__builtins__": bi}

    def firmware():
        try:
            exec(compile(prog.read_text(encoding="utf-8"), prog.name, "exec"), g)
            ponte.programa_acabou()
        except (ponte.FimDaSimulacao, Travou):
            pass
        except SystemExit:
            nucleo.comando("saiu", [])
        except Exception as e:
            # só os quadros do firmware do Luiz (tira o gêmeo do meio), no formato do traceback do Python
            quadros = [q for q in traceback.extract_tb(e.__traceback__)
                       if "/gemeo/firmware/" not in q.filename and "/gemeo/motor/" not in q.filename]
            txt = "Traceback (most recent call last):\n" + "".join(traceback.format_list(quadros))
            nucleo.comando("erro", [txt + "".join(traceback.format_exception_only(type(e), e))])
        finally:
            pronto.set()

    th = threading.Thread(target=firmware, daemon=True, name="firmware")
    th.start()
    fim_pc, parou = time.monotonic() + limite_real_s, None
    while not pronto.wait(0.1):
        agora = time.monotonic()
        if agora - nucleo.ultimo_pc > SILENCIO_S or agora > fim_pc:
            parou = (agora - nucleo.ultimo_pc, agora > fim_pc)
            break
    if parou:
        _travou(nucleo, limite_real_s if parou[1] else parou[0], parou[1])
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(th.ident), ctypes.py_object(Travou))
        th.join(0.5)
        if th.is_alive():
            nucleo.aviso("o firmware não parou (um 'except:' pelado num laço sem sleep): a thread fica parada até "
                         "o lab.py sair", "travou")
    elif nucleo.depois_do_fim >= 50:
        nucleo.aviso(ENGOLIU % "largou ele parado", "except")
    return {"modo": "cpython", "ram_mb": None}


def _ram(pid):
    try:
        for linha in Path("/proc/%d/status" % pid).read_text().splitlines():
            if linha.startswith("VmHWM:"):
                return round(int(linha.split()[1]) / 1024, 1)
    except (OSError, ValueError):
        pass
    return None


# o que os stubs do gêmeo (machine.py, time.py, _ponte, json...) ocupam do heap: medido 22,7 KB no começo do
# programa; o heapsize é o heap livre da placa mais isto, e o gc.mem_free() do programa sai perto do da placa
HEAP_STUBS = 24 * 1024


def micropython(prog, nucleo, binario, limite_real_s, ambiente, heap=None):
    prog = Path(prog).resolve()
    r1, w1 = os.pipe()   # núcleo -> micropython
    r2, w2 = os.pipe()   # micropython -> núcleo
    env = dict(ambiente, GEMEO_FDS="%d,%d" % (r1, w2),
               MICROPYPATH=":".join([str(FIRMWARE), str(prog.parent), str(BLOQUEADOS), ".frozen"]))
    heapsize = ["-X", "heapsize=%d" % (heap + HEAP_STUBS)] if heap else []
    p = subprocess.Popen([str(binario)] + heapsize + [str(FIRMWARE / "_rodar.py"), str(prog.parent), prog.name],
                         pass_fds=(r1, w2),
                         env=env, cwd=str(prog.parent), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    os.close(r1)
    os.close(w2)
    entrada = p.stdin.fileno()   # a serial da placa: o roteiro escreve aqui na hora de placa
    os.set_blocking(entrada, False)

    def manda(texto):
        try:
            os.write(entrada, texto.encode("utf-8"))
        except BlockingIOError:   # 64 KB sem ninguém ler: na placa o buffer da serial também perde
            nucleo.aviso("a serial da placa encheu (o programa não lê o que chega): o resto do texto se perdeu",
                         "serial_entrada")
        except OSError:
            pass
    nucleo.entrada = manda
    saida = codecs.getincrementaldecoder("utf-8")("replace")
    buf, fim_pc, ram, direto = b"", time.monotonic() + limite_real_s, None, ""
    fds = [r2, p.stdout.fileno()]
    try:
        while True:
            while b"\n" not in buf and r2 in fds:
                agora = time.monotonic()
                if agora > fim_pc:
                    _travou(nucleo, limite_real_s, True)
                    raise Travou()
                parado = agora - nucleo.ultimo_pc
                prontos, _, _ = select.select(fds, [], [], min(0.05, max(0.0, fim_pc - agora)))
                if not prontos:
                    if parado > LENDO_S and _lendo_stdin(p.pid):   # parado num read() da serial
                        if not nucleo.esperando_na_leitura():
                            raise Travou()   # o roteiro não manda mais nada: acabou o tempo esperando
                        nucleo.ultimo_pc = time.monotonic()
                    elif parado > SILENCIO_S:
                        _travou(nucleo, parado)
                        raise Travou()
                    continue
                for fd in prontos:
                    pedaco = os.read(fd, 65536)
                    if fd == r2:
                        if not pedaco:
                            fds.remove(r2)
                        buf += pedaco
                    elif pedaco:   # o firmware escreveu direto no stdout (sys.stdout.write): na placa é a serial
                        nucleo.ultimo_pc = time.monotonic()
                        texto = saida.decode(pedaco)
                        direto += texto
                        nucleo.escreve_serial(texto)
                    else:
                        fds.remove(fd)
            if b"\n" not in buf:
                break
            linha, buf = buf.split(b"\n", 1)
            nome, args = json.loads(linha)
            resp = nucleo.comando(nome, args)
            if nucleo.comandos % 200 == 0 or nucleo.acabou:
                ram = max(ram or 0, _ram(p.pid) or 0) or ram
            if nucleo.depois_do_fim > 50:   # um except: pelado está engolindo o fim: desliga o micropython
                nucleo.aviso(ENGOLIU % "desligou o micropython", "except")
                break
            try:
                os.write(w1, (json.dumps(resp) + "\n").encode())
            except BrokenPipeError:   # o micropython saiu (erro fora do firmware): a saída dele explica
                break
    except Travou:
        pass   # nucleo.acabou já diz o porquê
    finally:
        ram = max(ram or 0, _ram(p.pid) or 0) or ram
        if p.poll() is None:
            p.kill()
        os.close(r2)
        os.close(w1)
        try:
            p.stdin.close()
        except OSError:
            pass
        resto = p.stdout.read()   # depois do kill o cano fecha: lê o que sobrou
        p.stdout.close()
        p.wait()
    if resto:
        texto = saida.decode(resto, final=True)
        direto += texto
        nucleo.escreve_serial(texto)
    if not nucleo.acabou:
        nucleo.acabou = ("o micropython saiu sem avisar o gêmeo (código %s)" % p.returncode, "travou")
        nucleo.ev("erro", texto="o MicroPython do PC saiu sem avisar o gêmeo (código %s)%s" % (
            p.returncode, ":\n" + direto.strip()[-2000:] if direto.strip() else ""))
    return {"modo": "micropython", "ram_mb": ram, "retorno": p.returncode}
