---
name: placa
description: Editar uma placa deste repositório (placa.txt, requisitos.md, biblioteca, o programa do ESP32 em codigo/) e gerar os arquivos de fábrica (Gerber + Excellon). Use sempre que o Luiz pedir mudança numa placa, peça nova, ligação, programa da mini placa, ou pra mandar pra fábrica.
---

# Placa

O Claude decide só a **intenção** (quais peças, onde, o que liga em quê, o que o programa faz). Contas, pinos, checagens, o `pinos.py` e o Gerber são código em `ferramenta/`. Especificação inteira: `PROJETO.md`.

**Antes de desenhar vem o projeto**: objetivo, blocos e carrinho (`projeto.json`, skill `nova-placa`). Peça que não está no carrinho não entra na placa; peça nova vem do catálogo ou da loja (skill `peca-da-loja`).

## Fluxo

1. Edite `placas/<nome>/placa.txt` (e `requisitos.md` se o objetivo mudou; o `codigo/` se a placa tem ESP32). Nada mais à mão.
2. Rode a bateria (ela também gera tudo e salva a versão), sempre com o Python do `.venv` (o `python3` do sistema não tem o `gerbonara`, e sem ele a etapa 6 falha):
   ```
   .venv/bin/python ferramenta/testar.py placas/<nome> -m "o que mudou, numa frase"
   ```
   Sem `-m`, a frase sai do diff do txt. São 7 etapas; a placa com `codigo/main.py` ganha a 8ª, **Roda o programa**. Sai com 0 quando nada falhou (etapa que pulou não é falha).
3. Falhou? Leia `testes.json` (ou a saída do comando), corrija o txt (ou o `main.py`) e rode de novo, **sozinho**, até passar ou até precisar de uma decisão do Luiz. Aviso (amarelo) não falha, mas leia: antena, psram, botão que não lê 0, nome sem lugar na serigrafia.
4. Passou da etapa 6? Olhe `saida/foto.png` antes de dizer que está bom.
5. No fim da rodada, e só no fim, escreva o resumo (2 ou 3 frases, termine com a pergunta do próximo passo):
   ```
   .venv/bin/python ferramenta/testar.py placas/<nome> --resumo "..."
   ```
6. Atualize o `AGORA.md` no fim da sessão.

**Nunca diga que terminou sem ter rodado o `testar.py`.** Mexeu no código da ferramenta (`ferramenta/`, `bancada/`)? Rode também `.venv/bin/python testes/rodar.py`: simulador (com circuitos sorteados e a mesma conta no JS do app), gerador, as etapas com cada defeito, o programa, catálogo inteiro, segurança do app e fuzz. Pra testar a ferramenta numa placa sem mexer nela, rode numa cópia fora de `placas/` (o `testar.py` regrava `testes.json`, `saida/` e `versoes/`). O Sianvolt (`python3 ferramenta/app.py`, ou o atalho "Sianvolt" no menu) se atualiza sozinho; não descreva o progresso no chat, o resumo final basta.

## Simulador

`ferramenta/circuito.py` (etapa 4 e as checagens `acende`/`nao_queima`/`brilho`/`pino_seguro`/`adc_na_faixa`) e a função `simular` em `bancada/index.html` (o ▶ Ligar e o painel; o trecho de `const GMIN` até antes de `const mA =`) são **a mesma conta em duas línguas**: análise nodal; LED aceso = joelho (`vf − r_s·i_teste`) mais `r_s` em série, os três do datasheet, entre os pinos `mais` e `menos` da peça; pilha com a `r_interna` do datasheet em série (sem ela, uma resistência mínima só pra conta); chave apertada vira fio; LDR é um resistor com os ohms da luz (`ohms_do_ldr`, nos cantos `min`/`meio`/`max`); piezo e capacitor ficam abertos (o piezo na borda do apito vira fio); pino sem net é aberto. Com o ESP32, `com_pinos(modelo, estado)` põe o chip no lugar da pilha: `~terra`, `~3V3` e um `~GPIOn` por pino (1, 0, `pullup` ou solto); o VIN não é modelado. A curva de brilho (`blocos.brilho_da_corrente` e `brilhoDaCorrente`) também existe nas duas. Mudou um, muda o outro: o `testes/test_paridade_js.py` compara os dois em centenas de circuitos sorteados, e a lanterninha dá 4,3 mA nos dois (3,0 V e 240 Ω).

