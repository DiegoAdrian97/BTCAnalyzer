"""Medir antes de sumar: ¿el open interest, el flujo de compras/ventas, el long/short, el funding, la prima del
perpetuo (base contra el spot) y la volatilidad implicita de las opciones (DVOL) le ganan a la tasa base? ¿Y pesos
distintos por regimen de mercado? ¿Y cuando 15 min, 1 hora y 4 horas coinciden, aciertan mas? ¿El rango del 80%
ajustado con su propio pasado queda honesto?

Todo sin mirar el futuro, con el mismo aprendizaje que usa el analista (aprendizaje.aprender, repasando años en vez de
las ultimas 1.000 velas): cada prediccion se hace solo con lo que se sabia en ese momento y cada resultado se usa para
aprender recien cuando se conoce. Las escalas de las senales nuevas salen solo de 2022-2024. Se mide en 2023-2024 y
se verifica en 2025-2026: entra al analisis solo lo que gana en los dos tramos.

Datos publicos: data.binance.vision (velas, metrics cada 5 min, funding, prima) y Deribit (DVOL).
Uso: python medir_contexto.py [carpeta para guardar lo bajado, por defecto datos_medicion]
"""
import bisect, csv, io, json, math, os, sys, time, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import aprendizaje as apr
import indicadores as ind

BASE = "https://data.binance.vision/data/futures/um"
SYM = "BTCUSDT"
DESDE, HASTA = date(2022, 1, 1), date(2026, 11, 1)          # meses completos
TF_MS = {"5m": 300_000, "30m": 1_800_000, "4h": 14_400_000}
CACHE = sys.argv[1] if len(sys.argv) > 1 else "datos_medicion"
MEDIR = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000      # se mide desde aca
VERIF = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000      # tramo de verificacion
ESCALAS = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000    # escalas solo con lo anterior


# ---------- bajar (se guarda en CACHE: la segunda vez no se baja nada) ----------
def _bajar(url, archivo):
    ruta = os.path.join(CACHE, archivo)
    if os.path.exists(ruta):
        with open(ruta, "rb") as f:
            return f.read()
    for k in range(4):
        try:
            datos = urllib.request.urlopen(url, timeout=60).read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                datos = b""
                break
            time.sleep(3)
        except Exception:
            time.sleep(3)
    else:
        return b""
    with open(ruta, "wb") as f:
        f.write(datos)
    return datos


def _csv_zip(datos):
    if not datos:
        return []
    z = zipfile.ZipFile(io.BytesIO(datos))
    return list(csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))))


