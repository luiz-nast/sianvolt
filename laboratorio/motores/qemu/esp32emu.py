"""esp32emu.py: o QEMU da Espressif como biblioteca do motor qemu (veio do protótipo esp32emu.py).

O que faz: escreve uma imagem de flash limpa (4 MB de 0xFF + o firmware no lugar certo, como o
'esptool merge-bin'), sobe o QEMU com a serial e o monitor em socket unix, conversa com o MicroPython
pelo raw REPL com raw-paste (que tem controle de fluxo: a UART do QEMU não tem baud e o buffer de
entrada transborda no paste normal) e lê os pinos do trace 'memory_region_ops_write' (escritas nos
registradores, com a hora do PC): GPIO (OUT/W1TS/W1TC, ENABLE e a matriz de saída) e LEDC (PWM).
O prelúdio marca o começo e o fim do programa escrevendo em GPIO_BT_SELECT (base + 0), que o QEMU
descarta: a marca sai no trace na mesma régua de tempo dos pinos.
Só biblioteca padrão; nenhum caminho fixo (quem chama diz onde ficam as ferramentas e o trabalho).
Registradores: TRM do ESP32 e do ESP32-C3 (espressif.com), conferidos no trace do QEMU 9.2.2.
"""
import base64
import os
import re
import select
import signal
import socket
import subprocess
import time
import zlib
from pathlib import Path

FLASH = 4 * 1024 * 1024
MARCA = 0x53            # byte alto das marcas do prelúdio: 0x53 cc pp aa (código, pino, argumento)
# alvo -> o que muda de um chip pro outro. sel = GPIO_FUNCn_OUT_SEL_CFG (deslocamento na base do GPIO);
# sinal_gpio = SIG_GPIO_OUT_IDX; ledc_canais = (primeiro sinal da matriz, canais, grupo, base do canal, base do timer)
CHIPS = {
    "esp32": dict(qemu="qemu-system-xtensa", maquina="esp32", offset=0x1000, gpio=0x3FF44000,
                  sel=0x530, sel_mascara=0x1FF, sinal_gpio=0x100, pinos=40, banco1=True,
                  ledc=0x3FF59000, ledc_cheio=True, res_bits=5, div_desloca=5,
                  ledc_canais=((71, 8, "hs", 0x000, 0x140), (79, 8, "ls", 0x0A0, 0x160))),
    # no C3 o QEMU não tem LEDC: as escritas caem no 'esp32c3.iomem', que lê 0. Cada escrita do
    # ESP-IDF (lê, muda um campo, escreve) leva só o campo mudado: juntamos campo a campo.
    "c3": dict(qemu="qemu-system-riscv32", maquina="esp32c3", offset=0x0, gpio=0x60004000,
               sel=0x554, sel_mascara=0xFF, sinal_gpio=0x80, pinos=22, banco1=False,
               ledc=0x60019000, ledc_cheio=False, res_bits=4, div_desloca=4,
               ledc_canais=((45, 6, "ls", 0x000, 0x0A0),)),
}
# linhas da serial que querem dizer que o chip caiu (pânico, abort); com o programa rodando, reset também
PANICO = (b"Guru Meditation", b"A fatal error occurred", b"abort() was called", b"Brownout")
QUEDA = PANICO + (b"Rebooting...", b"rst:0x", b"MPY: soft reboot")
RE_HORA = re.compile(rb"@(\d+\.\d+):")
RE_TRACE = re.compile(rb"@(\d+\.\d+):memory_region_ops_write .*?addr (0x[0-9a-f]+) value (0x[0-9a-f]+)")


class ErroQemu(RuntimeError):
    """o emulador não subiu, fechou a serial ou não respondeu"""


def imagem(firmware, offset, destino):
    """flash de 4 MB: 0xFF e o firmware no offset (0x1000 no ESP32, 0x0 no C3)"""
    dados = bytearray(b"\xff") * FLASH
    b = Path(firmware).read_bytes()
    dados[offset:offset + len(b)] = b
    Path(destino).write_bytes(dados)
    return Path(destino)


def _morre_junto():
    """no filho: se o Python morrer de repente (SIGKILL, SIGTERM), o QEMU morre junto"""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGKILL)   # PR_SET_PDEATHSIG
    except Exception:
        pass


