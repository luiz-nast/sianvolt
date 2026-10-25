#!/usr/bin/env node
// emular.mjs: o Nano no avr8js e o Pico no rp2040js (os dois do Wokwi, licença MIT), sem placa. É o miolo dos
// motores avr8js e rp2040js (motores/avr8js.py e motores/rp2040js.py), que convertem a saída pro contrato.
// Um evento JSON por linha no stdout, no formato do simavr_nano: inicio, pino (só saída, quando muda), modo,
// pwm (lido dos registradores, no máximo 1 a cada 11 ms por pino (< 100/s)), serial (uma linha, UTF-8), aviso, erro, fim.
// t_ms = tempo de placa desde o começo do programa: Nano = o PC chega no --inicio (o main(), que chama o
// setup()); Pico Arduino = o PC chega no setup(); Pico MicroPython = a marca que o rodador escreve no
// SCRATCH3 do watchdog logo antes da primeira linha do main.py. Tudo em tempo virtual.
//
//   node emular.mjs nano firmware.hex --modulos <node_modules> [--ms N] [--inicio end] [entradas]
//   node emular.mjs pico firmware.uf2 --modulos <node_modules> [--bootrom b.mjs] [--ms N] [--inicio end]
//                         [--py carga.py rodar.py]
//   entradas: --pino P=v@t  --adc P=volts@t  --serial HEX@t   (t em ms desde o começo do programa)
//   --limite-pc S: para sozinho depois de S segundos de PC, com fim estado 'limite' (o emulador é que é lento)
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const [placa, arquivo, ...resto] = process.argv.slice(2);
const op = { ms: 3000, inicio: -1, limitePc: 0, modulos: null, bootrom: null, pinos: [], adc: [], serial: [], py: null };
for (let i = 0; i < resto.length; i++) {
  const a = resto[i], v = resto[i + 1];
  const m = /^([A-Za-z]+\d+)=([\d.]+)@([\d.]+)$/.exec(v ?? '');
  if (a === '--ms') op.ms = Number(v);
  else if (a === '--limite-pc') op.limitePc = Number(v);
  else if (a === '--inicio') op.inicio = Number(v);
  else if (a === '--modulos') op.modulos = v;
  else if (a === '--bootrom') op.bootrom = v;
  else if (a === '--py') { op.py = [readFileSync(v, 'utf8'), readFileSync(resto[i + 2], 'utf8')]; i++; }
  else if ((a === '--pino' || a === '--adc') && m) op[a === '--pino' ? 'pinos' : 'adc'].push({ pino: m[1].toUpperCase(), v: Number(m[2]), t: Number(m[3]) });
  else if (a === '--serial' && /^([0-9a-f]*)@([\d.]+)$/.test(v)) {
    const [hex, t] = v.split('@');
    op.serial.push({ bytes: [...Buffer.from(hex, 'hex')], t: Number(t) });
  } else { console.error('opção desconhecida ou torta:', a, v ?? ''); process.exit(2); }
  i++;
}
if (!['nano', 'pico'].includes(placa) || !arquivo || !op.modulos) {
  console.error('uso: node emular.mjs nano|pico <firmware> --modulos <node_modules> [--ms N] ...');
  process.exit(2);
}

