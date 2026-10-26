r"""programa.py: roda o programa da placa (codigo/main.py) no gêmeo do laboratório, sem mexer no laboratorio/.

uso: python3 ferramenta/programa.py placas/<x>            o roteiro de teste da placa -> saida/programa.json
     python3 ferramenta/programa.py placas/<x> --livre [--entradas '{"apertos": [...], "luz": [...]}']
                                                        do jeito do app, sem conferências -> saida/programa_livre.json
     python3 ferramenta/programa.py placas/<x> --pinos  só escreve o codigo/pinos.py

Uma rodada (rodar):
1. pinos: o codigo/pinos.py sai do placa.txt (D1 = 32 ...), pro programa e a placa nunca discordarem
2. preparar: a cópia saida/programa/sianvolt_<placa>_<hash8>/ com codigo/*.py, roteiro.json e gemeo.roteiro.
   O laboratório trabalha numa pasta com o NOME da cópia; o hash do caminho deixa cada placa com a sua.
   No livre (o do app), só valem as entradas que vieram do app: sem nenhuma, a placa roda sozinha
3. o lab.py roda a cópia no gêmeo, ligado no placa.txt (--circuito), e devolve a linha do tempo (--json)
4. normalizar: a linha do tempo vira o programa.json (tempos em ms), com os nomes do NOSSO placa.txt
5. conferir: o codigo/confere.json (só no roteiro de teste; o livre roda sem conferências)
6. gravar: saida/programa.json ou saida/programa_livre.json, de uma vez
A trava saida/.rodando deixa uma rodada por placa (a etapa 8 do testar usa a mesma).

Entradas do app, em segundos (como o roteiro.json): {"apertos": [{"ref": "SW1", "de": 1.0, "ate": 1.2}],
"luz": [{"ref": "LDR1", "t": 2.0, "lux": 1}]}. O aperto vira 'de 1 s a 1,2 s aperta SW1' no fim do gemeo.roteiro
(aperta a chave de verdade do circuito). A luz vai no roteiro.json, e o roteiro.json da placa traz a luz do mesmo
jeito: {"t": 5, "luz": "LDR1", "lux": 1}. O preparar pergunta pro laboratório se ele conhece a luz
(recursos_do_lab, sem supor): se conhece, a luz vai em lux e o gêmeo põe o LDR do meio no circuito, então o pino
lê o divisor de verdade (um LDR ligado errado aparece aqui); num laboratório antigo, a luz vira volts no GPIO do
LDR, pela conta do nosso circuito (com_pinos + resolver + ohms_do_ldr, o LDR do meio). O brilho dos LEDs vem do
evento 'led' do gêmeo (os números) ou, num laboratório antigo, do texto do aviso 'led'. O gemeo.roteiro da placa
não leva linha de lux: a luz mora no roteiro.json, que serve aos dois laboratórios.

codigo/confere.json, o que o roteiro do laboratório não sabe conferir: {"confere": [...]}, com 4 tipos fechados.
Tempo sem '_ms' no nome é em segundos, como no roteiro.json. Chave que começa com '_' é comentário.
  {"tipo": "leds_da_serial", "regex": "deu (\\d)", "grupo": 1, "mapa": {"1": ["D4"], "2": ["D1", "D7"]}}
      em cada linha da serial que casa, os LEDs acesos (dos que estão no mapa) são os da face que ela disse
  {"tipo": "pwm_freq", "pino": "GPIO26", "hz": 4000, "folga": 50, "depois_de": "GPIO25 sobe"}
      a cada vez que o evento acontece, o PWM ligado no pino (o que já estava ou o primeiro depois) fica a
      hz ± folga Hz. depois_de: "GPIOn sobe", "GPIOn desce" ou um tempo; sem ele, desde o começo
  {"tipo": "serial_menos_evento", "regex_ms": "ganhou em (\\d+) ms", "evento": "GPIO25 sobe", "folga_ms": 2}
      o número da linha (ms) = a hora da linha − a hora do último evento antes dela, ± folga_ms
  {"tipo": "duty_entre", "pino": "GPIO25", "de_t": 8.5, "ate_t": 14, "min": 0.35, "max": 0.37}
      de de_t a ate_t, o duty do pino fica entre min e max (o pino em 0 ou 1 conta como duty 0 ou 1)
"""
import contextlib
import fcntl
import hashlib
import importlib
import importlib.util
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import types
from datetime import datetime
from pathlib import Path

import blocos
import circuito
import gerar

RAIZ = Path(__file__).resolve().parent.parent
LAB = RAIZ / "laboratorio" / "lab.py"
LAB_PLACA = "esp32"   # a placa do laboratório: o DevKit DOIT de 30 pinos é um ESP32
LIMITE_S = 300        # a rodada inteira do lab.py; ele mesmo espera até 120 s por memória livre antes de rodar
TEMPO_DO_LAB = 5.0    # sem 'tempo' no roteiro, o lab.py roda 5 s de placa (TEMPO_PADRAO do lab.py)
TEMPO_MAX = 60        # o app manda aperto e luz de 0 a 60 s
MAX_ENTRADAS = 50
FOLGA_T = 0.0005      # ms: o mesmo instante (o laboratório arredonda o t_ms em 3 casas)
USO, TRAVOU, INDISPONIVEL = 2, 3, 5   # os códigos de saída do lab.py que o programa.py também usa
GPIO = re.compile(r"GPIO\d+$")
EVENTO = re.compile(r"(GPIO\d+) (sobe|desce)$")
_T = r"(\d+(?:[.,]\d+)?)\s*(s|ms|us|µs)"   # um tempo do gemeo.roteiro (o formato de laboratorio/.../roteiro.py)
NOME_DO_MODELO = {"led": "LED", "chave": "botão", "ldr": "olho de luz", "piezo": "som"}


class Ocupada(Exception):
    """outra rodada (o app, a etapa 8 ou um terminal) está usando a placa"""


def num(x, casas=3):
    """1.25 -> '1,25'; 2.0 -> '2' (o jeito do gemeo.roteiro e do Luiz)"""
    return f"{x:.{casas}f}".rstrip("0").rstrip(".").replace(".", ",")


def seg(ms):
    """ms -> '1,250 s' (como o laboratório escreve)"""
    return f"{ms / 1000:.3f} s".replace(".", ",")


def numero(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def ordem(ref):
    """D2 antes de D10"""
    m = re.match(r"(\D*)(\d*)(.*)", ref)
    return m.group(1), int(m.group(2) or 0), m.group(3)


def modelo_de(p):
    return (p.get("eletrica") or {}).get("modelo")


def tem_laboratorio():
    """o lab.py e o MicroPython do PC (o gêmeo) estão nesta máquina? O clone limpo não tem: a rodada dá código 5"""
    fe = Path(os.environ.get("LAB_FERRAMENTAS") or RAIZ / "laboratorio" / ".ferramentas")
    return LAB.is_file() and (fe / "micropython-unix" / "micropython").is_file()


_RECURSOS = {}   # o que o laboratório sabe, guardado até um dos arquivos mudar (o app fica aberto dias)
_TRAVA_DO_LAB = threading.Lock()   # o sys.modules e o sys.dont_write_bytecode são do processo: uma pergunta por vez


def recursos_do_lab():
    """o que o laboratório desta máquina sabe além do de sempre, perguntado pra ele mesmo (sem supor):
    'led' = o contrato tem o evento 'led' (o brilho de cada LED em número); 'luz' = o roteiro.json aceita
    {"t", "luz": "LDR1", "lux"} e o motor gemeo transforma isso em luz no LDR. Laboratório antigo ou nenhum: vazio"""
    nucleo, motor = LAB.parent / "nucleo", LAB.parent / "motores" / "gemeo" / "motor" / "roteiro.py"
    try:
        chave = (str(LAB), tuple((nucleo / a).stat().st_mtime_ns for a in ("contrato.py", "roteiro.py")),
                 motor.stat().st_mtime_ns)
    except OSError:
        return frozenset()
    with _TRAVA_DO_LAB:
        if _RECURSOS.get("chave") != chave:
            _RECURSOS.update(chave=chave, tem=_perguntar_ao_lab(nucleo, motor))
        return _RECURSOS["tem"]


def _perguntar_ao_lab(nucleo, motor):
    """carrega o contrato e o roteiro do laboratório com nomes só deles (sem pôr o laboratório no sys.path e sem
    escrever .pyc lá) e testa: o contrato conhece o 'led'? o roteiro e o gêmeo aceitam a luz?"""
    nome = "_nucleo_do_lab"
    for m in [m for m in sys.modules if m == nome or m.startswith(nome + ".")]:
        del sys.modules[m]   # o laboratório mudou: lê de novo
    sys.modules[nome] = types.ModuleType(nome)
    sys.modules[nome].__path__ = [str(nucleo)]
    antes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        contrato, roteiro = (importlib.import_module(f"{nome}.{m}") for m in ("contrato", "roteiro"))
        spec = importlib.util.spec_from_file_location("_roteiro_do_gemeo", motor)
        gemeo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gemeo)
    except Exception:   # um laboratório quebrado ou de outro formato: o caminho de sempre
        return frozenset()
    finally:
        sys.dont_write_bytecode = antes
    tem = {"led"} if "led" in getattr(contrato, "TIPOS", {}) else set()
    try:
        roteiro.validar({"entradas": [{"t": 0, "luz": "LDR1", "lux": 1}]})
        if any(a.get("tipo") == "luz" for _, a in gemeo.Roteiro(1e6, [{"t_ms": 0, "luz": "LDR1", "lux": 1}]).eventos):
            tem.add("luz")
    except Exception:   # o roteiro antigo recusa a chave 'luz', e o gêmeo antigo procura o pino dela
        pass
    return frozenset(tem)


