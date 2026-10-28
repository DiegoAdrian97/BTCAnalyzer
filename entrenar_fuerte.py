"""Entrena el modelo de "movimiento fuerte" (fuerte.py / JavascriptVersion/fuerte.js) y lo guarda en JavascriptVersion/modelo_fuerte.json.

Herramienta aparte (no corre en Render ni en Vercel): necesita numpy y lightgbm.
    python entrenar_fuerte.py velas_1h.json eventos.json [--probar]
velas_1h.json: [[t, o, h, l, c, v], ...] velas de 1 hora de BTCUSDT perpetuo (t = apertura, ms UTC), desde 2021.
eventos.json: [t_ms, ...] horas de los datos de importancia alta de EE.UU. (calendario de TradingView).
--probar: antes de entrenar, mide sin mirar el futuro (entrena con lo anterior a cada trimestre y prueba ese trimestre).
"""
import json
import sys

import numpy as np
import lightgbm as lgb

import fuerte

H = fuerte.H
PARAMS = dict(n_estimators=400, learning_rate=0.02, num_leaves=15, min_child_samples=300, subsample=0.7, subsample_freq=1,
              colsample_bytree=0.7, reg_lambda=5.0, verbose=-1, random_state=7)


def ema(x, span):
    a = 2 / (span + 1); out = np.empty_like(x); m = x[0]
    for i, xi in enumerate(x):
        m = a * xi + (1 - a) * m; out[i] = m
    return out


def roll(x, w, fn):
    from numpy.lib.stride_tricks import sliding_window_view
    out = np.full(len(x), np.nan); out[w - 1:] = fn(sliding_window_view(x, w), axis=1); return out


def rsi(c, p):
    d = np.diff(c, prepend=c[0]); up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    au, ad = ema(up, 2 * p - 1), ema(dn, 2 * p - 1)
    return 100 - 100 / (1 + au / np.maximum(ad, 1e-12))


