"""contrato.py: o combinado entre o lab.py e os motores. Todo motor e todo exemplo segue isto.

Motor = um arquivo motores/<nome>.py com:
  NOME, DESCRICAO, FIEL (frase: o que é de verdade e o que é de mentira),
  PLACAS = {"esp32": "esp32", "c6": ("c3", "aproximado: ...")}   id da placa -> alvo, ou (alvo, aviso)
  LINGUAGENS = {"micropython"} e/ou {"arduino"};  RECURSOS = subconjunto de RECURSOS (abaixo)
  faltando(ferramentas) -> list[str]   (vazio = pronto; cada item diz o quê e quanto ocupa; rápido, só olha arquivos)
  instalar(ferramentas, diga) -> None  (idempotente; brew/npm: levanta ferramentas.PrecisaDe)
  rodar(pedido) -> iterador de eventos (dicts); desliga todo processo filho no fim, sempre
  opcional: ocupa(ferramentas) -> int bytes

Evento: dict com "t_ms" (tempo DE PLACA em ms, 3 casas; 0 = primeira linha do main.py ou entrada
no setup()) e "tipo" (ver TIPOS). O último é sempre um "fim". O lab.py é quem insere os eventos do
roteiro (pino/adc/luz com origem "roteiro" e serial "rx"): se o motor mandar esses, eles são trocados.
Com o circuito (--circuito, só o gemeo):
  led   o brilho de um LED, a cada mudança: ref, i_med e i_max (A: a corrente média e a de quando liga, que no
        PWM são diferentes), luz (a fração do brilho do anúncio, a conta do blocos.brilho_da_corrente; sem a
        curva no datasheet, corrente ÷ corrente de teste), aceso (True/False: a regra do texto, luz de 1% ou
        mais ou 1 mA em algum momento; o LED de 35 µA de um pull-up tem números, mas está apagado), queima
        (True/False) e o texto pra gente
  luz   a luz que o roteiro põe num LDR do circuito (ref, lux); o motor põe o LDR no circuito com essa luz. A do
        roteiro.json o lab.py insere (origem "roteiro"); a do gemeo.roteiro o gemeo manda (origem "gemeo.roteiro")
  adc   com origem "circuito": a tensão que o circuito põe num GPIO quando a luz do LDR muda
"""
import dataclasses
import time
from dataclasses import dataclass
from pathlib import Path

from .ferramentas import PrecisaDe

RECURSOS = frozenset({"serial", "serial_entrada", "pino_saida", "pino_entrada", "pwm", "adc",
                      "i2c", "timer", "rede", "eletrica", "luz"})
LINGUAGENS = ("micropython", "arduino")
ESTADOS = ("acabou", "tempo", "erro", "travou", "indisponivel")
MODOS = ("saida", "entrada", "pullup", "pulldown", "adc", "pwm")

# códigos de saída do lab.py rodar
OK, ERRO, USO, TRAVOU, CONFERENCIA, INDISPONIVEL = 0, 1, 2, 3, 4, 5
CODIGOS = {OK: "ok", ERRO: "erro no programa", USO: "uso errado", TRAVOU: "travou",
           CONFERENCIA: "conferência falhou", INDISPONIVEL: "motor indisponível"}

