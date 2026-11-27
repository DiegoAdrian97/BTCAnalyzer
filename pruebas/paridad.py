"""Prueba que la version Python y la JavaScript den lo mismo (mismas filas, mismos numeros) con velas inventadas
(semilla fija). La corre GitHub Actions en cada push (.github/workflows/paridad.yml); a mano: python pruebas/paridad.py
Necesita node. Sale con error si algo difiere."""
import json, math, os, random, subprocess, sys, tempfile
from datetime import datetime, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import analisis_btc as A, aprendizaje as apr, fuerte, indicadores as ind, termometro  # noqa: E402

random.seed(7)


def velas(n, ms, p0, vol, t0=1_700_000_000_000):
    out, p = [], p0
    for i in range(n):
        o = p; p *= math.exp(random.gauss(0.0002, vol))
        h, l = max(o, p) * (1 + abs(random.gauss(0, vol / 3))), min(o, p) * (1 - abs(random.gauss(0, vol / 3)))
        out.append([t0 + i * ms, round(o, 2), round(h, 2), round(l, 2), round(p, 2), round(random.uniform(50, 500), 3)])
    return out


H1, H4, D1 = velas(2400, 3_600_000, 60000, 0.006), velas(700, 14_400_000, 60000, 0.012), velas(1600, 86_400_000, 9000, 0.03)
FC = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "filas_central.json"), encoding="utf-8"))   # filas reales para el analisis central
ALT = [[b[0], b[1] / 50000, b[2] / 50000, b[3] / 50000, b[4] / 50000, b[5]] for b in D1]
AHORA = D1[-1][0] + 3_600_000
LIQ = [[AHORA - k * 41_000, "long" if k % 3 else "short", 1000 + 37.5 * k] for k in range(300)]


def entrada_apr(bars, tf_min=60):
    c = [b[4] for b in bars]
    e50, e200, rsi, (ml, ms, mh) = ind.ema(c, 50), ind.ema(c, 200), ind.rsi(c), ind.macd(c)
    return apr.combos(apr.rasgos(bars, tf_min, e50, e200, rsi, mh)), apr.continuos(bars, tf_min, e50, e200, rsi, mh)


# explain (sin ventaja medida / rango del 80%) y el registro de predicciones con su rango
def plazo_1h(sin_ventaja, pu):
    return [{"tabla": "plazo", "plazo": "1 hora", "hora": "03/11 19:00", "veredicto": "Casi moneda", "sin_ventaja": sin_ventaja,
             "sube": 44.8, "base": 48.9, "obj_arriba": 77960.0, "obj_abajo": 77760.0, "primero_arriba": pu, "margen_primero": 3.0,
             "distancia": 100.0, "min": 77310.5, "max": 78420.2, "coinciden": "alcista" if pu == 70.0 else None},
            {"tabla": "marco", "tf": "15m", "rating": 0.3, "rating_txt": "Compra", "rsi": 55, "macd_cruce": None, "elliott_objetivo": None, "elliott_corto": ""},
            {"tabla": "marco", "tf": "1h", "rating": -0.4, "rating_txt": "Venta", "rsi": 72, "macd_cruce": "bajista", "elliott_objetivo": None, "elliott_corto": ""},
            {"tabla": "nivel", "nombre": "Máximo 24 h", "precio": 78500.0, "tipo": "resistencia", "distancia": 0.8},
            {"tabla": "nivel", "nombre": "Mínimo 24 h", "precio": 77000.0, "tipo": "soporte", "distancia": -1.1},
            {"tabla": "contexto", "clave": "flujo_1 h", "senal": "alcista", "detalle": "Dominan los compradores agresivos"},
            {"tabla": "aprendizaje", "plazo": "1 hora", "repasadas": 0}]


SPEC_1H = ["1 hora", "5m", 12, ["15m", "1h"], ["flujo_1 h", "flujo_4 h", "oi_1h"], "15 min"]
CASOS = {f"{sv}_{pu}": plazo_1h(sv, pu) for sv in (True, False) for pu in (30.0, 50.0, 70.0)}
CASOS["modelo"] = [{**r, "sube": 57.0, "base": 50.4, "veredicto": "Sesgo alcista", "fuente_sube": "modelo", "sube_casos": 44.8, "modelo_ventaja": 0.46}
                   if r["tabla"] == "plazo" else r for r in plazo_1h(False, 70.0)]
CASOS["perfil"] = [{**r, "perfil": {"poc": 77700.0, "vah": 78300.0, "val": 77450.0}} if r["tabla"] == "plazo" else r for r in plazo_1h(False, 70.0)]
LOG_ENTRADAS = [[2000, "1h", 4, 100.0, 55.0, 95.0, 105.0], [3000, "1h", 4, 100.0, 50.0, 99.0, 101.0], [4000, "4h", 3, 100.0, 40.0, 90.0, 110.0]]
LOG_CIERRES = {"1h": [[1000 + 4 * 3_600_000, 101.0], [2000 + 4 * 3_600_000, 104.0], [3000 + 4 * 3_600_000, 102.0]], "4h": [[4000 + 3 * 14_400_000, 95.0]]}


def registro_py():
    """log_and_score en un archivo aparte (no toca data/predicciones_btc.csv), con una fila vieja de 5 columnas."""
    tmp = tempfile.mkdtemp()
    A.LOG_FILE, A.DATA_DIR = os.path.join(tmp, "log.csv"), tmp
    with open(A.LOG_FILE, "w") as f:
        f.write("1000,1h,4,100.0,60.0\n")
    sc = A.log_and_score([tuple(e) for e in LOG_ENTRADAS], {tf: dict(xs) for tf, xs in LOG_CIERRES.items()})
    return {f"{tf}|{h}": list(v) for (tf, h), v in sorted(sc.items())}


