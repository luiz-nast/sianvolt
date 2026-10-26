---
name: peca-da-loja
description: Escolher, procurar e conferir peças de verdade pro Sianvolt - primeiro no catálogo (ferramenta/catalogo/, um arquivo por categoria, a lista de compras de sempre), com a loja JLCPCB/LCSC como double check e as lojas brasileiras (RoboCore) pras placas prontas como o ESP32 DevKit; importar a peça escolhida e conferir no datasheet o que a loja não diz (LED, LDR, piezo, capacitor). Use quando precisar de uma peça, trocar uma peça, ou quando o app avisar "falta o Claude conferir no datasheet".
---

# Peça da loja

## O catálogo primeiro

`ferramenta/catalogo/` é a lista de compras de sempre (vai pro repositório): milhares de peças, um arquivo por categoria (passivos, semicondutores, energia, cérebros como ESP32, comunicação, sensores, telas, conectores, movimento, módulos prontos), da LCSC e de lojas brasileiras (Eletrogate, Baú, Usinainfo, RoboCore). Cada arquivo diz como buscar, filtrar e dar nome às peças daquela categoria (formato no docstring de `catalogo.py`). Cada peça tem tudo que a loja diz, a montagem (furo, superfície, módulo, fio), `visto` (o dia em que viu), `situacao` (`ok`, `sem estoque`, `sumiu`) e, quando já foi lida, `conferido` (o que veio do datasheet). O app mostra o mundo de opções (tela Catálogo e o Trocar do carrinho) a partir dela.

```
python3 ferramenta/catalogo.py ver led              # o que tem na lista
python3 ferramenta/catalogo.py checar C779439       # preço e estoque agora, na loja (sem código: a lista toda)
python3 ferramenta/catalogo.py encher botao         # busca de novo as sementes da categoria e põe o que faltar
python3 ferramenta/catalogo.py categorias           # as categorias, por grupo
python3 ferramenta/catalogo.py recalcular botao     # refaz nome, montagem e tamanho com as regras de agora
```

Ao escolher uma peça, você é livre pra pensar: usar uma da lista, procurar uma melhor ou testar outra. Só siga estas regras:

1. **Olhe a lista antes da loja.** Prefira peça já `conferido` (está pronta pra placa).
2. **Antes de pôr no carrinho, confira na loja** (`checar`): preço e estoque mudam todo dia. Se ela estiver `sem estoque` ou tiver `sumiu`, ela fica na lista marcada (não apague) e você escolhe outra.
3. **Achou coisa melhor na loja?** Ela entra na lista: `python3 ferramenta/loja.py buscar "..."` e depois `importar`, ou o "Procurar mais na loja" do app.
4. **Viu que algo na lista está errado** (a loja mudou o atributo, o datasheet diz outra coisa)? Corrija na lista e diga ao Luiz o que mudou.
5. Depois de mexer no catálogo, faça commit dele ("Catálogo: ..."). Peça errada que o encher traz de volta: ponha o código em `filtro.fora` da categoria.
6. Loja brasileira (`ferramenta/lojas.py`): só página de produto, com a pausa que o robots.txt pede (10 s na Eletrogate e na Baú), sem `/buscar` nem `/api`; Mercado Livre, AliExpress, Mouser e MakerHero não deixam ler. Nunca login, carrinho ou pedido.

A busca da loja é por palavra exata: `CR2032 Plugin` acha, `CR2032 battery holder through hole` não. LED de qualquer cor: `LED 5mm` (as cores vêm nos atributos). As buscas que enchem cada bloco ficam em `SEMENTES` (`catalogo.py`).

## Placa pronta de loja brasileira (o DevKit)

A LCSC não vende o ESP32 DevKit; ele vem de loja brasileira. No catálogo, a peça de loja brasileira tem a chave `loja:slug` (`robocore:esp32-wifi-bluetooth`, em `placa_desenvolvimento.json`). Ela só pode ir pra placa se tiver o campo **`tipo`** apontando pra um tipo da `biblioteca.py` (`"tipo": "devkit_esp32_30"`): o desenho, os nomes dos pinos e a elétrica vêm de lá, e o `conferido` da peça guarda só a `fonte` (a página da loja, a foto, o desenho 1:1). O bloco `cerebro` só aceita peça com `tipo`.

`blocos.escolher(pasta, "U1", "robocore:esp32-wifi-bluetooth")` não chama a `loja.importar` nem grava nada em `pecas/`: põe `peca U1 devkit_esp32_30 X Y` no `placa.txt` e o preço em R$ no carrinho. O que vem junto (as 2 barras fêmea C41417327) está no `acompanha` do tipo e entra no carrinho em US$, da LCSC.

DevKit de outra loja só com o tipo certo: a Usinainfo e a Eletrogate vendem DevKits parecidos, mas a ficha da Eletrogate diz 25,5 mm de largura, que não cabe com as fileiras a 25,4 mm do nosso tipo (pesquisa de 2026-10-25, pendente); o de 38 pinos e o de fileiras a 22,86 mm não servem (o `compra` e o `confira` do `devkit_esp32_30`).

## Importar a escolhida

