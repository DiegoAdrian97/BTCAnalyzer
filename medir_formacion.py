"""Tres dudas del sistema, medidas (nov. 2026). BTC futuros 2021-2026, tramos 2021-24 y 2025-26.

1. VELA EN FORMACION. Todo se midio con velas cerradas, pero la app calcula con la vela a medio formar. Las señales de
   1 hora (resumen de indicadores al reves, fuera de Bollinger, RSI extremo, divergencias) calculadas a los 0, 15, 30 y
   45 minutos de la hora (la vela de 1 h armada con las de 5 min hasta ahi): ¿la hora siguiente DESDE ESE MOMENTO va
   para el lado que cuenta la app? Si a mitad de vela rinde igual que al cierre, no hay problema.
2. ESTRUCTURA AL REVES. Figura confirmada, Elliott, cruce del MACD y patrones de velas dieron "al reves" en 15 min y
   1 h. ¿Dicen algo mas que "el precio estirado corrige" (resumen al reves + Bollinger + RSI, que ya cuenta)? Acierto
   de cada una AL REVES cuando el trio no marca nada para ese lado, y cuando si.
3. EN PLATA. Retorno medio por operacion (en puntos basicos, 1 pb = 0,01%) siguiendo cada grupo de señales, contra la
   comision de ida y vuelta de BingX (taker 0,05% x 2 = 10 pb).
Uso: python medir_formacion.py [formacion] [estructura]
"""
import math
import sys
from collections import defaultdict

import indicadores as ind
import medir_nuevo as mn
from medir_senales import velas

H = 3600000
V = 600


def z_txt(sel, base_de, ne):
    """sel: [(acierto 0/1, lado, tramo)] → texto por tramo y lista de z."""
    txt, zs = "", []
    for k in (0, 1):
        s = [(a, l) for a, l, t in sel if t == k]
        if len(s) < 30:
            txt += f" | pocos ({len(s)})"; zs.append(None); continue
        ok = sum(a for a, _ in s) / len(s)
        ps = sum(1 for _, l in s if l > 0) / len(s)
        b = ps * base_de[k] + (1 - ps) * (1 - base_de[k])
        z = (ok - b) / math.sqrt(max(1e-9, b * (1 - b) / max(1, len(s) / ne)))
        zs.append(z)
        txt += f" | {len(s):>6} · acierta {100 * ok:4.1f}% (normal {100 * b:4.1f}%, z {z:+.1f})"
    ver = "A FAVOR" if all(x is not None and x >= 2 for x in zs) else "AL REVÉS" if all(x is not None and x <= -2 for x in zs) else "~"
    return txt + f"  → {ver}"


def trio(win):
    """Lado (para donde cuenta la app) de: resumen al reves, fuera de Bollinger, RSI extremo. 0 si no marca."""
    c = [b[4] for b in win]
    rows, res = ind.calificar(win)[:2]
    a = 0 if abs(res["rating"]) <= 0.1 else (-1 if res["rating"] > 0 else 1)
    bb = next((r for r in rows if r["indicador"] == "Bandas de Bollinger %B"), None)
    b = 0 if not bb or bb["valor"] is None else (-1 if bb["valor"] >= 100 else 1 if bb["valor"] <= 0 else 0)
    r = ind.rsi(c)[-1]
    return a, b, (-1 if r >= 70 else 1 if r <= 30 else 0)


def formacion():
    B5 = velas("5m")
    t0 = B5[0][0]
    n5 = len(B5)
    c5 = [b[4] for b in B5]
    # velas de 1 h cerradas, alineadas a la hora
    ini = next(i for i, b in enumerate(B5) if b[0] % H == 0)
    H1, pos = [], []                       # vela de 1 h y el indice de su primera vela de 5 min
    for i in range(ini, n5 - 11, 12):
        g = B5[i:i + 12]
        if g[-1][0] - g[0][0] != 55 * 60000:
            continue
        H1.append([g[0][0], g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[-1][4], sum(x[5] for x in g)]); pos.append(i)
    print(f"1. VELA EN FORMACIÓN: {len(H1)} velas de 1 h", flush=True)
    acum = defaultdict(list)               # (señal, minutos) -> [(acierto, lado, tramo)]
    base = defaultdict(lambda: [[0, 0], [0, 0]])
    for j in range(V, len(H1) - 2, 2):
        tr = 0 if H1[j][0] < mn.CORTE else 1
        i0 = pos[j]                         # primera vela de 5 min de la hora j
        for k in (0, 3, 6, 9):
            # k = 0: recien cerro la hora j-1 (ventana de velas cerradas). k > 0: la hora j con sus k primeras velas de 5 min
            if k == 0:
                win = H1[j - V:j]; ahora = i0 - 1
            else:
                g = B5[i0:i0 + k]
                win = H1[j - V + 1:j] + [[g[0][0], g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[-1][4], sum(x[5] for x in g)]]
                ahora = i0 + k - 1
            if ahora + 12 >= n5:
                continue
            sube = c5[ahora + 12] > c5[ahora]
            base[k][tr][0] += sube; base[k][tr][1] += 1
            a, b, r = trio(win)
            for nom, lado in (("resumen de indicadores, al revés", a), ("fuera de Bollinger: vuelve", b), ("RSI extremo: revierte", r)):
                if lado:
                    acum[(nom, k)].append((int(sube == (lado > 0)), lado, tr))
            for d in ind.divergencias(win):
                lado = 1 if d["tipo"] == "alcista" else -1
                acum[("divergencia (a favor)", k)].append((int(sube == (lado > 0)), lado, tr))
                break
        if (j - V) % 8000 == 0:
            print(f"  {j - V} de {len(H1) - V}", flush=True)
    for nom in ("resumen de indicadores, al revés", "fuera de Bollinger: vuelve", "RSI extremo: revierte", "divergencia (a favor)"):
        for k in (0, 3, 6, 9):
            bd = [base[k][t][0] / max(1, base[k][t][1]) for t in (0, 1)]
            print(f"  {nom:<34} a los {k * 5:>2} min de la hora" + z_txt(acum[(nom, k)], bd, 1), flush=True)


