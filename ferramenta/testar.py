"""testar.py: gera a placa e roda a bateria de 7 etapas, escrevendo testes.json a cada etapa.

uso: python ferramenta/testar.py placas/estudo [-m "o que mudou"]
     python ferramenta/testar.py placas/estudo --resumo "texto do Claude no fim da rodada"
"""
import json
import math
import re
import shutil
import subprocess
import sys
import warnings
from datetime import datetime
from pathlib import Path

import blocos
import catalogo
import circuito
import geometria
import gerar

# regras da fabrica: https://jlcpcb.com/capabilities/pcb-capabilities (1-2 camadas, 1 oz, lido em 2026-10-23)
TRILHA_MIN = 0.10      # largura minima da trilha
ESPACO_MIN = 0.10      # distancia minima entre cobres de nets diferentes
FURO_MIN = 0.15        # menor furo (broca mecanica)
FURO_MAX = 6.3         # maior furo
FURO_NPTH_MIN = 0.50   # menor furo sem cobre
ANEL_MIN = 0.18        # anel de cobre em volta do furo passante (minimo absoluto; recomendado 0,25)
BORDA_MIN = 0.2        # cobre ate a borda cortada (furo sem cobre conta como borda)
FURO_FURO_MIN = 0.45   # entre furos de pad, de borda a borda
PONTE_MIN = 0.10       # mascara entre dois pads (cor verde, 1 oz)
SILK_MIN = 0.15        # linha da serigrafia
LETRA_MIN = 1.0        # altura da letra da serigrafia

ETAPAS = ["Lê o txt", "Confere peças", "Confere ligações", "Liga o circuito",
          "Regras da fábrica", "Relê o Gerber", "Tira foto da placa"]


class Falhou(Exception):
    """etapa falhou; rotulos diz, pra cada peca, a etiqueta vermelha que a bancada desenha nela"""

    def __init__(self, detalhe, onde=(), rotulo=None, rotulos=None):
        super().__init__(detalhe)
        self.detalhe = detalhe
        self.rotulos = rotulos or {ref: rotulo for ref in onde}
        self.onde = list(self.rotulos)


class Pulou(Exception):
    """etapa que nao se aplica a esta placa; nao e falha"""


def mm(v):
    return f"{v:.2f}".replace(".", ",")


def ma(amp):
    return f"{amp * 1000:.0f}" if amp >= 0.0095 else f"{amp * 1000:.1f}".replace(".", ",")


def mw(watt):
    return f"{watt * 1000:.0f}"


# liga o circuito no papel, com as chaves apertadas, pra pilha fraca, nominal e nova
def ligar(modelo, pilha="v", apertadas=True):
    chaves = {p["ref"]: apertadas for p in modelo["pecas"] if (p.get("eletrica") or {}).get("modelo") == "chave"}
    pilhas = {p["ref"]: p["eletrica"][pilha] for p in modelo["pecas"] if (p.get("eletrica") or {}).get("modelo") == "pilha"}
    return circuito.resolver(modelo, {"pilha": pilhas, "chave": chaves})


# geometria do cobre (geometria.py): cada coisa e um "miolo" (segmentos ou retangulo) mais um raio em volta,
# e fica em uma camada ou nas duas (pad de furo e via atravessam a placa)
AMBOS = frozenset({"cima", "baixo"})


def cobres(modelo):
    """(nome, net, miolo, raio, lados); miolo = ("seg", a, b) ou ("ret", x0, y0, x1, y1)"""
    lista = []
    for peca in modelo["pecas"]:
        for p in peca["pinos"]:
            nome = f"{peca['ref']}.{p['n']}"
            miolo, raio = geometria.do_pad(p["x"], p["y"], p["pad"])
            lista.append((nome, p["net"] or nome, miolo, raio, AMBOS if p["furo"] else frozenset({"cima"})))   # pino solto e net sozinho
    for t in modelo["trilhas"]:
        nome = f"trilha {t['de']} → {t['ate']}"
        lista.append((nome, t["net"], ("seg", (t["x1"], t["y1"]), (t["x2"], t["y2"])), t["largura"] / 2,
                      frozenset({t.get("lado", "cima")})))
    for v in modelo.get("vias", []):
        lista.append((f"via {v['de']} → {v['ate']}", v["net"], ("seg", (v["x"], v["y"]), (v["x"], v["y"])), v["d"] / 2, AMBOS))
    return lista


dist_ponto_seg, cruza, dist_seg_seg = geometria.dist_ponto_seg, geometria.cruza, geometria.dist_seg_seg
segmentos, dentro, distancia, caixa = geometria.segmentos, geometria.dentro, geometria.distancia, geometria.caixa


def pares_perto(modelo, limite):
    """pares de cobre de nets diferentes, na mesma camada, mais perto que `limite` (o pior primeiro)"""
    cs = cobres(modelo)
    achados = []
    for i, (n1, net1, m1, r1, l1) in enumerate(cs):
        for n2, net2, m2, r2, l2 in cs[i + 1:]:
            if net1 != net2 and l1 & l2:
                d = distancia((m1, r1), (m2, r2))
                if d < limite:
                    achados.append((d, n1, n2))
    return sorted(achados)


def corpos_encostados(modelo, folga=0.05):
    """pares de peças cujos corpos se sobrepõem (uma em cima da outra na placa); corpo redondo é círculo"""
    def corpo(p):
        c = p["corpo"]
        if c["redondo"]:
            return ("circ", p["x"], p["y"], min(c["w"], c["h"]) / 2)
        return ("ret", p["x"] - c["w"] / 2, p["y"] - c["h"] / 2, p["x"] + c["w"] / 2, p["y"] + c["h"] / 2)
    ps = modelo["pecas"]
    return [(a["ref"], b["ref"]) for i, a in enumerate(ps) for b in ps[i + 1:] if geometria.sobrepoe(corpo(a), corpo(b), folga)]


def refs(*nomes):
    """'trilha R1.2–D1.1' / 'R1.2' -> ['R1', 'D1']"""
    saida = []
    for nome in nomes:
        for ref in re.findall(r"([A-Za-z_][\w]*)\.\w+", nome):
            if ref not in saida:
                saida.append(ref)
    return saida


def nets_partidas(modelo, bib):
    """nets cujo cobre ficou em mais de um pedaco (ex: dois GND que nao se encontram)"""
    pai = {}

    def raiz(a):
        while pai.setdefault(a, a) != a:
            a = pai[a]
        return a

    for t in modelo["trilhas"]:
        pai[raiz(t["de"])] = raiz(t["ate"])
    for peca in modelo["pecas"]:   # pinos da mesma peca com net fixa ja vem ligados por dentro (GND do DevKit)
        fixos = {}
        for n, *_, net in gerar.pinos_do_tipo(bib[peca["tipo"]]):
            if net:
                pai[raiz(f"{peca['ref']}.{n}")] = raiz(fixos.setdefault(net, f"{peca['ref']}.{n}"))
        for a, b in bib[peca["tipo"]].get("juntos", []):
            pai[raiz(f"{peca['ref']}.{a}")] = raiz(f"{peca['ref']}.{b}")
    pedacos = {}   # net -> {raiz: [pinos]}
    for peca in modelo["pecas"]:
        for p in peca["pinos"]:
            nome = f"{peca['ref']}.{p['n']}"
            if p["net"]:
                pedacos.setdefault(p["net"], {}).setdefault(raiz(nome), []).append(nome)
    return {net: list(ps.values()) for net, ps in pedacos.items() if len(ps) > 1}


# as 6 etapas; cada uma devolve o detalhe ou levanta Falhou
def le_txt(ctx):
    ctx["texto"] = (ctx["pasta"] / "placa.txt").read_text()
    ctx["lido"] = gerar.ler(ctx["texto"])
    n = sum(1 for linha in ctx["lido"]["linhas"] if linha.split("#")[0].strip())
    return f"{n} linhas, nenhum erro de digitação"


def confere_pecas(ctx):
    bib = ctx["bib"] = gerar.biblioteca(ctx["pasta"])
    gerar.conferir_tipos(ctx["lido"], bib)
    pecas = ctx["lido"]["pecas"].values()
    exemplo = sorted({p["ref"] for p in pecas if bib[p["tipo"]]["fonte"] is None})
    da_loja = [p["ref"] for p in pecas if bib[p["tipo"]].get("loja")]
    pendente = {p["ref"]: bib[p["tipo"]]["pendente"] for p in pecas if bib[p["tipo"]].get("pendente")}
    detalhe = f"{len(pecas)} peças" + (f", {len(da_loja)} da loja com o desenho oficial" if da_loja else ", todas existem na biblioteca")
    if exemplo:
        detalhe += f" · medidas de exemplo (sem datasheet): {', '.join(exemplo)}"
    for ref, falta in pendente.items():
        detalhe += f" · falta conferir no datasheet de {ref}: {'; '.join(falta)}"
    lista = catalogo.ler()["pecas"]   # a loja como o catalogo viu da ultima vez
    for p in pecas:
        e = lista.get(p["tipo"]) if bib[p["tipo"]].get("loja") else None
        if e and e["situacao"] != "ok":
            detalhe += f" · {p['ref']}: {e['situacao']} na loja (visto em {e['visto']})"
    conferir = {}   # o que a eletrica ainda tem pendente (não segura a fábrica, mas fica à vista): assuntos -> refs
    for p in pecas:
        falta = (bib[p["tipo"]].get("eletrica") or {}).get("pendentes")
        if falta:
            conferir.setdefault(", ".join(f.split(":")[0] for f in falta), []).append(p["ref"])
    if conferir:
        detalhe += " · ainda a conferir: " + "; ".join(f"{', '.join(rs)}: {assuntos}" for assuntos, rs in conferir.items())
    return detalhe


