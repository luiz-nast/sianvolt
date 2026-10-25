// WiFi.h de mentira: o sketch compila e "conecta" depois de um tempo de faz de conta.
// Nao tem rede de verdade (nem WiFiClient, HTTPClient, WebServer): isso quebra na compilacao, de proposito.
// --wifi-falha nao existe ainda; pra testar o caminho de erro, defina SIANVOLT_WIFI_FALHA antes do include.
#ifndef SIANVOLT_WIFI_H
#define SIANVOLT_WIFI_H
#include <Arduino.h>
#include <IPAddress.h>

typedef enum { WL_IDLE_STATUS = 0, WL_NO_SSID_AVAIL = 1, WL_CONNECTED = 3, WL_CONNECT_FAILED = 4, WL_DISCONNECTED = 6 } wl_status_t;
typedef enum { WIFI_OFF = 0, WIFI_STA = 1, WIFI_AP = 2, WIFI_AP_STA = 3 } wifi_mode_t;

void sianvolt_marca(const char* texto);

class SianvoltWiFi {
 public:
  bool mode(wifi_mode_t) { return true; }
  wl_status_t begin(const char* ssid, const char* = nullptr) {
    inicio_ = millis();
    tentando_ = true;
    String m = String("wifi: conectando em ") + ssid;
    sianvolt_marca(m.c_str());
    return WL_DISCONNECTED;
  }
  wl_status_t status() {
#if defined(SIANVOLT_WIFI_FALHA)
    return tentando_ ? WL_DISCONNECTED : WL_IDLE_STATUS;
#else
    if (!tentando_) return WL_IDLE_STATUS;
    if (millis() - inicio_ < 1500) return WL_DISCONNECTED;   // 1,5 s pra "conectar"
    if (!avisou_) { avisou_ = true; sianvolt_marca("wifi: conectado (de mentira)"); }
    return WL_CONNECTED;
#endif
  }
  bool isConnected() { return status() == WL_CONNECTED; }
  IPAddress localIP() { return status() == WL_CONNECTED ? IPAddress(192, 168, 0, 50) : IPAddress(0, 0, 0, 0); }
  int32_t RSSI() { return status() == WL_CONNECTED ? -60 : 0; }
  String macAddress() { return "24:0A:C4:00:00:01"; }
  bool disconnect(bool = false) { tentando_ = false; avisou_ = false; return true; }
  bool setAutoReconnect(bool) { return true; }
 private:
  unsigned long inicio_ = 0;
  bool tentando_ = false, avisou_ = false;
};

static SianvoltWiFi WiFi;
#endif
