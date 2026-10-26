# Objetivo: Placa de teste com o ESP32
Aperta o botão: o LED acende e o piezo apita; o olho de luz diz se está claro ou escuro. É a placa que os testes do Sianvolt usam (não é projeto do Luiz).

## R1 O ESP32 aguenta tudo que está ligado nele
pecas: U1 D1 R1 SW1 R2 BZ1 R4
verifica: pino_seguro U1
verifica: acende D1
verifica: nao_queima D1
- Nenhum pino passa da força padrão (20 mA) e o 3V3 fica no orçamento, com o pior caso da etapa 4

## R2 O olho de luz lê dentro da faixa boa
pecas: LDR1 R3
verifica: adc_na_faixa LDR1 10 100
- 3V3 → 22 kΩ → GPIO34 → LDR → GND: com 10 e 100 lux, nos cantos do LDR e do 3V3, o ADC fica de 0,15 a 2,45 V

## R3 O programa roda sem erro e passa nas conferências
pecas: U1
verifica: programa_ok
- O roteiro do laboratório (codigo/roteiro.json) e o nosso (codigo/confere.json) passam no gêmeo

## R4 Apertou, o LED acende
pecas: D1 SW1
verifica: programa_acende D1
