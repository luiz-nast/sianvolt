"""gerar.py: le placa.txt e escreve modelo.json, Gerbers e Excellon.

uso: python ferramenta/gerar.py placas/estudo [-m "o que mudou"]
"""
import json
import math
import re
import sys
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path

import blocos
import geometria
from biblioteca import BIBLIOTECA
from letras import LETRAS, tracos

BORDA_FURO = 3.5   # furos de fixacao a 3,5 mm das bordas
TRILHA = 0.3       # largura das trilhas, mm
VIA_FURO = 0.4     # via (o furinho que leva a trilha de um lado pro outro): furo e cobre em volta. JLCPCB: furo de via
VIA_PAD = 0.8      # a partir de 0,3 mm; o anel de 0,2 mm passa nos 0,18 mm das nossas regras
FOLGA_ROTA = 0.25  # o roteador deixa mais que o mínimo da fábrica (0,10) entre cobres de nets diferentes
BORDA_ROTA = 0.5   # e mais que o mínimo (0,2) até a borda e os furos de fixação
CONTORNO = 0.1     # largura da linha do contorno, mm
# serigrafia, pelas regras da JLCPCB (https://jlcpcb.com/capabilities/pcb-capabilities, lido em 2026-10-23)
SILK = 0.15        # linha (>= 0,15 mm)
LETRA = 1.2        # altura da letra (>= 1,0 mm)
LETRA_LINHA = 0.2  # traco da letra (proporcao 1:6 da altura)
SILK_PAD = 0.15    # distancia minima entre serigrafia e pad
NOME_LONGE = 0.5   # o nome da peça fica a 0,5 mm dela (em cima: do corpo; dos lados: do corpo ou do pino mais pra fora)
COMANDOS = {"placa": (2, 2), "furos": (2, 2), "peca": (4, 5), "liga": (2, 2)}   # comando -> (mínimo, máximo) de valores
DO_TIPO = ("serigrafia", "cuidados", "zonas", "confira", "acompanha")   # vão do tipo pra peça, quando o tipo tem (o DevKit)
PROIBIDAS = ("antena",)   # zonas onde o roteador não passa trilha nem via, nas duas camadas
DESVIO = FOLGA_ROTA + VIA_PAD / 2 + 0.05   # a trilha que contorna uma zona proibida passa a isso da borda dela (cabe uma via)
FOLHA = "imprimir_1x1.svg"   # a placa em tamanho real pra imprimir; fica fora do fabrica.zip
REGUA = 50                   # mm da régua da folha


class ErroTxt(Exception):
    """erro no placa.txt: a linha onde aconteceu e as pecas envolvidas"""

    def __init__(self, linha, msg, onde=()):
        super().__init__(f"linha {linha}: {msg}")
        self.linha, self.msg, self.onde = linha, msg, list(onde)


def r(v):
    return round(v, 4)


# 1. ler o txt, linha por linha, guardando o numero da linha
def numero(txt, n):
    try:
        return float(txt)
    except ValueError:
        raise ErroTxt(n, f"'{txt}' devia ser um número")


NOME = re.compile(r"[A-Za-z_]\w*$")   # ref de peca e nome de net: letras, numeros e _


def valor(txt, n):
    """'100', '330', '4.7k', '10k', '1M' -> ohms"""
    t = txt.replace("Ω", "").replace("R", "").rstrip("ohm")
    mult = {"k": 1e3, "M": 1e6}.get(t[-1:], 1)
    try:
        v = float(t[:-1] if mult != 1 else t) * mult
    except ValueError:
        raise ErroTxt(n, f"'{txt}' devia ser um valor como 100, 4.7k ou 10k")
    if v <= 0:
        raise ErroTxt(n, "o valor tem que ser maior que zero")
    return v


def ler(texto):
    lido = {"placa": None, "furos": [], "pecas": {}, "ligas": [], "linhas": texto.splitlines()}
    for n, linha in enumerate(lido["linhas"], 1):
        p = linha.split("#")[0].split()
        if not p:
            continue
        cmd, args = p[0], p[1:]
        if cmd not in COMANDOS:
            raise ErroTxt(n, f"comando desconhecido '{cmd}'")
        lo, hi = COMANDOS[cmd]
        if not lo <= len(args) <= hi:
            raise ErroTxt(n, f"'{cmd}' espera {lo if lo == hi else f'{lo} ou {hi}'} valores, veio {len(args)}")
        if cmd == "placa":
            lido["placa"] = {"w": numero(args[0], n), "h": numero(args[1], n), "linha": n}
        elif cmd == "furos":
            if args[0] != "cantos":
                raise ErroTxt(n, "por enquanto só existe 'furos cantos D'")
            lido["furos"].append({"d": numero(args[1], n), "linha": n})
        elif cmd == "peca":
            ref = args[0]
            if not NOME.match(ref):
                raise ErroTxt(n, f"'{ref}' não serve de nome: só letras, números e _ (ex: R1, DevKit)")
            if ref in lido["pecas"]:
                raise ErroTxt(n, f"{ref} já existe na linha {lido['pecas'][ref]['linha']}", [ref])
            lido["pecas"][ref] = {"ref": ref, "tipo": args[1], "x": numero(args[2], n), "y": numero(args[3], n),
                                  "valor": valor(args[4], n) if len(args) > 4 else None,
                                  "valor_txt": args[4] if len(args) > 4 else None, "linha": n}
        elif cmd == "liga":
            for ponta in args:
                if not NOME.match(ponta.replace(".", "", 1)) or ponta.count(".") > 1:
                    raise ErroTxt(n, f"'{ponta}' devia ser REF.PINO ou o nome de uma net (ex: R1.2, GND)")
            lido["ligas"].append({"de": args[0], "ate": args[1], "linha": n})
    if lido["placa"] is None:
        raise ErroTxt(1, "falta a linha 'placa L A'")
    return lido


# 2. todo tipo precisa existir na biblioteca (a do repositorio ou as pecas que vieram da loja pra esta placa)
def biblioteca(pasta=None):
    return {**BIBLIOTECA, **(blocos.carregar_pecas(pasta) if pasta else {})}


def conferir_tipos(lido, bib=BIBLIOTECA):
    for p in lido["pecas"].values():
        if p["tipo"] not in bib:
            dica = " (peça da loja: escolha ela no carrinho do Sianvolt ou importe com loja.py)" if re.match(r"C\d+$", p["tipo"]) else ""
            raise ErroTxt(p["linha"], f"o tipo '{p['tipo']}' não existe na biblioteca{dica}", [p["ref"]])


# 3. montar o modelo: pinos com posicao absoluta, nets e trilhas
def forma(pad):
    if isinstance(pad, dict):   # peca da loja: ja vem {"forma": "C"|"R"|"O", ...}
        return dict(pad)
    if isinstance(pad, tuple):
        return {"forma": "R", "w": pad[0], "h": pad[1]}
    return {"forma": "C", "d": pad}


