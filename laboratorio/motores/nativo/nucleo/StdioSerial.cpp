// Serial do motor nativo: troca o StdioSerial.cpp do EpoxyDuino. Escreve no stdout; cada linha impressa
// também vira um evento "serial" com hora. Lê primeiro o texto do roteiro (--serial, com hora marcada no
// relógio virtual) e depois o stdin (pra brincar no terminal com --real).
#include <unistd.h>
#include <string>
#include "StdioSerial.h"

void sianvolt_serial_linha(const std::string& linha);
int sianvolt_serial_chegou();
int sianvolt_serial_pega();
void sianvolt_serial_espera();

static std::string linha;
static int guardado = -1;   // o byte do peek(); o bufch do EpoxyDuino começa em 0 sem o Serial.begin()

void sianvolt_serial_termina() {
  if (!linha.empty()) sianvolt_serial_linha(linha);
  linha.clear();
}

size_t StdioSerial::write(uint8_t c) {
  ssize_t status = ::write(STDOUT_FILENO, &c, 1);
  if (c == '\n') sianvolt_serial_termina();
  else if (c != '\r') linha += (char)c;
  return (status <= 0) ? 0 : 1;
}

int StdioSerial::read() {
  int ch = peek();
  guardado = -1;
  return ch;
}

int StdioSerial::peek() {
  if (guardado == -1) {
    guardado = sianvolt_serial_pega();
    if (guardado == -1) {
      unsigned char c;
      ssize_t status = ::read(STDIN_FILENO, &c, 1);
      guardado = (status <= 0) ? -1 : c;
    }
  }
  return guardado;
}

int StdioSerial::available() {
  sianvolt_serial_espera();   // "chegou?" num laço deixa o relógio virtual andar
  int n = sianvolt_serial_chegou() + (guardado != -1);
  return n ? n : (peek() != -1);
}

StdioSerial Serial;
