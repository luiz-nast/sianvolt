"""ferramentas.py: baixar (só de fonte oficial, com sha256), extrair, medir disco e memória, pedir o brew.

Tudo mora em laboratorio/.ferramentas (ou em LAB_FERRAMENTAS, pra testar uma instalação do zero);
o que é temporário vai pra laboratorio/build/.tmp, nunca pro /tmp (que aqui fica na RAM).
"""
import contextlib
import fcntl
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent          # laboratorio/
BUILD = RAIZ / "build"
FONTES = ("github.com", "micropython.org", "arduino.cc", "espressif.com", "raspberrypi.com")
# o que dá pra apagar sem perder nada (volta sozinho na próxima instalação/compilação)
CACHE = {"arduino-cli/downloads": "pacotes baixados", "arduino-cli/cache": "cache de compilação"}
NOTAS = {"arduino-cli": "arduino-cli e os cores (avr, rp2040)", "EpoxyDuino": "base do motor nativo",
         "esp-idf": "só pra recompilar o firmware com rede (fora do instalar padrão)",
         "espressif": "compiladores do ESP-IDF (fora do instalar padrão)",
         "js": "avr8js e rp2040js (vieram do npm)", "micropython": "firmwares .bin/.uf2 do micropython.org",
         "micropython-unix": "MicroPython que roda no PC (gemeo)", "qemu-esp": "QEMU da Espressif (qemu)",
         "rp2040js-src": "fonte do rp2040js (de onde veio o bootrom_b1.mjs)",
         "simavr-src": "fonte do simavr", "simavr": "simavr_nano compilado"}


@contextlib.contextmanager
def trava(arquivo, esperar=True):
    """flock exclusivo em 'arquivo' (criado se faltar): vários Claudes e terminais usam o laboratório ao mesmo
    tempo. A trava sai sozinha quando o processo acaba, até com kill -9. esperar=False: devolve None na hora se
    outro já tem a trava (o 'with' roda com None)"""
    arquivo = Path(arquivo)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    f = open(arquivo, "a")
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | (0 if esperar else fcntl.LOCK_NB))
        except BlockingIOError:
            f.close()
            f = None
        yield f
    finally:
        if f is not None:
            f.close()


@contextlib.contextmanager
def vaga(base, quantas=8):
    """a pasta de trabalho só desta rodada: base, ou base~2, base~3... quando outra rodada (outro Claude, outro
    terminal) está usando a mesma (mesmo programa, ou outro com o mesmo nome, na mesma placa e motor). Cada vaga
    tem a sua trava (base.trava, base~2.trava...). Todas ocupadas: espera a primeira."""
    base = Path(base)
    for n in range(1, quantas + 1):
        pasta = base if n == 1 else base.with_name("%s~%d" % (base.name, n))
        with trava(pasta.with_name(pasta.name + ".trava"), esperar=False) as t:
            if t is not None:
                yield pasta
                return
    with trava(base.with_name(base.name + ".trava")):
        yield base


def pasta_ferramentas():
    return Path(os.environ.get("LAB_FERRAMENTAS") or RAIZ / ".ferramentas").resolve()


class PrecisaDe(Exception):
    """falta algo que o laboratório não instala sozinho (brew, npm): o que é e o comando que resolve"""

    def __init__(self, oque, comando):
        super().__init__("falta: %s. Pra resolver: %s" % (oque, comando))
        self.oque, self.comando = oque, comando


def temporaria():
    """build/.tmp: o TMPDIR dos subprocessos"""
    t = BUILD / ".tmp"
    t.mkdir(parents=True, exist_ok=True)
    return t


def proteger_tmp():
    """TMPDIR/TMP/TEMP deste processo (e dos filhos) em build/.tmp"""
    t = str(temporaria())
    os.environ.update(TMPDIR=t, TMP=t, TEMP=t)


def ambiente(**extra):
    """os.environ com TMPDIR/TMP/TEMP em build/.tmp, pros subprocessos dos motores"""
    t = str(temporaria())
    return dict(os.environ, TMPDIR=t, TMP=t, TEMP=t, **extra)


def fonte_oficial(url):
    host = urllib.parse.urlparse(url).hostname or ""
    return urllib.parse.urlparse(url).scheme == "https" and any(host == f or host.endswith("." + f) for f in FONTES)


