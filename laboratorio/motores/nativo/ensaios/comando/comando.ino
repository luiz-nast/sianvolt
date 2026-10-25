// comando: lê linhas da serial; "liga" acende o LED, "desliga" apaga (testa a serial que vem do roteiro)
#include "placa.h"

void setup() {
  Serial.begin(115200);
  pinMode(PINO_LED, OUTPUT);
  digitalWrite(PINO_LED, LOW);
}

void loop() {
  if (Serial.available() > 0) {
    String linha = Serial.readStringUntil('\n');
    linha.trim();
    if (linha == "liga") digitalWrite(PINO_LED, HIGH);
    if (linha == "desliga") digitalWrite(PINO_LED, LOW);
    Serial.print("ouvi: ");
    Serial.println(linha);
  }
}