NUM, NADA = (int, float), type(None)
# tipo -> {campo: (tipos aceitos, valores aceitos ou None)}; campo com "?" no fim é opcional
TIPOS = {
    "serial": {"dir": (str, ("tx", "rx")), "texto": (str, None), "porta": (str, None)},
    "pino": {"pino": (str, None), "valor": (int, (0, 1)), "origem": (str, ("firmware", "roteiro")),
             "nome?": (str, None)},
    "modo": {"pino": (str, None), "modo": (str, MODOS), "nome?": (str, None)},
    "pwm": {"pino": (str, None), "duty": (NUM, None), "freq_hz": (NUM + (NADA,), None), "nome?": (str, None)},
    "adc": {"pino": (str, None), "volts": (NUM, None), "origem": (str, ("roteiro", "circuito")), "nome?": (str, None)},
    "led": {"ref": (str, None), "i_med": (NUM, None), "i_max": (NUM, None), "luz": (NUM, None),
            "aceso": (bool, None), "queima": (bool, None), "texto": (str, None)},
    "luz": {"ref": (str, None), "lux": (NUM, None), "origem": (str, ("roteiro", "gemeo.roteiro"))},
    "aviso": {"texto": (str, None), "codigo?": ((str, NADA), None)},
    "erro": {"texto": (str, None)},
    "fim": {"estado": (str, ESTADOS), "motor": (str, None), "placa": (str, None), "alvo": (str, None),
            "tempo_placa_ms": (NUM, None), "tempo_pc_s": (NUM, None), "ram_mb": (NUM + (NADA,), None)},
    # só o lab.py escreve: a última linha do --json
    "conferencias": {"ok": (int, None), "falhas": (list, None)},
}
FOLGA_PC_S = 10   # o lab.py corta o motor que passar do limite_pc_s mais isto


class EventoInvalido(ValueError):
    pass


def valida(ev):
    """devolve uma cópia arrumada do evento (t_ms com 3 casas) ou levanta EventoInvalido"""
    if not isinstance(ev, dict):
        raise EventoInvalido("evento tem que ser um dict, veio %r" % (ev,))
    if "tipo" not in ev or "t_ms" not in ev:
        raise EventoInvalido("evento sem 'tipo' ou sem 't_ms': %r" % (ev,))
    tipo, t = ev["tipo"], ev["t_ms"]
    if tipo not in TIPOS:
        raise EventoInvalido("tipo de evento desconhecido: %r" % (tipo,))
    if isinstance(t, bool) or not isinstance(t, NUM) or t < 0:
        raise EventoInvalido("t_ms tem que ser um número >= 0: %r" % (ev,))
    novo = dict(ev, t_ms=round(float(t), 3))
    for campo, (tipos, opcoes) in TIPOS[tipo].items():
        opcional, campo = campo.endswith("?"), campo.rstrip("?")
        if campo not in ev:
            if opcional:
                continue
            raise EventoInvalido("evento %s sem '%s': %r" % (tipo, campo, ev))
        v = ev[campo]
        if isinstance(v, bool) and tipos is not bool:   # True/False: nível de pino (vira 0/1), aceso e queima
            if campo != "valor":
                raise EventoInvalido("'%s' não pode ser True/False: %r" % (campo, ev))
            v = novo[campo] = int(v)
        if not isinstance(v, tipos) or (opcoes is not None and v not in opcoes):
            raise EventoInvalido("'%s' inválido em %s: %r" % (campo, tipo, v))
    if tipo == "pwm" and not 0.0 <= ev["duty"] <= 1.0:
        raise EventoInvalido("duty tem que ficar entre 0 e 1: %r" % (ev["duty"],))
    if tipo == "luz" and ev["lux"] < 0:
        raise EventoInvalido("lux tem que ser >= 0 (0 é o escuro): %r" % (ev["lux"],))
    return novo


@dataclass
class Pedido:
    """o que o lab.py entrega a motor.rodar(pedido)"""
    placa: object               # nucleo.placas.Placa
    alvo: str                   # de motor.PLACAS
    linguagem: str              # "micropython" | "arduino"
    pasta: Path                 # programa já preparado em build/
    principal: Path             # main.py ou <nome>.ino dentro de pasta
    entradas: list              # [{"t_ms","pino","valor"} | {"t_ms","pino","volts"} | {"t_ms","serial"} |
                                #  {"t_ms","luz","lux"}]   (luz: a ref de um LDR do circuito)
    tempo_ms: float
    trabalho: Path              # build/<placa>/<motor>/<exemplo>/: imagem, log, TMPDIR
    ferramentas: Path           # laboratorio/.ferramentas
    circuito: Path | None = None   # placa.txt do Sianvolt (só o gêmeo usa)
    detalhe: bool = False       # -v
    limite_pc_s: float = 0.0    # 0 = padrão: 15 + 3 x tempo em s
    nomes: dict | None = None   # pino físico -> [nomes] que a linha do tempo mostra (preparar.nomes_dos_pinos: o
                                # pinos.py do programa, os apelidos se ele usa o placa.py); None = os apelidos

    def __post_init__(self):
        if not self.limite_pc_s:
            self.limite_pc_s = limite_padrao(self.tempo_ms)
        luz = next((e for e in self.entradas if "luz" in e), None)
        if luz and not self.circuito:   # o LDR mora no circuito: sem ele, a luz não tem onde cair
            raise ValueError("o roteiro põe %s lux no %s em %s, mas a luz entra num LDR do circuito: rode com "
                             "--circuito placa.txt (a placa do Sianvolt que tem o %s)" % (
                                 _n(luz["lux"]), luz["luz"], _s(luz["t_ms"]), luz["luz"]))