class Qemu:
    """um QEMU rodando: serial e monitor em socket unix e o trace num FIFO, tudo dentro de 'pasta'.
    O endereço de um socket unix tem no máximo 107 bytes (sun_path); a pasta pode ser bem mais comprida (o
    laboratório numa pasta funda). Por isso o QEMU roda DENTRO da pasta e cria os sockets pelo nome curto, e o
    Python, quando o caminho inteiro não cabe, conecta pelo /proc/self/fd/<a pasta aberta>/<nome>, que é o mesmo
    arquivo com um endereço curto. Nada sai da pasta (nem vai pro /tmp)."""

    def __init__(self, binario, maquina, flash, pasta, env=None, extra=()):
        self.pasta = Path(pasta).resolve()
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.sock_serial, self.sock_mon = self.pasta / "serial.sock", self.pasta / "monitor.sock"
        self.fifo = self.pasta / "trace.fifo"
        for p in (self.sock_serial, self.sock_mon, self.fifo):
            p.unlink(missing_ok=True)
        os.mkfifo(self.fifo, 0o600)
        self.trace = os.open(self.fifo, os.O_RDONLY | os.O_NONBLOCK)   # antes do QEMU, senão ele trava no open
        self.dir_fd = os.open(self.pasta, os.O_RDONLY | os.O_DIRECTORY)   # o endereço curto dos sockets
        cmd = [str(binario), "-machine", maquina, "-display", "none", "-nic", "none",
               "-drive", "file=%s,if=mtd,format=raw" % Path(flash).resolve(),
               "-serial", "unix:%s,server=on,wait=on" % self.sock_serial.name,      # relativo: o QEMU roda na pasta
               "-monitor", "unix:%s,server=on,wait=off" % self.sock_mon.name,
               # liga o log de trace com um evento que nunca dispara; o de escrita só depois do boot
               # (no boot o SHA do bootloader faz ~500 mil escritas)
               "-trace", "esp_error_unhandled_command", "-msg", "timestamp=on", "-D", str(self.fifo)] + list(extra)
        self.erros = open(self.pasta / "qemu.err", "wb")
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=self.erros,
                                         env=env, cwd=self.pasta, preexec_fn=_morre_junto, start_new_session=True)
        except OSError:   # o binário não roda: solta o que já abriu
            os.close(self.trace)
            os.close(self.dir_fd)
            self.erros.close()
            raise
        self.serial = None
        limite = time.monotonic() + 10
        while self.serial is None:
            s = socket.socket(socket.AF_UNIX)
            try:
                s.connect(self.endereco(self.sock_serial))
                self.serial = Serial(s)
            except (FileNotFoundError, ConnectionRefusedError):
                s.close()
                if self.proc.poll() is not None or time.monotonic() > limite:
                    self.parar()
                    raise ErroQemu("o QEMU não subiu: " + self.texto_erros())
                time.sleep(0.02)

    def endereco(self, sock):
        """o endereço pro connect: o caminho inteiro se ele cabe no socket unix (107 bytes), senão o mesmo arquivo
        por /proc/self/fd/<pasta aberta>/<nome>"""
        caminho = str(sock)
        if len(os.fsencode(caminho)) <= 107:
            return caminho
        return "/proc/self/fd/%d/%s" % (self.dir_fd, Path(sock).name)

    def texto_erros(self):
        try:
            return (self.pasta / "qemu.err").read_text(errors="replace").strip()[-800:] or "(sem mensagem)"
        except OSError:
            return "(sem mensagem)"

    def monitor(self, comando, ler=False):
        """um comando no monitor HMP do QEMU; com ler=True devolve a resposta em texto"""
        resp = b""
        try:
            with socket.socket(socket.AF_UNIX) as m:
                m.settimeout(0.3)
                m.connect(self.endereco(self.sock_mon))
                m.sendall((comando + "\n").encode())
                m.settimeout(0.005)
                limite = time.monotonic() + (3 if ler else 0.05)
                while time.monotonic() < limite:
                    if self.serial and self.serial.lateral:
                        self.serial.puxa(0)   # o trace não pode encher enquanto o monitor responde
                    try:
                        d = m.recv(65536)
                    except socket.timeout:
                        if ler and resp.count(b"(qemu)") >= 2:
                            break
                        continue
                    if not d:
                        break
                    resp += d
        except OSError:
            pass
        return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", resp.decode(errors="replace")).replace("\r", "")

    def caminho_qom(self, tipo):
        """o caminho QOM de um dispositivo (ex.: o sensor 'tmp105' do ESP32) pelo 'info qom-tree'"""
        pilha = []
        for ln in self.monitor("info qom-tree", ler=True).splitlines():
            m = re.match(r"^( *)(/[^ ]+) \(([^)]+)\)", ln)
            if m:
                pilha = pilha[:len(m.group(1)) // 2] + [m.group(2)]
                if m.group(3) == tipo:
                    return "".join(pilha)
        return None

    def ram_mb(self):
        """pico de RAM (VmHWM) do QEMU, em MB"""
        try:
            for ln in Path("/proc/%d/status" % self.proc.pid).read_text().splitlines():
                if ln.startswith("VmHWM:"):
                    return round(int(ln.split()[1]) / 1024, 1)
        except (OSError, ValueError):
            pass
        return None

    def parar(self):
        """mata o QEMU e apaga sockets e FIFO (sempre; pode chamar duas vezes)"""
        if self.proc.poll() is None:
            self.proc.kill()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
        if self.serial:
            self.serial.s.close()
        if self.trace is not None:
            os.close(self.trace)
            self.trace = None
        if self.dir_fd is not None:
            os.close(self.dir_fd)
            self.dir_fd = None
        self.erros.close()
        for p in (self.sock_serial, self.sock_mon, self.fifo):
            p.unlink(missing_ok=True)


class Serial:
    """a serial do QEMU; 'lateral' = (fd, função): enquanto espera a serial, esvazia o FIFO do trace
    (cheio, ele trava o QEMU: no C3 o trace passa de 30 mil linhas por segundo)"""

    def __init__(self, sock):
        self.s, self.buf, self.lateral = sock, b"", None
        self.chegadas = None   # quando é lista: (hora do PC, bytes) de cada pedaço que entrou em buf

    def puxa(self, espera):
        limite = time.monotonic() + espera
        while True:
            fds = [self.s] + ([self.lateral[0]] if self.lateral else [])
            r, _, _ = select.select(fds, [], [], max(0.0, limite - time.monotonic()))
            if self.lateral and self.lateral[0] in r:
                try:
                    self.lateral[1](os.read(self.lateral[0], 1 << 16))
                except BlockingIOError:
                    pass
            if self.s in r:
                d = self.s.recv(65536)
                if not d:
                    raise ErroQemu("o QEMU fechou a serial")
                self.buf += d
                if self.chegadas is not None:
                    self.chegadas.append((time.time(), len(d)))
                return len(d)
            if time.monotonic() >= limite:
                return 0

    def ler_ate(self, fim, espera, quedas=()):
        """lê até achar 'fim' e devolve o que veio antes; TimeoutError, ou ErroQemu se o chip caiu"""
        limite = time.monotonic() + espera
        while True:
            i = self.buf.find(fim)
            if i >= 0:
                antes, self.buf = self.buf[:i], self.buf[i + len(fim):]
                return antes
            if any(q in self.buf for q in quedas):
                raise ErroQemu("o chip caiu: " + self.buf.decode(errors="replace")[-600:])
            resto = limite - time.monotonic()
            if resto <= 0:
                raise TimeoutError(self.buf.decode(errors="replace")[-400:])
            self.puxa(min(resto, 0.2))

    def manda(self, b):
        self.s.sendall(b)


def boot(ser, espera=20):
    """espera o '>>> ' do MicroPython e entra no raw REPL"""
    ser.ler_ate(b">>> ", espera, PANICO)
    ser.manda(b"\r\x03\x03")
    time.sleep(0.05)
    ser.manda(b"\r\x01")
    ser.ler_ate(b"raw REPL; CTRL-B to exit\r\n>", 5)
    ser.buf = b""


def colar(ser, codigo, espera=15):
    """manda o código pelo raw-paste (com controle de fluxo) e espera o 'recebi' (\\x04) do MicroPython"""
    limite = time.monotonic() + espera
    ser.manda(b"\x05A\x01")
    while len(ser.buf) < 4 and not (len(ser.buf) >= 2 and ser.buf[:2] != b"R\x01"):
        if time.monotonic() > limite:
            raise ErroQemu("o MicroPython não respondeu ao raw-paste: %r" % ser.buf[-80:])
        ser.puxa(0.2)
    if ser.buf[:2] != b"R\x01":
        raise ErroQemu("este MicroPython não tem raw-paste: %r" % ser.buf[:40])
    janela = ser.buf[2] | ser.buf[3] << 8
    ser.buf, livre, i = ser.buf[4:], janela, 0
    while i < len(codigo):
        while livre == 0 or ser.buf:
            if not ser.buf:
                if time.monotonic() > limite:
                    raise ErroQemu("o MicroPython parou de pedir o código (raw-paste)")
                ser.puxa(0.2)
                continue
            c, ser.buf = ser.buf[:1], ser.buf[1:]
            if c == b"\x01":
                livre += janela
            elif c == b"\x04":
                raise ErroQemu("o MicroPython recusou o código")
        n = min(livre, len(codigo) - i)
        ser.manda(codigo[i:i + n])
        i, livre = i + n, livre - n
    ser.manda(b"\x04")
    ser.ler_ate(b"\x04", 10)


def executar(ser, codigo, espera=10):
    """roda um pedaço curto (arquivo, prelúdio) e devolve (saída, erro) em texto"""
    colar(ser, codigo.encode() if isinstance(codigo, str) else codigo)
    out = ser.ler_ate(b"\x04", espera, QUEDA)
    err = ser.ler_ate(b"\x04", espera, QUEDA)
    ser.ler_ate(b">", 5)
    return out.decode(errors="replace"), err.decode(errors="replace")


def enxuto(fonte):
    """tira linhas de comentário e linhas em branco (a serial do QEMU passa só uns 6 KB/s no raw-paste)"""
    return "\n".join(ln for ln in fonte.splitlines() if ln.strip() and not ln.lstrip().startswith("#")) + "\n"


def comprimido(fonte):
    """o código vira zlib + base64 e o MicroPython (módulo deflate, 1.21+) descomprime e roda: ~3x menos serial"""
    z = base64.b64encode(zlib.compress(enxuto(fonte).encode("utf-8"), 9)).decode()
    return ("import deflate, io, binascii\nexec(deflate.DeflateIO(io.BytesIO(binascii.a2b_base64(%r)), "
            "deflate.ZLIB).read())\n" % z)


def gravar(ser, nome, dados, pedaco=2048):
    """grava um arquivo no sistema de arquivos do MicroPython (pelo raw REPL)"""
    for i in range(0, max(len(dados), 1), pedaco):
        modo = "wb" if i == 0 else "ab"
        _, err = executar(ser, "f=open(%r,%r)\nf.write(%r)\nf.close()\n" % (nome, modo, dados[i:i + pedaco]))
        if err.strip():
            raise ErroQemu("não consegui gravar %s: %s" % (nome, err.strip()[-300:]))


def _junta(antes, v, campos, zero=0):
    """C3 sem LEDC: a escrita v mexe num campo só (o resto vem 0 da leitura); v == 0 vale pro campo 'zero'"""
    toca = [m for m in campos if v & m]
    if not toca:
        return antes & ~zero if v == 0 else antes
    if len(toca) == 1:
        return (antes & ~toca[0]) | v
    return v


CAMPOS_CONF0 = (0x3, 0x4, 0x8, 0x10)                                # timer_sel, sig_out_en, idle_lv, para_up
CAMPOS_TIMER = (0xF, 0x3FFFF0, 1 << 22, 1 << 23, 1 << 24, 1 << 25)  # duty_res, clk_div, pause, rst, tick, para_up


class Pinos:
    """lê o trace de escritas e junta (hora do PC, evento sem t_ms) de modo, pino e pwm, e as marcas"""

    def __init__(self, chip):
        self.c = CHIPS[chip] if isinstance(chip, str) else chip
        self.out, self.en, self.sel, self.ledc, self.papel = [0, 0], [0, 0], {}, {}, {}
        self.eventos, self.marcas, self.resto, self.ultima_hora = [], [], b"", 0.0
        c = self.c
        self.regs = {0x04: (0, "out", "="), 0x08: (0, "out", "|"), 0x0C: (0, "out", "~"),
                     0x20: (0, "en", "="), 0x24: (0, "en", "|"), 0x28: (0, "en", "~")}
        if c["banco1"]:   # ESP32: GPIO32-39 no banco 1
            self.regs.update({0x10: (1, "out", "="), 0x14: (1, "out", "|"), 0x18: (1, "out", "~"),
                              0x2C: (1, "en", "="), 0x30: (1, "en", "|"), 0x34: (1, "en", "~")})

    def alimentar(self, dados):
        linhas = (self.resto + dados).split(b"\n")
        self.resto = linhas.pop()
        if linhas:   # a hora da última linha diz até onde o trace já chegou
            m = RE_HORA.search(linhas[-1])
            if m:
                self.ultima_hora = max(self.ultima_hora, float(m.group(1)))
        for ln in linhas:
            if b"gpio" not in ln and b"ledc" not in ln and b"iomem" not in ln:
                continue
            m = RE_TRACE.search(ln)
            if m:
                self.escrita(float(m.group(1)), int(m.group(2), 16), int(m.group(3), 16))

    def escrita(self, hora, addr, v):
        self.ultima_hora = max(self.ultima_hora, hora)
        c, g, lc = self.c, addr - self.c["gpio"], addr - self.c["ledc"]
        if 0 <= g < 0x1000:
            if g == 0:
                if v >> 24 == MARCA:
                    self.marcas.append((hora, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF))
            elif g in self.regs:
                banco, qual, op = self.regs[g]
                lista = getattr(self, qual)
                antes = lista[banco]
                lista[banco] = v if op == "=" else antes | v if op == "|" else antes & ~v
                mudou = antes ^ lista[banco]
                for bit in range(32):
                    if mudou >> bit & 1:
                        self._atualiza(hora, bit + 32 * banco)
            elif c["sel"] <= g < c["sel"] + 4 * c["pinos"]:
                p = (g - c["sel"]) // 4
                self.sel[p] = v & c["sel_mascara"]
                self._atualiza(hora, p)
        elif 0 <= lc < 0x1000:
            antes = self.ledc.get(lc, 0)
            if c["ledc_cheio"]:
                self.ledc[lc] = v
            elif lc < 0xA0 and lc % 0x14 == 0:
                self.ledc[lc] = _junta(antes, v, CAMPOS_CONF0, zero=0x3)
            elif 0xA0 <= lc < 0xC0 and lc % 8 == 0:
                self.ledc[lc] = _junta(antes, v, CAMPOS_TIMER)
            else:
                self.ledc[lc] = v
            for p, (tipo, _) in list(self.papel.items()):
                if tipo == "pwm":
                    self._atualiza(hora, p)

    def _duty(self, sinal):
        """(duty, freq_hz) do canal do LEDC ligado no pino, ou None se ainda não dá pra calcular"""
        c, R = self.c, self.ledc.get
        for primeiro, n, grupo, base_canal, base_timer in c["ledc_canais"]:
            if primeiro <= sinal < primeiro + n:
                ch = base_canal + 0x14 * (sinal - primeiro)
                conf0 = R(ch, 0)
                tconf = R(base_timer + 8 * (conf0 & 3), 0)
                res = tconf & ((1 << c["res_bits"]) - 1)
                div = (tconf >> c["div_desloca"]) & 0x3FFFF
                if c["ledc_cheio"]:   # ESP32: tick_sel no bit 25; HS: 1 = APB 80 MHz; LS: 1 = REF_TICK 1 MHz
                    tick = tconf >> 25 & 1
                    clk = (80e6 if tick else 1e6) if grupo == "hs" else (1e6 if tick else
                                                                       80e6 if R(0x190, 0) & 1 else 8e6)
                else:                 # C3: LEDC_CONF.apb_clk_sel 1 = APB 80 MHz, 2 = RC_FAST, 3 = XTAL 40 MHz
                    clk = {2: 17.5e6, 3: 40e6}.get(R(0xD0, 1) & 3, 80e6)
                if not res:
                    return None
                duty = min(1.0, (R(ch + 8, 0) >> 4) / (1 << res))
                if c["ledc_cheio"] and not conf0 & 4:   # saída desligada: fica no nível de repouso
                    duty = float(conf0 >> 3 & 1)
                freq = round(clk * 256 / div / (1 << res), 1) if div else None
                return round(duty, 4), freq
        return None

    def _papel(self, p):
        banco, bit = divmod(p, 32)
        if not self.en[banco] >> bit & 1:
            return ("entrada", None)
        s = self.sel.get(p, self.c["sinal_gpio"])
        if s == self.c["sinal_gpio"]:
            return ("saida", self.out[banco] >> bit & 1)
        if any(a <= s < a + n for a, n, *_ in self.c["ledc_canais"]):
            return ("pwm", self._duty(s))
        return ("periferico", s)   # UART, SPI...: o nível não é do programa

    def _atualiza(self, hora, p):
        novo, antes = self._papel(p), self.papel.get(p)
        if novo == antes:
            return
        self.papel[p] = novo
        tipo, v, nome = novo[0], novo[1], "GPIO%d" % p
        if antes is None or antes[0] != tipo:
            if tipo in ("saida", "pwm") or (antes is not None and antes[0] in ("saida", "pwm")):
                modo = tipo if tipo in ("saida", "pwm") else "entrada"
                self.eventos.append((hora, {"tipo": "modo", "pino": nome, "modo": modo}))
        if tipo == "saida":
            self.eventos.append((hora, {"tipo": "pino", "pino": nome, "valor": v, "origem": "firmware"}))
        elif tipo == "pwm" and v is not None:
            self.eventos.append((hora, {"tipo": "pwm", "pino": nome, "duty": v[0], "freq_hz": v[1]}))


def agregar(eventos, janela=100.0, limite=10):
    """um pino do firmware que troca mais de 'limite' vezes numa janela de 'janela' ms vira um evento pwm
    por janela (duty = tempo alto / janela): o contrato não quer mais que ~100 eventos/s por pino"""
    por_pino = {}
    for i, e in enumerate(eventos):
        if e["tipo"] == "pino" and e.get("origem") == "firmware":
            por_pino.setdefault(e["pino"], []).append(i)
    tirar, novos = set(), []
    for pino, idx in por_pino.items():
        if len(idx) <= limite:
            continue
        janelas = {}
        for i in idx:
            janelas.setdefault(int(eventos[i]["t_ms"] // janela), []).append(i)
        nivel, ultimo, rajada = 0, None, None
        for j in sorted(janelas):
            lista, t0 = janelas[j], j * janela
            if rajada is not None and len(lista) <= limite:   # acabou a rajada: o nível em que o pino ficou
                novos.append(dict(eventos[rajada], t_ms=eventos[rajada]["t_ms"]))
                rajada = None
            if len(lista) > limite:
                alto, t, v = 0.0, t0, nivel
                for i in lista:
                    alto += (eventos[i]["t_ms"] - t) * v
                    t, v = eventos[i]["t_ms"], eventos[i]["valor"]
                alto += (t0 + janela - t) * v
                duty = round(alto / janela, 3)
                if ultimo is None or abs(duty - ultimo) > 0.01:
                    novos.append({"t_ms": max(t0, eventos[lista[0]]["t_ms"]) if ultimo is None else t0,
                                  "tipo": "pwm", "pino": pino, "duty": duty,
                                  "freq_hz": round(len(lista) / 2 / (janela / 1000), 1)})
                    ultimo = duty
                tirar.update(lista)
                rajada = lista[-1]
            else:
                ultimo = None
            nivel = eventos[lista[-1]]["valor"]
        if rajada is not None:
            novos.append(dict(eventos[rajada]))
    if not tirar:
        return eventos
    juntos = [e for i, e in enumerate(eventos) if i not in tirar] + novos
    return sorted(juntos, key=lambda e: e["t_ms"])
