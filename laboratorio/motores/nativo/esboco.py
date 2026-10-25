"""esboco.py: junta os .ino da pasta num sketch.cpp, como a IDE do Arduino faz antes de chamar o compilador.

- #include <Arduino.h> na frente (a IDE põe; o g++ puro exige)
- a aba principal primeiro e as outras .ino em ordem alfabética, cada uma com #line (o erro aponta o
  arquivo e a linha certos)
- com prototipos=True, os protótipos das funções do nível de fora, logo antes da primeira função (setup e
  loop contam como primeira; a IDE gera
  com o ctags; aqui é uma leitura simples: quem tem argumento com valor padrão, ponteiro de função ou é
  método de classe fica sem). O nativo.py só pede quando a compilação sem eles falhou por "not declared".
"""
import re
from pathlib import Path

PALAVRAS = {"if", "else", "while", "for", "switch", "do", "return", "sizeof", "catch", "struct", "class", "union",
            "enum", "namespace", "typedef", "using", "operator", "new", "delete", "case", "goto", "throw"}
ASSINATURA = re.compile(r"(?P<tipo>[A-Za-z_][\w:<>,\s\*&]*?[\s\*&])(?P<nome>[A-Za-z_]\w*)\s*\((?P<args>[^()]*)\)"
                        r"\s*(?:const\s*)?", re.S)


def limpar(texto):
    """o texto com comentários, textos ("..."), caracteres ('x') e linhas de #pré-processador trocados por
    espaço: mesmo tamanho e mesmas quebras de linha, pra posição no limpo valer no original"""
    out, i, n = list(texto), 0, len(texto)
    inicio_linha = True

    def apaga(a, b):
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = texto[i]
        if inicio_linha and c == "#":   # pré-processador, com as continuações de linha (\)
            j = i
            while j < n and (texto[j] != "\n" or texto[j - 1] == "\\"):
                j += 1
            apaga(i, j)
            i = j
            continue
        if c in " \t":
            i += 1
            continue
        inicio_linha = c == "\n"
        if texto.startswith("//", i):
            j = texto.find("\n", i)
            j = n if j < 0 else j
            apaga(i, j)
            i = j
        elif texto.startswith("/*", i):
            j = texto.find("*/", i + 2)
            j = n if j < 0 else j + 2
            apaga(i, j)
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and texto[j] != c and texto[j] != "\n":
                j += 2 if texto[j] == "\\" else 1
            apaga(i, j + 1)
            i = j + 1
        else:
            i += 1
    return "".join(out)


def funcoes(texto):
    """[(posição do começo da assinatura, protótipo, nome)] das funções definidas no nível de fora"""
    limpo = limpar(texto)
    saida, nivel, inicio = [], 0, 0
    for i, c in enumerate(limpo):
        if c == "{":
            if nivel == 0:
                cab = limpo[inicio:i]
                m = ASSINATURA.fullmatch(cab.strip())
                if (m and m["nome"] not in PALAVRAS and "=" not in m["args"]
                        and not set(m["tipo"].split()) & PALAVRAS and not m["tipo"].rstrip().endswith("::")):
                    pos = inicio + len(cab) - len(cab.lstrip())
                    saida.append((pos, " ".join(limpo[pos:i].split()) + ";", m["nome"]))
            nivel += 1
        elif c == "}":
            nivel = max(0, nivel - 1)
            if nivel == 0:
                inicio = i + 1
        elif c == ";" and nivel == 0:
            inicio = i + 1
    return saida


def abas(pasta, principal):
    """a aba principal e as outras .ino da pasta (em ordem alfabética)"""
    outras = sorted(a for a in Path(pasta).glob("*.ino") if a.is_file() and a.name != Path(principal).name)
    return [Path(principal)] + outras


def montar(pasta, principal, prototipos=False):
    """-> o texto do sketch.cpp"""
    textos = [(a.name, a.read_text(encoding="utf-8", errors="replace")) for a in abas(pasta, principal)]
    partes = ["#include <Arduino.h>\n"]
    achadas = [funcoes(t) for _, t in textos] if prototipos else [[] for _ in textos]
    protos = [p for fs in achadas for _, p, nome in fs if nome not in ("setup", "loop")]
    primeira = next((k for k, fs in enumerate(achadas) if fs), None) if protos else None
    for k, (nome, texto) in enumerate(textos):
        if k == primeira:   # os protótipos entram logo antes da primeira função (da aba principal, se tiver)
            pos = texto.rfind("\n", 0, achadas[k][0][0]) + 1
            linha = texto.count("\n", 0, pos) + 1
            partes += ['#line 1 "%s"\n' % nome, texto[:pos],
                       '#line %d "%s"\n' % (linha, nome), "\n".join(protos) + "\n",
                       '#line %d "%s"\n' % (linha, nome), texto[pos:]]
        else:
            partes += ['#line 1 "%s"\n' % nome, texto]
        if not texto.endswith("\n"):
            partes.append("\n")
    return "".join(partes)
