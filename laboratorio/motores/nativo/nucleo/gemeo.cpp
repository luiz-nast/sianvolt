// gemeo.cpp: o miolo do Arduino de mentira do motor nativo. Troca o Arduino.cpp e o main.cpp do EpoxyDuino.
// Veio do protótipo ~/.cache/sianvolt/lab/arduino_nativo (mesmo protocolo), com o que o laboratório pediu a mais.
//
// - relógio virtual: delay(1000) não espera 1 s de verdade, só anda o ponteiro. 10 s de firmware rodam em
//   milissegundos e sempre do mesmo jeito. t = 0 é a entrada no setup().
// - conta o que o firmware faz com os pinos, com a hora: uma linha JSON por evento ({"t":<us>,"ev":...})
// - as entradas (botão, potenciômetro, texto na serial) vêm de um roteiro com hora marcada
// - interrupção (attachInterrupt) dispara na hora em que a entrada muda
// - relógio parado (laço sem delay/millis) por --parado segundos de PC: para e avisa ("parado")
// - morreu (SIGSEGV, abort...): escreve o evento "sinal" antes de sair
//
// Uso (o binário é o firmware compilado pro PC; quem chama é o motores/nativo.py):
//   ./firmware --ate 5000 --log eventos.jsonl --entrada "1500 4 0" --entrada "0 34 1650mV" --serial 500 "liga\n"
//   ./firmware --real                 (relógio de verdade, pra brincar no terminal)
//   ./firmware --gemeo 3 4            (pinos ligados no circuito por canos; ver o gemeo.py do protótipo)
// Protocolo pelos canos (--gemeo): firmware -> {"t":<us>,"ev":"le"|"le_analog","pino":n}; resposta
//   "<valor> <ate_us>" (valor 0/1 ou milivolts; vale até ate_us, -1 = até o firmware mexer).

#include <Arduino.h>   // com <>: acha o nucleo/Arduino.h pelo -I, e o include_next chega no do EpoxyDuino
#include <fcntl.h>
#include <math.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>
#include <string>
#include <vector>

extern "C" {
int epoxy_argc;
const char* const* epoxy_argv;
void enableTerminalEcho() {}
}