def pinos_do_tipo(tipo):
    """(n, dx, dy, pad, furo, net fixa) de cada pino, nos dois formatos da biblioteca"""
    for n, v in tipo["pinos"].items():
        if isinstance(v, dict):   # peca da loja
            yield n, v["x"], v["y"], v["pad"], v["furo"], tipo.get("pinos_fixos", {}).get(n)
        else:
            dx, dy, pad, *net = v
            yield n, dx, dy, pad, tipo["furo"], net[0] if net else None


def zona(peca, nome):
    """(x0, y0, x1, y1) na placa, em mm, de uma zona da peça (ex: a 'antena' do DevKit); None se ela não tem.
    No tipo e na peça a zona fica como os pinos no tipo: {"x": (de, até), "y": (de, até)} a partir do centro da peça"""
    z = (peca.get("zonas") or {}).get(nome)
    if not z:
        return None
    return (r(peca["x"] + z["x"][0]), r(peca["y"] + z["y"][0]), r(peca["x"] + z["x"][1]), r(peca["y"] + z["y"][1]))


def corpo_na_placa(peca):
    """o corpo da peça na placa, no formato do geometria.sobrepoe: ("ret", x0, y0, x1, y1) ou, redondo, ("circ", x, y, raio)"""
    c = peca["corpo"]
    if c["redondo"]:
        return ("circ", peca["x"], peca["y"], min(c["w"], c["h"]) / 2)
    return ("ret", peca["x"] - c["w"] / 2, peca["y"] - c["h"] / 2, peca["x"] + c["w"] / 2, peca["y"] + c["h"] / 2)


def montar(lido, bib=BIBLIOTECA):
    conferir_tipos(lido, bib)
    pecas, pinos = [], {}   # pinos: "R1.1" -> pino
    for p in lido["pecas"].values():
        tipo = bib[p["tipo"]]
        if tipo.get("valor") is not None:   # resistor da loja: o valor e o da peca comprada
            if p["valor"] is not None and p["valor"] != tipo["valor"]:
                raise ErroTxt(p["linha"], f"{p['ref']} é a peça {p['tipo']} da loja, de {blocos.ohms_txt(tipo['valor'])}; "
                                          f"o {p['valor_txt']} do txt não bate (tire o valor da linha)", [p["ref"]])
            p = {**p, "valor": tipo["valor"], "valor_txt": f"{tipo['valor']:g}"}
        loja = tipo.get("loja")
        peca = {**p, "nome": tipo["nome"], "explica": tipo["explica"], "exemplo": tipo["fonte"] is None,
                "pendente": tipo.get("pendente", []), "bloco": tipo.get("bloco"),
                "corpo": {"w": tipo["corpo"][0], "h": tipo["corpo"][1], "redondo": tipo.get("redondo", False)},
                "desenho": tipo.get("desenho"),
                "juntos": tipo.get("juntos", []), "eletrica": tipo.get("eletrica"), "compra": tipo.get("compra"),
                "loja": {k: loja.get(k) for k in ("codigo", "preco", "minimo", "link", "datasheet", "foto", "tamanho")} if loja else None,
                "pinos": []}
        peca.update({c: tipo[c] for c in DO_TIPO if c in tipo})   # as zonas ficam como no tipo: a partir do centro da peça
        for n, dx, dy, pad, furo, net in pinos_do_tipo(tipo):
            pino = {"n": n, "nome": tipo.get("nomes", {}).get(n), "x": r(p["x"] + dx), "y": r(p["y"] + dy),
                    "pad": forma(pad), "furo": furo, "net": net}
            peca["pinos"].append(pino)
            pinos[f"{p['ref']}.{n}"] = pino
        pecas.append(peca)
    fixa = {p: pino["net"] for p, pino in pinos.items() if pino["net"]}   # pinos que nasceram numa net

    # nets: cada liga junta dois grupos; um grupo pode ter nome (GND) ou ganha um (N1, N2...)
    pai, nome = {}, {}

    def raiz(a):
        while pai.setdefault(a, a) != a:
            a = pai[a]
        return a

    def junta(a, b, linha):
        ra, rb = raiz(a), raiz(b)
        na, nb = nome.get(ra), nome.get(rb)
        if na and nb and na != nb:
            raise ErroTxt(linha, f"essa ligação junta {na} com {nb} (curto)")
        if ra != rb:
            pai[ra] = rb
            nome[rb] = na or nb

    for p, pino in pinos.items():
        if pino["net"]:
            nome.setdefault(raiz(pino["net"]), pino["net"])
            junta(p, pino["net"], lido["pecas"][p.split(".")[0]]["linha"])
    for ref, peca in lido["pecas"].items():   # pinos ligados por dentro da peca (ex: botao 1-2 e 3-4)
        for a, b in bib[peca["tipo"]].get("juntos", []):
            junta(f"{ref}.{a}", f"{ref}.{b}", peca["linha"])
    for lg in lido["ligas"]:
        for ponta in (lg["de"], lg["ate"]):
            if "." in ponta and ponta not in pinos:
                ref, n = ponta.split(".", 1)
                msg = f"{ref} não existe" if ref not in lido["pecas"] else f"{ref} não tem pino {n}"
                raise ErroTxt(lg["linha"], msg, [ref])
            if "." not in ponta:
                nome.setdefault(raiz(ponta), ponta)
        if "." not in lg["de"] and "." not in lg["ate"]:
            raise ErroTxt(lg["linha"], "a ligação precisa ter pelo menos um pino (REF.PINO)")
        junta(lg["de"], lg["ate"], lg["linha"])
    k = 0
    for lg in lido["ligas"]:
        rz = raiz(lg["de"])
        if not nome.get(rz):
            k += 1
            while f"N{k}" in nome.values():   # o Luiz pode ter usado N1 no txt
                k += 1
            nome[rz] = f"N{k}"
    for p, pino in pinos.items():
        pino["net"] = nome.get(raiz(p))

    # trilhas em linha reta. Ilha = pedaco de cobre ja ligado de verdade; pinos da mesma peca
    # com a mesma net fixa (os GND do DevKit) ja nascem juntos, ligados por dentro da peca.
    ilha = {}

    def raiz_ilha(a):
        while ilha.setdefault(a, a) != a:
            a = ilha[a]
        return a

    primeiro = {}   # (ref, net) -> primeiro pino daquela peca com essa net fixa
    for p, net in fixa.items():
        ilha[raiz_ilha(p)] = raiz_ilha(primeiro.setdefault((p.split(".")[0], net), p))
    for ref, peca in lido["pecas"].items():
        for a, b in bib[peca["tipo"]].get("juntos", []):
            ilha[raiz_ilha(f"{ref}.{a}")] = raiz_ilha(f"{ref}.{b}")

    def firme(p, net):   # a ilha de p tem um pino que nasceu nessa net (ex: GND do DevKit)?
        return any(raiz_ilha(q) == raiz_ilha(p) for q, n in fixa.items() if n == net)

    def ponto(ponta, outra):
        """ligar numa net vai ate o pino mais perto dela que esta em outra ilha (de preferencia uma firme)"""
        if ponta in pinos:
            return ponta
        net, de = nome[raiz(ponta)], pinos[outra]
        ref = outra.split(".")[0]
        mesma = [p for p, pino in pinos.items() if pino["net"] == net and p.split(".")[0] != ref]   # de outras pecas
        fora = [p for p in mesma if raiz_ilha(p) != raiz_ilha(outra)]
        if not fora:
            return "ja" if mesma else None   # ja esta ligado nessa net por outro caminho
        perto = [p for p in fora if firme(p, net)] or fora
        return min(perto, key=lambda p: (pinos[p]["x"] - de["x"]) ** 2 + (pinos[p]["y"] - de["y"]) ** 2)

    conexoes = []
    for lg in lido["ligas"]:
        a, b = ponto(lg["de"], lg["ate"]), ponto(lg["ate"], lg["de"])
        if a is None or b is None:
            net = lg["de"] if a is None else lg["ate"]
            raise ErroTxt(lg["linha"], f"{net} não tem nenhum outro pino na placa", [p.split(".")[0] for p in (a, b) if p])
        if "ja" in (a, b):
            continue
        ilha[raiz_ilha(a)] = raiz_ilha(b)
        conexoes.append((a, b, lg["linha"]))

    w, h = lido["placa"]["w"], lido["placa"]["h"]
    furos = []
    for f in lido["furos"]:
        b = BORDA_FURO
        for x, y in ((b, b), (w - b, b), (b, h - b), (w - b, h - b)):
            furos.append({"x": r(x), "y": r(y), "d": f["d"], "linha": f["linha"]})
    proibidas = [zona(p, nome) for p in pecas for nome in PROIBIDAS if nome in (p.get("zonas") or {})]
    trilhas, vias = rotear(conexoes, pinos, furos, w, h, proibidas=proibidas)

    # fabrica.zip so sai quando toda medida veio de datasheet (nenhum numero inventado vai pra fabrica)
    exemplo = [p["ref"] for p in pecas if p["exemplo"]]
    pendente = [p["ref"] for p in pecas if p["pendente"]]
    # lista de compras: a fabrica entrega so a placa nua
    compras = [{"ref": p["ref"], "nome": p["nome"], "compra": p["compra"], "valor": p["valor_txt"], "loja": p["loja"]} for p in pecas]
    compras += [{"ref": "", "nome": extra, "compra": "", "valor": None, "loja": None}
                for p in pecas for extra in bib[p["tipo"]].get("extras", [])]
    # da pra ligar no papel? so se toda peca tem modelo eletrico e todo resistor tem valor
    falta = [p["ref"] for p in pecas if not p["eletrica"]]
    sem_valor = [p["ref"] for p in pecas if p["eletrica"] and p["eletrica"]["modelo"] == "resistor" and p["valor"] is None]
    # o chip (modelo "mcu", o DevKit) tem 30 pinos e quase todos ficam sem net: pino dele sem nada não é pino solto
    soltos = [p["ref"] for p in pecas if p["eletrica"] and p["eletrica"]["modelo"] != "mcu" and any(q["net"] is None for q in p["pinos"])]
    modelo = {"placa": lido["placa"], "pecas": pecas, "trilhas": trilhas, "vias": vias, "furos": furos,
              "fabrica": {"pronta": not exemplo and not pendente, "falta_datasheet": exemplo, "falta_conferir": pendente},
              "simulacao": {"pode": not falta and not sem_valor and not soltos, "falta_modelo": falta,
                            "sem_valor": sem_valor, "soltos": soltos},
              "compras": compras, "linhas": lido["linhas"]}
    posicionar_nomes(modelo)   # depois do roteador: o nome também foge das vias
    return modelo


