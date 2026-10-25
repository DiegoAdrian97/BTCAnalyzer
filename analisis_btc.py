"""
Analisis de mercado de BTC/USDT perpetuo, de 5 minutos a diario (APIs publicas, sin keys).

Uso:
    .venv\\Scripts\\python.exe analisis_btc.py                 # analiza, imprime y guarda data/analisis_btc.json
    .venv\\Scripts\\python.exe analisis_btc.py --abrir         # ademas abre el dashboard local (reporte_btc.html)
    .venv\\Scripts\\python.exe analisis_btc.py --nota nota.txt # agrega la lectura de noticias al ultimo analisis

Fuentes:
- Binance Futures: velas (mas historia y menos limites que BingX), open interest, flujo de
  compras/ventas agresivas y ratio long/short.
- BingX: precio, funding y libro de ordenes del perpetuo donde operas.

Que calcula, por temporalidad (5m, 15m, 30m, 1h, 4h, 1d):
1. Calificacion tipo TradingView: ~20 medias y osciladores votan compra/venta/neutral, mas
   indicadores de tendencia, volatilidad y volumen que se muestran sin votar (indicadores.py).
2. Probabilidades: de las velas recientes en una situacion tecnica parecida a la actual, que
   porcentaje termino mas arriba, contra la tasa base del mismo periodo.
3. Escenarios: el camino tipico, uno alcista y uno bajista, tomados de caminos REALES de esas
   situaciones parecidas (escalados al precio de hoy), y el rango donde termino el 80%.
Ademas: contexto actual (open interest, flujo, posicionamiento, libro, funding), niveles clave
y aciertos de los pronosticos anteriores (data/predicciones_btc.csv).

No es una recomendacion de inversion.
"""

import argparse
import csv
import json
import os
from datetime import datetime, timedelta, timezone

import ccxt

import backtest_grid as bg
import indicadores as ind

SYMBOL = "BTC/USDT:USDT"
DATA_DIR = bg.DATA_DIR
LOG_FILE = os.path.join(DATA_DIR, "predicciones_btc.csv")
OUT_FILE = os.path.join(DATA_DIR, "analisis_btc.json")
LOCAL_TZ = timezone(timedelta(hours=-3))     # Argentina, sin horario de verano
MIN_SAMPLES = 40
CHART_BARS = 60
SCENARIO_STEPS = 12
# temporalidad: (dias de historia, horizontes de probabilidad en velas)
TIMEFRAMES = {"5m": (30, (3, 12)), "15m": (90, (4, 16)), "30m": (180, (4, 16)),
              "1h": (365, (4, 24)), "4h": (730, (3, 6)), "1d": (1500, (3, 7))}


# ---------- datos ----------
def update_candles(ex, tf, days):
    """Velas cerradas de Binance Futures con cache incremental en data/."""
    path = os.path.join(DATA_DIR, f"BTC_USDT_binance_perp_{tf}.csv")
    tf_ms = ex.parse_timeframe(tf) * 1000
    candles = []
    if os.path.exists(path):
        with open(path) as f:
            candles = [[int(r[0])] + [float(x) for x in r[1:]] for r in csv.reader(f)]
    now = ex.milliseconds()
    since = candles[-1][0] + tf_ms if candles else now - days * 86_400_000
    while since + tf_ms <= now:
        batch = bg._retry(ex.fetch_ohlcv, SYMBOL, tf, since=since, limit=1500)
        batch = [c for c in batch if c[0] >= since and c[0] + tf_ms <= now]
        if not batch:
            break
        candles += batch
        since = candles[-1][0] + tf_ms
    candles = [c for c in candles if c[0] >= now - days * 86_400_000]
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows(candles)
    return candles


def ar(x, d=0):
    """Numero con formato argentino: 80.757,25"""
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def arp(x, d=1):
    return ("+" if x > 0 else "") + ar(x, d) + "%"


def pct(a, b):
    return (a / b - 1) * 100


def trend_word(c, e20, e50, e200):
    if c > e20 > e50 > e200:
        return "Alcista fuerte"
    if c < e20 < e50 < e200:
        return "Bajista fuerte"
    if c > e200:
        return "Alcista con dudas" if c < e50 else "Alcista"
    return "Bajista con rebote" if c > e50 else "Bajista"


def label(minutes):
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 1440:
        return f"{minutes // 60} h"
    return f"{minutes // 1440} d"


