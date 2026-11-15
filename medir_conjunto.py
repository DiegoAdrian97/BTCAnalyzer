"""¿Como trabajan JUNTAS las señales que la app ya usa? (para ajustar pesos y umbrales con datos). Nov. 2026.

Las señales del analisis central que se pueden reconstruir con velas de 1 h y las metricas de Binance (2022-2026),
cada 2 horas, sin mirar el futuro, con el lado con el que la app las cuenta hoy:
  A. resumen de indicadores, al reves (corrige)        B. precio fuera de las bandas de Bollinger (vuelve adentro)
  C. RSI de 1 h en sobrecompra / sobreventa (revierte) D. open interest cae >= 1% en 4 h con el precio bajando (rebota)
  E. cuentas mas compradas que el 90% de 3 semanas (sigue subiendo)
  F. barrida de liquidez: la mecha pasa el extremo de 20 velas y cierra adentro (va para el otro lado)
(No entran los casos parecidos, patrones, flujo ni liquidaciones: no se reconstruyen barato.)

Preguntas, a 1, 4 y 24 horas, en 2022-24 y en 2025-26:
  1. Cada una sola: ¿sigue acertando?
  2. ¿Se repiten? A, B y C dicen lo mismo (el precio estirado corrige): cuando marcan 1, 2 o las 3 juntas, ¿acierta mas?
  3. Puntos netos (todas con peso 1): acierto y cuantas veces pasa con 1, 2, 3 o mas puntos netos. ¿Mas acuerdo = mas acierto?
  4. Pesos aprendidos (regresion logistica con 2022-24, probada en 2025-26) contra pesos iguales.
Uso: python medir_conjunto.py
"""
import bisect, math

import numpy as np

import indicadores as ind
import medir_nuevo as mn
from medir_senales import velas

H = 3600000
VENTANA = 500
NOMBRES = ["A resumen de indicadores (al revés)", "B fuera de Bollinger", "C RSI extremo", "D open interest cae con el precio",
           "E cuentas muy compradas", "F barrida de liquidez"]


