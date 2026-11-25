"""Lo descartado, otra vez, como ZONAS: ¿alguno marca zonas o mejora la lectura de las 9 zonas que ya estan?

Todo lo que quedo afuera en algun momento (README y mediciones anteriores), medido como zona a un año igual que
medir_zonas.py (cada dia en la zona: ¿BTC estaba mas arriba 365 dias despues?, contra un dia cualquiera del tramo), y
ademas: sumado al puntaje de las zonas actuales (cuantas marcan compra menos cuantas marcan venta), ¿separa mejor?
(AUC de que suba a 365 y a 180 dias, en cada tramo). Todo sin mirar el futuro.

Tramos: 2012-19 y 2020-25 si hay historia; lo que empieza en 2018-19 (Fear & Greed, funding, stablecoins), en 2019-21
y 2022-25. Una zona puede servir al reves de lo que dice su fama (por ejemplo, mucha emision de stablecoins como zona
de compra): se mide para los dos lados.

Indicadores: Fear & Greed, FRELDI por partes (RSI 14 diario, distancia a la EMA de 200, volumen contra el maximo del
mes, liquidez: balance de la Fed y M2, DXY), hash ribbons, hash price, emision de stablecoins (USDT+USDC), volatilidad
de 90 dias, caida desde el maximo y dias desde el maximo, Delta Price, Thermocap (con la emision, sin comisiones),
stock-to-flow (desvio), NVT por emision, RSI semanal, funding de los perpetuos (promedio de 30 dias).
Uso: python medir_zonas2.py
"""
import csv, io, json, math, urllib.request
from datetime import date, datetime, timezone

import medir_nuevo as mn
from medir_zonas import CAB, cm, fng, rank_exp, sma

TRAMOS_LARGOS = (("2012-19", "2012-01-01", "2020-01-01"), ("2020-25", "2020-01-01", "2100-01-01"))
TRAMOS_CORTOS = (("2019-21", "2019-01-01", "2022-01-01"), ("2022-25", "2022-01-01", "2100-01-01"))


def fred(serie):
    try:
        txt = urllib.request.urlopen(urllib.request.Request(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={serie}", headers=CAB), timeout=60).read().decode()
        out = {}
        for r in list(csv.reader(io.StringIO(txt)))[1:]:
            try:
                out[r[0]] = float(r[1])
            except (ValueError, IndexError):
                pass
        return out
    except Exception as e:
        print(f"  FRED {serie}: no disponible ({type(e).__name__})")
        return {}


def cm_activo(activo, met):
    out, u = {}, (f"https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets={activo}&metrics={met}"
                  f"&frequency=1d&page_size=10000&start_time=2014-01-01")
    try:
        while u:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=CAB), timeout=90).read())
            for r in j.get("data", []):
                if r.get(met) not in (None, ""):
                    out[r["time"][:10]] = float(r[met])
            u = j.get("next_page_url")
    except Exception as e:
        print(f"  {activo} {met}: no disponible ({type(e).__name__})")
    return out


def funding():
    """funding de BTCUSDT (data.binance.vision, desde 2019-09): promedio por dia."""
    por_dia = {}
    for y, m in mn.meses():
        if (y, m) < (2019, 9):
            continue
        rows = mn._zip(f"https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-{y}-{m:02d}.zip",
                       f"fr_{y}-{m:02d}.json", lambda r: [int(r[0]), float(r[2])])
        for t, f in rows:
            d = datetime.fromtimestamp(t / 1000, timezone.utc).date().isoformat()
            por_dia.setdefault(d, []).append(f)
    return {d: sum(v) / len(v) for d, v in por_dia.items()}


def relleno(dias, m):
    """serie diaria desde un dict fecha->valor (semanal o mensual: el ultimo dato publicado)."""
    ks, out, j, u = sorted(m), [], 0, None
    for d in dias:
        while j < len(ks) and ks[j] <= d:
            u = m[ks[j]]; j += 1
        out.append(u)
    return out


