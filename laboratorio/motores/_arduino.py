"""_arduino.py: o ajudante comum dos motores simavr, avr8js e rp2040js (não é motor: começa com _).

- arduino-cli 1.5.1 (release do GitHub, sha256 conferido) com um arduino-cli.yaml só do laboratório em
  .ferramentas/arduino-cli/ (dados/, downloads/ = cache apagável, cache/ = cache de compilação, usuario/);
- compilar(): --jobs 2, binários e log em build/ (os .o no cache/), erro do compilador vira texto de gente;
- simbolo(): o endereço do main()/setup() lido do .elf (é o t = 0 do contrato), sem ferramenta nenhuma;
- emular(): roda um emulador que escreve um evento JSON por linha (simavr_nano, emular.mjs) e devolve os
  eventos do contrato, com prazo de PC, pico de RAM medido e o processo sempre desligado no fim;
- rodar_compilado(): o rodar() inteiro de um motor Arduino (compila, acha o setup(), monta as entradas, emula);
- node(), faltando_js(), instalar_js(): o node (Homebrew) e os pacotes avr8js/rp2040js (npm), só com o OK do Luiz.
"""
import ctypes
import json
import os
import platform
import re
import select
import shutil
import signal
import struct
import subprocess
import time
from pathlib import Path

from nucleo import contrato
from nucleo import ferramentas as fer
from nucleo.texto import num

CLI_VERSAO = "1.5.1"
CLI_ARQ = "arduino-cli_1.5.1_Linux_64bit.tar.gz"
CLI_URL = "https://github.com/arduino/arduino-cli/releases/download/v1.5.1/" + CLI_ARQ
CLI_SHA = "28a8e119c498a25607821c36cb2dc49e8463941b261a0d99091baa7bc692dd2b"   # 1.5.1-checksums.txt do release
PICO_INDICE = "https://github.com/earlephilhower/arduino-pico/releases/download/global/package_rp2040_index.json"
# core -> (nome no arduino-cli, versão, pasta em dados/packages, tamanho instalado; medido em 2026-10-25)
CORES = {"avr": ("arduino:avr", "1.8.8", "arduino/hardware/avr",
                 "253 MB com o avr-gcc, mais ~56 MB de pacotes em downloads/; LGPL-2.1"),
         "rp2040": ("rp2040:rp2040", "6.3.1", "rp2040/hardware/rp2040",
                    "arduino-pico, do GitHub do earlephilhower: 1,5 GB com os 2 compiladores, mais ~440 MB de pacotes "
                    "em downloads/; LGPL-2.1")}
JS = {"avr8js": "0.21.1", "rp2040js": "1.4.1"}   # pacotes do npm (registry.npmjs.org), versão fixa
VAZIO = "void setup() {}\nvoid loop() {}\n"   # o sketch que compila o core uma vez (vai pro cache)
try:
    _LIBC = ctypes.CDLL(None, use_errno=True)
except OSError:
    _LIBC = None


def pasta(fe):
    return Path(fe) / "arduino-cli"


def binario(fe):
    return pasta(fe) / "arduino-cli"


def config(fe):
    """escreve (só se mudou) o arduino-cli.yaml com tudo dentro de .ferramentas/arduino-cli"""
    base = pasta(fe).resolve()
    texto = ("directories:\n  data: {0}/dados\n  downloads: {0}/downloads\n  user: {0}/usuario\n"
             "board_manager:\n  additional_urls:\n    - {1}\nmetrics:\n  enabled: false\n"
             "updater:\n  enable_notification: false\nbuild_cache:\n  path: {0}/cache\n").format(base, PICO_INDICE)
    arq = base / "arduino-cli.yaml"
    if not arq.is_file() or arq.read_text() != texto:
        arq.write_text(texto)
    return arq


def cli(fe):
    return [str(binario(fe)), "--config-file", str(config(fe)), "--no-color"]


def tem_core(fe, core):
    nome, versao, sub, _ = CORES[core]
    return (pasta(fe) / "dados" / "packages" / sub / versao / "platform.txt").is_file()


def faltando(fe, cores=("avr",)):
    falta = []
    if not os.access(binario(fe), os.X_OK):
        falta.append("arduino-cli %s (do GitHub, ~37 MB)" % CLI_VERSAO)
    falta += ["o core %s %s (%s)" % (CORES[c][0], CORES[c][1], CORES[c][3]) for c in cores if not tem_core(fe, c)]
    return falta