## Falar com o Luiz sobre eletrônica

Ele não sabe eletrônica e quer aprender pelo app, não por despejo de números. No app e nas respostas: nome de gente (`D1 +`, `o lado A do botão`, `LED do meio · D26 · GPIO26`), uma frase por ideia, e a conta só quando ela explica alguma coisa (`(pilha − LED) ÷ resistor`, `(pino − LED) ÷ (resistor + pino)`). A faixa importa mais que o valor exato: diga o que acontece com a pilha fraca e com a nova, ou com o 3V3 no mínimo e no máximo.

## Fábrica

Só quando o Luiz pedir: suba o `saida/fabrica.zip` (ele só existe se a última rodada passou inteira) na página de cotação da JLCPCB (`https://cart.jlcpcb.com/quote`, "Add gerber file") e pare na cotação. **Nunca** salve no carrinho, faça pedido ou pague sem ele confirmar o item e o total. Placa com DevKit: antes de cotar, lembre os "confira" do DevKit (régua e folha 1:1, abaixo). Depois, registre o que aconteceu em `placas/<nome>/fabrica.json` (a aba Processo mostra):

```json
{"site": "JLCPCB", "url": "https://cart.jlcpcb.com/quote", "quando": "AAAA-MM-DD HH:MM", "versao": 1,
 "situacao": "cotação, sem pedido", "detectou": "placa de 2 camadas, 34 × 52 mm",
 "preco": "US$ 4,00 por 5 placas, fabricação em 2 dias (sem o frete)", "imagem": "fabrica-jlcpcb.jpg"}
```

## placa.txt

Uma instrução por linha, mm, origem no canto inferior esquerdo. `#` começa comentário. Este exemplo passa nas 7 etapas (conferido em 2026-10-26, numa cópia com as peças da placa de teste `testes/placas/esp32`):

```
placa 54 62                 # contorno L x A
furos cantos 3.2            # 4 furos de fixação a 3,5 mm das bordas (3,2 = M3)
peca U1 devkit_esp32_30 26.5 36   # o DevKit (tipo da biblioteca): antena na borda da esquerda, USB na da direita; as barras fêmea vão no carrinho, não aqui
peca R1 resistor_axial 14.25 17 130   # tipo da biblioteca: VALOR em ohms (130, 4.7k, 1k); peça da loja já traz o valor
peca D1 C779439 5.22 17     # REF TIPO X Y; TIPO = código da LCSC (peça do carrinho) ou um tipo de biblioteca.py
peca R2 resistor_axial 37.11 18.5 1k
peca SW1 C393938 48.5 18.5  # tudo abaixo da fileira de baixo do DevKit, nada embaixo dele
liga U1.6 R1.2              # REF.PINO ou nome de net (GND); U1.6 é o GPIO32 (D32)
liga R1.1 D1.2              # no C779439 o + é o pino 2
liga D1.1 GND               # vai até o pino de GND mais perto
liga U1.11 R2.1             # GPIO14 (D14) → 1 kΩ → lado A do botão; o lado B no GND
liga R2.2 SW1.1
liga SW1.3 GND
```

Pelo `corpo` e pelas `zonas` do tipo (com as fontes na biblioteca), o DevKit em 26,5 36 ocupa de 0,6 a 52,4 mm em x e de 21,9 a 50,1 mm em y: a zona da antena começa na borda da esquerda, a do USB termina em 53,8 mm (a placa tem 54), e as outras peças ficam abaixo de 21,9. No projeto de verdade o resistor também sai do carrinho: `peca R1 C3482538 14.25 17` (o 130 Ω da loja, sem valor).

