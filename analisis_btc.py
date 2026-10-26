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
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import ccxt

import aprendizaje as apr
import avisos
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
_BANNED = {}        # exchange -> hasta cuando (ms) bloqueo nuestra IP por exceso de pedidos
_CALLS = {}         # exchange -> pedidos hechos (para controlar cuanto se le pide a cada uno)
_CACHE = {}


def api(eid, fn, *args, **kwargs):
    """Pedido a un exchange. Si el exchange bloqueo la IP, no se le vuelve a pedir nada hasta que venza."""
    now = time.time() * 1000
    if _BANNED.get(eid, 0) > now:
        raise ccxt.DDoSProtection(f"{eid} bloqueado por exceso de pedidos por {(_BANNED[eid] - now) / 60000:.0f} min mas")
    _CALLS[eid] = _CALLS.get(eid, 0) + 1
    try:
        return bg._retry(fn, *args, **kwargs)
    except (ccxt.DDoSProtection, ccxt.RateLimitExceeded) as e:
        until = re.search(r"banned until (\d+)", str(e))
        _BANNED[eid] = int(until.group(1)) if until else now + 120_000      # sin fecha: dos minutos de pausa
        print(f"({eid} limito los pedidos: pausa hasta {datetime.fromtimestamp(_BANNED[eid] / 1000, LOCAL_TZ):%H:%M})", flush=True)
        raise


def banned(eid):
    return _BANNED.get(eid, 0) > time.time() * 1000


def cached(key, ttl, fn):
    """Lo que cambia lento (open interest, liquidaciones, libros) no se pide en cada analisis."""
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = fn()
    _CACHE[key] = (time.time(), value)
    return value


def exchange(eid):
    """Cliente de cada exchange con sus mercados ya cargados: cargarlos tarda segundos y en vivo se reusan."""
    if eid not in _EXCHANGES:
        ex = getattr(ccxt, eid)({"enableRateLimit": True, "options": {"defaultType": "swap"}})
        api(eid, ex.load_markets)
        _EXCHANGES[eid] = ex
    return _EXCHANGES[eid]


def replace_file(tmp, path):
    """Reemplaza de una vez. En Windows falla si otro proceso tiene el archivo abierto: se reintenta un
    instante y, si sigue ocupado, se descarta este guardado (el proximo analisis lo vuelve a escribir)."""
    for _ in range(10):
        try:
            os.replace(tmp, path)
            return True
        except PermissionError:
            time.sleep(0.1)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return False


def candle_source():
    """Binance Futures; si bloqueo la IP (pasa en servidores con IP compartida), Bybit hasta que se libere."""
    return exchange("bybit") if banned("binanceusdm") else exchange("binanceusdm")


def update_candles(ex, tf, days):
    """Velas cerradas con cache incremental en data/ (un archivo por exchange)."""
    name = "binance" if ex.id == "binanceusdm" else ex.id
    path = os.path.join(DATA_DIR, f"BTC_USDT_{name}_perp_{tf}.csv")
    tf_ms = ex.parse_timeframe(tf) * 1000
    candles = []
    if os.path.exists(path):
        with open(path) as f:
            # una fila incompleta (un corte justo al guardar) se descarta: la vuelve a bajar el siguiente pedido
            candles = [[int(r[0])] + [float(x) for x in r[1:]] for r in csv.reader(f) if len(r) == 6]
    now = ex.milliseconds()
    since = candles[-1][0] + tf_ms if candles else now - days * 86_400_000
    while since + tf_ms <= now:
        batch = api(ex.id, ex.fetch_ohlcv, SYMBOL, tf, since=since, limit=1500 if ex.id == "binanceusdm" else 1000)
        batch = [c for c in batch if c[0] >= since and c[0] + tf_ms <= now]
        if not batch:
            break
        candles += batch
        since = candles[-1][0] + tf_ms
    candles = [c for c in candles if c[0] >= now - days * 86_400_000]
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path + ".tmp", "w", newline="") as f:   # se reemplaza de una vez: un corte no deja el archivo a medias
        csv.writer(f).writerows(candles)
    replace_file(path + ".tmp", path)
    return candles


def ap(x):
    """Precio: sin decimales desde 1.000 (BTC) y con dos debajo (ZEC)."""
    return ar(x, 0 if abs(x) >= 1000 else 2)


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
# la situacion de cada vela (que rasgos se comparan) la elige el aprendizaje: ver aprendizaje.py
def similar(st, last, warmup):
    now = st[-1]
    idxs, keep = [], 0
    for keep in (4, 3, 2, 1):
        idxs = [j for j in range(warmup, last) if st[j] and st[j][:keep] == now[:keep]]
        if len(idxs) >= MIN_SAMPLES:
            break
    return idxs, keep


# ---------- movimiento fuerte en la proxima hora ----------
# Probabilidad de que la hora siguiente se mueva mas del doble de lo normal y cuanto se mueve (mediana, en veces lo
# normal), segun la volatilidad de las velas de 5 min (rapida / lenta). Medido con velas de futuros de Binance
# 2021-2026: la tabla casi no cambio entre 2021-24 y 2025-26.
MOV_CORTES = (0.8, 1.0, 1.3, 1.6, 2.0, 2.5)
MOV_TABLA = {"BTC": {"prob": (8, 12, 19, 32, 43, 60, 68), "veces": (0.8, 0.96, 1.18, 1.53, 1.75, 2.3, 3.0), "base": 14},
             "ZEC": {"prob": (7, 8, 14, 24, 35, 50, 69), "veces": (0.87, 0.94, 1.11, 1.38, 1.6, 2.0, 3.7), "base": 11}}


