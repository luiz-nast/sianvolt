"""teste_nucleo.py: testes do núcleo com o motor de mentira (nucleo/mentira.py): python3 laboratorio/nucleo/teste_nucleo.py
Escreve só em laboratorio/build/; não mexe no catálogo nem em exemplos/; não usa rede."""
import contextlib, hashlib, io, json, os, shutil, subprocess, sys, tarfile, time  # noqa: E401
from pathlib import Path
from unittest import mock

LAB = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True   # sem .pyc: nada escrito fora de build/
sys.path.insert(0, str(LAB))
import lab  # noqa: E402
import motores  # noqa: E402
from nucleo import contrato, ferramentas as fer, mentira, placas, preparar, roteiro  # noqa: E402
from nucleo.mentira import pin  # noqa: E402

AQUI = fer.BUILD / ".tmp" / "teste_nucleo"
CONTA = {"ok": 0, "falha": 0}


def certo(cond, o_que):
    CONTA["ok" if cond else "falha"] += 1
    if not cond:
        print("  FALHA:", o_que)


def recusa(f, *args):   # True se f(*args) levanta ValueError (EventoInvalido também é)
    try:
        f(*args)
    except ValueError:
        return True
    return False


def programa(nome, modo, roteiro_json=None):
    pasta = AQUI / "exemplos" / nome
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "main.py").write_text("# modo: %s\nfrom placa import *\n" % modo)
    (pasta / (nome + ".ino")).write_text("// modo: %s\n#include \"placa.h\"\n" % modo)
    if roteiro_json is not None:
        (pasta / "roteiro.json").write_text(json.dumps(roteiro_json))
    return pasta


