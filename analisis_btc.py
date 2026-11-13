"""
Analisis de mercado de BTC/USDT perpetuo, de 5 minutos a diario (APIs publicas, sin keys).

Uso:
    .venv\\Scripts\\python.exe analisis_btc.py                 # analiza, imprime y guarda data/analisis_btc.json
    .venv\\Scripts\\python.exe analisis_btc.py --abrir         # ademas abre el dashboard local (reporte_btc.html)
    .venv\\Scripts\\python.exe analisis_btc.py --vivo          # dashboard en vivo en http://127.0.0.1:8765
    .venv\\Scripts\\python.exe analisis_btc.py --nota nota.txt # agrega la lectura de noticias al ultimo analisis

Fuentes:
- Bybit: velas, open interest y ratio long/short. OKX: flujo de compras/ventas agresivas y top traders.
- BingX: precio, libro de ordenes y funding (cada 3 h) del perpetuo donde operas. A Binance no se le pide nada.

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
import bisect
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
import historial
import util as bg   # HOUR_MS, DATA_DIR y reintentar (antes de backtest_grid.py)
import indicadores as ind
import fuerte
import termometro
import noticias

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
        return bg.reintentar(fn, *args, **kwargs)
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
    """Bybit. A Binance no se le pide nada: bloquea la IP de Render si se le pide mucho."""
    return exchange("bybit")


FUNDING_TTL = 3 * 3600



# las velas semanales y mensuales salen de las diarias: con toda la historia (desde que cotiza el futuro, como
# TradingView) sus EMA 50 y 200 dan lo mismo que en el grafico del exchange. Con 1.500 dias la EMA 200 semanal
# arrancaba en 2022 y quedaba corrida. El analisis diario (y el termometro) siguen con sus 1.500 dias.
DIAS_LARGOS = 3000


def update_candles(ex, tf, days, archivo=None):
    """Velas cerradas con cache incremental en data/ (un archivo por exchange)."""
    name = "binance" if ex.id == "binanceusdm" else ex.id
    path = os.path.join(DATA_DIR, f"BTC_USDT_{name}_perp_{archivo or tf}.csv")
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


def dec_precio(x):
    """Decimales para guardar un precio: 1 para BTC (desde 1.000), 2 desde 100, 3 desde 10 y 4 debajo (XRP)."""
    x = abs(x)
    return 1 if x >= 1000 else 2 if x >= 100 else 3 if x >= 10 else 4


def rp(x):
    """Precio redondeado con los decimales que pide su tamaño."""
    return None if x is None else round(x, dec_precio(x))


def ap(x):
    """Precio: sin decimales desde 1.000 (BTC), dos desde 10 (ZEC, SOL) y cuatro debajo (XRP)."""
    return ar(x, 0 if abs(x) >= 1000 else 2 if abs(x) >= 10 else 4)


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
             "ZEC": {"prob": (7, 8, 14, 24, 35, 50, 69), "veces": (0.87, 0.94, 1.11, 1.38, 1.6, 2.0, 3.7), "base": 11},
             "SOL": {"prob": (7, 9, 16, 26, 40, 61, 76), "veces": (0.84, 0.94, 1.14, 1.41, 1.77, 2.39, 3.52), "base": 12},
             "XRP": {"prob": (9, 11, 18, 29, 39, 53, 87), "veces": (0.84, 0.94, 1.13, 1.43, 1.68, 2.15, 4.96), "base": 14},
             # BABA: perpetuo de la accion de Alibaba (Binance, desde mediados de 2026: ~5 meses de velas de 5 min)
             "BABA": {"prob": (13, 24, 24, 48, 65, 86, 100), "veces": (0.75, 1.15, 1.17, 1.94, 2.56, 3.56, 4.57), "base": 22},
             # NVDA, GOOGL y AMD: perpetuos de las acciones en Binance (desde mediados de 2026)
             "NVDA": {"prob": (7, 26, 34, 46, 69, 89, 100), "veces": (0.71, 1.29, 1.55, 1.85, 2.56, 3.48, 7.52), "base": 22},
             "GOOGL": {"prob": (10, 25, 36, 50, 58, 96, 100), "veces": (0.78, 1.13, 1.55, 1.95, 2.41, 4.17, 3.31), "base": 23},
             "AMD": {"prob": (7, 20, 31, 40, 69, 79, 100), "veces": (0.69, 1.17, 1.42, 1.77, 2.56, 3.43, 4.13), "base": 20},
             # AAPL, MSFT, AMZN, SPCX, META, TSLA y QQQ: futuros de Binance desde enero-mayo de 2026
             "AAPL": {"prob": (10, 23, 33, 54, 72, 93, 100), "veces": (0.76, 1.15, 1.41, 2.21, 2.99, 3.75, 4.1), "base": 22},
             "MSFT": {"prob": (9, 22, 34, 40, 75, 91, 100), "veces": (0.75, 1.2, 1.44, 1.79, 2.8, 4.43, 4.33), "base": 22},
             "AMZN": {"prob": (9, 24, 34, 55, 66, 93, 94), "veces": (0.73, 1.23, 1.5, 2.14, 2.67, 3.87, 4.18), "base": 22},
             "SPCX": {"prob": (9, 33, 41, 60, 67, 84, 92), "veces": (0.62, 1.34, 1.68, 2.41, 2.73, 4.48, 4.03), "base": 24},
             "META": {"prob": (11, 28, 36, 52, 78, 92, 100), "veces": (0.75, 1.27, 1.55, 2.13, 3.18, 4.94, 6.39), "base": 25},
             "TSLA": {"prob": (9, 29, 40, 57, 82, 89, 100), "veces": (0.71, 1.37, 1.72, 2.23, 3.48, 4.71, 6.85), "base": 25},
             "QQQ": {"prob": (5, 15, 25, 50, 61, 61, 50), "veces": (0.72, 1.11, 1.35, 2.01, 2.31, 2.5, 2.4), "base": 18},
             "SPY": {"prob": (5, 15, 24, 48, 63, 70, 100), "veces": (0.77, 1.03, 1.32, 1.94, 2.36, 2.43, 2.33), "base": 17},   # S&P 500, Binance desde abril 2026
             # MELI: no cotiza en Binance; velas de 5 min de Bitget (desde agosto de 2026, ~3 meses)
             "MELI": {"prob": (20, 25, 36, 54, 59, 92, 0), "veces": (0.95, 1.36, 1.56, 2.14, 2.68, 4.1, 1.79), "base": 28}}


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
    t = MOV_TABLA.get(moneda)
    if t is None:             # MSTR: pocas semanas de historia, sin tabla medida (no se inventa)
        return None
    nivel = "Calma" if vol < 0.8 else "Normal" if vol < 1.3 else "Agitado" if vol < 1.8 else "Se despertó"
    return {"tabla": "movimiento", "volatilidad": round(vol, 2), "nivel": nivel, "prob_fuerte": t["prob"][k],
            "prob_normal": t["base"], "veces": t["veces"][k], "normal_pct": round(normal * 100, 2),
            "esperado_pct": round(normal * t["veces"][k] * 100, 2), "normal_usd": rp(normal * price),
            "esperado_usd": rp(normal * t["veces"][k] * price), "despierto": vol > 1.8 and serie[-7] <= 1.8}


# ---------- cuando se mueve: horas de la semana (velas de 1 hora cerradas) ----------
# Medido con BTC (medir_fuerza.py): la forma del movimiento por hora de la semana se mantiene (2021-24 contra 2025-26:
# correlacion 0,93) y las 20 franjas mas movidas segun 2021-24 se movieron 1,5 veces lo de una hora tipica en 2025-26
# (las 20 menos: 0,48). Cada hora se mide contra el promedio de su semana, para que no pesen los meses agitados.
HORAS_N, HORAS_MIN = 24 * 365, 24 * 7 * 8


def _mediana(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def perfil_horas(c1h):
    if not c1h or len(c1h) < HORAS_MIN:
        return None
    bars = c1h[-HORAS_N:]
    H_, S_ = 3_600_000, 7 * 86_400_000
    suma, cuenta = {}, {}
    for b in bars:
        w = b[0] // S_
        suma[w] = suma.get(w, 0.0) + (b[2] - b[3]) / b[1]
        cuenta[w] = cuenta.get(w, 0) + 1
    franjas = [[] for _ in range(168)]
    for b in bars:
        w = b[0] // S_
        m = suma[w] / cuenta[w]
        if m > 0:
            franjas[(b[0] // H_) % 24 + 24 * ((b[0] // 86_400_000 + 3) % 7)].append((b[2] - b[3]) / b[1] / m)
    med = [_mediana(f) if f else None for f in franjas]
    vals = [x for x in med if x is not None]
    if len(vals) < 168:
        return None
    prom = sum(vals) / len(vals)
    t0 = bars[-1][0] + H_                      # la hora que esta corriendo
    prox = []
    for k in range(24):
        t = t0 + k * H_
        prox.append([t, round(med[(t // H_) % 24 + 24 * ((t // 86_400_000 + 3) % 7)] / prom, 2)])
    mx = max(prox, key=lambda x: x[1])
    mn = min(prox, key=lambda x: x[1])
    return {"tabla": "horas", "proximas": prox, "max_t": mx[0], "max_f": mx[1], "min_t": mn[0], "min_f": mn[1],
            "ahora_f": prox[0][1], "corr": 0.93, "top_x": 1.5}


# ---------- compresion de las Bollinger (velas de 1 hora cerradas) ----------
# Medido con BTC 2021-2026 (medir_compresion.py): con el ancho entre el 10% mas angosto de 30 dias, el rango de las 24 h
# siguientes fue en mediana 1,6-1,7 veces el de las 24 h anteriores y mas del doble el 32-43% de las veces (una hora
# cualquiera: x1,0 y 12-15%). Contra lo habitual de largo plazo, las horas siguientes son MAS tranquilas: el movimiento
# sale de una base muy chica. No dice para donde. En el modelo de movimiento fuerte no mejoro (ya lo ve por la volatilidad).
COMP_N, COMP_CORTE = 720, 10


def compresion(c1h):
    if not c1h or len(c1h) < COMP_N + 20:
        return None
    ancho = []
    for i in range(len(c1h) - COMP_N, len(c1h)):
        s = s2 = 0.0
        for k in range(i - 19, i + 1):
            s += c1h[k][4]
            s2 += c1h[k][4] * c1h[k][4]
        mu = s / 20
        sd = math.sqrt(max(0.0, s2 / 20 - mu * mu))
        ancho.append(4 * sd / mu)
    hoy = ancho[-1]
    pct = sum(1 for x in ancho if x < hoy) / len(ancho) * 100
    hi = max(b[2] for b in c1h[-24:])
    lo = min(b[3] for b in c1h[-24:])
    return {"tabla": "compresion", "ancho_pct": round(hoy * 100, 2), "percentil": round(pct, 1), "comprimida": pct <= COMP_CORTE,
            "rango_24h": rp(hi - lo), "expande": 1.6, "mas_doble": 40, "mas_doble_normal": 13}


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
    return {"n": len(rets), "up": sum(r > 0 for r in rets) / len(rets) * 100, "p10": q(0.1), "p50": q(0.5), "p90": q(0.9)}


# ---------- rango del 80% honesto (calibracion "conformal" con su propio pasado) ----------
# Para las ultimas CAL_PUNTOS predicciones del pasado (cada h velas: no se pisan) arma el rango del 80% que habria dado
# ahi (los casos parecidos que habia hasta ese momento, llevados a la volatilidad de ese momento) y mide donde termino
# el precio, en "anchos de rango" desde la mediana: 1 es justo en el borde. El factor k que deja adentro al 80% de esas
# predicciones ensancha (k > 1) o angosta (k < 1) el rango de ahora. Igual en analisis.js (rangoPuntajes, rangoFactor).
CAL_PUNTOS, CAL_MIN, CAL_K = 200, 60, (0.6, 2.0)


def rango_grupos(st, warmup, j_max):
    """Velas de cada situacion (con 4, 3, 2 y 1 rasgos), en orden. No depende del horizonte: se arma una vez por receta."""
    grupos = {}
    for i in range(warmup, j_max + 1):
        e = st[i]
        if e:
            for keep in (4, 3, 2, 1):
                grupos.setdefault((keep, tuple(e[:keep])), []).append(i)
    return grupos


def rango_puntajes(closes, st, F, h, warmup, j_max, puntos=CAL_PUNTOS, ventana=None, grupos=None):
    """[(vela, puntaje)] de las ultimas `puntos` predicciones con resultado conocido (j <= j_max), de la mas nueva a
    la mas vieja. st: la situacion de cada vela (apr.estados). F: vol_escala (o None). ventana: solo casos de las
    ultimas `ventana` velas antes de cada prediccion (como el analisis en vivo, que tiene una ventana de historia).
    grupos: rango_grupos ya armado (con mas velas no cambia nada: solo se usan las de antes de j - h)."""
    grupos = grupos if grupos is not None else rango_grupos(st, warmup, j_max)
    out, j = [], j_max
    while j >= warmup and len(out) < puntos:
        e = st[j]
        if e:
            desde = max(warmup, j - ventana) if ventana else warmup
            for keep in (4, 3, 2, 1):           # como similar(): la situacion mas completa con casos suficientes
                lst = grupos.get((keep, tuple(e[:keep])), [])
                a, b = bisect.bisect_left(lst, desde), bisect.bisect_right(lst, j - h)
                if b - a >= MIN_SAMPLES:
                    break
            if b - a >= 10:
                fj = F[j] if F else 1.0
                rets = sorted((closes[i + h] / closes[i] - 1) * (F[i] / fj if F else 1.0) for i in lst[a:b])
                q = lambda p: rets[min(int(p * len(rets)), len(rets) - 1)]
                q10, q50, q90 = q(0.1), q(0.5), q(0.9)
                r = closes[j + h] / closes[j] - 1
                ancho = (q90 - q50) if r >= q50 else (q50 - q10)
                if ancho > 0:
                    out.append((j, abs(r - q50) / ancho))
        j -= h
    return out


def rango_factor(puntajes):
    """El factor que deja adentro al 80% (entre CAL_K) y cuantas veces el rango sin ajustar acerto (en %)."""
    if not puntajes:
        return {"k": 1.0, "cobertura": None, "casos": 0}
    xs = sorted(p for _, p in puntajes)
    cob = sum(1 for x in xs if x <= 1) / len(xs) * 100
    if len(xs) < CAL_MIN:
        return {"k": 1.0, "cobertura": cob, "casos": len(xs)}
    k = xs[min(int(0.8 * len(xs)), len(xs) - 1)]
    return {"k": min(CAL_K[1], max(CAL_K[0], k)), "cobertura": cob, "casos": len(xs)}


def calibracion(s, receta, h):
    """rango_factor de una temporalidad, una receta y un horizonte (una sola vez por analisis). Medido 2023-2026 sin
    mirar el futuro (medir_contexto.py): con velas de hasta 1 hora el rango ajustado termina adentro 80% (sin ajustar,
    78-79,5%); con velas de 4 horas no mejoro, asi que ahi solo se mide (k = 1)."""
    key = (receta, h)
    if key not in s["cal"]:
        last = len(s["closes"]) - (2 if s["partial"] else 1)          # ultima vela cerrada
        c = s["closed"][-1]
        clave, sello = (s["tf_ms"], receta, h), (len(s["closed"]), c[0], c[4], s["warmup"])
        hit = _CAL_CACHE.get(clave)
        if hit and hit[0] == sello:                                    # solo depende de las velas cerradas
            cal = hit[1]
        else:
            if receta not in s.setdefault("grupos", {}):     # una vez por receta, para todos los horizontes
                st = apr.estados(s["feats"], receta)
                s["grupos"][receta] = (st, rango_grupos(st, s["warmup"], last))
            st, gr = s["grupos"][receta]
            cal = rango_factor(rango_puntajes(s["closes"], st, vol_factor(s, h), h, s["warmup"], last - h, grupos=gr))
            if s["tf_min"] > 60:
                cal["k"] = 1.0
            _CAL_CACHE[clave] = (sello, cal)
        s["cal"][key] = cal
    return s["cal"][key]


_CAL_CACHE = {}


def scenarios(bars, idxs, price, tf_ms, F=None, ancho=1.0):
    """Camino tipico/alcista/bajista: el camino real mas parecido a la mediana y a los percentiles 75/25.
    ancho: el ajuste del rango (calibracion): el cono se ensancha o angosta alrededor de la mediana."""
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
                            "o": rp(z(o)), "h": rp(z(h)), "l": rp(z(l)), "c": rp(z(c)),
                            "desde": datetime.fromtimestamp(bars[j][0] / 1000, timezone.utc).strftime("%Y-%m-%d")})
    p10, p50, p90 = q(0.1), q(0.5), q(0.9)
    for n in range(SCENARIO_STEPS):
        cone.append({"tabla": "cono", "tf": None, "paso": n + 1, "t": t0 + (n + 1) * tf_ms,
                     "p10": rp(price * (1 + p50[n] - ancho * (p50[n] - p10[n]))), "p50": rp(price * (1 + p50[n])),
                     "p90": rp(price * (1 + p50[n] + ancho * (p90[n] - p50[n])))})
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
        paso = unit / 10
        up_lvl, dn_lvl = round((price + unit) / paso) * paso, round((price - unit) / paso) * paso
    rel = unit / price
    first = []
    for j in usable:
        for k in range(1, h + 1):
            a, b = (bars[j + k][2] / c[j] - 1) * v(j) >= rel, (bars[j + k][3] / c[j] - 1) * v(j) <= -rel
            if a or b:
                first.append(0.5 if a and b else 1.0 if a else 0.0)
                break
    pf = sum(first) / len(first) if first else None
    close = {"mediana": rp(price * (1 + q(0.5))), "p25": rp(price * (1 + q(0.25))),
             "p75": rp(price * (1 + q(0.75))), "hora": when,
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
             "ranking": ",".join(str(r) for r in L.get("ranking", [])), "calibracion": L.get("calibracion") or []}]
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
    L = fit.get("learn") or {}
    # si en su repaso honesto no le gano a la tasa base, una diferencia contra lo normal no es una ventaja: es ruido
    sin_ventaja = L.get("habilidad") is not None and L["habilidad"] <= 0
    verdict = ("Casi moneda" if sin_ventaja or abs(edge) < max(3, margin) else
               "Sesgo alcista" if edge > 0 else "Sesgo bajista")
    when_ms = bars[-1][0] + (h + 1) * s["tf_ms"]
    when = datetime.fromtimestamp(when_ms / 1000, LOCAL_TZ).strftime("%d/%m %H:%M")
    tg, close = targets(bars, sample, price, h, when, f, L.get("distancia"), fit.get("p_primero"), F)
    cal = calibracion(s, fit["receta"], h)
    k = cal["k"]
    lo, hi = o["p50"] - k * (o["p50"] - o["p10"]), o["p50"] + k * (o["p90"] - o["p50"])
    return ({"tf": tf, "horizonte": label(h * s["tf_min"]), "velas": h,
             "sube": round(up, 1), "baja": round(100 - up, 1), "base": round(b["up"], 1),
             "sube_crudo": round(o["up"], 1), "receta": fit["receta"], "factor": f,
             "veredicto": verdict, "sin_ventaja": sin_ventaja, "n": o["n"], "dias": s["days"], "hora": when, "t_hasta": when_ms,
             "margen": round(margin, 1), "pocos_casos": o["n"] < 100,
             "min": rp(price * (1 + lo / 100)), "max": rp(price * (1 + hi / 100)),
             "rango_k": round(k, 2), "rango_cobertura": None if cal["cobertura"] is None else round(cal["cobertura"], 1),
             "rango_casos": cal["casos"],
             **(close or {"mediana": None, "p25": None, "p75": None, "obj_arriba": None, "obj_abajo": None,
                          "distancia": None, "toca_arriba": None, "toca_abajo": None,
                          "primero_arriba": None, "primero_crudo": None, "margen_primero": None, "ninguno": None})}, tg)


# ---------- contexto actual ----------
def context(bgx, h1):
    """Open interest y long/short de Bybit, flujo y top traders de OKX, funding de BingX (cada 3 h)."""
    rows = []
    closes_1h = [b[4] for b in h1]

    def add(key, title, value, signal, detail, **num):
        rows.append({"tabla": "contexto", "clave": key, "titulo": title, "valor": value, "senal": signal, "detalle": detail, **num})

    byb, okx = exchange("bybit"), exchange("okx")
    try:
        close_at = {b[0] + bg.HOUR_MS: b[4] for b in h1}
        raw = api("bybit", byb.publicGetV5MarketOpenInterest,
                  {"category": "linear", "symbol": "BTCUSDT", "intervalTime": "1h", "limit": 30})["result"]["list"]
        oi = [v for _, v in sorted((int(x["timestamp"]), float(x["openInterest"]) * close_at[int(x["timestamp"])])
                                   for x in raw if int(x["timestamp"]) in close_at)]
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
            add(f"oi_{hrs}h", f"Open interest {hrs} h", f"{arp(d_oi)} con precio {arp(d_px)}", sig, why,
                d_oi=round(d_oi, 2), d_px=round(d_px, 2))
    except Exception as e:
        print(f"(open interest no disponible: {type(e).__name__})")

    try:   # OKX: [ts, ventas, compras] a mercado por hora, de la mas nueva a la mas vieja
        tk = api("okx", okx.publicGetRubikStatTakerVolumeContract,
                 {"instId": "BTC-USDT-SWAP", "period": "1H", "limit": "4"})["data"][:4]
        sell1, buy1 = float(tk[0][1]), float(tk[0][2])
        buy, sell = sum(float(x[2]) for x in tk), sum(float(x[1]) for x in tk)
        for name, r in (("1 h", buy1 / sell1), ("4 h", buy / sell)):
            sig = "alcista" if r > 1.1 else "bajista" if r < 0.9 else "neutral"
            add(f"flujo_{name}", f"Compras vs ventas a mercado {name}", ar(r, 2), sig,
                "Dominan los compradores agresivos" if sig == "alcista" else
                "Dominan los vendedores agresivos" if sig == "bajista" else "Flujo equilibrado", ratio=round(r, 3))
    except Exception as e:
        print(f"(flujo no disponible: {type(e).__name__})")

    try:
        ls = api("bybit", byb.publicGetV5MarketAccountRatio,
                 {"category": "linear", "symbol": "BTCUSDT", "period": "1h", "limit": 25})["result"]["list"]
        ls = [float(x["buyRatio"]) / float(x["sellRatio"]) for x in sorted(ls, key=lambda x: int(x["timestamp"]))
              if float(x["sellRatio"]) > 0]
        now_ls, prev_ls = ls[-1], ls[0]
        try:
            top = float(api("okx", okx.publicGetRubikStatContractsLongShortPositionRatioContractTopTrader,
                            {"instId": "BTC-USDT-SWAP", "period": "1H", "limit": "1"})["data"][0][1])
            top_txt = f", top traders {ar(top, 2)}"
        except Exception:
            top_txt = ""
        if now_ls > 2:
            crowd, sig = "Mayoría long: si cae, puede haber cascada de liquidaciones", "bajista"
        elif now_ls < 0.9:
            crowd, sig = "Mayoría short: si sube, puede haber squeeze", "alcista"
        else:
            crowd, sig = "Posicionamiento parejo", "neutral"
        add("long_short", "Cuentas long / short", f"{ar(now_ls, 2)} (24 h antes {ar(prev_ls, 2)}{top_txt})", sig, crowd)
    except Exception as e:
        print(f"(long/short no disponible: {type(e).__name__})")

    try:   # perpetuo contra spot: precio de marca e indice de Bybit (lo mismo que usa la app)
        tk = api("bybit", byb.publicGetV5MarketTickers, {"category": "linear", "symbol": "BTCUSDT"})["result"]["list"][0]
        rows.append(base_perp(float(tk["markPrice"]), float(tk["indexPrice"]), "Bybit"))
    except Exception as e:
        print(f"(base perpetuo-spot no disponible: {type(e).__name__})")
    # BingX: el exchange donde operas (el funding que pagas vos). Cambia cada 8 h: se pide cada 3 h
    try:
        now_ms = int(time.time() * 1000)
        rows.append(liq_reales(liq_okx(now_ms), now_ms))
    except Exception as e:
        print(f"(liquidaciones reales no disponibles: {type(e).__name__})")

    try:
        fr, f7 = cached("funding", FUNDING_TTL, lambda: funding_bingx(bgx))
    except Exception as e:
        print(f"(funding no disponible: {type(e).__name__})")
        return rows, None
    sig = "bajista" if fr > 0.0003 else "alcista" if fr < 0 else "neutral"
    add("funding", "Funding BingX", arp(fr * 100, 4) + " cada 8 h" + ("" if f7 is None else f" (7 días {arp(f7 * 100, 4)})"), sig,
        "Longs pagando caro: euforia" if fr > 0.0003 else "Shorts pagan: miedo" if fr < 0 else "Normal",
        **({} if f7 is None else {"f7": f7}))

    return rows, fr


# exchange: niveles a pedir. BingX va aparte: su libro publica 10-15 veces mas BTC que Binance en el mismo
# rango y dominaria cualquier total.
BOOKS = {"bybit": 500, "okx": 400, "bitget": 150, "bingx": 1000}
BOOK_BAND = 0.001      # +/-0.1%: el rango que cubren todos los libros publicos
WALL_BIN = 25.0        # USD por escalon al buscar muros


# Liquidaciones reales: las que publica OKX (BTC-USDT perpetuo), la ultima hora. Bybit solo las da por WebSocket y
# Binance no las publica por REST. No hay historia gratis para medir si anticipan: se muestran como contexto y para
# detectar barridas (muchas liquidaciones de un lado en pocos minutos), sin peso en las probabilidades.
BARRIDA_USD = 2_000_000        # en 15 min y en OKX solo (OKX es ~10-15% del mercado de futuros de BTC)


def liq_okx(now_ms):
    """[(ms, lado, usd)] de la ultima hora (lado: "long" o "short", lo que se liquido). Pagina hasta cubrir la hora."""
    import urllib.request
    out, after = [], None
    for _ in range(6):
        u = ("https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&instFamily=BTC-USDT&state=filled&limit=100"
             + (f"&after={after}" if after else ""))
        j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=10).read())
        det = [d for g in j.get("data") or [] for d in g.get("details") or []]
        if not det:
            break
        out += [(int(d["ts"]), d["posSide"], float(d["sz"]) * 0.01 * float(d["bkPx"])) for d in det]
        after = min(int(d["ts"]) for d in det)
        if after < now_ms - 3_600_000:
            break
    return out


def liq_reales(det, now_ms):
    """Fila de contexto con las liquidaciones reales de la ultima hora y de los ultimos 15 minutos (igual en JS)."""
    suma = lambda lado, mins: sum(u for t, s, u in det if s == lado and t >= now_ms - mins * 60_000)
    l60, s60, l15, s15 = suma("long", 60), suma("short", 60), suma("long", 15), suma("short", 15)
    barrida = "longs" if l15 >= BARRIDA_USD and l15 > 3 * s15 else "shorts" if s15 >= BARRIDA_USD and s15 > 3 * l15 else None
    m = lambda x: ar(x / 1e6, 1 if x < 1e7 else 0)
    det_txt = (f"Barrida de {barrida}: {m(l15 if barrida == 'longs' else s15)} M USD liquidados en 15 min solo en OKX. "
               f"Suele pasar en movimientos bruscos y a veces marca el final del tirón." if barrida else
               "Más longs liquidados: el precio barrió stops abajo" if l60 > 2 * s60 and l60 > 2e5 else
               "Más shorts liquidados: el precio barrió stops arriba" if s60 > 2 * l60 and s60 > 2e5 else "Sin barridas")
    return {"tabla": "contexto", "clave": "liq_reales", "titulo": "Liquidaciones reales 1 h (OKX)",
            "valor": f"longs {m(l60)} M · shorts {m(s60)} M USD", "senal": "neutral", "detalle": det_txt,
            "longs_1h": round(l60), "shorts_1h": round(s60), "longs_15m": round(l15), "shorts_15m": round(s15), "barrida": barrida}


# Perpetuo contra spot: cuanto mas caro (o barato) cotiza el perpetuo que el indice spot. Cortes: percentiles 90 y 5 de
# la prima de Binance 2022-2024 (medir_contexto.py). Contexto: sin peso en las probabilidades hasta medir que anticipa.
BASE_ALTA, BASE_BAJA = 0.05, -0.07


def base_perp(mark, index, fuente):
    """Fila de contexto con la base del perpetuo (precio de marca contra el indice spot, en %). Igual en JS."""
    b = (mark / index - 1) * 100
    if b >= BASE_ALTA:
        sig, det = "bajista", "Perpetuo caro contra el spot: compras apalancadas, calentamiento"
    elif b <= BASE_BAJA:
        sig, det = "alcista", "Perpetuo con descuento: ventas apalancadas o coberturas, miedo"
    else:
        sig, det = "neutral", "Perpetuo y spot parejos"
    return {"tabla": "contexto", "clave": "base_perp", "titulo": f"Perpetuo vs spot ({fuente})", "valor": arp(b, 3),
            "senal": sig, "detalle": det + ". Es contexto: no entra en las probabilidades.", "base": round(b, 4)}


# ---------- opciones de BTC (Deribit, publico) ----------
# Volatilidad implicita (DVOL), puts contra calls, el "dolor maximo" del vencimiento del viernes y cuanto mas caros
# estan los puts que los calls. Contexto: sin peso en las probabilidades (medir_contexto.py mide el DVOL).
MESES_EN = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}


def _vence(nombre):
    """BTC-13NOV26-83000-P -> (ms del vencimiento, 08:00 UTC; strike; 'C' o 'P'), o None."""
    try:
        _, d, k, tipo = nombre.split("-")
        dia, mes, anio = int(d[:-5]), MESES_EN[d[-5:-2]], 2000 + int(d[-2:])
        return int(datetime(anio, mes, dia, 8, tzinfo=timezone.utc).timestamp() * 1000), float(k), tipo
    except (ValueError, KeyError):
        return None


def opciones(libro, dvol, precio, ahora_ms):
    """Filas de contexto de las opciones. libro: get_book_summary_by_currency (kind=option); dvol: [[ms, valor]] por
    hora de los ultimos 30 dias. Igual en analisis.js."""
    rows = []

    def add(key, title, value, detail, **num):
        rows.append({"tabla": "contexto", "clave": key, "titulo": title, "valor": value, "senal": "neutral", "detalle": detail, **num})
    dv = [v for _, v in sorted(dvol)]
    if len(dv) >= 25:
        ahora, antes = dv[-1], dv[-25]
        pct_ = sum(1 for v in dv if v < ahora) / len(dv) * 100
        add("opciones_iv", "Volatilidad implícita (DVOL)", f"{ar(ahora, 1)} (24 h {arp(ahora - antes, 1).replace('%', '')})",
            f"Lo que las opciones esperan que se mueva BTC: ≈ ±{ar(ahora / 365 ** 0.5, 1)}% por día. Más alta que el "
            f"{ar(pct_)}% de los últimos 30 días. Alta: miedo o coberturas; baja: calma.",
            dvol=round(ahora, 2), dvol_24h=round(ahora - antes, 2), dvol_pct=round(pct_, 1))
    ops = []
    for o in libro:
        v = _vence(o.get("instrument_name", ""))
        if v and v[0] > ahora_ms and (o.get("open_interest") or 0) > 0:
            ops.append((v[0], v[1], v[2], float(o["open_interest"]), o.get("mark_iv")))
    if not ops or precio <= 0:
        return rows
    oi_c = sum(x[3] for x in ops if x[2] == "C")
    oi_p = sum(x[3] for x in ops if x[2] == "P")
    viernes = sorted({x[0] for x in ops if datetime.fromtimestamp(x[0] / 1000, timezone.utc).weekday() == 4})
    if viernes:
        vto = viernes[0]
        vs = [x for x in ops if x[0] == vto]
        vc, vp = sum(x[3] for x in vs if x[2] == "C"), sum(x[3] for x in vs if x[2] == "P")
        strikes = sorted({x[1] for x in vs})
        dolor = min(strikes, key=lambda K: (sum(x[3] * max(0.0, K - x[1]) for x in vs if x[2] == "C")
                                            + sum(x[3] * max(0.0, x[1] - K) for x in vs if x[2] == "P"), K))
        cuando = datetime.fromtimestamp(vto / 1000, LOCAL_TZ).strftime("%d/%m %H:%M")
        if oi_c > 0:
            add("opciones_pc", "Opciones: puts / calls", f"{ar(oi_p / oi_c, 2)} (vence {cuando[:5]}: {ar(vp / vc, 2) if vc else '—'})",
                "Contratos abiertos de puts por cada call. Más de 1: coberturas o apuestas a la baja; menos: apuestas a la suba.",
                ratio=round(oi_p / oi_c, 3), ratio_vto=None if not vc else round(vp / vc, 3))
        add("opciones_dolor", f"Dolor máximo (vence {cuando} h)", f"{ap(dolor)} ({arp(pct(dolor, precio), 1)})",
            "El precio donde más opciones de ese viernes vencen sin valor. Cerca del vencimiento a veces atrae al precio.",
            precio=dolor, vence=vto, distancia=round(pct(dolor, precio), 2))
    # sesgo: puts 5-15% abajo contra calls 5-15% arriba, en el primer vencimiento a 7 dias o mas
    lejos = sorted({x[0] for x in ops if x[0] - ahora_ms >= 7 * 86_400_000})
    if lejos:
        vs = [x for x in ops if x[0] == lejos[0] and x[4]]
        ivp = [x[4] for x in vs if x[2] == "P" and 0.85 * precio <= x[1] <= 0.95 * precio]
        ivc = [x[4] for x in vs if x[2] == "C" and 1.05 * precio <= x[1] <= 1.15 * precio]
        if ivp and ivc:
            sk = sum(ivp) / len(ivp) - sum(ivc) / len(ivc)
            add("opciones_sesgo", "Opciones: puts vs calls (IV)", f"{'+' if sk > 0 else ''}{ar(sk, 1)} puntos",
                "Volatilidad implícita de los puts 5-15% abajo menos la de los calls 5-15% arriba (vencimiento a 7 días o "
                "más). Positivo: pagan más por protegerse de una baja.", sesgo=round(sk, 2))
    return rows


def opciones_deribit(now_ms):
    """Libro de opciones de BTC y DVOL de los ultimos 30 dias, de Deribit (publico)."""
    import urllib.request
    get = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=15).read())["result"]
    libro = get("https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option")
    dv = get(f"https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&start_timestamp={now_ms - 30 * 86_400_000}"
             f"&end_timestamp={now_ms}&resolution=3600")["data"]
    return libro, [[int(x[0]) + 3_600_000, float(x[4])] for x in dv]


def funding_bingx(bgx):
    """Funding actual de BingX y promedio de los ultimos 7 dias (21 cobros de 8 h; entra en el termometro)."""
    fr = api("bingx", bgx.fetch_funding_rate, SYMBOL).get("fundingRate") or 0.0
    try:
        h = [float(x["fundingRate"]) for x in api("bingx", bgx.fetch_funding_rate_history, SYMBOL, limit=21)][-21:]
        f7 = sum(h) / len(h) if len(h) >= 15 else None
    except Exception as e:
        print(f"(historial de funding no disponible: {type(e).__name__})")
        f7 = None
    return fr, f7


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


TF_TXT = {"5m": "5 min", "15m": "15 min", "30m": "30 min", "1h": "1 hora", "4h": "4 horas", "1d": "diario", "1w": "semanal", "1M": "mensual"}
NO_LINES = {"l1_t": None, "l1_p": None, "l1_m": None, "l1_nombre": None, "l2_t": None, "l2_p": None, "l2_m": None,
            "l2_nombre": None, **{f"pt{k}_{f}": None for k in (1, 2, 3, 4, 5) for f in ("t", "p", "nombre")}}


# Velas semanales y mensuales: se arman con las diarias (1.500 dias: ~214 semanas y ~49 meses). Llevan grafico,
# indicadores, giros, Elliott, FVG, patrones y divergencias; no prediccion: hay pocas velas para repasarla.
TF_LARGOS = {"1w": 7 * 1440, "1M": 30 * 1440}


def _inicio_largo(t, tf):
    """Inicio (ms, UTC) de la semana (lunes, como Binance) o del mes que contiene t."""
    k = t // 86_400_000
    if tf == "1w":
        return (k - (k + 3) % 7) * 86_400_000
    d = datetime.fromtimestamp(t / 1000, tz=timezone.utc)
    return int(datetime(d.year, d.month, 1, tzinfo=timezone.utc).timestamp() * 1000)


def velas_largas(d1, tf, ultima_en_curso=False):
    """Velas semanales ('1w') o mensuales ('1M') con las diarias [t, o, h, l, c, v]. Se descarta la primera si empieza
    a mitad del periodo. Devuelve (velas, la ultima esta en curso)."""
    grupos = []
    for b in d1:
        k = _inicio_largo(b[0], tf)
        if grupos and grupos[-1][0] == k:
            g = grupos[-1]
            g[2], g[3], g[4], g[5] = max(g[2], b[2]), min(g[3], b[3]), b[4], g[5] + b[5]
        else:
            grupos.append([k, b[1], b[2], b[3], b[4], b[5], b[0]])
    if grupos and grupos[0][6] > grupos[0][0]:
        grupos = grupos[1:]
    if not grupos:
        return [], False
    siguiente = _inicio_largo(grupos[-1][0] + 32 * 86_400_000 if tf == "1M" else grupos[-1][0] + 7 * 86_400_000, tf)
    en_curso = ultima_en_curso or siguiente > d1[-1][0] + 86_400_000
    return [g[:6] for g in grupos], en_curso


CALIF_VELAS = 2000


def calificar_ultimas(bars):
    """calificar() solo mira la ultima vela: con las ultimas 2.000 alcanza (la media de 200 ya olvido el arranque: queda
    e^-18 de diferencia) y en 5m-1h (8.640 velas) tarda 4 veces menos. Las curvas vuelven con el largo de bars."""
    if len(bars) <= CALIF_VELAS:
        return ind.calificar(bars)
    off = len(bars) - CALIF_VELAS
    rows, summary, overlays = ind.calificar(bars[off:])
    # el OBV es acumulado: su valor (no su señal) depende de desde donde se suma; va el de toda la historia
    ob = ind.obv([b[4] for b in bars], [b[5] for b in bars])[-1]
    for r in rows:
        if r["indicador"] == "OBV":
            r["valor"] = round(ob, 2)
    return rows, summary, {k: [None] * off + list(v) for k, v in overlays.items()}


def analisis_largo(d1, tf, price, ultima_en_curso=False):
    """Filas del grafico y del analisis tecnico semanal o mensual (sin prediccion)."""
    bars, partial = velas_largas(d1, tf, ultima_en_curso)
    if len(bars) < 30:
        return []
    tf_min = TF_LARGOS[tf]
    closes = [b[4] for b in bars]
    ind_rows, summary, overlays = ind.calificar(bars)
    e20, e50, e200 = ind.ema(closes, 20), ind.ema(closes, 50), ind.ema(closes, 200)
    rsi = ind.rsi(closes)
    ml, ms, mh = ind.macd(closes)
    i = len(bars) - 1
    reg = apr.regimenes(bars, e200)
    pivots = ind.zigzag(bars)
    wave_labels, wave_desc, wave_target, wave_now, wave_short = ind.elliott(pivots, bars)
    crosses = ("alcista" if mh[k] > 0 and mh[k - 1] <= 0 else "bajista" if mh[k] < 0 and mh[k - 1] >= 0 else None for k in (i, i - 1))
    rows = [{"tabla": "marco", "tf": tf, "tendencia": trend_word(closes[i], e20[i], e50[i], e200[i]), **summary,
             "macd_cruce": next((x for x in crosses if x), None), "ema50": rp(e50[i]), "ema200": rp(e200[i]) if len(bars) >= 200 else None,
             "similares": 0, "criterio": "", "elliott": wave_desc, "elliott_objetivo": rp(wave_target), "elliott_curso": wave_now,
             "elliott_corto": wave_short, "regimen": None if reg[i] is None else apr.REGIMENES[reg[i]], "velas": len(bars), "sin_prediccion": True}]
    rows += [{"tabla": "indicador", "tf": tf, **r} for r in ind_rows]
    tail = pivots[-10:]
    offset = len(tail) - len(wave_labels)
    for n, (kind, k, p) in enumerate(tail):
        rows.append({"tabla": "giro", "tf": tf, "t": bars[k][0], "precio": rp(p), "tipo": kind,
                     "onda": wave_labels[n - offset] if n >= offset else "", "en_curso": n == len(tail) - 1})
    rows += [{"tabla": "fvg", "tf": tf, "tipo": z["tipo"], "t": z["t"], "bajo": rp(z["bajo"]), "alto": rp(z["alto"])} for z in ind.fvg(bars)]
    rows += ict_filas(tf, bars, tf_min)
    rows += patterns(tf, bars, pivots, e20, 3, tf_min, partial)
    rows += [{"tabla": "divergencia", "tf": tf, **d, "p1": rp(d["p1"]), "p2": rp(d["p2"])} for d in ind.divergencias(bars, pivots)]
    for k in range(max(0, i - CHART_BARS + 1), i + 1):
        t, o_, h_, l_, c_, v_ = bars[k]
        rows.append({"tabla": "vela", "tf": tf, "t": t, "o": o_, "h": h_, "l": l_, "c": c_, "v": round(v_, 2), "en_curso": partial and k == i,
                     "ema20": rp(overlays["ema20"][k]), "ema50": rp(overlays["ema50"][k]), "ema200": rp(e200[k]) if k >= 199 else None,
                     "bb_up": rp(overlays["bb_up"][k]),
                     "bb_lo": rp(overlays["bb_lo"][k]), "rsi": None if rsi[k] is None else round(rsi[k], 1),
                     "macd": round(ml[k], dec_precio(price) + 1), "macd_senal": round(ms[k], dec_precio(price) + 1),
                     "macd_hist": round(mh[k], dec_precio(price) + 1)})
    return rows


ICT_HORIZONTE = 6


def ict_filas(tf, bars, tf_min):
    """Order blocks, breakers, IFVG, barridas y Power of Three de esta temporalidad, con lo medido (igual que ictFilas en JS)."""
    h, l, c = [b[2] for b in bars], [b[3] for b in bars], [b[4] for b in bars]
    zs, st = ind.ict(bars, ind.atr_w(h, l, c), tf_min, ICT_HORIZONTE)
    plazo = label(ICT_HORIZONTE * tf_min)
    out = []
    for z in zs:
        n, ok = st.get(z["tipo"], [0, 0])
        out.append({"tabla": "ict", "tf": tf, "tipo": z["tipo"], "nombre": ind.ICT_NOMBRE[z["tipo"]], "sesgo": z["sesgo"], "t": z["t"],
                    "t_rompe": z["t_rompe"], "bajo": rp(z["bajo"]), "alto": rp(z["alto"]), "casos": n, "exito": int(ok * 100 / n + 0.5) if n else None,
                    "plazo": plazo, "descripcion": ind.ict_descripcion(z, st, ICT_HORIZONTE, plazo)})
    return out


def patterns(tf, bars, pivots, e20, horizon, tf_min, partial=False):
    """Patron de velas en las ultimas dos velas (con su historial de aciertos) y figura del grafico vigente."""
    o, h, l, c = ([b[k] for b in bars] for k in (1, 2, 3, 4))
    atr_ = ind.atr_w(h, l, c)
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
            lines.update({f"l{n_}_t": ln[0], f"l{n_}_p": rp(ln[1]), f"l{n_}_m": ln[2], f"l{n_}_nombre": ln[3]})
        for n_, pt in enumerate(g["puntos"][:5], start=1):
            lines.update({f"pt{n_}_t": pt[0], f"pt{n_}_p": rp(pt[1]), f"pt{n_}_nombre": pt[2]})
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


# Fibonacci: solo el swing de 90 dias en velas de 4 h mostro ventaja (medido 2020-2026, BTC): en los toques, el precio
# reboto 1,5 ATR antes de romper 1,5 ATR el 57% de las veces, contra 49% en niveles al azar del mismo rango (y se
# repitio en 2020-22 y 2023-26). Con 1 h, diario o semanal no hubo ventaja. Rebote medido de cada nivel:
FIB_REBOTE = {0.236: 58, 0.382: 59, 0.5: 59, 0.618: 42, 0.786: 62}


def fibonacci(h4, velas=540):
    """Retrocesos del swing de los ultimos 90 dias (540 velas de 4 h): desde el maximo si el tramo fue alcista
    (el minimo vino antes), desde el minimo si fue bajista. [(nivel, precio)]."""
    w = h4[-velas:]
    if len(w) < 100:
        return []
    hs, ls = [b[2] for b in w], [b[3] for b in w]
    hi, lo = max(hs), min(ls)
    sube = hs.index(hi) > ls.index(lo)
    return [(f, hi - (hi - lo) * f if sube else lo + (hi - lo) * f) for f in sorted(FIB_REBOTE)]


def fib_tramo(h4, velas=540):
    """Los dos extremos del swing de fibonacci() (para dibujarlo como en TradingView): el inicio (nivel 1) y el fin
    (nivel 0). Alcista: del minimo al maximo; bajista: del maximo al minimo."""
    w = h4[-velas:]
    if len(w) < 100:
        return None
    hs, ls = [b[2] for b in w], [b[3] for b in w]
    ih, il = hs.index(max(hs)), ls.index(min(ls))
    a, b = ((w[il][0], w[il][3]), (w[ih][0], w[ih][2])) if ih > il else ((w[ih][0], w[ih][2]), (w[il][0], w[il][3]))
    return {"t_inicio": a[0], "p_inicio": a[1], "t_fin": b[0], "p_fin": b[1]}


# Cuando 15 min, 1 hora y 4 horas van para el mismo lado. Medido 2023-2026 sin mirar el futuro (medir_contexto.py):
# el de 1 hora acerto la direccion 54,0% de las veces (52,6-55,4) contra 51,5% (50,5-52,4) cuando no coincidian; mejor
# en 2023-24 y en 2025-26. En 15 min y 4 horas no cambio. Se muestra como senal: no cambia la probabilidad.
COINCIDEN = {"si": 54.0, "no": 51.5}


def coinciden(rows):
    """'alcista' o 'bajista' si las predicciones de 15 min, 1 hora y 4 horas van para el mismo lado; None si no."""
    p = {r["plazo"]: r["sube"] for r in rows if r["tabla"] == "plazo"}
    xs = [p.get(k) for k in ("15 min", "1 hora", "4 horas")]
    if any(x is None for x in xs):
        return None
    return "alcista" if all(x > 50 for x in xs) else "bajista" if all(x < 50 for x in xs) else None


# ---------- analisis central: todo converge en 5 puntos, en cada temporalidad ----------
# Cada calculo de la app suma (o resta) puntos a uno de estos puntos, con su peso y su motivo:
#   fuerza    ¿se viene movimiento fuerte? (modelo de arboles, volatilidad, Bollinger comprimidas, volumen, ADX, hora del
#             dia, dato fuerte de EE.UU., liquidaciones cerca)
#   direccion ¿mas probable que suba o que baje? (prediccion por casos parecidos y aprendizaje, indicadores del marco,
#             patrones, divergencias, canales, Elliott, SuperTrend, Ichimoku, VWAP, OBV, Chaikin, SAR, liquidaciones,
#             libros, ciclo y funding)
#   alcance   ¿hasta donde? (rango del 80%, objetivos, rango esperado, objetivo de Elliott)
#   niveles   soporte, resistencia e invalidacion
#   riesgo    lo que hay que mirar antes de operar
# Ojo: medido sin mirar el futuro, la direccion casi no se puede predecir (la prediccion le gana a la tasa base por
# 0-0,2%); la fuerza si (modelo: 9-12%). El puntaje de direccion resume lo que dicen las senales, no promete acierto.
CENTRAL_TF = ("5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M")
CENTRAL_PLAZO = {"5m": "5 min", "15m": "15 min", "1h": "1 hora", "4h": "4 horas", "1d": "1 día"}
CENTRAL_HORAS = {"5m": 1, "15m": 1, "30m": 2, "1h": 2, "4h": 8, "1d": 24, "1w": 72, "1M": 168}


def _cf(lst, punto, lado, peso, texto):
    lst.append([punto, lado, peso, texto])


def central(rows, price, candles, now_ms):
    pick = lambda t: [r for r in rows if r.get("tabla") == t]
    mv = next(iter(pick("movimiento")), None)
    hs = next(iter(pick("horas")), None)
    tm = next(iter(pick("termometro")), None)
    liq = pick("liquidacion")
    libros = pick("libro")
    fu = next((c for c in pick("contexto") if c.get("clave") == "funding"), None)
    iv = next((c for c in pick("contexto") if c.get("clave") == "opciones_iv"), None)
    eventos = sorted(r["t"] for r in pick("evento") if r.get("t") and r["t"] > now_ms)
    # decision de tasa de la Fed. Medido (medir_fed.py, 45 decisiones 2021-2026): la hora del anuncio se movio en mediana
    # 3,2 veces lo normal y mas del doble el 78%; la direccion despues, ~50/50 (bajara, mantuviera o subiera la tasa)
    fed = sorted(r["t"] for r in pick("evento") if r.get("t") and r["t"] > now_ms and any(k in (r.get("original") or "").lower() for k in ("interest rate decision", "fomc decision", "interest rate fomc")))
    niveles = pick("nivel")
    out = []
    for tf in CENTRAL_TF:
        marco = next((m for m in pick("marco") if m["tf"] == tf), None)
        if marco is None:
            continue
        nombre_plazo = CENTRAL_PLAZO.get(tf)
        p = next((r for r in pick("plazo") if r["plazo"] == nombre_plazo), None) if nombre_plazo else None
        ind_ = {r["indicador"]: r for r in rows if r.get("tabla") == "indicador" and r.get("tf") == tf}
        F = []
        corto = tf in ("5m", "15m", "30m", "1h")
        largo_tf = tf in ("1d", "1w", "1M")
        # ----- fuerza -----
        prob = base = None
        if mv:
            if tf == "4h" and mv.get("modelo_4h") is not None:
                prob, base = mv["modelo_4h"], mv["modelo_base_4h"]
            elif corto and mv.get("modelo_1h") is not None:
                prob, base = mv["modelo_1h"], mv["modelo_base_1h"]
            elif corto:
                prob, base = mv["prob_fuerte"], mv["prob_normal"]
        if prob is not None and base:
            if prob >= 40:
                _cf(F, "fuerza", 1, 3, f"Modelo de movimiento fuerte: {round(prob)}% (lo normal {round(base)}%)")
            elif prob >= 25:
                _cf(F, "fuerza", 1, 2, f"Modelo de movimiento fuerte: {round(prob)}% (lo normal {round(base)}%)")
            elif prob >= 1.5 * base:
                _cf(F, "fuerza", 1, 1, f"Modelo de movimiento fuerte: {round(prob)}%, más que lo normal ({round(base)}%)")
            elif prob <= 0.6 * base:
                _cf(F, "fuerza", -1, 1, f"Modelo de movimiento fuerte: {round(prob)}%, menos que lo normal ({round(base)}%)")
        if mv and corto:
            if mv.get("despierto"):
                _cf(F, "fuerza", 1, 2, "El mercado se despertó: la volatilidad corta pasó 1,8 veces la habitual")
            elif mv["volatilidad"] >= 1.3:
                _cf(F, "fuerza", 1, 1, f"Mercado agitado: volatilidad {ar(mv['volatilidad'], 1)}× la habitual")
            elif mv["volatilidad"] < 0.8:
                _cf(F, "fuerza", -1, 1, f"Mercado en calma: volatilidad {ar(mv['volatilidad'], 1)}× la habitual")
        comp = compresion(candles.get(tf)) if candles.get(tf) else None
        if comp and comp["comprimida"]:
            _cf(F, "fuerza", 1, 1, f"Bollinger comprimidas (entre el {round(max(1, comp['percentil']))}% más angosto de sus últimas 720 velas): suele venir una expansión")
        # volatilidad implicita (solo BTC). Medido (medir_dvol.py): con el DVOL en su 20% mas alto de 30 dias, las 4 h
        # siguientes fueron un movimiento fuerte 18-26% de las veces (normal 12-13%); en su 20% mas bajo, 7-9%
        if iv and iv.get("dvol_pct") is not None and tf in ("15m", "30m", "1h", "4h", "1d"):
            if iv["dvol_pct"] >= 80:
                _cf(F, "fuerza", 1, 1, f"Las opciones esperan movimiento: volatilidad implícita más alta que el {round(iv['dvol_pct'])}% de 30 días")
            elif iv["dvol_pct"] <= 20:
                _cf(F, "fuerza", -1, 1, f"Las opciones esperan calma: volatilidad implícita en el {round(iv['dvol_pct'])}% más bajo de 30 días")
        vr = ind_.get("Volumen relativo")
        if vr and vr["valor"] is not None and vr["valor"] >= 2:
            _cf(F, "fuerza", 1, 1, f"Volumen {ar(vr['valor'], 1)} veces el promedio")
        adx = ind_.get("ADX 14")
        if adx and adx["valor"] is not None and adx["valor"] >= 25:
            _cf(F, "fuerza", 1, 0.5, f"ADX {round(adx['valor'])}: tendencia con fuerza")
        if hs and corto:
            if hs["ahora_f"] >= 1.25:
                _cf(F, "fuerza", 1, 1, f"Hora de mucho movimiento (×{ar(hs['ahora_f'], 2)} de una hora típica)")
            elif hs["ahora_f"] <= 0.7:
                _cf(F, "fuerza", -1, 1, f"Hora tranquila (×{ar(hs['ahora_f'], 2)} de una hora típica)")
        ventana = CENTRAL_HORAS[tf] * 3_600_000
        prox = [t for t in eventos if t - now_ms <= ventana]
        prox_fed = [t for t in fed if t - now_ms <= ventana]
        if prox_fed and tf in ("5m", "15m", "30m", "1h", "4h"):
            _cf(F, "fuerza", 1, 3, f"Decisión de la Fed dentro de {max(1, round((prox_fed[0] - now_ms) / 60000))} min: esa hora se mueve ~3 veces lo normal (medido)")
        elif prox and tf in ("5m", "15m", "30m", "1h", "4h"):            # un dato no hace fuerte una vela diaria
            _cf(F, "fuerza", 1, 2, f"Dato fuerte de EE.UU. dentro de {max(1, round((prox[0] - now_ms) / 60000))} min")
        cerca = [x for x in liq if abs(x["precio"] / price - 1) <= 0.01 and x["longs"] + x["shorts"] >= 5]
        if cerca and corto:
            _cf(F, "fuerza", 1, 1, "Liquidaciones acumuladas a menos de 1%: si llega, el movimiento se puede acelerar")
        # ----- direccion -----
        if p:
            tit = next((e for e in rows if e.get("tabla") == "explicacion" and e["plazo"] == nombre_plazo and e["tipo"] == "titular"), None)
            sesgo = tit["sesgo"] if tit else "neutral"
            if sesgo != "neutral":
                w = 1 if p.get("sin_ventaja") or p.get("factor") == 0 else 3
                pu = p.get("primero_arriba")
                txt = f"Casos parecidos y aprendizaje: {'sube' if sesgo == 'alcista' else 'baja'}" + (f" ({round(pu if sesgo == 'alcista' else 100 - pu)}% toca primero ese lado)" if pu is not None else "")
                _cf(F, "direccion", 1 if sesgo == "alcista" else -1, w, txt)
            for e in rows:
                if e.get("tabla") == "explicacion" and e["plazo"] == nombre_plazo and e["tipo"] == "senal" and e["sesgo"] in ("alcista", "bajista") \
                        and not e["texto"].startswith(("Indicadores de", "Casos parecidos")):
                    _cf(F, "direccion", 1 if e["sesgo"] == "alcista" else -1, 1, e["texto"])
        else:
            for x in pick("patron"):
                if x["tf"] == tf and x["sesgo"] in ("alcista", "bajista"):
                    _cf(F, "direccion", 1 if x["sesgo"] == "alcista" else -1, 1, f"{x['nombre']} ({x['estado']})")
            for x in pick("divergencia"):
                if x["tf"] == tf and x["tipo"] in ("alcista", "bajista"):
                    _cf(F, "direccion", 1 if x["tipo"] == "alcista" else -1, 1, f"Divergencia {x['tipo']} en {x['indicador']}")
        if p and nombre_plazo == "1 hora" and p.get("coinciden") in ("alcista", "bajista"):
            # medido (medir_contexto.py): asi la de 1 hora acerto 54,0% contra 51,5%, en los dos tramos
            _cf(F, "direccion", 1 if p["coinciden"] == "alcista" else -1, 1, "15 min, 1 hora y 4 horas apuntan para el mismo lado (medido: acierta 54% contra 51,5%)")
        # Medido (medir_direccion.py, BTC 1 h 2021-2026): a 1 y 4 horas los indicadores de tendencia aciertan MENOS que una
        # moneda (el resumen 45,6-48,1%; SuperTrend, Ichimoku, VWAP, OBV, Chaikin y SAR 45-49%, en los dos tramos): despues
        # de que marcan fuerte, el precio suele corregir. En 4 h o menos cuentan al reves (peso 1, solo el resumen: los
        # demas dicen lo mismo); en velas diarias o mas largas, a favor (sin medir).
        r_ = marco["rating"]
        if r_ is not None and abs(r_) > 0.1:
            if not largo_tf:
                _cf(F, "direccion", -1 if r_ > 0 else 1, 1,
                    f"Indicadores {marco['rating_txt'].lower()}: en las próximas horas suele corregir (medido: a favor aciertan 46–48%)")
            else:
                _cf(F, "direccion", 1 if r_ > 0 else -1, 2,
                    f"Indicadores: {marco['rating_txt'].lower()} (medias {marco['ma_compra']}↑ {marco['ma_venta']}↓, osciladores {marco['osc_compra']}↑ {marco['osc_venta']}↓)")
        el = marco.get("elliott") or ""
        cur = marco.get("elliott_curso")
        ya = any(f[3].startswith("Elliott") for f in F)                  # el de la explicacion ya esta
        if cur and not ya:
            alc = "alcista" in el.split(";")[0]
            if el.startswith("Impulso"):
                sube = (cur in ("1", "3", "5", "B")) == alc
            else:
                sube = (cur == "B") == alc
            _cf(F, "direccion", 1 if sube else -1, 1, f"Elliott: onda {cur} en curso ({el.split(';')[0].lower()})")
        for nombre, txt in () if not largo_tf else (("SuperTrend (10,3)", "SuperTrend"), ("Nube de Ichimoku", "Nube de Ichimoku"), ("VWAP del dia", "VWAP del día"),
                            ("OBV", "OBV"), ("Chaikin Money Flow 20", "Chaikin"), ("Parabolic SAR", "Parabolic SAR")):
            x = ind_.get(nombre)
            if x and x["senal"] in ("compra", "venta"):
                _cf(F, "direccion", 1 if x["senal"] == "compra" else -1, 0.5, f"{txt}: {'a favor de la suba' if x['senal'] == 'compra' else 'a favor de la baja'}" + (f" ({x['detalle']})" if x.get("detalle") else ""))
        bb = ind_.get("Bandas de Bollinger %B")
        if bb and bb["valor"] is not None and (bb["valor"] >= 100 or bb["valor"] <= 0):
            # medido: fuera de banda, la hora siguiente volvio hacia adentro el 56-59% de las veces (los dos tramos)
            _cf(F, "direccion", -1 if bb["valor"] >= 100 else 1, 0.5 if largo_tf else 1, f"Precio {'arriba de la banda superior' if bb['valor'] >= 100 else 'debajo de la banda inferior'} de Bollinger: suele volver adentro")
        arriba = sum(x["shorts"] for x in liq if 0 < x["precio"] / price - 1 <= 0.03)
        abajo = sum(x["longs"] for x in liq if 0 < 1 - x["precio"] / price <= 0.03)
        if arriba + abajo >= 10:
            if arriba >= 1.5 * abajo:
                _cf(F, "direccion", 1, 1, f"Más liquidaciones arriba ({ar(arriba, 0)} M de shorts) que abajo ({ar(abajo, 0)} M): imán hacia arriba")
            elif abajo >= 1.5 * arriba:
                _cf(F, "direccion", -1, 1, f"Más liquidaciones abajo ({ar(abajo, 0)} M de longs) que arriba ({ar(arriba, 0)} M): imán hacia abajo")
        if libros and corto:
            d = sum(x["desequilibrio"] for x in libros) / len(libros)
            if abs(d) >= 15:
                _cf(F, "direccion", 1 if d > 0 else -1, 0.5, f"Libros de órdenes: {'más compras' if d > 0 else 'más ventas'} cerca del precio ({ar(d, 0)}%)")
        if tm and tf in ("4h", "1d", "1w", "1M"):
            z = tm["medidor_zona"]
            if "compra" in z.lower():
                _cf(F, "direccion", 1, 1, f"Ciclo: {z.lower()}")
            elif "venta" in z.lower() or "caro" in z.lower():
                _cf(F, "direccion", -1, 1, f"Ciclo: {z.lower()}")
        if fu and fu.get("f7") is not None and tf in ("4h", "1d", "1w", "1M"):
            if fu["f7"] < 0:
                _cf(F, "direccion", 1, 0.5, "Funding negativo: hay miedo (a meses suele ser bueno)")
            elif fu["f7"] >= 0.0003:
                _cf(F, "direccion", -1, 0.5, "Funding alto: hay euforia")
        # ----- totales -----
        fz = sum(f[1] * f[2] for f in F if f[0] == "fuerza")
        dr = sum(f[1] * f[2] for f in F if f[0] == "direccion")
        a_favor = sum(f[2] for f in F if f[0] == "direccion" and f[1] > 0)
        en_contra = sum(f[2] for f in F if f[0] == "direccion" and f[1] < 0)
        fuerza = "alta" if fz >= 4 else "media" if fz >= 2 else "baja"
        lado = "sube" if dr >= 2.5 else "baja" if dr <= -2.5 else "neutral"
        # ----- alcance y niveles -----
        # el soporte y la resistencia de cada temporalidad: los mas cercanos que esten al menos a media vela tipica
        # (ATR) de esa temporalidad. Antes eran los mas cercanos a secas: en la semanal y la mensual quedaba un muro
        # del libro de ordenes a 0,1% del precio. Si no hay ninguno tan lejos, el mas lejano que haya.
        lejos = 0.5 * (marco.get("atr_pct") or 0) / 100 * price
        sop = max((n["precio"] for n in niveles if n["precio"] <= price - lejos and n["precio"] < price),
                  default=min((n["precio"] for n in niveles if n["precio"] < price), default=None))
        res = min((n["precio"] for n in niveles if n["precio"] >= price + lejos and n["precio"] > price),
                  default=max((n["precio"] for n in niveles if n["precio"] > price), default=None))
        inval = next((e["texto"] for e in rows if e.get("tabla") == "explicacion" and e["plazo"] == nombre_plazo and e["tipo"] == "invalida"), None) if p else None
        # ----- riesgo -----
        R = []
        rsi = ind_.get("RSI 14")
        if rsi and rsi["valor"] is not None and rsi["valor"] >= 75:
            R.append(f"RSI {round(rsi['valor'])}: sobrecompra")
        elif rsi and rsi["valor"] is not None and rsi["valor"] <= 25:
            R.append(f"RSI {round(rsi['valor'])}: sobreventa")
        if eventos and eventos[0] - now_ms <= 24 * 3_600_000:
            R.append(f"Dato fuerte de EE.UU. en {max(1, round((eventos[0] - now_ms) / 3_600_000))} h: el precio se mueve más")
        if fuerza == "alta":
            R.append("Se viene movimiento fuerte: revisá stops y tamaño")
        if (lado == "sube" and en_contra >= 0.6 * a_favor) or (lado == "baja" and a_favor >= 0.6 * en_contra):
            R.append("Hay señales en contra casi tan fuertes: dirección poco firme")
        out.append({"tabla": "central", "tf": tf, "plazo": nombre_plazo if p else None,
                    "fuerza": fuerza, "fuerza_puntos": fz, "prob_fuerte": prob, "prob_normal": base,
                    "direccion": lado, "direccion_puntos": dr, "a_favor": a_favor, "en_contra": en_contra,
                    "prob_sube": p.get("primero_arriba") if p else None,
                    "rango_min": p["min"] if p else None, "rango_max": p["max"] if p else None, "hasta": p["hora"] if p else None,
                    "obj_arriba": p["obj_arriba"] if p else None, "obj_abajo": p["obj_abajo"] if p else None,
                    "toca_arriba": p.get("toca_arriba") if p else None, "toca_abajo": p.get("toca_abajo") if p else None,
                    "esperado_usd": mv["esperado_usd"] if mv and corto else None, "elliott_objetivo": marco.get("elliott_objetivo"),
                    "soporte": sop, "resistencia": res, "invalida": inval, "riesgo": R, "factores": F})
    return out


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
    if "4h" in sig_tfs:     # tocando un Fibonacci de 90 dias que rebota mas que un nivel cualquiera
        fz = [n for n in get("nivel") if n.get("fib") and n["rebote"] >= 55 and abs(n["distancia"]) <= 0.4]
        if fz:
            n = min(fz, key=lambda n: abs(n["distancia"]))
            signals.append((3, "alcista" if n["tipo"] == "soporte" else "bajista",
                            f"En el Fibonacci {ar(n['fib'] * 100, 1)}% de 90 días ({ap(n['precio'])}): ahí rebotó {n['rebote']}% de las veces"))
    if main.get("coinciden"):
        signals.append((2, main["coinciden"], f"15 min, 1 hora y 4 horas van para el mismo lado: así acertó {ar(COINCIDEN['si'], 1)}% "
                                              f"(2023-26; {ar(COINCIDEN['no'], 1)}% cuando no)"))
    sma = next((n for n in get("nivel") if n["nombre"] == "Media simple 200 días"), None)
    if sma and name == "1 día":
        signals.append((6, "alcista" if price > sma["precio"] else "bajista",
                        "Arriba de la media simple de 200 días" if price > sma["precio"] else "Debajo de la media simple de 200 días"))
    signals.sort(key=lambda x: x[0])

    up, dn, pu, mg = main["obj_arriba"], main["obj_abajo"], main["primero_arriba"], main["margen_primero"] or 0
    n_up = sum(s == "alcista" for _, s, _ in signals)
    n_dn = len(signals) - n_up
    if main["sin_ventaja"]:
        pu = None       # sin ventaja medida, "que toca primero" tampoco es una prediccion
    if pu is not None and pu - 50 > max(5, mg):
        bias = "alcista"
        head = f"Hasta las {hh} h, es más probable que BTC suba a {ap(up)} ({ar(pu)}%) antes que baje a {ap(dn)}."
    elif pu is not None and 50 - pu > max(5, mg):
        bias = "bajista"
        head = f"Hasta las {hh} h, es más probable que BTC baje a {ap(dn)} ({ar(100 - pu)}%) antes que suba a {ap(up)}."
    else:
        bias = "neutral"
        # el rango real: donde termino el 80% de los casos parecidos (los niveles +/- un escalon se pasan seguido)
        lo, hi = main["min"], main["max"]
        rango = f"8 de cada 10 veces terminó entre {ap(lo)} y {ap(hi)}" if lo and hi else f"lo más cerca está {ap(dn)} o {ap(up)}"
        motivo = " (en su repaso no le ganó a lo normal)" if main["sin_ventaja"] else ""
        head = f"Hasta las {hh} h, sin dirección clara{motivo}: {rango}."
    agree = n_up if bias == "alcista" else n_dn
    if not signals:
        why = "No hay señales fuertes en este plazo."
    elif bias == "neutral":
        why = f"Las señales están repartidas: {n_up} alcista{'' if n_up == 1 else 's'} y {n_dn} bajista{'' if n_dn == 1 else 's'}."
    elif agree * 2 > len(signals):
        why = f"Lo acompañan {agree} de {len(signals)} señales."
    else:
        why = f"Ojo: solo {agree} de {len(signals)} señales acompañan. Convicción baja."

    def row(orden, tipo, sesgo, texto, precio=None):
        return {"tabla": "explicacion", "plazo": name, "orden": orden, "tipo": tipo, "sesgo": sesgo, "texto": texto,
                "precio": precio}

    out = [row(0, "titular", bias, head), row(1, "porque", bias, why)]
    out += [row(k, "senal", s, txt) for k, (_, s, txt) in enumerate(signals, start=2)]
    # niveles que importan para este plazo: la misma regla que central() (al menos a media vela tipica, ATR, de la
    # temporalidad del plazo; si no hay tan lejos, el mas lejano), asi el resumen, el "por que" y el grafico muestran
    # el mismo soporte y la misma resistencia
    m_tf = get("marco", tf=sig_tfs[-1])
    lejos = 0.5 * ((m_tf[0].get("atr_pct") if m_tf else 0) or 0) / 100 * price
    levels = sorted(get("nivel"), key=lambda n: n["precio"])
    arriba, abajo = [n for n in levels if n["precio"] > price], [n for n in levels if n["precio"] < price]
    res = next((n for n in arriba if n["precio"] >= price + lejos), arriba[-1] if arriba else None)
    sup = next((n for n in reversed(abajo) if n["precio"] <= price - lejos), abajo[0] if abajo else None)
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
            txt += f" Le gana a lo normal: {ar(hab, 1)}% menos error que decir siempre lo que pasa en general."
        elif hab > -0.5:
            txt += f" Todavía no le gana a lo normal en forma clara ({ar(hab, 1)}%): sus probabilidades quedan cerca de lo normal."
        else:
            txt += f" Viene peor que lo normal ({ar(hab, 1)}%): por eso modera sus probabilidades."
    ap, lo, hi = a["aciertos_aprendido"], a["ic_bajo"], a["ic_alto"]
    if ap is not None and lo is not None:
        txt += f" Acertó {ar(ap)}% qué tocaba primero (con el margen de error, entre {ar(lo)}% y {ar(hi)}%)."
    return txt


def log_and_score(entries, closes_by_tf):
    rows = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            rows = [r for r in csv.reader(f) if len(r) in (5, 7)]     # 5: registros viejos, sin el rango
    seen = {(r[0], r[1], r[2]) for r in rows}
    fmt = lambda x: f"{x:.{dec_precio(x)}f}"
    rows += [[str(t), tf, str(h), fmt(p), f"{pr:.1f}"] + ([] if lo is None or hi is None else [fmt(lo), fmt(hi)])
             for t, tf, h, p, pr, lo, hi, *_ in entries if (str(t), tf, str(h)) not in seen]   # *_: lo demas (historial.py)
    rows = rows[-20000:]        # como la version JS: el registro no crece sin limite (se lee y se escribe cada analisis)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOG_FILE, "w", newline="") as f:
        csv.writer(f).writerows(rows)
    score = {}      # (tf, h) -> [casos, aciertos, brier, con rango, adentro del rango]
    for r in rows:
        t, tf, h, p, pr = r[:5]
        tf_ms = ccxt.Exchange.parse_timeframe(tf) * 1000
        future = closes_by_tf.get(tf, {}).get(int(t) + int(h) * tf_ms)
        if future is None:
            continue
        sc = score.setdefault((tf, int(h)), [0, 0, 0.0, 0, 0])
        if len(r) == 7:
            sc[3] += 1
            sc[4] += float(r[5]) <= future <= float(r[6])
        prob = float(pr) / 100
        if prob == 0.5:
            continue
        up = future > float(p)
        sc[0] += 1
        sc[1] += (prob > 0.5) == up
        sc[2] += (prob - up) ** 2
    return score


# ---------- analisis completo ----------
def analyze():
    bgx, src = exchange("bingx"), candle_source()
    # los pedidos de red van en paralelo: velas de todas las temporalidades a la vez, y los libros de ordenes
    # (que se piden como mucho cada 20 s) se bajan mientras se calcula lo demas
    pool = ThreadPoolExecutor(max_workers=8)
    books_job = pool.submit(cached, "libros", 20, order_books)
    jobs = {tf: pool.submit(update_candles, src, tf, *((DIAS_LARGOS, "1d_largo") if tf == "1d" else (days,)))
            for tf, (days, _) in TIMEFRAMES.items()}
    candles = {tf: job.result() for tf, job in jobs.items()}
    d1_largo = candles["1d"]                       # toda la historia diaria: para la semanal y la mensual
    corte = int(time.time() * 1000) - TIMEFRAMES["1d"][0] * 86_400_000
    candles["1d"] = [c for c in d1_largo if c[0] >= corte]
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
        ind_rows, summary, overlays = calificar_ultimas(bars)
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
                      "vol": {}, "cal": {}, "partial": partial}
        main_fit = tune(tf, series[tf], horizons[0])
        idxs, keep = main_fit["idxs"], main_fit["keep"]
        i = len(bars) - 1
        trend = trend_word(closes[i], e20[i], e50[i], e200[i])
        reg = apr.regimenes(bars, e200)
        by_tf[tf] = {"summary": summary, "trend": trend}
        pivots = ind.zigzag(bars)
        wave_labels, wave_desc, wave_target, wave_now, wave_short = ind.elliott(pivots, bars)
        # cruce del MACD con su senal en la ultima o la anteultima vela
        crosses = ("alcista" if mh[k] > 0 and mh[k - 1] <= 0 else "bajista" if mh[k] < 0 and mh[k - 1] >= 0 else None
                   for k in (i, i - 1))
        cross = next((x for x in crosses if x), None)
        rows.append({"tabla": "marco", "tf": tf, "tendencia": trend, **summary, "macd_cruce": cross,
                     "ema50": rp(e50[i]), "ema200": rp(e200[i]), "similares": len(idxs),
                     "criterio": apr.receta_txt(main_fit["receta"], keep) if keep else "",
                     "elliott": wave_desc, "elliott_objetivo": rp(wave_target),
                     "elliott_curso": wave_now, "elliott_corto": wave_short,
                     # regimen de mercado: dato a la vista. Pesos distintos por regimen no mejoraron (medir_contexto.py)
                     "regimen": None if reg[i] is None else apr.REGIMENES[reg[i]]})
        rows += [{"tabla": "indicador", "tf": tf, **r} for r in ind_rows]
        tail = pivots[-10:]
        offset = len(tail) - len(wave_labels)
        for n, (kind, k, p) in enumerate(tail):
            rows.append({"tabla": "giro", "tf": tf, "t": bars[k][0], "precio": rp(p), "tipo": kind,
                         "onda": wave_labels[n - offset] if n >= offset else "", "en_curso": n == len(tail) - 1})
        rows += [{"tabla": "fvg", "tf": tf, "tipo": z["tipo"], "t": z["t"], "bajo": rp(z["bajo"]),
                  "alto": rp(z["alto"])} for z in ind.fvg(bars)]
        rows += ict_filas(tf, bars, tf_min)
        rows += patterns(tf, bars, pivots, e20, horizons[0], tf_min, partial)
        rows += [{"tabla": "divergencia", "tf": tf, **d, "p1": rp(d["p1"]), "p2": rp(d["p2"])}
                 for d in ind.divergencias(bars, pivots)]

        for h in horizons:
            prob, tg = horizon_stats(tf, series[tf], h, price, tune(tf, series[tf], h))
            rows.append({"tabla": "probabilidad", **prob})
            rows += [{"tabla": "objetivo", "tf": tf, "horizonte": prob["horizonte"], "hora": prob["hora"], **t} for t in tg]
            entries.append((bars[-1][0] + tf_ms, tf, h, closes[-1], prob["sube"], prob["min"], prob["max"], {c: prob.get(k) for c, k in (("m", "mediana"), ("a", "obj_arriba"), ("b", "obj_abajo"), ("ta", "toca_arriba"), ("tb", "toca_abajo"), ("pa", "primero_arriba"))}))

        sc, cone = scenarios(bars, idxs, price, tf_ms, vol_factor(series[tf], SCENARIO_STEPS),
                             calibracion(series[tf], main_fit["receta"], SCENARIO_STEPS)["k"])
        for r in sc + cone:
            r["tf"] = tf
        rows += sc + cone
        for k in range(max(0, i - CHART_BARS + 1), i + 1):
            t, o_, h_, l_, c_, v_ = bars[k]
            rows.append({"tabla": "vela", "tf": tf, "t": t, "o": o_, "h": h_, "l": l_, "c": c_, "v": round(v_, 2),
                         "en_curso": partial and k == i,
                         "ema20": rp(overlays["ema20"][k]), "ema50": rp(overlays["ema50"][k]),
                         "ema200": rp(e200[k]) if k >= 199 else None,       # con menos de 200 velas atras no vale
                         "bb_up": rp(overlays["bb_up"][k]),
                         "bb_lo": rp(overlays["bb_lo"][k]),
                         "rsi": None if rsi[k] is None else round(rsi[k], 1), "macd": round(ml[k], dec_precio(price) + 1),
                         "macd_senal": round(ms[k], dec_precio(price) + 1), "macd_hist": round(mh[k], dec_precio(price) + 1)})

    for tf in TF_LARGOS:                  # semanal y mensual con las diarias (sin prediccion)
        rows += analisis_largo(d1_largo + full["1d"][len(candles["1d"]):], tf, price, len(full["1d"]) > len(candles["1d"]))

    # una prediccion por plazo, cada una con la temporalidad que mas casos tiene para ese plazo
    for name, tf, h, *_ in PLAZOS:
        fit = tune(tf, series[tf], h)
        prob, tg = horizon_stats(tf, series[tf], h, price, fit)
        rows.append({"tabla": "plazo", "plazo": name, **prob})
        rows += learning_rows(name, tf, h, fit)
        rows += [{"tabla": "objetivo_plazo", "plazo": name, **t} for t in tg]
        if not any(e[1] == tf and e[2] == h for e in entries):
            entries.append((series[tf]["bars"][-1][0] + series[tf]["tf_ms"], tf, h, series[tf]["closes"][-1], prob["sube"],
                            prob["min"], prob["max"], {c: prob.get(k) for c, k in (("m", "mediana"), ("a", "obj_arriba"), ("b", "obj_abajo"), ("ta", "toca_arriba"), ("tb", "toca_abajo"), ("pa", "primero_arriba"))}))

    # niveles clave
    h1, d1 = candles["1h"], candles["1d"]
    levels = []
    for name, n in (("24 h", 24), ("7 días", 168), ("30 días", 720)):
        levels += [(f"Mínimo {name}", min(b[3] for b in h1[-n:])), (f"Máximo {name}", max(b[2] for b in h1[-n:]))]
    levels += [(f"Pivote {k}", v) for k, v in ind.pivotes(d1[-1]).items()]
    fib = fibonacci(candles["4h"])
    closes_d = [b[4] for b in d1]
    sma200d = sum(closes_d[-200:]) / 200
    ema200d = ind.ema(closes_d, 200)[-1]
    levels += [("Media simple 200 días", sma200d), ("EMA 200 diaria", ema200d)]
    for name, v in levels:
        rows.append({"tabla": "nivel", "nombre": name, "precio": rp(v),
                     "tipo": "resistencia" if v > price else "soporte", "distancia": round(pct(v, price), 2)})
    for f, v in fib:
        rows.append({"tabla": "nivel", "nombre": f"Fibonacci {ar(f * 100, 1)}% (90 d) · rebotó {FIB_REBOTE[f]}%", "precio": rp(v),
                     "tipo": "resistencia" if v > price else "soporte", "distancia": round(pct(v, price), 2),
                     "fib": f, "rebote": FIB_REBOTE[f]})
    tramo = fib_tramo(candles["4h"])
    if tramo:
        rows.append({"tabla": "fib_tramo", "t_inicio": tramo["t_inicio"], "p_inicio": rp(tramo["p_inicio"]),
                     "t_fin": tramo["t_fin"], "p_fin": rp(tramo["p_fin"])})

    try:
        ctx, funding = cached("contexto", 60, lambda: context(bgx, h1))
        rows += ctx
    except Exception as e:  # el contexto es complementario: si una fuente falla, el resto sirve
        funding = None
        rows.append({"tabla": "contexto", "clave": "error", "titulo": "Contexto no disponible", "valor": "",
                     "senal": "neutral",
                     "detalle": ("El exchange limitó los pedidos por un rato: funding, interés abierto y liquidaciones vuelven solos en los próximos análisis."
                                 if type(e).__name__ in ("DDoSProtection", "RateLimitExceeded", "ExchangeNotAvailable", "NetworkError", "RequestTimeout")
                                 else f"No se pudo leer: {type(e).__name__}")})
    try:   # opciones de BTC (Deribit): volatilidad implicita, puts/calls, dolor maximo del viernes. Contexto
        libro, dv = cached("opciones", 600, lambda: opciones_deribit(now_ms))
        rows += opciones(libro, dv, price, now_ms)
    except Exception as e:
        print(f"(opciones no disponibles: {type(e).__name__})")
    try:   # noticias, ETF y prima de Coinbase: para explicar los movimientos fuertes
        rows += cached("externo", 600, noticias.externo)
    except Exception as e:
        print(f"(noticias no disponibles: {type(e).__name__})")
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
        # con open interest y long/short de Bybit (a Binance solo se le pide el funding)
        heat = cached("liquidaciones", 300, lambda: liquidation_map_bybit(h1))
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
    global ULTIMAS_PREDICCIONES
    ULTIMAS_PREDICCIONES = entries   # las del modo en vivo van al historial constante (historial.py)
    for (tf, h), (n, hits, brier, nr, adentro) in sorted(log_and_score(entries, closes_by_tf).items()):
        if not n and not nr:        # sin casos medibles no hay nada que mostrar
            continue
        tf_min = ccxt.Exchange.parse_timeframe(tf) // 60
        rows.append({"tabla": "acierto", "tf": tf, "horizonte": label(h * tf_min), "pronosticos": n,
                     "aciertos": round(hits / n * 100, 1) if n else None, "brier": round(brier / n, 3) if n else None,
                     # el rango del 80% es honesto si el precio termina adentro ~80% de las veces
                     "con_rango": nr, "en_rango": round(adentro / nr * 100, 1) if nr else None})

    comp = compresion(candles.get("1h"))
    if comp:
        rows.append(comp)
    hs = perfil_horas(candles.get("1h"))
    if hs:
        rows.append(hs)
    mov = movimiento(candles["5m"], price)
    if mov:
        # movimiento fuerte segun el modelo de arboles (fuerte.py): mucho mejor que la tabla (ver README)
        try:
            pf = fuerte.prever(candles["1h"], [r["t"] for r in rows if r.get("tabla") == "evento"])
        except Exception as e:
            print(f"(modelo de movimiento fuerte no disponible: {type(e).__name__}: {e})")
            pf = None
        if pf:
            mov.update(modelo_1h=pf["1h"], modelo_4h=pf["4h"], modelo_base_1h=pf["base_1h"], modelo_base_4h=pf["base_4h"],
                       modelo_hasta=candles["1h"][-1][0] + 2 * 3600000)
        rows.append(mov)
    try:                                   # termometro de compra/venta del ciclo de BTC (termometro.py)
        fg = next((r for r in rows if r.get("tabla") == "contexto" and r.get("clave") == "miedo_codicia"), None)
        fu = next((r for r in rows if r.get("tabla") == "contexto" and r.get("clave") == "funding"), None)
        tm = termometro.termometro([b[4] for b in candles["1d"]], price, fng=fg["fng"] if fg else None, now_ms=now_ms,
                                   f7=fu.get("f7") if fu else None)
        if tm:
            rows.append(tm)
    except Exception as e:
        print(f"(termometro no disponible: {type(e).__name__}: {e})")
    try:                                   # minimo probable en los proximos 6 meses (termometro.piso)
        pi = termometro.piso("BTC", [b[4] for b in candles["1d"]], price, now_ms=now_ms)
        if pi:
            rows.append(pi)
    except Exception as e:
        print(f"(minimo a 6 meses no disponible: {type(e).__name__}: {e})")
    lado = coinciden(rows)
    for r in rows:
        if r["tabla"] == "plazo" and r["plazo"] == "1 hora":
            r["coinciden"] = lado
    explanation = [e for spec in PLAZOS for e in explain(rows, price, spec)]
    rows += explanation
    rows += central(rows, price, candles, now_ms)
    # al historial (historial.py): lo que decia del movimiento fuerte de la proxima hora (fuerte = el rango de la hora
    # siguiente pasa el doble del normal: umbral u, en %), como la version JS
    c1 = next((r for r in rows if r["tabla"] == "central" and r.get("plazo") == "1 hora"), None)
    mv = next((r for r in rows if r["tabla"] == "movimiento"), None)
    if c1:
        for e in entries:
            if len(e) > 7 and isinstance(e[7], dict):
                e[7].update({"f": c1.get("fuerza"), "pf": c1.get("prob_fuerte"), "pn": c1.get("prob_normal"),
                             "u": round(2 * mv["normal_pct"], 2) if mv and mv.get("normal_pct") else None})
    takeaway = next(e["texto"] for e in explanation if e["plazo"] == "1 hora" and e["tipo"] == "titular")
    local = datetime.fromtimestamp(now_ms / 1000, LOCAL_TZ)
    rows.insert(0, {"tabla": "resumen", "fecha": datetime.now(LOCAL_TZ).isoformat(timespec="milliseconds"),
                    "hora_local": local.strftime("%d/%m %H:%M"), "precio": rp(price),
                    "cambio_24h": round2(change_since(candles["5m"], now_ms, price, 24)),
                    "cambio_7d": round2(change_since(candles["5m"], now_ms, price, 168)),
                    "sma200d": rp(sma200d), "sma200d_dist": round(pct(price, sma200d), 2),
                    "ema200d": rp(ema200d), "ema200d_dist": round(pct(price, ema200d), 2),
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
        print("\nACIERTOS  " + "  ".join(f"{a['tf']} a {a['horizonte']}: {a['aciertos']:.0f}% ({a['pronosticos']})" for a in hits
                                       if a["aciertos"] is not None))


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
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --color-fg: #e8eaee; --color-fg-muted: #949bab; --color-bg: #121418; --color-panel: #1b1e24;
  --color-border-line: #2b3038; --color-ok: #3cc58a; --color-warn: #e0a64a; --color-bad: #f0645a; --cds-chart-grid: #252a31;
  --cds-surface-popover: #22262d; --cds-border: #343a43; --cds-shadow-popover: 0 6px 24px rgba(0,0,0,.45); --cds-text-secondary: #949bab; color-scheme: dark; } }
:root[data-theme="dark"] { --color-fg: #e8eaee; --color-fg-muted: #949bab; --color-bg: #121418; --color-panel: #1b1e24;
  --color-border-line: #2b3038; --color-ok: #3cc58a; --color-warn: #e0a64a; --color-bad: #f0645a; --cds-chart-grid: #252a31;
  --cds-surface-popover: #22262d; --cds-border: #343a43; --cds-shadow-popover: 0 6px 24px rgba(0,0,0,.45); --cds-text-secondary: #949bab; color-scheme: dark; }
html { touch-action: manipulation; }   /* sin zoom por doble toque en el telefono */
body { margin: 0; background: var(--color-bg); color: var(--color-fg); font: 14px var(--font-anthropic-sans); }
#dash-root { padding-block: 24px 40px; padding-left: max(16px, var(--dash-gutter, 24px)); padding-right: max(16px, var(--dash-gutter, 24px)); }
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@5.1.0/dist/lightweight-charts.standalone.production.js"></script>
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
  try { var tm = localStorage.getItem('ab-tema'); if (tm === 'dark' || tm === 'light') document.documentElement.dataset.theme = tm; } catch (e) { /* sin almacenamiento */ }
  window.abOscuro = function () { var t = document.documentElement.dataset.theme; return t ? t === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches; };
  window.dash = {
    get colors() { return window.abOscuro() ? ['#4a8af4', '#bf7f1a', '#9270f0', '#14a394', '#f08bb4', '#a3e635', '#fb923c', '#94a3b8']
                                            : ['#2563eb', '#d97706', '#7c3aed', '#0f9488', '#d1477e', '#4d7c0f', '#c2410c', '#64748b']; },
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
    plan = bg.leer_plan()        # seccion Proximas compras: el plan privado (la pagina de Render ya pide contraseña)
    if plan:
        page = page.replace("/*PLAN*/null/*FIN*/", json.dumps(plan, ensure_ascii=False).replace("</", "<\\/"))
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

    _GZ = {}                                     # ultima pagina comprimida (se rehace cuando cambia el archivo)

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
            if self.comprimido():
                return
            super().do_GET()

        def comprimido(self):
            """La pagina con los datos adentro pesa cerca de 1 MB: comprimida con gzip baja unas 6 veces (si el navegador acepta)."""
            import gzip
            if "gzip" not in self.headers.get("Accept-Encoding", ""):
                return False
            path = self.translate_path(self.path)
            if os.path.isdir(path):
                if not self.path.split("?")[0].endswith("/"):
                    return False                      # la redireccion a ".../" la hace la clase base
                path = os.path.join(path, "index.html")
            if not path.endswith((".html", ".json", ".js", ".css", ".txt")) or not os.path.isfile(path):
                return False
            try:
                clave = (path, os.stat(path).st_mtime_ns)
                data = _GZ.get(clave)
                if data is None:
                    with open(path, "rb") as fh:
                        data = gzip.compress(fh.read(), 6)
                    _GZ.clear()
                    _GZ[clave] = data
            except OSError:
                return False
            self.send_response(200)
            self.send_header("Content-Type", self.guess_type(path))
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Vary", "Accept-Encoding")
            self.end_headers()
            self.wfile.write(data)
            return True

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
        avisos.iniciar_comandos()
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
                if public:
                    try:                 # el historial de predicciones para "Reproducir" (rama historial del repo)
                        historial.anotar(getattr(live_mod, "ULTIMAS_PREDICCIONES", None))
                        historial.anotar_libro()
                    except Exception as e:
                        print(f"(historial: {type(e).__name__}: {e})", flush=True)
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