# opciones inventadas: vencimientos de viernes y de otros dias, puts y calls alrededor de 60.000
OPC_AHORA = 1_793_700_000_000          # martes 03/11/2026
OPC_LIBRO = [{"instrument_name": f"BTC-{d}-{k}-{t}", "open_interest": round(1 + (k / 1000) % 7 + (t == "P") * 2.5, 1),
              "mark_iv": 45 + (60000 - k) / 2000 + (t == "P") * 3}
             for d in ("4NOV26", "6NOV26", "13NOV26", "27NOV26") for k in range(50000, 70001, 2500) for t in "CP"]
OPC_DVOL = [[OPC_AHORA - (720 - k) * 3_600_000, 40 + 5 * math.sin(k / 30)] for k in range(721)]


# rango de "1 día" mezclado con el DVOL: con DVOL de ahora, con DVOL de hace 8 h (viejo: no toca), sin DVOL y sin rango
DVOL_DIA = [[59000.5, 63000.5, 61234.5, OPC_DVOL, OPC_AHORA], [59000.5, 63000.5, 61234.5, OPC_DVOL, OPC_AHORA + 8 * 3_600_000],
            [59000.5, 63000.5, 61234.5, [], OPC_AHORA], [None, None, 61234.5, OPC_DVOL, OPC_AHORA],
            [0.4123, 0.4377, 0.425, [[OPC_AHORA, 85.5]], OPC_AHORA + 1000]]


def dvol_dia_py():
    out = []
    for lo, hi, p, dv, t in DVOL_DIA:
        v = A.dvol_vigente(dv, t)
        out.append([v, list(A.mezcla_dvol_dia(lo, hi, p, v))])
    return out


# flujo de compras: velas de 1 h con volumen comprador, armadas para cada caso (divergencias, absorcion, vieja)
def flujo_casos():
    t0, H = 1_793_000_000_000 - 1_793_000_000_000 % 3_600_000, 3_600_000
    casos = []
    for forma, compra_spot in (("techo", 0.3), ("piso", 0.7), ("baja", 0.7), ("sube", 0.3), ("plano", 0.5)):
        perp, spot, p = [], [], 60000.0
        for k in range(26):
            paso = {"techo": 30 if k < 25 else 80, "piso": -30 if k < 25 else -80, "baja": -30, "sube": 30, "plano": 0}[forma]
            o, p = p, p + paso
            v = 100 + k
            tb = v * (0.7 if k < 12 else 0.35) if forma == "techo" else v * (0.3 if k < 12 else 0.65) if forma == "piso" else v * 0.5
            perp.append([t0 + k * H, o, max(o, p) + 5, min(o, p) - 5, p, v, round(tb, 3)])
            spot.append([t0 + k * H, o, max(o, p) + 5, min(o, p) - 5, p, v / 2, round(v / 2 * compra_spot, 3)])
        casos.append([perp, spot, t0 + 26 * H + 60_000])
    casos.append([casos[0][0], [], casos[0][2]])                      # sin spot
    casos.append([casos[0][0], casos[0][1], casos[0][2] + 2 * H])      # vieja
    return casos


FLUJO = flujo_casos()


def cme_casos():
    """Velas de 1 h con un hueco del CME armado: arriba abierto, abajo abierto, rellenado, chico, de verano y vencido."""
    import calendar
    HH = 3_600_000
    def serie(reapertura, hueco, despues, baja_a=None):
        r = calendar.timegm(reapertura) * 1000                    # apertura de la vela del domingo
        out = []
        for k in range(-120, despues + 1):
            t = r + k * HH
            p = 60000.0 if k <= -49 else 60000.0 * (1 + hueco * min(1.0, (k + 49) / 49)) if k <= 0 else 60000.0 * (1 + hueco)
            lo, hi = p * 0.999, p * 1.001
            if baja_a is not None and k == despues - 1:
                lo, hi = min(lo, baja_a), max(hi, baja_a)
            out.append([t, p, hi, lo, p, 10.0])
        return out, r + (despues + 1) * HH - 60_000
    inv, ver = (2026, 11, 8, 23, 0, 0), (2026, 6, 14, 22, 0, 0)
    return [serie(inv, 0.015, 20), serie(inv, -0.02, 30), serie(inv, 0.015, 20, 59990.0), serie(inv, 0.003, 20), serie(ver, 0.012, 40),
            serie(inv, 0.015, 24 * 7 + 5), serie((2026, 11, 8, 22, 0, 0), 0.015, 20)]


CME = [list(c) for c in cme_casos()]
# open interest inventado de dos exchanges (sube y baja) y la parte larga de las cuentas, para el mapa de liquidaciones
LIQ_OI = [[[b[0], round(8e9 + 4e8 * math.sin(i / 9) + 2e6 * i, 2)] for i, b in enumerate(H1[-400:])],
          [[b[0] + 60_000, round(3e9 + 2e8 * math.cos(i / 7), 2)] for i, b in enumerate(H1[-400:]) if i % 5]]
LIQ_LS = [[[b[0], round(0.5 + 0.12 * math.sin(i / 13), 4)] for i, b in enumerate(H1[-400:])]]
_HC = FC["ahora"] // 3_600_000 * 3_600_000 - 3_600_000
FC_FLUJO = [FC["filas"] + [{"tabla": "flujo", "t": _HC, "cvd_div": cd, "absorcion": ab, "cambio_24h": ch},
                           {"tabla": "ict", "tf": "1h", "tipo": "barrida", "sesgo": sb, "t": _HC, "bajo": 61234.5, "alto": 61234.5}]
            for cd, ab, ch, sb in (("alcista", "alcista", -1.8, "alcista"), ("bajista", "bajista", 2.1, "bajista"))]

