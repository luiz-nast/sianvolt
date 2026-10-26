#!/usr/bin/env python3
"""lab.py: o laboratório de mini placas do Sianvolt. Testa firmware sem ter a placa na mão.

  python3 laboratorio/lab.py placas [--md|--json]          as 5 placas, preço, papel e motores
  python3 laboratorio/lab.py instalar [motor...] [--ver]   baixa/compila os motores (--ver só mostra)
  python3 laboratorio/lab.py rodar <placa> <programa> [--roteiro x.json] [--tempo s] [--motor m]
        [--lingua micropython|arduino] [--json] [--html f] [--circuito placa.txt] [-v]
  python3 laboratorio/lab.py testar [--placa p] [--motor m] [--exemplo e] [--rapido]
Saída: 0 ok, 1 erro no programa, 2 uso errado, 3 travou, 4 conferência falhou, 5 motor indisponível.
O --tempo vai de 0,001 a 600 s de placa (sem ele: o do roteiro, ou 5 s).
"""
import argparse
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.dont_write_bytecode = True   # sem .pyc: nada escrito fora de build/
sys.path.insert(0, str(RAIZ))
import motores  # noqa: E402
from nucleo import contrato, placas, preparar, roteiro, texto  # noqa: E402
from nucleo import ferramentas as fer  # noqa: E402
from nucleo.texto import num  # noqa: E402

PADRAO = ["gemeo", "qemu", "simavr", "nativo"]   # instalar sem nome: os motores das top 5
VIRTUAIS = {"gemeo", "nativo", "simavr"}          # tempo virtual: o que o testar --rapido roda
TEMPO_PADRAO = 5.0                                # segundos de placa sem --tempo nem roteiro
TEMPO_MAX = roteiro.TEMPO_MAX                     # o --tempo (e o 'tempo' do roteiro) mais longo: 10 min de placa
EXEMPLOS = RAIZ / "exemplos"


def diga(*a):   # sem buffer: o testar mostra cada linha na hora
    print(*a, flush=True)


def erro(msg, codigo):
    print(msg, file=sys.stderr, flush=True)
    return codigo


def situacao(nome):
    return motores.situacao(nome, fer.pasta_ferramentas())


def achar_programa(nome):   # de onde o Luiz está, ou de dentro de laboratorio/ (o --circuito também)
    return next((c.resolve() for c in (Path(nome), RAIZ / nome) if c.exists()), None)


def tempo_valido(texto):
    """--tempo: segundos de placa, de 0,001 a TEMPO_MAX (aceita vírgula); a mesma faixa do 'tempo' do roteiro"""
    try:
        t = float(str(texto).replace(",", "."))
    except ValueError:
        raise argparse.ArgumentTypeError("'%s' não é um número de segundos" % texto) from None
    if not roteiro.TEMPO_MIN <= t <= TEMPO_MAX:   # também pega nan e inf
        raise argparse.ArgumentTypeError("o tempo vai de 0,001 a %s s de placa (veio %s)" % (num(TEMPO_MAX), texto))
    return t


def tempo_da_rodada(tempo, rot):
    """o --tempo, senão o 'tempo' do roteiro (já conferido: 0,001 a TEMPO_MAX), senão TEMPO_PADRAO"""
    return next(t for t in (tempo, rot["tempo"], TEMPO_PADRAO) if t is not None)


def rodar_um(placa, programa, lingua, motor, rot, tempo_s, circuito=None, detalhe=False):
    """prepara, roda e confere -> (eventos, resultados, código de saída). ValueError = uso errado."""
    nome = programa.name if programa.is_dir() else programa.stem
    with fer.vaga(fer.BUILD / placa.id / motor.NOME / nome) as trabalho:   # rodadas em paralelo não se pisam
        return _rodar_em(trabalho, placa, programa, lingua, motor, rot, tempo_s, circuito, detalhe)


