"""Arma JavascriptVersion/termometro.json: lo que necesita el termometro de compra/venta (ciclo de BTC).

    python armar_termometro.py btc_diario.json [fng.json]   (velas diarias desde 2011, p. ej. Bitstamp; historial del
                                                             Fear & Greed Index de api.alternative.me/fng/?limit=0)

Medido con BTC 2015-2026 (ver README): lo que mejor marco las buenas zonas de compra a 6-12 meses fue que tan lejos
esta el precio de su media de 200 semanas, cuanto cayo desde el maximo historico y cuanto subio o bajo en el ultimo
año (los tres comparados con toda la historia). El volumen, los indicadores de corto plazo, el indice de miedo y
codicia, la fase del halving y las noticias no lo anticiparon de forma pareja entre ciclos: quedan como contexto.
Herramienta aparte (no corre en Render ni en Vercel): necesita numpy.
"""
import bisect, json, sys
import numpy as np

COMP = ("wma200", "dd_ath", "ret365")
ZONAS = [(0, 20, "Compra fuerte"), (20, 40, "Buena zona de compra"), (40, 60, "Neutral"), (60, 80, "Caro: cuidado"), (80, 101, "Zona de venta")]


def metricas(c):
    """Las tres medidas para cada dia (np.nan si falta historia)."""
    n = len(c); cs = np.r_[0, np.cumsum(c)]
    wma = np.array([(cs[i + 1] - cs[i + 1 - 1400]) / 1400 if i >= 1399 else np.nan for i in range(n)])
    return {"wma200": np.log(c / wma), "dd_ath": c / np.maximum.accumulate(c) - 1,
            "ret365": np.r_[np.full(365, np.nan), np.log(c[365:] / c[:-365])]}


def temperatura(pcts):
    return float(np.mean(pcts))


# Medidor final de compra/venta: mitad "logica inversa" (cuanto mas barato esta BTC frente a su historia, mas compra:
# 1 - temperatura) y mitad momento del ciclo de 4 años (un modelo logistico con el año del ciclo y que tan avanzado va
# el año bajista y el 3er alcista: al final del bajista suele estar el piso; al final del 3er alcista, el techo).
# Probado año por año 2019-2026, entrenando el ciclo solo con lo anterior: separa mucho mejor que cada parte sola
# (AUC 0,96 contra 0,74 la temperatura y 0,80 el ciclo). Cualquier mezcla entre 30% y 70% da mas de 0,93.
PESO_VALUACION = 0.5
ZONAS_S = [(0.75, 9.0, "Compra fuerte"), (0.60, 0.75, "Buen momento de compra"), (0.45, 0.60, "Cuidado: caro"), (-9.0, 0.45, "Zona de venta")]


def X_ciclo(años, avance):
    """Señales del ciclo: año del ciclo (alcista 1, 2, 3; el bajista es la base) y avance del año (0 a 1) en el
    bajista y en el 3er alcista."""
    ph = (np.asarray(años) - 2) % 4; av = np.asarray(avance, float)
    return np.column_stack([(ph == k).astype(float) for k in (1, 2, 3)] + [(ph == 0) * av, (ph == 3) * av])


def avance_año(ms):
    """Que parte del año (UTC) paso: 0 el 1 de enero, casi 1 el 31 de diciembre."""
    import datetime as dt
    d = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
    return (d.timetuple().tm_yday - 1) / 366


def fase(y):
    """Ciclo de 4 años de BTC: 2014, 2018, 2022, 2026... bajistas; los tres de en medio, alcistas 1, 2 y 3."""
    return "bajista" if y % 4 == 2 else f"alcista {(y - 3) % 4 + 1}"


def ciclo(t, c, fng):
    """Lo que paso en cada fase del ciclo y con el Fear & Greed Index extremo segun la fase (12 meses despues)."""
    import datetime as dt
    yr = np.array([dt.datetime.fromtimestamp(x / 1000, dt.timezone.utc).year for x in t])
    años = [[int(y), fase(int(y)), round(float(c[yr == y][-1] / c[yr == y][0] - 1) * 100)] for y in range(2012, int(yr[-1])) if (yr == y).sum() > 300]
    # maximos y pisos de cada ciclo (el maximo, en el año anterior al bajista; el piso, lo mas bajo en los 20 meses siguientes)
    ciclos, piso_ant = [], None
    for y in range(2014, int(yr[-1]) + 1, 4):
        m = yr == y - 1
        if not m.any():
            continue
        i = int(np.where(m)[0][np.argmax(c[m])]); j = i + int(np.argmin(c[i:i + 600]))
        mes = lambda a, b: round(float(b - a) / 86400000 / 30.44, 1)
        ciclos.append({"pico_t": int(t[i]), "pico": round(float(c[i])), "piso_t": int(t[j]), "piso": round(float(c[j])),
                       "caida": round(float(c[j] / c[i] - 1) * 100), "meses_bajista": mes(t[i], t[j]),
                       "meses_alcista_antes": mes(piso_ant, t[i]) if piso_ant else None, "confirmado": bool(t[-1] - t[j] > 365 * 86400000)})
        piso_ant = t[j]
    out = {"años": años, "ciclos": ciclos, "reglas": {}}
    if fng is None:
        return out
    for clave, m in (("miedo_bajista", (fng < 25) & (yr % 4 == 2)), ("codicia_alcista3", (fng > 75) & (yr % 4 == 1)),
                     ("codicia_alcista12", (fng > 75) & np.isin(yr % 4, (3, 0)))):
        r = {}
        for hz in (90, 365):
            fut = np.r_[c[hz:] / c[:-hz] - 1, np.full(hz, np.nan)]; k = m & np.isfinite(fut)
            r[f"sube_{hz}"] = round(float(np.mean(fut[k] > 0)) * 100) if k.sum() >= 30 else None
            r[f"mediana_{hz}"] = round(float(np.median(fut[k])) * 100) if k.sum() >= 30 else None
        k = np.where(m)[0]
        dd = [np.min(c[i:i + 365]) / c[i] - 1 for i in k if i + 365 <= len(c)]
        r["caida_mediana"] = round(float(np.median(dd)) * 100) if len(dd) >= 30 else None
        r["dias"] = int(m.sum()); r["años"] = sorted({int(y) for y in yr[m]})
        out["reglas"][clave] = r
    return out


