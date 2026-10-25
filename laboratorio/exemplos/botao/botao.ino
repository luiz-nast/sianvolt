// botao: o LED acende enquanto o botão está apertado
// o botão liga o pino no GND: solto = HIGH (pull-up interno), apertado = LOW
#include "placa.h"

int antes = HIGH;

void setup() {
  Serial.begin(115200);
  pinMode(PINO_BOTAO, INPUT_PULLUP);
  pinMode(PINO_LED, OUTPUT);
  digitalWrite(PINO_LED, LOW);
}

void loop() {
  int agora = digitalRead(PINO_BOTAO);
  if (agora != antes) {   // só fala quando muda
    Serial.println(agora == LOW ? "apertou" : "soltou");
    antes = agora;
  }
  digitalWrite(PINO_LED, agora == LOW ? HIGH : LOW);
  delay(10);              // olha o botão 100 vezes por segundo
}
