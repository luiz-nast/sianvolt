// so_entrada: o GPIO34 da ESP32 não tem saída (datasheet); o GPIO2 é pino de boot
void setup() {
  pinMode(34, OUTPUT);
  digitalWrite(34, HIGH);
  pinMode(2, OUTPUT);
  digitalWrite(2, HIGH);
  pinMode(24, OUTPUT);   // a ESP32 não tem GPIO24
}

void loop() { delay(100); }
