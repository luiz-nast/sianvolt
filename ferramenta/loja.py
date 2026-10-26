"""loja.py: peça de verdade, da loja pra placa. Busca na JLCPCB (o estoque da LCSC, a loja irmã dela),
pega foto e datasheet na LCSC e o desenho oficial da peça (pads, furos, contorno) no EasyEDA, o editor da JLCPCB.

uso: python3 ferramenta/loja.py buscar "100Ω through hole resistor"
     python3 ferramenta/loja.py importar C119304 resistor placas/lanterna
"""
import gzip
import hashlib
import json
import math
import re
import sys
import time
import urllib.request
from pathlib import Path

CACHE = Path.home() / ".cache" / "sianvolt" / "loja"
NAVEGADOR = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
BUSCA = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
DESENHO = "https://easyeda.com/api/products/{}/components?version=6.4.19.5"
FICHA = "https://www.lcsc.com/product-detail/{}.html"
CODIGO = re.compile(r"C\d{1,12}\Z")   # \Z: o $ aceitaria "C1\\n"
UNIDADE = 0.254      # o EasyEDA desenha em unidades de 10 mil = 0,254 mm
UM_DIA = 24 * 3600


class SemLoja(Exception):
    """a loja nao respondeu (sem internet, ou mudou o formato)"""


def pedir(url, dados=None, validade=UM_DIA, binario=False):
    """GET (ou POST com json) com cache em disco; o desenho e a foto de uma peca nao mudam, a busca vale um dia"""
    chave = hashlib.sha1((url + json.dumps(dados or "")).encode()).hexdigest()
    arq = CACHE / chave
    if arq.exists() and (validade is None or time.time() - arq.stat().st_mtime < validade):   # validade 0 = sempre pergunta
        corpo = arq.read_bytes()
    else:
        req = urllib.request.Request(url, data=json.dumps(dados).encode() if dados else None,
                                     headers={"User-Agent": NAVEGADOR, "Accept-Encoding": "gzip",
                                              **({"Content-Type": "application/json"} if dados else {})})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                corpo = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    corpo = gzip.decompress(corpo)
        except OSError as e:
            raise SemLoja(f"a loja não respondeu ({e})")
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = arq.with_name(f"{chave}.{time.time_ns()}.tmp")   # varios agentes buscando juntos: grava inteiro ou nada
        tmp.write_bytes(corpo)
        tmp.replace(arq)
    return corpo if binario else corpo.decode("utf-8", "replace")


# 1. busca: o que a JLCPCB tem em estoque
def item(c):
    precos = sorted(c.get("componentPrices") or [], key=lambda p: p["startNumber"])
    return {
        "codigo": c["componentCode"],
        "modelo": c.get("componentModelEn") or "",
        "marca": c.get("componentBrandEn") or "",
        "pacote": c.get("componentSpecificationEn") or "",
        "descricao": c.get("describe") or "",
        "categoria": c.get("firstSortName") or c.get("componentTypeEn") or "",
        "estoque": c.get("stockCount") or 0,
        "preco": precos[0]["productPrice"] if precos else None,    # US$ por unidade, no menor lote
        "minimo": c.get("minPurchaseNum") or 1,
        "datasheet": c.get("dataManualUrl") or "",
        "link": c["lcscGoodsUrl"] if c.get("lcscGoodsUrl") and " " not in c["lcscGoodsUrl"] else FICHA.format(c["componentCode"]),
        "atributos": {a["attribute_name_en"]: a["attribute_value_name"] for a in c.get("attributes") or []},
    }


def buscar(texto, quantos=10, validade=UM_DIA):
    resposta = pedir(BUSCA, {"keyword": texto, "currentPage": 1, "pageSize": quantos}, validade=validade)
    try:
        lista = json.loads(resposta)["data"]["componentPageInfo"]["list"] or []
    except (ValueError, KeyError, TypeError):
        raise SemLoja("a busca da JLCPCB mudou de formato")
    return [item(c) for c in lista]


def ficha(codigo, validade=UM_DIA):
    """a peca pelo codigo da LCSC (C119304); validade=0 pergunta pra loja agora"""
    achados = [i for i in buscar(codigo, 5, validade) if i["codigo"] == codigo]
    if not achados:
        raise SemLoja(f"{codigo} não está na loja")
    return achados[0]


def pagina(codigo):
    """da pagina da peca na LCSC: a foto da frente e o link direto do datasheet"""
    texto = pedir(FICHA.format(codigo), validade=None)
    fotos = re.search(r'"productImages":\s*\[\s*"([^"]+)"', texto)
    pdf = re.search(r'"pdfUrl":\s*"([^"]+)"', texto)
    return {"foto": fotos[1] if fotos else None, "pdf": pdf[1] if pdf else None}