- Os pinos de uma peça da loja são os do desenho oficial: veja os `nomes` em `placas/<nome>/pecas/<codigo>.json` antes de ligar (no LED `C779439` o + é o pino **2**; no `C7433012` é o **1**).
- Trilha de 0,3 mm. O roteador (`gerar.rotear`) tenta a reta; se algo de outra net está no caminho, desvia em L ou Z e, se precisar, passa pro outro lado da placa por uma via (furo 0,4, anel 0,8, coberta pela máscara), sempre a 0,25 mm do cobre das outras nets e a 0,5 mm da borda e dos furos de fixação, e nunca pela zona da antena do DevKit. Pad de superfície só tem cobre em cima. Nada coube: fica o caminho mais curto e a etapa 3 acusa o curto; aí mude as peças de lugar.
- A etapa 3 também para quando uma peça sai da placa, um pino encosta no furo de fixação, os corpos de duas peças se sobrepõem ou o furo de uma peça fica embaixo do corpo de outra deitada (não dá pra soldar). O furo embaixo do DevKit não conta (ele fica no alto, na barra fêmea), mas o corpo de uma peça embaixo dele ainda dá "uma em cima da outra": embaixo do DevKit, só trilhas e vias.
- O nome de cada peça vai pro primeiro lado livre (em cima, embaixo, à direita, à esquerda); sem lado livre, a etapa 5 avisa. O `modelo.json` guarda o lugar (`nome_pos`) e a bancada desenha igual.
- Uma ligação entre nets com nome diferente (GND com 3V3) é erro.

## O DevKit do ESP32 (`devkit_esp32_30`)

O DOIT ESP32 DevKit V1 de 30 pinos da RoboCore. O `esp32_devkit` antigo da biblioteca é só do laboratório: não use em placa nova.

- **Pinos**: vista de cima, antena à esquerda, USB à direita. 1 a 15 na fileira de baixo (EN no 1, VIN no 15), 16 a 30 na de cima (3V3 no 16, D23 no 30); GND no 14 e no 17 (ligados por dentro). O GPIO de cada pino está nos `nomes` do tipo (`U1.6` = GPIO32, `U1.11` = GPIO14, `U1.4` = GPIO34, `U1.8` = GPIO25) e o que está escrito no DevKit, na `serigrafia` (D32, D14, D34, D25). No `placa.txt` liga-se pelo número do pino (`U1.6`); pro Luiz, fala-se o nome (LED A · D32 · GPIO32).
- **Zonas** (`zonas` do tipo, em mm a partir do centro da peça): `antena` — o roteador não passa trilha nem via nela, e a etapa 3 avisa (não falha) se pad, trilha ou via de outra peça entrar; ponha a ponta da antena na borda da placa ou virada pra um canto vazio. `usb` — a ponta do USB na borda, pro cabo entrar.
- **VIN: não soldar.** O pino 15 fica sem solda e sem ligação: qualquer peça no `U1.15` faz a etapa 4 falhar ("VIN usado: não sei ligar no papel"). A serigrafia escreve "VIN NAO SOLDAR" do lado dele.
- **Barras fêmea**: as 2 barras 1×15 (C41417327, alternativa C22373901) vão no `acompanha` do tipo, entram no carrinho e **nunca** no `placa.txt` (peça em cima de peça nos mesmos furos faria a etapa 3 falhar).
- **Layout**: ponha cada peça do lado da fileira que ela usa (uma peça de baixo ligada na fileira de cima faz a trilha atravessar o DevKit entre pinos, e costuma dar curto); nada embaixo dele nem na frente da antena.
- **Confira** (o app mostra no Montar e na Fábrica): medir 25,4 mm do centro do EN ao centro do D23 com o DevKit na mão (a medida vem de desenho e foto de terceiros, pendente de régua); imprimir `saida/imprimir_1x1.svg` em 100% (a régua de 50 mm da folha confere a impressão) e espetar o DevKit no papel; depois de soldar, procurar ponte de solda.

## O programa (`codigo/`) e a etapa 8

Só na placa com o DevKit. Tudo em `placas/<nome>/codigo/`:

