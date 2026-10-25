"""mentira.py: o motor de mentira do teste_nucleo.py. Também é o menor exemplo de motor que segue o contrato.

O 'firmware' não roda: o modo vem escrito no programa ('# modo: pisca' no main.py ou '// modo: pisca' no .ino)
e o motor inventa a linha do tempo de um LED piscando a cada 500 ms.
  pisca: termina com 'tempo'   erro: traceback e 'erro'   trava: termina sem 'fim'
  torto: manda um evento fora do contrato   indisponivel: levanta PrecisaDe
"""
import types

from . import contrato, placas
from .ferramentas import PrecisaDe

PEDIDOS = []   # (pedido, tinha o placa.py/placa.h ao lado?) de cada rodada


def pin(t, v, p="GPIO23", origem="firmware"):
    return {"t_ms": t, "tipo": "pino", "pino": p, "valor": v, "origem": origem}


def rodar(pedido):
    PEDIDOS.append((pedido, (pedido.pasta / ("placa.py" if pedido.linguagem == "micropython" else "placa.h")).is_file()))
    modo = pedido.principal.read_text().split("modo:")[1].split()[0]
    if modo == "indisponivel":
        raise PrecisaDe("node", "brew install node")
    led, t, v = pedido.placa.fisico("LED"), 0.0, 1
    yield {"t_ms": 0, "tipo": "modo", "pino": led, "modo": "saida"}
    yield {"t_ms": 0, "tipo": "serial", "dir": "tx", "texto": "olá do " + pedido.placa.nome, "porta": "uart0"}
    yield pin(1000, 0, "BOTAO", "roteiro")   # o lab.py troca pelo dele
    while t < pedido.tempo_ms:
        yield pin(t, v, led)
        v, t = v ^ 1, t + 500
    if modo == "erro":
        yield {"t_ms": t, "tipo": "erro", "texto": "Traceback (most recent call last):\nZeroDivisionError"}
        yield contrato.fim("erro", "mentira", pedido.placa.id, pedido.alvo, t, 0.01)
    elif modo == "torto":
        yield {"t_ms": t, "tipo": "pino", "pino": led}   # sem valor nem origem
    elif modo != "trava":
        yield contrato.fim("tempo", "mentira", pedido.placa.id, pedido.alvo, pedido.tempo_ms, 0.01, 3.0)


def motor():
    """um módulo novo com a interface de motor (dá pra trocar faltando/instalar/rodar no teste)"""
    m = types.ModuleType("mentira")
    m.NOME, m.DESCRICAO, m.FIEL = "mentira", "motor dos testes", "nada aqui é de verdade"
    m.PLACAS = dict({p: p for p in placas.PLACAS}, c6=("c3", "aproximado: roda no C3"))
    m.LINGUAGENS, m.RECURSOS = {"micropython", "arduino"}, {"serial", "pino_saida", "pino_entrada", "timer"}
    m.faltando, m.instalar, m.rodar = (lambda fe: []), (lambda fe, diga: diga("já tem")), rodar
    return m
