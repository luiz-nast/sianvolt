"""rp2040js.py: o motor rp2040js. O Raspberry Pi Pico (RP2040) no rp2040js (Wokwi, MIT,
https://github.com/wokwi/rp2040js), rodado pelo node. A placa é a reserva fora do top 5.

MicroPython: o firmware oficial RPI_PICO 1.29.0 (.uf2 do micropython.org) roda no chip emulado; o programa vai
pelo REPL bruto, como no mpremote: carga.py monta um disco na RAM com os arquivos da pasta (a flash não é
emulada) e rodar.py compila o main.py, marca o começo no SCRATCH3 do watchdog (t = 0) e roda.
Arduino: o .ino compilado pelo arduino-cli com o core arduino-pico 6.3.1 (rp2040:rp2040, 1,5 GB, só em
'instalar rp2040js'); t = 0 é o PC chegando no setup(). A Serial é a USB.
O miolo é motores/js/emular.mjs (o mesmo do avr8js), com duas correções que o rp2040js não faz sozinho:
pull-up/pull-down nas entradas e ler de volta o nível de um pino de saída.
O bootrom do RP2040 vem de motores/js/bootrom_b1.mjs ou, se ele não estiver no repositório, de
.ferramentas/js/bootrom_b1.mjs, copiado do rp2040js (GitHub, tag v1.4.1) pelo 'instalar rp2040js'.
Medido aqui (~100 MB de RAM, o node): Arduino com delay() ~10x mais rápido que a placa, loop() sem delay 0,44x;
MicroPython 0,34x a 0,38x, dormindo ou não (o MicroPython emulado gasta CPU no memcpy44 do bootrom mesmo parado,
provavelmente com a USB). O disco na RAM aguenta até 36 KB de programa e tira essa memória do programa (a placa usa a flash).
"""
import re
import shutil
import subprocess
import time
from pathlib import Path

from motores import _arduino
from nucleo import contrato
from nucleo import ferramentas as fer

NOME = "rp2040js"
DESCRICAO = "rp2040js 1.4.1 (Wokwi) no node: o RP2040 do Pico com o MicroPython 1.29 oficial ou o core arduino-pico"
FIEL = ("de verdade: as 2 CPUs Cortex-M0+, timers, PWM, UART, USB e ADC do RP2040 rodando o firmware oficial do "
        "MicroPython (ou o .uf2 do arduino-pico); de mentira: a flash (o sistema de arquivos vira um disco na RAM; "
        "abrir arquivo da flash dá ENODEV), o pull-up e o eco dos pinos de saída (o motor aplica), o ADC (a tensão "
        "do roteiro vira o número exato), o tempo de CPU (não é fiel; o MicroPython roda a ~0,36x da placa) e o Pico W "
        "(sem Wi-Fi)")
PLACAS = {"pico": "rp2040"}
LINGUAGENS = {"micropython", "arduino"}
RECURSOS = {"serial", "serial_entrada", "pino_saida", "pino_entrada", "pwm", "adc", "timer"}

FQBN = "rp2040:rp2040:rpipico"
AQUI = Path(__file__).resolve().parent / "js"
EMULAR, BOOTROM = AQUI / "emular.mjs", AQUI / "bootrom_b1.mjs"
UF2 = "RPI_PICO-20260824-v1.29.0.uf2"   # https://micropython.org/download/RPI_PICO/
UF2_URL = "https://micropython.org/resources/firmware/" + UF2
UF2_SHA = "e1160e602e277d85920adb5fe741435edccba9ba6ecadc85fdab75252eeff4e9"
FONTE_GIT, FONTE_TAG = "https://github.com/wokwi/rp2040js.git", "v1.4.1"
ADC = {"GP26", "GP27", "GP28", "GP29"}
ARDUINO_FONTE = (".ino", ".h", ".c", ".cpp", ".hpp", ".S")
MAX_ARQUIVOS = 36 * 1024   # medido: 32 KB de programa rodam (sobram 94 KB de heap); 48 KB dão MemoryError
FOLGA_BLOCOS = 32          # 16 KB livres no disco pro programa escrever arquivos


def _uf2(fe):
    return Path(fe) / "micropython" / UF2


def bootrom(fe):
    """o bootrom do repositório, ou o copiado do rp2040js em .ferramentas/js; None se não tiver"""
    return next((b for b in (BOOTROM, Path(fe) / "js" / "bootrom_b1.mjs") if b.is_file()), None)


