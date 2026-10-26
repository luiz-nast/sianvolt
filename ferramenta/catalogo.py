"""catalogo.py: a lista de compras de sempre (ferramenta/catalogo/, um arquivo por categoria).

Cada arquivo diz o que é a categoria (nome, grupo, uma frase pro Luiz), como achar as peças dela na loja (sementes),
o que serve (filtro), o que diferencia uma peça da outra (destaques) e como dar nome a cada uma; e guarda as peças.
Cada peça tem tudo que a loja diz, o dia em que viu (visto), a situação (ok, sem estoque, sumiu), outras lojas que
vendem a mesma coisa e, quando o Claude leu o datasheet, o que ele conferiu. O app procura aqui primeiro, na hora e
sem internet; a loja online é o double check (checar) e o jeito de achar peça nova (encher, buscar).

uso: python3 ferramenta/catalogo.py encher [categoria]      (busca as sementes na loja e põe as peças na lista)
     python3 ferramenta/catalogo.py checar [codigo ...]     (preço e estoque na loja agora; sem código, a lista toda)
     python3 ferramenta/catalogo.py ver [categoria]
     python3 ferramenta/catalogo.py limpar <categoria>     (tira da LCSC o que não passa mais no filtro; conferida fica)
     python3 ferramenta/catalogo.py recalcular [categoria]  (refaz montagem, nome e tamanho com as regras de agora)
     python3 ferramenta/catalogo.py categorias

Formato de uma categoria (ferramenta/catalogo/<id>.json):
  {"categoria": "capacitor", "nome": "Capacitor", "grupo": "Passivos",
   "explica": "uma frase de gente: pra que serve",
   "nome_peca": "Capacitor {Capacitance}, {Voltage Rated}",     # {Atributo da loja}, ou {type|Type} (o primeiro que tiver);
                                                                 # pode ser uma lista: vale o primeiro modelo que fechar;
                                                                 # {@categoria_loja}, {@modelo}, {@marca}: campos da peça;
                                                                 # nenhum fechou, vira "<nome> <modelo>"
   "traducoes": {"Timers / Clock Oscillators": "Timer"},        # valor da loja -> português, só nesta categoria
   "destaques": ["Capacitance", "Voltage Rated", "Tolerance"],   # o que aparece no cartão
   "chips": "Capacitance",                                       # atributo dos botões de filtro (opcional)
   "filtro": {"montagem": ["furo"],                              # furo | superfície | módulo (sem: qualquer)
              "categorias_loja": ["Capacitors"],                 # pedaço do nome da categoria na loja (sem: qualquer)
              "pacotes": ["4P"],                                 # pedaço do pacote (sem: qualquer)
              "pacotes_fora": ["SMD"],                           # pedaço do pacote que não serve
              "estoque_minimo": 50,                              # menos que isso não entra (sem: 1)
              "fora": ["C27983454"],                             # códigos barrados (dado da loja errado)
              "atributos": ["Capacitance"],                      # atributos que a peça tem que ter
              "valores": {"Illumination Color": ["Red", "Blue"]},   # atributo -> valores aceitos
              "valores_fora": {"Type": ["AMOLED"]}},                # atributo -> valores que não servem
   "sementes": [{"busca": "100nF 50V ceramic", "quantos": 4, "agrupar": "Capacitance"}],
   "pecas": {"C123": {...}}}

Uma peça pode ter "apelido": o nome que o Claude deu à mão quando a loja não diz o que ela é (o encher não mexe).
Montagem: furo, superfície, módulo (placa pronta), fio (vai no cabo, não na placa) ou "não informado".
"""
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

PASTA = Path(__file__).parent / "catalogo"
E24 = [10, 11, 12, 13, 15, 16, 18, 20, 22, 24, 27, 30, 33, 36, 39, 43, 47, 51, 56, 62, 68, 75, 82, 91]
CORES = {"Red": "vermelho", "Orange Red": "laranja-avermelhado", "Orange": "laranja", "Yellow": "amarelo",
         "Yellow Green": "verde-amarelado", "Green": "verde", "Emerald Green": "verde", "Blue": "azul", "White": "branco"}
