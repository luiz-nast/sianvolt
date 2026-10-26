"""o app (app.py): só serve o que deve, só pra esta máquina, e só aceita pedido que veio dele mesmo"""
import contextlib
import http.client
import io
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from apoio import PLACAS, RAIZ
import app
import programa

class Servidor(unittest.TestCase):
    """o app numa porta qualquer, com as placas de PASTA"""
    PASTA = PLACAS   # só a placa de teste (o clone limpo não tem placas/)

    @classmethod
    def setUpClass(cls):
        cls.placas_de_verdade, app.PLACAS = app.PLACAS, cls.PASTA
        cls.servidor = ThreadingHTTPServer(("127.0.0.1", 0), partial(app.Bancada, directory=str(RAIZ)))
        cls.porta = cls.servidor.server_address[1]
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        app.PLACAS = cls.placas_de_verdade

    def pedir(self, metodo, caminho, corpo=None, cabecalhos=None):
        c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=20)
        c.putrequest(metodo, caminho, skip_host=True, skip_accept_encoding=True)   # caminho cru, sem normalizar
        for k, v in {"Host": f"127.0.0.1:{self.porta}", **(cabecalhos or {})}.items():   # o app confere o Host
            c.putheader(k, v)
        dado = corpo.encode() if isinstance(corpo, str) else corpo
        if dado is not None:
            c.putheader("Content-Length", str(len(dado)))
        c.endheaders(dado)
        r = c.getresponse()
        texto = r.read()
        c.close()
        return r.status, texto

    def json(self, metodo, caminho, corpo=None, cabecalhos=None):
        status, texto = self.pedir(metodo, caminho, None if corpo is None else json.dumps(corpo), cabecalhos)
        return status, json.loads(texto)