# ---------- situaciones parecidas ----------
def states(closes, rsi, e50, e200, lookback):
    out = []
    for i, (c, r) in enumerate(zip(closes, rsi)):
        if r is None or i < lookback:
            out.append(None)
            continue
        move = c / closes[i - lookback] - 1
        out.append((c > e50[i], c > e200[i], 0 if r < 35 else 1 if r < 50 else 2 if r < 65 else 3,
                    0 if move < -0.02 else 1 if move <= 0.02 else 2))
    return out


def similar(st, last, warmup):
    now = st[-1]
    idxs, keep = [], 0
    for keep in (4, 3, 2, 1):
        idxs = [j for j in range(warmup, last) if st[j] and st[j][:keep] == now[:keep]]
        if len(idxs) >= MIN_SAMPLES:
            break
    return idxs, keep


def outcomes(closes, idxs, h):
    rets = sorted(closes[i + h] / closes[i] - 1 for i in idxs if i + h < len(closes))
    if not rets:
        return None
    q = lambda p: rets[min(int(p * len(rets)), len(rets) - 1)] * 100
    return {"n": len(rets), "up": sum(r > 0 for r in rets) / len(rets) * 100, "p10": q(0.1), "p90": q(0.9)}


def scenarios(bars, idxs, price, tf_ms):
    """Camino tipico/alcista/bajista: el camino real mas parecido a la mediana y a los percentiles 75/25."""
    closes = [b[4] for b in bars]
    usable = [j for j in idxs if j + SCENARIO_STEPS < len(bars)]
    if len(usable) < 10:
        return [], []
    paths = {j: [closes[j + k] / closes[j] - 1 for k in range(1, SCENARIO_STEPS + 1)] for j in usable}
    cols = [sorted(p[k] for p in paths.values()) for k in range(SCENARIO_STEPS)]
    q = lambda p: [col[min(int(p * len(col)), len(col) - 1)] for col in cols]
    targets = {"tipico": q(0.5), "alcista": q(0.75), "bajista": q(0.25)}
    t0 = bars[-1][0]
    candles, cone = [], []
    for name, target in targets.items():
        j = min(paths, key=lambda j: sum(abs(a - b) for a, b in zip(paths[j], target)))
        base = closes[j]
        for k in range(1, SCENARIO_STEPS + 1):
            _, o, h, l, c, _ = bars[j + k]
            s = price / base
            candles.append({"tabla": "escenario", "tf": None, "escenario": name, "paso": k, "t": t0 + k * tf_ms,
                            "o": round(o * s, 1), "h": round(h * s, 1), "l": round(l * s, 1), "c": round(c * s, 1),
                            "desde": datetime.fromtimestamp(bars[j][0] / 1000, timezone.utc).strftime("%Y-%m-%d")})
    p10, p50, p90 = q(0.1), q(0.5), q(0.9)
    for k in range(SCENARIO_STEPS):
        cone.append({"tabla": "cono", "tf": None, "paso": k + 1, "t": t0 + (k + 1) * tf_ms,
                     "p10": round(price * (1 + p10[k]), 1), "p50": round(price * (1 + p50[k]), 1),
                     "p90": round(price * (1 + p90[k]), 1)})
    return candles, cone


NICE_STEPS = (25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)