# 3b. roteador: o caminho de cada trilha
LADOS = ("cima", "baixo")


def caminhos(pa, pb, la, lb, desvios=((), ())):
    """caminhos candidatos de pa a pb: [(segmentos [(p, q, lado)], vias [ponto])], do mais curto pro mais longo.
    la/lb: os lados onde cada ponta tem cobre (pad de superficie so em cima). Trocar de lado custa uma via.
    desvios: (xs, ys) a mais pro trecho do meio do Z, pra dar a volta numa zona proibida rente a ela."""
    (x1, y1), (x2, y2) = pa, pb
    cands = []

    def poe(pontos, lados):
        segs = [(p, q, l) for p, q, l in zip(pontos, pontos[1:], lados) if p != q]
        if not segs or segs[0][2] not in la or segs[-1][2] not in lb:
            return
        vias = [s[1] for s, t in zip(segs, segs[1:]) if s[2] != t[2]]
        comprimento = sum(math.dist(p, q) * (1.02 if l == "baixo" else 1) for p, q, l in segs)   # empate: em cima ganha
        cands.append((comprimento + 4 * len(vias), segs, vias))

    for l in LADOS:
        poe([pa, pb], [l])
    for canto in ((x2, y1), (x1, y2)):
        for l1 in LADOS:
            for l2 in LADOS:
                poe([pa, canto, pb], [l1, l2])
    passo = [-9, -7, -5, -3, -1.5, 1.5, 3, 5, 7, 9]
    xs = [x1 + (x2 - x1) * k for k in (0.25, 0.5, 0.75)] + [min(x1, x2) + d for d in passo if d < 0] + [max(x1, x2) + d for d in passo if d > 0]
    ys = [y1 + (y2 - y1) * k for k in (0.25, 0.5, 0.75)] + [min(y1, y2) + d for d in passo if d < 0] + [max(y1, y2) + d for d in passo if d > 0]
    xs, ys = xs + list(desvios[0]), ys + list(desvios[1])
    for l1 in LADOS:
        for l2 in LADOS:
            for l3 in LADOS:
                for xm in xs:
                    poe([pa, (xm, y1), (xm, y2), pb], [l1, l2, l3])
                for ym in ys:
                    poe([pa, (x1, ym), (x2, ym), pb], [l1, l2, l3])
    cands.sort(key=lambda c: c[0])
    return [(segs, vias) for _, segs, vias in cands]


