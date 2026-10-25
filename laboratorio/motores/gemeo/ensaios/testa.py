"""testa.py: os ensaios do gêmeo, pelo lab.py de verdade, nos dois modos (MicroPython do PC e CPython).

    python3 laboratorio/motores/gemeo/ensaios/testa.py [--rapido]     (--rapido pula o laço que trava, ~3 s cada)

Cada caso roda 'lab.py rodar <placa> <programa> --motor gemeo --json', confere o código de saída, valida cada
linha contra o contrato e procura os eventos esperados. No fim confere que não sobrou micropython rodando (só os
que este teste abriu: outros Claudes podem estar usando o laboratório) e que ferramenta/ não mudou. Sai com 0
quando tudo passa.
"""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

AQUI = Path(__file__).resolve().parent
LAB = AQUI.parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(LAB))
from nucleo import contrato  # noqa: E402

E, X = "motores/gemeo/ensaios/", "exemplos/"
MARCA = "LAB_TESTA_GEMEO=%s" % uuid.uuid4().hex   # vai no ambiente de cada rodada: acha os micropython daqui
# (placa, programa, opções, código esperado, [(tipo, campo, texto que tem que aparecer)])
CASOS = [
    ("esp32", E + "pino35", ["--tempo", "1"], 1, [("erro", "texto", "ValueError: pin can only be input"),
                                                 ("erro", "texto", 'File "main.py", line 3')]),
    ("esp32", E + "so_entrada", ["--tempo", "1"], 1, [("erro", "texto", "ValueError: pin can only be input")]),
    ("esp32", E + "divisao", ["--tempo", "1"], 1, [("erro", "texto", "ZeroDivisionError"), ("serial", "texto", "antes")]),
    ("esp32", E + "except_pelado", ["--tempo", "3"], 0, [("aviso", "codigo", "except"), ("fim", "estado", "tempo")]),
    ("esp32", E + "erros", ["--tempo", "3", "--circuito", LAB / E / "placa_erros.txt"], 1,
     [("aviso", "texto", "D2 QUEIMA"), ("aviso", "texto", "GPIO12 é pino de boot e o circuito"),
      ("aviso", "texto", "GPIO4 está flutuando"), ("aviso", "codigo", "corrente"),
      ("erro", "texto", "ValueError: pin can only be input")]),
    ("esp32", X + "pisca", ["--circuito", LAB / E / "placa_teste.txt"], 0,
     [("aviso", "texto", "D1 aceso, 5,9 mA"), ("aviso", "texto", "D1 apagado")]),
    ("c3", X + "pisca", ["--circuito", LAB / E / "circuito_c3/placa_c3.txt"], 0,
     [("aviso", "texto", "GPIO9 é pino de boot e o circuito deixa ele em 0,60 V"), ("aviso", "texto", "D1 aceso, 5,9 mA")]),
    ("c3", X + "pisca", ["--circuito", LAB / E / "placa_teste.txt"], 0,
     [("aviso", "texto", "o circuito tem um ESP32 DevKit (U1), mas a placa escolhida é o C3")]),
    ("esp32", E + "wifi_adc2", ["--tempo", "3"], 0,
     [("aviso", "codigo", "adc2_wifi"), ("serial", "texto", "ADC2 com Wi-Fi ligado: ESP_ERR_TIMEOUT"),
      ("serial", "texto", "no module named 'urequests'"), ("aviso", "texto", "conectou em 'casa'")]),
    ("esp32", E + "boot", [], 0, [("aviso", "texto", "GPIO0 é pino de boot e o roteiro deixa ele em 0")]),
    ("esp32", E + "timer", [], 0, [("aviso", "codigo", "info")]),
    ("c3", E + "i2c", [], 0, [("aviso", "texto", "GPIO9 é pino de boot"), ("serial", "texto", "temperatura 30.0")]),
    ("esp32", E + "sair", [], 0, [("fim", "estado", "acabou")]),
    ("esp32", E + "reset", ["--tempo", "1"], 3, [("aviso", "codigo", "reset"), ("fim", "estado", "travou")]),
    ("c3", E + "c3_usb", ["--tempo", "1"], 1, [("erro", "texto", "ValueError: invalid pin")]),
    ("s3", E + "s3_psram", ["--tempo", "1"], 0, [("aviso", "codigo", "psram")]),
    ("c6", E + "c6_adc", ["--tempo", "1"], 1, [("erro", "texto", "ValueError: invalid pin")]),
    ("esp32", E + "linguagem", ["--tempo", "1"], 0, {"micropython": [("serial", "texto", "NÃO aceita: dict com **")],
                                                      "cpython": [("serial", "texto", "aceita: dict com **"),
                                                                  ("aviso", "codigo", "gemeo_cpython")]}),
    ("esp32", E + "rapido", ["--tempo", "1"], 0, [("aviso", "codigo", "rapido"), ("pwm", "duty", "0.33")]),
    ("esp32", E + "laco", ["--tempo", "1"], 3, [("aviso", "codigo", "travou"), ("fim", "estado", "travou")]),
    ("esp32", E + "espera_ocupada", [], 0, [("fim", "estado", "tempo")]),
    ("s3", E + "serial_entrada", [], 0, [("serial", "texto", "ultima: tchau"), ("aviso", "codigo", "serial_entrada")]),
    ("esp32", E + "irq_erro", [], 1, [("erro", "texto", 'File "main.py", line 7, in apertou'),
                                      ("serial", "texto", "vivo 100")]),
    # só no MicroPython do PC: o CPython não tem como limitar o heap
    ("esp32", E + "memoria", ["--tempo", "1"], 1, {"micropython": [
        ("erro", "texto", "MemoryError"), ("aviso", "codigo", "memoria"),
        ("serial", "texto", "Timer(7) doesn't exist, there are only 4 hardware timers")]}),
]