def movimiento(c5, price, moneda="BTC"):
    """Que tan agitado esta el mercado y que se puede esperar de la proxima hora. c5: velas de 5 min cerradas."""
    if len(c5) < 300:
        return None
    af, asl = 2 / 21, 2 / 201
    ef = es = None
    serie = []
    for b in c5:
        r = (b[2] - b[3]) / b[4]
        v = r * r
        ef = v if ef is None else ef + af * (v - ef)
        es = v if es is None else es + asl * (v - es)
        serie.append(math.sqrt(ef / es) if es > 0 else 1.0)
    vol = serie[-1]
    rangos = []
    j = len(c5) - 13
    while j >= 0 and len(rangos) < 720:
        hi = max(b[2] for b in c5[j + 1:j + 13])
        lo = min(b[3] for b in c5[j + 1:j + 13])
        rangos.append((hi - lo) / c5[j][4])
        j -= 12
    rangos.sort()
    normal = rangos[len(rangos) // 2]
    k = sum(1 for x in MOV_CORTES if vol >= x)
    t = MOV_TABLA[moneda]
    nivel = "Calma" if vol < 0.8 else "Normal" if vol < 1.3 else "Agitado" if vol < 1.8 else "Se despertó"
    return {"tabla": "movimiento", "volatilidad": round(vol, 2), "nivel": nivel, "prob_fuerte": t["prob"][k],
            "prob_normal": t["base"], "veces": t["veces"][k], "normal_pct": round(normal * 100, 2),
            "esperado_pct": round(normal * t["veces"][k] * 100, 2), "normal_usd": round(normal * price, 1),
            "esperado_usd": round(normal * t["veces"][k] * price, 1), "despierto": vol > 1.8 and serie[-7] <= 1.8}


# ---------- volatilidad prevista ----------
# Lo que se mueve el precio tiene memoria (despues de horas agitadas vienen horas agitadas) y depende de la hora
# del dia. Cada caso del pasado se lleva a la volatilidad de ahora antes de usarlo para el rango esperado, los
# niveles que puede tocar y los caminos posibles. Probado con velas reales de BTC (2025-2026, sin mirar el
# futuro): la probabilidad de tocar cada precio tiene 4,5% a 13% menos error y el rango, 1,3% a 5% menos.
VOL_RAPIDA, VOL_LENTA, VOL_PESO, VOL_MIN_FRANJA = 20, 200, 0.5, 20


def vol_escala(bars, tf_min, h, partial):
    """Para cada vela j, por cuanto multiplicar su movimiento de las h velas siguientes para llevarlo a la
    volatilidad de ahora: (volatilidad prevista ahora) / (volatilidad prevista en j). Solo usa datos hasta j."""
    n = len(bars)
    tf_ms = tf_min * 60_000
    slots = 1440 // tf_min if tf_min < 1440 else 1
    af, asl = 2 / (VOL_RAPIDA + 1), 2 / (VOL_LENTA + 1)
    ef = es = None
    sm, sc = [0.0] * slots, [0] * slots
    tm, tc = 0.0, 0
    S, base = [0.0] * n, [0.0] * n
    now = n - 2 if partial and n > 1 else n - 1
    s_now = None

    def franjas(i, desde):
        """Promedio del efecto de la hora del dia en las h velas que siguen a la vela 'desde' (tabla hasta i)."""
        if slots == 1 or not tc:
            return 1.0
        k0, acc = bars[desde][0] // tf_ms, 0.0
        for k in range(1, h + 1):
            x = (k0 + k) % slots
            acc += (sm[x] / sc[x]) / (tm / tc) if sc[x] >= VOL_MIN_FRANJA else 1.0
        return acc / h

    for i in range(n):
        r = (bars[i][2] - bars[i][3]) / bars[i][4]
        v = r * r
        ef = v if ef is None else ef + af * (v - ef)
        es = v if es is None else es + asl * (v - es)
        base[i] = math.sqrt(VOL_PESO * ef + (1 - VOL_PESO) * es)
        if i <= now:
            x = (bars[i][0] // tf_ms) % slots
            sm[x] += r
            sc[x] += 1
            tm += r
            tc += 1
        S[i] = base[i] * franjas(i, i)
        if i == now:
            s_now = base[i] * franjas(i, n - 1)
    return [s_now / x if x > 0 else 1.0 for x in S]


def outcomes(closes, idxs, h, F=None):
    rets = sorted((closes[i + h] / closes[i] - 1) * (F[i] if F else 1.0) for i in idxs if i + h < len(closes))
    if not rets:
        return None
    q = lambda p: rets[min(int(p * len(rets)), len(rets) - 1)] * 100
    return {"n": len(rets), "up": sum(r > 0 for r in rets) / len(rets) * 100, "p10": q(0.1), "p90": q(0.9)}


def scenarios(bars, idxs, price, tf_ms, F=None):
    """Camino tipico/alcista/bajista: el camino real mas parecido a la mediana y a los percentiles 75/25."""
    closes = [b[4] for b in bars]
    usable = [j for j in idxs if j + SCENARIO_STEPS < len(bars)]
    if len(usable) < 10:
        return [], []
    f = (lambda j: F[j]) if F else (lambda j: 1.0)
    paths = {j: [(closes[j + k] / closes[j] - 1) * f(j) for k in range(1, SCENARIO_STEPS + 1)] for j in usable}
    cols = [sorted(p[k] for p in paths.values()) for k in range(SCENARIO_STEPS)]
    q = lambda p: [col[min(int(p * len(col)), len(col) - 1)] for col in cols]
    targets = {"tipico": q(0.5), "alcista": q(0.75), "bajista": q(0.25)}
    t0 = bars[-1][0]
    candles, cone = [], []
    for name, target in targets.items():
        j = min(paths, key=lambda j: sum(abs(a - b) for a, b in zip(paths[j], target)))
        base, fj = closes[j], f(j)
        # el camino real, llevado al precio y a la volatilidad de ahora
        z = lambda x: price * (1 + (x / base - 1) * fj)
        for k in range(1, SCENARIO_STEPS + 1):
            _, o, h, l, c, _ = bars[j + k]
            candles.append({"tabla": "escenario", "tf": None, "escenario": name, "paso": k, "t": t0 + k * tf_ms,
                            "o": round(z(o), 1), "h": round(z(h), 1), "l": round(z(l), 1), "c": round(z(c), 1),
                            "desde": datetime.fromtimestamp(bars[j][0] / 1000, timezone.utc).strftime("%Y-%m-%d")})
    p10, p50, p90 = q(0.1), q(0.5), q(0.9)
    for k in range(SCENARIO_STEPS):
        cone.append({"tabla": "cono", "tf": None, "paso": k + 1, "t": t0 + (k + 1) * tf_ms,
                     "p10": round(price * (1 + p10[k]), 1), "p50": round(price * (1 + p50[k]), 1),
                     "p90": round(price * (1 + p90[k]), 1)})
    return candles, cone


NICE_STEPS = apr.NICE_STEPS


def targets(bars, idxs, price, h, when, f=1.0, unit=None, pf_ap=None, F=None):
    """Probabilidad de TOCAR precios redondos antes de 'when', y precio mas probable a esa hora.

    Para cada situacion parecida se mira el maximo y el minimo que alcanzo el precio en las h velas
    siguientes: la probabilidad de tocar un nivel es la fraccion de casos que llegaron a el.
    """
    usable = [j for j in idxs if j + h < len(bars)]
    if len(usable) < 10:
        return [], None
    c = [b[4] for b in bars]
    v = (lambda j: F[j]) if F else (lambda j: 1.0)      # cada caso, a la volatilidad de ahora
    highs = [(max(b[2] for b in bars[j + 1:j + h + 1]) / c[j] - 1) * v(j) for j in usable]
    lows = [(min(b[3] for b in bars[j + 1:j + h + 1]) / c[j] - 1) * v(j) for j in usable]
    ends = sorted((c[j + h] / c[j] - 1) * v(j) for j in usable)
    q = lambda p: ends[min(int(p * len(ends)), len(ends) - 1)]
    spread = (q(0.9) - q(0.1)) * price
    # la distancia la fija el aprendizaje (es la que viene midiendo); si no hay, la de los casos parecidos
    unit = unit or min(NICE_STEPS, key=lambda s: abs(s - spread / 4))
    unit = int(unit) if unit >= 1 else unit
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
    if unit >= 10:
        up_lvl, dn_lvl = round(price + unit, -1), round(price - unit, -1)
    else:                       # criptos de precio chico: se redondea a la decima parte del escalon
        q = unit / 10
        up_lvl, dn_lvl = round((price + unit) / q) * q, round((price - unit) / q) * q
    rel = unit / price
    first = []
    for j in usable:
        for k in range(1, h + 1):
            a, b = (bars[j + k][2] / c[j] - 1) * v(j) >= rel, (bars[j + k][3] / c[j] - 1) * v(j) <= -rel
            if a or b:
                first.append(0.5 if a and b else 1.0 if a else 0.0)
                break
    pf = sum(first) / len(first) if first else None
    close = {"mediana": round(price * (1 + q(0.5)), 1), "p25": round(price * (1 + q(0.25)), 1),
             "p75": round(price * (1 + q(0.75)), 1), "hora": when,
             "obj_arriba": up_lvl, "obj_abajo": dn_lvl, "distancia": unit,
             "toca_arriba": round(sum(x >= rel for x in highs) / len(usable) * 100, 1),
             "toca_abajo": round(sum(x <= -rel for x in lows) / len(usable) * 100, 1),
             # lo que dice el equipo que aprende (o la cruda con la confianza aprendida); la cruda queda aparte
             "primero_arriba": (round(pf_ap * 100, 1) if pf_ap is not None else
                                None if pf is None else round(apr.ajustar(pf, f) * 100, 1)),
             "primero_crudo": None if pf is None else round(pf * 100, 1),
             "margen_primero": None if pf is None else round(196 * (pf * (1 - pf) / len(first)) ** 0.5 * f, 1),
             "ninguno": round((1 - len(first) / len(usable)) * 100, 1)}
    return rows, close


def vol_factor(s, h):
    """vol_escala de una temporalidad y un horizonte (una sola vez por analisis). Solo hasta velas de 1 hora:
    con velas de 4 horas o diarias la prueba con datos reales no mostro mejora."""
    if s["tf_min"] > 60:
        return None
    if h not in s["vol"]:
        s["vol"][h] = vol_escala(s["bars"], s["tf_min"], h, s["partial"])
    return s["vol"][h]


def tune(tf, s, h):
    """Lo aprendido para predecir h velas de esta temporalidad, y los casos parecidos segun la receta aprendida."""
    if h in s["fit"]:
        return s["fit"][h]
    learn = apr.aprendido((tf, h), s["closed"], s["combo"], h, s["warmup"], s["X"])
    p_sube, p_prim = apr.prediccion(learn, s["combo"][-1], s["X"][-1])
    r = learn["receta"] if learn else 0
    if r not in s["similar"]:
        s["similar"][r] = similar(apr.estados(s["feats"], r), s["last"], s["warmup"])
    idxs, keep = s["similar"][r]
    s["fit"][h] = {"learn": learn, "receta": r, "factor": learn["factor"] if learn else 1.0, "idxs": idxs,
                   "keep": keep, "sample": idxs or s["base"], "p_sube": p_sube, "p_primero": p_prim}
    return s["fit"][h]


def learning_rows(name, tf, h, fit):
    """Que aprendio el analista para un plazo y como le fue, con la curva de aciertos a lo largo del repaso."""
    L = fit["learn"] or {}
    r2 = lambda k, d: None if L.get(k) is None else round(L[k], d)
    rows = [{"tabla": "aprendizaje", "plazo": name, "tf": tf, "velas": h, "receta": fit["receta"],
             "receta_txt": apr.receta_txt(fit["receta"]), "factor": fit["factor"],
             "confianza": apr.confianza_txt(fit["factor"]), "repasadas": L.get("repasadas", 0),
             "desde": L.get("desde"), "hasta": L.get("hasta"), "cambios": L.get("cambios", 0),
             "distancia": L.get("distancia"), "medidas": L.get("medidas", 0),
             "brier_aprendido": r2("brier_aprendido", 4), "brier_original": r2("brier_original", 4),
             "aciertos_aprendido": r2("aciertos_aprendido", 1), "aciertos_original": r2("aciertos_original", 1),
             "decisivas_aprendido": L.get("decisivas_aprendido", 0), "decisivas_original": L.get("decisivas_original", 0),
             "habilidad": r2("habilidad", 2), "habilidad_original": r2("habilidad_original", 2),
             "ic_bajo": r2("ic_bajo", 1), "ic_alto": r2("ic_alto", 1), "independientes": L.get("independientes", 0),
             "aciertos_seguro": r2("aciertos_seguro", 1), "decisivas_seguro": L.get("decisivas_seguro", 0),
             "sep_arriba": r2("sep_arriba", 1), "sep_abajo": r2("sep_abajo", 1), "margen_sep": r2("margen_sep", 1),
             "peso_modelo": None if not L.get("pesos") else round(L["pesos"][apr.MODELO] * 100, 1),
             "peso_base": None if not L.get("pesos") else round(L["pesos"][apr.BASE] * 100, 1),
             "lider": apr.experto_txt(L["ranking"][0]) if L.get("ranking") else "",
             "ranking": ",".join(str(r) for r in L.get("ranking", []))}]
    rows += [{"tabla": "aprendizaje_curva", "plazo": name, "paso": k, "aprendido": None if a is None else round(a, 2),
              "original": None if o is None else round(o, 2)} for k, a, o in L.get("curva", [])]
    return rows


def round2(x):
    return None if x is None else round(x, 2)


def change_since(closed_5m, now_ms, price, hours):
    """Cambio % contra el precio de hace exactamente `hours` horas (cierre de la vela de 5m de ese momento)."""
    ref = now_ms - hours * bg.HOUR_MS
    for c in reversed(closed_5m):
        if c[0] + 300_000 <= ref:
            return pct(price, c[4])
    return None


def horizon_stats(tf, s, h, price, fit):
    """Todo lo que se puede decir de las proximas h velas a partir de las situaciones parecidas.

    fit: lo aprendido para este plazo (ver tune): con que receta se buscan los casos parecidos y cuanto confiar
    en las probabilidades. Las probabilidades que se muestran ya vienen ajustadas; las crudas quedan aparte.
    """
    bars, closes, sample, f = s["bars"], s["closes"], fit["sample"], fit["factor"]
    F = vol_factor(s, h)
    o, b = outcomes(closes, sample, h, F), outcomes(closes, s["base"], h)
    # la probabilidad de subir la da el equipo que aprende; sin historia suficiente, los casos parecidos
    up = (fit["p_sube"] * 100 if fit.get("p_sube") is not None else
          o["up"] if f == 1.0 else apr.ajustar(o["up"] / 100, f) * 100)
    # contra la tasa normal moderada igual que la prediccion: si aprendio que no hay ventaja (confianza 0), es moneda
    edge = up - (apr.ajustar(b["up"] / 100, f) * 100 if fit.get("p_sube") is not None else b["up"])
    # margen de error del 95%: con pocos casos, una diferencia chica contra la tasa normal es ruido
    margin = 196 * ((o["up"] / 100) * (1 - o["up"] / 100) / o["n"]) ** 0.5 * f
    verdict = "Casi moneda" if abs(edge) < max(3, margin) else ("Sesgo alcista" if edge > 0 else "Sesgo bajista")
    when_ms = bars[-1][0] + (h + 1) * s["tf_ms"]
    when = datetime.fromtimestamp(when_ms / 1000, LOCAL_TZ).strftime("%d/%m %H:%M")
    L = fit.get("learn") or {}
    tg, close = targets(bars, sample, price, h, when, f, L.get("distancia"), fit.get("p_primero"), F)
    return ({"tf": tf, "horizonte": label(h * s["tf_min"]), "velas": h,
             "sube": round(up, 1), "baja": round(100 - up, 1), "base": round(b["up"], 1),
             "sube_crudo": round(o["up"], 1), "receta": fit["receta"], "factor": f,
             "veredicto": verdict, "n": o["n"], "dias": s["days"], "hora": when, "t_hasta": when_ms,
             "margen": round(margin, 1), "pocos_casos": o["n"] < 100,
             "min": round(price * (1 + o["p10"] / 100), 1), "max": round(price * (1 + o["p90"] / 100), 1),
             **(close or {"mediana": None, "p25": None, "p75": None, "obj_arriba": None, "obj_abajo": None,
                          "distancia": None, "toca_arriba": None, "toca_abajo": None,
                          "primero_arriba": None, "primero_crudo": None, "margen_primero": None, "ninguno": None})}, tg)


# ---------- contexto actual ----------
def context(bnc, bgx, closes_1h):
    rows = []

    def add(key, title, value, signal, detail):
        rows.append({"tabla": "contexto", "clave": key, "titulo": title, "valor": value, "senal": signal, "detalle": detail})

    oi = [x["openInterestValue"] for x in api("binanceusdm", bnc.fetch_open_interest_history, SYMBOL, "1h", limit=25)]
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

    taker = api("binanceusdm", bnc.fapiDataGetTakerlongshortRatio, {"symbol": "BTCUSDT", "period": "1h", "limit": 4})
    buy, sell = sum(float(x["buyVol"]) for x in taker), sum(float(x["sellVol"]) for x in taker)
    for name, r in (("1 h", float(taker[-1]["buySellRatio"])), ("4 h", buy / sell)):
        sig = "alcista" if r > 1.1 else "bajista" if r < 0.9 else "neutral"
        add(f"flujo_{name}", f"Compras vs ventas a mercado {name}", ar(r, 2), sig,
            "Dominan los compradores agresivos" if sig == "alcista" else
            "Dominan los vendedores agresivos" if sig == "bajista" else "Flujo equilibrado")

    ls = api("binanceusdm", bnc.fetch_long_short_ratio_history, SYMBOL, "1h", limit=25)
    now_ls, prev_ls = ls[-1]["longShortRatio"], ls[0]["longShortRatio"]
    top = float(api("binanceusdm", bnc.fapiDataGetTopLongShortPositionRatio, {"symbol": "BTCUSDT", "period": "1h", "limit": 1})[-1]["longShortRatio"])
    if now_ls > 2:
        crowd, sig = "Mayoría long: si cae, puede haber cascada de liquidaciones", "bajista"
    elif now_ls < 0.9:
        crowd, sig = "Mayoría short: si sube, puede haber squeeze", "alcista"
    else:
        crowd, sig = "Posicionamiento parejo", "neutral"
    add("long_short", "Cuentas long / short", f"{ar(now_ls, 2)} (24 h antes {ar(prev_ls, 2)}, top traders {ar(top, 2)})", sig, crowd)

    fr = api("bingx", bgx.fetch_funding_rate, SYMBOL).get("fundingRate") or 0.0
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
            book = api(eid, ex.fetch_order_book, SYMBOL, limit=limit)
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
    rows = api(ex.id, ex.fetch_ohlcv, SYMBOL, tf, limit=2)
    live = [c for c in rows if c[0] > last_closed_t and c[0] + tf_ms > now]
    return live[-1] if live else None


def forming_from_5m(closed_5m, live_5m, tf, last_closed_t):
    """Vela en curso de cualquier temporalidad, armada con las velas de 5m desde que abrio."""
    start = last_closed_t + ccxt.Exchange.parse_timeframe(tf) * 1000
    parts = [c for c in closed_5m if c[0] >= start] + ([live_5m] if live_5m and live_5m[0] >= start else [])
    if not parts:
        return None
    return [start, parts[0][1], max(c[2] for c in parts), min(c[3] for c in parts), parts[-1][4], sum(c[5] for c in parts)]


# ---------- registro de pronosticos ----------


def liquidation_map(bnc, h1, hours=168):
    """Liquidaciones pendientes estimadas con open interest nuevo y ratio long/short de la ultima semana."""
    oi = [(int(x["timestamp"]), x["openInterestValue"])
          for x in api("binanceusdm", bnc.fetch_open_interest_history, SYMBOL, "1h", limit=hours)]
    ls = {int(x["timestamp"]): x["longShortRatio"]
          for x in api("binanceusdm", bnc.fetch_long_short_ratio_history, SYMBOL, "1h", limit=hours)}
    bars = h1[-(hours + 2):]
    price_by_hour = {b[0] + bg.HOUR_MS: b[4] for b in bars}   # precio al cierre de cada hora
    suffix_lo, suffix_hi, lo, hi = {}, {}, float("inf"), 0.0
    for b in reversed(bars):
        suffix_lo[b[0]], suffix_hi[b[0]] = lo, hi
        lo, hi = min(lo, b[3]), max(hi, b[2])
    after = lambda t: (suffix_lo.get(t - bg.HOUR_MS, float("inf")), suffix_hi.get(t - bg.HOUR_MS, 0.0))
    return ind.mapa_liquidaciones(price_by_hour, oi, ls, after)


def liquidation_map_bybit(h1, hours=168):
    """El mismo mapa con datos de Bybit: open interest por hora (en BTC, se pasa a USD con el cierre) y la
    proporcion de cuentas compradas y vendidas."""
    ex = exchange("bybit")
    oi_raw = api("bybit", ex.publicGetV5MarketOpenInterest,
                 {"category": "linear", "symbol": "BTCUSDT", "intervalTime": "1h", "limit": 200})["result"]["list"]
    ls_raw = api("bybit", ex.publicGetV5MarketAccountRatio,
                 {"category": "linear", "symbol": "BTCUSDT", "period": "1h", "limit": 200})["result"]["list"]
    bars = h1[-(hours + 2):]
    close_at = {b[0] + bg.HOUR_MS: b[4] for b in bars}
    oi = sorted((int(x["timestamp"]), float(x["openInterest"]) * close_at[int(x["timestamp"])])
                for x in oi_raw if int(x["timestamp"]) in close_at)
    ls = {int(x["timestamp"]): float(x["buyRatio"]) / float(x["sellRatio"]) for x in ls_raw if float(x["sellRatio"]) > 0}
    price_by_hour = dict(sorted(close_at.items()))
    suffix_lo, suffix_hi, lo, hi = {}, {}, float("inf"), 0.0
    for b in reversed(bars):
        suffix_lo[b[0]], suffix_hi[b[0]] = lo, hi
        lo, hi = min(lo, b[3]), max(hi, b[2])
    after = lambda t: (suffix_lo.get(t - bg.HOUR_MS, float("inf")), suffix_hi.get(t - bg.HOUR_MS, 0.0))
    return ind.mapa_liquidaciones(price_by_hour, oi[-hours:], ls, after)


TF_TXT = {"5m": "5 min", "15m": "15 min", "30m": "30 min", "1h": "1 hora", "4h": "4 horas", "1d": "diario"}
NO_LINES = {"l1_t": None, "l1_p": None, "l1_m": None, "l1_nombre": None, "l2_t": None, "l2_p": None, "l2_m": None,
            "l2_nombre": None, **{f"pt{k}_{f}": None for k in (1, 2, 3, 4, 5) for f in ("t", "p", "nombre")}}


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
    # una figura clasica y, aparte, un esquema de Wyckoff si lo hay
    for g in (ind.patron_grafico(bars, pivots, atr_[i]), ind.wyckoff(bars, pivots, atr_[i])):
        if not g:
            continue
        lines = dict(NO_LINES)
        for n_, ln in enumerate(g["lineas"][:2], start=1):
            lines.update({f"l{n_}_t": ln[0], f"l{n_}_p": round(ln[1], 1), f"l{n_}_m": ln[2], f"l{n_}_nombre": ln[3]})
        for n_, pt in enumerate(g["puntos"][:5], start=1):
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
    # RSI y MACD de cada temporalidad, como los mira un trader
    for tf in sig_tfs:
        m = get("marco", tf=tf)[0]
        if m["rsi"] >= 70:
            signals.append((4, "bajista", f"RSI de {TF_TXT[tf]} en sobrecompra ({ar(m['rsi'])})"))
        elif m["rsi"] <= 30:
            signals.append((4, "alcista", f"RSI de {TF_TXT[tf]} en sobreventa ({ar(m['rsi'])})"))
        if m["macd_cruce"]:
            signals.append((4, m["macd_cruce"], f"MACD de {TF_TXT[tf]} cruzó {'al alza' if m['macd_cruce'] == 'alcista' else 'a la baja'}"))
    for p in get("patron"):
        if p["tf"] not in sig_tfs or p["sesgo"] == "neutral":
            continue
        target = f" → {ap(p['objetivo'])}" if p["objetivo"] else ""
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
                        f"Elliott {TF_TXT[sig_tfs[-1]]}: {m_last['elliott_corto'].split(':')[0]} → {ap(m_last['elliott_objetivo'])}"))
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
        head = f"Hasta las {hh} h, es más probable que BTC suba a {ap(up)} ({ar(pu)}%) antes que baje a {ap(dn)}."
    elif pu is not None and 50 - pu > max(5, mg):
        bias = "bajista"
        head = f"Hasta las {hh} h, es más probable que BTC baje a {ap(dn)} ({ar(100 - pu)}%) antes que suba a {ap(up)}."
    else:
        bias = "neutral"
        head = f"Hasta las {hh} h, sin dirección clara: lo esperable es que BTC se mueva entre {ap(dn)} y {ap(up)}."
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
        out.append(row(k, "vigilar", "alcista", f"Resistencia {ap(res['precio'])} ({lc1(res['nombre'])})", res["precio"]))
    if sup:
        out.append(row(k + 1, "vigilar", "bajista", f"Soporte {ap(sup['precio'])} ({lc1(sup['nombre'])})", sup["precio"]))
    if bias == "alcista" and sup:
        inval = f"Si una vela de {candle} cierra debajo de {ap(sup['precio'])}, la idea deja de valer."
    elif bias == "bajista" and res:
        inval = f"Si una vela de {candle} cierra arriba de {ap(res['precio'])}, la idea deja de valer."
    else:
        inval = f"La dirección la marca la primera vela de {candle} que cierre fuera de {ap(dn)} a {ap(up)}."
    out.append(row(k + 2, "invalida", bias, inval))
    out.append(row(k + 3, "aprendizaje", bias, learning_text(get("aprendizaje", plazo=name)[0])))
    return out