def señales(B, evs):
    """Las mismas señales que fuerte.señales, para todas las velas a la vez."""
    t, o, h, l, c, v = (np.asarray(x, dtype=float) for x in zip(*B))
    n = len(c); lc = np.log(c); r1 = np.diff(lc, prepend=lc[0])
    F = {}
    for k in (1, 2, 4, 8, 12, 24, 48, 72, 168, 336):
        F[f"ret{k}"] = np.concatenate([np.full(k, np.nan), lc[k:] - lc[:-k]])
    for w in (6, 24, 72, 168, 720):
        F[f"vol{w}"] = roll(r1, w, np.std)
    s = F["vol168"]
    F["volratio"] = F["vol6"] / s; F["volratio2"] = F["vol24"] / F["vol720"]
    F["rango"] = (h - l) / c / s; F["cuerpo"] = (c - o) / c / s
    for span in (20, 50, 200, 800):
        F[f"ema{span}"] = (c / ema(c, span) - 1) / s
    F["rsi14"], F["rsi56"] = rsi(c, 14), rsi(c, 56)
    macd = ema(c, 12) - ema(c, 26); F["macdh"] = (macd - ema(macd, 9)) / c / s
    lv = np.log1p(v); F["volz"] = (lv - roll(lv, 168, np.mean)) / roll(lv, 168, np.std)
    F["vol24_168"] = roll(v, 24, np.mean) / roll(v, 168, np.mean)
    for w in (24, 168, 720):
        hi, lo = roll(h, w, np.max), roll(l, w, np.min)
        F[f"pos{w}"] = (c - lo) / np.maximum(hi - lo, 1e-9); F[f"dd{w}"] = c / hi - 1
    hr = (t // H) % 24
    F["hora_s"], F["hora_c"] = np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24)
    F["finde"] = ((((t // (24 * H)) + 3) % 7) >= 5).astype(float)
    evs = np.asarray(sorted(evs), dtype=float); cierre = t + H
    j = np.searchsorted(evs, cierre)              # primer dato con hora >= cierre
    nxt = np.where(j < len(evs), evs[np.minimum(j, len(evs) - 1)] - cierre, 1e18)
    prv = np.where(j > 0, cierre - evs[np.maximum(j - 1, 0)], 1e18)
    F["evento_prox"] = (nxt <= 4 * H).astype(float); F["evento_ult"] = (prv <= 2 * H).astype(float)
    X = np.column_stack([F[k] for k in fuerte.NOMBRES])
    X[:fuerte.MINIMO - 1] = np.nan
    return t, lc, X


def objetivo(lc, hz):
    """1 si en las proximas hz horas se mueve mas del doble de lo habitual (promedio movil de movimientos ya terminados)."""
    n = len(lc); fut = np.full(n, np.nan); fut[:-hz] = lc[hz:] - lc[:-hz]
    past = np.full(n, np.nan); past[hz:] = np.abs(lc[hz:] - lc[:-hz])
    ew = np.full(n, np.nan); m = None; a = 2 / 2001
    for i in range(n):
        if not np.isnan(past[i]): m = past[i] if m is None else a * past[i] + (1 - a) * m
        ew[i] = np.nan if m is None else m
    y = (np.abs(fut) > 2 * ew).astype(float)
    ok = ~np.isnan(fut) & ~np.isnan(ew) & (np.arange(n) > 2 * hz)
    return y, ok


def exportar(g):
    """Arboles de LightGBM a listas [señal, umbral, izquierda, derecha] (hojas: numeros)."""
    def nodo(d):
        if "leaf_value" in d:
            return d["leaf_value"]
        assert d["decision_type"] == "<=", d["decision_type"]
        return [d["split_feature"], d["threshold"], nodo(d["left_child"]), nodo(d["right_child"])]
    return [nodo(tr["tree_structure"]) for tr in g.booster_.dump_model()["tree_info"]]


def probar(t, X, y, ok, hz):
    """Prueba honesta: cada trimestre desde 2023 se predice con un modelo entrenado solo con lo anterior."""
    import datetime as dt
    q = lambda y_, m: dt.datetime(y_, m, 1, tzinfo=dt.timezone.utc).timestamp() * 1000
    starts = [q(y_, m) for y_ in range(2023, 2027) for m in (1, 4, 7, 10)] + [1e18]
    P = np.full(len(t), np.nan); base = np.full(len(t), np.nan)
    good = ok & np.isfinite(X).all(axis=1)
    for a, b in zip(starts, starts[1:]):
        tr = good & (t + (hz + 1) * H <= a); te = good & (t >= a) & (t < b)
        if not te.any(): continue
        g = lgb.LGBMClassifier(**PARAMS).fit(X[tr], y[tr])
        P[te] = g.predict_proba(X[te])[:, 1]; base[te] = y[tr].mean()
    for name, a, b in (("2023-24", q(2023, 1), q(2025, 1)), ("2025", q(2025, 1), q(2026, 1)), ("2026", q(2026, 1), 1e18)):
        s = good & (t >= a) & (t < b) & np.isfinite(P)
        bs, bb = np.mean((P[s] - y[s]) ** 2), np.mean((base[s] - y[s]) ** 2)
        top = P[s] >= np.quantile(P[s], 0.9)
        print(f"  {hz} h {name}: ventaja {100 * (1 - bs / bb):.2f}% · el 10% más alto fue fuerte {100 * y[s][top].mean():.0f}% (una hora cualquiera {100 * y[s].mean():.0f}%)")


def main():
    B = json.load(open(sys.argv[1])); evs = json.load(open(sys.argv[2]))
    t, lc, X = señales(B, evs)
    # las señales de a una (fuerte.señales) dan lo mismo que las de todas juntas
    for i in (len(B) - 1, len(B) - 500, 20000):
        a = np.array(fuerte.señales(B[:i + 1], evs)); b = X[i]
        assert np.allclose(a, b, rtol=1e-6, atol=1e-9), (i, [fuerte.NOMBRES[k] for k in np.where(~np.isclose(a, b, rtol=1e-6, atol=1e-9))[0]])
    out = {"entrenado_hasta": int(t[-1]), "señales": fuerte.NOMBRES}
    for hz in (1, 4):
        y, ok = objetivo(lc, hz)
        if "--probar" in sys.argv:
            probar(t, X, y, ok, hz)
        good = ok & np.isfinite(X).all(axis=1)
        g = lgb.LGBMClassifier(**PARAMS).fit(X[good], y[good])
        arb = exportar(g)
        M = {"arboles": arb, "base": round(float(y[good][-8760:].mean()) * 100, 1)}
        # los arboles exportados dan lo mismo que LightGBM
        p_lgb = g.predict_proba(X[good][-2000:])[:, 1]
        p_mio = np.array([fuerte.probabilidad(M, x) for x in X[good][-2000:]])
        assert np.allclose(p_lgb, p_mio, atol=1e-9), np.abs(p_lgb - p_mio).max()
        out[f"{hz}h"] = M
        print(f"{hz} h: {len(arb)} árboles, tasa base último año {M['base']}%")
    with open("JavascriptVersion/modelo_fuerte.json", "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print("listo: JavascriptVersion/modelo_fuerte.json")


if __name__ == "__main__":
    main()
