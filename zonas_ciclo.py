"""Zonas de compra y de venta del ciclo de BTC (medidas con medir_zonas.py, nov. 2026).

Criterio: estando en la zona (aunque dure meses), a un año BTC subio 10 puntos o mas que un dia cualquiera (zona de
compra) o 10 o menos (venta), en 2012-19 y en 2020-25. Un dia cualquiera: subio a un año 78% (2012-19) y 60% (2020-25).
No marcan el punto exacto: marcan zonas. Quedaron afuera porque no separaron en los dos tramos: Delta Price, hash
ribbons, Fear & Greed y el RSI semanal como zona de venta; NUPL es el MVRV escrito de otra forma (no se repite).

armar_termometro.py llama a calcular() cada semana y guarda el resultado en termometro.json ("zonas"); la pagina lo
termina con el precio de ahora: para los que dependen del precio guarda un multiplicador (valor = precio x k).
"""
import math

import numpy as np

# id, nombre, como se calcula, zona de compra, zona de venta, lo medido (a 365 dias: % que subio en 2012-19 / 2020-25)
# zona: ("<=", numero) umbral clasico, ("p", 15) percentil de su historia, None: no sirvio para ese lado
ZONAS = (
    ("puell", "Puell (emisión del día / media del año)", ("<=", 0.5), ("p", 85), "96–99%", "30–50%"),
    ("mayer", "Mayer (precio / media de 200 días)", None, (">=", 2.4), None, "38–47%"),
    ("ma2a", "Media de 2 años", ("<=", 1.0), ("p", 85), "94–100%", "10–49%"),
    ("ma200s", "Media de 200 semanas", ("<=", 1.0), (">=", 4.0), "100%", "21–39%"),
    ("golden", "Golden Ratio (precio / media de 350 días)", ("<=", 0.8), (">=", 3.0), "83–89%", "19–45%"),
    ("pi", "Pi Cycle (media de 111 / 2 × media de 350)", ("<=", 0.35), ("p", 85), "100%", "0%"),
    ("potencia", "Ley de potencia (desvío del ajuste)", ("p", 15), ("p", 85), "89–100%", "15–33%"),
    ("metcalfe", "Metcalfe (precio contra direcciones activas)", None, ("p", 85), None, "39–48%"),
)


def _sma(x, n):
    c = np.cumsum(np.insert(np.nan_to_num(x), 0, 0.0))
    out = np.full(len(x), np.nan)
    out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def calcular(dia, P, sup, iss_usd, adr):
    """dia: dias desde 1970 (int), P: precio, sup: BTC en circulacion, iss_usd: emision del dia en USD, adr: direcciones
    activas (np.nan si falta). Devuelve la lista de zonas con lo que la pagina necesita para el valor de hoy."""
    P = np.asarray(P, float)
    n = len(P)
    out = []

    def umbral(serie, z):
        if z is None:
            return None
        if z[0] == "p":
            v = serie[np.isfinite(serie)]
            return float(np.percentile(v, z[1])) if len(v) > 730 else None
        return float(z[1])

    for zid, nom, zc, zv, mc, mv in ZONAS:
        e = {"id": zid, "nombre": nom, "compra_medido": mc, "venta_medido": mv}
        if zid in ("mayer", "ma2a", "ma200s", "golden"):
            k = {"mayer": 200, "ma2a": 730, "ma200s": 1400, "golden": 350}[zid]
            m = _sma(P, k)
            serie = P / m
            e["k"] = 1.0 / float(m[-1])                      # valor de hoy = precio x k
        elif zid == "pi":
            serie = _sma(P, 111) / (2 * _sma(P, 350))
            e["valor"] = float(serie[-1])
        elif zid == "puell":
            ma = _sma(np.asarray(iss_usd, float), 365)
            serie = np.asarray(iss_usd, float) / ma
            # hoy: BTC emitidos por dia (promedio del ultimo mes) x precio / media del año en USD
            btc = np.nanmean((np.asarray(iss_usd, float) / P)[-30:])
            e["k"] = float(btc / ma[-1])
        elif zid == "metcalfe":
            a30 = _sma(np.asarray(adr, float), 30)
            serie = P * np.asarray(sup, float) / a30 ** 2
            e["k"] = float(sup[-1] / a30[-1] ** 2) if np.isfinite(a30[-1]) else None
        elif zid == "potencia":
            gen = 14247                                       # 3/1/2009 en dias desde 1970
            lx = np.log10(np.asarray(dia, float) - gen)
            ly = np.log10(P)
            ok = np.isfinite(lx) & np.isfinite(ly)
            b, a = np.polyfit(lx[ok], ly[ok], 1)
            serie = ly - (a + b * lx)
            e.update({"a": float(a), "b": float(b), "gen": gen})   # valor de hoy = log10(precio) - (a + b log10(dias))
        if e.get("k") is None and "valor" not in e and "a" not in e:
            continue
        e["compra"] = umbral(serie, zc)
        e["venta"] = umbral(serie, zv)
        v = serie[np.isfinite(serie)]
        e["min"], e["max"] = float(np.percentile(v, 1)), float(np.percentile(v, 99))   # la escala de la barra
        e["log"] = zid in ("ma2a", "ma200s", "golden", "mayer", "puell", "metcalfe")     # razones: escala logaritmica
        out.append({k: (float(f"{x:.8g}") if isinstance(x, float) else x) for k, x in e.items()})
    return out
