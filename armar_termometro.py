"""Arma JavascriptVersion/termometro.json: lo que necesita el termometro de compra/venta (ciclo de BTC).

    python armar_termometro.py btc_diario.json        (velas diarias [t, o, h, l, c, v] desde 2011, p. ej. Bitstamp)

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


def main():
    B = json.load(open(sys.argv[1])); t = np.array([b[0] for b in B], float); c = np.array([b[4] for b in B], float)
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
    out = {"hasta": int(t[-1]), "zonas_desde": desde, "ath": float(c.max()), "componentes": list(COMP), "zonas": zonas,
           "q": {k: [round(float(x), 6) for x in np.quantile(np.array(hist[k]), np.linspace(0, 1, 201))] for k in COMP}}
    json.dump(out, open("JavascriptVersion/termometro.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(json.dumps(zonas, ensure_ascii=False, indent=1)); print("hoy:", round(float(T[-1]), 1))


if __name__ == "__main__":
    main()
