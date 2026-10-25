// trava: um laço que nunca chama delay/millis; na placa o resto do programa nunca roda
#include "placa.h"

void setup() {
  pinMode(PINO_LED, OUTPUT);
  digitalWrite(PINO_LED, HIGH);
}

void loop() {
  volatile long conta = 0;
  while (true) conta++;
}
