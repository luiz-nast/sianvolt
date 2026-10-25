#!/usr/bin/env python3
"""html.py: a linha do tempo de uma rodada do laboratório numa página HTML sozinha, pra ir e voltar no tempo.

    python3 laboratorio/pagina/html.py eventos.jsonl -o saida.html [--titulo "pisca no ESP32"]

Uma onda por pino (nível, PWM, tensão), a serial até o instante escolhido, avisos e erros, e uma régua
de tempo (arrastar, setas, botão tocar). Sem internet: tudo vai dentro do arquivo."""
import argparse
import json
import sys
from pathlib import Path


def _escapar(txt):   # sem "import html": este arquivo se chama html.py e taparia o da biblioteca
    return str(txt).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def gerar(eventos, titulo="Laboratório", resultados=None):
    """eventos do contrato (lista de dicts) e, se tiver, o resultado das conferências ([{ok, texto}], o mesmo do
    terminal) -> texto da página"""
    eventos = [e for e in eventos if isinstance(e, dict)]
    if resultados is not None:
        falhas = [r["texto"] for r in resultados if not r["ok"]]
        eventos.append({"t_ms": None, "tipo": "conferencias", "ok": len(resultados) - len(falhas), "falhas": falhas,
                        "lista": [{"ok": bool(r["ok"]), "texto": r["texto"]} for r in resultados]})
    dados = json.dumps(eventos, ensure_ascii=False).replace("</", "<\\/")
    return MODELO.replace("__TITULO__", _escapar(titulo)).replace("__DADOS__", dados)


