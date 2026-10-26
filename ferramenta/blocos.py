"""blocos.py: o começo de toda placa, na ordem em que a gente pensa.

1. objetivo: o que a placa faz e as perguntas de gente ("quanta luz você quer?")
2. blocos: o tipo de cada peça, sem número ainda (pilha -> botão -> resistor -> LED)
3. carrinho: pra cada bloco, uma peça de verdade da loja (loja.py); o resistor sai da conta do brilho
4. só então a placa: o placa.txt usa o código da peça da loja como tipo (peca R1 C119304 43 15); a peça de loja
   brasileira (robocore:...) entra com o tipo da biblioteca que o catálogo diz (peca U1 devkit_esp32_30 40 25)

Fica tudo em placas/<nome>/projeto.json; as peças importadas, em placas/<nome>/pecas/.

Projeto com ESP32: o bloco "cerebro" (o DevKit) fica no meio e cada bloco diz em que pino liga. Campos opcionais
de cada bloco no projeto.json (a lanterninha não usa nenhum):
  pino      o GPIO do cérebro em que o bloco liga ("GPIO32")
  nome      nome de gente ("LED do meio"); no estado ele vira "apelido" (o "nome" lá é o do tipo de bloco)
  led       no resistor: o LED que ele freia ("D1")
  para      no resistor: o bloco que ele atende (o botão "SW1", o som "BZ1" ou o olho de luz "LDR1");
            no capacitor: o olho de luz em que ele fica colado ("LDR1": aí ele é de 100 nF)
  duty_max  no LED: a maior parte do tempo que o programa deixa ele aceso (PWM, de 0 a 1)
  origem    de onde veio o número do bloco ("main.py: BRILHO_MAX²", a decisão que escolheu o resistor)
As respostas guardam quem decidiu; o brilho tem a geral e o ajuste de cada LED, a cor é sempre de um LED:
  "perguntas": {"brilho": {"resposta": "media", "quem": "Luiz", "quando": "...", "por_led": {"D3": {"resposta": "fraca", ...}}},
                "cor": {"por_led": {"D1": {"resposta": "vermelho", "quem": "sugestão do Claude", "quando": "..."}}}}
"""
import json
import math
import re
from datetime import datetime
from pathlib import Path

import catalogo
import circuito
from biblioteca import BIBLIOTECA

# cada bloco: o que ele faz, em uma frase, e como procurar a peca dele na loja (sempre de furo: a gente solda).
# a busca da JLCPCB e por palavra exata: "CR2032 Plugin" acha, "CR2032 battery holder through hole" nao
BLOCOS = {
    "pilha": {"nome": "Pilha", "funcao": "Energia", "ref": "BT",
              "por_que": "É de onde vem a força que empurra a corrente pelo circuito.",
              "explica": "Segura a pilha. O + e o − dela viram dois furos na placa; o − é o GND, o 0 V de referência.",
              "busca": "CR2032 Plugin"},
    "botao": {"nome": "Botão", "funcao": "Liga e desliga", "ref": "SW",
              "por_que": "Apertou, a corrente passa; soltou, ela para e a pilha não gasta.",
              "explica": "Apertou, liga; soltou, desliga. Tem o lado A (dois pinos, ligados por dentro) e o lado B (os outros dois). "
                         "Só faz alguma coisa se cada lado for pra um lugar diferente.",
              "busca": "6x6mm tactile"},
    "resistor": {"nome": "Resistor", "funcao": "Freio", "ref": "R",
                 "por_que": "Segura a corrente no tanto certo: é ele que decide o brilho e protege o LED.",
                 "explica": "Freia a corrente: quanto mais ohms, menos corrente passa. É o cilindrinho com faixas coloridas. "
                            "Não tem lado certo.",
                 "busca": "{valor} 250mW metal film through hole resistor"},
    "led": {"nome": "LED", "funcao": "Luz", "ref": "D",
            "por_que": "Transforma corrente em luz: mais corrente, mais brilho, até o limite dele.",
            "explica": "Só acende com a corrente no sentido certo: entra pelo + (a perna comprida) e sai pelo − "
                       "(a perna curta; na placa é o pad quadrado). Sempre com um resistor na frente.",
            "busca": "LED 5mm red", "atributo": ("Illumination Color", "Red")},
    # os blocos do projeto com ESP32. filtro = a parte da categoria do catálogo que serve pro bloco
    "cerebro": {"nome": "Cérebro", "funcao": "Pensa", "ref": "U",
                "por_que": "Roda o programa: lê os botões e a luz e decide quando cada LED acende e quando o som toca.",
                "explica": "Uma plaquinha pronta com o ESP32 (o DevKit). Ela não é soldada: encaixa em duas barras fêmea que "
                           "você solda na placa. Cada pino tem um nome (GPIO32...) e é por ele que o programa liga e desliga "
                           "as coisas; o 3V3 e o GND dão a energia pro resto.",
                "busca": None, "filtro": {"tipo": True}},   # só peça de loja com o tipo da biblioteca (o desenho vem de lá)
    "ldr": {"nome": "Olho de luz", "funcao": "Sente a luz", "ref": "LDR",
            "por_que": "Diz pro cérebro se o quarto está claro ou escuro.",
            "explica": "Um resistor que muda com a luz: no claro fica com poucos ohms, no escuro com muitos. Junto com um "
                       "resistor fixo, vira uma tensão que o pino do cérebro lê. Não tem lado certo.",
            "busca": "GL5528", "filtro": {"categoria_loja": ["Photoresistors"]}},
    "buzzer": {"nome": "Som", "funcao": "Apita", "ref": "BZ",
               "por_que": "Faz o apito: o cérebro liga e desliga o pino bem rápido, e isso vira som.",
               "explica": "Um piezo: uma plaquinha que entorta com a tensão. Ligando e desligando milhares de vezes por "
                          "segundo, ela apita nessa nota. Sozinho não apita (é passivo) e vai com um resistor na frente.",
               "busca": "piezoelectric", "filtro": {"atributos": {"Technology": ["Piezoelectric"]}}},
    "capacitor": {"nome": "Capacitor", "funcao": "Acalma a tensão", "ref": "C",
                  "por_que": "Guarda um pouquinho de carga e segura a tensão parada: no olho de luz, deixa a leitura do "
                             "cérebro mais firme.",
                  "explica": "O cerâmico de furo: uma gotinha com duas pernas. Em corrente contínua não passa nada; ele só "
                             "segura as mudanças rápidas da tensão. Não tem lado certo.",
                  "busca": "MLCC Leaded"},
}

# de que categoria do catálogo sai a peça de cada bloco (o bloco do ESP32 não se chama "esp32" porque essa é a
# categoria dos módulos soltos)
CATEGORIA = {"pilha": "pilha", "botao": "botao", "resistor": "resistor", "led": "led",
             "cerebro": "placa_desenvolvimento", "ldr": "sensor_luz", "buzzer": "buzzer_passivo",
             "capacitor": "capacitor_ceramico"}

# fracao = parte do brilho que o fabricante anuncia (o brilho medido na corrente de teste do datasheet)
# por_led: a resposta é de cada LED; so_com: a pergunta só aparece no projeto que tem esse bloco
PERGUNTAS = {
    "brilho": {"texto": "Quanta luz você quer?", "precisa": "led",
               "opcoes": {"fraca": {"nome": "Fraca", "fracao": 0.25, "explica": "Um quarto do brilho que o fabricante anuncia. A pilha dura mais."},
                          "media": {"nome": "Média", "fracao": 0.5, "explica": "Metade do brilho do anúncio."},
                          "forte": {"nome": "Forte", "fracao": 1.0, "explica": "O brilho do anúncio. Gasta a pilha bem mais rápido."}}},
    "cor": {"texto": "De que cor é cada LED?", "precisa": "led", "so_com": "cerebro", "por_led": True,
            "opcoes": None},   # as cores dos LEDs do catálogo (cores_do_catalogo)
}
# com o cérebro não tem pilha: o "explica" do brilho fala do pino
BRILHO_NO_PINO = {"fraca": "Um quarto do brilho que o fabricante anuncia. O pino do cérebro trabalha folgado.",
                  "media": "Metade do brilho do anúncio.",
                  "forte": "O brilho do anúncio. No pino do cérebro, pode passar da força padrão dele ou nem ser possível: "
                           "a conta de cada LED mostra."}

# o resistor do botão (decisão "Botões" do plano): fica bem dentro da faixa que a conta_do_botao mostra
# e é o mesmo 1 kΩ do piezo, uma peça a menos pra comprar
R_BOTAO = 1000
# o resistor fixo do olho de luz (decisão "Divisor da luz noturna"): com 10 kΩ o LDR do meio em 1 lux passava dos
# 2,45 V da faixa boa do ADC; com 22 kΩ ele fica dentro de 1 a 100 lux
R_DIVISOR = 22000
# o capacitor colado no pino do olho de luz (decisão "Divisor da luz noturna"): o ESP32 Series Datasheet v5.3,
# Tabela 4-3 (ADC Characteristics), mede a precisão do ADC com "an external 100 nF capacitor" no pino
C_DO_LDR = 100e-9
LUX_DA_TABELA = (0, 1, 10, 100)   # a tabelinha do olho de luz; 0 = escuro (o r_escuro do datasheet)
CANTOS = ("min", "meio", "max")   # os cantos do LDR (circuito.ohms_do_ldr)

E24 = [10, 11, 12, 13, 15, 16, 18, 20, 22, 24, 27, 30, 33, 36, 39, 43, 47, 51, 56, 62, 68, 75, 82, 91]


# ---------- números que a loja escreve como texto ----------
def numero_com_unidade(txt, unidade):
    """'4.7kΩ' -> 4700; '250mW' -> 0.25; '20mA' -> 0.02"""
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*([pnuµmkM]?)" + unidade, txt or "")
    if not m:
        return None
    return float(m[1]) * {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6, "": 1}[m[2]]


def ohms_txt(o):
    if o is None:
        return "?"
    if o == 0:
        return "0 Ω (jumper)"
    if o >= 1e6:
        return f"{o / 1e6:g} MΩ".replace(".", ",")
    if o >= 1000:
        return f"{o / 1000:g} kΩ".replace(".", ",")
    return f"{o:g} Ω".replace(".", ",")


def farads_txt(f):
    """1e-07 -> '100 nF'"""
    for fator, unidade in ((1e-6, "µF"), (1e-9, "nF"), (1e-12, "pF")):
        if f >= fator * 0.999:
            return f"{f / fator:.3g} {unidade}".replace(".", ",")
    return f"{f:g} F"


def watts_txt(w):
    return f"{w:g} W".replace(".", ",") if w >= 1 else f"{w * 1000:g} mW"


def mA_txt(i):
    """0.02258 -> '22,6' (miliampères, uma casa)"""
    return f"{i * 1000:.1f}".replace(".", ",")


