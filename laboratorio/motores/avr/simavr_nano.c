// simavr_nano: o Arduino Nano (ATmega328P) no simavr, sem placa. É o miolo do motor 'simavr' (motores/simavr.py).
// Roda o mesmo .elf que vai pra placa, instrução por instrução, em tempo virtual (sem esperar o relógio).
// Escreve um evento JSON por linha no stdout (o simavr.py converte pro contrato):
//   inicio  o programa começou: o PC chegou no endereço de --inicio (o main(), que chama o setup())
//   pino    só pino de SAÍDA, quando o nível muda (e o nível de quando ele vira saída)
//   modo    saida / entrada / pullup, quando muda
//   pwm     duty lido dos registradores dos timers (OCRnx/TCCRnx), no máximo 1 a cada 11 ms por pino (< 100/s)
//   serial  uma linha que o programa escreveu na UART0, em UTF-8 (bytes passados sem mexer)
//   aviso, fim (estado: tempo | acabou | travou | limite = passou do --limite-pc segundos de PC)
// t_ms = tempo de placa desde o --inicio = ciclos / 16 MHz.
//
// Uso: simavr_nano firmware.elf [--ms 3000] [--limite-pc 24] [--inicio 0x2ba] [--pino D2=0@1000] [--adc A0=2.5@0]
//                  [--serial 6c6967610a@500]   (texto em hexadecimal: qualquer byte, sem escape)
// Compilar (o simavr.py faz): gcc -O2 simavr_nano.c -I<simavr>/sim -I<simavr> <simavr>/obj-*/libsimavr.a -lelf -lm
// Licença: linka com a libsimavr (GPL-3, https://github.com/buserror/simavr), então o binário compilado é GPL-3.
// Ele só existe em .ferramentas/simavr/ (fora do git); este arquivo-fonte vai pro repositório.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "sim_avr.h"
#include "sim_elf.h"
#include "sim_hex.h"
#include "sim_io.h"
#include "avr_ioport.h"
#include "avr_uart.h"
#include "avr_adc.h"

#define FREQ 16000000u
static avr_t *avr;
static int comecou = 0;
static avr_cycle_count_t c0 = 0;   // ciclo do começo do programa
static double t_ms(void) { return comecou ? (double)(avr->cycle - c0) * 1000.0 / FREQ : 0.0; }

// ---------- pinos: porta B = D8..D13, C = A0..A5, D = D0..D7 ----------
static const char PORTAS[3] = {'B', 'C', 'D'};
static const int R_DDR[3] = {0x24, 0x27, 0x2A}, R_PORT[3] = {0x25, 0x28, 0x2B};
enum { ENTRADA, SAIDA, PULLUP };
static const char *MODOS[3] = {"entrada", "saida", "pullup"};
typedef struct { int porta, bit; char nome[8]; int nivel, modo, pwm; } pino_t;
static pino_t pinos[3][8];