def faltando(fe):
    falta = _arduino.faltando_js(fe, NOME) + _arduino.faltando(fe, ("rp2040",))   # o core é pro Arduino no Pico
    if not _uf2(fe).is_file():
        falta.append("o MicroPython %s do micropython.org (0,7 MB)" % UF2)
    if bootrom(fe) is None:
        falta.append("o bootrom do RP2040 (do rp2040js no GitHub, tag %s, 1,5 MB)" % FONTE_TAG)
    return falta


def ocupa(fe):
    return sum(fer.du(p) for p in (_arduino.modulos(fe) / NOME, _uf2(fe)) if p.exists())


def instalar(fe, diga=print):
    fe = Path(fe)
    _arduino.instalar_js(fe, NOME, diga)   # primeiro o node: sem ele o resto não serve
    fer.baixar(UF2_URL, UF2_SHA, _uf2(fe), diga)
    if bootrom(fe) is None:
        instalar_bootrom(fe, diga)
    _arduino.instalar(fe, diga, ("rp2040",))   # o core arduino-pico (1,5 GB), só pra Arduino no Pico
    diga("rp2040js: já tem (node, rp2040js %s, %s, core rp2040:rp2040 %s)" % (
        _arduino.versao_js(fe, NOME), UF2, _arduino.CORES["rp2040"][1]))


def instalar_bootrom(fe, diga=print):
    """sem motores/js/bootrom_b1.mjs no repositório: copia o demo/bootrom.ts do rp2040js (GitHub, tag fixa)"""
    src = Path(fe) / "rp2040js-src"
    if not (src / "demo" / "bootrom.ts").is_file():
        diga("  baixando o rp2040js %s do GitHub (só pelo bootrom)" % FONTE_TAG)
        r = subprocess.run(["git", "-c", "advice.detachedHead=false", "clone", "-q", "--depth", "1", "--branch",
                            FONTE_TAG, FONTE_GIT, str(src)], capture_output=True, text=True, env=fer.ambiente(),
                           stdin=subprocess.DEVNULL, timeout=600)
        if r.returncode:
            raise RuntimeError("git clone do rp2040js falhou: %s" % r.stderr.strip()[-400:])
    destino = Path(fe) / "js" / "bootrom_b1.mjs"   # o .ts é JavaScript puro: um Uint32Array exportado
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src / "demo" / "bootrom.ts", destino)
    diga("  bootrom do RP2040 em %s (licença: ver o cabeçalho de motores/js/bootrom_b1.mjs)" % destino)