def _rodar_cli(fe, args, diga, timeout=1800):
    r = subprocess.run(cli(fe) + args, capture_output=True, text=True, env=fer.ambiente(), timeout=timeout,
                       stdin=subprocess.DEVNULL)
    if r.returncode:
        raise RuntimeError("arduino-cli %s falhou: %s" % (" ".join(args), (r.stdout + r.stderr).strip()[-600:]))
    for linha in [x for x in r.stdout.splitlines() if x.strip()][-2:]:
        diga("    " + linha.strip())


def instalar(fe, diga, cores=("avr",)):
    """arduino-cli (GitHub, sha256) + os cores pedidos (arduino-cli core install, do arduino.cc e do GitHub)"""
    fe, base = Path(fe), pasta(fe)
    if not os.access(binario(fe), os.X_OK):
        if platform.machine().lower() not in ("x86_64", "amd64"):
            raise RuntimeError("o laboratório só traz o arduino-cli pra Linux x86_64 (aqui: %s)" % platform.machine())
        pacote = fer.baixar(CLI_URL, CLI_SHA, base / CLI_ARQ, diga)
        fer.extrair(pacote, base)
        pacote.unlink()
        diga("  arduino-cli %s em %s" % (CLI_VERSAO, base))
    config(fe)
    indice = False
    for c in cores:
        if tem_core(fe, c):
            continue
        nome, versao, _, tam = CORES[c]
        fer.esperar_memoria(400, diga=diga)
        if not indice:
            diga("  atualizando a lista de cores (arduino.cc e GitHub do arduino-pico)")
            _rodar_cli(fe, ["core", "update-index"], diga)
            indice = True
        diga("  instalando o core %s %s (%s; pode levar uns minutos)" % (nome, versao, tam))
        _rodar_cli(fe, ["core", "install", "%s@%s" % (nome, versao)], diga, timeout=3600)
        aquecer(fe, {"avr": "arduino:avr:nano", "rp2040": "rp2040:rp2040:rpipico"}[c], diga)


def aquecer(fe, fqbn, diga):
    """compila um sketch vazio: o core vai pro cache/cores e todo sketch novo usa ele (sem compilar o core)"""
    obra = fer.BUILD / ".aquecer" / fqbn.replace(":", "_")
    shutil.rmtree(obra, ignore_errors=True)
    sketch = obra / "aquecer"
    sketch.mkdir(parents=True, exist_ok=True)
    (sketch / "aquecer.ino").write_text(VAZIO)
    inicio = time.monotonic()
    r = subprocess.run(cli(fe) + ["compile", "--jobs", "2", "-b", fqbn, "--output-dir", str(obra / "bin"),
                                  str(sketch)], capture_output=True, text=True, env=fer.ambiente(), timeout=1800,
                       stdin=subprocess.DEVNULL)
    diga("  core de %s compilado pro cache em %s s%s" % (fqbn, num(time.monotonic() - inicio, 1),
                                                           "" if r.returncode == 0 else " (falhou: %s)" % r.stderr[-300:]))


