"""qemu.py: motor qemu = o QEMU da Espressif rodando o MicroPython 1.29 oficial (o chip emulado de verdade).

Cada rodada: imagem de flash limpa em build/, boot, grava o programa (e o placa.py) no sistema de arquivos
do MicroPython, manda o prelúdio (motores/qemu/preludio.py) e roda. Pinos de saída e PWM saem do trace de
escritas nos registradores (motores/qemu/esp32emu.py); entradas e ADC vêm do roteiro pelo prelúdio.
Tempo = relógio do PC (o QEMU não é preciso por ciclo). Um QEMU por vez, sempre desligado no fim.
A receita do firmware com rede (open_eth) fica em motores/qemu/rede/, fora do instalar.
"""
import ast
import importlib
import os
import platform
import re
import select
import shutil
import signal
import subprocess
import time
from pathlib import Path

from nucleo import contrato
from nucleo import ferramentas as fer

__path__ = [str(Path(__file__).with_suffix(""))]   # motores/qemu/ vira o pacote deste módulo
emu = importlib.import_module(__name__ + ".esp32emu")
PASTA = Path(__path__[0])

NOME = "qemu"
DESCRICAO = "QEMU da Espressif 9.2.2 + MicroPython 1.29 oficial (ESP32 e ESP32-C3)"
FIEL = ("De verdade: o firmware oficial do MicroPython no chip emulado (CPU, memória, timers, UART; o PWM pelo "
        "LEDC emulado só no ESP32), no relógio do PC. De mentira: no C3 o PWM (o QEMU não emula o LEDC do C3: o "
        "laboratório remonta o duty das escritas nos registradores), ler pino (o GPIO do QEMU não lê: entrada e "
        "pull-up vêm do roteiro), o ADC (faz de conta) e o Wi-Fi (dá OSError); o tempo de CPU não é o da placa e a "
        "serial não tem limite de baud. C6 roda como C3 (sem o rádio, sem o núcleo LP, GPIO18/19 viram 10/11). "
        "Sem S3: o MicroPython S3 1.29 trava no boot do QEMU 9.2.2 (PSRAM, 'Failed to set QIE bit'). Tabela do "
        "que o QEMU da Espressif emula: https://github.com/espressif/esp-toolchain-docs/blob/main/qemu/README.md")
PLACAS = {"esp32": "esp32", "c3": "c3", "c6": ("c3", "aproximado: roda no C3, sem o rádio nem o núcleo LP do C6")}
LINGUAGENS = {"micropython"}
RECURSOS = {"serial", "serial_entrada", "pino_saida", "pino_entrada", "pwm", "adc", "timer"}

VERSAO = "esp-develop-9.2.2-20260417"
RELEASE = "https://github.com/espressif/qemu/releases/download/%s/" % VERSAO
# sha256 e tamanho do qemu-esp_develop_9.2.2_20260417-checksum.sha256 do próprio release
QEMU = {
    "qemu-system-xtensa": ("esp32-v3-rom.bin", {
        "x86_64": ("qemu-xtensa-softmmu-esp_develop_9.2.2_20260417-x86_64-linux-gnu.tar.xz",
                   "0eecb2a34a5586c0e59110f77b9343b7b336e82fdb0e1a30e1dc1bab8a547e35", 15619396),
        "aarch64": ("qemu-xtensa-softmmu-esp_develop_9.2.2_20260417-aarch64-linux-gnu.tar.xz",
                    "00de5985094c14e47d1b38464a006b8ed64fd0fa7a289c56da24f3a329f65339", 15111492)}),
    "qemu-system-riscv32": ("esp32c3-rom.bin", {
        "x86_64": ("qemu-riscv32-softmmu-esp_develop_9.2.2_20260417-x86_64-linux-gnu.tar.xz",
                   "547f03e04701a92cbb699f7f7d015adc1f5b5ef93cbb94c0dd9b7107e2d84e77", 16842920),
        "aarch64": ("qemu-riscv32-softmmu-esp_develop_9.2.2_20260417-aarch64-linux-gnu.tar.xz",
                    "a9f7b98636008edcf7a11c96f10b3a3ec83c2a890fc54c3e3ceb3ec9edace427", 16325180)}),
}
MICROPYTHON = "https://micropython.org/resources/firmware/"
FIRMWARE = {   # https://micropython.org/download/ESP32_GENERIC/ e .../ESP32_GENERIC_C3/
    "esp32": ("ESP32_GENERIC-20260824-v1.29.0.bin",
              "e67ad6015a0a504c1fec9aa9bbf589d0432ed28e62546f4f8dd8a147f8bd95f6", 1790544),
    "c3": ("ESP32_GENERIC_C3-20260824-v1.29.0.bin",
           "bf72ed9eb88ad3a8f49d02c3d371f9ea34c90a8a303aeb9e324d8efd4a2a655a", 1754736),
}
# pinos com ADC por placa (MicroPython v1.29.0, ports/esp32/machine_adc.c): o ADC de faz de conta
# recusa os outros como a placa recusaria
ADC_PINOS = {"esp32": [36, 37, 38, 39, 32, 33, 34, 35, 4, 0, 2, 15, 13, 12, 14, 27, 25, 26],
             "c3": [0, 1, 2, 3, 4, 5], "c6": [0, 1, 2, 3, 4, 5, 6]}