def learning_text(a):
    """En una o dos frases: que aprendio para este plazo y si le esta sirviendo (contra la tasa base)."""
    if not a["repasadas"]:
        return "Todavía junta experiencia para este plazo: por ahora usa el método original."
    txt = (f"Repasó sus últimas {ar(a['repasadas'])} predicciones con un equipo de expertos; hoy pesa más "
           f"{a['lider']}. {a['confianza']}.")
    hab = a["habilidad"]
    if hab is not None:
        if hab >= 0.5:
            txt += f" Le gana a la tasa base: {ar(hab, 1)}% menos error que decir siempre lo normal."
        elif hab > -0.5:
            txt += f" Todavía no le gana a la tasa base en forma clara ({ar(hab, 1)}%): sus probabilidades quedan cerca de lo normal."
        else:
            txt += f" Viene peor que la tasa base ({ar(hab, 1)}%): por eso modera sus probabilidades."
    ap, lo, hi = a["aciertos_aprendido"], a["ic_bajo"], a["ic_alto"]
    if ap is not None and lo is not None:
        txt += f" Acertó {ar(ap)}% qué tocaba primero (con el margen de error, entre {ar(lo)}% y {ar(hi)}%)."
    return txt


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
    try:
        bnc = exchange("binanceusdm")
    except (ccxt.DDoSProtection, ccxt.RateLimitExceeded):
        bnc = None          # Binance bloqueo la IP: velas de Bybit y, por ahora, sin los datos que solo da Binance
    bgx, src = exchange("bingx"), candle_source()
    # los pedidos de red van en paralelo: velas de todas las temporalidades a la vez, y los libros de ordenes
    # (que se piden como mucho cada 20 s) se bajan mientras se calcula lo demas
    pool = ThreadPoolExecutor(max_workers=8)
    books_job = pool.submit(cached, "libros", 20, order_books)
    jobs = {tf: pool.submit(update_candles, src, tf, days) for tf, (days, _) in TIMEFRAMES.items()}
    candles = {tf: job.result() for tf, job in jobs.items()}
    global ULTIMAS_VELAS
    ULTIMAS_VELAS = candles          # velas cerradas: las usan los avisos (setups) en el modo en vivo
    # el analisis incluye la vela en curso de cada temporalidad (como TradingView): los indicadores, patrones y
    # escenarios se mueven con el precio. Todas salen de la vela de 5m en curso: un solo pedido.
    # El cache y el registro de aciertos siguen usando solo velas cerradas.
    try:
        live_5m = current_candle(src, "5m", candles["5m"][-1][0])
    except Exception:       # sin la vela en curso, el analisis igual sirve con las cerradas
        live_5m = None
    full = {}
    for tf in TIMEFRAMES:
        bar = live_5m if tf == "5m" else forming_from_5m(candles["5m"], live_5m, tf, candles[tf][-1][0])
        full[tf] = candles[tf] + [bar] if bar else candles[tf]
    price = float(api("bingx", bgx.fetch_ticker, SYMBOL)["last"])
    now_ms = int(time.time() * 1000)
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
        ml, ms, mh = ind.macd(closes)
        warmup = min(200, len(bars) // 3)
        feats = apr.rasgos(bars, tf_min, e50, e200, rsi, mh)
        X = apr.continuos(bars, tf_min, e50, e200, rsi, mh, partial)
        base = range(warmup, len(bars) - 1 - max(horizons))
        series[tf] = {"bars": bars, "closes": closes, "base": list(base), "tf_ms": tf_ms, "tf_min": tf_min, "days": days,
                      "closed": candles[tf], "feats": feats, "combo": apr.combos(feats), "X": X, "warmup": warmup,
                      "last": len(bars) - 1 - max(horizons + (SCENARIO_STEPS,)), "similar": {}, "fit": {},
                      "vol": {}, "partial": partial}
        main_fit = tune(tf, series[tf], horizons[0])
        idxs, keep = main_fit["idxs"], main_fit["keep"]
        i = len(bars) - 1
        trend = trend_word(closes[i], e20[i], e50[i], e200[i])
        by_tf[tf] = {"summary": summary, "trend": trend}
        pivots = ind.zigzag(bars)
        wave_labels, wave_desc, wave_target, wave_now, wave_short = ind.elliott(pivots, bars)
        # cruce del MACD con su senal en la ultima o la anteultima vela
        crosses = ("alcista" if mh[k] > 0 and mh[k - 1] <= 0 else "bajista" if mh[k] < 0 and mh[k - 1] >= 0 else None
                   for k in (i, i - 1))
        cross = next((x for x in crosses if x), None)
        rows.append({"tabla": "marco", "tf": tf, "tendencia": trend, **summary, "macd_cruce": cross,
                     "ema50": round(e50[i], 1), "ema200": round(e200[i], 1), "similares": len(idxs),
                     "criterio": apr.receta_txt(main_fit["receta"], keep) if keep else "",
                     "elliott": wave_desc, "elliott_objetivo": None if wave_target is None else round(wave_target, 1),
                     "elliott_curso": wave_now, "elliott_corto": wave_short})
        rows += [{"tabla": "indicador", "tf": tf, **r} for r in ind_rows]
        tail = pivots[-10:]
        offset = len(tail) - len(wave_labels)
        for n, (kind, k, p) in enumerate(tail):
            rows.append({"tabla": "giro", "tf": tf, "t": bars[k][0], "precio": round(p, 1), "tipo": kind,
                         "onda": wave_labels[n - offset] if n >= offset else "", "en_curso": n == len(tail) - 1})
        rows += [{"tabla": "fvg", "tf": tf, "tipo": z["tipo"], "t": z["t"], "bajo": round(z["bajo"], 1),
                  "alto": round(z["alto"], 1)} for z in ind.fvg(bars)]
        rows += patterns(tf, bars, pivots, e20, horizons[0], tf_min, partial)
        rows += [{"tabla": "divergencia", "tf": tf, **d, "p1": round(d["p1"], 1), "p2": round(d["p2"], 1)}
                 for d in ind.divergencias(bars, pivots)]

        for h in horizons:
            prob, tg = horizon_stats(tf, series[tf], h, price, tune(tf, series[tf], h))
            rows.append({"tabla": "probabilidad", **prob})
            rows += [{"tabla": "objetivo", "tf": tf, "horizonte": prob["horizonte"], "hora": prob["hora"], **t} for t in tg]
            entries.append((bars[-1][0] + tf_ms, tf, h, closes[-1], prob["sube"]))

        sc, cone = scenarios(bars, idxs, price, tf_ms, vol_factor(series[tf], SCENARIO_STEPS))
        for r in sc + cone:
            r["tf"] = tf
        rows += sc + cone
        for k in range(max(0, i - CHART_BARS + 1), i + 1):
            t, o_, h_, l_, c_, v_ = bars[k]
            rows.append({"tabla": "vela", "tf": tf, "t": t, "o": o_, "h": h_, "l": l_, "c": c_, "v": round(v_, 2),
                         "en_curso": partial and k == i,
                         "ema20": round(overlays["ema20"][k], 1), "ema50": round(overlays["ema50"][k], 1),
                         "bb_up": None if overlays["bb_up"][k] is None else round(overlays["bb_up"][k], 1),
                         "bb_lo": None if overlays["bb_lo"][k] is None else round(overlays["bb_lo"][k], 1),
                         "rsi": None if rsi[k] is None else round(rsi[k], 1), "macd": round(ml[k], 2),
                         "macd_senal": round(ms[k], 2), "macd_hist": round(mh[k], 2)})

    # una prediccion por plazo, cada una con la temporalidad que mas casos tiene para ese plazo
    for name, tf, h, *_ in PLAZOS:
        fit = tune(tf, series[tf], h)
        prob, tg = horizon_stats(tf, series[tf], h, price, fit)
        rows.append({"tabla": "plazo", "plazo": name, **prob})
        rows += learning_rows(name, tf, h, fit)
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
        if bnc is None:
            raise ccxt.DDoSProtection("Binance bloqueado")
        ctx, funding = cached("contexto", 60, lambda: context(bnc, bgx, [b[4] for b in h1]))
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
        # Binance suele bloquear la IP de Render: entonces se arma con open interest y long/short de Bybit
        heat = cached("liquidaciones", 300, lambda: liquidation_map(bnc, h1) if bnc is not None else liquidation_map_bybit(h1))
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

    mov = movimiento(candles["5m"], price)
    if mov:
        rows.append(mov)
    explanation = [e for spec in PLAZOS for e in explain(rows, price, spec)]
    rows += explanation
    takeaway = next(e["texto"] for e in explanation if e["plazo"] == "1 hora" and e["tipo"] == "titular")
    local = datetime.fromtimestamp(now_ms / 1000, LOCAL_TZ)
    rows.insert(0, {"tabla": "resumen", "fecha": datetime.now(LOCAL_TZ).isoformat(timespec="milliseconds"),
                    "hora_local": local.strftime("%d/%m %H:%M"), "precio": round(price, 1),
                    "cambio_24h": round2(change_since(candles["5m"], now_ms, price, 24)),
                    "cambio_7d": round2(change_since(candles["5m"], now_ms, price, 168)),
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
            extra = f", objetivo {ap(p['objetivo'])}" if p["objetivo"] else f", funcionó {ar(p['exito'])}% de {p['casos']}" if p["exito"] else ""
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
html { touch-action: manipulation; }   /* sin zoom por doble toque en el telefono */
body { margin: 0; background: var(--color-bg); color: var(--color-fg); font: 14px var(--font-anthropic-sans); }
#dash-root { padding-block: 24px 40px; padding-left: max(16px, var(--dash-gutter, 24px)); padding-right: max(16px, var(--dash-gutter, 24px)); }
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<script>
(function () {
  var rows = __DATA__, fns = [], pageVersion = __PAGEV__;
  // modo en vivo (servido por analisis_btc.py --vivo): la pagina se conecta a Binance y trae cada analisis nuevo
  window.abLive = __LIVE__;
  if (window.abLive) {
    setInterval(function () {
      fetch('analisis_btc.json', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (d) {
        if (d.pagina && d.pagina !== pageVersion) { location.reload(); return; }   // cambio el diseno: pagina nueva
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


def save_json(path, data):
    """Se escribe aparte y se reemplaza de una vez: quien lo lee nunca ve un archivo a medias."""
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    replace_file(path + ".tmp", path)


def write_waiting_page(path, message, error=""):
    """Pantalla mientras no hay analisis: se recarga sola y pasa al dashboard cuando esta listo."""
    import html
    extra = f'<pre class="err">{html.escape(error)}</pre><p>Si se repite, pasale este error a Claude.</p>' if error else ""
    page = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="refresh" content="5">
<title>Analista BTC</title><style>
body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: #121418; color: #e8eaee;
  font: 16px system-ui, sans-serif; padding: 24px; box-sizing: border-box; }}
main {{ max-width: 34rem; display: grid; gap: 12px; }} h1 {{ font: 400 2rem Georgia, serif; margin: 0; }}
p {{ margin: 0; color: #949bab; line-height: 1.5; }} .err {{ white-space: pre-wrap; background: #2a1517; color: #f0645a;
  padding: 12px; border-radius: 8px; font: 13px monospace; margin: 0; }}
.dot {{ width: 10px; height: 10px; border-radius: 50%; background: #3cc58a; animation: p 1.2s infinite alternate; }}
@keyframes p {{ to {{ opacity: .2; }} }}
</style></head><body><main><div class="dot"></div><h1>Analista BTC</h1><p>{html.escape(message)}</p>{extra}
<p>Esta página se actualiza sola.</p></main></body></html>"""
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(page)
    replace_file(path + ".tmp", path)


def page_version():
    return round(os.path.getmtime(PAGE_FILE), 3)


def write_local_html(data, path=LOCAL_HTML, live=False):
    """La misma pagina del dashboard, con los datos de este analisis adentro."""
    with open(PAGE_FILE, encoding="utf-8") as f:
        page = f.read()
    rows = json.dumps(data["rows"], ensure_ascii=False).replace("</", "<\\/")
    html = (LOCAL_SHELL.replace("__DATA__", rows).replace("__LIVE__", "true" if live else "false")
            .replace("__PAGEV__", json.dumps(page_version())).replace("__PAGE__", page))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(html)
    replace_file(tmp, path)


# el modo en vivo publica SOLO esta carpeta, y solo en esta PC: nunca el proyecto entero (ahi esta el .env)
LIVE_DIR = os.path.join(DATA_DIR, "vivo")
LIVE_PORT = 8765


def run_live(every, public=False):
    """Recalcula el analisis cada `every` segundos y lo sirve hasta Ctrl+C.

    Local: en http://127.0.0.1:8765. Publico (--servidor, para Render): en todas las interfaces y en el puerto
    de la variable PORT, y siempre con la contrasena de la variable VIVO_CLAVE.
    """
    import functools
    import http.server
    import importlib
    import threading
    import time
    import webbrowser

    # el analisis corre desde el modulo (no desde este script) para poder recargarlo cuando cambia el codigo
    import analisis_btc as live_mod
    code_files = [live_mod.__file__, ind.__file__, apr.__file__]
    code_stamp = [os.path.getmtime(f) for f in code_files]
    page_stamp = None

    password = os.environ.get("VIVO_CLAVE", "")
    if public and len(password) < 8:
        raise SystemExit("Para publicar el dashboard hace falta la variable VIVO_CLAVE con al menos 8 caracteres.")

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/salud":            # para que Render sepa que el servicio anda; no muestra datos
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ok")
                return
            if password and not self.authorized():
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="Analista BTC", charset="UTF-8"')
                self.end_headers()
                return
            super().do_GET()

        def do_HEAD(self):
            if password and not self.authorized():
                self.send_response(401)
                self.end_headers()
                return
            super().do_HEAD()

        def list_directory(self, path):
            self.send_error(404)                 # nunca se muestra el contenido de la carpeta
            return None

        def authorized(self):
            """Usuario cualquiera; vale la contrasena. Se compara en tiempo constante."""
            import base64
            import hmac
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Basic "):
                return False
            try:
                given = base64.b64decode(auth[6:]).decode("utf-8").split(":", 1)[1]
            except Exception:
                return False
            return hmac.compare_digest(given.encode(), password.encode())

    host, port = ("0.0.0.0", int(os.environ.get("PORT", LIVE_PORT))) if public else ("127.0.0.1", LIVE_PORT)
    os.makedirs(LIVE_DIR, exist_ok=True)
    index = os.path.join(LIVE_DIR, "index.html")
    if public or not os.path.exists(index):     # hasta que termine el primer analisis
        write_waiting_page(index, "Preparando el primer análisis: baja el historial de velas y calcula todo. "
                                  "Puede tardar uno o dos minutos.")
    server = http.server.ThreadingHTTPServer((host, port), functools.partial(Quiet, directory=LIVE_DIR))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    print(f"Modo en vivo: {'publicado en el puerto ' + str(port) if public else url} (recalcula cada {every} s, Ctrl+C para salir)",
          flush=True)
    first = True
    if public:
        avisos.mantener_despierto()
    try:
        while True:
            started = time.time()
            try:
                stamp = [os.path.getmtime(f) for f in code_files]
                if stamp != code_stamp:
                    importlib.reload(ind)
                    importlib.reload(apr)
                    live_mod = importlib.reload(live_mod)
                    code_stamp = stamp
                    print("Código del análisis actualizado: se usa la versión nueva desde este análisis.")
                data = {"rows": live_mod.analyze(), "pagina": page_version()}
                try:
                    avisos.revisar(data["rows"], getattr(live_mod, "ULTIMAS_VELAS", None))   # WhatsApp / notificacion
                except Exception as e:
                    print(f"(avisos: {type(e).__name__}: {e})", flush=True)
                save_json(OUT_FILE, data)
                save_json(os.path.join(LIVE_DIR, "analisis_btc.json"), data)
                if data["pagina"] != page_stamp:   # al arrancar, o si cambio el diseno: la pagina se recarga sola
                    write_local_html(data, os.path.join(LIVE_DIR, "index.html"), live=True)
                    if page_stamp is not None:
                        print("Diseño del dashboard actualizado: la página se recarga sola.")
                    page_stamp = data["pagina"]
                if first and not public:
                    webbrowser.open(url)
                first = False
                head = next(r for r in data["rows"] if r["tabla"] == "resumen")
                print(f"{time.strftime('%H:%M:%S')}  BTC {ar(head['precio'], 1)}  ({time.time() - started:.1f} s)  {head['lectura']}",
                      flush=True)
            except Exception as e:  # un corte de red no tiene que frenar el modo en vivo
                import traceback
                print(f"(no se pudo actualizar: {type(e).__name__}: {e})", flush=True)
                traceback.print_exc()
                if page_stamp is None:            # todavia no hay dashboard: el error se ve en la pantalla de espera
                    if isinstance(e, (ccxt.DDoSProtection, ccxt.RateLimitExceeded)):
                        write_waiting_page(index, "Un exchange limitó los pedidos desde este servidor. "
                                                  "En el próximo intento se usan otras fuentes; no hace falta hacer nada.")
                    else:
                        write_waiting_page(index, "El análisis falló y se vuelve a intentar solo.",
                                           f"{time.strftime('%H:%M:%S')}  {type(e).__name__}: {e}")
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
    ap.add_argument("--servidor", action="store_true",
                    help="con --vivo: publicar en internet (Render), con la contrasena de la variable VIVO_CLAVE")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # la consola de Windows no siempre es UTF-8
    if args.vivo:
        run_live(max(5, args.vivo), public=args.servidor)
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
    save_json(OUT_FILE, data)
    print(f"\nGuardado {OUT_FILE} ({os.path.getsize(OUT_FILE) / 1024:.0f} KB)")
    if os.path.exists(PAGE_FILE):
        write_local_html(data)
        print(f"Dashboard local: {LOCAL_HTML}")
        if args.abrir:
            import webbrowser
            webbrowser.open("file:///" + LOCAL_HTML.replace("\\", "/"))


if __name__ == "__main__":
    main()
