"""¿El rango del 80% de 1 dia, 1 semana y 1 mes mejoraria con la volatilidad implicita de las opciones (DVOL, Deribit)? (medir antes de sumar)

Para cada dia del pasado arma, solo con lo que se sabia ese dia:
  app         el rango del 80% como lo da la app hoy (casos parecidos: percentiles 10 y 90 de lo que paso despues de
              situaciones parecidas; ver rango_app abajo para lo que se replica y lo que no)
  dvol        precio * exp(±1,2816 * sigma), sigma = DVOL/100 * raiz(dias/365)   (log-normal, centrado en el precio)
  dvol_mart   igual pero con la mediana en -sigma²/2 (la media del precio queda en el precio de hoy)
  dvol_cal    dvol con la sigma multiplicada por un factor k ajustado SOLO con el tramo 1 (cobertura 80%)
  mezcla      media geometrica de los rangos (app, dvol): el ancho en log es el promedio de los dos
  mezcla_cal  media geometrica de (app, dvol_cal)
y compara por plazo y por tramo (1: 2021-03..2023-12, 2: 2024-01..hoy): cobertura (objetivo 80%), ancho promedio (%) y
puntaje de intervalo (Winkler, 80%: ancho + (2/0,2) * lo que se paso, en % del precio; menor es mejor).
Para el z y el n se usa un caso cada "plazo" (sin pisarse). Un metodo GANA contra la app si el puntaje es mejor en los
DOS tramos con cobertura entre 77% y 83% en los dos, o si la diferencia pareada del puntaje tiene z >= 2 en los dos.

Datos publicos: data.binance.vision (velas de futuros 4 h y diarias spot) y Deribit (DVOL por hora desde 2021-03).
Uso: python medir_rangos_dvol.py            (baja todo a datos_medicion/rangos_dvol, se reusa)
     python medir_rangos_dvol.py --prueba   (datos sinteticos, sin internet: solo prueba que el codigo corre de punta a punta)
"""
import bisect, math, os, sys, time
from datetime import date, datetime, timedelta, timezone

import numpy as np

import indicadores as ind
import aprendizaje as apr

