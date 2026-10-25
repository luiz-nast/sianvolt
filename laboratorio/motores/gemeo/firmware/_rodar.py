# _rodar.py: roda o firmware dentro do MicroPython de verdade (port unix), ligado no motor do gêmeo.
#   micropython _rodar.py <pasta do programa> main.py   (MICROPYPATH aponta pra esta pasta e pra do programa)
import sys
import builtins
import _ponte

pasta, nome = sys.argv[-2], sys.argv[-1]
f = open(pasta + "/" + nome)
src = f.read()
f.close()
builtins.print = _ponte.print_gemeo   # todo print (de qualquer módulo) sai pela serial do gêmeo
g = {"__name__": "__main__"}
try:
    exec(compile(src, nome, "exec"), g)   # 'main.py' no traceback, como na placa
    _ponte.programa_acabou()
except _ponte.FimDaSimulacao:
    pass
except BaseException as e:   # SystemExit e KeyboardInterrupt também: o motor decide o que é
    g.clear()          # solta a memória do firmware (um MemoryError deixa o heap cheio) antes de contar o erro
    import gc
    gc.collect()
    if isinstance(e, SystemExit):
        try:
            _ponte.rpc("saiu")
        except _ponte.FimDaSimulacao:
            pass
    else:
        import io
        s = io.StringIO()
        sys.print_exception(e, s)
        try:
            _ponte.rpc("erro", s.getvalue())
        except _ponte.FimDaSimulacao:
            pass