def confere_ligacoes(ctx):
    modelo = gerar.montar(ctx["lido"], ctx["bib"])
    ctx["estado"]["versao"] = gerar.salvar_versao(ctx["pasta"], ctx["texto"], modelo, ctx["frase"])
    ctx["arquivos"] = gerar.escrever(modelo, ctx["pasta"] / "saida")
    ctx["modelo"] = modelo
    ligados = {t[p] for t in modelo["trilhas"] for p in ("de", "ate")}
    sem, solto = [], []
    for peca in modelo["pecas"]:
        usados = [p for p in peca["pinos"] if f"{peca['ref']}.{p['n']}" in ligados]
        if not usados:
            sem.append(peca["ref"])
        elif len(peca["pinos"]) == 2 and len(usados) == 1:
            livre = next(p["n"] for p in peca["pinos"] if p not in usados)
            solto.append(f"{peca['ref']}.{livre}")
        elif len(peca["pinos"]) <= 4:   # peca pequena com um lado sem net (ex: so um lado do botao ligado)
            lados = set()
            for p in peca["pinos"]:
                if p["net"] is None and (p["nome"] or p["n"]) not in lados:
                    lados.add(p["nome"] or p["n"])
                    solto.append(f"{peca['ref']}.{p['n']}")
    if sem:
        raise Falhou(f"{' e '.join(sem)} sem ligação", sem, "sem ligação")
    if solto:
        raise Falhou(f"pino solto: {', '.join(solto)}", refs(*solto), "pino solto")
    w, h = modelo["placa"]["w"], modelo["placa"]["h"]
    fora = []   # pad que sai da placa: nenhuma trilha chega nele, e a fábrica corta ele fora
    for peca in modelo["pecas"]:
        for p in peca["pinos"]:
            x0, y0, x1, y1 = caixa(*geometria.do_pad(p["x"], p["y"], p["pad"]))
            if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
                fora.append(peca["ref"])
                break
    if fora:
        raise Falhou(f"{' e '.join(fora)} {'saem' if len(fora) > 1 else 'sai'} da placa: tem pino fora do contorno de "
                     f"{mm(w).replace(',00', '')} × {mm(h).replace(',00', '')} mm", fora, "fora da placa")
    for peca in modelo["pecas"]:   # pad em cima do furo de fixacao: o parafuso passa no meio do cobre
        for p in peca["pinos"]:
            for f in modelo["furos"]:
                if distancia(geometria.do_pad(p["x"], p["y"], p["pad"]), (("seg", (f["x"], f["y"]), (f["x"], f["y"])), f["d"] / 2)) < 0:
                    raise Falhou(f"{peca['ref']} está em cima do furo de fixação: o pino {p['nome'] or p['n']} encosta no furo",
                                 [peca["ref"]], "em cima do furo")
    encostados = corpos_encostados(modelo)
    if encostados:
        a, b = encostados[0]
        mais = f" (e mais {len(encostados) - 1})" if len(encostados) > 1 else ""
        raise Falhou(f"{a} está em cima de {b}: os corpos das peças se encostam{mais}", [a, b], "uma em cima da outra")
    for peca in modelo["pecas"]:   # resistor, LED, pilha: os dois pinos na mesma net = a peca esta em curto
        if len(peca["pinos"]) == 2 and peca["pinos"][0]["net"] and peca["pinos"][0]["net"] == peca["pinos"][1]["net"]:
            raise Falhou(f"{peca['ref']} em curto: os dois pinos estão na net {peca['pinos'][0]['net']}", [peca["ref"]], "curto")
    partidas = nets_partidas(modelo, ctx["bib"])
    if partidas:
        net, pedacos = next(iter(partidas.items()))
        soltos = [p for pedaco in pedacos[1:] for p in pedaco]
        raise Falhou(f"{net} ficou partida em {len(pedacos)} pedaços: {', '.join(soltos)} não chega no resto",
                     refs(*soltos), "net partida")
    curtos = pares_perto(modelo, 0)
    if curtos:
        _, a, b = curtos[0]
        raise Falhou(f"curto: {a} encosta em {b}" + (f" (e mais {len(curtos) - 1})" if len(curtos) > 1 else ""),
                     refs(a, b), "curto")
    detalhe = f"{len(modelo['trilhas'])} ligações, nenhum pino solto, nenhum curto"
    antena = na_antena(modelo)
    if antena:   # aviso, não falha: nenhum projeto liga o Wi-Fi, só piora o sinal
        nomes, u = [n for n, _ in antena], antena[0][1]
        mais = f" e mais {len(nomes) - 2}" if len(nomes) > 2 else ""
        texto = (f"{' e '.join(nomes[:2])}{mais} {'entra' if len(nomes) == 1 else 'entram'} na zona da antena do {u}: "
                 "o Wi-Fi e o Bluetooth pegam pior (só importa se o programa usar)")
        ctx["aviso"] = {"texto": texto, "rotulos": {ref: "na antena" for n, _ in antena for ref in refs(n) if ref != u}}
        detalhe += " · aviso: " + texto
    return detalhe


def na_antena(modelo):
    """[(cobre, ref do ESP32)]: trilha, via ou pad de outra peça dentro da zona 'antena' da peça (nas duas camadas).
    A zona é a mesma que o roteador evita (gerar.zona)"""
    achados = []
    for u in modelo["pecas"]:
        z = gerar.zona(u, "antena")
        if not z:
            continue
        for nome, _, miolo, raio, _ in cobres(modelo):
            if not nome.startswith(f"{u['ref']}.") and distancia((miolo, raio), (("ret", *z), 0)) < 0:
                achados.append((nome, u["ref"]))
    return achados


def modelo_de(p):
    return (p.get("eletrica") or {}).get("modelo")


def liga_circuito(ctx):
    modelo = ctx["modelo"]
    sim = modelo["simulacao"]
    if not sim["pode"]:   # os 30 pinos do ESP32 não contam como soltos: o gerar pula a peça mcu
        pendente = {p["ref"] for p in modelo["pecas"] if p["pendente"]}
        sem_modelo = [r for r in sim["falta_modelo"] if r not in pendente]
        motivo = []
        if pendente & set(sim["falta_modelo"]):
            motivo.append("falta conferir no datasheet: " + ", ".join(sorted(pendente & set(sim["falta_modelo"]))))
        if sem_modelo:
            motivo.append("sem modelo elétrico: " + ", ".join(sem_modelo))
        if sim["sem_valor"]:
            motivo.append("sem o valor em ohms no placa.txt: " + ", ".join(sim["sem_valor"]))
        if sim["soltos"]:
            motivo.append("pino sem ligação: " + ", ".join(sim["soltos"]))
        raise Pulou("não dá pra ligar no papel ainda · " + " · ".join(motivo))
    mcus = [p for p in modelo["pecas"] if modelo_de(p) == "mcu"]
    if mcus:   # o ESP32 no lugar da pilha
        return liga_com_esp32(ctx, mcus)
    try:
        nominal, fraca, nova = ligar(modelo, "v"), ligar(modelo, "v_min"), ligar(modelo, "v_max")
    except (ZeroDivisionError, KeyError) as e:
        raise Falhou(f"não consegui resolver o circuito: {e}")
    if nominal is None:
        raise Pulou("sem pilha na placa, nada pra ligar")
    ctx["sim"] = {"nominal": nominal, "nova": nova}   # as checagens acende/nao_queima usam isto
    problemas, frases = [], []
    for p in modelo["pecas"]:
        e, ref = p["eletrica"], p["ref"]
        r_nom, r_fraca, r_nova = nominal["pecas"][ref], fraca["pecas"][ref], nova["pecas"][ref]
        if e["modelo"] == "led":
            if r_nova["i"] > e["i_max"]:
                problemas.append((f"{ref} queima: recebe {ma(r_nova['i'])} mA com a pilha nova, o limite é {ma(e['i_max'])} mA", [ref], "queima"))
            brilho = blocos.brilho_da_corrente(e, r_nom["i"])
            quanto = f", ≈ {brilho * 100:.0f}% do brilho do anúncio" if brilho is not None else ""
            frases.append(f"{ref}: {ma(r_nom['i'])} mA{quanto} (de {ma(r_fraca['i'])} a {ma(r_nova['i'])} mA entre pilha fraca e nova; o limite é {ma(e['i_max'])} mA)")
        elif e["modelo"] == "resistor":
            if r_nova["p"] > e["potencia_max"]:
                problemas.append((f"{ref} esquenta demais: {mw(r_nova['p'])} mW, aguenta {mw(e['potencia_max'])} mW", [ref], "esquenta"))
            frases.append(f"{ref}: esquenta {mw(r_nova['p'])} mW, aguenta {mw(e['potencia_max'])} mW")
        elif e["modelo"] == "chave" and e.get("i_max") and abs(r_nova["i"]) > e["i_max"]:
            problemas.append((f"{ref} passa {ma(abs(r_nova['i']))} mA, o limite dele é {ma(e['i_max'])} mA", [ref], "corrente alta"))
        elif e["modelo"] == "pilha":
            horas = e["mah"] / (r_nom["i"] * 1000) if r_nom["i"] > 1e-6 else None
            frase = f"{ref}: {ma(r_nom['i'])} mA" + (f", dura no máximo ≈ {horas:.0f} h apertado" if horas and horas < 1e5 else "")
            if e.get("i_testada") and r_nom["i"] > e["i_testada"]:   # funciona, mas fora do que o fabricante da pilha mediu
                frase += f" (acima dos {ma(e['i_testada'])} mA que o fabricante da pilha testou: ela rende menos)"
            frases.append(frase)
    if problemas:
        problemas.sort(key=lambda p: p[2] != "queima")   # o LED queimando e o que importa, vem primeiro
        raise Falhou(" · ".join(p[0] for p in problemas), rotulos={ref: rot for _, onde, rot in problemas for ref in onde})
    return " · ".join(frases)


