"""nativo.py: o motor nativo. O seu .ino vira um programa do PC (g++), com o EpoxyDuino (MIT) por baixo pro
String/Print/Stream e o nosso núcleo (motores/nativo/nucleo/) no lugar do chip: relógio virtual, pinos, PWM,
ADC, Serial e interrupções, tudo contado com hora. Sabor esp32 (3,3 V, ADC 12 bits) pras 4 ESP; sabor uno
(5 V, ADC 10 bits, A0 = 14) pro Nano.

A pasta motores/nativo/ tem o resto: Makefile (make -j2), nucleo/ (gemeo.cpp, Arduino.h, StdioSerial.cpp,
esp32/WiFi.h), esboco.py (junta os .ino num sketch.cpp, como a IDE), eventos.py (a linha do tempo do firmware
vira eventos do contrato) e teste_nativo.py com os ensaios/.
Arquivos de cada rodada em build/<placa>/nativo/<exemplo>/: sketch.cpp, firmware, eventos.jsonl, serial.txt,
compilar.txt. Os .o do EpoxyDuino e do núcleo ficam em build/.nativo/<sabor>/ (compilados uma vez só).
"""
import importlib
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

from nucleo import contrato
from nucleo import ferramentas as fer
from nucleo.texto import fmt_t, num

__path__ = [str(Path(__file__).with_suffix(""))]   # motores/nativo/ vira o pacote deste módulo

NOME = "nativo"
DESCRICAO = "o seu .ino compilado pro PC (g++ + EpoxyDuino 1.6.0), com relógio virtual e pinos contados"
FIEL = ("de verdade: o seu código C++ e a lógica dele (g++ do PC, com os protótipos que a IDE gera), os números "
        "do Arduino de cada sabor (modos de pino, ADC de 12 bits a 3,3 V nas ESP e de 10 bits a 5 V no Nano, o PWM "
        "do analogWrite de cada core) e as regras de pino do datasheet (perfis do gêmeo); de mentira: o chip (nada "
        "de Xtensa, RISC-V ou AVR: é x86 do PC), o tempo (relógio virtual: só delay/millis/leituras andam), o int "
        "(32 bits; no Nano é 16), o Wi-Fi (o WiFi.h conecta de faz de conta em 1,5 s), e não tem FreeRTOS, "
        "registradores, HTTP nem bibliotecas além das que vierem na pasta do sketch")
PLACAS = {"esp32": "esp32", "c3": "esp32", "s3": "esp32", "c6": "esp32", "nano": "uno"}
LINGUAGENS = {"arduino"}
RECURSOS = {"serial", "serial_entrada", "pino_saida", "pino_entrada", "pwm", "adc", "timer", "rede"}

EPOXY_GIT = "https://github.com/bxparks/EpoxyDuino.git"
EPOXY_TAG, EPOXY_COMMIT = "v1.6.0", "4f3f0db2b9c31656da828f21838d0a30f7417370"   # git ls-remote ... v1.6.0
AQUI = Path(__file__).resolve().with_suffix("")
MAKEFILE = AQUI / "Makefile"
CHIP = {"esp32": "ESP32", "c3": "ESP32C3", "s3": "ESP32S3", "c6": "ESP32C6"}
PARADO_S = 3   # relógio virtual parado esse tanto de CPU = laço sem fim
NAO_DECLARADO = re.compile(r"was not declared in this scope")
DICAS = [   # erro do compilador -> o que dizer pro Luiz
    (re.compile(r"fatal error: ([\w/.]+\.h): No such file"), "o motor nativo só tem o núcleo do Arduino e o WiFi.h de "
     "mentira: a biblioteca %s não existe aqui (ponha os arquivos dela na pasta do sketch, ou teste na placa)"),
    (re.compile(r"'(x\w+|vTask\w+|portTICK\w*)' was not declared"), "%s é do FreeRTOS, que o motor nativo não tem"),
    (re.compile(r"'(GPIO|DDR[A-D]|PORT[A-D]|PIN[A-D]|TCCR\w+|OCR\w+|_BV)' was not declared"),
     "%s é registrador do chip: no PC não existe (use digitalWrite/analogWrite)"),
]


def _sub(nome):
    return importlib.import_module(__name__ + "." + nome)


def _epoxy(fe):
    return Path(fe) / "EpoxyDuino"


def _commit(pasta):
    try:
        return (Path(pasta) / ".git" / "HEAD").read_text().strip()
    except OSError:
        return None


