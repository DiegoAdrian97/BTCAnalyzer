"""Las señales "de estructura" que el analisis cuenta y nunca se midieron: figuras del grafico, Wyckoff, patrones de
velas, divergencias (RSI y MACD), Elliott y, en el diario, el cruce del MACD. Nov. 2026.

Con las mismas funciones que usa la app (indicadores.py) sobre la ventana de velas que tendria en cada momento, sin
mirar el futuro. Cuando la señal esta (como la cuenta la app: mientras dura), ¿el precio fue para ese lado?
  5 min → 5 y 15 min      15 min → 15 min y 1 h      1 h → 1 h y 4 h      4 h → 4 h y 24 h      diario → 1, 7 y 30 dias
Dos tramos (15 min, 1 h y 4 h: 2021-24 y 2025-26; diario: hasta 2021 y 2022-26). Lo normal de cada tramo descontado
(z). Las señales duran varias velas: para el z cuentan una vez por bloque del largo del horizonte. Aparte, solo la
PRIMERA vela en que aparece cada señal ("recien aparece").  A FAVOR / AL REVES: z >= 2 (o <= -2) en los dos tramos.
Uso: python medir_estructura.py [5m|15m|1h|4h|1d ...]
"""
import math
import sys
from collections import defaultdict

import indicadores as ind
import medir_largos as ml_
import medir_nuevo as mn
from medir_senales import velas

# temporalidad: (ventana, paso entre momentos, horizontes en velas, minutos por vela, horizonte de los patrones de velas)
TFS = {"5m": (600, 2, (1, 3), 5, 3), "15m": (600, 1, (1, 4), 15, 4), "1h": (600, 1, (1, 4), 60, 4), "4h": (600, 1, (1, 6), 240, 3),
       "1d": (600, 1, (1, 7, 30), 1440, 3)}


def senales(win, horizonte_velas):
    """{nombre: +1/-1} de lo que el analisis contaria con esta ventana (la ultima vela, cerrada)."""
    o, h, l, c = ([b[k] for b in win] for k in (1, 2, 3, 4))
    i = len(win) - 1
    out = {}
    pivots = ind.zigzag(win)
    atr_ = ind.atr_w(h, l, c)
    e20 = ind.ema(c, 20)
    g = ind.patron_grafico(win, pivots, atr_[i])
    if g and g["sesgo"] in ("alcista", "bajista"):
        s = 1 if g["sesgo"] == "alcista" else -1
        out["FIGURA del gráfico (cualquiera)"] = s
        out[f"FIGURA {g['estado']}"] = s
        out[f"  figura: {g['nombre']}"] = s
        if g.get("objetivo"):
            out["FIGURA con objetivo: hacia el objetivo"] = 1 if g["objetivo"] > c[i] else -1
    w = ind.wyckoff(win, pivots, atr_[i])
    if w and w["sesgo"] in ("alcista", "bajista"):
        s = 1 if w["sesgo"] == "alcista" else -1
        out["WYCKOFF (cualquiera)"] = s
        out[f"  wyckoff: {w['nombre']}"] = s
    for k in (i, i - 1):
        found = ind.patrones_velas(o, h, l, c, atr_, e20, k)
        if not found:
            continue
        name, bias = found[0]
        if bias in ("alcista", "bajista"):
            s = 1 if bias == "alcista" else -1
            out["VELAS: patrón (cualquiera)"] = s
            n, ok = ind.estadistica_velas(o, h, l, c, atr_, e20, horizonte_velas).get(name, (0, 0))
            if n >= 20 and ok / n * 100 >= 55:
                out["VELAS: patrón que la app cuenta (funcionó 55%+ en 20+ casos)"] = s
        break
    divs = ind.divergencias(win, pivots)
    for d in divs:
        s = 1 if d["tipo"] == "alcista" else -1
        out[f"DIVERGENCIA en {d['indicador']}"] = s
        out["DIVERGENCIA (cualquiera)"] = s
    if len({d["indicador"] for d in divs}) >= 2 and len({d["tipo"] for d in divs}) == 1:
        out["DIVERGENCIA en RSI y MACD a la vez"] = 1 if divs[0]["tipo"] == "alcista" else -1
    _, desc, target, cur, _ = ind.elliott(pivots, win)
    if cur:
        alc = "alcista" in (desc or "").split(";")[0]
        sube = ((cur in ("1", "3", "5", "B")) == alc) if (desc or "").startswith("Impulso") else ((cur == "B") == alc)
        out["ELLIOTT: onda en curso"] = 1 if sube else -1
        out[f"  elliott: onda {cur}"] = 1 if sube else -1
    if target:
        out["ELLIOTT: hacia el objetivo"] = 1 if target > c[i] else -1
    _, _, mh = ind.macd(c)
    for k in (i, i - 1):
        if mh[k] > 0 >= mh[k - 1]:
            out["MACD: cruce (última o anteúltima vela)"] = 1
            break
        if mh[k] < 0 <= mh[k - 1]:
            out["MACD: cruce (última o anteúltima vela)"] = -1
            break
    return out


