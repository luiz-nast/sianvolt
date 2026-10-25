"""motores: um arquivo motores/<nome>.py por motor; os que começam com _ são ajudantes (_arduino.py).

descobrir() acha os motores sozinho e confere a interface do contrato (nucleo/contrato.py). Motor com
defeito não derruba o laboratório: fica em RECUSADOS com o motivo. O menor motor que segue o contrato é
o de mentira dos testes, em nucleo/mentira.py.

A pasta motores/<nome>/ guarda o que o motor precisa. Não ponha __init__.py nela (viraria um pacote com
o mesmo nome do <nome>.py). Pra importar código de lá, o <nome>.py faz
    __path__ = [str(Path(__file__).with_suffix(""))]
e depois  from motores.<nome>.sub import x  (o módulo vira o pacote da própria pasta).
"""
import importlib.util
import sys
from pathlib import Path

PASTA = Path(__file__).resolve().parent
INTERFACE = ("NOME", "DESCRICAO", "FIEL", "PLACAS", "LINGUAGENS", "RECURSOS", "faltando", "instalar", "rodar")
INSTALAR = "python3 laboratorio/lab.py instalar %s"
RECUSADOS = {}
_achados = None
_situacao = {}


def conferir(mod, nome):
    """os problemas de interface de um motor (lista vazia = bom)"""
    from nucleo.contrato import LINGUAGENS, RECURSOS
    falta = [a for a in INTERFACE if not hasattr(mod, a)]
    if falta:
        return ["falta " + ", ".join(falta)]
    erros = []
    if mod.NOME != nome:
        erros.append("NOME %r diferente do arquivo %s.py" % (mod.NOME, nome))
    for a in ("DESCRICAO", "FIEL"):
        if not isinstance(getattr(mod, a), str):
            erros.append("%s tem que ser texto" % a)
    if not isinstance(mod.PLACAS, dict) or not mod.PLACAS:
        erros.append("PLACAS tem que ser um dict {placa: alvo ou (alvo, aviso)}")
    else:
        for p, a in mod.PLACAS.items():
            if not (isinstance(a, str) or (isinstance(a, tuple) and len(a) == 2 and all(isinstance(x, str) for x in a))):
                erros.append("PLACAS[%r] tem que ser 'alvo' ou ('alvo', 'aviso')" % p)
    if not mod.LINGUAGENS or not set(mod.LINGUAGENS) <= set(LINGUAGENS):
        erros.append("LINGUAGENS tem que ser parte de %s" % (LINGUAGENS,))
    if not set(mod.RECURSOS) <= RECURSOS:
        erros.append("RECURSOS desconhecidos: %s" % sorted(set(mod.RECURSOS) - RECURSOS))
    erros += ["%s tem que ser uma função" % f for f in ("faltando", "instalar", "rodar") if not callable(getattr(mod, f))]
    return erros


def descobrir(pasta=None, de_novo=False):
    """{nome: módulo} dos motores que seguem o contrato"""
    global _achados
    if _achados is not None and pasta is None and not de_novo:
        return _achados
    pasta = Path(pasta or PASTA)
    achados = {}
    for arq in sorted(pasta.glob("*.py")):
        nome = arq.stem
        if nome.startswith("_"):
            continue
        modulo = ("motores." if pasta == PASTA else "lab_motor_") + nome
        try:
            spec = importlib.util.spec_from_file_location(modulo, arq)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[modulo] = mod
            spec.loader.exec_module(mod)
        except Exception as e:   # motor quebrado não derruba o laboratório
            sys.modules.pop(modulo, None)
            RECUSADOS[nome] = "não carrega: %s: %s" % (type(e).__name__, e)
            continue
        erros = conferir(mod, nome)
        if erros:
            RECUSADOS[nome] = "; ".join(erros)
        else:
            achados[nome] = mod
    if pasta == PASTA:
        _achados = achados
    return achados