def main():
    B = velas("1h")
    T = [b[0] for b in B]; Hh = [b[2] for b in B]; L = [b[3] for b in B]; C = [b[4] for b in B]
    n = len(C)
    M = mn.metricas()
    mh = {t: (oi, ls) for t, oi, ls, _ in M if t % H == 0}
    print(f"{n} velas de 1 h; {len(mh)} horas con métricas", flush=True)
    rsi = ind.rsi(C)
    ratios = []            # (t, ratio de cuentas) por hora
    filas, ult_ls = [], []
    for i in range(VENTANA, n - 25, 2):
        t = T[i] + H                                   # la hora que empieza al cerrar la vela i
        f = [0] * 6
        rows, res = ind.calificar(B[i - VENTANA + 1:i + 1])[:2]
        if abs(res["rating"]) > 0.1:
            f[0] = -1 if res["rating"] > 0 else 1
        bb = next((r for r in rows if r["indicador"] == "Bandas de Bollinger %B"), None)
        if bb and bb["valor"] is not None:
            f[1] = -1 if bb["valor"] >= 100 else 1 if bb["valor"] <= 0 else 0
        f[2] = -1 if rsi[i] >= 70 else 1 if rsi[i] <= 30 else 0
        a, b4 = mh.get(t), mh.get(t - 4 * H)
        if a and b4 and b4[0] > 0 and (a[0] / b4[0] - 1) * 100 <= -1 and C[i] < C[i - 4]:
            f[3] = 1
        if a:
            r = a[1] / max(1e-9, 1 - a[1])
            ult_ls.append(r)
            w = ult_ls[-250:]                           # ~3 semanas a una cada 2 horas
            if len(w) >= 200 and sum(1 for x in w if x <= r) / len(w) >= 0.9:
                f[4] = 1
        lo20, hi20 = min(L[i - 20:i]), max(Hh[i - 20:i])
        if L[i] < lo20 and C[i] > lo20:
            f[5] = 1
        elif Hh[i] > hi20 and C[i] < hi20:
            f[5] = -1
        filas.append((i, t, f))
        if len(filas) % 4000 == 0:
            print(f"  {len(filas)} momentos", flush=True)
    X = np.array([f for _, _, f in filas], float)
    I = np.array([i for i, _, _ in filas])
    tr = np.array([0 if T[i] < mn.CORTE else 1 for i in I])
    Cn = np.array(C)
    print(f"{len(filas)} momentos (cada 2 h): {int((tr == 0).sum())} hasta 2024 y {int((tr == 1).sum())} en 2025-26", flush=True)

    def z_de(ok, b, m):
        return (ok - b) / math.sqrt(max(1e-9, b * (1 - b) / max(1, m)))

    for hz in (1, 4, 24):
        sube = Cn[I + hz] > Cn[I]
        ne = max(1, hz // 2)                                    # los momentos se pisan cuando el horizonte pasa las 2 h
        print(f"\n================ a {hz} h ================")
        base = [sube[tr == k].mean() for k in (0, 1)]
        print(f"un momento cualquiera: sube {100 * base[0]:.1f}% (2022-24) y {100 * base[1]:.1f}% (2025-26)")
        print("1. cada señal sola")
        for j, nom in enumerate(NOMBRES):
            txt = f"  {nom:<40}"
            for k in (0, 1):
                m = (X[:, j] != 0) & (tr == k)
                if m.sum() < 30:
                    txt += f" | pocos ({int(m.sum())})"; continue
                ok = ((X[m, j] > 0) == sube[m]).mean()
                ps = (X[m, j] > 0).mean(); b = ps * base[k] + (1 - ps) * (1 - base[k])
                txt += f" | {int(m.sum()):>5} · acierta {100 * ok:4.1f}% (normal {100 * b:4.1f}%, z {z_de(ok, b, m.sum() / ne):+.1f})"
            print(txt, flush=True)
        print("2. A, B y C (el precio estirado corrige): cuántas marcan a la vez, del mismo lado")
        trio = X[:, :3]
        for cuantas in (1, 2, 3):
            txt = f"  {cuantas} de 3"
            for k in (0, 1):
                s = trio.sum(axis=1)
                m = (np.abs(s) == cuantas) & ((trio != 0).sum(axis=1) == cuantas) & (tr == k)
                if m.sum() < 30:
                    txt += f" | pocos ({int(m.sum())})"; continue
                ok = ((s[m] > 0) == sube[m]).mean(); ps = (s[m] > 0).mean(); b = ps * base[k] + (1 - ps) * (1 - base[k])
                txt += f" | {int(m.sum()):>5} · acierta {100 * ok:4.1f}% (normal {100 * b:4.1f}%, z {z_de(ok, b, m.sum() / ne):+.1f})"
            print(txt, flush=True)
        print("3. puntos netos (todas con peso 1; y con A+B+C contando como una sola)")
        for nom, S in (("peso 1 cada una", X.sum(axis=1)), ("A+B+C como una", np.sign(trio.sum(axis=1)) + X[:, 3:].sum(axis=1))):
            for umbral in (1, 2, 3):
                txt = f"  {nom:<16} netos >= {umbral}"
                for k in (0, 1):
                    m = (np.abs(S) >= umbral) & (tr == k)
                    if m.sum() < 30:
                        txt += f" | pocos ({int(m.sum())})"; continue
                    ok = ((S[m] > 0) == sube[m]).mean(); ps = (S[m] > 0).mean(); b = ps * base[k] + (1 - ps) * (1 - base[k])
                    txt += f" | {100 * m.sum() / (tr == k).sum():4.1f}% de las veces · acierta {100 * ok:4.1f}% (normal {100 * b:4.1f}%, z {z_de(ok, b, m.sum() / ne):+.1f})"
                print(txt, flush=True)
        print("4. pesos aprendidos con 2022-24 (regresión logística), probados en 2025-26")
        Xa, ya = X[tr == 0], sube[tr == 0].astype(float)
        w, b0 = np.zeros(6), 0.0
        for _ in range(3000):
            p = 1 / (1 + np.exp(-(Xa @ w + b0)))
            w -= 0.5 * (Xa.T @ (p - ya) / len(ya) + 0.001 * w); b0 -= 0.5 * (p - ya).mean()
        print("  pesos: " + " · ".join(f"{NOMBRES[j][0]} {w[j]:+.2f}" for j in range(6)) + f" (base {b0:+.2f})")
        Xb, yb = X[tr == 1], sube[tr == 1]
        pb = 1 / (1 + np.exp(-(Xb @ w + b0)))
        Sb = Xb.sum(axis=1)
        for q in (0.02, 0.04):
            m = np.abs(pb - 0.5) >= q
            if m.sum() >= 30:
                ok = ((pb[m] > 0.5) == yb[m]).mean()
                print(f"  aprendidos, lejos de 50% por {int(q * 100)} puntos o más: {100 * m.mean():4.1f}% de las veces · acierta {100 * ok:4.1f}%")
        for umbral in (1, 2):
            m = np.abs(Sb) >= umbral
            if m.sum() >= 30:
                print(f"  pesos iguales, netos >= {umbral}: {100 * m.mean():4.1f}% de las veces · acierta {100 * ((Sb[m] > 0) == yb[m]).mean():4.1f}%")


if __name__ == "__main__":
    main()