# C6 rodando no C3: o MicroPython do C3 não tem GPIO14-19, 22 e 23 (18/19 são o USB; v1.29.0,
# ports/esp32/machine_pin.h). O 18 e o 19 do C6 rodam no 10 e no 11 do C3, que a C6 SuperMini não expõe.
TROCA = {"c6": {18: 10, 19: 11}}
MODOS = {1: "entrada", 2: "pullup", 3: "pulldown", 4: "adc"}
AVISO_ADC = "ADC de faz de conta: testa o seu código, não o ADC do chip"
AVISO_WIFI = "o QEMU não tem Wi-Fi: o WLAN de mentira deu OSError (no chip emulado ele trava ou cai)"
MAX_ARQUIVO = 64 * 1024


def _bin(fe, nome=""):
    return Path(fe) / "qemu-esp" / "qemu" / "bin" / nome


def _rom(fe, rom):
    return Path(fe) / "qemu-esp" / "qemu" / "share" / "qemu" / rom


def _qemu_ok(fe, binario):
    return os.access(_bin(fe, binario), os.X_OK) and _rom(fe, QEMU[binario][0]).is_file()


def _maquina():
    return {"amd64": "x86_64", "arm64": "aarch64"}.get(platform.machine().lower(), platform.machine().lower())


def faltando(ferramentas):
    """o que falta em .ferramentas (vazio = pronto); só olha arquivos"""
    falta = []
    for binario, (rom, pacotes) in QEMU.items():
        if not _qemu_ok(ferramentas, binario):
            pacote = pacotes.get(_maquina())
            falta.append("%s do QEMU da Espressif (%s)" % (binario, "baixa %s do GitHub, ~72 MB instalado"
                         % fer.tamanho(pacote[2]) if pacote else "o release só tem Linux x86_64 e aarch64"))
    for nome, _, n in FIRMWARE.values():
        f = Path(ferramentas) / "micropython" / nome
        if not f.is_file() or f.stat().st_size != n:
            falta.append("MicroPython %s (%s do micropython.org)" % (nome, fer.tamanho(n)))
    return falta


def ocupa(ferramentas):
    fe = Path(ferramentas)
    bins = [fe / "micropython" / n for n, _, _ in FIRMWARE.values()]
    return fer.du(fe / "qemu-esp") + sum(b.stat().st_size for b in bins if b.is_file())


def instalar(ferramentas, diga=print):
    """baixa o QEMU (GitHub da Espressif) e o MicroPython (micropython.org), conferindo o sha256"""
    fe = Path(ferramentas)
    if not faltando(fe):
        diga("qemu: já tem (QEMU %s e MicroPython 1.29.0 do ESP32 e do C3)" % VERSAO)
        return
    for binario, (rom, pacotes) in QEMU.items():
        if _qemu_ok(fe, binario):
            diga("  %s: já tem" % binario)
            continue
        if _maquina() not in pacotes:
            raise RuntimeError("o QEMU da Espressif só tem binário pra Linux x86_64 e aarch64 (aqui: %s)"
                               % _maquina())
        nome, soma, _ = pacotes[_maquina()]
        pacote = fer.baixar(RELEASE + nome, soma, fe / "qemu-esp" / nome, diga)
        diga("  extraindo %s" % nome)
        fer.extrair(pacote, fe / "qemu-esp")
        pacote.unlink()
    for nome, soma, _ in FIRMWARE.values():   # se já tem e o sha256 bate, não baixa de novo
        fer.baixar(MICROPYTHON + nome, soma, fe / "micropython" / nome, diga)
    for binario in QEMU:
        r = subprocess.run([str(_bin(fe, binario)), "--version"], capture_output=True, text=True,
                           timeout=20, env=fer.ambiente())
        diga("  %s: %s" % (binario, (r.stdout.splitlines() or ["não respondeu: " + r.stderr[-200:]])[0]))