# ---------- etapa 4 com o ESP32 ----------
# O chip vira "pilhas de mentira" (circuito.com_pinos): a saída é vdd ou 0 V com r_pino, o botão tem o pull-up de
# dentro (r_pull) e o 3V3 é uma fonte com r_3v3. O papel de cada GPIO sai do circuito, não do programa: o pino do
# botão em 1 com o botão apertado seria um curto. Todo número (vdd, i_pino, orçamento...) vem da eletrica da peça.
GPIO = re.compile(r"GPIO\d+$")
PAPEL = {"saida": "saída", "pullup": "botão com o pull-up de dentro", "pullup_fora": "botão com pull-up de fora",
         "pulldown_fora": "botão com pull-down de fora", "analogica": "leitura de tensão (ADC)",
         "energia": "ligado direto na energia", None: "ligado, sem papel conhecido"}


def num(x):
    return f"{x:g}".replace(".", ",")


def volts(x):
    return f"{x:.2f}".replace(".", ",")


def nome_do_pino(u, nome):
    """'GPIO32 (D32)': o nome de máquina e o que está escrito no DevKit"""
    n = next((q["n"] for q in u["pinos"] if q["nome"] == nome), None)
    escrito = (u.get("serigrafia") or {}).get(n)
    return f"{nome} ({escrito})" if escrito and escrito != nome else nome


def net_do_pino(u, nome):
    return next((q["net"] for q in u["pinos"] if q["nome"] == nome), None)


def pecas_na_net(modelo, u):
    """net -> refs das peças com pino nela (sem o ESP32)"""
    na_net = {}
    for p in modelo["pecas"]:
        for q in p["pinos"]:
            if p is not u and q["net"] and p["ref"] not in na_net.get(q["net"], []):
                na_net.setdefault(q["net"], []).append(p["ref"])
    return na_net


def papel_dos_pinos(modelo, u):
    """o papel de cada GPIO ligado, tirado do circuito: {nome: (papel, ramo, puxa)}. Olha as peças no pino e as que
    vêm depois de UM resistor: chave = 'pullup' ('pullup_fora' com resistor do pino pro 3V3, 'pulldown_fora' com um
    pro GND; vale um resistor ou dois em série, como um 10k que entra entre o 1k e o botão), LDR = 'analogica',
    LED, piezo ou capacitor = 'saida', nada disso = None. O pino que chega no LDR por um resistor, quando o LDR está
    colado em outro GPIO e nada mais leva o divisor pro 3V3, alimenta o divisor: é 'saida' (quem lê é o outro).
    Pino direto no 3V3, GND ou VIN = 'energia'. ramo = as refs dessas peças; puxa = aonde ele chega
    ({'3V3', 'GND', 'VIN'}), direto ou por resistor"""
    energia = {nome: {q["net"] for q in u["pinos"] if q["nome"] == nome and q["net"]} for nome in ("3V3", "GND", "VIN")}
    todas = set().union(*energia.values())
    pecas = {p["ref"]: p for p in modelo["pecas"]}
    na_net = pecas_na_net(modelo, u)

    def resistores(net, sem=None):
        return [x for x in na_net.get(net, []) if modelo_de(pecas[x]) == "resistor" and x != sem]

    def outra_ponta(ref, net):
        return {r["net"] for r in pecas[ref]["pinos"] if r["net"] and r["net"] != net}

    gpios = {q["net"] for q in u["pinos"] if q["net"] and GPIO.match(q["nome"] or "")} - todas
    colados = {x for net in gpios for x in na_net.get(net, []) if modelo_de(pecas[x]) == "ldr"}   # LDR colado num GPIO
    papeis = {}
    for q in u["pinos"]:
        if not q["net"] or not GPIO.match(q["nome"] or ""):
            continue
        if q["net"] in todas:
            papeis[q["nome"]] = ("energia", [], {k for k, v in energia.items() if q["net"] in v})
            continue
        direto = na_net.get(q["net"], [])
        ramo, chega = list(direto), set()   # chega: as nets do outro lado de um resistor (ou de dois em série)
        for r1 in resistores(q["net"]):
            for net in outra_ponta(r1, q["net"]):
                chega.add(net)
                if net in todas:   # o que vai pro 3V3 ou pro GND não leva adiante
                    continue
                ramo += [x for x in na_net[net] if x not in ramo]
                chega |= {n for r2 in resistores(net, r1) for n in outra_ponta(r2, net)}
        puxa = {k for k, v in energia.items() if chega & v}
        tem = {modelo_de(pecas[x]) for x in ramo}
        ldrs = [x for x in ramo if modelo_de(pecas[x]) == "ldr"]
        if "chave" in tem:
            papel = "pullup_fora" if "3V3" in puxa else "pulldown_fora" if "GND" in puxa else "pullup"
        elif any(x in direto or x not in colados for x in ldrs) or (ldrs and "3V3" in puxa):
            papel = "analogica"
        else:
            papel = "saida" if ldrs or tem & {"led", "piezo", "capacitor"} else None
        papeis[q["nome"]] = (papel, ramo, puxa)
    return papeis


# pino de boot que tem que estar em 0 quando o ESP32 liga. O de dentro já puxa pra 0 (Tabela 3, p. 11, linha 480);
# resistor ou fio pro 3V3 por fora estraga. Fonte: Espressif ESP32-WROOM-32 Datasheet v3.8
# https://documentation.espressif.com/esp32-wroom-32_datasheet_en.pdf (no cache: ~/.cache/sianvolt/esp32/devkit/
# ds_esp32-wroom-32.txt): o GPIO12 é o MTDI, que em 1 passa a energia da flash (VDD_SDIO) de 3,3 V pra 1,8 V
# (Seção 3.2, p. 13, linhas 580-586) e que a Espressif pede em 0 ao ligar (nota da Figura 6, p. 35, linha 1906);
# o GPIO2 em 1 não deixa o ESP32 entrar no modo de gravar (Tabela 5, p. 12, linhas 546-550)
EM_0_AO_LIGAR = {"GPIO12": "em 1, ele passa a energia da memória (flash) de 3,3 V pra 1,8 V",
                 "GPIO2": "em 1, o ESP32 não entra no modo de gravar o programa"}


def ligado_em(modelo, u, net, sem):
    """'no GND' / 'em R2 e D1': o que está nessa net, pro texto (sem o nome de máquina da net)"""
    energia = [q["nome"] for q in u["pinos"] if q["net"] == net and q["nome"] in ("3V3", "GND", "VIN") and q["nome"] != sem]
    if energia:
        return f"no {energia[0]}"
    outros = pecas_na_net(modelo, u).get(net, []) + [nome_do_pino(u, q["nome"]) for q in u["pinos"]
                                                     if q["net"] == net and q["nome"] != sem]
    return "em " + " e ".join(outros) if outros else "numa ligação sem peça"