CAMPOS_SPEC = ("categoria", "nome", "grupo", "explica", "nome_peca", "destaques", "chips", "traducoes", "filtro", "sementes")
GRUPOS = ["Passivos", "Semicondutores", "Energia", "Cérebros", "Comunicação", "Sensores", "Luz e som", "Telas",
          "Chaves e botões", "Conectores", "Movimento", "Módulos prontos"]   # a ordem da aba Peças
# valores da loja em inglês que aparecem em nome e filtro
TRADUCOES = {**CORES, "Through Hole": "de furo", "Right Angle": "a 90°", "Surface Mount, Right Angle": "de superfície a 90°",
             "Surface Mount,Vertical": "de superfície, reto", "Common Cathode": "catodo comum", "Common Anode": "anodo comum",
             "Step-down type": "abaixador", "Boost": "elevador", "Buck-Boost": "abaixa e eleva",
             "Step-down type、Boost": "abaixador e elevador", "Round Hole": "furo redondo", "Square Hole": "furo quadrado",
             "Phototransistor": "fototransistor", "Charging IC": "carregador", "Protection IC": "proteção",
             "Charging IC、Protection IC": "carregador e proteção", "Flat Vibration Motor": "de vibração chato (moeda)",
             "Cylindrical Vibration Motor": "de vibração cilíndrico", "Cylindrical DC Motor": "DC cilíndrico",
             "Piezoelectric": "piezoelétrico", "Electromagnetic": "eletromagnético", "Double pole single throw": "DPST",
             "Double pole triple throw": "DP3T", "Double pole four throw": "DP4T", "Water Clear": "lente transparente",
             "White Frosted Lens": "lente branca fosca", "Battery holder": "suporte", "Battery buckle": "suporte de mola",
             "Battery base": "base", "Battery clip": "clipe", "9V laminated battery": "bateria de 9 V",
             "Side insertion": "encaixe lateral", "N-Channel": "canal N", "P-Channel": "canal P"}

# pacote que comeca assim e de furo (a LCSC escreve de muitos jeitos; 插件 e 弯插 sao "plugin" e "plugin dobrado" em chines)
FURO = re.compile(r"^(Plugin|Through Hole|插件|弯插|Push-Pull|(C|P|SP|SK)?DIP|SIP|F?ZIP|Multiwatt|TOP-3|"
                  r"I?TO-(92|126|220|247|3P|3\b|5\b|05|18|202|39|46|4\b)|DO-(35|41|15|27|201|204)|A-405|R-6|"
                  r"HC-49(?!.*SMD)|DT-26|DT-38|KBP|KBL|KBJ|KBU|GBU|GBJ|GBP|WOM|WOB|DB(-|$)|CB-5|CB-2-3|PFF)", re.I)
FIO = ("Housing", "Crimp", "RF Cables", "Dupont wire", "Wire To Wire")   # categorias da loja de coisa que vai no cabo


def atributo(at, nome):
    """o valor do atributo; 'type|Type' = o primeiro que tiver (a loja escreve o mesmo atributo de jeitos diferentes)"""
    for n in nome.split("|"):
        v = at.get(n)
        if v and v != "-":
            return v
    return None


def ohms_busca(o):
    """como a loja escreve o valor: 240Ω, 1.1kΩ"""
    return f"{o:g}Ω" if o < 1000 else f"{o / 1000:g}kΩ"


def hoje():
    return datetime.now().strftime("%Y-%m-%d")


# ---------- ler e salvar ----------
def ler():
    """{"categorias": {id: spec}, "pecas": {codigo: peca (com "categoria")}}"""
    cat = {"categorias": {}, "pecas": {}}
    for arq in sorted(PASTA.glob("*.json")):
        d = json.loads(arq.read_text())
        cat["categorias"][d["categoria"]] = {k: d[k] for k in CAMPOS_SPEC if k in d}
        for codigo, e in d.get("pecas", {}).items():
            cat["pecas"][codigo] = {**e, "categoria": d["categoria"]}
    return cat


