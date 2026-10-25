"""
Analisis de mercado de BTC/USDT perpetuo, de 5 minutos a diario (APIs publicas, sin keys).

Uso:
    .venv\\Scripts\\python.exe analisis_btc.py                 # analiza, imprime y guarda data/analisis_btc.json
    .venv\\Scripts\\python.exe analisis_btc.py --abrir         # ademas abre el dashboard local (reporte_btc.html)
    .venv\\Scripts\\python.exe analisis_btc.py --vivo          # dashboard en vivo en http://127.0.0.1:8765
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
import sys
from concurrent.futures import ThreadPoolExecutor
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
CHART_BARS = 300
SCENARIO_STEPS = 12
# temporalidad: (dias de historia, horizontes de probabilidad en velas)
TIMEFRAMES = {"5m": (30, (3, 12)), "15m": (90, (4, 16)), "30m": (180, (4, 16)),
              "1h": (365, (4, 24)), "4h": (730, (3, 6)), "1d": (1500, (3, 7))}


# ---------- datos ----------
_EXCHANGES = {}


def exchange(eid):
    """Cliente de cada exchange con sus mercados ya cargados: cargarlos tarda segundos y en vivo se reusan."""
    if eid not in _EXCHANGES:
        ex = getattr(ccxt, eid)({"enableRateLimit": True, "options": {"defaultType": "swap"}})
        bg._retry(ex.load_markets)
        _EXCHANGES[eid] = ex
    return _EXCHANGES[eid]


def update_candles(ex, tf, days):
    """Velas cerradas de Binance Futures con cache incremental en data/."""
    path = os.path.join(DATA_DIR, f"BTC_USDT_binance_perp_{tf}.csv")
    tf_ms = ex.parse_timeframe(tf) * 1000
    candles = []
    if os.path.exists(path):
        with open(path) as f:
            # una fila incompleta (un corte justo al guardar) se descarta: la vuelve a bajar el siguiente pedido
            candles = [[int(r[0])] + [float(x) for x in r[1:]] for r in csv.reader(f) if len(r) == 6]
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
    with open(path + ".tmp", "w", newline="") as f:   # se reemplaza de una vez: un corte no deja el archivo a medias
        csv.writer(f).writerows(candles)
    os.replace(path + ".tmp", path)
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
    # cual se toco PRIMERO entre dos niveles A LA MISMA DISTANCIA del precio (precio +/- un escalon).
    # Con niveles redondos asimetricos ganaria siempre el que queda mas cerca, no el que tiene mas chances.
    up_lvl, dn_lvl = round(price + unit, -1), round(price - unit, -1)
    rel = unit / price
    first = []
    for j in usable:
        for k in range(1, h + 1):
            a, b = bars[j + k][2] / c[j] - 1 >= rel, bars[j + k][3] / c[j] - 1 <= -rel
            if a or b:
                first.append(0.5 if a and b else 1.0 if a else 0.0)
                break
    pf = sum(first) / len(first) if first else None
    close = {"mediana": round(price * (1 + q(0.5)), 1), "p25": round(price * (1 + q(0.25)), 1),
             "p75": round(price * (1 + q(0.75)), 1), "hora": when,
             "obj_arriba": up_lvl, "obj_abajo": dn_lvl, "distancia": unit,
             "toca_arriba": round(sum(x >= rel for x in highs) / len(usable) * 100, 1),
             "toca_abajo": round(sum(x <= -rel for x in lows) / len(usable) * 100, 1),
             "primero_arriba": None if pf is None else round(pf * 100, 1),
             "margen_primero": None if pf is None else round(196 * (pf * (1 - pf) / len(first)) ** 0.5, 1),
             "ninguno": round((1 - len(first) / len(usable)) * 100, 1)}
    return rows, close


def horizon_stats(tf, s, h, price):
    """Todo lo que se puede decir de las proximas h velas a partir de las situaciones parecidas."""
    bars, closes = s["bars"], s["closes"]
    o, b = outcomes(closes, s["sample"], h), outcomes(closes, s["base"], h)
    edge = o["up"] - b["up"]
    # margen de error del 95%: con pocos casos, una diferencia chica contra la tasa normal es ruido
    margin = 196 * ((o["up"] / 100) * (1 - o["up"] / 100) / o["n"]) ** 0.5
    verdict = "Casi moneda" if abs(edge) < max(3, margin) else ("Sesgo alcista" if edge > 0 else "Sesgo bajista")
    when_ms = bars[-1][0] + (h + 1) * s["tf_ms"]
    when = datetime.fromtimestamp(when_ms / 1000, LOCAL_TZ).strftime("%d/%m %H:%M")
    tg, close = targets(bars, s["sample"], price, h, when)
    return ({"tf": tf, "horizonte": label(h * s["tf_min"]), "velas": h,
             "sube": round(o["up"], 1), "baja": round(100 - o["up"], 1), "base": round(b["up"], 1),
             "veredicto": verdict, "n": o["n"], "dias": s["days"], "hora": when, "t_hasta": when_ms,
             "margen": round(margin, 1), "pocos_casos": o["n"] < 100,
             "min": round(price * (1 + o["p10"] / 100), 1), "max": round(price * (1 + o["p90"] / 100), 1),
             **(close or {"mediana": None, "p25": None, "p75": None, "obj_arriba": None, "obj_abajo": None,
                          "distancia": None, "toca_arriba": None, "toca_abajo": None,
                          "primero_arriba": None, "margen_primero": None, "ninguno": None})}, tg)


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
            ex = exchange(eid)
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


def current_candle(ex, tf, last_closed_t):
    """La vela que se esta formando ahora, como la muestra TradingView, o None."""
    tf_ms = ex.parse_timeframe(tf) * 1000
    now = ex.milliseconds()
    rows = bg._retry(ex.fetch_ohlcv, SYMBOL, tf, limit=2)
    live = [c for c in rows if c[0] > last_closed_t and c[0] + tf_ms > now]
    return live[-1] if live else None


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


TF_TXT = {"5m": "5 min", "15m": "15 min", "30m": "30 min", "1h": "1 hora", "4h": "4 horas", "1d": "diario"}
NO_LINES = {"l1_t": None, "l1_p": None, "l1_m": None, "l1_nombre": None, "l2_t": None, "l2_p": None, "l2_m": None,
            "l2_nombre": None, **{f"pt{k}_{f}": None for k in (1, 2, 3) for f in ("t", "p", "nombre")}}


def patterns(tf, bars, pivots, e20, horizon, tf_min, partial=False):
    """Patron de velas en las ultimas dos velas (con su historial de aciertos) y figura del grafico vigente."""
    o, h, l, c = ([b[k] for b in bars] for k in (1, 2, 3, 4))
    atr_ = ind.dmi(h, l, c)[3]
    i = len(bars) - 1
    rows = []
    for k in (i, i - 1):
        found = ind.patrones_velas(o, h, l, c, atr_, e20, k)
        if not found:
            continue
        name, bias = found[0]
        n, ok = ind.estadistica_velas(o, h, l, c, atr_, e20, horizon).get(name, (0, 0))
        rate = round(ok / n * 100, 1) if n else None
        if bias == "neutral":
            desc = "Indecisión: compradores y vendedores quedaron parejos en esa vela."
        elif rate is None:
            desc = "Sin casos anteriores para medir si funciona en esta temporalidad."
        else:
            desc = (f"Después de este patrón, BTC fue hacia {'arriba' if bias == 'alcista' else 'abajo'} en "
                    f"{ar(rate)}% de {n} casos ({label(horizon * tf_min)} después)"
                    + (": funcionó más de lo que falló." if rate >= 55 else ": casi como tirar una moneda." if rate >= 45
                       else ": falló más de lo que funcionó."))
        rows.append({"tabla": "patron", "tf": tf, "clase": "vela", "nombre": name, "sesgo": bias, "t": bars[k][0],
                     "estado": ("vela en curso" if partial else "última vela") if k == i else "vela anterior", "objetivo": None, "exito": rate, "casos": n,
                     "plazo": label(horizon * tf_min), "descripcion": desc, **NO_LINES})
        break
    g = ind.patron_grafico(bars, pivots, atr_[i])
    if g:
        lines = dict(NO_LINES)
        for n_, ln in enumerate(g["lineas"][:2], start=1):
            lines.update({f"l{n_}_t": ln[0], f"l{n_}_p": round(ln[1], 1), f"l{n_}_m": ln[2], f"l{n_}_nombre": ln[3]})
        for n_, pt in enumerate(g["puntos"][:3], start=1):
            lines.update({f"pt{n_}_t": pt[0], f"pt{n_}_p": round(pt[1], 1), f"pt{n_}_nombre": pt[2]})
        rows.append({"tabla": "patron", "tf": tf, "clase": "grafico", "nombre": g["nombre"], "sesgo": g["sesgo"],
                     "t": bars[i][0], "estado": g["estado"], "objetivo": g["objetivo"], "exito": None, "casos": None,
                     "plazo": None, "descripcion": g["descripcion"], **lines})
    return rows


def lc1(s):
    """Primera letra en minuscula, sin tocar siglas como R1 u onda C."""
    return s[:1].lower() + s[1:]


# plazo: (temporalidad con mas casos para ese plazo, velas, temporalidades cuyas senales pesan,
#         datos del momento que pesan, vela que confirma o invalida)
PLAZOS = [
    ("5 min", "5m", 1, ("5m",), ("libros", "flujo_1 h"), "5 min"),
    ("15 min", "5m", 3, ("5m", "15m"), ("libros", "flujo_1 h"), "5 min"),
    ("1 hora", "5m", 12, ("15m", "1h"), ("flujo_1 h", "flujo_4 h", "oi_1h"), "15 min"),
    ("4 horas", "30m", 8, ("1h", "4h"), ("flujo_4 h", "oi_4h", "oi_24h", "long_short"), "1 hora"),
    ("1 día", "4h", 6, ("4h", "1d"), ("oi_24h", "long_short", "funding"), "4 horas"),
]
SHORT_CTX = {"flujo_1 h": "Compras a mercado 1 h", "flujo_4 h": "Compras a mercado 4 h", "oi_1h": "Open interest 1 h",
             "oi_4h": "Open interest 4 h", "oi_24h": "Open interest 24 h", "long_short": "Long/short",
             "libros": "Libros de órdenes", "funding": "Funding"}


def explain(rows, price, spec):
    """La conclusion de un plazo en pocas palabras: prediccion, hasta 4 razones de cada lado, niveles e invalidacion."""
    name, _, _, sig_tfs, ctx_keys, candle = spec
    get = lambda t, **kw: [r for r in rows if r["tabla"] == t and all(r.get(k) == v for k, v in kw.items())]
    main = get("plazo", plazo=name)[0]
    hh = main["hora"][-5:]
    signals = []      # (prioridad, sesgo, texto corto)
    for pr, tf in zip((2, 3), sig_tfs):
        m = get("marco", tf=tf)[0]
        if abs(m["rating"]) > 0.1:
            signals.append((pr, "alcista" if m["rating"] > 0 else "bajista", f"Indicadores de {TF_TXT[tf]}: {m['rating_txt'].lower()}"))
    for p in get("patron"):
        if p["tf"] not in sig_tfs or p["sesgo"] == "neutral":
            continue
        target = f" → {ar(p['objetivo'])}" if p["objetivo"] else ""
        if p["clase"] == "grafico":
            signals.append((1 if p["estado"] == "confirmado" else 4, p["sesgo"], f"{p['nombre']} en {TF_TXT[p['tf']]}{target}"))
        elif p["exito"] is not None and p["exito"] >= 55 and p["casos"] >= 20:
            signals.append((5, p["sesgo"], f"{p['nombre']} en {TF_TXT[p['tf']]} (funcionó {ar(p['exito'])}%)"))
    divs = {}
    for d in get("divergencia"):
        if d["tf"] in sig_tfs:
            divs.setdefault((d["tf"], d["tipo"]), []).append(d["indicador"])
    for (tf, tipo), names in divs.items():
        signals.append((3, tipo, f"Divergencia {tipo} en {' y '.join(names)} ({TF_TXT[tf]})"))
    for c in get("contexto"):
        if c["senal"] in ("alcista", "bajista") and c["clave"] in ctx_keys:
            signals.append((3, c["senal"], f"{SHORT_CTX[c['clave']]}: {lc1(c['detalle'].split('.')[0].split(':')[0])}"))
    if main["veredicto"] != "Casi moneda":
        signals.append((2, "alcista" if main["veredicto"] == "Sesgo alcista" else "bajista",
                        f"Casos parecidos: cerró arriba {ar(main['sube'])}% (normal {ar(main['base'])}%)"))
    m_last = get("marco", tf=sig_tfs[-1])[0]
    if m_last["elliott_objetivo"]:
        signals.append((7, "alcista" if m_last["elliott_objetivo"] > price else "bajista",
                        f"Elliott {TF_TXT[sig_tfs[-1]]}: {lc1(m_last['elliott']).replace(' en curso', '')} → {ar(m_last['elliott_objetivo'])}"))
    sma = next((n for n in get("nivel") if n["nombre"] == "Media 200 días"), None)
    if sma and name == "1 día":
        signals.append((6, "alcista" if price > sma["precio"] else "bajista",
                        "Arriba de la media de 200 días" if price > sma["precio"] else "Debajo de la media de 200 días"))
    signals.sort(key=lambda x: x[0])

    up, dn, pu, mg = main["obj_arriba"], main["obj_abajo"], main["primero_arriba"], main["margen_primero"] or 0
    n_up = sum(s == "alcista" for _, s, _ in signals)
    n_dn = len(signals) - n_up
    if pu is not None and pu - 50 > max(5, mg):
        bias = "alcista"
        head = f"Hasta las {hh} h, es más probable que BTC suba a {ar(up)} ({ar(pu)}%) antes que baje a {ar(dn)}."
    elif pu is not None and 50 - pu > max(5, mg):
        bias = "bajista"
        head = f"Hasta las {hh} h, es más probable que BTC baje a {ar(dn)} ({ar(100 - pu)}%) antes que suba a {ar(up)}."
    else:
        bias = "neutral"
        head = f"Hasta las {hh} h, sin dirección clara: lo esperable es que BTC se mueva entre {ar(dn)} y {ar(up)}."
    agree = n_up if bias == "alcista" else n_dn
    if not signals:
        why = "No hay señales fuertes en este plazo."
    elif bias == "neutral":
        why = f"Las señales están repartidas: {n_up} alcistas y {n_dn} bajistas."
    elif agree * 2 > len(signals):
        why = f"Lo acompañan {agree} de {len(signals)} señales."
    else:
        why = f"Ojo: solo {agree} de {len(signals)} señales acompañan. Convicción baja."

    def row(orden, tipo, sesgo, texto, precio=None):
        return {"tabla": "explicacion", "plazo": name, "orden": orden, "tipo": tipo, "sesgo": sesgo, "texto": texto,
                "precio": precio}

    out = [row(0, "titular", bias, head), row(1, "porque", bias, why)]
    out += [row(k, "senal", s, txt) for k, (_, s, txt) in enumerate(signals, start=2)]
    # niveles que importan para este plazo: ni pegados al precio ni mas cerca de lo que se mueve en ese tiempo
    gap = max(0.0015, 0.5 * (main["distancia"] or 0) / price)
    levels = sorted(get("nivel"), key=lambda n: n["precio"])
    res = next((n for n in levels if n["precio"] > price * (1 + gap)), None)
    sup = next((n for n in reversed(levels) if n["precio"] < price * (1 - gap)), None)
    k = len(out)
    if res:
        out.append(row(k, "vigilar", "alcista", f"Resistencia {ar(res['precio'])} ({lc1(res['nombre'])})", res["precio"]))
    if sup:
        out.append(row(k + 1, "vigilar", "bajista", f"Soporte {ar(sup['precio'])} ({lc1(sup['nombre'])})", sup["precio"]))
    if bias == "alcista" and sup:
        inval = f"Si una vela de {candle} cierra debajo de {ar(sup['precio'])}, la idea deja de valer."
    elif bias == "bajista" and res:
        inval = f"Si una vela de {candle} cierra arriba de {ar(res['precio'])}, la idea deja de valer."
    else:
        inval = f"La dirección la marca la primera vela de {candle} que cierre fuera de {ar(dn)} a {ar(up)}."
    out.append(row(k + 2, "invalida", bias, inval))
    return out


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
    bnc, bgx = exchange("binanceusdm"), exchange("bingx")
    # los pedidos de red van en paralelo: velas de todas las temporalidades a la vez, y los libros de ordenes
    # se bajan mientras se calcula lo demas
    pool = ThreadPoolExecutor(max_workers=8)
    books_job = pool.submit(order_books)
    jobs = {tf: pool.submit(update_candles, bnc, tf, days) for tf, (days, _) in TIMEFRAMES.items()}
    candles = {tf: job.result() for tf, job in jobs.items()}
    # el analisis incluye la vela en curso de cada temporalidad (como TradingView): los indicadores, patrones y
    # escenarios se mueven con el precio. El cache y el registro de aciertos siguen usando solo velas cerradas.
    forming = {tf: pool.submit(current_candle, bnc, tf, candles[tf][-1][0]) for tf in TIMEFRAMES}
    full = {}
    for tf, job in forming.items():
        try:
            bar = job.result()
        except Exception:   # sin la vela en curso, el analisis igual sirve con las cerradas
            bar = None
        full[tf] = candles[tf] + [bar] if bar else candles[tf]
    price = float(bg._retry(bgx.fetch_ticker, SYMBOL)["last"])
    now_ms = bnc.milliseconds()
    rows, entries, by_tf, series = [], [], {}, {}

    for tf, (days, horizons) in TIMEFRAMES.items():
        bars = full[tf]
        partial = len(bars) > len(candles[tf])
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
        rows += patterns(tf, bars, pivots, e20, horizons[0], tf_min, partial)
        rows += [{"tabla": "divergencia", "tf": tf, **d, "p1": round(d["p1"], 1), "p2": round(d["p2"], 1)}
                 for d in ind.divergencias(bars, pivots)]

        series[tf] = {"bars": bars, "closes": closes, "sample": idxs or list(base), "base": list(base),
                      "tf_ms": tf_ms, "tf_min": tf_min, "days": days}
        for h in horizons:
            prob, tg = horizon_stats(tf, series[tf], h, price)
            rows.append({"tabla": "probabilidad", **prob})
            rows += [{"tabla": "objetivo", "tf": tf, "horizonte": prob["horizonte"], "hora": prob["hora"], **t} for t in tg]
            entries.append((bars[-1][0] + tf_ms, tf, h, closes[-1], prob["sube"]))

        sc, cone = scenarios(bars, idxs, price, tf_ms)
        for r in sc + cone:
            r["tf"] = tf
        rows += sc + cone
        for k in range(max(0, i - CHART_BARS + 1), i + 1):
            t, o_, h_, l_, c_, v_ = bars[k]
            rows.append({"tabla": "vela", "tf": tf, "t": t, "o": o_, "h": h_, "l": l_, "c": c_, "v": round(v_, 2),
                         "en_curso": partial and k == i,
                         "ema20": round(overlays["ema20"][k], 1), "ema50": round(overlays["ema50"][k], 1),
                         "bb_up": None if overlays["bb_up"][k] is None else round(overlays["bb_up"][k], 1),
                         "bb_lo": None if overlays["bb_lo"][k] is None else round(overlays["bb_lo"][k], 1)})

    # una prediccion por plazo, cada una con la temporalidad que mas casos tiene para ese plazo
    for name, tf, h, *_ in PLAZOS:
        prob, tg = horizon_stats(tf, series[tf], h, price)
        rows.append({"tabla": "plazo", "plazo": name, **prob})
        rows += [{"tabla": "objetivo_plazo", "plazo": name, **t} for t in tg]
        if not any(e[1] == tf and e[2] == h for e in entries):
            entries.append((series[tf]["bars"][-1][0] + series[tf]["tf_ms"], tf, h, series[tf]["closes"][-1], prob["sube"]))

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
    book_rows, per, mb, ma = books_job.result()
    pool.shutdown(wait=False)
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

    explanation = [e for spec in PLAZOS for e in explain(rows, price, spec)]
    rows += explanation
    takeaway = next(e["texto"] for e in explanation if e["plazo"] == "1 hora" and e["tipo"] == "titular")
    local = datetime.fromtimestamp(now_ms / 1000, LOCAL_TZ)
    rows.insert(0, {"tabla": "resumen", "fecha": datetime.now(LOCAL_TZ).isoformat(timespec="milliseconds"),
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
    print("\nQUE CREO QUE VA A PASAR")
    for e in get("explicacion"):
        if e["tipo"] == "titular":
            print(f"  En {e['plazo']:<8} {e['texto']}")
    for p in get("patron"):
        if p["tf"] in ("15m", "1h", "4h"):
            extra = f", objetivo {ar(p['objetivo'])}" if p["objetivo"] else f", funcionó {ar(p['exito'])}% de {p['casos']}" if p["exito"] else ""
            print(f"  Patrón {p['tf']}: {p['nombre']} ({p['estado']}{extra})")
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
  // modo en vivo (servido por analisis_btc.py --vivo): la pagina se conecta a Binance y trae cada analisis nuevo
  window.abLive = __LIVE__;
  if (window.abLive) {
    setInterval(function () {
      fetch('analisis_btc.json', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (d) {
        if (d.rows && d.rows[0] && d.rows[0].fecha !== rows[0].fecha) {
          rows = d.rows; window.abAnalyses = (window.abAnalyses || 1) + 1; fns.forEach(function (f) { f(); });
        }
      }).catch(function () {});
    }, 2000);
  }
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


def write_local_html(data, path=LOCAL_HTML, live=False):
    """La misma pagina del dashboard, con los datos de este analisis adentro."""
    with open(PAGE_FILE, encoding="utf-8") as f:
        page = f.read()
    rows = json.dumps(data["rows"], ensure_ascii=False).replace("</", "<\\/")
    html = LOCAL_SHELL.replace("__DATA__", rows).replace("__LIVE__", "true" if live else "false").replace("__PAGE__", page)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(html)
    os.replace(tmp, path)


# el modo en vivo publica SOLO esta carpeta, y solo en esta PC: nunca el proyecto entero (ahi esta el .env)
LIVE_DIR = os.path.join(DATA_DIR, "vivo")
LIVE_PORT = 8765


def run_live(every):
    """Recalcula el analisis cada `every` segundos y lo sirve en http://127.0.0.1:8765 hasta Ctrl+C."""
    import functools
    import http.server
    import threading
    import time
    import webbrowser

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    os.makedirs(LIVE_DIR, exist_ok=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", LIVE_PORT), functools.partial(Quiet, directory=LIVE_DIR))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{LIVE_PORT}/"
    print(f"Modo en vivo: {url} (recalcula cada {every} s, Ctrl+C para salir)")
    first = True
    try:
        while True:
            started = time.time()
            try:
                data = {"rows": analyze()}
                with open(OUT_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
                live_json = os.path.join(LIVE_DIR, "analisis_btc.json")
                with open(live_json + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
                os.replace(live_json + ".tmp", live_json)
                if first:
                    write_local_html(data, os.path.join(LIVE_DIR, "index.html"), live=True)
                    webbrowser.open(url)
                    first = False
                head = next(r for r in data["rows"] if r["tabla"] == "resumen")
                print(f"{time.strftime('%H:%M:%S')}  BTC {ar(head['precio'], 1)}  ({time.time() - started:.1f} s)  {head['lectura']}")
            except Exception as e:  # un corte de red no tiene que frenar el modo en vivo
                print(f"(no se pudo actualizar: {type(e).__name__}: {e})")
            time.sleep(max(1, every - (time.time() - started)))
    except KeyboardInterrupt:
        print("Modo en vivo detenido.")
    finally:
        server.shutdown()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nota", help="archivo de texto con la lectura de noticias para agregar al ultimo analisis")
    ap.add_argument("--abrir", action="store_true", help="abrir el dashboard local en el navegador al terminar")
    ap.add_argument("--vivo", nargs="?", const=5, type=int, metavar="SEGUNDOS",
                    help="modo en vivo: precio por WebSocket y analisis completo recalculado cada SEGUNDOS (5, sin pausa)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # la consola de Windows no siempre es UTF-8
    if args.vivo:
        run_live(max(5, args.vivo))
        return
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
