// rapido: PWM "na mão" (bit-banging): 25% ligado, 4 kHz. Sem cuidado, viraria 8 mil eventos por segundo.
#include "placa.h"

void setup() { pinMode(PINO_LED, OUTPUT); }

void loop() {
  digitalWrite(PINO_LED, HIGH);
  delayMicroseconds(62);
  digitalWrite(PINO_LED, LOW);
  delayMicroseconds(188);
}