def faltando(fe):
    falta = [p for p in ("g++", "make") if not shutil.which(p)]
    falta = ["%s (compilador do PC; não vem do laboratório)" % " e ".join(falta)] if falta else []
    e = _epoxy(fe)
    if not (e / "cores" / "epoxy" / "Arduino.h").is_file():
        falta.append("EpoxyDuino %s (github.com/bxparks/EpoxyDuino, MIT, ~1 MB)" % EPOXY_TAG)
    elif _commit(e) != EPOXY_COMMIT:
        falta.append("EpoxyDuino %s (a pasta %s tem outro commit)" % (EPOXY_TAG, e))
    return falta


def ocupa(fe):
    return fer.du(_epoxy(fe))


def instalar(fe, diga=print):
    """clona o EpoxyDuino na tag fixa (commit conferido) e compila um ensaio nos dois sabores"""
    fe, inicio = Path(fe), time.monotonic()
    destino = _epoxy(fe)
    if not faltando(fe):
        diga("nativo: já tem o EpoxyDuino %s (%s, %s)" % (EPOXY_TAG, destino, fer.tamanho(fer.du(destino))))
        return
    falta = [p for p in ("g++", "make", "git") if not shutil.which(p)]
    if falta:
        raise fer.PrecisaDe(" e ".join(falta), "brew install " + " ".join("gcc" if p == "g++" else p for p in falta))
    fe.mkdir(parents=True, exist_ok=True)
    parte = fe / "EpoxyDuino.parte"
    if parte.exists():
        shutil.rmtree(parte)   # sobra de uma instalação que parou no meio
    diga("nativo: baixando o EpoxyDuino %s do GitHub (%s)" % (EPOXY_TAG, EPOXY_GIT))
    r = subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--branch", EPOXY_TAG, EPOXY_GIT, str(parte)],
                       env=fer.ambiente(), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
    commit = _commit(parte) if r.returncode == 0 else None
    if commit != EPOXY_COMMIT:
        shutil.rmtree(parte, ignore_errors=True)
        raise RuntimeError("git clone do EpoxyDuino %s falhou ou veio outro commit (%s): %s" % (
            EPOXY_TAG, commit, (r.stderr or "").strip()[-500:]))
    diga("  commit %s conferido" % commit[:12])
    if destino.exists():
        shutil.rmtree(destino)   # outra versão
    parte.rename(destino)
    for sabor in ("esp32", "uno"):
        diga("  ensaio no sabor %s: %s" % (sabor, ensaio(fe, sabor)))
    diga("nativo: pronto em %s s; EpoxyDuino em %s (%s)" % (num(round(time.monotonic() - inicio, 1)), destino,
                                                           fer.tamanho(fer.du(destino))))


def ensaio(fe, sabor):
    """compila e roda um pisca de 2 s no sabor (deixa o cache dos .o pronto) -> texto curto; erro levanta"""
    pasta = fer.BUILD / ".nativo" / "ensaio" / sabor
    (pasta / "ensaio").mkdir(parents=True, exist_ok=True)
    ino = pasta / "ensaio" / "ensaio.ino"
    ino.write_text("void setup() { pinMode(13, OUTPUT); }\n"
                   "void loop() { digitalWrite(13, !digitalRead(13)); delay(500); }\n", encoding="utf-8")
    inicio = time.monotonic()
    ok, saida, _ = compilar(_epoxy(fe), sabor, None, ino.parent, ino, pasta)
    if not ok:
        raise RuntimeError("o ensaio não compilou no sabor %s:\n%s" % (sabor, saida))
    r = subprocess.run([str(pasta / "firmware"), "--ate", "2000", "--log", str(pasta / "eventos.jsonl")],
                       stdin=subprocess.DEVNULL, capture_output=True, env=fer.ambiente(), timeout=30)
    trocas = (pasta / "eventos.jsonl").read_text().count('"ev":"escreve"')
    if r.returncode != 0 or trocas != 4:
        raise RuntimeError("o ensaio rodou errado no sabor %s (código %d, %d trocas)" % (sabor, r.returncode, trocas))
    return ("compilou e piscou 4 vezes em %.1f s" % (time.monotonic() - inicio)).replace(".", ",")