def spec(categoria):
    """só as regras de uma categoria (sem as peças), lendo só o arquivo dela"""
    d = json.loads((PASTA / f"{categoria}.json").read_text())
    return {k: d[k] for k in CAMPOS_SPEC if k in d}


def categoria_de(nome):
    """o bloco do projeto vira a categoria de onde sai a peça dele (ldr -> sensor_luz); categoria fica como está"""
    import blocos
    return blocos.CATEGORIA.get(nome, nome)


def numero(txt):
    """'4.7kΩ' -> 4700, '100nF' -> 1e-07, '3.3V' -> 3.3; pra ordenar"""
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*([pnuµmkM]?)", str(txt or ""))
    if not m:
        return None
    return float(m[1]) * {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6, "": 1}[m[2]]


def chave(spec, e):
    """ordem dentro da categoria: pelo atributo dos chips (valor), depois mais estoque"""
    v = atributo(e["atributos"], spec.get("chips") or "") or ""
    return (numero(v) is None, numero(v) or 0, str(v), -(e.get("estoque") or 0))


def salvar(cat, so=None):
    """grava cada categoria no seu arquivo (so=lista de categorias pra gravar so essas)"""
    PASTA.mkdir(exist_ok=True)
    for cid, spec in cat["categorias"].items():
        if so and cid not in so:
            continue
        pecas = sorted(((c, e) for c, e in cat["pecas"].items() if e["categoria"] == cid),
                       key=lambda ce: (chave(spec, ce[1]), ce[0]))
        dado = {**{k: spec[k] for k in CAMPOS_SPEC if k in spec},
                "pecas": {c: {k: v for k, v in e.items() if k != "categoria"} for c, e in pecas}}
        arq = PASTA / f"{cid}.json"
        tmp = arq.with_suffix(".tmp")
        tmp.write_text(json.dumps(dado, ensure_ascii=False, indent=1) + "\n")
        tmp.replace(arq)


# ---------- o que serve pra cada categoria ----------
def montagem(i):
    if i.get("montagem_manual"):   # a loja nao diz e o Claude viu na pagina (ex: XT60 de placa)
        return i["montagem_manual"]
    pacote, loja = i["pacote"].strip(), i["categoria"]
    jeito = (i["atributos"].get("Mounting Type") or i["atributos"].get("Mounting Style") or "").lower()
    if any(p in loja for p in FIO) or i["atributos"].get("Holder Type") == "Free Hanging":   # capinha, cabo, IDC de fio
        return "fio"
    if FURO.match(pacote) or "Through Hole" in loja or "through hole" in jeito or "plug" in jeito:
        return "furo"
    if re.search(r"\bModules?$|Development|Dev Board|Evaluation|Raspberry Pi", loja) and "Thyristor" not in loja:
        return "módulo"
    if jeito in ("lead", "lead wire", "wire lead", "solder lug terminal"):
        return "fio"
    if pacote in ("", "-"):
        return "não informado"
    return "superfície"


def serve(cat, categoria, i):
    """a peca da loja e do tipo certo, com estoque? (a busca da loja traz de tudo)"""
    f = cat["categorias"][categoria].get("filtro", {})
    if (i.get("estoque") or 0) < max(1, f.get("estoque_minimo", 1)) or i.get("codigo") in f.get("fora", []):
        return False
    if f.get("montagem") and montagem(i) not in f["montagem"]:
        return False
    if f.get("categorias_loja") and not any(c.lower() in i["categoria"].lower() for c in f["categorias_loja"]):
        return False
    if f.get("pacotes") and not any(p in i["pacote"] for p in f["pacotes"]):
        return False
    if any(p in i["pacote"] for p in f.get("pacotes_fora", [])):
        return False
    if any(i["atributos"].get(a) in vs for a, vs in f.get("valores_fora", {}).items()):
        return False
    if any(not atributo(i["atributos"], a) for a in f.get("atributos", [])):
        return False
    return all(i["atributos"].get(a) in vs for a, vs in f.get("valores", {}).items())