def rotear(conexoes, pinos, furos_fix, w, h, tentativas=4, proibidas=()):
    """conexoes: [(pino a, pino b, linha do txt)]. Pra cada uma, o caminho mais curto (reta, L ou Z, em cima, embaixo
    ou trocando de lado por via) que passa longe do cobre das outras nets, da borda e dos furos. Se alguma nao coube,
    ela vai pro comeco da fila e tenta de novo; fica a tentativa com menos falhas. Falhou mesmo: fica a reta em cima
    (com zona proibida no caminho, o caminho mais curto que não entra nela), e a etapa 3 acusa o curto.
    Devolve (trilhas, vias); cada trilha e um segmento de uma camada.
    proibidas: [(x0, y0, x1, y1)] onde nenhuma trilha nem via entra, nas duas camadas (a antena do DevKit). Só a ligação
    que tem a ponta encostada ou dentro da zona chega tão perto quanto essa ponta (a etapa 3 avisa)."""
    ordem, melhor = list(conexoes), None
    for _ in range(tentativas):
        trilhas, vias, falhas = rotear_uma_vez(ordem, pinos, furos_fix, w, h, proibidas)
        if melhor is None or len(falhas) < len(melhor[2]):
            melhor = (trilhas, vias, falhas)
        if not falhas:
            break
        ordem = falhas + [c for c in ordem if c not in falhas]
    trilhas, vias, _ = melhor
    posicao = {c[:2]: i for i, c in enumerate(conexoes)}   # a ordem do txt de volta (a frase das versoes e o app contam com ela)
    trilhas.sort(key=lambda t: posicao[(t["de"], t["ate"])])
    return trilhas, vias


def rotear_uma_vez(conexoes, pinos, furos_fix, w, h, proibidas=()):
    obst = {l: [] for l in LADOS}   # lado -> [(net, miolo, raio)]
    for nome, p in pinos.items():
        miolo, raio = geometria.do_pad(p["x"], p["y"], p["pad"])
        for l in (LADOS if p["furo"] else ("cima",)):
            obst[l].append((p["net"] or nome, miolo, raio))
    furos = [((p["x"], p["y"]), p["furo"] / 2) for p in pinos.values() if p["furo"]]
    fixos = [((f["x"], f["y"]), f["d"] / 2) for f in furos_fix]
    zonas = [("ret", *z) for z in proibidas]   # retângulos sem raio, valem pras duas camadas
    desvios = ([v for z in proibidas for v in (z[0] - DESVIO, z[2] + DESVIO)],
               [v for z in proibidas for v in (z[1] - DESVIO, z[3] + DESVIO)])

    def dentro_da_placa(pts, raio):
        return all(BORDA_ROTA + raio <= x <= w - BORDA_ROTA - raio and BORDA_ROTA + raio <= y <= h - BORDA_ROTA - raio for x, y in pts)

    def limites(pa, pb):
        """a folga que cada zona pede pra essa ligação: FOLGA_ROTA, ou a distância da ponta que já está mais perto
        (peça encostada na antena: a trilha não chega mais perto que ela). Ponta dentro da zona: a trilha dessa ligação
        pode passar na zona (a etapa 3 avisa da peça na antena); via nunca, porque o raio dela é maior"""
        return [min(FOLGA_ROTA, *(geometria.distancia((("seg", p, p), TRILHA / 2), (z, 0)) for p in (pa, pb))) for z in zonas]

    def fora_das_zonas(segs, vs, lims):
        cobres = [(("seg", p, q), TRILHA / 2) for p, q, _ in segs] + [(("seg", v, v), VIA_PAD / 2) for v in vs]
        return all(geometria.distancia(c, (z, 0)) >= lim - 1e-9 for z, lim in zip(zonas, lims) for c in cobres)

    def seg_livre(net, p, q, lado):
        c = (("seg", p, q), TRILHA / 2)
        if not dentro_da_placa((p, q), TRILHA / 2):
            return False
        if any(geometria.dist_ponto_seg(f, p, q) - rf - TRILHA / 2 < BORDA_ROTA for f, rf in fixos):
            return False
        return all(n == net or geometria.distancia(c, (m, rr)) >= FOLGA_ROTA for n, m, rr in obst[lado])

    def via_livre(net, ponto):
        c = (("seg", ponto, ponto), VIA_PAD / 2)
        if not dentro_da_placa((ponto,), VIA_PAD / 2):
            return False
        if any(math.dist(ponto, f) - rf - VIA_PAD / 2 < BORDA_ROTA for f, rf in fixos):
            return False
        if any(math.dist(ponto, f) - rf - VIA_FURO / 2 < 0.5 for f, rf in furos):   # furo com furo (fábrica: 0,45)
            return False
        return all(n == net or geometria.distancia(c, (m, rr)) >= FOLGA_ROTA for l in LADOS for n, m, rr in obst[l])

    def na_placa(segs):
        return all(0 <= x <= w and 0 <= y <= h for s in segs for x, y in s[:2])

    trilhas, vias, falhas = [], [], []
    for conexao in conexoes:
        a, b, linha = conexao
        pa, pb, net = (pinos[a]["x"], pinos[a]["y"]), (pinos[b]["x"], pinos[b]["y"]), pinos[a]["net"]
        la = LADOS if pinos[a]["furo"] else ("cima",)
        lb = LADOS if pinos[b]["furo"] else ("cima",)
        cands, lims = caminhos(pa, pb, la, lb, desvios), limites(pa, pb)
        escolhido = next(((segs, vs) for segs, vs in cands if fora_das_zonas(segs, vs, lims)
                          and all(seg_livre(net, p, q, l) for p, q, l in segs) and all(via_livre(net, v) for v in vs)), None)
        if escolhido is None:
            falhas.append(conexao)
            # falhou mesmo: o caminho mais curto que menos estraga, nessa ordem: não entra na zona, fica na placa e passa
            # longe da zona, mesmo encostando em outro cobre (a etapa 3 acusa o curto). Sem zona é a reta em cima
            sem_entrar = [min(lim, 0) for lim in lims]
            escolhido = min(cands, key=lambda c: (not fora_das_zonas(*c, sem_entrar), not na_placa(c[0]),
                                                  not fora_das_zonas(*c, lims)), default=([(pa, pb, "cima")], []))
        for p, q, l in escolhido[0]:
            trilhas.append({"de": a, "ate": b, "x1": r(p[0]), "y1": r(p[1]), "x2": r(q[0]), "y2": r(q[1]), "largura": TRILHA,
                            "net": net, "linha": linha, "lado": l})
            obst[l].append((net, ("seg", p, q), TRILHA / 2))
        for v in escolhido[1]:
            vias.append({"x": r(v[0]), "y": r(v[1]), "d": VIA_PAD, "furo": VIA_FURO, "net": net, "de": a, "ate": b, "linha": linha})
            for l in LADOS:
                obst[l].append((net, ("seg", v, v), VIA_PAD / 2))
            furos.append((v, VIA_FURO / 2))
    return trilhas, vias, falhas


# 4. Gerber (RS-274X): coordenadas em milionesimos de mm
def xy(x, y):
    return f"X{round(x * 1e6)}Y{round(y * 1e6)}"


def abertura(pad):
    if pad["forma"] == "C":
        return f"C,{pad['d']:.3f}"
    return f"{'O' if pad['forma'] == 'O' else 'R'},{pad['w']:.3f}X{pad['h']:.3f}"   # O = oblongo