- `main.py` (MicroPython): **nunca** escreve número de pino. `from pinos import D1, SW1` e `Pin(D1, Pin.OUT)`.
- `pinos.py`: **gerado** a cada rodada a partir do `placa.txt` ("gerado pelo Sianvolt, não edite"): cada peça ligada num GPIO, direto ou por UM resistor, vira um nome (`D1 = 32  # LED A, U1 pino 6, D32, pelo R1`). Mudou a ligação no `placa.txt`, o `pinos.py` muda junto. Nunca crie um `placa.py` (o laboratório escreve por cima). Só ele: `.venv/bin/python ferramenta/programa.py placas/<nome> --pinos`.
- `roteiro.json`: o roteiro de teste do laboratório (formato em `laboratorio/README.md`): `tempo` (s de placa), `precisa`, `entradas` (a luz do olho de luz: `{"t": 5, "luz": "LDR1", "lux": 1}`) e `confere` (pino ou PWM num instante, `serial` com `desde`/`ate`, `trocas`, `estado`). Confira no meio dos intervalos, não na borda.
- `gemeo.roteiro`: os apertos de botão de verdade do circuito, `de 0,5 s a 1,2 s aperta SW1`. **Nunca** linha de lux aqui (o `programa.py` recusa): a luz mora no `roteiro.json`.
- `confere.json`: o que o roteiro do laboratório não confere, com 4 tipos fechados: `leds_da_serial` (a face que a serial diz = os LEDs acesos), `pwm_freq` (a frequência do PWM depois de um evento), `serial_menos_evento` (o ms que a serial diz = o tempo desde o evento) e `duty_entre` (o duty entre dois instantes). Formato no `PROJETO.md` (4.5) e no docstring do `programa.py`.
- Conta: tempo, mV e o que sai na serial em inteiros (`time.ticks_ms()`, `time.ticks_diff()`, `%d`). O float do gêmeo é de 64 bits e o da placa, de 32 (`laboratorio/README.md`, "Float"): um `print` de float ou um `==` entre floats que passa no gêmeo pode sair diferente na placa.
- Sorteio: `random.seed(time.ticks_us())` na hora em que o botão é solto. No gêmeo o relógio é virtual e o sorteio sai sempre igual, então as conferências não falham ao acaso. Mudou o `main.py`? Os instantes que dependem do sorteio (o "já!" da Largada) mudam, e o `gemeo.roteiro` tem que ser refeito a partir do `programa.json` novo.

A etapa 8 gera o `pinos.py`, roda o programa no gêmeo do laboratório (`programa.rodar`, numa cópia em `saida/programa/`) e grava `saida/programa.json`. Falha com erro no `main.py` (mostra a linha), programa travado, conferência que não bate e aviso de LED queimando, corrente alta, pino de boot, pino da flash ou leitura flutuando; ADC fora da faixa boa só avisa. **Pula** sem o MicroPython do PC (`laboratorio/.ferramentas/`, só na máquina): `python3 laboratorio/lab.py instalar gemeo`. Só o programa: `.venv/bin/python ferramenta/programa.py placas/<nome>`; do jeito do app (sem conferências, `saida/programa_livre.json`): `--livre --entradas '{"apertos": [{"ref": "SW1", "de": 1.0, "ate": 1.2}], "luz": [{"ref": "LDR1", "t": 2, "lux": 1}]}'`. Não edite nada em `laboratorio/` pra fazer uma placa passar.

## requisitos.md

```
# Objetivo: título
Uma frase.

## R1 Título do requisito
pecas: D1 R1
verifica: ligado R1.2 D1.2      # existe | ligado A B | separado A B | sem_pino_solto | acende REF | nao_queima REF | brilho REF
- sub-requisito em texto
```

`brilho D1`: o LED dá o nível que o Luiz pediu em `projeto.json` (fraca, média ou forte, o mais perto pela curva do datasheet; com o ESP32, o ajuste daquele LED, se tiver). Com o ESP32: `pino_seguro U1` (nenhum pino acima da força padrão, o 3V3 no orçamento, nenhuma regra de pino quebrada), `adc_na_faixa LDR1 10 23` (nos lux em que o programa decide, nos cantos do LDR e do 3V3, o ADC lê dentro da faixa boa), `programa_ok` (a etapa 8 passou) e `programa_acende D1` (o LED acendeu no programa). Sem a etapa 4 ou a 8, a checagem fica "?". Todo LED leva `acende` e `nao_queima`. O status é calculado pelo `testar.py`. Nunca escreva status à mão. Checagem nova vira código em `testar.py` (`CHECAGENS`, `checar`).

