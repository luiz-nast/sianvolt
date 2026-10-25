"""texto.py: a linha do tempo e as conferências em texto de gente (pro terminal e pro Claude)."""

MAX_LINHAS = 120   # sem -v, corta o meio de linhas do tempo compridas


def num(v, casas=2):
    """0.25 -> '0,25'; 1.0 -> '1'"""
    s = ("%.*f" % (casas, v)).rstrip("0").rstrip(".")
    return s.replace(".", ",")


def fmt_t(ms):
    """tempo de placa em ms -> '1,250 s'"""
    return ("%.3f s" % (ms / 1000)).replace(".", ",")


def _pino(ev):
    return "%s (%s)" % (ev["pino"], ev["nome"]) if ev.get("nome") else ev["pino"]


MODOS = {"saida": "vira saída", "entrada": "vira entrada", "pullup": "vira entrada com pull-up",
         "pulldown": "vira entrada com pull-down", "adc": "vira entrada analógica", "pwm": "vira PWM"}


def linha(ev):
    """um evento -> texto (sem o tempo); None pro que não aparece"""
    t = ev["tipo"]
    if t == "serial":
        return ("serial> " if ev["dir"] == "tx" else "serial< ") + ev["texto"]
    if t == "pino":
        return "%s = %d%s" % (_pino(ev), ev["valor"], "  (roteiro)" if ev["origem"] == "roteiro" else "")
    if t == "modo":
        return "%s %s" % (_pino(ev), MODOS.get(ev["modo"], ev["modo"]))
    if t == "pwm":
        f = ev.get("freq_hz")
        return "%s PWM %s%%%s" % (_pino(ev), num(ev["duty"] * 100, 1), " a %s Hz" % num(f, 1) if f else "")
    if t == "adc":
        return "%s = %s V  (roteiro)" % (_pino(ev), num(ev["volts"]))
    if t == "aviso":
        return "aviso: " + ev["texto"]
    if t == "erro":
        return "ERRO: " + ev["texto"].rstrip().replace("\n", "\n" + " " * 17)
    return None


def fim(ev):
    """'tempo · 3,000 s de placa em 0,12 s de PC · RAM 15 MB'"""
    pc = ("%.2f" % ev["tempo_pc_s"]).replace(".", ",")
    partes = [ev["estado"], "%s de placa em %s s de PC" % (fmt_t(ev["tempo_placa_ms"]), pc)]
    if ev.get("ram_mb") is not None:
        partes.append("RAM %s MB" % num(ev["ram_mb"], 0))
    partes.append("motor %s · %s (alvo %s)" % (ev["motor"], ev["placa"], ev["alvo"]))
    return " · ".join(partes)


def relatorio(eventos, resultados, titulo="", todos=False):
    """linha do tempo + conferências + linha final"""
    out = [titulo] if titulo else []
    corpo = [e for e in eventos[:-1] if linha(e) is not None]
    if not todos and len(corpo) > MAX_LINHAS:   # corta o meio, mas os avisos e erros do meio aparecem
        miolo = corpo[MAX_LINHAS - 40:-39]
        importantes = [e for e in miolo if e["tipo"] in ("aviso", "erro")][:20]
        nota = "  ... (%d eventos no meio%s; -v mostra tudo)" % (
            len(miolo) - len(importantes), ", aqui só os avisos e erros deles" if importantes else "")
        corpo = corpo[:MAX_LINHAS - 40] + [nota] + importantes + (["  ..."] if importantes else []) + corpo[-39:]
    for e in corpo:
        out.append(e if isinstance(e, str) else "  %7s  %s" % (fmt_t(e["t_ms"]), linha(e)))
    if resultados:
        bons = sum(r["ok"] for r in resultados)
        out.append("Conferências: %d de %d ok" % (bons, len(resultados)))
        out += ["  %-6s %s" % ("ok" if r["ok"] else "FALHA", r["texto"]) for r in resultados]
    out.append(fim(eventos[-1]))
    return "\n".join(out)


LINGUAS = {"micropython": "MicroPython", "arduino": "Arduino"}


def _reais(v):
    return ("R$ %.2f" % v).replace(".", ",")


def placas(dados, md=False):
    """a tabela do 'lab.py placas' (dados = o que o --json mostra); md = Markdown pronto pro README"""
    out = ["| Placa | Chip | Rádio | Dormindo (chip) | Preço BR (com estoque) | Loja | Visto | Papel | Testa com |",
           "|---|---|---|---|---|---|---|---|---|"] if md else []
    for d in dados:
        o = d["oferta"]
        preco, loja, visto = (_reais(o["preco"]), o["loja"], o["visto"]) if o else ("?", "sem oferta", "-")
        reserva = " (reserva)" if d["reserva"] else ""
        como = d.get("como") or {}
        nome_m = lambda m: m + (" (roda como %s)" % como[m].upper() if m in como else "")   # noqa: E731
        if md:
            testa = " · ".join("%s: %s" % (LINGUAS[lin], ", ".join(map(nome_m, ms)))
                               for lin, ms in d["motores"].items())
            loja = "[%s](%s)" % (loja, o["link"]) if o else loja
            out.append("| **%s** `%s`%s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                d["nome"], d["id"], reserva, d["chip"], d.get("radio") or "-", d.get("dormindo") or "-", preco, loja,
                visto, d["resumo"], testa))
            continue
        out.append("%-5s %-19s %-10s %-11s visto %-10s %s%s" % (d["id"], d["nome"], preco, loja, visto,
                                                                 d["resumo"], reserva))
        out.append("      %d oferta(s) com estoque em %d loja(s)" % (d["ofertas"], d["lojas"]))
        for lin, ms in d["motores"].items():
            out.append("      %-12s %s" % (LINGUAS[lin] + ":", ", ".join("%s (%s)" % (nome_m(m), s.split(":")[0])
                                                                 for m, s in ms.items())))
    if md:
        out.append("\nPreço: a oferta em reais mais barata com estoque em ferramenta/catalogo/placa_desenvolvimento.json"
                   " (coluna Visto = o dia em que a loja foi lida). Dormindo: o deep sleep do chip, do datasheet; a "
                   "placa de desenvolvimento inteira gasta bem mais (regulador, LED, conversor USB).")
    return out