# tasas de la Fed (factor medido_fed_plazos): la decision a 2 dias (suba esperada 99%), mercado dividido (baja esperada, peso 0,5) y a 10 dias (sin factor)
def _fila_fed(dias, esperada, prob, indeciso):
    fecha = datetime.fromtimestamp(FC["ahora"] / 1000 + dias * 86400, timezone.utc).strftime("%Y-%m-%d")
    return {"tabla": "contexto", "clave": "fed_tasas", "titulo": "Tasas de la Fed: lo que espera el mercado", "valor": "x", "senal": "neutral",
            "detalle": "x", "fecha": fecha, "dias": dias, "rango": [3.75, 4.0], "effr": 3.88, "esperada": esperada, "prob": prob,
            "indeciso": indeciso, "siguiente": None}


FC_FED = [FC["filas"] + [_fila_fed(2, 3.88 + 0.247, [[25, 0.986], [0, 0.014]], False)],
          FC["filas"] + [_fila_fed(2, 3.88 - 0.10, [[0, 0.6], [-25, 0.4]], True)],
          FC["filas"] + [_fila_fed(10, 3.88 + 0.247, [[25, 0.986], [0, 0.014]], False)]]


# perfil de volumen: filas reales del analisis central con el perfil de cada plazo cerca del precio (para que cambie el soporte y la resistencia)
_np = [r for r in FC["filas"] if r.get("tabla") == "plazo"]
FC_PERFIL = [{**r, "perfil": {"poc": round(FC["precio"] * (1 + 0.002 * (_np.index(r) + 1)), 1), "vah": round(FC["precio"] * (1 + 0.006 * (_np.index(r) + 1)), 1),
                              "val": round(FC["precio"] * (1 - 0.004 * (_np.index(r) + 1)), 1)}} if r.get("tabla") == "plazo" else r
             for r in FC["filas"]]
PERFIL_VELAS = {"h1": H1[-48:], "h4": H4[-48:], "d1": D1[-48:], "poca": H1[-4:], "sin_vol": [[*b[:5], 0.0] for b in H1[-48:]], "plano": [[b[0], 5, 5, 5, 5, 9.0] for b in H1[-48:]],
                "con_ceros": [b if k % 3 else [*b[:5], 0.0] for k, b in enumerate(H1[-48:])], "torcida": [[b[0], b[1], b[3], b[2], b[4], b[5]] if k == 7 else b for k, b in enumerate(H1[-48:])]}


# modelo estadistico de direccion: un modelo_direccion.json de prueba (H=1 con u10 chico: da sesgo; H=4 con u10 grande: casi
# moneda) y velas de 1 h con hora alineada, la vela en curso al precio actual y las de 5 min de esa hora; sin modelo, todo igual
_st = random.getstate(); random.seed(11)
VA = velas(1200, 3_600_000, 60000, 0.006, t0=1_700_000_000_000 - 1_700_000_000_000 % 3_600_000)
random.setstate(_st)
M_T0 = VA[-1][0] + 3_600_000
M_AHORA, M_PRECIO = M_T0 + 17 * 60_000, round(VA[-1][4] * 1.003, 2)
M_C5 = [[M_T0 + k * 300_000, VA[-1][4], VA[-1][4] * (1.004 if k == 2 else 1.001), VA[-1][4] * (0.9985 if k == 1 else 0.9995), VA[-1][4] * 1.002, 5.0] for k in range(4)]
M_FUERA = [[M_T0 - 300_000, 1, 1, 1, 1, 1]]                                   # una de 5 min de antes de la hora: no cuenta
_x0 = A.rasgos_direccion(VA)
_g = random.Random(5)
# H=1 pide los rasgos con el perfil de volumen (22) y H=4 los de siempre (20): la app los toma por nombre
def _modelo_h(nom, nrm, u10, vj):
    x = [_x0[A.RASGOS_APP.index(k)] for k in nom]
    return {"rasgos": list(nom), "media": [v * 0.9 for v in x], "escala": [abs(v) * 0.6 + 0.2 for v in x], "coef": [_g.gauss(0, 0.25) for _ in x],
            "intercepto": _g.gauss(0, 0.1), "normal": nrm, "u10": u10, "ventaja": vj, "ic90": [vj - 0.3, vj + 0.3], "n_ef": 5000.0}


MODELO = {"actualizado": 1, "H": {"1": _modelo_h(A.RASGOS_APP, 50.4, 0.001, 0.46), "4": _modelo_h(A.RASGOS_DIRECCION, 51.1, 0.45, -0.2)}}
MODELO["H"]["1"]["rasgos"] = MODELO["H"]["1"]["rasgos"][:5] + MODELO["H"]["1"]["rasgos"][5:][::-1]     # en otro orden: igual vale (por nombre)
for _k in ("media", "escala", "coef"):
    MODELO["H"]["1"][_k] = MODELO["H"]["1"][_k][:5] + MODELO["H"]["1"][_k][5:][::-1]
MODELO_MAL = {"H": {"1": {**MODELO["H"]["1"], "rasgos": MODELO["H"]["1"]["rasgos"][:-1] + ["rasgo_que_no_se_calcular"]},
                    "4": {**MODELO["H"]["4"], "escala": [0.0] + MODELO["H"]["4"]["escala"][1:]},
                    "2": {**MODELO["H"]["1"], "coef": MODELO["H"]["1"]["coef"][:-1]}, "3": {**MODELO["H"]["4"], "rasgos": ["ret_1"] * 20}, "x": 5}}