namespace {

const int NPINOS = 64;
const uint64_t NUNCA = UINT64_MAX;
const int MODO_ADC = -2;   // o firmware chamou analogRead (no Uno não existe o modo ANALOG)
const int MODO_PWM = -3;   // analogWrite/ledc

#if defined(PLACA_ESP32)
const char* PLACA = "esp32";
const double VCC = 3.3;
int bits_adc = 12;
const uint32_t CUSTO_ADC = 10;   // us por analogRead (ordem de grandeza)
#else
const char* PLACA = "uno";
const double VCC = 5.0;
int bits_adc = 10;
const uint32_t CUSTO_ADC = 100;  // o ADC do ATmega328P leva ~100 us (13 ciclos de ADC a 125 kHz)
#endif

struct Pino {
  int modo = -1;            // -1: o firmware nunca configurou
  int nivel = -1;           // último digitalWrite (-1: nunca)
  bool pwm = false;
  uint32_t pwm_res = 8, pwm_freq = 0;
  double duty = -1;         // último PWM (-1: nunca)
  int lido = -1;            // cache da leitura digital
  uint64_t lido_ate = 0;
  long mv = -1;             // cache da leitura analógica
  uint64_t mv_ate = 0;
  bool avisou_solto = false;
  void (*isr)() = nullptr;
  int isr_modo = 0, isr_nivel = -1;
};

Pino P[NPINOS];
bool virtual_ = true;
uint64_t t_virt = 0, t0_real = 0, ate = NUNCA;
uint32_t custo_loop = 10;          // us por volta do loop (virtual); número de faz de conta, não é o chip
FILE* ev = nullptr;                // eventos (log ou cano pro Sianvolt)
FILE* resp = nullptr;              // respostas do Sianvolt
bool tem_isr = false, em_isr = false;
uint64_t prox_isr = NUNCA;
unsigned long n_eventos = 0, n_perguntas = 0, max_eventos = 500000;
bool cheio = false;                // passou de max_eventos: para de contar os pinos
volatile sig_atomic_t em_emite = 0;
double parado_s = 0;               // 0 = sem vigia do relógio parado
uint64_t vigia_t = 0;
double vigia_parado = 0;

struct Passo { uint64_t t; int pino; long valor; bool mv; };
std::vector<Passo> roteiro;        // entradas com hora marcada (quando não tem Sianvolt)
struct Byte { uint64_t t; unsigned char c; };
std::vector<Byte> serial_rx;       // o texto que o roteiro manda pela serial, byte a byte, com hora
size_t serial_pos = 0;
std::vector<std::string> avisados;

uint64_t relogio_real() {
  timespec s;
  clock_gettime(CLOCK_MONOTONIC, &s);
  return (uint64_t)s.tv_sec * 1000000ull + s.tv_nsec / 1000;
}

uint64_t agora() { return virtual_ ? t_virt : relogio_real() - t0_real; }

void emite_sempre(const char* fmt, va_list ap) {
  em_emite = 1;
  fprintf(ev, "{\"t\":%llu,", (unsigned long long)agora());
  vfprintf(ev, fmt, ap);
  fputs("}\n", ev);
  if (!virtual_) fflush(ev);
  em_emite = 0;
}

// um evento na linha do tempo; depois de max_eventos, só os que fecham a rodada (pra não encher o disco)
void emite(const char* fmt, ...) {
  if (!ev) return;
  n_eventos++;
  if (n_eventos > max_eventos) {
    if (!cheio) {
      cheio = true;
      fprintf(ev, "{\"t\":%llu,\"ev\":\"cheio\",\"max\":%lu}\n", (unsigned long long)agora(), max_eventos);
    }
    return;
  }
  va_list ap;
  va_start(ap, fmt);
  emite_sempre(fmt, ap);
  va_end(ap);
}

void emite_fim(const char* fmt, ...) {   // não conta no limite
  if (!ev) return;
  va_list ap;
  va_start(ap, fmt);
  emite_sempre(fmt, ap);
  va_end(ap);
  fflush(ev);
}

std::string json_texto(const std::string& s) {
  std::string o = "\"";
  for (unsigned char c : s) {
    if (c == '"' || c == '\\') { o += '\\'; o += (char)c; }
    else if (c < 0x20) { char b[8]; snprintf(b, sizeof b, "\\u%04x", c); o += b; }
    else o += (char)c;
  }
  return o + "\"";
}

void avisa(const std::string& texto, const char* codigo = "nativo") {   // avisa uma vez cada coisa
  for (auto& a : avisados) if (a == texto) return;
  avisados.push_back(texto);
  emite("\"ev\":\"aviso\",\"texto\":%s,\"codigo\":\"%s\"", json_texto(texto).c_str(), codigo);
}

void nao_simula(const char* coisa) { avisa(std::string(coisa) + " não é simulado no motor nativo"); }

const char* nome_modo(int m) {
  if (m == INPUT) return "INPUT";
  if (m == OUTPUT) return "OUTPUT";
  if (m == INPUT_PULLUP) return "INPUT_PULLUP";
  if (m == MODO_ADC) return "ANALOG";
  if (m == MODO_PWM) return "PWM";
#if defined(PLACA_ESP32)
  if (m == INPUT_PULLDOWN) return "INPUT_PULLDOWN";
  if (m == OUTPUT_OPEN_DRAIN) return "OUTPUT_OPEN_DRAIN";
  if (m == ANALOG) return "ANALOG";
#endif
  return "?";
}

// o pico de RAM deste programa (VmHWM: só depois do exec, sem o Python que o abriu). Só open/read: dá pra
// chamar dentro do tratador de sinal
long ram_kb() {
  char b[4096];
  int fd = open("/proc/self/status", O_RDONLY);
  if (fd < 0) return -1;
  ssize_t n = read(fd, b, sizeof b - 1);
  close(fd);
  if (n <= 0) return -1;
  b[n] = 0;
  const char* c = strstr(b, "VmHWM:");
  if (!c) return -1;
  long kb = 0;
  for (c += 6; *c == ' ' || *c == '\t'; c++) {}
  for (; *c >= '0' && *c <= '9'; c++) kb = kb * 10 + (*c - '0');
  return kb;
}

void fim() {
  emite_fim("\"ev\":\"fim\",\"eventos\":%lu,\"perguntas\":%lu,\"ram_kb\":%ld", n_eventos, n_perguntas, ram_kb());
}

void confere_fim() {
  if (agora() >= ate) exit(0);   // o atexit escreve o "fim"
}

// morreu (SIGSEGV, abort...) ou foi desligado (SIGTERM): conta e sai com 128 + sinal, sem gerar core
// (aqui o core iria pro apport do Ubuntu e levaria mais de 1 s)
void morreu(int sinal) {
  if (ev && !em_emite) {
    fprintf(ev, "{\"t\":%llu,\"ev\":\"sinal\",\"n\":%d,\"ram_kb\":%ld}\n", (unsigned long long)agora(), sinal,
            ram_kb());
    fflush(ev);
  }
  _exit(128 + sinal);
}

// a cada 250 ms de CPU: se o relógio virtual não andou por parado_s segundos, o firmware está num laço que
// não chama delay/millis/digitalRead (na placa seria um laço sem fim). Conta e sai.
void vigia(int) {
  if (t_virt != vigia_t) { vigia_t = t_virt; vigia_parado = 0; return; }
  vigia_parado += 0.25;
  if (vigia_parado < parado_s || em_emite) return;
  if (ev) {
    fprintf(ev, "{\"t\":%llu,\"ev\":\"parado\",\"pc_s\":%.2f,\"ram_kb\":%ld}\n", (unsigned long long)t_virt,
            vigia_parado, ram_kb());
    fflush(ev);
  }
  _exit(4);
}

bool tem_passo(int pino, bool analog) {
  for (const Passo& s : roteiro) if (s.pino == pino && s.mv == analog) return true;
  return false;
}

// a pergunta: quanto vale a entrada agora e até quando esse valor vale
void pergunta(bool analog, int pino, long* valor, uint64_t* valido_ate) {
  n_perguntas++;
  if (resp) {
    emite("\"ev\":\"%s\",\"pino\":%d", analog ? "le_analog" : "le", pino);
    fflush(ev);
    char linha[128];
    if (!fgets(linha, sizeof linha, resp)) {
      fprintf(stderr, "gemeo: o Sianvolt fechou o cano\n");
      exit(3);
    }
    long v = 0;
    long long a = -1;
    sscanf(linha, "%ld %lld", &v, &a);
    *valor = v;
    *valido_ate = a < 0 ? NUNCA : (uint64_t)a;
    return;
  }
  // sem Sianvolt: o roteiro decide; antes do primeiro passo, o que a placa leria com o pino solto
  Pino& p = P[pino];
  uint64_t t = agora();
  if (!analog && p.modo == INPUT && !p.avisou_solto && !tem_passo(pino, false)) {
    p.avisou_solto = true;
    emite("\"ev\":\"solto\",\"pino\":%d", pino);
  }
  long v = analog ? 0 : (p.modo == INPUT_PULLUP ? 1 : (p.modo == OUTPUT ? (p.nivel > 0) : 0));
  uint64_t prox = NUNCA;
  for (const Passo& s : roteiro) {
    if (s.pino != pino || s.mv != analog) continue;
    if (s.t <= t) v = s.valor;
    else if (s.t < prox) prox = s.t;
  }
  *valor = v;
  *valido_ate = prox;
}

int le_digital(int pino) {
  Pino& p = P[pino];
  uint64_t t = agora();
  if (p.lido >= 0 && t < p.lido_ate) return p.lido;
  long v;
  uint64_t a;
  pergunta(false, pino, &v, &a);
  p.lido = v ? 1 : 0;
  p.lido_ate = a;
  return p.lido;
}

long le_mv(int pino) {
  Pino& p = P[pino];
  uint64_t t = agora();
  if (p.mv >= 0 && t < p.mv_ate) return p.mv;
  long v;
  uint64_t a;
  pergunta(true, pino, &v, &a);
  p.mv = v < 0 ? 0 : v;
  p.mv_ate = a;
  return p.mv;
}

void recalcula_prox_isr() {
  prox_isr = NUNCA;
  for (int i = 0; i < NPINOS; i++)
    if (P[i].isr && P[i].lido_ate < prox_isr) prox_isr = P[i].lido_ate;
}

void dispara_isrs() {
  if (em_isr || !tem_isr) return;
  for (int i = 0; i < NPINOS; i++) {
    Pino& p = P[i];
    if (!p.isr) continue;
    p.lido = -1;
    int antes = p.isr_nivel, depois = le_digital(i);
    p.isr_nivel = depois;
    bool sobe = antes == 0 && depois == 1, desce = antes == 1 && depois == 0;
    bool vai = (p.isr_modo == RISING && sobe) || (p.isr_modo == FALLING && desce) ||
               (p.isr_modo == CHANGE && (sobe || desce));
#if defined(PLACA_ESP32)
    vai = vai || (p.isr_modo == ONLOW && depois == 0) || (p.isr_modo == ONHIGH && depois == 1);
#endif
    if (vai) {
      emite("\"ev\":\"isr\",\"pino\":%d,\"nivel\":%d", i, depois);
      em_isr = true;
      p.isr();
      em_isr = false;
    }
  }
  recalcula_prox_isr();
}

// o firmware mexeu num pino: o que ele lê pode ter mudado (um pino de saída ligado num de entrada)
void mexeu() {
  for (int i = 0; i < NPINOS; i++) P[i].lido = -1, P[i].mv = -1;
  if (tem_isr) dispara_isrs();
}

void muda_modo(int pino, int modo) {
  Pino& p = P[pino];
  if (p.modo == modo) return;
  p.modo = modo;
  emite("\"ev\":\"modo\",\"pino\":%d,\"modo\":\"%s\"", pino, nome_modo(modo));
}

void escreve(int pino, int v) {
  Pino& p = P[pino];
  if (p.nivel == v && !p.pwm) return;   // escrever o mesmo valor não muda nada no pino
  p.nivel = v;
  p.pwm = false;
  p.duty = -1;
  emite("\"ev\":\"escreve\",\"pino\":%d,\"v\":%d", pino, v);
  mexeu();
}

// PWM: só conta quando muda (o sketch costuma escrever o mesmo brilho a cada volta do loop)
void muda_pwm(int pino, double duty, double freq) {
  Pino& p = P[pino];
  if (p.modo != MODO_PWM) muda_modo(pino, MODO_PWM);
  if (p.duty >= 0 && fabs(p.duty - duty) < 1e-6) return;
  p.duty = duty;
  p.pwm = duty > 0 && duty < 1;
  p.nivel = duty >= 1 ? 1 : (duty <= 0 ? 0 : -1);
  emite("\"ev\":\"pwm\",\"pino\":%d,\"duty\":%.4f,\"freq\":%.3f", pino, duty, freq);
  mexeu();
}

// o tempo passa: no virtual, pula direto; no real, dorme. Pelo caminho, as interrupções
void anda(uint64_t dt) {
  if (virtual_) {
    uint64_t alvo = t_virt + dt;
    while (tem_isr && !em_isr && prox_isr <= alvo && prox_isr <= ate) {
      if (prox_isr > t_virt) t_virt = prox_isr;   // pula direto pra hora em que a entrada muda
      dispara_isrs();
    }
    t_virt = alvo < ate ? alvo : ate;
    confere_fim();
    return;
  }
  uint64_t alvo = agora() + dt;
  for (;;) {
    uint64_t t = agora();
    if (t >= alvo || t >= ate) break;
    uint64_t ate_ = alvo < ate ? alvo : ate;
    if (tem_isr && prox_isr < ate_) ate_ = prox_isr > t ? prox_isr : t + 100;
    usleep((useconds_t)(ate_ - t));
    if (tem_isr && agora() >= prox_isr) dispara_isrs();
  }
  confere_fim();
}

// chamada barata (millis, digitalRead): no virtual custa 1 us; no real o relógio anda sozinho
void tique(uint64_t us) {
  if (virtual_) anda(us);
  else {
    if (tem_isr && agora() >= prox_isr) dispara_isrs();
    confere_fim();
  }
}

void le_roteiro(const char* linha) {
  // "1500 4 0"  -> aos 1500 ms o pino 4 lê 0
  // "0 34 1650mV" -> o pino 34 (analógico) lê 1,65 V
  double ms;
  int pino;
  char val[32] = {0};
  if (sscanf(linha, "%lf %d %31s", &ms, &pino, val) != 3 || pino < 0 || pino >= NPINOS || ms < 0) {
    fprintf(stderr, "gemeo: não entendi a entrada \"%s\" (formato: <ms> <pino> <0|1|1650mV>)\n", linha);
    exit(2);
  }
  bool mv = strstr(val, "mV") || strstr(val, "mv");
  roteiro.push_back({(uint64_t)llround(ms * 1000), pino, atol(val), mv});
}

void le_serial(const char* ms, const char* texto) {   // --serial 500 "liga\n"
  char* fim_ = nullptr;
  double t = strtod(ms, &fim_);
  if (fim_ == ms || t < 0) {
    fprintf(stderr, "gemeo: não entendi a hora \"%s\" do --serial\n", ms);
    exit(2);
  }
  if (!*texto) return;
  std::vector<Byte> novos;
  for (const char* c = texto; *c; c++) novos.push_back({(uint64_t)llround(t * 1000), (unsigned char)*c});
  // em ordem de hora (o roteiro já vem em ordem; isto só garante)
  size_t i = serial_rx.size();
  while (i > 0 && serial_rx[i - 1].t > novos[0].t) i--;
  serial_rx.insert(serial_rx.begin() + i, novos.begin(), novos.end());
}

void ajuda() {
  fprintf(stderr,
          "firmware no motor nativo do laboratório do Sianvolt (sabor %s)\n"
          "  --ate MS           para depois de MS milissegundos de firmware (padrão 10000 no virtual)\n"
          "  --real             relógio de verdade (padrão: virtual, rápido e sempre igual)\n"
          "  --log ARQ          escreve os eventos (JSON, uma linha cada) em ARQ (- = stderr)\n"
          "  --entrada \"MS PINO VALOR\"   entrada com hora marcada; VALOR 0/1 ou 1650mV (repete)\n"
          "  --roteiro ARQ      as entradas num arquivo, uma por linha (# comenta)\n"
          "  --serial MS TEXTO  o texto chega na serial do firmware aos MS milissegundos (repete)\n"
          "  --parado S         sai se o relógio virtual ficar S segundos de CPU sem andar (padrão: não sai)\n"
          "  --max-eventos N    depois de N eventos para de contar os pinos (padrão 500000)\n"
          "  --custo-loop US    quanto tempo de faz de conta cada volta do loop() gasta (padrão 10)\n"
          "  --gemeo FD_OUT FD_IN   conversa com o Sianvolt (o gemeo.py do protótipo abre os canos)\n",
          PLACA);
}

void configura(int argc, char** argv) {
  bool deu_ate = false;
  for (int i = 1; i < argc; i++) {
    std::string a = argv[i];
    auto proximo = [&]() -> const char* {
      if (i + 1 >= argc) { ajuda(); exit(2); }
      return argv[++i];
    };
    if (a == "--ate") { ate = (uint64_t)llround(atof(proximo()) * 1000); deu_ate = true; }
    else if (a == "--real") virtual_ = false;
    else if (a == "--log") {
      const char* f = proximo();
      ev = strcmp(f, "-") == 0 ? stderr : fopen(f, "w");
      if (!ev) { perror(f); exit(2); }
    } else if (a == "--entrada") le_roteiro(proximo());
    else if (a == "--roteiro") {
      const char* f = proximo();
      FILE* r = fopen(f, "r");
      if (!r) { perror(f); exit(2); }
      char linha[256];
      while (fgets(linha, sizeof linha, r)) {
        char* c = strchr(linha, '#');
        if (c) *c = 0;
        if (strspn(linha, " \t\r\n") < strlen(linha)) le_roteiro(linha);
      }
      fclose(r);
    } else if (a == "--serial") {
      const char* ms = proximo();
      le_serial(ms, proximo());
    } else if (a == "--parado") parado_s = atof(proximo());
    else if (a == "--max-eventos") max_eventos = (unsigned long)atol(proximo());
    else if (a == "--custo-loop") custo_loop = (uint32_t)atol(proximo());
    else if (a == "--gemeo") {
      ev = fdopen(atoi(proximo()), "w");
      resp = fdopen(atoi(proximo()), "r");
      if (!ev || !resp) { perror("gemeo"); exit(2); }
    } else if (a == "--ajuda" || a == "-h") { ajuda(); exit(0); }
    else { fprintf(stderr, "gemeo: não conheço \"%s\"\n", a.c_str()); ajuda(); exit(2); }
  }
  if (virtual_ && !deu_ate) ate = 10000000;   // 10 s de firmware
  if (ev && ev != stderr) setvbuf(ev, nullptr, _IOFBF, 1 << 16);
}

void liga_sinais() {
  struct sigaction s;
  memset(&s, 0, sizeof s);
  s.sa_handler = morreu;
  for (int n : {SIGSEGV, SIGABRT, SIGFPE, SIGBUS, SIGILL, SIGTERM}) sigaction(n, &s, nullptr);
  if (virtual_ && parado_s > 0) {
    s.sa_handler = vigia;
    s.sa_flags = SA_RESTART;
    sigaction(SIGVTALRM, &s, nullptr);
    itimerval it = {{0, 250000}, {0, 250000}};
    setitimer(ITIMER_VIRTUAL, &it, nullptr);   // tempo de CPU do firmware: PC lento ou ocupado não conta
  }
}

}  // namespace