def carga(pasta):
    """o script que monta um disco na RAM (LittleFS) em /ram com os arquivos do programa -> (texto, avisos)"""
    arquivos, avisos, total = {}, [], 0
    for a in sorted(Path(pasta).rglob("*")):
        if not a.is_file() or a.suffix in ARDUINO_FONTE:
            continue
        nome = a.relative_to(pasta).as_posix()
        if total + a.stat().st_size > MAX_ARQUIVOS:
            avisos.append(contrato.aviso(0, "%s (%d KB) ficou de fora: o disco na RAM do motor rp2040js aguenta "
                                         "até %d KB de programa" % (nome, a.stat().st_size // 1024,
                                                                    MAX_ARQUIVOS // 1024), NOME))
            continue
        arquivos[nome] = a.read_bytes()
        total += a.stat().st_size
    # LittleFS com blocos de 512 bytes: 2 pro superbloco, 2 pra raiz, cada arquivo os dele mais 2, e a folga
    blocos = 4 + FOLGA_BLOCOS + sum(len(d) // 480 + 3 for d in arquivos.values())
    if total > 8 * 1024:
        avisos.append(contrato.aviso(0, "os %d KB do programa foram num disco na RAM (a flash do Pico não é emulada): "
                                     "aqui o programa tem uns %d KB de memória a menos que na placa"
                                     % (total // 1024, blocos // 2), NOME))
    linhas = [
        "import os, sys",
        "try:\n import vfs\nexcept ImportError:\n vfs = os",
        "class _RAM:",
        " def __init__(s, n): s.d = bytearray(n * 512)",
        " def readblocks(s, b, buf, o=0):\n  a = b * 512 + (o or 0)\n  buf[:] = s.d[a:a + len(buf)]",
        " def writeblocks(s, b, buf, o=0):\n  a = b * 512 + (o or 0)\n  s.d[a:a + len(buf)] = buf",
        " def ioctl(s, op, arg):\n  return len(s.d) // 512 if op == 4 else 512 if op == 5 else 0",
        "_d = _RAM(%d)" % blocos,
        "vfs.VfsLfs2.mkfs(_d)",
        "vfs.mount(_d, '/ram')",
        "os.chdir('/ram')",
        "for _n, _b in %r:" % sorted(arquivos.items()),
        " _p = ''",
        " for _x in _n.split('/')[:-1]:\n  _p += _x\n  try:\n   os.mkdir(_p)\n  except OSError:\n   pass\n  _p += '/'",
        " with open(_n, 'wb') as _f:\n  _f.write(_b)",
        "del _n, _b, _f, _p",
    ]
    return "\n".join(linhas) + "\n", avisos


# rodar.py: compila o main.py, marca o começo (SCRATCH3 do watchdog = 0x5AB0_0001) e roda; marca o fim (…0002)
RODAR = """import machine, gc
gc.collect()
_c = compile(open('main.py').read(), 'main.py', 'exec')
gc.collect()
machine.mem32[0x40058018] = 0x5AB00001
try:
    exec(_c, {'__name__': '__main__'})
except SystemExit:   # sys.exit() no main.py: na placa o programa para e cai no REPL
    pass
finally:
    machine.mem32[0x40058018] = 0x5AB00002
"""


def _traduz(e, porta):
    ev = _arduino.converter(e, porta)
    if ev and ev["tipo"] == "erro":   # o traceback sem a linha do rodar.py (que o Luiz não escreveu)
        ev["texto"] = "\n".join(x for x in ev["texto"].splitlines() if '"<stdin>"' not in x)
    return ev


def _fontes(pasta):
    return "\n".join(a.read_text(encoding="utf-8", errors="replace") for a in sorted(Path(pasta).rglob("*"))
                     if a.is_file() and a.suffix in ARDUINO_FONTE)


def _traduz_arduino(pasta):
    """o aviso da porta USB só serve pra quem não espera ela abrir (while (!Serial) ...)"""
    espera = re.search(r"while\s*\(\s*!\s*Serial\b", _fontes(pasta)) is not None

    def traduz(e, porta):
        ev = _arduino.converter(e, porta)
        return None if espera and ev and ev.get("codigo") == "usb" else ev
    return traduz


def rodar(pedido):
    fe = Path(pedido.ferramentas)
    falta = faltando(fe)
    if falta:
        raise fer.PrecisaDe("; ".join(falta), "python3 laboratorio/lab.py instalar rp2040js")
    base = [_arduino.node(), str(EMULAR), "pico"]
    resto = ["--modulos", str(_arduino.modulos(fe)), "--bootrom", str(bootrom(fe))]
    if pedido.linguagem == "arduino":
        if not _arduino.tem_core(fe, "rp2040"):
            raise fer.PrecisaDe("o core rp2040:rp2040 %s (arduino-pico, 1,5 GB)" % _arduino.CORES["rp2040"][1],
                                "python3 laboratorio/lab.py instalar rp2040js")
        if re.search(r"#\s*include\s*[<\"]WiFi\.h", _fontes(pedido.pasta)):
            yield contrato.aviso(0, "o programa usa WiFi.h, mas o Pico (sem W) não tem rádio: compila, e na placa o "
                                    "WiFi.begin() fica esperando pra sempre. Wi-Fi é com o Pico W, que o laboratório "
                                    "não emula, ou com uma ESP", "sem_wifi")
        yield from _arduino.rodar_compilado(pedido, NOME, FQBN, lambda uf2: base + [str(uf2)] + resto, ".uf2",
                                            adc_ok=lambda p: p in ADC, porta="usb",
                                            traduz=_traduz_arduino(pedido.pasta))
        return
    inicio = time.monotonic()
    texto, avisos = carga(pedido.pasta)
    trabalho = Path(pedido.trabalho)
    (trabalho / "carga.py").write_text(texto, encoding="utf-8")
    (trabalho / "rodar.py").write_text(RODAR, encoding="utf-8")
    yield from avisos
    args, avisos = _arduino.argumentos(pedido.entradas, lambda p: p in ADC)
    yield from avisos
    cmd = base + [str(_uf2(fe))] + resto + ["--ms", "%.3f" % pedido.tempo_ms, "--py", str(trabalho / "carga.py"),
                                            str(trabalho / "rodar.py")] + args
    yield from _arduino.emular(pedido, NOME, cmd, inicio, "usb", _traduz)
