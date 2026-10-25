"""simavr.py: o motor simavr. O Arduino Nano (ATmega328P) emulado instrução por instrução.

O .ino vira o mesmo .elf que vai pra placa (arduino-cli + core arduino:avr 1.8.8, no _arduino.py) e roda no
simavr (GPL-3, https://github.com/buserror/simavr, commit 5b08da6), em tempo virtual. O miolo é
motores/avr/simavr_nano.c: pinos, PWM lido dos timers, Serial em UTF-8 e as entradas do roteiro, um evento
JSON por linha. Fica compilado em .ferramentas/simavr/simavr_nano (libsimavr.a dentro, libelf do sistema
ou do Homebrew). Arquivos de cada rodada em build/nano/simavr/<exemplo>/: bin/ (.elf, .hex), compilacao.log e
simavr.log. Medido aqui: ~5,7x mais rápido que a placa, 3 MB de RAM, compilação com cache de 0,4 a 0,5 s.
"""
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from motores import _arduino
from nucleo import ferramentas as fer

NOME = "simavr"
DESCRICAO = "simavr (commit 5b08da6): o ATmega328P do Nano emulado instrução por instrução, com o .elf do arduino-cli"
FIEL = ("de verdade: o chip (CPU AVR, timers, PWM, UART, ADC, pull-up) rodando o mesmo .elf que vai pra placa, "
        "ciclo a ciclo a 16 MHz, com o int de 16 bits e os 2 KB de RAM; de mentira: a tensão nos pinos (só 0 ou 1), "
        "pino solto (lê 0 em vez de flutuar), o ADC (a tensão do roteiro vira o número exato) e o relógio "
        "(virtual: ~5,7x mais rápido que a placa)")
PLACAS = {"nano": "atmega328p"}
LINGUAGENS = {"arduino"}
RECURSOS = {"serial", "serial_entrada", "pino_saida", "pino_entrada", "pwm", "adc", "timer"}

FQBN = "arduino:avr:nano"
GIT = "https://github.com/buserror/simavr.git"
COMMIT = "5b08da60497f7564f50941f74a549fe2851db030"   # 2026-10-13, "Fix libelf detection in the 32 bit..."
FONTE = Path(__file__).resolve().parent / "avr" / "simavr_nano.c"


def _s(segundos):
    return ("%.1f" % segundos).replace(".", ",")


def _src(fe):
    return Path(fe) / "simavr-src"


def _binario(fe):
    return Path(fe) / "simavr" / "simavr_nano"


def _marca():
    """o que o binário tem que ter sido compilado de: o commit do simavr e o sha256 do simavr_nano.c"""
    return "%s %s\n" % (COMMIT, hashlib.sha256(FONTE.read_bytes()).hexdigest())


def _pronto(fe):
    b = _binario(fe)
    marca = b.with_name("simavr_nano.fonte")
    return os.access(b, os.X_OK) and marca.is_file() and marca.read_text() == _marca()


def _libsimavr(fe):
    return next(iter(sorted((_src(fe) / "simavr").glob("obj-*/libsimavr.a"))), None)


def _commit(src):
    r = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def _libelf():
    """-> (pkg-config, flags de compilação e de link da libelf, pasta da lib); PrecisaDe se faltar"""
    brew = fer.tem_brew()
    pc = shutil.which("pkg-config") or (str(Path(brew).parent / "pkg-config") if brew else None)
    r = subprocess.run([pc, "--cflags", "--libs", "libelf"], capture_output=True, text=True,
                       env=fer.ambiente()) if pc and os.access(pc, os.X_OK) else None
    if r is None or r.returncode:
        raise fer.PrecisaDe("a libelf, que o simavr usa pra ler o .elf (vem do Homebrew, no pacote elfutils, ~10 MB)",
                            "brew install elfutils")
    flags = shlex.split(r.stdout)
    # rpath no caminho que não muda quando o brew atualiza (Cellar/elfutils/0.197 -> opt/elfutils)
    libs = [re.sub(r"/Cellar/([^/]+)/[^/]+/", r"/opt/\1/", f[2:]) for f in flags if f.startswith("-L")]
    return pc, flags, libs


