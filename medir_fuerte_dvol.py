"""¿Sumar la volatilidad implicita (DVOL) al modelo de movimiento fuerte lo mejora? (medir antes de sumar)

El modelo de entrenar_fuerte.py con y sin 3 senales del DVOL (percentil de 30 dias, contra su promedio de 30 dias y
cambio de 24 h), con la misma prueba honesta (cada trimestre desde 2023 con un modelo entrenado solo con lo anterior).
Entra si mejora en 2023-24, 2025 y 2026 (z por dia > 2).
Uso: python medir_fuerte_dvol.py velas_1h.json eventos.json [carpeta de cache]
"""
import bisect, json, os, sys
import numpy as np
import entrenar_fuerte as ef
import medir_compresion as mcomp
import medir_contexto as mc

H = 3_600_000


def dvol_senales(t, dv):
    tdv = [x[0] for x in dv]; vdv = [x[1] for x in dv]
    out = np.full((len(t), 3), np.nan)
    for i, ti in enumerate(t):
        k = bisect.bisect_right(tdv, ti + H) - 1          # lo que se sabia al cerrar la vela
        if k >= 720 and ti + H - tdv[k] <= 3 * H:
            w = vdv[k - 719:k + 1]
            out[i] = [sum(1 for x in w if x < vdv[k]) / 720, np.log(vdv[k] / np.mean(w)), np.log(vdv[k] / vdv[k - 24])]
    return out


def main():
    B = json.load(open(sys.argv[1])); evs = json.load(open(sys.argv[2]))
    mc.CACHE = sys.argv[3] if len(sys.argv) > 3 else "datos_medicion"; os.makedirs(mc.CACHE, exist_ok=True)
    t, lc, X = ef.señales(B, evs)
    XD = np.column_stack([X, dvol_senales(t, mc.dvol())])
    for hz in (1, 4):
        y, ok = ef.objetivo(lc, hz)
        P0, b0, g0 = mcomp.honesto(t, X, y, ok, hz)
        P1, b1, g1 = mcomp.honesto(t, XD, y, ok, hz)
        for nombre, a, b in mcomp.TRAMOS:
            s = g0 & g1 & (t >= a) & (t < b) & np.isfinite(P0) & np.isfinite(P1)
            e0, e1, eb = (P0[s] - y[s]) ** 2, (P1[s] - y[s]) ** 2, (b0[s] - y[s]) ** 2
            dia = (t[s] // (24 * H)).astype(int)
            d = np.bincount(dia - dia.min(), weights=e0 - e1)[np.unique(dia - dia.min())]
            z = d.mean() / (d.std(ddof=1) / len(d) ** 0.5)
            print(f"  {hz} h {nombre}: actual {100 * (1 - e0.sum() / eb.sum()):.2f}% · con DVOL {100 * (1 - e1.sum() / eb.sum()):.2f}%  z {z:+.1f}  ({s.sum()} horas)", flush=True)


if __name__ == "__main__":
    main()
