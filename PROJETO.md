# Sianvolt

Ferramenta pessoal que transforma a descrição de uma placa em texto nos arquivos que a fábrica aceita (Gerber + Excellon), sem KiCad. O Claude Code constrói e edita; o Luiz investiga e aprende pelo Sianvolt (um app leve, janela própria no navegador).

Este arquivo é a especificação inteira. Leia tudo antes do primeiro passo.

---

## 1. Princípios (não quebrar)

1. **Texto é a fonte da verdade.** Tudo que importa vive em arquivos de texto no repositório. O app só lê e desenha.
2. **O que pode ser código vira código.** O Claude decide só a intenção (quais peças, onde, o que liga em quê, o que o programa faz). Contas, posições de pinos, checagens, o `pinos.py` e o Gerber são código determinístico.
3. **Clean.** Interface mínima, informação sob demanda. Nada aberto que não foi pedido.
4. **IA não gasta token com acompanhamento.** Status de requisitos e progresso dos testes são calculados pelo script. O Claude só dá um resumo **no final** da rodada.
5. **Nenhum número inventado.** Medidas de componentes vêm de datasheet (com a página). Regras da fábrica vêm da página de capacidades da fábrica (JLCPCB como referência). Se não souber, pergunte ou marque como **pendente**, com o que falta conferir; o app mostra o pendente.
6. **Simples primeiro.** Python puro, poucas dependências, arquivos pequenos. Nada de framework no app.
7. **Primeiro o que quer, depois a peça, por último o desenho.** O objetivo (com as perguntas de gente, como "quanta luz?") decide o tipo de cada peça; a peça é de verdade, de uma loja com estoque, com o desenho oficial dela; só então ela vai pra placa. Nada é posicionado "de cabeça".

---

## 2. Como o trabalho flui

```
Luiz diz o que quer (no Claude Code ou respondendo as perguntas no app)
  → objetivo e blocos em projeto.json; peças de verdade no carrinho (catálogo, loja.py, conferidas no datasheet)
  → Claude edita requisitos.md e/ou placa.txt (só intenção, com as peças do carrinho)
  → placa com ESP32: Claude escreve o programa em codigo/ (main.py, roteiro.json, gemeo.roteiro, confere.json)
  → ferramenta/gerar.py: txt → modelo.json + Gerber + Excellon + folha 1:1
  → ferramenta/testar.py: bateria de 7 etapas (8 com programa) → testes.json
      falhou? Claude corrige e roda de novo, sozinho
  → nova versão salva em versoes/
  → bancada atualiza sozinha (lê os arquivos)
  → Luiz investiga → pede mudança (volta ao início) ou aprova
  → saida/fabrica.zip pra JLCPCB (só até a cotação)
```

---

## 3. Estrutura do repositório

```
PROJETO.md            ← este arquivo
README.md             ← como usar, em uma página
AGORA.md              ← onde paramos (Claude atualiza a cada sessão)
.claude/skills/        ← placa (editar, testar, programa), nova-placa (a ordem), peca-da-loja (buscar e conferir peça)
ferramenta/
  gerar.py            ← lê placa.txt, roteia, escreve modelo.json, Gerbers, Excellon e a folha 1:1
  geometria.py        ← distância entre pads, trilhas e corpos (o roteador e a etapa 3 usam)
  blocos.py           ← objetivo, perguntas, blocos, contas (brilho, divisor, botão, piezo) e o carrinho (projeto.json)
  loja.py             ← busca peça na JLCPCB, foto e datasheet na LCSC, desenho oficial no EasyEDA
  catalogo.py         ← a lista de compras: encher (da loja), checar (preço e estoque agora), ver
  catalogo/           ← a lista: um arquivo por categoria (89 categorias, 4.464 peças contadas em 2026-10-26)
  lojas.py            ← preço e estoque das lojas brasileiras (Eletrogate, Baú, Usinainfo, RoboCore), pela página do produto
  biblioteca.py       ← peças de antes da loja, de exemplo e o DevKit do ESP32 (devkit_esp32_30)
  circuito.py         ← liga o circuito no papel (corrente contínua), com a pilha ou com o pino do ESP32
  programa.py         ← roda o codigo/main.py no gêmeo do laboratório → saida/programa.json
  testar.py           ← bateria de testes → testes.json
  letras.py           ← fonte de traços pra serigrafia
  app.py              ← abre a bancada como app (servidor local + janela)
  instalar.py         ← atalho "Sianvolt" no menu de aplicativos
bancada/
  index.html          ← o app (HTML + JS puro, SVG)
  icone.svg
laboratorio/          ← roda o programa de uma mini placa sem a placa (README próprio); .ferramentas/ só na máquina
testes/
  rodar.py            ← a bateria inteira (unittest)
  placas/lanterna/    ← a placa de teste com pilha (vai pro git)
  placas/esp32/       ← a placa de teste com o ESP32 e programa (vai pro git)
placas/<nome>/        ← as placas de verdade (só na máquina)
  projeto.json        ← objetivo, respostas, blocos e a peça escolhida de cada um (o app também escreve)
  pecas/              ← as peças do carrinho: desenho oficial + foto
  requisitos.md
  placa.txt
  codigo/             ← só na placa com ESP32: main.py, roteiro.json, gemeo.roteiro, confere.json e o pinos.py gerado
  saida/              ← gerado: modelo.json, placa-*.gbr, placa-PTH/NPTH.drl, foto.png, imprimir_1x1.svg,
                        fabrica.zip, programa.json, programa_livre.json
  testes.json         ← gerado
  versoes/            ← v1.txt, v2.txt, ... + v1.json, v2.json (modelo de cada versão) + versoes.json
  fabrica.json        ← o que aconteceu no site da fábrica (o Claude escreve depois de subir o zip)
```

