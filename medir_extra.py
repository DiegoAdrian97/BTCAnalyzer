"""Medir antes de sumar, tercera tanda: ideas de trader. Entra a la app solo lo que se repite en todos los tramos.

Cada idea se compara con un "control" (lo que daria el azar en la misma situacion), sin mirar el futuro:
1. Gap del CME: BTC el domingo a la reapertura del CME lejos del cierre del viernes. ¿Vuelve al cierre del viernes
   (rellena el gap) mas que a un nivel a la misma distancia del otro lado?
2. Niveles: maximos y minimos de swing (1 h, el mayor/menor de +-24 h). La primera vez que el precio vuelve a tocarlo,
   ¿rebota (se aleja 1% hacia atras antes de pasarlo 1%) mas que en un nivel falso a la misma distancia?
3. Liquidaciones como iman: con el mapa estimado de la app (open interest y long/short de Binance), ¿el precio llega
   antes a la zona con mas liquidaciones que a la otra, mas de lo que dice la distancia?
4. Funding extremo (5% mas alto o mas bajo del ultimo año): ¿anticipa un giro en 1 y 3 dias?
5. Flujo de los ETF de BTC (Farside): dias de mucha entrada o salida (10% extremos) y el dia siguiente.
6. Vencimiento de opciones: no hay historia gratuita del interes abierto por precio (para el "dolor maximo"): no se mide.
7. Nasdaq (QQQ, velas de 1 h de Yahoo, ~2 años): ¿la hora de QQQ anticipa la hora siguiente de BTC?

Uso: python medir_extra.py velas_1h.json [carpeta de cache]   (velas_1h.json lo arma datos_entrenamiento.py)
"""
import bisect, json, math, os, re, sys, time, urllib.request
from datetime import datetime, timezone, timedelta

H, D = 3_600_000, 86_400_000
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
RES = {}


def ms(y, m, d=1):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


TRAMOS = (("2021-22", ms(2021, 1), ms(2023, 1)), ("2023-24", ms(2023, 1), ms(2025, 1)), ("2025-26", ms(2025, 1), ms(2100, 1)))


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (100 * (c - r) / d, 100 * (c + r) / d)


def pct(k, n):
    return round(100 * k / n, 1) if n else None


def tramo(t):
    for nombre, a, b in TRAMOS:
        if a <= t < b:
            return nombre
    return None


def dst_eeuu(t):
    d = datetime.fromtimestamp(t / 1000, timezone.utc)
    y = d.year
    # segundo domingo de marzo y primer domingo de noviembre (aprox. a las 7 UTC)
    mar = datetime(y, 3, 8, tzinfo=timezone.utc); mar += timedelta(days=(6 - mar.weekday()) % 7)
    nov = datetime(y, 11, 1, tzinfo=timezone.utc); nov += timedelta(days=(6 - nov.weekday()) % 7)
    return mar <= d < nov


def primero(B, i0, arriba, abajo, hasta):
    """Desde la vela i0 (incluida), ¿que nivel se toca primero? 1 arriba, -1 abajo, 0 ninguno antes de 'hasta'."""
    for j in range(i0, min(len(B), hasta)):
        a, b = B[j][2] >= arriba, B[j][3] <= abajo
        if a and b:
            return 0          # los dos en la misma vela: no se sabe cual primero
        if a:
            return 1
        if b:
            return -1
    return 0