// ---------------- saída: um evento por linha, t_ms desde o começo do programa ----------------
let agoraMs = () => 0;          // tempo de placa desde o começo (0 antes dele)
let comecou = false;
let saida = [];
const t0real = performance.now();
const passouDoLimite = () => op.limitePc > 0 && performance.now() - t0real > op.limitePc * 1000;
const despejar = () => { if (saida.length) { process.stdout.write(saida.join('')); saida = []; } };
const evento = (o, forcar = false) => {
  if (!comecou && !forcar) return;
  saida.push(JSON.stringify({ t_ms: Number(Math.max(0, agoraMs()).toFixed(3)), ...o }) + '\n');
  if (saida.length > 500) despejar();
};
function leitorDeLinhas(porta) {   // bytes -> linhas UTF-8 (o que não for UTF-8 vira U+FFFD)
  let bytes = [];
  const soltar = () => { evento({ tipo: 'serial', porta, texto: Buffer.from(bytes).toString('utf8') }); bytes = []; };
  const f = (b) => {
    if (b === 13) return;
    if (b === 10) soltar(); else { bytes.push(b); if (bytes.length >= 1024) soltar(); }
  };
  f.soltar = () => { if (bytes.length) soltar(); };
  return f;
}
// PWM: o duty tem que se repetir em 2 olhadas (filtra o meio de uma troca de registradores) e sai no máximo
// 1 evento a cada 11 ms por pino. d < 0 = o pino não está em PWM.
function novoPwm(nome, aoSair) {
  const w = { visto: -1, vistoT: 0, emitido: -1, emitidoT: -1e9, ativo: false };
  w.olhar = (d, f) => {
    const agora = agoraMs();
    if (d !== w.visto) { w.visto = d; w.vistoT = agora; return; }
    if (d === w.emitido || (w.emitido >= 0 && agora - w.emitidoT < 11)) return;
    w.ativo = d >= 0;
    if (d < 0) aoSair();
    else evento({ tipo: 'pwm', pino: nome, duty: Number(d.toFixed(4)), freq_hz: Number(f.toFixed(1)), t_ms: Number(w.vistoT.toFixed(3)) });
    w.emitido = d; w.emitidoT = agora;
  };
  return w;
}
function fim(estado, motivo, extra = {}) {
  if (motivo) evento({ tipo: 'aviso', texto: motivo, codigo: placa === 'nano' ? 'avr8js' : 'rp2040js' }, true);
  const real = performance.now() - t0real;
  evento({ tipo: 'fim', estado, tempo_real_ms: Math.round(real), velocidade: Number((agoraMs() / real).toFixed(3)), ...extra }, true);
  despejar();
}

if (placa === 'nano') rodarNano(); else await rodarPico();

// ============================ NANO (avr8js) ============================
function lerIntelHex(texto, tamanho) {
  const mem = new Uint8Array(tamanho);
  let base = 0;
  for (const linha of texto.split(/\r?\n/)) {
    if (!linha.startsWith(':')) continue;
    const n = parseInt(linha.substr(1, 2), 16), end = parseInt(linha.substr(3, 4), 16), tipo = parseInt(linha.substr(7, 2), 16);
    if (tipo === 0) for (let i = 0; i < n; i++) mem[base + end + i] = parseInt(linha.substr(9 + 2 * i, 2), 16);
    else if (tipo === 2) base = parseInt(linha.substr(9, 4), 16) << 4;
    else if (tipo === 4) base = parseInt(linha.substr(9, 4), 16) << 16;
  }
  return mem;
}

