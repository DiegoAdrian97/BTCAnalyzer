"""Ronda de candidatos nuevos para complementar el analisis (medir antes de sumar). Nov. 2026.

Lo que la app todavia no usa y tiene historia gratis:
  A. Tendencia para la semana y el mes (diario, CoinMetrics 2011-2026): precio contra las medias de 50 y 200 dias,
     cruce dorado, retorno de 7, 30 y 90 dias, rupturas de 20 y 55 dias (Donchian). ¿Sigue (momentum) o revierte?
  B. Estacionalidad: dia de la semana (diario) y hora del dia (velas de 1 h, 2021-2026).
  C. Prima del perpetuo contra el spot (premium index de Binance, 1 h): extremos contra sus ultimos 30 dias.
  D. Funding de cada pago (8 h): alto (>= 0,03%) o negativo, a 8 h, 1 dia y 7 dias.
  E. Huecos del CME (viernes al cierre → domingo a la reapertura): ¿se rellenan mas que un movimiento cualquiera igual?
  F. Otros mercados: Nasdaq y dolar (FRED o Stooq) y ETH/BTC, tendencia de 20 dias → BTC a 7 y 30 dias.
Cada señal dice un lado; acierta si el precio fue para ahi. Se compara con un momento cualquiera del tramo, en dos
tramos (diario: 2012-19 y 2020-26; velas: 2021-24 y 2025-26). Las señales que se pisan cuentan una vez por horizonte.
A FAVOR / AL REVES: z >= 2 (o <= -2) en los dos tramos.
Uso: python medir_complementos.py
"""
import csv, io, json, math, time, urllib.request
from datetime import date, datetime, timezone

import medir_nuevo as mn
from medir_senales import velas
from medir_zonas import CAB, cm, sma

RES = []


def z_de(ok, b, ne):
    return (ok - b) / math.sqrt(max(1e-9, b * (1 - b) / max(1.0, ne)))


