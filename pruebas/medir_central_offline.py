"""Prueba sin red de medir_central.evaluar / escribir con filas y precios sinteticos.
python pruebas/medir_central_offline.py (sale con error si algo no da lo esperado)."""
import json, os, sys, tempfile
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import medir_central as m  # noqa: E402

H, V = 3600000, 300000
T0 = 1_700_000_100_000 // H * H            # una hora redonda
fallas = []


def chequear(nombre, real, esperado):
    if real != esperado:
        fallas.append(f"{nombre}: dio {real!r}, esperaba {esperado!r}")


def fila(plazo, t, precio=100.0, dir="sube", pts=4.0, t_real=None, sen=None):
    return {"t": t, "plazo": plazo, "precio": precio, "dir": dir, "pts": pts, "sen": sen or {"macd": 1.0}, "t_real": t_real}


# velas de 5 min (apertura -> cierre): todas a 110 salvo las que se indican
P = {T0 + i * V: 110.0 for i in range(-2, 12 * 30)}
AHORA = max(P) + V

# 1) base de tiempo: con t_real manda t_real; el cierre es el de la vela que cierra en el primer multiplo de 5 min >= base + plazo
real = T0 + 7 * 60000 + 30000                                    # 7 min 30 s despues de la hora
fin = -(-(real + H) // V) * V                                    # = T0 + H + 10 min
P2 = dict(P); P2[fin - V] = 90.0                                 # solo esa vela baja
por, sen, plata, cal = m.evaluar([fila("1 hora", T0, t_real=real)], P2, AHORA)
chequear("t_real usa su vela", por[("1 hora", "todas")], [0, 1])  # dijo sube, cerro en 90 -> fallo
por, *_ = m.evaluar([fila("1 hora", T0)], P2, AHORA)              # sin t_real: base = t -> cierra T0 + H, otra vela (110)
chequear("sin t_real usa t", por[("1 hora", "todas")], [1, 1])
chequear("clave de 3,5 puntos", ("1 hora", "3,5 puntos o más") in por and ("1 hora", "3 puntos o más") not in por, True)

# multiplo exacto de 5 min: base + plazo ya es multiplo -> la vela que abre 5 min antes
P3 = dict(P); P3[T0 + H - V] = 90.0
por, *_ = m.evaluar([fila("1 hora", T0)], P3, AHORA)
chequear("multiplo exacto", por[("1 hora", "todas")], [0, 1])

# 2) 5 y 15 min: sin t_real se descartan, con t_real se miden
F = [fila("5 min", T0), fila("15 min", T0), fila("5 min", T0, t_real=T0 + 60000), fila("15 min", T0, t_real=T0 + 60000)]
por, *_ = m.evaluar(F, P, AHORA)
chequear("5 min", por[("5 min", "todas")], [2 - 1, 1])
chequear("15 min", por[("15 min", "todas")], [1, 1])

# 3) n efectivo y estados
chequear("n_ef 1 hora", m.n_ef("1 hora", 240), 240)
chequear("n_ef 4 horas", m.n_ef("4 horas", 240), 60)
chequear("n_ef 1 dia", m.n_ef("1 día", 240), 10)
chequear("n_ef 5 min", m.n_ef("5 min", 50), 50)

# estados: 1 hora con 400 casos (ef. 400) y 4 horas con 400 casos (ef. 100) y 1 dia (ef. ~16.7 -> pocos)
sen = {("1 hora", "macd"): [100, 400],        # 25% acierta: deriva
       ("4 horas", "macd"): [60, 400],        # 15% acierta, ef. 100: deriva
       ("4 horas", "vwap"): [40, 399],        # ef. 99,75 -> pocos
       ("1 día", "obv"): [5, 400],            # ef. 16,7 -> pocos
       ("1 hora", "bollinger"): [230, 400],   # 57,5% (esperado 56) -> ok
       ("1 hora", "casos"): [200, 400]}       # esperado null -> 50 -> ok
M = {"senales": {"bollinger": {"nombre": "Bollinger", "esperado": 56}, "casos": {"nombre": "Casos", "esperado": None}}}
with tempfile.TemporaryDirectory() as d:
    json.dump(M, open(os.path.join(d, "mediciones.json"), "w"))
    ruta = os.path.join(d, "track.json")
    F0 = [fila("1 hora", T0)]
    por = {("1 hora", "todas"): [50, 100], ("4 horas", "todas"): [30, 100], ("1 hora", "3,5 puntos o más"): [10, 20]}
    m.escribir(ruta, F0, por, sen, {}, {})
    out = json.load(open(ruta, encoding="utf-8"))
est = {(x["plazo"], x["clave"]): x for x in out["senales"]}
chequear("estado 1h macd", est[("1 hora", "macd")]["estado"], "deriva")
chequear("estado 4h macd", est[("4 horas", "macd")]["estado"], "deriva")
chequear("estado 4h vwap", est[("4 horas", "vwap")]["estado"], "pocos")
chequear("estado 1d obv", est[("1 día", "obv")]["estado"], "pocos")
chequear("estado bollinger", est[("1 hora", "bollinger")]["estado"], "ok")
chequear("estado casos (null=50)", est[("1 hora", "casos")]["estado"], "ok")
chequear("n_ef senal", (est[("4 horas", "macd")]["n"], est[("4 horas", "macd")]["n_ef"]), (400, 100))
pl = {x["plazo"]: x for x in out["plazos"]}
chequear("n_ef plazo", (pl["4 horas"]["n"], pl["4 horas"]["n_ef"]), (100, 25))
chequear("n_fuerte", pl["1 hora"]["n_fuerte"], 20)

# 4) las filas viejas (9 columnas) y las nuevas (10, o 9 + coma vacia) se leen igual
import historial  # noqa: E402
chequear("columna t_real", historial.CENTRAL_COL.split(",")[-1], "t_real")
historial._central.clear(); historial._cargados.clear(); historial._sucios.clear()
historial._ultima_subida = 1e18                               # que no intente subir
rows = [{"tabla": "resumen", "precio": 100.0},
        {"tabla": "central", "plazo": "1 hora", "direccion": "sube", "direccion_puntos": 4.0, "a_favor": 3, "en_contra": 1, "fuerza": "alta",
         "factores": [["direccion", 1, 2.0, "MACD de algo"]]}]
historial._cargados.add(("central", historial._dia(T0)))
historial.anotar_central(rows, ahora_ms=T0 + 123456)
linea = next(iter(historial._central[historial._dia(T0)].values()))
chequear("fila nueva: t redondeada y t_real", (linea.split(",")[0], linea.split(",")[-1]), (str(T0), str(T0 + 123456)))
chequear("fila nueva: 10 columnas", len(linea.split(",")), 10)
for texto, esperado in (("1,1 hora,100,sube,4,3,1,alta,macd:2", None), ("1,1 hora,100,sube,4,3,1,alta,macd:2,", None), ("1,1 hora,100,sube,4,3,1,alta,macd:2,1700", 1700)):
    p = texto.split(",")
    chequear("t_real de " + texto[-8:], int(p[9]) if len(p) > 9 and p[9].strip().isdigit() else None, esperado)

if fallas:
    print("FALLAS:", *fallas, sep="\n  ")
    sys.exit(1)
print("medir_central_offline: todo ok")