# ---------- a placa ----------
_MODELOS = {}   # pasta -> (chave, modelo): o montar roteia a placa, e com 7 LEDs isso leva ~1 s


def modelo_da_placa(pasta):
    """o placa.txt montado com as peças da loja da placa (o mesmo do testar e do gêmeo)"""
    pasta = Path(pasta).resolve()
    texto = (pasta / "placa.txt").read_text()
    chave = (texto, tuple((a.name, a.stat().st_mtime_ns) for a in sorted((pasta / "pecas").glob("C*.json"))))
    if _MODELOS.get(pasta, (None,))[0] != chave:
        try:
            _MODELOS[pasta] = (chave, gerar.montar(gerar.ler(texto), gerar.biblioteca(pasta)))
        except gerar.ErroTxt as e:
            raise ValueError(f"o placa.txt não monta ({e})") from None
    return _MODELOS[pasta][1]


def modelos_das_pecas(pasta):
    """ref -> modelo elétrico ('chave', 'ldr'...), direto do placa.txt e da biblioteca, sem montar (é rápido)"""
    try:
        lido = gerar.ler((Path(pasta) / "placa.txt").read_text())
    except gerar.ErroTxt as e:
        raise ValueError(f"o placa.txt tem erro ({e})") from None
    bib = gerar.biblioteca(pasta)
    return {ref: modelo_de(bib.get(p["tipo"]) or {}) for ref, p in lido["pecas"].items()}


def mcu_da(modelo):
    return next((p for p in modelo["pecas"] if modelo_de(p) == "mcu"), None)


def nos_gpios(modelo):
    """GPIO -> [(ref, pino da peça, resistor do meio ou None)]: as peças ligadas direto no pino ou por UM resistor.
    O resistor é o caminho e o capacitor só acalma a tensão: nenhum dos dois entra. O lado do resistor que cai na
    energia (3V3, GND) ou noutro pino do ESP32 não leva adiante; GPIO ligado direto na energia fica de fora"""
    u = mcu_da(modelo)
    if u is None:
        return {}
    do_u = {q["net"] for q in u["pinos"] if q["net"]}
    energia = {q["net"] for q in u["pinos"] if q["net"] and not GPIO.match(q["nome"] or "")}
    na_net = {}   # net -> [(peça, pino)]
    for p in modelo["pecas"]:
        for q in p["pinos"]:
            if p is not u and q["net"]:
                na_net.setdefault(q["net"], []).append((p, q["n"]))
    saida = {}
    for q in u["pinos"]:
        if not q["net"] or not GPIO.match(q["nome"] or "") or q["net"] in energia:
            continue
        achou = []
        for p, n in na_net.get(q["net"], []):
            if modelo_de(p) == "resistor":
                for outra in {r["net"] for r in p["pinos"] if r["net"] and r["net"] != q["net"]} - do_u:
                    achou += [(x["ref"], m, p["ref"]) for x, m in na_net[outra]
                              if x is not p and modelo_de(x) not in ("resistor", "capacitor")]
            elif modelo_de(p) != "capacitor":
                achou.append((p["ref"], n, None))
        unicos = {}   # (ref, resistor) -> o primeiro pino: o botão tem dois pinos em cada lado, ligados por dentro
        for ref, n, por in achou:
            unicos.setdefault((ref, por), (ref, n, por))
        if unicos:
            saida[q["nome"]] = sorted(unicos.values(), key=lambda a: (a[2] is not None, ordem(a[0])))
    return saida


def por_peca(modelo):
    """ref -> [(GPIO, pino da peça, resistor do meio)], a ligação direta primeiro"""
    refs = {}
    for gpio, lista in nos_gpios(modelo).items():
        for ref, n, por in lista:
            refs.setdefault(ref, []).append((gpio, n, por))
    return {ref: sorted(v, key=lambda x: x[2] is not None) for ref, v in refs.items()}


def nome_de_gente(proj, peca):
    """'LED A' (o nome do bloco no projeto.json); sem ele, o nome do tipo de peça ('LED', 'botão'...)"""
    b = next((b for b in (proj or {}).get("blocos", []) if b.get("ref") == peca["ref"]), None)
    if b and b.get("nome"):
        return b["nome"]
    return NOME_DO_MODELO.get(modelo_de(peca)) or peca.get("nome") or peca["ref"]


# ---------- 1. pinos.py ----------
def pinos(pasta):
    """escreve o codigo/pinos.py (D1 = 32  # LED A, U1 pino 6, D32) e devolve {nome: GPIO}. Peça ligada em dois
    GPIOs ganha um nome por pino (SW1_1, SW1_3). Nunca se chama placa.py: o laboratório escreve por cima dele"""
    pasta = Path(pasta)
    modelo = modelo_da_placa(pasta)
    u = mcu_da(modelo)
    if u is None:
        raise ValueError("a placa não tem o ESP32 (a peça com modelo 'mcu', o devkit_esp32_30)")
    proj = blocos.ler_projeto(pasta)
    pecas = {p["ref"]: p for p in modelo["pecas"]}
    furo = {q["nome"]: q["n"] for q in u["pinos"]}
    linhas = [f"# pinos.py: gerado pelo Sianvolt, não edite. Sai do placa.txt da placa {pasta.name} a cada rodada.",
              f"# Cada nome é uma peça da placa e o número é o GPIO do {u['ref']} (ESP32) em que ela liga, direto ou "
              "por um resistor.",
              "# No main.py: from pinos import D1  ->  Pin(D1, Pin.OUT)"]
    nomes = {}
    for ref, ligs in sorted(por_peca(modelo).items(), key=lambda x: ordem(x[0])):
        for gpio, n, por in ligs:
            nome = ref if len(ligs) == 1 else f"{ref}_{n}"
            nome = f"{nome}_{gpio[4:]}" if nome in nomes else nome   # dois GPIOs na mesma ligação
            escrito = (u.get("serigrafia") or {}).get(furo[gpio])
            nota = [nome_de_gente(proj, pecas[ref]), f"{u['ref']} pino {furo[gpio]}"]
            nota += [escrito] if escrito and escrito != gpio else []
            nota += [f"pelo {por}"] if por else []
            nomes[nome] = int(gpio[4:])
            linhas.append(f"{nome} = {nomes[nome]}  # {', '.join(nota)}")
    texto = "\n".join(linhas) + "\n"
    arq = pasta / "codigo" / "pinos.py"
    arq.parent.mkdir(exist_ok=True)
    if not arq.is_file() or arq.read_text() != texto:   # sem mudança, o arquivo fica como está
        tmp = arq.with_suffix(".tmp")
        tmp.write_text(texto)
        tmp.replace(arq)
    return nomes