# 2. desenho oficial (footprint) do EasyEDA: pads, furos e a serigrafia, em mm, com y pra cima
def arco(x0, y0, rx, ry, grande, horario, x1, y1, passos=24):
    """arco do SVG (so circular) em pontos"""
    r = (rx + ry) / 2
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    d = math.hypot(x1 - x0, y1 - y0)
    if d == 0 or r < d / 2:
        return [(x0, y0), (x1, y1)]
    h = math.sqrt(r * r - d * d / 4)
    ux, uy = (y0 - y1) / d, (x1 - x0) / d   # perpendicular a corda
    sinal = 1 if grande != horario else -1
    cx, cy = mx + sinal * h * ux, my + sinal * h * uy
    a0, a1 = math.atan2(y0 - cy, x0 - cx), math.atan2(y1 - cy, x1 - cx)
    if horario and a1 < a0:
        a1 += 2 * math.pi
    if not horario and a1 > a0:
        a1 -= 2 * math.pi
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / passos), cy + r * math.sin(a0 + (a1 - a0) * i / passos))
            for i in range(passos + 1)]


def caminho(d):
    """'M x y L x y A ...' do EasyEDA em listas de pontos"""
    linhas, atual = [], []
    t = re.findall(r"[MLAZ]|-?\d+(?:\.\d+)?", d.replace(",", " "))
    i = 0
    while i < len(t):
        c = t[i]
        if c == "M":
            if len(atual) > 1:
                linhas.append(atual)
            atual = [(float(t[i + 1]), float(t[i + 2]))]
            i += 3
        elif c == "L":
            i += 1
            while i + 1 < len(t) and t[i] not in "MLAZ":
                atual.append((float(t[i]), float(t[i + 1])))
                i += 2
        elif c == "A":
            rx, ry, _, grande, horario, x, y = map(float, t[i + 1:i + 8])
            atual += arco(*atual[-1], rx, ry, int(grande), int(horario), x, y)[1:]
            i += 8
        elif c == "Z":
            if atual:
                atual.append(atual[0])
            i += 1
        else:
            i += 1
    if len(atual) > 1:
        linhas.append(atual)
    return linhas


SILK = "3"   # camada da serigrafia de cima no EasyEDA (1 cobre de cima, 11 todas as camadas, 99 contorno da peca)


def desenho(codigo):
    dado = json.loads(pedir(DESENHO.format(codigo), validade=None))
    if not dado.get("success"):
        raise SemLoja(f"o EasyEDA não tem o desenho de {codigo}")
    res = dado["result"]
    pacote = res["packageDetail"]["dataStr"]
    pads, silk, contorno = [], [], []
    for s in pacote["shape"]:
        p = s.split("~")
        if p[0] == "PAD":
            forma, x, y, w, h, camada, numero, raio_furo, giro = p[1], *map(float, p[2:6]), p[6], p[8], float(p[9] or 0), float(p[11] or 0)
            if round(giro) % 180 == 90:
                w, h = h, w
            if p[13] and float(p[13]) > 0:
                raise SemLoja(f"{codigo}: furo oblongo (rasgo) ainda não sai no nosso Gerber")
            pads.append({"n": numero, "x": x, "y": y, "w": w, "h": h, "furo": 2 * raio_furo if camada == "11" else None,
                         "forma": {"ELLIPSE": "C", "RECT": "R", "OVAL": "O"}.get(forma, "R")})
        elif p[0] == "TRACK" and p[2] in (SILK, "99"):
            v = list(map(float, p[4].split()))
            (silk if p[2] == SILK else contorno).append(list(zip(v[::2], v[1::2])))
        elif p[0] == "CIRCLE" and p[5] in (SILK, "99"):
            cx, cy, r = map(float, p[1:4])
            (silk if p[5] == SILK else contorno).append(
                [(cx + r * math.cos(i * math.pi / 24), cy + r * math.sin(i * math.pi / 24)) for i in range(49)])
        elif p[0] == "ARC" and p[2] in (SILK, "99"):
            (silk if p[2] == SILK else contorno).extend(caminho(p[4]))
        elif p[0] == "SOLIDREGION" and p[1] in (SILK, "99"):
            (silk if p[1] == SILK else contorno).extend(caminho(p[3]))
    if not pads:
        raise SemLoja(f"o desenho de {codigo} veio sem pads")
    # centro = meio do contorno da peca (a serigrafia; sem ela, os pads); y do EasyEDA cresce pra baixo, o nosso pra cima
    if silk:
        xs, ys = [x for l in silk for x, _ in l], [y for l in silk for _, y in l]
    else:
        xs = [v for pd in pads for v in (pd["x"] - pd["w"] / 2, pd["x"] + pd["w"] / 2)]
        ys = [v for pd in pads for v in (pd["y"] - pd["h"] / 2, pd["y"] + pd["h"] / 2)]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

    def mm(x, y):
        return [round((x - cx) * UNIDADE, 3), round((cy - y) * UNIDADE, 3)]

    for pd in pads:
        pd["x"], pd["y"] = mm(pd["x"], pd["y"])
        pd["w"], pd["h"] = round(pd["w"] * UNIDADE, 3), round(pd["h"] * UNIDADE, 3)
        pd["furo"] = round(pd["furo"] * UNIDADE, 3) if pd["furo"] else None
    silk = [[mm(*pt) for pt in l] for l in silk]
    contorno = [[mm(*pt) for pt in l] for l in contorno]
    caixa = silk or contorno
    cxs, cys = [x for l in caixa for x, _ in l], [y for l in caixa for _, y in l]
    corpo = [round(max(cxs) - min(cxs), 2), round(max(cys) - min(cys), 2)] if caixa else None
    simbolo = {}   # numero do pino -> nome no simbolo (A/K no LED)
    for s in res["dataStr"]["shape"]:
        if s.startswith("P~"):
            partes = s.split("^^")
            numero = partes[0].split("~")[3]
            nome = partes[3].split("~")[4] if len(partes) > 3 else ""
            simbolo[numero] = nome
    return {"pacote": pacote["head"]["c_para"].get("package", ""), "pads": pads, "silk": silk, "corpo": corpo,
            "simbolo": simbolo}