class App(Servidor):
    def test_pagina_e_api(self):
        self.assertEqual(self.pedir("GET", "/")[0], 302)
        self.assertEqual(self.pedir("GET", "/bancada/index.html")[0], 200)
        status, texto = self.pedir("GET", "/api/placas")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(texto)["raiz"], str(RAIZ))
        self.assertEqual(json.loads(texto)["placas"], ["esp32", "lanterna"])
        status, texto = self.pedir("GET", "/api/catalogo")
        d = json.loads(texto)
        self.assertGreater(len(d["pecas"]), 1000)
        self.assertEqual(d["grupos"][0], "Passivos")

    def test_placa_de_teste_do_esp32(self):
        """a placa de teste com o programa abre no Processo e no ▶ Programa, e nada é escrito nela (ela vai pro git)"""
        status, proj = self.json("GET", "/api/projeto?placa=esp32")
        self.assertEqual(status, 200)
        self.assertEqual([b["ref"] for b in proj["blocos"]][:2], ["U1", "D1"])
        self.assertEqual(self.json("GET", "/api/programa?placa=esp32"),
                         (200, {"erro": "o programa desta placa ainda não rodou", "ainda_nao_rodou": True}))
        self.assertTrue(self.json("GET", "/api/programa?placa=lanterna")[1]["sem_programa"])
        self.assertEqual(self.pedir("GET", "/placas/esp32/fabrica.json")[0], 204, "sem cotação: 204, não 404")
        self.assertFalse((PLACAS / "esp32" / "saida").exists())

    def test_nao_sai_da_bancada_e_das_placas(self):
        for caminho in ("/bancada/../.git/HEAD", "/bancada/%2e%2e/.git/HEAD", "/placas/../ferramenta/app.py",
                        "/placas/%2e%2e/%2e%2e/etc/passwd", "/.git/HEAD", "/ferramenta/app.py", "/bancada/../../../etc/passwd"):
            self.assertEqual(self.pedir("GET", caminho)[0], 404, caminho)
            self.assertEqual(self.pedir("HEAD", caminho)[0], 404, f"HEAD {caminho}")

    def test_host_de_outro_site_e_barrado(self):
        for metodo in ("GET", "POST"):
            self.assertEqual(self.pedir(metodo, "/api/placas", cabecalhos={"Host": "evil.com"})[0], 403)
        self.assertEqual(self.pedir("GET", "/api/placas", cabecalhos={"Host": f"127.0.0.1:{self.porta}.evil.com"})[0], 403)

    def test_host_e_o_da_porta_de_verdade(self):
        """o app pode estar fora da 8765 (outro programa nela): o Host que vale é o da porta em que ele está"""
        self.assertEqual(self.pedir("GET", "/api/placas", cabecalhos={"Host": f"localhost:{self.porta}"})[0], 200)
        if self.porta != app.PORTA:
            self.assertEqual(self.pedir("GET", "/api/placas", cabecalhos={"Host": f"127.0.0.1:{app.PORTA}"})[0], 403)
            self.assertEqual(self.pedir("HEAD", "/bancada/index.html", cabecalhos={"Host": f"127.0.0.1:{app.PORTA}"})[0], 404)

    def test_post_so_com_o_cabecalho_do_app(self):
        self.assertEqual(self.pedir("POST", "/api/testar?placa=lanterna", "{}")[0], 404)
        self.assertEqual(self.pedir("POST", "/api/qualquer", "{}", {"X-Bancada": "1"})[0], 404)

    def test_post_com_dado_ruim(self):
        x = {"X-Bancada": "1"}
        self.assertEqual(self.pedir("POST", "/api/testar?placa=nao_existe", "{}", x)[0], 404)
        self.assertEqual(self.pedir("POST", "/api/testar?placa=..", "{}", x)[0], 404)
        self.assertEqual(self.pedir("POST", "/api/escolher?placa=lanterna", "isto não é json", x)[0], 400)
        self.assertEqual(self.pedir("POST", "/api/escolher?placa=lanterna", "[1, 2]", x)[0], 400)
        self.assertEqual(self.pedir("POST", "/api/escolher?placa=lanterna", "{" + " " * 20000 + "}", x)[0], 400)
        self.assertEqual(self.pedir("POST", "/api/escolher?placa=lanterna", json.dumps({"ref": "R1", "codigo": "../x"}), x)[0], 400)
        self.assertEqual(self.pedir("POST", "/api/escolher?placa=lanterna", json.dumps({"ref": "R1;rm", "codigo": "C1"}), x)[0], 400)
        self.assertEqual(self.pedir("POST", "/api/catalogo/buscar", json.dumps({"bloco": "../../etc", "texto": "x"}), x)[0], 400)
        for ref in ("D1;rm", ["D1"], "../D1", ""):   # o ref do LED (cor, brilho só dele) é conferido antes de gravar
            corpo = json.dumps({"pergunta": "brilho", "resposta": "media", "ref": ref})
            self.assertEqual(self.pedir("POST", "/api/responder?placa=lanterna", corpo, x)[0], 400, ref)

    def test_escolher_aceita_peca_de_loja_brasileira(self):
        """'robocore:esp32-wifi-bluetooth' passa da validação e chega no blocos.escolher (que aqui só para)"""
        pedidos, escolher = [], app.blocos.escolher

        def parar(pasta, ref, codigo):
            pedidos.append((pasta.name, ref, codigo))
            raise ValueError("parou no teste")
        app.blocos.escolher = parar
        try:
            x = {"X-Bancada": "1"}
            pedido = {"ref": "U1", "codigo": "robocore:esp32-wifi-bluetooth"}
            status, r = self.json("POST", "/api/escolher?placa=lanterna", pedido, x)
            self.assertEqual((status, r), (400, {"erro": "parou no teste"}))
            self.assertEqual(pedidos, [("lanterna", "U1", "robocore:esp32-wifi-bluetooth")])
            for ruim in ("robocore:../x", "Robocore:esp32", "robocore:", "robocore:a b", ":esp32", "robocore:esp32\n",
                         "C1\n"):
                status, r = self.json("POST", "/api/escolher?placa=lanterna", {"ref": "U1", "codigo": ruim}, x)
                self.assertEqual((status, r), (400, {"erro": "ref ou código inválido"}), ruim)
            self.assertEqual(len(pedidos), 1)
        finally:
            app.blocos.escolher = escolher

    def test_get_com_dado_ruim(self):
        self.assertEqual(self.pedir("GET", "/api/foto?codigo=../../etc/passwd")[0], 400)
        self.assertEqual(self.pedir("GET", "/api/foto?codigo=C1%0A")[0], 400)
        self.assertEqual(self.pedir("GET", "/api/projeto?placa=%00")[0], 404)
        self.assertEqual(self.pedir("GET", "/api/opcoes?placa=..&ref=R1")[0], 404)

    def test_placa_so_dentro_de_placas(self):
        self.assertIsNone(app.placa(".."))
        self.assertIsNone(app.placa("../ferramenta"))
        self.assertIsNone(app.placa("\x00"))
        self.assertIsNone(app.placa(""))