def _rodar_em(trabalho, placa, programa, lingua, motor, rot, tempo_s, circuito, detalhe):
    alvo, aviso_alvo = motores.alvo(motor, placa.id)
    pasta, principal = preparar.preparar(placa, lingua, programa, trabalho)
    pedido = contrato.Pedido(placa=placa, alvo=alvo, linguagem=lingua, pasta=pasta, principal=principal,
                             entradas=roteiro.entradas(rot, placa), tempo_ms=tempo_s * 1000, trabalho=trabalho,
                             ferramentas=fer.pasta_ferramentas(), circuito=circuito, detalhe=detalhe,
                             nomes=preparar.nomes_dos_pinos(placa, programa, lingua))
    extras = [contrato.aviso(0, aviso_alvo, "aproximado")] if aviso_alvo else []
    if circuito and "eletrica" not in motor.RECURSOS:
        extras.append(contrato.aviso(0, "o motor %s não usa o circuito (só o gemeo)" % motor.NOME, "circuito"))
    falta = roteiro.falta_recurso(rot, motor.RECURSOS)
    if falta:
        extras.append(contrato.aviso(0, "o motor %s não tem %s: essas conferências podem falhar"
                                     % (motor.NOME, ", ".join(falta)), "recurso"))
    eventos = extras + contrato.executar(motor, pedido)
    resultados = roteiro.conferir(eventos, rot, placa)
    codigo = contrato.codigo_saida(eventos, [r for r in resultados if not r["ok"]], roteiro.espera_estado(rot))
    return eventos, resultados, codigo


def cmd_rodar(a):
    placa = placas.PLACAS.get(a.placa)
    if not placa:
        return erro("placa desconhecida: %s\nplacas: %s" % (a.placa, ", ".join(placas.PLACAS)), contrato.USO)
    programa = achar_programa(a.programa)
    if not programa:
        return erro("não achei o programa %s" % a.programa, contrato.USO)
    tem = preparar.linguagens_de(programa)
    lingua = a.lingua or next((lin for lin in placa.motores if lin in tem), None)
    if lingua not in placa.motores or lingua not in tem:
        return erro("a %s roda %s; %s tem %s" % (placa.id, " ou ".join(placa.motores), programa.name,
                                                  " e ".join(sorted(tem)) or "nenhum .py/.ino"), contrato.USO)
    try:
        arq = Path(a.roteiro) if a.roteiro else roteiro.procurar(programa)
        rot = roteiro.ler(arq) if arq else roteiro.vazio()
    except (OSError, ValueError) as e:
        return erro("roteiro: %s" % e, contrato.USO)
    circuito = achar_programa(a.circuito) if a.circuito else None
    if a.circuito and not (circuito and circuito.is_file()):
        return erro("não achei o circuito %s (nem a partir daqui, nem de laboratorio/)" % a.circuito, contrato.USO)
    motor, problema = motores.escolher(placa, lingua, a.motor, rot["precisa"], fer.pasta_ferramentas())
    if problema:
        return erro(problema[1], problema[0])
    fer.esperar_memoria(400, diga=lambda m: print(m, file=sys.stderr))
    try:
        eventos, resultados, codigo = rodar_um(placa, programa, lingua, motor, rot,
                                               tempo_da_rodada(a.tempo, rot), circuito, a.v)
    except ValueError as e:
        return erro(str(e), contrato.USO)
    titulo = "%s · %s · %s · motor %s" % (placa.nome, programa.name, lingua, motor.NOME)
    if a.json:
        falhas = [r["texto"] for r in resultados if not r["ok"]]
        for ev in eventos + [{"t_ms": eventos[-1]["t_ms"], "tipo": "conferencias",
                              "ok": len(resultados) - len(falhas), "falhas": falhas}]:
            print(json.dumps(ev, ensure_ascii=False))
    else:
        diga(texto.relatorio(eventos, resultados, titulo, todos=a.v))
    if a.html:
        try:
            from pagina import html   # só quando pedido
        except ImportError as e:
            return erro("sem a página (pagina/html.py): %s" % e, codigo or contrato.USO)
        Path(a.html).write_text(html.gerar(eventos, titulo, resultados), encoding="utf-8")
        print("página: %s" % Path(a.html).resolve(), file=sys.stderr)
    return codigo


def cmd_placas(a):
    dados = []
    for p in placas.PLACAS.values():
        of = placas.ofertas(p) or []
        achados = motores.descobrir()
        como = {m: achados[m].PLACAS[p.id][0] for ms in p.motores.values() for m in ms     # roda como outro chip
                if m in achados and isinstance(achados[m].PLACAS.get(p.id), tuple)}
        dados.append({"id": p.id, "nome": p.nome, "chip": p.chip, "resumo": p.resumo, "papel": p.papel,
                      "reserva": p.reserva, "oferta": of[0] if of else None, "ofertas": len(of),
                      "lojas": len({o["loja"] for o in of}), "apelidos": p.apelidos, "radio": p.radio,
                      "dormindo": p.dormindo, "como": como,
                      "motores": {lin: {m: situacao(m) for m in ms} for lin, ms in p.motores.items()},
                      "nao_testa": list(p.nao_testa), "fontes": list(p.fontes)})
    diga(json.dumps(dados, ensure_ascii=False, indent=1) if a.json else "\n".join(texto.placas(dados, a.md)))
    return 0