def _cache(epoxy, sabor):
    """build/.nativo/<sabor>: os .o do EpoxyDuino e do núcleo. Os .d guardam o caminho do EpoxyDuino; se ele
    mudou (outra pasta de ferramentas), o cache velho quebraria o make: começa de novo"""
    cache = fer.BUILD / ".nativo" / sabor
    marca, de_quem = cache / "epoxy.txt", str(Path(epoxy).resolve())
    try:
        velho = marca.read_text(encoding="utf-8")
    except OSError:
        velho = None
    if velho != de_quem:
        shutil.rmtree(cache, ignore_errors=True)
        cache.mkdir(parents=True, exist_ok=True)
        marca.write_text(de_quem, encoding="utf-8")
    return cache


def compilar(epoxy, sabor, chip, pasta, principal, trabalho):
    """make -j2 do sketch -> (ok, saída do compilador, se precisou dos protótipos gerados)"""
    esboco, trabalho = _sub("esboco"), Path(trabalho)
    with fer.trava(fer.BUILD / ".nativo" / (sabor + ".trava")):
        cache = _cache(epoxy, sabor)
    caminhos = [str(p) for p in (epoxy, pasta, trabalho, cache, MAKEFILE)]
    if any(c != c.strip() or " " in c for c in caminhos):
        return False, "o make não aceita espaço no caminho: %s" % next(c for c in caminhos if " " in c), False
    fonte = trabalho / "sketch.cpp"
    cmd = ["make", "-s", "--no-print-directory", "-j2", "-f", str(MAKEFILE), "EPOXY=%s" % epoxy, "SABOR=%s" % sabor,
           "CHIP=%s" % (chip or ""), "FONTE=%s" % fonte, "PASTA=%s" % pasta, "SAIDA=%s" % trabalho,
           "CACHE=%s" % cache]
    primeira, textos = None, [esboco.montar(pasta, principal, p) for p in (False, True)]
    for prototipos, texto in zip((False, True), textos):
        fonte.write_text(texto, encoding="utf-8")
        with fer.trava(cache.with_name(cache.name + ".trava")):   # o cache dos .o é de todas as rodadas
            r = subprocess.run(cmd, env=fer.ambiente(LC_ALL="C"), stdin=subprocess.DEVNULL, capture_output=True,
                               text=True, errors="replace", timeout=600)
        saida = (r.stdout + r.stderr).strip()
        if r.returncode == 0:
            return True, saida, prototipos
        primeira = primeira or saida
        if not NAO_DECLARADO.search(saida) or textos[0] == textos[1]:   # protótipo não ajuda
            break
    return False, primeira, False


def _erro_de_compilacao(saida, pasta, trabalho):
    """a saída do g++ enxuta: sem caminho de build/, sem as linhas do make, no máximo 30 linhas"""
    linhas = []
    for linha in saida.splitlines():
        if linha.startswith("make") or "Error 1" in linha:
            continue
        linhas.append(linha.replace(str(pasta) + "/", "").replace(str(trabalho) + "/", ""))
    linhas = linhas or saida.splitlines()   # só o make reclamou: mostra o make
    texto = "\n".join(linhas[:30]) + ("\n..." if len(linhas) > 30 else "")
    dicas = []
    for padrao, dica in DICAS:
        m = padrao.search(saida)
        if m:
            dicas.append(dica % m.group(1))
    return "não compilou no motor nativo:\n" + texto + "".join("\ndica: " + d for d in dicas)


def _esperar(proc, limite_s):
    """espera o firmware -> (status, rusage, estourou); desliga se passar do limite de PC"""
    inicio, pausa = time.monotonic(), 0.001
    while True:
        pid, status, uso = os.wait4(proc.pid, os.WNOHANG)
        if pid:
            proc.returncode = os.waitstatus_to_exitcode(status)
            return status, uso, False
        if time.monotonic() - inicio > limite_s:
            proc.send_signal(signal.SIGTERM)   # o gemeo.cpp escreve o evento "sinal" e sai
            for _ in range(200):
                pid, status, uso = os.wait4(proc.pid, os.WNOHANG)
                if pid:
                    break
                time.sleep(0.01)
            else:
                proc.kill()
                pid, status, uso = os.wait4(proc.pid, 0)
            proc.returncode = os.waitstatus_to_exitcode(status)
            return status, uso, True
        time.sleep(pausa)
        pausa = min(pausa * 2, 0.02)


