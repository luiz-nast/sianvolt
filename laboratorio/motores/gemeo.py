"""gemeo.py: o motor gêmeo digital. Roda o main.py (MicroPython) no PC, com um chip de mentira que segue as
regras do datasheet (pinos, boot, ADC1/ADC2), relógio virtual e, com --circuito, a elétrica do Sianvolt.

O que roda: o MicroPython 1.29.0 do PC (port unix, em .ferramentas/micropython-unix/; 'lab.py instalar gemeo'
compila) quando existe; senão o próprio CPython, com um aviso. LAB_GEMEO=cpython ou =micropython força um modo.
A pasta motores/gemeo/ tem o resto: motor/ (núcleo, periféricos, elétrica, roteiro, os dois jeitos de rodar),
firmware/ (machine.py, time.py, network.py que o programa importa), chips/ (esp32, c3, s3, c6) e ensaios/.
Extra opcional na pasta do programa: gemeo.roteiro (aparelhos I2C, wifi falha, aperta SW1; ver motor/roteiro.py).
"""
import importlib
import os
import shutil
import subprocess
import time
from pathlib import Path

from nucleo import contrato
from nucleo import ferramentas as fer

__path__ = [str(Path(__file__).with_suffix(""))]   # motores/gemeo/ vira o pacote deste módulo

NOME = "gemeo"
DESCRICAO = "gêmeo digital: seu main.py no MicroPython 1.29 do PC, chip de mentira com as regras do datasheet"
FIEL = ("de verdade: a linguagem (o MicroPython 1.29.0, compilado pro PC), as regras de pino de cada chip "
        "(datasheet: só-entrada, boot, ADC1/ADC2) e, com --circuito, a corrente e a tensão do circuito.py; "
        "de mentira: o tempo (relógio virtual: só as chamadas de hardware custam), o Wi-Fi (faz de conta, nada sai "
        "pela rede), o ADC (sem ruído), a memória (o heap é o do PC) e as interrupções (chegam no próximo sleep)")
PLACAS = {"esp32": "esp32", "c3": "c3", "s3": "s3", "c6": "c6"}
LINGUAGENS = {"micropython"}
RECURSOS = {"serial", "serial_entrada", "pino_saida", "pino_entrada", "pwm", "adc", "i2c", "timer", "rede",
            "eletrica"}

MP_GIT = "https://github.com/micropython/micropython.git"
MP_TAG, MP_COMMIT = "v1.29.0", "0fd6c573ea815774668bbb16b8e197c8822368b2"   # git ls-remote ... v1.29.0^{}
AVISO_CPYTHON = ("rodando no CPython: o MicroPython recusa coisas que o CPython aceita (pra rodar no MicroPython "
                 "1.29 de verdade: python3 laboratorio/lab.py instalar gemeo)")


def _sub(nome):
    return importlib.import_module(__name__ + "." + nome)


def _pasta(fe):
    return Path(fe) / "micropython-unix"


def _versao(binario):
    """a versão do MicroPython do binário, ou None se ele não roda"""
    try:
        r = subprocess.run([str(binario), "-c", "import sys; print(sys.implementation.version)"], timeout=10,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, env=fer.ambiente())
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def modo(fe):
    """-> ('micropython', binário) ou ('cpython', None)"""
    pedido = os.environ.get("LAB_GEMEO", "").strip().lower()
    binario = _pasta(fe) / "micropython"
    if pedido == "cpython":
        return "cpython", None
    if binario.is_file() and os.access(binario, os.X_OK):
        return "micropython", binario
    if pedido == "micropython":
        raise fer.PrecisaDe("o MicroPython do PC (LAB_GEMEO=micropython)", "python3 laboratorio/lab.py instalar gemeo")
    return "cpython", None