def volts_txt(v):
    return f"{v:g}".replace(".", ",")


def valores_e24():
    """os resistores de loja da série E24, de 10 Ω a 9,1 MΩ, do menor pro maior"""
    return [v * 10 ** d for d in range(0, 6) for v in E24]


def mais_perto(ohms):
    """o valor comercial (série E24) mais perto, olhando a proporção"""
    return min(valores_e24(), key=lambda v: abs(math.log(v / ohms)))


def tamanho(pacote):
    """'Plugin,D2.3xL6.5mm' -> 'corpo de 6,5 × 2,3 mm'; a loja nao diz ('-') -> ''"""
    if pacote.strip() in ("", "-"):
        return ""
    num = lambda s: s.replace(".", ",")
    if m := re.search(r"D(\d+(?:\.\d+)?)xL(\d+(?:\.\d+)?)mm", pacote):
        return f"corpo de {num(m[2])} × {num(m[1])} mm"
    if m := re.search(r"D=(\d+(?:\.\d+)?)mm", pacote):
        return f"{num(m[1])} mm de diâmetro"
    if m := re.search(r"(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)mm", pacote):
        return f"{num(m[1])} × {num(m[2])} mm"
    return pacote


def de_furo(i):
    """peca de furo passante (a gente solda na mao); SMD fica de fora por enquanto"""
    return catalogo.montagem(i) == "furo"


# ---------- a peca da loja vira um tipo da placa ----------
def nome_da_loja(bloco, d):
    """nome de gente de uma peca da loja, so com o que a loja diz"""
    at = d["atributos"]
    if bloco == "resistor":
        ohms, w = numero_com_unidade(at.get("Resistance"), "Ω"), numero_com_unidade(at.get("Power(Watts)"), "W")
        return f"Resistor {ohms_txt(ohms)}, {watts_txt(w)}" if ohms is not None and w else "Resistor"
    if bloco == "led":
        cor = catalogo.CORES.get(at.get("Illumination Color"), "")
        return f"LED {cor} {tamanho(d['pacote'])}".replace("  ", " ").replace(" de diâmetro", "").strip()
    if bloco == "botao":
        altura = re.sub(r"(\d)\s*mm", r"\1 mm", at["Switch Height"]) if at.get("Switch Height") not in (None, "-") else None
        return f"Botão {tamanho(d['pacote']) or catalogo.medida(d)}{f', {altura} de altura' if altura else ''}".replace(".", ",").strip()
    if bloco == "pilha":
        tipo = at.get("Battery Type") or at.get("Applicable battery specifications") or ""
        tipo = {"No. 5": "AA", "No. 7": "AAA"}.get(tipo, tipo)   # a loja escreve o nome chines da AA e da AAA
        return f"Suporte de pilha {tipo}".strip()
    if CATEGORIA.get(bloco, bloco) != bloco:   # ldr, buzzer, cerebro: o nome sai das regras da categoria do catalogo
        cid = CATEGORIA[bloco]                  # ("LDR (fotorresistor) 8kΩ~20kΩ"), nunca o nome generico do bloco
        return catalogo.nome_da_peca({"categorias": {cid: catalogo.spec(cid)}}, cid, d)
    return BLOCOS[bloco]["nome"]


def pad(p):
    if p["forma"] == "C" and abs(p["w"] - p["h"]) < 1e-6:
        return {"forma": "C", "d": p["w"]}
    return {"forma": "O" if p["forma"] in ("C", "O") else "R", "w": p["w"], "h": p["h"]}


def tipo_da_loja(bloco, d, des):
    """d = ficha da loja (loja.item), des = desenho do EasyEDA (loja.desenho)"""
    b, at, codigo = BLOCOS[bloco], d["atributos"], d["codigo"]
    medida = tamanho(d["pacote"])
    if medida == d["pacote"] and des["corpo"]:   # o pacote nao diz a medida: usa o contorno do desenho
        medida = f"{des['corpo'][0]:.1f} × {des['corpo'][1]:.1f} mm".replace(".", ",")
    no_catalogo = catalogo.ler()["pecas"].get(codigo) or {}
    tipo = {   # o apelido do catálogo é o nome que o Claude deu quando a loja não diz direito o que a peça é
        "nome": no_catalogo.get("apelido") or nome_da_loja(bloco, d), "bloco": bloco, "explica": b["explica"],
        "fonte": f"desenho {des['pacote']} do EasyEDA; ficha LCSC {codigo}; datasheet {d['datasheet']}",
        "corpo": des["corpo"] or [2 * max(abs(p["x"]) + p["w"] / 2 for p in des["pads"]),
                                  2 * max(abs(p["y"]) + p["h"] / 2 for p in des["pads"])],
        "redondo": bloco == "led", "desenho": des["silk"],
        "pinos": {p["n"]: {"x": p["x"], "y": p["y"], "pad": pad(p), "furo": p["furo"]} for p in des["pads"]},
        "eletrica": None, "pendente": [],
        "compra": f"{d['marca']} {d['modelo']} (LCSC {codigo})",
        "loja": {k: d[k] for k in ("codigo", "modelo", "marca", "pacote", "preco", "minimo", "estoque", "datasheet", "link", "atributos")}
                | {"tamanho": medida, "quando": datetime.now().strftime("%Y-%m-%d")},
    }
    if bloco == "resistor":
        ohms, w = numero_com_unidade(at.get("Resistance"), "Ω"), numero_com_unidade(at.get("Power(Watts)"), "W")
        tipo["nomes"] = {"1": "lado 1", "2": "lado 2"}
        tipo["valor"] = ohms
        if ohms and w:
            tipo["eletrica"] = {"modelo": "resistor", "potencia_max": w}
        else:
            tipo["pendente"].append("o valor e a potência do resistor")
    elif bloco == "led":
        tipo["nomes"] = {n: {"A": "+", "K": "−"}.get(nome, nome) for n, nome in des["simbolo"].items()}
        tipo["pendente"].append("o + e o −, a corrente máxima e a curva de brilho do LED")
        menos = [n for n, nome in tipo["nomes"].items() if nome == "−"]
        if len(menos) == 1 and tipo["pinos"][menos[0]]["pad"]["forma"] != "R":   # o app ensina: o − é o pad quadrado
            velho = tipo["pinos"][menos[0]]["pad"]
            lado = velho.get("d") or max(velho["w"], velho["h"])
            tipo["pinos"][menos[0]]["pad"] = {"forma": "R", "w": lado, "h": lado}
            tipo["fonte"] += ("; o − virou pad quadrado do mesmo tamanho (o EasyEDA traz os dois redondos), pra valer a "
                              "regra que o app ensina: o − é o pad quadrado")
    elif bloco == "botao":
        tipo["pendente"].append("quais pinos do botão são o mesmo lado")
    elif bloco == "pilha":
        tipo["pendente"].append("qual furo é o + e qual pilha vai nele")
    elif bloco == "ldr":
        tipo["nomes"] = {"1": "lado 1", "2": "lado 2"}   # é um resistor: não tem lado certo
        tipo["pendente"].append("a resistência do LDR com 10 lux, no escuro e o gama (a curva da luz)")
    elif bloco == "buzzer":
        tipo["pendente"].append("se o piezo tem lado certo, a capacitância e o resistor que vai em série")
    elif bloco == "capacitor":   # cerâmico: não tem lado certo e a loja diz o valor (em corrente contínua ele é aberto)
        farads, volts = numero_com_unidade(at.get("Capacitance"), "F"), numero_com_unidade(at.get("Voltage Rating"), "V")
        tipo["nomes"] = {"1": "lado 1", "2": "lado 2"}
        if farads and volts:
            tipo["eletrica"] = {"modelo": "capacitor", "c": farads, "v_max": volts}
        else:
            tipo["pendente"].append("a capacitância e a tensão do capacitor")
    conferido = no_catalogo.get("conferido")
    if conferido:   # o que o Claude ja conferiu no datasheet
        for chave in ("nomes", "juntos", "eletrica", "pinos_fixos", "extras"):
            if chave in conferido:
                tipo[chave] = conferido[chave]
        tipo["fonte"] += f"; conferido: {conferido['fonte']}"
        tipo["pendente"] = [p for p in tipo["pendente"] if bloco in ("resistor", "capacitor")]   # o que a loja não disse
    return tipo


def carregar_pecas(pasta):
    """codigo -> tipo, das pecas que vieram da loja pra esta placa"""
    pecas = {}
    for arq in sorted((Path(pasta) / "pecas").glob("C*.json")):
        pecas[arq.stem] = json.loads(arq.read_text())
    return pecas


# ---------- brilho, corrente e o resistor ----------
def corrente_do_brilho(e, fracao):
    """corrente que da essa parte do brilho do anuncio, pela curva do datasheet (None sem curva)"""
    pts = e.get("brilho") or []
    for (i0, b0), (i1, b1) in zip(pts, pts[1:]):
        if b0 <= fracao <= b1:
            return i0 + (i1 - i0) * (fracao - b0) / (b1 - b0)
    return None


def brilho_da_corrente(e, i):
    """parte do brilho do anuncio que essa corrente da (1,0 = o anuncio)"""
    pts = e.get("brilho") or []
    if not pts:
        return None
    if i <= pts[0][0]:
        return 0.0
    for (i0, b0), (i1, b1) in zip(pts, pts[1:]):
        if i0 <= i <= i1:
            return b0 + (b1 - b0) * (i - i0) / (i1 - i0)
    return pts[-1][1]   # acima da curva: nao inventa, fica no ultimo ponto medido


def nivel_do_brilho(fracao):
    """fracao -> 'fraca' | 'media' | 'forte' (o mais perto)"""
    ops = PERGUNTAS["brilho"]["opcoes"]
    return min(ops, key=lambda k: abs(ops[k]["fracao"] - fracao))


def conta_do_freio(pilha, led, fracao):
    """pilha -> botao -> resistor -> LED, tudo em serie: que resistor da esse brilho?
    I = (pilha − joelho do LED) / (R + r_s do LED + resistencia interna da pilha)"""
    i = corrente_do_brilho(led, fracao)
    if i is None:
        return None
    joelho = led["vf"] - led["r_s"] * led["i_teste"]
    resto = led["r_s"] + pilha.get("r_interna", 0)
    ohms = (pilha["v"] - joelho) / i - resto
    if ohms <= 0:
        return {"i": i, "impossivel": True, "joelho": joelho}
    padrao = mais_perto(ohms)
    i_padrao = (pilha["v"] - joelho) / (padrao + resto)
    return {"i": i, "ohms": ohms, "padrao": padrao, "i_padrao": i_padrao, "joelho": joelho,
            "brilho": brilho_da_corrente(led, i_padrao), "r_interna": pilha.get("r_interna", 0), "r_s": led["r_s"],
            "v": pilha["v"]}


