"""¿Se viene un movimiento fuerte? Modelo de arboles (LightGBM) entrenado con velas de 1 hora de BTC 2021-2026.

"Movimiento fuerte" = en la proxima hora (o en las proximas 4) BTC se mueve mas del doble de lo habitual, para
cualquier lado. Medido sin mirar el futuro (entrenando con el pasado y probando cada trimestre siguiente), mucho mejor
que la tabla de antes (que solo miraba que tan agitado estaba el mercado):
  ventaja sobre la tasa base, proxima hora:  tabla 3,7% / 4,3% / 4,2%  ->  modelo 9,3% / 11,0% / 11,8%  (2023-24 / 2025 / 2026)
  el 10% de horas que el modelo ve mas peligrosas: fuerte 36-37% de las veces (tabla: 26-27%; una hora cualquiera: 12%)
  proximas 4 horas: 7,3% / 7,1% / 8,7%
No dice para donde (para la direccion no sirvio: ver README).

Las señales salen solo de las velas de 1 hora cerradas (retornos, volatilidad, medias, RSI, MACD, volumen, posicion
en el rango, hora del dia) y del calendario de datos fuertes de EE.UU. Los arboles estan en
JavascriptVersion/modelo_fuerte.json (los arma entrenar_fuerte.py; lo leen las dos versiones). La version JavaScript es JavascriptVersion/fuerte.js: mismas cuentas, mismos numeros.
"""
import json
import math
import os

H = 3600000
NOMBRES = ["ret1", "ret2", "ret4", "ret8", "ret12", "ret24", "ret48", "ret72", "ret168", "ret336",
           "vol6", "vol24", "vol72", "vol168", "vol720", "volratio", "volratio2", "rango", "cuerpo",
           "ema20", "ema50", "ema200", "ema800", "rsi14", "rsi56", "macdh", "volz", "vol24_168",
           "pos24", "dd24", "pos168", "dd168", "pos720", "dd720", "hora_s", "hora_c", "finde", "evento_prox", "evento_ult"]
MINIMO = 900          # velas de 1 hora cerradas que hacen falta
_MODELO = None


def _std(xs):
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def _ema_last(xs, span):
    a = 2 / (span + 1)
    m = xs[0]
    for x in xs:
        m = a * x + (1 - a) * m
    return m


def _ema_series(xs, span):
    a = 2 / (span + 1)
    m, out = xs[0], []
    for x in xs:
        m = a * x + (1 - a) * m
        out.append(m)
    return out


def _rsi_last(c, p):
    a = 1 / p                                  # ema de span 2p-1 = Wilder
    up = dn = 0.0
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]
        up = a * (d if d > 0 else 0.0) + (1 - a) * up
        dn = a * (-d if d < 0 else 0.0) + (1 - a) * dn
    return 100 - 100 / (1 + up / max(dn, 1e-12))


def señales(bars, eventos=()):
    """bars: velas de 1 hora cerradas [t, o, h, l, c, v] (t = apertura, ms UTC), en orden. eventos: horas (ms UTC) de
    los datos fuertes de EE.UU. Devuelve las señales de la ultima vela, en el orden de NOMBRES (o None si faltan velas)."""
    if len(bars) < MINIMO:
        return None
    t = [b[0] for b in bars]; o = [b[1] for b in bars]; h = [b[2] for b in bars]; l = [b[3] for b in bars]
    c = [b[4] for b in bars]; v = [b[5] for b in bars]
    n = len(c); i = n - 1
    lc = [math.log(x) for x in c]
    r1 = [0.0] + [lc[k] - lc[k - 1] for k in range(1, n)]
    f = {}
    for k in (1, 2, 4, 8, 12, 24, 48, 72, 168, 336):
        f[f"ret{k}"] = lc[i] - lc[i - k]
    for w in (6, 24, 72, 168, 720):
        f[f"vol{w}"] = _std(r1[i - w + 1:i + 1])
    s = f["vol168"]
    f["volratio"] = f["vol6"] / s
    f["volratio2"] = f["vol24"] / f["vol720"]
    f["rango"] = (h[i] - l[i]) / c[i] / s
    f["cuerpo"] = (c[i] - o[i]) / c[i] / s
    for span in (20, 50, 200, 800):
        f[f"ema{span}"] = (c[i] / _ema_last(c, span) - 1) / s
    f["rsi14"] = _rsi_last(c, 14)
    f["rsi56"] = _rsi_last(c, 56)
    e12, e26 = _ema_series(c, 12), _ema_series(c, 26)
    macd = [x - y for x, y in zip(e12, e26)]
    f["macdh"] = (macd[i] - _ema_last(macd, 9)) / c[i] / s
    lv = [math.log1p(x) for x in v[i - 167:i + 1]]
    f["volz"] = (lv[-1] - sum(lv) / 168) / _std(lv)
    f["vol24_168"] = (sum(v[i - 23:i + 1]) / 24) / (sum(v[i - 167:i + 1]) / 168)
    for w in (24, 168, 720):
        hi, lo = max(h[i - w + 1:i + 1]), min(l[i - w + 1:i + 1])
        f[f"pos{w}"] = (c[i] - lo) / max(hi - lo, 1e-9)
        f[f"dd{w}"] = c[i] / hi - 1
    hr = (t[i] // H) % 24
    f["hora_s"], f["hora_c"] = math.sin(2 * math.pi * hr / 24), math.cos(2 * math.pi * hr / 24)
    f["finde"] = 1.0 if ((t[i] // (24 * H)) + 3) % 7 >= 5 else 0.0
    cierre = t[i] + H
    f["evento_prox"] = 1.0 if any(cierre <= e <= cierre + 4 * H for e in eventos) else 0.0
    f["evento_ult"] = 1.0 if any(cierre - 2 * H <= e < cierre for e in eventos) else 0.0
    return [f[k] for k in NOMBRES]


def _arbol(nodo, x):
    while isinstance(nodo, list):
        f, thr, izq, der = nodo
        nodo = izq if x[f] <= thr else der
    return nodo


def probabilidad(modelo, x):
    z = sum(_arbol(a, x) for a in modelo["arboles"])
    return 1 / (1 + math.exp(-z))


def modelo():
    global _MODELO
    if _MODELO is None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "JavascriptVersion", "modelo_fuerte.json"), encoding="utf-8") as fh:
            _MODELO = json.load(fh)
    return _MODELO


def prever(bars, eventos=()):
    """Probabilidad de movimiento fuerte en la proxima hora y en las proximas 4 (0-100), o None."""
    x = señales(bars, eventos)
    if x is None:
        return None
    M = modelo()
    return {"1h": round(probabilidad(M["1h"], x) * 100, 1), "4h": round(probabilidad(M["4h"], x) * 100, 1),
            "base_1h": M["1h"]["base"], "base_4h": M["4h"]["base"]}
