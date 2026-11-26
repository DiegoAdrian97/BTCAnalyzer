"""¿Los datos diarios gratis anticipan a BTC (y a las alts)? (medir antes de sumar). Nov. 2026.

Señales (cada una prendida/apagada, mas la "dosis": Spearman de la variable continua contra el retorno futuro):
  1. Exchanges (CoinMetrics): netflow (entradas - salidas) a 7 y 30 dias y cambio de la reserva (SplyExNtv) a 30 y 90 dias,
     en el 10% mas alto / mas bajo de los 365 dias previos.
  2. Liquidez neta de la Fed = activos totales (H.4.1) - TGA - reverse repo; cambio a 4 y 13 semanas, 20% extremo de 3 años.
  3. Atencion: pageviews diarios de "Bitcoin" en Wikipedia; promedio 7d / promedio 365d en el 10% extremo; dia pico (>3x mediana 30d).
  4. Stablecoins vs BTC: SSR = cap de BTC / (USDT + USDC); extremos de 2 años; cambio a 30 dias de la oferta stable.
  5. VIX (CBOE): nivel alto, salto diario, cambio a 5 dias, estructura invertida (VIX > VIX3M) + correlacion del mismo dia.
  6. Alts (SOL, XRP, ZEC): dominancia de BTC (cap BTC / caps de BTC+ETH+SOL+XRP+BNB+ADA+DOGE) cambio a 30 dias, 20% extremo.
Sin mirar el futuro: umbrales y percentiles solo con datos previos; un dato se usa desde el dia siguiente a su publicacion
(CoinMetrics/VIX/Wikipedia/TGA/RRP: dia siguiente; Fed semanal: miercoles publicado el jueves, se usa desde el viernes).
Retorno futuro: del cierre del dia de la señal al de h dias despues (h = 1, 7, 30, 90).
Contra lo normal del mismo tramo (todos los dias con la señal definida): retorno medio (z) y % de veces que subio.
Los dias se pisan: n efectivo = cantidad de bloques distintos de h dias (i // h), no dias sueltos. Dosis: un dia de cada h.
Dos tramos. SE REPITE: z >= 2 del mismo lado en los dos tramos. Se cuentan las pruebas: al azar cada una pasa ~0,11%.
Uso: python medir_diarios.py [corte desde]   (p. ej. 2024-01-01 2022-01-01: solo 2022-2026, partido en 2022-23 y 2024-26)
     python medir_diarios.py --prueba        (sin internet: series al azar para probar el codigo de punta a punta)
"""
import json
import math
import random
import statistics
import sys
import urllib.request
import zlib
from bisect import bisect_left, bisect_right, insort
from datetime import date, datetime, timedelta

CAB = {"User-Agent": "analista-btc-medicion"}
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
PRUEBA = "--prueba" in sys.argv
CORTE = ARGS[0] if ARGS else "2022-01-01"
DESDE = ARGS[1] if len(ARGS) > 1 else "2013-01-01"
HS = (1, 7, 30, 90)
HS_ALT = (7, 30)
ESTADO = {"pruebas": 0, "rep": [], "pruebas_e": 0, "rep_e": [], "pruebas_a": 0, "rep_a": [], "pruebas_i": 0, "rep_i": []}
HOY = {"vars": [], "senales": []}
G = {}


# ---------------------------------------------------------------- bajada de datos
def http(u, ua=None, timeout=90):
    cab = {"User-Agent": ua or CAB["User-Agent"]}
    return urllib.request.urlopen(urllib.request.Request(u, headers=cab), timeout=timeout).read().decode("utf-8", "replace")


def f_cm(activo, metrica, desde="2013-01-01"):
    out, u = {}, (f"https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets={activo}&metrics={metrica}"
                  f"&frequency=1d&page_size=10000&start_time={desde}")
    while u:
        j = json.loads(http(u))
        for r in j.get("data", []):
            if r.get(metrica) not in (None, ""):
                out[r["time"][:10]] = float(r[metrica])
        u = j.get("next_page_url")
    if not out:
        raise ValueError("sin datos")
    return out


def _fecha(s):
    s = s.strip().strip('"')
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def csv_fechas(txt, col=1):
    """CSV generico: primera columna fecha, columna col numerica; lo que no cierra (encabezados, 'ND', '.') se saltea."""
    out = {}
    for ln in txt.splitlines():
        p = ln.split(",")
        if len(p) <= col:
            continue
        d = _fecha(p[0])
        if not d:
            continue
        try:
            out[d] = float(p[col].strip().strip('"'))
        except ValueError:
            continue
    return out


def _variantes_csv(nombre, variantes, ok):
    """Prueba cada variante (nombre, url, col) hasta que una devuelve datos que pasan el control de cordura `ok`."""
    for nom, u, col in variantes:
        try:
            d = csv_fechas(http(u), col)
            if len(d) < 100:
                raise ValueError(f"solo {len(d)} filas (¿HTML o serie equivocada?)")
            med = statistics.median(d.values())
            if not ok(med):
                raise ValueError(f"mediana {med:.3g} fuera de rango")
            print(f"  {nombre}: anduvo {nom}", flush=True)
            return d
        except Exception as e:
            print(f"  {nombre} / {nom} no: {type(e).__name__}: {e}", flush=True)
    raise ValueError("ninguna variante anduvo")


