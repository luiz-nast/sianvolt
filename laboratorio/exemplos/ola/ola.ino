// ola: diz olá pela serial a cada meio segundo, contando as vezes
#include "placa.h"   // NOME = o nome da placa, ex.: "Arduino Nano"

int vez = 1;

void setup() {
  Serial.begin(115200);
  // no Pico a Serial é a USB: o que sai antes do PC abrir a porta se perde. Espera até 2 s (no Nano e nas ESP
  // a Serial já está pronta e isto passa direto)
  while (!Serial && millis() < 2000) delay(10);
}

void loop() {
  Serial.print(vez);               // sai assim: "1: olá do Arduino Nano"
  Serial.print(": olá do ");
  Serial.println(NOME);
  vez++;
  delay(500);
}