M_SIN_VOL = [b if k < len(VA) - 30 else [*b[:5], 0.0] for k, b in enumerate(VA)]   # sin volumen en las ultimas 30 velas: el perfil no se arma
M_PROB = {"tf": "5m", "horizonte": "1 hora", "velas": 12, "sube": 47.3, "baja": 52.7, "base": 49.1, "sube_crudo": 46.0, "veredicto": "Casi moneda", "sin_ventaja": False}
M_CASOS = [("5m", 12, True), ("30m", 8, True), ("5m", 3, True), ("1h", 4, True), ("30m", 8, False)]      # (tf, h, con velas)


def modelo_py():
    A.usar_modelo(MODELO)
    vs = A.velas_direccion(VA, M_C5 + M_FUERA, M_PRECIO, M_AHORA)
    out = {"rasgos": A.rasgos_direccion(VA), "velas": vs, "rasgos_vivo": A.rasgos_direccion(vs), "p": [A.prob_modelo(H, vs) for H in (1, 4, 2)],
           "corto": [A.prob_modelo(1, vs[-100:]), A.prob_modelo(1, None), A.rasgos_direccion(vs[-168:])],
           "falta": [A.velas_direccion(VA[:-1], M_C5, M_PRECIO, M_AHORA), A.velas_direccion([], M_C5, M_PRECIO, M_AHORA)],
           "filas": [A.aplicar_modelo(dict(M_PROB), tf, h, vs if con else None) for tf, h, con in M_CASOS],
           "validos": sorted(A.modelo_valido(MODELO_MAL)), "validos_ok": sorted(A.modelo_valido(MODELO)),
           "sin_perfil": [A.prob_modelo(1, M_SIN_VOL), A.prob_modelo(4, M_SIN_VOL)], "rasgos_sin_perfil": A.rasgos_direccion(M_SIN_VOL)[:20]}
    A.usar_modelo({})
    out["sin_modelo"] = [A.aplicar_modelo(dict(M_PROB), tf, h, vs) for tf, h, _ in M_CASOS] + [A.prob_modelo(1, vs)]
    return out


# rango del 80% recalibrado con lo medido en vivo: un track.json de prueba con "rangos" (factor_80 por (tf, h)); sin track, igual que antes
TRACK = {"rangos": [
    {"tf": "1h", "h": 4, "n_ef": 410.5, "factor_80": 1.2, "cobertura_factor": 80.1},
    {"tf": "1h", "h": 1, "n_ef": 120.0, "factor_80": 1.4},                           # n_ef < 150: no se aplica
    {"tf": "15m", "h": 4, "n_ef": 90.0, "pocos": True, "factor_80": 1.4},             # pocos: no se aplica
    {"tf": "4h", "h": 3, "n_ef": 200.0, "factor_80": 2.6},                            # recortado a 2,0
    {"tf": "5m", "h": 12, "n_ef": 300.0, "factor_80": 0.5},                           # recortado a 0,8
    {"tf": "30m", "h": 2, "n_ef": 300.0, "factor_80": None},                          # sin factor
    {"tf": "1d", "h": 1, "n_ef": 150.0, "factor_80": 1.035},                          # justo 150: se aplica
    {"tf": "1d", "h": 3, "n_ef": 500.0}]}                                             # sin la clave
RANGO_O = {"p10": -0.8, "p50": 0.1, "p90": 1.1}
RANGO_CASOS = [(tf, h) for tf, h in (("1h", 4), ("1h", 1), ("15m", 4), ("4h", 3), ("5m", 12), ("30m", 2), ("1d", 1), ("1d", 3), ("2h", 2))]


def rango_vivo_py():
    fv = A.factores_vivos(TRACK)
    out = {"factores": sorted([tf, h, f] for (tf, h), f in fv.items()), "vacio": sorted(A.factores_vivos({}).items()) + sorted(A.factores_vivos(None).items()),
           "con": [A.rango_80(tf, h, RANGO_O, 1.07, 77860.5, fv) for tf, h in RANGO_CASOS],
           "sin": [A.rango_80(tf, h, RANGO_O, 1.07, 77860.5, {}) for tf, h in RANGO_CASOS],
           "sin_track": [A.rango_80(tf, h, RANGO_O, 1.07, 77860.5) for tf, h in RANGO_CASOS]}
    A.usar_track(TRACK)
    out["global"] = [A.rango_80(tf, h, RANGO_O, 1.07, 77860.5) for tf, h in RANGO_CASOS]
    A.usar_track({})
    return out


def rango_py():
    """Calibracion del rango del 80% (rango_puntajes / rango_factor) con la volatilidad prevista (vol_escala)."""
    c = [b[4] for b in H1]
    e50, e200, rsi, (ml, ms, mh) = ind.ema(c, 50), ind.ema(c, 200), ind.rsi(c), ind.macd(c)
    st = apr.estados(apr.rasgos(H1, 60, e50, e200, rsi, mh), 2)
    F = A.vol_escala(H1, 60, 4, False)
    pts = A.rango_puntajes(c, st, F, 4, 200, len(c) - 1 - 4)
    return {"F": F[-50:], "puntajes": pts, "factor": A.rango_factor(pts), "sin_vol": A.rango_factor(A.rango_puntajes(c, st, None, 6, 200, len(c) - 7, ventana=900))}


