"""circuito.py: liga o circuito no papel. Corrente contínua, com pilha, resistor, LED, chave, LDR, piezo e capacitor.

O mesmo modelo existe em JS na bancada (simular, comPinos, ohmsDoLdr e divisorDoLdr), pro painel responder
na hora. Mudou aqui, muda lá (testes/test_paridade_js.py confere).
- resistor: I = V / R
- LED aceso: V = joelho + r_s · I (joelho = vf − r_s · i_teste, do datasheet); abaixo do joelho não passa nada.
  O + e o − vêm da peça (mais/menos); sem isso, 1 é o + e 2 o −
- chave: apertada vira fio; solta, fica aberta
- pilha: fonte de tensão com a resistência interna em série (r_interna, do gráfico do datasheet); sem ela,
  uma resistência bem pequena (R_PILHA), só pra conta fechar com duas pilhas em paralelo
- LDR: resistor que muda com a luz (ohms_do_ldr); sem ajuste, fica com a luz de LUX_PADRAO
- piezo: aberto (em corrente contínua ele é um capacitor); ajustado como fio, é a borda do apito
- capacitor: aberto (corrente contínua não passa)
- pino sem net = circuito aberto
- peça mcu (o ESP32) e modelo desconhecido: o resolver não liga. Quem liga os pinos é o com_pinos, que põe
  "pilhas de mentira" no lugar do chip (a mesma ideia do gêmeo do laboratório)

A conta é análise nodal: uma incógnita por net (tensão). Fonte com resistência em série entra como
condutância + corrente injetada (Norton), então a matriz nunca fica sem solução.
"""
import re

GMIN = 1e-9      # condutância mínima de cada net pro terra, só pra net solta não travar a conta
R_CHAVE = 1e-3   # chave apertada = resistor bem pequeno
R_PILHA = 1e-3   # ver docstring


def joelho(e):
    return e["vf"] - e["r_s"] * e["i_teste"]


def polos(e):
    """(+, −) da peca: LED e pilha"""
    return e.get("mais", "1"), e.get("menos", "2")


def r_pilha(e):
    return e.get("r_interna") or R_PILHA