def _pasta_emulador(trabalho):
    """onde ficam imagem, sockets e FIFO: trabalho/emu (socket unix aceita no máximo 107 caracteres)"""
    pasta = Path(trabalho) / "emu"
    if len(str(pasta / "monitor.sock")) > 100:
        pasta = fer.temporaria() / ("qemu%d" % os.getpid())
    return pasta


def _preludio(pedido, chip):
    placa, E, V = pedido.placa, {}, {}
    for e in pedido.entradas:
        if "pino" in e:
            n = placa.numero(e["pino"])
            if "volts" in e:
                V.setdefault(n, []).append((int(e["t_ms"]), float(e["volts"])))
            else:
                E.setdefault(n, []).append((int(e["t_ms"]), int(e["valor"])))
    dados = {"M": chip["gpio"], "E": E, "V": V, "ADC": ADC_PINOS.get(placa.id, ADC_PINOS[pedido.alvo]),
             "T": TROCA.get(placa.id, {})}
    fonte = (PASTA / "preludio.py").read_text(encoding="utf-8")
    return fonte + "\n_sv_roda = _sv_instala(%r)\ndel _sv_instala\n" % (dados,)


def _arquivos(pedido, grandes=None):
    """os arquivos do programa que vão pro sistema de arquivos do MicroPython (os grandes demais ficam fora)"""
    for a in sorted(Path(pedido.pasta).iterdir()):
        if a.is_file() and a.name != "roteiro.json":
            if a.stat().st_size <= MAX_ARQUIVO:
                yield a
            elif grandes is not None:
                grandes.append(a.name)


