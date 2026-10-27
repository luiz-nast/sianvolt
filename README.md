# Sianvolt

Ferramenta pessoal que transforma a descrição de uma placa em texto nos arquivos que a fábrica aceita (Gerber + Excellon), sem KiCad. Vem com um app local para investigar a placa, ligar o circuito no papel, rodar o programa da placa sem ter a placa e acompanhar o caminho até a fábrica.

A ordem é a de quem projeta de verdade: primeiro o que a placa tem que fazer ("quanta luz você quer?"), depois o tipo de cada peça (pilha → botão → resistor → LED), depois as peças de verdade, escolhidas no estoque da JLCPCB/LCSC (ou de uma loja brasileira) com o desenho oficial delas, e só então a placa:

```
placa 52 34
furos cantos 3.2
peca BT1 C5365915 20 17     # suporte de CR2032 (código da LCSC)
peca SW1 C393938 43 25      # botão 6×6
peca R1 C119310 43 15       # 240 Ω: sai da conta do brilho fraco
peca D1 C779439 43 7        # LED vermelho 5 mm
liga BT1.1 SW1.1
liga SW1.3 R1.1
liga R1.2 D1.2
liga D1.1 GND
```

## Mini placas com ESP32

No lugar da pilha entra o **cérebro**: um ESP32 DevKit de 30 pinos (o DOIT DevKit V1 da RoboCore), encaixado em duas barras fêmea soldadas na placa. Cada peça liga num pino dele (GPIO), e o programa (`codigo/main.py`, em MicroPython) decide quando cada LED acende. Na biblioteca o DevKit é o tipo `devkit_esp32_30`. Três projetos usam ele: o **Dado** (`placas/dado`), a **Largada**, um jogo de reflexo pra 2 (`placas/reflexo`), e a **Luz noturna** (`placas/luz_noturna`). Os três ficam só na máquina, como toda pasta de `placas/`; o que vai pro repositório é a placa de teste `testes/placas/esp32`.

## Usar

Precisa ter:

- **Python 3.12 ou mais novo** pro `.venv`: o `gerbonara` 1.6.3 (o que o `requirements.txt` traz hoje) pede isso ("Requires-Python: >=3.12" na ficha dele). A bateria passou com o 3.12.14, o 3.14.4 e o 3.15.0 (2026-10-26).
- **`uv`** pra montar o `.venv`. Sem ele: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (no Ubuntu, o `python3` que vem com o sistema só faz o `venv` depois de instalar o pacote `python3-venv`). O `uv venv` escolhe sozinho qual Python usa (aqui, o 3.12.14 que ele mesmo instalou); pra outro, `uv venv --python 3.14 .venv`.
- **Chrome ou Chromium** (`google-chrome`, `chromium` ou `chromium-browser`) pra foto da etapa 7. Sem nenhum deles, a etapa salva só o `saida/foto.svg` e passa assim mesmo. O app abre numa janela do Chrome, do Chromium ou do Edge; sem eles, no navegador padrão.
- **`git`, `make` e `gcc`** só pro gêmeo do laboratório (a etapa 8, abaixo).

```bash
uv venv .venv && uv pip install -r requirements.txt   # o .venv tem o gerbonara
.venv/bin/python ferramenta/testar.py placas/<nome>   # gera tudo e roda as etapas
python3 ferramenta/app.py                             # o app (ou o atalho do menu); porta 8765 ou a próxima livre
python3 ferramenta/instalar.py                        # põe o "Sianvolt" no menu de aplicativos
.venv/bin/python testes/rodar.py                      # a bateria da própria ferramenta
```

Rode o `testar.py` sempre com o `.venv/bin/python`: o `python3` do sistema não tem o `gerbonara` (nesta máquina, conferido), aí a etapa 6 (relê o Gerber) falha e o `fabrica.zip` não sai. O app já chama o Python do `.venv` sozinho.

O `testar.py` gera `modelo.json`, os Gerbers, o Excellon, a folha `saida/imprimir_1x1.svg` (a placa em tamanho real, com uma régua de 50 mm pra conferir a impressão) e a versão, e depois roda as etapas: lê o txt, confere peças, confere ligações, liga o circuito no papel, regras da fábrica (JLCPCB), relê o Gerber com o `gerbonara` e tira uma foto da placa. A placa com programa (`codigo/main.py`) ganha a 8ª etapa, **Roda o programa**. O `fabrica.zip` só sai quando nada falhou (etapa que pulou não é falha), e o comando sai com 0 nesse caso.

## Projeto com ESP32, passo a passo

1. Objetivo, blocos e carrinho no app (ou pela skill `nova-placa`): o bloco **cérebro** fica no meio e cada bloco diz em que GPIO liga.
2. O `placa.txt` com `peca U1 devkit_esp32_30 X Y` e as ligações nos pinos dele (`liga U1.6 R1.2` é o GPIO32). A etapa 4 liga o circuito com o pino do ESP32 no lugar da pilha (o 3V3 do DevKit, com a faixa do regulador e a fonte de cada número na `eletrica` do tipo), no pior caso, e reprova o pino errado: saída num pino só de entrada, de boot ou da serial, qualquer ligação num pino da flash ou no VIN, e botão em 34–39 sem resistor pro 3V3. Botão (com o pull-up de dentro) num pino de boot ou da serial só dá aviso.
3. O programa em `placas/<nome>/codigo/`: `main.py`, `roteiro.json` (o que acontece e o que conferir), `gemeo.roteiro` (os apertos de botão) e `confere.json` (as conferências do Sianvolt). O `codigo/pinos.py` é gerado a cada rodada a partir do `placa.txt` (`D1 = 32`): o `main.py` faz `from pinos import D1` e nunca escreve número de pino.
4. `.venv/bin/python ferramenta/testar.py placas/<nome>`: as 8 etapas. Só o programa: `.venv/bin/python ferramenta/programa.py placas/<nome>` (grava `saida/programa.json`); `--livre --entradas '{"apertos": [{"ref": "SW1", "de": 1.0, "ate": 1.2}]}'` roda do jeito do app, sem conferências (`saida/programa_livre.json`); `--pinos` só escreve o `pinos.py`.
5. No app, aba **Projeto**: o **▶ Ligar** liga e desliga cada GPIO na mão e mostra a corrente; o **▶ Programa** mostra a régua do tempo do `programa.json`, com os LEDs na luz e na cor de cada um, a serial e as conferências. No painel dele, clicar no botão desenhado e escolher a luz do quarto põe apertos e luz no instante da régua, e **Rodar de novo ↻** roda o programa só com eles (`saida/programa_livre.json`).