# ---------- 2. preparar ----------
def tempo_do_app(v, onde):
    """segundos de 0 a 60, no ms: o gemeo.roteiro e o programa.json enxergam até o ms"""
    if not numero(v) or not 0 <= v <= TEMPO_MAX:
        raise ValueError(f"{onde}: o tempo vai de 0 a {TEMPO_MAX} s (veio {v!r})")
    return round(float(v), 3)


def lux_valido(v, onde):
    if not numero(v) or v < 0:
        raise ValueError(f"{onde}: a luz é um número de lux, de 0 pra cima (veio {v!r}; 0 é o escuro)")
    return v


def validar_entradas(pasta, entradas):
    """o que o app manda (em segundos) -> {"apertos": [{ref, de, ate}], "luz": [{ref, t, lux}]}, ou ValueError
    numa frase pro Luiz: aperto só em botão, luz só em olho de luz, tempo de 0 a 60 s, no máximo 50 entradas"""
    if entradas is None:
        return {"apertos": [], "luz": []}
    if not isinstance(entradas, dict) or set(entradas) - {"apertos", "luz"}:
        raise ValueError('as entradas são {"apertos": [...], "luz": [...]}')
    apertos, luz = entradas.get("apertos", []), entradas.get("luz", [])
    if not isinstance(apertos, list) or not isinstance(luz, list):
        raise ValueError("apertos e luz são listas")
    if len(apertos) + len(luz) > MAX_ENTRADAS:
        raise ValueError(f"no máximo {MAX_ENTRADAS} apertos e luzes juntos (vieram {len(apertos) + len(luz)})")
    modelos = modelos_das_pecas(pasta)
    tem = {m: sorted((r for r, x in modelos.items() if x == m), key=ordem) for m in ("chave", "ldr")}
    saida = {"apertos": [], "luz": []}
    for n, a in enumerate(apertos, 1):
        onde = f"aperto {n}"
        if not isinstance(a, dict) or set(a) != {"ref", "de", "ate"}:
            raise ValueError(f'{onde}: é {{"ref", "de", "ate"}}, com os tempos em segundos')
        if a["ref"] not in tem["chave"]:
            raise ValueError(f"{onde}: {a['ref']!r} não é um botão da placa (botões: {', '.join(tem['chave']) or 'nenhum'})")
        de, ate = tempo_do_app(a["de"], onde), tempo_do_app(a["ate"], onde)
        if ate <= de:   # já no ms: 1,0001 a 1,0004 s seria um aperto de 0 ms
            raise ValueError(f"{onde}: o {a['ref']} tem que soltar pelo menos 1 ms depois de apertar (veio: aperta "
                             f"em {num(de)} s e solta em {num(ate)} s)")
        saida["apertos"].append({"ref": a["ref"], "de": de, "ate": ate})
    for n, x in enumerate(luz, 1):
        onde = f"luz {n}"
        if not isinstance(x, dict) or set(x) != {"ref", "t", "lux"}:
            raise ValueError(f'{onde}: é {{"ref", "t", "lux"}}, com o tempo em segundos')
        if x["ref"] not in tem["ldr"]:
            raise ValueError(f"{onde}: {x['ref']!r} não é um olho de luz da placa (tem: {', '.join(tem['ldr']) or 'nenhum'})")
        saida["luz"].append({"ref": x["ref"], "t": tempo_do_app(x["t"], onde), "lux": lux_valido(x["lux"], onde)})
    return saida


def gpio_do_ldr(modelo, ref):
    """(o LDR, o GPIO em que ele liga, direto ou por um resistor), ou ValueError"""
    p = next((p for p in modelo["pecas"] if p["ref"] == ref), None)
    ligs = por_peca(modelo).get(ref)
    if p is None or modelo_de(p) != "ldr" or not ligs:
        raise ValueError(f"{ref} não é um olho de luz ligado num GPIO do ESP32")
    return p, ligs[0][0]


def volts_da_luz(modelo, ref, lux):
    """(GPIO, volts) que o pino do LDR lê com essa luz: o circuito inteiro (com_pinos + resolver), com os GPIOs
    soltos e o LDR do meio (circuito.ohms_do_ldr). No divisor de sempre dá igual ao circuito.divisor_do_ldr"""
    p, gpio = gpio_do_ldr(modelo, ref)
    net = next(q["net"] for q in mcu_da(modelo)["pinos"] if q["nome"] == gpio)
    r = circuito.resolver(circuito.com_pinos(modelo, {}), {"ldr": {ref: circuito.ohms_do_ldr(p["eletrica"], lux, quem=ref)}})
    return gpio, r["nets"][net]


def ler_json(arq, padrao):
    if not arq.is_file():
        return padrao
    try:
        return json.loads(arq.read_text())
    except ValueError as e:
        raise ValueError(f"o codigo/{arq.name} não é JSON válido: {e}") from None


def apertos_do_roteiro(texto):
    """os apertos de chave do gemeo.roteiro da placa -> [{ref, de, ate}] em ms (ate None = até o fim)"""
    def ms(v, u):
        return round(float(v.replace(",", ".")) * {"s": 1000, "ms": 1, "us": 0.001, "µs": 0.001}[u], 3)
    saida, abertos = [], {}
    for linha in texto.splitlines():
        s = linha.split("#")[0].strip()
        m = re.match(rf"de\s+{_T}\s+a\s+{_T}\s+aperta\s+(\S+)$", s)
        if m and not m.group(5).upper().startswith("GPIO"):
            saida.append({"ref": m.group(5), "de": ms(*m.group(1, 2)), "ate": ms(*m.group(3, 4))})
            continue
        m = re.match(rf"(?:em\s+)?{_T}\s+(aperta|solta)\s+(\S+)$", s)
        if m and not m.group(4).upper().startswith("GPIO"):
            if m.group(3) == "aperta":
                abertos[m.group(4)] = {"ref": m.group(4), "de": ms(*m.group(1, 2)), "ate": None}
                saida.append(abertos[m.group(4)])
            elif m.group(4) in abertos:
                abertos.pop(m.group(4))["ate"] = ms(*m.group(1, 2))
    return saida


def nome_da_copia(pasta, isolada=False):
    """sianvolt_<placa>_<8 hex do caminho> (+ _<pid> quando isolada: testes e rodadas em paralelo)"""
    pasta = Path(pasta).resolve()
    nome = f"sianvolt_{pasta.name}_{hashlib.sha256(str(pasta).encode()).hexdigest()[:8]}"
    return f"{nome}_{os.getpid()}" if isolada else nome


