// Arduino.h do motor nativo: o Arduino.h do EpoxyDuino (String, Print, Serial...) + o sabor da placa.
// O EpoxyDuino só finge um AVR genérico; aqui a gente acerta os números que o sketch enxerga
// (modos de pino, LED_BUILTIN, A0...) e acrescenta o que o ESP32 tem a mais (ledc, analogReadMilliVolts).
// Sabor esp32 (-DPLACA_ESP32): as 4 ESP do laboratório; o nativo.py passa CONFIG_IDF_TARGET_ESP32/C3/S3/C6.
// Sabor uno (sem nada): o Nano (ATmega328P), com A6 e A7 que o Nano tem a mais que o Uno.
// Fontes dos numeros do ESP32 (arduino-esp32, master de 2026-10, versao 3.3.12):
//   https://github.com/espressif/arduino-esp32/blob/master/cores/esp32/esp32-hal-gpio.h
//   https://github.com/espressif/arduino-esp32/blob/master/variants/esp32/pins_arduino.h
//   https://github.com/espressif/arduino-esp32/blob/master/variants/doitESP32devkitV1/pins_arduino.h (LED_BUILTIN 2)
#ifndef SIANVOLT_ARDUINO_H
#define SIANVOLT_ARDUINO_H

#include_next <Arduino.h>

#if defined(PLACA_ESP32)
  #undef INPUT
  #undef OUTPUT
  #undef INPUT_PULLUP
  #define INPUT             0x01
  #define OUTPUT            0x03
  #define PULLUP            0x04
  #define INPUT_PULLUP      0x05
  #define PULLDOWN          0x08
  #define INPUT_PULLDOWN    0x09
  #define OPEN_DRAIN        0x10
  #define OUTPUT_OPEN_DRAIN 0x13
  #define ANALOG            0xC0
  #undef RISING
  #undef FALLING
  #undef CHANGE
  #define RISING  0x01
  #define FALLING 0x02
  #define CHANGE  0x03
  #define ONLOW   0x04
  #define ONHIGH  0x05
  #undef LED_BUILTIN
  #define LED_BUILTIN 2            // DOIT DevKit V1; o "ESP32 Dev Module" generico nem define
  #undef A0
  #undef A3
  #undef A4
  #undef A5
  #undef A6
  #undef A7
  #define A0 36
  #define A3 39
  #define A4 32
  #define A5 33
  #define A6 34
  #define A7 35
  #undef F_CPU
  #define F_CPU 240000000L
  #define digitalPinToInterrupt(p) (p)
  #define IRAM_ATTR                // no chip põe a rotina na RAM interna; no PC não faz nada
  #define ARDUINO_ISR_ATTR
  #define ESP32 1
  #define ARDUINO_ARCH_ESP32 1

  // PWM do ESP32 (API do core 3.x: por pino). O core 2.x usava canal; mesma assinatura, nao da pra ter as duas.
  bool ledcAttach(uint8_t pin, uint32_t freq, uint8_t resolution);
  bool ledcWrite(uint8_t pin, uint32_t duty);
  bool ledcDetach(uint8_t pin);
  // ADC: o ESP32 le 12 bits (0..4095) e sabe devolver em milivolts
  uint32_t analogReadMilliVolts(uint8_t pin);
  void analogReadResolution(uint8_t bits);
  inline void analogSetAttenuation(int) {}
  inline void analogSetPinAttenuation(uint8_t, int) {}

  class EspClass {
   public:
    uint32_t getFreeHeap() { return 300000; }   // numero de faz de conta, so pra compilar
    const char* getChipModel() { return "ESP32 (gemeo)"; }
    uint32_t getCpuFreqMHz() { return 240; }
    void restart();
  };
  extern EspClass ESP;
#else
  // Uno/Nano: o EpoxyDuino põe LED_BUILTIN 1 e A0 = 0 (arbitrário). Acerta pro Uno/Nano de verdade.
  #undef LED_BUILTIN
  #define LED_BUILTIN 13
  #undef A0
  #undef A1
  #undef A2
  #undef A3
  #undef A4
  #undef A5
  #undef A6
  #undef A7
  #define A0 14
  #define A1 15
  #define A2 16
  #define A3 17
  #define A4 18
  #define A5 19
  #define A6 20                    // o Nano tem A6 e A7 (só analógicos): variants/eightanaloginputs
  #define A7 21
  #define digitalPinToInterrupt(p) ((p) == 2 ? 0 : ((p) == 3 ? 1 : -1))
#endif

// O que o motor nativo dá a mais pro sketch (opcional; com #if defined(SIANVOLT) o mesmo .ino compila na placa)
#define SIANVOLT 1
void sianvolt_marca(const char* texto);   // poe uma marca na linha do tempo ("comecou a piscar")

#endif
