"""avr8js.py: o motor avr8js. O Arduino Nano no avr8js (o emulador de AVR em JavaScript do Wokwi, MIT,
https://github.com/wokwi/avr8js), rodado pelo node. É o segundo motor do Nano: o mesmo .hex do arduino-cli
num emulador escrito por outra gente, pra conferir o simavr.

O miolo é motores/js/emular.mjs (o mesmo do rp2040js), que lê o .hex, liga os timers, a USART e o ADC, aplica o
pull-up (o avr8js não aplica sozinho) e escreve um evento JSON por linha. Precisa do node (Homebrew) e do pacote
avr8js@0.21.1, que só existe no npm: o laboratório não roda brew nem npm sem o OK do Luiz.
Medido aqui: ~2x mais rápido que a placa, ~85 MB de RAM (o node); nos 6 exemplos, os mesmos eventos do simavr
com no máximo 0,54 ms de diferença nos pinos.
"""
from pathlib import Path

from motores import _arduino
from nucleo import ferramentas as fer

NOME = "avr8js"
DESCRICAO = "avr8js 0.21.1 (Wokwi) no node: o ATmega328P do Nano em JavaScript, o segundo motor pra conferir o simavr"
FIEL = ("de verdade: a CPU AVR, os timers, a USART e o ADC rodando o mesmo .hex que vai pra placa, ciclo a ciclo a "
        "16 MHz; de mentira: o pull-up (o avr8js não tem: o motor aplica), a tensão nos pinos (só 0 ou 1), pino solto "
        "(lê 0), o ADC (a tensão do roteiro vira o número exato) e o relógio (virtual: ~2x a placa, mais lento que o "
        "simavr)")
PLACAS = {"nano": "atmega328p"}
LINGUAGENS = {"arduino"}
RECURSOS = {"serial", "serial_entrada", "pino_saida", "pino_entrada", "pwm", "adc", "timer"}

FQBN = "arduino:avr:nano"
EMULAR = Path(__file__).resolve().parent / "js" / "emular.mjs"


def faltando(fe):
    return _arduino.faltando_js(fe, NOME) + _arduino.faltando(fe, ("avr",))


def ocupa(fe):
    return sum(fer.du(p) for p in [_arduino.modulos(fe) / NOME] if p.exists())


def instalar(fe, diga=print):
    fe = Path(fe)
    _arduino.instalar(fe, diga, ("avr",))
    _arduino.instalar_js(fe, NOME, diga)   # PrecisaDe se faltar o node ou o pacote do npm
    diga("avr8js: já tem (node %s, avr8js %s, core arduino:avr %s)" % (
        _arduino.node(), _arduino.versao_js(fe, NOME), _arduino.CORES["avr"][1]))


def rodar(pedido):
    fe = Path(pedido.ferramentas)
    falta = faltando(fe)
    if falta:
        raise fer.PrecisaDe("; ".join(falta), "python3 laboratorio/lab.py instalar avr8js")
    montar = lambda hexa: [_arduino.node(), str(EMULAR), "nano", str(hexa), "--modulos", str(_arduino.modulos(fe))]
    yield from _arduino.rodar_compilado(pedido, NOME, FQBN, montar, ".hex", adc_ok=lambda p: p.startswith("A"))