def limite_padrao(tempo_ms):
    return 15 + 3 * tempo_ms / 1000


def aviso(t_ms, texto, codigo=None):
    return {"t_ms": round(float(t_ms), 3), "tipo": "aviso", "texto": texto, "codigo": codigo}


def fim(estado, motor, placa, alvo, tempo_placa_ms, tempo_pc_s, ram_mb=None):
    """atalho pros motores montarem o último evento"""
    return {"t_ms": round(float(tempo_placa_ms), 3), "tipo": "fim", "estado": estado, "motor": motor,
            "placa": placa, "alvo": alvo, "tempo_placa_ms": round(float(tempo_placa_ms), 3),
            "tempo_pc_s": round(float(tempo_pc_s), 3), "ram_mb": ram_mb}


def _do_roteiro(ev):
    return ev.get("origem") == "roteiro" or (ev["tipo"] == "serial" and ev["dir"] == "rx")


def eventos_do_roteiro(entradas, porta="uart0"):
    """entradas do Pedido -> eventos que o lab.py insere na linha do tempo"""
    saida = []
    for e in entradas:
        e = dict(e, t_ms=round(float(e["t_ms"]), 3))
        if "serial" in e:
            for linha in e["serial"].rstrip("\n").split("\n"):
                saida.append({"t_ms": e["t_ms"], "tipo": "serial", "dir": "rx", "texto": linha, "porta": porta})
        elif "volts" in e:
            saida.append({"t_ms": e["t_ms"], "tipo": "adc", "pino": e["pino"], "volts": e["volts"],
                          "origem": "roteiro"})
        elif "luz" in e:
            saida.append({"t_ms": e["t_ms"], "tipo": "luz", "ref": e["luz"], "lux": e["lux"], "origem": "roteiro"})
        else:
            saida.append({"t_ms": e["t_ms"], "tipo": "pino", "pino": e["pino"], "valor": e["valor"],
                          "origem": "roteiro"})
    return saida


