# coisas que o CPython aceita e o MicroPython não (ou faz diferente): o gêmeo no CPython deixa passar
import sys
print("rodando em", sys.implementation.name)
testes = {
    "dict com **": "d = {'a': 1}; x = {**d, 'b': 2}",
    "f-string com =": "v = 3; s = f'{v=}'",
    "str.removeprefix": "'GPIO2'.removeprefix('GPIO')",
    "int.bit_count": "(255).bit_count()",
    "match/case": "exec('match 1:\\n case 1: pass')",
    "dataclasses": "import dataclasses",
    "typing": "import typing",
    "1_000 (sublinhado)": "x = 1_000",
    "walrus :=": "(y := 5)",
}
for nome, cod in testes.items():
    try:
        exec(cod)
        print("aceita:", nome)
    except Exception as e:
        print("NÃO aceita:", nome, "->", type(e).__name__)
