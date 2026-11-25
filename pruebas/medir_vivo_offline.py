"""Prueba sin red de medir_vivo.evaluar_vivo con velas sinteticas.
python pruebas/medir_vivo_offline.py (sale con error si algo no da lo esperado)."""
import json, os, sys, tempfile
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import medir_vivo as mv  # noqa: E402
import medir_central as mc  # noqa: E402

H, V, D = 3600000, 300000, 86400000
T0 = 1_700_000_000_000 // D * D + 40 * D          # un dia redondo, con 40 dias de velas antes
fallas = []


def chequear(nombre, real, esperado):
    if real != esperado:
        fallas.append(f"{nombre}: dio {real!r}, esperaba {esperado!r}")


def velas(f, desde, hasta):
    """{apertura: cierre} de velas de 5 min con cierre f(apertura)."""
    return {t: f(t) for t in range(desde, hasta, V)}


def fila(t, sube, precio=100.0, lo=None, hi=None, tf="1h", h=1):
    return {"tf": tf, "t": t, "h": h, "precio": precio, "sube": sube, "min": lo, "max": hi}


# 30+ dias de velas alternando: cada hora completa sube o baja segun la paridad (cierre 110 o 90 vs precio 100)
def serie(t):
    return 110.0 if (t // H) % 2 == 0 else 90.0


P = velas(serie, T0 - 35 * D, T0 + 3 * D)
AHORA = max(P) + V
# resultado de h=1 de 1h con t=T0+k*H: la vela 5m que abre en t+H-V, o sea la de la hora (t//H) -> paridad de t//H (la vela cae en la hora t//H)
filas_ = [fila(T0 + k * H, 50.0, lo=50, hi=150) for k in range(48)]
pr, rg = mv.evaluar_vivo(filas_, P, AHORA)
x = pr[0]
chequear("(a) n", x["n"], 48)
chequear("(a) brier 50%", x["brier"], 0.25)
chequear("(a) ventaja_50 = 0", x["ventaja_50"], 0.0)
chequear("(a) n_ef 1h h=1", x["n_ef"], 48.0)
chequear("(a) horizonte", x["horizonte"], "1 hora")
chequear("(a) pocos con n_ef < 100", x.get("pocos"), True)

# (b) predicciones perfectas: 100% cuando sube, 0% cuando baja
perf = []
for k in range(48):
    t = T0 + k * H
    sube = P[t + H - V] > 100
    perf.append(fila(t, 100.0 if sube else 0.0))
pr, _ = mv.evaluar_vivo(perf, P, AHORA)
chequear("(b) brier 0", pr[0]["brier"], 0.0)
chequear("(b) ventaja_50 = 100", pr[0]["ventaja_50"], 100.0)
chequear("(b) logloss recortado", round(pr[0]["logloss"], 4), round(-__import__("math").log(0.99), 4))

# (c) rango que siempre contiene: cobertura 100, ancho y Winkler = ancho; uno que nunca contiene: Winkler suma 10x la distancia
chequear("(c) cobertura", rg[0]["cobertura"], 100.0)
chequear("(c) ancho", rg[0]["ancho"], 100.0)
chequear("(c) winkler = ancho", rg[0]["winkler"], 100.0)
fuera = [fila(T0 + k * H, 50.0, lo=10, hi=20) for k in range(10)]              # cierres a 110 o 90: distancia 90 o 70 (en % del precio)
_, rg2 = mv.evaluar_vivo(fuera, P, AHORA)
esperado = sum(10 + 10 * (110 - 20 if P[T0 + k * H + H - V] > 100 else 90 - 20) for k in range(10)) / 10
chequear("(c) cobertura 0", rg2[0]["cobertura"], 0.0)
chequear("(c) winkler con distancia", rg2[0]["winkler"], round(esperado, 3))

# filas cuyo resultado todavia no ocurrio: se saltan
pr, _ = mv.evaluar_vivo([fila(AHORA - V, 50.0), fila(AHORA + H, 50.0)], P, AHORA)
chequear("sin resultado: nada", pr, [])

# convencion de h: el resultado es el cierre de la vela que cierra en t + h*tf (la 5m que abre h*tf - 5 min despues de t)
P3 = velas(lambda t: 100.0, T0 - 35 * D, T0 + 3 * D)
P3[T0 + 4 * H - V] = 120.0                                                        # solo la ultima vela 5m de la 4a hora
pr, _ = mv.evaluar_vivo([fila(T0, 90.0, h=4)], P3, max(P3) + V)
chequear("h=4: usa la vela que cierra en t+4h", (pr[0]["brier"], pr[0]["horizonte"]), (round(0.1 ** 2, 4), "4 horas"))
chequear("n_ef = n/h", mv.evaluar_vivo([fila(T0 + k * H, 60.0, h=4) for k in range(8)], P3, max(P3) + V)[0][0]["n_ef"], 2.0)

# (d) la tasa normal no usa velas posteriores a la fila: dos mundos iguales hasta t, distintos despues
t_fila = T0 + 10 * D
base = velas(serie, T0 - 35 * D, T0 + 30 * D)
mundo_a = dict(base)
mundo_b = {k: (v if k < t_fila else (90.0 if v > 100 else 110.0)) for k, v in base.items()}    # invierte todo lo posterior
# el resultado de la propia fila sale de una vela posterior a t, asi que se deja igual en los dos (solo cambia la tasa si mira el futuro)
t_res = t_fila + H - V
mundo_b[t_res] = mundo_a[t_res]
fila_d = [fila(t_fila, 70.0)]
ahora_d = T0 + 30 * D
va = mv.evaluar_vivo(fila_d, mundo_a, ahora_d)[0][0]
vb = mv.evaluar_vivo(fila_d, mundo_b, ahora_d)[0][0]
chequear("(d) ventaja_normal igual con otro futuro", va["ventaja_normal"], vb["ventaja_normal"])
chequear("(d) la tasa normal existe", va["ventaja_normal"] is not None, True)
# y la funcion interna: con todo el futuro invertido, las subas de los 30 dias anteriores a t no cambian
ta, tb = mv._tasas("1h", 1, mundo_a, t_fila, t_fila)(t_fila), mv._tasas("1h", 1, mundo_b, t_fila, t_fila)(t_fila)
chequear("(d) tasa igual", ta, tb)
chequear("(d) tasa de alternancia ~50% con casos", (abs(ta[0] - 0.5) < 0.01, ta[1] > 600), (True, True))
# si la tasa SI mirara velas posteriores (mundo invertido a partir de t - 1 dia) cambiaria: control de que el caso detecta fugas
mundo_c = {k: (v if k < t_fila - D else 110.0) for k, v in base.items()}
chequear("(d) control: el pasado si cambia la tasa", mv._tasas("1h", 1, mundo_c, t_fila, t_fila)(t_fila) != ta, True)
# el ultimo origen usable termina en t: un origen mas tarde (s + h*tf > t) no cuenta
pocos_dias = {k: v for k, v in base.items() if k >= t_fila - 2 * D}
tp, npoc = mv._tasas("1h", 1, pocos_dias, t_fila, t_fila)(t_fila)
chequear("(d) con 2 dias: usa lo disponible (<= 48 origenes)", 10 <= npoc <= 48, True)
va2 = mv.evaluar_vivo(fila_d, pocos_dias, ahora_d)[0][0]
chequear("(d) clima_dias con 2 dias", va2["clima_dias"], 2.0)

# retorno neto en track.json
with tempfile.TemporaryDirectory() as d:
    ruta = os.path.join(d, "track.json")
    json.dump({"senales": {}}, open(os.path.join(d, "mediciones.json"), "w"))
    F0 = [{"t": T0, "plazo": "1 hora", "precio": 100.0, "dir": "sube", "pts": 4.0, "sen": {}, "t_real": None}]
    mc.escribir(ruta, F0, {("1 hora", "todas"): [5, 10]}, {}, {"1 hora": [20.0, 10.0]}, {}, (pr, []))
    out = json.load(open(ruta, encoding="utf-8"))
chequear("retorno_pb", out["plazos"][0]["retorno_pb"], 15.0)
chequear("retorno_neto_pb", out["plazos"][0]["retorno_neto_pb"], 15.0 - mv.COSTO_PB)
chequear("secciones nuevas", ("probabilidades" in out, "rangos" in out, "senales" in out, "calibracion" in out), (True,) * 4)

# lectura del CSV por nombre de columna
csv = "t,h,precio,sube,min,max,mediana\n1700000000000,2,100.5,55.2,99,102,100.6\n1700003600000,2,,50,,,\n"
f = mv.leer(csv, "30m")
chequear("leer: filas validas", len(f), 1)
chequear("leer: campos", (f[0]["tf"], f[0]["h"], f[0]["sube"], f[0]["min"], f[0]["max"]), ("30m", 2, 55.2, 99.0, 102.0))
chequear("horizonte 30m x2", mv.horizonte_txt("30m", 2), "1 hora")
chequear("horizonte 1d x7", mv.horizonte_txt("1d", 7), "7 días")

if fallas:
    print("FALLAS:", *fallas, sep="\n  ")
    sys.exit(1)
print("medir_vivo_offline: todo ok")
