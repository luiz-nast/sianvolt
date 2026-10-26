---
name: nova-placa
description: Começar uma placa nova (ou refazer uma) na ordem certa com o Luiz - objetivo e perguntas de gente, blocos (tipo de peça sem número), carrinho com peças de verdade da loja, e só então o desenho; com pilha ou com o ESP32 (DevKit) no meio. Use quando o Luiz pedir uma placa nova, uma ideia de circuito ou de mini placa com ESP32, ou quiser mudar o que a placa faz.
---

# Placa nova, na ordem

O Luiz não sabe eletrônica. Ele precisa ver **de onde vem cada decisão**. Nada de peça posicionada "de cabeça": primeiro o que ele quer, depois o tipo de cada peça, depois a peça de verdade da loja, por último o desenho.

## 1. Objetivo (com ele, em linguagem de gente)

- Uma frase do que a placa faz ("aperta o botão e o LED acende"; "segura o botão e o dado rola").
- As perguntas que decidem o projeto (`PERGUNTAS` em `ferramenta/blocos.py`):
  - `brilho`: fraca, média, forte = ¼, metade e o brilho que o fabricante anuncia. Com o ESP32 tem a resposta geral e o ajuste de cada LED (`por_led`); se um LED não dá conta (o verde em "forte"), o app diz "impossível neste LED" e o projeto não fica pronto até mudar.
  - `cor` (só com o ESP32): a cor de cada LED, entre as cores dos LEDs do catálogo. Pergunte; o verde e o branco ficam fracos no pino do ESP32, e a conta mostra isso.
- Pergunte; se ele não quiser escolher, sugira e marque `"quem": "sugestão do Claude"`. Ele troca no app (Processo, passo 1). Pergunta nova (duração, volume, ...) vira código: `PERGUNTAS`, com a conta que ela muda.

## 2. Blocos (tipo de peça, sem número)

Com pilha, a cadeia de funções: Energia (pilha) → Liga e desliga (botão) → Freio (resistor) → Luz (LED). Cada bloco tem uma frase de "por que ele está aí" em `BLOCOS` (`blocos.py`). Bloco novo entra lá, com a categoria do catálogo de onde a peça sai (`CATEGORIA`) e o que ela precisa conferir.

**Com o ESP32, o desenho vira uma estrela**: o bloco `cerebro` (o DevKit, ref U) no meio e cada ramo um bloco ligado num pino dele. Cada bloco ganha `pino` (o GPIO), `nome` (de gente: "LED do meio", "botão rolar") e, no resistor, `led` (o LED que ele freia) ou `para` (o botão, o som ou o olho de luz que ele atende). Blocos que só existem com o cérebro: `ldr` (olho de luz), `buzzer` (som) e `capacitor`.

- **O pino no lugar da pilha.** Não tem pilha: o USB do DevKit dá a energia, e cada pino em 1 é uma "pilha" de 3,3 V com uns 30 Ω por dentro (o 3V3 do DevKit e a estimativa do MicroPython; as fontes e a faixa estão na `eletrica` do `devkit_esp32_30`). A conta do resistor do LED usa o pino (`(pino − LED) ÷ (resistor + pino)`) e avisa quando passa da força padrão do pino.
- **GPIOs que servem pra saída** (LED, som): 4, 13, 14, 18, 19, 21, 22, 23, 25, 26, 27, 32 e 33. O olho de luz vai num pino do ADC1 que só entra: o GPIO34. Nunca saída em 34–39 (só entram), 6–11 (memória flash), 1 e 3 (serial do PC) nem 0, 2, 5, 12 e 15 (boot); 16 e 17 dão aviso (psram). O VIN (pino 15) não é usado. A etapa 4 reprova cada um desses, com as fontes do ESP32 Series Datasheet v5.3 na `eletrica` do tipo.
- **Botão**: GPIO → 1 kΩ (C713997) → botão → GND, com o pull-up de dentro. Apertado, o pino ainda lê 0 (a etapa 4 mostra os volts); com uma ponte de solda ou o pino virado em saída por engano, o 1 kΩ evita o curto. Nunca botão em 34–39 sem um resistor de fora pro 3V3.
- **Olho de luz**: o divisor 3V3 → 22 kΩ (C119354) → GPIO34 → LDR (C10081) → GND, com um 100 nF de furo do GPIO34 pro GND, colado no pino (decisão "Divisor da luz noturna": com 22 kΩ, de 1 a 100 lux cai dentro da faixa boa do ADC no LDR do meio). A conta mostra os volts por lux nos cantos do LDR. Os limites do programa saem dessa conta e ficam marcados "calibrar no quarto".
- **LDR longe do LED.** O LDR numa ponta da placa, longe dos LEDs e da ponta do DevKit onde fica o LED de energia dele; o LED da placa apontado pra fora. O gêmeo não prova a luz do LED batendo no LDR: escreva isso no `requisitos.md`, e no Montar vai a dica de cobrir o LED vermelho do DevKit com fita.
- **Som**: o piezo C128650 com 1 kΩ em série (a Murata pede de 1 a 2 kΩ, catálogo `buzzer_passivo.json`).