def ver_ferramentas(fe):
    diga("\n".join(fer.ocupacao(fe)) + "\nMotores")
    for nome in sorted(motores.conhecidos() | set(motores.RECUSADOS)):
        diga("  %-9s %s" % (nome, "pronto" if situacao(nome) == "instalado" else situacao(nome)))
    return 0


def cmd_instalar(a):
    fe, achados, codigo = fer.pasta_ferramentas(), motores.descobrir(), 0
    if a.ver:
        return ver_ferramentas(fe)
    for nome in a.motores or PADRAO:
        m = achados.get(nome)
        if m is None:
            desconhecido = bool(a.motores) and nome not in motores.conhecidos()
            diga("%s: %s" % (nome, motores.RECUSADOS.get(nome) or ("motor desconhecido" if desconhecido else
                                                                  "ainda não existe (motores/%s.py)" % nome)))
            codigo = max(codigo, 2 if desconhecido else 1 if nome in motores.RECUSADOS else 0)
            continue
        falta, inicio = motores.faltando(m, fe), time.monotonic()
        antes = fer.du(fe) if falta else 0   # só mede o disco quando vai baixar algo
        if falta:
            fer.esperar_memoria(400, diga=diga)
        problema = motores.instalar(m, fe, diga)   # "" = faltou brew/npm e o pedir() já disse como resolver
        if problema:
            diga("%s: %s" % (nome, problema))
            codigo = max(codigo, 1 if problema.startswith("deu errado") else 0)
        sobra = motores.faltando(m, fe)
        if falta and sobra != falta:   # baixou ou compilou alguma coisa
            diga("%s: %s s, %s a mais em disco" % (nome, num(time.monotonic() - inicio, 1),
                                                   fer.tamanho(max(0, fer.du(fe) - antes))))
        if sobra:
            diga("%s: ainda falta%s %s" % (nome, "m" if len(sobra) > 1 else "", "; ".join(sobra)))
            codigo = max(codigo, contrato.INDISPONIVEL)
    return codigo


def testar_um(ex, rot, placa, lingua, m, a):
    """uma linha do testar -> (resultado, tempo de PC, RAM)"""
    falta = roteiro.falta_recurso(rot, m.RECURSOS)
    if situacao(m.NOME) != "instalado":   # o resumo do fim diz o que falta e o comando
        return "pulado (%s)" % ("falta instalar" if situacao(m.NOME).startswith("falta") else situacao(m.NOME)), "", ""
    if falta:
        return "pulado (%s: sem %s)" % (m.NOME, ", ".join(falta)), "", ""
    fer.esperar_memoria(400, diga=diga)
    try:
        eventos, resultados, codigo = rodar_um(placa, ex, lingua, m, rot, tempo_da_rodada(None, rot))
    except ValueError as e:
        return "FALHA (%s)" % e, "", ""
    fim = eventos[-1]
    ruins = [r["texto"] for r in resultados if not r["ok"]]
    res = "ok" if codigo == 0 else "FALHA (%s: %s)" % (contrato.CODIGOS[codigo], ruins[0] if ruins else fim["estado"])
    ram = "%.0f MB" % fim["ram_mb"] if fim.get("ram_mb") is not None else "-"
    return res, ("%.2f s" % fim["tempo_pc_s"]).replace(".", ","), ram