def faltando(fe):
    falta = _arduino.faltando(fe, ("avr",))
    if not _pronto(fe):
        if _libsimavr(fe) is None or _commit(_src(fe)) != COMMIT:
            falta.append("o simavr (fonte do GitHub, commit 5b08da6, ~36 MB; compila em segundos)")
        falta.append("o simavr_nano (motores/avr/simavr_nano.c, compila em 1 s)")
        try:
            _libelf()   # sem ela o simavr não compila
        except fer.PrecisaDe as e:
            falta.append("%s: %s" % (e.oque, e.comando))
    return falta


def ocupa(fe):
    return sum(fer.du(p) for p in (_src(fe), _binario(fe).parent) if p.exists())


def _rodar(cmd, nome, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, errors="replace", **kw)
    if r.returncode:
        raise RuntimeError("%s falhou (código %d): %s" % (nome, r.returncode, (r.stdout + r.stderr).strip()[-800:]))
    return r


def instalar(fe, diga=print):
    fe = Path(fe)
    _arduino.instalar(fe, diga, ("avr",))
    if _pronto(fe):
        diga("simavr: já tem (arduino-cli, core arduino:avr %s e %s)" % (_arduino.CORES["avr"][1], _binario(fe)))
        return
    inicio, src = time.monotonic(), _src(fe)
    pc, flags, libdirs = _libelf()   # antes de baixar: sem libelf não adianta
    if _commit(src) != COMMIT:
        if not (src / ".git").is_dir():
            diga("  baixando o simavr do GitHub (commit %s)" % COMMIT[:7])
            src.mkdir(parents=True, exist_ok=True)
            _rodar(["git", "init", "-q", str(src)], "git init")
            _rodar(["git", "-C", str(src), "remote", "add", "origin", GIT], "git remote")
        _rodar(["git", "-C", str(src), "fetch", "-q", "--depth", "1", "origin", COMMIT], "git fetch",
               env=fer.ambiente(), timeout=600)
        _rodar(["git", "-C", str(src), "checkout", "-q", "--detach", COMMIT], "git checkout")
    fer.esperar_memoria(400, diga=diga)
    t = time.monotonic()
    # o Makefile do simavr acha a libelf pelo pkg-config: o do Homebrew vai na frente do PATH
    env = fer.ambiente(PATH=os.path.dirname(pc) + os.pathsep + os.environ.get("PATH", ""))
    _rodar(["make", "-C", str(src / "simavr"), "-j2"], "make do simavr", env=env, timeout=1200)
    lib = _libsimavr(fe)
    diga("  simavr compilado com make -j2 em %s s" % _s(time.monotonic() - t))
    b = _binario(fe)
    b.parent.mkdir(parents=True, exist_ok=True)
    s = src / "simavr"
    _rodar(["gcc", "-O2", "-Wall", "-Wno-format-overflow", "-o", str(b), str(FONTE), "-I" + str(s / "sim"),
            "-I" + str(s), str(lib)] + flags + ["-lm"] + ["-Wl,-rpath," + d for d in libdirs],
           "gcc do simavr_nano", env=fer.ambiente())
    b.with_name("simavr_nano.fonte").write_text(_marca())
    diga("  simavr_nano pronto em %s (total %s s, %s em .ferramentas)" % (
        b, _s(time.monotonic() - inicio), fer.tamanho(ocupa(fe))))


def rodar(pedido):
    fe = Path(pedido.ferramentas)
    falta = faltando(fe)
    if falta:
        raise fer.PrecisaDe("; ".join(falta), "python3 laboratorio/lab.py instalar simavr")
    yield from _arduino.rodar_compilado(pedido, NOME, FQBN, lambda elf: [str(_binario(fe)), str(elf)], ".elf",
                                        adc_ok=lambda p: p.startswith("A"))