def usar(motores):
    """troca os motores achados (pros testes, com motor de mentira)"""
    global _achados
    _achados = dict(motores)
    _situacao.clear()


def alvo(motor, placa_id):
    """-> (alvo, aviso ou None); KeyError se o motor não roda essa placa"""
    a = motor.PLACAS[placa_id]
    return (a, None) if isinstance(a, str) else a


def faltando(motor, ferramentas):
    """motor.faltando() sem deixar uma exceção derrubar a listagem"""
    try:
        return list(motor.faltando(ferramentas))
    except Exception as e:
        return ["faltando() quebrou: %s: %s" % (type(e).__name__, e)]


def conhecidos():
    """todos os motores que alguma placa usa, mais os achados"""
    from nucleo.placas import PLACAS
    return {m for p in PLACAS.values() for ms in p.motores.values() for m in ms} | set(descobrir())


def situacao(nome, ferramentas):
    """'instalado', 'falta: ...' ou 'recusado: ...'"""
    if nome not in _situacao:
        m = descobrir().get(nome)
        falta = faltando(m, ferramentas) if m else None
        _situacao[nome] = ("recusado: " + RECUSADOS[nome] if nome in RECUSADOS else
                           "falta: ainda não existe (motores/%s.py)" % nome if m is None else
                           "falta: " + "; ".join(falta) if falta else "instalado")
    return _situacao[nome]


def escolher(placa, lingua, nome, precisa, ferramentas):
    """-> (motor, None) ou (None, (código de saída, mensagem)); sem nome, o primeiro pronto da placa,
    de preferência um que tenha tudo que o roteiro precisa"""
    candidatos = placa.motores[lingua]
    if nome:
        if nome not in conhecidos():
            return None, (2, "motor desconhecido: %s (motores: %s)" % (nome, ", ".join(sorted(conhecidos()))))
        if nome not in candidatos:
            return None, (2, "o motor %s não roda %s na %s (só %s)" % (nome, lingua, placa.id, ", ".join(candidatos)))
        candidatos = [nome]
    achados = descobrir()
    prontos = [achados[m] for m in candidatos if situacao(m, ferramentas) == "instalado"
               and placa.id in achados[m].PLACAS and lingua in achados[m].LINGUAGENS]
    if not prontos:
        linhas = "\n".join("  %s: %s" % (m, situacao(m, ferramentas)) for m in candidatos)
        if nome:   # pediu um motor que não está pronto: diga qual está
            outros = [m for m in placa.motores[lingua] if m != nome and situacao(m, ferramentas) == "instalado"]
            return None, (5, "o motor %s não está pronto pra %s na %s:\n%s\nrode: %s%s" % (
                nome, lingua, placa.id, linhas, INSTALAR % nome,
                "\n(prontos pra %s na %s: %s)" % (lingua, placa.id, ", ".join(outros)) if outros else ""))
        return None, (5, "nenhum motor pronto pra %s na %s:\n%s\nrode: %s" % (lingua, placa.id, linhas,
                                                                              INSTALAR % candidatos[0]))
    completos = [m for m in prontos if set(precisa) <= set(m.RECURSOS)]
    return (completos or prontos)[0], None


def instalar(motor, ferramentas, diga=print):
    """motor.instalar() com a pergunta do brew/npm no meio -> None (foi), "" (faltou algo e o pedir() já disse o
    quê e como resolver) ou o texto do problema"""
    from nucleo.ferramentas import PrecisaDe, pedir
    for tentativa in (1, 2):   # a segunda é depois do Luiz deixar rodar o brew
        try:
            motor.instalar(ferramentas, diga)
            return None
        except PrecisaDe as e:
            if tentativa == 2:
                return str(e)
            if not pedir(e, diga):
                return ""
        except Exception as e:
            return "deu errado: %s: %s" % (type(e).__name__, e)
        finally:
            _situacao.pop(motor.NOME, None)
