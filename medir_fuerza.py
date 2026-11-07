"""Medir antes de sumar: no la direccion, sino la fuerza y el momento del movimiento.

a) Movimiento fuerte en las proximas 24 h (BTC): el mismo modelo de arboles que ya anda a 1 y 4 h, ¿sirve a 24 h?
b) Un modelo propio para SOL, XRP y ZEC (hoy usan una tabla): ¿le gana a la tabla y al modelo de BTC aplicado a ellas?
c) Cuando: el movimiento medio de cada hora de la semana (168 franjas) medido con 2021-2024, ¿anticipa cuales horas se
   mueven mas en 2025-2026? (si la forma se mantiene, la app puede decir "las horas que mas se mueven hoy")

Prueba honesta como entrenar_fuerte.py: cada trimestre desde 2023 se predice con un modelo entrenado solo con lo anterior.
Uso: python medir_fuerza.py velas_1h.json eventos.json
"""
import datetime as dt, json, sys
import numpy as np
import lightgbm as lgb

import entrenar_fuerte as ef
import datos_entrenamiento as de

H = 3600000


def q(y, m):
    return dt.datetime(y, m, 1, tzinfo=dt.timezone.utc).timestamp() * 1000


TRAMOS = (("2023-24", q(2023, 1), q(2025, 1)), ("2025", q(2025, 1), q(2026, 1)), ("2026", q(2026, 1), 1e18))


def honesto(t, X, y, ok, hz, Xte=None, base_de=None):
    """P (honesta) y tasa base. Xte: otras senales para predecir (mismo t). base_de: modelo ya entrenado (dict tramo->g)."""
    starts = [q(y_, m) for y_ in range(2023, 2027) for m in (1, 4, 7, 10)] + [1e18]
    P = np.full(len(t), np.nan); base = np.full(len(t), np.nan)
    good = ok & np.isfinite(X).all(axis=1)
    for a, b in zip(starts, starts[1:]):
        tr = good & (t + (hz + 1) * H <= a); te = good & (t >= a) & (t < b)
        if not te.any() or tr.sum() < 5000:
            continue
        g = lgb.LGBMClassifier(**ef.PARAMS).fit(X[tr], y[tr])
        P[te] = g.predict_proba(X[te])[:, 1]; base[te] = y[tr].mean()
    return P, base, good


def ventaja(t, y, P, base, good, a, b):
    s = good & (t >= a) & (t < b) & np.isfinite(P)
    if s.sum() < 500:
        return None, None, None
    bs, bb = np.mean((P[s] - y[s]) ** 2), np.mean((base[s] - y[s]) ** 2)
    top = P[s] >= np.quantile(P[s], 0.9)
    return round(100 * (1 - bs / bb), 2), round(100 * y[s][top].mean(), 1), round(100 * y[s].mean(), 1)