def main():
    B = json.load(open(sys.argv[1])); t = np.array([b[0] for b in B], float); c = np.array([b[4] for b in B], float)
    fng = None
    if len(sys.argv) > 2:
        fv = {int(d["timestamp"]) * 1000: int(d["value"]) for d in json.load(open(sys.argv[2]))["data"]}
        fng = np.array([fv.get(int(x), np.nan) for x in t])
    M = metricas(c)
    # temperatura de cada dia con la historia que habia hasta ese dia (sin mirar el futuro), para medir las zonas
    hist = {k: [] for k in COMP}; T = np.full(len(c), np.nan)
    for i in range(len(c)):
        p = []
        for k in COMP:
            v = M[k][i]
            if np.isfinite(v):
                if len(hist[k]) >= 365: p.append(bisect.bisect_left(hist[k], v) / len(hist[k]) * 100)
                bisect.insort(hist[k], v)
        if len(p) == len(COMP): T[i] = temperatura(p)
    # medidor: mitad valuacion (1 - temperatura) y mitad ciclo; zonas medidas año por año desde 2019 sin mirar el futuro
    from sklearn.linear_model import LogisticRegression
    import datetime as dt
    años = np.array([dt.datetime.fromtimestamp(x / 1000, dt.timezone.utc).year for x in t])
    fut365 = np.r_[c[365:] / c[:-365] - 1, np.full(365, np.nan)]; fut180 = np.r_[c[180:] / c[:-180] - 1, np.full(180, np.nan)]
    Xc = X_ciclo(años, [avance_año(x) for x in t]); okc = t >= 1325376000000          # ciclo desde 2012
    Pc = np.full(len(c), np.nan)
    for Y in range(2019, int(años[-1]) + 1):
        a = dt.datetime(Y, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000
        tr = okc & np.isfinite(fut365) & (t + 365 * 86400000 < a); te = okc & (años == Y)
        if tr.sum() > 300 and te.any():
            Pc[te] = LogisticRegression(max_iter=4000).fit(Xc[tr], fut365[tr] > 0).predict_proba(Xc[te])[:, 1]
    S = PESO_VALUACION * (1 - T / 100) + (1 - PESO_VALUACION) * Pc
    zonas_s = []
    for lo, hi, nom in ZONAS_S:
        z = {"desde": lo, "hasta": hi, "nombre": nom}
        for hz, fut in ((180, fut180), (365, fut365)):
            m = np.isfinite(S) & (S >= lo) & (S < hi) & np.isfinite(fut)
            z[f"sube_{hz}"] = round(float(np.mean(fut[m] > 0)) * 100) if m.sum() >= 30 else None
            z[f"mediana_{hz}"] = round(float(np.median(fut[m])) * 100) if m.sum() >= 30 else None
            z[f"dias_{hz}"] = int(m.sum())
        zonas_s.append(z)
    trf = okc & np.isfinite(fut365)
    fin = LogisticRegression(max_iter=4000).fit(Xc[trf], fut365[trf] > 0)
    modelo = {"intercepto": round(float(fin.intercept_[0]), 6), "pesos": [round(float(w), 6) for w in fin.coef_[0]],
              "peso_valuacion": PESO_VALUACION, "zonas": zonas_s}
    # las zonas se miden desde 2019: antes la media de 200 semanas tenia menos de un ciclo de historia para comparar
    # (en 2016-17 casi todo salia "caro" en plena suba)
    desde = 1546300800000
    zonas = []
    for lo, hi, nom in ZONAS:
        z = {"desde": lo, "hasta": min(hi, 100), "nombre": nom}
        for hz in (180, 365):
            fut = np.r_[c[hz:] / c[:-hz] - 1, np.full(hz, np.nan)]
            m = (T >= lo) & (T < hi) & np.isfinite(fut) & (t >= desde)
            z[f"sube_{hz}"] = round(float(np.mean(fut[m] > 0)) * 100) if m.sum() >= 30 else None
            z[f"mediana_{hz}"] = round(float(np.median(fut[m])) * 100) if m.sum() >= 30 else None
            z[f"dias_{hz}"] = int(m.sum())
        zonas.append(z)
    out = {"medidor": modelo, "ciclo": ciclo(t, c, fng), "hasta": int(t[-1]), "zonas_desde": desde, "ath": float(c.max()), "componentes": list(COMP), "zonas": zonas,
           "q": {k: [round(float(x), 6) for x in np.quantile(np.array(hist[k]), np.linspace(0, 1, 201))] for k in COMP}}
    json.dump(out, open("JavascriptVersion/termometro.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(json.dumps(zonas_s, ensure_ascii=False, indent=1)); print("hoy: temperatura", round(float(T[-1]), 1), "ciclo", modelo["intercepto"], modelo["pesos"])


if __name__ == "__main__":
    main()
