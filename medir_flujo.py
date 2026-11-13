"""¿Las senales nuevas (flujo de compras, VWAP, perfil de volumen y conceptos ICT) predicen la direccion? (medir antes de sumar)

Velas de 1 hora de BTCUSDT 2021-2026 de data.binance.vision (perpetuos y spot, con el volumen comprador para el delta y el
CVD). Para cada senal: cuantas veces aparece y en que % acierta la direccion de la proxima hora y de las proximas 4 (lo
honesto es ~50%; z = cuantos desvios se aleja de 50%). Se mide aparte en 2021-24 y en 2025-26: entra a la app solo lo
que gana en los dos (z >= 2 y el mismo lado).
Uso: python medir_flujo.py   (baja los archivos a datos_medicion/flujo, se reusan)
"""
import csv, io, json, math, os, time, urllib.request, zipfile
from datetime import date

import indicadores as ind

CABEZAS = {"User-Agent": "analista-btc-medicion"}
DIR = os.path.join("datos_medicion", "flujo")


def _mes(base, sym, y, m):
    os.makedirs(DIR, exist_ok=True)
    f = os.path.join(DIR, f"{base.split('/')[-1]}_{sym}_{y}-{m:02d}.json")
    if os.path.exists(f):
        return json.load(open(f))
    u = f"https://data.binance.vision/data/{base}/monthly/klines/{sym}/1h/{sym}-1h-{y}-{m:02d}.zip"
    for _ in range(3):
        try:
            z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(urllib.request.Request(u, headers=CABEZAS), timeout=60).read()))
            rows = [[int(r[0]) // (1000 if int(r[0]) > 10**14 else 1), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]), float(r[9])]
                    for r in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))) if r[0].isdigit()]
            json.dump(rows, open(f, "w"))
            return rows
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []
            time.sleep(3)
        except Exception:
            time.sleep(3)
    return []


def serie(base):
    out, hoy, y, m = [], date.today(), 2021, 1
    while (y, m) < (hoy.year, hoy.month):
        out += _mes(base, "BTCUSDT", y, m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def z_de(ok, n):
    return (ok / n - 0.5) / math.sqrt(0.25 / n) if n else 0.0


def ind_perfil(bars, nb=24):
    lo, hi = min(b[3] for b in bars), max(b[2] for b in bars)
    if hi <= lo:
        return None
    paso, vol = (hi - lo) / nb, [0.0] * nb
    for b in bars:
        k0, k1 = min(nb - 1, int((b[3] - lo) / paso)), min(nb - 1, int((b[2] - lo) / paso))
        for k in range(k0, k1 + 1):
            vol[k] += b[5] / (k1 - k0 + 1)
    k = max(range(nb), key=lambda i: vol[i])
    return lo + (k + 0.5) * paso


def main():
    P = serie("futures/um")
    S = {r[0]: r for r in serie("spot")}
    print(f"{len(P)} velas de perpetuos, {len(S)} de spot", flush=True)
    t, o, h, l, c, v, tb = (list(x) for x in zip(*P))
    n = len(P)
    dp = [2 * tb[k] - v[k] for k in range(n)]                                  # delta perpetuos (BTC)
    ds = [2 * S[t[k]][6] - S[t[k]][5] if t[k] in S else 0.0 for k in range(n)]  # delta spot
    corte = next(k for k in range(n) if t[k] >= 1735689600000)                 # 2025-01-01
    senales = {}

    def anotar(nombre, k, lado):
        if lado:
            senales.setdefault(nombre, []).append((k, lado))

    pv = vv = 0.0
    for k in range(n):
        if k == 0 or t[k] // 86400000 != t[k - 1] // 86400000:
            pv = vv = 0.0
        pv += (h[k] + l[k] + c[k]) / 3 * v[k]
        vv += v[k]
        if vv and k >= 24:
            vw = pv / vv
            anotar("precio arriba del VWAP del día", k, 1 if c[k] > vw else -1)
            pr = ind_perfil(P[k - 23:k + 1])
            if pr:
                anotar("precio arriba del POC de 24 h", k, 1 if c[k] > pr else -1)
        if k >= 24:
            d1, d4 = dp[k], sum(dp[k - 3:k + 1])
            anotar("delta perp de la última hora", k, 1 if d1 > 0 else -1)
            anotar("delta perp de 4 h", k, 1 if d4 > 0 else -1)
            s24 = sum(ds[k - 23:k + 1])
            anotar("delta spot de 24 h", k, 1 if s24 > 0 else -1)
            ch = c[k] / c[k - 24] - 1
            if ch < -0.01 and s24 > 0:
                anotar("spot compra con el precio bajando (24 h)", k, 1)
            elif ch > 0.01 and s24 < 0:
                anotar("spot vende con el precio subiendo (24 h)", k, -1)
            cvd, acc = [], 0.0
            for j in range(k - 23, k + 1):
                acc += dp[j]
                cvd.append(acc)
            if c[k] >= max(c[k - 23:k + 1]) and cvd[-1] < max(cvd):
                anotar("divergencia de CVD bajista", k, -1)
            elif c[k] <= min(c[k - 23:k + 1]) and cvd[-1] > min(cvd):
                anotar("divergencia de CVD alcista", k, 1)
            s4 = sum(ds[k - 3:k + 1])
            if d4 > 0 and s4 < 0:
                anotar("perp compra y spot vende (4 h)", k, 1)
            elif d4 < 0 and s4 > 0:
                anotar("perp vende y spot compra (4 h)", k, -1)
    for nombre, ev in sorted(senales.items()):
        linea = f"  {nombre:<42}"
        for hz in (1, 4):
            for a, z in ((0, corte), (corte, n)):
                xs = [(k, s) for k, s in ev if a <= k < z and k + hz < n]
                ok = sum(1 for k, s in xs if (c[k + hz] > c[k]) == (s > 0))
                linea += f" | {hz} h {'21-24' if a == 0 else '25-26'}: {len(xs):>6} · {100 * ok / max(1, len(xs)):5.1f}% (z {z_de(ok, len(xs)):+5.1f})"
        print(linea, flush=True)
    # conceptos ICT con la misma medicion de la app (ict() en indicadores), en 1 h y en 4 h
    for tf, k4 in (("1 h", 1), ("4 h", 4)):
        B = P if k4 == 1 else [[P[i][0], P[i][1], max(x[2] for x in P[i:i + 4]), min(x[3] for x in P[i:i + 4]), P[i + 3][4], sum(x[5] for x in P[i:i + 4])]
                                for i in range(0, n - 3) if P[i][0] % (4 * 3600000) == 0]
        cut = next(i for i in range(len(B)) if B[i][0] >= 1735689600000)
        for hz in ((1, 4) if k4 == 1 else (1, 3)):
            for a, z in ((0, cut), (cut, len(B))):
                sub = B[max(0, a - 25):z]
                atr = ind.atr_w([b[2] for b in sub], [b[3] for b in sub], [b[4] for b in sub])
                _, st = ind.ict(sub, atr, 60 * k4, horizon=hz, lookback=len(sub), sigue=400)
                txt = " · ".join(f"{k} {s[0]} veces {100 * s[1] / max(1, s[0]):.1f}% (z {z_de(s[1], s[0]):+.1f})" for k, s in sorted(st.items()))
                print(f"  ICT {tf}, {hz * k4} h después, {'2021-24' if a == 0 else '2025-26'}: {txt}", flush=True)


if __name__ == "__main__":
    main()
