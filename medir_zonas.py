"""¿Que indicadores de ciclo marcan ZONAS de compra y de venta? (medir antes de sumar)

No importa si marcan el punto exacto: importa si, estando en su zona extrema (aunque dure meses), lo que pasa despues
es distinto de un dia cualquiera, y si la zona aparece en cada ciclo. Para cada indicador, con datos diarios gratis
(CoinMetrics desde 2010, Fear & Greed desde 2018) y SIN mirar el futuro:

  - Zonas por percentil: hoy contra toda su historia hasta hoy (minimo 2 años). Zona baja <= 15, zona alta >= 85.
    Y las zonas clasicas de cada uno (MVRV 1 y 3,5; Mayer 0,8 y 2,4; Puell 0,5 y 4; NUPL 0 y 0,75; etc).
  - Cada dia dentro de la zona: % de veces que BTC subio a 180 y 365 dias, contra un dia cualquiera del mismo tramo
    (2012-19 y 2020-25). Sirve si la zona baja sube 10 puntos o mas que lo normal y la alta 10 o mas menos, en los
    dos tramos.
  - Cobertura: en cada techo (2013, 2017, 2021, 2025) y piso (2011, 2015, 2018, 2022) del ciclo, ¿estuvo en su
    zona dentro de +-120 dias?
Uso: python medir_zonas.py
"""
import bisect, json, math, urllib.request
from datetime import date

CAB = {"User-Agent": "analista-btc-medicion"}
TECHOS = ["2013-12-04", "2017-12-17", "2021-11-10", "2025-10-06"]
PISOS = ["2011-11-18", "2015-01-14", "2018-12-15", "2022-11-21"]
METRICAS = ["PriceUSD", "CapMrktCurUSD", "CapMVRVCur", "SplyCur", "IssTotNtv", "HashRate", "NVTAdj90", "NVTAdj",
            "SplyAct1yr", "VelCur1yr", "RevUSD", "AdrActCnt"]


def cm(met):
    out, u = {}, (f"https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics={met}"
                  f"&frequency=1d&page_size=10000&start_time=2010-07-01")
    try:
        while u:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=CAB), timeout=90).read())
            for r in j.get("data", []):
                if r.get(met) not in (None, ""):
                    out[r["time"][:10]] = float(r[met])
            u = j.get("next_page_url")
    except Exception as e:
        print(f"  {met}: no disponible ({type(e).__name__})")
    return out


def fng():
    try:
        j = json.loads(urllib.request.urlopen(urllib.request.Request("https://api.alternative.me/fng/?limit=0&format=json", headers=CAB), timeout=60).read())
        return {date.fromtimestamp(int(r["timestamp"])).isoformat(): float(r["value"]) for r in j["data"]}
    except Exception as e:
        print(f"  Fear & Greed: no disponible ({type(e).__name__})")
        return {}


def sma(x, n):
    out, s = [None] * len(x), 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def rank_exp(v, minimo=730):
    """percentil de cada dia contra su propia historia hasta ese dia (0-100); None sin historia suficiente."""
    hist, out = [], []
    for x in v:
        if x is None or not math.isfinite(x):
            out.append(None)
            continue
        if len(hist) >= minimo:
            out.append(100.0 * bisect.bisect_left(hist, x) / len(hist))
        else:
            out.append(None)
        bisect.insort(hist, x)
    return out