// ------------------------------------------------------------------ a serial que vem do roteiro (StdioSerial.cpp)

int sianvolt_serial_chegou() {   // quantos bytes do roteiro já chegaram e ninguém leu
  uint64_t t = agora();
  int n = 0;
  for (size_t i = serial_pos; i < serial_rx.size() && serial_rx[i].t <= t; i++) n++;
  return n;
}

int sianvolt_serial_pega() {     // o próximo byte que já chegou, ou -1
  if (serial_pos < serial_rx.size() && serial_rx[serial_pos].t <= agora()) return serial_rx[serial_pos++].c;
  return -1;
}

void sianvolt_serial_espera() { tique(1); }   // quem fica perguntando "chegou?" deixa o tempo passar

// ------------------------------------------------------------------ a API do Arduino

extern "C" {

void yield() {
  if (virtual_) tique(1);
  else usleep(100);   // no real, não deixa o PC a 100%
}

void pinMode(uint8_t pino, uint8_t modo) {
  if (pino >= NPINOS) return;
  P[pino].pwm = false;
  P[pino].duty = -1;
  P[pino].modo = -1;   // sempre conta, mesmo repetido
  muda_modo(pino, modo);
  mexeu();
}

void digitalWrite(uint8_t pino, uint8_t val) {
  if (pino >= NPINOS) return;
  escreve(pino, val ? 1 : 0);
}

int digitalRead(uint8_t pino) {
  if (pino >= NPINOS) return 0;
  tique(1);
  return le_digital(pino);
}

// o que o EpoxyDuino tinha pra teste: continua funcionando (vira um passo do roteiro "agora")
void digitalReadValue(uint8_t pino, uint8_t val) {
  if (pino >= NPINOS) return;
  roteiro.push_back({agora(), pino, (long)(val ? 1 : 0), false});
  P[pino].lido = -1;
}

uint8_t digitalWriteValue(uint8_t pino) { return pino < NPINOS && P[pino].nivel > 0; }

int analogRead(uint8_t pino) {
  if (pino >= NPINOS) return 0;
  if (P[pino].modo != MODO_ADC
#if defined(PLACA_ESP32)
      && P[pino].modo != ANALOG
#endif
  )
    muda_modo(pino, MODO_ADC);
  tique(CUSTO_ADC);
  long mv = le_mv(pino);
  long max = (1L << bits_adc) - 1;
  long raw = (long)(mv / (VCC * 1000.0) * max + 0.5);
  return raw < 0 ? 0 : (raw > max ? max : raw);
}

void analogReference(uint8_t) { nao_simula("analogReference"); }

#if defined(PLACA_ESP32)
// arduino-esp32 3.x (cores/esp32/esp32-hal-ledc.c): analogWrite liga o LEDC a 1000 Hz, 8 bits, e
// ledcWrite com o valor máximo (255) vira 100%; o resto é valor / 256
// https://github.com/espressif/arduino-esp32/blob/master/cores/esp32/esp32-hal-ledc.c
void analogWrite(uint8_t pino, int val) {
  if (pino >= NPINOS) return;
  if (P[pino].modo != MODO_PWM) P[pino].pwm_freq = 1000, P[pino].pwm_res = 8;
  uint32_t max = (1u << P[pino].pwm_res) - 1;
  double d = val <= 0 ? 0 : ((uint32_t)val >= max ? 1 : val / (double)(max + 1));
  muda_pwm(pino, d, P[pino].pwm_freq);
}
#else
// ArduinoCore-avr (cores/arduino/wiring_analog.c): 0 e 255 viram digitalWrite; pino sem timer vira LOW/HIGH
// (abaixo/acima de 128). Timer0 (pinos 5 e 6) é fast PWM: (val+1)/256 a 976,5625 Hz; timers 1 e 2 (3, 9,
// 10, 11) são phase correct: val/255 a 490,196 Hz (16 MHz / 64 / 510).
// https://github.com/arduino/ArduinoCore-avr/blob/master/cores/arduino/wiring_analog.c
void analogWrite(uint8_t pino, int val) {
  if (pino >= NPINOS) return;
  bool timer0 = pino == 5 || pino == 6, outro = pino == 3 || pino == 9 || pino == 10 || pino == 11;
  if (P[pino].modo != OUTPUT && P[pino].modo != MODO_PWM) muda_modo(pino, OUTPUT);   // o core chama pinMode
  if (val <= 0 || val >= 255 || !(timer0 || outro)) {
    escreve(pino, val >= 128 ? 1 : 0);
    return;
  }
  muda_pwm(pino, timer0 ? (val + 1) / 256.0 : val / 255.0, timer0 ? 976.5625 : 490.196);
}
#endif

unsigned long millis() {
  tique(1);
  return (unsigned long)(agora() / 1000);
}

unsigned long micros() {
  tique(1);
  return (unsigned long)agora();
}

void delay(unsigned long ms) { anda((uint64_t)ms * 1000); }

void delayMicroseconds(unsigned int us) { anda(us); }

unsigned long pulseIn(uint8_t pino, uint8_t estado, unsigned long timeout) {
  if (pino >= NPINOS) return 0;
  uint64_t t0 = agora(), limite = t0 + timeout;
  int alvo = estado ? 1 : 0;
  while (le_digital(pino) == alvo) { if (agora() >= limite) return 0; tique(1); }   // espera o pulso anterior acabar
  while (le_digital(pino) != alvo) { if (agora() >= limite) return 0; tique(1); }
  uint64_t comeco = agora();
  while (le_digital(pino) == alvo) { if (agora() >= limite) return 0; tique(1); }
  return (unsigned long)(agora() - comeco);
}

unsigned long pulseInLong(uint8_t pino, uint8_t estado, unsigned long timeout) {
  return pulseIn(pino, estado, timeout);
}

void shiftOut(uint8_t dados, uint8_t clock, uint8_t ordem, uint8_t val) {
  for (int i = 0; i < 8; i++) {
    int bit = ordem == LSBFIRST ? (val >> i) & 1 : (val >> (7 - i)) & 1;
    digitalWrite(dados, bit);
    digitalWrite(clock, HIGH);
    digitalWrite(clock, LOW);
  }
}

uint8_t shiftIn(uint8_t dados, uint8_t clock, uint8_t ordem) {
  uint8_t v = 0;
  for (int i = 0; i < 8; i++) {
    digitalWrite(clock, HIGH);
    int bit = digitalRead(dados);
    v |= ordem == LSBFIRST ? bit << i : bit << (7 - i);
    digitalWrite(clock, LOW);
  }
  return v;
}

void attachInterrupt(uint8_t num, void (*rotina)(void), int modo) {
#if defined(PLACA_ESP32)
  int pino = num;
#else
  int pino = num == 0 ? 2 : (num == 1 ? 3 : -1);
#endif
  if (pino < 0 || pino >= NPINOS) return;
  Pino& p = P[pino];
  p.isr = rotina;
  p.isr_modo = modo;
  p.lido = -1;
  p.isr_nivel = le_digital(pino);
  tem_isr = true;
  emite("\"ev\":\"interrupcao\",\"pino\":%d,\"modo\":%d", pino, modo);
  recalcula_prox_isr();
}

void detachInterrupt(uint8_t num) {
#if defined(PLACA_ESP32)
  int pino = num;
#else
  int pino = num == 0 ? 2 : (num == 1 ? 3 : -1);
#endif
  if (pino < 0 || pino >= NPINOS) return;
  P[pino].isr = nullptr;
  tem_isr = false;
  for (int i = 0; i < NPINOS; i++) tem_isr = tem_isr || P[i].isr;
  recalcula_prox_isr();
}

}  // extern "C"