def rodar(modo, placa, programa, opcoes):
    cmd = [sys.executable, str(LAB / "lab.py"), "rodar", placa, str(LAB / programa), "--motor", "gemeo", "--json"]
    inicio = time.monotonic()
    nome, valor = MARCA.split("=")
    r = subprocess.run(cmd + [str(o) for o in opcoes], capture_output=True, text=True,
                       env=dict(os.environ, LAB_GEMEO=modo, **{nome: valor}))
    return r, time.monotonic() - inicio


def conferir(r, esperado, procura):
    problemas, eventos = [], []
    if r.returncode != esperado:
        problemas.append("código %d, esperava %d (%s)" % (r.returncode, esperado, r.stderr.strip()[-200:]))
    for linha in r.stdout.splitlines():
        ev = json.loads(linha)
        if ev["tipo"] != "conferencias":
            try:
                contrato.valida(ev)
            except contrato.EventoInvalido as e:
                problemas.append("fora do contrato: %s" % e)
        eventos.append(ev)
    if not eventos or eventos[-1]["tipo"] != "conferencias" or eventos[-2]["tipo"] != "fim":
        problemas.append("a saída não termina em fim + conferencias")
    for tipo, campo, texto in procura:
        if not any(e["tipo"] == tipo and texto in str(e.get(campo)) for e in eventos):
            problemas.append("faltou %s com %s '%s'" % (tipo, campo, texto))
    fim = next((e for e in eventos if e["tipo"] == "fim"), {})
    por_segundo = {}
    for e in eventos:   # o contrato: no máximo ~100 eventos 'pino' por segundo por pino
        if e["tipo"] == "pino":
            chave = (e["pino"], int(e["t_ms"] // 1000))
            por_segundo[chave] = por_segundo.get(chave, 0) + 1
    if por_segundo and max(por_segundo.values()) > 110:
        problemas.append("pino demais: %d eventos num segundo" % max(por_segundo.values()))
    return problemas, fim


def sobrando():
    """os micropython ainda vivos que vieram deste teste (pela MARCA no ambiente), não os de outra sessão"""
    vivos = []
    for d in Path("/proc").glob("[0-9]*"):
        try:
            if (d / "comm").read_text().strip() == "micropython" and \
                    MARCA.encode() in (d / "environ").read_bytes().split(b"\0"):
                vivos.append(d.name)
        except OSError:   # o processo acabou no meio, ou é de outro usuário
            pass
    return vivos


def foto_ferramenta():
    """(caminho, tamanho, mtime) de cada arquivo de ferramenta/: comparar antes e depois diz se o teste mexeu lá
    (o git status não serve: outra sessão pode ter mudança ainda sem commit)"""
    raiz = LAB.parent / "ferramenta"
    return {str(a.relative_to(raiz)): (a.stat().st_size, a.stat().st_mtime_ns) for a in raiz.rglob("*")
            if a.is_file() and "__pycache__" not in a.parts}


def main():
    rapido = "--rapido" in sys.argv
    antes = foto_ferramenta()
    falhas, inicio = 0, time.monotonic()
    print("%-28s %-6s %-11s %3s %8s  %s" % ("caso", "placa", "modo", "rc", "PC", "resultado"))
    for modo in ("micropython", "cpython"):
        for placa, programa, opcoes, esperado, procura in CASOS:
            if rapido and programa.endswith("laco"):
                continue
            if isinstance(procura, dict) and modo not in procura:
                continue
            procura = procura[modo] if isinstance(procura, dict) else procura
            r, pc = rodar(modo, placa, programa, opcoes)
            problemas, fim = conferir(r, esperado, procura)
            if programa.endswith("laco") and fim and fim["tempo_pc_s"] > 6:   # o vigia é de 3 s de PC parado
                problemas.append("demorou pra ver o laço: %.1f s" % fim["tempo_pc_s"])
            falhas += bool(problemas)
            circuito = Path(opcoes[opcoes.index("--circuito") + 1]).stem if "--circuito" in opcoes else ""
            nome = programa.split("/")[-1] + (" +" + circuito if circuito else "")
            print("%-28s %-6s %-11s %3d %7s  %s" % (nome, placa, modo, r.returncode, ("%.2f s" % pc).replace(".", ","),
                                                     "ok" if not problemas else "FALHA: " + "; ".join(problemas)))
    vivos = sobrando()
    depois = foto_ferramenta()
    diff = ", ".join(sorted(k for k in set(antes) | set(depois) if antes.get(k) != depois.get(k)))
    print("micropython rodando depois: %s; ferramenta/ mudou: %s" % (vivos or "nenhum", diff or "não"))
    falhas += bool(vivos) + bool(diff)
    print(("%s em %.1f s" % ("tudo ok" if not falhas else "%d FALHA(S)" % falhas, time.monotonic() - inicio))
          .replace(".", ","))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
