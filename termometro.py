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


def termometro(closes_d, price, T=None):
    """Fila del termometro. closes_d: cierres diarios (al menos 1400). None si falta historia."""
    T = T or _datos()
    if len(closes_d) < 1400 or price <= 0:
        return None
    wma = sum(closes_d[-1400:]) / 1400
    ath = max(T["ath"], max(closes_d), price)
    med = {"wma200": math.log(price / wma), "dd_ath": price / ath - 1, "ret365": math.log(price / closes_d[-365])}
    p = {k: percentil(med[k], T["q"][k]) for k in T["componentes"]}
    temp = sum(p.values()) / len(p)
    z = next(z for z in T["zonas"] if temp < z["hasta"] or z["hasta"] >= 100)
    return {"tabla": "termometro", "temp": round(temp, 1), "zona": z["nombre"],
            "p_wma200": round(p["wma200"], 1), "p_dd_ath": round(p["dd_ath"], 1), "p_ret365": round(p["ret365"], 1),
            "wma200": round(wma, 1), "sobre_wma": round((price / wma - 1) * 100, 1), "caida_ath": round(med["dd_ath"] * 100, 1),
            "ath": round(ath, 1), "ret_anual": round((price / closes_d[-365] - 1) * 100, 1),
            "sube_180": z["sube_180"], "mediana_180": z["mediana_180"], "sube_365": z["sube_365"], "mediana_365": z["mediana_365"],
            "zonas": [[x["desde"], x["hasta"], x["nombre"], x["sube_365"], x["mediana_365"]] for x in T["zonas"]]}
