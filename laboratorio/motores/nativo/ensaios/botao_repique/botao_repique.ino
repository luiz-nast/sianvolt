// Botao + LED: apertou, acende. E conta os apertos com interrupcao (com filtro de 50 ms pro "repique").
#if defined(ESP32)
const int LED = 2, BOTAO = 4;       // DevKit: GPIO2 tem o LED azul; GPIO4 livre
#else
const int LED = 13, BOTAO = 2;      // Uno: pino 2 e o da interrupcao 0
#endif

volatile unsigned long apertos = 0, ultimo = 0;

void conta() {                       // roda na interrupcao (quando o pino desce)
  unsigned long t = millis();
  if (t - ultimo > 50) apertos++;
  ultimo = t;
}

void setup() {
  Serial.begin(115200);
  pinMode(LED, OUTPUT);
  pinMode(BOTAO, INPUT_PULLUP);     // solto = 1 (o resistor de dentro puxa pra cima); apertado = 0
  attachInterrupt(digitalPinToInterrupt(BOTAO), conta, FALLING);
}

void loop() {
  static unsigned long visto = 0;
  bool apertado = digitalRead(BOTAO) == LOW;
  digitalWrite(LED, apertado ? HIGH : LOW);
  if (apertos != visto) {
    visto = apertos;
    Serial.print("apertos: ");
    Serial.println(visto);
  }
}
