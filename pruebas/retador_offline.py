"""Prueba sin red de medir_retador con velas sinteticas (los datos entran por parametro).
python pruebas/retador_offline.py  (sale con error si algo no da lo esperado; tarda un par de minutos o menos).
(a) camino aleatorio: la ventaja de logistica y LightGBM NO puede ser significativamente > 0 (si lo es, hay fuga de futuro)
(b) señal plantada (autocorrelacion del retorno de 1 h): la logistica tiene que sacar ventaja > 0
(c) los rasgos de la vela t no cambian si se modifican las velas posteriores."""
import os, sys, time
import numpy as np
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import medir_retador as m  # noqa: E402

T0 = 1609459200000                  # 2021-01-01
PEQ = dict(meses_ini=5, arboles=40, n_boot=200)
fallas = []


def chequear(nombre, ok, detalle=""):
    print(("ok   " if ok else "FALLA"), nombre, detalle, flush=True)
    if not ok:
        fallas.append(nombre)


def sintetico(n, seed, phi=0.0, sigma=0.004):
    """Retornos de 1 h r[t] = phi*r[t-1] + ruido; velas [t, o, h, l, c, vol, taker]."""
    g = np.random.default_rng(seed)
    r = np.zeros(n)
    e = g.normal(0, sigma, n)
    for i in range(1, n):
        r[i] = phi * r[i - 1] + e[i]
    c = 30000 * np.exp(np.cumsum(r))
    o = np.concatenate([[30000], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(g.normal(0, 0.001, n)))
    l = np.minimum(o, c) * (1 - np.abs(g.normal(0, 0.001, n)))
    v = np.exp(g.normal(5, 0.5, n))
    tb = v * np.clip(0.5 + g.normal(0, 0.05, n), 0, 1)
    return [[T0 + i * m.HMS, o[i], h[i], l[i], c[i], v[i], tb[i]] for i in range(n)]


# (a) camino aleatorio puro
for seed in (1, 2):
    t = time.time()
    res = m.correr(sintetico(9000, seed), **PEQ)
    for H, r in res["por_H"].items():
        for k in ("logistica", "lightgbm"):
            a = r["modelos"][k]
            chequear(f"(a) azar seed {seed} H={H} {k}: lim inf IC90 <= 0 (sin fuga)", a["ventaja_ic90"][0] <= 0,
                     f"ventaja {a['ventaja'] * 100:+.2f}% IC90 [{a['ventaja_ic90'][0] * 100:+.2f}, {a['ventaja_ic90'][1] * 100:+.2f}] "
                     f"{'(incluye 0)' if a['ventaja_ic90'][0] <= 0 <= a['ventaja_ic90'][1] else '(<0 entero: sobreajuste, no fuga)'}")
    print(f"   ({time.time() - t:.0f} s)")
txt = m.resumen(m._limpio(res))
n_lin = len(txt.strip().splitlines())
chequear("resumen de 20 a 40 lineas", 20 <= n_lin <= 40, f"({n_lin})")
chequear("resumen con veredicto por H", sum("Veredicto H=" in x for x in txt.splitlines()) == 3)

# (b) señal plantada
t = time.time()
res = m.correr(sintetico(9000, 3, phi=0.3), horizontes=(1,), **PEQ)
a = res["por_H"]["1"]["modelos"]["logistica"]
chequear("(b) señal plantada: logistica con ventaja > 0 en H=1", a["ventaja"] > 0 and a["ventaja_ic90"][0] > 0,
         f"ventaja {a['ventaja'] * 100:+.2f}% IC90 [{a['ventaja_ic90'][0] * 100:+.2f}, {a['ventaja_ic90'][1] * 100:+.2f}] ({time.time() - t:.0f} s)")
chequear("(b) el veredicto lo dice", res["veredicto"]["1"]["logistica"] is True)

# (c) rasgos sin mirar el futuro
filas = sintetico(3000, 4)
X1, nom = m.rasgos(m.armar(filas))
for tt in (1000, 2500):
    mod = [list(f) for f in filas]
    g = np.random.default_rng(9)
    for i in range(tt + 1, len(mod)):
        mod[i][1:5] = [x * g.uniform(0.7, 1.4) for x in mod[i][1:5]]
        mod[i][5] *= g.uniform(0.1, 9)
        mod[i][6] *= g.uniform(0.1, 9)
    X2, _ = m.rasgos(m.armar(mod))
    igual = np.allclose(X1[:tt + 1], X2[:tt + 1], rtol=0, atol=1e-12, equal_nan=True)
    chequear(f"(c) rasgos de t<={tt} no cambian al tocar velas posteriores", igual)
    chequear(f"(c) control: los rasgos de t={tt + 1} si cambian (la prueba tiene poder)", not np.allclose(X1[tt + 1], X2[tt + 1], equal_nan=True))

if fallas:
    print("\nFALLARON:", *fallas, sep="\n  ")
    sys.exit(1)
print("\ntodo ok")