```
python3 ferramenta/loja.py importar C779439 led placas/<nome>
```

ou `blocos.escolher(pasta, ref, codigo, quem="Luiz", *, atualizar_catalogo=True)`, que também grava o `projeto.json` e troca o tipo no `placa.txt` quando ele já tem a linha `peca` daquele REF (sem ela, `na_placa: False`: a peça fica no carrinho e entra no `placa.txt` quando o Claude desenhar a placa; nunca escreva a linha antes do carrinho). O import pega o desenho oficial (pads, furos, serigrafia) do EasyEDA e a foto e o pdf da LCSC. Essas coisas ficam só na máquina (`placas/<nome>/pecas/` e `~/.cache/sianvolt/`), e a peça entra (ou se atualiza) na lista.

O `<nome>` do `importar` é de uma placa que já existe (com `placa.txt`). O `importar` grava a peça, com o preço e o estoque que leu na loja (a busca fica guardada por um dia), no `ferramenta/catalogo/<categoria>.json`, que é do git: confira o `git status` depois.

**`atualizar_catalogo=False`** (só pelo nome): nada é gravado em `ferramenta/catalogo/`. A peça sai do `conferido` que já existe no catálogo e vai só pro `pecas/C*.json` da placa. Use quando outra pessoa (ou outro agente) está mexendo no catálogo, ou pra testar uma troca sem mexer na lista. O `quem` é sempre um nome: `escolher(p, ref, codigo, False)` é erro.

## O que a loja não diz: conferir no datasheet

Sem `conferido`, a peça fica `pendente`: não liga no papel nem vai pra fábrica. Baixe o PDF pelo `pdfUrl` da página da LCSC (com o OK do Luiz) e leia as figuras (`pdftoppm`, depois Read na imagem; o texto com `pdftotext -layout`). Escreva em `conferido`, dentro da peça, no arquivo da categoria em `ferramenta/catalogo/`, com a origem em `fonte` (o link `https://` e a página, `p. 4`) e o que foi lido no olho ou no vetor em `_eletrica`. O `testes/test_catalogo.py` exige os campos de cada modelo e, no LED, LDR, piezo e capacitor, o link e a página na fonte.

| bloco | conferir (dentro de `conferido.eletrica`, com o `modelo`) |
|---|---|
| pilha (suporte) | qual furo é o + (desenho "PCB layout"); a pilha que vai nele e o datasheet dela: `mais`, `menos`, `v`, `v_min`, `v_max`, `mah`, `r_interna` (gráfico IR), `i_testada` (o maior consumo que o fabricante testou) |
| botão | quais pinos são ligados por dentro (SCHEMATIC do datasheet): `lados`; `i_max` |
| LED (`led`) | o + e o − (`mais`/`menos`; símbolo do EasyEDA: A = +, K = −; a numeração muda de um fabricante pro outro), `i_max` (IF contínua), `i_teste`, `vf` típica, `vf_min` e `vf_max` (tabela), `r_s` (curva IF × VF entre 10 e 30 mA), `brilho` (curva de intensidade relativa × corrente, pares `[corrente A, fração]` que começam com brilho 0, com a corrente crescendo e 1,0 na corrente de teste) e `cor` em português (`vermelho`, `amarelo`, `verde`, `branco quente`) |
| olho de luz (`ldr`) | `r10_min` e `r10_max` (a resistência em 10 lux), `gama` e `gama_tol` (a inclinação da curva e o erro dela), `r_escuro`, `p_max`, `v_max`; um ponto de outra curva (1 lux) só com a fonte dele (`ponto_1lux`, ex.: o gráfico da Senba C125626). Sem polaridade: pinos `lado 1`/`lado 2` |
| som (`piezo`) | `c` e `c_tol` (a capacitância), `v_max_op` (a tensão de pico de trabalho), `r_serie` (o resistor em série que o fabricante pede), `f_teste` e `spl_db` (a nota e o som da tabela); em DC ele é aberto |
| capacitor (`capacitor`) | `c` (a capacitância) e `v_max` (a tensão); de furo, com a distância entre as pernas do desenho |
| resistor | nada: valor e potência vêm dos atributos da loja (se o PDF não foi aberto, diga em `pendentes`) |

Barra fêmea e outras peças mecânicas: `conferido` com `fonte` e `mecanica` (passo, altura, furo recomendado, temperatura e tempo máximos de solda), sem `eletrica`.

Dúvida que não segura a fábrica (a cor do LED que o gráfico contradiz, o PDF não aberto) vai em `eletrica["pendentes"]`, uma frase por item começando pelo assunto (`"a cor: ..."`): o app mostra com o selo pendente. O `pendente` da peça é outra coisa: segura a fábrica.

O `C779439` (LED) e o `C393938` (botão) estão lá de exemplo; o LDR `C10081`, o piezo `C128650` e os LEDs `C779441`, `C779440`, `C779443` e `C7433012` também. Depois, importe de novo e rode o `testar.py`.

**Nunca chute** o + de uma peça ou os pinos de um botão. Se o datasheet não deixar claro, deixe pendente e diga ao Luiz qual figura faltou.
