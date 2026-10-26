"""roteiro.py: o que acontece do lado de fora da placa (roteiro.json) e as conferências.

{"tempo": 3, "precisa": ["pino_saida"],                      tempo em SEGUNDOS de placa (0,001 a 600)
 "entradas": [{"t": 1.0, "pino": "BOTAO", "valor": 0},       pino por apelido ou nome físico
              {"t": 0, "pino": "POT", "volts": 1.0}, {"t": 0.5, "serial": "liga\\n"},
              {"t": 5, "luz": "LDR1", "lux": 1}],           a luz num LDR do --circuito (só o gemeo)
 "confere": [{"t": 1.25, "pino": "LED", "valor": 1},        nível no instante t
             {"t": 0.5, "pwm": "PWM", "duty": [0.2, 0.3]},   último duty até t
             {"serial": "olá", "ate": 1.5},                  alguma linha tx contém o texto (antes de 'ate')
             {"serial": "oi", "desde": 1, "ate": 2},         ... e saiu DEPOIS de 'desde' (os dois são opcionais)
             {"trocas": "LED", "min": 4, "max": 7},          mudanças de nível vindas do firmware (min/max: números)
             {"estado": "acabou"}]}                          sem isso, vale acabou ou tempo
Chaves que começam com "_" são comentário; "sobre" (no topo) descreve o roteiro.
luz: a ref de uma peça com modelo 'ldr' no placa.txt do --circuito e a luz em lux (0 = escuro). O motor põe o LDR
no circuito com essa resistência (o LDR do meio) e o pino lê o divisor de verdade. Sem --circuito, é uso errado.
trocas: o pino começa em 0; cada vez que o firmware muda o nível conta 1 (0 -> 1 -> 0 são 2 trocas; escrever
o mesmo nível de novo não conta). Conferência num instante depois do fim da rodada: se o tempo acabou antes
(estado tempo), ela falha com 'não deu pra ver'; se o programa acabou, travou ou deu erro, vale o último estado.
"""
import json
import math
from pathlib import Path

from .contrato import ESTADOS, RECURSOS
from .texto import fmt_t, num

NUM = (int, float)
TEMPO_MIN, TEMPO_MAX = 0.001, 600.0   # segundos de placa de uma rodada: o 'tempo' do roteiro e o --tempo do lab.py


def _numero(v, o_que, minimo=0.0):
    if isinstance(v, bool) or not isinstance(v, NUM) or not math.isfinite(v) or v < minimo:
        raise ValueError("%s tem que ser um número >= %s, veio %r" % (o_que, minimo, v))
    return float(v)


def tempo_valido(v, o_que="tempo"):
    """o tempo de uma rodada em segundos de placa, de TEMPO_MIN a TEMPO_MAX -> float; senão ValueError (0 não é
    'sem tempo': vira erro, como no --tempo)"""
    if isinstance(v, bool) or not isinstance(v, NUM) or not TEMPO_MIN <= v <= TEMPO_MAX:   # também pega nan e inf
        raise ValueError("%s vai de %s a %s s de placa (veio %r)" % (o_que, num(TEMPO_MIN, 3), num(TEMPO_MAX), v))
    return float(v)


def _chaves(item, aceitas, onde):
    sobra = [k for k in item if k not in aceitas and not k.startswith("_")]
    if sobra:
        raise ValueError("%s: não conheço %s" % (onde, ", ".join(sobra)))