A placa de teste `testes/placas/esp32` (DevKit, LED, botão, olho de luz e piezo, com programa) é o exemplo que roda em qualquer clone. O `testar.py` escreve na pasta da placa (`saida/`, `versoes/`, `testes.json`, `codigo/pinos.py`) e o app só mostra o que está em `placas/`, então copie ela pra `placas/` (a pasta que o git ignora) e rode lá:

```bash
mkdir -p placas && cp -r testes/placas/esp32 placas/esp32
.venv/bin/python ferramenta/testar.py placas/esp32
python3 ferramenta/app.py                             # o "esp32" aparece na lista
```

A lanterninha de teste (`testes/placas/lanterna`, com pilha e sem programa) vai do mesmo jeito: `mkdir -p placas && cp -r testes/placas/lanterna placas/lanterna`.

## O laboratório

`laboratorio/` testa o programa de uma mini placa sem a placa na mão: roda o `main.py` no **gêmeo** (o MicroPython 1.29 compilado pro PC, ligado no `ferramenta/circuito.py`) e devolve a linha do tempo dos pinos, da serial, do brilho dos LEDs e das conferências. A etapa 8 e o ▶ Programa usam ele pelo `ferramenta/programa.py`, que roda o `laboratorio/lab.py` numa cópia do `codigo/` e nunca mexe na placa. Detalhes, motores e o formato do roteiro: [laboratorio/README.md](laboratorio/README.md).

O código do laboratório vai pro repositório, mas o que ele baixa e compila (`laboratorio/.ferramentas/`, onde fica o MicroPython do PC) fica só na máquina. **Sem o MicroPython do PC, a etapa 8 pula** (o `pinos.py` sai assim mesmo, o `fabrica.zip` também, e as checagens `programa_ok`/`programa_acende` ficam em "?"). Pra instalar só o gêmeo: `python3 laboratorio/lab.py instalar gemeo` (baixa o MicroPython do GitHub e compila; precisa de `git`, `make` e `gcc`). O `python3 laboratorio/lab.py instalar --ver` mostra o que já tem, sem baixar nada. Pra só experimentar o laboratório sem compilar nada, `LAB_GEMEO=cpython python3 laboratorio/lab.py testar --rapido` roda o gêmeo no Python do PC: é menos fiel (o CPython aceita coisa que o MicroPython recusa) e a etapa 8 não usa esse atalho (sem o MicroPython do PC, ela pula do mesmo jeito).

## O app

O app (`ferramenta/app.py`) abre numa janela própria, com a lista de projetos (com busca, e dá pra renomear e remover; o removido vai pra `placas/.lixeira/`, não é apagado) e a aba **Peças**. Cada projeto tem quatro abas: **Processo** (a história em 7 passos: objetivo, blocos, carrinho, placa, testes, fábrica, montar; com o cérebro, os blocos viram uma estrela com o nome e o pino de cada ramo, e o total do carrinho sai em R$ + US$), **Thinking** (objetivo e requisitos), **Projeto** (a placa, com inspetor, ▶ Ligar e, na placa com programa, ▶ Programa) e **Testes** (as etapas ao vivo, com os avisos desenhados nas peças). Dá pra responder as perguntas, trocar uma peça pelas opções do catálogo e rodar os testes de lá. Sem instalar: `python3 ferramenta/app.py`.

Peças: a lista de compras de sempre é a pasta `ferramenta/catalogo/` (4.464 peças em 89 categorias, contadas em 2026-10-26; um arquivo por categoria, da LCSC e de lojas brasileiras, com preço, estoque, o dia em que viu, a montagem e o que já foi conferido no datasheet). A loja online é o double check: `python3 ferramenta/catalogo.py checar C779439` (preço e estoque agora; sem código, confere a lista inteira), `python3 ferramenta/loja.py buscar "LED 5mm"` e `python3 ferramenta/loja.py importar C779439 led placas/<nome>`. O `<nome>` é de uma placa que já existe (com `placa.txt`; no clone, uma das de teste copiada pra `placas/`, como acima): o `importar` põe o desenho e a foto em `placas/<nome>/pecas/`. O `checar` e o `importar` gravam o preço e o estoque que leram na loja no `ferramenta/catalogo/`, que é do git: o `git status` mostra a mudança.

A especificação inteira está em [PROJETO.md](PROJETO.md); onde paramos, em [AGORA.md](AGORA.md). As peças da loja trazem o desenho do EasyEDA; o que a loja não diz (o + do LED, os pinos do botão, as curvas, o LDR, o piezo) o Claude lê no datasheet e guarda na própria peça, no catálogo. Todo número da tela tem fonte ou um selo "pendente" que diz o que falta conferir.
