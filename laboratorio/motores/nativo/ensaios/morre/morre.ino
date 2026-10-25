// morre: escreve num ponteiro nulo aos 300 ms (no ESP32 dá "Guru Meditation Error" e a placa reinicia)
#include "placa.h"

int* nada = nullptr;

void setup() { Serial.begin(115200); Serial.println("vou morrer"); }

void loop() {
  delay(300);
  *nada = 1;
}