void tone(uint8_t pino, unsigned int freq, unsigned long dur) {
  emite("\"ev\":\"tom\",\"pino\":%d,\"freq\":%u,\"dur_ms\":%lu", pino, freq, dur);
}

void noTone(uint8_t pino) { emite("\"ev\":\"tom\",\"pino\":%d,\"freq\":0,\"dur_ms\":0", pino); }

void sianvolt_marca(const char* texto) { emite("\"ev\":\"marca\",\"texto\":%s", json_texto(texto).c_str()); }

// o espelho do Serial: cada linha que o firmware imprime vira um evento com hora
void sianvolt_serial_linha(const std::string& linha) {
  emite("\"ev\":\"serial\",\"texto\":%s", json_texto(linha).c_str());
}

#if defined(PLACA_ESP32)
EspClass ESP;
void EspClass::restart() {
  emite("\"ev\":\"reinicia\"");
  exit(0);
}

bool ledcAttach(uint8_t pino, uint32_t freq, uint8_t res) {
  if (pino >= NPINOS || res < 1 || res > 20) return false;
  P[pino].pwm_freq = freq;
  P[pino].pwm_res = res;
  muda_modo(pino, MODO_PWM);
  return true;
}

bool ledcWrite(uint8_t pino, uint32_t duty) {
  if (pino >= NPINOS) return false;
  uint32_t max = (1u << P[pino].pwm_res) - 1;   // o mesmo arredondamento do core 3.x (ver analogWrite)
  muda_pwm(pino, duty >= max ? 1 : duty / (double)(max + 1), P[pino].pwm_freq);
  return true;
}