# a placa com o ESP32 e um programa: o D1 pisca e o SW1 é lido; o 220 Ω e o led_5mm são só de ensaio
ESP32 = """placa 80 56
furos cantos 3.2
peca U1 devkit_esp32_30 40 32
peca R1 resistor_axial 28 9 220
peca D1 led_5mm 18 9
peca R2 resistor_axial 52 9 1k
peca SW1 botao_6x6 66 9
liga U1.6 R1.2
liga R1.1 D1.1
liga D1.2 GND
liga U1.11 R2.1
liga R2.2 SW1.1
liga SW1.3 GND
"""
MAIN = """from machine import Pin
import time
from pinos import D1, SW1
led, botao = Pin(D1, Pin.OUT), Pin(SW1, Pin.IN, Pin.PULL_UP)
antes = 1
for i in range(100):
    led.value(i // 10 % 2)
    if botao.value() != antes:
        antes = botao.value()
        print("botao", antes)
    time.sleep_ms(10)
"""


class Programa(Servidor):
    """o ▶ Programa do app: POST roda o programa.py como subprocesso e responde na hora; o GET diz como está"""

    @classmethod
    def setUpClass(cls):
        cls.raiz = Path(tempfile.mkdtemp(prefix="sianvolt-teste-"))
        cls.PASTA = cls.raiz / "placas"
        for nome, codigo in (("esp32", True), ("sem_programa", False)):
            (cls.PASTA / nome / "codigo").mkdir(parents=True)
            (cls.PASTA / nome / "placa.txt").write_text(ESP32)
            if codigo:
                (cls.PASTA / nome / "codigo" / "main.py").write_text(MAIN)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        programa.apagar_vaga(programa.nome_da_copia(cls.PASTA / "esp32"))   # a placa temporária não volta
        shutil.rmtree(cls.raiz, ignore_errors=True)

    def setUp(self):
        self.esperar("esp32")
        app.rodando.pop("esp32", None)   # cada teste começa sem rodada nenhuma
        app.testar_depois.discard("esp32")
        self.addCleanup(self.esperar, "esp32")

    def esperar(self, nome, limite=60):
        """espera a rodada da placa acabar (o processo que o app abriu)"""
        p = app.rodando.get(nome)
        if p is not None:
            p.wait(limite)

    def post(self, corpo, placa="esp32", cabecalhos=None):
        return self.json("POST", f"/api/programa?placa={placa}", corpo, {"X-Bancada": "1"} if cabecalhos is None else cabecalhos)

    def test_sem_o_cabecalho_do_app(self):
        self.assertEqual(self.post({}, cabecalhos={})[0], 404)
        self.assertNotIn("esp32", app.rodando)

    def test_corpo_conferido(self):
        ruins = {"aperto em quem não é botão": {"apertos": [{"ref": "D1", "de": 1, "ate": 1.2}]},
                 "luz em quem não é olho de luz": {"luz": [{"ref": "SW1", "t": 1, "lux": 10}]},
                 "tempo 999": {"apertos": [{"ref": "SW1", "de": 1, "ate": 999}]},
                 "51 entradas": {"apertos": [{"ref": "SW1", "de": 1, "ate": 2}] * 51},
                 "campo a mais": {"apertos": [], "x": 1}}
        for nome, corpo in ruins.items():
            with self.subTest(nome):
                status, r = self.post(corpo)
                self.assertEqual(status, 400)
                self.assertTrue(r["erro"])
        self.assertIn("'D1' não é um botão da placa (botões: SW1)", self.post(ruins["aperto em quem não é botão"])[1]["erro"])
        self.assertEqual(self.post({}, "sem_programa"), (400, {"erro": "esta placa não tem programa (falta o codigo/main.py)"}))
        self.assertEqual(self.json("GET", "/api/programa?placa=sem_programa"),
                         (200, {"erro": "esta placa não tem programa (falta o codigo/main.py)", "sem_programa": True}))
        self.assertEqual(self.post({}, "nao_existe")[0], 404)
        self.assertEqual(self.post({}, "..")[0], 404)
        self.assertNotIn("esp32", app.rodando)   # nada disso rodou

    def test_responde_sem_esperar(self):
        """o POST volta na hora com {rodando: true}; enquanto roda, o GET diz rodando, outro POST dá 409 e o testar
        pedido no meio fica pra quando o programa acabar (em vez de sumir)"""
        comando, rodar_testes, testadas = app.comando_do_programa, app.rodar_testes, []
        app.comando_do_programa = lambda pasta, entradas: [sys.executable, "-c", "import time; time.sleep(4)"]
        app.rodar_testes = lambda pasta, frase=None: testadas.append(pasta.name) or True   # o testar.py de mentira
        try:
            inicio = time.monotonic()
            status, r = self.post({"apertos": [{"ref": "SW1", "de": 0.5, "ate": 0.7}]})
            self.assertLess(time.monotonic() - inicio, 2)
            self.assertEqual((status, r), (200, {"rodando": True}))
            self.assertEqual(self.json("GET", "/api/programa?placa=esp32"), (200, {"rodando": True}))
            self.assertEqual(self.post({}), (409, {"erro": "o programa da placa está rodando; tenta de novo em uns segundos"}))
            self.assertEqual(self.json("POST", "/api/testar?placa=esp32", {}, {"X-Bancada": "1"}),
                             (200, {"ok": True, "ja_rodando": False, "depois_do_programa": True}))
            self.assertEqual(testadas, [])   # ainda não: o programa está rodando
            self.esperar("esp32")
            limite = time.monotonic() + 10
            while not testadas and time.monotonic() < limite:
                time.sleep(0.05)
            self.assertEqual(testadas, ["esp32"])   # e roda quando ele acaba
        finally:
            app.comando_do_programa, app.rodar_testes = comando, rodar_testes
        self.assertEqual(self.json("GET", "/api/programa?placa=esp32"),
                         (200, {"erro": "o programa desta placa ainda não rodou", "ainda_nao_rodou": True}))   # o de mentira não gravou nada
        self.assertEqual(self.json("GET", "/api/programa?placa=nao_existe")[0], 404)

    def test_com_os_testes_rodando(self):
        """o testar também ocupa a placa: o programa espera (409), e a placa sem programa continua 'sem programa'
        (a bancada esconde o ▶ Programa por ele), mesmo no meio dos testes"""
        for nome in ("esp32", "sem_programa"):   # o testar.py de mentira
            app.rodando[nome] = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
            app.o_que[nome] = "testes"
        try:
            self.assertEqual(self.json("GET", "/api/programa?placa=sem_programa"),
                             (200, {"erro": "esta placa não tem programa (falta o codigo/main.py)", "sem_programa": True}))
            self.assertEqual(self.json("GET", "/api/programa?placa=esp32"), (200, {"rodando": True}))
            self.assertEqual(self.post({}), (409, {"erro": "os testes estão rodando; tenta de novo em uns segundos"}))
            self.assertEqual(self.json("POST", "/api/testar?placa=esp32", {}, {"X-Bancada": "1"}),
                             (200, {"ok": True, "ja_rodando": True}))
        finally:
            for nome in ("esp32", "sem_programa"):
                app.rodando[nome].kill()
                app.rodando.pop(nome).wait()

    def test_get_devolve_o_mais_novo(self):
        saida = self.PASTA / "esp32" / "saida"
        saida.mkdir(exist_ok=True)
        try:
            (saida / "programa.json").write_text(json.dumps({"livre": False, "codigo": 0}))
            self.assertEqual(self.json("GET", "/api/programa?placa=esp32"),
                             (200, {"livre": False, "codigo": 0, "rodando": False}))
            time.sleep(0.01)
            (saida / "programa_livre.json").write_text(json.dumps({"livre": True, "codigo": 1}))
            self.assertEqual(self.json("GET", "/api/programa?placa=esp32")[1]["livre"], True)
        finally:
            for nome in ("programa.json", "programa_livre.json"):
                (saida / nome).unlink(missing_ok=True)

    @unittest.skipUnless(programa.tem_laboratorio(), "sem o laboratório e o MicroPython do PC")
    def test_rodar_de_novo_no_gemeo(self):
        """de ponta a ponta: o POST abre o programa.py de verdade e o GET acaba devolvendo o programa_livre.json"""
        status, r = self.post({"apertos": [{"ref": "SW1", "de": 0.3, "ate": 0.5}]})
        self.assertEqual((status, r), (200, {"rodando": True}))
        self.esperar("esp32")
        status, prog = self.json("GET", "/api/programa?placa=esp32")
        self.assertEqual(status, 200)
        self.assertEqual((prog["rodando"], prog["livre"], prog["codigo"], prog["erro"]), (False, True, 0, None))
        apertou = next(t for t, txt in prog["serial"] if txt == "botao 0")
        self.assertAlmostEqual(apertou, 300, delta=15)   # o programa olha o botão a cada 10 ms
        self.assertTrue(any(x[1] > 0 for x in prog["leds"]["D1"]))
        self.assertEqual(prog["entradas"]["apertos"], [{"ref": "SW1", "de": 300.0, "ate": 500.0, "origem": "app"}])
        self.assertTrue((self.PASTA / "esp32" / "codigo" / "pinos.py").is_file())