def estructura(tf, paso, hz):
    B = velas(tf)
    n = len(B)
    c = [b[4] for b in B]
    print(f"\n2 y 3. ESTRUCTURA AL REVÉS y EN PLATA, velas de {tf}: {n}", flush=True)
    filas = []                               # (i, tramo, lado del trio (suma), {señal: lado al reves})
    for i in range(V - 1, n - max(hz) - 1, paso):
        win = B[i - V + 1:i + 1]
        o, h, l, cc = ([b[k] for b in win] for k in (1, 2, 3, 4))
        a, b, r = trio(win)
        s = {}
        pivots = ind.zigzag(win)
        atr_ = ind.atr_w(h, l, cc)
        g = ind.patron_grafico(win, pivots, atr_[-1])
        if g and g["sesgo"] in ("alcista", "bajista") and g["estado"] == "confirmado":
            s["figura confirmada"] = -1 if g["sesgo"] == "alcista" else 1
        _, desc, target, cur, _ = ind.elliott(pivots, win)
        if cur:
            alc = "alcista" in (desc or "").split(";")[0]
            sube = ((cur in ("1", "3", "5", "B")) == alc) if (desc or "").startswith("Impulso") else ((cur == "B") == alc)
            s["Elliott, onda en curso"] = -1 if sube else 1
        _, _, mh = ind.macd(cc)
        for k in (-1, -2):
            if mh[k] > 0 >= mh[k - 1]:
                s["cruce del MACD"] = -1; break
            if mh[k] < 0 <= mh[k - 1]:
                s["cruce del MACD"] = 1; break
        e20 = ind.ema(cc, 20)
        for k in (len(win) - 1, len(win) - 2):
            f = ind.patrones_velas(o, h, l, cc, atr_, e20, k)
            if f:
                if f[0][1] in ("alcista", "bajista"):
                    s["patrón de velas"] = -1 if f[0][1] == "alcista" else 1
                break
        dv = ind.divergencias(win)
        if dv:
            s["DIVERGENCIA (a favor)"] = 1 if dv[0]["tipo"] == "alcista" else -1
        filas.append((i, 0 if B[i][0] < mn.CORTE else 1, (a, b, r), s))
        if len(filas) % 20000 == 0:
            print(f"  {len(filas)} momentos", flush=True)
    for h_ in hz:
        ne = max(1, h_ // paso)
        base = [sum(c[i + h_] > c[i] for i, t, _, _ in filas if t == k) / max(1, sum(1 for f in filas if f[1] == k)) for k in (0, 1)]
        print(f"\n--- a {h_} velas ({tf}) · un momento cualquiera sube {100 * base[0]:.1f}% / {100 * base[1]:.1f}% ---")
        for nom in ("figura confirmada", "Elliott, onda en curso", "cruce del MACD", "patrón de velas", "DIVERGENCIA (a favor)"):
            for caso, cond in (("siempre", lambda T, l: True), ("el trío NO marca ese lado", lambda T, l: not any(x == l for x in T)),
                               ("el trío SÍ marca ese lado", lambda T, l: any(x == l for x in T))):
                sel = [(int((c[i + h_] > c[i]) == (s[nom] > 0)), s[nom], t) for i, t, T, s in filas if nom in s and cond(T, s[nom])]
                print(f"  {nom + (' al revés' if nom[0].islower() else ''):<32} {caso:<26}" + z_txt(sel, base, ne), flush=True)
        # en plata: retorno medio por operacion en pb
        print("  EN PLATA (retorno medio por operación, pb; comisión ida y vuelta 10 pb):")
        grupos = (("trío: 1 marca", lambda T, s: (lambda x: x if abs(sum(T)) == 1 and sum(1 for v in T if v) == 1 else 0)(sum(T))),
                  ("trío: 2 o 3 del mismo lado", lambda T, s: (1 if sum(T) >= 2 else -1 if sum(T) <= -2 else 0)),
                  ("figura confirmada al revés", lambda T, s: s.get("figura confirmada", 0)),
                  ("divergencia", lambda T, s: s.get("DIVERGENCIA (a favor)", 0)),
                  ("divergencia + trío del mismo lado", lambda T, s: (lambda d: d if d and any(x == d for x in T) else 0)(s.get("DIVERGENCIA (a favor)", 0))))
        for nom, f in grupos:
            txt = f"    {nom:<34}"
            for k in (0, 1):
                rs = [l * (c[i + h_] / c[i] - 1) * 1e4 for i, t, T, s in filas if t == k for l in (f(T, s),) if l]
                if len(rs) < 30:
                    txt += f" | pocos ({len(rs)})"; continue
                m = sum(rs) / len(rs); sd = math.sqrt(sum((x - m) ** 2 for x in rs) / len(rs))
                txt += f" | {len(rs):>6} op · {m:+5.1f} pb (z {m / (sd / math.sqrt(len(rs) / ne)):+.1f}) · gana {100 * sum(x > 0 for x in rs) / len(rs):.1f}%"
            print(txt, flush=True)


if __name__ == "__main__":
    q = sys.argv[1:] or ["formacion", "estructura"]
    if "formacion" in q:
        formacion()
    if "estructura" in q:
        estructura("15m", 2, (1, 4))
        estructura("1h", 1, (1, 4))