## Biblioteca

Peça nova sai do catálogo (`ferramenta/catalogo/`) ou da loja (skill `peca-da-loja`): o desenho é o oficial do EasyEDA e o que a loja não diz entra no `conferido` da peça, no catálogo. A `ferramenta/biblioteca.py` fica pras peças de antes, de exemplo e as que não vêm da LCSC (o DevKit): `tipo -> pinos (dx, dy, pad[, net]), furo, corpo, juntos, nomes, eletrica, compra, fonte` e, quando precisa, `serigrafia`, `cuidados`, `zonas`, `acompanha` e `confira` (o `gerar.montar` passa esses pra peça). **Toda peça leva `nomes`** pros pinos (`+`, `−`, `A`/`B`, `lado 1`, `GPIO32`): o Luiz não sabe o que é "pino 1", e o app mostra o nome. `eletrica` é o modelo do simulador; sem ele a etapa 4 pula. `juntos` = pinos ligados por dentro da peça (botão 1-2 e 3-4; os dois GND do DevKit): ligar os dois lados do botão no mesmo pino deixa ele em curto. **Nenhum número inventado**: medidas vêm do datasheet da peça escolhida, com o link e a página em `fonte` (ou `fontes`, uma lista por campo, como na `eletrica` do DevKit). `fonte: None` = exemplo: a bancada avisa e o `fabrica.zip` não é gerado. Número que falta conferir mas não segura a fábrica vai em `eletrica["pendentes"]` (cada item começa pelo assunto: `"porta USB: ..."`), e o app mostra; o `pendente` da peça segura a fábrica. Não sabe a medida? Pergunte ou deixe pendente. Peça nova: tire pinos, pads e furo do footprint oficial do KiCad (`.kicad_mod` bruto do GitLab, y invertido, origem no centro do corpo) e confira com o datasheet.

## Regras de formato (já aprendidas)

- Gerber: `%FSLAX46Y46*%` e `%MOMM*%`, coordenadas em milionésimos de mm (arredondar, não truncar), `G01*` antes de desenhar, `D02` move, `D01` desenha, `D03` carimba pad, `M02*` no fim. Aberturas a partir de `D10`.
- Excellon: `M48`, `METRIC,TZ`, ferramentas `T1C3.200`, **`G90` antes do `%`** (fora do cabeçalho o leitor reclama), `M30` no fim. Furo com cobre (PTH) e sem cobre (NPTH) em arquivos separados.
- Máscara: arquivo com `%TF.FilePolarity,Negative*%` (desenhar = abrir); abertura 1:1 com o pad.
- Serigrafia: texto com a fonte de traços de `letras.py` (só maiúsculas, sem acento: "VIN NAO SOLDAR"), recortado pra ficar a 0,15 mm dos pads e dentro da placa.
- Nomes no padrão do KiCad (`placa-F_Cu.gbr`, `placa-Edge_Cuts.gbr`, `placa-PTH.drl`, `placa-NPTH.drl`): o gerbonara e a fábrica reconhecem sozinhos.
- A folha `saida/imprimir_1x1.svg` (a placa em mm de verdade, com a régua de 50 mm) fica fora do `fabrica.zip`.
- Regras da fábrica ficam em `testar.py`, com o link da página da JLCPCB. Mudou a página? Atualize o número e a data.

## Eletrônica (regras simples, pra explicar pro Luiz)