class Gerber:
    """junta aberturas e desenho; D02 move, D01 desenha, D03 carimba pad"""

    def __init__(self, funcao):
        self.funcao, self.aberturas, self.desenho, self.atual = funcao, {}, [], None

    def usa(self, ab):
        d = self.aberturas.setdefault(ab, 10 + len(self.aberturas))
        if d != self.atual:
            self.desenho.append(f"D{d}*")
            self.atual = d

    def carimba(self, pad, x, y):
        self.usa(abertura(pad))
        self.desenho.append(xy(x, y) + "D03*")

    def risca(self, largura, pontos):
        self.usa(abertura({"forma": "C", "d": largura}))
        self.desenho.append(xy(*pontos[0]) + "D02*")
        self.desenho += [xy(*p) + "D01*" for p in pontos[1:]]

    def texto(self):
        cab = ["%TF.GenerationSoftware,sianvolt,gerar.py*%", f"%TF.FileFunction,{self.funcao}*%"]
        if self.funcao.startswith("Soldermask"):
            cab.append("%TF.FilePolarity,Negative*%")   # na mascara, desenhar = abrir buraco
        cab += ["%FSLAX46Y46*%", "%MOMM*%", "%LPD*%"]
        cab += [f"%ADD{d}{ab}*%" for ab, d in self.aberturas.items()]
        return "\n".join(cab + ["G01*"] + self.desenho + ["M02*"]) + "\n"


def contorno(modelo):
    w, h = modelo["placa"]["w"], modelo["placa"]["h"]
    g = Gerber("Profile,NP")
    g.risca(CONTORNO, [(0, 0), (w, 0), (w, h), (0, h), (0, 0)])
    return g.texto()


def pads(modelo, lado):
    """pinos com pad nesse lado: em cima todos; embaixo so os de furo passante"""
    return [p for peca in modelo["pecas"] for p in peca["pinos"] if lado == "cima" or p["furo"]]


def cobre(modelo, lado):
    g = Gerber("Copper,L1,Top" if lado == "cima" else "Copper,L2,Bot")
    for p in pads(modelo, lado):
        g.carimba(p["pad"], p["x"], p["y"])
    for v in modelo.get("vias", []):
        g.carimba({"forma": "C", "d": v["d"]}, v["x"], v["y"])
    for t in modelo["trilhas"]:
        if t.get("lado", "cima") == lado:
            g.risca(t["largura"], [(t["x1"], t["y1"]), (t["x2"], t["y2"])])
    return g.texto()


def mascara(modelo, lado):
    """buraco na mascara do tamanho do pad (JLCPCB abre 1:1); a via fica coberta"""
    g = Gerber("Soldermask,Top" if lado == "cima" else "Soldermask,Bot")
    for p in pads(modelo, lado):
        g.carimba(p["pad"], p["x"], p["y"])
    return g.texto()


def longe(x, y, obstaculos, folga):
    for ox, oy, pad in obstaculos:
        if pad["forma"] == "C":
            d = math.hypot(x - ox, y - oy) - pad["d"] / 2
        else:
            d = math.hypot(max(abs(x - ox) - pad["w"] / 2, 0), max(abs(y - oy) - pad["h"] / 2, 0))
        if d < folga:
            return False
    return True


def recortar(a, b, obstaculos, folga, passo=0.05):
    """pedacos da linha a-b que ficam longe dos pads e furos"""
    n = max(1, math.ceil(math.dist(a, b) / passo))
    pts = [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n + 1)]
    pedacos, atual = [], []
    for pt in pts:
        if longe(*pt, obstaculos, folga):
            atual.append(pt)
        elif atual:
            pedacos.append(atual)
            atual = []
    if atual:
        pedacos.append(atual)
    return [(c[0], c[-1]) for c in pedacos if len(c) > 1 or a == b]


def no_retangulo(a, b, x0, y0, x1, y1):
    """o pedaço do segmento a-b que fica dentro do retângulo (o próprio a-b se ele já está dentro), ou None"""
    if not (x0 <= x1 and y0 <= y1):
        return None
    if all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in (a, b)):
        return a, b
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):   # Liang-Barsky
        if p == 0:
            if q < 0:
                return None
        elif p < 0:
            t0 = max(t0, q / p)
        else:
            t1 = min(t1, q / p)
    if t0 >= t1:
        return None
    return (a[0] + t0 * dx, a[1] + t0 * dy), (a[0] + t1 * dx, a[1] + t1 * dy)


def so_letras(texto):
    """o texto do jeito que a fonte da serigrafia escreve: maiúsculo, sem acento, e o que ela não tem vira espaço
    ('VIN: não soldar' -> 'VIN NAO SOLDAR')"""
    t = "".join(c for c in unicodedata.normalize("NFD", texto.upper()) if not unicodedata.combining(c))
    return " ".join("".join(c if c in LETRAS else " " for c in t).split())


def comprimento(texto):
    """quantos mm o texto ocupa escrito com LETRA (cada letra anda LETRA; a última não tem o espaço depois)"""
    t = so_letras(texto)
    return len(t) * LETRA - LETRA / 3 if t else 0


def texto_na_placa(texto, x, y, em_pe=False):
    """as linhas (pontos em mm) do texto com o meio em (x, y); em pé = girado 90°, lido de baixo pra cima"""
    linhas = tracos(so_letras(texto), 0, -LETRA / 2, LETRA)
    if em_pe:
        return [[(x - v, y + u) for u, v in pontos] for pontos in linhas]
    return [[(x + u, y + v) for u, v in pontos] for pontos in linhas]


def textos_da_peca(peca, placa=None):
    """o que a serigrafia escreve numa peça com zonas (o DevKit): [(texto, x, y, em_pé)], com o meio do texto em (x, y).
    O nome de cada zona vai no meio dela ('ANTENA', 'USB'), deitado se couber, em pé se não; se nem assim couber (a
    peça passa da borda da placa), fica sem. O aviso do pino que não leva solda ('VIN NAO SOLDAR') vai em pé do lado
    de fora do pino, entrando no corpo da peça. placa: (w, h), pra contar só a parte da zona que fica na placa"""
    if not peca.get("zonas"):
        return []
    textos = []
    cw, ch = peca["corpo"]["w"] / 2, peca["corpo"]["h"] / 2
    px0, py0, px1, py1 = (0, 0, *placa) if placa else (-math.inf, -math.inf, math.inf, math.inf)
    margem = LETRA_LINHA + 2 * (SILK + SILK_PAD)   # o traço da letra e a linha da zona, com a folga, dos dois lados
    for nome in peca["zonas"]:
        # só a parte em cima do corpo (o USB passa da borda dele) e dentro da placa (a antena pode passar da borda)
        x0, y0, x1, y1 = zona(peca, nome)
        x0, y0 = max(x0, peca["x"] - cw, px0), max(y0, peca["y"] - ch, py0)
        x1, y1 = min(x1, peca["x"] + cw, px1), min(y1, peca["y"] + ch, py1)
        deitado = comprimento(nome) + margem <= x1 - x0 and LETRA + margem <= y1 - y0
        em_pe = comprimento(nome) + margem <= y1 - y0 and LETRA + margem <= x1 - x0
        if deitado or em_pe:
            textos.append((so_letras(nome), r((x0 + x1) / 2), r((y0 + y1) / 2), not deitado))
    for pino in peca["pinos"]:
        aviso = (peca.get("cuidados") or {}).get(pino["n"], "")
        if "não soldar" not in aviso:
            continue
        bx0, _, bx1, _ = geometria.caixa(*geometria.do_pad(pino["x"], pino["y"], pino["pad"]))
        folga = SILK_PAD + LETRA_LINHA / 2 + LETRA / 2 + 0.1   # da borda do pad até o meio da coluna de letras
        x = bx1 + folga if pino["x"] >= peca["x"] else bx0 - folga
        meio = comprimento(aviso) / 2 - LETRA / 2   # a ponta do texto fica na altura do pino
        y = pino["y"] + meio if pino["y"] < peca["y"] else pino["y"] - meio
        textos.append((so_letras(aviso), r(x), r(y), True))
    return textos


