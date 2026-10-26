# Laboratório de mini placas

Aqui a gente testa o programa de uma placa (ESP32, Arduino Nano...) **sem ter a placa na mão**.
Você escreve o `main.py` (MicroPython) ou o `.ino` (Arduino), o laboratório roda num emulador ou num "gêmeo"
no PC e mostra o que os pinos e a serial fizeram, com hora. Serve pro Luiz e pro Claude, sozinho, sem hardware.

Tudo roda de `~/sianvolt` com o Python do sistema, só com a biblioteca padrão:
`python3 laboratorio/lab.py <comando>`. O que é baixado fica em `laboratorio/.ferramentas/` e o que é gerado
em `laboratorio/build/` (os dois fora do git). Nada vai pro `/tmp`.

## 1. As 5 placas (e uma reserva)

Saída de `python3 laboratorio/lab.py placas --md` em 2026-10-25. O preço vem do catálogo
(`ferramenta/catalogo/placa_desenvolvimento.json`), não é copiado: rode de novo pra ver o de hoje.

| Placa | Chip | Rádio | Dormindo (chip) | Preço BR (com estoque) | Loja | Visto | Papel | Testa com |
|---|---|---|---|---|---|---|---|---|
| **ESP32 DevKit** `esp32` | ESP32 (2 núcleos Xtensa LX6, 240 MHz, 520 KB SRAM, 4 MB flash); o chip muda com o módulo: ESP32-D0WDQ6 no WROOM-32 (o da oferta mais barata), ESP32-D0WD-V3 no WROOM-32E | Wi-Fi 4 (802.11 b/g/n), Bluetooth clássico e BLE | 10 µA | R$ 42,90 | [RoboCore](https://www.robocore.net/wifi/esp32-wifi-bluetooth) | 2026-10-24 | a de todo dia | MicroPython: gemeo, qemu · Arduino: nativo |
| **ESP32-C3 SuperMini** `c3` | ESP32-C3 (1 núcleo RISC-V, 160 MHz, 400 KB SRAM, 4 MB flash no chip) | Wi-Fi 4 (802.11 b/g/n) e BLE 5 (sem Bluetooth clássico) | 5 µA | R$ 31,46 | [Usinainfo](https://www.usinainfo.com.br/esp32/esp32-c3-super-mini-com-wifi-e-bluetooth-com-usb-c-8967.html) | 2026-10-24 | a barata e pequena | MicroPython: gemeo, qemu · Arduino: nativo |
| **ESP32-S3 DevKitC-1** `s3` | ESP32-S3 (2 núcleos Xtensa LX7, 240 MHz, 512 KB SRAM); a N8R2 do preço: módulo ESP32-S3-WROOM-1, 8 MB de flash e 2 MB de PSRAM quad | Wi-Fi 4 (802.11 b/g/n) e BLE 5 (sem Bluetooth clássico) | 7 µA | R$ 69,08 | [Usinainfo](https://www.usinainfo.com.br/esp32/esp32-s3-devkitc-1-n8r2-8mb-flash-com-wifi-e-bluetooth-com-usb-c-8679.html) | 2026-10-24 | a potente | MicroPython: gemeo · Arduino: nativo |
| **ESP32-C6 SuperMini** `c6` | ESP32-C6 (RISC-V 160 MHz + núcleo LP 20 MHz, 512 KB SRAM, 4 MB flash) | Wi-Fi 6 (802.11ax, com TWT), BLE 5, Zigbee e Thread | 7 µA | R$ 54,84 | [Usinainfo](https://www.usinainfo.com.br/esp32/esp32-c6-super-mini-4mb-wi-fi-6-ble-zigbee-thread-usb-c-9162.html) | 2026-10-24 | a de bateria e casa conectada | MicroPython: gemeo, qemu (roda como C3) · Arduino: nativo |
| **Arduino Nano V3** `nano` | ATmega328P (AVR 8 bits, 16 MHz, 2 KB SRAM, 32 KB flash) | nenhum | 0,1 µA (1,8 V; a 5 V gasta mais) | R$ 28,90 | [RoboCore](https://www.robocore.net/placa-arduino/placa-nano-v3-com-cabo-usb-para-arduino) | 2026-10-24 | a pra aprender (e a mais fiel) | Arduino: simavr, avr8js, nativo |
| **Raspberry Pi Pico** `pico` (reserva) | RP2040 (2 núcleos Cortex-M0+, 133 MHz, 264 KB SRAM, 2 MB flash) | nenhum (o Pico W tem Wi-Fi) | 0,8 mA (a placa inteira) | R$ 39,90 | [Eletrogate](https://www.eletrogate.com/raspberry-pi-pico) | 2026-10-24 | reserva fora do top 5 | MicroPython: rp2040js · Arduino: rp2040js |

Preço: a oferta em reais mais barata com estoque em ferramenta/catalogo/placa_desenvolvimento.json (coluna Visto = o dia em que a loja foi lida). Dormindo: o deep sleep do chip, do datasheet; a placa de desenvolvimento inteira gasta bem mais (regulador, LED, conversor USB).

O papel de cada uma (os números do chip são dos datasheets; os cuidados estão em `nucleo/placas.py`):

- **esp32, a de todo dia**: a com mais oferta, mais tutorial e mais bem emulada; já é a DevKit da placa de
  estudo. Cuidados: é 3,3 V (5 V num pino queima); GPIO34 a 39 só leem; com Wi-Fi ligado, analógico só no
  ADC1 (GPIO32 a 39). O LED do laboratório fica no GPIO23 porque o GPIO2 é pino de boot. O chip muda com o
  módulo: a oferta mais barata (RoboCore) é um ESP32-WROOM-32, "versão tradicional, sem o sufixo", segundo a
  equipe na [página da loja](https://www.robocore.net/wifi/esp32-wifi-bluetooth), com o chip ESP32-D0WDQ6, e
  a Espressif marca esse módulo como NRND, "não recomendado pra projeto novo"
  ([datasheet do WROOM-32 v3.8](https://documentation.espressif.com/esp32-wroom-32_datasheet_en.pdf)). Pra
  aprender e testar ele serve; na placa final, use o WROOM-32E (chip ESP32-D0WD-V3).
  [datasheet do ESP32](https://documentation.espressif.com/esp32_datasheet_en.pdf),
  [DevKitC](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp32-devkitc/user_guide.html)
- **c3, a barata e pequena**: a placa com Wi-Fi mais barata do catálogo. Cuidados: sem Bluetooth clássico;
  GPIO2/8/9 são de boot; e alguns lotes de SuperMini vendidos no AliExpress têm o cristal perto demais da
  antena e o Wi-Fi quase não pega. Isso é coisa de lote, não de toda C3: num
  [tópico do fórum Arduino](https://forum.arduino.cc/t/esp32-c3-super-mini-wifi-test-not-working-solved/1440107)
  alguém aponta esses lotes (post 4), mas ali o problema era o nome da rede em branco no código (post 14). Se
  não conectar nem perto do roteador, confira o código e depois desconfie da placa.
  [datasheet](https://documentation.espressif.com/esp32-c3_datasheet_en.pdf)
- **s3, a potente**: PSRAM, USB de verdade (vira teclado, mouse, pendrive), tela e câmera. A do preço é a
  **N8R2**: módulo ESP32-S3-WROOM-1, "8MB SPI Flash" e "2 MB QD" de PSRAM (quad), segundo a
  [Usinainfo](https://www.usinainfo.com.br/esp32/esp32-s3-devkitc-1-n8r2-8mb-flash-com-wifi-e-bluetooth-com-usb-c-8679.html).
  Cuidados: o preço muda muito com a versão e a loja (a N16R8, de 16 MB e 8 MB de PSRAM octal, sai bem mais
  cara no catálogo); nas versões R8 (N16R8, N8R8) os GPIO35-37 ficam presos à PSRAM octal, na N8R2 ficam livres
  ([DevKitC-1](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.1.html)).
  [datasheet](https://documentation.espressif.com/esp32-s3_datasheet_en.pdf)
- **c6, a de bateria e casa conectada**: não é o chip dormindo que ganha (no deep sleep o C6 gasta 7 µA e o
  C3, 5 µA, pelos datasheets): é o rádio. O Wi-Fi 6 tem o TWT ("target wake time": o aparelho combina com o
  roteador quando vai acordar e o rádio dorme no meio), e o C6 fala Zigbee e Thread (802.15.4, a base do
  Matter), redes feitas pra sensor de bateria ([datasheet](https://documentation.espressif.com/esp32-c6_datasheet_en.pdf),
  páginas de recursos do Wi-Fi e do 802.15.4). Pra bateria de verdade, a placa final leva o módulo
  ESP32-C6-MINI-1 do catálogo com regulador de baixo consumo, não a SuperMini: a placa de desenvolvimento
  inteira (regulador, LED, USB) gasta muito mais que o chip.
- **nano, a pra aprender**: a mais barata, 5 V, e a mais fiel no emulador (o ATmega328P roda instrução por
  instrução). Sem rádio. Cuidado: a oferta da RoboCore diz "Microcontrolador: ATMega328P ou ATmega328PB"
  ([loja](https://www.robocore.net/placa-arduino/placa-nano-v3-com-cabo-usb-para-arduino)); o simavr e o avr8js
  emulam o 328P, e o 328PB tem periféricos a mais e outra assinatura: a fidelidade depende de qual chip vier.
  [datasheet do ATmega328P](https://ww1.microchip.com/downloads/aemDocuments/documents/MCU08/ProductDocuments/DataSheets/ATmega48A-PA-88A-PA-168A-PA-328-P-DS-DS40002061B.pdf),
  [original na loja da Arduino](https://store.arduino.cc/products/arduino-nano)
- **pico (reserva)**: fica de reserva, fora do top 5. Dormindo (DORMANT), a placa inteira gasta 0,8 mA a 25 °C.
  [datasheet](https://pip-assets.raspberrypi.com/categories/610-raspberry-pi-pico/documents/RP-008307-DS-2-pico-datasheet.pdf)

Os números de rádio e de consumo dormindo da tabela são dos datasheets (ESP32 10 µA, C3 5 µA, S3 7 µA, C6 7 µA
no deep sleep, só o chip; ATmega328P 0,1 µA em power-down a 1,8 V). Consumo de verdade, com a placa inteira,
nenhum motor mede: só a placa e um multímetro.

Por que ficaram de fora:

- **ESP8266** (D1 Mini, NodeMCU): a Espressif marcou o chip ESP8266EX inteiro como NRND, "não recomendado
  pra projeto novo" ([datasheet v7.1](https://documentation.espressif.com/0a-esp8266ex_datasheet_en.pdf)); da
  ESP32 só saiu de linha o módulo WROOM-32 antigo, e o WROOM-32E segue. A C3 SuperMini custa o mesmo ou menos
  (D1 Mini R$ 32,90 na [Eletrogate](https://www.eletrogate.com/wemos-d1-mini-pro-wifi-esp8266)) e é melhor em
  tudo. E não tem emulador oficial que sirva pra testar programa: nem o QEMU da Espressif
  ([só ESP32, S3 e C3](https://github.com/espressif/esp-toolchain-docs/blob/main/qemu/README.md)) nem o
  Wokwi ([lista](https://docs.wokwi.com/getting-started/supported-hardware)) têm ESP8266; o que existe são
  máquinas esp8266 em versões não oficiais do QEMU, com poucos periféricos (não testamos).
- **CH32V003**: nenhuma placa com ele no catálogo, e nenhum emulador local oficial (o Wokwi também não tem).
  Fonte do chip: [openwch no GitHub](https://github.com/openwch/ch32v003).
- **XIAO (Seeed) C3 e C6**: sem estoque no Brasil quando olhamos
  ([XIAO C3, R$ 59,90](https://www.robocore.net/seeed-studio/seeed-studio-xiao-esp32c3),
  [XIAO C6, R$ 69,90](https://www.robocore.net/seeed-studio/seeed-studio-xiao-esp32c6)); o chip é o mesmo
  da SuperMini, que custa menos.

## 2. Testar sem placa: os motores

Um **motor** é o jeito de rodar o programa. Cada placa tem os seus, em ordem de preferência (`lab.py placas`).

| Motor | Placas e linguagem | O que é de verdade | O que é de mentira | 3 s de placa levam | RAM |
|---|---|---|---|---|---|
| `gemeo` | esp32, c3, s3, c6 · MicroPython | a linguagem (MicroPython 1.29 compilado pro PC), as regras de pino do datasheet (só-entrada, boot, ADC2 com Wi-Fi), os timers que existem (4 no ESP32 e no S3, 2 no C3 e no C6), a serial nos dois sentidos, e com `--circuito` a corrente do `ferramenta/circuito.py` | o chip, o tempo (relógio virtual: o código Python não gasta tempo, só sleep, pino, relógio e serial), o Wi-Fi (faz de conta), o ADC (sem ruído), o float (de 64 bits, e na placa é de 32: abaixo), a memória (o heap tem o tamanho da placa: ESP32 e C3 medidos no qemu, S3 e C6 estimados; mas no PC cada objeto ocupa até 2x mais e o heap é um bloco só) | 0,01 s | 3 MB |
| `qemu` | esp32, c3 · MicroPython (c6 roda como C3: sem o rádio, sem o núcleo LP, e o GPIO18/19 do C6 vira o 10/11 do C3) | o MicroPython oficial no chip emulado: CPU, memória, timers, UART, o float de 32 bits; o PWM pelo LEDC emulado só no ESP32 | no C3 o PWM (o QEMU não emula o LEDC do C3: o laboratório remonta o duty das escritas nos registradores), ler pino (o GPIO do QEMU só tem o strap: entrada e pull-up vêm do roteiro), o ADC (faz de conta), Wi-Fi e Bluetooth (não existem); relógio do PC, não é preciso por ciclo; a serial não tem limite de baud (o laboratório avisa quando passa de 115200); o S3 não sobe (trava no boot, PSRAM) | 4,5 s (C3), 7 s (ESP32) | 48 MB (C3), 270 MB (ESP32) |
| `simavr` | nano · Arduino | o chip: o `.elf` do arduino-cli rodando no ATmega328P instrução por instrução; PWM lido dos timers | a tensão nos pinos; pino solto lê 0 (na placa fica no ar); o ADC arredonda pra baixo | ~1 s | 3 MB |
| `nativo` | as 4 ESP e o nano · Arduino | o seu código C++ compilado pro PC (g++ + EpoxyDuino), os números do Arduino de cada placa (ADC de 12 bits a 3,3 V nas ESP, 10 bits a 5 V no Nano, o PWM do `analogWrite`) | o chip, o tempo (relógio virtual), o `int` (32 bits; no Nano é 16!), o Wi-Fi (`WiFi.h` "conecta" em 1,5 s); sem FreeRTOS, registrador nem biblioteca de fora | 0,2 s (com cache) | 4 MB |
| `avr8js` | nano · Arduino (segundo motor, pra conferir o simavr) | o mesmo `.elf` no ATmega328P emulado em JavaScript (precisa de node) | o pull-up fomos nós que pusemos; o resto como no simavr | 2 s | 80 MB |
| `rp2040js` | pico · MicroPython e Arduino (arduino-pico) | o RP2040 emulado em JavaScript com o firmware oficial (precisa de node) | sem flash (`open()` dá `ENODEV`), sem Pico W (sem rádio); pull-up e leitura de pino de saída fomos nós que pusemos | 8 s (MicroPython), 1 s (Arduino) | 105 MB |

Fontes: [QEMU da Espressif](https://github.com/espressif/esp-toolchain-docs/blob/main/qemu/README.md)
(o que ele emula: a linha "LEDC" da tabela tem ✅ só no ESP32), [simavr](https://github.com/buserror/simavr), [EpoxyDuino](https://github.com/bxparks/EpoxyDuino),
[avr8js](https://github.com/wokwi/avr8js), [rp2040js](https://github.com/wokwi/rp2040js). Os tempos e a RAM
foram medidos aqui (PC de 8 núcleos) com o `pisca` (3 s de placa) no `lab.py testar`.

**Float: o gêmeo conta com mais casas que a placa.** O MicroPython do PC usa float de 64 bits (`MICROPY_FLOAT_IMPL_DOUBLE` em `ports/unix/variants/mpconfigvariant_common.h`) e o das ESP, de 32 bits (`MICROPY_FLOAT_IMPL_FLOAT` em `ports/esp32/mpconfigport.h`, o mesmo pro ESP32, o C3, o S3 e o C6), no [código do MicroPython v1.29.0](https://github.com/micropython/micropython/blob/v1.29.0/ports/esp32/mpconfigport.h). O mesmo `main.py`, rodado em 2026-10-26 no `gemeo` e no `qemu` (do ESP32 e do C3):

| Conta | `gemeo` | `qemu` (como na placa) |
|---|---|---|
| `print(0.1 + 0.2)` | `0.30000000000000004` | `0.3` |
| `print(16777217.0)` | `16777217.0` | `16777216.0` (2²⁴ + 1 não cabe no float de 32 bits) |
| `40 * 1.25` onze vezes (o freio do Dado: passou de 400 ms, ele para) | `465.66128730773926` | `465.6613` |

Nas mesmas contas do Dado (11 faces) e da Luz noturna (duty 23592 no fim da subida) os dois motores deram igual, e a Largada não faz conta com float. Um programa que imprime float na serial, compara float com `==` ou soma tempo em float pode sair diferente na placa: confira no `qemu`, ou faça a conta em inteiros (`time.ticks_ms()`, mV, duty).

**O que a placa recusa, o gêmeo recusa igual.** O `time` e o `PWM` do gêmeo seguem as regras do MicroPython 1.29
das ESP ([`extmod/modtime.c`](https://github.com/micropython/micropython/blob/v1.29.0/extmod/modtime.c) e
[`ports/esp32/machine_pwm.c`](https://github.com/micropython/micropython/blob/v1.29.0/ports/esp32/machine_pwm.c)),
com as mesmas mensagens: `sleep_ms`, `sleep_us`, `ticks_add` e os números do PWM só aceitam int
(`time.sleep_ms(40 * 1.25)` dá `TypeError: can't convert float to int`; o certo é `time.sleep_ms(int(espera))`);
`duty_u16` vai de 0 a 65535, `duty` de 0 a 1023, `duty_ns` até o período e `freq` de 1 Hz a 40 MHz (fora disso,
`ValueError`, e não um número cortado calado); `ticks_add` com o delta de 2²⁹ ou mais, pra frente ou pra trás, dá
`OverflowError`; e o `duty_ns` dentro do `PWM(...)` novo dá `RuntimeError: PWM is inactive` (no 1.29 ele só
funciona depois, com `pwm.duty_ns(...)`). O `ensaios/recusa` confere tudo isso, e o `testa.py` compara as linhas
dele com o `qemu`, que roda o firmware oficial.

**Nenhum motor testa**: Wi-Fi e Bluetooth de verdade, ADC de verdade (o ruído; no ESP32 clássico, "±6%
differences in measured results between chips", segundo o
[datasheet do ESP32](https://documentation.espressif.com/esp32_datasheet_en.pdf)), consumo, tensão e corrente
reais (o `gemeo` com `--circuito` chega perto) e tempo de CPU exato. Isso só a placa mostra.

**Wokwi** (o simulador mais completo, com C6 e Pico W) **não está no laboratório**: a simulação roda na nuvem
deles, pede uma conta e um token do Luiz (a variável `WOKWI_CLI_TOKEN`,
[uso do CLI](https://docs.wokwi.com/wokwi-ci/cli-usage)). Os planos ([preços](https://wokwi.com/pricing),
[limites do CI](https://docs.wokwi.com/wokwi-ci/getting-started)), vistos em 2026-10-25, todos com cobrança anual:

| Plano | Preço | Minutos de CI a cada 30 dias | Máximo por rodada |
|---|---|---|---|
| Community (grátis) | €0, "For open source projects" | 50 | 5 min |
| Hobby | €5,6 por mês | 200 | 5 min |
| Hobby+ | €8,1 por mês | 500 | 10 min |
| Pro | €20 por pessoa ("seat") por mês | 2000 | 50 min |

Pro nosso uso (projeto fechado, poucas rodadas), o Hobby já serviria. O Luiz decide se vale.

## 3. Como usar

### Instalar

Antes, o sistema precisa ter: `git`, `make`, `gcc` e `g++` (pro gêmeo, o simavr e o nativo), `pkg-config` e a
libelf (pro simavr; aqui veio do Homebrew: `brew install elfutils`) e, só pro avr8js e o rp2040js, o `node`
(`brew install node`). O que falta do Homebrew ou do npm o laboratório **pergunta antes** ("Posso rodar: brew
install ...? [s/N]"), nunca roda sozinho; sem terminal, só mostra o comando.

```
python3 laboratorio/lab.py instalar --ver     # o que já tem, quanto ocupa e o que falta (não baixa nada)
python3 laboratorio/lab.py instalar           # gemeo, qemu, simavr e nativo; o que já tem diz "já tem"
python3 laboratorio/lab.py instalar nativo    # só um
```

Pra experimentar sem compilar nada: `LAB_GEMEO=cpython python3 laboratorio/lab.py testar --rapido` roda o `gemeo` no Python do PC (o CPython), sem o MicroPython 1.29. É menos fiel: o CPython aceita coisa que o MicroPython recusa, e a linha do tempo avisa isso. `LAB_GEMEO=micropython` faz o contrário: exige o MicroPython do PC (sem ele, código 5). Sem a variável, o `gemeo` usa o MicroPython quando ele está instalado e, sem ele, fica "falta" (o `testar` pula). A etapa 8 do Sianvolt não usa o atalho: sem o MicroPython do PC, ela pula.

| Motor | O que baixa | De onde | Ocupa (medido) | Tempo (medido) |
|---|---|---|---|---|
| `gemeo` | MicroPython v1.29.0 (fonte, [MIT](https://github.com/micropython/micropython/blob/master/LICENSE)), compila o port unix com `make -j2` e apaga a fonte | GitHub | 1,3 MB (mais ~176 MB de fonte durante a compilação) | ~68 s: clone 24,5 s, submódulos 21,9 s, mpy-cross 7,7 s, port unix 13,9 s |
| `qemu` | QEMU esp-develop-9.2.2-20260417 ([GPL-2.0](https://github.com/espressif/qemu/blob/esp-develop/COPYING)) e MicroPython 1.29 do ESP32 e do C3, sha256 conferido | [GitHub](https://github.com/espressif/qemu/releases/tag/esp-develop-9.2.2-20260417), micropython.org | 152 MB | ~16 s |
| `simavr` | arduino-cli 1.5.1 ([GPL-3.0](https://github.com/arduino/arduino-cli/blob/master/LICENSE.txt)), core arduino:avr 1.8.8 (LGPL-2.1), simavr no commit 5b08da6 ([GPL-3.0](https://github.com/buserror/simavr/blob/master/COPYING)) | GitHub, arduino.cc | 458 MB: o arduino-cli com o core e o avr-gcc ~421 MB (aí dentro, 56 MB de `downloads/` apagáveis e um `library_index.json` de 60 MB que o arduino-cli baixa), o simavr ~38 MB | ~25 s |
| `nativo` | EpoxyDuino v1.6.0 ([MIT](https://github.com/bxparks/EpoxyDuino/blob/develop/LICENSE)), commit conferido | GitHub | 1 MB | 2 a 4 s |
| `rp2040js` (fora do padrão) | os pacotes avr8js/rp2040js do npm (com o seu OK), o MicroPython 1.29 do Pico (0,7 MB), o bootrom do rp2040js e o core **arduino-pico 6.3.1** (rp2040:rp2040, [LGPL-2.1](https://github.com/earlephilhower/arduino-pico/blob/master/LICENSE)) com os 2 compiladores dele | npm, micropython.org, GitHub | ~1,5 GB instalado (core 481 MB, pqt-gcc 363 MB, pqt-gcc-riscv 649 MB) mais ~440 MB de pacotes em `downloads/` | minutos (o `instalar --ver` mostra antes) |

A instalação padrão inteira (gemeo, qemu, simavr e nativo), numa pasta vazia, deu **609 MB em 109 s**
(medida numa cópia limpa em 2026-10-25). Nesta máquina, com tudo, `laboratorio/.ferramentas` tem **4,6 GB**:
2,4 GB do arduino-cli (o core do Pico é a maior parte), e 2 GB de `esp-idf` e `espressif`, que só servem pra
recompilar o firmware com rede do QEMU (`motores/qemu/rede/`) e não entram no instalar padrão. Os `downloads/`
do arduino-cli (489 MB aqui) podem ser apagados: voltam se precisar.

Nesta máquina já foi feito `brew install node elfutils` (67 s): node 26.12.1, elfutils 0.197 (a libelf do
simavr), 13 dependências do node, e o brew atualizou junto o python@3.15 (3.15.0 → 3.15.0_1), o brotli e o
ca-certificates. O avr8js 0.21.1 ([MIT](https://github.com/wokwi/avr8js/blob/main/LICENSE)) e o rp2040js 1.4.1
([MIT](https://github.com/wokwi/rp2040js/blob/main/LICENSE)) vieram do npm (registry.npmjs.org), que é o canal
oficial deles mas fica fora da lista de fontes combinada: por isso só com o seu OK.

### Rodar

```
python3 laboratorio/lab.py rodar esp32 exemplos/pisca                       # MicroPython no gemeo
python3 laboratorio/lab.py rodar esp32 exemplos/botao --lingua arduino      # o .ino no nativo
python3 laboratorio/lab.py rodar nano exemplos/pwm                          # o Nano no simavr
python3 laboratorio/lab.py rodar c3 exemplos/pisca --motor qemu             # o chip emulado
python3 laboratorio/lab.py rodar esp32 exemplos/pisca --circuito laboratorio/motores/gemeo/ensaios/placa_teste.txt
```

O programa é um `.py`, um `.ino` ou uma pasta; ele e o `--circuito` são procurados a partir da pasta atual e,
se não estiverem lá, a partir de `laboratorio/`. Sem `--motor`, usa o primeiro motor pronto da placa (de
preferência um que tenha tudo que o roteiro `precisa`); sem `--lingua`, a primeira linguagem da placa que a
pasta tiver. Opções: `--tempo s` (segundos de placa, de 0,001 a 600; sem ele vale o `tempo` do roteiro, que
tem a mesma faixa, e, sem roteiro, 5 s), `--roteiro x.json`, `--json` (um evento por linha), `-v` (mostra tudo; sem ele, linhas do
tempo compridas perdem o meio, mas os avisos e erros do meio aparecem). A saída é a linha do tempo:

```
  1,000 s  GPIO4 (BOTAO) = 0  (roteiro)
  1,001 s  serial> apertou
  1,001 s  GPIO23 (LED/PWM) = 1
Conferências: 5 de 5 ok
tempo · 2,500 s de placa em 0,20 s de PC · RAM 4 MB · motor nativo · esp32 (alvo esp32)
```

Código de saída: 0 ok, 1 erro no programa, 2 uso errado, 3 travou, 4 conferência falhou, 5 falta instalar o motor.

- **1, erro no programa**: exceção, erro de compilação, programa que morre (ponteiro nulo no `nativo`), e também
  erro dentro de um callback (`Pin.irq`, `Timer`) no `gemeo` e no `qemu`: na placa o traceback sai na serial e o
  programa segue; aqui ele segue também, mas a rodada sai com 1.
- **3, travou**: o programa ficou preso num laço que não chama sleep, pino, relógio nem serial (`while True:
  pass`). Só os motores de relógio virtual percebem isso: o `gemeo` depois de 3 s de PC sem notícia do
  programa, o `nativo` depois de 3 s de CPU com o relógio parado. No `qemu`, `simavr`, `avr8js` e `rp2040js` o
  mesmo programa roda até o fim do `--tempo` e sai 0, como a placa faria (ela não "sabe" que travou).
  Também é 3: `machine.reset()`/`ESP.restart()`, o WDT estourar e o emulador passar do limite de PC. No `qemu`
  o `--tempo` conta do começo do `main.py` (carregar os módulos leva segundos e não conta); se o `main.py` nem
  começa até o limite de PC (15 s mais 3 vezes o `--tempo`), a rodada fica em 0 s de placa, as entradas do
  roteiro depois do 0 não acontecem, e sai 3.

**Pinos sem número.** Os exemplos nunca escrevem número de pino: usam `from placa import *` (MicroPython)
ou `#include "placa.h"` (Arduino), que o laboratório escreve pra cada placa (`PINO_LED`, `PINO_BOTAO`,
`PINO_POT`, `PINO_PWM`, `PINO_VERMELHO`, `PINO_AMARELO`, `PINO_VERDE`, `ADC_MAX`, `VREF_MV`, `NOME`).
O mesmo programa roda nas 6 placas. No `placa.h`, `ADC_MAX` é o maior valor do `analogRead()` do core: 4095
nas ESP, 1023 no Nano e no Pico (o arduino-pico começa em 10 bits até alguém chamar `analogReadResolution(12)`).
Na linha do tempo, o nome entre parênteses é o que o programa usa: o apelido do `placa.py`/`placa.h` quando ele
importa o placa (`GPIO4 (BOTAO)`), o nome do `pinos.py` da pasta quando tem (as placas do Sianvolt: o LED G do
dado é `GPIO4 (D7)`), e nenhum quando o programa não usa nenhum dos dois.

### Roteiro: o que entra e o que conferir

O `roteiro.json` da pasta (ou `--roteiro`). Tempo em segundos de placa; pino pelo apelido (LED, BOTAO...):

```
{"tempo": 2.5, "precisa": ["pino_saida", "pino_entrada", "serial", "serial_entrada"],
 "entradas": [{"t": 1.0, "pino": "BOTAO", "valor": 0}, {"t": 1.5, "pino": "BOTAO", "valor": 1},
              {"t": 0, "pino": "POT", "volts": 1.0}, {"t": 0.5, "serial": "liga\n"}],
 "confere": [{"t": 1.25, "pino": "LED", "valor": 1},
             {"t": 0.5, "pwm": "PWM", "duty": [0.2, 0.3]},
             {"serial": "apertou", "ate": 1.25},
             {"serial": "soltou", "desde": 1.5, "ate": 2},
             {"trocas": "LED", "min": 4, "max": 7},
             {"estado": "acabou"}]}
```

Os recursos do `precisa`: `serial` (a placa escreve), `serial_entrada` (o roteiro manda texto pra placa:
`sys.stdin`, `input()`, `select.poll`, `Serial.read()`), `pino_saida`, `pino_entrada`, `pwm`, `adc`, `i2c`,
`timer`, `rede`, `eletrica`, `luz` (a luz num LDR do circuito, abaixo; só o `gemeo`). Hoje todos os motores
têm `serial_entrada`. No `testar`, o motor que não tem algum deles é **pulado** (e aparece como pulado). No
`rodar`, sem `--motor` o laboratório escolhe um motor da placa que tenha tudo; com `--motor`, ou se nenhum motor
da placa tiver, ele **roda assim mesmo e avisa** ("o motor X não tem Y: essas conferências podem falhar").

Como as conferências contam:

- `{"t": 1.25, "pino": ...}` e `pwm`: o último valor até aquele instante. Confira no meio dos intervalos (0,25 s,
  não 0,5 s): assim vale no motor de relógio virtual e no de relógio real (QEMU).
- Instante depois do fim da rodada: se o tempo acabou antes (`--tempo` curto), a conferência **falha** com
  "não deu pra ver"; se o programa acabou, travou ou deu erro, vale o último estado (a placa fica parada com os
  pinos como estavam).
  Entrada do roteiro depois do fim não acontece, e o laboratório avisa.
- `trocas`: o pino começa em 0 e cada mudança de nível vinda do programa conta 1. Um LED que só acendeu (0 → 1)
  tem 1 troca; piscando 3 vezes (0 → 1 → 0, três vezes) são 6. Escrever o mesmo nível de novo não conta.
  `min` e `max` são números (os dois opcionais, e o `min` até o `max`); `"min": "2"` é uso errado (código 2).
- `serial` com `ate`: alguma linha até aquele instante contém o texto; quando falha, mostra a última linha
  que saiu **até lá**. Com `desde`, a linha tem que sair **depois** daquele instante (no mesmo instante não
  vale): `{"serial": "clareou", "desde": 15, "ate": 15.5}` só passa com um "clareou" novo, e não com um que já
  tinha saído antes de 15 s. Os dois são opcionais, e o `desde` tem que vir antes do `ate`. Um `desde` no fim
  da rodada ou depois dele, com o tempo acabando antes (estado `tempo`), falha com "não deu pra ver": não sobrou
  tempo de placa pra linha sair.

O laboratório também avisa, em todo motor, quando o roteiro faz algo que na placa daria problema: forçar um
pino que o programa usa como saída (na placa é um curto, e cada motor resolve de um jeito) e pôr num pino mais
tensão do que ele aguenta (ESP: VDD + 0,3 V, [datasheet do ESP32](https://documentation.espressif.com/esp32_datasheet_en.pdf)
Tabela 5-3; Nano: VCC + 0,5 V, datasheet do ATmega328P, "Absolute Maximum Ratings").

**Luz num LDR do circuito** (só o `gemeo`, só com `--circuito`): `{"t": 5, "luz": "LDR1", "lux": 1}` nas
`entradas` põe 1 lux no LDR1 do `placa.txt` a partir de 5 s (0 lux = escuro). O LDR1 tem que ser uma peça com
modelo elétrico `ldr` no circuito. O gêmeo põe a resistência do LDR do meio nessa luz (`circuito.ohms_do_ldr` do
Sianvolt, com o r10 e o gama do datasheet) no circuito, e o pino ligado nele lê o divisor de verdade: um LDR
ligado do lado errado lê o contrário. A linha do tempo mostra a luz (`LDR1 com 1 lux (roteiro)`) e a tensão que
o circuito põe no pino (`GPIO34 = 2,38 V (circuito)`, um evento `adc` com origem `circuito`) do GPIO ligado no
LDR, direto ou, sem nenhum direto, por um resistor (GPIO34 → 1 kΩ → LDR). Sem `--circuito`, é uso errado
(código 2); um LDR que o circuito não tem é erro (código 1). O LDR sem luz no roteiro fica em 10 lux, e um aviso
diz isso. No `gemeo.roteiro` vale `em 5 s LDR1 = 1 lux` (o `em` é opcional), e na linha do tempo ela aparece
com a origem dela (`LDR1 com 1 lux (gemeo.roteiro)`). O `ensaios/luz` (com `ensaios/circuito_ldr/placa_ldr.txt`,
ou o `placa_ldr_res.txt`, com o resistor no meio) é o exemplo.

**O brilho de cada LED** (só o `gemeo`, com `--circuito`): a cada mudança no circuito, o LED que mudou vira um
evento `led` com os números: `ref`, `i_med` e `i_max` (em A: a corrente média e a de quando liga, que no PWM são
diferentes), `luz` (a fração do brilho do anúncio, pela curva do datasheet da peça, a mesma conta do
`blocos.brilho_da_corrente`; sem curva, corrente ÷ corrente de teste), `aceso` e `queima` (true/false), mais o
`texto` de sempre ("D1 aceso, 5,9 mA, luz 59% do anúncio"). O `aceso` é a regra do texto: com menos de 1% da luz
e sem nunca passar 1 mA, o LED está apagado, mesmo com números acima de 0 (o pino do LED que ficou como entrada
com pull-up passa uns 35 µA: `ensaios/pullup`). Quem decide se um LED acendeu usa o `aceso`, e não a luz > 0. No
terminal sai o texto, uma linha por texto novo; no `--json` saem todos; no `--html`, uma onda por LED.

**Serial que chega na placa**: no `gemeo`, o texto do roteiro chega no `sys.stdin` na hora de placa certa;
`input()`, `sys.stdin.read()`/`readline()` e `select.poll().poll(ms)` esperam andando o relógio da placa até o
texto chegar (ou o tempo do poll acabar). Se o programa espera e o roteiro não manda mais nada, a rodada vai até
o fim do tempo, como na placa, com um aviso. No Pico com Arduino, a Serial é a USB: o que sai antes do PC abrir
a porta (uns 10 ms depois do começo) se perde, como na placa; o laboratório avisa, e `while (!Serial &&
millis() < 2000) delay(10);` no começo do `setup()` resolve (o exemplo `ola` faz isso).

### Testar tudo e ir e voltar no tempo

```
python3 laboratorio/lab.py testar --rapido      # só os de tempo virtual (gemeo, nativo, simavr): ~12 s
python3 laboratorio/lab.py testar               # todo exemplo x placa x linguagem x motor: ~3 min
python3 laboratorio/lab.py testar --placa nano --motor simavr --exemplo pwm
python3 laboratorio/lab.py rodar esp32 exemplos/botao --lingua arduino --html laboratorio/build/botao.html
```

O `--html` gera uma página sozinha (abre sem internet): uma onda por pino, por LED (a luz) e por LDR (o lux do
roteiro), a serial e uma régua de tempo pra arrastar, ir e voltar (setas, Home/End, espaço toca).

### Pro Claude: onde mexer

- `nucleo/contrato.py` é a regra de todo motor (eventos, Pedido, códigos). `nucleo/mentira.py` é o menor motor.
- Um motor novo é um `motores/<nome>.py` com `NOME`, `PLACAS`, `LINGUAGENS`, `RECURSOS`, `faltando()`,
  `instalar()` e `rodar()`; o `lab.py` acha sozinho.
- Testes: `python3 laboratorio/nucleo/teste_nucleo.py`, `python3 laboratorio/motores/gemeo/ensaios/testa.py`,
  `python3 laboratorio/motores/nativo/teste_nativo.py`, `python3 laboratorio/motores/qemu/teste_qemu.py`, e o
  `lab.py testar`. O `testar` diz no fim o que ficou sem testar (pulado) e o comando que instala; se tudo foi
  pulado, sai com 5. No clone limpo (sem `.ferramentas`), o `testa.py` pula o modo micropython e o `teste_nativo`
  pula a parte 2, os dois dizendo o comando que instala; com o `qemu` instalado, o `testa.py` também roda o
  `ensaios/recusa` no chip emulado e compara.
- **Vários Claudes ao mesmo tempo**: pode. Cada rodada pega uma vaga só dela em `build/<placa>/<motor>/<nome>`
  (ou `<nome>~2`, `<nome>~3`... se outra rodada estiver usando a mesma, com uma trava `flock` que solta
  sozinha quando o processo acaba). Programas diferentes com o mesmo nome (`codigo`) também não se pisam.
  O que pesa é a RAM: um qemu do ESP32 usa ~260 MB, então não abra muitos de uma vez.
- Regras: `make -j2`, nada em `/tmp`, todo caminho relativo ao arquivo.

## 4. Ligado no Sianvolt

O firmware de uma placa do Sianvolt mora junto dela, em `placas/<nome>/codigo/` (`main.py`, `roteiro.json`,
`gemeo.roteiro` e o `confere.json` do Sianvolt). Quem roda é o `ferramenta/programa.py` (a etapa 8 do `testar.py`
e o ▶ Programa do app): ele copia o `codigo/` pra `saida/programa/`, roda
`lab.py rodar esp32 <cópia> --motor gemeo --circuito placas/<nome>/placa.txt --json` e transforma a linha do
tempo no `saida/programa.json`. Ele olha o que este laboratório sabe antes de rodar: com a luz em lux (acima),
manda a luz do quarto como `{"luz": "LDR1", "lux": ...}`; num laboratório antigo, troca pelos volts do divisor.
O brilho dos LEDs vem do evento `led` (num laboratório antigo, do texto do aviso).