# ---------- as contas com o ESP32: o pino no lugar da pilha ----------
def fontes_de(mcu, *campos):
    """as fontes (datasheet e página) dos números do cérebro que a conta usou"""
    fontes = mcu.get("fontes") or {}
    return {c: fontes[c] for c in campos if c in fontes}


# o nome de gente de cada número que as contas usam, pras frases de falta e de pendente (os do LDR e do 3V3 vêm do circuito.py)
NOME_DO_NUMERO = {**circuito.NOME_DO_CAMPO, "vdd_max": "a tensão máxima do 3V3", "vdd_min": "a tensão mínima do 3V3",
                  "i_pino": "a força padrão do pino",
                  "vil": "a tensão em que o pino passa a ler 0 (VIL)", "adc_min": "o começo da faixa boa do ADC",
                  "adc_max": "o fim da faixa boa do ADC", "vf": "a tensão do LED aceso", "r_s": "a resistência de dentro do LED",
                  "i_teste": "a corrente de teste do LED", "vf_max": "a tensão mais alta do LED aceso",
                  "vf_min": "a tensão mais baixa do LED aceso", "gama_tol": "quanto o gama pode variar",
                  "r_serie": "o resistor em série que o fabricante pede", "v": "a tensão"}
# os números de cada peça sem os quais a conta do resistor não sai (o LDR: os que o circuito.ohms_do_ldr pede)
NUMEROS_DA_PECA = {"led": ("vf", "r_s", "i_teste"), "ldr": ("r_escuro", "gama", "r10_min", "r10_max"), "pilha": ("v",)}


def e_numero(x, zero=False):
    """número de verdade (não texto 'pendente' nem True/False) e maior que 0 (ou 0, com zero=True)"""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and (x >= 0 if zero else x > 0)


def falta_no_cerebro(mcu, *campos):
    """os números do cérebro que a conta precisa e que estão pendentes: sem número não tem conta (nada de chute)"""
    return [f"{NOME_DO_NUMERO.get(c, c)} do cérebro está pendente: sem esse número não dá pra fazer a conta"
            for c in campos if not e_numero(mcu.get(c))]


def falta_na_peca(e, ref, bloco):
    """o mesmo pros números da peça (LED, LDR, piezo): o que falta conferir no datasheet antes da conta"""
    falta = [c for c in NUMEROS_DA_PECA.get(bloco, ()) if not e_numero(e.get(c), zero=c == "r_s")]
    if bloco == "ldr" and e.get("gama_tol") is not None and not e_numero(e["gama_tol"], zero=True):
        falta.append("gama_tol")
    r_serie = e.get("r_serie")
    if bloco == "buzzer" and not (isinstance(r_serie, (list, tuple)) and len(r_serie) == 2
                                  and all(e_numero(x) for x in r_serie) and r_serie[0] <= r_serie[1]):
        falta.append("r_serie")
    return [f"falta conferir {NOME_DO_NUMERO[c]} do {ref} no datasheet" for c in falta]


def v_do_pior(mcu):
    """o 3V3 do pior caso: o máximo da faixa; sem ele, o do meio, e a conta diz isso. (volts, pendentes)"""
    if e_numero(mcu.get("vdd_max")):
        return mcu["vdd_max"], []
    return mcu["vdd"], ["a tensão máxima do 3V3 do cérebro está pendente: o pior caso usa o 3V3 do meio"]


def conta_do_led(mcu, led, fracao):
    """o pino do cérebro é a pilha: 3V3 com o r_pino por dentro. A conta do freio escolhe o resistor com o vf típico;
    a faixa diz a corrente de verdade, que vai do LED com o vf mais alto (vf_max, a menor) ao mais baixo (vf_min, a maior).
    O pior caso (3V3 no máximo e vf_min) é o que conta pra força padrão do pino"""
    c = conta_do_freio({"v": mcu["vdd"], "r_interna": mcu["r_pino"]}, led, fracao)
    if c is None:
        return None
    c.update(fonte="pino", r_pino=mcu["r_pino"], i_pino=mcu["i_pino"], condicao_3v3=mcu.get("condicao_3v3"),
             fontes=fontes_de(mcu, "vdd", "vdd_max", "r_pino", "i_pino"))
    if c.get("impossivel"):
        return c
    resto = c["padrao"] + led["r_s"] + mcu["r_pino"]

    def corrente(vf, v):   # o joelho anda junto com o vf; o r_s do LED fica
        return max(0.0, (v - (vf - led["r_s"] * led["i_teste"])) / resto) if vf is not None else None

    vf_max, vf_min = (led.get(k) if e_numero(led.get(k)) else None for k in ("vf_max", "vf_min"))   # 'pendente' = sem número
    de, ate = corrente(vf_max, mcu["vdd"]), corrente(vf_min, mcu["vdd"])
    c["faixa"] = {"de": de, "ate": ate, "brilho_de": brilho_da_corrente(led, de) if de is not None else None,
                  "brilho_ate": brilho_da_corrente(led, ate) if ate is not None else None}
    v_pior, pendentes = v_do_pior(mcu)
    pendentes = [f"{NOME_DO_NUMERO[campo]} está pendente: a faixa de corrente fica sem essa ponta"
                 for campo, vf in (("vf_max", vf_max), ("vf_min", vf_min)) if vf is None] + pendentes
    c["pior"] = {"i": corrente(vf_min or led["vf"], v_pior), "v": v_pior, "vf": vf_min or led["vf"]}
    c["passa_do_pino"] = c["pior"]["i"] > mcu["i_pino"]
    if pendentes:
        c["pendentes"] = pendentes
    return c


def tensoes_do_3v3(mcu):
    """o 3V3 do meio e as pontas da faixa dele (vdd_min e vdd_max); a ponta pendente fica de fora, e a conta diz isso.
    (volts, pendentes)"""
    vs, pendentes = [mcu["vdd"]], []
    for campo in ("vdd_min", "vdd_max"):
        if e_numero(mcu.get(campo)):
            vs.append(mcu[campo])
        else:
            pendentes.append(f"{NOME_DO_NUMERO[campo]} do cérebro está pendente: a faixa do olho de luz usa o 3V3 do meio")
    return vs, pendentes


def tabela_do_divisor(ldr, r, mcu):
    """os volts no pino em cada luz e em cada canto do LDR: 'v' com o 3V3 do meio, 'v_de' e 'v_ate' nas pontas do 3V3.
    na_faixa vale nas pontas também (a mesma conta da etapa 4, testar.faixa_do_ldr)"""
    vdds, _ = tensoes_do_3v3(mcu)
    linhas = []
    for lux in LUX_DA_TABELA:
        cantos = {}
        for canto in CANTOS:
            vs = [circuito.divisor_do_ldr(ldr, r, vdd, lux, canto) for vdd in vdds]
            cantos[canto] = {"ohms": circuito.ohms_do_ldr(ldr, lux, canto), "v": vs[0], "v_de": min(vs), "v_ate": max(vs),
                             "na_faixa": mcu["adc_min"] <= min(vs) and max(vs) <= mcu["adc_max"]}
        linhas.append({"lux": lux, "escuro": not lux, "cantos": cantos,
                       "na_faixa": all(c["na_faixa"] for c in cantos.values())})
    return linhas


def serve_no_divisor(linhas):
    """a regra da decisão do divisor: o LDR do meio na faixa boa de 1 a 100 lux e, em 10 lux (circuito.LUX_PADRAO),
    os dois cantos também"""
    return (all(x["cantos"]["meio"]["na_faixa"] for x in linhas if x["lux"])
            and all(x["na_faixa"] for x in linhas if x["lux"] == circuito.LUX_PADRAO))


def conta_do_divisor(ldr, ohms, mcu):
    """3V3 → resistor fixo → pino → LDR → GND: os volts no pino em cada luz, nos cantos do LDR (o de menor resistência,
    o do meio e o de maior), e se cai na faixa boa do ADC (adc_min a adc_max). No escuro a tensão sobe.
    faixa = do menor ao maior resistor de loja (E24) que passa na regra (serve_no_divisor). O sugerido: o do carrinho,
    se serve; senão os 22 kΩ da decisão, se servem pra esse LDR; senão o do meio da faixa. Sem resistor no carrinho,
    a conta é a do sugerido"""
    servem = [r for r in valores_e24() if serve_no_divisor(tabela_do_divisor(ldr, r, mcu))]
    serve = ohms is not None and serve_no_divisor(tabela_do_divisor(ldr, ohms, mcu))
    meio = math.sqrt(servem[0] * servem[-1]) if servem else None
    padrao = (ohms if serve else R_DIVISOR if R_DIVISOR in servem
              else min(servem, key=lambda v: abs(math.log(v / meio))) if servem else None)
    r = ohms if ohms is not None else padrao or R_DIVISOR
    vdds, pendentes = tensoes_do_3v3(mcu)
    c = {"tipo": "divisor", "padrao": padrao, "r_fixo": r, "v": mcu["vdd"], "vdd": mcu["vdd"],
         "vdd_de": min(vdds), "vdd_ate": max(vdds), "adc_min": mcu["adc_min"], "adc_max": mcu["adc_max"],
         "linhas": tabela_do_divisor(ldr, r, mcu), "faixa": {"de": servem[0], "ate": servem[-1]} if servem else None,
         "ponto_1lux": ldr.get("ponto_1lux"), "condicao_3v3": mcu.get("condicao_3v3"),
         "fontes": fontes_de(mcu, "vdd", "vdd_min", "vdd_max", "adc_min", "adc_max")}
    if ohms is not None:
        c["bate"] = serve
    if not servem:   # nenhum resistor de loja dá: o problema é o LDR
        c["impossivel"] = True
        c["aviso"] = ("nenhum resistor de loja (série E24) deixa esse olho de luz na faixa boa do ADC, com o LDR do meio "
                      "de 1 a 100 lux e os dois cantos em 10 lux: troque o LDR")
    if pendentes:
        c["pendentes"] = pendentes
    return c


def conta_do_piezo(piezo, ohms, mcu):
    """o resistor em série com o piezo: a faixa vem do fabricante (r_serie). O pico é a borda do apito, quando o piezo
    vira um fio por um instante: só o resistor e o pino seguram a corrente"""
    lo, hi = piezo["r_serie"]
    serve = ohms is not None and lo <= ohms <= hi
    padrao = ohms if serve else mais_perto(lo)
    r = padrao if ohms is None else ohms   # a conta é a do resistor do carrinho; sem ele, a do sugerido
    v_pior, pendentes = v_do_pior(mcu)
    c = {"tipo": "piezo", "padrao": padrao, "ohms": r, "r_serie": [lo, hi], "v": mcu["vdd"], "r_pino": mcu["r_pino"],
         "pico": mcu["vdd"] / (r + mcu["r_pino"]), "pior": {"i": v_pior / (r + mcu["r_pino"]), "v": v_pior},
         "i_pino": mcu["i_pino"], "nota": piezo.get("nota"), "condicao_3v3": mcu.get("condicao_3v3"),
         "fontes": fontes_de(mcu, "vdd", "vdd_max", "r_pino", "i_pino")}
    c["passa_do_pino"] = c["pior"]["i"] > mcu["i_pino"]
    if ohms is not None:
        c["bate"] = serve
    if pendentes:
        c["pendentes"] = pendentes
    return c