def _meses():
    y, m = DESDE.year, DESDE.month
    while (y, m) < (HASTA.year, HASTA.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def velas(tf):
    rows = []
    for y, m in _meses():
        nombre = f"{SYM}-{tf}-{y}-{m:02d}.zip"
        rows += [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
                 for r in _csv_zip(_bajar(f"{BASE}/monthly/klines/{SYM}/{tf}/{nombre}", "k" + nombre)) if r[0].isdigit()]
    return sorted({r[0]: r for r in rows}.values())


def prima():
    """Prima del perpetuo contra el indice (spot) cada 5 min: [ms de cierre, prima]."""
    rows = []
    for y, m in _meses():
        nombre = f"{SYM}-5m-{y}-{m:02d}.zip"
        rows += [[int(r[0]) + 300_000, float(r[4])] for r in
                 _csv_zip(_bajar(f"{BASE}/monthly/premiumIndexKlines/{SYM}/5m/{nombre}", "p" + nombre)) if r[0].isdigit()]
    return sorted(rows)


def funding():
    rows = []
    for y, m in _meses():
        nombre = f"{SYM}-fundingRate-{y}-{m:02d}.zip"
        rows += [[int(r[0]), float(r[2])] for r in _csv_zip(_bajar(f"{BASE}/monthly/fundingRate/{SYM}/{nombre}", nombre))
                 if r[0].isdigit()]
    return sorted(rows)


def metrics():
    """Cada 5 min: [ms, OI en USD, top traders long/short, cuentas long/short, compras/ventas a mercado]."""
    dias = [DESDE + timedelta(days=k) for k in range((HASTA - DESDE).days)]

    def uno(d):
        nombre = f"{SYM}-metrics-{d}.zip"
        out = []
        for r in _csv_zip(_bajar(f"{BASE}/daily/metrics/{SYM}/{nombre}", nombre)):
            if not r or not r[0][:1].isdigit():
                continue
            try:
                t = int(datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)
                out.append([t, float(r[3] or 0), float(r[5] or 0), float(r[6] or 0), float(r[7] or 0)])
            except ValueError:
                continue
        return out

    with ThreadPoolExecutor(16) as pool:
        rows = [x for parte in pool.map(uno, dias) for x in parte]
    return sorted({r[0]: r for r in rows}.values())


def dvol():
    """Volatilidad implicita de las opciones de BTC (Deribit), por hora: [ms de cierre, DVOL]."""
    ruta = os.path.join(CACHE, "dvol.json")
    if os.path.exists(ruta):
        with open(ruta) as f:
            return json.load(f)
    out, a = {}, int(datetime(DESDE.year, DESDE.month, 1, tzinfo=timezone.utc).timestamp() * 1000)
    fin = int(datetime(HASTA.year, HASTA.month, 1, tzinfo=timezone.utc).timestamp() * 1000)
    while a < fin:
        b = min(fin, a + 900 * 3_600_000)
        u = f"https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&start_timestamp={a}&end_timestamp={b}&resolution=3600"
        for k in range(4):
            try:
                for t, o, h, l, c in json.loads(urllib.request.urlopen(u, timeout=60).read())["result"]["data"]:
                    out[int(t) + 3_600_000] = float(c)
                break
            except Exception:
                time.sleep(3)
        a = b
    rows = sorted([t, v] for t, v in out.items())
    with open(ruta, "w") as f:
        json.dump(rows, f)
    return rows


def bajar_todo():
    os.makedirs(CACHE, exist_ok=True)
    t0 = time.time()
    with ThreadPoolExecutor(6) as pool:
        trabajos = {"5m": pool.submit(velas, "5m"), "30m": pool.submit(velas, "30m"), "4h": pool.submit(velas, "4h"),
                    "prima": pool.submit(prima), "funding": pool.submit(funding), "dvol": pool.submit(dvol)}
        m = metrics()
        datos = {k: v.result() for k, v in trabajos.items()}
    datos["metrics"] = m
    print("bajado en", round(time.time() - t0), "s:", {k: len(v) for k, v in datos.items()}, flush=True)
    return datos


# ---------- senales nuevas de cada vela: solo lo que se sabia al cerrar ----------
NOMBRES = ("OI 1 h", "OI 24 h", "flujo 1 h", "flujo 4 h", "top traders", "cuentas long/short", "funding", "funding 7 d",
           "prima", "prima 24 h", "DVOL vs 30 d", "DVOL 24 h")
GRUPOS = {"open interest": (0, 1), "flujo de compras/ventas": (2, 3), "long/short": (4, 5), "funding": (6, 7),
          "prima perpetuo-spot": (8, 9), "opciones (DVOL)": (10, 11), "flujo + open interest": (0, 1, 2, 3),
          "todas juntas": tuple(range(12))}
H1, H24 = 3_600_000, 86_400_000


def _acum(xs):
    out = [0.0]
    for x in xs:
        out.append(out[-1] + x)
    return out


def senales(bars, tf_ms, D):
    M, fu, pr, dv = D["metrics"], D["funding"], D["prima"], D["dvol"]
    # en los archivos de metrics la hora es la del inicio de los 5 minutos: el dato se conoce recien al final (la API de
    # Binance lo confirma: el flujo lleva la hora de inicio y el open interest aparece 5 min despues). Sin este corrimiento
    # la medicion veia el flujo y el open interest 5 minutos antes de tiempo.
    mt, ft, pt, dt = [r[0] + 300_000 for r in M], [r[0] for r in fu], [r[0] for r in pr], [r[0] for r in dv]
    lt = _acum(math.log(r[4]) if r[4] > 0 else 0.0 for r in M)
    fc, pc, dc = _acum(r[1] for r in fu), _acum(r[1] for r in pr), _acum(r[1] for r in dv)
    out = []
    for b in bars:
        T = b[0] + tf_ms
        i = bisect.bisect_right(mt, T) - 1
        f = [None] * 12
        if i >= 0 and T - mt[i] <= H1:
            for ms, k in ((H1, 0), (H24, 1)):
                j = bisect.bisect_right(mt, T - ms) - 1
                if j >= 0 and T - ms - mt[j] <= H1 and M[j][1] > 0 and M[i][1] > 0:
                    f[k] = math.log(M[i][1] / M[j][1])
            for ms, k in ((H1, 2), (4 * H1, 3)):
                a = bisect.bisect_right(mt, T - ms)
                if i + 1 - a > 0:
                    f[k] = (lt[i + 1] - lt[a]) / (i + 1 - a)
            f[4] = math.log(M[i][2]) if M[i][2] > 0 else None
            f[5] = math.log(M[i][3]) if M[i][3] > 0 else None
        k = bisect.bisect_right(ft, T) - 1
        if k >= 20:
            f[6], f[7] = fu[k][1], (fc[k + 1] - fc[k - 20]) / 21
        p = bisect.bisect_right(pt, T) - 1
        if p >= 288 and T - pt[p] <= H1:
            f[8], f[9] = pr[p][1], (pc[p + 1] - pc[p + 1 - 288]) / 288
        d = bisect.bisect_right(dt, T) - 1
        if d >= 720 and T - dt[d] <= 3 * H1:
            f[10] = math.log(dv[d][1] / ((dc[d + 1] - dc[d + 1 - 720]) / 720))
            f[11] = math.log(dv[d][1] / dv[d - 24][1])
        out.append(f)
    return out


def escalar(F, bars):
    """Cada senal a desvios de su media (media y desvio solo de antes de 2025), con tope +-4; 0 si falta."""
    est = []
    for k in range(12):
        xs = [f[k] for f, b in zip(F, bars) if f[k] is not None and b[0] < ESCALAS]
        mu = sum(xs) / len(xs) if xs else 0.0
        sd = (sum((x - mu) ** 2 for x in xs) / len(xs)) ** 0.5 if len(xs) > 1 else 1.0
        est.append((mu, sd or 1.0))
    return [[0.0 if f[k] is None else max(-4.0, min(4.0, (f[k] - est[k][0]) / est[k][1])) for k in range(12)] for f in F]


# ---------- el analista en vivo, ventana por ventana ----------
PLAZOS_M = (("15 min", "5m", 3, 8640), ("1 hora", "5m", 12, 8640), ("4 horas", "30m", 8, 8640), ("1 día", "4h", 6, 4380))
VARIANTES = ("actual",) + tuple(GRUPOS) + ("pesos por régimen",)


def _ventana(args):
    """Una ventana como la ve la app (W velas de historia) y su repaso de 1.000 predicciones, con cada variante."""
    bars, ctx, h, tf_min = args
    c = [b[4] for b in bars]
    e50, e200, rsi, (_, _, mh) = ind.ema(c, 50), ind.ema(c, 200), ind.rsi(c), ind.macd(c)
    combo = apr.combos(apr.rasgos(bars, tf_min, e50, e200, rsi, mh))
    X = apr.continuos(bars, tf_min, e50, e200, rsi, mh)
    reg = apr.regimenes(bars, e200)
    warmup = min(200, len(bars) // 3)
    out = {}
    for v in VARIANTES:
        if v == "actual" or v == "pesos por régimen":
            Xv = X
        else:
            g = GRUPOS[v]
            Xv = [None if x is None else x + [ctx[i][k] for k in g] for i, x in enumerate(X)]
        apr.REGISTRO = []
        apr.aprender(bars, combo, h, warmup, Xv, reg if v == "pesos por régimen" else None)
        out[v] = [(bars[t][0], ps, os_, e_ap, e_bs) for ps, os_, pf, of, t, e_ap, e_bs in apr.REGISTRO]
    apr.REGISTRO = None
    return out, [(bars[t][0], reg[t]) for t in range(len(bars) - 1000, len(bars))]


def medir_plazo(nombre, tf, h, W, bars, ctx, pool):
    tf_min = TF_MS[tf] // 60_000
    fin = len(bars)
    trabajos = []
    while fin - 1000 > 0 and bars[fin - 1][0] >= MEDIR:
        ini = max(0, fin - W)
        trabajos.append((bars[ini:fin], ctx[ini:fin], h, tf_min))
        fin -= 1000
    res = {v: {} for v in VARIANTES}
    regs = {}
    for out, rg in pool.map(_ventana, trabajos):
        for v in VARIANTES:
            for t, ps, os_, ea, eb in out[v]:
                if t >= MEDIR:
                    res[v][t] = (ps, os_, ea, eb)
        regs.update(rg)
    return res, regs


def _dia(t):
    return int(t // H24)


def comparar(res, base="actual"):
    """Ventaja sobre la tasa base de cada variante por tramo, y si la diferencia con la actual es real (z por dia)."""
    filas = []
    for v, d in res.items():
        for tramo, (a, b) in (("2023-24", (MEDIR, VERIF)), ("2025-26", (VERIF, 1e15))):
            ts = [t for t in d if a <= t < b and t in res[base]]
            ea = sum(d[t][2] for t in ts)
            eb = sum(d[t][3] for t in ts)
            dias = {}
            for t in ts:
                dias[_dia(t)] = dias.get(_dia(t), 0.0) + (res[base][t][2] - d[t][2])   # + = la variante erra menos
            xs = list(dias.values())
            mu = sum(xs) / len(xs) if xs else 0.0
            sd = (sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5 if len(xs) > 1 else 0.0
            z = mu / (sd / len(xs) ** 0.5) if sd > 0 else 0.0
            filas.append((v, tramo, len(ts), (1 - ea / eb) * 100 if eb else None, z))
    return filas


# ---------- idea 4: cuando 15 min, 1 hora y 4 horas coinciden ----------
def coincidencias(R):
    """Con las predicciones honestas del repaso (variante actual): en cada cierre de 30 min, si los tres plazos van para
    el mismo lado, ¿cada uno acierta mas que cuando no coinciden?"""
    q15, q1h, q4h = R["15 min"]["actual"], R["1 hora"]["actual"], R["4 horas"]["actual"]
    filas = []
    for tramo, (a, b) in (("2023-24", (MEDIR, VERIF)), ("2025-26", (VERIF, 1e15))):
        cuenta = {}
        for t30, p4 in q4h.items():
            if not a <= t30 < b:
                continue
            t5 = t30 + 25 * 60_000           # la vela de 5 min que cierra junto con la de 30 min
            if t5 not in q15 or t5 not in q1h:
                continue
            ps = (q15[t5][0], q1h[t5][0], p4[0])
            lado = 1 if all(p > 0.5 for p in ps) else -1 if all(p < 0.5 for p in ps) else 0
            for nombre, d, t in (("15 min", q15, t5), ("1 hora", q1h, t5), ("4 horas", q4h, t30)):
                p, os_ = d[t][0], d[t][1]
                if p == 0.5:
                    continue
                key = (nombre, "coinciden" if lado else "no coinciden")
                n, ok = cuenta.get(key, (0, 0))
                cuenta[key] = (n + 1, ok + ((p > 0.5) == (os_ == 1)))
        for (nombre, caso), (n, ok) in sorted(cuenta.items()):
            hh = {"15 min": 1, "1 hora": 2, "4 horas": 8}[nombre]       # predicciones que se pisan (en cierres de 30 min)
            lo, hi = apr.wilson(ok / hh, n / hh)
            filas.append((tramo, nombre, caso, n, ok / n * 100 if n else None, lo, hi))
    return filas


# ---------- idea 2: el rango del 80% ajustado con su propio pasado, ¿queda honesto? ----------
def rango_honesto(nombre, tf, h, W, bars):
    import analisis_btc as A
    tf_min = TF_MS[tf] // 60_000
    c = [b[4] for b in bars]
    e50, e200, rsi, (_, _, mh) = ind.ema(c, 50), ind.ema(c, 200), ind.rsi(c), ind.macd(c)
    st = apr.estados(apr.rasgos(bars, tf_min, e50, e200, rsi, mh), 0)
    F = A.vol_escala(bars, tf_min, h, False) if tf_min <= 60 else None
    pts = A.rango_puntajes(c, st, F, h, 200, len(c) - 1 - h, puntos=10 ** 9, ventana=W)[::-1]   # de la mas vieja a la mas nueva
    filas = []
    for tramo, (a, b) in (("2023-24", (MEDIR, VERIF)), ("2025-26", (VERIF, 1e15))):
        crudo = ajustado = n = 0
        for i, (j, x) in enumerate(pts):
            if not a <= bars[j][0] < b or i < A.CAL_MIN:
                continue
            k = A.rango_factor(pts[max(0, i - A.CAL_PUNTOS):i])["k"]          # solo lo que ya se sabia
            n += 1
            crudo += x <= 1
            ajustado += x <= k
        filas.append((nombre, tramo, n, crudo / n * 100 if n else None, ajustado / n * 100 if n else None))
    return filas


def main():
    D = bajar_todo()
    from concurrent.futures import ProcessPoolExecutor
    R, regs = {}, {}
    with ProcessPoolExecutor(max(1, (os.cpu_count() or 2) - 1)) as pool:
        for nombre, tf, h, W in PLAZOS_M:
            if os.environ.get("PLAZOS") and nombre not in os.environ["PLAZOS"].split(","):
                continue
            t0 = time.time()
            bars = D[tf]
            ctx = escalar(senales(bars, TF_MS[tf], D), bars)
            R[nombre], regs[nombre] = medir_plazo(nombre, tf, h, W, bars, ctx, pool)
            print(f"{nombre}: {len(R[nombre]['actual'])} predicciones repasadas en {round(time.time() - t0)} s", flush=True)
    resumen = {"ventaja": {}, "coincidencias": coincidencias(R) if len(R) == len(PLAZOS_M) else [], "rango": [], "regimenes": {}}
    print("\nVENTAJA SOBRE LA TASA BASE (% menos error; z: la diferencia con la actual, por dia; |z| > 2 es real)")
    for nombre in R:
        filas = comparar(R[nombre])
        resumen["ventaja"][nombre] = filas
        print(f"\n  {nombre}")
        for v, tramo, n, hab, z in filas:
            print(f"    {v:<26} {tramo}  {n:>7} pred.  ventaja {hab:+.2f}%  z {z:+.1f}")
        cuenta = {}
        for t, g in regs[nombre].items():
            if t < ESCALAS:
                cuenta[g] = cuenta.get(g, 0) + 1
        resumen["regimenes"][nombre] = {apr.REGIMENES[g]: round(n / sum(cuenta.values()) * 100, 1) for g, n in sorted(cuenta.items())}
        print("    regimenes (2023-24):", resumen["regimenes"][nombre])
    print("\nCUANDO 15 MIN, 1 HORA Y 4 HORAS COINCIDEN (acierto de la direccion, con margen del 95%)")
    for tramo, nombre, caso, n, ac, lo, hi in resumen["coincidencias"]:
        print(f"  {tramo} {nombre:<8} {caso:<13} {n:>7} casos  acierta {ac:.1f}% ({lo:.1f}-{hi:.1f})")
    print("\nRANGO DEL 80%: CUANTAS VECES TERMINO ADENTRO (sin ajustar / ajustado con su pasado)")
    for nombre, tf, h, W in PLAZOS_M:
        if nombre not in R:
            continue
        for fila in rango_honesto(nombre, tf, h, W, D[tf]):
            resumen["rango"].append(fila)
            print(f"  {fila[0]:<8} {fila[1]}  {fila[2]:>6} pred.  {fila[3]:.1f}% -> {fila[4]:.1f}%")
    with open(os.path.join(CACHE, "resultado.json"), "w") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    if os.environ.get("SOLO_BAJAR"):
        bajar_todo()
    else:
        main()
