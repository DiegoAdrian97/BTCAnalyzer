"""Dos candidatos nuevos (nov. 2026).

leadlag  ¿BTC se mueve antes que SOL, XRP, ZEC y ETH? Velas de 1 minuto de futuros de Binance, 2023-24 y 2025-26.
         Cuando BTC se movio fuerte en los ultimos k minutos (k = 1 y 5) y la moneda hizo menos de la mitad, ¿la moneda
         va para el lado de BTC en los k minutos siguientes? % de aciertos y retorno medio en pb (comision: 10 pb).
macro    Nasdaq, dolar (DXY), VIX y tasa a 10 años (cierres diarios de Yahoo): ¿anticipan a BTC a 7 y 30 dias?
         2017-21 y 2022-26; z por bloques de 30 dias.
Uso: python medir_extra.py leadlag|macro
"""
import json
import math
import sys
import urllib.request
from collections import defaultdict
from datetime import date

import numpy as np

import medir_nuevo as mn

CAB = {"User-Agent": "Mozilla/5.0"}


def minutos(sym, desde=(2023, 1)):
    t, c = [], []
    for y, m in mn.meses(desde=desde):
        rows = mn._zip(f"https://data.binance.vision/data/futures/um/monthly/klines/{sym}USDT/1m/{sym}USDT-1m-{y}-{m:02d}.zip",
                       f"m1_{sym}_{y}-{m:02d}.json", lambda r: [int(r[0]) // (1000 if int(r[0]) > 10**14 else 1) // 60000, float(r[4])])
        for a, b in rows:
            t.append(a); c.append(b)
    return dict(zip(t, c))


def leadlag():
    btc = minutos("BTC")
    T = np.array(sorted(btc)); 
    corte = (date(2025, 1, 1) - date(1970, 1, 1)).days * 1440
    print(f"BTC: {len(T)} minutos", flush=True)
    for sym in ("ETH", "SOL", "XRP", "ZEC"):
        alt = minutos(sym)
        ts = np.array([x for x in T if x in alt and x - 5 in alt and x + 5 in alt and x - 5 in btc and x - 1 in btc and x - 1 in alt and x + 1 in alt])
        if len(ts) < 100000:
            print(f"{sym}: pocos datos ({len(ts)})"); continue
        b0 = np.array([btc[x] for x in ts]); a0 = np.array([alt[x] for x in ts])
        print(f"\n=== {sym}: {len(ts)} minutos ===", flush=True)
        for k, umb in ((1, 0.0015), (1, 0.003), (5, 0.003), (5, 0.006)):
            rb = b0 / np.array([btc[x - k] for x in ts]) - 1
            ra = a0 / np.array([alt[x - k] for x in ts]) - 1
            fut = np.array([alt[x + k] for x in ts]) / a0 - 1
            sel = (np.abs(rb) >= umb) & (ra * np.sign(rb) < 0.5 * np.abs(rb))
            txt = f"  BTC ±{umb * 100:.2f}% en {k} min y {sym} menos de la mitad → {sym} a {k} min"
            for tr in (0, 1):
                m = sel & ((ts < corte) == (tr == 0))
                base = float(np.mean(fut[(ts < corte) == (tr == 0)] > 0))
                n = int(m.sum())
                if n < 100:
                    txt += f" | pocos ({n})"; continue
                lado = np.sign(rb[m]); ok = float(np.mean((fut[m] > 0) == (lado > 0)))
                ps = float(np.mean(lado > 0)); b = ps * base + (1 - ps) * (1 - base)
                r = lado * fut[m] * 1e4
                ne = len(set((ts[m] // max(k, 1)).tolist()))
                txt += f" | {n:>6} · acierta {100 * ok:4.1f}% (normal {100 * b:4.1f}%, z {(ok - b) / math.sqrt(b * (1 - b) / ne):+.1f}) · {r.mean():+5.1f} pb por operación (z {r.mean() / (r.std() / math.sqrt(ne)):+.1f})"
            print(txt, flush=True)


def yahoo(sym):
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=1420070400&period2=1900000000&interval=1d"
    d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=CAB), timeout=30).read())["chart"]["result"][0]
    return {int(t) // 86400: c for t, c in zip(d["timestamp"], d["indicators"]["quote"][0]["close"]) if c}


def macro():
    import medir_largos as ml
    B = ml.diarias()
    dias = [b[0] // 86400000 for b in B]; c = [b[4] for b in B]
    pos = {d: i for i, d in enumerate(dias)}
    corte = (date(2022, 1, 1) - date(1970, 1, 1)).days
    S = {}
    for nom, sym in (("Nasdaq", "%5ENDX"), ("dólar (DXY)", "DX-Y.NYB"), ("VIX", "%5EVIX"), ("tasa a 10 años", "%5ETNX"), ("S&P 500", "%5EGSPC"), ("oro", "GC%3DF")):
        try:
            S[nom] = yahoo(sym); print(f"{nom}: {len(S[nom])} días", flush=True)
        except Exception as e:
            print(f"({nom}: {type(e).__name__}: {e})", flush=True)
    ev = defaultdict(list)                     # señal -> [(dia BTC, lado)]
    for nom, s in S.items():
        ds = sorted(s); v = [s[d] for d in ds]
        inv = nom in ("dólar (DXY)", "VIX", "tasa a 10 años")
        for j in range(60, len(ds)):
            d = ds[j]
            if d not in pos:
                continue
            for n in (5, 20):
                r = v[j] / v[j - n] - 1
                if abs(r) > 0:
                    ev[f"{nom}: {'baja' if inv else 'sube'} en {n} ruedas → BTC sube" if True else ""].append((d, (1 if r > 0 else -1) * (-1 if inv else 1)))
            ma = sum(v[j - 49:j + 1]) / 50
            ev[f"{nom}: {'debajo' if inv else 'arriba'} de su media de 50 → BTC sube"].append((d, (1 if v[j] > ma else -1) * (-1 if inv else 1)))
            if nom == "VIX":
                if v[j] >= 30:
                    ev["VIX >= 30 (pánico) → BTC sube"].append((d, 1))
    print()
    for nom in sorted(ev):
        for h in (7, 30):
            txt, zs = f"  {nom:<52} {h:>2} d", []
            for tr in (0, 1):
                en = lambda d: (d < corte) == (tr == 0)
                tot = [c[i + h] > c[i] for i, d in enumerate(dias) if en(d) and i + h < len(c)]
                base = sum(tot) / len(tot)
                bl = defaultdict(list)
                for d, l in ev[nom]:
                    i = pos[d]
                    if en(d) and i + h < len(c):
                        bl[d // 30].append(((c[i + h] > c[i]) == (l > 0)) - (base if l > 0 else 1 - base))
                n = sum(len(x) for x in bl.values())
                if len(bl) < 12:
                    txt += f" | pocos ({n})"; zs.append(None); continue
                mb = [sum(x) / len(x) for x in bl.values()]
                mu = sum(mb) / len(mb); sd = math.sqrt(sum((x - mu) ** 2 for x in mb) / (len(mb) - 1))
                z = mu / (sd / math.sqrt(len(mb) / max(1, h / 30))) if sd else 0
                zs.append(z)
                txt += f" | {n:>5} días · {100 * sum(sum(x) for x in bl.values()) / n:+5.1f} pts sobre lo normal (z {z:+.1f})"
            ver = "A FAVOR" if all(x is not None and x >= 2 for x in zs) else "AL REVÉS" if all(x is not None and x <= -2 for x in zs) else "~"
            print(txt + f"  → {ver}", flush=True)


if __name__ == "__main__":
    {"leadlag": leadlag, "macro": macro}[sys.argv[1]]()