# o nome de cada peça na serigrafia: em cima, embaixo, à direita ou à esquerda, o primeiro lado livre
def largura_do_nome(ref):
    """mm que o nome ocupa escrito com LETRA (a conta do letras.tracos: cada letra anda LETRA, a última sem o espaço)"""
    return len(ref) * LETRA - LETRA / 3


def lugares_do_nome(peca):
    """[(lado, x, y)] na ordem em que o gerar tenta, com (x, y) o meio da base do texto. Em cima é onde o nome sempre
    ficou; embaixo, o mesmo do outro lado do corpo; dos lados, no meio da altura, depois do pino mais pra fora (o
    resistor e o botão têm pino pra fora do corpo)"""
    x, y, cw, ch = peca["x"], peca["y"], peca["corpo"]["w"] / 2, peca["corpo"]["h"] / 2
    pads = [geometria.caixa(*geometria.do_pad(q["x"], q["y"], q["pad"])) for q in peca["pinos"]]
    direita = max([x + cw] + [c[2] for c in pads])
    esquerda = min([x - cw] + [c[0] for c in pads])
    meio = largura_do_nome(peca["ref"]) / 2
    return [("cima", x, y + ch + NOME_LONGE), ("baixo", x, y - ch - NOME_LONGE - LETRA),
            ("direita", direita + NOME_LONGE + meio, y - LETRA / 2), ("esquerda", esquerda - NOME_LONGE - meio, y - LETRA / 2)]


def caixa_do_nome(pos):
    """(x0, y0, x1, y1) que as letras do nome ocupam, com a grossura do traço; pos = o nome_pos da peça"""
    m = LETRA_LINHA / 2
    return (pos["x"] - pos["largura"] / 2 - m, pos["y"] - m, pos["x"] + pos["largura"] / 2 + m, pos["y"] + pos["altura"] + m)


def o_que_o_nome_cobre(modelo, peca, pos, outros=()):
    """o que fica embaixo das letras do nome da peça em pos: [(o que, quem)], vazio = lugar livre. o que = 'fora' (sai
    da placa), 'corpo' (de outra peça), 'zona' (a antena e o USB do DevKit), 'pad', 'furo' (de fixação), 'via' ou 'nome'
    (outros = [(ref, pos)] dos nomes já postos). Mesmas folgas da serigrafia: SILK_PAD do pad, furo e via (senão o
    recorte come a letra) e meia linha do contorno das outras peças (as letras não encostam nele)"""
    x0, y0, x1, y1 = caixa = caixa_do_nome(pos)
    w, h = modelo["placa"]["w"], modelo["placa"]["h"]
    ret, perto = ("ret", *caixa), -SILK / 2
    achados = [] if 0 <= x0 and 0 <= y0 and x1 <= w and y1 <= h else [("fora", "")]
    for p in modelo["pecas"]:
        if p is not peca and geometria.sobrepoe(corpo_na_placa(p), ret, perto):
            achados.append(("corpo", p["ref"]))
        for nome in p.get("zonas") or {}:
            if geometria.sobrepoe(("ret", *zona(p, nome)), ret, perto):
                achados.append(("zona", f"{so_letras(nome)} do {p['ref']}"))
    for p in modelo["pecas"]:
        for q in p["pinos"]:
            if geometria.distancia((ret, 0), geometria.do_pad(q["x"], q["y"], q["pad"])) < SILK_PAD:
                achados.append(("pad", f"{p['ref']}.{q['n']}"))
    buracos = [("furo", "", f) for f in modelo["furos"]] + [("via", f"{v['de']} → {v['ate']}", v) for v in modelo.get("vias", [])]
    for oque, quem, f in buracos:
        if geometria.distancia((ret, 0), (("seg", (f["x"], f["y"]), (f["x"], f["y"])), f["d"] / 2)) < SILK_PAD:
            achados.append((oque, quem))
    for ref, outra in outros:
        if geometria.sobrepoe(("ret", *caixa_do_nome(outra)), ret, perto):
            achados.append(("nome", ref))
    return achados


def posicionar_nomes(modelo):
    """grava em cada peça o nome_pos {x, y, lado, altura, largura}: o meio da base do texto em mm (y pra cima, como os
    pinos), o lado escolhido, a altura e o comprimento das letras. É o primeiro lado (cima, baixo, direita, esquerda)
    em que o nome não cobre nada (o_que_o_nome_cobre, contando os nomes das peças de antes); sem nenhum, fica em cima
    e a etapa 5 avisa. O Gerber, a folha 1:1 e a bancada desenham o nome daqui"""
    postos = []
    for peca in modelo["pecas"]:
        lugares = [{"x": r(x), "y": r(y), "lado": lado, "altura": LETRA, "largura": r(largura_do_nome(peca["ref"]))}
                   for lado, x, y in lugares_do_nome(peca)]
        peca["nome_pos"] = next((pos for pos in lugares if not o_que_o_nome_cobre(modelo, peca, pos, postos)), lugares[0])
        postos.append((peca["ref"], peca["nome_pos"]))


