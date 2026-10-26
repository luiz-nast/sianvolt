"""preparar.py: copia o programa pra build/ e escreve, junto dele, placa.py (MicroPython) ou placa.h (Arduino).

Os exemplos fazem 'from placa import *' ou '#include "placa.h"' e nunca escrevem número de pino.
A pasta do programa (exemplos/ ou a do Luiz) nunca é alterada: tudo vai pra build/.
nomes_dos_pinos diz o nome de cada pino na linha do tempo: o do pinos.py (placas do Sianvolt) ou o apelido do
placa.py, só quando o programa usa um deles.
"""
import ast
import re
import shutil
from pathlib import Path

from .placas import APELIDOS

EXTENSAO = {"micropython": ".py", "arduino": ".ino"}
FONTES = {"micropython": (".py",), "arduino": (".ino", ".h", ".hpp", ".c", ".cpp")}
USA_PLACA = {"micropython": re.compile(r"^[ \t]*(?:from[ \t]+placa[ \t]+import\b|import[ \t]+(?:[\w.]+[ \t]*,[ \t]*)*"
                                       r"placa\b)", re.M),
             "arduino": re.compile(r'^[ \t]*#[ \t]*include[ \t]*[<"]placa\.h[>"]', re.M)}


def linguagens_de(programa):
    """as linguagens que o programa (arquivo .py/.ino ou pasta) tem, sem ordem"""
    programa = Path(programa)
    arquivos = [programa] if programa.is_file() else sorted(programa.iterdir()) if programa.is_dir() else []
    return {lin for lin, ext in EXTENSAO.items() if any(a.suffix == ext and a.is_file() for a in arquivos)}


def principal(programa, linguagem):
    """o arquivo que roda: main.py (ou o único .py); <pasta>.ino (ou o único .ino)"""
    programa, ext = Path(programa), EXTENSAO[linguagem]
    if programa.is_file():
        if programa.suffix != ext:
            raise ValueError("%s não é um programa %s (%s)" % (programa.name, linguagem, ext))
        return programa
    candidatos = sorted(a for a in programa.glob("*" + ext) if a.is_file())
    preferido = programa / ("main.py" if linguagem == "micropython" else programa.name + ".ino")
    if preferido in candidatos:
        return preferido
    if len(candidatos) == 1:
        return candidatos[0]
    raise ValueError("em %s não sei qual %s roda (%s)" % (programa, ext, ", ".join(a.name for a in candidatos)
                                                         or "nenhum"))


def placa_py(placa):
    linhas = ["# placa.py: escrito pelo lab.py pra %s (%s). Não edite: muda a cada rodada." % (placa.nome, placa.id),
              'NOME = "%s"' % placa.nome, 'PLACA = "%s"' % placa.id]
    linhas += ["PINO_%s = %r" % (a, placa.numero(placa.apelidos[a])) for a in APELIDOS]
    linhas += ["ADC_MAX = %d" % placa.adc_max, "VREF_MV = %d" % placa.vref_mv]
    return "\n".join(linhas) + "\n"


def placa_h(placa):
    linhas = ["// placa.h: escrito pelo lab.py pra %s (%s). Não edite: muda a cada rodada." % (placa.nome, placa.id),
              "#pragma once", '#define NOME "%s"' % placa.nome, '#define PLACA "%s"' % placa.id]
    linhas += ["#define PINO_%s %s" % (a, placa.numero(placa.apelidos[a])) for a in APELIDOS]
    linhas += ["#define ADC_MAX %d   // o maior valor do analogRead() (sem analogReadResolution)"
               % (placa.adc_max_arduino or placa.adc_max), "#define VREF_MV %d" % placa.vref_mv]
    return "\n".join(linhas) + "\n"


def _fontes(programa, linguagem):
    """os arquivos de código que vão pra rodada (os mesmos que o preparar copia), sem o placa.py/placa.h"""
    programa = Path(programa)
    if programa.is_file():
        return [programa]
    achados = [a for a in sorted(programa.iterdir()) if a.is_file()]
    if linguagem == "arduino" and (programa / "src").is_dir():
        achados += sorted(a for a in (programa / "src").rglob("*") if a.is_file())
    return [a for a in achados if a.suffix in FONTES[linguagem] and a.name not in ("placa.py", "placa.h")]


def _constantes(arquivo):
    """NOME = número, no nível de cima de um .py (o pinos.py que o Sianvolt gera), sem rodar o arquivo"""
    try:
        arvore = ast.parse(Path(arquivo).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return []
    return [(no.targets[0].id, no.value.value) for no in arvore.body
            if isinstance(no, ast.Assign) and len(no.targets) == 1 and isinstance(no.targets[0], ast.Name)
            and isinstance(no.value, ast.Constant) and type(no.value.value) is int]


def nomes_dos_pinos(placa, programa, linguagem):
    """o nome que a linha do tempo põe junto de cada pino físico -> {pino: [nomes]}. Vem do que o programa usa: o
    pinos.py da pasta (o Sianvolt gera do placa.txt: D7 = 4 -> 'GPIO4 (D7)') e, se ele importa o placa.py (ou
    inclui o placa.h) do laboratório, os apelidos dele (LED, BOTAO...). Um programa que não usa nenhum dos dois fica
    sem nome: o GPIO4 do dado é o LED G, e não o BOTAO dos exemplos"""
    programa, nomes = Path(programa), {}
    pinos_py = programa / "pinos.py"
    if linguagem == "micropython" and programa.is_dir() and pinos_py.is_file():
        for nome, n in _constantes(pinos_py):
            p = placa.fisico(str(n), None)
            if p and nome not in nomes.get(p, []):
                nomes.setdefault(p, []).append(nome)
    usa = USA_PLACA[linguagem]
    if any(usa.search(a.read_text(encoding="utf-8", errors="replace")) for a in _fontes(programa, linguagem)):
        for apelido in APELIDOS:
            p = placa.apelidos[apelido]
            if apelido not in nomes.get(p, []):
                nomes.setdefault(p, []).append(apelido)
    return nomes


def preparar(placa, linguagem, programa, trabalho):
    """-> (pasta, principal) dentro de trabalho/<nome>/; apaga a cópia anterior"""
    programa, trabalho = Path(programa).resolve(), Path(trabalho).resolve()
    if "build" not in trabalho.parts:
        raise ValueError("a pasta de trabalho tem que ficar dentro de build/: %s" % trabalho)
    origem = principal(programa, linguagem)
    nome = origem.stem if linguagem == "arduino" else (programa.name if programa.is_dir() else origem.stem)
    pasta = trabalho / nome
    if pasta.exists():
        shutil.rmtree(pasta)
    pasta.mkdir(parents=True)
    if programa.is_dir():
        for a in sorted(programa.iterdir()):
            if a.is_file() and a.name not in ("placa.py", "placa.h"):
                shutil.copy2(a, pasta / a.name)
            elif a.is_dir() and a.name == "src" and linguagem == "arduino":   # src/ do sketch
                shutil.copytree(a, pasta / "src")
    else:
        shutil.copy2(origem, pasta / origem.name)
    if linguagem == "micropython":
        (pasta / "placa.py").write_text(placa_py(placa), encoding="utf-8")
    else:
        (pasta / "placa.h").write_text(placa_h(placa), encoding="utf-8")
    return pasta, pasta / origem.name
