"""¿La volatilidad implicita de las opciones (DVOL, Deribit) anticipa cuanto se va a mover BTC? (medir antes de sumar)

Con el DVOL de cada hora en su percentil de los ultimos 30 dias: cuando esta alto (80% o mas) o bajo (20% o menos),
¿cuantas veces las proximas 4 y 24 horas se movieron mas del doble de lo habitual? (contra cualquier hora)
Uso: python medir_dvol.py velas_1h.json [carpeta de cache]
"""
import bisect, json, sys
import numpy as np
import entrenar_fuerte as ef
import medir_contexto as mc


def main():
    B = json.load(open(sys.argv[1])); mc.CACHE = sys.argv[2] if len(sys.argv) > 2 else "datos_medicion"
    import os; os.makedirs(mc.CACHE, exist_ok=True)
    dv = mc.dvol()                               # [ms de cierre de la hora, DVOL]
    tdv = [x[0] for x in dv]; vdv = [x[1] for x in dv]
    t = np.asarray([b[0] for b in B], dtype=float); lc = np.log([b[4] for b in B])
    pct = np.full(len(B), np.nan)
    for i, b in enumerate(B):
        k = bisect.bisect_right(tdv, b[0] + 3_600_000) - 1
        if k >= 720:
            w = vdv[k - 719:k + 1]
            pct[i] = sum(1 for x in w if x < vdv[k]) / 720
    for hz in (4, 24):
        y, ok = ef.objetivo(lc, hz)
        for nom, a, b in (("2022", 1640995200000, 1672531200000), ("2023-24", 1672531200000, 1735689600000), ("2025-26", 1735689600000, 1e18)):
            s = ok & np.isfinite(pct) & (t >= a) & (t < b)
            alto, bajo = s & (pct >= 0.8), s & (pct <= 0.2)
            print(f"{hz:>2} h {nom}: cualquier hora {100 * y[s].mean():.1f}% · DVOL alto {100 * y[alto].mean():.1f}% ({alto.sum()}) · DVOL bajo {100 * y[bajo].mean():.1f}% ({bajo.sum()})", flush=True)


if __name__ == "__main__":
    main()