def _modulos(pedido):
    """os módulos que os .py do programa importam (o prelúdio carrega antes do t = 0)"""
    nomes = []
    for a in _arquivos(pedido):
        if a.suffix != ".py":
            continue
        fonte = a.read_text(encoding="utf-8", errors="replace")
        try:
            for no in ast.walk(ast.parse(fonte)):
                if isinstance(no, ast.Import):
                    nomes += [x.name for x in no.names]
                elif isinstance(no, ast.ImportFrom) and no.module and not no.level:
                    nomes.append(no.module)
        except SyntaxError:   # o MicroPython é quem vai reclamar; aqui só um palpite
            nomes += re.findall(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", fonte, re.M)
    proprio = Path(pedido.principal).stem
    return tuple(dict.fromkeys(n for n in nomes if n != proprio))


def rodar(pedido):
    inicio = time.monotonic()
    falta = faltando(pedido.ferramentas) if pedido.alvo in emu.CHIPS else ["o alvo %s" % pedido.alvo]
    if falta:
        yield contrato.aviso(0, "falta %s: rode python3 laboratorio/lab.py instalar qemu" % "; ".join(falta),
                             "indisponivel")
        yield contrato.fim("indisponivel", NOME, pedido.placa.id, pedido.alvo, 0, time.monotonic() - inicio)
        return
    eventos, final = _sessao(pedido, inicio)
    yield from eventos
    yield final


def _sessao(pedido, inicio):
    """sobe, roda e desliga o QEMU -> (eventos, fim); o QEMU morre aqui, aconteça o que acontecer"""
    chip, fe, q, r = emu.CHIPS[pedido.alvo], Path(pedido.ferramentas), None, None
    pasta = _pasta_emulador(pedido.trabalho)
    infos, antes, grandes = [], None, []
    try:   # SIGTERM vira saída normal: o finally desliga o QEMU e apaga sockets e FIFO
        antes = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(SystemExit(143)))
    except ValueError:   # fora da thread principal: fica o PR_SET_PDEATHSIG do esp32emu
        pass
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        flash = emu.imagem(fe / "micropython" / FIRMWARE[pedido.alvo][0], chip["offset"], pasta / "flash.bin")
        q = emu.Qemu(_bin(fe, chip["qemu"]), chip["maquina"], flash, pasta, env=fer.ambiente())
        emu.boot(q.serial, min(20, pedido.limite_pc_s))
        infos.append("boot do %s em %.2f s" % (chip["maquina"], time.monotonic() - inicio))
        for a in _arquivos(pedido, grandes):
            emu.gravar(q.serial, a.name, a.read_bytes())
        _, err = emu.executar(q.serial, emu.comprimido(_preludio(pedido, chip)))
        if err.strip():
            raise emu.ErroQemu("o prelúdio do motor falhou: " + err.strip()[-400:])
        tmp105 = None
        if any("temperatura" in e for e in pedido.entradas):
            tmp105 = q.caminho_qom("tmp105") if pedido.alvo == "esp32" else None
            if not tmp105:
                infos.append("só o ESP32 do QEMU tem o sensor TMP105: as temperaturas do roteiro ficaram de fora")
        infos.append("programa gravado e prelúdio pronto em %.2f s" % (time.monotonic() - inicio))
        r = _executa(q, pedido, chip, inicio, tmp105)
        if r.get("mono_t0"):
            infos.append("t = 0 (main.py e módulos carregados) em %.2f s" % (r["mono_t0"] - inicio))
        infos.append("programa parado em %.2f s" % (r["mono_fim"] - inicio))
    except (emu.ErroQemu, TimeoutError, OSError) as e:
        r = {"estado": "travou", "problema": "o emulador não chegou a rodar o programa: %s" % e}
    finally:
        ram = max((r or {}).get("ram") or 0, (q.ram_mb() if q else 0) or 0) or None
        if q:
            q.parar()
        if antes is not None:
            signal.signal(signal.SIGTERM, antes)
        if pedido.detalhe and r and r.get("serial_bruta"):
            (pasta / "serial.log").write_bytes(r["serial_bruta"])
        if not pedido.detalhe:
            shutil.rmtree(pasta, ignore_errors=True)
    eventos, t_fim = _eventos(r, pedido)
    if grandes:
        eventos.insert(0, contrato.aviso(0, "ficou fora do chip (mais de %d KB): %s" % (
            MAX_ARQUIVO // 1024, ", ".join(grandes)), "qemu"))
    if pedido.detalhe:
        eventos = [contrato.aviso(0, i, "qemu") for i in infos] + eventos
    return eventos, contrato.fim(r["estado"], NOME, pedido.placa.id, pedido.alvo, t_fim,
                                 time.monotonic() - inicio, ram)


def _executa(q, pedido, chip, inicio, tmp105):
    """o laço do programa rodando: serial, trace, entradas do roteiro e os prazos -> dicionário do resultado"""
    ser, pinos, tempo_s = q.serial, emu.Pinos(chip), pedido.tempo_ms / 1000
    acoes = [e for e in pedido.entradas if "serial" in e or ("temperatura" in e and tmp105)]
    ser.lateral = (q.trace, pinos.alimentar)
    q.monitor("trace-event memory_region_ops_write on")
    emu.colar(ser, ("_sv_roda(%r, %r)\n" % (pedido.principal.name, _modulos(pedido))).encode())
    r = {"estado": None, "enviado": time.time(), "linhas": [], "erro": "", "queda": bytearray(),
         "hora_queda": None, "hora_fim": None, "pinos": pinos, "serial_bruta": bytearray(), "ram": None}
    fase, linha, err, queda_ate = "out", bytearray(), bytearray(), None
    ser.chegadas = [(time.time(), len(ser.buf))] if ser.buf else []
    t0 = None

    def guarda(ln, hora):
        r["linhas"].append((hora, ln.rstrip(b"\r").decode("utf-8", "replace")))

    def caiu(hora):   # daqui pra frente a serial é o relato da queda, não o programa
        nonlocal queda_ate, linha
        queda_ate, r["hora_queda"] = hora + 1.0, hora
        r["queda"] += linha
        linha = bytearray()
        if r["linhas"] and not r["linhas"][-1][1] and r["linhas"][-1][0] > hora - 0.05:
            r["linhas"].pop()   # a linha em branco que o MicroPython põe antes do relato

    proxima_ram = 0.0
    while True:
        agora = time.time()
        if agora >= proxima_ram:   # o pico de RAM, de meio em meio segundo (com swap o VmHWM do fim mente)
            r["ram"], proxima_ram = max(r["ram"] or 0, q.ram_mb() or 0) or None, agora + 0.5
        if t0 is None:
            t0 = next((h for h, c, _, _ in pinos.marcas if c == 1), None)
            r["mono_t0"] = time.monotonic() - (agora - t0) if t0 else None
        base = t0 or r["enviado"]
        if queda_ate is not None:
            if agora > queda_ate or b"Rebooting" in r["queda"]:
                r["estado"] = "travou"
                break
        elif agora >= base + tempo_s:
            r["estado"], r["hora_fim"] = "tempo", base + tempo_s
            break
        if time.monotonic() > inicio + pedido.limite_pc_s:
            r["estado"], r["problema"] = "travou", "passou do limite de %.0f s de PC" % pedido.limite_pc_s
            r["hora_fim"] = agora
            break
        while t0 and acoes and agora >= t0 + acoes[0]["t_ms"] / 1000:
            e = acoes.pop(0)
            if "serial" in e:
                ser.manda(e["serial"].encode("utf-8"))
            else:
                q.monitor("qom-set %s temperature %d" % (tmp105, round(e["temperatura"] * 1000)))
        if not ser.chegadas:   # puxa() também esvazia o trace; o que chegou durante o monitor já está lá
            try:
                ser.puxa(0.02)
            except emu.ErroQemu:
                r["estado"], r["problema"], r["hora_queda"] = "travou", "o QEMU fechou a serial", time.time()
                break
            if not ser.chegadas:
                continue
        hora, n = ser.chegadas.pop(0)
        d, ser.buf = ser.buf[:n], ser.buf[n:]
        r["serial_bruta"] += d
        if queda_ate is not None:
            r["queda"] += d
            continue
        if fase == "out":
            i = d.find(b"\x04")
            linha += d if i < 0 else d[:i]
            while b"\n" in linha and queda_ate is None:
                ln, _, resto = bytes(linha).partition(b"\n")
                if any(m in ln for m in emu.QUEDA):
                    caiu(hora)
                    break
                linha = bytearray(resto)
                guarda(ln, hora)
            if queda_ate is None and any(m in linha for m in emu.QUEDA):
                caiu(hora)
            if queda_ate is not None:
                continue
            if i >= 0:
                if linha:
                    guarda(bytes(linha), hora)
                fase, d = "err", d[i + 1:]
        if fase == "err":
            j = d.find(b"\x04")
            err += d if j < 0 else d[:j]
            if j >= 0:
                r["estado"] = "erro" if err.strip() else "acabou"
                r["hora_fim"], r["erro"] = hora, err.decode("utf-8", "replace")
                break
    # o trace chega um pouco depois: lê até passar do instante do fim (ou 0,5 s)
    corte = r["hora_fim"] or r["hora_queda"] or time.time()
    limite = time.monotonic() + 0.5
    while time.monotonic() < limite and (pinos.ultima_hora < corte or
                                         (r["estado"] in ("acabou", "erro") and
                                          not any(c == 2 for _, c, _, _ in pinos.marcas))):
        if select.select([q.trace], [], [], 0.05)[0]:
            try:
                pinos.alimentar(os.read(q.trace, 1 << 16))
            except BlockingIOError:
                pass
    r["t0"] = t0 or next((h for h, c, _, _ in pinos.marcas if c == 1), None)
    r["mono_fim"] = time.monotonic()
    return r


def _traceback(texto):
    """tira do traceback as linhas do prelúdio (<stdin> e <string>): sobra o que é do programa"""
    linhas = texto.replace("\r", "").strip("\n").split("\n")
    return "\n".join(ln for ln in linhas if 'File "<stdin>"' not in ln and 'File "<string>"' not in ln)


def _queda(bruto):
    """o relato do pânico do ESP-IDF em poucas linhas: o motivo, onde parou e se reiniciou"""
    linhas = [x.strip() for x in bruto.decode("utf-8", "replace").replace("\r", "").split("\n") if x.strip()]
    chave = [x for x in linhas if any(m in x for m in ("Guru Meditation", "abort() was called", "Brownout",
                                                       "rst:0x", "soft reboot"))]
    achados = (re.match(r"(MEPC|PC)\s*:\s*(0x[0-9a-fA-F]+)", x) for x in linhas)
    pc = ["parou em %s = %s" % m.groups() for m in achados if m]
    fim = "o chip reiniciou" if any("Rebooting" in x or "rst:0x" in x for x in linhas) else ""
    partes = (chave[:2] or linhas[:3]) + pc[:1] + ([fim] if fim else [])
    return "o chip caiu: " + "\n".join(partes) + "\n(relato inteiro com -v, em build/.../emu/serial.log)"


def _eventos(r, pedido):
    """resultado do laço -> (eventos do contrato em ordem, tempo de placa do fim em ms)"""
    if r is None or "pinos" not in r:
        texto = (r or {}).get("problema", "o emulador não rodou")
        return [{"t_ms": 0.0, "tipo": "erro", "texto": texto}], 0.0
    pinos, base = r["pinos"], r["t0"] or r["enviado"]

    def t(hora):
        return round(max(0.0, (hora - base) * 1000), 3)

    marca_fim = next((h for h, c, _, _ in pinos.marcas if c == 2), None)
    if r["estado"] == "tempo":
        t_fim = pedido.tempo_ms
    elif r["estado"] in ("acabou", "erro") and marca_fim and r["t0"]:
        t_fim = t(marca_fim)
    else:
        t_fim = t(r["hora_queda"] or r["hora_fim"] or time.time())
    ev = [dict(e, t_ms=t(h)) for h, e in pinos.eventos if h >= base]
    volta = {"GPIO%d" % c: "GPIO%d" % p for p, c in TROCA.get(pedido.placa.id, {}).items()}
    trocados = sorted({e["pino"] for e in ev if e["pino"] in volta})
    for e in ev:
        e["pino"] = volta.get(e["pino"], e["pino"])
    if trocados:
        ev.append(contrato.aviso(0, "o C3 do QEMU não tem %s do C6: rodaram no %s do C3" % (
            " e ".join(volta[x] for x in trocados), " e ".join(trocados)), "aproximado"))
    avisou = False
    for h, c, p, a in pinos.marcas:
        if c == 3 and a in MODOS and h >= base:
            ev.append({"t_ms": t(h), "tipo": "modo", "pino": "GPIO%d" % p, "modo": MODOS[a]})
        elif c == 5 and not avisou:
            ev.append(contrato.aviso(t(h), AVISO_ADC, "adc_falso"))
            avisou = True
        elif c == 6:
            ev.append(contrato.aviso(t(h), AVISO_WIFI, "sem_wifi"))
    # a serial chega aqui uns ms depois da marca do fim: o que veio antes do \x04 é do programa. Um traceback
    # na serial é erro dentro de callback (Pin.irq, Timer): o programa seguiu, como na placa; vira evento erro
    linhas, i = r["linhas"], 0
    while i < len(linhas):
        h, x = linhas[i]
        if x.strip() == "Traceback (most recent call last):":
            j = i + 1
            while j < len(linhas) and linhas[j][1].startswith("  "):
                j += 1
            texto = _traceback("\n".join(y for _, y in linhas[i:j + 1]))
            ev.append({"t_ms": min(t(h), t_fim), "tipo": "erro", "texto": "erro dentro de um callback (Pin.irq ou "
                       "Timer); na placa o traceback sai na serial e o programa segue rodando:\n" + texto})
            i = j + 1
            continue
        ev.append({"t_ms": min(t(h), t_fim), "tipo": "serial", "dir": "tx", "texto": x, "porta": "uart0"})
        i += 1
    if not r["t0"] and r["estado"] != "erro":   # erro de sintaxe: o programa nem começou
        ev.append(contrato.aviso(0, "não vi a marca de começo do programa: os tempos contam do envio", "qemu"))
    if r.get("erro"):
        ev.append({"t_ms": t_fim, "tipo": "erro", "texto": _traceback(r["erro"])})
    if r["queda"]:
        ev.append({"t_ms": t_fim, "tipo": "erro", "texto": _queda(r["queda"])})
    if r.get("problema"):
        ev.append(contrato.aviso(t_fim, r["problema"], "limite_pc" if "limite" in r["problema"] else "qemu"))
    ev = [e for e in ev if e["t_ms"] <= t_fim]
    ev.sort(key=lambda e: e["t_ms"])
    return emu.agregar(ev), t_fim