def executar(motor, pedido):
    """roda o motor e devolve a linha do tempo final: validada, com o roteiro e os apelidos dos pinos,
    em ordem de tempo e com exatamente um 'fim' no fim (sem 'fim' do motor = travou)"""
    placa, eventos, final = pedido.placa, [], None
    inicio = time.monotonic()
    gen = None
    luzes = [e for e in pedido.entradas if "luz" in e]
    if luzes and "luz" not in motor.RECURSOS:   # o motor não sabe pôr luz num LDR: ela fica de fora, avisada
        pedido = dataclasses.replace(pedido, entradas=[e for e in pedido.entradas if "luz" not in e])
        eventos.append(aviso(0, "o motor %s não põe luz no LDR do circuito (só o gemeo): %s %s de fora" % (
            motor.NOME, ", ".join("%s com %s lux em %s" % (e["luz"], _n(e["lux"]), _s(e["t_ms"])) for e in luzes),
            "ficou" if len(luzes) == 1 else "ficaram"), "recurso"))
    try:
        gen = iter(motor.rodar(pedido))
        for ev in gen:
            try:
                ev = valida(ev)
            except EventoInvalido as e:
                eventos.append(aviso(ev.get("t_ms", 0) if isinstance(ev, dict) and isinstance(ev.get("t_ms"), NUM)
                                     else 0, "o motor mandou um evento fora do contrato: %s" % e, "contrato"))
                continue
            if ev["tipo"] == "fim":
                final = ev
                break
            if ev["tipo"] != "conferencias" and not _do_roteiro(ev):
                eventos.append(ev)
            if time.monotonic() - inicio > pedido.limite_pc_s + FOLGA_PC_S:
                eventos.append(aviso(ev["t_ms"], "o motor passou do limite de %.0f s de PC" % pedido.limite_pc_s,
                                     "limite_pc"))
                break
    except PrecisaDe as e:
        eventos.append(aviso(0, "falta: %s. Pra resolver: %s" % (e.oque, e.comando), "indisponivel"))
        final = fim("indisponivel", motor.NOME, placa.id, pedido.alvo, 0, time.monotonic() - inicio)
    except Exception as e:   # defeito do motor, não do programa
        eventos.append(aviso(eventos[-1]["t_ms"] if eventos else 0,
                             "o motor %s quebrou: %s: %s" % (motor.NOME, type(e).__name__, e), "motor"))
    finally:
        if gen is not None and hasattr(gen, "close"):
            gen.close()   # o motor desliga os processos filhos no finally dele
    ultimo = max((e["t_ms"] for e in eventos), default=0.0)
    if final is None:
        final = fim("travou", motor.NOME, placa.id, pedido.alvo, ultimo, time.monotonic() - inicio)
    final["t_ms"] = max(final["t_ms"], ultimo)
    for ev in eventos:
        if "pino" in ev:
            ev["pino"] = placa.fisico(ev["pino"], ev["pino"])
    if final["estado"] != "indisponivel":
        porta = next((e["porta"] for e in eventos if e["tipo"] == "serial"), placa.porta_serial)
        todos = eventos_do_roteiro(pedido.entradas, porta)
        roteiro = [e for e in todos if e["t_ms"] <= final["t_ms"]]
        depois = sorted({e["t_ms"] for e in todos if e["t_ms"] > final["t_ms"]})
        if depois:   # o roteiro manda coisa depois do fim da rodada: não aconteceu
            eventos.append(aviso(final["t_ms"], "%d entrada(s) do roteiro ficaram depois do fim da rodada (%s; a "
                                 "rodada parou em %s, estado %s) e não aconteceram" % (
                                     sum(e["t_ms"] > final["t_ms"] for e in todos),
                                     ", ".join(_s(t) for t in depois[:4]) + (" ..." if len(depois) > 4 else ""),
                                     _s(final["t_ms"]), final["estado"]), "roteiro"))
        eventos = roteiro + eventos   # no mesmo instante, o de fora vem antes (causa antes do efeito)
    eventos.sort(key=lambda e: e["t_ms"])
    nomes_do = nomes_dos_pinos(pedido)
    eventos = _conferir_entradas(eventos, placa, nomes_do)
    eventos = _conferir_baud(eventos, motor.NOME)
    for ev in eventos:
        nomes = nomes_do(ev["pino"]) if "pino" in ev else []
        if nomes:
            ev["nome"] = "/".join(nomes)
    return eventos + [final]


def nomes_dos_pinos(pedido):
    """-> função pino físico -> [nomes] da linha do tempo: os do Pedido (o que o programa usa) ou os apelidos da
    placa, quando quem montou o Pedido não disse"""
    if pedido.nomes is None:
        return pedido.placa.apelidos_do
    return lambda pino: list(pedido.nomes.get(pino, ()))


def _s(t_ms):
    return ("%.3f s" % (t_ms / 1000)).replace(".", ",")


def _n(x):
    return ("%g" % x).replace(".", ",")