def tracos_da_serigrafia(modelo):
    """[(largura, a, b)]: os pedaços de linha da serigrafia, já recortados longe dos pads e dentro da placa.
    Contorno de cada peça e o nome dela no lado que o posicionar_nomes escolheu; nas peças com zonas (o DevKit), o
    retângulo e os textos de cada zona"""
    w, h = modelo["placa"]["w"], modelo["placa"]["h"]
    obstaculos = [(p["x"], p["y"], p["pad"]) for p in pads(modelo, "cima")]
    obstaculos += [(f["x"], f["y"], {"forma": "C", "d": f["d"]}) for f in modelo["furos"] + modelo.get("vias", [])]
    saida = []

    def linha(largura, pontos):
        for a, b in zip(pontos, pontos[1:] or pontos):
            for c, d in recortar(a, b, obstaculos, SILK_PAD + largura / 2):
                dentro = no_retangulo(c, d, largura / 2, largura / 2, w - largura / 2, h - largura / 2)
                if dentro:   # o pedaço que sai da placa (o DevKit rente à borda) fica de fora
                    saida.append((largura, *dentro))

    for peca in modelo["pecas"]:
        x, y = peca["x"], peca["y"]
        if peca.get("desenho"):   # peca da loja: o contorno oficial dela (EasyEDA)
            for traco in peca["desenho"]:
                linha(SILK, [(x + dx, y + dy) for dx, dy in traco])
        else:
            linha(SILK, borda(peca))
        pos = peca.get("nome_pos") or dict(zip(("lado", "x", "y"), lugares_do_nome(peca)[0]))   # modelo feito à mão: em cima
        for pontos in tracos(peca["ref"], pos["x"], pos["y"], LETRA):
            linha(LETRA_LINHA, pontos)
        for nome in peca.get("zonas") or {}:
            x0, y0, x1, y1 = zona(peca, nome)
            linha(SILK, [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])
        for texto, tx, ty, em_pe in textos_da_peca(peca, (w, h)):
            for pontos in texto_na_placa(texto, tx, ty, em_pe):
                linha(LETRA_LINHA, pontos)
    return saida


def borda(peca):
    """o contorno do corpo da peça (retângulo ou círculo), em pontos"""
    cw, ch, x, y = peca["corpo"]["w"], peca["corpo"]["h"], peca["x"], peca["y"]
    if peca["corpo"]["redondo"]:
        return [(x + cw / 2 * math.cos(i * math.pi / 24), y + ch / 2 * math.sin(i * math.pi / 24)) for i in range(49)]
    return [(x - cw / 2, y - ch / 2), (x + cw / 2, y - ch / 2), (x + cw / 2, y + ch / 2),
            (x - cw / 2, y + ch / 2), (x - cw / 2, y - ch / 2)]


def serigrafia(modelo):
    """contorno de cada peca e o nome dela no lado livre (nome_pos), sem encostar nos pads nem sair da placa"""
    g = Gerber("Legend,Top")
    for largura, a, b in tracos_da_serigrafia(modelo):
        g.risca(largura, [a, b])
    return g.texto()


# 5. Excellon (furos); G90 fica antes do %, fora do cabecalho o leitor reclama
def excellon(furos, cobre):
    if not furos:
        return None
    ferramentas = {d: i + 1 for i, d in enumerate(sorted({f["d"] for f in furos}))}
    funcao = "Plated,1,2,PTH" if cobre else "NonPlated,1,2,NPTH"
    t = ["M48", f"; #@! TF.FileFunction,{funcao}", "METRIC,TZ"]
    t += [f"T{i}C{d:.3f}" for d, i in ferramentas.items()]
    t += ["G90", "%"]
    for d, i in ferramentas.items():
        t.append(f"T{i}")
        t += [f"X{f['x']:.3f}Y{f['y']:.3f}" for f in furos if f["d"] == d]
    return "\n".join(t + ["M30"]) + "\n"


def furos_com_cobre(modelo):
    return [{"x": p["x"], "y": p["y"], "d": p["furo"]}
            for peca in modelo["pecas"] for p in peca["pinos"] if p["furo"]] + \
           [{"x": v["x"], "y": v["y"], "d": v["furo"]} for v in modelo.get("vias", [])]


# 5b. a folha pra imprimir: a placa em tamanho real (1 unidade do desenho = 1 mm)
def folha_1x1(modelo):
    """SVG da placa em tamanho real, vista de cima: contorno, pads (cinza), furos e serigrafia, com uma régua de 50 mm
    embaixo. Imprime, mede a régua e espeta as peças (o DevKit) no papel antes de pedir a placa."""
    w, h = modelo["placa"]["w"], modelo["placa"]["h"]
    m, topo, frase = 10, 16, 100           # margem do papel, espaço do texto em cima e largura da frase, em mm
    largura, altura = max(w, REGUA, frase) + 2 * m, topo + h + 26

    def n(v):
        return f"{round(v, 4):.10g}"

    def X(x):
        return n(m + x)

    def Y(y):   # no placa.txt o y cresce pra cima; no SVG, pra baixo
        return n(topo + h - y)

    def figura(x, y, pad, estilo):
        if pad["forma"] == "C":
            return f'<circle cx="{X(x)}" cy="{Y(y)}" r="{n(pad["d"] / 2)}" {estilo}/>'
        canto = min(pad["w"], pad["h"]) / 2 if pad["forma"] == "O" else 0
        return (f'<rect x="{X(x - pad["w"] / 2)}" y="{Y(y + pad["h"] / 2)}" width="{n(pad["w"])}" '
                f'height="{n(pad["h"])}" rx="{n(canto)}" {estilo}/>')

    letra = 'font-family="sans-serif" fill="#000"'
    partes = ['<?xml version="1.0" encoding="UTF-8"?>',
              f'<svg xmlns="http://www.w3.org/2000/svg" width="{n(largura)}mm" height="{n(altura)}mm" '
              f'viewBox="0 0 {n(largura)} {n(altura)}">',
              '<title>Placa em tamanho real</title>',
              f'<rect width="{n(largura)}" height="{n(altura)}" fill="#fff"/>',
              f'<text x="{m}" y="7" font-size="3.5" textLength="{frase}" lengthAdjust="spacingAndGlyphs" {letra}>'
              'imprima em 100%, sem ajustar à página; meça a régua antes</text>',
              f'<text x="{m}" y="12" font-size="2.5" {letra}>placa de {n(w)} × {n(h)} mm, vista de cima</text>',
              f'<rect id="placa" x="{X(0)}" y="{Y(h)}" width="{n(w)}" height="{n(h)}" fill="none" stroke="#000" '
              f'stroke-width="{CONTORNO}"/>']
    partes += [figura(p["x"], p["y"], p["pad"], 'fill="#d0d0d0"') for p in pads(modelo, "cima")]
    partes += [figura(f["x"], f["y"], {"forma": "C", "d": f["d"]}, 'fill="#fff" stroke="#000" stroke-width="0.1"')
               for f in furos_com_cobre(modelo) + modelo["furos"]]
    silk = tracos_da_serigrafia(modelo)
    for grossura in sorted({t[0] for t in silk}):
        d = " ".join(f"M{X(a[0])} {Y(a[1])}L{X(b[0])} {Y(b[1])}" for g, a, b in silk if g == grossura)
        partes.append(f'<path d="{d}" fill="none" stroke="#000" stroke-width="{n(grossura)}" stroke-linecap="round"/>')
    yr = topo + h + 12   # a régua: traço a cada mm, maior a cada 5 e a cada 10, com o número
    regua = [f'<line x1="{n(m)}" y1="{n(yr)}" x2="{n(m + REGUA)}" y2="{n(yr)}"/>']
    regua += [f'<line x1="{n(m + i)}" y1="{n(yr)}" x2="{n(m + i)}" y2="{n(yr - (3 if i % 10 == 0 else 2 if i % 5 == 0 else 1))}"/>'
              for i in range(REGUA + 1)]
    partes.append(f'<g id="regua" stroke="#000" stroke-width="0.15">{"".join(regua)}</g>')
    partes += [f'<text x="{n(m + i)}" y="{n(yr + 4)}" font-size="2.5" text-anchor="middle" {letra}>{i}</text>'
               for i in range(0, REGUA + 1, 10)]
    partes.append(f'<text x="{m}" y="{n(yr + 9)}" font-size="2.5" {letra}>régua de {REGUA} mm: se não der {REGUA} mm '
                  'na régua de verdade, a impressão saiu fora do tamanho</text>')
    return "\n".join(partes + ["</svg>"]) + "\n"