def nome_da_peca(cat, categoria, i):
    import blocos
    categoria = categoria_de(categoria)
    if blocos.CATEGORIA.get(categoria) == categoria:   # pilha, botao, resistor, led: o nome e feito a mao (blocos.py)
        return blocos.nome_da_loja(categoria, i)
    spec = cat["categorias"][categoria]
    traducoes = {**TRADUCOES, **spec.get("traducoes", {})}

    def valor(campo):   # {Atributo|Outro} ou {@campo_da_peca}
        if campo.startswith("@"):
            v = i.get({"categoria_loja": "categoria"}.get(campo[1:], campo[1:]))
            return v if v and v != "-" else None
        return atributo(i["atributos"], campo)

    modelos = spec.get("nome_peca") or []
    for modelo in [modelos] if isinstance(modelos, str) else modelos:
        campos = re.findall(r"\{([^}]+)\}", modelo)
        if campos and all(valor(c) for c in campos):
            return re.sub(r"\{([^}]+)\}", lambda m: traducoes.get(valor(m[1]), valor(m[1])), modelo)
    return f"{spec['nome']} {i['modelo']}".strip()


def medida(i):
    """o tamanho: do pacote ('Plugin,D2.3xL6.5mm'); se ele nao diz, dos atributos Length e Width; senao vazio"""
    import blocos
    m = blocos.tamanho(i["pacote"])
    if m and m != i["pacote"].strip():
        return m
    c, l = (numero(atributo(i["atributos"], a) or "") for a in ("Length|Length(mm)", "Width|Width(mm)"))
    return f"{c * 1000:g} × {l * 1000:g} mm".replace(".", ",") if c and l and c < 1 and l < 1 else ""


def entrada(cat, categoria, i):
    return {"nome": nome_da_peca(cat, categoria, i), "marca": i["marca"], "modelo": i["modelo"],
            "pacote": i["pacote"], "tamanho": medida(i), "montagem": montagem(i),
            "categoria_loja": i["categoria"], "descricao": i["descricao"], "atributos": i["atributos"],
            "datasheet": i["datasheet"], "loja": "LCSC", "link": i["link"], "preco": i["preco"], "moeda": "USD",
            "minimo": i["minimo"], "estoque": i["estoque"], "visto": hoje(), "situacao": "ok"}


def adicionar(cat, categoria, itens):
    """poe (ou atualiza) pecas da LCSC na lista; o conferido, outras lojas e a medida do desenho ficam. Devolve as novas.
    categoria pode ser o nome de um bloco do projeto (ldr vira sensor_luz). Quem ja estava numa categoria fica nela,
    com o nome pelas regras dela; e nome generico de bloco ("Olho de luz") nunca passa por cima de um nome bom"""
    import blocos
    categoria = categoria_de(categoria)
    if categoria not in cat["categorias"]:   # o salvar nao gravaria a peca, e ela sumiria calada
        raise ValueError(f"a categoria '{categoria}' não existe no catálogo")
    genericos = {b["nome"] for b in blocos.BLOCOS.values()}
    novas = 0
    for i in itens:
        velha = cat["pecas"].get(i["codigo"])
        onde = velha["categoria"] if velha else categoria
        nova = {**entrada(cat, onde, i), "categoria": onde}
        if velha:
            tamanho = velha.get("tamanho")
            nova = {**velha, **nova}
            nova["montagem"] = velha.get("montagem_manual") or nova["montagem"]
            if not nova["tamanho"] and tamanho and tamanho != nova["pacote"]:   # a medida tirada do desenho fica
                nova["tamanho"] = tamanho
            if nova["nome"] in genericos and velha.get("nome"):
                nova["nome"] = velha["nome"]
        else:
            novas += 1
        cat["pecas"][i["codigo"]] = nova
    return novas