## 3. Carrinho (peças de verdade)

Pra cada bloco, uma peça que a loja tem em estoque e que a gente solda na mão (de furo): **primeiro do catálogo** (`ferramenta/catalogo/`, a lista de compras de sempre), conferida na loja antes de entrar no carrinho. Siga a skill `peca-da-loja`. O resistor **sai da conta** (`blocos.py`: brilho pedido → corrente pela curva do LED → resistor → valor E24 mais perto) e só é procurado com esse valor. O cérebro é o DevKit da RoboCore (`robocore:esp32-wifi-bluetooth`, tipo `devkit_esp32_30`), e as 2 barras fêmea vão junto no carrinho, sem entrar no `placa.txt`. O total aparece em R$ + US$.

Tudo fica em `placas/<nome>/projeto.json`:

```json
{"objetivo": "Lanterninha de chaveiro", "frase": "Aperta o botão e o LED acende.",
 "perguntas": {"brilho": {"resposta": "fraca", "quem": "sugestão do Claude"}},
 "blocos": [{"ref": "BT1", "bloco": "pilha", "peca": "C5365915", "quem": "sugestão do Claude"}, ...]}
```

Com o ESP32 (formato inteiro no `PROJETO.md`, 4.0):

```json
{"perguntas": {"brilho": {"resposta": "media", "quem": "sugestão do Claude"},
               "cor": {"por_led": {"D1": {"resposta": "vermelho", "quem": "sugestão do Claude"}}}},
 "blocos": [{"ref": "U1", "bloco": "cerebro", "peca": "robocore:esp32-wifi-bluetooth", "quem": "sugestão do Claude"},
            {"ref": "D1", "bloco": "led", "pino": "GPIO32", "nome": "LED A", "peca": "C779439", "quem": "sugestão do Claude"},
            {"ref": "R1", "bloco": "resistor", "led": "D1"}]}
```

`blocos.escolher(pasta, ref, codigo, quem="Luiz", *, atualizar_catalogo=True)` põe a peça no bloco e grava o projeto. O carrinho vem antes do desenho: sem `placa.txt` (ou sem a linha `peca` daquele REF) ele devolve `na_placa: False`, e a peça fica só no carrinho até o passo 4, quando o Claude escreve o `placa.txt` com o código dela. **Não** escreva linhas `peca` antes do carrinho pra ele achar. Se a placa já existe (trocar uma peça), ele troca o tipo na linha `peca` daquele REF. `atualizar_catalogo=False` (só pelo nome) não grava nada em `ferramenta/catalogo/`. Trocar um LED por outro com o + em outro furo vira as linhas `liga` dele, e o retorno diz. O app faz o mesmo quando o Luiz clica em Escolher.

## 4. Só então a placa

`placa.txt` com o código da peça do carrinho (a `peca` de cada bloco no `projeto.json`) como tipo (`peca R1 C119310 43 15`, sem valor: o valor é o da peça) e o DevKit pelo tipo da biblioteca (`peca U1 devkit_esp32_30 X Y`). Os números dos pinos são os do desenho oficial: confira os `nomes` em `placas/<nome>/pecas/<codigo>.json` antes de ligar (no LED da loja TUOZHAN o pino 2 é o +). Depois siga a skill `placa` (o DevKit, o layout, testar, foto, resumo).

`requisitos.md` ganha `verifica: brilho D1` quando tem pergunta de brilho, e todo LED leva `acende` e `nao_queima`. Com o ESP32: `pino_seguro U1`, `adc_na_faixa LDR1 <lux de decisão>` no olho de luz, `programa_ok` e `programa_acende D1`.

## 5. O programa (só com o ESP32)

Em `placas/<nome>/codigo/` (detalhes na skill `placa`): o `main.py` usa `from pinos import ...` e nunca escreve número de pino; o `roteiro.json` diz o que acontece e o que conferir; o `gemeo.roteiro` aperta os botões; o `confere.json` confere o que o roteiro não sabe. **Sorteio**: `random.seed(time.ticks_us())` na hora em que o botão é solto. Na placa sai diferente a cada vez; no gêmeo, sempre igual, e as conferências não falham ao acaso. Conferência estatística ("as 6 faces em 30 roladas") não entra.