MODELO = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITULO__</title>
<style>
:root{--fundo:#f7f6f2;--painel:#fff;--texto:#1d1f23;--fraco:#6b6f76;--linha:#e2e0d9;--onda:#1f6feb;
--entrada:#b35900;--pwm:#7c3aed;--adc:#0f8a5f;--cursor:#d1242f;--aviso:#9a6700;--erro:#cf222e;--ok:#1a7f37;--grade:#efede6}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--fundo:#14161a;--painel:#1c1f24;--texto:#e6e6e3;
--fraco:#9aa0a6;--linha:#30343b;--onda:#58a6ff;--entrada:#f0a050;--pwm:#b392f0;--adc:#3fb950;--cursor:#ff6b6b;
--aviso:#d29922;--erro:#ff7b72;--ok:#3fb950;--grade:#23262c}}
:root[data-theme="dark"]{--fundo:#14161a;--painel:#1c1f24;--texto:#e6e6e3;--fraco:#9aa0a6;--linha:#30343b;--onda:#58a6ff;
--entrada:#f0a050;--pwm:#b392f0;--adc:#3fb950;--cursor:#ff6b6b;--aviso:#d29922;--erro:#ff7b72;--ok:#3fb950;--grade:#23262c}
*{box-sizing:border-box}
body{margin:0;background:var(--fundo);color:var(--texto);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:1.25rem;margin:0 0 2px}
.sub{color:var(--fraco);font-size:.9rem;margin-bottom:12px}
.mono{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
.caixa{background:var(--painel);border:1px solid var(--linha);border-radius:10px;padding:12px}
.regua{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin-bottom:12px}
.regua input[type=range]{flex:1 1 220px;accent-color:var(--cursor);min-width:0}
button,select{font:inherit;background:var(--painel);color:var(--texto);border:1px solid var(--linha);border-radius:8px;padding:5px 10px;cursor:pointer}
button:hover{border-color:var(--fraco)}
#agora{font-size:1.1rem;font-weight:600;min-width:6.5em;text-align:right}
.dica{color:var(--fraco);font-size:.8rem;flex-basis:100%}
#ondas{width:100%;display:block;touch-action:none;cursor:ew-resize;user-select:none}
#ondas text{fill:var(--texto);font-size:12px}
#ondas .fraco{fill:var(--fraco)}
.grade{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}
@media (max-width:720px){.grade{grid-template-columns:1fr}}
h2{font-size:.95rem;margin:0 0 8px}
#serial{height:220px;overflow:auto;margin:0;font-size:.85rem;white-space:pre-wrap;word-break:break-word}
#serial .rx{color:var(--entrada)}
#serial .ultima{background:var(--grade)}
.t{color:var(--fraco)}
ul{list-style:none;margin:0;padding:0;font-size:.88rem}
li{padding:3px 0;border-bottom:1px solid var(--grade)}
li.futuro{opacity:.4}
.aviso{color:var(--aviso)}.erro{color:var(--erro);white-space:pre-wrap}.ok{color:var(--ok)}
.vazio{color:var(--fraco);font-style:italic}
</style></head><body><main>
<h1>__TITULO__</h1><div class="sub" id="sub"></div>
<div class="caixa regua">
<button id="tocar" aria-label="tocar">&#9654; tocar</button>
<select id="vel" aria-label="velocidade"><option value="0.25">0,25x</option><option value="1" selected>1x</option><option value="4">4x</option></select>
<input type="range" id="tempo" min="0" max="1000" step="any" value="0" aria-label="instante">
<span id="agora" class="mono">0,000 s</span>
<span class="dica">Arraste a régua ou as ondas. Setas: um passo; Shift + setas: pula pro evento anterior/seguinte; espaço: tocar.</span>
</div>
<div class="caixa"><svg id="ondas" role="img" aria-label="ondas dos pinos"></svg></div>
<div class="grade">
<div class="caixa"><h2>Serial até o instante</h2><pre id="serial" class="mono"></pre></div>
<div class="caixa"><h2>Avisos, erros e conferências</h2><ul id="avisos"></ul></div>
</div></main>
<script type="application/json" id="dados">__DADOS__</script>
<script>
"use strict";
const EV = JSON.parse(document.getElementById("dados").textContent).filter(e => typeof e.t_ms === "number" || e.tipo === "conferencias");
EV.sort((a, b) => (a.t_ms ?? 1e18) - (b.t_ms ?? 1e18));
const fim = EV.find(e => e.tipo === "fim");
const FIM = EV.reduce((m, e) => e.t_ms != null && e.t_ms > m ? e.t_ms : m, Math.max(1, fim && fim.tempo_placa_ms || 0));
const fmt = ms => (ms / 1000).toFixed(3).replace(".", ",") + " s";
const MEIO = 0.5;   // meio milissegundo (t_ms): o que aparece como 0,000 s já vale em 0,000 s
const $ = id => document.getElementById(id);
// uma linha por pino: [t, tipo, valor, origem]
const pinos = new Map();
for (const e of EV) {
  if (!["pino", "pwm", "adc"].includes(e.tipo)) continue;
  if (!pinos.has(e.pino)) pinos.set(e.pino, {pino: e.pino, nome: e.nome, pts: [], vmax: 0});
  const p = pinos.get(e.pino);
  if (e.nome) p.nome = e.nome;
  const v = e.tipo === "pino" ? e.valor : e.tipo === "pwm" ? e.duty : e.volts;
  if (e.tipo === "adc") p.vmax = Math.max(p.vmax, v);
  p.pts.push([e.t_ms, e.tipo, v, e.origem || ""]);
}
const linhas = [...pinos.values()];
const tempos = [...new Set(EV.filter(e => e.t_ms != null && e.tipo !== "fim").map(e => e.t_ms))];
if (fim) $("sub").textContent = [fim.motor, fim.placa + (fim.alvo && fim.alvo !== fim.placa ? " (" + fim.alvo + ")" : ""),
  "estado: " + fim.estado, fmt(fim.tempo_placa_ms) + " de placa",
  fim.tempo_pc_s != null ? fim.tempo_pc_s.toFixed(2).replace(".", ",") + " s de PC" : "",
  fim.ram_mb ? String(fim.ram_mb).replace(".", ",") + " MB de RAM" : ""].filter(Boolean).join(" · ");
const ALT = 46, ESQ_LARG = () => (innerWidth < 600 ? 92 : 140), TOPO = 22;
let cursor = 0, larg = 600, esq = 140;
const svgNS = "http://www.w3.org/2000/svg";
function el(nome, at, pai) { const n = document.createElementNS(svgNS, nome); for (const k in at) n.setAttribute(k, at[k]); if (pai) pai.appendChild(n); return n; }
const x = t => esq + (t / FIM) * (larg - esq - 8);
function valorEm(p, t) {   // último ponto até t (busca binária)
  let a = 0, b = p.pts.length - 1, r = -1;
  while (a <= b) { const m = (a + b) >> 1; if (p.pts[m][0] <= t + MEIO) { r = m; a = m + 1; } else b = m - 1; }
  return r < 0 ? null : p.pts[r];
}
function rotulo(pt) {
  if (!pt) return "—";
  if (pt[1] === "pwm") return "PWM " + Math.round(pt[2] * 100) + "%";
  if (pt[1] === "adc") return pt[2].toFixed(2).replace(".", ",") + " V";
  return pt[2] ? "1 alto" : "0 baixo";
}
function medias(p, n) {   // nível médio (0 a 1) em cada uma das n colunas, pesado pelo tempo
  const r = new Array(n).fill(0), dt = FIM / n;
  p.pts.forEach((q, k) => {
    const a = q[0], b = k + 1 < p.pts.length ? p.pts[k + 1][0] : FIM;
    if (q[2]) for (let c = Math.floor(a / dt); c < n && c * dt < b; c++) r[c] += (Math.min(b, (c + 1) * dt) - Math.max(a, c * dt)) / dt * q[2];
  });
  return r;
}
let marcas = [];
function desenhar() {
  const svg = $("ondas"); svg.innerHTML = "";
  larg = svg.parentNode.clientWidth - 24; esq = ESQ_LARG();
  const alt = TOPO + Math.max(1, linhas.length) * ALT + 4;
  svg.setAttribute("viewBox", "0 0 " + larg + " " + alt); svg.setAttribute("height", alt);
  const passo = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 60000].find(s => FIM / s <= (larg - esq) / 70) || 60000;
  for (let t = 0; t <= FIM + 1e-9; t += passo) {
    el("line", {x1: x(t), x2: x(t), y1: TOPO - 4, y2: alt, stroke: "var(--grade)"}, svg);
    const ancora = x(t) > larg - 40 ? "end" : x(t) < esq + 20 ? "start" : "middle";
    el("text", {x: x(t), y: 12, "text-anchor": ancora, class: "fraco mono"}, svg).textContent = fmt(t).replace(",000 s", " s");
  }
  if (!linhas.length) el("text", {x: esq, y: TOPO + 24, class: "fraco"}, svg).textContent = "nenhum pino mexeu nesta rodada";
  marcas = linhas.map((p, i) => {
    const y0 = TOPO + i * ALT, base = y0 + ALT - 12, topo = y0 + 8, h = base - topo;
    const nome = el("text", {x: 0, y: y0 + 17, "font-weight": 600}, svg);
    nome.textContent = p.nome || p.pino;
    if (p.nome && esq > 100) el("tspan", {class: "fraco mono", "font-weight": 400}, nome).textContent = " " + p.pino;
    el("title", {}, nome).textContent = (p.nome ? p.nome + " = " : "") + p.pino;
    el("line", {x1: esq, x2: larg - 8, y1: base, y2: base, stroke: "var(--linha)"}, svg);
    let d = "", dpwm = "", prev = null, med = null;
    const ent = p.pts.length && p.pts.every(q => q[3] === "roteiro" || q[1] === "adc");
    const yv = q => q[1] === "adc" ? base - h * q[2] / (p.vmax || 1) : base - h * q[2];
    const ncol = Math.floor((larg - esq - 8) / 2);
    if (p.pts.length > ncol / 2 && !p.vmax) {   // troca rápido demais pra ver (PWM pelo pino): a média de cada coluna
      med = medias(p, ncol);
      dpwm = "M" + esq + " " + base + med.map((m, k) => "L" + x(k * FIM / ncol) + " " + (base - h * m) + "H" + x((k + 1) * FIM / ncol)).join("") + "V" + base + "Z";
    } else for (let k = 0; k < p.pts.length; k++) {
      const q = p.pts[k], t1 = k + 1 < p.pts.length ? p.pts[k + 1][0] : FIM;
      const y = yv(q), xa = x(q[0]), xb = x(t1);
      d += (prev === null ? "M" + xa + " " + y : "L" + xa + " " + prev + "L" + xa + " " + y) + "L" + xb + " " + y;
      if (q[1] === "pwm") dpwm += "M" + xa + " " + base + "H" + xb + "V" + y + "H" + xa + "Z";
      prev = y;
    }
    if (dpwm) el("path", {d: dpwm, fill: "var(--pwm)", opacity: med ? .6 : .25}, svg);
    const cor = p.pts.some(q => q[1] === "pwm") ? "var(--pwm)" : p.vmax ? "var(--adc)" : ent ? "var(--entrada)" : "var(--onda)";
    if (d) el("path", {d, fill: "none", stroke: cor, "stroke-width": 2, "stroke-linejoin": "round"}, svg);
    const estado = el("text", {x: 0, y: y0 + 34, class: "mono"}, svg);
    return {p, estado, ponto: el("circle", {r: 4, fill: "var(--cursor)"}, svg), yv, med, base, h};
  });
  svg.appendChild(el("line", {id: "cur", y1: TOPO - 4, y2: alt, stroke: "var(--cursor)", "stroke-width": 1.5}));
  mover(cursor);
}
function mover(t) {
  cursor = Math.max(0, Math.min(FIM, t));
  $("tempo").value = cursor / FIM * 1000; $("agora").textContent = fmt(cursor);
  const c = $("cur"); if (c) { c.setAttribute("x1", x(cursor)); c.setAttribute("x2", x(cursor)); }
  for (const m of marcas) {
    const pt = valorEm(m.p, cursor), md = m.med && m.med[Math.min(m.med.length - 1, Math.floor(cursor / FIM * m.med.length))];
    m.estado.textContent = m.med ? "≈ " + Math.round(md * 100) + "% ligado" : rotulo(pt);
    m.ponto.setAttribute("cx", x(cursor)); m.ponto.setAttribute("cy", m.med ? m.base - m.h * md : pt ? m.yv(pt) : -10);
  }
  const ser = EV.filter(e => e.tipo === "serial" && e.t_ms <= cursor + MEIO);
  const pre = $("serial");
  pre.innerHTML = ser.length ? "" : '<span class="vazio">nada na serial até aqui</span>';
  ser.forEach((e, i) => {
    const s = document.createElement("div");
    s.className = (e.dir === "rx" ? "rx" : "") + (i === ser.length - 1 ? " ultima" : "");
    s.innerHTML = '<span class="t"></span> '; s.firstChild.textContent = fmt(e.t_ms) + (e.dir === "rx" ? " →" : "  ");
    s.appendChild(document.createTextNode(e.texto)); pre.appendChild(s);
  });
  pre.scrollTop = pre.scrollHeight;
  const ul = $("avisos"); ul.innerHTML = "";
  const lista = EV.filter(e => ["aviso", "erro", "conferencias", "fim"].includes(e.tipo));
  if (!lista.length) ul.innerHTML = '<li class="vazio">nenhum aviso</li>';
  for (const e of lista) {
    const li = document.createElement("li");
    if (e.tipo === "conferencias") {
      li.className = e.falhas && e.falhas.length ? "erro" : "ok";
      const n = e.ok + (e.falhas ? e.falhas.length : 0);
      if (e.lista) {   // uma linha por conferência, como no terminal
        li.textContent = "Conferências: " + e.ok + " de " + n + " ok";
        ul.appendChild(li);
        for (const r of e.lista) {
          const c = document.createElement("li");
          c.className = r.ok ? "ok" : "erro";
          c.textContent = (r.ok ? "ok     " : "FALHA  ") + r.texto;
          ul.appendChild(c);
        }
        continue;
      }
      li.textContent = "Conferências: " + e.ok + " ok" + (e.falhas && e.falhas.length ? ", " + e.falhas.length + " falha(s): " +
        e.falhas.map(f => typeof f === "string" ? f : JSON.stringify(f)).join("; ") : "");
    } else {
      li.className = (e.tipo === "fim" ? (["acabou", "tempo"].includes(e.estado) ? "ok" : "erro") : e.tipo) + (e.t_ms > cursor + MEIO ? " futuro" : "");
      li.textContent = fmt(e.t_ms) + "  " + (e.tipo === "fim" ? "fim: " + e.estado : e.texto);
    }
    ul.appendChild(li);
  }
}
// régua, arrastar nas ondas, teclado e tocar
$("tempo").addEventListener("input", e => { parar(); mover(e.target.value / 1000 * FIM); });
const svg = $("ondas");
function doPonteiro(e) { const r = svg.getBoundingClientRect(); mover(((e.clientX - r.left) * larg / r.width - esq) / (larg - esq - 8) * FIM); }
svg.addEventListener("pointerdown", e => { parar(); svg.setPointerCapture(e.pointerId); doPonteiro(e); });
svg.addEventListener("pointermove", e => { if (svg.hasPointerCapture(e.pointerId)) doPonteiro(e); });
document.addEventListener("keydown", e => {
  if (e.target.tagName === "SELECT" || e.target.tagName === "BUTTON" && e.key === " ") return;
  const passo = Math.max(1, FIM / 200);
  if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
    e.preventDefault(); parar();
    const dir = e.key === "ArrowRight" ? 1 : -1;
    if (e.shiftKey) { const alvo = dir > 0 ? tempos.find(t => t > cursor + 1e-6) : [...tempos].reverse().find(t => t < cursor - 1e-6); mover(alvo ?? (dir > 0 ? FIM : 0)); }
    else mover(cursor + dir * passo);
  } else if (e.key === " ") { e.preventDefault(); alternar(); }
  else if (e.key === "Home") { e.preventDefault(); mover(0); } else if (e.key === "End") { e.preventDefault(); mover(FIM); }
});
let tocando = null;
function parar() { if (tocando) cancelAnimationFrame(tocando); tocando = null; $("tocar").innerHTML = "&#9654; tocar"; }
function alternar() {
  if (tocando) return parar();
  if (cursor >= FIM) mover(0);
  let antes = performance.now();
  $("tocar").innerHTML = "&#10074;&#10074; pausar";
  const passo = agora => {
    mover(cursor + (agora - antes) * Number($("vel").value)); antes = agora;
    if (cursor >= FIM) return parar();
    tocando = requestAnimationFrame(passo);
  };
  tocando = requestAnimationFrame(passo);
}
$("tocar").addEventListener("click", alternar);
addEventListener("resize", desenhar);
desenhar();
</script></body></html>
"""


def ler_jsonl(caminho):
    eventos = []
    for n, linha in enumerate(Path(caminho).read_text(encoding="utf-8").splitlines(), 1):
        if linha.strip():
            try:
                eventos.append(json.loads(linha))
            except json.JSONDecodeError as e:
                sys.exit("%s, linha %d: não é JSON (%s)" % (caminho, n, e.msg))
    return eventos


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("eventos", help="arquivo .jsonl (um evento do contrato por linha, como o lab.py rodar --json)")
    ap.add_argument("-o", "--saida", help="página a gravar (padrão: o mesmo nome, .html)")
    ap.add_argument("--titulo", help="título da página (padrão: o nome do arquivo)")
    a = ap.parse_args()
    saida = Path(a.saida or Path(a.eventos).with_suffix(".html"))
    saida.write_text(gerar(ler_jsonl(a.eventos), a.titulo or Path(a.eventos).stem), encoding="utf-8")
    print("página: %s" % saida)


if __name__ == "__main__":
    main()
