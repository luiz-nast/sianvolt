// pisca: o LED fica meio segundo aceso e meio segundo apagado, pra sempre
#include "placa.h"   // PINO_LED e os outros pinos da placa escolhida

void setup() {
  pinMode(PINO_LED, OUTPUT);
}

void loop() {
  digitalWrite(PINO_LED, HIGH);   // acende
  delay(500);
  digitalWrite(PINO_LED, LOW);    // apaga
  delay(500);
}