def conta_do_botao(ohms, mcu, pino=None):
    """GPIO (com o pull-up de dentro) → resistor → botão → GND. O resistor pode ir de r_min a r_max:
    abaixo de r_min, um pino que virou saída em 1 (ou uma ponte de solda) com o botão apertado passa da força padrão;
    acima de r_max, apertado o pino não chega abaixo do VIL e não lê 0"""
    if pino in mcu.get("so_entrada", []):
        return {"falta": [f"o {pino} não tem pull-up de dentro: o botão precisa de outro pino ou de um resistor pro 3V3"]}
    (v_pior, pendentes), vdd, r_pull, vil = v_do_pior(mcu), mcu["vdd"], mcu["r_pull"], mcu["vil"]
    r_min, r_max = v_pior / mcu["i_pino"] - mcu["r_pino"], r_pull * vil / (1 - vil)
    serve = ohms is not None and r_min <= ohms <= r_max
    padrao = ohms if serve else R_BOTAO if r_min <= R_BOTAO <= r_max else mais_perto(math.sqrt(r_min * r_max))
    r = padrao if ohms is None else ohms   # a conta é a do resistor do carrinho; sem ele, a do sugerido
    c = {"tipo": "botao", "padrao": padrao, "ohms": r, "faixa": {"de": r_min, "ate": r_max}, "v": vdd, "r_pull": r_pull,
         "vil": vil * vdd, "v_apertado": vdd * r / (r + r_pull),
         "curto": {"i": v_pior / (r + mcu["r_pino"]), "v": v_pior}, "i_pino": mcu["i_pino"],
         "condicao_3v3": mcu.get("condicao_3v3"), "fontes": fontes_de(mcu, "vdd", "vdd_max", "r_pino", "i_pino", "r_pull", "vil")}
    c["le_zero"] = c["v_apertado"] < c["vil"]
    c["passa_do_pino"] = c["curto"]["i"] > mcu["i_pino"]
    if ohms is not None:
        c["bate"] = serve
    if pendentes:
        c["pendentes"] = pendentes
    return c


# ---------- projeto.json ----------
def ler_projeto(pasta):
    arq = Path(pasta) / "projeto.json"
    return json.loads(arq.read_text()) if arq.exists() else None


def salvar_projeto(pasta, proj):
    arq = Path(pasta) / "projeto.json"
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(proj, ensure_ascii=False, indent=1))
    tmp.replace(arq)


def bloco_do_ref(proj, ref):
    return next((b for b in proj["blocos"] if b["ref"] == ref), None)


def ref_do_bloco(proj, bloco):
    return next((b["ref"] for b in proj["blocos"] if b["bloco"] == bloco), None)


def eletrica_do_bloco(proj, pecas, bloco):
    b = next((b for b in proj["blocos"] if b["bloco"] == bloco), None)
    return (pecas.get(b.get("peca")) or {}).get("eletrica") if b else None


def conta_do_projeto(proj, pecas):
    """a conta do freio, quando o projeto e uma pilha, um resistor e um LED (a lanterninha)"""
    led_b = next((b for b in proj["blocos"] if b["bloco"] == "led"), None)
    resposta = brilho_pedido(proj, led_b["ref"])[0] if led_b else proj.get("perguntas", {}).get("brilho", {}).get("resposta")
    pilha, led = eletrica_do_bloco(proj, pecas, "pilha"), eletrica_do_bloco(proj, pecas, "led")
    resposta = resposta if resposta in PERGUNTAS["brilho"]["opcoes"] else None   # editada à mão com outra: sem conta
    if not resposta or not pilha or not led:
        falta = [] if resposta else ["responder quanta luz você quer"]
        falta += [] if pilha else ["escolher a pilha"]
        falta += [] if led else ["escolher o LED (e conferir o datasheet dele)"]
        return {"falta": falta}
    falta = falta_na_peca(pilha, ref_do_bloco(proj, "pilha"), "pilha") + falta_na_peca(led, led_b["ref"], "led")
    if falta:   # número pendente: sem conta (nada de chute)
        return {"falta": falta}
    conta = conta_do_freio(pilha, led, PERGUNTAS["brilho"]["opcoes"][resposta]["fracao"])
    if conta is None:
        return {"falta": ["a curva de brilho do LED (datasheet)"]}
    conta["resposta"] = resposta
    if conta.get("impossivel"):
        conta["aviso"] = aviso_do_led(conta, led_b["ref"], por_led=ajuste_por_led_a_vista(proj, None))
    conta["i_testada"] = pilha.get("i_testada")
    conta["mah"] = pilha.get("mah")
    return conta


def tipos_no_txt(pasta):
    """REF -> tipo, direto do placa.txt (sem montar a placa)"""
    arq = Path(pasta) / "placa.txt"
    tipos = {}
    if arq.exists():
        for linha in arq.read_text().splitlines():
            p = linha.split("#")[0].split()
            if len(p) >= 3 and p[0] == "peca":
                tipos[p[1]] = p[2]
    return tipos


# ---------- projeto com ESP32: a peça de loja brasileira, o cérebro e uma conta por resistor ----------
def tipo_de_outra_loja(chave, e):
    """peça de loja brasileira com 'tipo' (robocore:...): o desenho e a elétrica vêm do tipo da biblioteca;
    o preço, a foto e o link, do catálogo"""
    bib = BIBLIOTECA[e["tipo"]]
    return {**bib, "tipo": e["tipo"], "nome": e.get("apelido") or e["nome"], "pendente": list(bib.get("pendente", [])),
            "loja": {"codigo": chave, "modelo": e["modelo"], "marca": e["marca"], "pacote": e["pacote"],
                     "tamanho": e.get("tamanho") or "", "preco": e["preco"], "moeda": e.get("moeda", "BRL"),
                     "minimo": e.get("minimo") or 1, "estoque": e.get("estoque"), "datasheet": e.get("datasheet") or "",
                     "link": e["link"], "foto": e.get("foto"), "loja": e.get("loja"), "situacao": e.get("situacao")}}


def tipo_do_bloco(b, pecas, cat=None):
    """o tipo da peça escolhida pro bloco: da LCSC (pecas/C*.json) ou, olhando o catálogo, de loja brasileira com tipo"""
    codigo = b.get("peca")
    if not codigo:
        return None
    if codigo in pecas:
        return pecas[codigo]
    e = (cat or {}).get("pecas", {}).get(codigo)
    return tipo_de_outra_loja(codigo, e) if e and e.get("tipo") in BIBLIOTECA else None


def cerebro_do_projeto(proj, tipos):
    """(o bloco do cérebro, o tipo da peça dele); (None, None) quando o projeto não tem cérebro"""
    b = next((b for b in proj["blocos"] if b["bloco"] == "cerebro"), None)
    return b, (tipos.get(b["ref"]) if b else None)


def mcu_de(tipo):
    """a elétrica do cérebro (modelo mcu), ou None"""
    e = (tipo or {}).get("eletrica") or {}
    return e if e.get("modelo") == "mcu" else None


def pino_no_cerebro(tipo, nome):
    """onde o GPIO fica no DevKit: o número do furo, o que está escrito do lado e o cuidado com ele"""
    n = next((n for n, x in (tipo.get("nomes") or {}).items() if x == nome), None)
    if n is None:
        return None
    return {"pino": n, "serigrafia": (tipo.get("serigrafia") or {}).get(n), "cuidado": (tipo.get("cuidados") or {}).get(n)}


def brilho_pedido(proj, ref):
    """o brilho que esse LED tem que dar: o ajuste dele, se tiver; senão a resposta geral. (resposta, quem, do_led)"""
    p = proj.get("perguntas", {}).get("brilho", {})
    proprio = (p.get("por_led") or {}).get(ref)
    if proprio:
        return proprio.get("resposta"), proprio.get("quem"), True
    return p.get("resposta"), p.get("quem"), False


def ajuste_por_led_a_vista(proj, mcu):
    """a pergunta do brilho mostra o ajuste de cada LED: sempre com o cérebro; sem ele, só se o projeto já tem um"""
    return bool(mcu) or bool(proj.get("perguntas", {}).get("brilho", {}).get("por_led"))


def aviso_do_led(c, ref, mcu=None, por_led=True):
    """a frase da conta que não dá (impossível) ou que a etapa 4 reprova (passa da força padrão do pino), com o que fazer:
    pedir menos luz só pra esse LED (a resposta geral fica) ou, sem o ajuste de cada LED à vista, na pergunta geral"""
    nome = PERGUNTAS["brilho"]["opcoes"][c["resposta"]]["nome"]
    fazer = ("peça menos luz pra ele (o ajuste de cada LED)" if por_led
             else f"peça menos luz na pergunta '{PERGUNTAS['brilho']['texto']}'")
    if c.get("impossivel"):
        quem = f"o pino do cérebro ({volts_txt(mcu['vdd'])} V)" if mcu else "a pilha"
        return f"{quem} não tem força pro brilho '{nome}' no {ref}, nem sem resistor: {fazer}"
    # a mesma conta da etapa 4 (testar.liga_com_esp32: "puxa demais do pino")
    return (f"com o brilho '{nome}', o {ref} puxa até {mA_txt(c['pior']['i'])} mA no pior caso (3V3 em "
            f"{volts_txt(c['pior']['v'])} V e o LED que acende com menos tensão), acima da força padrão do pino "
            f"(~{mA_txt(c['i_pino'])} mA): a etapa 4 reprova. {fazer[:1].upper() + fazer[1:]}")