def encher(cat, categoria=None, avisar=print):
    import loja
    total = 0
    for cid, spec in cat["categorias"].items():
        if categoria and cid != categoria:
            continue
        for s in spec.get("sementes", []):
            itens = [i for i in loja.buscar(s["busca"], 100 if s.get("agrupar") else 30) if serve(cat, cid, i)]
            itens.sort(key=lambda i: -i["estoque"])
            grupos = {}   # agrupar: as de mais estoque de cada valor do atributo (ex: de cada cor)
            for i in itens:
                grupos.setdefault(i["atributos"].get(s["agrupar"]) if s.get("agrupar") else "", []).append(i)
            escolhidas = [i for g in grupos.values() for i in g[:s.get("quantos", 4)]]
            n = adicionar(cat, cid, escolhidas)
            total += n
            avisar(f"{cid}: '{s['busca']}' -> {len(escolhidas)} peças ({n} novas)")
            time.sleep(0.3)   # devagar com a loja
    return total


def checar_outra_loja(e, avisar=print):
    """preco e estoque de uma peca de loja brasileira (e das outras lojas dela), pela pagina do produto"""
    import lojas
    mudou = False
    for oferta in ([e] if e.get("link") else []) + e.get("outras_lojas", []):
        if not lojas.nome_da_loja(oferta.get("link", "")):
            continue
        try:
            d = lojas.ler(oferta["link"])
        except lojas.SemPagina as erro:
            avisar(f"{oferta['link']}: {erro}")
            continue
        antes = (oferta.get("preco"), oferta.get("estoque"), oferta.get("situacao"))
        oferta.update(visto=hoje(), estoque=d["estoque"])
        if d["preco"] is not None:
            oferta["preco"] = d["preco"]
        if oferta is e:
            e["situacao"] = "sem estoque" if d["disponivel"] is False else "ok"
        mudou |= (oferta.get("preco"), oferta.get("estoque"), oferta.get("situacao")) != antes
        avisar(f"{oferta['link']}: R$ {oferta.get('preco')}, {'tem' if d['disponivel'] else 'sem estoque' if d['disponivel'] is False else '?'}")
    return mudou


def checar(cat, codigos=None, avisar=print):
    """preco e estoque agora, direto da loja (sem cache); marca 'sem estoque' e 'sumiu'.
    LCSC pela busca da JLCPCB; lojas brasileiras pela pagina do produto, com a pausa que o robots.txt delas pede"""
    import loja
    mudou = []
    for codigo in codigos or list(cat["pecas"]):
        e = cat["pecas"].get(codigo)
        if not e:
            continue
        if e.get("loja", "LCSC") != "LCSC":
            if checar_outra_loja(e, avisar):
                mudou.append(codigo)
            continue
        if e.get("outras_lojas") and checar_outra_loja({"outras_lojas": e["outras_lojas"]}, avisar):   # a placa da LCSC tambem a venda no Brasil
            mudou.append(codigo)
        try:
            i = loja.ficha(codigo, validade=0)
        except loja.SemLoja as erro:
            if "não está na loja" in str(erro):
                e.update(situacao="sumiu", visto=hoje())
                mudou.append(codigo)
                avisar(f"{codigo}: sumiu da loja")
            else:
                avisar(f"{codigo}: {erro}")
            continue
        antes = (e["estoque"], e["preco"], e["situacao"])
        e.update(estoque=i["estoque"], preco=i["preco"], minimo=i["minimo"], visto=hoje(),
                 situacao="ok" if i["estoque"] > 0 else "sem estoque")
        if (e["estoque"], e["preco"], e["situacao"]) != antes:
            mudou.append(codigo)
        avisar(f"{codigo}: {e['situacao']}, {e['estoque']} em estoque, US$ {e['preco']}")
        time.sleep(0.2)
    return mudou