def compilar(pedido, fqbn):
    """-> (pasta com os binários, None, segundos) ou (None, texto do erro, segundos). Os binários e o log vão pra
    pedido.trabalho; os .o ficam no cache do arduino-cli (.ferramentas/arduino-cli/cache, apagável). Sem
    --build-path de propósito: com ele o arduino-cli não usa o core já compilado do cache (Pico: 11 s em vez de 1 s)."""
    saida = Path(pedido.trabalho) / "bin"
    cmd = cli(pedido.ferramentas) + ["compile", "--jobs", "2", "-b", fqbn, "--output-dir", str(saida),
                                     str(pedido.pasta)]
    inicio = time.monotonic()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=fer.ambiente(), timeout=900,
                           stdin=subprocess.DEVNULL, errors="replace")
    except subprocess.TimeoutExpired:
        return None, "a compilação passou de 15 minutos", time.monotonic() - inicio
    gasto = time.monotonic() - inicio
    (Path(pedido.trabalho) / "compilacao.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    if r.returncode:
        return None, erro_de_compilacao(r.stdout + r.stderr, pedido.pasta), gasto
    return saida, None, gasto


def erro_de_compilacao(texto, pasta_sketch):
    """as linhas do compilador que importam, com o caminho de build/ trocado pelo nome do arquivo"""
    texto = texto.replace(str(Path(pasta_sketch).resolve()) + "/", "").replace(str(pasta_sketch) + "/", "")
    linhas = [x.rstrip() for x in texto.splitlines() if x.strip()]
    achadas = []
    for i, x in enumerate(linhas):
        if re.search(r"\b(fatal )?error\b", x) and not x.startswith("Error during build"):
            achadas += [y for y in linhas[i:i + 3] if y not in achadas]
    return "erro de compilação:\n" + "\n".join((achadas or linhas[-12:])[:20])


def simbolo(elf, nomes=("setup", "_Z5setupv", "main")):
    """o endereço (em bytes) da primeira função de 'nomes' que existe no .elf (ELF32), ou None"""
    try:
        d = Path(elf).read_bytes()
    except OSError:
        return None
    if d[:4] != b"\x7fELF" or d[4] != 1:
        return None
    o = "<" if d[5] == 1 else ">"
    shoff, = struct.unpack_from(o + "I", d, 0x20)
    tam, quantas = struct.unpack_from(o + "HH", d, 0x2E)
    secoes = [struct.unpack_from(o + "10I", d, shoff + i * tam) for i in range(quantas)]
    achados = {}
    for s in secoes:
        if s[1] != 2:   # SHT_SYMTAB
            continue
        strtab = secoes[s[6]][4]
        for p in range(s[4], s[4] + s[5], 16):
            nome, valor, _, info, _, _ = struct.unpack_from(o + "IIIBBH", d, p)
            if info & 0xF == 2:   # STT_FUNC
                n = d[strtab + nome:d.index(b"\0", strtab + nome)].decode("ascii", "replace")
                if n in nomes:
                    achados.setdefault(n, valor)
    return next((achados[n] for n in nomes if n in achados), None)


def argumentos(entradas, adc_ok=lambda p: True):
    """entradas do Pedido -> opções do emulador (--pino P=v@t, --adc P=V@t, --serial HEX@t) + avisos"""
    args, avisos = [], []
    for e in entradas:
        t = "%.3f" % e["t_ms"]
        if "serial" in e:
            args += ["--serial", e["serial"].encode("utf-8").hex() + "@" + t]
        elif "volts" in e:
            if adc_ok(e["pino"]):
                args += ["--adc", "%s=%.4f@%s" % (e["pino"], e["volts"], t)]
            else:
                avisos.append(contrato.aviso(e["t_ms"], "%s não tem ADC: a tensão do roteiro ficou de fora" % e["pino"],
                                             "roteiro"))
        elif "valor" in e:
            args += ["--pino", "%s=%d@%s" % (e["pino"], e["valor"], t)]
    return args, avisos


def _morrer_junto():   # no filho, antes do exec: se o lab.py morrer, o emulador morre junto
    if _LIBC is not None:
        _LIBC.prctl(1, signal.SIGTERM, 0, 0, 0)   # PR_SET_PDEATHSIG


def desligar(p, espera=2.0):
    """espera o processo sair (ou desliga: TERM, depois KILL); devolve o ru_maxrss em MB (que inclui o fork)"""
    for sinal, prazo in ((None, espera), (signal.SIGTERM, 2.0), (signal.SIGKILL, 5.0)):
        if p.returncode is not None:
            return None
        if sinal is not None:
            try:
                os.kill(p.pid, sinal)
            except ProcessLookupError:
                pass
        limite = time.monotonic() + prazo
        while True:
            try:
                pid, status, uso = os.wait4(p.pid, os.WNOHANG)
            except ChildProcessError:
                p.returncode = -1
                return None
            if pid:
                p.returncode = os.waitstatus_to_exitcode(status)
                return round(uso.ru_maxrss / 1024, 1)
            if time.monotonic() >= limite:
                break
            time.sleep(0.01)
    return None


def converter(e, porta):
    """um evento do emulador -> evento do contrato (None = interno: inicio, marca_fim)"""
    tipo, t = e.get("tipo"), e.get("t_ms", 0)
    if tipo == "pino":
        return {"t_ms": t, "tipo": "pino", "pino": e["pino"], "valor": e["valor"], "origem": "firmware"}
    if tipo == "modo":
        return {"t_ms": t, "tipo": "modo", "pino": e["pino"], "modo": e["modo"]}
    if tipo == "pwm":
        return {"t_ms": t, "tipo": "pwm", "pino": e["pino"], "duty": e["duty"], "freq_hz": e.get("freq_hz")}
    if tipo == "serial":
        return {"t_ms": t, "tipo": "serial", "dir": "tx", "texto": e["texto"], "porta": e.get("porta") or porta}
    if tipo == "aviso":
        return contrato.aviso(t, e["texto"], e.get("codigo"))
    if tipo == "erro":
        return {"t_ms": t, "tipo": "erro", "texto": e["texto"]}
    return None


def emular(pedido, motor, cmd, inicio, porta="uart0", traduz=None):
    """roda o emulador e devolve os eventos do contrato, com exatamente um 'fim' no fim.
    O processo é desligado aconteça o que acontecer (fim normal, limite de PC, Ctrl-C, gerador fechado)."""
    trabalho = Path(pedido.trabalho)
    log = trabalho / (motor + ".log")
    # o emulador para sozinho antes do limite e diz até onde chegou (o prazo daqui é a rede de segurança); a
    # compilação não conta, mas ele para antes do corte do lab.py (limite + FOLGA_PC_S desde o começo do rodar)
    sobra = pedido.limite_pc_s + contrato.FOLGA_PC_S - 3 - (time.monotonic() - inicio)
    cmd = list(cmd) + ["--limite-pc", "%.1f" % max(1.0, min(pedido.limite_pc_s - 2, sobra))]
    pai = fer.pico_ram_mb(os.getpid()) or 0   # o ru_maxrss do filho inclui o Python de antes do exec
    with open(log, "wb") as erro:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=erro, cwd=str(trabalho),
                             env=fer.ambiente(), preexec_fn=_morrer_junto)
    final, ultimo, buf, ram, info = None, 0.0, b"", None, {}
    prazo = time.monotonic() + pedido.limite_pc_s
    try:
        fd = p.stdout.fileno()
        while True:
            resta = prazo - time.monotonic()
            if resta <= 0:
                final = {"estado": "travou", "t_ms": ultimo}
                yield contrato.aviso(ultimo, "o emulador passou do limite de %.0f s de PC: desliguei"
                                     % pedido.limite_pc_s, "limite_pc")
                break
            pronto = select.select([fd], [], [], min(resta, 0.05))[0]
            pico = fer.pico_ram_mb(p.pid)   # VmHWM do emulador vivo (o ru_maxrss do wait4 conta o fork do Python)
            ram = max(ram or 0, pico or 0) or None
            if not pronto:
                continue
            bloco = os.read(fd, 1 << 16)
            if not bloco:
                break
            *linhas, buf = (buf + bloco).split(b"\n")
            for linha in linhas:
                if not linha.startswith(b"{"):
                    continue
                try:
                    e = json.loads(linha.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if e.get("tipo") == "fim":
                    final = e
                elif e.get("tipo") in ("inicio", "marca_fim"):
                    info[e["tipo"]] = e
                else:
                    ev = (traduz or converter)(e, porta)
                    if ev is not None and ev["t_ms"] <= pedido.tempo_ms:
                        ultimo = max(ultimo, ev["t_ms"])
                        yield ev
    finally:
        p.stdout.close()
        fora = desligar(p, 2.0 if final else 0.0)
        if fora and fora > pai + 1:   # passou do Python: é o pico do próprio emulador
            ram = max(ram or 0, fora)
    if final is None:   # o processo morreu sem dizer como terminou
        cauda = [x for x in log.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()][-4:]
        yield contrato.aviso(ultimo, "o emulador parou sem terminar (código %s)%s" % (
            p.returncode, (": " + " | ".join(cauda)) if cauda else ""), motor)
        final = {"estado": "travou", "t_ms": ultimo}
    estado = final["estado"]
    t_fim = pedido.tempo_ms if estado == "tempo" else min(final.get("t_ms", ultimo), pedido.tempo_ms)
    if estado == "limite":   # o programa não travou: o emulador é que não chegou no --tempo dentro do limite
        estado = "tempo"
        yield contrato.aviso(t_fim, "o limite de %s s de PC acabou em %s s de placa (o %s roda a %sx a velocidade "
                             "da placa): parei aqui, o resto não foi testado; use um --tempo menor" % (
                                 num(pedido.limite_pc_s, 1), num(t_fim / 1000, 3), motor,
                                 num(final.get("velocidade", 0))), "limite_pc")
    if pedido.detalhe and final.get("velocidade"):
        antes = info.get("inicio", {})
        depois = ("; o programa começou %s ciclos depois do reset" % antes["ciclos_antes"] if "ciclos_antes" in antes
                  else "; o programa começou %s s de placa depois do reset" % num(antes["ms_antes"] / 1000, 3)
                  if "ms_antes" in antes else "")
        yield contrato.aviso(t_fim, "%s: %sx a velocidade da placa (%s s de placa em %s s de PC)%s" % (
            motor, num(final["velocidade"]), num(t_fim / 1000, 1), num(final.get("tempo_real_ms", 0) / 1000, 1),
            depois), motor)
    yield contrato.fim(estado, motor, pedido.placa.id, pedido.alvo, t_fim, time.monotonic() - inicio, ram)


def rodar_compilado(pedido, motor, fqbn, montar, extensao, adc_ok=lambda p: True, porta="uart0", traduz=None):
    """o rodar() de um motor Arduino: compila em pedido.trabalho, acha o setup() no .elf (t = 0) e roda
    montar(binario) + --ms/--inicio/entradas. Erro de compilação = evento erro + fim 'erro'."""
    inicio = time.monotonic()
    fer.esperar_memoria(400, diga=lambda *a: None)
    saida, erro, gasto = compilar(pedido, fqbn)
    if erro:
        yield {"t_ms": 0, "tipo": "erro", "texto": erro}
        yield contrato.fim("erro", motor, pedido.placa.id, pedido.alvo, 0, time.monotonic() - inicio)
        return
    nome = Path(pedido.principal).name   # pisca.ino -> bin/pisca.ino.elf, .hex, .uf2
    elf, binario = saida / (nome + ".elf"), saida / (nome + extensao)
    endereco = simbolo(elf)
    if pedido.detalhe:
        yield contrato.aviso(0, "compilado com o arduino-cli (%s) em %s s; começo do programa em %s" % (
            fqbn, num(gasto, 1), "0x%x" % endereco if endereco is not None else "? (o tempo conta do reset)"), motor)
    args, avisos = argumentos(pedido.entradas, adc_ok)
    yield from avisos
    cmd = montar(binario) + ["--ms", "%.3f" % pedido.tempo_ms] + args
    if endereco is not None:
        cmd += ["--inicio", str(endereco)]
    yield from emular(pedido, motor, cmd, inicio, porta, traduz)


# ---------- node e os pacotes do npm (avr8js, rp2040js) ----------
def node():
    """o node: LAB_NODE (se definido), o do PATH ou o do Homebrew; None se não tiver"""
    if "LAB_NODE" in os.environ:
        n = os.environ["LAB_NODE"]
        return n if n and os.access(n, os.X_OK) else None
    brew = fer.tem_brew()
    extra = Path(brew).parent / "node" if brew else None
    return shutil.which("node") or (str(extra) if extra and os.access(extra, os.X_OK) else None)


def modulos(fe):
    return Path(fe) / "js" / "node_modules"


def versao_js(fe, pacote):
    try:
        return json.loads((modulos(fe) / pacote / "package.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        return None


def faltando_js(fe, pacote):
    falta = [] if node() else ["node (do Homebrew: brew install node; 118 MB, mais até ~300 MB de dependências)"]
    if versao_js(fe, pacote) != JS[pacote]:
        falta.append("o pacote %s@%s (do npm, < 2 MB)" % (pacote, JS[pacote]))
    return falta


def instalar_js(fe, pacote, diga):
    """node e o pacote do npm: o laboratório não roda brew nem npm sozinho (PrecisaDe pergunta ao Luiz)"""
    n = node()
    if not n:
        raise fer.PrecisaDe("o node, que roda o %s (vem do Homebrew)" % pacote, "brew install node")
    if versao_js(fe, pacote) == JS[pacote]:
        return
    js = Path(fe) / "js"   # o npm cria a pasta: nada é escrito antes do OK
    npm = Path(n).parent / "npm"
    raise fer.PrecisaDe("os pacotes %s, que só existem no npm (registry.npmjs.org, o canal oficial do autor, "
                        "Uri Shaked/Wokwi, licença MIT). O npm está fora da lista de fontes combinada: só com o seu OK"
                        % " e ".join("%s@%s" % x for x in JS.items()),
                        "%s install --prefix %s --cache %s --no-audit --no-fund %s" % (
                            npm if npm.exists() else "npm", js, js / ".cache-npm",
                            " ".join("%s@%s" % x for x in JS.items())))
