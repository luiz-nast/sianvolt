"""apoio dos testes: caminho da ferramenta, placa de teste numa pasta temporária, modelo de circuito à mão"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ferramenta"))

import gerar  # noqa: E402
import programa  # noqa: E402

PLACAS = Path(__file__).resolve().parent / "placas"
PREFIXO = "sianvolt-teste-"   # o mkdtemp de toda cópia dos testes: o apagar só apaga pasta com esse nome


def copia(nome="lanterna", troca=None):
    """copia a placa de teste (testes/placas/<nome>) pra uma pasta temporária, com o pid no nome (dá pra saber de que
    rodada dos testes ela sobrou); troca = {"texto velho": "texto novo"} no placa.txt"""
    pasta = Path(tempfile.mkdtemp(prefix=f"{PREFIXO}{os.getpid()}-")) / nome
    shutil.copytree(PLACAS / nome, pasta)
    if troca:
        txt = (pasta / "placa.txt").read_text()
        for velho, novo in troca.items():
            assert velho in txt, velho
            txt = txt.replace(velho, novo)
        (pasta / "placa.txt").write_text(txt)
    return pasta


def apagar(pasta):
    """apaga a cópia e a vaga que o laboratório abriu pra ela (a etapa 8 roda o programa no build/ do laboratório,
    numa pasta com o nome da cópia, que não volta). A cópia é <mkdtemp>/<nome>: quem vai embora é o mkdtemp, o pai
    dela. Por isso o apagar recebe a cópia, nunca o mkdtemp: com o mkdtemp, o pai seria a pasta temporária do sistema
    (o /tmp inteiro). Pai sem o PREFIXO no nome (ou o próprio gettempdir) é engano do teste: para com erro, sem apagar"""
    pai = Path(pasta).resolve().parent
    if not pai.name.startswith(PREFIXO) or pai == Path(tempfile.gettempdir()).resolve():
        raise ValueError(f"apagar({pasta}): o pai ({pai}) não é um mkdtemp dos testes ({PREFIXO}...); "
                         "passe a cópia (<mkdtemp>/<nome>), não o mkdtemp")
    programa.apagar_vaga(programa.nome_da_copia(pasta))
    shutil.rmtree(pai, ignore_errors=True)


def modelo(texto):
    """placa.txt (texto) -> modelo montado, com a biblioteca do repositório"""
    return gerar.montar(gerar.ler(texto))


# circuito à mão: peças com pinos em nets, sem placa
def peca(ref, eletrica, nets, valor=None):
    return {"ref": ref, "eletrica": eletrica, "valor": valor,
            "pinos": [{"n": n, "net": net} for n, net in nets.items()]}


PILHA = {"modelo": "pilha", "mais": "1", "menos": "2", "v": 3.0, "v_min": 2.0, "v_max": 3.3, "mah": 235}
LED = {"modelo": "led", "vf": 1.9, "vf_max": 2.3, "i_teste": 0.010, "i_max": 0.030, "r_s": 20}
RESISTOR = {"modelo": "resistor", "potencia_max": 0.25}
CHAVE = {"modelo": "chave", "lados": [["1", "2"], ["3", "4"]], "i_max": 0.05}
