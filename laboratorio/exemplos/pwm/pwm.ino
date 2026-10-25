// pwm: o LED liga e desliga bem rápido; o que muda é quanto tempo fica ligado
// 25% ligado por 1 s (fraquinho), 75% por 1 s (forte), e repete
#include "placa.h"

void setup() {
  pinMode(PINO_PWM, OUTPUT);
}

void loop() {
  analogWrite(PINO_PWM, 64);    // 64 de 255 = 25%
  delay(1000);
  analogWrite(PINO_PWM, 191);   // 191 de 255 = 75%
  delay(1000);
}