def conta_do_led_no_projeto(proj, led_b, led, mcu, pecas, ohms):
    """o resistor de um LED: com cérebro, o pino é a pilha (conta_do_led); sem cérebro, a pilha do projeto (igual à lanterninha)"""
    ref = led_b["ref"]
    resposta, _, do_led = brilho_pedido(proj, ref)
    pilha = None if mcu else eletrica_do_bloco(proj, pecas, "pilha")
    falta = [] if resposta in PERGUNTAS["brilho"]["opcoes"] else [f"responder quanta luz você quer no {ref}"]
    falta += falta_na_peca(led, ref, "led") if led else [f"escolher o {ref} (e conferir o datasheet dele)"]
    falta += [] if mcu else falta_na_peca(pilha, ref_do_bloco(proj, "pilha"), "pilha") if pilha else ["escolher a pilha"]
    duty = led_b.get("duty_max")
    if duty is not None and not (isinstance(duty, (int, float)) and not isinstance(duty, bool) and 0 < duty <= 1):
        falta.append(f"o duty_max do {ref} vai de 0 a 1 (a parte do tempo em que ele fica aceso)")
    if falta:
        return {"falta": falta}
    fracao = PERGUNTAS["brilho"]["opcoes"][resposta]["fracao"]
    if mcu:
        c = conta_do_led(mcu, led, fracao)
    else:
        c = conta_do_freio(pilha, led, fracao)
        if c is not None:
            c.update(i_testada=pilha.get("i_testada"), mah=pilha.get("mah"))
    if c is None:
        return {"falta": [f"a curva de brilho do {ref} (datasheet)"]}
    c.update(resposta=resposta, led=ref, resposta_do_led=do_led)
    if c.get("impossivel") or c.get("passa_do_pino"):
        c["aviso"] = aviso_do_led(c, ref, mcu, ajuste_por_led_a_vista(proj, mcu))
    if duty is not None and not c.get("impossivel"):   # PWM: aceso só nessa parte do tempo
        c.update(duty_max=duty, duty_origem=led_b.get("origem"),
                 luz_media=c["brilho"] * duty if c.get("brilho") is not None else None)
    if ohms is not None and c.get("padrao"):
        c["bate"] = ohms == c["padrao"]
    return c


def conta_do_resistor(proj, b, tipos, pecas):
    """a conta de um resistor, pelo bloco que ele atende ('led' ou 'para'): o LED (brilho), o olho de luz (divisor),
    o som (piezo) ou o botão. Sem 'led' nem 'para' é a lanterninha: uma pilha, um resistor e um LED (conta_do_projeto)"""
    alvo_ref = b.get("led") or b.get("para")
    cerebro, tipo_cerebro = cerebro_do_projeto(proj, tipos)
    if not alvo_ref:
        if cerebro:
            return {"falta": [f"dizer pra que serve o {b['ref']} ('led' ou 'para' no projeto.json)"]}
        return conta_do_projeto(proj, pecas)
    alvo = bloco_do_ref(proj, alvo_ref)
    if not alvo or (b.get("led") and alvo["bloco"] != "led"):
        return {"falta": [f"o {alvo_ref} do {b['ref']} não é um bloco {'de LED ' if b.get('led') else ''}deste projeto"]}
    juntos = [x["ref"] for x in proj["blocos"] if x["bloco"] == "resistor" and (x.get("led") or x.get("para")) == alvo_ref]
    if len(juntos) > 1:   # dois em série dariam outra conta: um resistor por LED (e por botão, som e olho de luz)
        return {"falta": [f"o {alvo_ref} está com {len(juntos)} resistores no projeto.json ({', '.join(juntos)}): "
                          f"é um só pra ele"]}
    mcu = mcu_de(tipo_cerebro)
    if cerebro and not mcu:
        return {"falta": ["escolher o cérebro (o DevKit)"]}
    eletrica = (tipos.get(alvo_ref) or {}).get("eletrica") or {}
    ohms = (tipos.get(b["ref"]) or {}).get("valor")
    precisa = {"led": ("vdd", "r_pino", "i_pino"), "ldr": ("vdd", "adc_min", "adc_max"), "buzzer": ("vdd", "r_pino", "i_pino"),
               "botao": ("vdd", "r_pino", "i_pino", "r_pull", "vil")}.get(alvo["bloco"])
    if precisa is None:
        return {"falta": [f"ainda não sei fazer a conta de um resistor pro bloco {alvo['bloco']} ({alvo_ref})"]}
    if mcu and falta_no_cerebro(mcu, *precisa):
        return {"falta": falta_no_cerebro(mcu, *precisa)}
    if alvo["bloco"] == "led":
        return conta_do_led_no_projeto(proj, alvo, eletrica or None, mcu, pecas, ohms)
    if not mcu:
        return {"falta": [f"o cérebro (o DevKit): a conta do {b['ref']} é com o pino dele"]}
    if alvo["bloco"] == "ldr":
        ok = eletrica.get("modelo") == "ldr"
        falta = falta_na_peca(eletrica, alvo_ref, "ldr") if ok else [f"escolher o {alvo_ref} (e conferir o datasheet dele)"]
        c = {"falta": falta} if falta else conta_do_divisor(eletrica, ohms, mcu)
    elif alvo["bloco"] == "buzzer":
        ok = eletrica.get("modelo") == "piezo"
        falta = falta_na_peca(eletrica, alvo_ref, "buzzer") if ok else [f"escolher o {alvo_ref} (e conferir o datasheet dele)"]
        c = {"falta": falta} if falta else conta_do_piezo(eletrica, ohms, mcu)
    else:
        c = conta_do_botao(ohms, mcu, alvo.get("pino"))
    if "falta" not in c:   # de onde veio o valor: o que o projeto.json diz; senão, o fabricante (piezo) ou a conta
        c.update(para=alvo_ref, origem=b.get("origem") or de_onde_veio(proj, alvo, c, tipos))
        if alvo["bloco"] == "ldr" and c["padrao"] not in (None, R_DIVISOR):   # o do carrinho, ou o sugerido pra outro LDR
            c["aviso"] = (f"a decisão 'Divisor da luz noturna' é {ohms_txt(R_DIVISOR)}, e os limites de luz do programa "
                          f"(acende em 10 lux, apaga em 23 lux) foram calculados com ele: com {ohms_txt(c['padrao'])}, "
                          "refaça essa conta")
    return c


def de_onde_veio(proj, alvo, c, tipos):
    """a frase de onde veio o valor sugerido (o 'padrao'), dita só com o que vale pra este projeto e este carrinho"""
    if alvo["bloco"] == "buzzer":
        return c.get("nota")
    if alvo["bloco"] == "ldr":
        regra = "o LDR do meio fica na faixa boa do ADC de 1 a 100 lux e, em 10 lux, os dois cantos também"
        if c["padrao"] is None:   # nenhum serve: o aviso da conta diz o que fazer
            return None
        if c["padrao"] == R_DIVISOR:
            return ("decisão 'Divisor da luz noturna': com 10 kΩ o escuro de 1 lux passava da faixa boa do ADC; "
                    "com 22 kΩ, de 1 a 100 lux fica dentro com o LDR do meio")
        if c.get("bate"):
            return f"a conta: com o {ohms_txt(c['padrao'])} do carrinho, {regra}"
        return (f"a conta: os {ohms_txt(R_DIVISOR)} da decisão 'Divisor da luz noturna' não servem pra esse LDR; "
                f"de {ohms_txt(c['faixa']['de'])} a {ohms_txt(c['faixa']['ate'])}, {regra}, e {ohms_txt(c['padrao'])} "
                "fica no meio dessa faixa")
    faixa = (f"faixa da conta, de {ohms_txt(round(c['faixa']['de']))} a {ohms_txt(round(c['faixa']['ate']))} "
             "(a força padrão do pino e a tensão em que o pino lê 0)")
    if c["padrao"] != R_BOTAO:
        return f"a {faixa}"
    som = [x["ref"] for x in proj["blocos"] if x["bloco"] == "resistor" and x.get("para")
           and (bloco_do_ref(proj, x["para"]) or {}).get("bloco") == "buzzer" and (tipos.get(x["ref"]) or {}).get("valor") == R_BOTAO]
    return (f"decisão 'Botões': 1 kΩ fica bem dentro da {faixa}"
            + (f"; é o mesmo resistor do som ({', '.join(som)}), uma peça a menos pra comprar" if som else ""))


def acompanha_com_preco(lista, cat):
    """o que vem junto com a peça e não entra no placa.txt (as barras fêmea do DevKit), com o preço do catálogo"""
    pecas = cat["pecas"]

    def da_loja(codigo):
        e = pecas.get(codigo) or {}
        return {"codigo": codigo, "nome": e.get("apelido") or e.get("nome"), "preco": e.get("preco"),
                "moeda": e.get("moeda", "USD"), "minimo": e.get("minimo") or 1, "estoque": e.get("estoque"),
                "situacao": e.get("situacao"), "visto": e.get("visto"), "link": e.get("link"),
                "datasheet": e.get("datasheet"), "conferido": bool(e.get("conferido")), "no_catalogo": bool(e)}

    saida = []
    for a in lista:
        x = {**da_loja(a["codigo"]), **a}   # o nome que a biblioteca deu fica
        x["subtotal"] = (x["preco"] or 0) * max(a.get("qtd", 1), x["minimo"])
        if a.get("alternativa"):
            x["alternativa_peca"] = da_loja(a["alternativa"])
        saida.append(x)
    return saida


def cor_da_peca(e):
    """a cor de um LED em português: a do datasheet conferido, senão a que a loja diz (serve pro tipo e pro catálogo)"""
    el = e.get("eletrica") or (e.get("conferido") or {}).get("eletrica") or {}
    loja = (e.get("atributos") or (e.get("loja") or {}).get("atributos") or {}).get("Illumination Color")
    return el.get("cor") or catalogo.CORES.get(loja) or loja


def cores_do_catalogo(cat):
    """as opções da pergunta 'cor': as cores dos LEDs do catálogo, primeiro as que têm LED conferido (dá pra fazer a conta)"""
    cores = {}
    for codigo, e in cat["pecas"].items():
        cor = cor_da_peca(e) if e["categoria"] == CATEGORIA["led"] else None
        if cor:
            d = cores.setdefault(cor, {"id": cor, "nome": cor[:1].upper() + cor[1:], "pecas": 0, "conferidos": []})
            d["pecas"] += 1
            if e.get("conferido"):
                d["conferidos"].append(codigo)
    for d in cores.values():
        n, conf = d["pecas"], d["conferidos"]
        d["explica"] = (f"{n} LED{'s' if n > 1 else ''} dessa cor no catálogo; "
                        + (f"com o datasheet conferido: {', '.join(conf)}" if conf else "nenhum com o datasheet conferido ainda"))
    return sorted(cores.values(), key=lambda d: (not d["conferidos"], -d["pecas"], d["id"]))


# num projeto com cérebro o "por quê" muda: quem alimenta é o USB, e o resistor serve a quem ele está na frente
POR_QUE_COM_CEREBRO = {
    "botao": "Apertou, o pino do cérebro lê 0; solto, o pull-up de dentro segura o 1. O programa decide o que fazer.",
    ("resistor", "led"): "Segura a corrente que sai do pino no tanto certo: é ele que decide o brilho e protege o LED e o pino.",
    ("resistor", "botao"): "Protege o pino: se o programa errar e ligar esse pino como saída, com o botão apertado "
                           "seria um curto direto pro GND.",
    ("resistor", "buzzer"): "Segura o pico de corrente que o piezo puxa do pino a cada vez que ele liga.",
    ("resistor", "ldr"): "Junto com o olho de luz forma o divisor: a tensão no meio muda com a luz, e é ela que o pino lê.",
}


