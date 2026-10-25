"""
Indicadores tecnicos (los de TradingView / Binance / BingX) sobre listas de velas.

Cada funcion recibe listas alineadas (open, high, low, close, volume) y devuelve listas del mismo
largo, con None mientras no hay datos suficientes. Sin dependencias.

calificar(bars) arma el resumen tipo "Technical Ratings" de TradingView: cada media movil y cada
oscilador vota compra / venta / neutral con las reglas de TradingView, y se suman los votos.
"""

import math


def _ar(x, d=0):
    """Numero con formato argentino: 80.757,25"""
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------- medias ----------
def sma(v, n):
    out, acc = [None] * len(v), 0.0
    for i, x in enumerate(v):
        acc += x
        if i >= n:
            acc -= v[i - n]
        if i >= n - 1:
            out[i] = acc / n
    return out


def ema(v, n):
    out, e, k = [None] * len(v), None, 2 / (n + 1)
    for i, x in enumerate(v):
        if x is None:
            continue
        e = x if e is None else x * k + e * (1 - k)
        out[i] = e
    return out


def rma(v, n):
    """Media de Wilder (la que usan RSI, ATR y ADX)."""
    out, a = [None] * len(v), None
    for i, x in enumerate(v):
        if x is None:
            continue
        a = x if a is None else (a * (n - 1) + x) / n
        out[i] = a
    return out


def wma(v, n):
    out, w = [None] * len(v), n * (n + 1) / 2
    for i in range(n - 1, len(v)):
        win = v[i - n + 1:i + 1]
        if None in win:
            continue
        out[i] = sum(x * (j + 1) for j, x in enumerate(win)) / w
    return out