def rodar(pedido):
    inicio, placa = time.monotonic(), pedido.placa
    sabor, trab = pedido.alvo, Path(pedido.trabalho)
    falta = faltando(pedido.ferramentas)
    if falta:
        raise fer.PrecisaDe("; ".join(falta), "python3 laboratorio/lab.py instalar nativo")
    trab.mkdir(parents=True, exist_ok=True)

    def acaba(estado, t_ms, ram=None):
        return contrato.fim(estado, NOME, placa.id, pedido.alvo, t_ms, time.monotonic() - inicio, ram)

    ok, saida, prototipos = compilar(_epoxy(pedido.ferramentas), sabor, CHIP.get(placa.id), pedido.pasta,
                                     pedido.principal, trab)
    (trab / "compilar.txt").write_text(saida + "\n", encoding="utf-8")
    if not ok:
        yield {"t_ms": 0, "tipo": "erro", "texto": _erro_de_compilacao(saida, pedido.pasta, trab)}
        yield acaba("erro", 0)
        return
    avisos = []
    if pedido.detalhe:
        avisos.append(contrato.aviso(0, "nativo: compilou no sabor %s%s em %s s" % (
            sabor, " com os protótipos gerados (como a IDE)" if prototipos else "", num(time.monotonic() - inicio)),
            "nativo_detalhe"))
        if saida:
            avisos.append(contrato.aviso(0, "o compilador avisou:\n" + "\n".join(saida.splitlines()[:12]),
                                         "compilador"))
    log = trab / "eventos.jsonl"
    cmd = [str(trab / "firmware"), "--ate", "%.3f" % pedido.tempo_ms, "--log", str(log),
           "--parado", "%g" % min(PARADO_S, pedido.limite_pc_s)] + _sub("eventos").argumentos(pedido.entradas)
    proc = None
    try:
        with open(trab / "serial.txt", "wb") as so, open(trab / "stderr.txt", "wb") as se:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=so, stderr=se, cwd=trab,
                                    env=fer.ambiente(), start_new_session=True)
            status, uso, estourou = _esperar(proc, pedido.limite_pc_s)
    finally:
        if proc is not None and proc.returncode is None:   # Ctrl-C no meio: não deixa o firmware rodando
            proc.kill()
            proc.wait()
    with open(log, encoding="utf-8", errors="replace") as f:
        evs, final = _sub("eventos").converter(f, placa, sabor, placa.porta_serial, pedido.detalhe)
    # o pico de RAM que o firmware mediu de si (VmHWM); o rusage do wait4 inclui o Python antes do exec
    ram = round((final.get("ram_kb") or 0) / 1024 or uso.ru_maxrss / 1024, 1)
    t_fim = max(final["t_ms"], 0.0)
    codigo = proc.returncode
    sinal = final.get("sinal") or (-codigo if codigo < 0 else codigo - 128 if codigo > 128 else None)
    if estourou:
        estado = "travou"
        evs.append(contrato.aviso(t_fim, "passou do limite de %s s de PC: desliguei o firmware" % num(pedido.limite_pc_s),
                                  "limite_pc"))
    elif final.get("parado") is not None:
        estado = "travou"
        evs.append(contrato.aviso(t_fim, "o relógio ficou parado %s s de CPU em %s de placa: um laço que não chama "
                                         "delay(), millis() nem digitalRead(); na placa o programa ficaria preso aí"
                                  % (num(final.get("parado") or PARADO_S), fmt_t(t_fim)), "parado"))
    elif sinal:   # morreu (ponteiro nulo, divisão por zero...): é erro no programa (código 1), como no gemeo
        estado = "erro"
        evs.append({"t_ms": t_fim, "tipo": "erro", "texto": "o programa morreu com %s; na placa seria um reset%s" % (
            _sub("eventos").SINAIS.get(sinal, "o sinal %d" % sinal),
            " ('Guru Meditation Error' na serial)" if sabor == "esp32" else " (o Nano recomeça do setup)")})
    elif final["estado"] == "travou":   # ESP.restart()
        estado = "travou"
    elif codigo == 2:
        raise RuntimeError("o firmware recusou os argumentos: %s" % (trab / "stderr.txt").read_text(errors="replace"))
    elif t_fim >= pedido.tempo_ms - 0.001:
        estado, t_fim = "tempo", pedido.tempo_ms
    else:
        estado = "acabou"
        evs.append(contrato.aviso(t_fim, "o programa chamou exit(%d): na placa não existe sair do programa" % codigo,
                                  "exit"))
    yield from avisos + evs
    yield acaba(estado, t_fim, ram)