class OutroPrograma(BaseHTTPRequestHandler):
    """um programa qualquer na porta (como o radar-vagas na 8765): responde 404 pra tudo"""

    def do_GET(self):
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):
        pass


def porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class AbrirOApp(unittest.TestCase):
    """o app não fica preso na 8765: outro programa nela, ele vai pra próxima; ele mesmo aberto, só abre a janela"""

    def setUp(self):
        self.addCleanup(setattr, app, "PLACAS", app.PLACAS)
        app.PLACAS = PLACAS
        self.outro = ThreadingHTTPServer(("127.0.0.1", 0), OutroPrograma)
        threading.Thread(target=self.outro.serve_forever, daemon=True).start()
        self.addCleanup(self.outro.server_close)
        self.addCleanup(self.outro.shutdown)
        self.ocupada = self.outro.server_address[1]

    def servir(self, servidor):
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        self.addCleanup(servidor.server_close)
        self.addCleanup(servidor.shutdown)

    def test_portas_pedidas(self):
        self.assertEqual(app.portas_do_app([], {}), list(range(8765, 8775)))
        self.assertEqual(app.portas_do_app(["--sem-janela", "--porta", "8800"], {}), [8800])
        self.assertEqual(app.portas_do_app([], {"SIANVOLT_PORTA": "8801"}), [8801])
        self.assertEqual(app.portas_do_app(["--porta", "8800"], {"SIANVOLT_PORTA": "8801"}), [8800], "o --porta ganha")
        for args, amb in ((["--porta"], {}), (["--porta", "x"], {}), ([], {"SIANVOLT_PORTA": "0"}),
                          ([], {"SIANVOLT_PORTA": "70000"})):
            with self.subTest(args=args, amb=amb), self.assertRaises(ValueError):
                app.portas_do_app(args, amb)

    def test_vai_pra_proxima_porta_e_depois_reaproveita(self):
        livre = porta_livre()
        servidor, aberto = app.subir([self.ocupada, livre])
        self.assertIsNone(aberto)
        self.assertEqual(servidor.server_address[1], livre, "a ocupada por outro programa fica pra trás")
        self.servir(servidor)
        self.assertIsNone(app.raiz_em(self.ocupada), "o outro programa não é o Sianvolt")
        self.assertEqual(app.raiz_em(livre), str(RAIZ))
        self.assertEqual(app.subir([self.ocupada, livre]), (None, livre), "o Sianvolt já aberto: a janela vai nele")
        with contextlib.redirect_stdout(io.StringIO()) as saida:
            self.assertEqual(app.main(["--sem-janela", "--porta", str(livre)], {}), 0)
        self.assertIn(f"já está aberto em http://127.0.0.1:{livre}/bancada/", saida.getvalue())

    def test_porta_so_com_outro_programa_avisa(self):
        avisos = []
        with mock.patch.object(app, "avisar", avisos.append):
            self.assertEqual(app.main(["--sem-janela", "--porta", str(self.ocupada)], {}), 1)
            self.assertEqual(app.main(["--sem-janela", "--porta", "x"], {}), 2)
        self.assertIn(f"a porta {self.ocupada} está com outros programas", avisos[0])
        self.assertIn("--porta 8800", avisos[0])
        self.assertIn("não é um número", avisos[1])

    def test_sem_terminal_o_aviso_vira_notificacao(self):
        """o atalho do menu abre sem terminal: o erro não pode sumir calado"""
        notificou = []
        with mock.patch.object(app, "notificar", notificou.append), mock.patch.object(sys, "stderr", io.StringIO()):
            app.avisar("o Sianvolt não abriu: teste")
            self.assertIn("o Sianvolt não abriu: teste", sys.stderr.getvalue())
        self.assertEqual(notificou, ["o Sianvolt não abriu: teste"])

    def test_app_que_abriu_na_segunda_porta_funciona(self):
        """o caminho da 1ª porta com outro programa e da 2ª livre: o app sobe inteiro (o 'vivo' do __main__ apagava a
        função vivo() e o /api/programa caía com TypeError)"""
        for _ in range(20):   # o outro programa numa porta com a seguinte livre
            try:
                with socket.socket() as s:
                    s.bind(("127.0.0.1", self.ocupada + 1))
                break
            except OSError:
                self.outro = ThreadingHTTPServer(("127.0.0.1", 0), OutroPrograma)
                threading.Thread(target=self.outro.serve_forever, daemon=True).start()
                self.addCleanup(self.outro.server_close)
                self.addCleanup(self.outro.shutdown)
                self.ocupada = self.outro.server_address[1]
        else:
            self.skipTest("nenhuma porta com a seguinte livre aqui")
        livre = self.ocupada + 1
        criados, subir = [], app.subir

        def guarda(portas):
            servidor, aberto = subir(portas)
            criados.append(servidor)
            return servidor, aberto
        with mock.patch.object(app, "PORTA", self.ocupada), mock.patch.object(app, "subir", guarda), \
                contextlib.redirect_stdout(io.StringIO()) as saida:
            linha = threading.Thread(target=app.main, args=(["--sem-janela"], {}), daemon=True)
            linha.start()
            limite = time.monotonic() + 10
            while not criados and time.monotonic() < limite:
                time.sleep(0.02)
            try:
                self.assertEqual(criados[0].server_address[1], livre)
                c = http.client.HTTPConnection("127.0.0.1", livre, timeout=20)
                c.request("GET", "/api/programa?placa=esp32")
                r = c.getresponse()
                corpo = json.loads(r.read())
                c.close()
            finally:
                criados[0].shutdown()
                linha.join(10)
        self.assertEqual((r.status, corpo), (200, {"erro": "o programa desta placa ainda não rodou", "ainda_nao_rodou": True}))
        self.assertTrue(callable(app.vivo))
        self.assertIn(f"bancada em http://127.0.0.1:{livre}/bancada/ (a {self.ocupada} está com outro programa)",
                      saida.getvalue())


if __name__ == "__main__":
    unittest.main()
