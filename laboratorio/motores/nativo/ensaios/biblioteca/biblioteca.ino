// biblioteca: usa uma biblioteca que o motor nativo não tem
#include <WiFi.h>
#include <HTTPClient.h>

void setup() { HTTPClient h; h.begin("http://example.com"); h.GET(); }
void loop() {}