def main():
    S = {m: cm(m) for m in METRICAS}
    F = fng()
    dias = sorted(d for d in S["PriceUSD"] if d >= "2010-07-18")
    n = len(dias)
    P = [S["PriceUSD"][d] for d in dias]
    g = lambda m: [S[m].get(d) for d in dias]
    cap, mv, sup, iss, hr = g("CapMrktCurUSD"), g("CapMVRVCur"), g("SplyCur"), g("IssTotNtv"), g("HashRate")
    print(f"{n} días: {dias[0]} a {dias[-1]}")

    def relleno(x):          # huecos: el ultimo valor conocido
        u, out = None, []
        for v in x:
            u = v if v is not None else u
            out.append(u)
        return out

    cap, mv, sup, iss, hr = map(relleno, (cap, mv, sup, iss, hr))
    I = {}       # nombre -> (serie, umbral_bajo, umbral_alto) ; mas alto = mas caro
    I["MVRV"] = (mv, 1.0, 3.5)
    I["NUPL"] = ([None if m is None else 1 - 1 / m for m in mv], 0.0, 0.75)
    issusd = [None if a is None else a * p for a, p in zip(iss, P)]
    m365 = sma([x or 0.0 for x in issusd], 365)
    I["Puell"] = ([None if m365[i] in (None, 0) or issusd[i] is None else issusd[i] / m365[i] for i in range(n)], 0.5, 4.0)
    for nom, k, lo, hi in (("Mayer (precio / media de 200 días)", 200, 0.8, 2.4), ("Media de 2 años (precio / media de 730 días)", 730, 1.0, 5.0),
                           ("Media de 200 semanas (precio / media de 1400 días)", 1400, 1.0, 4.0), ("Golden Ratio (precio / media de 350 días)", 350, 0.8, 3.0)):
        m = sma(P, k)
        I[nom] = ([None if m[i] is None else P[i] / m[i] for i in range(n)], lo, hi)
    m111, m350 = sma(P, 111), sma(P, 350)
    I["Pi Cycle (media 111 / 2 x media 350)"] = ([None if m350[i] is None else m111[i] / (2 * m350[i]) for i in range(n)], 0.35, 1.0)
    # ley de potencia: residuo del log del precio contra log de los dias desde el genesis, ajustado con lo que habia
    gen = date(2009, 1, 3)
    lx = [math.log10((date.fromisoformat(d) - gen).days) for d in dias]
    ly = [math.log10(p) for p in P]
    pl, sx = [None] * n, [0.0] * 5
    a = b = None
    for i in range(n):
        sx[0] += 1; sx[1] += lx[i]; sx[2] += ly[i]; sx[3] += lx[i] * lx[i]; sx[4] += lx[i] * ly[i]
        if i >= 730 and (i % 30 == 0 or a is None):
            den = sx[0] * sx[3] - sx[1] ** 2
            b = (sx[0] * sx[4] - sx[1] * sx[2]) / den
            a = (sx[2] - b * sx[1]) / sx[0]
        if a is not None:
            pl[i] = ly[i] - (a + b * lx[i])
    I["Ley de potencia (desvío del ajuste)"] = (pl, None, None)
    # delta price: (precio realizado - precio promedio historico) ; precio <= delta = piso
    rcap = [None if c is None or m in (None, 0) else c / m for c, m in zip(cap, mv)]
    acum, dp = 0.0, []
    for i in range(n):
        acum += cap[i] or 0.0
        avg = acum / (i + 1)
        dp.append(None if rcap[i] is None or not sup[i] or rcap[i] - avg <= 0 else P[i] / ((rcap[i] - avg) / sup[i]))
    I["Delta Price (precio / delta)"] = (dp, 1.0, None)
    rev = g("RevUSD")
    if any(rev):
        acum, th = 0.0, []
        for i in range(n):
            acum += rev[i] or 0.0
            th.append(None if not acum or cap[i] is None else cap[i] / acum)
        I["Thermocap (capitalización / ingresos mineros)"] = (th, None, None)
    for met, nom in (("NVTAdj90", "NVT Signal (90 días)"), ("NVTAdj", "NVT"), ("VelCur1yr", "Velocidad (1 año)")):
        x = g(met)
        if any(x):
            I[nom] = (x, None, None)
    sa = g("SplyAct1yr")
    if any(sa):
        I["Oferta que se movió en el último año (%)"] = ([None if s is None or not sup[i] else 100 * s / sup[i] for i, s in enumerate(sa)], None, None)
    ad = g("AdrActCnt")
    if any(ad):
        a30 = sma([x or 0.0 for x in ad], 30)
        I["Metcalfe (capitalización / direcciones²)"] = ([None if a30[i] in (None, 0) or cap[i] is None else cap[i] / a30[i] ** 2 for i in range(n)], None, None)
    h30, h60 = sma(hr, 30), sma(hr, 60)
    I["Hash ribbons (media 30 / media 60 del hashrate)"] = ([None if h60[i] in (None, 0) else h30[i] / h60[i] for i in range(n)], 0.97, None)
    if F:
        I["Fear & Greed"] = ([F.get(d) for d in dias], 20.0, 80.0)
    # RSI 14 semanal (velas de 7 dias desde el genesis de la serie)
    rs, ag, al_ = [None] * n, None, None
    for i in range(7, n):
        if i % 7:
            rs[i] = rs[i - 1]
            continue
        ch = P[i] - P[i - 7]
        up, dn = max(ch, 0), max(-ch, 0)
        ag = up if ag is None else (ag * 13 + up) / 14
        al_ = dn if al_ is None else (al_ * 13 + dn) / 14
        rs[i] = 100 - 100 / (1 + ag / al_) if al_ else 100.0
    I["RSI 14 semanal"] = (rs, 35.0, 85.0)

    def fut(i, h):
        return P[i + h] > P[i] if i + h < n else None

    tramos = (("2012-19", "2012-01-01", "2020-01-01"), ("2020-25", "2020-01-01", "2100-01-01"))
    base = {}
    for h in (180, 365):
        for tn, a0, b0 in tramos:
            idx = [i for i in range(n) if a0 <= dias[i] < b0 and fut(i, h) is not None]
            base[(h, tn)] = sum(fut(i, h) for i in idx) / len(idx)
    print("\nUn día cualquiera: " + " · ".join(f"{h} d {tn}: sube {100 * base[(h, tn)]:.0f}%" for h in (180, 365) for tn, _, _ in tramos))

    def evalua(nom, zona):
        """zona: lista de 'baja'/'alta'/None por dia. Devuelve texto y veredicto."""
        res, ok_b, ok_a = [], [], []
        for h in (180, 365):
            for tn, a0, b0 in tramos:
                for z in ("baja", "alta"):
                    sel = [i for i in range(n) if zona[i] == z and a0 <= dias[i] < b0 and fut(i, h) is not None]
                    if len(sel) < 20:
                        res.append(f"{z} {h}d {tn}: pocos ({len(sel)})")
                        if h == 365:
                            (ok_b if z == "baja" else ok_a).append(None)
                        continue
                    up = sum(fut(i, h) for i in sel) / len(sel)
                    d = up - base[(h, tn)]
                    res.append(f"{z} {h}d {tn}: {len(sel)} d, sube {100 * up:.0f}% ({100 * d:+.0f})")
                    if h == 365:     # el veredicto: un año despues (la zona puede durar meses; a 180 dias es dato)
                        (ok_b if z == "baja" else ok_a).append(d >= 0.10 if z == "baja" else d <= -0.10)
        cob = []
        for lista, z in ((PISOS, "baja"), (TECHOS, "alta")):
            hits = tot = 0
            for c in lista:
                k = bisect.bisect_left(dias, c)
                if k >= n:
                    continue
                win = [zona[j] for j in range(max(0, k - 120), min(n, k + 121))]
                if all(v is None for v in [zona[j] for j in range(max(0, k - 120), min(n, k + 121))]) and k < 730:
                    continue
                tot += 1
                hits += z in win
            cob.append(f"{'pisos' if z == 'baja' else 'techos'} {hits}/{tot}")
        # SIRVE: en los dos tramos; "solo un tramo": el otro no tiene dias en la zona (no se puede confirmar)
        def ver(ok):
            v = [x for x in ok if x is not None]
            return "SIRVE" if len(v) == 2 and all(v) else "1 tramo" if len(v) == 1 and v[0] else "no" if v else "sin datos"
        vb, va = ver(ok_b), ver(ok_a)
        return res, cob, vb, va

    resumen = []
    for nom, (x, lo, hi) in I.items():
        print(f"\n=== {nom} ===")
        hoy = next((v for v in reversed(x) if v is not None), None)
        r = rank_exp(x)
        variantes = [("percentil (<=15 / >=85)", [None if v is None else "baja" if v <= 15 else "alta" if v >= 85 else None for v in r])]
        if lo is not None or hi is not None:
            variantes.append((f"clásica ({'<= ' + str(lo) if lo is not None else '—'} / {'>= ' + str(hi) if hi is not None else '—'})",
                              [None if v is None else "baja" if lo is not None and v <= lo else "alta" if hi is not None and v >= hi else None for v in x]))
        for vn, zona in variantes:
            res, cob, vb, va = evalua(nom, zona)
            print(f"  [{vn}] hoy: {hoy if hoy is None else round(hoy, 3)} (percentil {None if r[-1] is None else round(r[-1])}) · zona de compra: {vb} · zona de venta: {va} · {' · '.join(cob)}")
            for t in res:
                print(f"      {t}")
            resumen.append((nom, vn, vb, va, " · ".join(cob), hoy, r[-1]))
    print("\n=== resumen (SIRVE = en los dos tramos, a 365 días, 10 puntos o más mejor que un día cualquiera; 1 tramo = el otro no llegó a la zona) ===")
    for nom, vn, vb, va, cob, hoy, rk in resumen:
        print(f"  {nom:<52} {vn:<26} compra: {vb:<9} venta: {va:<9} {cob:<20} hoy: percentil {'—' if rk is None else round(rk)}")


if __name__ == "__main__":
    main()