bool ledcDetach(uint8_t pino) {
  if (pino >= NPINOS) return false;
  P[pino].pwm = false;
  return true;
}

uint32_t analogReadMilliVolts(uint8_t pino) {
  if (pino >= NPINOS) return 0;
  if (P[pino].modo != MODO_ADC && P[pino].modo != ANALOG) muda_modo(pino, MODO_ADC);
  tique(CUSTO_ADC);
  return (uint32_t)le_mv(pino);
}

void analogReadResolution(uint8_t bits) { bits_adc = bits; }
#endif

// ------------------------------------------------------------------ main

extern void sianvolt_serial_termina();

int main(int argc, char** argv) {
  epoxy_argc = argc;
  epoxy_argv = argv;
  configura(argc, argv);
  t0_real = relogio_real();
  fcntl(STDIN_FILENO, F_SETFL, fcntl(STDIN_FILENO, F_GETFL, 0) | O_NONBLOCK);   // Serial.read() não trava
  atexit([] { sianvolt_serial_termina(); fim(); });
  liga_sinais();
  emite("\"ev\":\"inicio\",\"placa\":\"%s\",\"tempo\":\"%s\",\"vcc\":%.1f", PLACA, virtual_ ? "virtual" : "real", VCC);
  setup();
  for (;;) {
    loop();
    if (virtual_) tique(custo_loop);
    else yield();
  }
}
