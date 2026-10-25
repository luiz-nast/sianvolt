// prototipo: usa a função antes de definir. A IDE do Arduino gera o protótipo; o g++ puro não compila.
#include "placa.h"

void setup() {
  Serial.begin(115200);
  mostra(42);
}

void loop() { delay(100); }

void mostra(int x) {
  Serial.print("x = ");
  Serial.println(x);
}
