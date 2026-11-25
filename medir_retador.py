"""Laboratorio honesto: ¿un modelo probabilistico le gana a la tasa normal FUERA DE MUESTRA? No toca nada de la pagina.

Velas 1h de BTCUSDT perpetuo (data.binance.vision, desde 2021). Para H en (1, 4, 24): y = cierre[t+H] > cierre[t],
prediccion hecha al cierre de la vela t con datos <= t. Walk-forward: 2 años de entrenamiento, reentrena cada mes y
predice el mes siguiente (purga de H velas + embargo de H). Modelos: tasa normal (365 dias previos), logistica L2 y
LightGBM chico calibrado con isotonica. Metricas: Brier, ventaja sobre la tasa normal con IC90 por bootstrap en
bloques, log loss, abstencion (10% / 20% mas confiadas), regimenes y rangos a H (cuantiles 10/90 de 90 dias).
Escribe resultados/retador.json y resultados/retador.txt. Necesita numpy, scikit-learn y lightgbm
(NO estan en requirements.txt, que usa Render): lo corre .github/workflows/medir_retador.yml.
"""
import csv, io, json, os, sys, time, urllib.error, urllib.request, warnings, zipfile
from datetime import date, datetime, timedelta, timezone

import numpy as np

HORAS = (1, 4, 24)
HMS = 3600000
WARM = 600                      # velas de calentamiento (la EMA 200 arrastra su valor inicial)
COSTO_PB = 10.0                 # puntos basicos por jugada (ida y vuelta)
SEMILLA = 12345
EPS = 0.01                      # las probabilidades se recortan a [EPS, 1-EPS] (log loss finito)
V90 = 90 * 24                   # ventana de 90 dias en horas
ANIO = 365 * 24


# ---------------------------------------------------------------- datos
def _zip(u):
    """Como datos_entrenamiento._zip pero conserva el volumen comprador taker (columna 9) si esta."""
    for k in range(3):
        try:
            z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(u, timeout=60).read()))
            out = []
            for r in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))):
                if r and r[0].isdigit():
                    tb = float(r[9]) if len(r) > 9 and r[9] != "" else float("nan")
                    out.append([int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]), tb])
            return out
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []
            time.sleep(5)
        except Exception:
            time.sleep(5)
    return []


def velas(sym="BTCUSDT"):
    """Velas 1h cerradas desde 2021: [t_apertura_ms, o, h, l, c, vol, taker_buy_vol]."""
    base = "https://data.binance.vision/data/futures/um"
    rows, hoy = [], date.today()
    y, m = 2021, 1
    while (y, m) < (hoy.year, hoy.month):
        rows += _zip(f"{base}/monthly/klines/{sym}/1h/{sym}-1h-{y}-{m:02d}.zip")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    d = date(hoy.year, hoy.month, 1)
    while d < hoy:
        rows += _zip(f"{base}/daily/klines/{sym}/1h/{sym}-1h-{d}.zip")
        d += timedelta(days=1)
    rows = sorted({r[0]: r for r in rows}.values())
    ahora = time.time() * 1000
    rows = [r for r in rows if r[0] + HMS <= ahora]              # solo velas cerradas
    for i in range(1, len(rows)):                                 # si falta un archivo reciente, se corta ahi
        if rows[i][0] - rows[i - 1][0] > 6 * HMS and rows[i][0] > ahora - 15 * 86400000:
            print(f"(falta el archivo de {datetime.fromtimestamp(rows[i - 1][0] / 1000 + 3600, timezone.utc):%Y-%m-%d}: corto ahí)")
            return rows[:i]
    return rows