def regras_dos_pinos(modelo, u, papeis):
    """o que o datasheet não deixa em cada pino (as listas da eletrica): (problemas, avisos), [(texto, refs, rótulo)]"""
    e, ref = u["eletrica"], u["ref"]
    pecas = {p["ref"]: p for p in modelo["pecas"]}
    lista = {k: set(e.get(k) or []) for k in ("so_entrada", "flash", "serial", "boot", "psram", "adc1")}
    proibidos = set().union(*(lista[k] for k in ("so_entrada", "flash", "serial", "boot", "psram")))
    livres = sorted(int(q["nome"][4:]) for q in u["pinos"]
                    if GPIO.match(q["nome"] or "") and q["nome"] not in proibidos and not q["net"])
    use = f" (pinos livres: GPIO {', '.join(map(str, livres))})" if livres else ""
    cuidados = u.get("cuidados") or {}
    problemas, avisos = [], []
    for q in u["pinos"]:
        if q["net"] and q["nome"] == "VIN":
            quem = pecas_na_net(modelo, u).get(q["net"], [])
            problemas.append((f"VIN usado: não sei ligar no papel (o VIN, {ref}.{q['n']}, está ligado "
                              f"{ligado_em(modelo, u, q['net'], 'VIN')}; ele é o 5 V do USB e fica fora da conta): "
                              "tire essa ligação ou passe ela pro 3V3", [ref] + quem, "VIN usado"))
        elif q["net"] and q["nome"] == "EN":
            avisos.append((f"o EN ({ref}.{q['n']}) está ligado: o reinício fica fora da conta do papel", [ref], "EN"))
        elif q["net"] and q["nome"] in lista["flash"]:
            problemas.append((f"{ref} {nome_do_pino(u, q['nome'])} é da flash do módulo: não dá pra usar{use}",
                              [ref] + papeis.get(q["nome"], (None, [], set()))[1], "pino da flash"))
    juntos = {}   # net -> GPIOs nela (sem os que estão direto na energia)
    for nome, (papel, _, _) in papeis.items():
        if papel != "energia":
            juntos.setdefault(net_do_pino(u, nome), []).append(nome_do_pino(u, nome))
    for pinos in juntos.values():
        if len(pinos) > 1:
            avisos.append((f"{' e '.join(pinos)} estão ligados um no outro: se dois virarem saída, um puxa o outro (curto)",
                           [ref], "pinos juntos"))
    for nome, (papel, ramo, puxa) in papeis.items():
        pino, quem = nome_do_pino(u, nome), [ref] + ramo
        chaves = [x for x in ramo if modelo_de(pecas[x]) == "chave"]
        cuidado = (cuidados.get(next(q["n"] for q in u["pinos"] if q["nome"] == nome)) or "").replace("cuidado no boot", "")
        extra = f" ({cuidado.strip('; ')})" if cuidado.strip("; ") else ""
        if nome in lista["flash"]:
            continue   # já reprovado lá em cima
        if papel == "saida" and nome in lista["so_entrada"]:
            problemas.append((f"{ref} {pino} só entra: não tem saída pra ligar {', '.join(ramo)}{use}", quem, "pino só entra"))
        elif papel == "saida" and nome in lista["serial"]:
            problemas.append((f"{ref} {pino} é a serial do PC: não use como saída{use}", quem, "pino da serial"))
        elif papel == "saida" and nome in lista["boot"]:
            problemas.append((f"{ref} {pino} é pino de boot: o que estiver ligado nele muda o jeito que o ESP32 liga; "
                              f"não use como saída{use}", quem, "pino de boot"))
        elif nome in lista["boot"] and nome in EM_0_AO_LIGAR and "3V3" in puxa:
            v3 = net_do_pino(u, "3V3")
            pra_cima = [x for x in ramo if modelo_de(pecas[x]) == "resistor" and any(r["net"] == v3 for r in pecas[x]["pinos"])]
            como = "direto no 3V3" if papel == "energia" else f"puxado pro 3V3 por {e_lista(pra_cima)}"
            problemas.append((f"{ref} {pino} tem que estar em 0 quando o ESP32 liga, e ele está {como}: "
                              f"{EM_0_AO_LIGAR[nome]}. Tire essa ligação pro 3V3 ou use outro pino{use}",
                              [ref] + pra_cima, "pino de boot"))
        elif papel == "pullup" and nome in lista["so_entrada"]:
            problemas.append((f"{ref} {pino} não tem pull-up de dentro: o botão precisa de um resistor do {nome} pro 3V3 "
                              f"(ou use outro pino{use})", quem, "sem pull-up"))
        elif papel == "energia":
            avisos.append((f"{pino} está ligado direto no {' e no '.join(sorted(puxa))}: nunca use como saída (seria um curto)",
                           [ref], "direto na energia"))
        elif nome in lista["boot"] and nome in EM_0_AO_LIGAR and papel == "pulldown_fora":
            avisos.append((f"{pino} tem que estar em 0 quando o ESP32 liga ({EM_0_AO_LIGAR[nome]}): não segure "
                           f"{' nem '.join(chaves)} apertado na hora de ligar, ou use outro pino{use}", [ref] + chaves, "pino de boot"))
        elif nome in lista["boot"]:
            avisos.append((f"{pino} é pino de boot{extra}: o ESP32 lê esse pino na hora de ligar pra escolher como sobe; "
                           f"se ele não ligar ou não gravar o programa, troque de pino{use}", quem, "pino de boot"))
        elif nome in lista["serial"]:
            avisos.append((f"{pino} é a serial do PC: a gravação do programa e o print passam por ele, e o que estiver ligado "
                           f"pode atrapalhar; se não gravar, troque de pino{use}", quem, "pino da serial"))
        if nome in lista["psram"]:
            avisos.append((f"{pino}: nos módulos WROVER esse pino é da memória extra; o WROOM-32 deste DevKit não tem essa "
                           "memória, então funciona (só não troque por um DevKit com WROVER)", [ref], "psram"))
        if papel == "analogica" and lista["adc1"] and nome not in lista["adc1"]:
            avisos.append((f"{pino} não é do ADC1: a leitura de tensão pode não funcionar (use um de "
                           f"{', '.join(sorted(lista['adc1'], key=lambda g: int(g[4:])))})", quem, "fora do ADC1"))
    return problemas, avisos


def ligar_esp32(modelo, estado, vdd, ldr=None):
    """liga com o ESP32 no lugar da pilha: chaves apertadas e piezo na borda do apito (vira fio); ldr = {ref: ohms}"""
    aj = {"chave": {p["ref"]: True for p in modelo["pecas"] if modelo_de(p) == "chave"},
          "piezo": {p["ref"]: True for p in modelo["pecas"] if modelo_de(p) == "piezo"}, "ldr": ldr or {}}
    return circuito.resolver(circuito.com_pinos(modelo, estado, vdd), aj)


def combinacoes(base, saidas):
    """cada saída em 1 e em 0: todas juntas e cada uma sozinha contra as outras. O primeiro é todas em 1"""
    niveis = [dict.fromkeys(saidas, 1), dict.fromkeys(saidas, 0)]
    for s in saidas:
        niveis += [{**dict.fromkeys(saidas, 0), s: 1}, {**dict.fromkeys(saidas, 1), s: 0}]
    vistos, estados = set(), []
    for n in niveis:
        if tuple(n.items()) not in vistos:
            vistos.add(tuple(n.items()))
            estados.append({**base, **n})
    return estados


def com_vf(modelo, campo):
    """o modelo com cada LED no vf_min ou no vf_max do datasheet (LED sem o campo fica no vf típico)"""
    def troca(p):
        e = p.get("eletrica") or {}
        return {**p, "eletrica": {**e, "vf": e[campo]}} if e.get("modelo") == "led" and e.get(campo) else p
    return {**modelo, "pecas": [troca(p) for p in modelo["pecas"]]}


def juntar(resultados):
    """um resultado só: cada peça no estado em que passa mais corrente; as nets e o 'entra' são os do primeiro estado"""
    pecas = {}
    for r in resultados:
        for ref, x in r["pecas"].items():
            if ref not in pecas or abs(x.get("i", 0)) > abs(pecas[ref].get("i", 0)):
                pecas[ref] = x
    return {**resultados[0], "pecas": pecas}


def soma_3v3(r):
    """o que o regulador entrega: o 3V3 mais os pinos que fornecem (o pino que afunda corrente não soma)"""
    return sum(max(x["i"], 0) for ref, x in r["pecas"].items() if ref == "~3V3" or ref.startswith("~GPIO"))


def curto_do_3v3(modelo, u):
    """as chaves (apertadas) e os piezos (na borda do apito) que fecham um caminho do 3V3 direto pro GND, ou None.
    Aí a corrente só pararia no r_3v3, que é suposição: vira 'curto', sem número. [] = o 3V3 está no GND já no txt"""
    v3, gnd = net_do_pino(u, "3V3"), net_do_pino(u, "GND")
    if not v3 or not gnd:
        return None
    vizinhos = {}   # net -> [(ref, a net do outro lado)]
    for p in modelo["pecas"]:
        e, m = p.get("eletrica") or {}, modelo_de(p)
        if m not in ("chave", "piezo"):
            continue
        a, b = (e["lados"][0][0], e["lados"][1][0]) if m == "chave" else ("1", "2")
        na, nb = (next((q["net"] for q in p["pinos"] if q["n"] == n), None) for n in (a, b))
        if na and nb:
            vizinhos.setdefault(na, []).append((p["ref"], nb))
            vizinhos.setdefault(nb, []).append((p["ref"], na))
    caminho, fila = {v3: []}, [v3]
    for net in fila:
        for ref, outra in vizinhos.get(net, []):
            if outra not in caminho:
                caminho[outra] = caminho[net] + [ref]
                fila.append(outra)
    return caminho.get(gnd)


def numero(x):
    return blocos.e_numero(x)