def validar(dados):
    """confere o formato e devolve o roteiro arrumado; ValueError com a explicação se estiver errado"""
    if not isinstance(dados, dict):
        raise ValueError("o roteiro tem que ser um objeto JSON {...}")
    _chaves(dados, {"tempo", "precisa", "entradas", "confere", "sobre"}, "roteiro")
    rot = {"tempo": None, "precisa": list(dados.get("precisa", [])), "entradas": [], "confere": []}
    if dados.get("tempo") is not None:
        rot["tempo"] = tempo_valido(dados["tempo"])
    falta = [r for r in rot["precisa"] if r not in RECURSOS]
    if falta:
        raise ValueError("precisa: recurso desconhecido %s (os que existem: %s)" % (falta, ", ".join(sorted(RECURSOS))))
    for n, e in enumerate(dados.get("entradas", []), 1):
        onde = "entrada %d" % n
        if not isinstance(e, dict):
            raise ValueError("%s tem que ser um objeto" % onde)
        _chaves(e, {"t", "pino", "valor", "volts", "serial", "luz", "lux"}, onde)
        _numero(e.get("t"), onde + ": t")
        if "serial" in e:
            if not isinstance(e["serial"], str) or "pino" in e:
                raise ValueError("%s: serial é um texto, sem pino" % onde)
        elif "luz" in e or "lux" in e:
            if not (isinstance(e.get("luz"), str) and e["luz"].strip()) or "lux" not in e or \
                    any(k in e for k in ("pino", "valor", "volts")):
                raise ValueError('%s: a luz é {"t": 5, "luz": "LDR1", "lux": 1} (a ref do LDR no circuito e a luz '
                                 'em lux), sem pino' % onde)
            _numero(e["lux"], onde + ": lux")
        elif "pino" not in e or ("valor" in e) == ("volts" in e):
            raise ValueError("%s: precisa de pino e de valor (0/1) ou volts" % onde)
        elif "valor" in e and e["valor"] not in (0, 1):
            raise ValueError("%s: valor é 0 ou 1" % onde)
        elif "volts" in e:
            _numero(e["volts"], onde + ": volts")
        rot["entradas"].append(dict(e))
    for n, c in enumerate(dados.get("confere", []), 1):
        onde = "confere %d" % n
        if not isinstance(c, dict):
            raise ValueError("%s tem que ser um objeto" % onde)
        if "pwm" in c:
            _chaves(c, {"t", "pwm", "duty"}, onde)
            _numero(c.get("t"), onde + ": t")
            d = c.get("duty")
            if not (isinstance(d, list) and len(d) == 2 and all(isinstance(x, NUM) for x in d)):
                raise ValueError("%s: duty é [mínimo, máximo], como [0.2, 0.3]" % onde)
        elif "pino" in c:
            _chaves(c, {"t", "pino", "valor"}, onde)
            _numero(c.get("t"), onde + ": t")
            if c.get("valor") not in (0, 1):
                raise ValueError("%s: valor é 0 ou 1" % onde)
        elif "serial" in c:
            _chaves(c, {"serial", "desde", "ate"}, onde)
            for k in ("desde", "ate"):
                if k in c:
                    _numero(c[k], onde + ": " + k)
            if "desde" in c and "ate" in c and c["desde"] >= c["ate"]:
                raise ValueError("%s: desde (%s s) tem que vir antes do ate (%s s)" % (onde, num(c["desde"], 3),
                                                                                       num(c["ate"], 3)))
        elif "trocas" in c:
            _chaves(c, {"trocas", "min", "max"}, onde)
            if not (isinstance(c["trocas"], str) and c["trocas"].strip()):
                raise ValueError('%s: trocas é o nome do pino, como {"trocas": "LED", "min": 4, "max": 7}' % onde)
            for k in ("min", "max"):
                if k in c:
                    _numero(c[k], onde + ": " + k)
            if c.get("min", 0) > c.get("max", float("inf")):
                raise ValueError("%s: min (%s) tem que ser até o max (%s)" % (onde, num(c["min"]), num(c["max"])))
        elif "estado" in c:
            _chaves(c, {"estado"}, onde)
            est = c["estado"] if isinstance(c["estado"], list) else [c["estado"]]
            if any(e not in ESTADOS for e in est):
                raise ValueError("%s: estado é um de %s" % (onde, ", ".join(ESTADOS)))
        else:
            raise ValueError("%s: não sei conferir %r" % (onde, c))
        rot["confere"].append(dict(c))
    return rot


def ler(arquivo):
    arquivo = Path(arquivo)
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ValueError("%s não é JSON válido: %s" % (arquivo, e)) from None
    try:
        return validar(dados)
    except ValueError as e:
        raise ValueError("%s: %s" % (arquivo, e)) from None


def procurar(programa):
    """o roteiro.json da pasta do programa, se tiver"""
    programa = Path(programa)
    r = (programa if programa.is_dir() else programa.parent) / "roteiro.json"
    return r if r.is_file() else None


def vazio():
    return validar({})


def entradas(rot, placa):
    """entradas do roteiro -> entradas do Pedido (t_ms, pino físico), em ordem de tempo"""
    saida = []
    for e in rot["entradas"]:
        novo = {"t_ms": round(float(e["t"]) * 1000, 3)}
        if "serial" in e:
            novo["serial"] = e["serial"]
        elif "luz" in e:   # a ref do LDR vai como está: quem acha a peça é o motor, no circuito
            novo["luz"], novo["lux"] = e["luz"].strip(), float(e["lux"])
        else:
            novo["pino"] = placa.fisico(e["pino"])
            if "volts" in e:
                novo["volts"] = float(e["volts"])
            else:
                novo["valor"] = int(e["valor"])
        saida.append(novo)
    return sorted(saida, key=lambda e: e["t_ms"])


def espera_estado(rot):
    return any("estado" in c for c in rot["confere"])


def _nome(placa, apelido):
    p = placa.fisico(apelido)
    return p if p == str(apelido).upper() else "%s (%s)" % (apelido, p), p