def evalua(grupo, nom, ev, c, t, corte, hs, paso_h=1.0):
    """ev: [(i, lado)]; hs: horizontes en horas; paso_h: horas por vela."""
    n = len(c)
    for h in hs:
        k = max(1, round(h / paso_h))
        zs, txt = [], f"  {nom:<52} {h:>4} h"
        for tramo in (0, 1):
            idx = [i for i in range(n - k) if (t[i] < corte) == (tramo == 0)]
            base = sum(c[i + k] > c[i] for i in idx) / max(1, len(idx))
            sel = [(i, l) for i, l in ev if i + k < n and (t[i] < corte) == (tramo == 0)]
            if len(sel) < 20:
                txt += f" | tramo {tramo + 1}: pocos ({len(sel)})"
                zs.append(None)
                continue
            ok = sum((c[i + k] > c[i]) == (l > 0) for i, l in sel) / len(sel)
            sube = sum(1 for _, l in sel if l > 0) / len(sel)
            b = sube * base + (1 - sube) * (1 - base)
            z = z_de(ok, b, len({i // k for i, _ in sel}))
            zs.append(z)
            txt += f" | tramo {tramo + 1}: {len(sel):>5} · acierta {100 * ok:4.1f}% (normal {100 * b:4.1f}%, z {z:+.1f})"
        ver = "A FAVOR" if all(x is not None and x >= 2 for x in zs) else "AL REVÉS" if all(x is not None and x <= -2 for x in zs) else "~"
        print(txt + f"  → {ver}", flush=True)
        if ver != "~":
            RES.append((grupo, nom, h, ver))


def serie_ext(nombre, fred_id, stooq):
    for intento in range(3):
        try:
            txt = urllib.request.urlopen(urllib.request.Request(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={fred_id}", headers=CAB), timeout=120).read().decode()
            out = {}
            for r in list(csv.reader(io.StringIO(txt)))[1:]:
                try:
                    out[r[0]] = float(r[1])
                except (ValueError, IndexError):
                    pass
            if len(out) > 1000:
                return out
        except Exception:
            time.sleep(3)
    try:
        txt = urllib.request.urlopen(urllib.request.Request(f"https://stooq.com/q/d/l/?s={stooq}&i=d", headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read().decode()
        out = {}
        for r in list(csv.reader(io.StringIO(txt)))[1:]:
            try:
                out[r[0]] = float(r[4])
            except (ValueError, IndexError):
                pass
        if len(out) > 1000:
            return out
    except Exception as e:
        print(f"  {nombre}: no disponible ({type(e).__name__})")
    print(f"  {nombre}: no disponible")
    return {}


def relleno(dias, m):
    ks, out, j, u = sorted(m), [], 0, None
    for d in dias:
        while j < len(ks) and ks[j] < d:          # lo publicado hasta el dia anterior (sin mirar el futuro)
            u = m[ks[j]]; j += 1
        out.append(u)
    return out


def diario():
    px = cm("PriceUSD")
    dias = sorted(d for d in px if d >= "2011-01-01")
    c = [px[d] for d in dias]
    n = len(c)
    t = [(date.fromisoformat(d) - date(1970, 1, 1)).days * 86400000 for d in dias]
    corte = (date(2020, 1, 1) - date(1970, 1, 1)).days * 86400000
    print(f"\n=== A. Tendencia para la semana y el mes (diario, {n} días) ===", flush=True)
    m50, m200 = sma(c, 50), sma(c, 200)
    S = {}
    S["Precio sobre / bajo la media de 50 días"] = [(i, 1 if c[i] > m50[i] else -1) for i in range(n) if m50[i]]
    S["Precio sobre / bajo la media de 200 días"] = [(i, 1 if c[i] > m200[i] else -1) for i in range(n) if m200[i]]
    S["Media de 50 sobre / bajo la de 200 (cruce dorado)"] = [(i, 1 if m50[i] > m200[i] else -1) for i in range(n) if m200[i]]
    for k in (7, 30, 90):
        S[f"Retorno de {k} días (sigue el signo)"] = [(i, 1 if c[i] > c[i - k] else -1) for i in range(k, n)]
    for k in (20, 55):
        ev = []
        for i in range(k, n):
            w = c[i - k:i]
            if c[i] > max(w): ev.append((i, 1))
            elif c[i] < min(w): ev.append((i, -1))
        S[f"Ruptura de {k} días (máximo: sube · mínimo: baja)"] = ev
    S["Solo arriba: precio sobre la media de 200 días"] = [(i, 1) for i in range(n) if m200[i] and c[i] > m200[i]]
    S["Solo abajo: precio bajo la media de 200 días"] = [(i, -1) for i in range(n) if m200[i] and c[i] < m200[i]]
    S["Solo arriba: retorno de 30 días positivo"] = [(i, 1) for i in range(30, n) if c[i] > c[i - 30]]
    S["Solo abajo: retorno de 30 días negativo"] = [(i, -1) for i in range(30, n) if c[i] < c[i - 30]]
    for nom, ev in S.items():
        evalua("A", nom, ev, c, t, corte, (168, 720), 24)

    print("\n=== B1. Día de la semana (cierre diario UTC contra el anterior) ===", flush=True)
    DS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    for wd in range(7):
        txt, zs = f"  {DS[wd]:<10}", []
        for tramo in (0, 1):
            idx = [i for i in range(1, n) if (t[i] < corte) == (tramo == 0)]
            base = sum(c[i] > c[i - 1] for i in idx) / len(idx)
            sel = [i for i in idx if date.fromisoformat(dias[i]).weekday() == wd]
            up = sum(c[i] > c[i - 1] for i in sel) / len(sel)
            z = z_de(up, base, len(sel)); zs.append(z)
            txt += f" | tramo {tramo + 1}: sube {100 * up:4.1f}% (normal {100 * base:4.1f}%, z {z:+.1f})"
        ver = "SUBE MÁS" if all(x >= 2 for x in zs) else "SUBE MENOS" if all(x <= -2 for x in zs) else "~"
        print(txt + f"  → {ver}", flush=True)
        if ver != "~":
            RES.append(("B", f"Día de la semana: {DS[wd]}", 24, ver))

    print("\n=== F. Otros mercados (tendencia de 20 días → BTC) ===", flush=True)
    eth = cm_eth()
    ext = {"Nasdaq": (serie_ext("Nasdaq", "NASDAQCOM", "^ndq"), 1), "Dólar (índice amplio)": (serie_ext("Dólar", "DTWEXBGS", "dx.f"), -1)}
    for nom, (m, sg) in ext.items():
        if not m:
            continue
        x = relleno(dias, m)
        ev = [(i, sg if x[i] > x[i - 20] else -sg) for i in range(20, n) if x[i] and x[i - 20] and x[i] != x[i - 20]]
        evalua("F", f"{nom}: tendencia de 20 días ({'a favor' if sg > 0 else 'al revés'})", ev, c, t, corte, (168, 720), 24)
        ev = [(i, sg if x[i] > x[i - 5] else -sg) for i in range(5, n) if x[i] and x[i - 5] and x[i] != x[i - 5]]
        evalua("F", f"{nom}: tendencia de 5 días ({'a favor' if sg > 0 else 'al revés'})", ev, c, t, corte, (24, 168), 24)
    if eth:
        r = [None if d not in eth else eth[d] / px[d] for d in dias]
        ev = [(i, 1 if r[i] > r[i - 30] else -1) for i in range(30, n) if r[i] and r[i - 30]]
        evalua("F", "ETH/BTC subiendo en 30 días (apetito de riesgo)", ev, c, t, corte, (168, 720), 24)


def cm_eth():
    out, u = {}, ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=eth&metrics=PriceUSD&frequency=1d&page_size=10000&start_time=2015-08-01")
    try:
        while u:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=CAB), timeout=90).read())
            for r in j.get("data", []):
                if r.get("PriceUSD"):
                    out[r["time"][:10]] = float(r["PriceUSD"])
            u = j.get("next_page_url")
    except Exception as e:
        print(f"  ETH: no disponible ({type(e).__name__})")
    return out


def horario():
    B = velas("1h")
    t = [b[0] for b in B]; c = [b[4] for b in B]; n = len(c)
    print(f"\n=== B2. Hora del día (velas de 1 h, {n}; hora de Argentina) ===", flush=True)
    for hr in range(24):
        txt, zs = f"  {((hr - 3) % 24):02d} h", []
        for tramo in (0, 1):
            idx = [i for i in range(1, n) if (t[i] < mn.CORTE) == (tramo == 0)]
            base = sum(c[i] > c[i - 1] for i in idx) / len(idx)
            sel = [i for i in idx if (t[i] // 3600000) % 24 == hr]
            up = sum(c[i] > c[i - 1] for i in sel) / len(sel)
            z = z_de(up, base, len(sel)); zs.append(z)
            txt += f" | tramo {tramo + 1}: sube {100 * up:4.1f}% (z {z:+.1f})"
        ver = "SUBE MÁS" if all(x >= 2 for x in zs) else "SUBE MENOS" if all(x <= -2 for x in zs) else "~"
        print(txt + f"  → {ver}", flush=True)
        if ver != "~":
            RES.append(("B", f"Hora {((hr - 3) % 24):02d} (Argentina)", 1, ver))

    print("\n=== C. Prima del perpetuo contra el spot (percentil de 30 días) ===", flush=True)
    pm = {}
    for y, m in mn.meses():
        for r in mn._zip(f"https://data.binance.vision/data/futures/um/monthly/premiumIndexKlines/BTCUSDT/1h/BTCUSDT-1h-{y}-{m:02d}.zip",
                         f"pi1h_{y}-{m:02d}.json", lambda r: [int(r[0]) // (1000 if int(r[0]) > 10**14 else 1), float(r[4])]):
            pm[r[0]] = r[1]
    if len(pm) > 5000:
        import bisect
        prem = [pm.get(x) for x in t]
        for lo, hi in ((10, 90), (5, 95)):
            ev, win = [], []
            for i in range(n):
                if prem[i] is None:
                    continue
                if len(win) >= 720:
                    s = sorted(win[-720:])
                    rk = 100 * bisect.bisect_left(s, prem[i]) / 720
                    if rk >= hi: ev.append((i, -1))
                    elif rk <= lo: ev.append((i, 1))
                win.append(prem[i])
            evalua("C", f"Prima extrema (alta ≥ {hi}: baja · baja ≤ {lo}: sube)", ev, c, t, mn.CORTE, (1, 4, 24))
            evalua("C", f"  solo prima alta ≥ {hi} (baja)", [e for e in ev if e[1] < 0], c, t, mn.CORTE, (1, 4, 24))
            evalua("C", f"  solo prima baja ≤ {lo} (sube)", [e for e in ev if e[1] > 0], c, t, mn.CORTE, (1, 4, 24))
    else:
        print("  premium index: no disponible")

    print("\n=== D. Funding de cada pago ===", flush=True)
    idx_t = {x: i for i, x in enumerate(t)}
    fr = []
    for y, m in mn.meses():
        fr += mn._zip(f"https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-{y}-{m:02d}.zip",
                      f"fr_{y}-{m:02d}.json", lambda r: [int(r[0]), float(r[2])])
    ev_a, ev_n, ev_x = [], [], []
    for tt, f in fr:
        i = idx_t.get((tt // 3600000) * 3600000)
        if i is None:
            continue
        if f >= 0.0003: ev_a.append((i, -1))
        if f >= 0.0005: ev_x.append((i, -1))
        if f < 0: ev_n.append((i, 1))
    evalua("D", "Funding alto ≥ 0,03% (baja)", ev_a, c, t, mn.CORTE, (8, 24, 168))
    evalua("D", "Funding muy alto ≥ 0,05% (baja)", ev_x, c, t, mn.CORTE, (8, 24, 168))
    evalua("D", "Funding negativo (sube)", ev_n, c, t, mn.CORTE, (8, 24, 168))

    print("\n=== E. Huecos del CME (viernes al cierre → domingo a la reapertura) ===", flush=True)
    for tramo in (0, 1):
        gaps, ctrl = [], []
        for i in range(60, n - 170):
            if (t[i] < mn.CORTE) != (tramo == 0):
                continue
            d = datetime.fromtimestamp(t[i] / 1000, timezone.utc)
            verano = 4 <= d.month <= 10
            ref_i = i - 49
            g = c[i] / c[ref_i] - 1
            if abs(g) < 0.005:
                continue
            fut = B[i + 1:i + 169]
            def toca(h, ref=c[ref_i], g=g, fut=fut):
                return any((b[3] <= ref) if g > 0 else (b[2] >= ref) for b in fut[:h])
            fila = [toca(24), toca(72), toca(168)]
            ctrl.append(fila)
            # domingo a la reapertura (22 UTC en verano, 23 en invierno): 49 h despues del cierre del viernes (21 / 22 UTC)
            if d.weekday() == 6 and d.hour == (22 if verano else 23):
                gaps.append(fila)
        if gaps:
            f = lambda L, k: 100 * sum(x[k] for x in L) / len(L)
            print(f"  tramo {tramo + 1}: {len(gaps)} huecos de 0,5% o más · se rellenó en 24 h {f(gaps, 0):.0f}%, 72 h {f(gaps, 1):.0f}%, 7 días {f(gaps, 2):.0f}%"
                  f"  | un movimiento igual en cualquier otro momento ({len(ctrl)}): {f(ctrl, 0):.0f}%, {f(ctrl, 1):.0f}%, {f(ctrl, 2):.0f}%", flush=True)


def main():
    diario()
    horario()
    print("\n=== resumen: lo que pasó la prueba (los dos tramos, z >= 2) ===")
    for g, nom, h, ver in RES:
        print(f"  [{g}] {nom:<56} {h:>4} h  {ver}")
    if not RES:
        print("  nada")


if __name__ == "__main__":
    main()