def lux_de(texto):
    """'10' ou '1,5' (com vírgula, do jeito do Luiz) -> lux"""
    return float(texto.replace(",", "."))


def volts_no_ldr(modelo, info, ldr, lux, canto="meio", vdd=None):
    """a tensão que o ADC lê no GPIO do LDR com essa luz (lux 0 = escuro), pelo circuito inteiro: com_pinos + resolver
    com o LDR em ohms_do_ldr. É a mesma conta que o programa usa pros volts do roteiro; no divisor de sempre
    (3V3 → resistor → GPIO → LDR → GND) dá igual ao circuito.divisor_do_ldr, e com mais peças no caminho (um resistor
    entre o pino e o LDR, o divisor ligado num GPIO) ela continua certa, onde a conta do divisor sozinha erraria"""
    e = next(p for p in modelo["pecas"] if p["ref"] == ldr)["eletrica"]
    r = ligar_esp32(modelo, info["estado"], vdd or info["eletrica"]["vdd"], {ldr: circuito.ohms_do_ldr(e, lux, canto, ldr)})
    return r["nets"][info["ldr"][ldr][1]]


def faixa_do_ldr(modelo, info, ldr, lux):
    """(menor, maior) tensão no GPIO do LDR: nos cantos min e max do LDR e com o 3V3 em vdd_min e vdd_max
    (o que estiver pendente fica no vdd)"""
    e = info["eletrica"]
    tensoes = [e[k] if numero(e.get(k)) else e["vdd"] for k in ("vdd_min", "vdd_max")]
    vs = [volts_no_ldr(modelo, info, ldr, lux, canto, vdd) for canto in ("min", "max") for vdd in tensoes]
    return min(vs), max(vs)


def lux_de_decisao(pasta, ref):
    """os lux que o requisitos.md pede pro LDR (verifica: adc_na_faixa LDR1 10 23)"""
    try:
        obj = ler_requisitos((pasta / "requisitos.md").read_text())
    except (OSError, gerar.ErroTxt):
        return []
    lux = []
    for item in obj["itens"]:
        for v in item["verifica"]:
            cmd, *a = v["texto"].split()
            if cmd == "adc_na_faixa" and a[0] == ref:
                lux += [lux_de(x) for x in a[1:]] or [circuito.LUX_PADRAO]
    return lux


def frase_do_ldr(modelo, info, ref, luxes, pino):
    e = info["eletrica"]
    partes, fora = [], []
    for lux in sorted({0, *luxes}):   # 0 = o escuro, uma vez só
        lo, hi = faixa_do_ldr(modelo, info, ref, lux)
        v = volts(volts_no_ldr(modelo, info, ref, lux))
        partes.append(f"{num(lux)} lux {v} V ({volts(lo)} a {volts(hi)})" if lux else f"escuro {v} V")
        if e.get("adc_min") is not None and e.get("adc_max") is not None and (lo < e["adc_min"] or hi > e["adc_max"]):
            fora.append(f"{num(lux)} lux" if lux else "escuro")
    cantos = ("nos cantos do LDR e do 3V3" if numero(e.get("vdd_min")) and numero(e.get("vdd_max"))
              else "nos cantos do LDR; a faixa do 3V3 está pendente, então fica no 3V3 do meio")
    texto = f"{ref} no {pino}: " + ", ".join(partes) + f" (entre parênteses, {cantos})"
    if e.get("adc_min") is not None and e.get("adc_max") is not None:
        texto += f"; a faixa boa do ADC é {volts(e['adc_min'])} a {volts(e['adc_max'])} V"
        texto += f", fora dela: {', '.join(fora)}" if fora else ", tudo dentro"
    return texto


def rotulos_de(lista):
    """[(texto, refs, rótulo)] -> {ref: rótulo}; cada peça fica com o rótulo do primeiro em que aparece"""
    rotulos = {}
    for _, onde, rot in lista:
        for r in onde:
            rotulos.setdefault(r, rot)
    return rotulos


def reprovar(problemas):
    raise Falhou(" · ".join(t for t, _, _ in problemas), rotulos=rotulos_de(problemas))


def e_lista(itens):
    """['a', 'b', 'c'] -> 'a, b e c'"""
    return " e ".join([", ".join(itens[:-1]), itens[-1]]) if len(itens) > 1 else "".join(itens)