def por_que(proj, b, com_cerebro):
    if not com_cerebro:
        return BLOCOS[b["bloco"]]["por_que"]
    alvo = (bloco_do_ref(proj, b.get("led") or b.get("para") or "") or {}).get("bloco") if b["bloco"] == "resistor" else None
    return POR_QUE_COM_CEREBRO.get((b["bloco"], alvo)) or POR_QUE_COM_CEREBRO.get(b["bloco"]) or BLOCOS[b["bloco"]]["por_que"]


def estado(pasta):
    """tudo que a aba Processo mostra dos passos 1 a 3"""
    proj = ler_projeto(pasta)
    if not proj:
        return None
    pecas = carregar_pecas(pasta)
    tem = {b["bloco"] for b in proj["blocos"]}
    com_cerebro = "cerebro" in tem
    # o catálogo só é lido quando precisa: peça de loja brasileira, as barras do cérebro e as cores dos LEDs
    cat = catalogo.ler() if com_cerebro or any(":" in str(b.get("peca") or "") for b in proj["blocos"]) else None
    tipos = {b["ref"]: tipo_do_bloco(b, pecas, cat) for b in proj["blocos"]}
    contas = {b["ref"]: conta_do_resistor(proj, b, tipos, pecas) for b in proj["blocos"] if b["bloco"] == "resistor"}
    _, tipo_cerebro = cerebro_do_projeto(proj, tipos)
    no_txt = tipos_no_txt(pasta)
    blocos, totais, pendentes = [], {"BRL": 0.0, "USD": 0.0}, []
    for b in proj["blocos"]:
        info = BLOCOS[b["bloco"]]
        tipo, codigo = tipos[b["ref"]], b.get("peca")
        no_placa = (tipo or {}).get("tipo") if codigo and ":" in codigo else codigo   # loja brasileira: o tipo da biblioteca
        item = {"ref": b["ref"], "bloco": b["bloco"], "nome": info["nome"], "funcao": info["funcao"],
                "por_que": por_que(proj, b, com_cerebro), "quem": b.get("quem"), "peca": None,
                "na_placa": no_placa is not None and no_txt.get(b["ref"]) == no_placa if codigo else None}
        for campo in ("pino", "led", "para", "duty_max", "origem"):   # os campos do projeto com ESP32
            if campo in b:
                item[campo] = b[campo]
        if b.get("nome"):
            item["apelido"] = b["nome"]
        if b.get("pino") and tipo_cerebro:
            item["no_cerebro"] = pino_no_cerebro(tipo_cerebro, b["pino"])
        if tipo:
            loja = tipo["loja"]
            item["peca"] = {"codigo": loja["codigo"], "nome": tipo["nome"], "modelo": loja["modelo"], "marca": loja["marca"],
                            "tamanho": loja["tamanho"], "preco": loja["preco"], "minimo": loja["minimo"],
                            "estoque": loja["estoque"], "datasheet": loja["datasheet"], "link": loja["link"],
                            "foto": loja.get("foto"), "pendente": tipo.get("pendente", []), "valor": tipo.get("valor"),
                            "extras": tipo.get("extras", [])}
            moeda = loja.get("moeda", "USD")   # a LCSC é em US$; o que não diz moeda é de lá
            if moeda != "USD":
                item["peca"].update(moeda=moeda, loja=loja.get("loja"))
            if tipo.get("tipo"):
                item["peca"]["tipo"] = tipo["tipo"]
            eletrica = tipo.get("eletrica") or {}
            if eletrica.get("pendentes"):   # o que falta conferir e não segura a fábrica: fica à vista
                item["peca"]["avisos"] = list(eletrica["pendentes"])
                pendentes += [{"ref": b["ref"], "texto": t} for t in eletrica["pendentes"]]
            if eletrica.get("condicao_3v3"):
                item["peca"]["condicao_3v3"] = eletrica["condicao_3v3"]
            totais[moeda] = totais.get(moeda, 0.0) + (loja["preco"] or 0) * max(1, loja["minimo"] or 1)
            if tipo.get("acompanha"):   # as barras do DevKit: não entram no placa.txt, mas entram no carrinho
                item["acompanha"] = acompanha_com_preco(tipo["acompanha"], cat or catalogo.ler())
                for a in item["acompanha"]:
                    totais[a["moeda"]] = totais.get(a["moeda"], 0.0) + a["subtotal"]
            if tipo.get("confira"):
                item["confira"] = list(tipo["confira"])
        if b["bloco"] == "resistor":
            conta = contas[b["ref"]]
            if conta.get("padrao") and tipo and "bate" not in conta:
                conta["bate"] = tipo.get("valor") == conta["padrao"]
            item["conta"] = conta
            pendentes += [{"ref": b["ref"], "texto": t} for t in conta.get("pendentes", [])]
        blocos.append(item)

    # perguntas; no projeto com cérebro, a resposta de cada LED (o brilho geral pode ter ajuste por LED)
    leds = [b for b in proj["blocos"] if b["bloco"] == "led"]
    # a conta de cada LED: pelo 'led' do resistor; na lanterninha (sem cérebro, sem 'led' nem 'para'), o LED do projeto
    conta_do = {b.get("led") or b.get("para") or (None if com_cerebro or not leds else leds[0]["ref"]): contas[b["ref"]]
                for b in proj["blocos"] if b["ref"] in contas}
    perguntas = []
    for pid, p in PERGUNTAS.items():
        if p["precisa"] not in tem or (p.get("so_com") and p["so_com"] not in tem):
            continue
        r = proj.get("perguntas", {}).get(pid, {})
        q = {"id": pid, "texto": p["texto"], "resposta": r.get("resposta"), "quem": r.get("quem"),
             "opcoes": [{"id": k, **o} for k, o in p["opcoes"].items()] if p["opcoes"] else cores_do_catalogo(cat or catalogo.ler())}
        if pid == "brilho" and com_cerebro:
            q["opcoes"] = [{**o, "explica": BRILHO_NO_PINO[o["id"]]} for o in q["opcoes"]]
        if com_cerebro or r.get("por_led"):
            q["por_led"] = []
            for b in leds:
                if pid == "brilho":
                    resposta, quem, do_led = brilho_pedido(proj, b["ref"])
                    x = {"resposta": resposta, "quem": quem, "do_led": do_led,
                         "impossivel": bool((conta_do.get(b["ref"]) or {}).get("impossivel"))}
                else:
                    pedida = (r.get("por_led") or {}).get(b["ref"]) or {}
                    da_peca = cor_da_peca(tipos[b["ref"]]) if tipos[b["ref"]] else None
                    x = {"resposta": pedida.get("resposta"), "quem": pedida.get("quem"), "da_peca": da_peca,
                         "bate": pedida["resposta"] == da_peca if pedida.get("resposta") and da_peca else None}
                q["por_led"].append({"ref": b["ref"], "apelido": b.get("nome"), **x})
            q["respondida"] = all(x["resposta"] for x in q["por_led"])
        perguntas.append(q)

    # passar da força padrão do pino também segura: a etapa 4 reprova com a mesma conta (o "aviso" da conta diz isso)
    contas_ok = all(not c.get("falta") and not c.get("impossivel") and not c.get("passa_do_pino") and c.get("bate", True)
                    for c in contas.values())
    cores_ok = all(x.get("bate") is not False for q in perguntas if q["id"] == "cor" for x in q["por_led"])
    saida = {"objetivo": proj.get("objetivo", ""), "frase": proj.get("frase", ""), "perguntas": perguntas,
             "blocos": blocos, "total": round(totais["USD"], 4),   # o total de sempre: o que se paga em US$
             "totais": {m: round(v, 2 if m == "BRL" else 4) for m, v in totais.items()},
             "pronto": all(b["peca"] and not b["peca"]["pendente"] and b["na_placa"] for b in blocos)
                       and all(q.get("respondida", bool(q["resposta"])) for q in perguntas) and contas_ok and cores_ok}
    if pendentes:
        saida["pendentes"] = pendentes
    return saida


# ---------- o que o app muda ----------
def serve_no_bloco(bloco, e):
    """a categoria do catálogo tem de tudo; o bloco quer só uma parte dela (o LDR no meio dos sensores de luz,
    o piezo no meio dos buzzers, a placa pronta que tem o tipo da biblioteca)"""
    f = BLOCOS[bloco].get("filtro", {})
    if f.get("tipo") and e.get("tipo") not in BIBLIOTECA:
        return False
    if f.get("categoria_loja") and e.get("categoria_loja") not in f["categoria_loja"]:
        return False
    return all(e["atributos"].get(a) in vs for a, vs in f.get("atributos", {}).items())