Instalar uma vez: `uv venv .venv && uv pip install -r requirements.txt` (só o `gerbonara`, pra etapa 6; sem o `uv`: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`; no Ubuntu, o `python3` do sistema pede o pacote `python3-venv` antes). O `.venv` precisa de Python 3.12 ou mais novo (o `gerbonara` 1.6.3 pede "Requires-Python: >=3.12"; a bateria passou com o 3.12.14, o 3.14.4 e o 3.15.0 em 2026-10-26). A foto da etapa 7 usa o Chrome ou o Chromium headless; sem nenhum dos dois, a etapa salva só o `saida/foto.svg` e passa. O gêmeo do laboratório precisa de `git`, `make` e `gcc` pra compilar. O `python3` do sistema não tem o `gerbonara` (nesta máquina, conferido): rode o `testar.py` com o `.venv/bin/python`.
Gerar e testar: `.venv/bin/python ferramenta/testar.py placas/<nome>` (o `testar.py` chama o `gerar.py`; o `gerar.py` sozinho também funciona).
Rodar o programa: `.venv/bin/python ferramenta/programa.py placas/<nome>` (precisa do MicroPython do PC: `python3 laboratorio/lab.py instalar gemeo`; sem ele a etapa 8 pula).
Rodar a bancada: `python3 ferramenta/app.py` (ou o atalho do menu, depois do `instalar.py`). Abre uma janela com os projetos; o app fecha sozinho uns minutos depois que a janela fecha. Também funciona com `python -m http.server` na raiz e `localhost:8000/bancada/`, só sem os botões que rodam coisas (testes, programa, escolher peça). A página relê os arquivos a cada 1 s (polling simples).
As pastas em `placas/` ficam só na máquina (`.gitignore`); o repositório público leva a ferramenta, o laboratório e as placas de teste de `testes/placas/`. O app e o `testar.py` trabalham em `placas/`: pra ver uma placa de teste no app, copie ela pra lá (`mkdir -p placas && cp -r testes/placas/esp32 placas/esp32`); rodar o `testar.py` direto em `testes/placas/` escreve `saida/`, `versoes/` e `testes.json` dentro do repositório.

---

## 4. Os arquivos de texto

### 4.0 `projeto.json` (o começo: o Claude e o app escrevem)

O objetivo, as perguntas respondidas e os blocos, cada um com a peça escolhida e quem escolheu. No `placa.txt`, o tipo de uma peça da LCSC é o código dela (`peca R1 C119310 43 15`), e o valor vem da peça; a peça de loja brasileira entra com o tipo da biblioteca que o catálogo diz (`robocore:esp32-wifi-bluetooth` → `peca U1 devkit_esp32_30 X Y`).

Perguntas (`PERGUNTAS` em `blocos.py`), cada resposta com `quem` (o Luiz ou "sugestão do Claude") e `quando`:
- `brilho`: fraca, média ou forte (¼, metade ou o brilho que o fabricante anuncia). Com o ESP32, tem a resposta geral e o ajuste de cada LED em `por_led` (`{"D3": {"resposta": "fraca", ...}}`). Se um LED não dá conta da resposta (o verde C779443 em "forte": a conta do pino não chega lá), aparece "impossível neste LED" e o projeto não fica pronto até mudar.
- `cor` (só com o cérebro): a cor de cada LED, em `por_led`; as opções são as cores dos LEDs do catálogo.

Campos opcionais de cada bloco, pro projeto com ESP32 (a lanterninha não usa nenhum):

| campo | o que é |
|---|---|
| `pino` | o GPIO do cérebro em que o bloco liga (`"GPIO32"`) |
| `nome` | nome de gente (`"LED do meio"`); no estado ele vira `apelido` |
| `led` | no resistor: o LED que ele freia (`"D1"`) |
| `para` | no resistor: o bloco que ele atende (o botão `"SW1"`, o som `"BZ1"`, o olho de luz `"LDR1"`); no capacitor: o olho de luz em que ele fica colado |
| `duty_max` | no LED: a maior parte do tempo que o programa deixa ele aceso (PWM, de 0 a 1) |
| `origem` | de onde veio o número do bloco (`"main.py: BRILHO_MAX², 0,6² = 0,36"`) |

```json
{"objetivo": "Placa de teste com o ESP32", "frase": "Aperta o botão: o LED acende e o piezo apita.",
 "perguntas": {"brilho": {"resposta": "media", "quem": "sugestão do Claude"},
               "cor": {"por_led": {"D1": {"resposta": "vermelho", "quem": "sugestão do Claude"}}}},
 "blocos": [{"ref": "U1", "bloco": "cerebro", "peca": "robocore:esp32-wifi-bluetooth", "quem": "sugestão do Claude"},
            {"ref": "D1", "bloco": "led", "pino": "GPIO32", "nome": "LED", "peca": "C779439", "quem": "sugestão do Claude"},
            {"ref": "R1", "bloco": "resistor", "led": "D1"},
            {"ref": "SW1", "bloco": "botao", "pino": "GPIO14", "nome": "botão", "peca": "C393938", "quem": "sugestão do Claude"},
            {"ref": "R2", "bloco": "resistor", "para": "SW1"}]}
```

Blocos (`BLOCOS` em `blocos.py`): `pilha`, `botao`, `resistor`, `led` e, com o ESP32, `cerebro` (o DevKit, ref U), `ldr` (olho de luz, ref LDR), `buzzer` (som, ref BZ) e `capacitor` (ref C). Cada bloco sai de uma categoria do catálogo (`CATEGORIA`); o `cerebro` só aceita peça com `tipo` da biblioteca.

As contas (`blocos.py`), uma por resistor, cada uma com a fonte de cada número:
- **LED**: corrente pela curva do LED → (pilha ou pino − LED) ÷ corrente − o que o LED e a pilha (ou o pino) freiam sozinhos → valor E24 mais perto. Com o ESP32 a conta mostra a faixa de mA do vf máximo ao vf mínimo do LED, avisa quando passa da força padrão do pino e mostra a luz média com o `duty_max`.
- **Olho de luz**: o divisor 3V3 → resistor fixo → GPIO → LDR → GND (`circuito.divisor_do_ldr`), em volts por lux (escuro, 1, 10 e 100 lux), nos cantos do LDR, contra a faixa boa do ADC.
- **Botão** e **piezo**: o resistor em série, com a origem (o porquê de cada um está na seção 8 e nas regras de eletrônica da skill `placa`).

### 4.1 `placa.txt` (o Claude escreve)

Uma instrução por linha. Unidades em mm, origem no canto inferior esquerdo. `#` começa comentário. Este exemplo passa nas 7 etapas (conferido em 2026-10-26, numa cópia com as peças da placa de teste `testes/placas/esp32`):

```
placa 54 62
furos cantos 3.2
peca U1 devkit_esp32_30 26.5 36
peca R1 resistor_axial 14.25 17 130
peca D1 C779439 5.22 17
peca R2 resistor_axial 37.11 18.5 1k
peca SW1 C393938 48.5 18.5
liga U1.6 R1.2       # GPIO32 (D32) → 130 Ω (a conta do brilho médio) → + do LED (no C779439 é o pino 2)
liga R1.1 D1.2
liga D1.1 GND
liga U1.11 R2.1      # GPIO14 (D14) → 1 kΩ (o do botão, blocos.R_BOTAO) → lado A do botão; o lado B no GND
liga R2.2 SW1.1
liga SW1.3 GND
```

- `placa L A` — contorno retangular.
- `furos cantos D` — 4 furos de fixação a 3,5 mm das bordas (D = 3,2 mm pra M3).
- `peca REF TIPO X Y [VALOR]` — TIPO é o código da LCSC de uma peça do carrinho (`pecas/C*.json`) ou um tipo de `biblioteca.py` (`devkit_esp32_30`, `resistor_axial`). VALOR em ohms só pro resistor da biblioteca (`100`, `4.7k`, `1k`); sem ele o circuito não liga no papel.
- `liga A B` — `REF.PINO` ou o nome de uma net (`GND`; liga no pino de GND mais perto). O roteador (`gerar.rotear`) faz a trilha: reta, L ou Z, nas duas camadas, com via pra trocar de lado, longe da zona da antena do DevKit.
- No DevKit, `U1.n` é o pino físico: 1 a 15 na fileira de baixo (EN no 1, VIN no 15), 16 a 30 na de cima (3V3 no 16, D23 no 30), vista de cima com a antena à esquerda. O GPIO de cada pino está nos `nomes` do tipo (`U1.6` = GPIO32, `U1.11` = GPIO14, `U1.4` = GPIO34); o que está escrito no DevKit, na `serigrafia` (D32, D14, D34).

### 4.2 `requisitos.md` (o Claude escreve uma vez)

Cada requisito declara as peças e **como é verificado**. O script calcula o status, a IA nunca atualiza status à mão.

```
# Objetivo: LED e botão no ESP32
O programa lê o botão e acende o LED.

## R1 LED no GPIO32, sem queimar
pecas: U1 R1 D1
verifica: ligado U1.6 R1.2
verifica: ligado R1.1 D1.2
verifica: ligado D1.1 GND
verifica: acende D1
verifica: nao_queima D1
verifica: pino_seguro U1
- R1 limita a corrente; a etapa 4 confere o pino e o 3V3 no pior caso

## R2 Botão no GPIO14
pecas: SW1 R2
verifica: ligado U1.11 R2.1
verifica: separado SW1.1 SW1.3
```

Checagens (`CHECAGENS` em `testar.py`):
- `existe REF`, `ligado A B`, `separado A B` (não podem ser a mesma net), `sem_pino_solto REF`.
- `acende REF` (LED com pelo menos 1 mA, botões apertados), `nao_queima REF` (abaixo da corrente máxima no pior caso), `brilho REF` (o nível que o Luiz pediu no `projeto.json`, pela curva do datasheet).
- `pino_seguro U1`: nenhum pino do ESP32 acima da força padrão, a soma no orçamento do 3V3, nenhuma regra de pino quebrada; "?" com número pendente.
- `adc_na_faixa LDR1 10 23`: nos lux pedidos (sem lux, 10), nos cantos do LDR e do 3V3, o pino do olho de luz lê dentro da faixa boa do ADC.
- `programa_ok` (a etapa 8 passou) e `programa_acende REF` (o LED acendeu em algum momento do programa no gêmeo); "?" sem a etapa 8.

### 4.3 `testes.json` (o script escreve, etapa por etapa)

```json
{
  "versao": 3,
  "rodando": false,
  "etapas": [
    {"nome": "Lê o txt", "estado": "ok", "detalhe": "10 linhas"},
    {"nome": "Confere ligações", "estado": "ok", "detalhe": "...", "aviso": "R1.1 entra na zona da antena do U1: ...",
     "onde": ["R1"], "rotulos": {"R1": "na antena"}},
    {"nome": "Roda o programa", "estado": "falhou", "detalhe": "erro na linha 12 do main.py, em 0,500 s: AttributeError: ...",
     "onde": ["U1"], "rotulos": {"U1": "erro no programa"}, "codigo": "led.onn()", "requisitos": ["R3"]}
  ],
  "requisitos": {"R1": "ok", "R2": "ok", "R3": "falha"}
}
```

`estado`: aguardando, rodando, ok, pulou, falhou ou nao_rodou. `rotulos` é a etiqueta que a bancada desenha em cada peça (vermelha na falha, amarela no aviso); `codigo` é a linha com o erro (do `placa.txt` ou do `main.py`). O script reescreve o arquivo a cada etapa, e é assim que a bancada mostra "ao vivo" sem IA.

### 4.4 `saida/modelo.json` (o gerar.py escreve)

É o que a bancada desenha e inspeciona: cada peça e pino com posição absoluta, nome de gente, net e **a linha do placa.txt que o criou**.

```json
{
  "placa": {"w": 58, "h": 62},
  "pecas": [{"ref": "U1", "tipo": "devkit_esp32_30", "x": 26.5, "y": 36, "linha": 3,
             "corpo": {"w": 51.8, "h": 28.2, "redondo": false},
             "pinos": [{"n": "6", "nome": "GPIO32", "x": 19.33, "y": 23.3, "furo": 1.0, "net": "N1"}],
             "serigrafia": {"6": "D32"}, "cuidados": {"15": "VIN: não soldar"}, "zonas": {"antena": {...}},
             "nome_pos": {"x": 26.5, "y": 50.6, "lado": "cima"}}],
  "trilhas": [{"de": "U1.6", "ate": "R1.2", "largura": 0.3, "lado": "cima", "linha": 8}],
  "vias": [], "furos": [{"x": 3.5, "y": 3.5, "d": 3.2}],
  "simulacao": {"pode": true}, "fabrica": {"pronta": true}
}
```

O tipo que tem `serigrafia`, `cuidados`, `zonas`, `confira` e `acompanha` (o DevKit) passa esses campos pra peça. `nome_pos` é onde o nome da peça fica na serigrafia (o `gerar` escolhe o lado livre: em cima, embaixo, à direita, à esquerda), e a bancada desenha no mesmo lugar.

### 4.5 `codigo/` (o programa da placa com ESP32; o Claude escreve)

- `main.py`: MicroPython. Nunca escreve número de pino: `from pinos import D1, SW1`.
- `pinos.py`: **gerado** pelo `programa.pinos` a cada rodada, a partir do `placa.txt` ("gerado pelo Sianvolt, não edite"). Cada peça ligada num GPIO, direto ou por UM resistor, vira um nome: `D1 = 32  # LED A, U1 pino 6, D32, pelo R1`. Nunca se chama `placa.py` (o laboratório escreve por cima desse).
- `roteiro.json`: o roteiro de teste do laboratório (formato no `laboratorio/README.md`): `tempo` em segundos de placa, `precisa`, `entradas` (a luz do olho de luz é `{"t": 5, "luz": "LDR1", "lux": 1}`) e `confere` (pino ou PWM num instante, serial com `desde`/`ate`, trocas, estado do fim).
- `gemeo.roteiro`: os apertos de botão de verdade do circuito, uma linha cada: `de 0,5 s a 1,2 s aperta SW1`. **Nunca** uma linha de lux (o `programa.preparar` recusa: a luz mora no `roteiro.json`).
- `confere.json`: o que o roteiro do laboratório não sabe conferir, com 4 tipos fechados sobre o `programa.json` (tempo sem `_ms` no nome é em segundos; chave que começa com `_` é comentário):

```json
{"confere": [
  {"tipo": "leds_da_serial", "regex": "deu (\\d)", "grupo": 1, "mapa": {"1": ["D4"], "2": ["D1", "D7"]}},
  {"tipo": "pwm_freq", "pino": "GPIO26", "hz": 4000, "folga": 50, "depois_de": "GPIO25 sobe"},
  {"tipo": "serial_menos_evento", "regex_ms": "ganhou em (\\d+) ms", "evento": "GPIO25 sobe", "folga_ms": 2},
  {"tipo": "duty_entre", "pino": "GPIO25", "de_t": 8.5, "ate_t": 14, "min": 0.35, "max": 0.37}
]}
```

`leds_da_serial`: em cada linha da serial que casa, os LEDs acesos são os da face que ela disse. `pwm_freq`: a cada vez que o evento acontece, o PWM do pino fica em hz ± folga. `serial_menos_evento`: o número da linha (ms) = a hora da linha − a hora do último evento antes dela, ± folga. `duty_entre`: de `de_t` a `ate_t`, o duty do pino fica entre `min` e `max`.

Sorteio: o `main.py` chama `random.seed(time.ticks_us())` quando o botão é solto. Na placa sai diferente a cada vez; no gêmeo, sempre igual, então as conferências não falham ao acaso.

### 4.6 `saida/programa.json` (o programa.py escreve)

O contrato entre o `programa.py`, a etapa 8 e a bancada. Tempos em ms. `saida/programa_livre.json` tem o mesmo formato, do jeito do app (só as entradas que o app mandou, sem conferências).

```
{placa, quando, livre, codigo, tempo_ms,
 pinos: {GPIOn: {quem, nome, modo: [[t, m]], nivel: [[t, v]], pwm: [[t, duty, freq]], volts: [[t, v]]}},
 leds: {REF: [[t, luz, i_mA, queima]]}, serial: [[t, texto]], avisos: [[t, codigo, texto]],
 erro: null | {t, texto, linha}, conferencias: {ok: [...], falhas: [...]},
 entradas: {apertos: [{ref, de, ate, origem}], luz: [{ref, t, lux, volts, origem}]}, pendentes: [...]}
```

`codigo` é o código de saída do `lab.py`: 0 ok, 1 erro no programa, 2 uso errado, 3 travou, 4 conferência falhou, 5 falta instalar o motor. `quem` e `nome` saem do nosso `placa.txt` e do `projeto.json`. `luz` é a fração do brilho do anúncio que o gêmeo calculou pela curva do datasheet.

---

## 5. A ferramenta (Python)

`ferramenta/gerar.py` (evoluir, sem reescrever do zero):

1. Ler (linha por linha, guardando o número da linha).
2. Calcular posição absoluta de cada pino = posição da peça + offset da biblioteca ou do desenho da loja.
3. Rotear (`rotear`): duas camadas, folga de 0,25 mm entre cobres de nets diferentes e de 0,5 mm da borda (mais que o mínimo da JLCPCB, com o link em `testar.py`); a zona `antena` do DevKit é proibida pra trilha e via.
4. Escrever `modelo.json`, os Gerbers (contorno, cobre de cima e de baixo, máscara, serigrafia com o nome de cada peça no lado livre), o Excellon (furos) e a folha `imprimir_1x1.svg` (fora do `fabrica.zip`).
5. Copiar `placa.txt` pra `versoes/vN.txt` e anotar em `versoes.json` uma frase do que mudou.

**Biblioteca (`biblioteca.py`):** um dicionário `tipo → {pinos: {pino: (dx, dy, pad[, net])}, furo, corpo, juntos, nomes, eletrica, compra, fonte}`. `nomes` dá nome pra cada pino (`+`, `−`, `A`/`B`, `lado 1`, `GPIO32`): o app nunca mostra "pino 1" sozinho. `eletrica` é o que o simulador precisa (LED: vf e correntes; resistor: potência; pilha: tensão nominal, fraca e nova, mAh; chave: lados). Peça com `fonte: None` é **exemplo**; as reais saem do footprint oficial do KiCad conferido com o datasheet, e cada número elétrico cita o datasheet.

**`devkit_esp32_30`** (o DOIT ESP32 DevKit V1 de 30 pinos da RoboCore; o `esp32_devkit` antigo fica como está, porque o laboratório usa ele):
- Desenho: corpo de 51,8 × 28,2 mm, fileiras a 25,40 mm, passo 2,54 mm e os pinos 2,09 mm pro lado da antena (as fontes estão no `fonte` do tipo: o esquema do DOIT, o desenho 1:1 do Mischianti, as medidas do fórum do Fritzing, o footprint da comunidade e as fotos). A régua no DevKit de verdade está **pendente**: o `confira` manda medir 25,4 mm do EN ao D23 antes de pedir a placa.
- `nomes` de máquina (`GPIO32`, `3V3`, `GND`, `VIN`, `EN`), `serigrafia` (o que está escrito no DevKit: D32, VP, TX0), `cuidados` por pino ("só entrada", "cuidado no boot", "serial do PC", "LED azul da placa", "VIN: não soldar"), `zonas` (`antena` e `usb`, em mm a partir do centro da peça), `acompanha` (2 barras fêmea 1×15 C41417327, alternativa C22373901: vão no carrinho, nunca no `placa.txt`), `confira` (3 frases) e `compra`.
- `eletrica` modelo `mcu`: `vdd`, `vdd_min`/`vdd_max` (a faixa do regulador AMS1117, com a `condicao_3v3`), `r_pino`, `i_pino` (força padrão), `r_pull`, `vil`, `i_soma_max` (máximo absoluto), `orcamento_3v3` (o que a etapa 4 usa), `r_3v3`, `adc_min`/`adc_max`, as listas `so_entrada`, `boot`, `flash`, `serial`, `psram`, `adc1`, `fontes` (uma lista por campo, com URL e página) e `pendentes` (porta USB, queda do SS14, r_3v3). O pendente fica dentro da `eletrica`: o `pendente` da peça seguraria a fábrica.

**Circuito (`circuito.py`)** e a gêmea em JS no `index.html` (o trecho de `const GMIN` até antes de `const mA =`), a mesma conta em duas línguas: `resolver(modelo, ajustes)` (análise nodal; sem pilha devolve `None`); `com_pinos(modelo, estado, vdd)` põe o ESP32 no circuito (`~terra`, `~3V3` e um `~GPIOn` por pino: 1, 0, `pullup` ou solto; o VIN não é modelado); modelos `pilha`, `resistor`, `chave`, `led`, `ldr` (`ohms_do_ldr(e, lux, canto)`), `piezo` (aberto; na borda do apito vira fio) e `capacitor` (aberto em DC); `divisor_do_ldr(e, r_fixo, vdd, lux, canto)`.

**Programa (`programa.py`)**: `pinos(pasta)` escreve o `pinos.py`; `preparar` monta a cópia `saida/programa/sianvolt_<placa>_<hash8>/` com o `codigo/*.py`, o `roteiro.json` e o `gemeo.roteiro`; `rodar(pasta, entradas, livre)` roda `laboratorio/lab.py rodar esp32 <cópia> --motor gemeo --circuito <placa.txt> --json`, normaliza e confere; uma rodada por placa (trava `saida/.rodando`). Ele pergunta pro laboratório o que ele sabe: com a luz em lux, manda a luz do quarto como lux e o gêmeo põe o LDR do meio no circuito; num laboratório antigo, troca pelos volts do nosso divisor.

**Regras de formato já aprendidas (estão na skill `placa`):**
- Gerber: cabeçalho `%FSLAX46Y46*%` e `%MOMM*%`, coordenadas em milionésimos de mm, `D02` move, `D01` desenha, `D03` carimba pad, `M02*` fim.
- Excellon: `M48`, `METRIC,TZ`, ferramentas `T1C3.200`, **`G90` antes do `%`** (fora do cabeçalho o leitor reclama), `M30` fim.

---

## 6. A bateria de testes (`testar.py`)

Sete etapas, em ordem, e a oitava na placa com `codigo/main.py`. Para na primeira que falhar. Uma etapa pode **pular** (não se aplica a esta placa) sem ser falha; uma etapa pode passar com **aviso** (amarelo, sem falhar).

1. **Lê o txt**: sintaxe, comandos conhecidos.
2. **Confere peças**: todo TIPO existe (biblioteca ou `pecas/`); diz o que ainda está a conferir.
3. **Confere ligações**: peça sem ligação, pino solto, peça fora da placa, pino em cima do furo de fixação, corpos encostados, furo de uma peça embaixo do corpo de outra deitada (o DevKit, no alto da barra fêmea, não conta pro furo; o corpo de uma peça embaixo dele ainda dá corpos encostados), peça de 2 pinos em curto, net partida, curto. **Aviso** (não falha) quando trilha, via ou pad entra na zona da antena do DevKit: nenhum projeto liga o Wi-Fi.
4. **Liga o circuito**: `circuito.py` resolve a corrente contínua com os botões apertados. Com pilha: pilha fraca, nominal e nova. Com o ESP32: o papel de cada GPIO sai do circuito (saída, botão com pull-up, olho de luz) e o pior caso põe cada saída em 1 e em 0, no 3V3 nominal e no máximo, com o LED de vf mínimo, o piezo na borda do apito e o LDR no escuro e em 100 lux. Falha com LED acima da corrente máxima, resistor ou chave acima do limite, pino acima da força padrão, soma acima do orçamento do 3V3, saída num pino só de entrada, da serial ou de boot, qualquer ligação num pino da flash (6 a 11), GPIO2 ou GPIO12 puxado pro 3V3, por resistor ou direto (têm que estar em 0 quando o ESP32 liga), botão em 34–39 sem pull-up de fora e qualquer coisa no VIN ("VIN usado: não sei ligar no papel"). Dão aviso: botão ou outra peça (que não seja saída) num pino de boot ou da serial, GPIO16/17 (psram), o EN ligado, outro GPIO direto no 3V3 ou no GND e olho de luz fora do ADC1. O detalhe tem a frase de cada LED, os volts do olho de luz por lux e o pico do piezo, e termina com a condição do 3V3. Pula se alguma peça não tem modelo elétrico ou um número está pendente.
5. **Regras da fábrica**: trilha, espaço, furo, anel, borda, máscara, serigrafia (números da página da JLCPCB, com link no código); aviso quando o nome de uma peça não acha lugar livre.
6. **Relê o Gerber**: abre os arquivos gerados com um leitor independente (`gerbonara`) e confere que lê sem aviso.
7. **Tira foto da placa**: renderiza `foto.png` pra o Claude olhar.
8. **Roda o programa** (só com `codigo/main.py`): gera o `pinos.py`, roda o programa no gêmeo (`programa.rodar`) e soma as conferências do `roteiro.json` e do `confere.json`. Falha com erro no programa (com a linha do `main.py`), programa travado, conferência que não bate e aviso de LED queimando, corrente alta, pino de boot, pino da memória flash ou leitura flutuando. O aviso de ADC fora da faixa boa aparece sem falhar. Pula sem o laboratório ou sem o MicroPython do PC (código 5).

O `fabrica.zip` só é criado no fim, quando nenhuma etapa falhou e a fábrica está pronta (nenhuma peça de exemplo nem pendente). O comando sai com 0 quando nada falhou.

Também calcula o status de cada requisito a partir das linhas `verifica:`.

---

## 7. A bancada (app)

HTML + JS puro, desenho em SVG (facilita clique, destaque e zoom via viewBox). Tema escuro, fonte IBM Plex Sans/Mono. Referência visual: `design/App.dc.html` e `design/Board.dc.html` (abrir no navegador não roda; é pra ler o layout e as cores).

**Início:** a lista de projetos (`placas/*`), cada um com a miniatura da placa, o status dos testes, a versão e se já foi pra fábrica. Clicar abre o projeto.

**Processo:** a história do projeto em 7 passos, o caminho de toda placa, pra mostrar pra alguém:
- **objetivo**, com as perguntas que o Luiz responde clicando (brilho geral e por LED; cor de cada LED), cada uma dizendo quem decidiu;
- **blocos**: sem cérebro, a corrente de tipos de peça com o símbolo e o porquê de cada um; com o cérebro, uma **estrela** com o ESP32 no meio e cada ramo com o nome de gente e o pino;
- **carrinho**: foto, tamanho, preço e estoque de cada peça, o DevKit com as barras que acompanham, uma conta por resistor (faixa de mA, força padrão do pino, luz média com o duty), a tabelinha do olho de luz (lux → volts, faixa boa do ADC), o total em R$ + US$ e o Trocar com as opções do catálogo (escolher troca o `placa.txt` e roda os testes);
- a **placa** e as versões; os **testes** (com o resumo do Claude e o botão de rodar de novo);
- a **fábrica**: `fabrica.zip`, a folha 1:1 pra imprimir e os "confira antes de pedir" e, se tiver `fabrica.json`, a cotação com a imagem do site;
- **montar e acender**: com o DevKit, o lado das barras, a ordem de solda, procurar ponte de solda, "VIN: não soldar", nunca encaixar com o USB ligado, cabo de dados, o grupo dialout, gravar o MicroPython 1.29 e copiar `main.py` + `pinos.py`.
Os pendentes ficam sempre à vista, com o detalhe em letra pequena.

**Catálogo de peças** (pela tela inicial): o mundo de opções de cada bloco, com filtro por valor, cor e texto, o que já está em uso, o que já foi conferido no datasheet, e os botões de conferir na loja agora e procurar mais. O Trocar do carrinho lê daqui (na hora, sem internet).

**Topo:** ← projetos · nome do projeto · abas **Processo | Thinking | Projeto | Testes** · status dos testes (✓/✗) · relógio de versões (abre lista; escolher v1/v2 mostra a placa daquela versão; opção "destacar o que mudou").

**Thinking:** o objetivo num card em cima, os requisitos em cards ligados embaixo, cada um com status (ok / falta ligar) e peças. Modo **Simples** e **Detalhado** (mostra os sub-requisitos). "Ver na placa →" abre a peça na aba Projeto.

**Projeto:** a placa ocupa a tela; o tamanho dela fica pequenininho no canto.
- Ferramentas no canto: **seta**, **mão** (arrastar), **+ / −** zoom, centralizar, **▶ ligar o circuito** e, na placa com programa, **▶ Programa**.
- **▶ Ligar**: a mesma conta do `circuito.py`, em JS, pra responder na hora. A corrente vira bolinhas andando nas trilhas (mais rápido com mais corrente), o LED brilha na cor dele, clicar no botão da placa aperta e solta. Com pilha, o **painel** à direita tem a pilha (de fraca a nova), o resistor (valores comerciais E24) e, pra cada LED, a corrente com a faixa verde, o risquinho do datasheet e o vermelho do limite, e a conta `(pilha − LED) ÷ resistor`. Com o ESP32, o painel lista cada GPIO usado pelo nome de gente com uma chave 0/1 (botão: apertado/solto; olho de luz: escuro, 1, 10 ou 100 lux) e a conta `(pino − LED) ÷ (resistor + pino)`; os pendentes da `eletrica` aparecem em letra pequena.
- **▶ Programa**: a régua do tempo do `programa.json` (ou do `programa_livre.json`), com ▶/⏸, setas e velocidade. No instante escolhido, os LEDs brilham com a luz que o gêmeo calculou, na cor de cada um, cada GPIO mostra 0, 1, PWM % ou volts, a serial corre até ali, e as conferências aparecem com ✓ ou ✗ (ou "só no roteiro de teste" no livre). No painel, **Mexer e rodar de novo**: clicar no botão desenhado aperta ele por 0,2 s a partir do instante da régua, e a luz do quarto (1, 10 ou 100 lux) muda a luz do LDR nesse instante, com os volts que o pino lê; cada um vira um chip com ✕ (tracejado até rodar). **Rodar de novo ↻** manda os chips pelo `POST /api/programa`, mostra "rodando…" e troca a régua pelo `programa_livre.json` novo quando ele chega; o erro do app aparece em português.
- Pinos sempre com nome de gente (`D1 +`, `SW1 lado A`, `U1 GPIO32 · D32`); o número fica em letra pequena.
- **HUD** que segue o mouse: nome do que está embaixo + x/y em mm.
- Clicar numa peça ou pino abre o **inspetor** (direita): tipo, ligações, linha do `placa.txt` que criou aquilo, "O que é isso?" (explicação curta pra aprender), requisito atendido.
- Clicar num pino: **escurece tudo que não é da net dele**.

**Testes:** a lista das etapas (7, ou 8 com programa) atualizando ao vivo (lê `testes.json`) e, ao lado, a placa com o que falhou contornado em vermelho ("sem ligação") e os avisos em amarelo ("na antena"). Ao terminar, um único bloco "Resumo do Claude" (texto que o Claude escreve no fim, em `testes.json` campo `resumo`).

Paleta: fundo `#14171A`, área da placa `#0E1012`, painéis `#1C2024`, bordas `#2A3036`, texto `#E8EAED`, secundário `#9AA3AD`, placa `#1F6F4A`, cobre `#E0A458`, ok `#6FD39B`, erro `#FF8A80`, destaque `#8EC5FF`.

---

## 8. Os 3 mini projetos com ESP32

Os três ficam em `placas/` (só na máquina), cada um com `codigo/` e as 8 etapas. Em todos: o DevKit `devkit_esp32_30` (U1) encaixado em 2 barras fêmea C41417327, energia pelo USB do DevKit, o VIN (pino 15) sem solda, nenhuma peça embaixo do DevKit nem na frente da antena (a ponta dela na borda da placa ou virada pra um canto vazio) e o USB na borda, pro cabo entrar. Cada botão vai do GPIO → 1 kΩ (C713997) → botão C393938 → GND, com o pull-up de dentro; cada LED, do GPIO → resistor da conta do brilho → LED → GND. As correntes, os volts e as faixas de cada peça estão no detalhe da etapa 4 e no carrinho, com as fontes.

**Dado eletrônico (`placas/dado`).** Segura o botão e uma luz roda pela borda; solta e ele rola, cada face mais lenta, e para num número de 1 a 6 que pisca. A serial mostra `rolada N (segurou X s): deu F`. Pinos (`pinos.py`): os 7 LEDs vermelhos C779439 no desenho do dado em GPIO32, 33, 25, 26 (o do meio), 27, 13 e 4, cada um com 130 Ω (C3482538, conta do brilho médio); o botão rolar no GPIO14. Conferências: `leds_da_serial` (a face que a serial diz é a dos LEDs acesos), `duty_entre` e `serial_menos_evento`.

**Largada, o jogo de reflexo pra 2 (`placas/reflexo`).** O LED do "já!" acende com um apito num instante sorteado entre 2 e 4 s; quem apertar primeiro depois dele ganha o ponto, e quem aperta antes queima a largada (bronca grave e o LED do culpado pisca). A serial mostra o tempo em ms, o recorde e o placar; com 3 pontos sai o campeão. Tudo na fileira de baixo do DevKit: botão J1 no GPIO32, LED J1 (vermelho C779439) no GPIO33, "já!" (verde C779443) no GPIO25, apito no GPIO26, LED J2 (amarelo C779441) no GPIO27, botão J2 no GPIO14. O apito é o piezo Murata PKM13EPYH4002-B0 (C128650) com 1 kΩ em série (a Murata pede de 1 a 2 kΩ quando o piezo vai direto num CI, catálogo `buzzer_passivo.json`); o apito toca em 4 kHz (a nota em que a Murata mede o som) e a bronca fica de 1 a 2 kHz, dentro do gráfico dela. O DC no piezo durante o apito foi aceito, com o porquê no `requisitos.md`. Conferências: `pwm_freq` (4 kHz no GPIO26 depois do "já!", e a bronca entre 1 e 2 kHz), `serial_menos_evento` (o ms da serial = o aperto − a subida do GPIO25), `leds_da_serial` (quando a serial diz quem ganhou, o LED aceso é o dele) e `duty_entre` (o apito calado do preparar até o "já!"). O aperto do J1 no `gemeo.roteiro` é "já! + 300 ms", lido de um `programa.json` anterior: se o `main.py` mudar, o instante do "já!" muda e a linha tem que ser refeita.

**Luz noturna automática (`placas/luz_noturna`).** Quando o quarto escurece, o LED acende sozinho e devagar; quando clareia, apaga com folga, sem pisca-pisca. O botão troca o modo (automática, vela, sempre acesa, desligada) e a serial mostra a leitura da luz a cada 5 s, pra calibrar. O olho de luz é o divisor 3V3 → 22 kΩ (C119354) → GPIO34 → LDR GL5528 (C10081) → GND, com o 100 nF C84772 do GPIO34 pro GND colado no pino (o ESP32 Series Datasheet v5.3 mede a precisão do ADC com 100 nF no pino, Tabela 4-3, p. 43). O LED amarelo difuso C779441 no GPIO25, com 130 Ω e no máximo 0,36 do tempo aceso (`duty_max`, do `main.py`: BRILHO_MAX², 0,6²); as opções visíveis são o C779440 (lente clara) e o branco quente C7433012 (a cor dele está pendente). O botão modo no GPIO14. Os limites do `main.py` (acende acima de 1205 mV ≈ 10 lux, apaga abaixo de 827 mV ≈ 23 lux) saem da conta do divisor com o LDR do meio e estão marcados **calibrar no quarto**. A luz do quarto entra no `roteiro.json` em lux; o gêmeo não prova a luz do LED batendo no LDR. Conferências: `duty_entre` (depois de 1 lux o PWM sobe até 0,36 em uns 3 s; depois de 100 lux volta a 0) e `pwm_freq`.

---

## 9. Marcos (fazer em ordem, um por vez)

Cada marco termina com algo que o Luiz vê funcionando, testado pelo Claude.

1. **Ferramenta mínima completa**: `gerar.py` com contorno, furos (Excellon), pads, trilhas e `modelo.json`. Testar com `gerbonara` e mostrar a imagem.
2. **Bateria de testes**: `testar.py` com as etapas escrevendo `testes.json` etapa por etapa.
3. **Bancada, aba Projeto**: SVG da placa a partir do `modelo.json`, seta/mão/zoom, HUD, inspetor, destaque de net.
4. **Bancada, aba Testes**: etapas ao vivo + placa com os erros contornados + resumo final.
5. **Requisitos + aba Thinking** (modo simples primeiro).
6. **Skill**: `.claude/skills/placa/SKILL.md` com o fluxo, o formato do `placa.txt`, as regras de Gerber/Excellon e "rode testar.py antes de dizer que terminou".
7. **Placa de estudo de verdade**: biblioteca com valores de datasheet (DevKit, LED, resistor, botão, buzzer), pads passantes nos dois lados pros pinos do DevKit, máscara e serigrafia, regras reais da JLCPCB, `fabrica.zip`. **Encomendar.**
8. **Ordem nova e loja** (feito em 2026-10-24): objetivo com perguntas, blocos, carrinho com peças da JLCPCB/LCSC e desenho oficial do EasyEDA, conta do brilho, app escolhendo peça. Depois, o catálogo: a lista de compras de sempre, com a loja como double check.
9. **Laboratório** (commit 9f69dff, 2026-10-25): o programa de uma mini placa roda no PC, sem a placa.
10. **Mini placas com ESP32** (2026-10-25 e 26): o DevKit de verdade (`devkit_esp32_30`), o pino do ESP32 no lugar da pilha (etapa 4), a etapa 8 com o gêmeo, o ▶ Ligar e o ▶ Programa, e o Dado, a Largada e a Luz noturna passando nas 8 etapas. O que falta conferir está no `AGORA.md`.
11. Depois, se fizer falta: extensão do Chrome pra mandar peça de qualquer loja pro carrinho; peças de superfície (SMD) montadas pela fábrica; MCP pra o Claude consultar a bancada direto.

Fora do escopo por agora: chat embutido no app, mais de 2 camadas, Wi-Fi e Bluetooth nos projetos, gravar o MicroPython pelo app (o Montar só explica), pedir a placa na fábrica (só até a cotação), simular ponte de solda, som, luz de verdade e ruído do ADC, e o VIN no circuito do papel (a tensão dele depende da queda do SS14 e da porta USB, pendentes: a etapa 4 recusa a placa que usa o VIN).

---

## 10. Como trabalhar com o Luiz

- Um passo de cada vez. Mostre o resultado de cada passo antes do próximo.
- Código pequeno e simples, que dá pra ler e decorar. Mantenha o estilo que já existe.
- **O Claude testa, sempre.** Rode, confira e mostre o resultado (imagem quando der). O Luiz não testa na mão.
- Edite sempre o mesmo arquivo em vez de criar caminho novo.
- Respostas curtas e diretas.
- Quando explicar algo de eletrônica, explique simples e adicione a regra na skill.
- No fim de cada sessão, atualize o `AGORA.md`.