def faltando(fe):
    """sem o MicroPython do PC o gêmeo fica 'falta' (o testar pula e diz por quê). O CPython é só de propósito:
    LAB_GEMEO=cpython roda sem instalar nada, menos fiel (aceita coisa que o MicroPython recusa)"""
    if os.environ.get("LAB_GEMEO", "").strip().lower() == "cpython":
        return []
    b = _pasta(fe) / "micropython"
    if b.is_file() and os.access(b, os.X_OK):
        return []
    return ["o MicroPython 1.29.0 do PC (compila do GitHub: ~70 s e uns 176 MB de fonte que são apagados no fim; "
            "fica 1,3 MB). Sem instalar, LAB_GEMEO=cpython roda no Python do PC, menos fiel"]


def ocupa(fe):
    return fer.du(_pasta(fe))


def _rodar_cmd(cmd, diga, **kw):
    inicio = time.monotonic()
    r = subprocess.run(cmd, env=fer.ambiente(), stdin=subprocess.DEVNULL, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError("%s falhou (código %d):\n%s" % (" ".join(map(str, cmd[:4])), r.returncode,
                                                           (r.stdout + r.stderr).strip()[-1500:]))
    diga(("  %s: %.1f s" % (" ".join(map(str, cmd[:4])), time.monotonic() - inicio)).replace(".", ","))


def instalar(fe, diga=print):
    """compila o MicroPython 1.29.0 do PC (port unix) em .ferramentas/micropython-unix/ e apaga a fonte"""
    fe, inicio = Path(fe), time.monotonic()
    destino = _pasta(fe)
    v = _versao(destino / "micropython") if (destino / "micropython").is_file() else None
    if v and v.startswith("(1, 29, 0"):
        diga("gemeo: já tem o MicroPython 1.29.0 do PC (%s, %s)" % (destino, fer.tamanho(fer.du(destino))))
        return
    falta = [p for p in ("git", "make", "gcc") if not shutil.which(p)]
    if falta:
        raise fer.PrecisaDe(" e ".join(falta), "brew install " + " ".join(falta))
    fer.esperar_memoria(400, diga=diga)
    fe.mkdir(parents=True, exist_ok=True)
    fonte = fe / "micropython-src"
    if fonte.exists():
        shutil.rmtree(fonte)   # sobra de uma instalação que parou no meio
    diga("gemeo: baixando o MicroPython %s do GitHub (%s)" % (MP_TAG, MP_GIT))
    _rodar_cmd(["git", "clone", "--quiet", "--depth", "1", "--branch", MP_TAG, MP_GIT, str(fonte)], diga)
    commit = subprocess.run(["git", "-C", str(fonte), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if commit != MP_COMMIT:
        shutil.rmtree(fonte)
        raise RuntimeError("o commit da tag %s não bate: veio %s, esperava %s" % (MP_TAG, commit, MP_COMMIT))
    diga("  commit %s conferido" % commit[:12])
    _rodar_cmd(["make", "-C", "ports/unix", "submodules"], diga, cwd=fonte)   # mbedtls, berkeley-db, micropython-lib
    fer.esperar_memoria(400, diga=diga)
    _rodar_cmd(["make", "-C", "mpy-cross", "-j2"], diga, cwd=fonte)
    fer.esperar_memoria(400, diga=diga)
    _rodar_cmd(["make", "-C", "ports/unix", "-j2", "MICROPY_PY_FFI=0"], diga, cwd=fonte)   # sem libffi
    novo = fonte / "ports/unix/build-standard/micropython"
    v = _versao(novo)
    if not (v and v.startswith("(1, 29, 0")):
        raise RuntimeError("o micropython compilado não roda direito (versão %r); a fonte ficou em %s" % (v, fonte))
    destino.mkdir(parents=True, exist_ok=True)
    shutil.copy2(novo, destino / "micropython")
    shutil.copy2(fonte / "mpy-cross/build/mpy-cross", destino / "mpy-cross")
    (destino / "LEIA.txt").write_text(
        "MicroPython %s (commit %s), port unix (variante standard, MICROPY_PY_FFI=0), compilado por\n"
        "'python3 laboratorio/lab.py instalar gemeo' em %s. Fonte: %s, licença MIT.\n"
        "Uso: o motor gemeo roda o main.py aqui dentro (motores/gemeo/motor/rodar.py).\n"
        % (MP_TAG, MP_COMMIT[:12], time.strftime("%Y-%m-%d"), MP_GIT), encoding="utf-8")
    apagado = fer.du(fonte)
    shutil.rmtree(fonte)
    diga("gemeo: pronto em %.0f s; MicroPython do PC em %s (%s); a fonte (%s) foi apagada" % (
        time.monotonic() - inicio, destino, fer.tamanho(fer.du(destino)), fer.tamanho(apagado)))


def rodar(pedido):
    inicio = time.monotonic()
    chip = _sub("chips." + pedido.alvo)
    miolo, roteiro, rodar_ = _sub("motor.nucleo"), _sub("motor.roteiro"), _sub("motor.rodar")
    qual, binario = modo(pedido.ferramentas)
    avisos = [contrato.aviso(0, AVISO_CPYTHON, "gemeo_cpython") if qual == "cpython" else
              contrato.aviso(0, "rodando no MicroPython 1.29.0 do PC: a linguagem é a da placa; o hardware é o "
                                "gêmeo do %s; heap de %s como a placa (%s)" % (
                                    chip.NOME, fer.tamanho(chip.HEAP_LIVRE), chip.HEAP_FONTE), "gemeo_micropython")]
    extra = pedido.pasta / "gemeo.roteiro"
    try:
        rot = roteiro.Roteiro(pedido.tempo_ms * 1000, pedido.entradas,
                              extra.read_text(encoding="utf-8") if extra.is_file() else "")
    except ValueError as e:
        yield from avisos
        yield {"t_ms": 0, "tipo": "erro", "texto": str(e)}
        yield contrato.fim("erro", NOME, pedido.placa.id, pedido.alvo, 0, time.monotonic() - inicio)
        return
    el = None
    if pedido.circuito:
        try:
            el = _sub("motor.eletrica").Eletrica(pedido.circuito, chip)
            avisos.append(contrato.aviso(0, "ligado no circuito %s (%s): %d peças com modelo elétrico" % (
                Path(pedido.circuito).name, el.mcu["ref"], len(el.pecas)), "circuito"))
        except Exception as e:   # circuito ruim não derruba a rodada: vira aviso e o gêmeo segue sem ele
            avisos.append(contrato.aviso(0, "não deu pra ligar o circuito %s: %s" % (Path(pedido.circuito).name, e),
                                         "circuito"))
    n = miolo.Nucleo(rot, chip, el, pedido.placa)
    if qual == "micropython":
        info = rodar_.micropython(pedido.principal, n, binario, pedido.limite_pc_s, fer.ambiente(),
                                  getattr(chip, "HEAP_LIVRE", None))
    else:
        info = rodar_.cpython(pedido.principal, n, pedido.limite_pc_s)
    n.finalizar()
    if qual == "micropython" and any(e["tipo"] == "erro" and "MemoryError" in e["texto"] for e in n.eventos):
        n.aviso("MemoryError: o gêmeo dá ao programa o heap da placa (%s, %s); mas no PC cada objeto ocupa até 2x "
                "mais (64 bits) e o heap é um bloco só (na placa é dividido): perto do limite a placa pode se sair "
                "diferente. Pra ter certeza, rode com --motor qemu (esp32, c3)" % (fer.tamanho(chip.HEAP_LIVRE),
                                                                                    chip.HEAP_FONTE), "memoria")
    if pedido.detalhe:   # -v: como o gêmeo rodou
        n.ev("aviso", texto="gêmeo: modo %s%s, %d chamadas ao núcleo" % (
            qual, " (%s)" % binario if binario else "", n.comandos), codigo="gemeo_detalhe")
    yield from avisos + n.eventos
    yield contrato.fim(n.acabou[1] if n.acabou else "travou", NOME, pedido.placa.id, pedido.alvo, n.t / 1000,
                       time.monotonic() - inicio, info.get("ram_mb"))