def opcoes(pasta, ref, online=False):
    """o mundo de pecas que servem pra esse bloco: primeiro o catalogo (na hora, sem internet); online=True
    (ou catalogo sem nada pra esse caso) busca na loja e poe o que achar no catalogo.
    Resistor so com o valor da conta; LED da cor pedida pra ele (pergunta 'cor') ou da mesma cor do escolhido.
    O cérebro nunca vai na LCSC: só as placas do catálogo que têm o tipo da biblioteca."""
    import loja
    proj = ler_projeto(pasta)
    b = proj and bloco_do_ref(proj, ref)
    if not b:
        raise ValueError(f"{ref} não é um bloco deste projeto")
    bloco, atual, pecas = b["bloco"], b.get("peca"), carregar_pecas(pasta)
    categoria, cat = CATEGORIA[bloco], catalogo.ler()
    busca, alvo, cor, cor_pt = BLOCOS[bloco]["busca"], None, None, None
    if bloco == "resistor":
        tipos = {x["ref"]: tipo_do_bloco(x, pecas, cat) for x in proj["blocos"]}
        conta = conta_do_resistor(proj, b, tipos, pecas)
        alvo = conta.get("padrao") or (pecas.get(atual) or {}).get("valor")
        if not alvo:   # sem conta não tem valor pra procurar: diz o que fazer antes (a conta impossível diz no aviso)
            qual = f"do {ref}" if b.get("para") else "do brilho"
            raise ValueError(f"primeiro a conta {qual}: " + (conta.get("aviso") or ", ".join(conta.get("falta", []))
                                                              or "ainda não sei fazer"))
        busca = busca.format(valor=catalogo.ohms_busca(alvo))
    if bloco == "capacitor" and (bloco_do_ref(proj, b.get("para") or "") or {}).get("bloco") == "ldr":
        alvo = C_DO_LDR   # o do olho de luz; sem 'para', o valor ainda não foi decidido e a lista tem todos
    if bloco == "led":
        cor_pt = ((proj.get("perguntas", {}).get("cor", {}).get("por_led") or {}).get(ref) or {}).get("resposta")
        if not cor_pt:   # sem a pergunta: a cor do LED escolhido, como a loja diz
            cor = ((pecas.get(atual) or {}).get("loja", {}).get("atributos") or {}).get("Illumination Color")

    def servem(cat):
        lista = [e for e in catalogo.do_bloco(cat, categoria) if serve_no_bloco(bloco, e)]
        if alvo:   # o valor da conta (ohms) ou o do capacitor (farads)
            campo, unidade = ("Capacitance", "F") if bloco == "capacitor" else ("Resistance", "Ω")
            lista = [e for e in lista if math.isclose(numero_com_unidade(e["atributos"].get(campo), unidade) or 0, alvo)]
        if cor:
            lista = [e for e in lista if e["atributos"].get("Illumination Color") == cor]
        if cor_pt:
            lista = [e for e in lista if cor_da_peca(e) == cor_pt]
        return lista

    novas, ingles = 0, None
    if cor or cor_pt:   # a cor como a loja escreve: verde é "Green" (não "Emerald Green"); a que o CORES não tem sai do catálogo
        ingles = cor or next((k for k, v in catalogo.CORES.items() if v == cor_pt), None) or next(
            (e["atributos"]["Illumination Color"] for e in catalogo.do_bloco(cat, categoria)
             if cor_da_peca(e) == cor_pt and (e.get("atributos") or {}).get("Illumination Color")), None)
        pacote = (pecas.get(atual) or {}).get("loja", {}).get("pacote", "")
        busca = f"LED {'3mm' if '3' in pacote else '5mm'} {ingles.lower()}" if ingles else None   # sem a cor, não busca às cegas
    if busca and (online or not servem(cat)):
        achadas = [i for i in loja.buscar(busca, 30, validade=0 if online else loja.UM_DIA) if catalogo.serve(cat, categoria, i)
                   and (not ingles or i["atributos"].get("Illumination Color") == ingles or (cor_pt and cor_da_peca(i) == cor_pt))]
        novas = catalogo.adicionar(cat, categoria, sorted(achadas, key=lambda i: -i["estoque"])[:12])
        catalogo.salvar(cat, [categoria])
    lista = servem(cat)
    for e in lista:
        e["escolhida"] = e["codigo"] == atual
        e["conferida"] = bool(e.get("conferido")) or bloco in ("resistor", "capacitor")   # a loja ja diz tudo
        e.pop("conferido", None)
    if bloco == "botao":   # so o mesmo jeito de pinos da escolhida (o desenho da placa conta com ele)
        pacote = (pecas.get(atual) or {}).get("loja", {}).get("pacote", "")
        pinos = re.search(r"\d+P", pacote)
        lista = [e for e in lista if not pinos or pinos[0] in e["pacote"] or e["codigo"] == atual]
    potencia = lambda e: numero_com_unidade(e["atributos"].get("Power(Watts)"), "W") or 0   # resistor: o menor que aguenta vem antes
    lista.sort(key=lambda e: (not e["escolhida"], e["situacao"] != "ok", not e["conferida"], potencia(e), -(e["estoque"] or 0)))
    alvo_txt = (farads_txt(alvo) if bloco == "capacitor" else ohms_txt(alvo)) if alvo else None   # o filtro, pro app
    return {"ref": ref, "bloco": bloco, "busca": busca, "alvo": alvo, "alvo_txt": alvo_txt,
            "cor": cor_pt or catalogo.CORES.get(cor), "novas": novas,
            "destaques": cat["categorias"][categoria].get("destaques", []),
            "itens": lista}


def trocar_no_txt(pasta, ref, codigo, nome):
    """peca REF TIPO X Y [VALOR] -> peca REF CODIGO X Y   # nome (o valor vem da peca; o comentario velho sai).
    CODIGO pode ser um tipo da biblioteca (devkit_esp32_30). False se REF nao esta na placa (ou ainda nao tem placa.txt)"""
    arq = Path(pasta) / "placa.txt"
    if not arq.exists():   # o carrinho vem antes do desenho: a placa pode ainda nao ter placa.txt
        return False
    linhas, achou = arq.read_text().splitlines(keepends=True), False
    for i, linha in enumerate(linhas):
        codigo_txt, _, comentario = linha.partition("#")
        p = codigo_txt.split()
        if len(p) >= 5 and p[0] == "peca" and p[1] == ref and p[2] != codigo:
            fim = "\n" if linha.endswith("\n") else ""
            linhas[i] = f"peca {ref} {codigo} {p[3]} {p[4]}   # {nome}, escolhido no carrinho{fim}"
            achou = True
    if achou:
        arq.write_text("".join(linhas))
    return achou


def peca_de_outra_loja(codigo, bloco, cat):
    """a peça de loja brasileira (robocore:...) pro bloco: só do catálogo, da categoria do bloco e com o tipo da
    biblioteca (é de lá que vem o desenho; o catálogo dá o preço, a foto e o link)"""
    e = cat["pecas"].get(codigo)
    if not e:
        raise ValueError(f"{codigo} não está no catálogo: peça de loja brasileira só sai de lá (ferramenta/catalogo/)")
    if e.get("tipo") not in BIBLIOTECA:
        raise ValueError(f"{codigo} não tem um tipo da biblioteca no catálogo: sem ele a placa não tem o desenho da peça")
    if e["categoria"] != CATEGORIA[bloco] or not serve_no_bloco(bloco, e):
        raise ValueError(f"{codigo} ({e.get('apelido') or e['nome']}) não serve pro bloco {BLOCOS[bloco]['nome']}")
    return tipo_de_outra_loja(codigo, e)


def ficha_do_catalogo(codigo, e):
    """a peça do catálogo como a busca da loja devolve (loja.item): o catálogo guarda a categoria da loja em categoria_loja"""
    return {"codigo": codigo, "categoria": e.get("categoria_loja") or "", "atributos": e.get("atributos") or {},
            **{k: e.get(k) or "" for k in ("modelo", "marca", "pacote", "descricao", "datasheet", "link")},
            "preco": e.get("preco"), "minimo": e.get("minimo") or 1, "estoque": e.get("estoque") or 0}


def serve_da_lcsc(codigo, bloco, cat, ficha=None):
    """a peça da LCSC é do tipo do bloco? (um LDR não vira LED). A do catálogo, pela categoria dela e pelo filtro do
    bloco, como no opcoes; a que o catálogo não tem, pela ficha da loja (busca uma, se não veio) com as regras da
    categoria do bloco. O estoque não conta aqui: quem avisa dele é o catálogo. Erro antes de gravar qualquer coisa"""
    import loja
    cid, e = CATEGORIA[bloco], cat["pecas"].get(codigo)
    if e:
        ok, o_que = e["categoria"] == cid and serve_no_bloco(bloco, e), e.get("apelido") or e["nome"]
        onde = f"no catálogo ele está em {cat['categorias'].get(e['categoria'], {}).get('nome') or e['categoria']}"
    else:
        i = ficha or loja.ficha(codigo)
        i = {**i, "categoria_loja": i["categoria"], "estoque": math.inf}
        ok, o_que = catalogo.serve(cat, cid, i) and serve_no_bloco(bloco, i), i["descricao"] or i["modelo"]
        onde = f"na loja ele está em {i['categoria']}"
    if not ok:
        raise ValueError(f"{codigo} ({o_que}) não serve pro bloco {BLOCOS[bloco]['nome']}: {onde}")


def importar_sem_catalogo(codigo, bloco, pasta):
    """o loja.importar sem gravar nada em ferramenta/catalogo/: a ficha (preço, estoque) e o conferido saem do catálogo
    como estão; o desenho e a foto, do EasyEDA e da LCSC (o cache da loja guarda os dois de vez). A peça que o catálogo
    não tem vem da loja e fica só nesta placa. Devolve (tipo, avisos)"""
    import loja
    if not loja.CODIGO.match(codigo):
        raise loja.SemLoja(f"'{codigo}' não é um código da LCSC (ex: C119304)")
    cat, avisos = catalogo.ler(), []
    e = cat["pecas"].get(codigo)
    if e:
        dados = ficha_do_catalogo(codigo, e)
        if e.get("situacao", "ok") != "ok":
            avisos.append(f"no catálogo o {codigo} está '{e['situacao']}' (visto em {e.get('visto')})")
    else:
        dados = loja.ficha(codigo)
        avisos.append(f"o {codigo} não está no catálogo e ficou fora dele (atualizar_catalogo=False): só esta placa tem ele")
    serve_da_lcsc(codigo, bloco, cat, dados)
    try:   # primeiro só a resposta do EasyEDA: sem ela (e sem cache) é falta de internet; com ela, é o desenho
        loja.pedir(loja.DESENHO.format(codigo), validade=None)
    except loja.SemLoja as erro:   # o catálogo não guarda o desenho: o cache da loja guarda de vez, depois da 1ª vez
        raise loja.SemLoja(f"o desenho do {codigo} (EasyEDA) ainda não está no cache da loja: precisa de internet "
                           f"uma vez ({erro})")
    des = loja.desenho(codigo)   # o EasyEDA respondeu: um erro aqui é dele (não tem o desenho, ou é um que não sai no Gerber)
    try:
        pag = loja.pagina(codigo)
    except loja.SemLoja:
        pag = {"foto": None, "pdf": None}
    if pag["pdf"]:
        dados["datasheet"] = pag["pdf"]   # o link direto do pdf, como no loja.importar
    tipo = tipo_da_loja(bloco, dados, des)
    destino = Path(pasta) / "pecas"
    destino.mkdir(parents=True, exist_ok=True)
    try:
        jpg = loja.pedir(pag["foto"], validade=None, binario=True) if pag["foto"] else None
    except loja.SemLoja:
        jpg = None
    if jpg:
        (destino / f"{codigo}.jpg").write_bytes(jpg)
        tipo["loja"]["foto"] = f"{codigo}.jpg"
    (destino / f"{codigo}.json").write_text(json.dumps(tipo, ensure_ascii=False, indent=1))
    return tipo, avisos


def tipo_conhecido(tipo, pecas):
    """o tipo que o placa.txt usa (código da loja ou tipo da biblioteca): o de pecas/ desta placa, o da biblioteca ou
    o que o catálogo conferiu (nomes e elétrica); None se ninguém conhece"""
    return pecas.get(tipo) or BIBLIOTECA.get(tipo) or catalogo.conferido(tipo)