def _conferir_entradas(eventos, placa, nomes_do=None):
    """o que o roteiro faz e na placa de verdade daria problema, igual pra todo motor (cada motor resolve de um
    jeito diferente, então o laboratório avisa): forçar um pino que o programa usa como saída (curto) e pôr
    mais tensão num pino do que a placa aguenta. nomes_do: pino -> nomes (padrão: os apelidos da placa).
    -> eventos com os avisos no lugar certo"""
    nomes_do = nomes_do or placa.apelidos_do
    saida, modo, avisados, novos = {}, {}, set(), []
    for ev in eventos:
        p = ev.get("pino")
        if ev["tipo"] == "modo":
            modo[p] = ev["modo"]
        elif ev["tipo"] in ("pino", "pwm") and ev.get("origem", "firmware") == "firmware":
            saida[p] = True
        if ev.get("origem") != "roteiro":
            continue
        nomes = nomes_do(p)
        nome = "%s (%s)" % (p, "/".join(nomes)) if nomes else p
        if modo.get(p) in ("saida", "pwm") or (saida.get(p) and modo.get(p) not in ("entrada", "pullup", "pulldown",
                                                                                     "adc")):
            if ("curto", p) not in avisados:
                avisados.add(("curto", p))
                novos.append(aviso(ev["t_ms"], "o roteiro força %s, mas o programa usa esse pino como saída: na placa "
                                   "isso é um curto (a saída briga com o que está ligado nela e pode queimar o pino); "
                                   "cada motor resolve de um jeito, não confie nas conferências desse pino" % nome,
                                   "curto"))
        maximo = getattr(placa, "pino_max_v", 0) or placa.tensao + 0.3
        if ev["tipo"] == "adc" and ev["volts"] > maximo and ("volts", p) not in avisados:
            avisados.add(("volts", p))
            v = lambda x: ("%g" % x).replace(".", ",")   # noqa: E731
            novos.append(aviso(ev["t_ms"], "o roteiro põe %s V em %s, acima do máximo do pino (%s V; a placa é de "
                               "%s V): na placa isso pode queimar o pino. O laboratório lê assim mesmo" % (
                                   v(ev["volts"]), nome, v(maximo), v(placa.tensao)), "tensao"))
    if not novos:
        return eventos
    return sorted(eventos + novos, key=lambda e: e["t_ms"])


BAUD = 115200   # a serial UART das placas (Serial.begin(115200), o REPL do MicroPython)


def _conferir_baud(eventos, motor):
    """a UART a 115200 baud manda no máximo ~11.520 caracteres por segundo (10 bits cada): o print() da placa
    espera a serial. Motor que manda mais rápido que isso (o qemu não tem limite) esconde essa lentidão: avisa"""
    por_s = {}
    for ev in eventos:
        if ev["tipo"] == "serial" and ev["dir"] == "tx" and ev.get("porta", "").startswith("uart"):
            k = int(ev["t_ms"] // 1000)
            por_s[k] = por_s.get(k, 0) + len(ev["texto"].encode("utf-8")) + 2   # + \r\n
    cabe = BAUD / 10
    pior = max(por_s.items(), key=lambda x: x[1], default=(0, 0))
    if pior[1] <= cabe * 1.1:
        return eventos
    av = aviso(pior[0] * 1000.0, "a serial mandou %d caracteres no segundo que começa em %s, mas a %d baud cabem uns "
               "%d por segundo: na placa o print() espera a serial e o programa fica mais lento que aqui (o motor %s "
               "não segue o baud)" % (pior[1], _s(pior[0] * 1000.0), BAUD, cabe, motor), "baud")
    return sorted(eventos + [av], key=lambda e: e["t_ms"])


def codigo_saida(eventos, falhas, espera_estado=False):
    """0 ok, 1 erro no programa, 3 travou, 4 conferência falhou, 5 motor indisponível.
    Se o roteiro confere o estado, é a conferência que decide (um teste pode esperar 'erro')."""
    estado = eventos[-1]["estado"]
    if estado == "indisponivel":
        return INDISPONIVEL
    if not espera_estado:
        if estado == "travou":
            return TRAVOU
        if estado == "erro" or any(e["tipo"] == "erro" for e in eventos):
            return ERRO
    return CONFERENCIA if falhas else OK
