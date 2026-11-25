"""Prueba sin red del modelo de direccion de la app (python pruebas/modelo_direccion_offline.py; tarda un par de minutos).
(a) los rasgos de rasgos_direccion (Python) y rasgosDireccion (JS, por node), con los 2 del perfil de volumen, coinciden con
    medir_retador.rasgos_ultima sobre velas sinteticas (1e-9), con distintas cantidades de velas
(b) la exportacion con compuerta (medir_retador.modelo_direccion) elige por H la variante sin taker o la con perfil (mayor limite
    inferior del IC90, > 0) y produce un JSON valido que, cargado por la app (Python y JS), da la misma probabilidad que el modelo de
    sklearn; un H que no pasa la compuerta no va, y si ninguno pasa "H" queda vacio."""
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
chequear("(a) los nombres de rasgos_ultima son los de la app (con los 2 del perfil), en orden", ref[0][1] == A.RASGOS_APP and len(ref[0][0]) == 22)
js = con_js(cortes, {})
for n, c, (x_ref, _), x_js in zip(largos, cortes, ref, js["rasgos"]):
    chequear(f"(a) Python = rasgos_ultima con {n} velas (1e-9)", cerca(A.rasgos_direccion(c), x_ref), f"max dif {np.max(np.abs(np.array(A.rasgos_direccion(c)) - x_ref)):.1e}")
    chequear(f"(a) JS = rasgos_ultima con {n} velas (1e-9)", cerca(x_js, x_ref), f"max dif {np.max(np.abs(np.array(x_js) - x_ref)):.1e}")
chequear("(a) con menos de 169 velas no hay rasgos", A.rasgos_direccion(cortes[0][:168]) is None and js["rasgos"] is not None)
js_corto = con_js([cortes[0][:168]], {})
chequear("(a) JS tampoco con 168 velas", js_corto["rasgos"] == [None])

# (b) exportacion con compuerta: por H va la variante sin taker o la con perfil (la de mayor limite inferior del IC90, > 0)
res = m.correr(filas, meses_ini=5, arboles=40, n_boot=200, horizontes=(1, 4))
st1 = res["por_H"]["1"]["modelos"]["logistica_sin_taker"]
pf1 = res["por_H"]["1"]["modelos"]["logistica_perfil"]
chequear("(b) las variantes sin taker y con perfil estan en el resultado y en el veredicto",
         all(k in res["veredicto"]["1"] and res["por_H"]["1"]["modelos"][k]["ventaja_ic90"][0] is not None for k in ("logistica_sin_taker", "logistica_perfil")),
         f"H=1 sin taker {st1['ventaja'] * 100:+.2f}% IC90 [{st1['ventaja_ic90'][0] * 100:+.2f}, {st1['ventaja_ic90'][1] * 100:+.2f}]; "
         f"con perfil {pf1['ventaja'] * 100:+.2f}% IC90 [{pf1['ventaja_ic90'][0] * 100:+.2f}, {pf1['ventaja_ic90'][1] * 100:+.2f}]")
vs = [f[:6] for f in filas]
x_ref = m.rasgos_ultima(filas)[0]
NOMBRES = {"logistica_sin_taker": list(A.RASGOS_DIRECCION), "logistica_perfil": list(A.RASGOS_APP)}


def verificar(etq, res_, esperado):
    """Exporta con `res_`, revisa el archivo y que la app (Python y JS) de la misma probabilidad que sklearn. esperado = {H: variante}."""
    objetos = {}
    mod = json.loads(json.dumps(m._limpio(m.modelo_direccion(filas, res_, ahora_ms=123456789, objetos=objetos))))   # lo que queda en el archivo
    chequear(f"(b) {etq}: el archivo tiene exactamente los H que pasan la compuerta, con la variante elegida",
             {H: g["variante"] for H, g in mod["H"].items()} == {str(H): v for H, v in esperado.items()} and mod["actualizado"] == 123456789,
             f"{ {H: g['variante'] for H, g in mod['H'].items()} }")
    for H, g in mod["H"].items():
        n = len(g["rasgos"])
        chequear(f"(b) {etq} H={H}: campos completos ({g['variante']})",
                 g["rasgos"] == NOMBRES[g["variante"]] and len(g["media"]) == len(g["escala"]) == len(g["coef"]) == n and min(g["escala"]) > 0
                 and 0 < g["u10"] < 0.5 and 0 < g["normal"] < 100 and g["ic90"][0] > 0 and g["n_ef"] > 0
                 and abs(g["ventaja"] - res_["por_H"][H]["modelos"][g["variante"]]["ventaja"] * 100) < 1e-9,
                 f"normal {g['normal']:.1f}% u10 {g['u10']:.4f} ventaja {g['ventaja']:+.2f}%")
    chequear(f"(b) {etq}: la app valida el archivo", sorted(A.modelo_valido(mod)) == sorted(int(H) for H in mod["H"]))
    A.usar_modelo(mod)
    js = con_js([vs], mod)
    chequear(f"(b) {etq}: JS valida los mismos H", js["validos"] == sorted(int(H) for H in mod["H"]))
    for H, (sc, lr, ci) in objetos.items():
        p_sk = float(lr.predict_proba(sc.transform(x_ref[ci][None, :]))[0, 1])
        chequear(f"(b) {etq} H={H}: prob de la app (Python) = sklearn (1e-9)", abs(A.prob_modelo(H, vs) - p_sk) < 1e-9, f"{A.prob_modelo(H, vs):.6f} vs {p_sk:.6f}")
        chequear(f"(b) {etq} H={H}: prob de la app (JS) = sklearn (1e-9)", abs(js["probs"][0][[1, 4].index(H)] - p_sk) < 1e-9)
    chequear(f"(b) {etq}: un H sin modelo da None", A.prob_modelo(24, vs) is None and (str(4) in mod["H"] or A.prob_modelo(4, vs) is None))
    A.usar_modelo({})
    return mod