# 3. importar: a peca escolhida vira um tipo da placa (placas/<nome>/pecas/<codigo>.json)
def importar(codigo, bloco, pasta):
    import blocos
    if not CODIGO.match(codigo):
        raise SemLoja(f"'{codigo}' não é um código da LCSC (ex: C119304)")
    if bloco not in blocos.BLOCOS:
        raise SemLoja(f"bloco '{bloco}' não existe (tem: {', '.join(blocos.BLOCOS)})")
    if blocos.BLOCOS[bloco].get("filtro", {}).get("tipo"):
        raise SemLoja(f"o bloco '{bloco}' não vem da LCSC: é uma placa pronta de loja brasileira com o tipo da biblioteca "
                      "(ex.: robocore:esp32-wifi-bluetooth), escolhida pelo catálogo")
    if not (Path(pasta) / "placa.txt").is_file():   # antes de ir na loja: nada de criar placa nem gravar no catálogo
        raise SemLoja(f"'{pasta}' não é uma placa (falta o placa.txt): importe pra uma placa que já existe")
    dados, des = ficha(codigo), desenho(codigo)
    try:
        pag = pagina(codigo)
    except SemLoja:
        pag = {"foto": None, "pdf": None}
    if pag["pdf"]:
        dados["datasheet"] = pag["pdf"]   # o link direto do pdf (o da busca as vezes e uma pagina)
    tipo = blocos.tipo_da_loja(bloco, dados, des)
    import catalogo
    cat = catalogo.ler()
    catalogo.adicionar(cat, blocos.CATEGORIA[bloco], [dados])   # toda peca escolhida fica na lista de compras (ldr -> sensor_luz)
    e = cat["pecas"][codigo]
    if not e.get("tamanho") and tipo["loja"]["tamanho"] not in ("", "-", e["pacote"].strip()):
        e["tamanho"] = tipo["loja"]["tamanho"]   # a medida do desenho, so quando a loja nao diz (a mesma regra do recalcular)
    catalogo.salvar(cat, [e["categoria"]])
    destino = Path(pasta) / "pecas"
    destino.mkdir(parents=True, exist_ok=True)
    arq = destino / f"{codigo}.json"
    try:
        jpg = pedir(pag["foto"], validade=None, binario=True) if pag["foto"] else None
    except SemLoja:
        jpg = None
    if jpg:
        (destino / f"{codigo}.jpg").write_bytes(jpg)
        tipo["loja"]["foto"] = f"{codigo}.jpg"
    arq.write_text(json.dumps(tipo, ensure_ascii=False, indent=1))
    return tipo


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    args = sys.argv[1:]
    try:
        if args[:1] == ["buscar"] and len(args) == 2:
            for i in buscar(args[1]):
                print(f"{i['codigo']:>10}  {i['modelo'][:28]:28}  {i['pacote'][:22]:22}  "
                      f"US$ {i['preco'] or 0:.4f}  estoque {i['estoque']:>7}  {i['categoria']}")
        elif args[:1] == ["importar"] and len(args) == 4:
            t = importar(args[1], args[2], args[3])
            print(f"ok: {t['nome']} -> {args[3]}/pecas/{args[1]}.json")
            for p in t["pendente"]:
                print(f"  pendente: {p}")
        else:
            sys.exit(__doc__)
    except SemLoja as e:
        sys.exit(f"loja: {e}")
