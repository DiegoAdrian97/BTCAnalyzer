"""¿El puntaje de direccion del analisis central acierta? ¿Que peso merece cada senal? (medir antes de sumar)

Con velas de 1 hora de BTC 2021-2026, cada 4 horas se calcula lo que la app usa para la direccion y sale de las velas
(los indicadores de calificar: el resumen de medias y osciladores, SuperTrend, Ichimoku, VWAP, OBV, Chaikin, SAR,
Bollinger fuera de banda; las divergencias recientes) y se mira si la proxima hora y las proximas 4 subieron.
- Cada senal sola: % de acierto cuando aparece (lo honesto es ~50%).
- El puntaje con los pesos de hoy: % de acierto cuando marca direccion (|puntaje| >= 2,5).
- Pesos aprendidos (regresion logistica con 2021-2024) probados en 2025-2026: error contra la tasa base.
Uso: python medir_direccion.py velas_1h.json
"""
import json, math, sys
import numpy as np
import indicadores as ind

NOMBRES = ["resumen", "SuperTrend (10,3)", "Nube de Ichimoku", "VWAP del dia", "OBV", "Chaikin Money Flow 20", "Parabolic SAR", "Bollinger fuera", "divergencia"]
PESOS_HOY = [2, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 1]


def senales(win):
    rows, resumen = ind.calificar(win)[:2]
    d = {r["indicador"]: r for r in rows}
    x = [0.0] * len(NOMBRES)
    r_ = resumen["rating"]
    x[0] = 1.0 if r_ > 0.1 else -1.0 if r_ < -0.1 else 0.0
    for k, nombre in enumerate(NOMBRES[1:7], 1):
        s = d.get(nombre, {}).get("senal")
        x[k] = 1.0 if s == "compra" else -1.0 if s == "venta" else 0.0
    bb = d.get("Bandas de Bollinger %B", {}).get("valor")
    if bb is not None:
        x[7] = -1.0 if bb >= 100 else 1.0 if bb <= 0 else 0.0
    t_fin = win[-1][0]
    for dv in ind.divergencias(win):
        if t_fin - dv["ti2"] <= 6 * 3_600_000 and dv["tipo"] in ("alcista", "bajista"):
            x[8] = 1.0 if dv["tipo"] == "alcista" else -1.0
    return x


def main():
    B = json.load(open(sys.argv[1]))
    c = np.asarray([b[4] for b in B]); t = np.asarray([b[0] for b in B])
    X, T, I = [], [], []
    for i in range(2500, len(B) - 5, 4):
        X.append(senales(B[i - 1999:i + 1])); T.append(B[i][0]); I.append(i)
    X = np.asarray(X); T = np.asarray(T); I = np.asarray(I)
    print(f"{len(X)} momentos", flush=True)
    corte = 1735689600000  # 2025-01-01
    for h in (1, 4):
        y = (c[I + h] > c[I]).astype(float)
        print(f"\n=== proximas {h} h (sube en {100 * y.mean():.1f}% de los casos) ===")
        for nom, s in (("2021-24", T < corte), ("2025-26", T >= corte)):
            print(f"  {nom}:")
            for k, n in enumerate(NOMBRES):
                a = s & (X[:, k] != 0)
                if a.sum() < 50:
                    continue
                ok = ((X[a, k] > 0) == (y[a] == 1)).mean()
                z = (ok - 0.5) / math.sqrt(0.25 / a.sum())
                print(f"    {n:<24} {a.sum():>6} veces · acierta {100 * ok:.1f}%  (z {z:+.1f})")
            sc = X @ np.asarray(PESOS_HOY)
            a = s & (np.abs(sc) >= 2.5)
            ok = ((sc[a] > 0) == (y[a] == 1)).mean()
            print(f"    PUNTAJE con los pesos de hoy (|p| >= 2,5): {a.sum()} veces · acierta {100 * ok:.1f}%  (z {(ok - 0.5) / math.sqrt(0.25 / max(1, a.sum())):+.1f})")
        # pesos aprendidos con 2021-24, probados en 2025-26
        tr, te = T < corte, T >= corte
        w = np.zeros(X.shape[1]); b0 = 0.0
        for _ in range(3000):
            p = 1 / (1 + np.exp(-(X[tr] @ w + b0)))
            g = p - y[tr]
            w -= 0.5 * (X[tr].T @ g / tr.sum() + 0.01 * w); b0 -= 0.5 * g.mean()
        p = 1 / (1 + np.exp(-(X[te] @ w + b0)))
        base = y[tr].mean()
        bs, bb = np.mean((p - y[te]) ** 2), np.mean((base - y[te]) ** 2)
        print(f"  pesos aprendidos 2021-24: " + ", ".join(f"{n} {v:+.3f}" for n, v in zip(NOMBRES, w)))
        print(f"  probados en 2025-26: {100 * (1 - bs / bb):+.2f}% menos error que la tasa base · acierta {100 * ((p > 0.5) == (y[te] == 1)).mean():.1f}%")


if __name__ == "__main__":
    main()