def central_modelo(d):
    """Las filas del analisis central con la probabilidad de cada plazo venida del modelo (sube = normal + d)."""
    return [{**r, "fuente_sube": "modelo", "sube": r["base"] + d, "veredicto": "Sesgo alcista" if d > 0 else "Sesgo bajista"}
            if r.get("tabla") == "plazo" and r.get("base") is not None else r for r in FC["filas"]]


def py():
    piv = ind.zigzag(H4)
    raw = {"oi": [[b[0] + 3_600_000, 1000 + i] for i, b in enumerate(H1[-40:])], "ls": [1.2 + i / 100 for i in range(25)],
           "taker": [{"buy": 120 + i, "sell": 100} for i in range(4)], "top": 1.3, "funding": 0.0001, "funding7": -0.00002, "fundingFuente": "BingX"}
    return {
        "calificar": ind.calificar(H1)[:2], "zigzag": piv, "elliott": ind.elliott(piv, H4), "elliott_1h": ind.elliott(ind.zigzag(H1), H1), "fvg": ind.fvg(H4), "divergencias": ind.divergencias(H4, piv),
        "fibonacci": A.fibonacci(H4), "fib_tramo": A.fib_tramo(H4), "compresion": A.compresion(H1), "central": A.central(FC["filas"], FC["precio"], {"1h": H1, "4h": H4}, FC["ahora"]), "horas": A.perfil_horas(H1),
        "termometro": termometro.termometro([b[4] for b in D1], D1[-1][4] * 1.01, now_ms=AHORA, f7=-0.00001),
        "termometro_alt": termometro.termometro_alt("XRP", ALT[-600:], ALT[-1][4], now_ms=AHORA),
        "semanal": A.analisis_largo(D1, "1w", D1[-1][4], True),
        "mensual": A.analisis_largo(D1, "1M", D1[-1][4]),
        "velas_semana_cerrada": A.velas_largas(D1[:-3], "1w"),
        "piso": termometro.piso("BTC", [b[4] for b in D1], D1[-1][4] * 1.01, now_ms=AHORA),
        "piso_alt": termometro.piso("SOL", [b[4] for b in ALT], ALT[-1][4], now_ms=AHORA + 37 * 86_400_000),
        "piso_prob": [termometro.piso_prob(termometro._datos()["piso"], m, x, v) for m, x, v in (("BTC", -0.2, 0.3), ("ZEC", -0.7, 0.9), ("XRP", 0.1, 0.4), ("NADA", -0.3, 0.5))],
        "fuerte": fuerte.prever(H1),
        "liq_reales": A.liq_reales([tuple(x) for x in LIQ], AHORA),
        "aprender": {k: v for k, v in apr.aprender(H1, *entrada_apr(H1)[:1], 4, 200, entrada_apr(H1)[1]).items()
                     if k not in ("_estado", "pesos")},
        "explain": {k: A.explain(v, 77860.0, tuple(SPEC_1H)) for k, v in CASOS.items()},
        "registro": registro_py(),
        "rango": rango_py(),
        "rango_vivo": rango_vivo_py(),
        "opciones": A.opciones(OPC_LIBRO, OPC_DVOL, 61234.5, OPC_AHORA),
        "dvol_dia": dvol_dia_py(),
        "ict_h1": ind.ict(H1, ind.atr_w([b[2] for b in H1], [b[3] for b in H1], [b[4] for b in H1]), 60),
        "ict_h4": ind.ict(H4, ind.atr_w([b[2] for b in H4], [b[3] for b in H4], [b[4] for b in H4]), 240),
        "ict_filas": A.ict_filas("1h", H1, 60),
        "flujo": [ind.flujo_senales(*c) for c in FLUJO],
        "cme": [ind.hueco_cme(*c) for c in CME],
        "liq_perfil": ind.liq_perfil([b[:5] for b in H1[-400:]], LIQ_OI, LIQ_LS, 3_600_000, 5 * 86_400_000, H1[-1][4],
                                     escala=ind.liq_escala(LIQ_OI, {"bitget": 1.2e9, "hyperliquid": 2.6e9, "mexc": 0, "x": None})),
        "central_flujo": [A.central(f, FC["precio"], {"1h": H1, "4h": H4}, FC["ahora"]) for f in FC_FLUJO],
        "central_fed": [A.central(f, FC["precio"], {"1h": H1, "4h": H4}, FC["ahora"]) for f in FC_FED],
        "central_modelo": [A.central(central_modelo(d), FC["precio"], {"1h": H1, "4h": H4}, FC["ahora"]) for d in (20, -20)],
        "modelo": modelo_py(),
        "perfil": {k: ind.perfil_volumen(v) for k, v in PERFIL_VELAS.items()} | {"n24": ind.perfil_volumen(H1[-24:], 24), "plazo": [A.perfil_plazo(H1), A.perfil_plazo(H4), A.perfil_plazo(D1[:3])]},
        "central_perfil": A.central(FC_PERFIL, FC["precio"], {"1h": H1, "4h": H4}, FC["ahora"]),
        "base_perp": [A.base_perp(61300, 61234.5, "Bybit"), A.base_perp(61190, 61234.5, "Bybit"), A.base_perp(61240, 61234.5, "Bybit")],
        "_ctx_raw": raw,
    }


