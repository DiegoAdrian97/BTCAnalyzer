"""Termometro de compra/venta del ciclo de BTC (0 = frio, buena zona de compra; 100 = caliente, zona de venta).

Compara tres medidas con toda la historia de BTC desde 2011 (JavascriptVersion/termometro.json, lo arma
armar_termometro.py): que tan lejos esta el precio de su media de 200 semanas, cuanto cayo desde el maximo historico
y cuanto subio o bajo en el ultimo año. Medido desde 2019, sin mirar el futuro: en "compra fuerte" BTC estaba mas
arriba 12 meses despues el 98% de las veces; en "zona de venta", el 23%. Es para semanas o meses, no para horas.
La version JavaScript esta en JavascriptVersion/analisis.js (termometro): mismas cuentas, mismos numeros.
"""
import json
import math
import os

_T = None


def _datos():
    global _T
    if _T is None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "JavascriptVersion", "termometro.json"), encoding="utf-8") as fh:
            _T = json.load(fh)
    return _T


def percentil(v, q):
    """Que parte de la historia (0-100) quedo por debajo de v. q: 201 cuantiles de 0 a 100%."""
    if v <= q[0]:
        return 0.0
    if v >= q[-1]:
        return 100.0
    for i in range(1, len(q)):
        if v <= q[i]:
            lo, hi = q[i - 1], q[i]
            f = 0.0 if hi == lo else (v - lo) / (hi - lo)
            return (i - 1 + f) / (len(q) - 1) * 100
    return 100.0


def fase(y):
    """Ciclo de 4 años: 2014, 2018, 2022, 2026... bajistas; los tres de en medio, alcistas 1, 2 y 3."""
    return "bajista" if y % 4 == 2 else f"alcista {(y - 3) % 4 + 1}"


def ajuste_funding(md, f7):
    """+1 si el funding promedio de 7 dias es negativo (miedo: compra), -1 si es 0,03% o mas cada 8 h (euforia), 0 si no."""
    fu = (md or {}).get("funding")
    if not fu or f7 is None:
        return 0
    return 1 if f7 < fu["bajo"] else -1 if f7 >= fu["alto"] else 0


def termometro(closes_d, price, T=None, fng=None, now_ms=None, f7=None):
    """Fila del termometro. closes_d: cierres diarios (al menos 1400); fng: Fear & Greed Index de hoy; now_ms: ahora;
    f7: funding promedio de los ultimos 7 dias (por cada 8 h, 0.0001 = 0,01%). None si falta historia."""
    T = T or _datos()
    if len(closes_d) < 1400 or price <= 0:
        return None
    wma = sum(closes_d[-1400:]) / 1400
    ath = max(T["ath"], max(closes_d), price)
    med = {"wma200": math.log(price / wma), "dd_ath": price / ath - 1, "ret365": math.log(price / closes_d[-365])}
    p = {k: percentil(med[k], T["q"][k]) for k in T["componentes"]}
    temp = sum(p.values()) / len(p)
    z = next(z for z in T["zonas"] if temp < z["hasta"] or z["hasta"] >= 100)
    import time
    y = time.gmtime((now_ms or time.time() * 1000) / 1000).tm_year
    fs = fase(y)
    regla = None
    if fng is not None:
        regla = ("miedo_bajista" if fng < 25 and fs == "bajista" else "codicia_alcista3" if fng > 75 and fs == "alcista 3"
                 else "codicia_alcista12" if fng > 75 and fs in ("alcista 1", "alcista 2") else None)
    cic = T.get("ciclo") or {}
    # medidor de compra/venta: mitad logica inversa (1 - temperatura) y mitad momento del ciclo (armar_termometro.py)
    av = (time.gmtime((now_ms or time.time() * 1000) / 1000).tm_yday - 1) / 366
    md = T.get("medidor")
    pos_m = prob = zm = None
    adj = ajuste_funding(md, f7)
    if md:
        ph = (y - 2) % 4
        x = [float(ph == 1), float(ph == 2), float(ph == 3), (ph == 0) * av, (ph == 3) * av]
        prob = 1 / (1 + math.exp(-(md["intercepto"] + sum(w * v for w, v in zip(md["pesos"], x)))))
        S = md["peso_valuacion"] * (1 - temp / 100) + (1 - md["peso_valuacion"]) * prob
        S += (md.get("funding") or {}).get("peso", 0) * adj       # funding extremo de 7 dias: mueve el medidor un poco
        zm = next(q for q in md["zonas"] if q["desde"] <= S < q["hasta"])
        pos_m = min(100.0, max(0.0, (1 - S) * 100))
    return {"tabla": "termometro", "medidor": None if pos_m is None else round(pos_m, 1), "medidor_zona": zm["nombre"] if zm else None,
            "m_sube_180": zm["sube_180"] if zm else None, "m_mediana_180": zm["mediana_180"] if zm else None,
            "m_sube_365": zm["sube_365"] if zm else None, "m_mediana_365": zm["mediana_365"] if zm else None,
            "avance": round(av * 100), "funding7": None if f7 is None else round(f7 * 100, 4), "funding_ajuste": adj, "p_ciclo": None if prob is None else round(prob * 100), "m_zonas": [[q["nombre"], q["sube_365"], q["mediana_365"]] for q in md["zonas"]] if md else [],
            "temp": round(temp, 1), "zona": z["nombre"], "año": y, "fase": fs, "fng": fng, "regla": regla,
            "reglas": cic.get("reglas") or {}, "años": cic.get("años") or [], "ciclos": cic.get("ciclos") or [],
            "p_wma200": round(p["wma200"], 1), "p_dd_ath": round(p["dd_ath"], 1), "p_ret365": round(p["ret365"], 1),
            "wma200": round(wma, 1), "sobre_wma": round((price / wma - 1) * 100, 1), "caida_ath": round(med["dd_ath"] * 100, 1),
            "ath": round(ath, 1), "ret_anual": round((price / closes_d[-365] - 1) * 100, 1),
            "sube_180": z["sube_180"], "mediana_180": z["mediana_180"], "sube_365": z["sube_365"], "mediana_365": z["mediana_365"],
            "zonas": [[x["desde"], x["hasta"], x["nombre"], x["sube_365"], x["mediana_365"]] for x in T["zonas"]]}