def liga_com_esp32(ctx, mcus):
    modelo = ctx["modelo"]
    if len(mcus) > 1:
        raise Pulou(f"mais de um ESP32 na placa ({', '.join(u['ref'] for u in mcus)}): ainda não sei ligar no papel")
    u = mcus[0]
    e, ref = u["eletrica"], u["ref"]
    pecas = {p["ref"]: p for p in modelo["pecas"]}
    papeis = papel_dos_pinos(modelo, u)
    regras, avisos = regras_dos_pinos(modelo, u, papeis)
    so_entrada = set(e.get("so_entrada") or [])
    base = {}   # o estado de cada pino: saída em 1 (o pior caso troca pra 0) ou o pull-up de dentro
    for nome, (papel, _, _) in papeis.items():
        if nome not in so_entrada and papel in ("saida", "pullup", "pullup_fora"):
            base[nome] = 1 if papel == "saida" else "pullup"
    saidas = [n for n, v in base.items() if v == 1]
    ldrs = [p for p in modelo["pecas"] if modelo_de(p) == "ldr"]
    vdd = e.get("vdd")
    vdd_max = e["vdd_max"] if numero(e.get("vdd_max")) else vdd   # pendente: o pior caso fica no do meio, e a frase diz
    lim, orc, vil = (e.get(k) if numero(e.get(k)) else None for k in ("i_pino", "orcamento_3v3", "vil"))
    pendente = [nome for k, nome in (("i_pino", "a força padrão do pino"), ("orcamento_3v3", "o orçamento do 3V3"),
                                     ("vdd_max", "a tensão máxima do 3V3")) if not numero(e.get(k))]
    estados = combinacoes(base, saidas)
    baixo = com_vf(modelo, "vf_min")   # o LED de vf mínimo é o que mais puxa
    try:
        luzes = [{p["ref"]: circuito.ohms_do_ldr(p["eletrica"], lux, "min", p["ref"]) for p in ldrs} for lux in (0, 100)] if ldrs else [{}]
        nominal = [ligar_esp32(modelo, s, vdd) for s in estados]
        ate = [ligar_esp32(baixo, s, vdd) for s in estados]
        de = [ligar_esp32(com_vf(modelo, "vf_max"), s, vdd) for s in estados]
        pior = [ligar_esp32(baixo, s, vdd_max, luz) for luz in luzes for s in estados]
    except (ValueError, ZeroDivisionError, KeyError, TypeError) as err:
        if regras:   # o que o datasheet não deixa vale mesmo sem a conta
            reprovar(regras)
        if isinstance(err, ValueError) and "falta conferir" in str(err):   # número pendente: a conta recusa, não inventa
            raise Pulou(f"não dá pra ligar no papel ainda · {err}")
        raise Falhou(f"não consegui resolver o circuito: {err}", [ref], "não resolveu")
    sim = {"nominal": juntar(nominal), "nova": juntar(pior)}   # cada peça no estado em que mais puxa
    pn, pp = sim["nominal"]["pecas"], sim["nova"]["pecas"]
    i_pinos = {n: max(abs(r["pecas"]["~" + n]["i"]) for r in pior) for n in base}
    soma = max(soma_3v3(r) for r in pior)
    curto, em_curto = curto_do_3v3(modelo, u), []
    queima, limites, resto, frases = [], [], [], []
    if curto is not None:   # a corrente do curto só pararia no r_3v3 (suposição): sem número
        em_curto = curto
        como = e_lista([f"{x} {'apertado' if modelo_de(pecas[x]) == 'chave' else 'na borda do apito'}" for x in curto])
        limites.append((f"curto: com {como}, o 3V3 do {ref} vai direto pro GND" if curto else
                        f"curto: o 3V3 do {ref} está ligado direto no GND", [ref] + curto, "curto"))
    for n, i in i_pinos.items():
        if lim and i > lim:
            limites.append((f"{ref} {nome_do_pino(u, n)} passa até {ma(i)} mA no pior caso: a força padrão do pino é "
                            f"~{ma(lim)} mA (ponha um resistor maior)", [ref] + papeis[n][1], "puxa demais do pino"))
    if orc and soma > orc and curto is None:
        limites.append((f"o 3V3 do {ref} entrega até {ma(soma)} mA no pior caso, acima do orçamento de {ma(orc)} mA", [ref], "3V3 no limite"))
    ldr_gpio, leitura = {}, {}   # LDR -> (GPIO, net) onde o ADC lê; botão -> o que o pino lê com ele apertado
    for nome, (papel, ramo, _) in papeis.items():
        net = net_do_pino(u, nome)
        if papel == "analogica":   # o GPIO colado no LDR ganha do que chega nele por um resistor
            for x in ramo:
                if modelo_de(pecas[x]) == "ldr" and (x not in ldr_gpio or any(q["net"] == net for q in pecas[x]["pinos"])):
                    ldr_gpio[x] = (nome, net)
        elif papel == "pullup_fora" or (papel == "pullup" and nome not in so_entrada):   # apertado, o pino tem que ler 0
            v = max(r["nets"][net] for r in nominal)
            chaves = [x for x in ramo if modelo_de(pecas[x]) == "chave"]
            texto = f"{' e '.join(chaves)} apertado: o {nome_do_pino(u, nome)} fica em {volts(v)} V"
            if vil:   # vil é fração do 3V3 (DS v5.3, Tabela 5-3)
                texto += f" (até {volts(vil * vdd)} V o pino lê 0)"
                if v > vil * vdd:
                    avisos.append((f"{texto}: o programa pode não ver o botão apertado", [ref] + ramo, "botão não lê 0"))
            leitura.update(dict.fromkeys(chaves, texto))
    info = {"ref": ref, "eletrica": e, "estado": base, "ldr": ldr_gpio, "pinos": i_pinos, "soma": soma,
            "pendente": pendente}
    # pino_seguro: False com regra quebrada ou limite passado; '?' (None) com número pendente que a conta pede
    info["seguro"] = False if regras or limites else None if pendente else True
    ctx["sim"] = {**sim, "esp32": info}   # os requisitos usam isto
    calor = {}   # o que cada resistor aguenta -> ['R1 7 mW', ...]
    for p in modelo["pecas"]:
        pe, r, m = p["eletrica"], p["ref"], modelo_de(p)
        if m == "led":
            i_ate, i_de = max(x["pecas"][r]["i"] for x in ate), max(x["pecas"][r]["i"] for x in de)
            if pp[r]["i"] > pe["i_max"]:
                queima.append((f"{r} queima: até {ma(pp[r]['i'])} mA no pior caso, o limite é {ma(pe['i_max'])} mA", [r], "queima"))
            brilho = blocos.brilho_da_corrente(pe, i_ate)
            quanto = f" ≈ {brilho * 100:.0f}% do anúncio" if brilho is not None else ""
            apagado = "" if pn[r]["acende"] else ", não acende"
            no_pior, limite = f"{ma(pp[r]['i'])} mA no pior caso", f"o limite é {ma(pe['i_max'])} mA"
            if pe.get("vf_min"):
                faixa = (f"de {ma(i_de)} a {ma(i_ate)} mA com {num(vdd)} V, cada LED sai um pouco diferente"
                         if ma(i_de) != ma(i_ate) else f"{ma(i_ate)} mA com {num(vdd)} V")
                frases.append(f"{r}: até {ma(i_ate)} mA{quanto}{apagado} ({faixa}; {no_pior}; {limite})")
            else:   # sem o vf mínimo, o máximo fica sem número: a conta usa o vf típico
                menos = f"pelo menos {ma(i_de)} mA com o vf máximo; " if ma(i_de) != ma(i_ate) else ""
                frases.append(f"{r}: {ma(i_ate)} mA com o vf típico{quanto}{apagado} ({menos}o vf mínimo do LED está pendente, "
                              f"então o máximo fica sem número; {no_pior} com o vf típico; {limite})")
        elif m == "resistor":
            if pp[r]["p"] > pe["potencia_max"]:
                resto.append((f"{r} esquenta demais: {mw(pp[r]['p'])} mW no pior caso, aguenta {mw(pe['potencia_max'])} mW", [r], "esquenta"))
            calor.setdefault(pe["potencia_max"], []).append(f"{r} {mw(pp[r]['p'])} mW")
        elif m == "chave":
            if pe.get("i_max") and abs(pp[r]["i"]) > pe["i_max"] and r not in em_curto:
                resto.append((f"{r} passa {ma(abs(pp[r]['i']))} mA no pior caso, o limite dele é {ma(pe['i_max'])} mA", [r], "corrente alta"))
            if r in leitura:
                frases.append(leitura[r])
        elif m == "ldr" and r in ldr_gpio:
            luxes = sorted({1, 10, 100, *lux_de_decisao(ctx["pasta"], r)})
            frases.append(frase_do_ldr(modelo, info, r, luxes, nome_do_pino(u, ldr_gpio[r][0])))
        elif m == "piezo":
            frases.append(f"{r}: pico de {ma(abs(pn[r]['i']))} mA na borda do apito com {num(vdd)} V "
                          f"({ma(abs(pp[r]['i']))} mA no pior caso); parado, ele não passa corrente")
    for aguenta, rs in calor.items():
        frases.append(f"esquenta{'m' if len(rs) > 1 else ''} no pior caso: {', '.join(rs)} "
                      f"({'cada um aguenta' if len(rs) > 1 else 'aguenta'} {mw(aguenta)} mW)")
    grupos = {}
    for nome, (papel, _, _) in papeis.items():
        grupos.setdefault(papel, []).append(nome_do_pino(u, nome))
    partes = [f"{PAPEL[k]}: {', '.join(v)}" for k, v in grupos.items()]
    if i_pinos:
        n = max(i_pinos, key=i_pinos.get)
        forca = f"a força padrão do pino é ~{ma(lim)} mA" if lim else "a força padrão do pino está pendente"
        partes.append(f"o pino que mais puxa é o {nome_do_pino(u, n)}, até {ma(i_pinos[n])} mA no pior caso ({forca})")
    partes.append(f"o 3V3 entrega até {ma(soma)} mA" + (f" (o orçamento é {ma(orc)} mA)" if orc else " (o orçamento está pendente)"))
    frases.append(f"{ref}: " + "; ".join(partes))
    tem = {modelo_de(p) for p in modelo["pecas"]}
    pior_caso = (["cada saída em 1 e em 0"] if saidas else []) + [
        txt for m, txt in (("chave", "botões apertados"), ("piezo", "piezo na borda do apito"),
                           ("ldr", "LDR no escuro e com 100 lux")) if m in tem]
    pior_caso.append(f"3V3 em {num(vdd_max)} V" if numero(e.get("vdd_max")) else
                     f"3V3 em {num(vdd)} V (a tensão máxima do 3V3 está pendente: o pior caso usa o 3V3 do meio)")
    if any(modelo_de(p) == "led" and numero(p["eletrica"].get("vf_min")) for p in modelo["pecas"]):
        pior_caso.append("LED de vf mínimo")
    frases.append("pior caso: " + e_lista(pior_caso))
    if numero(e.get("vdd_min")) and e.get("condicao_3v3"):
        frases.append(f"3V3 de {num(e['vdd_min'])} a {num(vdd_max)} V: {e['condicao_3v3']}")
    if pendente:
        frases.append(f"falta conferir no datasheet: {e_lista(pendente)} (até lá, o pino_seguro fica em ?)")
    frases += [f"aviso: {texto}" for texto, _, _ in avisos]
    if regras or queima or limites or resto:
        reprovar(regras + queima + limites + resto)
    if avisos:
        ctx["aviso"] = {"texto": " · ".join(t for t, _, _ in avisos), "rotulos": rotulos_de(avisos)}
    return " · ".join(frases)