JS = r"""
const R = process.argv[1];
globalThis.Ind = require(R + '/JavascriptVersion/indicadores.js'); globalThis.Aprendizaje = require(R + '/JavascriptVersion/aprendizaje.js'); const Apr = globalThis.Aprendizaje;
const Fu = require(R + '/JavascriptVersion/fuerte.js'); const A = require(R + '/JavascriptVersion/analisis.js');
const T = require(R + '/JavascriptVersion/termometro.json'), M = require(R + '/JavascriptVersion/modelo_fuerte.json');
const d = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const piv = Ind.zigzag(d.H4), c = Ind.calificar(d.H1);
console.log(JSON.stringify({
  calificar: [c[0], c[1]], zigzag: piv, elliott: Ind.elliott(piv, d.H4), elliott_1h: Ind.elliott(Ind.zigzag(d.H1), d.H1), fvg: Ind.fvg(d.H4), divergencias: Ind.divergencias(d.H4, piv), fibonacci: A.fibonacci(d.H4), fib_tramo: A.fibTramo(d.H4), compresion: A.compresion(d.H1), central: A.central(d.FC.filas, d.FC.precio, { "1h": d.H1, "4h": d.H4 }, d.FC.ahora), horas: A.perfilHoras(d.H1),
  termometro: A.termometro(d.D1.map((b) => b[4]), d.D1[d.D1.length - 1][4] * 1.01, T, null, d.AHORA, -0.00001),
  termometro_alt: A.termometroAlt('XRP', d.ALT.slice(-600), d.ALT[d.ALT.length - 1][4], T, d.AHORA),
  semanal: A.analisisLargo(d.D1, '1w', d.D1[d.D1.length - 1][4], true),
  mensual: A.analisisLargo(d.D1, '1M', d.D1[d.D1.length - 1][4]),
  velas_semana_cerrada: A.velasLargas(d.D1.slice(0, -3), '1w'),
  piso: A.piso('BTC', d.D1.map((b) => b[4]), d.D1[d.D1.length - 1][4] * 1.01, T, d.AHORA),
  piso_alt: A.piso('SOL', d.ALT.map((b) => b[4]), d.ALT[d.ALT.length - 1][4], T, d.AHORA + 37 * 86400000),
  piso_prob: [['BTC', -0.2, 0.3], ['ZEC', -0.7, 0.9], ['XRP', 0.1, 0.4], ['NADA', -0.3, 0.5]].map(([m, x, v]) => A.pisoProb(T.piso, m, x, v)),
  fuerte: Fu.prever(M, d.H1), contexto: A.context(d.raw, d.H1), liq_reales: A.liqReales(d.LIQ, d.AHORA),
  explain: Object.fromEntries(Object.entries(d.CASOS).map(([k, v]) => [k, A.explain(v, 77860.0, d.SPEC_1H)])),
  registro: (() => { const cl = {}; Object.entries(d.LOG_CIERRES).forEach(([tf, xs]) => { cl[tf] = new Map(xs); });
    const sc = A.logAndScore([[1000, '1h', 4, 100.0, 60.0]], d.LOG_ENTRADAS, cl);
    return Object.fromEntries([...sc.entries()].sort()); })(),
  opciones: A.opciones(d.OPC_LIBRO, d.OPC_DVOL, 61234.5, d.OPC_AHORA),
  dvol_dia: d.DVOL_DIA.map(([lo, hi, p, dv, t]) => { const v = A.dvolVigente(dv, t); return [v, A.mezclaDvolDia(lo, hi, p, v)]; }),
  ict_h1: Ind.ict(d.H1, Ind.atrW(d.H1.map((b) => b[2]), d.H1.map((b) => b[3]), d.H1.map((b) => b[4])), 60),
  ict_h4: Ind.ict(d.H4, Ind.atrW(d.H4.map((b) => b[2]), d.H4.map((b) => b[3]), d.H4.map((b) => b[4])), 240),
  ict_filas: A.ictFilas('1h', d.H1, 60),
  flujo: d.FLUJO.map((c) => Ind.flujoSenales(...c)),
  cme: d.CME.map((c) => Ind.huecoCme(...c)),
  liq_perfil: Ind.liqPerfil(d.H1.slice(-400).map((b) => b.slice(0, 5)), d.LIQ_OI, d.LIQ_LS, 3600000, 5 * 86400000, d.H1[d.H1.length - 1][4], 0.12, 0.0025, Ind.LIQ_NIVELES, Ind.LIQ_MANT,
    Ind.liqEscala(d.LIQ_OI, { bitget: 1.2e9, hyperliquid: 2.6e9, mexc: 0, x: null })),
  central_flujo: d.FC_FLUJO.map((f) => A.central(f, d.FC.precio, { "1h": d.H1, "4h": d.H4 }, d.FC.ahora)),
  central_fed: d.FC_FED.map((f) => A.central(f, d.FC.precio, { "1h": d.H1, "4h": d.H4 }, d.FC.ahora)),
  central_modelo: [20, -20].map((x) => A.central(d.FC.filas.map((r) => (r.tabla === 'plazo' && r.base !== null && r.base !== undefined ? { ...r, fuente_sube: 'modelo', sube: r.base + x, veredicto: x > 0 ? 'Sesgo alcista' : 'Sesgo bajista' } : r)), d.FC.precio, { "1h": d.H1, "4h": d.H4 }, d.FC.ahora)),
  modelo: (() => { globalThis.MODELO_DIRECCION = d.MODELO;
    const vs = A.velasDireccion(d.VA, d.M_C5.concat(d.M_FUERA), d.M_PRECIO, d.M_AHORA);
    const out = { rasgos: A.rasgosDireccion(d.VA), velas: vs, rasgos_vivo: A.rasgosDireccion(vs), p: [1, 4, 2].map((H) => A.probModelo(H, vs)),
      corto: [A.probModelo(1, vs.slice(-100)), A.probModelo(1, null), A.rasgosDireccion(vs.slice(-168))],
      falta: [A.velasDireccion(d.VA.slice(0, -1), d.M_C5, d.M_PRECIO, d.M_AHORA), A.velasDireccion([], d.M_C5, d.M_PRECIO, d.M_AHORA)],
      filas: d.M_CASOS.map(([tf, h, con]) => A.aplicarModelo({ ...d.M_PROB }, tf, h, con ? vs : null)),
      validos: Object.keys(A.modeloValido(d.MODELO_MAL)).map(Number).sort((a, b) => a - b), validos_ok: Object.keys(A.modeloValido(d.MODELO)).map(Number).sort((a, b) => a - b),
      sin_perfil: [1, 4].map((H) => A.probModelo(H, d.M_SIN_VOL)), rasgos_sin_perfil: A.rasgosDireccion(d.M_SIN_VOL).slice(0, 20) };
    globalThis.MODELO_DIRECCION = {};
    out.sin_modelo = d.M_CASOS.map(([tf, h]) => A.aplicarModelo({ ...d.M_PROB }, tf, h, vs)).concat([A.probModelo(1, vs)]);
    delete globalThis.MODELO_DIRECCION; return out; })(),
  perfil: Object.assign(Object.fromEntries(Object.entries(d.PERFIL_VELAS).map(([k, v]) => [k, Ind.perfilVolumen(v)])), { n24: Ind.perfilVolumen(d.H1.slice(-24), 24), plazo: [A.perfilPlazo(d.H1), A.perfilPlazo(d.H4), A.perfilPlazo(d.D1.slice(0, 3))] }),
  central_perfil: A.central(d.FC_PERFIL, d.FC.precio, { "1h": d.H1, "4h": d.H4 }, d.FC.ahora),
  base_perp: [A.basePerp(61300, 61234.5, 'Bybit'), A.basePerp(61190, 61234.5, 'Bybit'), A.basePerp(61240, 61234.5, 'Bybit')],
  rango: (() => { const c = d.H1.map((b) => b[4]), e50 = Ind.ema(c, 50), e200 = Ind.ema(c, 200), rsi = Ind.rsi(c), mh = Ind.macd(c)[2];
    const st = Apr.estados(Apr.rasgos(d.H1, 60, e50, e200, rsi, mh), 2), F = A.volEscala(d.H1, 60, 4, false);
    const pts = A.rangoPuntajes(c, st, F, 4, 200, c.length - 1 - 4);
    return { F: F.slice(-50), puntajes: pts, factor: A.rangoFactor(pts), sin_vol: A.rangoFactor(A.rangoPuntajes(c, st, null, 6, 200, c.length - 7, 200, 900)) }; })(),
  rango_vivo: (() => { const fv = A.factoresVivos(d.TRACK), O = d.RANGO_O, f = (fx) => d.RANGO_CASOS.map(([tf, h]) => A.rango80(tf, h, O, 1.07, 77860.5, fx));
    const out = { factores: Object.entries(fv).map(([k, v]) => { const [tf, h] = k.split('|'); return [tf, Number(h), v]; }).sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] - b[1])),
      vacio: [], con: f(fv), sin: f({}), sin_track: f(undefined) };
    globalThis.TRACK = d.TRACK; out.global = f(undefined); delete globalThis.TRACK; return out; })(),
  aprender: (() => { const c = d.H1.map((b) => b[4]), e50 = Ind.ema(c, 50), e200 = Ind.ema(c, 200), rsi = Ind.rsi(c), mh = Ind.macd(c)[2];
    const r = Apr.aprender(d.H1, Apr.combos(Apr.rasgos(d.H1, 60, e50, e200, rsi, mh)), 4, 200, Apr.continuos(d.H1, 60, e50, e200, rsi, mh));
    delete r._estado; delete r.pesos; return r; })(),
}));
"""