PRUEBA = "--prueba" in sys.argv
CARPETA = "datos_medicion/rangos_dvol"
H1, D1MS, H4 = 3_600_000, 86_400_000, 14_400_000
Z80 = 1.2815515655                       # percentil 90 de la normal: el 80% central
ALFA = 0.2
CORTE = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)          # tramo 1 / tramo 2
DVOL_DESDE = int(datetime(2021, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
# plazo: (nombre, velas de la app, minutos por vela, h velas, ventana de historia en velas, dias del plazo)
# igual que analisis_btc.PLAZOS y TIMEFRAMES: "1 dia" = 4 h x 6 (730 dias de historia), "1 semana" = diarias x 7 y
# "1 mes" = diarias x 30 (1500 dias de historia)
PLAZOS = (("1 día", "4h", 240, 6, 4380, 1), ("1 semana", "1d", 1440, 7, 1500, 7), ("1 mes", "1d", 1440, 30, 1500, 30))
METODOS = ("app", "dvol", "dvol_mart", "dvol_cal", "mezcla", "mezcla_cal")
COHERENCIA = True        # como la app: el rango de un plazo mas largo nunca es mas angosto que el del anterior


# ---------- datos ----------
def datos_reales():
    import medir_contexto as mc
    import medir_largos as ml
    os.makedirs(CARPETA, exist_ok=True)
    mc.CACHE = CARPETA
    hoy = date.today()
    mc.HASTA = date(hoy.year + (hoy.month == 12), hoy.month % 12 + 1, 1)          # hasta el mes que viene: trae lo de hoy
    mc.DESDE = date(2021, 3, 1)
    dv = mc.dvol()
    mc.DESDE = date(2019, 10, 1)                                                   # velas de 4 h: 730 dias antes de 2021-03
    b4 = mc.velas("4h")
    d1 = ml.diarias()
    return d1, b4, dv, precio_hoy(d1)


def precio_hoy(d1):
    import json, urllib.request
    for u, f in (("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", lambda r: float(r["price"])),
                 ("https://www.deribit.com/api/v2/public/get_index_price?index_name=btc_usd", lambda r: float(r["result"]["index_price"]))):
        try:
            return f(json.loads(urllib.request.urlopen(u, timeout=20).read()))
        except Exception:
            pass
    return d1[-1][4]


def datos_sinteticos():
    """BTC de mentira: volatilidad que cambia lenta (AR(1) en log), colas pesadas, DVOL = vol real * 1,15 con ruido."""
    rng = np.random.default_rng(7)
    t0 = int(datetime(2019, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)
    hoy = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    dias = (hoy - t0) // D1MS
    lv, sig = math.log(0.03), []
    for _ in range(dias):
        lv = math.log(0.03) + 0.97 * (lv - math.log(0.03)) + 0.12 * rng.standard_normal()
        sig.append(math.exp(lv))
    b4, p = [], 8000.0
    for d in range(dias):
        for k in range(6):
            r = sig[d] / math.sqrt(6) * rng.standard_t(5) / math.sqrt(5 / 3) + 0.0003 / 6
            o, c = p, p * math.exp(r)
            hi, lo = max(o, c) * (1 + abs(rng.normal()) * sig[d] / 6), min(o, c) * (1 - abs(rng.normal()) * sig[d] / 6)
            b4.append([t0 + d * D1MS + k * H4, o, hi, lo, c, 100.0])
            p = c
    d1 = []
    for d in range(dias):
        g = b4[d * 6:d * 6 + 6]
        d1.append([t0 + d * D1MS, g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[-1][4], 600.0])
    dv, a = [], max(DVOL_DESDE + 23 * D1MS, t0)
    while a < hoy:
        s = sig[int((a - t0) // D1MS)]
        dv.append([a + H1, s * math.sqrt(365) * 100 * 1.15 * math.exp(0.1 * rng.standard_normal())])
        a += H1
    return d1, b4, dv, d1[-1][4]


# ---------- el rango de la app, repetido dia por dia ----------
def rango_app(bars, tf_min, h, W, js):
    """{j: (min, max)} del rango del 80% que daba la app al cerrar la vela j, usando solo velas hasta j.
    Replica analisis_btc.horizon_stats + rango_80 para estas temporalidades (4 h y diaria):
      - casos parecidos: los de aprendizaje.estados (receta 0) con 4, 3, 2 y 1 rasgos hasta juntar MIN_SAMPLES
        (misma busqueda que analisis_btc.rango_puntajes, el repaso honesto de la propia app), solo de las ultimas W velas
        y solo con resultado ya conocido (vela i <= j - h);
      - movimiento de cada caso = cierre(i+h)/cierre(i) - 1 sin escalar por volatilidad (vol_factor da None con velas > 1 h);
      - min/max = p10/p90 con el factor k = 1 (analisis_btc.calibracion fija k = 1 con velas > 1 h) y sin ajuste vivo.
    Diferencias: la app usa la receta que aprendio (apr.aprendido) y aca es la 0; la app suma el ajuste con lo medido en
    vivo (FACTORES_VIVOS: no hay historia para repetirlo); la app corta los casos en `last` (j_max) y aca en j - h."""
    import analisis_btc as A
    c = [b[4] for b in bars]
    e50, e200, rsi, (_, _, mh) = ind.ema(c, 50), ind.ema(c, 200), ind.rsi(c), ind.macd(c)
    st = apr.estados(apr.rasgos(bars, tf_min, e50, e200, rsi, mh), 0)
    warmup = min(200, len(bars) // 3)
    grupos = A.rango_grupos(st, warmup, len(bars) - 1)
    out = {}
    for j in js:
        e = st[j] if j >= warmup else None
        if not e:
            continue
        desde = max(warmup, j - W)
        for keep in (4, 3, 2, 1):                       # como similar(): la situacion mas completa con casos suficientes
            lst = grupos.get((keep, tuple(e[:keep])), [])
            a, b = bisect.bisect_left(lst, desde), bisect.bisect_right(lst, j - h)
            if b - a >= A.MIN_SAMPLES:
                break
        if b - a < 10:
            continue
        rets = sorted(c[i + h] / c[i] - 1 for i in lst[a:b])
        q = lambda p: rets[min(int(p * len(rets)), len(rets) - 1)]
        out[j] = (c[j] * (1 + q(0.1)), c[j] * (1 + q(0.9)))
    return out


# ---------- rangos con el DVOL ----------
def rango_dvol(precio, dvol, dias, k=1.0, mart=False):
    s = dvol / 100 * math.sqrt(dias / 365) * k
    m = -s * s / 2 if mart else 0.0
    return precio * math.exp(m - Z80 * s), precio * math.exp(m + Z80 * s)


def mezclar(a, b):
    return math.sqrt(a[0] * b[0]), math.sqrt(a[1] * b[1])


def dvol_en(tdv, vdv, t):
    k = bisect.bisect_right(tdv, t) - 1
    return vdv[k] if k >= 0 and t - tdv[k] <= 6 * H1 else None


def armar(d1, b4, dv):
    """Por plazo: lista de casos {t, P, y, app, dvol} con un caso por dia (a las 00:00 UTC), con resultado conocido."""
    tdv, vdv = [x[0] for x in dv], [x[1] for x in dv]
    out, hoy = {}, {}
    for nombre, tf, tf_min, h, W, dias in PLAZOS:
        bars = b4 if tf == "4h" else d1
        paso = tf_min * 60_000
        js = [j for j, b in enumerate(bars) if (b[0] + paso) % D1MS == 0 and (b[0] + paso) >= tdv[0] and j + h < len(bars)]
        ra = rango_app(bars, tf_min, h, W, js + [len(bars) - 1])
        casos = []
        for j in js:
            t, d = bars[j][0] + paso, dvol_en(tdv, vdv, bars[j][0] + paso)
            if j in ra and d is not None:
                casos.append({"t": t, "P": bars[j][4], "y": bars[j + h][4], "app": ra[j], "dvol": d})
        out[nombre] = casos
        hoy[nombre] = (bars[-1][0] + paso, bars[-1][4], ra.get(len(bars) - 1))
        print(f"  {nombre}: {len(casos)} dias con rango de la app y DVOL", flush=True)
    if COHERENCIA:                                           # el rango de un plazo largo no es mas angosto que el del anterior
        ant = None
        for nombre, *_ in PLAZOS:
            por_t = {c["t"]: c for c in out[nombre]}
            if ant is not None:
                for t, c in por_t.items():
                    if t in ant:
                        c["app"] = (min(c["app"][0], ant[t][0]), max(c["app"][1], ant[t][1]))
            ant = {t: c["app"] for t, c in por_t.items()}
    return out, hoy


# ---------- medir ----------
def factor_k(casos, dias):
    """Factor de sigma que deja adentro al 80% en el tramo 1 (con todos los dias: es solo un numero)."""
    xs = [abs(math.log(c["y"] / c["P"])) / (Z80 * c["dvol"] / 100 * math.sqrt(dias / 365)) for c in casos if c["t"] < CORTE]
    return float(np.quantile(xs, 0.8)) if len(xs) >= 20 else 1.0


def rangos_de(c, dias, k):
    a, d = c["app"], rango_dvol(c["P"], c["dvol"], dias)
    dc = rango_dvol(c["P"], c["dvol"], dias, k)
    return {"app": a, "dvol": d, "dvol_mart": rango_dvol(c["P"], c["dvol"], dias, mart=True), "dvol_cal": dc,
            "mezcla": mezclar(a, d), "mezcla_cal": mezclar(a, dc)}


def puntaje(r, c):
    lo, hi = r
    return ((hi - lo) + (2 / ALFA) * (max(lo - c["y"], 0) + max(c["y"] - hi, 0))) / c["P"] * 100


def sin_pisar(casos, dias):
    out, ult = [], None
    for c in sorted(casos, key=lambda c: c["t"]):
        if ult is None or c["t"] >= ult + dias * D1MS:
            out.append(c)
            ult = c["t"]
    return out


def medir(casos, dias, k):
    """{tramo: {metodo: dict}} con cobertura, ancho y puntaje (un caso cada plazo) y la cobertura con todos los dias."""
    res = {}
    for tramo, f in ((1, lambda c: c["t"] < CORTE), (2, lambda c: c["t"] >= CORTE)):
        todos = [c for c in casos if f(c)]
        base = sin_pisar(todos, dias)
        res[tramo] = {"n": len(base), "n_todos": len(todos), "m": {}}
        for m in METODOS:
            R = [rangos_de(c, dias, k)[m] for c in base]
            Rt = [rangos_de(c, dias, k)[m] for c in todos]
            ins = np.array([puntaje(r, c) for r, c in zip(R, base)])
            res[tramo]["m"][m] = {
                "cob": 100 * np.mean([r[0] <= c["y"] <= r[1] for r, c in zip(R, base)]) if base else float("nan"),
                "cob_todos": 100 * np.mean([r[0] <= c["y"] <= r[1] for r, c in zip(Rt, todos)]) if todos else float("nan"),
                "ancho": np.mean([(r[1] - r[0]) / c["P"] * 100 for r, c in zip(R, base)]) if base else float("nan"),
                "is": ins.mean() if len(ins) else float("nan"), "v": ins}
    return res


def z_pareado(a, b):
    """z de (puntaje app - puntaje metodo): positivo = el metodo es mejor. Un par por bloque (caso sin pisar)."""
    d = a - b
    if len(d) < 3 or d.std(ddof=1) == 0:
        return 0.0
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))


def veredicto(res, m):
    z, mejor, cob_ok = [], [], []
    for t in (1, 2):
        a, x = res[t]["m"]["app"], res[t]["m"][m]
        z.append(z_pareado(a["v"], x["v"]))
        mejor.append(x["is"] < a["is"])
        cob_ok.append(77 <= x["cob"] <= 83)
    gana = (all(mejor) and all(cob_ok)) or all(v >= 2 for v in z)
    return gana, z, mejor, cob_ok


def main():
    t0 = time.time()
    if PRUEBA:
        print("*** MODO PRUEBA: datos sinteticos, los numeros no dicen nada de BTC ***", flush=True)
        d1, b4, dv, px = datos_sinteticos()
    else:
        d1, b4, dv, px = datos_reales()
    print(f"datos: {len(d1)} velas diarias, {len(b4)} de 4 h, {len(dv)} DVOL por hora ({round(time.time() - t0)} s)", flush=True)
    print("armando el rango de la app dia por dia...", flush=True)
    casos, hoy = armar(d1, b4, dv)
    ks, R = {}, {}
    print("\nRANGO DEL 80% (cobertura objetivo 80%; ancho y puntaje en % del precio; menor puntaje = mejor)")
    for nombre, tf, tf_min, h, W, dias in PLAZOS:
        ks[nombre] = factor_k(casos[nombre], dias)
        R[nombre] = medir(casos[nombre], dias, ks[nombre])
        print(f"\n  {nombre}  (k de la sigma ajustado con el tramo 1: {ks[nombre]:.2f})")
        for t in (1, 2):
            r = R[nombre][t]
            print(f"    tramo {t}: n = {r['n']} sin pisarse ({r['n_todos']} dias)")
            for m in METODOS:
                x = r["m"][m]
                nota = "  (en muestra)" if t == 1 and m.endswith("_cal") else ""
                print(f"      {m:<11} cobertura {x['cob']:5.1f}% (todos los dias {x['cob_todos']:5.1f}%)  ancho {x['ancho']:5.1f}%  puntaje {x['is']:6.2f}{nota}")
    print("\nVEREDICTO contra la app (GANA: mejor puntaje en los 2 tramos con cobertura 77-83% en los 2, o z >= 2 en los 2)")
    ganadores = {}
    for nombre, *_ in PLAZOS:
        for m in METODOS[1:]:
            gana, z, mejor, cob_ok = veredicto(R[nombre], m)
            if gana:
                ganadores.setdefault(nombre, []).append(m)
            print(f"  {nombre:<9} {m:<11} {'GANA' if gana else 'no gana':<8} z tramo 1 {z[0]:+.1f} / tramo 2 {z[1]:+.1f}  "
                  f"puntaje mejor: {'si' if mejor[0] else 'no'}/{'si' if mejor[1] else 'no'}  cobertura 77-83%: {'si' if cob_ok[0] else 'no'}/{'si' if cob_ok[1] else 'no'}"
                  f"{'  (tramo 1 en muestra)' if m.endswith('_cal') else ''}")
    print("\nRESUMEN")
    for nombre, *_ in PLAZOS:
        a1, a2 = R[nombre][1]["m"]["app"], R[nombre][2]["m"]["app"]
        g = ganadores.get(nombre)
        print(f"  {nombre:<9} app: cobertura {a1['cob']:.1f}% / {a2['cob']:.1f}%, puntaje {a1['is']:.2f} / {a2['is']:.2f}  ->  "
              + (f"le gana: {', '.join(g)}" if g else "ningun metodo con DVOL le gana a la app"))
    print("  Ojo: los *_cal usan el tramo 1 para ajustar k, asi que ahi se miden en muestra; lo que vale es el tramo 2.")
    print("  Replica de la app: receta 0 (no la aprendida), sin el ajuste vivo; ver rango_app.")
    # HOY
    dvh = dv[-1]
    print(f"\nHOY  precio {px:,.0f}  DVOL {dvh[1]:.1f} (de {datetime.fromtimestamp(dvh[0] / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC)")
    for nombre, tf, tf_min, h, W, dias in PLAZOS:
        lo, hi = rango_dvol(px, dvh[1], dias)
        lc, hc = rango_dvol(px, dvh[1], dias, ks[nombre])
        t, p, ra = hoy[nombre]
        print(f"  {nombre:<9} DVOL 80%: {lo:,.0f} - {hi:,.0f} (±{(hi / px - 1) * 100:.1f}%)   calibrado (k {ks[nombre]:.2f}): {lc:,.0f} - {hc:,.0f}"
              + (f"   app al {datetime.fromtimestamp(t / 1000, timezone.utc):%Y-%m-%d}: {ra[0]:,.0f} - {ra[1]:,.0f}" if ra else ""))
    print(f"\nlisto en {round(time.time() - t0)} s", flush=True)


if __name__ == "__main__":
    main()
