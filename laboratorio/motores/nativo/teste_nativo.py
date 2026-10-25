"""teste_nativo.py: confere o motor nativo (python3 laboratorio/motores/nativo/teste_nativo.py).

Parte 1, sem compilar: esboco.py (protótipos como a IDE) e eventos.py (pinos, entradas, PWM agregado).
Parte 2, de verdade (precisa do 'lab.py instalar nativo'): cada ensaio de ensaios/ com o seu roteiro.json, na
esp32 e no nano, mais o limite de PC e o Ctrl-C no meio (sem sobrar firmware rodando). Leva uns 15 s:
o 'trava' espera 3 s de CPU parado em cada placa. Tudo que escreve vai pra build/.
"""
import os
import signal
import sys
import threading
import time
from pathlib import Path

sys.dont_write_bytecode = True
RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
import lab  # noqa: E402
import motores  # noqa: E402
from nucleo import contrato, placas, preparar, roteiro  # noqa: E402
from nucleo import ferramentas as fer  # noqa: E402

ENSAIOS = Path(__file__).resolve().parent / "ensaios"
nativo = motores.descobrir()["nativo"]
esboco, eventos = nativo._sub("esboco"), nativo._sub("eventos")
falhas = []


def confere(cond, texto):
    print("  %s  %s" % ("ok   " if cond else "FALHA", texto))
    if not cond:
        falhas.append(texto)


def parte_python():
    print("esboco.py e eventos.py")
    pasta = ENSAIOS / "prototipo"
    sem, com = esboco.montar(pasta, pasta / "prototipo.ino"), esboco.montar(pasta, pasta / "prototipo.ino", True)
    confere("void mostra(int x);" in com and "void mostra(int x);" not in sem, "protótipo gerado só quando pedido")
    confere(com.index("void mostra(int x);") < com.index("void setup()"), "o protótipo vem antes do setup()")
    confere('#line 1 "prototipo.ino"' in com, "#line aponta o arquivo do Luiz, não o sketch.cpp")
    texto = 'int a = 1; // { }\nchar* s = "{";\n'
    confere(len(esboco.limpar(texto)) == len(texto) and "{" not in esboco.limpar(texto), "limpar tira { de texto")
    confere([eventos.numero(p) for p in ("GPIO23", "D13", "A0", "GP25")] == [23, 13, 14, 25], "nome físico -> número")
    confere([eventos.nome_pino(14, "uno"), eventos.nome_pino(13, "uno"), eventos.nome_pino(4, "esp32")] ==
            ["A0", "D13", "GPIO4"], "número -> nome físico (A0 = 14 no Nano)")
    args = eventos.argumentos([{"t_ms": 0, "pino": "A0", "volts": 2.5}, {"t_ms": 1000, "pino": "D2", "valor": 0},
                               {"t_ms": 500, "serial": "liga\n"}])
    confere(args == ["--entrada", "0.000 14 2500mV", "--entrada", "1000.000 2 0", "--serial", "500.000", "liga\n"],
            "entradas do Pedido -> --entrada/--serial (viu %s)" % args)
    rapido = [{"t_ms": 0.5 * i, "tipo": "pino", "pino": "GPIO3", "valor": (i + 1) % 2, "origem": "firmware"}
              for i in range(400)]   # 200 ms trocando a cada 0,5 ms: 50% ligado
    junto = eventos.agrupar(rapido, 300.0)
    pwm = [e for e in junto if e["tipo"] == "pwm"]
    confere(len(junto) <= 5 and pwm and abs(pwm[0]["duty"] - 0.5) < 0.01,
            "400 trocas em 200 ms viram %d evento(s), duty %s" % (len(junto), pwm[0]["duty"] if pwm else "-"))
    repique = [{"t_ms": t, "tipo": "pino", "pino": "GPIO4", "valor": v, "origem": "firmware"}
               for t, v in ((1000, 0), (1002, 1), (1004, 0), (1300, 1))]
    confere(eventos.agrupar(repique, 2000.0) == repique, "repique de botão (4 trocas) fica como está")


def rodar(ensaio, placa_id, rot_nome="roteiro.json"):
    placa, pasta = placas.PLACAS[placa_id], ENSAIOS / ensaio
    rot = roteiro.ler(pasta / rot_nome)
    evs, res, codigo = lab.rodar_um(placa, pasta, "arduino", nativo, rot, rot["tempo"] or 1.0)
    ruins = [r["texto"] for r in res if not r["ok"]]
    return evs, codigo, ruins


def ensaio(nome, placa_id, extra=None, rot_nome="roteiro.json"):
    evs, codigo, ruins = rodar(nome, placa_id, rot_nome)
    fim = evs[-1]
    texto = "%-13s %-5s %s, %s s de PC%s" % (nome, placa_id, fim["estado"], lab.texto.num(fim["tempo_pc_s"]),
                                            "; " + "; ".join(ruins) if ruins else "")
    ok = codigo == 0
    if ok and extra:
        msg = extra(evs)
        ok, texto = not msg, texto + ("; " + msg if msg else "")
    confere(ok, texto)
    return evs


