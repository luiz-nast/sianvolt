// Painel: o potenciometro escolhe o brilho do LED (PWM). Mostra a leitura a cada 250 ms sem usar delay.
// Passou de 90%, apita o buzzer.
#if defined(ESP32)
const int POT = 34, LED = 2, BUZZER = 25;   // GPIO34 e so entrada, com ADC
const int MAX_ADC = 4095;
#else
const int POT = A0, LED = 9, BUZZER = 8;    // Uno: pino 9 tem PWM
const int MAX_ADC = 1023;
#endif

unsigned long ultimo = 0;
bool apitando = false;

void setup() {
  Serial.begin(115200);
  pinMode(LED, OUTPUT);
  Serial.println("painel pronto");
}

void loop() {
  int bruto = analogRead(POT);
  int brilho = map(bruto, 0, MAX_ADC, 0, 255);
  analogWrite(LED, brilho);
  bool alto = bruto > MAX_ADC * 9 / 10;
  if (alto && !apitando) tone(BUZZER, 2000);
  if (!alto && apitando) noTone(BUZZER);
  apitando = alto;
  if (millis() - ultimo >= 250) {
    ultimo = millis();
#if defined(ESP32)
    Serial.printf("t=%lu pot=%d (%u mV) brilho=%d\n", ultimo, bruto, (unsigned)analogReadMilliVolts(POT), brilho);
#else
    Serial.print("t="); Serial.print(ultimo); Serial.print(" pot="); Serial.print(bruto);
    Serial.print(" brilho="); Serial.println(brilho);
#endif
  }
}