static void ev_pino(pino_t *p, int v) {
	p->nivel = v;
	if (comecou) printf("{\"t_ms\":%.3f,\"tipo\":\"pino\",\"pino\":\"%s\",\"valor\":%d}\n", t_ms(), p->nome, v);
}
static void ev_modo(pino_t *p, int m) {
	if (p->modo == m) return;
	p->modo = m;
	if (comecou) printf("{\"t_ms\":%.3f,\"tipo\":\"modo\",\"pino\":\"%s\",\"modo\":\"%s\"}\n", t_ms(), p->nome, MODOS[m]);
}
// o nível do pino mudou (o simavr já aplica o pull-up): só interessa pino de saída fora do PWM
static void ao_mudar_pino(struct avr_irq_t *irq, uint32_t value, void *param) {
	pino_t *p = (pino_t *)param;
	int v = value ? 1 : 0;
	if (((avr->data[R_DDR[p->porta]] >> p->bit) & 1) && !p->pwm && v != p->nivel) ev_pino(p, v);
}
// DDR escrito (o valor novo vem em value; avr->data ainda tem o antigo)
static void ao_mudar_ddr(struct avr_irq_t *irq, uint32_t value, void *param) {
	int k = (int)(intptr_t)param;
	uint8_t port = avr->data[R_PORT[k]];
	for (int b = 0; b < 8; b++) {
		pino_t *p = &pinos[k][b];
		if (!p->nome[0]) continue;
		int saida = (value >> b) & 1;
		ev_modo(p, saida ? SAIDA : ((port >> b) & 1) ? PULLUP : ENTRADA);
		if (saida && !p->pwm && ((port >> b) & 1) != p->nivel) ev_pino(p, (port >> b) & 1);   // vira saída já num nível
		if (!saida) p->nivel = -1;
	}
}
// PORT escrito: num pino de entrada, liga ou desliga o pull-up
static void ao_mudar_port(struct avr_irq_t *irq, uint32_t value, void *param) {
	int k = (int)(intptr_t)param;
	uint8_t ddr = avr->data[R_DDR[k]];
	for (int b = 0; b < 8; b++)
		if (pinos[k][b].nome[0] && !((ddr >> b) & 1)) ev_modo(&pinos[k][b], ((value >> b) & 1) ? PULLUP : ENTRADA);
}
static pino_t *pino_de_nome(const char *s) {
	int n = atoi(s + 1);
	if (s[0] == 'D' && n >= 0 && n < 8) return &pinos[2][n];
	if (s[0] == 'D' && n >= 8 && n <= 13) return &pinos[0][n - 8];
	if (s[0] == 'A' && n >= 0 && n <= 5) return &pinos[1][n];
	return NULL;
}

// ---------- PWM pelos registradores dos timers (o simavr não põe a onda no pino em phase-correct) ----------
// ATmega328P: OC0A=D6 OC0B=D5 (timer 0), OC1A=D9 OC1B=D10 (timer 1), OC2A=D11 OC2B=D3 (timer 2)
typedef struct { const char *nome; int timer, com_shift, ocr; double visto, visto_t, emitido, emitido_t; } pwm_t;
static pwm_t pwms[] = {
	{"D6", 0, 6, 0x47}, {"D5", 0, 4, 0x48}, {"D9", 1, 6, 0x88}, {"D10", 1, 4, 0x8A}, {"D11", 2, 6, 0xB3}, {"D3", 2, 4, 0xB4},
};
static const int TCCRA[3] = {0x44, 0x80, 0xB0}, TCCRB[3] = {0x45, 0x81, 0xB1};
static const int DIV01[8] = {0, 1, 8, 64, 256, 1024, 0, 0}, DIV2[8] = {0, 1, 8, 32, 64, 128, 256, 1024};
#define U16(a) (avr->data[a] | (avr->data[(a) + 1] << 8))

