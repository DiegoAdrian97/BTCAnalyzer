"""Prueba sin red del modelo de direccion de la app (python pruebas/modelo_direccion_offline.py; tarda un par de minutos).
(a) los rasgos de rasgos_direccion (Python) y rasgosDireccion (JS, por node) coinciden con medir_retador.rasgos_ultima
    sobre velas sinteticas (1e-9), con distintas cantidades de velas
(b) la exportacion con compuerta (medir_retador.modelo_direccion) produce un JSON valido que, cargado por la app (Python y JS),
    da la misma probabilidad que el modelo de sklearn; un H que no pasa la compuerta no va, y si ninguno pasa "H" queda vacio."""
import json, os, subprocess, sys
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import numpy as np  # noqa: E402
import analisis_btc as A  # noqa: E402
import medir_retador as m  # noqa: E402

T0 = 1_700_000_000_000 - 1_700_000_000_000 % m.HMS          # hora redonda
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
    return [[T0 + i * m.HMS, float(o[i]), float(h[i]), float(l[i]), float(c[i]), float(v[i]), float(tb[i])] for i in range(n)]


JS = r"""
const R = process.argv[1];
const A = require(R + '/JavascriptVersion/analisis.js');
const d = JSON.parse(require('fs').readFileSync(0, 'utf8'));
globalThis.MODELO_DIRECCION = d.modelo;
console.log(JSON.stringify({ rasgos: d.cortes.map((v) => A.rasgosDireccion(v)), probs: d.cortes.map((v) => [1, 4].map((H) => A.probModelo(H, v))),
  validos: Object.keys(A.modeloValido(d.modelo)).map(Number).sort((a, b) => a - b) }));
"""


def con_js(cortes, modelo):
    out = subprocess.run(["node", "-e", JS, RAIZ], input=json.dumps({"cortes": cortes, "modelo": modelo}), capture_output=True, text=True)
    if out.returncode:
        raise SystemExit("node fallo:\n" + out.stderr[-2000:])
    return json.loads(out.stdout)


def cerca(a, b, tol=1e-9):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return a.shape == b.shape and bool(np.all(np.abs(a - b) <= tol * np.maximum(1.0, np.abs(a))))


# (a) rasgos
filas = sintetico(9000, 3, phi=0.3)
largos = (169, 400, 1000, 3000, 9000)
cortes = [[f[:6] for f in filas[:n]] for n in largos]
ref = [m.rasgos_ultima(filas[:n]) for n in largos]
chequear("(a) los nombres de rasgos_ultima son los de la app, en orden", ref[0][1] == A.RASGOS_DIRECCION)
js = con_js(cortes, {})
for n, c, (x_ref, _), x_js in zip(largos, cortes, ref, js["rasgos"]):
    chequear(f"(a) Python = rasgos_ultima con {n} velas (1e-9)", cerca(A.rasgos_direccion(c), x_ref), f"max dif {np.max(np.abs(np.array(A.rasgos_direccion(c)) - x_ref)):.1e}")
    chequear(f"(a) JS = rasgos_ultima con {n} velas (1e-9)", cerca(x_js, x_ref), f"max dif {np.max(np.abs(np.array(x_js) - x_ref)):.1e}")
chequear("(a) con menos de 169 velas no hay rasgos", A.rasgos_direccion(cortes[0][:168]) is None and js["rasgos"] is not None)
js_corto = con_js([cortes[0][:168]], {})
chequear("(a) JS tampoco con 168 velas", js_corto["rasgos"] == [None])

# (b) exportacion con compuerta
res = m.correr(filas, meses_ini=5, arboles=40, n_boot=200, horizontes=(1, 4))
st1 = res["por_H"]["1"]["modelos"]["logistica_sin_taker"]
chequear("(b) la variante sin taker esta en el resultado y en el veredicto", "logistica_sin_taker" in res["veredicto"]["1"] and st1["ventaja_ic90"][0] is not None,
         f"H=1 ventaja {st1['ventaja'] * 100:+.2f}% IC90 [{st1['ventaja_ic90'][0] * 100:+.2f}, {st1['ventaja_ic90'][1] * 100:+.2f}]")
objetos = {}
mod = m._limpio(m.modelo_direccion(filas, res, ahora_ms=123456789, objetos=objetos))
mod = json.loads(json.dumps(mod))                                      # lo que queda en el archivo
pasan = [H for H in ("1", "4") if res["por_H"][H]["modelos"]["logistica_sin_taker"]["ventaja_ic90"][0] > 0]
chequear("(b) la señal plantada pasa la compuerta en H=1", "1" in pasan)
chequear("(b) el archivo tiene exactamente los H que pasan la compuerta", sorted(mod["H"]) == sorted(pasan) and mod["actualizado"] == 123456789, f"{sorted(mod['H'])}")
for H, g in mod["H"].items():
    n = len(A.RASGOS_DIRECCION)
    chequear(f"(b) H={H}: campos completos", g["rasgos"] == A.RASGOS_DIRECCION and len(g["media"]) == len(g["escala"]) == len(g["coef"]) == n and min(g["escala"]) > 0
             and 0 < g["u10"] < 0.5 and 0 < g["normal"] < 100 and g["ic90"][0] > 0 and g["n_ef"] > 0 and abs(g["ventaja"] - res["por_H"][H]["modelos"]["logistica_sin_taker"]["ventaja"] * 100) < 1e-9,
             f"normal {g['normal']:.1f}% u10 {g['u10']:.4f} ventaja {g['ventaja']:+.2f}%")
chequear("(b) la app valida el archivo", sorted(A.modelo_valido(mod)) == sorted(int(H) for H in mod["H"]))

A.usar_modelo(mod)
vs = [f[:6] for f in filas]
x = np.array([m.rasgos_ultima(filas)[0]])
js = con_js([vs], mod)
for H, (sc, lr) in objetos.items():
    p_sk = float(lr.predict_proba(sc.transform(x))[0, 1])
    chequear(f"(b) H={H}: prob de la app (Python) = sklearn (1e-9)", abs(A.prob_modelo(H, vs) - p_sk) < 1e-9, f"{A.prob_modelo(H, vs):.6f} vs {p_sk:.6f}")
    chequear(f"(b) H={H}: prob de la app (JS) = sklearn (1e-9)", abs(js["probs"][0][[1, 4].index(H)] - p_sk) < 1e-9)
chequear("(b) un H sin modelo da None", A.prob_modelo(24, vs) is None and (str(4) in mod["H"] or A.prob_modelo(4, vs) is None))
A.usar_modelo({})

# compuerta cerrada: sin ventaja significativa no va ningun H
cerrada = json.loads(json.dumps(res))
for H in ("1", "4"):
    cerrada["por_H"][H]["modelos"]["logistica_sin_taker"]["ventaja_ic90"][0] = -0.001
vacio = m.modelo_direccion(filas, cerrada, ahora_ms=1)
chequear("(b) compuerta cerrada: el archivo queda con \"H\": {}", vacio == {"actualizado": 1, "H": {}})
chequear("(b) la app lo carga sin modelo y todo sigue como antes", (A.usar_modelo(vacio), A.prob_modelo(1, vs))[1] is None)

# el resumen y el JSON de resultados incluyen la variante
txt = m.resumen(m._limpio(res))
chequear("(b) el resumen cuenta la variante sin taker", "logística sin taker" in txt and "abstención logística sin taker" in txt)

if fallas:
    print("\nFALLARON:", *fallas, sep="\n  ")
    sys.exit(1)
print("\ntodo ok")
