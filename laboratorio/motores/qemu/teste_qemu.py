"""teste_qemu.py: confere o motor qemu sem subir o QEMU (python3 laboratorio/motores/qemu/teste_qemu.py).

As linhas de trace abaixo são de verdade (QEMU 9.2.2, MicroPython 1.29): PWM(Pin(23)) 25% -> 75% no ESP32,
PWM(Pin(3)) no C3 (sem LEDC no QEMU: cada escrita leva um campo só) e Pin(3, OUT) piscando no C3.
O teste com o QEMU de verdade é o 'lab.py testar --motor qemu'.
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
import motores  # noqa: E402

qemu = motores.descobrir()["qemu"]
emu = qemu.emu
falhas = []


def confere(cond, texto):
    print("  %s  %s" % ("ok   " if cond else "FALHA", texto))
    if not cond:
        falhas.append(texto)


def trace(linhas):
    return "".join("704@%s:memory_region_ops_write cpu 1 mr 0x0 addr %s value %s size 4 name '%s'\n" % ln
                   for ln in linhas).encode()


ESP32_PWM = [("10.000000", "0x3ff44000", "0x53010000", "esp32.gpio"),            # marca 1: t = 0
             ("10.001000", "0x3ff59140", "0x2002730", "misc.esp32.ledc"),         # HSTIMER0: 16 bits, APB
             ("10.001100", "0x3ff59008", "0x40000", "misc.esp32.ledc"),           # HSCH0 duty = 0x4000
             ("10.001200", "0x3ff59000", "0x4", "misc.esp32.ledc"),               # HSCH0: timer 0, saída ligada
             ("10.001300", "0x3ff4458c", "0x47", "esp32.gpio"),                   # GPIO23 <- sinal 71 (HS0)
             ("10.001400", "0x3ff44024", "0x800000", "esp32.gpio"),               # GPIO23 vira saída
             ("11.001000", "0x3ff59008", "0xc0000", "misc.esp32.ledc"),           # duty 0xC000 = 75%
             ("11.002000", "0x3ff44000", "0x53020000", "esp32.gpio")]             # marca 2: fim
C3_PWM = [("5.000000", "0x600190d0", "0x1", "esp32c3.iomem"), ("5.000100", "0x600190a0", "0x9c40", "esp32c3.iomem"),
          ("5.000200", "0x600190a0", "0xd", "esp32c3.iomem"), ("5.000300", "0x600190a0", "0x2000000", "esp32c3.iomem"),
          ("5.000400", "0x600190a0", "0x0", "esp32c3.iomem"), ("5.000500", "0x60019008", "0x8000", "esp32c3.iomem"),
          ("5.000600", "0x60019000", "0x4", "esp32c3.iomem"), ("5.000700", "0x60019000", "0x10", "esp32c3.iomem"),
          ("5.000800", "0x60019000", "0x0", "esp32c3.iomem"), ("5.000900", "0x60004560", "0x2d", "esp32.gpio"),
          ("5.001000", "0x60004024", "0x8", "esp32.gpio"), ("5.100000", "0x60019008", "0x18000", "esp32c3.iomem")]
C3_PISCA = [("1.000000", "0x60004560", "0x80", "esp32.gpio"), ("1.000100", "0x60004024", "0x8", "esp32.gpio"),
            ("1.000200", "0x60004080", "0x0", "esp32.gpio"), ("1.000300", "0x60004008", "0x8", "esp32.gpio"),
            ("1.500300", "0x6000400c", "0x8", "esp32.gpio"), ("1.500400", "0x6000400c", "0x8", "esp32.gpio")]


def teste_pwm_esp32():
    p = emu.Pinos("esp32")
    dados = trace(ESP32_PWM)
    p.alimentar(dados[:300])   # em dois pedaços: a linha cortada no meio tem que juntar
    p.alimentar(dados[300:])
    pwm = [e for _, e in p.eventos if e["tipo"] == "pwm"]
    confere([e["duty"] for e in pwm] == [0.25, 0.75], "ESP32: duty 25%% e 75%% do LEDC (viu %s)" % pwm)
    confere(pwm[0]["freq_hz"] == 998.4, "ESP32: 998,4 Hz como o ESP-IDF calcula (viu %s)" % pwm[0]["freq_hz"])
    confere(not [e for _, e in p.eventos if e["tipo"] == "pino"], "ESP32: pino em PWM não vira evento de nível")
    confere([m[1] for m in p.marcas] == [1, 2] and p.marcas[0][0] == 10.0, "ESP32: marcas de começo e fim")


def teste_pwm_c3():
    p = emu.Pinos("c3")
    p.alimentar(trace(C3_PWM))
    pwm = [(e["duty"], e["freq_hz"]) for _, e in p.eventos if e["tipo"] == "pwm"]
    confere(pwm == [(0.25, 1000.0), (0.75, 1000.0)], "C3: campos juntados, 25%% e 75%% a 1000 Hz (viu %s)" % pwm)


def teste_pisca_c3():
    p = emu.Pinos("c3")
    p.alimentar(trace(C3_PISCA))
    ev = [(e["tipo"], e.get("valor", e.get("modo"))) for _, e in p.eventos]
    confere(ev == [("modo", "saida"), ("pino", 0), ("pino", 1), ("pino", 0)],
            "C3: vira saída com o nível inicial, troca só quando muda (viu %s)" % ev)
    confere(p.ultima_hora == 1.5004, "C3: sabe até onde o trace chegou")


def teste_agregar():
    ev = [{"t_ms": 0.5 * i, "tipo": "pino", "pino": "GPIO3", "valor": (i + 1) % 2, "origem": "firmware"}
          for i in range(400)]   # 200 ms trocando a cada 0,5 ms, 50% ligado
    ev.append({"t_ms": 500.0, "tipo": "pino", "pino": "GPIO3", "valor": 1, "origem": "firmware"})
    saida = emu.agregar(ev)
    pwm = [e for e in saida if e["tipo"] == "pwm"]
    confere(len(saida) < 10 and pwm and abs(pwm[0]["duty"] - 0.5) < 0.02, "rajada vira pwm 50%% (viu %s)" % pwm)
    pinos = [e for e in saida if e["tipo"] == "pino"]
    confere([e["valor"] for e in pinos][-1:] == [1] and len(pinos) == 2, "o nível depois da rajada fica")


def teste_textos():
    tb = 'Traceback (most recent call last):\r\n  File "<stdin>", line 1, in <module>\r\n  File "<string>", ' \
         'line 220, in roda\r\n  File "main.py", line 3, in <module>\r\nZeroDivisionError: divide by zero\r\n'
    confere(qemu._traceback(tb).splitlines() == ["Traceback (most recent call last):",
                                                 '  File "main.py", line 3, in <module>',
                                                 "ZeroDivisionError: divide by zero"], "traceback sem o prelúdio")
    q = qemu._queda(b"A fatal error occurred.\r\nGuru Meditation Error: Core  1 panic'ed (StoreProhibited).\r\n"
                    b"PC      : 0x40134c88  PS      : 0x00060830\r\nRebooting...\r\n")
    confere("StoreProhibited" in q and "0x40134c88" in q and "reiniciou" in q, "relato curto do pânico")
    confere(emu._junta(0xD, 0x9C40, emu.CAMPOS_TIMER) == 0x9C4D, "C3: escrita de um campo só não apaga o outro")
    fonte = emu.comprimido("# comentário\nprint('olá')\n\n")
    confere("deflate" in fonte and "comentário" not in fonte, "prelúdio vai comprimido e sem comentários")


def teste_modulos():
    pasta = RAIZ / "build" / "teste_qemu"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "main.py").write_text("from placa import *\nimport time, machine\nfrom machine import Pin\n")
    (pasta / "placa.py").write_text("NOME = 'x'\n")

    class P:
        pass
    pedido = P()
    pedido.pasta, pedido.principal = pasta, pasta / "main.py"
    confere(qemu._modulos(pedido) == ("placa", "time", "machine"), "módulos pra carregar antes do t = 0")
    confere([a.name for a in qemu._arquivos(pedido)] == ["main.py", "placa.py"], "arquivos que vão pro chip")


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("teste_"):
            print(nome)
            f()
    print("%s" % ("tudo ok" if not falhas else "%d FALHA(S)" % len(falhas)))
    sys.exit(1 if falhas else 0)