def igual(a, b, ruta, err):
    if isinstance(a, tuple):
        a = list(a)
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None or not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or abs(a - b) > 1e-6 * max(1, abs(a)):
            err.append(f"{ruta}: {a!r} != {b!r}")
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            igual(a.get(k), b.get(k), f"{ruta}.{k}", err)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            err.append(f"{ruta}: largo {len(a)} != {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            igual(x, y, f"{ruta}[{i}]", err)
    elif a != b:
        err.append(f"{ruta}: {a!r} != {b!r}")


def main():
    p = py()
    raw = p.pop("_ctx_raw")
    entrada = {"FC": FC, "H1": H1, "H4": H4, "D1": D1, "ALT": ALT, "AHORA": AHORA, "raw": raw, "LIQ": LIQ,
               "CASOS": CASOS, "SPEC_1H": SPEC_1H, "LOG_ENTRADAS": LOG_ENTRADAS, "LOG_CIERRES": LOG_CIERRES,
               "OPC_LIBRO": OPC_LIBRO, "OPC_DVOL": OPC_DVOL, "OPC_AHORA": OPC_AHORA, "DVOL_DIA": DVOL_DIA, "FLUJO": FLUJO, "CME": CME, "FC_FLUJO": FC_FLUJO, "FC_FED": FC_FED, "LIQ_OI": LIQ_OI, "LIQ_LS": LIQ_LS,
               "TRACK": TRACK, "RANGO_O": RANGO_O, "RANGO_CASOS": RANGO_CASOS,
               "VA": VA, "M_C5": M_C5, "M_FUERA": M_FUERA, "M_PRECIO": M_PRECIO, "M_AHORA": M_AHORA, "MODELO": MODELO, "MODELO_MAL": MODELO_MAL, "M_SIN_VOL": M_SIN_VOL, "FC_PERFIL": FC_PERFIL, "PERFIL_VELAS": PERFIL_VELAS, "M_PROB": M_PROB, "M_CASOS": M_CASOS}
    out = subprocess.run(["node", "-e", JS, RAIZ], input=json.dumps(entrada), capture_output=True, text=True)
    if out.returncode:
        raise SystemExit("node fallo:\n" + out.stderr[-2000:])
    js = json.loads(out.stdout)
    js_ctx = js.pop("contexto")
    err = []
    for k in p:
        igual(json.loads(json.dumps(p[k])), js.get(k), k, err)
    rv = p["rango_vivo"]
    aplicados = [(c["ajuste_vivo"]) for c in rv["con"]]
    if aplicados != [1.2, None, None, 2.0, 0.8, None, 1.035, None, None] or any(c["ajuste_vivo"] is not None for c in rv["sin"] + rv["sin_track"]) \
            or rv["sin"] != rv["sin_track"] or [c["min"] for c in rv["sin"]] != [c["min_crudo"] for c in rv["con"]] or rv["global"] != rv["con"] \
            or not all(c["min"] < c["min_crudo"] and c["max"] > c["max_crudo"] for c in (rv["con"][0], rv["con"][3], rv["con"][6])) \
            or not (rv["con"][4]["min"] > rv["con"][4]["min_crudo"] and rv["con"][4]["max"] < rv["con"][4]["max_crudo"]):
        raise SystemExit(f"rango_vivo: el ajuste no se aplica como se espera: {aplicados}")
    dd = p["dvol_dia"]
    if dd[0][0] is None or not (59000.5 < dd[0][1][0] < 61234.5 < dd[0][1][1] < 63000.5) or dd[1] != [None, [59000.5, 63000.5]] \
            or dd[2] != [None, [59000.5, 63000.5]] or dd[3][1] != [None, None] or dd[4][1] == [0.4123, 0.4377]:
        raise SystemExit(f"dvol_dia: la mezcla con el DVOL no se comporta como se espera: {dd}")
    mo = p["modelo"]
    f, f4 = mo["filas"][0], mo["filas"][1]
    if mo["validos"] != [] or mo["validos_ok"] != [1, 4] or mo["p"][2] is not None or mo["p"][0] is None or any(x is not None for x in mo["corto"]) \
            or any(x is not None for x in mo["falta"]) or f["fuente_sube"] != "modelo" or f["sube_casos"] != 47.3 or f["sube"] != round(mo["p"][0] * 100, 1) \
            or f["base"] != 50.4 or f["veredicto"] not in ("Sesgo alcista", "Sesgo bajista") or f4["veredicto"] != "Casi moneda" \
            or "fuente_sube" in mo["filas"][2] or "fuente_sube" in mo["filas"][3] or "fuente_sube" in mo["filas"][4] \
            or mo["sin_modelo"] != [M_PROB] * 5 + [None] or mo["velas"][-1][4] != M_PRECIO or mo["velas"][-1][2] <= M_PRECIO:
        raise SystemExit(f"modelo: no se comporta como se espera: {mo['filas'][:2]} {mo['p']} {mo['validos']} {mo['validos_ok']}")
    for caso, esperado in zip(p["central_fed"], ({"1d": (-1, 1), "1w": (-1, 1)}, {"1d": (1, 0.5), "1w": (1, 0.5)}, {})):
        for c in caso:
            fs = [f for f in c["factores"] if f[3].startswith("Fed el ")]
            if c["tf"] in esperado and [(f[1], f[2]) for f in fs] != [esperado[c["tf"]]] or c["tf"] not in esperado and fs:
                raise SystemExit(f"central_fed: factor de la Fed no esperado en {c['tf']}: {fs}")
    if not any(f[3].startswith("Fed el ") and "mercado dividido" in f[3] for c in p["central_fed"][1] for f in c["factores"]):
        raise SystemExit("central_fed: falta el texto del mercado dividido")
    pf, cp, c0 = p["perfil"], p["central_perfil"], p["central"]
    if pf["h1"] is None or not pf["h1"]["val"] < pf["h1"]["poc"] < pf["h1"]["vah"] or pf["poca"] is not None or pf["sin_vol"] is not None or pf["plano"] is not None \
            or pf["torcida"] is None or pf["con_ceros"] is None or p["perfil"]["plazo"][2] is not None or p["perfil"]["plazo"][0]["poc"] != round(pf["h1"]["poc"], 1):
        raise SystemExit(f"perfil: no se comporta como se espera: {pf}")
    if all((a["soporte"], a["resistencia"]) == (b["soporte"], b["resistencia"]) for a, b in zip(cp, c0)):
        raise SystemExit("niveles: el perfil de cada plazo no cambio ningun soporte ni resistencia (la prueba no tiene poder)")
    ex = p["explain"]
    if "(POC del perfil)" not in json.dumps(ex["perfil"], ensure_ascii=False) or "(borde del perfil (VAH))" not in json.dumps(ex["perfil"], ensure_ascii=False) \
            or json.dumps(ex["perfil"]) == json.dumps(ex["False_70.0"]):
        raise SystemExit("explain: el perfil del plazo no entra como soporte o resistencia")
    if mo["sin_perfil"][0] is not None or mo["sin_perfil"][1] is None:
        raise SystemExit(f"modelo: sin perfil el modelo con perfil debe quedar sin prob y el otro no: {mo['sin_perfil']}")
    print(f"comparados: {', '.join(p)} · contexto ({len(js_ctx[0])} filas en JS)")
    if err:
        print(f"{len(err)} diferencias:\n  " + "\n  ".join(err[:40]))
        raise SystemExit(1)
    print("Python y JavaScript dan lo mismo.")


if __name__ == "__main__":
    main()