def tipo(evs, t):
    return [e for e in evs if e["tipo"] == t]


def parte_ensaios():
    print("ensaios (compila e roda)")
    for p in ("esp32", "nano"):
        ensaio("botao_repique", p, lambda e: "contou o repique" if any("apertos: 3" in s["texto"]
                                                                       for s in tipo(e, "serial")) else "")
        ensaio("comando", p)
        ensaio("morre", p, lambda e: "" if contrato.codigo_saida(e, []) == contrato.ERRO else "sem roteiro não deu 1")
        ensaio("prototipo", p)
        ensaio("rapido", p, lambda e: "" if len([x for x in e if x.get("pino") in ("GPIO23", "D13")]) < 100
               else "inundou de eventos")
        ensaio("sintaxe", p, lambda e: "" if "sintaxe.ino:6" in tipo(e, "erro")[0]["texto"] and
               contrato.codigo_saida(e, []) == contrato.ERRO else "o erro não aponta sintaxe.ino:6")
        ensaio("trava", p, lambda e: "" if e[-1]["tempo_pc_s"] < 6 else "demorou pra ver o laço")
    ensaio("painel", "esp32")
    ensaio("painel", "nano", rot_nome="roteiro_nano.json")
    ensaio("wifi", "esp32")
    ensaio("biblioteca", "esp32", lambda e: "" if "dica:" in tipo(e, "erro")[0]["texto"] else "sem dica")
    ensaio("so_entrada", "esp32", lambda e: "" if {"so_entrada", "boot", "pino"} <= {a["codigo"] for a in
                                                                                   tipo(e, "aviso")}
           and not [x for x in tipo(e, "pino") if x["pino"] == "GPIO34"] else "faltou aviso ou GPIO34 mexeu")
    pisca = RAIZ / "exemplos" / "pisca"
    evs, _, _ = lab.rodar_um(placas.PLACAS["esp32"], pisca, "arduino", nativo, roteiro.ler(pisca / "roteiro.json"), 3)
    ts = [e["t_ms"] for e in tipo(evs, "pino")]
    confere(ts and all(abs(t - 500 * round(t / 500)) < 0.1 for t in ts),
            "exemplos/pisca na esp32: trocas a cada 500 ms de relógio virtual (%s)" % ts[:4])


def lento(nome):
    """um sketch que anda o relógio devagar e nunca acaba: pro limite de PC e pro Ctrl-C"""
    fonte = fer.BUILD / ".nativo" / "teste" / "fonte" / nome
    fonte.mkdir(parents=True, exist_ok=True)
    (fonte / (nome + ".ino")).write_text("void setup() {}\nvoid loop() { for (volatile long i = 0; i < 200000; "
                                         "i++) {} delayMicroseconds(1); }\n", encoding="utf-8")
    placa = placas.PLACAS["esp32"]
    trab = fer.BUILD / ".nativo" / "teste" / "trabalho" / nome
    pasta, principal = preparar.preparar(placa, "arduino", fonte, trab)
    return contrato.Pedido(placa=placa, alvo="esp32", linguagem="arduino", pasta=pasta, principal=principal,
                           entradas=[], tempo_ms=3600e3, trabalho=trab, ferramentas=fer.pasta_ferramentas(),
                           limite_pc_s=1.5)


def vivos(trab):
    alvo, achou = str(trab / "firmware").encode(), []
    for p in Path("/proc").iterdir():
        try:
            if p.name.isdigit() and (p / "cmdline").read_bytes().split(b"\0")[0] == alvo:
                achou.append(p.name)
        except OSError:
            pass
    return achou


def parte_limites():
    print("limite de PC e Ctrl-C")
    pedido = lento("lento")
    inicio = time.monotonic()
    evs = contrato.executar(nativo, pedido)
    gasto = time.monotonic() - inicio
    confere(evs[-1]["estado"] == "travou" and any(e.get("codigo") == "limite_pc" for e in evs) and gasto < 4,
            "1 h de placa com limite de 1,5 s de PC: %s em %s s" % (evs[-1]["estado"], lab.texto.num(gasto)))
    confere(not vivos(pedido.trabalho), "nenhum firmware sobrou depois do limite")
    pedido = lento("ctrlc")
    relogio = threading.Timer(1.0, os.kill, (os.getpid(), signal.SIGINT))
    relogio.start()
    try:
        list(nativo.rodar(pedido))
        parou = False
    except KeyboardInterrupt:
        parou = True
    relogio.cancel()
    confere(parou and not vivos(pedido.trabalho), "Ctrl-C no meio: o firmware foi desligado junto")


def main():
    fer.proteger_tmp()
    parte_python()
    falta = nativo.faltando(fer.pasta_ferramentas())
    if falta:
        print("pulei a parte 2: falta %s (rode python3 laboratorio/lab.py instalar nativo)" % "; ".join(falta))
    else:
        parte_ensaios()
        parte_limites()
    print("%s" % ("tudo certo" if not falhas else "%d FALHA(s)" % len(falhas)))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