def regras_fabrica(ctx):
    modelo = ctx["modelo"]
    w, h = modelo["placa"]["w"], modelo["placa"]["h"]
    problemas = []   # (texto, onde, rotulo)
    for t in modelo["trilhas"]:
        if t["largura"] < TRILHA_MIN:
            problemas.append((f"trilha {t['de']}–{t['ate']} com {mm(t['largura'])} mm (mínimo {mm(TRILHA_MIN)})",
                              refs(t["de"], t["ate"]), "trilha fina"))
    for d, a, b in pares_perto(modelo, ESPACO_MIN):
        problemas.append((f"{a} a {mm(max(d, 0))} mm de {b} (mínimo {mm(ESPACO_MIN)})", refs(a, b), "perto demais"))
    furos_pad = []
    for peca in modelo["pecas"]:
        for p in peca["pinos"]:
            if not p["furo"]:
                continue
            nome = f"{peca['ref']}.{p['n']}"
            furos_pad.append((nome, p["x"], p["y"], p["furo"]))
            if not FURO_MIN <= p["furo"] <= FURO_MAX:
                problemas.append((f"furo de {nome} com {mm(p['furo'])} mm", [peca["ref"]], "furo"))
            menor = p["pad"]["d"] if p["pad"]["forma"] == "C" else min(p["pad"]["w"], p["pad"]["h"])
            anel = (menor - p["furo"]) / 2
            if anel < ANEL_MIN:
                problemas.append((f"anel de {nome} com {mm(anel)} mm (mínimo {mm(ANEL_MIN)})", [peca["ref"]], "anel fino"))
    for v in modelo.get("vias", []):
        nome = f"via {v['de']}–{v['ate']}"
        furos_pad.append((nome, v["x"], v["y"], v["furo"]))
        if not FURO_MIN <= v["furo"] <= FURO_MAX:
            problemas.append((f"{nome} com furo de {mm(v['furo'])} mm", refs(v["de"], v["ate"]), "furo"))
        if (v["d"] - v["furo"]) / 2 < ANEL_MIN:
            problemas.append((f"anel da {nome} com {mm((v['d'] - v['furo']) / 2)} mm (mínimo {mm(ANEL_MIN)})", refs(v["de"], v["ate"]), "anel fino"))
    for i, (n1, x1, y1, d1) in enumerate(furos_pad):
        for n2, x2, y2, d2 in furos_pad[i + 1:]:
            vao = math.hypot(x1 - x2, y1 - y2) - d1 / 2 - d2 / 2
            if vao < FURO_FURO_MIN:
                problemas.append((f"furos {n1} e {n2} a {mm(vao)} mm (mínimo {mm(FURO_FURO_MIN)})", refs(n1, n2), "furos colados"))
    for f in modelo["furos"]:
        if f["d"] < FURO_NPTH_MIN:
            problemas.append((f"furo de fixação com {mm(f['d'])} mm (mínimo {mm(FURO_NPTH_MIN)})", [], ""))
        r = f["d"] / 2
        if f["x"] - r < 0 or f["y"] - r < 0 or f["x"] + r > w or f["y"] + r > h:
            problemas.append(("furo de fixação fora da placa", [], ""))
    for nome, _, miolo, raio, _ in cobres(modelo):
        x0, y0, x1, y1 = caixa(miolo, raio)
        folga = min(x0, y0, w - x1, h - y1)
        if folga < BORDA_MIN:
            problemas.append((f"{nome} a {mm(folga)} mm da borda (mínimo {mm(BORDA_MIN)})", refs(nome), "perto da borda"))
        for f in modelo["furos"]:
            d = distancia((miolo, raio), (("seg", (f["x"], f["y"]), (f["x"], f["y"])), f["d"] / 2))
            if d < BORDA_MIN:
                problemas.append((f"{nome} a {mm(d)} mm do furo de fixação (mínimo {mm(BORDA_MIN)})", refs(nome), "perto do furo"))
    pads = [(n, m, r, l) for n, _, m, r, l in cobres(modelo) if not n.startswith(("trilha", "via"))]   # via fica coberta pela mascara
    for i, (n1, m1, r1, l1) in enumerate(pads):
        for n2, m2, r2, l2 in pads[i + 1:]:
            if not l1 & l2:
                continue
            d = distancia((m1, r1), (m2, r2))
            if 0 < d < PONTE_MIN:
                problemas.append((f"máscara entre {n1} e {n2} com {mm(d)} mm (mínimo {mm(PONTE_MIN)})", refs(n1, n2), "máscara"))
    if min(gerar.SILK, gerar.LETRA_LINHA) < SILK_MIN or gerar.LETRA < LETRA_MIN:
        problemas.append((f"serigrafia fina demais (linha {mm(SILK_MIN)} e letra {mm(LETRA_MIN)} mm no mínimo)", [], ""))
    if problemas:
        mais = f" (e mais {len(problemas) - 1})" if len(problemas) > 1 else ""
        rotulos = {}
        for _, onde, rotulo in problemas:
            for ref in onde:
                rotulos.setdefault(ref, rotulo)
        raise Falhou(problemas[0][0] + mais, rotulos=rotulos)
    return "trilha, espaço, furo, anel, borda, máscara e serigrafia (JLCPCB)"


MAPA_GERBER = {r".*-F_Cu\.gbr": "top copper", r".*-B_Cu\.gbr": "bottom copper",
               r".*-F_Mask\.gbr": "top mask", r".*-B_Mask\.gbr": "bottom mask",
               r".*-F_Silkscreen\.gbr": "top silk", r".*-Edge_Cuts\.gbr": "mechanical outline",
               r".*-PTH\.drl": "drill plated", r".*-NPTH\.drl": "drill nonplated"}


def rele_gerber(ctx):
    try:
        from gerbonara import LayerStack
    except ImportError:
        raise Falhou("gerbonara não instalado: uv pip install -r requirements.txt")
    saida = ctx["pasta"] / "saida"
    with warnings.catch_warnings(record=True) as avisos:
        warnings.simplefilter("always")
        pilha = LayerStack.open_dir(saida, autoguess=False, overrides=MAPA_GERBER)
    if avisos:
        raise Falhou(f"{len(avisos)} aviso(s): {avisos[0].message}")
    ctx["pilha"] = pilha
    lidos = [f for f in saida.iterdir() if any(re.fullmatch(e, f.name) for e in MAPA_GERBER)]
    return f"{len(lidos)} arquivos lidos pelo gerbonara, nenhum aviso"


def tira_foto(ctx):
    saida = ctx["pasta"] / "saida"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # avisa das camadas que ainda nao existem (mascara, serigrafia)
        svg = str(ctx["pilha"].to_pretty_svg(side="top"))
    vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', svg)[1].split()]
    largura = 1400
    altura = round(largura * vb[3] / vb[2])
    svg = re.sub(r'width="[^"]*" height="[^"]*"', f'width="{largura}" height="{altura}"', svg, count=1)
    (saida / "foto.svg").write_text(svg)
    chrome = next(filter(None, map(shutil.which, ["google-chrome", "chromium", "chromium-browser"])), None)
    if not chrome:
        return "sem Chrome pra virar png; salvei saida/foto.svg"
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    f"--screenshot={(saida / 'foto.png').resolve()}", f"--window-size={largura},{altura}",
                    (saida / "foto.svg").resolve().as_uri()], capture_output=True, timeout=60, check=True)
    return "saida/foto.png, desenhada a partir do Gerber"


# requisitos: o requisitos.md declara o objetivo e, pra cada requisito, as pecas e como verificar
CHECAGENS = {"existe": 1, "ligado": 2, "separado": 2, "sem_pino_solto": 1, "acende": 1, "nao_queima": 1,
             "brilho": 1, "pino_seguro": 1, "adc_na_faixa": (1, None)}   # checagem -> quantos valores ((1, None) = 1 ou mais)
MOTIVOS = {"existe": "falta a peça", "ligado": "falta ligar", "separado": "em curto", "sem_pino_solto": "pino solto",
           "acende": "não acende", "nao_queima": "queima", "brilho": "brilho diferente do pedido",
           "pino_seguro": "pino do ESP32 em risco", "adc_na_faixa": "fora da faixa boa do ADC"}


def ler_requisitos(texto):
    obj = {"titulo": "", "texto": "", "itens": []}
    atual = None
    for n, linha in enumerate(texto.splitlines(), 1):
        l = linha.strip()
        if not l:
            continue
        if l.startswith("# "):
            obj["titulo"] = l[2:].removeprefix("Objetivo:").strip()
        elif l.startswith("## "):
            ident, _, titulo = l[3:].partition(" ")
            atual = {"id": ident, "titulo": titulo.strip(), "pecas": [], "detalhes": [], "verifica": []}
            obj["itens"].append(atual)
        elif atual is None:
            obj["texto"] = f"{obj['texto']} {l}".strip()
        elif l.startswith("pecas:"):
            atual["pecas"] += l[6:].split()
        elif l.startswith("verifica:"):
            p = l[9:].split()
            if not p or p[0] not in CHECAGENS:
                raise gerar.ErroTxt(n, f"checagem desconhecida '{l[9:].strip()}' (tem: {', '.join(CHECAGENS)})")
            quantos = CHECAGENS[p[0]]
            minimo, maximo = quantos if isinstance(quantos, tuple) else (quantos, quantos)
            if len(p) - 1 < minimo or (maximo is not None and len(p) - 1 > maximo):
                raise gerar.ErroTxt(n, f"'{p[0]}' espera {quantos} valores" if maximo else f"'{p[0]}' espera {minimo} ou mais valores")
            if p[0] == "adc_na_faixa":   # adc_na_faixa LDR1 10 23: os lux em que o programa decide (1,5 vale)
                for lux in p[2:]:
                    try:
                        ok = math.isfinite(lux_de(lux)) and lux_de(lux) >= 0
                    except ValueError:
                        ok = False
                    if not ok:
                        raise gerar.ErroTxt(n, f"'{lux}' devia ser os lux, um número (ex: adc_na_faixa LDR1 10 23)")
            atual["verifica"].append({"texto": " ".join(p)})
        elif l.startswith("- "):
            atual["detalhes"].append(l[2:])
    return obj