def medir(tf, B, corte):
    ventana, paso, horizontes, tf_min, hv = TFS[tf]
    n = len(B)
    c = [b[4] for b in B]
    acum = defaultdict(list)                 # nombre -> [(i, lado, recien)]
    antes = {}
    momentos = list(range(ventana - 1, n - 1, paso))
    for q, i in enumerate(momentos):
        s = senales(B[i - ventana + 1:i + 1], hv)
        for nom, lado in s.items():
            acum[nom].append((i, lado, antes.get(nom) != lado))
        antes = s
        if q % 20000 == 0:
            print(f"  {tf}: {q} de {len(momentos)}", flush=True)
    dia = lambda h: f"{h * tf_min // 1440} d" if tf_min >= 1440 else f"{h * tf_min // 60} h" if h * tf_min >= 60 else f"{h * tf_min} min"
    print(f"\n=== velas de {tf}: {len(momentos)} momentos ===", flush=True)
    res = []
    orden = sorted(acum, key=lambda k: (k.startswith("  "), k))
    for nom in orden:
        for solo_nuevas in (False, True):
            ev = [(i, l) for i, l, nuevo in acum[nom] if nuevo or not solo_nuevas]
            for h in horizontes:
                zs, txt = [], f"  {(nom + (' · recién aparece' if solo_nuevas else '')):<62} {dia(h):>6}"
                for tramo in (0, 1):
                    idx = [i for i in momentos if i + h < n and (B[i][0] < corte) == (tramo == 0)]
                    base = sum(c[i + h] > c[i] for i in idx) / max(1, len(idx))
                    sel = [(i, l) for i, l in ev if i + h < n and (B[i][0] < corte) == (tramo == 0)]
                    if len(sel) < 30:
                        txt += f" | pocos ({len(sel)})"; zs.append(None); continue
                    ok = sum((c[i + h] > c[i]) == (l > 0) for i, l in sel) / len(sel)
                    ps = sum(1 for _, l in sel if l > 0) / len(sel)
                    b = ps * base + (1 - ps) * (1 - base)
                    m = len({i // max(h, paso) for i, _ in sel})
                    z = (ok - b) / math.sqrt(max(1e-9, b * (1 - b) / max(1, m)))
                    zs.append(z)
                    txt += f" | {len(sel):>5} · acierta {100 * ok:4.1f}% (normal {100 * b:4.1f}%, z {z:+.1f})"
                ver = "A FAVOR" if all(x is not None and x >= 2 for x in zs) else "AL REVÉS" if all(x is not None and x <= -2 for x in zs) else "~"
                if not nom.startswith("  ") or ver != "~":
                    print(txt + f"  → {ver}", flush=True)
                res.append((tf, nom + (" · recién aparece" if solo_nuevas else ""), dia(h), ver, zs))
    return res


def main():
    quiero = [a for a in sys.argv[1:] if a in TFS] or list(TFS)
    R = []
    for tf in quiero:
        B = ml_.diarias() if tf == "1d" else velas(tf)
        print(f"{tf}: {len(B)} velas", flush=True)
        R += medir(tf, B, ml_.CORTE if tf == "1d" else mn.CORTE)
    print("\n=== lo que pasó (z >= 2 del mismo lado en los dos tramos) ===")
    for tf, nom, d, ver, zs in R:
        if ver != "~":
            print(f"  {tf:<4} {nom:<62} {d:>6}  {ver:<9} z {' / '.join('—' if z is None else f'{z:+.1f}' for z in zs)}")
    print("\n=== las generales (todas) ===")
    for tf, nom, d, ver, zs in R:
        if not nom.startswith("  ") and "recién" not in nom:
            print(f"  {tf:<4} {nom:<62} {d:>6}  {ver:<9} z {' / '.join('—' if z is None else f'{z:+.1f}' for z in zs)}")


if __name__ == "__main__":
    main()