def apagar_vaga(nome):
    """apaga a pasta de trabalho que o lab.py abriu pra cópia 'nome' (laboratorio/build/esp32/gemeo/<nome>, ou a
    ~2, ~3... de rodadas em paralelo) e a .trava dela, se ninguém está nela. Pras cópias de nome único (a isolada e
    a da placa de teste), que deixavam uma vaga a cada rodada. A da placa de verdade fica: o lab.py reaproveita"""
    if not nome.startswith("sianvolt_"):   # só as nossas
        return
    obra = Path(LAB).parent / "build" / LAB_PLACA / "gemeo"
    for n in range(1, 9):   # as vagas do lab.py: nome, nome~2 ... nome~8
        pasta = obra / (nome if n == 1 else f"{nome}~{n}")
        arq = pasta.with_name(pasta.name + ".trava")
        if not arq.is_file():
            continue
        with open(arq, "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:   # outra rodada está nela
                continue
            shutil.rmtree(pasta, ignore_errors=True)
            arq.unlink(missing_ok=True)


def so_o_ambiente(extra):
    """o gemeo.roteiro da placa sem as entradas (apertos e pino forçado): ficam os comentários e o que é o mundo
    em volta (aparelho I2C, wifi). É o que vale no livre, onde as entradas são só as do app"""
    fica = []
    for linha in extra.splitlines():
        s = linha.split("#")[0].strip()
        if not s or re.match(rf"(?:(?:em\s+)?{_T}\s+)?(?:i2c|wifi)\b", s):
            fica.append(linha)
    return "\n".join(fica)


def preparar(pasta, entradas=None, livre=False, isolada=False, lux=None):
    """monta a cópia que o lab.py roda -> (pasta da cópia, entradas usadas em ms, pro programa.json).
    A cópia tem os codigo/*.py, o roteiro.json e o gemeo.roteiro. Fora do livre: o roteiro de teste da placa, com o
    que o app mandou no fim. No livre (o do app): só as entradas do app; o roteiro.json vai sem entradas e sem
    'confere', e o gemeo.roteiro só com o mundo em volta (I2C, wifi): sem nada do app, a placa roda sozinha.
    lux: a luz vai em lux pro gêmeo (True) ou em volts no pino do LDR, pela nossa conta (False, o laboratório antigo);
    None pergunta pro laboratório (recursos_do_lab). Na luz em lux, os volts do programa.json saem do gêmeo
    (normalizar). A placa (codigo/) nunca é mudada"""
    pasta = Path(pasta).resolve()
    codigo = pasta / "codigo"
    if not (codigo / "main.py").is_file():
        raise ValueError("a placa não tem programa: falta o codigo/main.py")
    if lux is None:
        lux = "luz" in recursos_do_lab()
    app = validar_entradas(pasta, entradas)
    rot = ler_json(codigo / "roteiro.json", {})
    if not isinstance(rot, dict) or not isinstance(rot.get("entradas", []), list):
        raise ValueError('o codigo/roteiro.json é um objeto {"tempo", "entradas": [...], "confere": [...]}')
    extra = (codigo / "gemeo.roteiro").read_text() if (codigo / "gemeo.roteiro").is_file() else ""
    for n, linha in enumerate(extra.splitlines(), 1):
        if re.search(r"\blux\b", linha.split("#")[0], re.I):
            raise ValueError(f'codigo/gemeo.roteiro, linha {n}: a luz vai no roteiro.json ({{"t": 5, "luz": "LDR1", '
                             '"lux": 1}}), que serve ao laboratório novo (em lux) e ao antigo (em volts)')
    if livre:   # só o que veio do app: nem os apertos do gemeo.roteiro nem as entradas do roteiro.json
        rot = {k: v for k, v in rot.items() if k not in ("confere", "entradas")}
        extra = so_o_ambiente(extra)
    usadas = {"apertos": [{**a, "origem": "roteiro"} for a in apertos_do_roteiro(extra)] +
              [{"ref": a["ref"], "de": round(a["de"] * 1000, 3), "ate": round(a["ate"] * 1000, 3), "origem": "app"}
               for a in app["apertos"]],
              "luz": []}   # em ms, como o resto do programa.json
    luzes, outras = [], []
    for n, e in enumerate(rot.get("entradas", []), 1):
        if isinstance(e, dict) and ("luz" in e or "lux" in e):
            onde = f"codigo/roteiro.json, entrada {n}"
            if set(k for k in e if not k.startswith("_")) != {"t", "luz", "lux"} or not numero(e["t"]) or e["t"] < 0:
                raise ValueError(f'{onde}: a luz é {{"t": segundos, "luz": "LDR1", "lux": 1}}')
            luzes.append({"ref": e["luz"], "t": float(e["t"]), "lux": lux_valido(e["lux"], onde), "origem": "roteiro"})
        else:
            outras.append(e)
    luzes += [{**x, "origem": "app"} for x in app["luz"]]
    if luzes and lux:   # o gêmeo põe a luz no LDR do circuito: a ref tem que ser um LDR ligado num GPIO
        modelo = modelo_da_placa(pasta)
        for x in luzes:
            gpio_do_ldr(modelo, x["ref"])
            outras.append({"t": x["t"], "luz": x["ref"], "lux": x["lux"], "_": "o gêmeo põe o LDR do meio no circuito"})
            usadas["luz"].append({"ref": x["ref"], "t": round(x["t"] * 1000, 3), "lux": x["lux"], "volts": None,
                                  "origem": x["origem"]})
    elif luzes:   # o laboratório antigo não conhece a luz: vira a tensão do divisor no pino, pela nossa conta
        modelo = modelo_da_placa(pasta)
        for x in luzes:
            gpio, v = volts_da_luz(modelo, x["ref"], x["lux"])
            outras.append({"t": x["t"], "pino": gpio, "volts": round(v, 4),
                           "_": f"{x['ref']} com {num(x['lux'])} lux, pelo divisor do Sianvolt (LDR do meio)"})
            usadas["luz"].append({"ref": x["ref"], "t": round(x["t"] * 1000, 3), "lux": x["lux"], "volts": round(v, 4),
                                  "origem": x["origem"]})
    rot["entradas"] = outras
    ultimo = max([a["ate"] for a in app["apertos"]] + [x["t"] for x in app["luz"]], default=None)
    if ultimo is not None and (rot["tempo"] if numero(rot.get("tempo")) else TEMPO_DO_LAB) < ultimo + 1:
        rot["tempo"] = round(ultimo + 1, 3)   # o que o app mandou acontece antes do fim da rodada
    extra = extra.rstrip("\n") + "\n" if extra.strip() else ""
    extra += "".join(f"de {num(a['de'])} s a {num(a['ate'])} s aperta {a['ref']}   # do app\n" for a in app["apertos"])

    copia = pasta / "saida" / "programa" / nome_da_copia(pasta, isolada)
    if copia.exists():
        shutil.rmtree(copia)
    copia.mkdir(parents=True)
    for arq in sorted(codigo.glob("*.py")):
        if arq.is_file():
            shutil.copy2(arq, copia / arq.name)
    (copia / "roteiro.json").write_text(json.dumps(rot, ensure_ascii=False, indent=1))
    (copia / "gemeo.roteiro").write_text(extra)
    return copia, usadas


# ---------- 3. o laboratório ----------
def rodar_lab(copia, placa_txt):
    """lab.py rodar esp32 <cópia> --motor gemeo --circuito <placa.txt> --roteiro <cópia>/roteiro.json --json
    -> (linhas do --json, código de saída, problema ou None). Sem o lab.py: código 5. Passou de LIMITE_S: código 3"""
    if not LAB.is_file():
        return [], INDISPONIVEL, "sem o laboratório (falta o laboratorio/lab.py): o programa não roda no papel"
    cmd = [sys.executable, str(LAB), "rodar", LAB_PLACA, str(copia), "--motor", "gemeo", "--circuito", str(placa_txt),
           "--roteiro", str(copia / "roteiro.json"), "--json"]
    try:
        proc = subprocess.Popen(cmd, cwd=RAIZ, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                start_new_session=True)   # o gêmeo abre o MicroPython: no limite, sai o grupo inteiro
    except OSError as e:
        return [], INDISPONIVEL, f"não deu pra abrir o laboratório: {e}"
    try:
        saida, erro = proc.communicate(timeout=LIMITE_S)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        return [], TRAVOU, f"o laboratório passou de {LIMITE_S} s e foi parado"
    linhas = [x for x in saida.splitlines() if x.startswith("{")]
    if proc.returncode < 0:   # parado por um sinal (falta de memória, kill): a rodada não acabou, conta como travou
        return linhas, TRAVOU, f"o laboratório foi parado pelo sistema (sinal {-proc.returncode}) antes de acabar"
    problema = None
    if not any('"tipo": "fim"' in x for x in linhas):   # nem rodou: uso errado ou motor que falta (o lab.py diz)
        problema = (erro.strip() or saida.strip() or f"o lab.py saiu com {proc.returncode} sem dizer nada")[-1500:]
    return linhas, proc.returncode, problema


# ---------- 4. normalizar ----------
LED_APAGADO = re.compile(r"(\w+) apagado$")
LED_ACESO = re.compile(r"(\w+) aceso, ([\d,]+) mA, luz (\d+)% do anúncio$")
LED_MEIA = re.compile(r"(\w+) meia luz, ([\d,]+) mA na média \(([\d,]+) mA quando liga\), luz (\d+)% do anúncio$")
QUEIMA = re.compile(r"(\w+) QUEIMA: passa ([\d,]+) mA")
LDR_COMECA = re.compile(r"(\w+) começa com ([\d,]+) lux \(o LDR do meio: ([^)]+)\)")


def vazio_do_pino():
    return {"quem": None, "nome": None, "modo": [], "nivel": [], "pwm": [], "volts": []}


def led_do_evento(ev):
    """o evento 'led' do gêmeo (o brilho em número: ref, i_med e i_max em A, luz, aceso, queima) -> (ref, luz, mA na
    média, queima), ou None se faltar número. O LED que o gêmeo diz apagado (aceso False: menos de 1% de luz e nunca
    1 mA, a regra do texto) entra com 0 e 0, como o texto 'D1 apagado': o de 35 µA de um pino que ficou como
    entrada com pull-up não 'acende' na etapa 8, e os dois caminhos decidem igual"""
    if not (isinstance(ev.get("ref"), str) and numero(ev.get("luz")) and numero(ev.get("i_med"))
            and isinstance(ev.get("aceso"), bool)):
        return None
    if not ev["aceso"]:
        return ev["ref"], 0.0, 0.0, bool(ev.get("queima"))
    return ev["ref"], float(ev["luz"]), round(ev["i_med"] * 1000, 3), bool(ev.get("queima"))


def led_do_aviso(ev):
    """o aviso 'led' do laboratório antigo (só texto) -> (ref, luz, mA na média, mA quando liga, queima ou None), ou
    None se não entendeu. A luz e a corrente saem arredondadas como no texto (1% e 0,1 mA)"""
    txt = ev.get("texto", "")
    m = LED_APAGADO.match(txt)
    if m:
        return m.group(1), 0.0, 0.0, "0,0", None
    m = LED_ACESO.match(txt)
    if m:
        return m.group(1), int(m.group(3)) / 100, float(m.group(2).replace(",", ".")), m.group(2), None
    m = LED_MEIA.match(txt)
    if m:
        return m.group(1), int(m.group(4)) / 100, float(m.group(2).replace(",", ".")), m.group(3), None
    return None


def linha_do_main(texto):
    """a linha do main.py no traceback do MicroPython (a última que aparece), ou None"""
    achou = re.findall(r'File "main\.py", line (\d+)', texto)
    return int(achou[-1]) if achou else None


def codigo_dos_eventos(fim, falhas, erro):
    """o código que o lab.py daria (contrato.codigo_saida), pra linha do tempo lida sem ele"""
    estado = (fim or {}).get("estado", "travou")
    return {"indisponivel": INDISPONIVEL, "travou": TRAVOU}.get(estado) or (1 if estado == "erro" or erro else
                                                                           4 if falhas else 0)


def janela_da_serial(c):
    """' depois de 5,000 s até 5,500 s' (o 'desde' e o 'ate' da conferência 'serial', como o laboratório escreve)"""
    return ((f" depois de {seg(c['desde'] * 1000)}" if numero(c.get("desde")) else "") +
            (f" até {seg(c['ate'] * 1000)}" if numero(c.get("ate")) else ""))


def descrever(c):
    """uma conferência do roteiro.json em texto, do jeito que o laboratório escreve"""
    if "pwm" in c:
        return f"{c['pwm']} em {seg(c['t'] * 1000)} com duty entre {num(c['duty'][0], 2)} e {num(c['duty'][1], 2)}"
    if "pino" in c:
        return f"{c['pino']} = {c['valor']} em {seg(c['t'] * 1000)}"
    if "serial" in c:
        return f"serial com '{c['serial']}'" + janela_da_serial(c)
    if "trocas" in c:
        return f"trocas de {c['trocas']} entre {c.get('min', 0)} e {c.get('max', '∞')}"
    est = c.get("estado")
    return f"estado {' ou '.join(est) if isinstance(est, list) else est}"


def e_a_falha(c, texto):
    """o texto de falha do laboratório é desta conferência? (ele começa pela descrição dela; o pino pode vir com o
    apelido na frente, 'LED (GPIO23)', então confere o começo e o miolo)"""
    if "pwm" in c and numero(c.get("t")):
        return texto.startswith(str(c["pwm"])) and f" em {seg(c['t'] * 1000)} com duty entre " in texto
    if "pino" in c and numero(c.get("t")):
        return texto.startswith(str(c["pino"])) and f" = {c.get('valor')} em {seg(c['t'] * 1000)}" in texto
    if "serial" in c:
        return texto.startswith(f"serial com '{c['serial']}'{janela_da_serial(c)}:")
    if "trocas" in c:
        return texto.startswith(f"trocas de {c['trocas']}") and f" entre {c.get('min', 0)} e " in texto
    return texto.startswith("estado ")


def do_laboratorio(conf, confere):
    """a linha 'conferencias' do lab.py ({ok: N, falhas: [texto]}) -> ([ok], [falhas]). Ele só manda o texto das
    que falharam (na ordem do roteiro): as que passaram saem da descrição de cada item do roteiro"""
    if not conf:
        return [], []
    falhas, sobra, oks = list(conf.get("falhas") or []), list(conf.get("falhas") or []), []
    for c in confere or []:
        if sobra and isinstance(c, dict) and e_a_falha(c, sobra[0]):
            sobra.pop(0)
        else:
            oks.append(descrever(c) if isinstance(c, dict) else str(c))
    if sobra or len(oks) != conf.get("ok", 0):   # não deu pra casar com o roteiro: fica só a conta
        oks = [f"conferência {i} de {conf.get('ok', 0)} do roteiro.json" for i in range(1, conf.get("ok", 0) + 1)]
    return oks, falhas


def normalizar(linhas, pasta, codigo=None, livre=False, entradas=None, confere=None):
    """a linha do tempo do lab.py (as linhas do --json, texto ou dict) -> o programa.json:
    {placa, quando, livre, codigo, tempo_ms, pinos: {GPIOn: {quem, nome, modo: [[t, m]], nivel: [[t, v]],
     pwm: [[t, duty, freq]], volts: [[t, v]]}}, leds: {REF: [[t, luz, i_mA, queima]]}, serial: [[t, texto]],
     avisos: [[t, codigo, texto]], erro: None | {t, texto, linha}, conferencias: {ok: [...], falhas: [...]},
     entradas: {apertos: [{ref, de, ate, origem}], luz: [{ref, t, lux, volts, origem}]}, pendentes: [...]}
    Tempos em ms. 'quem' e 'nome' saem do NOSSO placa.txt e do projeto.json (o 'nome' dos eventos é apelido
    do laboratório). A luz do LED é a fração do brilho do anúncio; i_mA é a corrente média (no PWM, a média): do
    evento 'led' (os números do gêmeo; o LED que ele diz apagado vai com 0 e 0) ou, num laboratório antigo, do
    texto do aviso 'led' (1% e 0,1 mA). A luz que o preparar mandou em lux chega aqui com volts None: os volts são
    os do gêmeo (o evento 'adc' com origem 'circuito' no pino do LDR), ou None se a rodada parou antes.
    codigo: o do lab.py (None = o que ele daria por esta linha do tempo). confere: a lista do roteiro.json"""
    pasta = Path(pasta)
    eventos = []
    for x in linhas:
        try:
            eventos.append(json.loads(x) if isinstance(x, str) else dict(x))
        except ValueError:
            continue   # linha que não é evento (o lab.py só escreve evento no stdout)
    try:
        modelo = modelo_da_placa(pasta)
    except (OSError, ValueError):
        modelo = None
    try:
        proj = blocos.ler_projeto(pasta)
    except ValueError:
        proj = None
    prog = {"placa": pasta.name, "quando": datetime.now().isoformat(timespec="seconds"), "livre": livre,
            "codigo": codigo, "tempo_ms": 0.0, "pinos": {}, "leds": {}, "serial": [], "avisos": [], "erro": None,
            "conferencias": {"ok": [], "falhas": []}, "pendentes": [],
            "entradas": {k: [dict(x) for x in v] for k, v in (entradas or {"apertos": [], "luz": []}).items()}}

    def pino(nome):
        return prog["pinos"].setdefault(nome, vazio_do_pino())

    queimou, fim, conf = set(), None, None   # queimou: (ref, mA quando liga); o gêmeo avisa cada texto uma vez só
    numerico = any(ev.get("tipo") == "led" for ev in eventos)   # o laboratório manda o brilho em número
    do_circuito = []   # (t, GPIO, volts): o que o circuito pôs no pino quando a luz do LDR mudou
    # a luz foi em lux: o preparar não fez a conta dos volts (None), mesmo se nenhuma luz coube na rodada
    em_lux = any(x.get("volts") is None for x in prog["entradas"].get("luz", []))
    pecas = {p["ref"]: p for p in modelo["pecas"]} if modelo else {}
    for ev in eventos:
        t, tipo = ev.get("t_ms", 0.0), ev.get("tipo")
        if tipo == "led":
            led = led_do_evento(ev)
            if led is None:   # sem os números (ou sem o aceso): o texto de sempre, como no laboratório antigo
                velho = led_do_aviso(ev)
                led = velho and (*velho[:3], bool(ev.get("queima")))
            if not led:
                prog["avisos"].append([t, "led", ev.get("texto", "")])   # sem os números: o texto não some
                continue
            linha = prog["leds"].setdefault(led[0], [])
            if not linha or linha[-1][1:] != list(led[1:]):   # o apagado de 35 µA repete o 0 e 0: fica um só
                linha.append([t, *led[1:]])
        elif tipo == "modo":
            pino(ev["pino"])["modo"].append([t, ev["modo"]])
        elif tipo == "pino":
            pino(ev["pino"])["nivel"].append([t, ev["valor"]])
        elif tipo == "pwm":
            pino(ev["pino"])["pwm"].append([t, ev["duty"], ev.get("freq_hz")])
        elif tipo == "adc":
            pino(ev["pino"])["volts"].append([t, ev["volts"]])
            if ev.get("origem") == "circuito":   # a tensão que o circuito pôs no pino quando a luz do LDR mudou
                do_circuito.append((t, ev["pino"], ev["volts"]))
        elif tipo == "serial" and ev.get("dir") == "tx":
            prog["serial"].append([t, ev["texto"]])
        elif tipo == "aviso":
            if ev.get("codigo") == "led" and numerico:   # o mesmo brilho já veio em número no evento 'led'
                continue
            led = led_do_aviso(ev) if ev.get("codigo") == "led" else None
            if led:
                ref, luz, i, i_liga, queima = led
                prog["leds"].setdefault(ref, []).append([t, luz, i, bool(queima) or (ref, i_liga) in queimou])
                continue
            m = QUEIMA.match(ev.get("texto", "")) if ev.get("codigo") == "queima" else None
            if m:
                queimou.add(m.groups())
                ultimo = (prog["leds"].get(m.group(1)) or [None])[-1]
                if ultimo and abs(ultimo[0] - t) <= FOLGA_T:
                    ultimo[3] = True
            texto = ev.get("texto", "")
            m = LDR_COMECA.match(texto) if ev.get("codigo") == "luz" else None
            if m:   # a dica do laboratório é a do roteiro dele: aqui a luz muda pelo app ou pelo roteiro.json
                nome = f" ({nome_de_gente(proj, pecas[m[1]])})" if m[1] in pecas else ""
                texto = (f"{m[1]}{nome} começa com {m[2]} lux (o LDR do meio: {m[3]}) e fica assim até " +
                         ("o app mudar a luz dele" if livre else "uma luz do codigo/roteiro.json mudar"))
            prog["avisos"].append([t, ev.get("codigo"), texto])
        elif tipo == "erro" and prog["erro"] is None:
            prog["erro"] = {"t": t, "texto": ev["texto"], "linha": linha_do_main(ev["texto"])}
        elif tipo == "fim":
            fim, prog["tempo_ms"] = ev, ev.get("tempo_placa_ms", t)
        elif tipo == "conferencias":
            conf = ev

    if modelo is not None:
        for gpio, lista in nos_gpios(modelo).items():
            p = pino(gpio)
            refs = list(dict.fromkeys(ref for ref, _, _ in lista))
            p["quem"] = ", ".join(refs)
            p["nome"] = " e ".join(nome_de_gente(proj, pecas[r]) for r in refs)
        u = mcu_da(modelo)
        prog["pendentes"] += [f"{u['ref']}: {x}" for x in (u["eletrica"].get("pendentes") or [])] if u else []
        prog["pendentes"] += [f"{p['ref']}: o datasheet não tem a curva de brilho; a luz é a corrente ÷ a corrente de "
                              "teste (uma reta)" for p in modelo["pecas"]
                              if modelo_de(p) == "led" and p["ref"] in prog["leds"] and not p["eletrica"].get("brilho")]
    gpios_de = {ref: [g for g, _, _ in ligs] for ref, ligs in por_peca(modelo).items()} if modelo else {}
    for x in prog["entradas"].get("luz", []):
        if x.get("volts") is None:   # a luz foi em lux: os volts são os que o gêmeo viu no pino do LDR naquela hora
            achou = [v for tl, p, v in do_circuito if abs(tl - x["t"]) <= FOLGA_T and p in gpios_de.get(x["ref"], [p])]
            x["volts"] = achou[-1] if achou else None
    if prog["entradas"].get("luz") and em_lux:   # pelo que o preparar mandou, e não pelo que coube na rodada
        prog["pendentes"].append("a luz do quarto entra em lux no LDR, com o LDR do meio do datasheet: cada LDR de "
                                 "verdade sai de um jeito, então os limites do main.py se calibram no quarto")
    elif prog["entradas"].get("luz"):
        prog["pendentes"].append("a luz do quarto entra como volts no pino do LDR, pela nossa conta (o LDR do meio, com "
                                 "os outros pinos soltos): este laboratório não recebe lux, então o que o programa liga "
                                 "nos pinos não muda essa tensão")
    prog["pinos"] = dict(sorted(prog["pinos"].items(), key=lambda x: ordem(x[0])))
    ok, falhas = do_laboratorio(conf, confere)
    prog["conferencias"] = {"ok": ok, "falhas": falhas}
    if prog["codigo"] is None:
        prog["codigo"] = codigo_dos_eventos(fim, falhas, prog["erro"])
    return prog


# ---------- 5. conferir (codigo/confere.json) ----------
def lista(refs):
    return ", ".join(sorted(refs, key=ordem))


def no_instante(linha, t):
    """o último [t, ...] da linha do tempo até t (no mesmo instante, vale o que veio por último), ou None"""
    antes = [x for x in linha if x[0] <= t + FOLGA_T]
    return antes[-1] if antes else None


def aceso(prog, ref, t):
    x = no_instante(prog["leds"].get(ref, []), t)
    return bool(x) and (x[1] > 0 or x[2] > 0)


def instantes(prog, evento):
    """'GPIO25 sobe' -> os ms em que o pino foi pra 1 (ele começa em 0, como no laboratório); 'desce', pra 0"""
    gpio, lado = EVENTO.match(evento).groups()
    quer, antes, achou = (1 if lado == "sobe" else 0), 0, []
    for t, v in prog["pinos"].get(gpio, vazio_do_pino())["nivel"]:
        if v == quer and antes != quer:
            achou.append(t)
        antes = v
    return achou


def _leds_da_serial(prog, c):
    rx, todos = re.compile(c["regex"]), sorted({r for refs in c["mapa"].values() for r in refs}, key=ordem)
    quer_txt = f"os LEDs acesos são a face que a serial diz ('{c['regex']}')"
    sem = [r for r in todos if r not in prog["leds"]]
    if sem:
        return False, f"{quer_txt}: {lista(sem)} não aparece no programa (o gêmeo não viu esse LED no circuito)"
    linhas = [(t, txt, m) for t, txt in prog["serial"] for m in [rx.search(txt)] if m]
    if not linhas:
        return False, f"{quer_txt}: a serial nunca escreveu isso"
    for t, txt, m in linhas:
        face = m.group(c.get("grupo", 1))
        if face not in c["mapa"]:
            return False, f"{quer_txt}: em {seg(t)} a serial disse '{txt}', e a face '{face}' não está no mapa"
        acesos, quer = {r for r in todos if aceso(prog, r, t)}, set(c["mapa"][face])
        if acesos != quer:
            return False, (f"{quer_txt}: em {seg(t)} a serial disse '{txt}' e os acesos são {lista(acesos) or 'nenhum'} "
                           f"(a face {face} é {lista(quer) or 'nenhum'})")
    return True, f"{quer_txt}: bateu em {len(linhas)} de {len(linhas)} linhas"


def _pwm_freq(prog, c):
    pwm, d = prog["pinos"].get(c["pino"], vazio_do_pino())["pwm"], c.get("depois_de")
    quer_txt = f"{c['pino']} em {num(c['hz'])} Hz (± {num(c['folga'])})"
    if isinstance(d, str):
        quer_txt += f" depois de cada '{d}'"
        ts = instantes(prog, d)
        if not ts:
            return False, f"{quer_txt}: o {d.split()[0]} nunca {'subiu' if d.endswith('sobe') else 'desceu'}"
    else:
        ts = [0.0 if d is None else d * 1000]
        quer_txt += f" desde {seg(ts[0])}" if d else ""
    for ti in ts:
        agora = no_instante(pwm, ti)
        ligado = agora if agora and agora[1] > 0 else next((x for x in pwm if x[0] >= ti - FOLGA_T and x[1] > 0), None)
        if ligado is None:
            return False, f"{quer_txt}: depois de {seg(ti)} o PWM não ligou"
        if not numero(ligado[2]) or abs(ligado[2] - c["hz"]) > c["folga"]:
            return False, f"{quer_txt}: em {seg(ligado[0])} ligou em {num(ligado[2]) if numero(ligado[2]) else '?'} Hz"
    return True, f"{quer_txt}: viu {len(ts)} vez{'es' if len(ts) > 1 else ''}"


def _serial_menos_evento(prog, c):
    rx, ts = re.compile(c["regex_ms"]), instantes(prog, c["evento"])
    quer_txt = f"o tempo da serial ('{c['regex_ms']}') = a linha − o '{c['evento']}' (± {num(c['folga_ms'])} ms)"
    linhas = [(t, txt, m) for t, txt in prog["serial"] for m in [rx.search(txt)] if m]
    if not linhas:
        return False, f"{quer_txt}: a serial nunca escreveu isso"
    for t, txt, m in linhas:
        antes = [x for x in ts if x <= t + FOLGA_T]
        if not antes:
            return False, f"{quer_txt}: '{txt}' saiu em {seg(t)}, sem nenhum '{c['evento']}' antes"
        try:
            disse, real = float(m.group(1).replace(",", ".")), t - antes[-1]
        except ValueError:
            return False, f"{quer_txt}: em '{txt}' o grupo da regex não é um número"
        if abs(disse - real) > c["folga_ms"]:
            return False, (f"{quer_txt}: '{txt}' em {seg(t)}: a serial diz {num(disse)} ms e o relógio da placa, "
                           f"{num(real, 1)} ms (o '{c['evento']}' foi em {seg(antes[-1])})")
    return True, f"{quer_txt}: bateu em {len(linhas)} de {len(linhas)} linhas"


def _duty_entre(prog, c):
    p = prog["pinos"].get(c["pino"], vazio_do_pino())
    de, ate = c["de_t"] * 1000, c["ate_t"] * 1000
    quer_txt = f"{c['pino']} de {seg(de)} a {seg(ate)} com duty entre {num(c['min'], 2)} e {num(c['max'], 2)}"
    if ate > prog["tempo_ms"] + FOLGA_T:
        return False, f"{quer_txt}: não deu pra ver, a rodada parou em {seg(prog['tempo_ms'])} (aumente o tempo do roteiro)"
    linha = sorted([[t, float(v)] for t, v in p["nivel"]] + [[t, float(d)] for t, d, _ in p["pwm"]], key=lambda x: x[0])
    inicio = no_instante(linha, de)
    vistos = ([[de, inicio[1]]] if inicio else []) + [x for x in linha if de + FOLGA_T < x[0] <= ate + FOLGA_T]
    if not vistos:
        return False, f"{quer_txt}: o pino nunca mexeu até {seg(ate)}"
    fora = next((x for x in vistos if not c["min"] - 1e-9 <= x[1] <= c["max"] + 1e-9), None)
    if fora:
        return False, f"{quer_txt}: em {seg(fora[0])} o duty era {num(fora[1], 4)}"
    duties = [x[1] for x in vistos]
    return True, f"{quer_txt}: viu de {num(min(duties), 4)} a {num(max(duties), 4)}"


# tipo -> (função, campos que precisa, campos opcionais)
TIPOS = {"leds_da_serial": (_leds_da_serial, {"regex", "mapa"}, {"grupo"}),
         "pwm_freq": (_pwm_freq, {"pino", "hz", "folga"}, {"depois_de"}),
         "serial_menos_evento": (_serial_menos_evento, {"regex_ms", "evento", "folga_ms"}, set()),
         "duty_entre": (_duty_entre, {"pino", "de_t", "ate_t", "min", "max"}, set())}


def validar_confere(dados):
    """o codigo/confere.json ({"confere": [...]} ou só a lista) -> a lista conferida, ou ValueError numa frase.
    Chave de cima errada ou a mais não passa calada como zero conferências"""
    if isinstance(dados, dict) and {k for k in dados if not k.startswith("_")} != {"confere"}:
        raise ValueError('o confere.json é {"confere": [...]}, e só isso (fora as chaves de comentário, com "_")')
    itens = dados["confere"] if isinstance(dados, dict) else dados
    if not isinstance(itens, list):
        raise ValueError('o confere.json é {"confere": [...]}')
    for n, c in enumerate(itens, 1):
        onde = f"confere {n}"
        if not isinstance(c, dict) or c.get("tipo") not in TIPOS:
            raise ValueError(f"{onde}: o tipo é um de {', '.join(TIPOS)}")
        _, precisa, pode = TIPOS[c["tipo"]]
        campos = {k for k in c if not k.startswith("_")} - {"tipo"}
        if precisa - campos or campos - precisa - pode:
            raise ValueError(f"{onde} ({c['tipo']}): precisa de {', '.join(sorted(precisa))}"
                             + (f" (e pode ter {', '.join(sorted(pode))})" if pode else ""))

        def regex(k, grupos=1):
            try:
                rx = re.compile(c[k])
            except (re.error, TypeError) as e:
                raise ValueError(f"{onde}: {k} não é uma expressão regular ({e})") from None
            if rx.groups < grupos:
                raise ValueError(f"{onde}: {k} precisa de um grupo entre parênteses, como 'deu (\\d)'")

        def positivo(k, zero=True):
            if not numero(c[k]) or c[k] < 0 or (not zero and c[k] == 0):
                raise ValueError(f"{onde}: {k} é um número{' maior que 0' if not zero else ' de 0 pra cima'}")

        def pino(k):
            if not isinstance(c[k], str) or not GPIO.match(c[k]):
                raise ValueError(f"{onde}: {k} é um GPIO, como 'GPIO25'")

        def evento(k):
            if not isinstance(c[k], str) or not EVENTO.match(c[k]):
                raise ValueError(f"{onde}: {k} é 'GPIOn sobe' ou 'GPIOn desce'")

        if c["tipo"] == "leds_da_serial":
            g = c.get("grupo", 1)
            if not isinstance(g, int) or isinstance(g, bool) or g < 0:
                raise ValueError(f"{onde}: grupo é o número do grupo da regex (1 = o primeiro parêntese)")
            regex("regex", g)
            mapa = c["mapa"]
            if not isinstance(mapa, dict) or not mapa or not all(
                    isinstance(v, list) and all(isinstance(r, str) for r in v) for v in mapa.values()):
                raise ValueError(f'{onde}: mapa é {{"face": ["D1", ...]}}')
        elif c["tipo"] == "pwm_freq":
            pino("pino")
            positivo("hz", zero=False)
            positivo("folga")
            if "depois_de" in c and not numero(c["depois_de"]):
                evento("depois_de")
            elif "depois_de" in c:
                positivo("depois_de")
        elif c["tipo"] == "serial_menos_evento":
            regex("regex_ms")
            evento("evento")
            positivo("folga_ms")
        else:
            pino("pino")
            for k in ("de_t", "ate_t", "min", "max"):
                positivo(k)
            if c["ate_t"] < c["de_t"] or c["max"] < c["min"] or c["max"] > 1:
                raise ValueError(f"{onde}: de_t ≤ ate_t (s) e 0 ≤ min ≤ max ≤ 1")
    return itens


def conferir(prog, confere):
    """o codigo/confere.json em cima do programa.json -> {"ok": [texto], "falhas": [texto]}, um texto por item.
    confere.json errado: ValueError (o rodar põe a frase nas falhas)"""
    saida = {"ok": [], "falhas": []}
    for c in validar_confere(confere):
        bom, texto = TIPOS[c["tipo"]][0](prog, c)
        saida["ok" if bom else "falhas"].append(texto)
    return saida


# ---------- 6. gravar, a trava e a rodada ----------
def arquivo(pasta, livre):
    return Path(pasta) / "saida" / ("programa_livre.json" if livre else "programa.json")


def gravar(pasta, prog):
    """saida/programa.json (ou programa_livre.json) de uma vez: a bancada nunca lê arquivo pela metade"""
    arq = arquivo(pasta, prog["livre"])
    arq.parent.mkdir(parents=True, exist_ok=True)
    tmp = arq.with_name(arq.name + ".tmp")
    tmp.write_text(json.dumps(prog, ensure_ascii=False))
    tmp.replace(arq)
    return arq


_SEGURAS = set()   # (thread, trava) que este processo já tem: a etapa 8 pode chamar o rodar segurando a dela
_OLHANDO = threading.Lock()   # o app olha de várias threads: uma de cada vez, senão uma vê a espiada da outra


@contextlib.contextmanager
def trava(pasta, esperar=True, tentativas=5):
    """flock em saida/.rodando: uma rodada do programa por placa (o app, a etapa 8 e um terminal). Sai sozinha
    quando o processo acaba, até com kill -9. A mesma thread pode pegar de novo; outra thread espera como outro
    processo. esperar=False: o 'with' recebe None se outro tem a trava (tenta algumas vezes em 0,2 s, porque o
    ocupada() pega a trava por um instante só pra olhar)"""
    arq = (Path(pasta) / "saida" / ".rodando").resolve()
    chave = (threading.get_ident(), arq)
    if chave in _SEGURAS:
        yield True
        return
    arq.parent.mkdir(parents=True, exist_ok=True)
    f = open(arq, "a")
    try:
        vezes = 1 if esperar else tentativas
        for n in range(vezes):
            try:
                fcntl.flock(f, fcntl.LOCK_EX | (0 if esperar else fcntl.LOCK_NB))
                break
            except BlockingIOError:
                if n < vezes - 1:
                    time.sleep(0.05)
                    continue
                f.close()
                f = None
        if f is not None:
            _SEGURAS.add(chave)
        yield f
    finally:
        if f is not None:
            _SEGURAS.discard(chave)
            f.close()


def ocupada(pasta):
    """alguém (outro processo ou outra thread) está rodando o programa desta placa agora? Se a trava está presa,
    olha de novo em 50 ms: a espiada de outro processo dura um instante, uma rodada dura segundos"""
    if not (Path(pasta) / "saida" / ".rodando").exists():
        return False
    with _OLHANDO, trava(pasta, esperar=False, tentativas=2) as t:
        return t is None


def vazio(pasta, livre, codigo, texto):
    """o programa.json de uma rodada que nem chegou no laboratório (placa, roteiro ou entradas com erro)"""
    prog = normalizar([], pasta, codigo, livre)
    prog["erro"] = {"t": 0.0, "texto": texto, "linha": None}
    return prog


def rodar(pasta, entradas=None, livre=False, isolada=False, esperar=True):
    """roda o programa da placa no gêmeo e grava o saida/programa.json (livre: programa_livre.json, sem as
    conferências); devolve o mesmo dict. Fora do roteiro de teste, o confere.json não entra.
    O codigo é o do lab.py: 0 ok; 5 sem o laboratório (com um aviso 'indisponivel': quem testa pula). Qualquer
    outro é falha: 1 erro no programa, 2 nem chegou no laboratório (placa, roteiro.json, gemeo.roteiro ou
    entradas com erro, que vira o 'erro' do arquivo), 3 travou (passou de LIMITE_S ou o sistema parou o lab.py),
    4 conferência do roteiro falhou. As falhas do confere.json (e o confere.json errado) ficam só em
    conferencias.falhas.
    isolada: a cópia ganha o pid no nome e é apagada no fim. Outra rodada na placa: espera (esperar=False: Ocupada)"""
    pasta = Path(pasta).resolve()
    with trava(pasta, esperar) as t:
        if t is None:
            raise Ocupada(f"o programa da placa {pasta.name} já está rodando")
        copia = None
        try:
            pinos(pasta)
            copia, usadas = preparar(pasta, entradas, livre, isolada)
            linhas, codigo, problema = rodar_lab(copia, pasta / "placa.txt")
            rot = json.loads((copia / "roteiro.json").read_text())
            prog = normalizar(linhas, pasta, codigo, livre, usadas, rot.get("confere"))
            if problema and codigo == INDISPONIVEL:
                prog["avisos"].append([0.0, "indisponivel", problema])
            elif problema and prog["erro"] is None:
                prog["erro"] = {"t": prog["tempo_ms"], "texto": problema, "linha": None}
            if not livre and codigo != INDISPONIVEL and (pasta / "codigo" / "confere.json").is_file():
                try:   # confere.json errado vira uma falha: a linha do tempo continua valendo
                    feito = conferir(prog, ler_json(pasta / "codigo" / "confere.json", None))
                except ValueError as e:
                    feito = {"ok": [], "falhas": [f"codigo/confere.json: {e}"]}
                prog["conferencias"]["ok"] += feito["ok"]
                prog["conferencias"]["falhas"] += feito["falhas"]
        except ValueError as e:
            prog = vazio(pasta, livre, USO, str(e))
        except Exception as e:   # defeito do programa.py: o app ainda vê o que aconteceu, em vez do arquivo antigo
            prog = vazio(pasta, livre, USO, f"erro inesperado no programa.py: {type(e).__name__}: {e}")
        finally:
            if isolada and copia is not None:   # a cópia e a vaga que o lab.py abriu pra ela (nome que não volta)
                shutil.rmtree(copia, ignore_errors=True)
                apagar_vaga(copia.name)
        gravar(pasta, prog)
    return prog


if __name__ == "__main__":
    args = sys.argv[1:]
    entradas = None
    if "--entradas" in args:
        i = args.index("--entradas")
        try:
            entradas = json.loads(args[i + 1])
        except (IndexError, ValueError):
            sys.exit('--entradas espera um JSON: {"apertos": [...], "luz": [...]}')
        del args[i:i + 2]
    pastas = [a for a in args if not a.startswith("--")]
    if len(pastas) != 1:
        sys.exit("\n\n".join(__doc__.split("\n\n")[:2]))
    pasta = Path(pastas[0])
    if "--pinos" in args:
        try:
            for nome, gpio in pinos(pasta).items():
                print(f"{nome} = {gpio}")
        except (OSError, ValueError) as e:
            sys.exit(str(e))
        sys.exit()
    prog = rodar(pasta, entradas, livre="--livre" in args)
    c = prog["conferencias"]
    print(f"{prog['placa']}: código {prog['codigo']}, {seg(prog['tempo_ms'])} de placa, {len(prog['serial'])} linhas na "
          f"serial, {len(c['ok'])} conferências ok e {len(c['falhas'])} falharam -> {arquivo(pasta, prog['livre'])}")
    for f in c["falhas"]:
        print(f"  ✗ {f}")
    if prog["erro"]:
        print(f"  erro{' na linha %d do main.py' % prog['erro']['linha'] if prog['erro']['linha'] else ''}: "
              f"{prog['erro']['texto'].splitlines()[-1]}")
    sys.exit(prog["codigo"] or 0)