def hma(v, n):
    a, b = wma(v, n // 2), wma(v, n)
    diff = [None if x is None or y is None else 2 * x - y for x, y in zip(a, b)]
    return wma_skip(diff, int(math.sqrt(n)))


def wma_skip(v, n):
    first = next((i for i, x in enumerate(v) if x is not None), len(v))
    return [None] * first + wma(v[first:], n)


def vwma(c, vol, n):
    out = [None] * len(c)
    for i in range(n - 1, len(c)):
        vs = sum(vol[i - n + 1:i + 1])
        out[i] = sum(x * y for x, y in zip(c[i - n + 1:i + 1], vol[i - n + 1:i + 1])) / vs if vs else c[i]
    return out


def rolling(v, n, fn):
    return [None if i < n - 1 else fn(v[i - n + 1:i + 1]) for i in range(len(v))]


# ---------- osciladores ----------
def rsi(c, n=14):
    up = [None] + [max(b - a, 0.0) for a, b in zip(c, c[1:])]
    dn = [None] + [max(a - b, 0.0) for a, b in zip(c, c[1:])]
    au, ad = rma(up, n), rma(dn, n)
    return [None if u is None else 100.0 if d == 0 else 100 - 100 / (1 + u / d) for u, d in zip(au, ad)]


def stoch(h, l, c, n=14, smooth=3, d=3):
    hh, ll = rolling(h, n, max), rolling(l, n, min)
    raw = [None if a is None else (50.0 if a == b else (x - b) / (a - b) * 100) for x, a, b in zip(c, hh, ll)]
    k = sma_skip(raw, smooth)
    return k, sma_skip(k, d)


def sma_skip(v, n):
    first = next((i for i, x in enumerate(v) if x is not None), len(v))
    return [None] * first + sma(v[first:], n)


def stoch_rsi(c, n_rsi=14, n_st=14, k=3, d=3):
    r = rsi(c, n_rsi)
    first = next((i for i, x in enumerate(r) if x is not None), len(r))
    rr = r[first:]
    kk, dd = stoch(rr, rr, rr, n_st, k, d)
    return [None] * first + kk, [None] * first + dd


def cci(h, l, c, n=20):
    tp = [(a + b + x) / 3 for a, b, x in zip(h, l, c)]
    m = sma(tp, n)
    out = [None] * len(c)
    for i in range(n - 1, len(c)):
        md = sum(abs(x - m[i]) for x in tp[i - n + 1:i + 1]) / n
        out[i] = 0.0 if md == 0 else (tp[i] - m[i]) / (0.015 * md)
    return out


def williams_r(h, l, c, n=14):
    hh, ll = rolling(h, n, max), rolling(l, n, min)
    return [None if a is None else (-50.0 if a == b else (a - x) / (a - b) * -100) for x, a, b in zip(c, hh, ll)]


def momentum(c, n=10):
    return [None if i < n else c[i] - c[i - n] for i in range(len(c))]


def macd(c, fast=12, slow=26, sig=9):
    line = [a - b for a, b in zip(ema(c, fast), ema(c, slow))]
    signal = ema(line, sig)
    return line, signal, [a - b for a, b in zip(line, signal)]


def awesome(h, l):
    hl2 = [(a + b) / 2 for a, b in zip(h, l)]
    return [None if a is None or b is None else a - b for a, b in zip(sma(hl2, 5), sma(hl2, 34))]


def bull_bear_power(h, l, c, n=13):
    e = ema(c, n)
    return [a - x + b - x for a, b, x in zip(h, l, e)]


def ultimate(h, l, c, a=7, b=14, d=28):
    bp, tr = [0.0], [0.0]
    for i in range(1, len(c)):
        lo, hi = min(l[i], c[i - 1]), max(h[i], c[i - 1])
        bp.append(c[i] - lo)
        tr.append(hi - lo)
    out = [None] * len(c)
    for i in range(d, len(c)):
        avg = lambda n: sum(bp[i - n + 1:i + 1]) / (sum(tr[i - n + 1:i + 1]) or 1)
        out[i] = 100 * (4 * avg(a) + 2 * avg(b) + avg(d)) / 7
    return out


def dmi(h, l, c, n=14):
    tr, pdm, mdm = [None], [None], [None]
    for i in range(1, len(c)):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
    atr_, ap, am = rma(tr, n), rma(pdm, n), rma(mdm, n)
    pdi = [None if not t else 100 * p / t for p, t in zip(ap, atr_)]
    mdi = [None if not t else 100 * m / t for m, t in zip(am, atr_)]
    dx = [None if p is None else (0.0 if p + m == 0 else 100 * abs(p - m) / (p + m)) for p, m in zip(pdi, mdi)]
    return rma(dx, n), pdi, mdi, atr_


def mfi(h, l, c, vol, n=14):
    tp = [(a + b + x) / 3 for a, b, x in zip(h, l, c)]
    out = [None] * len(c)
    for i in range(n, len(c)):
        pos = sum(tp[j] * vol[j] for j in range(i - n + 1, i + 1) if tp[j] > tp[j - 1])
        neg = sum(tp[j] * vol[j] for j in range(i - n + 1, i + 1) if tp[j] < tp[j - 1])
        out[i] = 100.0 if neg == 0 else 100 - 100 / (1 + pos / neg)
    return out


def cmf(h, l, c, vol, n=20):
    mfv = [0.0 if a == b else ((x - b) - (a - x)) / (a - b) * v for a, b, x, v in zip(h, l, c, vol)]
    out = [None] * len(c)
    for i in range(n - 1, len(c)):
        vs = sum(vol[i - n + 1:i + 1])
        out[i] = sum(mfv[i - n + 1:i + 1]) / vs if vs else 0.0
    return out


def obv(c, vol):
    out, acc = [0.0], 0.0
    for i in range(1, len(c)):
        acc += vol[i] if c[i] > c[i - 1] else -vol[i] if c[i] < c[i - 1] else 0.0
        out.append(acc)
    return out


# ---------- volatilidad / bandas ----------
def bollinger(c, n=20, k=2.0):
    mid = sma(c, n)
    up, lo = [None] * len(c), [None] * len(c)
    for i in range(n - 1, len(c)):
        sd = math.sqrt(sum((x - mid[i]) ** 2 for x in c[i - n + 1:i + 1]) / n)
        up[i], lo[i] = mid[i] + k * sd, mid[i] - k * sd
    return mid, up, lo


def keltner(h, l, c, n=20, k=2.0):
    mid = ema(c, n)
    _, _, _, a = dmi(h, l, c, 10)
    return mid, [None if x is None else m + k * x for m, x in zip(mid, a)], [None if x is None else m - k * x for m, x in zip(mid, a)]


def psar(h, l, step=0.02, mx=0.2):
    out = [None] * len(h)
    if len(h) < 2:
        return out
    up, af, ep, sar = h[1] > h[0], step, None, None
    sar, ep = (l[0], h[0]) if up else (h[0], l[0])
    for i in range(1, len(h)):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, l[i - 1], l[i - 2] if i > 1 else l[i - 1])
            if l[i] < sar:
                up, sar, ep, af = False, ep, l[i], step
            elif h[i] > ep:
                ep, af = h[i], min(af + step, mx)
        else:
            sar = max(sar, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > sar:
                up, sar, ep, af = True, ep, h[i], step
            elif l[i] < ep:
                ep, af = l[i], min(af + step, mx)
        out[i] = sar
    return out


def supertrend(h, l, c, n=10, k=3.0):
    _, _, _, a = dmi(h, l, c, n)
    line, direction = [None] * len(c), [None] * len(c)
    fu = fl = None
    trend = 1
    for i in range(len(c)):
        if a[i] is None:
            continue
        hl2 = (h[i] + l[i]) / 2
        bu, bl = hl2 + k * a[i], hl2 - k * a[i]
        fu = bu if fu is None or bu < fu or c[i - 1] > fu else fu
        fl = bl if fl is None or bl > fl or c[i - 1] < fl else fl
        if trend == 1 and c[i] < fl:
            trend = -1
        elif trend == -1 and c[i] > fu:
            trend = 1
        line[i], direction[i] = (fl if trend == 1 else fu), trend
    return line, direction


def ichimoku(h, l, tenkan=9, kijun=26, senkou=52):
    mid = lambda n: [None if i < n - 1 else (max(h[i - n + 1:i + 1]) + min(l[i - n + 1:i + 1])) / 2 for i in range(len(h))]
    t, k, sb = mid(tenkan), mid(kijun), mid(senkou)
    sa = [None if a is None or b is None else (a + b) / 2 for a, b in zip(t, k)]
    # la nube que se ve HOY se calculo hace 26 velas
    shift = lambda v: [None] * kijun + v[:-kijun] if len(v) > kijun else [None] * len(v)
    return t, k, shift(sa), shift(sb)


def vwap_session(ts, h, l, c, vol, day_ms=86_400_000):
    out, pv, vv, day = [], 0.0, 0.0, None
    for t, a, b, x, v in zip(ts, h, l, c, vol):
        if t // day_ms != day:
            pv, vv, day = 0.0, 0.0, t // day_ms
        pv += (a + b + x) / 3 * v
        vv += v
        out.append(pv / vv if vv else x)
    return out


# ---------- calificacion tipo TradingView ----------
COMPRA, VENTA, NEUTRAL = "compra", "venta", "neutral"


def _rising(v, i):
    return v[i] is not None and v[i - 1] is not None and v[i] > v[i - 1]


def calificar(bars):
    """Devuelve (filas de indicadores, resumen) para la ultima vela de bars [ts, o, h, l, c, v]."""
    ts = [b[0] for b in bars]
    h, l, c, vol = [b[2] for b in bars], [b[3] for b in bars], [b[4] for b in bars], [b[5] for b in bars]
    i = len(c) - 1
    px = c[i]
    rows = []

    def add(group, name, value, signal, detail="", rated=True):
        rows.append({"grupo": group, "indicador": name, "valor": None if value is None else round(value, 2),
                     "senal": signal, "detalle": detail, "vota": rated})

    # medias moviles: precio encima = compra
    for kind, fn in (("EMA", ema), ("SMA", sma)):
        for n in (10, 20, 30, 50, 100, 200):
            m = fn(c, n)[i]
            add("Medias móviles", f"{kind} {n}", m, NEUTRAL if m is None else COMPRA if px > m else VENTA)
    t, k, sa, sb = ichimoku(h, l)
    base = k[i]
    add("Medias móviles", "Ichimoku línea base (26)", base,
        NEUTRAL if base is None else COMPRA if px > base and t[i] > base else VENTA if px < base and t[i] < base else NEUTRAL)
    vw = vwma(c, vol, 20)[i]
    add("Medias móviles", "VWMA 20", vw, COMPRA if px > vw else VENTA)
    hm = hma(c, 9)[i]
    add("Medias móviles", "Hull MA 9", hm, NEUTRAL if hm is None else COMPRA if px > hm else VENTA)

    # osciladores, con las reglas de TradingView
    r = rsi(c)
    add("Osciladores", "RSI 14", r[i], COMPRA if r[i] < 30 and _rising(r, i) else VENTA if r[i] > 70 and not _rising(r, i) else NEUTRAL,
        "sobreventa" if r[i] < 30 else "sobrecompra" if r[i] > 70 else "zona media")
    sk, sd = stoch(h, l, c)
    add("Osciladores", "Estocástico %K (14,3,3)", sk[i],
        COMPRA if sk[i] < 20 and sk[i] > sd[i] else VENTA if sk[i] > 80 and sk[i] < sd[i] else NEUTRAL)
    cc = cci(h, l, c)
    add("Osciladores", "CCI 20", cc[i], COMPRA if cc[i] < -100 and _rising(cc, i) else VENTA if cc[i] > 100 and not _rising(cc, i) else NEUTRAL)
    adx, pdi, mdi, atr_ = dmi(h, l, c)
    add("Osciladores", "ADX 14", adx[i],
        COMPRA if adx[i] > 20 and pdi[i] > mdi[i] and _rising(adx, i) else VENTA if adx[i] > 20 and pdi[i] < mdi[i] and _rising(adx, i) else NEUTRAL,
        f"+DI {pdi[i]:.0f} / -DI {mdi[i]:.0f}" + (" (tendencia)" if adx[i] > 25 else " (lateral)"))
    ao = awesome(h, l)
    add("Osciladores", "Awesome Oscillator", ao[i], COMPRA if ao[i] > 0 and _rising(ao, i) else VENTA if ao[i] < 0 and not _rising(ao, i) else NEUTRAL)
    mo = momentum(c)
    add("Osciladores", "Momentum 10", mo[i], COMPRA if _rising(mo, i) else VENTA)
    ml, ms, mh = macd(c)
    add("Osciladores", "MACD (12,26)", ml[i], COMPRA if ml[i] > ms[i] else VENTA,
        f"histograma {'subiendo' if mh[i] > mh[i - 1] else 'bajando'}")
    srk, srd = stoch_rsi(c)
    add("Osciladores", "Stoch RSI (3,3,14,14)", srk[i],
        COMPRA if srk[i] is not None and srk[i] < 20 and srk[i] > srd[i] else VENTA if srk[i] is not None and srk[i] > 80 and srk[i] < srd[i] else NEUTRAL)
    wr = williams_r(h, l, c)
    add("Osciladores", "Williams %R 14", wr[i], COMPRA if wr[i] < -80 and _rising(wr, i) else VENTA if wr[i] > -20 and not _rising(wr, i) else NEUTRAL)
    bbp = bull_bear_power(h, l, c)
    add("Osciladores", "Bull Bear Power", bbp[i], COMPRA if bbp[i] > 0 and _rising(bbp, i) else VENTA if bbp[i] < 0 and not _rising(bbp, i) else NEUTRAL)
    uo = ultimate(h, l, c)
    add("Osciladores", "Ultimate Oscillator", uo[i], COMPRA if uo[i] > 70 else VENTA if uo[i] < 30 else NEUTRAL)

    # informativos (no votan): tendencia, volatilidad y volumen
    mid, up, lo = bollinger(c)
    pb = (px - lo[i]) / (up[i] - lo[i]) * 100 if up[i] != lo[i] else 50
    add("Volatilidad", "Bandas de Bollinger %B", pb, VENTA if pb > 100 else COMPRA if pb < 0 else NEUTRAL,
        f"ancho {_ar((up[i] - lo[i]) / mid[i] * 100, 2)}% del precio", rated=False)
    km, ku, kl = keltner(h, l, c)
    add("Volatilidad", "Canal de Keltner", km[i], COMPRA if px > ku[i] else VENTA if px < kl[i] else NEUTRAL,
        "fuera del canal" if px > ku[i] or px < kl[i] else "dentro del canal", rated=False)
    add("Volatilidad", "ATR 14", atr_[i], NEUTRAL, f"{_ar(atr_[i] / px * 100, 2)}% del precio por vela", rated=False)
    dh, dl = max(h[i - 19:i + 1]), min(l[i - 19:i + 1])
    add("Volatilidad", "Donchian 20", (dh + dl) / 2, COMPRA if px >= dh else VENTA if px <= dl else NEUTRAL,
        f"{_ar(dl)} - {_ar(dh)}", rated=False)
    sar = psar(h, l)
    add("Tendencia", "Parabolic SAR", sar[i], COMPRA if px > sar[i] else VENTA, "puntos debajo del precio" if px > sar[i] else "puntos encima del precio", rated=False)
    st, sdir = supertrend(h, l, c)
    add("Tendencia", "SuperTrend (10,3)", st[i], COMPRA if sdir[i] == 1 else VENTA, "", rated=False)
    cloud_top, cloud_bot = max(sa[i] or px, sb[i] or px), min(sa[i] or px, sb[i] or px)
    add("Tendencia", "Nube de Ichimoku", (cloud_top + cloud_bot) / 2,
        COMPRA if px > cloud_top else VENTA if px < cloud_bot else NEUTRAL,
        "precio encima de la nube" if px > cloud_top else "precio debajo de la nube" if px < cloud_bot else "precio dentro de la nube", rated=False)
    vw_s = vwap_session(ts, h, l, c, vol)[i]
    add("Volumen", "VWAP del dia", vw_s, COMPRA if px > vw_s else VENTA, "precio sobre el promedio ponderado del día" if px > vw_s else "precio bajo el promedio ponderado del día", rated=False)
    ob = obv(c, vol)
    ob_ema = ema(ob, 20)
    add("Volumen", "OBV", ob[i], COMPRA if ob[i] > ob_ema[i] else VENTA, "volumen acompaña" if (ob[i] > ob_ema[i]) == (px > c[i - 20]) else "volumen no acompaña", rated=False)
    mf = mfi(h, l, c, vol)
    add("Volumen", "MFI 14", mf[i], COMPRA if mf[i] < 20 else VENTA if mf[i] > 80 else NEUTRAL, "", rated=False)
    cm = cmf(h, l, c, vol)
    add("Volumen", "Chaikin Money Flow 20", cm[i], COMPRA if cm[i] > 0.05 else VENTA if cm[i] < -0.05 else NEUTRAL,
        "entra dinero" if cm[i] > 0 else "sale dinero", rated=False)
    vrel = vol[i] / (sum(vol[i - 20:i]) / 20 or 1)
    add("Volumen", "Volumen relativo", vrel, NEUTRAL, f"x{_ar(vrel, 1)} del promedio de 20 velas", rated=False)
    div = divergencia(c, r, i)
    if div:
        add("Osciladores", "Divergencia RSI", None, COMPRA if div == "alcista" else VENTA, f"divergencia {div} en las últimas 30 velas", rated=False)

    def score(group):
        g = [x for x in rows if x["grupo"] == group and x["vota"]]
        b = sum(x["senal"] == COMPRA for x in g)
        s = sum(x["senal"] == VENTA for x in g)
        return (b - s) / len(g), b, s, len(g) - b - s

    ma, osc = score("Medias móviles"), score("Osciladores")
    total = (ma[0] + osc[0]) / 2
    resumen = {"rating": round(total, 3), "rating_txt": rating_txt(total),
               "ma_rating": round(ma[0], 3), "ma_compra": ma[1], "ma_venta": ma[2], "ma_neutral": ma[3],
               "osc_rating": round(osc[0], 3), "osc_compra": osc[1], "osc_venta": osc[2], "osc_neutral": osc[3],
               "rsi": round(r[i], 1), "adx": round(adx[i], 1), "atr_pct": round(atr_[i] / px * 100, 3),
               "vol_rel": round(vrel, 2), "macd_sube": mh[i] > mh[i - 1]}
    overlays = {"ema20": ema(c, 20), "ema50": ema(c, 50), "bb_up": up, "bb_lo": lo}
    return rows, resumen, overlays


def rating_txt(x):
    # TradingView dice "compra/venta"; aca "alcista/bajista" para que no se lea como una orden
    return ("Bajista fuerte" if x <= -0.5 else "Bajista" if x < -0.1 else "Neutral" if x <= 0.1
            else "Alcista" if x < 0.5 else "Alcista fuerte")


def divergencia(c, r, i, n=30):
    """Divergencia simple: el precio hace un extremo nuevo y el RSI no lo confirma."""
    if i < n or r[i - n] is None:
        return None
    win_c, win_r = c[i - n:i - 3], r[i - n:i - 3]
    if c[i] > max(win_c) and r[i] < max(win_r):
        return "bajista"
    if c[i] < min(win_c) and r[i] > min(win_r):
        return "alcista"
    return None


def fvg(bars, lookback=200, keep=6):
    """Fair Value Gaps sin llenar: hueco entre la vela k-2 y la k que la vela k-1 dejo sin operar."""
    h, l = [b[2] for b in bars], [b[3] for b in bars]
    px, start = bars[-1][4], max(2, len(bars) - lookback)
    zones = []
    for k in range(start, len(bars)):
        if l[k] > h[k - 2]:
            zones.append({"tipo": "alcista", "t": bars[k - 1][0], "bajo": h[k - 2], "alto": l[k], "k": k})
        elif h[k] < l[k - 2]:
            zones.append({"tipo": "bajista", "t": bars[k - 1][0], "bajo": h[k], "alto": l[k - 2], "k": k})
    open_zones = []
    for z in zones:
        later = range(z["k"] + 1, len(bars))
        if z["tipo"] == "alcista":
            low = min((l[j] for j in later), default=z["alto"])
            if low <= z["bajo"]:
                continue  # el precio ya volvio y lleno el hueco
            z["alto"] = min(z["alto"], low)  # parte ya cubierta
        else:
            high = max((h[j] for j in later), default=z["bajo"])
            if high >= z["alto"]:
                continue
            z["bajo"] = max(z["bajo"], high)
        if z["alto"] > z["bajo"]:
            open_zones.append(z)
    open_zones.sort(key=lambda z: abs((z["alto"] + z["bajo"]) / 2 - px))
    return [{k: v for k, v in z.items() if k != "k"} for z in open_zones[:keep]]


def zigzag(bars, atr_mult=2.5):
    """Giros del precio: un nuevo pivote cuando se revierte mas de atr_mult * ATR desde el ultimo extremo."""
    h, l, c = [b[2] for b in bars], [b[3] for b in bars], [b[4] for b in bars]
    _, _, _, atr_ = dmi(h, l, c)
    pivots, direction, ext_i, hi_i, lo_i = [], 0, 0, 0, 0
    for i in range(1, len(bars)):
        a = atr_[i] or (h[i] - l[i])
        if direction == 0:                      # todavia sin tendencia: esperar el primer movimiento grande
            hi_i = i if h[i] > h[hi_i] else hi_i
            lo_i = i if l[i] < l[lo_i] else lo_i
            if h[hi_i] - l[lo_i] > atr_mult * a:
                if hi_i > lo_i:
                    pivots.append(("bajo", lo_i, l[lo_i]))
                    direction, ext_i = 1, hi_i
                else:
                    pivots.append(("alto", hi_i, h[hi_i]))
                    direction, ext_i = -1, lo_i
        elif direction == 1:
            if h[i] >= h[ext_i]:
                ext_i = i
            elif h[ext_i] - l[i] > atr_mult * a:
                pivots.append(("alto", ext_i, h[ext_i]))
                direction, ext_i = -1, i
        else:
            if l[i] <= l[ext_i]:
                ext_i = i
            elif h[i] - l[ext_i] > atr_mult * a:
                pivots.append(("bajo", ext_i, l[ext_i]))
                direction, ext_i = 1, i
    # el extremo del tramo en curso, todavia sin confirmar
    if direction:
        pivots.append(("alto" if direction == 1 else "bajo", ext_i, h[ext_i] if direction == 1 else l[ext_i]))
    return pivots


def elliott(pivots):
    """Busca un conteo de Elliott que cumpla las reglas sobre los ultimos pivotes.

    Reglas de impulso: la onda 2 no pasa el inicio de la 1, la 3 no es la mas corta de 1/3/5 y la 4 no
    se superpone con la 1. Correccion ABC: B no supera el inicio de A. El ultimo pivote es el tramo en
    curso. Devuelve (etiquetas por pivote, descripcion, objetivo o None).
    """
    p = [x[2] for x in pivots]

    def impulse(pts, up):
        s = 1 if up else -1
        w = [s * (pts[k + 1] - pts[k]) for k in range(len(pts) - 1)]
        if any(x <= 0 for x in w[0::2]) or any(x >= 0 for x in w[1::2]):
            return False
        if len(pts) > 2 and s * (pts[2] - pts[0]) <= 0:
            return False                                   # onda 2 pasa el inicio de la 1
        if len(pts) > 4 and s * (pts[4] - pts[1]) <= 0:
            return False                                   # onda 4 se superpone con la 1
        if len(w) >= 5 and w[2] < min(w[0], w[4]):
            return False                                   # onda 3 la mas corta
        return True

    for n, names in ((6, ["0", "1", "2", "3", "4", "5"]), (5, ["0", "1", "2", "3", "4"])):
        if len(p) >= n:
            pts = p[-n:]
            for up in (True, False):
                if impulse(pts, up):
                    sentido = "alcista" if up else "bajista"
                    if n == 6:
                        return names, f"Impulso {sentido} de 5 ondas posiblemente completo: suele seguir una corrección ABC", None
                    target = pts[4] + (pts[1] - pts[0])           # onda 5 = onda 1, la proporcion mas comun
                    return names, f"Posible onda 5 {sentido} en curso", target
    for n, names in ((4, ["0", "A", "B", "C"]), (3, ["0", "A", "B"])):
        if len(p) >= n:
            pts = p[-n:]
            a = pts[1] - pts[0]
            if a and (pts[2] - pts[1]) * a < 0 and abs(pts[2] - pts[1]) < abs(a):
                sentido = "bajista" if a < 0 else "alcista"
                if n == 4 and (pts[3] - pts[2]) * a > 0:
                    return names, f"Corrección ABC {sentido} posiblemente completa", None
                if n == 3:
                    return names, f"Posible onda C {sentido} en curso", pts[2] + a     # C = A
    return [], "Sin conteo de Elliott claro: el precio no cumple las reglas en los últimos giros", None


def mapa_liquidaciones(price_by_hour, oi_hist, ls_hist, after_extremes, lev_weights=None, band=0.12, step=0.0025):
    """Estimacion de donde quedan liquidaciones pendientes (mismo enfoque que los heatmaps publicos).

    price_by_hour: {ts: precio}; oi_hist: [(ts, oi_usd)]; ls_hist: {ts: ratio long/short de cuentas};
    after_extremes(ts) -> (minimo, maximo) del precio despues de ts, para descartar lo ya liquidado.
    """
    lev_weights = lev_weights or {10: 0.3, 25: 0.3, 50: 0.25, 100: 0.15}
    ref = list(price_by_hour.values())[-1]
    lo_edge, n_bins = ref * (1 - band), int(2 * band / step)
    longs, shorts = [0.0] * n_bins, [0.0] * n_bins
    for (t0, oi0), (t1, oi1) in zip(oi_hist, oi_hist[1:]):
        new = oi1 - oi0
        entry = price_by_hour.get(t1)
        if new <= 0 or entry is None:
            continue
        r = ls_hist.get(t1, 1.0)
        share_long = r / (1 + r)
        low, high = after_extremes(t1)
        for lev, w in lev_weights.items():
            for side, size, liq in (("long", new * share_long * w, entry * (1 - 1 / lev + 0.004)),
                                    ("short", new * (1 - share_long) * w, entry * (1 + 1 / lev - 0.004))):
                if (side == "long" and low <= liq) or (side == "short" and high >= liq):
                    continue  # el precio ya paso por ahi: esa liquidacion ocurrio
                k = int((liq - lo_edge) / (ref * step))
                if 0 <= k < n_bins:
                    (longs if side == "long" else shorts)[k] += size
    return [{"precio": round(lo_edge + (k + 0.5) * ref * step, 1), "longs": round(longs[k] / 1e6, 2),
             "shorts": round(shorts[k] / 1e6, 2)} for k in range(n_bins) if longs[k] or shorts[k]]


def patrones_velas(o, h, l, c, atr_, trend, i):
    """Patrones de velas japonesas que terminan en la vela i, del mas fuerte al mas debil: [(nombre, sesgo)]."""
    if i < 3 or atr_[i] is None:
        return []
    body = lambda k: abs(c[k] - o[k])
    rng = lambda k: (h[k] - l[k]) or 1e-9
    green = lambda k: c[k] > o[k]
    red = lambda k: c[k] < o[k]
    big = lambda k: body(k) > 0.6 * rng(k) and rng(k) > 0.6 * atr_[i]
    up = trend[i - 1] is not None and c[i - 1] > trend[i - 1]
    out = []
    if all(green(k) and body(k) > 0.5 * rng(k) for k in (i - 2, i - 1, i)) and c[i] > c[i - 1] > c[i - 2] and body(i) > 0.4 * atr_[i]:
        out.append(("Tres soldados blancos", "alcista"))
    if all(red(k) and body(k) > 0.5 * rng(k) for k in (i - 2, i - 1, i)) and c[i] < c[i - 1] < c[i - 2] and body(i) > 0.4 * atr_[i]:
        out.append(("Tres cuervos negros", "bajista"))
    if red(i - 2) and big(i - 2) and body(i - 1) < 0.3 * body(i - 2) and green(i) and c[i] > (o[i - 2] + c[i - 2]) / 2:
        out.append(("Estrella de la mañana", "alcista"))
    if green(i - 2) and big(i - 2) and body(i - 1) < 0.3 * body(i - 2) and red(i) and c[i] < (o[i - 2] + c[i - 2]) / 2:
        out.append(("Estrella vespertina", "bajista"))
    if red(i - 1) and green(i) and c[i] >= o[i - 1] and o[i] <= c[i - 1] and body(i) > body(i - 1) and body(i) > 0.5 * atr_[i]:
        out.append(("Envolvente alcista", "alcista"))
    if green(i - 1) and red(i) and c[i] <= o[i - 1] and o[i] >= c[i - 1] and body(i) > body(i - 1) and body(i) > 0.5 * atr_[i]:
        out.append(("Envolvente bajista", "bajista"))
    if big(i - 1) and body(i) < 0.5 * body(i - 1) and max(o[i], c[i]) < max(o[i - 1], c[i - 1]) and min(o[i], c[i]) > min(o[i - 1], c[i - 1]):
        out.append(("Harami alcista", "alcista") if red(i - 1) else ("Harami bajista", "bajista"))
    if rng(i) > 0.7 * atr_[i]:
        b, lw, uw = body(i), min(o[i], c[i]) - l[i], h[i] - max(o[i], c[i])
        if b <= 0.1 * rng(i):
            out.append(("Doji", "neutral"))
        elif lw >= 2 * b and uw <= 0.6 * b:
            out.append(("Hombre colgado", "bajista") if up else ("Martillo", "alcista"))
        elif uw >= 2 * b and lw <= 0.6 * b:
            out.append(("Estrella fugaz", "bajista") if up else ("Martillo invertido", "alcista"))
    return out


def estadistica_velas(o, h, l, c, atr_, trend, horizon, start=30):
    """Para cada patron: en cuantos casos del historial el precio fue hacia donde dice el patron en `horizon` velas."""
    stats = {}
    for i in range(start, len(c) - horizon):
        for name, bias in patrones_velas(o, h, l, c, atr_, trend, i):
            if bias == "neutral":
                continue
            ret = c[i + horizon] / c[i] - 1
            n, ok = stats.get(name, (0, 0))
            stats[name] = (n + 1, ok + ((ret > 0) == (bias == "alcista")))
    return stats


def patron_grafico(bars, pivots, atr_last):
    """Busca figuras clasicas sobre los giros confirmados. Devuelve un dict o None.

    Lineas en formato (t, precio, pendiente por milisegundo, nombre) para dibujarlas extendidas, y los
    puntos de la figura como (t, precio, nombre), para marcarlos sobre las velas.
    """
    P = pivots[:-1]                     # el ultimo giro todavia no esta confirmado
    if len(P) < 4:
        return None
    i_last, px = len(bars) - 1, bars[-1][4]
    if P[-1][1] < i_last - 80:
        return None                     # sin giros recientes: ninguna figura vigente
    t = lambda k: bars[k][0]
    tol = 0.8 * atr_last
    line = lambda a, b, name: (t(a[1]), a[2], (b[2] - a[2]) / ((t(b[1]) - t(a[1])) or 1), name)
    flat_line = lambda a, name: (t(a[1]), a[2], 0.0, name)
    at_now = lambda ln: ln[1] + ln[2] * (t(i_last) - ln[0])
    point = lambda p, name: (t(p[1]), p[2], name)
    highs = [p for p in P if p[0] == "alto"]
    lows = [p for p in P if p[0] == "bajo"]

    def result(name, bias, lines, points, target, desc, broke):
        return {"nombre": name, "sesgo": bias, "estado": "confirmado" if broke else "en formación",
                "objetivo": None if target is None else round(target, 1), "descripcion": desc,
                "lineas": lines, "puntos": points}

    def still_valid(last_point, bias, extreme, neck_at):
        """Una figura se anula si despues el precio paso su extremo (en contra) o si ya confirmo y volvio."""
        after = range(last_point[1] + 1, len(bars))
        if bias == "alcista":
            if any(bars[j][3] < extreme - tol for j in after):
                return False
            fired = any(bars[j][4] > neck_at(j) for j in after)
            return not fired or px > neck_at(i_last)
        if any(bars[j][2] > extreme + tol for j in after):
            return False
        fired = any(bars[j][4] < neck_at(j) for j in after)
        return not fired or px < neck_at(i_last)

    # hombro-cabeza-hombro (y su inverso) sobre los ultimos 5 giros
    q = P[-5:]
    if len(q) == 5:
        k = [p[2] for p in q]
        shoulders = [point(q[0], "Hombro"), point(q[2], "Cabeza"), point(q[4], "Hombro")]
        neck_line = line(q[1], q[3], "Cuello")
        neck_at = lambda j: neck_line[1] + neck_line[2] * (t(j) - neck_line[0])
        if (q[0][0] == "alto" and k[2] > k[0] + tol and k[2] > k[4] + tol and abs(k[0] - k[4]) < 1.5 * tol
                and still_valid(q[4], "bajista", k[2], neck_at)):
            neck = line(q[1], q[3], "Cuello")
            n_now = at_now(neck)
            target, broke = n_now - (k[2] - (k[1] + k[3]) / 2), px < n_now
            desc = (f"Tres máximos, el del medio más alto. BTC perdió el cuello en {_ar(n_now)}: objetivo {_ar(target)}." if broke
                    else f"Tres máximos, el del medio más alto. Si BTC cierra debajo del cuello ({_ar(n_now)}), "
                         f"se confirma y el objetivo es {_ar(target)}.")
            return result("Hombro-cabeza-hombro", "bajista", [neck], shoulders, target, desc, broke)
        if (q[0][0] == "bajo" and k[2] < k[0] - tol and k[2] < k[4] - tol and abs(k[0] - k[4]) < 1.5 * tol
                and still_valid(q[4], "alcista", k[2], neck_at)):
            neck = line(q[1], q[3], "Cuello")
            n_now = at_now(neck)
            target, broke = n_now + ((k[1] + k[3]) / 2 - k[2]), px > n_now
            desc = (f"Tres mínimos, el del medio más bajo. BTC superó el cuello en {_ar(n_now)}: objetivo {_ar(target)}." if broke
                    else f"Tres mínimos, el del medio más bajo. Si BTC cierra arriba del cuello ({_ar(n_now)}), "
                         f"se confirma y el objetivo es {_ar(target)}.")
            return result("Hombro-cabeza-hombro invertido", "alcista", [neck], shoulders, target, desc, broke)
    # doble techo / doble piso: dos extremos parecidos y el cuello en el giro del medio
    if len(highs) >= 2 and highs[-1][1] > highs[-2][1]:
        a, b = highs[-2], highs[-1]
        mid = [p for p in lows if a[1] < p[1] < b[1]]
        if (mid and abs(a[2] - b[2]) < tol and min(a[2], b[2]) - mid[0][2] > 2 * tol and P[-1][1] >= b[1]
                and still_valid(b, "bajista", max(a[2], b[2]), lambda j: mid[0][2])):
            neck, top = mid[0][2], (a[2] + b[2]) / 2
            target, broke = neck - (top - neck), px < neck
            desc = (f"Dos máximos parecidos cerca de {_ar(top)}. BTC perdió el cuello en {_ar(neck)}: objetivo {_ar(target)}." if broke
                    else f"Dos máximos parecidos cerca de {_ar(top)}. Si BTC cierra debajo del cuello ({_ar(neck)}), "
                         f"se confirma y el objetivo es {_ar(target)}.")
            return result("Doble techo", "bajista", [flat_line(mid[0], "Cuello")],
                          [point(a, "Techo 1"), point(b, "Techo 2")], target, desc, broke)
    if len(lows) >= 2 and lows[-1][1] > lows[-2][1]:
        a, b = lows[-2], lows[-1]
        mid = [p for p in highs if a[1] < p[1] < b[1]]
        if (mid and abs(a[2] - b[2]) < tol and mid[0][2] - max(a[2], b[2]) > 2 * tol and P[-1][1] >= b[1]
                and still_valid(b, "alcista", min(a[2], b[2]), lambda j: mid[0][2])):
            neck, bot = mid[0][2], (a[2] + b[2]) / 2
            target, broke = neck + (neck - bot), px > neck
            desc = (f"Dos mínimos parecidos cerca de {_ar(bot)}. BTC superó el cuello en {_ar(neck)}: objetivo {_ar(target)}." if broke
                    else f"Dos mínimos parecidos cerca de {_ar(bot)}. Si BTC cierra arriba del cuello ({_ar(neck)}), "
                         f"se confirma y el objetivo es {_ar(target)}.")
            return result("Doble piso", "alcista", [flat_line(mid[0], "Cuello")],
                          [point(a, "Piso 1"), point(b, "Piso 2")], target, desc, broke)
    # triangulos, cunas y canales con los dos ultimos maximos y minimos
    if len(highs) >= 2 and len(lows) >= 2:
        h1, h2, l1, l2 = highs[-2], highs[-1], lows[-2], lows[-1]
        up_l, lo_l = line(h1, h2, "Techo"), line(l1, l2, "Piso")
        bar_ms = bars[-1][0] - bars[-2][0]
        su, sl = up_l[2] * bar_ms * 20 / px, lo_l[2] * bar_ms * 20 / px     # pendiente en 20 velas, en fraccion del precio
        flat = 0.003
        u_now, l_now = at_now(up_l), at_now(lo_l)
        start = min(h1[1], l1[1])
        width0 = (up_l[1] + up_l[2] * (t(start) - up_l[0])) - (lo_l[1] + lo_l[2] * (t(start) - lo_l[0]))
        width = u_now - l_now
        if width <= 0:
            return None
        converging = width < width0 * 0.85
        if abs(su) < flat and sl > flat:
            name, bias = "Triángulo ascendente", "alcista"
        elif abs(sl) < flat and su < -flat:
            name, bias = "Triángulo descendente", "bajista"
        elif su < -flat and sl > flat:
            name, bias = "Triángulo simétrico", "neutral"
        elif su > flat and sl > flat and converging:
            name, bias = "Cuña ascendente", "bajista"
        elif su < -flat and sl < -flat and converging:
            name, bias = "Cuña descendente", "alcista"
        elif su > flat and sl > flat:
            name, bias = "Canal alcista", "alcista"
        elif su < -flat and sl < -flat:
            name, bias = "Canal bajista", "bajista"
        else:
            name, bias = "Rango lateral", "neutral"
        height = max(width0, width)
        art = "una" if name.startswith("Cuña") else "un"
        val = lambda ln, j: ln[1] + ln[2] * (t(j) - ln[0])
        recent = range(max(0, i_last - 20), i_last)
        if px > u_now + tol:
            if not any(bars[j][4] <= val(up_l, j) for j in recent):
                return None             # la ruptura fue hace mucho: la figura ya no esta vigente
            target = u_now + height
            return result(f"Ruptura alcista de {name.lower()}", "alcista", [up_l, lo_l], [], target,
                          f"BTC rompió hacia arriba el techo de {art} {name.lower()} en {_ar(u_now)}: "
                          f"el objetivo de la ruptura es {_ar(target)}.", True)
        if px < l_now - tol:
            if not any(bars[j][4] >= val(lo_l, j) for j in recent):
                return None
            target = l_now - height
            return result(f"Ruptura bajista de {name.lower()}", "bajista", [up_l, lo_l], [], target,
                          f"BTC rompió hacia abajo el piso de {art} {name.lower()} en {_ar(l_now)}: "
                          f"el objetivo de la ruptura es {_ar(target)}.", True)
        target = u_now + height if bias == "alcista" else l_now - height if bias == "bajista" else None
        if bias == "alcista":
            side = f"suele romper hacia arriba; si supera {_ar(u_now)}, el objetivo es {_ar(target)}"
        elif bias == "bajista":
            side = f"suele romper hacia abajo; si pierde {_ar(l_now)}, el objetivo es {_ar(target)}"
        else:
            side = "puede romper para cualquier lado: la dirección la da la ruptura"
        return result(name, bias, [up_l, lo_l], [], target,
                      f"BTC se mueve entre un piso en {_ar(l_now)} y un techo en {_ar(u_now)}; {side}.", False)
    return None


def divergencias(bars, pivots, max_age=40, min_gap=5):
    """Divergencias clasicas en RSI y MACD sobre los dos ultimos giros del precio del mismo tipo.

    Bajista: el precio hace un maximo mas alto y el indicador uno mas bajo. Alcista: el precio hace un
    minimo mas bajo y el indicador uno mas alto. Solo cuentan si el ultimo giro es reciente.
    """
    c = [b[4] for b in bars]
    series = {"RSI": rsi(c), "MACD": macd(c)[0]}
    last = len(bars) - 1
    out = []
    for kind in ("alto", "bajo"):
        pts = [p for p in pivots if p[0] == kind]
        if len(pts) < 2:
            continue
        a, b = pts[-2], pts[-1]
        if last - b[1] > max_age or b[1] - a[1] < min_gap:
            continue
        for name, ser in series.items():
            va, vb = ser[a[1]], ser[b[1]]
            # una diferencia minima en el indicador no es divergencia: es ruido
            if va is None or vb is None or abs(vb - va) < (2 if name == "RSI" else 0.05 * abs(va)):
                continue
            if kind == "alto" and b[2] > a[2] and vb < va:
                tipo = "bajista"
            elif kind == "bajo" and b[2] < a[2] and vb > va:
                tipo = "alcista"
            else:
                continue
            out.append({"indicador": name, "tipo": tipo, "t1": bars[a[1]][0], "p1": a[2], "t2": bars[b[1]][0], "p2": b[2],
                        "v1": round(va, 2), "v2": round(vb, 2)})
    return out


def pivotes(prev_day):
    """Pivotes clasicos a partir de la vela diaria anterior [ts, o, h, l, c, v]."""
    _, _, h, l, c, _ = prev_day
    p = (h + l + c) / 3
    return {"P": p, "R1": 2 * p - l, "S1": 2 * p - h, "R2": p + (h - l), "S2": p - (h - l),
            "R3": h + 2 * (p - l), "S3": l - 2 * (h - p)}