- LED sempre com resistor em série; sem ele, o LED queima. O `+` (ânodo, perna comprida) muda de número conforme a peça: olhe os `nomes`.
- Quem manda no brilho é a **corrente**, não a voltagem: a pilha empurra, o LED pede uns 1,9 V (o joelho do C779439, da curva do datasheet), o resistor freia o resto. Resistor menor, mais luz e pilha dura menos.
- Corrente do LED = (pilha − LED) ÷ (resistor + o que a pilha e o LED freiam sozinhos). Lanterninha com brilho fraco: (3,0 − 1,9) ÷ (240 + 13,5) ≈ 4,3 mA, ≈ 27% do brilho do anúncio.
- Pilha CR2032: 3,0 V nominal, fraca em 2,0 V; o fabricante só testou até ~6,8 mA (pulsos de 2 s). Acima disso funciona, mas rende menos. Teste sempre a faixa toda, não só o valor nominal.
- Botão de 4 pinos: 1-2 são o mesmo lado, 3-4 o outro. Ligar a pilha e o resistor no mesmo lado deixa o LED sempre aceso (a checagem `separado` pega).
- GND é o terra, o 0 V de referência. Todo GND da placa é a mesma net.
- Furo de fixação não tem cobre; cobre perto dele conta como borda (0,2 mm).
- **Com o ESP32, o pino é a pilha.** Em 1 ele dá o 3V3 do DevKit (de 3,201 a 3,399 V pelo datasheet do AMS1117, p. 2, só com VIN ≥ 4,8 V e o AMS1117 original; a queda do SS14 e a porta USB estão pendentes) com uns 30 Ω por dentro (estimativa do MicroPython quickref, não é datasheet). A conta é `(pino − LED) ÷ (resistor + pino)`.
- Cada pino tem uma **força padrão** de ~20 mA (ESP32 Series Datasheet v5.3, nota 8 da tabela IO_MUX, p. 62): não é o limite de dano, mas a etapa 4 reprova acima dela. Todos os pinos juntos com o resto da placa saem do 3V3, e a etapa 4 compara a soma com o orçamento de 0,5 A (1 A do AMS1117, p. 1, menos os 0,5 A que a Espressif reserva pro módulo, datasheet do WROOM-32, Tabela 13).
- **Botão no ESP32**: GPIO → 1 kΩ → botão → GND, com o pull-up de dentro (45 kΩ, DS v5.3, Tabela 5-3). Apertado, o pino fica em ~0,07 V (a etapa 4 calcula), abaixo do 0,25 × VDD em que ele ainda lê 0 (mesma tabela). Se o programa virar o pino em saída por engano, o 1 kΩ segura a corrente em 3,3 mA no máximo (3,3 V ÷ 1 kΩ), em vez de um curto.
- **Pinos que não servem pra saída**: GPIO34 a 39 só entram e não têm pull-up de dentro (DS v5.3, Tabela 6-1, nota 2: botão neles só com pull-up de fora); GPIO6 a 11 são da memória flash; GPIO1 e 3 são a serial do PC; GPIO0, 2, 5, 12 e 15 decidem o boot; GPIO16 e 17 dão aviso (psram nos módulos WROVER). As fontes de cada lista estão na `eletrica` do `devkit_esp32_30`.
- **Olho de luz (LDR)**: sozinho ele é só um resistor que muda com a luz. Com um resistor fixo do 3V3 pro pino e o LDR do pino pro GND, vira uma tensão que o ADC lê: no escuro o LDR sobe e a tensão sobe junto. O ADC com 11 dB lê bem de 0,15 a 2,45 V (DS v5.3, Tabela 4-4, p. 44), e o ESP32 mede essa precisão com 100 nF no pino (Tabela 4-3, p. 43). Use um pino do ADC1 (GPIO32 a 39, DS v5.3, Tabela 4-6, p. 46): o ADC2 é usado pelo Wi-Fi e não lê com ele ligado (MicroPython quickref do ESP32, seção ADC: "ADC block 2 is also used by WiFi", https://docs.micropython.org/en/latest/esp32/quickref.html).
- **Piezo (som)**: vai com um resistor em série; a Murata pede de 1 a 2 kΩ quando o piezo vai direto num CI (PKM13EPYH4002-B0, catálogo `buzzer_passivo.json`). Em DC ele é aberto: só apita com o pino ligando e desligando (PWM).
