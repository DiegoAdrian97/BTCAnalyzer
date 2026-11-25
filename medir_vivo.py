"""¿Sirven las PROBABILIDADES y los RANGOS que da el analisis, no solo la conclusion central? (con lo que fue diciendo en vivo)

El servidor guarda cada prediccion en la rama `historial` (historial/BTC/<tf>/<dia>.csv, ver historial.COLUMNAS):
t = cierre de la vela en curso de esa temporalidad, precio = precio en vivo al analizar, sube = % de que cierre arriba,
min/max = rango del 80%. Aca se cruza con lo que hizo el precio (velas de 5 min {apertura: cierre}). Todo puro, sin red:
medir_central.py baja los archivos y las velas y llama a evaluar_vivo().

Resultado de cada fila (igual que analisis_btc.log_and_score): el cierre de la vela de la temporalidad que cierra en
t + h * tf_ms; con velas de 5 min, la vela de 5 min que abre 5 min antes de ese instante. Sube si ese cierre > precio.
Las filas se pisan (h velas seguidas comparten resultado): n_ef = n / h.
"""
import math

V = 300000                         # una vela de 5 min en ms
DIA = 86400000
CLIMA_DIAS = 30                    # la tasa normal de cada fila: % de subas de ese (tf, h) en los 30 dias anteriores
COSTO_PB = 10                      # comision ida y vuelta en puntos base: taker 0,05% por lado, como la pagina
MIN_CLIMA = 10                     # casos minimos en esos 30 dias para calcular la tasa normal
POCOS = 100                        # casos efectivos minimos para decir algo
TF_MS = {"5m": 300000, "15m": 900000, "30m": 1800000, "1h": 3600000, "4h": 14400000, "1d": 86400000}
TFS = tuple(TF_MS)


def horizonte_txt(tf, h):
    """'1 hora', '30 min', '2 días': lo que dura h velas de esa temporalidad."""
    m = TF_MS[tf] * h // 60000
    if m < 60:
        return f"{m} min"
    if m < 1440:
        return f"{m // 60} {'hora' if m == 60 else 'horas'}" if m % 60 == 0 else f"{m} min"
    return f"{m // 1440} {'día' if m == 1440 else 'días'}" if m % 1440 == 0 else f"{m // 60} horas"


def _num(x):
    try:
        return float(x) if x not in (None, "") else None
    except ValueError:
        return None


def leer(texto, tf):
    """CSV de historial/BTC/<tf>/<dia>.csv -> filas {tf, t, h, precio, sube, min, max, mediana} (las columnas se buscan por nombre)."""
    lineas = texto.splitlines()
    if not lineas:
        return []
    col = {c: i for i, c in enumerate(lineas[0].split(","))}
    out = []
    for ln in lineas[1:]:
        p = ln.split(",")
        try:
            g = lambda k: _num(p[col[k]]) if k in col and col[k] < len(p) else None
            t, h, precio, sube = g("t"), g("h"), g("precio"), g("sube")
        except (KeyError, IndexError):
            continue
        if None in (t, h, precio, sube) or h < 1 or precio <= 0:
            continue
        out.append({"tf": tf, "t": int(t), "h": int(h), "precio": precio, "sube": sube, "min": g("min"), "max": g("max"),
                    "mediana": g("mediana")})
    return out