# ---------- 1. gap del CME ----------
def cme(B):
    idx = {b[0]: i for i, b in enumerate(B)}
    filas = {}
    t = ms(2021, 1, 1)
    t -= ((t // D + 3) % 7 - 4) * D            # un viernes
    while t < B[-1][0]:
        cierre = t + (21 if dst_eeuu(t) else 22) * H                   # viernes 16:00 de Chicago
        abre = t + 2 * D + (22 if dst_eeuu(t + 2 * D) else 23) * H     # domingo 17:00 de Chicago
        i, j = idx.get(cierre - H), idx.get(abre)
        t += 7 * D
        if i is None or j is None:
            continue
        fc, ab = B[i][4], B[j][1]
        gap = ab / fc - 1
        if abs(gap) < 0.005:
            continue
        nom = tramo(abre)
        for dias in (1, 3, 7):
            fin = j + dias * 24
            hi = max(b[2] for b in B[j:fin]); lo = min(b[3] for b in B[j:fin])
            relleno = lo <= fc if gap > 0 else hi >= fc
            espejo = ab * ab / fc                          # la misma distancia (en %) del otro lado
            control = hi >= espejo if gap > 0 else lo <= espejo
            k = (nom, dias); n, r, c = filas.get(k, (0, 0, 0)); filas[k] = (n + 1, r + relleno, c + control)
    out = []
    for (nom, dias), (n, r, c) in sorted(filas.items()):
        out.append({"tramo": nom, "dias": dias, "gaps": n, "rellena": pct(r, n), "control": pct(c, n), "ic": wilson(r, n)})
    return out


# ---------- 2. niveles de swing ----------
def niveles(B, x=0.01, ventana=24, vida=30 * 24):
    n = len(B)
    h = [b[2] for b in B]; l = [b[3] for b in B]; c = [b[4] for b in B]
    import random
    random.seed(7)
    filas = {}
    for i in range(ventana, n - ventana - 2):
        tipo = 1 if h[i] == max(h[i - ventana:i + ventana + 1]) else -1 if l[i] == min(l[i - ventana:i + ventana + 1]) else 0
        if not tipo:
            continue
        nivel = h[i] if tipo == 1 else l[i]
        desde = i + ventana + 1                       # se confirma recien ahi
        p0 = c[desde - 1]
        dist = (nivel - p0) / p0 * tipo              # cuanto falta para tocarlo (positivo)
        if dist < 0.003:
            continue
        falso = p0 * (1 + tipo * dist * random.uniform(0.5, 1.5))
        for nombre, L in (("real", nivel), ("control", falso)):
            for j in range(desde, min(n - 1, desde + vida)):
                toca = h[j] >= L * (1 - 0.001) if tipo == 1 else l[j] <= L * (1 + 0.001)
                if toca:
                    # resistencia: rebota si baja 1% antes de subir 1%; soporte al reves
                    r = primero(B, j + 1, L * (1 + x), L * (1 - x), j + 1 + 72)
                    if r:
                        reb = (r == -1) if tipo == 1 else (r == 1)
                        k = (tramo(B[j][0]), nombre); a, bb = filas.get(k, (0, 0)); filas[k] = (a + 1, bb + reb)
                    break
    return [{"tramo": k[0], "nivel": k[1], "toques": a, "rebota": pct(bb, a), "ic": wilson(bb, a)} for k, (a, bb) in sorted(filas.items()) if k[0]]


# ---------- 3. liquidaciones como iman ----------
def iman(B, metrics):
    import indicadores as ind
    cierre = {b[0] + H: b[4] for b in B}
    hora_oi = {}
    for r in metrics:                                     # [ms inicio 5 min, OI USD, top, cuentas long/short, flujo]
        t = (r[0] + 300_000) // H * H
        if t in cierre and r[1] > 0:
            hora_oi[t] = (r[1], r[3])
    ts = sorted(hora_oi)
    idx = {b[0]: i for i, b in enumerate(B)}
    filas = {}
    for k in range(200, len(ts), 6):
        t = ts[k]
        i = idx.get(t - H)
        if i is None or i + 73 >= len(B):
            continue
        ventana = [x for x in ts[max(0, k - 168):k + 1]]
        if len(ventana) < 150:
            continue
        precio = {u: cierre[u] for u in ventana}
        oi = [(u, hora_oi[u][0]) for u in ventana]
        ls = {u: hora_oi[u][1] for u in ventana if hora_oi[u][1] > 0}
        lo_s, hi_s = {}, {}
        lo, hi = float("inf"), 0.0
        for u in reversed(ventana):
            lo_s[u], hi_s[u] = lo, hi
            b = B[idx[u - H]]
            lo, hi = min(lo, b[3]), max(hi, b[2])
        mapa = ind.mapa_liquidaciones(precio, oi, ls, lambda u: (lo_s.get(u, float("inf")), hi_s.get(u, 0.0)))
        p = B[i][4]
        arriba = [m for m in mapa if m["precio"] > p * 1.003]
        abajo = [m for m in mapa if m["precio"] < p * 0.997]
        if not arriba or not abajo:
            continue
        za = max(arriba, key=lambda m: m["shorts"] + m["longs"]); zb = max(abajo, key=lambda m: m["shorts"] + m["longs"])
        va, vb = za["shorts"] + za["longs"], zb["shorts"] + zb["longs"]
        if va <= 0 or vb <= 0:
            continue
        da, db = za["precio"] / p - 1, 1 - zb["precio"] / p
        r = primero(B, i + 1, za["precio"], zb["precio"], i + 1 + 72)
        if not r:
            continue
        grande = 1 if va >= vb else -1
        esperado = db / (da + db) if grande == 1 else da / (da + db)    # con solo la distancia (paseo al azar)
        kk = tramo(t); n, ok, e = filas.get(kk, (0, 0, 0.0)); filas[kk] = (n + 1, ok + (r == grande), e + esperado)
    return [{"tramo": k, "casos": n, "llega_a_la_grande": pct(ok, n), "esperado_por_distancia": round(100 * e / n, 1), "ic": wilson(ok, n)}
            for k, (n, ok, e) in sorted(filas.items()) if k]


# ---------- 4. funding extremo ----------
def funding_extremo(B, fu):
    idx = {b[0]: i for i, b in enumerate(B)}
    xs = []
    filas = {}
    for t, f in fu:
        xs.append(f)
        if len(xs) < 3 * 365:
            continue
        ult = sorted(xs[-3 * 365:-1])                      # el ultimo año (3 por dia), sin el de ahora
        alto, bajo = ult[int(0.95 * len(ult))], ult[int(0.05 * len(ult))]
        clase = "alto" if f >= alto else "bajo" if f <= bajo else "normal"
        i = idx.get(t // H * H)
        if i is None or i + 72 >= len(B):
            continue
        for dias in (1, 3):
            r = B[i + 24 * dias][4] / B[i][1] - 1
            k = (tramo(t), clase, dias); n, s, sube = filas.get(k, (0, 0.0, 0)); filas[k] = (n + 1, s + r, sube + (r > 0))
    return [{"tramo": k[0], "funding": k[1], "dias": k[2], "casos": n, "retorno_medio_%": round(100 * s / n, 2), "sube_%": pct(u, n)}
            for k, (n, s, u) in sorted(filas.items()) if k[0]]


# ---------- 5. ETF ----------
def etf(B):
    import noticias
    req = urllib.request.Request(noticias.FARSIDE, headers={"User-Agent": UA})
    page = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    flujos = noticias.parse_farside(page, dias=100000)
    idx = {b[0]: i for i, b in enumerate(B)}
    vals, filas = [], {}
    for f in flujos:
        y, m, d = map(int, f["fecha"].split("-"))
        vals.append(f["neto"])
        if len(vals) < 60:
            continue
        ult = sorted(vals[-121:-1])
        alto, bajo = ult[int(0.9 * len(ult))], ult[int(0.1 * len(ult))]
        clase = "mucha entrada" if f["neto"] >= alto else "mucha salida" if f["neto"] <= bajo else "normal"
        t = ms(y, m, d) + D + 12 * H                        # ya publicado: desde el mediodia UTC del dia siguiente
        i = idx.get(t)
        if i is None or i + 24 >= len(B):
            continue
        r = B[i + 24][4] / B[i][1] - 1
        nom = "2024-25" if t < ms(2025, 7) else "2025-26"
        k = (nom, clase); n, s, u = filas.get(k, (0, 0.0, 0)); filas[k] = (n + 1, s + r, u + (r > 0))
    return [{"tramo": k[0], "flujo": k[1], "dias": n, "retorno_medio_%": round(100 * s / n, 2), "sube_%": pct(u, n)} for k, (n, s, u) in sorted(filas.items())]


# ---------- 7. Nasdaq ----------
def nasdaq(B):
    j = None
    for k in range(6):                                     # Yahoo corta con 429 si se le pide seguido: se reintenta
        u = f"https://query{1 + k % 2}.finance.yahoo.com/v8/finance/chart/QQQ?interval=1h&range=730d"
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "application/json"}), timeout=60).read())["chart"]["result"][0]
            break
        except Exception:
            time.sleep(20 * (k + 1))
    if j is None:
        raise RuntimeError("Yahoo no respondio")
    ts, cl = j["timestamp"], j["indicators"]["quote"][0]["close"]
    idx = {b[0]: i for i, b in enumerate(B)}
    filas = {}
    for k in range(1, len(ts)):
        if cl[k] is None or cl[k - 1] is None:
            continue
        t1 = ts[k] * 1000                                     # apertura de la vela k de QQQ (cierra ~1 h despues)
        fin = (t1 // H + 1) * H                               # la hora de BTC que empieza cuando cierra esta de QQQ
        i = idx.get(fin)
        if i is None:
            continue
        rq = cl[k] / cl[k - 1] - 1
        rb = B[i][4] / B[i][1] - 1
        if abs(rq) < 0.002:
            continue
        nom = "año 1" if t1 < ts[0] * 1000 + 365 * D else "año 2"
        n, ok = filas.get(nom, (0, 0)); filas[nom] = (n + 1, ok + ((rq > 0) == (rb > 0)))
    return [{"tramo": k, "horas": n, "btc_sigue_a_qqq_%": pct(ok, n), "ic": wilson(ok, n)} for k, (n, ok) in sorted(filas.items())]


def main():
    B = json.load(open(sys.argv[1]))
    cache = sys.argv[2] if len(sys.argv) > 2 else "datos_medicion"
    import medir_contexto as mc
    mc.CACHE = cache
    os.makedirs(cache, exist_ok=True)
    pasos = [("1. gap del CME", lambda: cme(B)), ("2. niveles de swing", lambda: niveles(B)),
             ("4. funding extremo", lambda: funding_extremo(B, mc.funding())), ("5. ETF", lambda: etf(B)),
             ("7. Nasdaq", lambda: nasdaq(B)), ("3. liquidaciones como imán", lambda: iman(B, mc.metrics()))]
    for nombre, fn in pasos:
        t0 = time.time()
        try:
            RES[nombre] = fn()
        except Exception as e:
            RES[nombre] = f"no se pudo: {type(e).__name__}: {e}"
        print(f"\n{nombre} ({round(time.time() - t0)} s)")
        if isinstance(RES[nombre], str):
            print("  " + RES[nombre])
        else:
            for f in RES[nombre]:
                print("  " + json.dumps(f, ensure_ascii=False))
        sys.stdout.flush()
    print("\n6. vencimiento de opciones: no hay historia gratuita del interés abierto por precio; no se mide.")
    json.dump(RES, open("resultado_extra.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