def polos_do_led(tipo):
    """(pino do +, pino do −) de um LED: o conferido no datasheet (eletrica mais/menos) ou o nome dos pinos;
    None se o tipo não diz (o desenho de cada fabricante numera de um jeito)"""
    e, nomes = (tipo or {}).get("eletrica") or {}, (tipo or {}).get("nomes") or {}
    mais = e.get("mais") or next((n for n, x in nomes.items() if x == "+"), None)
    menos = e.get("menos") or next((n for n, x in nomes.items() if x in ("−", "-")), None)
    return (str(mais), str(menos)) if mais and menos and str(mais) != str(menos) else None


def pinos_ligados(pasta, ref):
    """os pinos do REF que as linhas 'liga' do placa.txt usam (o comentário não conta), em ordem de número"""
    arq, usados = Path(pasta) / "placa.txt", set()
    for linha in arq.read_text().splitlines() if arq.exists() else []:
        p = linha.split("#")[0].split()
        if p[:1] == ["liga"]:
            usados |= {x.partition(".")[2] for x in p[1:] if x.partition(".")[0] == ref and "." in x}
    return sorted(usados, key=lambda n: (not n.isdigit(), int(n) if n.isdigit() else 0, n))


def virar_ligas(pasta, ref, troca):
    """troca = {pino velho: pino novo} do REF nas linhas 'liga' do placa.txt, tudo de uma vez (1↔2 não vira 1→2→1).
    O comentário da linha vira junto ('# D1.1 é o −' continua certo); o resto fica. Devolve [{'antes', 'depois'}]
    das linhas que mudaram, sem o comentário"""
    arq = Path(pasta) / "placa.txt"
    if not troca or not arq.exists():
        return []
    linhas, mudou = arq.read_text().splitlines(keepends=True), []
    pino = re.compile(rf"(?<![\w.]){re.escape(ref)}\.(\w+)")   # o D1.2, e não o D10.2 nem o XD1.2

    def virar(txt):   # os espaços e o resto ficam: só os pinos do REF mudam
        return pino.sub(lambda m: f"{ref}.{troca[m[1]]}" if m[1] in troca else m[0], txt)

    for i, linha in enumerate(linhas):
        codigo_txt, cerca, comentario = linha.partition("#")
        if codigo_txt.split()[:1] != ["liga"]:
            continue
        depois = virar(codigo_txt)
        if depois != codigo_txt:
            linhas[i] = depois + cerca + virar(comentario)
            mudou.append({"antes": " ".join(codigo_txt.split()), "depois": " ".join(depois.split())})
    if mudou:
        arq.write_text("".join(linhas))
    return mudou


def nome_e_codigo(nome, codigo):
    """'LED amarelo 5 mm, código C779441': com vírgula, porque o nome às vezes já termina num parêntese"""
    return f"{nome}, código {codigo}" if nome and nome != codigo else codigo


def trocar_polos(pasta, ref, antes, tipo_antes, codigo, tipo):
    """LED trocado por outro: se o + mudou de furo, as linhas 'liga' do LED mudam de furo junto, e o LED continua
    virado pro mesmo lado. Devolve (ligas, frase, avisos)"""
    velho, novo = polos_do_led(tipo_antes), polos_do_led(tipo)
    if not velho or not novo:   # sem saber o + de um dos dois, não vira nada; só avisa se tem ligação pra conferir
        qual = (f"do LED de antes ({nome_e_codigo((tipo_antes or {}).get('nome'), antes)})" if not velho
                else f"do LED novo ({nome_e_codigo(tipo['nome'], codigo)})")
        return [], None, [f"não sei qual furo é o + {qual}: as ligações do {ref} ficaram como estavam; confira o + e o "
                          "− delas antes de fabricar"] if pinos_ligados(pasta, ref) else []
    troca = {v: n for v, n in zip(velho, novo) if v != n}
    if not troca:
        return [], None, []
    ligas = virar_ligas(pasta, ref, troca)
    frase = "no desenho do LED novo o + fica no outro furo: " + (
        f"virei as {len(ligas)} ligações do {ref} pra o + continuar ligado no mesmo lugar" if ligas
        else f"o {ref} ainda não tem ligação pra virar")
    sem_datasheet = [nome_e_codigo(t.get("nome"), c) for c, t in ((antes, tipo_antes), (codigo, tipo)) if t.get("pendente")]
    avisos = [f"o + e o − do {p} ainda não foram conferidos no datasheet: virei pelo desenho do EasyEDA; confira "
              "antes de fabricar" for p in sem_datasheet] if ligas else []
    return ligas, frase, avisos


def furos_com_outro_nome(pasta, ref, tipo_antes, tipo):
    """peça trocada por uma que numera os furos de outro jeito (o esp32_devkit e o devkit_esp32_30): os furos do REF
    nas linhas 'liga' que têm outro nome na peça nova, [(furo, nome antes, nome agora)]. Só pra avisar: quem sabe
    pra onde cada ligação vai é o Claude, conferindo (o LED tem a troca dele, trocar_polos)"""
    velhos, novos = (tipo_antes or {}).get("nomes") or {}, (tipo or {}).get("nomes") or {}
    return [(n, velhos.get(n), novos.get(n)) for n in pinos_ligados(pasta, ref) if velhos.get(n) != novos.get(n)]


def escolher(pasta, ref, codigo, quem="Luiz", *, atualizar_catalogo=True):
    """põe a peça de verdade no bloco: no projeto.json (com quem escolheu e quando), em pecas/ e no placa.txt.
    Código da LCSC (C119304), só da categoria do bloco (serve_da_lcsc): loja.importar, que traz a peça e põe ela no
    catálogo; com atualizar_catalogo=False (só pelo nome) nada é gravado em ferramenta/catalogo/ (importar_sem_catalogo).
    Peça de loja brasileira (robocore:...): sai do catálogo, sem loja.importar nem pecas/; no placa.txt entra o tipo da
    biblioteca (peca U1 devkit_esp32_30). LED trocado por um com o + em outro furo: as linhas 'liga' dele mudam de furo
    junto (trocar_polos), e o retorno diz; outra peça com os furos de outro nome: o retorno avisa"""
    import loja
    if not isinstance(quem, str) or not quem.strip():   # escolher(p, ref, codigo, False) seria quem=False, e no catálogo
        raise TypeError(f"quem escolheu é um nome (veio {quem!r}); pra não gravar no catálogo: atualizar_catalogo=False")
    proj = ler_projeto(pasta)
    b = proj and bloco_do_ref(proj, ref)
    if not b:
        raise ValueError(f"{ref} não é um bloco deste projeto")
    bloco = b["bloco"]
    if bloco not in BLOCOS:
        raise ValueError(f"o bloco '{bloco}' do {ref} não existe (tem: {', '.join(BLOCOS)})")
    antes = tipos_no_txt(pasta).get(ref)   # o tipo que as linhas 'liga' do placa.txt conhecem
    tipo_antes = tipo_conhecido(antes, carregar_pecas(pasta)) if antes else None   # lido antes de gravar a nova
    avisos = []
    if ":" in codigo:
        tipo = peca_de_outra_loja(codigo, bloco, catalogo.ler())
        no_txt = tipo["tipo"]
    elif BLOCOS[bloco].get("filtro", {}).get("tipo"):
        raise ValueError(f"o bloco {BLOCOS[bloco]['nome']} não vem da LCSC: é uma placa pronta de loja brasileira com o "
                         "tipo da biblioteca, escolhida pelo catálogo (ex.: robocore:esp32-wifi-bluetooth)")
    elif not loja.CODIGO.match(codigo):
        raise loja.SemLoja(f"'{codigo}' não é um código da LCSC (ex: C119304)")
    elif atualizar_catalogo:
        serve_da_lcsc(codigo, bloco, catalogo.ler())   # antes do loja.importar, que põe a peça na categoria do bloco
        tipo, no_txt = loja.importar(codigo, bloco, pasta), codigo
    else:
        (tipo, avisos), no_txt = importar_sem_catalogo(codigo, bloco, pasta), codigo
    b.update(peca=codigo, quem=quem, quando=datetime.now().strftime("%Y-%m-%d %H:%M"))
    salvar_projeto(pasta, proj)
    trocar_no_txt(pasta, ref, no_txt, tipo["nome"])
    frase = f"trocou o {ref} por {nome_e_codigo(tipo['nome'], codigo)}, no carrinho" + (
        f"; no placa.txt é o {no_txt}" if no_txt != codigo else "")
    ligas = []
    if bloco == "led" and antes and antes != no_txt:   # o LED mudou de tipo na placa: o + pode ter mudado de furo
        ligas, mais, aviso = trocar_polos(pasta, ref, antes, tipo_antes, codigo, tipo)
        frase += f"; {mais}" if mais else ""
        avisos += aviso
    elif antes and antes != no_txt:   # outra peça: o mesmo número de furo pode ser outra coisa nela
        mudam = furos_com_outro_nome(pasta, ref, tipo_antes, tipo)
        if mudam:
            avisos.append(f"a peça nova numera os furos de outro jeito, e as ligações do {ref} ficaram como estavam: "
                          + ", ".join(f"{ref}.{n} agora é o {agora or '?'}" + (f" (era o {era})" if era else "")
                                      for n, era, agora in mudam) + ". Confira cada uma antes de fabricar")
    saida = {"tipo": tipo["nome"], "na_placa": tipos_no_txt(pasta).get(ref) == no_txt, "pendente": tipo["pendente"],
             "frase": frase, "no_txt": no_txt, "ligas": ligas}
    if avisos:
        saida["avisos"] = avisos
    return saida


def responder(pasta, pergunta, resposta, quem="Luiz", ref=None):
    """grava a resposta e quem decidiu. ref = um LED: a resposta é só dele (o brilho de um LED ou a cor dele);
    a cor é sempre de um LED"""
    p = PERGUNTAS.get(pergunta)
    validas = (p["opcoes"] or {d["id"] for d in cores_do_catalogo(catalogo.ler())}) if p else ()
    if resposta not in validas:
        raise ValueError("pergunta ou resposta desconhecida")
    proj = ler_projeto(pasta)
    if not proj:
        raise ValueError("esta placa não tem projeto.json")
    if (ref or p.get("por_led")) and (bloco_do_ref(proj, ref or "") or {}).get("bloco") != "led":
        raise ValueError(f"{ref or 'falta dizer o LED'}: essa resposta é de um LED deste projeto (D1, D2...)")
    r = {"resposta": resposta, "quem": quem, "quando": datetime.now().strftime("%Y-%m-%d %H:%M")}
    respostas = proj.setdefault("perguntas", {})
    if ref:
        respostas.setdefault(pergunta, {}).setdefault("por_led", {})[ref] = r
    else:   # a resposta geral; o ajuste de cada LED fica
        respostas[pergunta] = {**r, **({"por_led": respostas[pergunta]["por_led"]}
                                       if respostas.get(pergunta, {}).get("por_led") else {})}
    salvar_projeto(pasta, proj)