def _positivo(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0


# o nome de gente de cada número da eletrica, pras frases de pendente (o Luiz lê na etapa 4 e no painel)
NOME_DO_CAMPO = {"vdd": "a tensão do 3V3", "r_3v3": "a resistência do 3V3", "r_pino": "a resistência do pino",
                 "r_pull": "o pull-up de dentro", "r_escuro": "a resistência no escuro",
                 "r10_min": "a resistência mínima em 10 lux", "r10_max": "a resistência máxima em 10 lux",
                 "gama": "quanto a resistência cai com a luz (gama)"}


def _da_eletrica(e, campo, quem):
    """número da eletrica que a conta precisa; pendente (sem número) recusa, em vez de inventar um"""
    if not _positivo(e.get(campo)):
        raise ValueError(f"{quem}: falta conferir {NOME_DO_CAMPO[campo]} no datasheet")
    return e[campo]


# LDR: R(lux) = r10 · (lux / 10)^(−gama). O datasheet dá a faixa do r10 (resistência a 10 lux) e o gama ± gama_tol;
# no escuro (e nunca acima disso) vale o r_escuro
LUX_PADRAO = 10   # sem ajuste, o LDR fica em 10 lux, o ponto da tabela do datasheet (r10)


def ohms_do_ldr(e, lux, canto="meio", quem="LDR"):
    """resistência do LDR nessa luz. canto: 'meio' (média geométrica da faixa do r10, gama do datasheet),
    'min' ou 'max' (o r10 e o gama ± gama_tol que dão a menor ou a maior resistência). lux 0 ou None = escuro.
    quem: a ref, pras frases de erro. Canto ou lux que não existem recusam sempre, até no escuro"""
    if canto not in ("meio", "min", "max"):
        raise ValueError(f"canto {canto!r} não existe ('meio', 'min' ou 'max')")
    if lux is not None and not (isinstance(lux, (int, float)) and not isinstance(lux, bool) and lux >= 0):
        raise ValueError(f"{quem}: {lux!r} lux não existe (a luz é um número de 0 pra cima; 0 é o escuro)")
    escuro = _da_eletrica(e, "r_escuro", quem)
    if not lux:
        return escuro
    g, tol = _da_eletrica(e, "gama", quem), e.get("gama_tol") or 0
    r10_min, r10_max = _da_eletrica(e, "r10_min", quem), _da_eletrica(e, "r10_max", quem)
    if canto == "meio":
        r = (r10_min * r10_max) ** 0.5 * (lux / 10) ** -g
    elif canto == "min":
        r = min(r10_min * (lux / 10) ** -(g - tol), r10_min * (lux / 10) ** -(g + tol))
    else:
        r = max(r10_max * (lux / 10) ** -(g - tol), r10_max * (lux / 10) ** -(g + tol))
    return min(r, escuro)


def divisor_do_ldr(e, r_fixo, vdd, lux, canto="meio", quem="LDR"):
    """volts no pino do divisor vdd → r_fixo → pino → LDR → GND (no escuro, a tensão sobe).
    O pino do ADC não puxa corrente: é a conta do divisor, sem o resto do circuito"""
    r = ohms_do_ldr(e, lux, canto, quem)
    return vdd * r / (r_fixo + r)


def _fonte(ref, mais, menos, volts, ohms):
    """pilha de mentira: volts com ohms em série (a mesma forma do _fonte do gêmeo, laboratorio/.../eletrica.py)"""
    return {"ref": ref, "eletrica": {"modelo": "pilha", "mais": "1", "menos": "2", "v": volts, "r_interna": ohms},
            "pinos": [{"n": "1", "net": mais}, {"n": "2", "net": menos}]}


def com_pinos(modelo, estado, vdd=None):
    """o modelo com o ESP32 trocado por pilhas de mentira, pro resolver:
    ~terra (primeira: o GND do chip vira o terra da conta), ~3V3 (vdd com o r_3v3 da eletrica) e um ~GPIOn por pino.
    estado: {"GPIO32": 1 | 0 | "pullup" | None}. 1 = vdd com r_pino em série; 0 = 0 V com r_pino;
    "pullup" = vdd com r_pull (o pull-up de dentro); None ou fora do estado = solto. Só GPIOn entra no estado.
    vdd: a tensão do 3V3 (None = a da eletrica). O VIN não entra: os 5 V dele seriam suposição.
    Número pendente na eletrica (vdd; r_3v3 com o 3V3 ligado; r_pino e r_pull quando o estado pede) recusa com
    ValueError, numa frase de gente. True e False valem 1 e 0. Sem peça mcu, devolve o modelo como está."""
    mcu = next((p for p in modelo["pecas"] if (p.get("eletrica") or {}).get("modelo") == "mcu"), None)
    if mcu is None:
        return modelo
    e, ref = mcu["eletrica"], mcu["ref"]
    vdd = _da_eletrica(e, "vdd", ref) if vdd is None else vdd
    if not _positivo(vdd):
        raise ValueError(f"{ref}: {vdd!r} não serve como tensão do 3V3 (é um número em volts)")
    net = {q["nome"]: q["net"] for q in mcu["pinos"] if q["net"] and q.get("nome")}
    gnds = sorted(q["net"] for q in mcu["pinos"] if q["net"] and q.get("nome") == "GND")
    gnd = gnds[0] if gnds else "GND"
    virt = [_fonte("~terra", gnd, gnd, 0.0, 1e9)]
    if "3V3" in net:
        virt.append(_fonte("~3V3", net["3V3"], gnd, vdd, _da_eletrica(e, "r_3v3", ref)))
    for nome, nivel in estado.items():
        if not re.fullmatch(r"GPIO[0-9]+", nome):
            raise ValueError(f"{nome}: só pino GPIO entra no estado (o 3V3 e o GND entram sozinhos; o VIN não é modelado)")
        if nivel == "pullup":
            volts, ohms = vdd, _da_eletrica(e, "r_pull", ref)
        elif nivel in (0, 1):
            volts, ohms = vdd * nivel, _da_eletrica(e, "r_pino", ref)
        elif nivel is None:
            continue
        else:
            raise ValueError(f"{nome}: o estado {nivel!r} não existe (o pino fica em 1, 0, 'pullup' ou solto)")
        if nome in net:
            virt.append(_fonte("~" + nome, net[nome], gnd, volts, ohms))
    return {**modelo, "pecas": virt + modelo["pecas"]}


def resolver_linear(A, b):
    """Gauss com pivô; A quadrada, b vetor"""
    n = len(b)
    M = [linha[:] + [b[i]] for i, linha in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda i: abs(M[i][c]))
        M[c], M[p] = M[p], M[c]
        if abs(M[c][c]) < 1e-18:
            raise ZeroDivisionError("circuito sem solução")
        for i in range(n):
            if i != c and M[i][c]:
                f = M[i][c] / M[c][c]
                M[i] = [x - f * y for x, y in zip(M[i], M[c])]
    return [M[i][n] / M[i][i] for i in range(n)]


def resolver(modelo, ajustes=None):
    """ajustes: {"pilha": {ref: volts}, "resistor": {ref: ohms}, "chave": {ref: True = apertada},
                 "ldr": {ref: ohms}, "piezo": {ref: True = fio}}
    devolve {"nets": {net: V}, "pecas": {ref: {...}}, "entra": {"REF.N": corrente que entra pelo pino}}
    ou None quando não tem pilha (com ESP32, chame com com_pinos(modelo, estado))."""
    aj = {"pilha": {}, "resistor": {}, "chave": {}, "ldr": {}, "piezo": {}, **(ajustes or {})}
    pecas = [p for p in modelo["pecas"] if p.get("eletrica")]
    net_de = {(p["ref"], q["n"]): q["net"] for p in modelo["pecas"] for q in p["pinos"]}
    pilhas = [p for p in pecas if p["eletrica"]["modelo"] == "pilha"]
    if not pilhas:
        return None
    terra = net_de[(pilhas[0]["ref"], pilhas[0]["eletrica"]["menos"])]
    nets = sorted({n for n in net_de.values() if n and n != terra})
    idx = {n: i for i, n in enumerate(nets)}

    def net(ref, n):
        return net_de[(ref, n)]

    def tensao(v, a, b):
        return v[a] - v[b] if a is not None and b is not None else None

    def ohms(p):   # resistor ou LDR
        if p["eletrica"]["modelo"] == "resistor":
            return aj["resistor"].get(p["ref"], p["valor"])
        o = aj["ldr"].get(p["ref"])
        if o is None:
            return ohms_do_ldr(p["eletrica"], LUX_PADRAO, quem=p["ref"])
        if not _positivo(o):
            raise ValueError(f"{p['ref']}: LDR com {o!r} Ω não existe (o ajuste do LDR é em ohms, maior que 0)")
        return o

    acesos = {p["ref"]: True for p in pecas if p["eletrica"]["modelo"] == "led"}
    v = {}
    for _ in range(30):
        N = len(nets)
        A = [[0.0] * N for _ in range(N)]
        b = [0.0] * N
        for i in range(N):
            A[i][i] += GMIN

        def condutancia(na, nb, g):
            if na is None or nb is None:   # pino sem net: aberto
                return
            for x, outro in ((na, nb), (nb, na)):
                if x == terra:
                    continue
                A[idx[x]][idx[x]] += g
                if outro != terra:
                    A[idx[x]][idx[outro]] -= g

        def fonte(na, nb, volts, r):   # fonte de tensão com r em série, + em na: Norton
            if na is None or nb is None:
                return
            g = 1 / r
            condutancia(na, nb, g)
            if na != terra:
                b[idx[na]] += g * volts
            if nb != terra:
                b[idx[nb]] -= g * volts

        for p in pecas:
            e, ref = p["eletrica"], p["ref"]
            if e["modelo"] in ("resistor", "ldr"):
                condutancia(net(ref, "1"), net(ref, "2"), 1 / ohms(p))
            elif e["modelo"] == "chave" and aj["chave"].get(ref, False):
                condutancia(net(ref, e["lados"][0][0]), net(ref, e["lados"][1][0]), 1 / R_CHAVE)
            elif e["modelo"] == "piezo" and aj["piezo"].get(ref, False):
                condutancia(net(ref, "1"), net(ref, "2"), 1 / R_CHAVE)
            elif e["modelo"] == "pilha":
                fonte(net(ref, e["mais"]), net(ref, e["menos"]), aj["pilha"].get(ref, e["v"]), r_pilha(e))
            elif e["modelo"] == "led" and acesos[ref]:
                fonte(net(ref, polos(e)[0]), net(ref, polos(e)[1]), joelho(e), e["r_s"])
        x = resolver_linear(A, b)
        v = {n: x[idx[n]] for n in nets}
        v[terra] = 0.0

        # LED aceso puxando corrente pra trás apaga; LED apagado com tensão acima do joelho acende
        mudou = False
        for p in pecas:
            if p["eletrica"]["modelo"] != "led":
                continue
            ref, e = p["ref"], p["eletrica"]
            vab = tensao(v, net(ref, polos(e)[0]), net(ref, polos(e)[1]))
            if vab is None:
                acesos[ref] = False
            elif acesos[ref] and vab < joelho(e) - 1e-9:
                acesos[ref], mudou = False, True
            elif not acesos[ref] and vab > joelho(e) + 1e-9:
                acesos[ref], mudou = True, True
        if not mudou:
            break

    saida, entra = {}, {}
    for p in pecas:
        e, ref = p["eletrica"], p["ref"]
        if e["modelo"] in ("resistor", "ldr"):
            r = ohms(p)
            vab = tensao(v, net(ref, "1"), net(ref, "2"))
            i = vab / r if vab is not None else 0.0
            saida[ref] = {"i": i, "p": i * i * r, "ohms": r}
            entra[f"{ref}.1"], entra[f"{ref}.2"] = i, -i
        elif e["modelo"] == "led":
            mais, menos = polos(e)
            vab = tensao(v, net(ref, mais), net(ref, menos))
            i = max((vab - joelho(e)) / e["r_s"], 0.0) if acesos[ref] and vab is not None else 0.0
            saida[ref] = {"i": i, "v": joelho(e) + e["r_s"] * i if i > 0 else (vab or 0.0),
                          "acende": i >= 0.001, "forte": i > (e["i_teste"] + e["i_max"]) / 2, "queima": i > e["i_max"]}
            entra[f"{ref}.{mais}"], entra[f"{ref}.{menos}"] = i, -i
        elif e["modelo"] == "pilha":
            volts = aj["pilha"].get(ref, e["v"])
            vab = tensao(v, net(ref, e["mais"]), net(ref, e["menos"]))
            i = (volts - vab) / r_pilha(e) if vab is not None else 0.0   # corrente que sai do +
            saida[ref] = {"i": i, "v": volts}
            entra[f"{ref}.{e['mais']}"], entra[f"{ref}.{e['menos']}"] = -i, i
        elif e["modelo"] == "chave":
            apertada = aj["chave"].get(ref, False)
            vab = tensao(v, net(ref, e["lados"][0][0]), net(ref, e["lados"][1][0]))
            i = vab / R_CHAVE if apertada and vab is not None else 0.0
            saida[ref] = {"i": i, "apertada": apertada}
            for n in e["lados"][0]:
                entra[f"{ref}.{n}"] = i
            for n in e["lados"][1]:
                entra[f"{ref}.{n}"] = -i
        elif e["modelo"] == "piezo":
            fio = bool(aj["piezo"].get(ref, False))
            vab = tensao(v, net(ref, "1"), net(ref, "2"))
            i = vab / R_CHAVE if fio and vab is not None else 0.0
            saida[ref] = {"i": i, "fio": fio}
            entra[f"{ref}.1"], entra[f"{ref}.2"] = i, -i
        elif e["modelo"] == "capacitor":
            saida[ref] = {"i": 0.0}
            entra[f"{ref}.1"], entra[f"{ref}.2"] = 0.0, 0.0
    return {"nets": v, "pecas": saida, "entra": entra}
