// So ESP32: conecta no Wi-Fi piscando rapido; conectou, LED fica aceso e mostra o IP.
// No gemeo o Wi-Fi e de mentira (conecta em 1,5 s); o que importa e testar a logica de esperar e desistir.
#include <WiFi.h>

const int LED = 2;

void setup() {
  Serial.begin(115200);
  pinMode(LED, OUTPUT);
  WiFi.mode(WIFI_STA);
  WiFi.begin("casa-do-luiz", "senha-de-teste");
  unsigned long comeco = millis();
  while (WiFi.status() != WL_CONNECTED) {
    digitalWrite(LED, !digitalRead(LED));
    delay(100);
    if (millis() - comeco > 10000) {
      Serial.println("desisti do wifi");
      return;
    }
  }
  digitalWrite(LED, HIGH);
  Serial.print("conectado, IP ");
  Serial.println(WiFi.localIP());
}

void loop() { delay(1000); }