function rodarNano() {
  const avr = createRequire(join(op.modulos, 'x.js'))('avr8js');
  const FREQ = 16e6;
  const flash = lerIntelHex(readFileSync(arquivo, 'utf8'), 0x8000);
  const cpu = new avr.CPU(new Uint16Array(flash.buffer), 2048);   // ATmega328P: 32 KB de flash, 2 KB de RAM
  let c0 = 0;
  agoraMs = () => (comecou ? ((cpu.cycles - c0) / FREQ) * 1000 : 0);
  for (const t of [avr.timer0Config, avr.timer1Config, avr.timer2Config]) new avr.AVRTimer(cpu, t);
  const usart = new avr.AVRUSART(cpu, avr.usart0Config, FREQ);
  const adc = new avr.AVRADC(cpu, avr.adcConfig);   // analogRead(): volts, referência AVcc = 5 V
  const serial = leitorDeLinhas('uart0');
  usart.onByteTransmit = serial;
  const cfg = { B: avr.portBConfig, C: avr.portCConfig, D: avr.portDConfig };
  const portas = {};
  for (const p of 'BCD') portas[p] = new avr.AVRIOPort(cpu, cfg[p]);
  const nome = (p, b) => (p === 'D' ? `D${b}` : p === 'B' ? `D${8 + b}` : `A${b}`);
  const existe = (p, b) => p === 'D' || b <= 5;   // PB6/PB7 = cristal, PC6 = reset
  const forcado = { B: 0, C: 0, D: 0 };       // pinos que o roteiro está segurando
  const estado = {};                          // 'D13' -> {nivel, modo}
  for (const p of 'BCD') for (let b = 0; b < 8; b++) if (existe(p, b)) estado[nome(p, b)] = { nivel: -1, modo: 'entrada' };
  // PWM pelos registradores dos timers, como no simavr_nano.c (OC0A=D6 OC0B=D5 OC1A=D9 OC1B=D10 OC2A=D11 OC2B=D3)
  const CANAIS = [['D6', 0, 6, 0x47], ['D5', 0, 4, 0x48], ['D9', 1, 6, 0x88], ['D10', 1, 4, 0x8a], ['D11', 2, 6, 0xb3], ['D3', 2, 4, 0xb4]];
  const TCCRA = [0x44, 0x80, 0xb0], TCCRB = [0x45, 0x81, 0xb1];
  const DIV01 = [0, 1, 8, 64, 256, 1024, 0, 0], DIV2 = [0, 1, 8, 32, 64, 128, 256, 1024];
  const TOPS1 = [0, 0xff, 0x1ff, 0x3ff, 0, 0xff, 0x1ff, 0x3ff, -1, -2, -1, -2, 0, 0, -1, -2];
  const u16 = (a) => cpu.data[a] | (cpu.data[a + 1] << 8);
  const de = (n) => (n[0] === 'A' ? ['C', +n.slice(1)] : +n.slice(1) < 8 ? ['D', +n.slice(1)] : ['B', +n.slice(1) - 8]);
  function duty([pino, timer, sh, ocrA]) {
    const a = cpu.data[TCCRA[timer]], b = cpu.data[TCCRB[timer]], com = (a >> sh) & 3;
    const div = (timer === 2 ? DIV2 : DIV01)[b & 7], [p, bit] = de(pino);
    if (com < 2 || !div || !(cpu.data[cfg[p].DDR] & (1 << bit))) return [-1, 0];
    let top, rapido;
    if (timer !== 1) {
      const wgm = (a & 3) | (((b >> 3) & 1) << 2);
      if (![1, 3, 5, 7].includes(wgm)) return [-1, 0];
      top = wgm >= 5 ? cpu.data[timer === 0 ? 0x47 : 0xb3] : 0xff;
      rapido = wgm === 3 || wgm === 7;
    } else {
      const wgm = (a & 3) | (((b >> 3) & 3) << 2);
      top = TOPS1[wgm];
      if (top === 0) return [-1, 0];
      if (top === -1) top = u16(0x86);   // ICR1
      if (top === -2) top = u16(0x88);   // OCR1A
      rapido = (wgm >= 5 && wgm <= 7) || wgm >= 14;
    }
    if (top <= 0) return [-1, 0];
    const ocr = timer === 1 ? u16(ocrA) : cpu.data[ocrA];
    let d = Math.min(1, rapido ? (ocr + 1) / (top + 1) : ocr / top);
    if (com === 3) d = 1 - d;
    return [d, rapido ? FREQ / div / (top + 1) : FREQ / div / (2 * top)];
  }
  const pwms = {};
  for (const c of CANAIS) pwms[c[0]] = novoPwm(c[0], () => olhar(de(c[0])[0]));

  function olhar(p) {   // um registrador da porta mudou: modo, pull-up e nível das saídas
    const c = cfg[p], ddr = cpu.data[c.DDR], out = cpu.data[c.PORT];
    for (let b = 0; b < 8; b++) {
      if (!existe(p, b)) continue;
      const m = 1 << b, e = estado[nome(p, b)];
      // o avr8js não liga o pull-up sozinho: entrada com pull-up e sem o roteiro segurando lê 1
      if (!(ddr & m) && !(forcado[p] & m) && !!(cpu.data[c.PIN] & m) !== !!(out & m)) portas[p].setPin(b, !!(out & m));
      const modo = ddr & m ? 'saida' : out & m ? 'pullup' : 'entrada';
      if (modo !== e.modo) { e.modo = modo; evento({ tipo: 'modo', pino: nome(p, b), modo }); }
      if (!(ddr & m)) { e.nivel = -1; continue; }
      const nivel = out & m ? 1 : 0;
      if (nivel !== e.nivel && !(pwms[nome(p, b)] && pwms[nome(p, b)].ativo)) {
        e.nivel = nivel;
        evento({ tipo: 'pino', pino: nome(p, b), valor: nivel });
      }
    }
  }
  for (const p of 'BCD') portas[p].addListener(() => olhar(p));
  const olharPwm = () => { for (const c of CANAIS) { const [d, f] = duty(c); pwms[c[0]].olhar(d, f); } cpu.addClockEvent(olharPwm, 256); };

  const filaRx = [];
  const umByte = Math.round(FREQ / 11520);   // ~1 byte a 115200 baud
  const bombearRx = () => { if (filaRx.length && usart.writeByte(filaRx[0])) filaRx.shift(); cpu.addClockEvent(bombearRx, umByte); };
  const ciclos = (t) => Math.max(1, Math.round((t / 1000) * FREQ));
  function comecar() {   // o programa começou: liga as entradas do roteiro, relativas a agora
    comecou = true; c0 = cpu.cycles;
    evento({ tipo: 'inicio', endereco: op.inicio, ciclos_antes: c0 });
    for (const e of op.adc) {
      const aplicar = () => { adc.channelValues[Number(e.pino.slice(1))] = e.v; };
      if (e.t === 0) aplicar(); else cpu.addClockEvent(aplicar, ciclos(e.t));
    }
    for (const e of op.pinos) {
      const [p, b] = de(e.pino);
      cpu.addClockEvent(() => { forcado[p] |= 1 << b; portas[p].setPin(b, !!e.v); olhar(p); }, ciclos(e.t));
    }
    for (const s of op.serial) cpu.addClockEvent(() => filaRx.push(...s.bytes), ciclos(s.t));
    cpu.addClockEvent(bombearRx, umByte);
    cpu.addClockEvent(olharPwm, 256);
  }
  const alvo = op.inicio >= 0 ? op.inicio / 2 : -1;   // o avr8js conta o PC em palavras de 16 bits
  if (alvo < 0) comecar();
  const limite = (op.ms / 1000) * FREQ;
  let est = 'tempo', motivo = null, voltas = 0;
  for (;;) {
    if ((++voltas & 0xffff) === 0 && passouDoLimite()) { est = 'limite'; break; }
    if (!comecou) {
      if (cpu.pc === alvo) comecar();
      else if (cpu.cycles > FREQ) { est = 'travou'; motivo = 'o programa não chegou no main() em 1 s'; break; }
    } else {
      if (cpu.cycles - c0 >= limite) break;
      if (cpu.pc === 0 && cpu.cycles > c0) { est = 'travou'; motivo = 'o chip reiniciou (o PC voltou pro endereço 0)'; break; }
      // rjmp .-2 com a interrupção desligada: o programa acabou (o exit() do avr-libc)
      if (cpu.progMem[cpu.pc] === 0xcfff && !(cpu.data[0x5f] & 0x80)) { est = 'acabou'; break; }
    }
    avr.avrInstruction(cpu);
    cpu.tick();
    if (saida.length > 200) despejar();
  }
  serial.soltar();
  fim(est, motivo, { ciclos: cpu.cycles });
}

