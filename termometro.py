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


def _interp(x, xs, ys):
    """como numpy.interp, con 0 a la izquierda y 1 a la derecha (probabilidad acumulada)"""
    if x <= xs[0]:
        return 0.0
    if x >= xs[-1]:
        return 1.0
    for i in range(1, len(xs)):
        if x <= xs[i]:
            lo, hi = xs[i - 1], xs[i]
            return ys[i - 1] if hi == lo else ys[i - 1] + (ys[i] - ys[i - 1]) * (x - lo) / (hi - lo)
    return 1.0


def piso_prob(P, moneda, x, vol):
    """Probabilidad de que el minimo de los proximos 180 dias quede por debajo de exp(x) veces el precio de hoy."""
    own = P["own"].get(moneda)
    pz = _interp(x / vol, P["z"], P["grid"])
    return pz if own is None else 0.5 * pz + 0.5 * _interp(x, own, P["grid"])


def _dec(v):
    return 0 if v >= 1000 else 2 if v >= 10 else 4


def piso(moneda, closes_d, price, T=None, now_ms=None):
    """Minimo probable en los proximos 6 meses (armar_termometro.piso_modelo): 'no baja de' cada precio con 50, 80, 90
    y 95% de confianza. closes_d: cierres diarios ya cerrados (hacen falta 366). None si no hay modelo o datos."""
    T = T or _datos()
    P = T.get("piso")
    if not P or price <= 0 or len(closes_d) < 366:
        return None
    lr = [math.log(closes_d[i] / closes_d[i - 1]) for i in range(len(closes_d) - 365, len(closes_d))]
    med = sum(lr) / 365
    vol = math.sqrt(sum((v - med) ** 2 for v in lr) / 365) * math.sqrt(P["dias"])
    if vol <= 0:
        return None
    niveles = []
    for conf in (50, 80, 90, 95):
        lo, hi = -6.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if piso_prob(P, moneda, mid, vol) < 1 - conf / 100:
                lo = mid
            else:
                hi = mid
        v = price * math.exp((lo + hi) / 2)
        niveles.append([conf, round(v, _dec(v))])
    # años anteriores desde esta misma fecha (bajistas y alcistas): cuanto cayo en los 180 dias siguientes
    import time
    from datetime import datetime, timezone
    d = datetime.fromtimestamp((now_ms or time.time() * 1000) / 1000, tz=timezone.utc)
    doy = d.timetuple().tm_yday
    def anteriores_de(m):
        out = []
        for y, fila in sorted((P.get("analogos") or {}).get(m, {}).items()):
            mejor = min(fila, key=lambda e: abs(e[0] - doy))
            if abs(mejor[0] - doy) <= 4:
                out.append([int(y), fase(int(y)), mejor[1]])
        return out
    todas = {m: anteriores_de(m) for m in sorted(P.get("analogos") or {})}
    anteriores = todas.get(moneda, [])
    return {"tabla": "piso", "moneda": moneda, "dias": P["dias"], "precio": price, "vol": round(vol * 100, 1), "niveles": niveles,
            "anteriores": anteriores,
            "modelo": {"grid": P["grid"], "z": P["z"], "own": P["own"], "vol": {**P["vol"], moneda: round(vol, 6)}, "anteriores": todas}}