def main_quieto(*args):
    """lab.main sem sujar a tela e sem terminal -> (código, stdout, stderr)"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(sys, "stdin", io.StringIO()):
        codigo = lab.main([str(a) for a in args])
    return codigo, out.getvalue(), err.getvalue()


def teste_apelidos():
    # pinos de boot, só-entrada e ADC1 conferidos nos datasheets (ver nucleo/placas.py)
    regras = {"esp32": ({0, 2, 5, 12, 15}, set(range(34, 40)), set(range(32, 40))),
              "c3": ({2, 8, 9}, set(), set(range(0, 5))), "s3": ({0, 3, 45, 46}, set(), set(range(1, 11))),
              "c6": ({4, 5, 8, 9, 15}, set(), set(range(0, 7)))}
    for p in placas.PLACAS.values():
        for a in placas.APELIDOS:
            fis = p.fisico(a)
            certo(fis in p.pinos and p.fisico(a.lower()) == fis, "%s: %s -> %s existe" % (p.id, a, fis))
            certo(p.fisico(fis) == fis and a in p.apelidos_do(fis), "%s: %s volta pro apelido" % (p.id, fis))
            boot, so_entrada, adc1 = regras.get(p.id, (set(), set(), None))
            n = p.numero(fis)
            certo(n not in boot, "%s: %s (%s) não é pino de boot" % (p.id, a, fis))
            certo(a in ("BOTAO", "POT") or n not in so_entrada, "%s: %s não é só-entrada" % (p.id, a))
            certo(a != "POT" or adc1 is None or n in adc1, "%s: POT no ADC1" % p.id)
    e, n, pi = placas.PLACAS["esp32"], placas.PLACAS["nano"], placas.PLACAS["pico"]
    certo(e.fisico("IO23") == e.fisico("23") == "GPIO23" and e.fisico("GPIO99", None) is None, "grafias do ESP32")
    certo(n.fisico("13") == "D13" and n.fisico("D14") == n.fisico("a0") == "A0" and n.numero("A0") == "A0", "Nano")
    certo(pi.fisico("GPIO25") == pi.fisico(25) == "GP25" and pi.numero("GP26") == 26, "Pico")
    certo(recusa(e.fisico, "XYZ") and recusa(n.fisico, "D22") and recusa(pi.fisico, "GP23"), "pino que não existe")


def teste_valida():
    bom = pin(1, True, "GPIO2")
    certo(contrato.valida(bom) == dict(bom, t_ms=1.0, valor=1), "valida arruma t_ms e True")
    for ev in [{"tipo": "pino"}, {"t_ms": 0}, {"t_ms": 0, "tipo": "piscou"}, {"t_ms": -1, "tipo": "erro", "texto": ""},
               pin(0, 2), {"t_ms": 0, "tipo": "pwm", "pino": "GPIO2", "duty": 1.5, "freq_hz": None},
               {"t_ms": 0, "tipo": "fim", "estado": "acabou"}, "texto solto"]:
        certo(recusa(contrato.valida, ev), "valida devia recusar %r" % (ev,))


def teste_conferencias():
    ev = [pin(0.0, 1), {"t_ms": 0.0, "tipo": "pwm", "pino": "GPIO23", "duty": 0.25, "freq_hz": 1000},
          {"t_ms": 300.0, "tipo": "serial", "dir": "tx", "texto": "olá 3", "porta": "uart0"},
          pin(500.0, 0), pin(900.0, 0), contrato.fim("tempo", "mentira", "esp32", "esp32", 1000, 0.1)]
    casos = [({"t": 0.25, "pino": "LED", "valor": 1}, True), ({"t": 0.75, "pino": "LED", "valor": 1}, False),
             ({"t": 0.5, "pino": "VERDE", "valor": 0}, False),        # nunca mexeu
             ({"t": 0.2, "pwm": "PWM", "duty": [0.2, 0.3]}, True), ({"t": 0.2, "pwm": "PWM", "duty": [0.7, 0.8]}, False),
             ({"t": 0.7, "pwm": "PWM", "duty": [0, 0.05]}, True),      # pino em 0 = duty 0
             ({"serial": "olá"}, True), ({"serial": "olá", "ate": 0.1}, False), ({"serial": "tchau"}, False),
             ({"trocas": "LED", "min": 2, "max": 2}, True), ({"trocas": "LED", "min": 3}, False),   # o repetido não conta
             ({"estado": "tempo"}, True), ({"estado": ["acabou", "erro"]}, False)]
    casos += [({"t": 1.5, "pino": "LED", "valor": 0}, False),   # depois do fim (estado tempo): não deu pra ver
              ({"serial": "olá", "ate": 5}, True), ({"serial": "tchau", "ate": 5}, False)]
    rot = roteiro.validar({"confere": [c for c, _ in casos]})
    res = roteiro.conferir(ev, rot, placas.PLACAS["esp32"])
    for (c, quer), r in zip(casos, res):
        certo(r["ok"] == quer, "confere %r deu %s (%s)" % (c, r["ok"], r["texto"]))
    certo("não deu pra ver" in res[-3]["texto"] and "não deu pra ver" in res[-1]["texto"],
          "depois do fim: diz que não deu pra ver: %s | %s" % (res[-3]["texto"], res[-1]["texto"]))
    certo("nada até 0,100 s" in res[7]["texto"], "serial: diz o que saiu até 'ate': %s" % res[7]["texto"])
    acabou = ev[:-1] + [contrato.fim("acabou", "mentira", "esp32", "esp32", 1000, 0.1)]
    r = roteiro.conferir(acabou, roteiro.validar({"confere": [{"t": 1.5, "pino": "LED", "valor": 0}]}),
                         placas.PLACAS["esp32"])[0]
    certo(r["ok"], "o programa acabou: o pino fica como estava, a conferência depois do fim vale (%s)" % r["texto"])
    uma = [pin(10.0, 1), pin(20.0, 1), contrato.fim("tempo", "mentira", "esp32", "esp32", 100, 0.1)]
    r = roteiro.conferir(uma, roteiro.validar({"confere": [{"trocas": "LED", "min": 1, "max": 1}]}),
                         placas.PLACAS["esp32"])[0]
    certo(r["ok"], "trocas: 0 -> 1 uma vez só é 1 troca (%s)" % r["texto"])
    esp = placas.PLACAS["esp32"]
    forca = [{"t_ms": 0.0, "tipo": "modo", "pino": "GPIO23", "modo": "saida"}, pin(1.0, 1),
             pin(5.0, 0, "GPIO23", "roteiro"), {"t_ms": 6.0, "tipo": "adc", "pino": "GPIO34", "volts": 7.5,
                                                 "origem": "roteiro"}]
    cods = [e.get("codigo") for e in contrato._conferir_entradas(forca, esp) if e["tipo"] == "aviso"]
    certo(cods == ["curto", "tensao"], "roteiro forçando pino de saída e 7,5 V na ESP32 viram aviso: %r" % cods)
    for ruim in ({"tempo": -1}, {"precisa": ["voar"]}, {"entradas": [{"t": 0, "pino": "LED"}]},
                 {"confere": [{"t": 1, "pwm": "PWM", "duty": 0.5}]}, {"confere": [{"olha": 1}]}, {"extra": 1}):
        certo(recusa(roteiro.validar, ruim), "roteiro devia recusar %r" % ruim)


def pedido(pasta, entradas, tempo_ms, **extra):
    p, trab = placas.PLACAS["esp32"], AQUI / "trabalho"
    pasta_p, princ = preparar.preparar(p, "micropython", pasta, trab)
    return contrato.Pedido(p, "esp32", "micropython", pasta_p, princ, entradas, tempo_ms, trab, AQUI, **extra)


def teste_roteiro_e_fim():
    rot = roteiro.validar({"entradas": [{"t": 1.0, "pino": "BOTAO", "valor": 0}, {"t": 0, "pino": "POT", "volts": 1.0},
                                        {"t": 0.5, "serial": "liga\n"}, {"t": 9, "pino": "BOTAO", "valor": 1}]})
    ent = roteiro.entradas(rot, placas.PLACAS["esp32"])
    certo([e["t_ms"] for e in ent] == [0, 500, 1000, 9000] and ent[2]["pino"] == "GPIO4", "entradas em ordem, físicas")
    pasta = programa("insercao", "pisca")
    ev = contrato.executar(mentira.motor(), pedido(pasta, ent, 2000))
    do_rot = [e for e in ev if e.get("origem") == "roteiro" or e.get("dir") == "rx"]
    certo(len(do_rot) == 3, "3 eventos do roteiro (o de 9 s fica fora; o do motor é trocado): %r" % do_rot)
    botao = [e for e in ev if e.get("pino") == "GPIO4"]
    certo(botao and botao[0]["nome"] == "BOTAO" and botao[0]["t_ms"] == 1000.0, "BOTAO inserido com nome")
    depois = ev[ev.index(botao[0]) + 1]
    certo(depois["t_ms"] == 1000.0 and depois["origem"] == "firmware", "no mesmo instante, o roteiro vem antes")
    certo(any(e["tipo"] == "adc" and e["nome"] == "POT" and e["volts"] == 1.0 for e in ev), "adc do roteiro")
    certo(any(e["tipo"] == "serial" and e["dir"] == "rx" and e["texto"] == "liga" for e in ev), "serial rx sem \\n")
    certo(ev[-1]["tipo"] == "fim" and [e["tipo"] for e in ev].count("fim") == 1, "um fim, no fim")
    certo(all(ev[i]["t_ms"] <= ev[i + 1]["t_ms"] for i in range(len(ev) - 1)), "em ordem de tempo")
    certo(all(contrato.valida(e) == e for e in ev), "tudo valida")
    (pasta / "main.py").write_text("# modo: trava\n")
    ev = contrato.executar(mentira.motor(), pedido(pasta, [], 1000))
    certo(ev[-1]["estado"] == "travou" and contrato.codigo_saida(ev, []) == contrato.TRAVOU, "sem fim = travou")
    desligou, m = [], mentira.motor()

    def sem_fim(ped):   # motor que nunca para: o lab.py corta no limite e o finally do motor roda
        try:
            for i in range(10 ** 6):
                time.sleep(0.01)
                yield pin(i, i % 2)
        finally:
            desligou.append(True)
    m.rodar, inicio = sem_fim, time.monotonic()
    with mock.patch.object(contrato, "FOLGA_PC_S", 0):
        ev = contrato.executar(m, pedido(pasta, [], 1000, limite_pc_s=0.3))
    certo(ev[-1]["estado"] == "travou" and ev[-2]["codigo"] == "limite_pc" and desligou and
          time.monotonic() - inicio < 1, "limite de PC: corta, avisa e o motor desliga")


def teste_codigos():
    m, pisca = mentira.motor(), {"tempo": 3, "precisa": ["pino_saida"], "confere": [
        {"t": 0.25, "pino": "LED", "valor": 1}, {"t": 0.75, "pino": "LED", "valor": 0}, {"trocas": "LED", "min": 4, "max": 7}]}
    casos = [("pisca", "pisca", pisca, 0), ("erro", "erro", {}, 1), ("trava", "trava", {}, 3), ("torto", "torto", {}, 3),
             ("falha", "pisca", {"confere": [{"t": 0.25, "pino": "LED", "valor": 0}]}, 4),
             ("indisponivel", "indisponivel", {}, 5), ("espera_erro", "erro", {"confere": [{"estado": "erro"}]}, 0)]
    guardado = {p.id: p.motores for p in placas.PLACAS.values()}
    for p in placas.PLACAS.values():
        p.motores = {lin: ["mentira"] for lin in p.motores}
    motores.usar({"mentira": m})
    try:
        for nome, modo, rot, quer in casos:
            pasta = programa(nome, modo, rot)
            for placa in ("esp32", "c6", "nano", "pico"):
                codigo, out, err = main_quieto("rodar", placa, pasta)
                certo(codigo == quer, "rodar %s %s: código %s, queria %s\n%s%s" % (placa, nome, codigo, quer, out, err))
        codigo, out, err = main_quieto("rodar", "c6", AQUI / "exemplos" / "pisca", "--json")
        linhas = [json.loads(x) for x in out.splitlines()]
        certo(codigo == 0 and linhas[-1]["tipo"] == "conferencias" and linhas[-1]["ok"] == 3, "--json com conferências")
        certo(any(e.get("codigo") == "aproximado" for e in linhas), "aviso do alvo aproximado (c6 no c3)")
        certo(all(contrato.valida(e) for e in linhas), "--json valida linha a linha")
        certo(main_quieto("instalar", "mentira")[:2] == (0, "já tem\n"), "instalar: já tem")
        m.faltando = lambda fe: ["node (90 MB)"]
        m.instalar = mock.Mock(side_effect=fer.PrecisaDe("node", "brew install node"))
        motores.usar({"mentira": m})
        with mock.patch.dict(os.environ, LAB_FERRAMENTAS=str(AQUI / "ferramentas")):   # o du fica pequeno
            codigo, out, err = main_quieto("instalar", "mentira")
        certo(codigo == 5 and "rode: brew install node" in out, "instalar sem terminal só mostra o comando\n" + out)
        codigo, out, err = main_quieto("rodar", "esp32", AQUI / "exemplos" / "pisca")
        certo(codigo == 5 and "lab.py instalar mentira" in err, "motor faltando: 5 e o comando de instalar")
        m.faltando = lambda fe: []
        shutil.rmtree(AQUI / "exemplos")
        programa("pisca", "pisca", pisca)
        programa("pwm", "pisca", {"tempo": 2, "precisa": ["pwm"], "confere": [{"t": 0.5, "pwm": "PWM", "duty": [0.2, 0.3]}]})
        motores.usar({"mentira": m})
        with mock.patch.object(lab, "EXEMPLOS", AQUI / "exemplos"):
            codigo, out, err = main_quieto("testar")
        oks = sum(linha.endswith("  ok") for linha in out.splitlines())
        certo(codigo == 0 and out.count("pulado (mentira: sem pwm)") == 11 and oks == 11,
              "testar: 11 ok (pisca em 6 placas x linguagens), 11 pulados por precisa\n" + out + err)
    finally:
        for p in placas.PLACAS.values():
            p.motores = guardado[p.id]
        motores.usar({})
    certo(main_quieto("testar")[0] == 5, "testar sem motor nenhum: 5")
    certo(len(mentira.PEDIDOS) > 40 and all(tinha for _, tinha in mentira.PEDIDOS), "o programa chega com placa.py/.h")
    certo(motores.conferir(m, "mentira") == [], "motor de mentira segue a interface")
    del m.rodar
    certo(motores.conferir(m, "mentira") != [], "motor sem rodar é recusado")


def teste_vagas():
    base = AQUI / "vagas" / "codigo"
    with fer.vaga(base) as a, fer.vaga(base) as b, fer.vaga(base) as c:
        certo(a == base and b.name == "codigo~2" and c.name == "codigo~3", "rodadas iguais em paralelo: uma vaga "
              "cada (%s, %s, %s)" % (a.name, b.name, c.name))
    with fer.vaga(base) as d:
        certo(d == base, "a vaga volta a ficar livre no fim da rodada")
    for ruim in ("-1", "0", "1e9", "nan", "abc"):
        try:
            codigo = main_quieto("rodar", "esp32", AQUI / "exemplos", "--tempo", ruim)[0]
        except SystemExit as e:
            codigo = e.code
        certo(codigo == contrato.USO, "--tempo %s é uso errado (2), deu %s" % (ruim, codigo))


def teste_ferramentas():
    falta, diz = fer.PrecisaDe("nada", "true"), []

    def tty(resposta):
        return mock.Mock(isatty=lambda: True, readline=lambda: resposta)
    certo(fer.pedir(falta, diz.append, io.StringIO()) is False and "  rode: true" in diz, "sem terminal: só mostra")
    certo(fer.pedir(falta, diz.append, tty("n\n")) is False and "Posso rodar: true? [s/N] " in diz, "pergunta e respeita")
    certo(fer.pedir(falta, diz.append, tty("s\n")) is True, "com 's', roda o comando")
    arq = AQUI / "dados.bin"
    arq.write_bytes(b"x" * 5000)
    soma = hashlib.sha256(arq.read_bytes()).hexdigest()
    certo(fer.baixar("https://github.com/x/y/releases/z.bin", soma, arq, diz.append) == arq, "já tem: não baixa")
    certo(recusa(fer.baixar, "https://exemplo.com/z.bin", "0" * 64, AQUI / "z.bin", diz.append), "fonte fora da lista")
    with tarfile.open(AQUI / "pacote.tar.gz", "w:gz") as t:
        t.add(arq, "pasta/dados.bin")
    fer.extrair(AQUI / "pacote.tar.gz", AQUI / "extraido")
    certo((AQUI / "extraido" / "pasta" / "dados.bin").stat().st_size == 5000, "extrair .tar.gz")
    certo(fer.du(AQUI / "extraido") >= 5000 and (fer.memoria_livre_mb() or 0) > 0, "du e memória livre")
    certo(fer.ambiente()["TMPDIR"].startswith(str(fer.BUILD)), "TMPDIR dos filhos em build/.tmp")


def teste_catalogo_e_exemplos():
    copia, real = AQUI / "catalogo.json", placas.CATALOGO.read_bytes()
    dados = json.loads(real)
    dados["pecas"]["robocore:esp32-wifi-bluetooth"]["preco"] = 12.34
    copia.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    comando = ["/usr/bin/python3", str(LAB / "lab.py"), "placas"]
    saida = subprocess.run(comando, env=dict(os.environ, LAB_CATALOGO=str(copia)), capture_output=True, text=True)
    certo("R$ 12,34" in saida.stdout and saida.returncode == 0, "preço vem do catálogo (cópia)\n" + saida.stdout)
    md = subprocess.run(comando + ["--md"], capture_output=True, text=True)
    certo(md.stdout.startswith("| Placa |") and md.stdout.count("\n| **") == 6 and "R$ 12,34" not in md.stdout,
          "--md: tabela com as 6 placas e o preço de verdade")
    certo(placas.CATALOGO.read_bytes() == real, "o catálogo de verdade não mudou")
    ex = LAB / "exemplos" / "pisca"
    if ex.is_dir():
        antes = {a.name: hashlib.sha256(a.read_bytes()).hexdigest() for a in ex.iterdir()}
        preparar.preparar(placas.PLACAS["nano"], "arduino", ex, AQUI / "trabalho")
        depois = {a.name: hashlib.sha256(a.read_bytes()).hexdigest() for a in ex.iterdir()}
        h = (AQUI / "trabalho" / "pisca" / "placa.h").read_text()
        certo(antes == depois and "#define PINO_POT A0" in h and "#define ADC_MAX 1023" in h, "preparar: placa.h")
    py = preparar.placa_py(placas.PLACAS["esp32"])
    certo("PINO_LED = 23" in py and "PINO_POT = 34" in py and "VREF_MV = 3300" in py, "placa.py do esp32")


if __name__ == "__main__":
    shutil.rmtree(AQUI, ignore_errors=True)
    AQUI.mkdir(parents=True)
    for teste in (teste_apelidos, teste_valida, teste_conferencias, teste_roteiro_e_fim, teste_codigos,
                  teste_vagas, teste_ferramentas, teste_catalogo_e_exemplos):
        antes = CONTA["falha"], teste()
        print("%-28s %s" % (teste.__name__, "ok" if CONTA["falha"] == antes[0] else "FALHOU"))
    for pasta in [AQUI] + [fer.BUILD / p / "mentira" for p in placas.PLACAS]:   # o que o motor de mentira deixou
        shutil.rmtree(pasta, ignore_errors=True)
    print("%d conferências ok, %d falhas" % (CONTA["ok"], CONTA["falha"]))
    sys.exit(1 if CONTA["falha"] else 0)