def targets(bars, idxs, price, h, when):
    """Probabilidad de TOCAR precios redondos antes de 'when', y precio mas probable a esa hora.

    Para cada situacion parecida se mira el maximo y el minimo que alcanzo el precio en las h velas
    siguientes: la probabilidad de tocar un nivel es la fraccion de casos que llegaron a el.
    """
    usable = [j for j in idxs if j + h < len(bars)]
    if len(usable) < 10:
        return [], None
    c = [b[4] for b in bars]
    highs = [max(b[2] for b in bars[j + 1:j + h + 1]) / c[j] - 1 for j in usable]
    lows = [min(b[3] for b in bars[j + 1:j + h + 1]) / c[j] - 1 for j in usable]
    ends = sorted(c[j + h] / c[j] - 1 for j in usable)
    q = lambda p: ends[min(int(p * len(ends)), len(ends) - 1)]
    spread = (q(0.9) - q(0.1)) * price
    unit = min(NICE_STEPS, key=lambda s: abs(s - spread / 4))
    rows = []
    # el primer nivel de cada lado queda al menos a medio escalon: uno pegado al precio se toca siempre
    first_up = (int((price + unit / 2) // unit) + 1) * unit
    first_dn = int((price - unit / 2) // unit) * unit
    for k in range(4):
        for side, level in (("arriba", first_up + k * unit), ("abajo", first_dn - k * unit)):
            rel = level / price - 1
            hits = sum(x >= rel for x in highs) if side == "arriba" else sum(x <= rel for x in lows)
            rows.append({"precio": level, "lado": side, "prob": round(hits / len(usable) * 100, 1)})
    close = {"mediana": round(price * (1 + q(0.5)), 1), "p25": round(price * (1 + q(0.25)), 1),
             "p75": round(price * (1 + q(0.75)), 1), "hora": when}
    return rows, close


# ---------- contexto actual ----------
def context(bnc, bgx, closes_1h):
    rows = []

    def add(key, title, value, signal, detail):
        rows.append({"tabla": "contexto", "clave": key, "titulo": title, "valor": value, "senal": signal, "detalle": detail})

    oi = [x["openInterestValue"] for x in bg._retry(bnc.fetch_open_interest_history, SYMBOL, "1h", limit=25)]
    for hrs in (1, 4, 24):
        d_oi, d_px = pct(oi[-1], oi[-1 - hrs]), pct(closes_1h[-1], closes_1h[-1 - hrs])
        if abs(d_oi) < 0.5:
            why, sig = "Posicionamiento estable", "neutral"
        elif d_px >= 0:
            why, sig = (("Entran longs nuevos: suba con fuerza", "alcista") if d_oi > 0 else
                        ("Cierran shorts: suba sin dinero nuevo", "neutral"))
        else:
            why, sig = (("Entran shorts nuevos: baja con fuerza", "bajista") if d_oi > 0 else
                        ("Cierran o liquidan longs: baja por descarga", "neutral"))
        add(f"oi_{hrs}h", f"Open interest {hrs} h", f"{arp(d_oi)} con precio {arp(d_px)}", sig, why)

    taker = bg._retry(bnc.fapiDataGetTakerlongshortRatio, {"symbol": "BTCUSDT", "period": "1h", "limit": 4})
    buy, sell = sum(float(x["buyVol"]) for x in taker), sum(float(x["sellVol"]) for x in taker)
    for name, r in (("1 h", float(taker[-1]["buySellRatio"])), ("4 h", buy / sell)):
        sig = "alcista" if r > 1.1 else "bajista" if r < 0.9 else "neutral"
        add(f"flujo_{name}", f"Compras vs ventas a mercado {name}", ar(r, 2), sig,
            "Dominan los compradores agresivos" if sig == "alcista" else
            "Dominan los vendedores agresivos" if sig == "bajista" else "Flujo equilibrado")

    ls = bg._retry(bnc.fetch_long_short_ratio_history, SYMBOL, "1h", limit=25)
    now_ls, prev_ls = ls[-1]["longShortRatio"], ls[0]["longShortRatio"]
    top = float(bg._retry(bnc.fapiDataGetTopLongShortPositionRatio, {"symbol": "BTCUSDT", "period": "1h", "limit": 1})[-1]["longShortRatio"])
    if now_ls > 2:
        crowd, sig = "Mayoría long: si cae, puede haber cascada de liquidaciones", "bajista"
    elif now_ls < 0.9:
        crowd, sig = "Mayoría short: si sube, puede haber squeeze", "alcista"
    else:
        crowd, sig = "Posicionamiento parejo", "neutral"
    add("long_short", "Cuentas long / short", f"{ar(now_ls, 2)} (24 h antes {ar(prev_ls, 2)}, top traders {ar(top, 2)})", sig, crowd)

    fr = bg._retry(bgx.fetch_funding_rate, SYMBOL).get("fundingRate") or 0.0
    sig = "bajista" if fr > 0.0003 else "alcista" if fr < 0 else "neutral"
    add("funding", "Funding BingX", arp(fr * 100, 4) + " cada 8 h", sig,
        "Longs pagando caro: euforia" if fr > 0.0003 else "Shorts pagan: miedo" if fr < 0 else "Normal")

    return rows, fr


# exchange: niveles a pedir. BingX va aparte: su libro publica 10-15 veces mas BTC que Binance en el mismo
# rango y dominaria cualquier total.
BOOKS = {"binanceusdm": 1000, "bybit": 500, "okx": 400, "bitget": 150, "bingx": 1000}
BOOK_BAND = 0.001      # +/-0.1%: el rango que cubren todos los libros publicos
WALL_BIN = 25.0        # USD por escalon al buscar muros


def order_books():
    """Ordenes limite esperando en los libros de varios exchanges: desequilibrio y muros."""
    per, merged_bids, merged_asks, rows = [], {}, {}, []
    for eid, limit in BOOKS.items():
        try:
            ex = getattr(ccxt, eid)({"enableRateLimit": True, "options": {"defaultType": "swap"}})
            ex.load_markets()
            size = ex.market(SYMBOL).get("contractSize") or 1    # OKX cotiza en contratos de 0.01 BTC
            book = bg._retry(ex.fetch_order_book, SYMBOL, limit=limit)
        except Exception as e:
            print(f"(libro de {eid} no disponible: {type(e).__name__})")
            continue
        bids = [(x[0], x[1] * size) for x in book["bids"]]
        asks = [(x[0], x[1] * size) for x in book["asks"]]
        mid = (bids[0][0] + asks[0][0]) / 2
        b = sum(q for p, q in bids if p >= mid * (1 - BOOK_BAND))
        a = sum(q for p, q in asks if p <= mid * (1 + BOOK_BAND))
        wall_b, wall_a = max(bids, key=lambda x: x[1]), max(asks, key=lambda x: x[1])
        name = {"binanceusdm": "Binance", "okx": "OKX", "bingx": "BingX"}.get(eid, eid.capitalize())
        rows.append({"tabla": "libro", "exchange": name, "compras": round(b, 2), "ventas": round(a, 2),
                     "desequilibrio": round((b - a) / (b + a) * 100, 1) if b + a else 0.0,
                     "muro_compra": wall_b[0], "muro_compra_btc": round(wall_b[1], 2),
                     "muro_venta": wall_a[0], "muro_venta_btc": round(wall_a[1], 2), "en_total": eid != "bingx"})
        if eid != "bingx":
            per.append((b, a))
            for side, src in ((merged_bids, bids), (merged_asks, asks)):
                for p, q in src:
                    k = round(p / WALL_BIN) * WALL_BIN
                    side[k] = side.get(k, 0.0) + q
    return rows, per, merged_bids, merged_asks


# ---------- registro de pronosticos ----------


def liquidation_map(bnc, h1, hours=168):
    """Liquidaciones pendientes estimadas con open interest nuevo y ratio long/short de la ultima semana."""
    oi = [(int(x["timestamp"]), x["openInterestValue"])
          for x in bg._retry(bnc.fetch_open_interest_history, SYMBOL, "1h", limit=hours)]
    ls = {int(x["timestamp"]): x["longShortRatio"]
          for x in bg._retry(bnc.fetch_long_short_ratio_history, SYMBOL, "1h", limit=hours)}
    bars = h1[-(hours + 2):]
    price_by_hour = {b[0] + bg.HOUR_MS: b[4] for b in bars}   # precio al cierre de cada hora
    suffix_lo, suffix_hi, lo, hi = {}, {}, float("inf"), 0.0
    for b in reversed(bars):
        suffix_lo[b[0]], suffix_hi[b[0]] = lo, hi
        lo, hi = min(lo, b[3]), max(hi, b[2])
    after = lambda t: (suffix_lo.get(t - bg.HOUR_MS, float("inf")), suffix_hi.get(t - bg.HOUR_MS, 0.0))
    return ind.mapa_liquidaciones(price_by_hour, oi, ls, after)


def log_and_score(entries, closes_by_tf):
    rows = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            rows = [r for r in csv.reader(f) if len(r) == 5]
    seen = {(r[0], r[1], r[2]) for r in rows}
    rows += [[str(t), tf, str(h), f"{p:.1f}", f"{pr:.1f}"] for t, tf, h, p, pr in entries if (str(t), tf, str(h)) not in seen]
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOG_FILE, "w", newline="") as f:
        csv.writer(f).writerows(rows)
    score = {}
    for t, tf, h, p, pr in rows:
        tf_ms = ccxt.Exchange.parse_timeframe(tf) * 1000
        future = closes_by_tf.get(tf, {}).get(int(t) + int(h) * tf_ms)
        prob = float(pr) / 100
        if future is None or prob == 0.5:
            continue
        up = future > float(p)
        n, hits, brier = score.get((tf, int(h)), (0, 0, 0.0))
        score[(tf, int(h))] = (n + 1, hits + ((prob > 0.5) == up), brier + (prob - up) ** 2)
    return score


# ---------- analisis completo ----------
def analyze():
    bnc = ccxt.binanceusdm({"enableRateLimit": True})
    bgx = ccxt.bingx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    candles = {tf: update_candles(bnc, tf, days) for tf, (days, _) in TIMEFRAMES.items()}
    price = float(bg._retry(bgx.fetch_ticker, SYMBOL)["last"])
    now_ms = bnc.milliseconds()
    rows, entries, by_tf = [], [], {}

    for tf, (days, horizons) in TIMEFRAMES.items():
        bars = candles[tf]
        tf_ms = ccxt.Exchange.parse_timeframe(tf) * 1000
        tf_min = tf_ms // 60_000
        closes = [b[4] for b in bars]
        ind_rows, summary, overlays = ind.calificar(bars)
        e20, e50, e200 = ind.ema(closes, 20), ind.ema(closes, 50), ind.ema(closes, 200)
        rsi = ind.rsi(closes)
        warmup = min(200, len(bars) // 3)
        st = states(closes, rsi, e50, e200, max(1, 1440 // tf_min))
        idxs, keep = similar(st, len(bars) - 1 - max(horizons + (SCENARIO_STEPS,)), warmup)
        base = range(warmup, len(bars) - 1 - max(horizons))
        i = len(bars) - 1
        trend = trend_word(closes[i], e20[i], e50[i], e200[i])
        by_tf[tf] = {"summary": summary, "trend": trend}
        pivots = ind.zigzag(bars)
        wave_labels, wave_desc, wave_target = ind.elliott(pivots)
        rows.append({"tabla": "marco", "tf": tf, "tendencia": trend, **summary,
                     "ema50": round(e50[i], 1), "ema200": round(e200[i], 1), "similares": len(idxs),
                     "criterio": ["", "precio vs EMA50", "precio vs EMA50 y EMA200", "medias y RSI",
                                  "medias, RSI y movimiento del ultimo dia"][keep],
                     "elliott": wave_desc, "elliott_objetivo": None if wave_target is None else round(wave_target, 1)})
        rows += [{"tabla": "indicador", "tf": tf, **r} for r in ind_rows]
        tail = pivots[-8:]
        offset = len(tail) - len(wave_labels)
        for n, (kind, k, p) in enumerate(tail):
            rows.append({"tabla": "giro", "tf": tf, "t": bars[k][0], "precio": round(p, 1), "tipo": kind,
                         "onda": wave_labels[n - offset] if n >= offset else "", "en_curso": n == len(tail) - 1})
        rows += [{"tabla": "fvg", "tf": tf, "tipo": z["tipo"], "t": z["t"], "bajo": round(z["bajo"], 1),
                  "alto": round(z["alto"], 1)} for z in ind.fvg(bars)]

        for h in horizons:
            o, b = outcomes(closes, idxs or list(base), h), outcomes(closes, base, h)
            edge = o["up"] - b["up"]
            verdict = "Casi moneda" if abs(edge) < 3 else ("Sesgo alcista" if edge > 0 else "Sesgo bajista")
            when_ms = bars[-1][0] + (h + 1) * tf_ms
            when = datetime.fromtimestamp(when_ms / 1000, LOCAL_TZ).strftime("%d/%m %H:%M")
            tg, close = targets(bars, idxs or list(base), price, h, when)
            rows.append({"tabla": "probabilidad", "tf": tf, "horizonte": label(h * tf_min), "velas": h,
                         "sube": round(o["up"], 1), "baja": round(100 - o["up"], 1), "base": round(b["up"], 1),
                         "veredicto": verdict, "n": o["n"], "dias": days, "hora": when, "t_hasta": when_ms,
                         "min": round(price * (1 + o["p10"] / 100), 1), "max": round(price * (1 + o["p90"] / 100), 1),
                         **(close or {"mediana": None, "p25": None, "p75": None})})
            rows += [{"tabla": "objetivo", "tf": tf, "horizonte": label(h * tf_min), "hora": when, **t} for t in tg]
            entries.append((bars[-1][0] + tf_ms, tf, h, closes[-1], o["up"]))

        sc, cone = scenarios(bars, idxs, price, tf_ms)
        for r in sc + cone:
            r["tf"] = tf
        rows += sc + cone
        for k in range(max(0, i - CHART_BARS + 1), i + 1):
            t, o_, h_, l_, c_, v_ = bars[k]
            rows.append({"tabla": "vela", "tf": tf, "t": t, "o": o_, "h": h_, "l": l_, "c": c_, "v": round(v_, 2),
                         "ema20": round(overlays["ema20"][k], 1), "ema50": round(overlays["ema50"][k], 1),
                         "bb_up": None if overlays["bb_up"][k] is None else round(overlays["bb_up"][k], 1),
                         "bb_lo": None if overlays["bb_lo"][k] is None else round(overlays["bb_lo"][k], 1)})

    # niveles clave
    h1, d1 = candles["1h"], candles["1d"]
    levels = []
    for name, n in (("24 h", 24), ("7 días", 168), ("30 días", 720)):
        levels += [(f"Mínimo {name}", min(b[3] for b in h1[-n:])), (f"Máximo {name}", max(b[2] for b in h1[-n:]))]
    levels += [(f"Pivote {k}", v) for k, v in ind.pivotes(d1[-1]).items()]
    lo30, hi30 = min(b[3] for b in h1[-720:]), max(b[2] for b in h1[-720:])
    levels += [(f"Fibonacci {ar(f * 100, 1)}% (30 d)", hi30 - (hi30 - lo30) * f) for f in (0.236, 0.382, 0.5, 0.618, 0.786)]
    closes_d = [b[4] for b in d1]
    sma200d = sum(closes_d[-200:]) / 200
    levels += [("Media 200 días", sma200d), ("EMA 200 diaria", ind.ema(closes_d, 200)[-1])]
    for name, v in levels:
        rows.append({"tabla": "nivel", "nombre": name, "precio": round(v, 1),
                     "tipo": "resistencia" if v > price else "soporte", "distancia": round(pct(v, price), 2)})

    try:
        ctx, funding = context(bnc, bgx, [b[4] for b in h1])
        rows += ctx
    except Exception as e:  # el contexto es complementario: si una fuente falla, el resto sirve
        funding = None
        rows.append({"tabla": "contexto", "clave": "error", "titulo": "Contexto no disponible", "valor": "",
                     "senal": "neutral", "detalle": f"No se pudo leer: {type(e).__name__}"})
    book_rows, per, mb, ma = order_books()
    rows += book_rows
    if per:
        b, a = sum(x[0] for x in per), sum(x[1] for x in per)
        imb = (b - a) / (b + a) * 100 if b + a else 0.0
        sig = "alcista" if imb > 15 else "bajista" if imb < -15 else "neutral"
        rows.append({"tabla": "contexto", "clave": "libros", "titulo": f"Libros de {len(per)} exchanges ±0,1%",
                     "valor": f"{ar(b)} BTC en compras vs {ar(a)} en ventas ({arp(imb, 0)})", "senal": sig,
                     "detalle": ("Más compras esperando debajo" if sig == "alcista" else "Más ventas esperando arriba"
                                 if sig == "bajista" else "Parejo") + ". Son órdenes, no posiciones: pueden retirarse."})
        for side, book, kind in (("compra", mb, "soporte"), ("venta", ma, "resistencia")):
            away = {p: q for p, q in book.items() if abs(p / price - 1) > 0.0005}  # lo pegado al precio no es un muro
            if away:
                p, q = max(away.items(), key=lambda x: x[1])
                rows.append({"tabla": "nivel", "nombre": f"Muro de {side} ({ar(q)} BTC en libros)", "precio": p,
                             "tipo": kind, "distancia": round(pct(p, price), 2)})
    try:
        heat = liquidation_map(bnc, h1)
        rows += [{"tabla": "liquidacion", **x} for x in heat]
        for side, kind in (("longs", "soporte"), ("shorts", "resistencia")):
            near = [x for x in heat if (x["precio"] < price) == (side == "longs") and x[side] > 0]
            if near:
                top = max(near, key=lambda x: x[side])
                rows.append({"tabla": "nivel", "nombre": f"Liquidaciones de {side} (est.)",
                             "precio": top["precio"], "tipo": kind, "distancia": round(pct(top["precio"], price), 2)})
    except Exception as e:
        print(f"(mapa de liquidaciones no disponible: {type(e).__name__})")

    closes_by_tf = {tf: {c[0] + ccxt.Exchange.parse_timeframe(tf) * 1000: c[4] for c in cs} for tf, cs in candles.items()}
    for (tf, h), (n, hits, brier) in sorted(log_and_score(entries, closes_by_tf).items()):
        tf_min = ccxt.Exchange.parse_timeframe(tf) // 60
        rows.append({"tabla": "acierto", "tf": tf, "horizonte": label(h * tf_min), "pronosticos": n,
                     "aciertos": round(hits / n * 100, 1), "brier": round(brier / n, 3)})

    p4 = next(r for r in rows if r["tabla"] == "probabilidad" and r["tf"] == "1h" and r["velas"] == 4)
    goal = lambda side: next((t for t in rows if t["tabla"] == "objetivo" and t["tf"] == "1h" and t["horizonte"] == p4["horizonte"]
                              and t["lado"] == side), None)
    up, dn = goal("arriba"), goal("abajo")
    short = by_tf["1h"]["summary"]["rating_txt"].lower()
    daily = by_tf["1d"]["summary"]["rating_txt"].lower()
    takeaway = (f"Para las {p4['hora'][-5:]} h: {ar(up['prob'])}% de probabilidad de que BTC toque {ar(up['precio'])} USD y "
                f"{ar(dn['prob'])}% de que toque {ar(dn['precio'])} USD; precio más probable {ar(p4['mediana'])}. "
                f"Calificación de 1 h en {short}, diario en {daily}." if up and dn and p4["mediana"] else
                f"Calificación de 1 h en {short}, diario en {daily}.")
    local = datetime.fromtimestamp(now_ms / 1000, LOCAL_TZ)
    rows.insert(0, {"tabla": "resumen", "fecha": local.strftime("%Y-%m-%dT%H:%M:%S-03:00"),
                    "hora_local": local.strftime("%d/%m %H:%M"), "precio": round(price, 1),
                    "cambio_24h": round(pct(price, h1[-24][4]), 2), "cambio_7d": round(pct(price, h1[-168][4]), 2),
                    "sma200d": round(sma200d, 1), "sma200d_dist": round(pct(price, sma200d), 2),
                    "funding": None if funding is None else round(funding * 100, 4),
                    "rating_1h": by_tf["1h"]["summary"]["rating"], "rating_1d": by_tf["1d"]["summary"]["rating"],
                    "lectura": takeaway, "nota_claude": ""})
    return rows


def print_console(rows):
    get = lambda t: [r for r in rows if r["tabla"] == t]
    s = get("resumen")[0]
    print(f"=== BTC {s['precio']:,.1f} | {s['hora_local']} (UTC-3) | 24h {s['cambio_24h']:+.2f}% | 7d {s['cambio_7d']:+.2f}%"
          f" | media 200d {s['sma200d']:,.0f} ({s['sma200d_dist']:+.1f}%) ===")
    print(s["lectura"])
    print("\nTEMPORALIDAD  tendencia            calificacion    medias c/v   osc c/v   RSI   ADX")
    for m in get("marco"):
        print(f"  {m['tf']:<5} {m['tendencia']:<20} {m['rating_txt']:<14} {m['ma_compra']:>3}/{m['ma_venta']:<3}"
              f"       {m['osc_compra']:>2}/{m['osc_venta']:<2}   {m['rsi']:5.1f} {m['adx']:5.1f}")
    print("\nPROBABILIDADES (hora Argentina)")
    for p in get("probabilidad"):
        goals = [t for t in get("objetivo") if t["tf"] == p["tf"] and t["horizonte"] == p["horizonte"]]
        near = sorted(goals, key=lambda t: abs(t["precio"] - s["precio"]))[:2]
        touch = " | ".join(f"{t['prob']:.0f}% de tocar {t['precio']:,.0f}" for t in near)
        print(f"  {p['tf']:>4} hasta las {p['hora']}: SUBE {p['sube']:4.1f}% / BAJA {p['baja']:4.1f}% ({p['veredicto']})"
              f"  mas probable {p['mediana'] or 0:,.0f}  | {touch}")
    print("\nELLIOTT Y FVG")
    for m in get("marco"):
        target = f" -> objetivo {m['elliott_objetivo']:,.0f}" if m["elliott_objetivo"] else ""
        zones = [z for z in get("fvg") if z["tf"] == m["tf"]][:2]
        fv = "; ".join(f"FVG {z['tipo']} {z['bajo']:,.0f}-{z['alto']:,.0f}" for z in zones)
        print(f"  {m['tf']:<4} {m['elliott']}{target}" + (f" | {fv}" if fv else ""))
    print("\nCONTEXTO ACTUAL")
    for c in get("contexto"):
        print(f"  {c['titulo']}: {c['valor']} -> {c['detalle']}")
    near = sorted(get("nivel"), key=lambda n: abs(n["distancia"]))[:6]
    print("\nNIVELES CERCANOS  " + "  ".join(f"{n['nombre']} {n['precio']:,.0f} ({n['distancia']:+.1f}%)" for n in near))
    hits = get("acierto")
    if hits:
        print("\nACIERTOS  " + "  ".join(f"{a['tf']} a {a['horizonte']}: {a['aciertos']:.0f}% ({a['pronosticos']})" for a in hits))


PAGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard", "index.html")
LOCAL_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reporte_btc.html")
# lo que el dashboard de claude.ai le da a la pagina: colores y medidas del tema, y el objeto `dash` con los datos
LOCAL_SHELL = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Analista BTC (local)</title>
<style>
:root { --color-fg: #1d2129; --color-fg-muted: #6a7180; --color-bg: #f3f4f6; --color-panel: #ffffff;
  --color-border-line: #e2e5ea; --color-ok: #138a5b; --color-warn: #b7791f; --color-bad: #c8423a;
  --font-anthropic-sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-anthropic-serif: Georgia, "Times New Roman", serif;
  --cds-font-size-caption: .78rem; --cds-font-size-body: .95rem; --cds-font-size-heading: 1.08rem; --cds-font-size-title: 1.6rem;
  --cds-font-weight-medium: 600; --cds-gap-xs: 4px; --cds-gap-sm: 8px; --cds-gap-md: 14px; --cds-gap-lg: 22px; --cds-gap-xl: 32px;
  --cds-pad-xs: 4px; --cds-pad-sm: 8px; --cds-pad-md: 12px; --cds-pad-lg: 18px; --cds-pad-xl: 28px; --cds-radius: 8px;
  --cds-chart-grid: #eceef2; --cds-surface-popover: #ffffff; --cds-border: #dde1e7; --cds-shadow-popover: 0 6px 24px rgba(20,24,32,.12);
  --cds-text-secondary: #6a7180; --cds-ease-out: cubic-bezier(.2,.8,.2,1); --cds-dur-slow: .4s; color-scheme: light; }
@media (prefers-color-scheme: dark) { :root { --color-fg: #e8eaee; --color-fg-muted: #949bab; --color-bg: #121418; --color-panel: #1b1e24;
  --color-border-line: #2b3038; --color-ok: #3cc58a; --color-warn: #e0a64a; --color-bad: #f0645a; --cds-chart-grid: #252a31;
  --cds-surface-popover: #22262d; --cds-border: #343a43; --cds-shadow-popover: 0 6px 24px rgba(0,0,0,.45); --cds-text-secondary: #949bab; color-scheme: dark; } }
body { margin: 0; background: var(--color-bg); color: var(--color-fg); font: 14px var(--font-anthropic-sans); }
#dash-root { padding-block: 24px 40px; padding-left: max(16px, var(--dash-gutter, 24px)); padding-right: max(16px, var(--dash-gutter, 24px)); }
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<script>
(function () {
  var rows = __DATA__, fns = [];
  var dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  window.dash = {
    colors: dark ? ['#7aa7ff', '#e0a64a', '#c78bff', '#4fd1c5', '#f08bb4', '#a3e635', '#fb923c', '#94a3b8']
                 : ['#2f6fde', '#b7791f', '#8b4fd6', '#0f9488', '#d1477e', '#4d7c0f', '#c2410c', '#64748b'],
    data: function () { return { status: 'ok', data: rows, columns: [], meta: [], refreshing: false }; },
    onData: function (fn) { fns.push(fn); fn(); },
    params: function () { return {}; }, setParams: function () {}, resetParams: function () {}, setLink: function () {}, refresh: function () {}
  };
  var t; window.addEventListener('resize', function () { clearTimeout(t); t = setTimeout(function () { fns.forEach(function (f) { f(); }); }, 150); });
})();
</script>
</head><body><div id="dash-root">
__PAGE__
</div></body></html>
"""


def write_local_html(data):
    """La misma pagina del dashboard, con los datos de este analisis adentro, para abrir sin internet de por medio."""
    with open(PAGE_FILE, encoding="utf-8") as f:
        page = f.read()
    rows = json.dumps(data["rows"], ensure_ascii=False).replace("</", "<\\/")
    with open(LOCAL_HTML, "w", encoding="utf-8") as f:
        f.write(LOCAL_SHELL.replace("__DATA__", rows).replace("__PAGE__", page))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nota", help="archivo de texto con la lectura de noticias para agregar al ultimo analisis")
    ap.add_argument("--abrir", action="store_true", help="abrir el dashboard local en el navegador al terminar")
    args = ap.parse_args()
    if args.nota:
        with open(OUT_FILE, encoding="utf-8") as f:
            data = json.load(f)
        with open(args.nota, encoding="utf-8") as f:
            data["rows"][0]["nota_claude"] = f.read().strip()[:4000]
    else:
        rows = analyze()
        print_console(rows)
        data = {"rows": rows}
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nGuardado {OUT_FILE} ({os.path.getsize(OUT_FILE) / 1024:.0f} KB)")
    if os.path.exists(PAGE_FILE):
        write_local_html(data)
        print(f"Dashboard local: {LOCAL_HTML}")
        if args.abrir:
            import webbrowser
            webbrowser.open("file:///" + LOCAL_HTML.replace("\\", "/"))


if __name__ == "__main__":
    main()