def checar(texto, modelo, sim, projeto=None):
    """True/False, ou None quando nao da pra saber (acende/nao_queima/brilho sem simulacao)"""
    cmd, *a = texto.split()
    pecas = {p["ref"]: p for p in modelo["pecas"]}
    pecas_da_net = {}   # net -> pecas que tem pino nela
    for p in modelo["pecas"]:
        for pino in p["pinos"]:
            pecas_da_net.setdefault(pino["net"], set()).add(p["ref"])

    def nets(x):   # REF.PINO -> net do pino; REF -> nets de qualquer pino dela; senao e nome de net
        if "." in x:
            ref, n = x.split(".", 1)
            pino = next((q for q in pecas.get(ref, {}).get("pinos", []) if q["n"] == n), None)
            return {pino["net"]} if pino and pino["net"] else set()
        if x in pecas:
            return {q["net"] for q in pecas[x]["pinos"] if q["net"]}
        return {x}

    if cmd == "existe":
        return a[0] in pecas
    if cmd == "ligado":
        return bool(nets(a[0]) & nets(a[1]))
    if cmd == "separado":   # nao pode ser a mesma net (ex: os dois lados de um botao)
        return not nets(a[0]) & nets(a[1])
    if cmd in ("acende", "nao_queima"):   # com as chaves apertadas: acende na pilha nominal, nao queima na nova
        r = (sim or {}).get("nominal", {}).get("pecas", {}).get(a[0])
        if not r or "acende" not in r:   # sem simulacao, ou a peca nao e LED
            return None
        return r["acende"] if cmd == "acende" else not sim["nova"]["pecas"][a[0]]["queima"]
    if cmd == "brilho":   # o brilho na pilha nominal e o nivel que o Luiz pediu (fraca/media/forte, o mais perto)
        r = (sim or {}).get("nominal", {}).get("pecas", {}).get(a[0])
        pedido = blocos.brilho_pedido(projeto or {}, a[0])[0]   # o ajuste desse LED, se tiver; senão a resposta geral
        e = (pecas.get(a[0]) or {}).get("eletrica") or {}
        b = blocos.brilho_da_corrente(e, r["i"]) if r and "acende" in r else None
        if b is None or not pedido:
            return None
        return blocos.nivel_do_brilho(b) == pedido
    if cmd == "sem_pino_solto":   # cada pino chega em alguma OUTRA peca (o par interno do botao nao conta)
        return a[0] in pecas and all(q["net"] and pecas_da_net[q["net"]] - {a[0]} for q in pecas[a[0]]["pinos"])
    info = (sim or {}).get("esp32")   # o que a etapa 4 viu do ESP32 (só existe se ela ligou a placa com ele)
    if cmd == "pino_seguro":   # nenhum pino acima da força padrão, a soma no orçamento do 3V3, nenhum curto e nenhuma
        # regra quebrada; '?' com número pendente. Aviso não conta (botão num pino de boot, psram)
        return info["seguro"] if info and info["ref"] == a[0] else None
    if cmd == "adc_na_faixa":   # nos lux pedidos (sem lux, 10), nos cantos do LDR e do 3V3, o ADC lê dentro da faixa boa
        e = (info or {}).get("eletrica") or {}
        if not info or a[0] not in info["ldr"] or not e.get("adc1") or e.get("adc_min") is None or e.get("adc_max") is None:
            return None
        if info["ldr"][a[0]][0] not in e["adc1"]:
            return False
        luxes = [lux_de(x) for x in a[1:]] or [circuito.LUX_PADRAO]
        return all(e["adc_min"] <= v <= e["adc_max"] for lux in luxes for v in faixa_do_ldr(modelo, info, a[0], lux))


def avaliar_requisitos(pasta, modelo, sim=None):
    """sim = o resultado da etapa 4 (so existe se ela passou); sem ele, acende/nao_queima ficam em '?'"""
    arq = pasta / "requisitos.md"
    if not arq.exists():
        return None
    try:
        obj = ler_requisitos(arq.read_text())
    except gerar.ErroTxt as e:
        return {"titulo": "", "texto": "", "itens": [], "erro": f"requisitos.md, linha {e.linha}: {e.msg}"}
    projeto = blocos.ler_projeto(pasta)
    for item in obj["itens"]:
        if modelo is None:
            item.update(status="?", motivo="a placa não montou")
            continue
        for v in item["verifica"]:
            v["ok"] = checar(v["texto"], modelo, sim, projeto)
        falha = next((v for v in item["verifica"] if v["ok"] is False), None)
        if not item["verifica"]:
            item.update(status="?", motivo="sem verificação")
        elif any(v["ok"] is None for v in item["verifica"]) and not falha:
            item.update(status="?", motivo="não dá pra ligar no papel")
        elif falha:
            item.update(status="falha", motivo=MOTIVOS[falha["texto"].split()[0]])
        else:
            item.update(status="ok", motivo="ok")
    return obj


# a rodada
def salvar(arq, estado):
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=1))
    tmp.replace(arq)   # troca de uma vez: a bancada nunca le arquivo pela metade


def rodar(pasta, frase=None):
    arq = pasta / "testes.json"
    try:
        anterior = json.loads(arq.read_text())
    except (OSError, ValueError):
        anterior = {}
    estado = {"versao": None, "rodando": True, "inicio": datetime.now().isoformat(timespec="seconds"),
              "etapas": [{"nome": n, "estado": "aguardando", "detalhe": ""} for n in ETAPAS],
              "requisitos": {}, "resumo": ""}
    ctx = {"pasta": pasta, "frase": frase, "estado": estado, "anterior": anterior}
    (pasta / "saida" / "fabrica.zip").unlink(missing_ok=True)
    salvar(arq, estado)
    funcoes = [le_txt, confere_pecas, confere_ligacoes, liga_circuito, regras_fabrica, rele_gerber, tira_foto]
    try:
        rodar_etapas(ctx, funcoes, arq)
    finally:   # aconteca o que acontecer, o testes.json nunca fica "rodando" pra sempre
        estado["rodando"] = False
        estado["fim"] = datetime.now().isoformat(timespec="seconds")
        salvar(arq, estado)
    return estado


def rodar_etapas(ctx, funcoes, arq):
    estado, pasta = ctx["estado"], ctx["pasta"]
    for etapa, funcao in zip(estado["etapas"], funcoes):
        etapa["estado"] = "rodando"
        salvar(arq, estado)
        ctx.pop("aviso", None)
        try:
            etapa["detalhe"] = funcao(ctx)
            etapa["estado"] = "ok"
            if ctx.get("aviso"):   # passou com aviso (ex.: trilha na antena): o texto e as etiquetas nas peças
                rotulos = ctx["aviso"]["rotulos"]
                etapa.update(aviso=ctx["aviso"]["texto"], onde=list(rotulos), rotulos=rotulos)
        except Pulou as e:
            etapa.update(estado="pulou", detalhe=str(e))
        except Falhou as e:
            etapa.update(estado="falhou", detalhe=e.detalhe, onde=e.onde, rotulos=e.rotulos)
        except gerar.ErroTxt as e:
            linhas = ctx.get("texto", "").splitlines()
            etapa.update(estado="falhou", detalhe=f"linha {e.linha}: {e.msg}", onde=e.onde, linha=e.linha,
                         codigo=linhas[e.linha - 1] if 0 < e.linha <= len(linhas) else "",
                         rotulos={ref: "erro no txt" for ref in e.onde})
        except Exception as e:   # erro inesperado tambem para a rodada, sem esconder
            etapa.update(estado="falhou", detalhe=f"erro inesperado: {e!r}", onde=[], rotulos={})
        if etapa["estado"] == "falhou":
            for resto in estado["etapas"][estado["etapas"].index(etapa) + 1:]:
                resto["estado"] = "nao_rodou"
            break
    tudo_ok = all(e["estado"] in ("ok", "pulou") for e in estado["etapas"])
    if tudo_ok and ctx["modelo"]["fabrica"]["pronta"]:
        gerar.zipar(pasta / "saida", ctx["arquivos"])   # fabrica.zip so existe se passou em tudo
    try:
        objetivo = avaliar_requisitos(pasta, ctx.get("modelo"), ctx.get("sim"))
    except Exception as e:   # requisito nao pode derrubar a rodada inteira
        objetivo = {"titulo": "", "texto": "", "itens": [], "erro": f"requisitos: erro inesperado: {e!r}"}
    if objetivo:
        estado["objetivo"] = objetivo
        estado["requisitos"] = {i["id"]: i["status"] for i in objetivo["itens"]}
        for etapa in estado["etapas"]:
            if etapa.get("onde"):
                etapa["requisitos"] = [i["id"] for i in objetivo["itens"] if set(i["pecas"]) & set(etapa["onde"])]
    if ctx["anterior"].get("resumo") and ctx["anterior"].get("versao") == estado["versao"]:
        estado["resumo"] = ctx["anterior"]["resumo"]   # a placa nao mudou, o resumo do Claude continua valendo


def escrever_resumo(pasta, texto):
    arq = pasta / "testes.json"
    estado = json.loads(arq.read_text())
    estado["resumo"] = texto
    salvar(arq, estado)


if __name__ == "__main__":
    args = sys.argv[1:]
    opcoes = {}
    for chave in ("-m", "--resumo"):
        if chave in args:
            i = args.index(chave)
            opcoes[chave] = args[i + 1]
            del args[i:i + 2]
    pasta = Path(args[0] if args else "placas/estudo")
    if "--resumo" in opcoes:
        escrever_resumo(pasta, opcoes["--resumo"])
        sys.exit()
    estado = rodar(pasta, opcoes.get("-m"))
    for i, e in enumerate(estado["etapas"], 1):
        marca = {"ok": "✓", "falhou": "✗"}.get(e["estado"], "·")
        print(f"{marca} {i}. {e['nome']}: {e['detalhe'] or e['estado']}")
    for ident, status in estado["requisitos"].items():
        print(f"  {ident}: {status}")
    if estado.get("objetivo", {}).get("erro"):
        print(f"  {estado['objetivo']['erro']}")
    sys.exit(1 if any(e["estado"] == "falhou" for e in estado["etapas"]) else 0)   # pulou não é falha
