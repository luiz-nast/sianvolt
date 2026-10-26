"""roda a bateria inteira do Sianvolt: python3 testes/rodar.py (melhor com o .venv, que tem o gerbonara)

As cópias de placa, o Chrome da foto e o laboratório dos testes ficam numa pasta só desta rodada, em
~/.cache/sianvolt/testes/rodada-*, e não no /tmp (que é RAM e é de todo mundo): os testes e os programas que eles
abrem (testar.py, lab.py, Chrome) recebem ela como TMPDIR. No fim ela vai embora inteira."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TEMPORARIAS = Path.home() / ".cache" / "sianvolt" / "testes"


def bateria(aqui):
    TEMPORARIAS.mkdir(parents=True, exist_ok=True)
    rodada = Path(tempfile.mkdtemp(prefix="rodada-", dir=TEMPORARIAS))
    antes = os.environ.get("TMPDIR"), tempfile.tempdir
    os.environ["TMPDIR"], tempfile.tempdir = str(rodada), str(rodada)
    try:
        sys.path.insert(0, str(aqui))
        return unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover(str(aqui)))
    finally:
        tempfile.tempdir = antes[1]
        if antes[0] is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = antes[0]
        shutil.rmtree(rodada, ignore_errors=True)


if __name__ == "__main__":
    resultado = bateria(Path(__file__).resolve().parent)
    sys.exit(0 if resultado.wasSuccessful() else 1)