# con lo medido de verdad en los datos sinteticos
esp = {H: m.elegir_variante(res, H)[0] for H in (1, 4) if m.elegir_variante(res, H)}
chequear("(b) la señal plantada pasa la compuerta en H=1", 1 in esp)
verificar("natural", res, esp)

# forzado: gana la con perfil en H=1 y la sin taker en H=4 (los dos con limite inferior > 0)
forzada = json.loads(json.dumps(res))
for H, (a, b) in {"1": (0.010, 0.005), "4": (0.004, 0.009)}.items():
    forzada["por_H"][H]["modelos"]["logistica_sin_taker"]["ventaja_ic90"][0] = b
    forzada["por_H"][H]["modelos"]["logistica_perfil"]["ventaja_ic90"][0] = a
mod = verificar("forzada (perfil en 1, sin taker en 4)", forzada, {1: "logistica_perfil", 4: "logistica_sin_taker"})
chequear("(b) forzada: la con perfil lleva 22 rasgos y la sin taker 20", len(mod["H"]["1"]["rasgos"]) == 22 and len(mod["H"]["4"]["rasgos"]) == 20)
# empate: gana la sin taker; la que no pasa (limite <= 0) nunca gana aunque la otra sea peor
emp = json.loads(json.dumps(forzada))
emp["por_H"]["1"]["modelos"]["logistica_perfil"]["ventaja_ic90"][0] = emp["por_H"]["1"]["modelos"]["logistica_sin_taker"]["ventaja_ic90"][0]
emp["por_H"]["4"]["modelos"]["logistica_sin_taker"]["ventaja_ic90"][0] = -0.001
chequear("(b) empate: gana la sin taker; si una no pasa, va la otra", m.elegir_variante(emp, 1)[0] == "logistica_sin_taker" and m.elegir_variante(emp, 4)[0] == "logistica_perfil")

# compuerta cerrada: sin ventaja significativa en ninguna variante no va ningun H
cerrada = json.loads(json.dumps(res))
for H in ("1", "4"):
    for k in ("logistica_sin_taker", "logistica_perfil"):
        cerrada["por_H"][H]["modelos"][k]["ventaja_ic90"][0] = -0.001
vacio = m.modelo_direccion(filas, cerrada, ahora_ms=1)
chequear("(b) compuerta cerrada: el archivo queda con \"H\": {}", vacio == {"actualizado": 1, "H": {}})
chequear("(b) la app lo carga sin modelo y todo sigue como antes", (A.usar_modelo(vacio), A.prob_modelo(1, vs))[1] is None)
# un modelo que pide un rasgo que la app no sabe calcular queda sin modelo (en Python y en JS)
raro = json.loads(json.dumps(mod))
raro["H"]["1"]["rasgos"][-1] = "rasgo_que_no_existe"
chequear("(b) un rasgo desconocido deja ese H sin modelo (Python y JS)", sorted(A.modelo_valido(raro)) == [4] and con_js([vs], raro)["validos"] == [4])

# el resumen y el JSON de resultados incluyen las variantes
txt = m.resumen(m._limpio(res))
chequear("(b) el resumen cuenta las variantes sin taker y con perfil", "logística sin taker" in txt and "abstención logística sin taker" in txt
         and "logística con perfil" in txt and "abstención logística con perfil" in txt)

if fallas:
    print("\nFALLARON:", *fallas, sep="\n  ")
    sys.exit(1)
print("\ntodo ok")