def _depois_do_fim(t_ms, eventos, depois=False):
    """o instante t_ms ficou fora da rodada porque o tempo acabou antes? -> texto ou None. depois: o que se quer ver
    é DEPOIS de t_ms (o 'desde' da serial), então t_ms no fim da rodada também fica fora. Se o programa acabou,
    travou ou deu erro, a placa fica parada com os pinos como estavam: aí o último estado vale"""
    fim = eventos[-1] if eventos and eventos[-1]["tipo"] == "fim" else None
    if fim is None or fim["estado"] != "tempo":
        return None
    if t_ms > fim["t_ms"] + 0.0005:
        return "não deu pra ver: a rodada parou em %s (estado %s), antes desse instante; aumente o --tempo" % (
            fmt_t(fim["t_ms"]), fim["estado"])
    if depois and t_ms + 0.0005 >= fim["t_ms"]:
        return "não deu pra ver: a rodada parou em %s (estado %s), bem nesse instante, e não sobrou tempo de placa " \
               "depois dele; aumente o --tempo" % (fmt_t(fim["t_ms"]), fim["estado"])
    return None


def _confere(c, eventos, placa):
    """-> (ok, texto) de uma conferência"""
    if "pwm" in c or "pino" in c:
        nome, p = _nome(placa, c.get("pwm", c.get("pino")))
        t = c["t"] * 1000
        fora = _depois_do_fim(t, eventos)
        antes = [e for e in eventos if e.get("pino") == p and e["t_ms"] <= t and
                 (e["tipo"] == "pino" or ("pwm" in c and e["tipo"] == "pwm"))]
        if "pwm" in c:
            a, b = c["duty"]
            quer = "%s em %s com duty entre %s e %s" % (nome, fmt_t(t), num(a), num(b))
            if fora:
                return False, quer + ": " + fora
            if not antes:
                return False, quer + ": nunca mexeu"
            ult = antes[-1]
            duty = ult["duty"] if ult["tipo"] == "pwm" else float(ult["valor"])
            return a <= duty <= b, quer + ": viu %s" % num(duty)
        quer = "%s = %d em %s" % (nome, c["valor"], fmt_t(t))
        if fora:
            return False, quer + ": " + fora
        if not antes:
            return False, quer + ": nunca mexeu"
        return antes[-1]["valor"] == c["valor"], quer + ": viu %d" % antes[-1]["valor"]
    if "serial" in c:
        desde, ate = c.get("desde"), c.get("ate")
        quer = "serial com '%s'%s%s" % (c["serial"], " depois de %s" % fmt_t(desde * 1000) if desde is not None else "",
                                       " até %s" % fmt_t(ate * 1000) if ate is not None else "")
        tx = [e for e in eventos if e["tipo"] == "serial" and e["dir"] == "tx"]
        desde_ms = None if desde is None else desde * 1000
        ate_ms = None if ate is None else ate * 1000
        depois = [e for e in tx if desde_ms is None or e["t_ms"] > desde_ms + 0.0005]   # DEPOIS de 'desde'
        janela = [e for e in depois if ate_ms is None or e["t_ms"] <= ate_ms + 0.0005]  # o que saiu até 'ate'
        achou = [e for e in janela if c["serial"] in e["texto"]]
        if achou:
            return True, quer + ": viu '%s' em %s" % (achou[0]["texto"], fmt_t(achou[0]["t_ms"]))
        fora = (_depois_do_fim(ate_ms, eventos) if ate_ms is not None else None) or \
            (_depois_do_fim(desde_ms, eventos, depois=True) if desde_ms is not None else None)
        if fora:
            return False, quer + ": " + fora
        if not janela:
            if not tx:
                return False, quer + ": a placa não escreveu nada"
            if not depois:
                return False, quer + ": nada depois de %s (a última linha saiu em %s)" % (fmt_t(desde_ms),
                                                                                            fmt_t(tx[-1]["t_ms"]))
            return False, quer + ": nada até %s (a primeira linha %ssaiu em %s)" % (
                fmt_t(ate_ms), "depois de %s " % fmt_t(desde_ms) if desde_ms is not None else "",
                fmt_t(depois[0]["t_ms"]))
        return False, quer + ": última linha até lá '%s' (em %s)" % (janela[-1]["texto"], fmt_t(janela[-1]["t_ms"]))
    if "trocas" in c:
        nome, p = _nome(placa, c["trocas"])
        n, antes = 0, 0   # o pino começa em 0: só mudança de nível conta
        for e in eventos:
            if e["tipo"] == "pino" and e["pino"] == p and e["origem"] == "firmware":
                n, antes = n + (e["valor"] != antes), e["valor"]
        mn, mx = c.get("min", 0), c.get("max", float("inf"))
        return mn <= n <= mx, "trocas de %s entre %s e %s: viu %d" % (nome, mn, mx if mx != float("inf") else "∞", n)
    quer = c["estado"] if isinstance(c["estado"], list) else [c["estado"]]
    viu = eventos[-1]["estado"] if eventos and eventos[-1]["tipo"] == "fim" else "?"
    return viu in quer, "estado %s: viu %s" % (" ou ".join(quer), viu)


def conferir(eventos, rot, placa):
    """-> [{"ok", "texto"}] na ordem do roteiro"""
    return [dict(zip(("ok", "texto"), _confere(c, eventos, placa))) for c in rot["confere"]]


def falta_recurso(rot, recursos):
    """os recursos que o roteiro precisa e o motor não tem"""
    return [r for r in rot["precisa"] if r not in recursos]