def sha256(arquivo):
    h = hashlib.sha256()
    with open(arquivo, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def baixar(url, soma, destino, diga=print):
    """baixa url pra destino conferindo o sha256; se já tem e a soma bate, não baixa de novo"""
    destino = Path(destino)
    if destino.is_file() and sha256(destino) == soma:
        return destino
    if not fonte_oficial(url):
        raise ValueError("fonte fora da lista combinada (%s): %s" % (", ".join(FONTES), url))
    destino.parent.mkdir(parents=True, exist_ok=True)
    parte = destino.with_name(destino.name + ".parte")
    diga("baixando %s" % url)
    h, inicio = hashlib.sha256(), time.monotonic()
    with urllib.request.urlopen(url, timeout=60) as r, open(parte, "wb") as f:
        for bloco in iter(lambda: r.read(1 << 20), b""):
            h.update(bloco)
            f.write(bloco)
    if h.hexdigest() != soma:
        parte.unlink()
        raise ValueError("sha256 não bate em %s: veio %s, esperava %s" % (url, h.hexdigest(), soma))
    parte.replace(destino)
    diga(("  %s em %.1f s, sha256 ok" % (tamanho(destino.stat().st_size), time.monotonic() - inicio)).replace(".", ","))
    return destino


def extrair(arquivo, destino):
    """.tar(.gz/.xz/.bz2) ou .zip pra dentro de destino (sem sair dele)"""
    arquivo, destino = Path(arquivo), Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(arquivo):
        with zipfile.ZipFile(arquivo) as z:
            for nome in z.namelist():
                if not (destino / nome).resolve().is_relative_to(destino.resolve()):
                    raise ValueError("caminho perigoso no zip: %s" % nome)
            z.extractall(destino)
    else:
        with tarfile.open(arquivo) as t:
            t.extractall(destino, filter="data")
    return destino


def du(caminho):
    """bytes ocupados no disco (como o du), sem seguir link e sem contar hardlink duas vezes"""
    total, vistos, pilha = 0, set(), [str(caminho)]
    while pilha:
        try:
            itens = os.scandir(pilha.pop())
        except OSError:
            continue
        with itens:
            for e in itens:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if (st.st_dev, st.st_ino) in vistos:
                    continue
                vistos.add((st.st_dev, st.st_ino))
                total += st.st_blocks * 512
                if e.is_dir(follow_symlinks=False):
                    pilha.append(e.path)
    return total


def ocupacao(fe):
    """linhas do 'instalar --ver': cada pasta de .ferramentas com o du, e o que é cache apagável"""
    out, total = ["Ferramentas em %s" % fe], 0
    for d in sorted(fe.iterdir()) if fe.is_dir() else []:
        if d.is_dir():
            n = du(d)
            total += n
            out.append("  %-18s %9s  %s" % (d.name + "/", tamanho(n), NOTAS.get(d.name, "")))
            for sub, o_que in CACHE.items():
                if sub.startswith(d.name + "/") and (fe / sub).exists():
                    out.append("    %-16s %9s  cache apagável (%s)" % (sub.split("/", 1)[1] + "/",
                                                                     tamanho(du(fe / sub)), o_que))
    return out + ["  total %s" % tamanho(total)]


def tamanho(n):
    for unidade, base in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= base:
            return ("%.1f %s" % (n / base, unidade)).replace(".", ",")
    return "%d B" % n


def memoria_livre_mb():
    """MemAvailable de /proc/meminfo, em MB (None se não der pra ler)"""
    try:
        for linha in Path("/proc/meminfo").read_text().splitlines():
            if linha.startswith("MemAvailable:"):
                return int(linha.split()[1]) / 1024
    except OSError:
        pass
    return None


def esperar_memoria(minimo=400, maximo_s=120, diga=print):
    """espera até ter 'minimo' MB livres; depois de maximo_s segue assim mesmo (devolve False)"""
    inicio, avisou = time.monotonic(), False
    while True:
        livre = memoria_livre_mb()
        if livre is None or livre >= minimo:
            return True
        if time.monotonic() - inicio > maximo_s:
            diga("memória ainda baixa (%d MB livres): seguindo assim mesmo" % livre)
            return False
        if not avisou:
            diga("só %d MB de memória livre: esperando chegar a %d MB..." % (livre, minimo))
            avisou = True
        time.sleep(2)


def pico_ram_mb(pid):
    """o pico de RAM (VmHWM) de um processo ainda vivo, em MB"""
    try:
        for linha in Path("/proc/%d/status" % pid).read_text().splitlines():
            if linha.startswith("VmHWM:"):
                return round(int(linha.split()[1]) / 1024, 1)
    except (OSError, ValueError):
        pass
    return None


def parar(processo, espera=3):
    """desliga um subprocesso: terminate, espera, kill"""
    if processo is None or processo.poll() is not None:
        return
    processo.terminate()
    try:
        processo.wait(espera)
    except subprocess.TimeoutExpired:
        processo.kill()
        processo.wait()


def tem_brew():
    """o caminho do brew, ou None"""
    padrao = Path("/home/linuxbrew/.linuxbrew/bin/brew")
    return shutil.which("brew") or (str(padrao) if padrao.exists() else None)


def pedir(falta, diga=print, entrada=None):
    """PrecisaDe -> com terminal, pergunta 'Posso rodar: ...? [s/N]' e roda se o Luiz deixar;
    sem terminal, só mostra o comando. Devolve True se rodou e deu certo."""
    entrada = entrada or sys.stdin
    diga("falta: %s" % falta.oque)
    if not entrada.isatty():
        diga("  rode: %s" % falta.comando)
        return False
    diga("Posso rodar: %s? [s/N] " % falta.comando)
    if entrada.readline().strip().lower() not in ("s", "sim", "y"):
        diga("  ok, não rodei. Quando quiser: %s" % falta.comando)
        return False
    return subprocess.run(shlex.split(falta.comando), env=ambiente()).returncode == 0
