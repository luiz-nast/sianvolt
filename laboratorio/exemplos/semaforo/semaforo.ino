// semaforo: verde 2 s, amarelo 0,5 s, vermelho 2 s, e repete
#include "placa.h"   // PINO_VERDE, PINO_AMARELO, PINO_VERMELHO

// a luz escolhida acende, as outras apagam, e espera
void so_acende(int luz, unsigned long ms) {
  digitalWrite(PINO_VERDE, luz == PINO_VERDE ? HIGH : LOW);
  digitalWrite(PINO_AMARELO, luz == PINO_AMARELO ? HIGH : LOW);
  digitalWrite(PINO_VERMELHO, luz == PINO_VERMELHO ? HIGH : LOW);
  delay(ms);
}

void setup() {
  pinMode(PINO_VERDE, OUTPUT);
  pinMode(PINO_AMARELO, OUTPUT);
  pinMode(PINO_VERMELHO, OUTPUT);
}

void loop() {
  so_acende(PINO_VERDE, 2000);
  so_acende(PINO_AMARELO, 500);
  so_acende(PINO_VERMELHO, 2000);
}
