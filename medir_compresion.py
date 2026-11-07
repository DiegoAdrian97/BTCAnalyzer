"""¿La compresion de las Bollinger anticipa un movimiento fuerte? (medir antes de sumar)

1) Directo: cuando el ancho de las Bollinger (20, 2) esta entre el 10% mas angosto de las ultimas 720 horas, ¿cuantas
   veces la proxima hora, las proximas 4 y las proximas 24 se movio mas del doble de lo habitual? (contra cualquier hora)
2) En el modelo de movimiento fuerte: los mismos arboles con y sin 3 senales de compresion (ancho de hoy contra su
   promedio de 7 y 30 dias, y su percentil en 30 dias), con la prueba honesta de entrenar_fuerte.py (cada trimestre desde
   2023 con un modelo entrenado solo con lo anterior). Entra si mejora en 2023-24, 2025 y 2026 (z por dia > 2).

Uso: python medir_compresion.py velas_1h.json eventos.json   (los arma datos_entrenamiento.py)
"""
import datetime as dt, json, sys
import numpy as np
import lightgbm as lgb

import entrenar_fuerte as ef

H = 3600000


def compresion(B):
    c = np.asarray([b[4] for b in B], dtype=float)
    mu = ef.roll(c, 20, np.mean); sd = ef.roll(c, 20, np.std)
    ancho = np.log(4 * sd / mu)
    s7, s30 = ef.roll(ancho, 168, np.mean), ef.roll(ancho, 720, np.mean)
    # percentil del ancho de hoy entre las ultimas 720 horas (0 = el mas angosto)
    pct = np.full(len(c), np.nan)
    for i in range(740, len(c)):
        w = ancho[i - 719:i + 1]
        pct[i] = (w < ancho[i]).mean()
    return np.column_stack([ancho - s7, ancho - s30, pct]), pct


def q(y, m):
    return dt.datetime(y, m, 1, tzinfo=dt.timezone.utc).timestamp() * 1000


TRAMOS = (("2023-24", q(2023, 1), q(2025, 1)), ("2025", q(2025, 1), q(2026, 1)), ("2026", q(2026, 1), 1e18))


def honesto(t, X, y, ok, hz):
    starts = [q(y_, m) for y_ in range(2023, 2027) for m in (1, 4, 7, 10)] + [1e18]
    P = np.full(len(t), np.nan); base = np.full(len(t), np.nan)
    good = ok & np.isfinite(X).all(axis=1)
    for a, b in zip(starts, starts[1:]):
        tr = good & (t + (hz + 1) * H <= a); te = good & (t >= a) & (t < b)
        if not te.any():
            continue
        g = lgb.LGBMClassifier(**ef.PARAMS).fit(X[tr], y[tr])
        P[te] = g.predict_proba(X[te])[:, 1]; base[te] = y[tr].mean()
    return P, base, good


def main():
    B = json.load(open(sys.argv[1])); evs = json.load(open(sys.argv[2]))
    t, lc, X = ef.señales(B, evs)
    C, pct = compresion(B)
    res = {"directo": [], "modelo": []}
    print("1) DIRECTO: Bollinger entre el 10% mas angosto de 30 dias -> ¿movimiento fuerte despues?")
    for hz in (1, 4, 24):
        y, ok = ef.objetivo(lc, hz)
        for nombre, a, b in (("2021-22", q(2021, 1), q(2023, 1)),) + TRAMOS:
            s = ok & np.isfinite(pct) & (t >= a) & (t < b)
            ang = s & (pct <= 0.10); anc = s & (pct >= 0.90)
            fila = (hz, nombre, int(s.sum()), round(100 * y[s].mean(), 1), round(100 * y[ang].mean(), 1), round(100 * y[anc].mean(), 1))
            res["directo"].append(fila)
            print(f"  {hz:>2} h {nombre}: cualquier hora {fila[3]}% · comprimida {fila[4]}% · muy ancha {fila[5]}%  ({fila[2]} horas)")
    print("\n1b) ¿EXPANDE? rango de las proximas N horas contra el de las ultimas N (mediana), y si se mueve mas del doble de su propio ritmo reciente")
    h_ = np.asarray([x[2] for x in B], dtype=float); l_ = np.asarray([x[3] for x in B], dtype=float); n = len(h_)
    for N in (24, 72):
        hi_f = np.full(n, np.nan); lo_f = np.full(n, np.nan)
        hi_f[:-N] = ef.roll(h_, N, np.max)[N:]; lo_f[:-N] = ef.roll(l_, N, np.min)[N:]
        r_f = np.log(hi_f / lo_f); r_p = np.log(ef.roll(h_, N, np.max) / ef.roll(l_, N, np.min))
        ex = r_f / r_p
        for nombre, a_, b_ in (("2021-22", q(2021, 1), q(2023, 1)),) + TRAMOS:
            s = np.isfinite(ex) & np.isfinite(pct) & (t >= a_) & (t < b_)
            ang = s & (pct <= 0.10)
            fila = (N, nombre, round(float(np.median(ex[s])), 2), round(float(np.median(ex[ang])), 2),
                    round(100 * float((ex[s] > 2).mean()), 1), round(100 * float((ex[ang] > 2).mean()), 1))
            res.setdefault("expande", []).append(fila)
            print(f"  {N} h {nombre}: rango siguiente / anterior, mediana: cualquier hora x{fila[2]} · comprimida x{fila[3]} · "
                  f"mas del doble: {fila[4]}% / {fila[5]}%")
    print("\n2) EN EL MODELO DE MOVIMIENTO FUERTE (prueba honesta, % menos error que la tasa base)")
    XC = np.column_stack([X, C])
    for hz in (1, 4):
        y, ok = ef.objetivo(lc, hz)
        P0, b0, g0 = honesto(t, X, y, ok, hz)
        P1, b1, g1 = honesto(t, XC, y, ok, hz)
        for nombre, a, b in TRAMOS:
            s = g0 & g1 & (t >= a) & (t < b) & np.isfinite(P0) & np.isfinite(P1)
            e0, e1, eb = (P0[s] - y[s]) ** 2, (P1[s] - y[s]) ** 2, (b0[s] - y[s]) ** 2
            dia = (t[s] // (24 * H)).astype(int)
            d = np.bincount(dia - dia.min(), weights=e0 - e1)[np.unique(dia - dia.min())]
            z = d.mean() / (d.std(ddof=1) / len(d) ** 0.5)
            fila = (hz, nombre, round(100 * (1 - e0.sum() / eb.sum()), 2), round(100 * (1 - e1.sum() / eb.sum()), 2), round(float(z), 1))
            res["modelo"].append(fila)
            print(f"  {hz} h {nombre}: actual {fila[2]}% · con compresion {fila[3]}%  z {fila[4]:+}")
    json.dump(res, open("resultado_compresion.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