def recalcular(cat, categoria=None):
    """refaz montagem, nome, tamanho e link das pecas da LCSC com as regras de agora (sem ir na loja).
    O apelido (nome dado a mao) e a montagem_manual ficam."""
    import loja
    mudou = 0
    for codigo, e in cat["pecas"].items():
        if (categoria and e["categoria"] != categoria) or e.get("loja", "LCSC") != "LCSC":
            continue
        como_loja = {**e, "codigo": codigo, "categoria": e.get("categoria_loja", "")}
        antes = (e.get("montagem"), e["nome"], e.get("tamanho"), e.get("link"))
        e["nome"], e["montagem"] = nome_da_peca(cat, e["categoria"], como_loja), montagem(como_loja)
        tamanho = medida(como_loja)
        if tamanho or e.get("tamanho") in (None, "", "-", e["pacote"].strip()):   # sem medida nova, fica a do desenho
            e["tamanho"] = tamanho
        if " " in (e.get("link") or ""):   # a JLCPCB as vezes manda o link com espaco, e ele nao abre
            e["link"] = loja.FICHA.format(codigo)
        mudou += (e.get("montagem"), e["nome"], e.get("tamanho"), e.get("link")) != antes
    return mudou


def limpar(cat, categoria):
    """tira da categoria as pecas da LCSC que nao passam mais no filtro dela (depois de apertar o filtro); conferida fica"""
    fora = []
    for codigo, e in list(cat["pecas"].items()):
        if e["categoria"] != categoria or e.get("loja", "LCSC") != "LCSC" or e.get("conferido"):
            continue
        como_loja = {**e, "codigo": codigo, "categoria": e.get("categoria_loja", ""),
                     "estoque": max(e.get("estoque") or 0, cat["categorias"][categoria].get("filtro", {}).get("estoque_minimo", 1))}   # sem estoque fica, marcada
        if not serve(cat, categoria, como_loja):
            fora.append(codigo)
            del cat["pecas"][codigo]
    return fora


def do_bloco(cat, categoria):
    """as pecas de uma categoria (ou da categoria de um bloco: ldr -> sensor_luz)"""
    categoria = categoria_de(categoria)
    return [{"codigo": c, **e} for c, e in cat["pecas"].items() if e["categoria"] == categoria]


def conferido(codigo):
    return (ler()["pecas"].get(codigo) or {}).get("conferido")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    args = sys.argv[1:]
    cat = ler()
    if args[:1] == ["encher"]:
        alvo = args[1] if len(args) > 1 else None
        if alvo and alvo not in cat["categorias"]:
            sys.exit(f"categoria '{alvo}' não existe (tem: {', '.join(cat['categorias'])})")
        print(f"{encher(cat, alvo)} peças novas")
        salvar(cat, [alvo] if alvo else None)
    elif args[:1] == ["checar"]:
        codigos = args[1:] or list(cat["pecas"])
        print(f"{len(checar(cat, codigos))} mudaram")
        salvar(cat, sorted({cat["pecas"][c]["categoria"] for c in codigos if c in cat["pecas"]}))   # so as categorias tocadas
    elif args[:1] == ["ver"]:
        for c, e in cat["pecas"].items():
            if len(args) < 2 or e["categoria"] == args[1]:
                print(f"{c:>12}  {e['categoria']:12}  {(e.get('apelido') or e['nome'])[:38]:38}  {e['modelo'][:24]:24}  {e.get('montagem', ''):10}  "
                      f"{e['situacao']:11}  {e.get('estoque') or '':>7}  {'conferido' if e.get('conferido') else ''}")
    elif args[:1] == ["recalcular"]:
        print(f"{recalcular(cat, args[1] if len(args) > 1 else None)} peças mudaram")
        salvar(cat, [args[1]] if len(args) > 1 else None)
    elif args[:1] == ["limpar"] and len(args) == 2 and args[1] in cat["categorias"]:
        fora = limpar(cat, args[1])
        print(f"{len(fora)} peças saíram: {' '.join(fora)}")
        salvar(cat, [args[1]])
    elif args[:1] == ["categorias"]:
        for cid, spec in cat["categorias"].items():
            n = sum(1 for e in cat["pecas"].values() if e["categoria"] == cid)
            print(f"{cid:16} {spec['grupo']:22} {spec['nome']:28} {n:>4} peças")
    else:
        sys.exit(__doc__)