def cmd_testar(a):
    inicio, achados = time.monotonic(), motores.descobrir()
    if not achados:
        return erro("nenhum motor instalado: rode python3 laboratorio/lab.py instalar", contrato.INDISPONIVEL)
    if (a.placa and a.placa not in placas.PLACAS) or (a.motor and a.motor not in motores.conhecidos()):
        return erro("placa ou motor desconhecido (placas: %s)" % ", ".join(placas.PLACAS), contrato.USO)
    exemplos = [d for d in sorted(EXEMPLOS.glob("*/")) if d.is_dir() and a.exemplo in (None, d.name)]
    if not exemplos:
        return erro("nenhum exemplo %s em %s" % (a.exemplo or "", EXEMPLOS), contrato.USO)
    conta, formato, pulados = {"ok": 0, "FALHA": 0, "pulado": 0}, "%-9s %-5s %-11s %-9s %8s %7s  %s", {}
    diga(formato % ("exemplo", "placa", "linguagem", "motor", "PC", "RAM", "resultado"))
    for ex in exemplos:
        try:
            rot, ruim = (roteiro.ler(ex / "roteiro.json") if (ex / "roteiro.json").is_file() else roteiro.vazio()), None
        except ValueError as e:
            rot, ruim = roteiro.vazio(), str(e)
        for placa in placas.PLACAS.values():
            for lingua, nomes in placa.motores.items():
                for nome in nomes:
                    m = achados.get(nome)
                    if (a.placa not in (None, placa.id) or a.motor not in (None, nome) or m is None or
                            lingua not in preparar.linguagens_de(ex) or (a.rapido and nome not in VIRTUAIS) or
                            placa.id not in m.PLACAS or lingua not in m.LINGUAGENS):
                        continue
                    res, pc, ram = ("FALHA (%s)" % ruim, "", "") if ruim else testar_um(ex, rot, placa, lingua, m, a)
                    conta[res.split()[0]] += 1
                    if res.startswith("pulado"):
                        pulados[nome] = pulados.get(nome, 0) + 1
                    diga(formato % (ex.name, placa.id, lingua, nome, pc, ram, res))
    diga("%d ok, %d FALHA, %d pulados em %s s" % (conta["ok"], conta["FALHA"], conta["pulado"],
                                                   num(time.monotonic() - inicio, 1)))
    nao_instalados = sorted(m for m in pulados if situacao(m) != "instalado")
    if pulados:   # pulado não é ok: diga o que ficou sem testar e como resolver
        diga("ficou sem testar: %s" % ", ".join("%s (%d)" % x for x in sorted(pulados.items())))
        if nao_instalados:
            diga("  falta instalar: python3 laboratorio/lab.py instalar %s" % " ".join(nao_instalados))
    if conta["FALHA"]:
        return contrato.CONFERENCIA
    return contrato.INDISPONIVEL if pulados and not conta["ok"] else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lab.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("instalar", help="baixa e compila os motores (sem nome: %s)" % ", ".join(PADRAO))
    p.add_argument("motores", nargs="*")
    p.add_argument("--ver", action="store_true", help="só mostra o que tem, o que falta e quanto ocupa")
    p = sub.add_parser("rodar", help="roda um programa numa placa, sem a placa")
    p.add_argument("placa", help=", ".join(placas.PLACAS))
    p.add_argument("programa", help=".py, .ino ou pasta")
    for o, ajuda in (("--roteiro", "entradas e conferências (padrão: roteiro.json da pasta)"), ("--motor", None),
                     ("--html", "página de ir e voltar"), ("--circuito", "placa.txt do Sianvolt (gemeo)")):
        p.add_argument(o, help=ajuda)
    p.add_argument("--tempo", type=tempo_valido, help="segundos de placa (0,001 a %s; padrão: o do roteiro, ou %s)"
                   % (num(TEMPO_MAX), num(TEMPO_PADRAO)))
    p.add_argument("--lingua", choices=contrato.LINGUAGENS)
    p.add_argument("--json", action="store_true", help="um evento por linha")
    p.add_argument("-v", action="store_true", help="mostra tudo")
    p = sub.add_parser("placas", help="as 5 placas com preço, papel e motores")
    p.add_argument("--md", action="store_true", help="tabela Markdown pro README")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("testar", help="todo exemplo x placa x linguagem x motor instalado")
    for o in ("--placa", "--motor", "--exemplo"):
        p.add_argument(o)
    p.add_argument("--rapido", action="store_true", help="só os de tempo virtual: %s" % ", ".join(sorted(VIRTUAIS)))
    a = ap.parse_args(argv)
    fer.proteger_tmp()
    try:
        return {"instalar": cmd_instalar, "rodar": cmd_rodar, "placas": cmd_placas, "testar": cmd_testar}[a.comando](a)
    except KeyboardInterrupt:
        return erro("interrompido", 130)


if __name__ == "__main__":
    sys.exit(main())