// duty de 0 a 1, ou -1 se o pino não está em PWM agora
static double duty_de(pwm_t *w, double *freq) {
	int a = avr->data[TCCRA[w->timer]], b = avr->data[TCCRB[w->timer]], com = (a >> w->com_shift) & 3;
	pino_t *p = pino_de_nome(w->nome);
	int div = (w->timer == 2 ? DIV2 : DIV01)[b & 7];
	if (com < 2 || !div || !((avr->data[R_DDR[p->porta]] >> p->bit) & 1)) return -1;
	int wgm = (a & 3) | (w->timer == 1 ? ((b >> 3) & 3) << 2 : ((b >> 3) & 1) << 2), top, rapido;
	if (w->timer != 1) {   // timers de 8 bits
		if (wgm != 1 && wgm != 3 && wgm != 5 && wgm != 7) return -1;
		top = wgm >= 5 ? avr->data[w->timer == 0 ? 0x47 : 0xB3] : 0xFF;
		rapido = wgm == 3 || wgm == 7;
	} else {
		static const int TOPS[16] = {0, 0xFF, 0x1FF, 0x3FF, 0, 0xFF, 0x1FF, 0x3FF, -1, -2, -1, -2, 0, 0, -1, -2};
		top = TOPS[wgm];
		if (!top) return -1;
		if (top == -1) top = U16(0x86);   // ICR1
		if (top == -2) top = U16(0x88);   // OCR1A
		rapido = wgm >= 5 && wgm <= 7 ? 1 : wgm >= 14;
	}
	if (top <= 0) return -1;
	int ocr = w->timer == 1 ? U16(w->ocr) : avr->data[w->ocr];
	double d = rapido ? (ocr + 1.0) / (top + 1.0) : (double)ocr / top;
	if (d > 1) d = 1;
	if (com == 3) d = 1 - d;   // invertido
	*freq = rapido ? (double)FREQ / div / (top + 1) : (double)FREQ / div / (2.0 * top);
	return d;
}
static void olhar_pwm(void) {
	double agora = t_ms();
	for (unsigned k = 0; k < sizeof pwms / sizeof pwms[0]; k++) {
		pwm_t *w = &pwms[k];
		double f = 0, d = duty_de(w, &f);
		pino_t *p = pino_de_nome(w->nome);
		if (d != w->visto) { w->visto = d; w->visto_t = agora; continue; }   // espera ficar igual em 2 olhadas
		if (d == w->emitido || (w->emitido >= 0 && agora - w->emitido_t < 11.0)) continue;
		if (d < 0) {   // saiu do PWM: o pino volta a falar pelo nível
			p->pwm = 0;
			int v = (avr->data[R_PORT[p->porta]] >> p->bit) & 1;
			if (v != p->nivel) ev_pino(p, v);
		} else {
			p->pwm = 1;
			if (comecou) printf("{\"t_ms\":%.3f,\"tipo\":\"pwm\",\"pino\":\"%s\",\"duty\":%.4f,\"freq_hz\":%.1f}\n",
			                    w->visto_t, w->nome, d, f);
		}
		w->emitido = d; w->emitido_t = agora;
	}
}

// ---------- Serial (UART0), uma linha por evento ----------
static char linha[1024];
static int nlinha = 0;
static void soltar_linha(void) {
	printf("{\"t_ms\":%.3f,\"tipo\":\"serial\",\"texto\":\"", t_ms());
	for (int i = 0; i < nlinha; i++) {
		unsigned char c = linha[i];
		if (c == '"' || c == '\\') printf("\\%c", c);
		else if (c < 0x20 || c == 0x7f) printf("\\u%04x", c);
		else putchar(c);   // UTF-8 passa como veio
	}
	printf("\"}\n");
	nlinha = 0;
}
static void ao_sair_byte(struct avr_irq_t *irq, uint32_t value, void *param) {
	char c = (char)value;
	if (c == '\r') return;
	if (c == '\n') { soltar_linha(); return; }
	linha[nlinha++] = c;
	if (nlinha == (int)sizeof(linha)) soltar_linha();
}

// ---------- entradas do roteiro, em ordem de tempo ----------
typedef struct { double t; int tipo; pino_t *pino; int valor; unsigned char *texto; int n, pos, feito; } estimulo_t;
static estimulo_t *est;
static int nest = 0;
static int por_tempo(const void *a, const void *b) {
	double d = ((const estimulo_t *)a)->t - ((const estimulo_t *)b)->t;
	return d < 0 ? -1 : d > 0;
}
static void nao_dormir(struct avr_t *a, avr_cycle_count_t howLong) { (void)a; (void)howLong; }
static void fim(const char *estado, const char *motivo, double real) {
	if (nlinha) soltar_linha();
	if (motivo) printf("{\"t_ms\":%.3f,\"tipo\":\"aviso\",\"texto\":\"%s\",\"codigo\":\"simavr\"}\n", t_ms(), motivo);
	printf("{\"t_ms\":%.3f,\"tipo\":\"fim\",\"estado\":\"%s\",\"ciclos\":%llu,\"tempo_real_ms\":%.1f,\"velocidade\":%.2f}\n",
	       t_ms(), estado, (unsigned long long)avr->cycle, real, real > 0 ? t_ms() / real : 0);
	fflush(stdout);
}