def escrever(modelo, saida):
    """escreve modelo.json, os arquivos da fabrica (nomes no padrao do KiCad) e a folha pra imprimir em tamanho real"""
    saida.mkdir(parents=True, exist_ok=True)
    arquivos = {
        "modelo.json": json.dumps(modelo, ensure_ascii=False, indent=1),
        "placa-Edge_Cuts.gbr": contorno(modelo),
        "placa-F_Cu.gbr": cobre(modelo, "cima"),
        "placa-B_Cu.gbr": cobre(modelo, "baixo"),
        "placa-F_Mask.gbr": mascara(modelo, "cima"),
        "placa-B_Mask.gbr": mascara(modelo, "baixo"),
        "placa-F_Silkscreen.gbr": serigrafia(modelo),
        "placa-PTH.drl": excellon(furos_com_cobre(modelo), cobre=True),
        "placa-NPTH.drl": excellon(modelo["furos"], cobre=False),
    }
    for nome, texto in arquivos.items():
        if texto is None:
            (saida / nome).unlink(missing_ok=True)
        else:
            (saida / nome).write_text(texto)
    (saida / FOLHA).write_text(folha_1x1(modelo), encoding="utf-8")   # pra imprimir: não vai no fabrica.zip
    (saida / "fabrica.zip").unlink(missing_ok=True)   # so o testar.py cria, depois que tudo passa
    return [nome for nome, texto in arquivos.items() if texto is not None and nome != "modelo.json"]


def zipar(saida, nomes):
    with zipfile.ZipFile(saida / "fabrica.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for nome in nomes:
            z.write(saida / nome, nome)


# 6. versoes: cada placa.txt diferente vira vN.txt (+ vN.json pra bancada) e uma frase em versoes.json
def o_que_mudou(antigo, novo):
    if antigo is None:
        return "primeira versão"
    try:
        a, b = ler(antigo), ler(novo)
    except ErroTxt:
        return "mudou o placa.txt"
    feito = {}   # verbo -> coisas

    def anota(verbo, coisa):
        feito.setdefault(verbo, []).append(coisa)

    if (a["placa"]["w"], a["placa"]["h"]) != (b["placa"]["w"], b["placa"]["h"]):
        anota("mudou", f"a placa pra {b['placa']['w']:g}×{b['placa']['h']:g}")
    if [f["d"] for f in a["furos"]] != [f["d"] for f in b["furos"]]:
        anota("mudou", "os furos")
    pa, pb = a["pecas"], b["pecas"]
    for ref in pb:
        if ref not in pa:
            anota("adicionou", ref)
        elif pa[ref]["tipo"] != pb[ref]["tipo"]:
            anota("trocou", ref)
        else:
            if (pa[ref]["x"], pa[ref]["y"]) != (pb[ref]["x"], pb[ref]["y"]):
                anota("moveu", ref)
            if pa[ref]["valor"] != pb[ref]["valor"]:
                if pb[ref]["valor"] is None:
                    anota("tirou", f"o valor de {ref}")
                else:
                    anota("trocou", f"{ref} pra {pb[ref]['valor_txt']} Ω")
    for ref in pa:
        if ref not in pb:
            anota("tirou", ref)
    la = [frozenset((l["de"], l["ate"])) for l in a["ligas"]]   # liga A B = liga B A
    lb = [frozenset((l["de"], l["ate"])) for l in b["ligas"]]
    for l in b["ligas"]:
        if frozenset((l["de"], l["ate"])) not in la:
            anota("ligou", f"{l['de']}–{l['ate']}")
    for l in a["ligas"]:
        if frozenset((l["de"], l["ate"])) not in lb:
            anota("desligou", f"{l['de']}–{l['ate']}")
    if not feito:
        return "só comentários"
    e = lambda c: c[0] if len(c) == 1 else ", ".join(c[:-1]) + " e " + c[-1]
    return "; ".join(f"{verbo} {e(coisas)}" for verbo, coisas in feito.items())


def salvar_versao(pasta, texto, modelo, frase=None):
    vdir = pasta / "versoes"
    vdir.mkdir(exist_ok=True)
    arq = vdir / "versoes.json"
    lista = json.loads(arq.read_text()) if arq.exists() else []
    antigo = (vdir / f"v{lista[-1]['v']}.txt").read_text() if lista else None
    if antigo != texto:
        lista.append({"v": len(lista) + 1, "frase": frase or o_que_mudou(antigo, texto),
                      "quando": datetime.now().strftime("%Y-%m-%d %H:%M")})
        (vdir / f"v{lista[-1]['v']}.txt").write_text(texto)
        arq.write_text(json.dumps(lista, ensure_ascii=False, indent=1))
    v = lista[-1]["v"]
    modelo["versao"] = v
    (vdir / f"v{v}.json").write_text(json.dumps(modelo, ensure_ascii=False, indent=1))
    return v


def gerar(pasta, frase=None):
    """placa.txt -> modelo + arquivos + versao. Levanta ErroTxt se o txt tiver erro."""
    texto = (pasta / "placa.txt").read_text()
    modelo = montar(ler(texto), biblioteca(pasta))
    salvar_versao(pasta, texto, modelo, frase)
    escrever(modelo, pasta / "saida")
    return modelo


if __name__ == "__main__":
    args = sys.argv[1:]
    frase = None
    if "-m" in args:
        i = args.index("-m")
        frase = args[i + 1]
        del args[i:i + 2]
    pasta = Path(args[0] if args else "placas/estudo")
    try:
        m = gerar(pasta, frase)
    except ErroTxt as e:
        sys.exit(f"erro no placa.txt, {e}")
    print(f"ok: v{m['versao']}, {len(m['pecas'])} peças, {len(m['trilhas'])} trilhas, "
          f"{len(m['furos'])} furos de fixação -> {pasta / 'saida'}")