// ============================ PICO (rp2040js) ============================
function lerUF2(buf, flash) {
  let blocos = 0;
  for (let o = 0; o + 512 <= buf.length; o += 512) {
    const v = new DataView(buf.buffer, buf.byteOffset + o, 512);
    if (v.getUint32(0, true) !== 0x0a324655 || v.getUint32(4, true) !== 0x9e5d5157) continue;
    const endereco = v.getUint32(12, true), tam = v.getUint32(16, true);
    if (endereco >= 0x10000000 && endereco < 0x11000000) { flash.set(buf.subarray(o + 32, o + 32 + tam), endereco - 0x10000000); blocos++; }
  }
  return blocos;
}

async function rodarPico() {
  const rp = await import(pathToFileURL(join(op.modulos, 'rp2040js', 'dist', 'esm', 'index.js')));
  const { bootromB1 } = await import(op.bootrom ? pathToFileURL(op.bootrom) : new URL('./bootrom_b1.mjs', import.meta.url));
  const sim = new rp.Simulator();
  const mcu = sim.rp2040, clock = sim.clock;
  let n0 = 0;
  agoraMs = () => (comecou ? (clock.nanos - n0) / 1e6 : 0);
  mcu.logger = { debug() {}, info() {}, warn() {}, error: (c, m) => process.stderr.write(`[erro ${c}] ${m}\n`) };
  mcu.loadBootrom(bootromB1);
  lerUF2(readFileSync(arquivo), mcu.flash);
  const u0 = leitorDeLinhas('uart0'), u1 = leitorDeLinhas('uart1'), usb = leitorDeLinhas('usb');
  mcu.uart[0].onByte = u0;
  mcu.uart[1].onByte = u1;
  const cdc = new rp.USBCDC(mcu.usbCtrl);
  const filaUsb = [];
  let est = 'tempo', motivo = null, acabou = false;

  // GPIO: modo, nível das saídas, pull-up/pull-down e eco da saída (o rp2040js não faz esses dois sozinho)
  const S = rp.GPIOPinState, FUNC_PWM = 4;
  const forcado = new Set(), estado = [];
  const MODO = { [S.High]: 'saida', [S.Low]: 'saida', [S.InputPullUp]: 'pullup', [S.InputPullDown]: 'pulldown' };
  const pwms = [];
  mcu.gpio.forEach((g, i) => {
    // depois do reset todo GPIO do RP2040 é entrada com pull-down (PADS_BANK0: PDE = 1): começar assim tira o
    // "vira entrada com pull-down" que aparecia antes de todo pinMode(OUTPUT) e em pino que o programa nem usa
    estado[i] = { nivel: -1, modo: 'pulldown' };
    const e = estado[i];
    const atualizar = (st) => {
      if (!forcado.has(i)) {   // na placa, ler um pino de saída devolve o nível que ele está puxando
        if (st === S.High || st === S.InputPullUp) g.setInputValue(true);
        else if (st === S.Low || st === S.InputPullDown) g.setInputValue(false);
      }
      const modo = MODO[st] ?? 'entrada';
      if (modo !== e.modo) { e.modo = modo; evento({ tipo: 'modo', pino: `GP${i}`, modo }); }
      if (modo !== 'saida') { e.nivel = -1; return; }
      const nivel = st === S.High ? 1 : 0;
      if (nivel !== e.nivel && g.functionSelect !== FUNC_PWM) { e.nivel = nivel; evento({ tipo: 'pino', pino: `GP${i}`, valor: nivel }); }
    };
    pwms[i] = novoPwm(`GP${i}`, () => { e.nivel = -1; atualizar(g.value); });
    g.addListener((st) => atualizar(st));
  });
  // PWM pelos registradores do slice (GPIO n = slice (n/2)%8, canal A se par): duty = CC / (TOP + 1)
  const olharPwm = () => {
    mcu.gpio.forEach((g, i) => {
      if (g.functionSelect !== FUNC_PWM && !pwms[i].ativo && pwms[i].visto < 0) return;
      const ch = mcu.pwm.channels[(i >> 1) & 7], b = i & 1;
      let d = -1, f = 0;
      if (g.functionSelect === FUNC_PWM && ch.csr & 1) {
        const top = ch.top + 1, cc = b ? ch.cc >>> 16 : ch.cc & 0xffff;
        const div = ((ch.div >> 4) & 0xff || 256) + (ch.div & 0xf) / 16;
        d = Math.min(cc, top) / top;
        if (ch.csr & (b ? 8 : 4)) d = 1 - d;
        f = mcu.pwm.clockFreq / div / top / (ch.csr & 2 ? 2 : 1);
      }
      pwms[i].olhar(d, f);
    });
    alarmePwm.schedule(1e6);
  };
  const alarmePwm = clock.createAlarm(olharPwm);

  const agendar = (t, fn) => clock.createAlarm(fn).schedule(Math.max(1, t * 1e6));
  function comecar() {   // o programa começou: as entradas do roteiro contam daqui
    comecou = true; n0 = clock.nanos;
    evento({ tipo: 'inicio', endereco: op.inicio, ms_antes: Number((n0 / 1e6).toFixed(3)) });
    for (const e of op.adc) {
      const aplicar = () => { mcu.adc.channelValues[Number(e.pino.slice(2)) - 26] = Math.max(0, Math.min(4095, Math.round((e.v / 3.3) * 4095))); };
      if (e.t === 0) aplicar(); else agendar(e.t, aplicar);
    }
    for (const e of op.pinos) {
      const i = Number(e.pino.slice(2));
      agendar(e.t, () => { forcado.add(i); mcu.gpio[i].setInputValue(!!e.v); });
    }
    for (const s of op.serial) agendar(s.t, () => filaUsb.push(...s.bytes));
    alarmePwm.schedule(1e6);
  }

  // MicroPython: REPL bruto (Ctrl-A, código, Ctrl-D), igual ao mpremote: 1) a carga monta o sistema de
  // arquivos na RAM com os arquivos do programa; 2) o rodador compila o main.py, marca o começo e roda.
  // Resposta do REPL bruto: "OK" saída \x04 erro \x04 ">"
  let fase = op.py ? 'prompt' : 'arduino', texto = '', resposta = null;
  const marca = mcu.findPeripheral(0x40058000), escrever = marca.writeUint32.bind(marca);
  marca.writeUint32 = (off, v) => {   // SCRATCH3 = 0x5AB0_0001 começo, 0x5AB0_0002 fim
    if (off === 0x18 && v >>> 16 === 0x5ab0) {
      if ((v & 0xffff) === 1 && !comecou) comecar();
      if ((v & 0xffff) === 2) evento({ tipo: 'marca_fim' });
    }
    escrever(off, v);
  };
  const mandar = (s) => filaUsb.push(...Buffer.from(s, 'utf8'));
  function aoResponder(r) {   // r = {saida, erro} de uma execução no REPL bruto
    if (fase === 'carga') {
      if (r.erro.trim()) { est = 'travou'; motivo = 'o motor não conseguiu pôr o programa na RAM: ' + r.erro.trim().slice(-300); acabou = true; return; }
      fase = 'rodando'; mandar(op.py[1]); filaUsb.push(4);
    } else if (fase === 'rodando') {
      if (!comecou) comecar();   // erro antes da marca (SyntaxError no main.py)
      if (r.erro.trim()) { evento({ tipo: 'erro', texto: r.erro.trim() }); est = 'erro'; } else est = 'acabou';
      fase = 'fim'; acabou = true;
    }
  }
  function aoReceberUsb(b) {
    texto = (texto + String.fromCharCode(b)).slice(-200);
    if (op.py && comecou && !acabou && /MicroPython v\d|soft reboot/.test(texto)) {
      est = 'travou'; motivo = 'o chip reiniciou (o MicroPython deu boot de novo)'; acabou = true;
    }
    if (fase === 'arduino') return usb(b);
    if (fase === 'fim') return;   // depois do fim só vem o '>' do REPL bruto
    if (resposta) {   // dentro de uma execução: saída até o 1º \x04, erro até o 2º
      if (resposta.n === 0 && resposta.ok < 2 && b === 'OK'.charCodeAt(resposta.ok)) { resposta.ok++; return; }
      if (b === 4) { resposta.n++; if (resposta.n === 2) { const r = resposta; resposta = null; usb.soltar(); aoResponder({ erro: Buffer.from(r.erro).toString('utf8') }); } return; }
      if (resposta.n === 0) { if (fase === 'rodando') usb(b); } else resposta.erro.push(b);
      return;
    }
    if (fase === 'prompt' && texto.endsWith('>>> ')) { fase = 'raw'; texto = ''; filaUsb.push(3, 3, 1); }
    else if (fase === 'raw' && texto.endsWith('raw REPL; CTRL-B to exit\r\n>')) {
      fase = 'carga'; texto = ''; mandar(op.py[0]); filaUsb.push(4);
    }
  }
  const enviarTexto = filaUsb.push.bind(filaUsb);
  cdc.onDeviceConnected = () => {
    if (op.py) return enviarTexto(13, 10);   // um Enter faz o >>> aparecer
    // Arduino: a Serial do Pico é a USB, que só entrega depois que o PC abre a porta (DTR); o que o programa
    // escreveu antes some sem erro, na placa também. Avisa quando a porta abre depois do começo do programa
    if (comecou && agoraMs() > 0) evento({ tipo: 'aviso', codigo: 'usb', texto: 'a porta USB abriu agora (' +
      (agoraMs() / 1000).toFixed(3).replace('.', ',') + ' s): o que o programa escreveu na Serial antes disso se ' +
      'perdeu, como na placa (o USB só entrega com a porta aberta no PC). Pra não perder, comece o setup() com ' +
      'while (!Serial) delay(10);' });
  };
  cdc.onSerialData = (buf) => {
    for (const b of buf) {
      if (fase !== 'arduino' && fase !== 'fim' && !resposta && (fase === 'carga' || fase === 'rodando') && b === 0x4f) resposta = { n: 0, ok: 0, erro: [] };
      aoReceberUsb(b);
    }
  };

  // Arduino: o começo é o PC chegando no setup()
  const alvo = op.inicio >= 0 ? op.inicio & ~1 : -1;
  if (!op.py && alvo < 0) comecar();
  mcu.core.PC = 0x10000000;
  const cicloNs = 1e9 / 125e6, limiteNs = op.ms * 1e6, antesNs = 10e9;
  while (!acabou) {
    for (let i = 0; i < 10000; i++) {
      if (mcu.core.waiting) {
        const n = clock.nanosToNextAlarm;
        clock.tick(n > 0 ? n : 1000);
      } else {
        if (!comecou && alvo >= 0 && mcu.core.PC === alvo) comecar();
        clock.tick(mcu.core.executeInstruction() * cicloNs);
      }
    }
    while (filaUsb.length && cdc.txFIFO.itemCount < cdc.txFIFO.size) cdc.sendSerialByte(filaUsb.shift());
    despejar();
    if (comecou && clock.nanos - n0 >= limiteNs) break;
    if (passouDoLimite()) { est = 'limite'; break; }
    if (!comecou && clock.nanos > antesNs) { est = 'travou'; motivo = 'o programa não começou em 10 s de placa (fase ' + fase + ')'; break; }
  }
  u0.soltar(); u1.soltar(); usb.soltar();
  fim(est, motivo, { fase });
}