def main():
    print("bajando datos...", flush=True)
    S = {k: cm(k) for k in ("PriceUSD", "CapMrktCurUSD", "CapMVRVCur", "SplyCur", "IssTotNtv", "IssTotUSD", "HashRate", "AdrActCnt")}
    dias = sorted(d for d in S["PriceUSD"] if d >= "2010-07-18")
    n = len(dias)
    P = [S["PriceUSD"][d] for d in dias]
    g = lambda k: relleno(dias, S[k])
    cap, mv, sup, iss, issu, hr, adr = map(g, ("CapMrktCurUSD", "CapMVRVCur", "SplyCur", "IssTotNtv", "IssTotUSD", "HashRate", "AdrActCnt"))
    F = fng()
    FUN = funding()
    USDT, USDC = cm_activo("usdt", "SplyCur"), cm_activo("usdc", "SplyCur")
    WALCL, M2, DXY = fred("WALCL"), fred("M2SL"), fred("DTWEXBGS")
    print(f"{n} días: {dias[0]} a {dias[-1]}", flush=True)

    def fut(i, h):
        return P[i + h] > P[i] if i + h < n else None

    # ---- las 9 zonas de hoy, sin mirar el futuro (umbrales por percentil con la historia hasta cada dia) ----
    def pct_zona(x, lo_p=None, hi_p=None, lo=None, hi=None):
        r = rank_exp(x)
        z = []
        for v, rk in zip(x, r):
            if v is None or rk is None:
                z.append(0); continue
            c = (lo is not None and v <= lo) or (lo_p is not None and rk <= lo_p)
            s = (hi is not None and v >= hi) or (hi_p is not None and rk >= hi_p)
            z.append(1 if c else -1 if s else 0)
        return z

    s_ = 0.0; s2 = 0.0; mvz = []
    for k, x in enumerate(mv):
        x = x or 0.0
        s_ += x; s2 += x * x; m = s_ / (k + 1); sd = math.sqrt(max(1e-12, s2 / (k + 1) - m * m)); mvz.append((x - m) / sd)
    ZA = {"MVRV": [1 if z <= -0.5 else -1 if z >= 2 else 0 for z in mvz]}
    m365 = sma([x or 0.0 for x in issu], 365)
    puell = [None if not m365[i] or issu[i] is None else issu[i] / m365[i] for i in range(n)]
    ZA["Puell"] = pct_zona(puell, hi_p=85, lo=0.5)
    for nom, k, kw in (("Mayer", 200, {"hi": 2.4}), ("2 años", 730, {"lo": 1.0, "hi_p": 85}), ("200 semanas", 1400, {"lo": 1.0, "hi": 4.0}),
                       ("Golden", 350, {"lo": 0.8, "hi": 3.0})):
        m = sma(P, k)
        ZA[nom] = pct_zona([None if m[i] is None else P[i] / m[i] for i in range(n)], **kw)
    m111, m350 = sma(P, 111), sma(P, 350)
    ZA["Pi"] = pct_zona([None if m350[i] is None else m111[i] / (2 * m350[i]) for i in range(n)], lo=0.35, hi_p=85)
    gen = date(2009, 1, 3)
    lx = [math.log10((date.fromisoformat(d) - gen).days) for d in dias]
    ly = [math.log10(p) for p in P]
    pl, sx, a, b = [None] * n, [0.0] * 5, None, None
    for i in range(n):
        sx[0] += 1; sx[1] += lx[i]; sx[2] += ly[i]; sx[3] += lx[i] ** 2; sx[4] += lx[i] * ly[i]
        if i >= 730 and (i % 30 == 0 or a is None):
            den = sx[0] * sx[3] - sx[1] ** 2; b = (sx[0] * sx[4] - sx[1] * sx[2]) / den; a = (sx[2] - b * sx[1]) / sx[0]
        if a is not None:
            pl[i] = ly[i] - (a + b * lx[i])
    ZA["Ley de potencia"] = pct_zona(pl, lo_p=15, hi_p=85)
    a30 = sma([x or 0.0 for x in adr], 30)
    ZA["Metcalfe"] = pct_zona([None if not a30[i] or cap[i] is None else cap[i] / a30[i] ** 2 for i in range(n)], hi_p=85)
    puntaje = [sum(ZA[k][i] for k in ZA) for i in range(n)]

    # ---- candidatos (mas alto = mas caro, salvo que la medicion diga lo contrario: se miden los dos lados) ----
    C = {}
    if F:
        C["Fear & Greed"] = [F.get(d) for d in dias]
    # RSI 14 diario
    rsi, ag, al_ = [None] * n, None, None
    for i in range(1, n):
        ch = P[i] - P[i - 1]; up, dn = max(ch, 0), max(-ch, 0)
        ag = up if ag is None else (ag * 13 + up) / 14; al_ = dn if al_ is None else (al_ * 13 + dn) / 14
        if i >= 14:
            rsi[i] = 100 - 100 / (1 + ag / al_) if al_ else 100.0
    C["RSI 14 diario"] = rsi
    e200, k_ = [None] * n, 2 / 201
    for i, p in enumerate(P):
        e200[i] = p if i == 0 else p * k_ + e200[i - 1] * (1 - k_)
    C["Distancia a la EMA de 200 días"] = [P[i] / e200[i] - 1 if i >= 200 else None for i in range(n)]
    # RSI semanal
    rs, ag, al_ = [None] * n, None, None
    for i in range(7, n):
        if i % 7:
            rs[i] = rs[i - 1]; continue
        ch = P[i] - P[i - 7]; up, dn = max(ch, 0), max(-ch, 0)
        ag = up if ag is None else (ag * 13 + up) / 14; al_ = dn if al_ is None else (al_ * 13 + dn) / 14
        rs[i] = 100 - 100 / (1 + ag / al_) if al_ else 100.0
    C["RSI 14 semanal"] = rs
    h30, h60 = sma([x or 0.0 for x in hr], 30), sma([x or 0.0 for x in hr], 60)
    C["Hash ribbons (30/60)"] = [None if not h60[i] else h30[i] / h60[i] for i in range(n)]
    C["Hash price (emisión USD / hashrate)"] = [None if not hr[i] or issu[i] is None else issu[i] / hr[i] for i in range(n)]
    # volatilidad de 90 dias, caida desde el maximo, dias desde el maximo
    lr = [0.0] + [math.log(P[i] / P[i - 1]) for i in range(1, n)]
    vol = [None] * n
    for i in range(90, n):
        w = lr[i - 89:i + 1]; m = sum(w) / 90
        vol[i] = math.sqrt(sum((x - m) ** 2 for x in w) / 89) * math.sqrt(365)
    C["Volatilidad de 90 días"] = vol
    mx, dmx, caida, dsm = 0.0, 0, [], []
    for i, p in enumerate(P):
        if p >= mx:
            mx, dmx = p, i
        caida.append(p / mx - 1); dsm.append(i - dmx)
    C["Caída desde el máximo"] = caida
    C["Días desde el máximo"] = [float(x) for x in dsm]
    # Delta Price, Thermocap (con la emision), stock-to-flow
    rcap = [None if c is None or not m else c / m for c, m in zip(cap, mv)]
    acum, dp, th, ac2 = 0.0, [], [], 0.0
    for i in range(n):
        acum += cap[i] or 0.0; ac2 += issu[i] or 0.0
        avg = acum / (i + 1)
        dp.append(None if rcap[i] is None or not sup[i] or rcap[i] - avg <= 0 else P[i] / ((rcap[i] - avg) / sup[i]))
        th.append(None if not ac2 or cap[i] is None else cap[i] / ac2)
    C["Delta Price (precio / delta)"] = dp
    C["Thermocap (con la emisión)"] = th
    iss365 = sma([x or 0.0 for x in iss], 365)
    s2f = [None if not iss365[i] or not sup[i] else sup[i] / (iss365[i] * 365) for i in range(n)]
    # desvio del precio contra el ajuste log(precio) ~ log(s2f), con lo que habia hasta cada dia
    dev, sx, a, b = [None] * n, [0.0] * 5, None, None
    for i in range(n):
        if s2f[i] is None or s2f[i] <= 0:
            continue
        x, y = math.log10(s2f[i]), math.log10(P[i])
        sx[0] += 1; sx[1] += x; sx[2] += y; sx[3] += x * x; sx[4] += x * y
        if sx[0] >= 730 and (i % 30 == 0 or a is None):
            den = sx[0] * sx[3] - sx[1] ** 2; b = (sx[0] * sx[4] - sx[1] * sx[2]) / den; a = (sx[2] - b * sx[1]) / sx[0]
        if a is not None:
            dev[i] = y - (a + b * x)
    C["Stock-to-flow (desvío del ajuste)"] = dev
    C["NVT por emisión (capitalización / emisión anual USD)"] = [None if not m365[i] or cap[i] is None else cap[i] / (m365[i] * 365) for i in range(n)]
    if FUN:
        f = [FUN.get(d) for d in dias]
        f30 = [None] * n
        for i in range(n):
            w = [x for x in f[max(0, i - 29):i + 1] if x is not None]
            f30[i] = sum(w) / len(w) if len(w) >= 20 else None
        C["Funding de los perpetuos (30 días)"] = f30
    if USDT or USDC:
        st = [(USDT.get(d) or 0.0) + (USDC.get(d) or 0.0) or None for d in dias]
        C["Emisión de stablecoins (90 días)"] = [None if i < 90 or not st[i] or not st[i - 90] else st[i] / st[i - 90] - 1 for i in range(n)]
    for nom, m in (("Balance de la Fed (año contra año)", WALCL), ("M2 de EE.UU. (año contra año)", M2)):
        if m:
            x = relleno(dias, m)
            C[nom] = [None if i < 365 or x[i] is None or not x[i - 365] else x[i] / x[i - 365] - 1 for i in range(n)]
    if DXY:
        x = relleno(dias, DXY)
        C["DXY (contra su media de 200 días)"] = [None if i < 200 or x[i] is None or not x[i - 200] else x[i] / (sum(v or 0 for v in x[i - 199:i + 1]) / 200) - 1 for i in range(n)]
    vol_d = None    # volumen: CoinMetrics community no lo trae para BTC gratis; queda afuera

    # ---- evaluacion ----

    def auc(score, idx, h):
        pos = [score[i] for i in idx if fut(i, h)]
        neg = [score[i] for i in idx if fut(i, h) is False]
        if not pos or not neg:
            return None
        # AUC por rangos (empates a la mitad)
        todos = sorted(pos + neg)
        rk = {}
        i = 0
        while i < len(todos):
            j = i
            while j < len(todos) and todos[j] == todos[i]:
                j += 1
            rk[todos[i]] = (i + j + 1) / 2
            i = j
        sp = sum(rk[v] for v in pos)
        return (sp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))

    if F:
        fg = C["Fear & Greed"]
        print("\n=== Fear & Greed con la lógica 'cuanto más miedo, mejor para comprar' (zonas clásicas) ===")
        for lo, hi in ((20, 80), (25, 75), (10, 90)):
            for h in (30, 90, 180, 365):
                partes = []
                for tn, a0, b0 in (("2018-19", "2018-02-01", "2020-01-01"), ("2020-21", "2020-01-01", "2022-01-01"), ("2022-23", "2022-01-01", "2024-01-01"), ("2024-25", "2024-01-01", "2100-01-01")):
                    idx = [i for i in range(n) if a0 <= dias[i] < b0 and fut(i, h) is not None and fg[i] is not None]
                    if not idx:
                        continue
                    base = sum(fut(i, h) for i in idx) / len(idx)
                    c_ = [i for i in idx if fg[i] <= lo]; v_ = [i for i in idx if fg[i] >= hi]
                    pc = f"{100 * sum(fut(i, h) for i in c_) / len(c_):.0f}%" if len(c_) >= 10 else "—"
                    pv = f"{100 * sum(fut(i, h) for i in v_) / len(v_):.0f}%" if len(v_) >= 10 else "—"
                    partes.append(f"{tn}: miedo<= {lo} sube {pc} ({len(c_)} d) · codicia>= {hi} sube {pv} ({len(v_)} d) · normal {100 * base:.0f}%")
                print(f"  {h:>3} días | " + " | ".join(partes), flush=True)

    resumen = []
    for nom, x in C.items():
        primero = next((dias[i] for i, v in enumerate(x) if v is not None), "2100")
        tramos = TRAMOS_LARGOS if primero < "2013-06-01" else TRAMOS_CORTOS
        r = rank_exp(x, minimo=365 if primero >= "2017" else 730)
        print(f"\n=== {nom} (desde {primero}; tramos {tramos[0][0]} y {tramos[1][0]}) ===", flush=True)
        mejor = None
        for lo_p, hi_p in ((15, 85), (10, 90)):
            zona = [0 if rk is None else 1 if rk <= lo_p else -1 if rk >= hi_p else 0 for rk in r]   # +1: zona baja, -1: alta
            lados = {}
            for lado, val in (("baja", 1), ("alta", -1)):
                difs = []
                for tn, a0, b0 in tramos:
                    idx = [i for i in range(n) if a0 <= dias[i] < b0 and fut(i, 365) is not None]
                    base = sum(fut(i, 365) for i in idx) / len(idx) if idx else 0
                    sel = [i for i in idx if zona[i] == val]
                    if len(sel) < 20:
                        difs.append(None); continue
                    difs.append(sum(fut(i, 365) for i in sel) / len(sel) - base)
                if all(d is not None and d >= 0.10 for d in difs):
                    lados[lado] = "COMPRA"
                elif all(d is not None and d <= -0.10 for d in difs):
                    lados[lado] = "VENTA"
                else:
                    lados[lado] = "—"
                print(f"  percentil {lo_p}/{hi_p} zona {lado}: " + " · ".join("pocos" if d is None else f"{100 * d:+.0f} pts" for d in difs) + f" → {lados[lado]}")
            # ¿suma al puntaje de las zonas actuales? (con su signo medido: compra +1, venta -1)
            signo = {"baja": 0, "alta": 0}
            for lado in ("baja", "alta"):
                signo[lado] = 1 if lados[lado] == "COMPRA" else -1 if lados[lado] == "VENTA" else 0
            nuevo = [puntaje[i] + (signo["baja"] if zona[i] == 1 else signo["alta"] if zona[i] == -1 else 0) for i in range(n)]
            txt = []
            for tn, a0, b0 in tramos:
                for h in (180, 365):
                    idx = [i for i in range(n) if a0 <= dias[i] < b0 and fut(i, h) is not None]
                    a1, a2 = auc(puntaje, idx, h), auc(nuevo, idx, h)
                    if a1 is not None and a2 is not None:
                        txt.append(f"{tn} {h}d {a1:.3f}→{a2:.3f}")
            print(f"  sumado a las 9 zonas: {' · '.join(txt) if any(signo.values()) else 'no aplica (no marca zona en los dos tramos)'}")
            if any(signo.values()):
                difs = [float(t.split('→')[1]) - float(t.split(' ')[-1].split('→')[0]) for t in txt]
                mejor = (lo_p, hi_p, lados, difs) if mejor is None or min(difs) > min(mejor[3]) else mejor
        hoy = next((v for v in reversed(x) if v is not None), None)
        resumen.append((nom, mejor, None if r[-1] is None else round(r[-1]), hoy))
    print("\n=== resumen: zona sola (en los dos tramos, 10 puntos o más) y sumada al puntaje de las 9 zonas (AUC, cambio mínimo entre tramos y plazos) ===")
    for nom, mejor, rk, hoy in resumen:
        if mejor is None:
            print(f"  {nom:<54} no marca zona                      hoy: percentil {rk}")
        else:
            lo_p, hi_p, lados, difs = mejor
            print(f"  {nom:<54} {lo_p}/{hi_p}: baja {lados['baja']:<6} alta {lados['alta']:<6} AUC {min(difs):+.3f} a {max(difs):+.3f}   hoy: percentil {rk}")


if __name__ == "__main__":
    main()