def _tasas(tf, h, P, t_ini, t_fin):
    """Devuelve f(t) -> (tasa de subas, casos) de los CLIMA_DIAS anteriores a t, sin usar nada posterior a t:
    solo origenes s (en la grilla de la temporalidad) con s + h*tf_ms <= t. Se arma con sumas acumuladas."""
    tm = TF_MS[tf]
    hm = h * tm
    g0 = (t_ini - CLIMA_DIAS * DIA) // tm * tm
    n_g = int((t_fin - g0) // tm) + 1
    cn, cu = [0], [0]
    for i in range(n_g):
        s = g0 + i * tm
        a, b = P.get(s - V), P.get(s + hm - V)
        ok = a is not None and b is not None
        cn.append(cn[-1] + ok)
        cu.append(cu[-1] + (ok and b > a))

    def tasa(t):
        lo = max(0, -(-(t - CLIMA_DIAS * DIA - g0) // tm))
        hi = min(n_g - 1, (t - hm - g0) // tm)
        if hi < lo:
            return None, 0
        n = cn[hi + 1] - cn[lo]
        return (None, n) if n < MIN_CLIMA else ((cu[hi + 1] - cu[lo]) / n, n)
    return tasa


def distancia_rango(r, lo, hi, m):
    """Cuantos rangos del 80% (medidos desde la mediana m) se alejo el resultado r: d = (r - m)/(hi - m) si r >= m,
    (m - r)/(m - lo) si r < m. None si el rango no rodea a m (hi <= m o lo >= m)."""
    if hi <= m or lo >= m:
        return None
    return (r - m) / (hi - m) if r >= m else (m - r) / (m - lo)


def factor_80(ds):
    """(factor, cobertura con el factor): el cuantil 0,8 de d (como rango_factor de analisis_btc.py) lleva la cobertura al 80%.
    El factor se redondea a 3 y la cobertura se calcula con el ya redondeado."""
    if not ds:
        return None, None
    xs = sorted(ds)
    f = round(xs[min(int(0.8 * len(xs)), len(xs) - 1)], 3)
    return f, round(100 * sum(d <= f for d in xs) / len(xs), 1)


def evaluar_vivo(F, P, ahora):
    """Puro: filas {tf,t,h,precio,sube,min,max} + {apertura: cierre} de velas de 5 min -> (probabilidades, rangos)."""
    grupos = {}
    for r in F:
        if r["tf"] in TF_MS:
            grupos.setdefault((r["tf"], r["h"]), []).append(r)
    primera = min(P) if P else 0
    probs, rangos = [], []
    for (tf, h), filas in sorted(grupos.items(), key=lambda kv: (TF_MS[kv[0][0]] * kv[0][1], kv[0][0])):
        tm = TF_MS[tf]
        tasa = _tasas(tf, h, P, min(r["t"] for r in filas), max(r["t"] for r in filas))
        n = nm = 0
        sb = sm = sbc = sl = 0.0               # Brier, Brier del modelo y de la tasa normal (solo filas con tasa), log loss
        dias = None
        bins = [[0, 0.0, 0] for _ in range(5)]  # n, suma de prob, subas
        nr = adentro = 0
        ds = []
        sa = sw = 0.0
        for r in filas:
            fin = r["t"] + h * tm
            c = P.get(fin - V) if fin <= ahora else None
            if c is None:
                continue
            up = 1 if c > r["precio"] else 0
            p = min(1.0, max(0.0, r["sube"] / 100))
            n += 1
            sb += (p - up) ** 2
            pc = min(0.99, max(0.01, p))
            sl -= up * math.log(pc) + (1 - up) * math.log(1 - pc)
            b = bins[min(4, int(p * 5))]
            b[0] += 1; b[1] += p; b[2] += up
            q = tasa(r["t"])[0]
            if q is not None:
                nm += 1
                sm += (p - up) ** 2
                sbc += (q - up) ** 2
                d = min(CLIMA_DIAS, (r["t"] - primera) / DIA)
                dias = d if dias is None else min(dias, d)
            lo, hi = r["min"], r["max"]
            if lo is not None and hi is not None and hi >= lo:
                nr += 1
                adentro += lo <= c <= hi
                m = r.get("mediana")
                d = distancia_rango(c, lo, hi, (lo + hi) / 2 if m is None else m)
                if d is not None:
                    ds.append(d)
                ancho = (hi - lo) / r["precio"] * 100
                fuera = max(lo - c, c - hi, 0) / r["precio"] * 100
                sa += ancho
                sw += ancho + (2 / 0.2) * fuera
        if not n:
            continue
        hz = horizonte_txt(tf, h)
        ne_n = nm / h
        vn = None if not nm or not sbc else round(100 * (1 - sm / sbc), 2)
        probs.append({"tf": tf, "h": h, "horizonte": hz, "n": n, "n_ef": round(n / h, 1), "brier": round(sb / n, 4),
                      "ventaja_50": round(100 * (1 - sb / n / 0.25), 2), "ventaja_normal": vn, "n_normal": nm,
                      "n_ef_normal": round(ne_n, 1), "clima_dias": None if dias is None else round(dias, 1),
                      "logloss": round(sl / n, 4),
                      "calibracion": [{"desde": 20 * i, "hasta": 20 * (i + 1), "n": x[0], "prob": round(100 * x[1] / x[0], 1),
                                       "real": round(100 * x[2] / x[0], 1)} for i, x in enumerate(bins) if x[0]],
                      **({"pocos": True} if vn is None or ne_n < POCOS else {})})
        if nr:
            f80, cob80 = factor_80(ds)
            rangos.append({"tf": tf, "h": h, "horizonte": hz, "n": nr, "n_ef": round(nr / h, 1), "cobertura": round(100 * adentro / nr, 1),
                           "ancho": round(sa / nr, 3), "winkler": round(sw / nr, 3), "factor_80": f80, "cobertura_factor": cob80,
                           **({"pocos": True} if nr / h < POCOS else {})})
    return probs, rangos