def main():
    B = json.load(open(sys.argv[1])); evs = json.load(open(sys.argv[2]))
    res = {}
    t, lc, X = ef.señales(B, evs)
    print("a) BTC, movimiento fuerte: ventaja sobre la tasa base · el 10% mas alto fue fuerte (una hora cualquiera)")
    res["btc"] = []
    for hz in (1, 4, 24):
        y, ok = ef.objetivo(lc, hz)
        P, base, good = honesto(t, X, y, ok, hz)
        for nom, a, b in TRAMOS:
            v = ventaja(t, y, P, base, good, a, b)
            res["btc"].append((hz, nom) + v)
            print(f"  {hz:>2} h {nom}: ventaja {v[0]}% · top 10% fuerte {v[1]}% (cualquiera {v[2]}%)", flush=True)
    # modelos de BTC por trimestre, para aplicarlos a las alts
    print("\nb) Alts: modelo propio vs modelo de BTC aplicado (ventaja sobre la tasa base de cada una)")
    res["alts"] = []
    for sym in ("SOLUSDT", "XRPUSDT", "ZECUSDT", "ETHUSDT"):
        try:
            A = de.velas(sym)
        except Exception as e:
            print(f"  {sym}: no se pudo bajar ({e})"); continue
        if len(A) < 20000:
            print(f"  {sym}: pocas velas ({len(A)})"); continue
        ta, lca, XA = ef.señales(A, evs)
        for hz in (1, 4, 24):
            y, ok = ef.objetivo(lca, hz)
            Pp, bp, gp = honesto(ta, XA, y, ok, hz)
            # modelo de BTC: entrenado con BTC hasta el trimestre, aplicado a la alt
            yb, okb = ef.objetivo(lc, hz)
            starts = [q(y_, m) for y_ in range(2023, 2027) for m in (1, 4, 7, 10)] + [1e18]
            Pb = np.full(len(ta), np.nan)
            gb = okb & np.isfinite(X).all(axis=1)
            for a, b in zip(starts, starts[1:]):
                tr = gb & (t + (hz + 1) * H <= a); te = gp & (ta >= a) & (ta < b)
                if not te.any():
                    continue
                g = lgb.LGBMClassifier(**ef.PARAMS).fit(X[tr], yb[tr])
                Pb[te] = g.predict_proba(XA[te])[:, 1]
            for nom, a, b in TRAMOS:
                vp = ventaja(ta, y, Pp, bp, gp, a, b); vb = ventaja(ta, y, Pb, bp, gp, a, b)
                res["alts"].append((sym, hz, nom, vp[0], vb[0], vp[1], vp[2]))
                print(f"  {sym} {hz:>2} h {nom}: propio {vp[0]}% · el de BTC {vb[0]}% · top 10% (propio) fuerte {vp[1]}% (cualquiera {vp[2]}%)", flush=True)
    print("\nc) Cuando: movimiento medio por hora de la semana (UTC), forma 2021-24 contra 2025-26")
    c = np.asarray([b[4] for b in B]); o = np.asarray([b[1] for b in B]); hh = np.asarray([b[2] for b in B]); ll = np.asarray([b[3] for b in B])
    ts = np.asarray([b[0] for b in B]); mv = (hh - ll) / o
    franja = ((ts // H) % 24 + 24 * (((ts // (24 * H)) + 3) % 7)).astype(int)
    res["horas"] = {}
    for nom, a, b in (("2021-24", q(2021, 1), q(2025, 1)), ("2025-26", q(2025, 1), 1e18)):
        s = (ts >= a) & (ts < b)
        # contra la volatilidad de esa semana, para que no pesen los meses agitados
        sem = (ts // (7 * 24 * H)).astype(int)
        media_sem = {k: mv[s & (sem == k)].mean() for k in np.unique(sem[s])}
        rel = np.array([mv[i] / media_sem[sem[i]] for i in np.where(s)[0]])
        fr = franja[s]
        perfil = np.array([np.median(rel[fr == k]) for k in range(168)])
        res["horas"][nom] = [round(float(x), 3) for x in perfil]
    p1, p2 = np.array(res["horas"]["2021-24"]), np.array(res["horas"]["2025-26"])
    corr = float(np.corrcoef(p1, p2)[0, 1])
    top = np.argsort(-p1)[:20]
    print(f"  correlacion de la forma 2021-24 vs 2025-26: {corr:.2f}")
    print(f"  las 20 franjas mas movidas segun 2021-24, en 2025-26 se movieron x{p2[top].mean():.2f} lo de una hora tipica (las 20 menos: x{p2[np.argsort(p1)[:20]].mean():.2f})")
    dias = "lun mar mie jue vie sab dom".split()
    print("  mas movidas (2021-24):", ", ".join(f"{dias[k // 24]} {k % 24:02d} UTC x{p1[k]:.2f}" for k in top[:10]))
    res["horas_corr"] = round(corr, 3)
    json.dump(res, open("resultado_fuerza.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