def armar(filas):
    """Lista de filas -> dict de arrays en una grilla horaria regular (huecos: cierre arrastrado, volumen 0)."""
    a = np.array([list(f) + [float("nan")] * (7 - len(f)) for f in filas], dtype=float)
    a = a[np.argsort(a[:, 0], kind="stable")]
    a = a[np.unique(a[:, 0], return_index=True)[1]]
    t0 = int(a[0, 0])
    idx = ((a[:, 0] - t0) // HMS).astype(int)
    n = int(idx[-1]) + 1
    pos = np.full(n, -1)
    pos[idx] = np.arange(len(idx))
    src = np.maximum.accumulate(pos)                              # fila de la ultima vela real
    hueco = pos < 0
    g = a[src].copy()
    g[:, 0] = t0 + np.arange(n) * HMS
    g[hueco, 1:5] = a[src[hueco], 4][:, None]
    g[hueco, 5] = 0.0
    tiene_taker = bool(np.isfinite(a[:, 6]).any())
    g[hueco, 6] = 0.0 if tiene_taker else np.nan
    return {"t": g[:, 0].astype(np.int64), "o": g[:, 1], "h": g[:, 2], "l": g[:, 3], "c": g[:, 4], "v": g[:, 5],
            "tb": g[:, 6], "taker": tiene_taker, "huecos": int(hueco.sum())}


# ---------------------------------------------------------------- rasgos (solo pasado)
def _roll(x, w, f):
    """f aplicada a la ventana x[t-w+1..t] (NaN si no hay w datos todavia). Por tandas para no gastar memoria."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if len(x) < w:
        return out
    ven = np.lib.stride_tricks.sliding_window_view(x, w)         # fila j = x[j..j+w-1] -> termina en t=j+w-1
    paso = max(1, 4_000_000 // w)
    for i in range(0, len(ven), paso):
        out[w - 1 + i:w - 1 + i + len(ven[i:i + paso])] = f(ven[i:i + paso])
    return out


def _std(a):
    return a.std(axis=1, ddof=1)


def _ema(x, n):
    a, out, e = 2.0 / (n + 1), np.empty(len(x)), x[0]
    for i in range(len(x)):
        e = e + a * (x[i] - e)
        out[i] = e
    return out


def _rsi(c, n=14):
    d = np.diff(c, prepend=np.nan)
    g, p = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    ag, ap = g[1:n + 1].mean(), p[1:n + 1].mean()
    for i in range(n, len(c)):
        if i > n:
            ag, ap = (ag * (n - 1) + g[i]) / n, (ap * (n - 1) + p[i]) / n
        out[i] = 100.0 if ap == 0 else 100.0 - 100.0 / (1.0 + ag / ap)
    return out


def rasgos(v):
    """Matriz (n, k) y nombres. La fila t usa solo velas <= t."""
    c, h, l, vol = v["c"], v["h"], v["l"], v["v"]
    n = len(c)
    lc = np.log(c)
    cols, nom = [], []

    def add(nombre, x):
        nom.append(nombre)
        cols.append(np.asarray(x, float))

    for k in (1, 2, 4, 8, 24, 72, 168):
        r = np.full(n, np.nan)
        r[k:] = lc[k:] - lc[:-k]
        add(f"ret_{k}", r)
    r1 = np.full(n, np.nan)
    r1[1:] = np.diff(lc)
    v24 = _roll(r1, 24, _std)
    v168 = _roll(r1, 168, _std)
    add("vol_24", v24)
    add("vol_168", v168)
    with np.errstate(all="ignore"):
        add("vol_cociente", v24 / v168)
        add("rsi_14", _rsi(c, 14))
        for k in (20, 50, 200):
            add(f"dist_ema_{k}", np.log(c / _ema(c, k)) / v168)
        for w in (24, 168):
            mn, mx = _roll(l, w, lambda a: a.min(axis=1)), _roll(h, w, lambda a: a.max(axis=1))
            add(f"rango_pos_{w}", np.where(mx > mn, (c - mn) / (mx - mn), 0.5))
        m24 = _roll(vol, 24, lambda a: a.mean(axis=1))
        m168 = _roll(vol, 168, lambda a: a.mean(axis=1))
        s168 = _roll(vol, 168, _std)
        add("vol_z", np.where(s168 > 0, (m24 - m168) / s168, 0.0))
        if v["taker"]:
            s_tb = _roll(v["tb"], 24, lambda a: a.sum(axis=1))
            s_v = _roll(vol, 24, lambda a: a.sum(axis=1))
            add("taker_24", np.where(s_v > 0, s_tb / s_v, 0.5))
    hora = (v["t"] // HMS) % 24
    add("hora_sin", np.sin(2 * np.pi * hora / 24))
    add("hora_cos", np.cos(2 * np.pi * hora / 24))
    add("dia_semana", ((v["t"] // 86400000) + 3) % 7)
    return np.column_stack(cols), nom


# ---------------------------------------------------------------- walk-forward
def _meses(t):
    return ((t + HMS) // 1000).astype("datetime64[s]").astype("datetime64[M]").astype(np.int64)


def walk_forward(v, X, ok, H, meses_ini=24, arboles=300):
    """Predicciones fuera de muestra a H. Devuelve dict de arrays alineados (una fila por prediccion)."""
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    import lightgbm as lgb
    c, n = v["c"], len(v["c"])
    y = np.zeros(n, bool)
    y[:n - H] = c[H:] > c[:n - H]
    mes = _meses(v["t"])
    cl = lambda p: np.clip(p, EPS, 1 - EPS)
    cab = ["idx", "y", "p_normal", "p_log", "p_lgb", "u10_log", "u20_log", "u10_lgb", "u20_lgb"]
    sal = {k: [] for k in cab}
    for M in range(int(mes[0]) + meses_ini, int(mes[-1]) + 1):
        i0, i1 = np.searchsorted(mes, M, "left"), np.searchsorted(mes, M, "right")
        te = np.arange(i0, min(i1, n - H))
        te = te[ok[te]] if len(te) else te
        tr = np.arange(WARM, i0 - 2 * H + 1)                      # purga (H) + embargo (H)
        tr = tr[ok[tr]] if len(tr) else tr
        if len(te) == 0 or len(tr) < 500:
            continue
        p_n = y[max(0, i0 - ANIO - H + 1):i0 - H + 1].mean()      # solo resultados ya conocidos al inicio del mes
        sc = StandardScaler().fit(X[tr])
        lr = LogisticRegression(C=0.1, max_iter=1000).fit(sc.transform(X[tr]), y[tr])
        p_l = cl(lr.predict_proba(sc.transform(X[te]))[:, 1])
        d = np.abs(cl(lr.predict_proba(sc.transform(X[tr]))[:, 1]) - 0.5)
        u_l = (np.quantile(d, 0.90), np.quantile(d, 0.80))
        k = int(len(tr) * 0.8)
        a, b = tr[:max(k - H, 1)], tr[k:]                         # 80% antiguo ajusta, 20% reciente calibra (hueco de H)
        gb = lgb.LGBMClassifier(n_estimators=arboles, learning_rate=0.03, num_leaves=15, min_child_samples=200,
                                subsample=0.8, subsample_freq=1, random_state=7, verbose=-1, n_jobs=2)
        gb.fit(X[a], y[a])
        raw_b = gb.predict_proba(X[b])[:, 1]
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(raw_b, y[b])
        p_g = cl(iso.predict(gb.predict_proba(X[te])[:, 1]))
        d = np.abs(cl(iso.predict(raw_b)) - 0.5)                  # umbral con el entrenamiento (tramo de calibracion)
        u_g = (np.quantile(d, 0.90), np.quantile(d, 0.80))
        m = len(te)
        for kk, val in zip(cab, (te, y[te], np.full(m, p_n), p_l, p_g, np.full(m, u_l[0]), np.full(m, u_l[1]),
                                 np.full(m, u_g[0]), np.full(m, u_g[1]))):
            sal[kk].append(val)
    if not sal["idx"]:
        return None
    return {k: np.concatenate(x) for k, x in sal.items()}


# ---------------------------------------------------------------- metricas
def _bloques(perd_a, perd_b, L, n_boot, rng):
    """IC90 de 1 - sum(perd_a)/sum(perd_b) por bootstrap en bloques moviles de largo L."""
    n = len(perd_a)
    L = min(L, n)
    nb = -(-n // L)
    ca, cb = np.concatenate([[0], np.cumsum(perd_a)]), np.concatenate([[0], np.cumsum(perd_b)])
    ini = rng.integers(0, n - L + 1, size=(n_boot, nb))
    sa, sb = (ca[ini + L] - ca[ini]).sum(1), (cb[ini + L] - cb[ini]).sum(1)
    s = 1 - sa / sb
    return float(np.quantile(s, 0.05)), float(np.quantile(s, 0.95))


def _abst(p, y, ret, u, H):
    sel = np.abs(p - 0.5) >= u
    n = int(sel.sum())
    if n == 0:
        return {"n": 0, "n_ef": 0.0, "acierto": None, "bruto_pb": None, "neto_pb": None}
    lado = np.where(p[sel] >= 0.5, 1.0, -1.0)
    bruto = float((lado * ret[sel]).mean() * 1e4)
    return {"n": n, "n_ef": n / H, "acierto": float(((p[sel] >= 0.5) == y[sel]).mean()),
            "bruto_pb": bruto, "neto_pb": bruto - COSTO_PB}


def _rangos(v, r1, ew, idx, H):
    """Cuantiles 10/90 de los retornos a H de los 90 dias previos: (a) tal cual, (b) escalados por vol EWMA / vol 90d."""
    lc, n = np.log(v["c"]), len(v["c"])
    rH = lc[H:] - lc[:-H]                                          # rH[s] se conoce en s+H
    fin = idx - H                                                  # ultimo s ya conocido al cierre de t
    ok = fin >= V90 - 1
    idx, fin = idx[ok], fin[ok]
    if len(idx) == 0:
        return None
    sd90 = _roll(r1, V90, _std)[idx]
    k = ew[idx] / sd90
    ven = np.lib.stride_tricks.sliding_window_view(rH, V90)        # fila j termina en s = j+V90-1
    q = np.empty((len(idx), 2))
    for i in range(0, len(idx), 1500):
        q[i:i + 1500] = np.quantile(ven[fin[i:i + 1500] - (V90 - 1)], [0.1, 0.9], axis=1).T
    real = lc[idx + H] - lc[idx]
    out = {}
    for nombre, f in (("tal_cual", np.ones(len(idx))), ("escalado", k)):
        lo, hi = np.exp(q[:, 0] * f) - 1, np.exp(q[:, 1] * f) - 1
        r = np.exp(real) - 1
        w = hi - lo
        wink = w + 10.0 * np.maximum(lo - r, 0) + 10.0 * np.maximum(r - hi, 0)   # alfa = 0.2 -> 2/alfa = 10
        out[nombre] = {"n": int(len(idx)), "cobertura": float(((r >= lo) & (r <= hi)).mean()),
                       "ancho_medio_pct": float(w.mean() * 100), "winkler_80_pct": float(wink.mean() * 100)}
    return out


def evaluar_H(v, X, nom, ok, ew, H, meses_ini, arboles, n_boot):
    wf = walk_forward(v, X, ok, H, meses_ini, arboles)
    if wf is None:
        return None
    idx, y = wf["idx"], wf["y"].astype(float)
    c = v["c"]
    ret = c[idx + H] / c[idx] - 1
    rng = np.random.default_rng(SEMILLA + H)
    L = max(H, 24)
    ps = {"normal": wf["p_normal"], "logistica": wf["p_log"], "lightgbm": wf["p_lgb"]}
    perd = {k: (p - y) ** 2 for k, p in ps.items()}
    r168 = np.exp(X[idx, nom.index("ret_168")]) - 1
    regs = {"sube_mas_5pct": r168 > 0.05, "baja_mas_5pct": r168 < -0.05}
    regs["en_el_medio"] = ~(regs["sube_mas_5pct"] | regs["baja_mas_5pct"])
    mods = {}
    for k, p in ps.items():
        m = {"n": int(len(y)), "n_ef": len(y) / H, "brier": float(perd[k].mean()),
             "log_loss": float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())}
        if k != "normal":
            lo, hi = _bloques(perd[k], perd["normal"], L, n_boot, rng)
            m["ventaja"] = float(1 - perd[k].sum() / perd["normal"].sum())
            m["ventaja_ic90"] = [lo, hi]
            u = "log" if k == "logistica" else "lgb"
            m["abstencion"] = {"top10": _abst(p, y, ret, wf["u10_" + u], H), "top20": _abst(p, y, ret, wf["u20_" + u], H)}
            m["regimen"] = {r: {"n": int(s.sum()), "n_ef": float(s.sum()) / H,
                                "ventaja": float(1 - perd[k][s].sum() / perd["normal"][s].sum()) if s.sum() else None}
                            for r, s in regs.items()}
        mods[k] = m
    r1 = np.full(len(c), np.nan)
    r1[1:] = np.diff(np.log(c))
    return {"n": int(len(y)), "n_ef": len(y) / H, "modelos": mods, "rangos": _rangos(v, r1, ew, idx, H),
            "primer_prediccion": int(v["t"][idx[0]]), "ultima_prediccion": int(v["t"][idx[-1]])}


def _ewma_vol(r1, lam=0.97):
    var, out = np.nanvar(r1[1:200]) if len(r1) > 200 else 1e-6, np.empty(len(r1))
    out[0] = np.sqrt(var)
    for i in range(1, len(r1)):
        var = lam * var + (1 - lam) * r1[i] ** 2
        out[i] = np.sqrt(var)
    return out


def correr(filas, meses_ini=24, arboles=300, n_boot=500, horizontes=HORAS):
    """Todo el laboratorio sobre una lista de velas (sin red). Devuelve el dict de resultados."""
    warnings.filterwarnings("ignore")
    t0 = time.time()
    v = armar(filas)
    X, nom = rasgos(v)
    ok = np.isfinite(X).all(1)
    ok[:WARM] = False
    r1 = np.full(len(v["c"]), np.nan)
    r1[1:] = np.diff(np.log(v["c"]))
    ew = _ewma_vol(r1)
    res = {"meta": {"velas": len(v["c"]), "desde": int(v["t"][0]), "hasta": int(v["t"][-1]), "huecos_rellenados": v["huecos"],
                    "taker": v["taker"], "rasgos": nom, "meses_entrenamiento_inicial": meses_ini, "arboles": arboles,
                    "bootstrap": n_boot, "semilla": SEMILLA, "costo_pb": COSTO_PB}, "por_H": {}, "veredicto": {}}
    for H in horizontes:
        t1 = time.time()
        r = evaluar_H(v, X, nom, ok, ew, H, meses_ini, arboles, n_boot)
        res["por_H"][str(H)] = r
        if r:
            res["veredicto"][str(H)] = {k: bool(r["modelos"][k]["ventaja_ic90"][0] > 0) for k in ("logistica", "lightgbm")}
        print(f"H={H}: {time.time() - t1:.0f} s", flush=True)
    res["meta"]["segundos"] = round(time.time() - t0, 1)
    return res


# ---------------------------------------------------------------- salida
def _limpio(x):
    if isinstance(x, dict):
        return {k: _limpio(a) for k, a in x.items()}
    if isinstance(x, (list, tuple)):
        return [_limpio(a) for a in x]
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    return x


def _f(x, d=1, signo=False):
    return "s/d" if x is None else f"{x:{'+' if signo else ''}.{d}f}"


def resumen(res):
    m = res["meta"]
    dia = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")
    nombre = {"logistica": "logística", "lightgbm": "LightGBM"}
    L = ["Laboratorio retador BTCUSDT 1h: fuera de muestra, walk-forward mensual (no cambia nada de la página)",
         f"Datos {dia(m['desde'])} a {dia(m['hasta'])}: {m['velas']} velas, taker {'sí' if m['taker'] else 'no'}, "
         f"{m['meses_entrenamiento_inicial']} meses de entrenamiento inicial, purga y embargo de H velas.",
         "Ventaja = 1 - Brier/Brier de la tasa normal (365 días), con IC90 por bootstrap en bloques; jugadas con costo de " + f"{COSTO_PB:g} pb."]
    ver = []
    for H in map(str, HORAS):
        r = res["por_H"].get(H)
        if not r:
            L.append(f"== H={H} h: sin predicciones (pocos datos)")
            continue
        L.append(f"== H={H} h  n={r['n']}  n_ef={r['n_ef']:.0f}  ({dia(r['primer_prediccion'])} a {dia(r['ultima_prediccion'])})")
        mo = r["modelos"]
        L.append(f"tasa normal: Brier {mo['normal']['brier']:.4f}  log loss {mo['normal']['log_loss']:.4f}")
        for k in ("logistica", "lightgbm"):
            a = mo[k]
            L.append(f"{nombre[k]}: Brier {a['brier']:.4f}  ventaja {_f(a['ventaja'] * 100, 2, True)}% "
                     f"[{_f(a['ventaja_ic90'][0] * 100, 2, True)}, {_f(a['ventaja_ic90'][1] * 100, 2, True)}]  log loss {a['log_loss']:.4f}")
        for k in ("logistica", "lightgbm"):
            t = []
            for q, e in (("10%", "top10"), ("20%", "top20")):
                b = mo[k]["abstencion"][e]
                t.append(f"top {q}: acierto {_f(None if b['acierto'] is None else b['acierto'] * 100)}% n_ef {b['n_ef']:.0f} "
                         f"bruto {_f(b['bruto_pb'], 1, True)} neto {_f(b['neto_pb'], 1, True)} pb")
            L.append(f"abstención {nombre[k]}: " + "; ".join(t))
        reg = []
        for q, e in (("sube>5%", "sube_mas_5pct"), ("baja>5%", "baja_mas_5pct"), ("medio", "en_el_medio")):
            x = [mo[k]["regimen"][e]["ventaja"] for k in ("logistica", "lightgbm")]
            reg.append(f"{q} (n_ef {mo['logistica']['regimen'][e]['n_ef']:.0f}): " +
                       "/".join(_f(None if z is None else z * 100, 1, True) + "%" for z in x))
        L.append("ventaja por régimen de 168 h (logíst./LGBM): " + "; ".join(reg))
        for k, tit in (("tal_cual", "rango 90d tal cual"), ("escalado", "rango 90d escalado por vol")):
            g = (r["rangos"] or {}).get(k)
            L.append(f"{tit}: " + ("sin historia suficiente" if not g else
                                   f"cobertura {g['cobertura'] * 100:.1f}% (meta 80), ancho {g['ancho_medio_pct']:.2f}%, Winkler {g['winkler_80_pct']:.2f}"))
        v = res["veredicto"][H]
        ver.append(f"Veredicto H={H} h: " + "; ".join(
            f"{nombre[k]} {'le gana' if v[k] else 'no le gana'} a la tasa normal (lím. inf. IC90 {_f(mo[k]['ventaja_ic90'][0] * 100, 2, True)}%)"
            for k in ("logistica", "lightgbm")))
    return "\n".join(L + ver) + "\n"


def main():
    t0 = time.time()
    filas = velas()
    if len(filas) < 24 * 365 * 3:
        print(f"Pocas velas ({len(filas)}): no alcanza para medir.")
        sys.exit(1)
    print(f"{len(filas)} velas en {time.time() - t0:.0f} s", flush=True)
    res = _limpio(correr(filas))
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "retador.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    txt = resumen(res)
    with open(os.path.join(d, "retador.txt"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)


if __name__ == "__main__":
    main()