def termometro_alt(moneda, velas_d, price, T=None, now_ms=None):
    """Medidor de XRP o SOL: su propio barato o caro (con su historia, armar_termometro.py) y el ciclo de BTC.
    velas_d: velas diarias cerradas [t, o, h, l, c, v]. None si no hay datos para esa moneda."""
    import time
    T = T or _datos()
    A, md = (T.get("alts") or {}).get(moneda), T.get("medidor")
    if not A or not md or price <= 0:
        return None
    now_ms = now_ms or time.time() * 1000
    hoy = int(now_ms // 86400000)
    dias = {int(d): c for d, c in A["cierres"]}
    for b in velas_d:
        dias[int(b[0] // 86400000)] = b[4]
    closes = [dias[d] for d in sorted(dias) if d < hoy]
    comps = A["componentes"]
    if len(closes) < (1400 if "wma200" in comps else 365):
        return None
    wma = sum(closes[-1400:]) / 1400 if "wma200" in comps else None
    ath = max(A["ath"], max(closes), price)
    med = {"dd_ath": price / ath - 1, "ret365": math.log(price / closes[-365])}
    if wma:
        med["wma200"] = math.log(price / wma)
    p = {k: percentil(med[k], A["q"][k]) for k in comps}
    temp = sum(p.values()) / len(p)
    y = time.gmtime(now_ms / 1000).tm_year
    av = (time.gmtime(now_ms / 1000).tm_yday - 1) / 366
    ph = (y - 2) % 4
    x = [float(ph == 1), float(ph == 2), float(ph == 3), (ph == 0) * av, (ph == 3) * av]
    prob = 1 / (1 + math.exp(-(md["intercepto"] + sum(w * v for w, v in zip(md["pesos"], x)))))
    S = md["peso_valuacion"] * (1 - temp / 100) + (1 - md["peso_valuacion"]) * prob
    zm = next(q for q in A["zonas"] if q["desde"] <= S < q["hasta"])
    z = next(z for z in T["zonas"] if temp < z["hasta"] or z["hasta"] >= 100)
    return {"tabla": "termometro", "moneda": moneda, "medidor": round(min(100.0, max(0.0, (1 - S) * 100)), 1),
            "medidor_zona": zm["nombre"], "m_sube_180": zm["sube_180"], "m_mediana_180": zm["mediana_180"],
            "m_sube_365": zm["sube_365"], "m_mediana_365": zm["mediana_365"], "avance": round(av * 100),
            "funding7": None, "funding_ajuste": 0, "p_ciclo": round(prob * 100),
            "m_zonas": [[q["nombre"], q["sube_365"], q["mediana_365"]] for q in A["zonas"]],
            "temp": round(temp, 1), "zona": z["nombre"], "año": y, "fase": fase(y), "fng": None, "regla": None,
            "reglas": {}, "años": [], "ciclos": [], "p_wma200": round(p["wma200"], 1) if wma else None,
            "p_dd_ath": round(p["dd_ath"], 1), "p_ret365": round(p["ret365"], 1), "wma200": round(wma, 4) if wma else None,
            "sobre_wma": round((price / wma - 1) * 100, 1) if wma else None, "caida_ath": round(med["dd_ath"] * 100, 1),
            "ath": round(ath, 4), "ret_anual": round((price / closes[-365] - 1) * 100, 1)}


def onchain_hoy(T, price, now_ms=None):
    """MVRV y Puell de hoy, estimados con lo ultimo de CoinMetrics (armar_termometro.py): el precio realizado (costo
    promedio de todos los BTC) sigue su tendencia del ultimo mes y los mineros cobran los BTC de cada dia al precio
    de ahora. {} si el termometro no trae datos on-chain."""
    import time
    o = T.get("onchain")
    if not o or price <= 0:
        return {}
    hoy = int((now_ms or time.time() * 1000) // 86400000)
    rp = o["rp"] + o["rp_pend"] * max(0, min(45, hoy - o["dia"]))
    iss = o["btc_dia"] * price
    return {"mvrv": price / rp, "puell": iss / ((o["iss_suma364"] + iss) / 365), "precio_realizado": rp}


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
    oc = onchain_hoy(T, price, now_ms)
    med.update({k: math.log(v) for k, v in oc.items() if k in ("mvrv", "puell")})
    p = {k: percentil(med[k], T["q"][k]) for k in T["componentes"] if k in med}
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
            "p_mvrv": round(p["mvrv"], 1) if "mvrv" in p else None, "p_puell": round(p["puell"], 1) if "puell" in p else None,
            "mvrv": round(oc["mvrv"], 3) if oc else None, "puell": round(oc["puell"], 3) if oc else None,
            "precio_realizado": round(oc["precio_realizado"], 1) if oc else None,
            "wma200": round(wma, 1), "sobre_wma": round((price / wma - 1) * 100, 1), "caida_ath": round(med["dd_ath"] * 100, 1),
            "ath": round(ath, 1), "ret_anual": round((price / closes_d[-365] - 1) * 100, 1),
            "sube_180": z["sube_180"], "mediana_180": z["mediana_180"], "sube_365": z["sube_365"], "mediana_365": z["mediana_365"],
            "zonas": [[x["desde"], x["hasta"], x["nombre"], x["sube_365"], x["mediana_365"]] for x in T["zonas"]]}