def f_fed_activos():
    """Activos totales de la Fed, miercoles, millones de USD. Descarga de la Fed (la clave 'series' puede ser un hash: sin
    seguridad) y, de ultima, FRED WALCL."""
    base = "https://www.federalreserve.gov/datadownload/Output.aspx?rel=H41&series=RESPPANWW&lastobs="
    vs = [("DDP H.4.1 RESPPANWW", base + "&from=01/01/2014&to=12/31/2030&filetype=csv&label=include&layout=seriescolumn", 1),
          ("DDP H.4.1 RESPPANWW (label=omit)", base + "&from=01/01/2014&to=12/31/2030&filetype=csv&label=omit&layout=seriescolumn", 1),
          ("FRED WALCL", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=WALCL", 1)]
    return _variantes_csv("Fed activos", vs, lambda m: 1e6 < m < 2e7)


def tga_filas(filas):
    """Saldo de cierre del TGA (millones). Antes de ~2022 la fila es 'Federal Reserve Account' (close_today_bal); despues
    'Treasury General Account (TGA) Closing Balance' (el valor suele venir en open_today_bal). Se prefiere la de cierre."""
    cierre, fed = {}, {}
    for r in filas:
        tipo, d = (r.get("account_type") or ""), r.get("record_date")
        v = None
        for k in ("close_today_bal", "open_today_bal", "closing_balance"):
            try:
                v = float(r[k])
                break
            except (KeyError, TypeError, ValueError):
                continue
        if v is None or not d:
            continue
        if "Closing Balance" in tipo and ("TGA" in tipo or "Treasury General" in tipo):
            cierre[d] = v
        elif tipo.strip() == "Federal Reserve Account":
            fed[d] = v
    fed.update(cierre)
    return fed


def f_tga():
    base = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance"
            "?filter=record_date:gte:2014-01-01&sort=record_date&page[size]=10000")
    try:
        filas, p, tot = [], 1, 1
        while p <= tot:
            j = json.loads(http(f"{base}&page[number]={p}"))
            if p == 1 and j.get("data"):
                print(f"  TGA: campos de la 1ra fila: {sorted(j['data'][0])}", flush=True)
            filas += j.get("data", [])
            tot = int((j.get("meta") or {}).get("total-pages") or 1)
            p += 1
        d = tga_filas(filas)
        if len(d) < 100:
            tipos = sorted({r.get("account_type") for r in filas})[:8]
            raise ValueError(f"solo {len(d)} dias reconocidos; account_type vistos: {tipos}")
        med = statistics.median(d.values())
        if not 1e4 < med < 3e6:
            raise ValueError(f"mediana {med:.3g} fuera de rango (millones)")
        print("  TGA: anduvo FiscalData", flush=True)
        return d
    except Exception as e:
        print(f"  TGA / FiscalData no: {type(e).__name__}: {e}", flush=True)
    return _variantes_csv("TGA", [("FRED WTREGEN (semanal)", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=WTREGEN", 1)],
                          lambda m: 1e4 < m < 3e6)


def f_rrp():
    """Reverse repo de la NY Fed: suma de totalAmtAccepted por operationDate (dolares -> millones), año por año."""
    hoy, d, malos = date.today(), {}, []
    for y in range(2014, hoy.year + 1):
        fin = min(date(y, 12, 31), hoy).isoformat()
        u = f"https://markets.newyorkfed.org/api/rp/reverserepo/propositions/search.json?startDate={y}-01-01&endDate={fin}"
        try:
            j = json.loads(http(u))
            for op in (j.get("repo") or {}).get("operations") or []:
                v, f = op.get("totalAmtAccepted"), op.get("operationDate")
                if v in (None, "") or not f:
                    continue
                d[f[:10]] = d.get(f[:10], 0.0) + float(v) / 1e6
        except Exception as e:
            malos.append(f"{y}: {type(e).__name__}: {e}")
    if malos:
        print(f"  RRP: años que fallaron: {malos}", flush=True)
    if len(d) >= 200:
        print("  RRP: anduvo NY Fed", flush=True)
        return d
    print(f"  RRP / NY Fed no: solo {len(d)} dias", flush=True)
    fr = _variantes_csv("RRP", [("FRED RRPONTSYD (miles de millones)", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=RRPONTSYD", 1)],
                        lambda m: m >= 0)
    return {k: v * 1000 for k, v in fr.items()}


def f_wiki():
    hoy = date.today().strftime("%Y%m%d")
    j = json.loads(http("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/Bitcoin/"
                        f"daily/2015070100/{hoy}00", ua="analista-medicion"))
    out = {}
    for it in j.get("items", []):
        t = it["timestamp"]
        out[f"{t[:4]}-{t[4:6]}-{t[6:8]}"] = float(it["views"])
    if not out:
        raise ValueError("sin datos")
    return out


def f_vix(nombre):
    u = f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{nombre}_History.csv"
    try:
        d = csv_fechas(http(u), 4)
    except Exception:
        d = csv_fechas(http(u, ua="Mozilla/5.0"), 4)
    if not d:
        raise ValueError("sin datos")
    return d


def intentar(nombre, f, *a):
    """Una fuente que falla no mata a las demas: avisa y sigue. Si anda, imprime filas y primera/ultima fecha."""
    try:
        d = f(*a)
    except Exception as e:
        print(f"  {nombre} no: {type(e).__name__}: {e}", flush=True)
        return None
    ks = sorted(d)
    print(f"  {nombre}: {len(d)} filas, {ks[0]} a {ks[-1]}", flush=True)
    return d


# ---------------------------------------------------------------- estadistica
def rangos(xs):
    o = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and xs[o[j + 1]] == xs[o[i]]:
            j += 1
        for k in range(i, j + 1):
            r[o[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(x, y):
    if len(x) < 6 or len(set(x)) < 2:
        return None, None
    rx, ry = rangos(x), rangos(y)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if not sx or not sy:
        return None, None
    r = sxy / (sx * sy)
    return r, r * math.sqrt(len(x) - 1)                       # z aproximado


def pearson(x, y):
    n = len(x)
    if n < 10:
        return None, None
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    if not sx or not sy:
        return None, None
    r = sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)
    return r, r * math.sqrt(n - 1)


def pct_trailing(x, W, minimo=None):
    """Percentil (0-1) de x[i] dentro de x[i-W:i] (solo el pasado, sin el dia). Hace falta al menos W/2 datos."""
    minimo = minimo or W // 2
    win, out = [], [None] * len(x)
    for i, v in enumerate(x):
        if i >= 1 and x[i - 1] is not None:
            insort(win, x[i - 1])
        if i - W - 1 >= 0 and x[i - W - 1] is not None:
            del win[bisect_left(win, x[i - W - 1])]
        if v is not None and len(win) >= minimo:
            a, b = bisect_left(win, v), bisect_right(win, v)
            out[i] = (a + 0.5 * (b - a)) / len(win)
    return out


def rodar(x, w, f):
    out = [None] * len(x)
    for i in range(w - 1, len(x)):
        v = x[i - w + 1:i + 1]
        if None not in v:
            out[i] = f(v)
    return out


def cambio(x, w):
    return [None if i < w or x[i] is None or not x[i - w] else x[i] / x[i - w] - 1 for i in range(len(x))]


def alinear(d, o, lag, vence=10):
    """Serie {fecha: valor} -> lista sobre el calendario de BTC (o = ordinales). El valor de un dia es el ultimo dato cuya
    fecha + lag <= ese dia (se usa desde lag dias despues) y que no tenga mas de `vence` dias de viejo."""
    ks = sorted(d)
    uso = [date.fromisoformat(k).toordinal() + lag for k in ks]
    out, j, ult = [None] * len(o), 0, None
    for i, oi in enumerate(o):
        while j < len(ks) and uso[j] <= oi:
            ult = j
            j += 1
        if ult is not None and oi - (uso[ult] - lag) <= vence:
            out[i] = d[ks[ult]]
    return out


def ext(nom, var, W, q, nhi, nlo):
    p = pct_trailing(var, W)
    return p, [(f"{nom} {nhi}", [None if x is None else x >= 1 - q for x in p]),
               (f"{nom} {nlo}", [None if x is None else x <= q for x in p])]


# ---------------------------------------------------------------- medicion
def celda(on, ret, tr, t, h):
    idx = [i for i in range(len(tr)) if tr[i] == t and on[i] is not None and ret[i] is not None]
    if len(idx) < 60:
        return f"{'sin datos':^64}", None
    norm = [ret[i] for i in idx]
    sel = [i for i in idx if on[i]]
    ne = len({i // h for i in sel})
    if ne < 4:
        return f"{'pocos (b ' + str(ne) + ', d ' + str(len(sel)) + ')':^64}", None
    mb, sd = statistics.fmean(norm), statistics.pstdev(norm)
    if not sd:
        return f"{'sin variacion':^64}", None
    rs = [ret[i] for i in sel]
    m = statistics.fmean(rs)
    z = (m - mb) / (sd / math.sqrt(ne))
    pu, pb = sum(r > 0 for r in rs) / len(rs), sum(r > 0 for r in norm) / len(norm)
    return (f"b{ne:>3} d{len(sel):>4} media {100 * m:+6.1f}% (normal {100 * mb:+5.1f}%) z {z:+4.1f} "
            f"sube {100 * pu:3.0f}% (normal {100 * pb:3.0f}%)"), z


def celda_dosis(var, ret, tr, t, h):
    idx = [i for i in range(0, len(tr), h) if tr[i] == t and var[i] is not None and ret[i] is not None]
    if len(idx) < 20:
        return f"{'sin datos':^34}", None
    r, z = spearman([var[i] for i in idx], [ret[i] for i in idx])
    if r is None:
        return f"{'sin datos':^34}", None
    return f"n {len(idx):>4} · r {r:+.2f} (z {z:+5.1f})".ljust(34), z


def veredicto(zs):
    if all(z is not None and z >= 2 for z in zs):
        return "SE REPITE ▲"
    if all(z is not None and z <= -2 for z in zs):
        return "SE REPITE ▼"
    return ""


def evaluar(titulo, sens, dosis, rets, tr, hs, registrar=True):
    print(f"\n=== {titulo} ===")
    print(f"  (b = bloques independientes de h días · d = días con la señal · tramo 1 hasta {CORTE}, tramo 2 desde {CORTE})")
    for nom, on in sens:
        if registrar:
            HOY["senales"].append((nom, on))
        for h in hs:
            txt, zs = f"  {nom:<44} {h:>3} d", []
            for t in (0, 1):
                c, z = celda(on, rets[h], tr, t, h)
                txt += f" | {c}"
                zs.append(z)
            if all(z is not None for z in zs):
                ESTADO["pruebas"] += 1
            v = veredicto(zs)
            if v:
                ESTADO["rep"].append((titulo, nom, h, zs))
            print(txt + f" | {v}", flush=True)
    if dosis:
        print(f"  -- dosis: Spearman de la variable contra el retorno futuro (un día de cada h) --")
    for nom, var, pct in dosis:
        if registrar:
            HOY["vars"].append((nom, var, pct if pct is not None else pct_trailing(var, 365)))
        for h in hs:
            txt, zs = f"  {nom:<44} {h:>3} d", []
            for t in (0, 1):
                c, z = celda_dosis(var, rets[h], tr, t, h)
                txt += f" | {c}"
                zs.append(z)
            if all(z is not None for z in zs):
                ESTADO["pruebas"] += 1
            v = veredicto(zs)
            if v:
                ESTADO["rep"].append((titulo + " (dosis)", nom, h, zs))
            print(txt + f" | {v.replace('▲', '(más variable = BTC mejor)').replace('▼', '(más variable = BTC peor)')}", flush=True)


def retornos(P, hs):
    n = len(P)
    return {h: [None if i + h >= n or P[i] is None or P[i + h] is None else P[i + h] / P[i] - 1 for i in range(n)] for h in hs}


# ---------------------------------------------------------------- estados del mercado (seccion principal)
ESTADOS = ("piso", "piso extremo", "techo", "rally en curso", "indecisión")
ESTADOS_DESC = {"piso": "mín 90d próximos >= 0,90 x precio y máx 180d >= 1,30 x precio",
                "piso extremo": "precio <= 1,05 x mín de [-180, +180] días",
                "techo": "máx 90d próximos <= 1,10 x precio y mín 180d <= 0,70 x precio",
                "rally en curso": "retorno 60d >= +25% y mín 30d próximos >= 0,92 x precio",
                "indecisión": "próximos 45d dentro de ±12% del precio de hoy"}


def etiquetas_estados(P):
    """Etiquetas con FUTURO (solo como respuesta a predecir, nunca como entrada). None si la ventana no esta completa."""
    n = len(P)
    out = {e: [None] * n for e in ESTADOS}
    for i in range(n):
        p = P[i]
        if p is None:
            continue
        if i + 180 < n:
            w = P[i + 1:i + 181]
            if None not in w:
                out["piso"][i] = min(w[:90]) >= 0.90 * p and max(w) >= 1.30 * p
                out["techo"][i] = max(w[:90]) <= 1.10 * p and min(w) <= 0.70 * p
            if i >= 180:
                w2 = P[i - 180:i + 181]
                if None not in w2:
                    out["piso extremo"][i] = p <= 1.05 * min(w2)
        if i + 60 < n:
            w = P[i + 1:i + 61]
            if None not in w:
                out["rally en curso"][i] = w[59] / p - 1 >= 0.25 and min(w[:30]) >= 0.92 * p
        if i + 45 < n:
            w = P[i + 1:i + 46]
            if None not in w:
                out["indecisión"][i] = max(w) <= 1.12 * p and min(w) >= 0.88 * p
    return out


def puntaje_termometro(o, P):
    """Puntaje del termometro SIN mirar el futuro. Preferido: la temperatura historica de armar_termometro (media de los
    percentiles de wma200, dd_ath y ret365 contra la historia previa; 0 = barato, 100 = caro). No incluye la parte de ciclo
    de 4 años del medidor final (es un modelo logistico entrenado aparte y muy enredado). Si no se puede importar, proxy:
    percentil del MVRV (CoinMetrics CapMVRVCur) contra los 4 años previos."""
    try:
        import numpy as np
        import armar_termometro as at
        c, ult = [], None
        for x in P:
            ult = x if x is not None else ult
            c.append(ult)
        T, _ = at.temperatura_historica(np.array(c, dtype=float), at.COMP)
        return [float(x) if math.isfinite(x) else None for x in T], "temperatura de armar_termometro (wma200, dd_ath, ret365; sin la parte de ciclo)"
    except Exception as e:
        print(f"  termómetro no: {type(e).__name__}: {e} -> proxy MVRV", flush=True)
    mv = intentar("BTC CapMVRVCur (proxy)", f_cm, "btc", "CapMVRVCur")
    if not mv:
        return None, "sin puntaje"
    p = pct_trailing(alinear(mv, o, 1, 5), 1460, 365)
    return [None if x is None else 100 * x for x in p], "PROXY: percentil del MVRV contra 4 años previos"


def auc(x, y):
    """Mann-Whitney: P(x de un caso con estado > x de uno sin estado). y bool."""
    n1 = sum(y)
    n0 = len(y) - n1
    if n1 < 10 or n0 < 10:
        return None, 0, 0
    r = rangos(x)
    u = sum(ri for ri, yi in zip(r, y) if yi) - n1 * (n1 - 1) / 2
    return u / (n1 * n0), n1, n0


def logit_fit(X, y, l2=1.0):
    import numpy as np
    w = np.zeros(X.shape[1])
    reg = np.diag([0.0] + [1.0] * (X.shape[1] - 1)) * l2 + 1e-6 * np.eye(X.shape[1])
    for _ in range(50):
        p = 1 / (1 + np.exp(-np.clip(X @ w, -30, 30)))
        paso = np.linalg.solve((X.T * (p * (1 - p))) @ X + reg, X.T @ (p - y) + np.r_[0.0, w[1:]] * l2)
        w -= paso
        if abs(paso).max() < 1e-7:
            break
    return w


def auc_incremental(score, var, lab, tr, a, b):
    """Ajusta estado ~ puntaje (solo) y estado ~ puntaje + variable en el tramo a; AUC en el tramo b."""
    import numpy as np
    def filas(t, con_var):
        ix = [i for i in range(len(tr)) if tr[i] == t and score[i] is not None and lab[i] is not None and (not con_var or var[i] is not None)]
        return ix
    res = []
    for con in (False, True):
        ia, ib = filas(a, True), filas(b, True)
        if len(ia) < 200 or len(ib) < 200:
            return None
        cols = (lambda i: [score[i]]) if not con else (lambda i: [score[i], var[i]])
        Xa, Xb = np.array([cols(i) for i in ia], float), np.array([cols(i) for i in ib], float)
        mu, sd = Xa.mean(0), Xa.std(0)
        sd[sd == 0] = 1
        Xa, Xb = (Xa - mu) / sd, (Xb - mu) / sd
        w = logit_fit(np.c_[np.ones(len(Xa)), Xa], np.array([lab[i] for i in ia], float))
        s = (np.c_[np.ones(len(Xb)), Xb] @ w).tolist()
        r = auc(s, [lab[i] for i in ib])[0]
        if r is None:
            return None
        res.append(r)
    return res


def evaluar_estados(labs, tr, score, desc_score):
    sens, vars_ = HOY["senales"], HOY["vars"]
    tabla = {}                                                    # (señal, estado) -> [(p, base, z) por tramo]
    print("\n" + "=" * 100)
    print("=== SECCIÓN PRINCIPAL: ESTADOS DEL MERCADO (¿la señal anticipa un piso, un techo, un rally o un rango?) ===")
    print("=" * 100)
    print("Etiquetas (con futuro, solo como respuesta; la señal nunca las ve):")
    for e in ESTADOS:
        bs = []
        for t in (0, 1):
            xs = [labs[e][i] for i in range(len(tr)) if tr[i] == t and labs[e][i] is not None]
            bs.append(f"tramo {t + 1}: {100 * sum(xs) / len(xs):.0f}% de {len(xs)} d" if xs else f"tramo {t + 1}: sin datos")
        print(f"  {e:<15} {ESTADOS_DESC[e]} · tasa base {' · '.join(bs)}")
    for e in ESTADOS:
        lab = labs[e]
        print(f"\n--- P({e} | señal prendida) contra la tasa base del mismo tramo (z con n efectivo = bloques de 90 días) ---")
        for nom, on in sens:
            txt, zs, cs = f"  {nom:<44}", [], []
            for t in (0, 1):
                idx = [i for i in range(len(tr)) if tr[i] == t and on[i] is not None and lab[i] is not None]
                sel = [i for i in idx if on[i]]
                ne = len({i // 90 for i in sel})
                if len(idx) < 100 or ne < 4:
                    txt += f" | {'pocos (b ' + str(ne) + ')':^44}"
                    zs.append(None)
                    cs.append(None)
                    continue
                base = sum(lab[i] for i in idx) / len(idx)
                p = sum(lab[i] for i in sel) / len(sel)
                z = (p - base) / math.sqrt(max(base * (1 - base), 1e-9) / ne) if 0 < base < 1 else None
                zs.append(z)
                cs.append((p, base, z))
                txt += (f" | b{ne:>3} d{len(sel):>4} P {100 * p:3.0f}% (base {100 * base:3.0f}%) z {z:+4.1f}" if z is not None else f" | {'base 0/1':^44}")
            tabla[(nom, e)] = cs
            if all(z is not None for z in zs):
                ESTADO["pruebas_e"] += 1
            v = veredicto(zs)
            if v:
                ESTADO["rep_e"].append((e, nom, zs))
            print(txt + f" | {v}", flush=True)

    print("\n--- AUC de cada variable continua para separar cada estado (0,5 = nada; z con n efectivo = días/90) ---")
    print("    ▲ = variable alta marca el estado; ▼ = variable baja marca el estado; SE REPITE = z >= 2 del mismo lado en los dos tramos")
    for nom, var, _ in vars_:
        for e in ESTADOS:
            txt, zs = f"  {nom:<44} {e:<14}", []
            for t in (0, 1):
                ix = [i for i in range(len(tr)) if tr[i] == t and var[i] is not None and labs[e][i] is not None]
                a, n1, n0 = auc([var[i] for i in ix], [labs[e][i] for i in ix]) if len(ix) >= 100 else (None, 0, 0)
                if a is None:
                    txt += f" | {'sin datos':^24}"
                    zs.append(None)
                    continue
                se = math.sqrt((n1 / 90 + n0 / 90 + 1) / (12 * max(n1 / 90, 1) * max(n0 / 90, 1)))
                z = (a - 0.5) / se
                zs.append(z)
                txt += f" | AUC {a:.3f} (z {z:+4.1f})".ljust(27)
            if all(z is not None for z in zs):
                ESTADO["pruebas_a"] += 1
            v = veredicto(zs)
            if v:
                ESTADO["rep_a"].append((e, nom, zs))
            print(txt + f" | {v}", flush=True)

    print("\n--- VALOR AGREGADO sobre el termómetro: estado ~ puntaje  contra  estado ~ puntaje + variable ---")
    if score is None or not any(x is not None for x in score):
        print("  sin puntaje del termómetro: no se puede medir")
    else:
        print(f"  puntaje usado: {desc_score}")
        print("  logística ajustada en un tramo y probada en el otro (AUC fuera de muestra), en las dos direcciones; SUMA = mejora >= +0,01 en las dos")
        for nom, var, _ in vars_:
            for e in ("piso", "piso extremo", "techo"):
                txt, ds = f"  {nom:<44} {e:<13}", []
                for a, b in ((0, 1), (1, 0)):
                    try:
                        r = auc_incremental(score, var, labs[e], tr, a, b)
                    except Exception as ex:
                        r = None
                        print(f"    (logística no: {type(ex).__name__}: {ex})")
                    if r is None:
                        txt += f" | {a + 1}→{b + 1}: {'sin datos':^26}"
                        ds.append(None)
                    else:
                        txt += f" | {a + 1}→{b + 1}: {r[0]:.3f}→{r[1]:.3f} ({r[1] - r[0]:+.3f})"
                        ds.append(r[1] - r[0])
                if all(d is not None for d in ds):
                    ESTADO["pruebas_i"] += 1
                v = "SUMA" if all(d is not None and d >= 0.01 for d in ds) else ("RESTA" if all(d is not None and d <= -0.01 for d in ds) else "")
                if v == "SUMA":
                    ESTADO["rep_i"].append((e, nom, ds))
                print(txt + f" | {v}", flush=True)
    return tabla


# ---------------------------------------------------------------- bloques
def b_flujos():
    o = G["o"]
    fin = intentar("BTC FlowInExNtv", f_cm, "btc", "FlowInExNtv")
    fout = intentar("BTC FlowOutExNtv", f_cm, "btc", "FlowOutExNtv")
    res = intentar("BTC SplyExNtv", f_cm, "btc", "SplyExNtv")
    sens, dosis = [], []
    if fin and fout:
        nf = {d: fin[d] - fout[d] for d in fin if d in fout}
        a = alinear(nf, o, 1, 5)
        for w in (7, 30):
            v = rodar(a, w, sum)
            p, s = ext(f"netflow {w}d", v, 365, 0.1, "mayores ENTRADAS (esp ▼)", "mayores SALIDAS=acumulación (esp ▲)")
            sens += s
            dosis.append((f"netflow {w}d (BTC, + = entradas)", v, p))
    if res:
        a = alinear(res, o, 1, 5)
        for w in (30, 90):
            v = cambio(a, w)
            p, s = ext(f"reserva exch. cambio {w}d", v, 365, 0.1, "SUBE mucho (esp ▼)", "BAJA mucho (esp ▲)")
            sens += s
            dosis.append((f"reserva exch. cambio {w}d", v, p))
    if not sens:
        raise ValueError("sin flujos ni reservas")
    evaluar("1. EXCHANGES: netflow y reservas (BTC)", sens, dosis, G["rets"], G["tr"], HS)


def b_liquidez():
    o = G["o"]
    A = intentar("Fed activos totales", f_fed_activos)
    T = intentar("TGA", f_tga)
    R = intentar("RRP", f_rrp)
    if not (A and T and R):
        raise ValueError("falta alguna pata de la liquidez neta (activos, TGA o RRP)")
    a, t, r = alinear(A, o, 2, 21), alinear(T, o, 2, 21), alinear(R, o, 1, 7)
    primero_r = date.fromisoformat(min(R)).toordinal()
    net = []
    for i in range(len(o)):
        rr = r[i] if r[i] is not None else (0.0 if o[i] < primero_r else None)      # antes de que existiera el RRP, cero
        net.append(None if a[i] is None or t[i] is None or rr is None else a[i] - t[i] - rr)
    ult = [x for x in net if x is not None]
    print(f"  liquidez neta (millones USD): primera {ult[0]:,.0f} · ultima {ult[-1]:,.0f} (activos {A[max(A)]:,.0f}, "
          f"TGA {T[max(T)]:,.0f}, RRP {R[max(R)]:,.0f})", flush=True)
    sens, dosis = [], []
    for w, nom in ((28, "4s"), (91, "13s")):
        v = cambio(net, w)
        p, s = ext(f"liquidez neta cambio {nom}", v, 1095, 0.2, "SUBE (esp ▲)", "BAJA (esp ▼)")
        sens += s
        dosis.append((f"liquidez neta cambio {nom}", v, p))
    evaluar("2. LIQUIDEZ NETA DE LA FED (activos - TGA - RRP)", sens, dosis, G["rets"], G["tr"], HS)


def b_atencion():
    o = G["o"]
    w = intentar("Wikipedia pageviews Bitcoin", f_wiki)
    if not w:
        raise ValueError("sin pageviews")
    x = alinear(w, o, 1, 5)
    m7, m365 = rodar(x, 7, statistics.fmean), rodar(x, 365, statistics.fmean)
    ratio = [None if a is None or not b else a / b for a, b in zip(m7, m365)]
    p, sens = ext("atención 7d/365d", ratio, 365, 0.1, "ALTA (esp ▼)", "BAJA (esp ▲)")
    pico = [None] * len(x)
    for i in range(31, len(x)):
        ven = x[i - 30:i]
        if x[i] is not None and None not in ven:
            pico[i] = x[i] > 3 * statistics.median(ven)
    sens.append(("día pico (> 3x mediana 30d)", pico))
    evaluar("3. ATENCIÓN: pageviews de Wikipedia 'Bitcoin'", sens, [("atención 7d/365d", ratio, p)], G["rets"], G["tr"], HS)


def b_stable():
    o = G["o"]
    cap = intentar("BTC CapMrktCurUSD", f_cm, "btc", "CapMrktCurUSD")
    usdt = intentar("USDT SplyCur", f_cm, "usdt", "SplyCur")
    if usdt is None:
        partes = [x for x in (intentar(f"{a} SplyCur", f_cm, a, "SplyCur") for a in ("usdt_eth", "usdt_trx", "usdt_omni")) if x]
        usdt = {}
        for dd in partes:
            for k, v in dd.items():
                usdt[k] = usdt.get(k, 0.0) + v
        print(f"  USDT sumado de {len(partes)} activos", flush=True)
    usdc = intentar("USDC SplyCur", f_cm, "usdc", "SplyCur")
    if not cap or not (usdt or usdc):
        raise ValueError("falta cap de BTC o oferta de stablecoins")
    st = {}
    for dd in (usdt or {}, usdc or {}):
        for k, v in dd.items():
            st[k] = st.get(k, 0.0) + v
    print(f"  stablecoins usadas: {'USDT ' if usdt else ''}{'USDC' if usdc else ''}", flush=True)
    c, s = alinear(cap, o, 1, 5), alinear(st, o, 1, 5)
    ssr = [None if a is None or not b else a / b for a, b in zip(c, s)]
    p, sens = ext("SSR (cap BTC / stables)", ssr, 730, 0.1, "ALTO: pocas stables (esp ▼)", "BAJO: mucha pólvora (esp ▲)")
    v30 = cambio(s, 30)
    p2, s2 = ext("oferta stable cambio 30d", v30, 730, 0.1, "SUBE mucho (esp ▲)", "BAJA/poco (esp ▼)")
    evaluar("4. STABLECOINS vs BTC (SSR)", sens + s2, [("SSR", ssr, p), ("oferta stable cambio 30d", v30, p2)],
            G["rets"], G["tr"], HS)


def b_vix():
    o, P, dias = G["o"], G["P"], G["dias"]
    vix = intentar("VIX", f_vix, "VIX")
    if not vix:
        raise ValueError("sin VIX")
    v3 = intentar("VIX3M", f_vix, "VIX3M")
    ks = sorted(vix)
    v = [vix[k] for k in ks]
    c1 = [None] + [v[i] / v[i - 1] - 1 if v[i - 1] else None for i in range(1, len(v))]
    c5 = [None] * 5 + [v[i] / v[i - 5] - 1 if v[i - 5] else None for i in range(5, len(v))]
    pn, p5 = pct_trailing(v, 252), pct_trailing(c5, 252)          # 252 ruedas ~ 365 dias; solo ruedas, sin fines de semana
    al = lambda lst: alinear(dict(zip(ks, lst)), o, 1, 6)
    nivel, pniv, jump, c5a, p5a = al(v), al(pn), al(c1), al(c5), al(p5)
    sens = [("VIX ALTO (top 10% 365d): ¿cae más o rebota?", [None if x is None else x >= 0.9 for x in pniv]),
            ("VIX salto 1 día > +20%", [None if x is None else x > 0.2 for x in jump]),
            ("VIX cambio 5d ALTO (top 10%)", [None if x is None else x >= 0.9 for x in p5a]),
            ("VIX cambio 5d BAJO (bottom 10%)", [None if x is None else x <= 0.1 for x in p5a])]
    if v3:
        inv = alinear({k: 1.0 if vix[k] > v3[k] else 0.0 for k in vix if k in v3}, o, 1, 6)
        sens.append(("estructura invertida (VIX > VIX3M)", [None if x is None else x == 1.0 for x in inv]))
    evaluar("5. VIX (CBOE)", sens, [("VIX nivel", nivel, pniv), ("VIX cambio 5d", c5a, p5a)], G["rets"], G["tr"], HS)
    # correlacion del mismo dia: retorno de BTC desde el cierre de la rueda anterior contra cambio del VIX (solo informativo)
    pos = {d: i for i, d in enumerate(dias)}
    print("  -- correlación del MISMO día (informativa): retorno BTC vs cambio del VIX entre ruedas --")
    for t in (0, 1):
        xs, ys = [], []
        for j in range(1, len(ks)):
            d, dp = ks[j], ks[j - 1]
            if d in pos and dp in pos and G["tr"][pos[d]] == t and P[pos[d]] and P[pos[dp]] and v[j - 1]:
                xs.append(v[j] / v[j - 1] - 1)
                ys.append(P[pos[d]] / P[pos[dp]] - 1)
        r, z = pearson(xs, ys)
        print(f"    tramo {t + 1}: " + (f"n {len(xs)} · r {r:+.2f} (z {z:+.1f})" if r is not None else "sin datos"), flush=True)


def b_alts():
    o, P = G["o"], G["P"]
    caps = {}
    for a in ("btc", "eth", "sol", "xrp", "bnb", "ada", "doge"):
        d = intentar(f"{a} CapMrktCurUSD", f_cm, a, "CapMrktCurUSD")
        if d:
            caps[a] = alinear(d, o, 1, 5)
    if "btc" not in caps or len(caps) < 3:
        raise ValueError(f"poca cobertura de caps ({sorted(caps)})")
    print(f"  dominancia con: {sorted(caps)} (en cada día solo las que existen hoy y hace 30 d)", flush=True)
    n = len(o)
    dom = [None] * n
    for i in range(30, n):
        sn = sp = 0.0
        k = 0
        for x in caps.values():
            if x[i] is not None and x[i - 30] is not None:
                sn += x[i]
                sp += x[i - 30]
                k += 1
        b = caps["btc"]
        if k >= 2 and b[i] is not None and b[i - 30] is not None and sn and sp:
            dom[i] = (b[i] / sn) / (b[i - 30] / sp) - 1
    p, sens = ext("dominancia BTC cambio 30d", dom, 365, 0.2, "SUBE (esp alt ▼)", "BAJA (esp alt ▲)")
    for a in ("sol", "xrp", "zec"):
        d = intentar(f"{a} PriceUSD", f_cm, a, "PriceUSD")
        if not d:
            continue
        pa = alinear(d, o, 0, 3)
        val = [i for i in range(n) if pa[i] is not None]
        mid = o[val[0]] + (o[val[-1]] - o[val[0]]) // 2
        tr = [None if pa[i] is None else (0 if o[i] <= mid else 1) for i in range(n)]
        print(f"  {a}: historia {G['dias'][val[0]]} a {G['dias'][val[-1]]}, mitades cortadas en {date.fromordinal(mid)}", flush=True)
        ab = retornos(pa, HS_ALT)
        rel = {h: [None if ab[h][i] is None or P[i] is None or P[i + h] is None else (1 + ab[h][i]) / (P[i + h] / P[i]) - 1
                   for i in range(n)] for h in HS_ALT}
        ss = [(f"{nm}", on) for nm, on in sens]
        evaluar(f"6. {a.upper()} vs dominancia de BTC: retorno ABSOLUTO", ss, [("dominancia cambio 30d", dom, p)], ab, tr, HS_ALT, False)
        evaluar(f"6. {a.upper()} vs dominancia de BTC: retorno RELATIVO a BTC", ss, [], rel, tr, HS_ALT, False)
    HOY["vars"].append(("dominancia BTC cambio 30d", dom, p))
    HOY["senales"] += sens


# ---------------------------------------------------------------- modo prueba (sin internet)
def _sintetico():
    hoy = date.today()

    def dias(ini, fin=hoy):
        return [ini + timedelta(k) for k in range((fin - ini).days + 1)]

    def paseo(clave, ini, base, vol, deriva=0.0, h=None):
        rnd, x, out = random.Random(zlib.crc32(clave.encode())), base, {}
        for d in dias(ini):
            if h and d.weekday() >= 5:
                continue
            x *= math.exp(rnd.gauss(deriva, vol))
            out[d.isoformat()] = x
        return out

    ini = {"btc": date(2013, 1, 1), "eth": date(2015, 8, 8), "xrp": date(2013, 8, 5), "bnb": date(2017, 7, 25),
           "ada": date(2017, 10, 2), "doge": date(2013, 12, 15), "sol": date(2020, 4, 11), "zec": date(2016, 10, 28),
           "usdt_eth": date(2017, 11, 28), "usdt_trx": date(2019, 4, 16), "usdc": date(2018, 10, 1)}
    precio = {"btc": 100, "eth": 1, "xrp": 0.01, "bnb": 0.1, "ada": 0.02, "doge": 0.0002, "sol": 1, "zec": 50}

    def cm(activo, met, desde="2013-01-01"):
        if activo == "usdt" or activo not in ini:
            raise ValueError("HTTP Error 400: Bad Request (activo de prueba inexistente)")
        k = f"{activo}{met}"
        if met == "PriceUSD":
            return paseo(k, ini[activo], precio[activo], 0.035, 0.0008)
        if met == "CapMrktCurUSD":
            p = paseo(activo + "PriceUSD", ini[activo], precio[activo], 0.035, 0.0008)
            return {d: v * 1e7 for d, v in p.items()}
        rnd = random.Random(zlib.crc32(k.encode()))
        if met in ("FlowInExNtv", "FlowOutExNtv"):
            return {d.isoformat(): 1e4 * (1 + abs(rnd.gauss(0, 0.5))) for d in dias(ini[activo])}
        if met == "CapMVRVCur":
            return paseo(k, ini[activo], 2.0, 0.01)
        if met == "SplyExNtv":
            return paseo(k, ini[activo], 2.5e6, 0.003)
        if met == "SplyCur":
            return paseo(k, ini[activo], 1e8, 0.004, 0.002)
        raise ValueError("metrica de prueba desconocida")

    def fed():
        print("  Fed activos / DDP H.4.1 RESPPANWW no: URLError: sin internet (prueba)")
        print("  Fed activos: anduvo (series de prueba)")
        return {d.isoformat(): v for d, v in ((x, paseo("fed", date(2014, 1, 1), 4.2e6, 0.004, 0.0004)[x.isoformat()])
                                                for x in dias(date(2014, 1, 1)) if x.weekday() == 2)}

    def tga():
        return {k: v / 4e6 * 5e5 for k, v in paseo("tga", date(2014, 1, 1), 4e6, 0.02, 0, True).items()}

    def rrp():
        return {k: v / 1e5 for k, v in paseo("rrp", date(2014, 1, 1), 1e5, 0.03, 0.0003, True).items()}

    def wiki():
        rnd = random.Random(5)
        return {d.isoformat(): 20000 * math.exp(rnd.gauss(0, 0.3)) * (4 if rnd.random() < 0.01 else 1) for d in dias(date(2015, 7, 1))}

    def vix(nombre):
        return paseo(nombre, date(2014, 1, 1), 18, 0.05, 0, True)

    globals().update(f_cm=cm, f_fed_activos=fed, f_tga=tga, f_rrp=rrp, f_wiki=wiki, f_vix=vix)


def _autotest():
    """Los lectores de formatos de las fuentes reales, contra textos de ejemplo (sin red)."""
    fred = "observation_date,WALCL\n2014-01-01,4000000\n2014-01-08,.\n2014-01-15,4010000\n"
    assert csv_fechas(fred) == {"2014-01-01": 4000000.0, "2014-01-15": 4010000.0}
    vix = "DATE,OPEN,HIGH,LOW,CLOSE\n01/02/2014,14.3,14.9,13.9,14.23\n01/03/2014,14.3,14.4,13.1,14.0\n"
    assert csv_fechas(vix, 4) == {"2014-01-02": 14.23, "2014-01-03": 14.0}
    tga = tga_filas([{"record_date": "2020-01-02", "account_type": "Federal Reserve Account", "close_today_bal": "380000", "open_today_bal": "350000"},
                     {"record_date": "2022-06-01", "account_type": "Treasury General Account (TGA) Closing Balance", "close_today_bal": "null", "open_today_bal": "700000"},
                     {"record_date": "2022-06-01", "account_type": "Treasury General Account (TGA) Opening Balance", "open_today_bal": "690000"}])
    assert tga == {"2020-01-02": 380000.0, "2022-06-01": 700000.0}, tga
    print("  autotest de lectores de formato: ok", flush=True)


# ---------------------------------------------------------------- principal
def main():
    if PRUEBA:
        print("MODO PRUEBA: series al azar, sin internet")
        _sintetico()
        _autotest()
    print(f"Tramo 1: {DESDE} a {CORTE} (sin incluirlo) · tramo 2: desde {CORTE}", flush=True)
    print("Fuentes:", flush=True)
    px = intentar("BTC PriceUSD", f_cm, "btc", "PriceUSD")
    if not px:
        print("sin precio de BTC no se puede medir nada")
        return
    o0, o1 = date.fromisoformat(min(px)).toordinal(), date.fromisoformat(max(px)).toordinal()
    o = list(range(o0, o1 + 1))
    dias = [date.fromordinal(x).isoformat() for x in o]
    P = [px.get(d) for d in dias]
    G.update(o=o, dias=dias, P=P, rets=retornos(P, HS),
             tr=[None if d < DESDE else (0 if d < CORTE else 1) for d in dias])
    for t in (0, 1):
        ix = [i for i, x in enumerate(G["tr"]) if x == t]
        if ix:
            print(f"  tramo {t + 1}: {dias[ix[0]]} a {dias[ix[-1]]} ({len(ix)} días)", flush=True)
    for nombre, fn in (("exchanges", b_flujos), ("liquidez", b_liquidez), ("atención", b_atencion),
                       ("stablecoins", b_stable), ("VIX", b_vix), ("alts", b_alts)):
        try:
            fn()
        except Exception as e:
            print(f"\n=== bloque {nombre} no: {type(e).__name__}: {e} ===", flush=True)

    labs = etiquetas_estados(P)
    if "--proxy" in sys.argv:                                      # fuerza el proxy de MVRV (para probarlo)
        mv = intentar("BTC CapMVRVCur (proxy)", f_cm, "btc", "CapMVRVCur")
        score = [None if x is None else 100 * x for x in pct_trailing(alinear(mv, o, 1, 5), 1460, 365)] if mv else None
        desc = "PROXY: percentil del MVRV contra 4 años previos"
    else:
        score, desc = puntaje_termometro(o, P)
    tabla = {}
    try:
        tabla = evaluar_estados(labs, G["tr"], score, desc)
    except Exception as e:
        print(f"\n=== sección de estados no: {type(e).__name__}: {e} ===", flush=True)

    print("\n" + "=" * 100)
    pe, pa, pi = ESTADO["pruebas_e"], ESTADO["pruebas_a"], ESTADO["pruebas_i"]
    print(f"=== RESUMEN DE ESTADOS: {pe} pruebas de señal prendida con los dos tramos (al azar pasarían ~{pe * 0.0011:.1f}) · "
          f"{pa} de AUC (~{pa * 0.0011:.1f}) ===")
    for e, nom, zs in ESTADO["rep_e"]:
        print(f"  señal  {e:<15} {nom:<44} z {zs[0]:+.1f} / {zs[1]:+.1f}")
    for e, nom, zs in ESTADO["rep_a"]:
        print(f"  AUC    {e:<15} {nom:<44} z {zs[0]:+.1f} / {zs[1]:+.1f}")
    if not (ESTADO["rep_e"] or ESTADO["rep_a"]):
        print("  ninguna se repite en los dos tramos")
    print(f"  valor agregado sobre el termómetro ({pi} pruebas; la mejora de AUC no tiene z, es un umbral de +0,01 en las dos direcciones):")
    for e, nom, ds in ESTADO["rep_i"]:
        print(f"  SUMA   {e:<15} {nom:<44} {ds[0]:+.3f} / {ds[1]:+.3f}")
    if not ESTADO["rep_i"]:
        print("  ninguna variable suma en las dos direcciones")

    p, rep = ESTADO["pruebas"], ESTADO["rep"]
    print(f"\n=== RESUMEN DE RETORNOS (secundario): {p} pruebas con los dos tramos; al azar pasarían ~{p * 0.0011:.1f} (0,11% cada una; "
          f"las señales de un mismo bloque están correlacionadas, así que es una cota gruesa) ===")
    if not rep:
        print("  ninguna se repite en los dos tramos")
    for tit, nom, h, zs in rep:
        print(f"  {tit[:44]:<44} {nom:<44} {h:>3} d  z {zs[0]:+.1f} / {zs[1]:+.1f}")

    L = len(G["o"]) - 1
    print(f"\n=== HOY ({dias[L]}; cada dato usable desde el día siguiente a su publicación) ===")
    if score and score[L] is not None:
        print(f"  puntaje del termómetro ({desc}): {score[L]:.0f}")
    for nom, var, pct in HOY["vars"]:
        v, q = var[L], pct[L]
        print(f"  {nom:<44} valor {'sin dato' if v is None else f'{v:,.4g}'} · percentil {'—' if q is None else f'{100 * q:.0f}%'}")
    on = [nom for nom, s in HOY["senales"] if s[L]]
    print("  señales prendidas hoy: " + ("; ".join(on) if on else "ninguna"))
    print("  qué implican (P(estado | señal) tramo 1 / tramo 2, con la tasa base entre paréntesis; * = SE REPITE):")
    for nom in on:
        partes = []
        for e in ESTADOS:
            cs = tabla.get((nom, e))
            if cs and all(c and c[2] is not None for c in cs):
                rep_ = "*" if veredicto([c[2] for c in cs]) else ""
                partes.append(f"{e} {100 * cs[0][0]:.0f}/{100 * cs[1][0]:.0f}% ({100 * cs[0][1]:.0f}/{100 * cs[1][1]:.0f}){rep_}")
        print(f"    {nom}: " + (" · ".join(partes) if partes else "sin datos suficientes"))


if __name__ == "__main__":
    main()
