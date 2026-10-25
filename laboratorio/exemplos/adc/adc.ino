// adc: lê o potenciômetro a cada 200 ms, mostra a tensão e acende o LED acima de 1500 mV
#include "placa.h"   // PINO_POT, PINO_LED, ADC_MAX (o maior valor lido), VREF_MV (a tensão dele)

void setup() {
  Serial.begin(115200);
  pinMode(PINO_LED, OUTPUT);
  digitalWrite(PINO_LED, LOW);
}

void loop() {
  long mv = (long)analogRead(PINO_POT) * VREF_MV / ADC_MAX;   // long: no Nano o int estoura
  Serial.print("pot=");
  Serial.print(mv);
  Serial.println(" mV");
  digitalWrite(PINO_LED, mv > 1500 ? HIGH : LOW);
  delay(200);
}