int main(int argc, char **argv) {
	const char *arquivo = NULL;
	double ms = 3000, limite_pc = 0;
	long inicio = -1;
	est = calloc(argc, sizeof *est);
	for (int i = 1; i < argc; i++) {
		char nome[16]; double v, t;
		if (!strcmp(argv[i], "--ms") && i + 1 < argc) ms = atof(argv[++i]);
		else if (!strcmp(argv[i], "--limite-pc") && i + 1 < argc) limite_pc = atof(argv[++i]);
		else if (!strcmp(argv[i], "--inicio") && i + 1 < argc) inicio = strtol(argv[++i], NULL, 0);
		else if ((!strcmp(argv[i], "--pino") || !strcmp(argv[i], "--adc")) && i + 1 < argc) {
			int adc = argv[i][2] == 'a';
			estimulo_t *e = &est[nest++];
			if (sscanf(argv[++i], "%15[^=]=%lf@%lf", nome, &v, &t) != 3) { fprintf(stderr, "%s P=v@ms\n", argv[i - 1]); return 2; }
			e->t = t; e->tipo = adc ? 2 : 0; e->valor = adc ? (int)(v * 1000 + 0.5) : (v != 0);
			if (adc) { if (nome[0] != 'A' || atoi(nome + 1) > 7) { fprintf(stderr, "--adc: A0..A7\n"); return 2; } e->n = atoi(nome + 1); }
			else if (!(e->pino = pino_de_nome(nome))) { fprintf(stderr, "pino? %s\n", nome); return 2; }
		} else if (!strcmp(argv[i], "--serial") && i + 1 < argc) {
			const char *s = argv[++i], *arroba = strrchr(s, '@');
			estimulo_t *e = &est[nest++];
			int n = arroba ? (int)(arroba - s) / 2 : 0;
			e->tipo = 1; e->t = arroba ? atof(arroba + 1) : 0; e->texto = malloc(n + 1); e->n = n;
			for (int j = 0; j < n; j++) { unsigned x; sscanf(s + 2 * j, "%2x", &x); e->texto[j] = (unsigned char)x; }
		} else if (argv[i][0] != '-') arquivo = argv[i];
	}
	if (!arquivo) { fprintf(stderr, "uso: simavr_nano firmware.elf [--ms N] [--inicio end] [--pino D2=0@1000] ...\n"); return 2; }
	qsort(est, nest, sizeof *est, por_tempo);

	elf_firmware_t f; memset(&f, 0, sizeof f);
	strcpy(f.mmcu, "atmega328p"); f.frequency = FREQ;
	f.vcc = f.avcc = f.aref = 5000;   // milivolts: Nano em 5 V
	fflush(stdout); int so = dup(1); dup2(2, 1);   // o carregador escreve "Loaded N bytes" no stdout
	sim_setup_firmware(arquivo, AVR_SEGMENT_OFFSET_FLASH, &f, "simavr_nano");
	fflush(stdout); dup2(so, 1); close(so);
	strcpy(f.mmcu, "atmega328p"); f.frequency = FREQ;
	avr = avr_make_mcu_by_name(f.mmcu);
	if (!avr) { fprintf(stderr, "mcu desconhecido\n"); return 1; }
	avr_init(avr);
	avr->log = 0;
	avr_load_firmware(avr, &f);
	avr->frequency = FREQ;
	avr->sleep = nao_dormir;   // tempo virtual: dormir não espera o relógio

	for (int k = 0; k < 3; k++) {
		for (int b = 0; b < 8; b++) {
			pino_t *p = &pinos[k][b];
			p->porta = k; p->bit = b; p->nivel = -1; p->modo = ENTRADA;
			if (PORTAS[k] == 'D') sprintf(p->nome, "D%d", b);
			else if (b <= 5) sprintf(p->nome, PORTAS[k] == 'B' ? "D%d" : "A%d", PORTAS[k] == 'B' ? 8 + b : b);
			else continue;   // PB6/PB7 são do cristal, PC6 é o reset
			avr_irq_register_notify(avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ(PORTAS[k]), b), ao_mudar_pino, p);
		}
		avr_irq_register_notify(avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ(PORTAS[k]), IOPORT_IRQ_DIRECTION_ALL),
		                        ao_mudar_ddr, (void *)(intptr_t)k);
		avr_irq_register_notify(avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ(PORTAS[k]), IOPORT_IRQ_REG_PORT),
		                        ao_mudar_port, (void *)(intptr_t)k);
	}
	for (unsigned k = 0; k < sizeof pwms / sizeof pwms[0]; k++) pwms[k].visto = pwms[k].emitido = -1;
	uint32_t fl = 0;   // Serial: tira o "imprime no terminal" do simavr e pega os bytes
	avr_ioctl(avr, AVR_IOCTL_UART_GET_FLAGS('0'), &fl);
	fl &= ~AVR_UART_FLAG_STDIO;
	avr_ioctl(avr, AVR_IOCTL_UART_SET_FLAGS('0'), &fl);
	avr_irq_register_notify(avr_io_getirq(avr, AVR_IOCTL_UART_GETIRQ('0'), UART_IRQ_OUTPUT), ao_sair_byte, NULL);
	avr_irq_t *rx = avr_io_getirq(avr, AVR_IOCTL_UART_GETIRQ('0'), UART_IRQ_INPUT);

	struct timespec t0, t1; clock_gettime(CLOCK_MONOTONIC, &t0);
	avr_cycle_count_t limite = (avr_cycle_count_t)(ms / 1000.0 * FREQ), proximo_byte = 0, proximo_pwm = 0;
	int estado = cpu_Running, prox = 0;
	unsigned long voltas = 0;
	const char *resultado = "tempo", *motivo = NULL;
	if (inicio < 0) { comecou = 1; c0 = 0; printf("{\"t_ms\":0,\"tipo\":\"inicio\",\"endereco\":-1}\n"); }
	for (;;) {
		if (limite_pc > 0 && (++voltas & 0xFFFFF) == 0) {   // de vez em quando: o relógio do PC passou do limite?
			clock_gettime(CLOCK_MONOTONIC, &t1);
			if ((t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9 > limite_pc) { resultado = "limite"; break; }
		}
		if (!comecou) {
			if (avr->pc == (avr_flashaddr_t)inicio) {
				comecou = 1; c0 = avr->cycle;
				printf("{\"t_ms\":0,\"tipo\":\"inicio\",\"endereco\":%ld,\"ciclos_antes\":%llu}\n", inicio, (unsigned long long)c0);
			} else if (avr->cycle > FREQ) { resultado = "travou"; motivo = "o programa não chegou no main() em 1 s"; break; }
		} else {
			avr_cycle_count_t agora = avr->cycle - c0;
			if (agora >= limite) break;
			if (avr->pc == 0 && agora > 0) { resultado = "travou"; motivo = "o chip reiniciou (o PC voltou pro endereço 0)"; break; }
			double agora_ms = agora * 1000.0 / FREQ;
			for (int i = prox; i < nest && est[i].t <= agora_ms; i++) {   // entradas vencidas
				estimulo_t *e = &est[i];
				if (e->feito) continue;
				if (e->tipo == 2) avr_raise_irq(avr_io_getirq(avr, AVR_IOCTL_ADC_GETIRQ, ADC_IRQ_ADC0 + e->n), e->valor);
				else if (e->tipo == 0)
					avr_raise_irq(avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ(PORTAS[e->pino->porta]), e->pino->bit), e->valor);
				else if (avr->cycle >= proximo_byte && e->pos < e->n) {   // 1 byte por vez, no ritmo de 115200 baud
					avr_raise_irq(rx, e->texto[e->pos++]);
					proximo_byte = avr->cycle + FREQ / 11520;
				}
				e->feito = e->tipo != 1 || e->pos >= e->n;
			}
			while (prox < nest && est[prox].feito) prox++;
			if (avr->cycle >= proximo_pwm) { olhar_pwm(); proximo_pwm = avr->cycle + 256; }
		}
		estado = avr_run(avr);
		if (estado == cpu_Done) { resultado = "acabou"; break; }   // rjmp .-2 (ou sleep) com interrupção desligada
		if (estado == cpu_Crashed) { resultado = "travou"; motivo = "o simavr parou o chip (instrução ou endereço inválido)"; break; }
	}
	clock_gettime(CLOCK_MONOTONIC, &t1);
	fim(resultado, motivo, (t1.tv_sec - t0.tv_sec) * 1000.0 + (t1.tv_nsec - t0.tv_nsec) / 1e6);
	return 0;
}
