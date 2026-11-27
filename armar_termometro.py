"""Arma JavascriptVersion/termometro.json: lo que necesita el termometro de compra/venta (ciclo de BTC).

    python armar_termometro.py btc_diario.json [fng.json] [alts_diario.json] [onchain.json]
        (velas diarias de BTC desde 2011, p. ej. Bitstamp; historial del Fear & Greed Index de api.alternative.me;
         velas diarias de XRP, SOL y ZEC con toda su historia, {"XRP": [[t, o, h, l, c, v], ...], ...})

Medido con BTC 2015-2026 (ver README): lo que mejor marco las buenas zonas de compra a 6-12 meses fue que tan lejos
esta el precio de su media de 200 semanas, cuanto cayo desde el maximo historico y cuanto subio o bajo en el ultimo
año (los tres comparados con toda la historia). El volumen, los indicadores de corto plazo, el indice de miedo y
codicia, la fase del halving y las noticias no lo anticiparon de forma pareja entre ciclos: quedan como contexto.
Herramienta aparte (no corre en Render ni en Vercel): necesita numpy.
"""
import bisect, json, sys
import numpy as np

COMP = ("wma200", "dd_ath", "ret365")
# On-chain (CoinMetrics, gratis): MVRV (precio contra el costo promedio de todos los BTC) y Puell (lo que cobran los
# mineros por dia contra su promedio de un año). Medido 2019-2026 sin mirar el futuro, sumados al "barato o caro":
# a 6 meses el medidor separa mejor en los dos tramos (2019-22: 0,870 -> 0,893; 2023-26: 0,841 -> 0,863), a 12 meses
# queda igual (0,965 -> 0,963) y a 3 meses, parejo. Solos anticipan menos que lo que ya habia (MVRV 0,77 a 12 meses;
# las tres medidas de precio, 0,97 con el ciclo). Hash ribbons y emision de stablecoins no anticiparon de forma
# pareja (en 2023-26, al reves): quedan afuera.
ONCHAIN = ("mvrv", "puell")
ZONAS = [(0, 20, "Compra fuerte"), (20, 40, "Buena zona de compra"), (40, 60, "Neutral"), (60, 80, "Caro: cuidado"), (80, 101, "Zona de venta")]


# Termometro de XRP y SOL: su propio "barato o caro" (con su historia) y el mismo momento del ciclo de BTC.
# Medido 2019-2026 sin mirar el futuro (AUC a 12 meses): XRP 0,95 con las tres medidas; SOL 0,88 sin la media de 200
# semanas (no tiene historia suficiente para compararla). ZEC no: su "barato" siguio abaratandose años (AUC 0,6).
ALTS = {"XRP": ("wma200", "dd_ath", "ret365"), "SOL": ("dd_ath", "ret365")}


def metricas(c):
    """Las tres medidas para cada dia (np.nan si falta historia)."""
    n = len(c); cs = np.r_[0, np.cumsum(c)]
    wma = np.array([(cs[i + 1] - cs[i + 1 - 1400]) / 1400 if i >= 1399 else np.nan for i in range(n)])
    return {"wma200": np.log(c / wma), "dd_ath": c / np.maximum.accumulate(c) - 1,
            "ret365": np.r_[np.full(365, np.nan), np.log(c[365:] / c[:-365])]}


def temperatura(pcts):
    return float(np.mean(pcts))


# Medidor final de compra/venta: mitad "logica inversa" (cuanto mas barato esta BTC frente a su historia, mas compra:
# 1 - temperatura) y mitad momento del ciclo de 4 años (un modelo logistico con el año del ciclo y que tan avanzado va
# el año bajista y el 3er alcista: al final del bajista suele estar el piso; al final del 3er alcista, el techo).
# Probado año por año 2019-2026, entrenando el ciclo solo con lo anterior: separa mucho mejor que cada parte sola
# (AUC 0,96 contra 0,74 la temperatura y 0,80 el ciclo). Cualquier mezcla entre 30% y 70% da mas de 0,93.
PESO_VALUACION = 0.5
# Funding promedio de 7 dias (BTCUSDT perpetuo, 2020-2026): negativo (miedo) suma 0,03 al medidor de compra y 0,03% o
# mas cada 8 h (euforia) resta 0,03. Medido: dentro de cada zona, con funding negativo BTC subio mas a 1-3 meses
# (Compra fuerte 95% contra 63% a 30 dias); con funding alto, menos. AUC a 30/90/180 dias +0,005; a 12 meses -0,007.
FUNDING = {"peso": 0.03, "bajo": 0.0, "alto": 0.0003}
ZONAS_S = [(0.75, 9.0, "Compra fuerte"), (0.60, 0.75, "Buen momento de compra"), (0.45, 0.60, "Cuidado: caro"), (-9.0, 0.45, "Zona de venta")]


# Minimo probable en los proximos 6 meses (para elegir el apalancamiento): mitad lo que cayo cada moneda en su historia
# (el minimo de las proximas 180 velas diarias contra el cierre) y mitad lo mismo en unidades de su volatilidad de un año
# (juntando BTC, SOL, XRP y ZEC). Medido año por año 2019-2026 sin mirar el futuro: el piso del 90% se rompio el 9,8% de
# las veces en 2019-22 y el 6,6% en 2023-26 (el del 95%: 5,0% y 0,8%; el del 80%: 22% y 19%). Probado contra la
# historia sola, la volatilidad de 90 o 180 dias, el estado del termometro y una regresion por cuantiles (esta ultima se
# sobreajusta): esta mezcla fue la mas pareja en los dos tramos.
PISO_H = 180
PISO_GRID = [0.005] + [k / 100 for k in range(1, 100)] + [0.995]
PISO_DESDE = {"BTC": 1325376000000, "ZEC": 1483228800000}       # BTC desde 2012; ZEC desde 2017 (antes, velas raras)


PISO_ZONAS = ((0, 40, "barato"), (40, 60, "medio"), (60, 101, "caro"))     # temperatura del ciclo de BTC


def piso_modelo(series, t_btc=None, T_btc=None):
    """series: {moneda: [[t, o, h, l, c, v], ...]} diarias. Cuantiles del minimo a 180 dias (log del minimo / cierre)
    de cada moneda y, juntando todas, en unidades de su volatilidad de 365 dias; y la volatilidad de hoy.
    Con la temperatura del ciclo de BTC de cada dia (sin mirar el futuro) tambien por zona del ciclo: 'zc' son los
    cuantiles de la zona de hoy, si en los dos tramos (hasta 2019 y desde 2020) esa zona tuvo mas o menos caidas
    fuertes que lo normal para el mismo lado; si no, no se usa (queda 'z')."""
    own, zs, vol_hoy = {}, [], {}
    temp = {int(a): float(b) for a, b in zip(t_btc, T_btc) if np.isfinite(b)} if t_btc is not None else {}
    zona_de = lambda x: next(k for k, (lo, hi, _) in enumerate(PISO_ZONAS) if lo <= x < hi)
    cond = []                                    # (z, zona, tramo)
    for m, rows in series.items():
        rows = [r for r in rows if r[0] >= PISO_DESDE.get(m, 0)]
        c = np.array([r[4] for r in rows], float); lo = np.array([r[3] for r in rows], float); n = len(c)
        if n < 365 + PISO_H + 30:
            continue
        lr = np.diff(np.log(c))
        vol = np.array([lr[i - 365:i].std() * np.sqrt(PISO_H) if i >= 365 else np.nan for i in range(n)])
        y = np.array([np.log(lo[i + 1:i + 1 + PISO_H].min() / c[i]) if i + PISO_H < n else np.nan for i in range(n)])
        ok = np.isfinite(y)
        own[m] = [round(float(x), 6) for x in np.quantile(y[ok], PISO_GRID)]
        ok2 = ok & np.isfinite(vol); zs.append(y[ok2] / vol[ok2])
        vol_hoy[m] = round(float(vol[-1]), 6)
        for i in np.where(ok2)[0]:
            tt = temp.get(int(rows[i][0]))
            if tt is not None:
                cond.append((y[i] / vol[i], zona_de(tt), 0 if rows[i][0] < 1577836800000 else 1))
    todos = np.concatenate(zs)
    z = [round(float(x), 6) for x in np.quantile(todos, PISO_GRID)]
    out = {"dias": PISO_H, "grid": PISO_GRID, "z": z, "own": own, "vol": vol_hoy, "analogos": analogos(series)}
    if cond and temp:
        C = np.array(cond); hoy = zona_de(temp[max(temp)])
        print("\n===== mínimo a 180 días según la zona del ciclo de BTC (en volatilidades; % de días que cayó más que el 10% y el 5% peor de siempre) =====")
        q10, q05 = np.quantile(todos, 0.10), np.quantile(todos, 0.05)
        usar = {}
        for k, (_, _, nom) in enumerate(PISO_ZONAS):
            txt, lados = f"  {nom:<7}", []
            for tr, tn in ((0, "hasta 2019"), (1, "2020-26")):
                s = C[(C[:, 1] == k) & (C[:, 2] == tr), 0]
                if len(s) < 200:
                    txt += f" | {tn}: pocos ({len(s)})"; lados.append(0); continue
                p10 = float(np.mean(s < q10)) * 100
                txt += f" | {tn}: {len(s)} días · mediana {np.median(s):+.2f} · peor que el 10%: {p10:.1f}% · peor que el 5%: {float(np.mean(s < q05)) * 100:.1f}%"
                lados.append(-1 if p10 <= 8 else 1 if p10 >= 12.5 else 0)
            usar[k] = lados[0] != 0 and lados[0] == lados[1]
            print(txt + ("  → se usa" if usar[k] else "  → no se usa (no repite en los dos tramos)"), flush=True)
        out["zona"] = PISO_ZONAS[hoy][2]
        if usar.get(hoy):
            out["zc"] = [round(float(x), 6) for x in np.quantile(C[C[:, 1] == hoy, 0], PISO_GRID)]
        print(f"  hoy: zona {out['zona']} (temperatura {temp[max(temp)]:.0f}) → {'cuantiles de la zona' if 'zc' in out else 'cuantiles de siempre'}")
    return out


def analogos(series):
    """Para comparar con años anteriores (bajistas y alcistas): cuanto cayo cada moneda en los 180 dias siguientes a
    cada fecha del año (cada 7 dias). No entra en las probabilidades: separar año bajista, semestre o mes no mejoro en
    los dos tramos (2019-22 mejora con el año bajista; 2023-26 empeora)."""
    import datetime as dt
    out = {}
    for m, rows in series.items():
        rows = [r for r in rows if r[0] >= PISO_DESDE.get(m, 0)]
        dia = {int(r[0] // 86400000): k for k, r in enumerate(rows)}
        lo = [r[3] for r in rows]; c = [r[4] for r in rows]; n = len(rows); a = {}
        for y in range(dt.datetime.fromtimestamp(rows[0][0] / 1000, dt.timezone.utc).year, 2100):
            base = int(dt.datetime(y, 1, 1, tzinfo=dt.timezone.utc).timestamp() // 86400)
            fila = []
            for doy in range(1, 367, 7):
                i = dia.get(base + doy - 1)
                if i is not None and i + PISO_H < n:
                    fila.append([doy, round((min(lo[i + 1:i + 1 + PISO_H]) / c[i] - 1) * 100, 1)])
            if fila:
                a[str(y)] = fila
            if base * 86400000 > rows[-1][0]:
                break
        out[m] = a
    return out


def X_ciclo(años, avance):
    """Señales del ciclo: año del ciclo (alcista 1, 2, 3; el bajista es la base) y avance del año (0 a 1) en el
    bajista y en el 3er alcista."""
    ph = (np.asarray(años) - 2) % 4; av = np.asarray(avance, float)
    return np.column_stack([(ph == k).astype(float) for k in (1, 2, 3)] + [(ph == 0) * av, (ph == 3) * av])


def avance_año(ms):
    """Que parte del año (UTC) paso: 0 el 1 de enero, casi 1 el 31 de diciembre."""
    import datetime as dt
    d = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
    return (d.timetuple().tm_yday - 1) / 366


def fase(y):
    """Ciclo de 4 años de BTC: 2014, 2018, 2022, 2026... bajistas; los tres de en medio, alcistas 1, 2 y 3."""
    return "bajista" if y % 4 == 2 else f"alcista {(y - 3) % 4 + 1}"


def ciclo(t, c, fng):
    """Lo que paso en cada fase del ciclo y con el Fear & Greed Index extremo segun la fase (12 meses despues)."""
    import datetime as dt
    yr = np.array([dt.datetime.fromtimestamp(x / 1000, dt.timezone.utc).year for x in t])
    años = [[int(y), fase(int(y)), round(float(c[yr == y][-1] / c[yr == y][0] - 1) * 100)] for y in range(2012, int(yr[-1])) if (yr == y).sum() > 300]
    # maximos y pisos de cada ciclo (el maximo, en el año anterior al bajista; el piso, lo mas bajo en los 20 meses siguientes)
    ciclos, piso_ant = [], None
    for y in range(2014, int(yr[-1]) + 1, 4):
        m = yr == y - 1
        if not m.any():
            continue
        i = int(np.where(m)[0][np.argmax(c[m])]); j = i + int(np.argmin(c[i:i + 600]))
        mes = lambda a, b: round(float(b - a) / 86400000 / 30.44, 1)
        ciclos.append({"pico_t": int(t[i]), "pico": round(float(c[i])), "piso_t": int(t[j]), "piso": round(float(c[j])),
                       "caida": round(float(c[j] / c[i] - 1) * 100), "meses_bajista": mes(t[i], t[j]),
                       "meses_alcista_antes": mes(piso_ant, t[i]) if piso_ant else None, "confirmado": bool(t[-1] - t[j] > 365 * 86400000)})
        piso_ant = t[j]
    out = {"años": años, "ciclos": ciclos, "reglas": {}}
    if fng is None:
        return out
    for clave, m in (("miedo_bajista", (fng < 25) & (yr % 4 == 2)), ("codicia_alcista3", (fng > 75) & (yr % 4 == 1)),
                     ("codicia_alcista12", (fng > 75) & np.isin(yr % 4, (3, 0)))):
        r = {}
        for hz in (90, 365):
            fut = np.r_[c[hz:] / c[:-hz] - 1, np.full(hz, np.nan)]; k = m & np.isfinite(fut)
            r[f"sube_{hz}"] = round(float(np.mean(fut[k] > 0)) * 100) if k.sum() >= 30 else None
            r[f"mediana_{hz}"] = round(float(np.median(fut[k])) * 100) if k.sum() >= 30 else None
        k = np.where(m)[0]
        dd = [np.min(c[i:i + 365]) / c[i] - 1 for i in k if i + 365 <= len(c)]
        r["caida_mediana"] = round(float(np.median(dd)) * 100) if len(dd) >= 30 else None
        r["dias"] = int(m.sum()); r["años"] = sorted({int(y) for y in yr[m]})
        out["reglas"][clave] = r
    return out


def temperatura_historica(c, comps):
    """Temperatura de cada dia comparando solo con la historia que habia hasta ese dia; y la historia completa."""
    M = metricas(c); hist = {k: [] for k in comps}; T = np.full(len(c), np.nan)
    for i in range(len(c)):
        p = []
        for k in comps:
            v = M[k][i]
            if np.isfinite(v):
                if len(hist[k]) >= 365: p.append(bisect.bisect_left(hist[k], v) / len(hist[k]) * 100)
                bisect.insort(hist[k], v)
        if len(p) == len(comps): T[i] = temperatura(p)
    return T, hist


def zonas_medidor(S, c, ok):
    zs = []
    for lo, hi, nom in ZONAS_S:
        z = {"desde": lo, "hasta": hi, "nombre": nom}
        for hz in (180, 365):
            fut = np.r_[c[hz:] / c[:-hz] - 1, np.full(hz, np.nan)]
            m = ok & np.isfinite(S) & (S >= lo) & (S < hi) & np.isfinite(fut)
            z[f"sube_{hz}"] = round(float(np.mean(fut[m] > 0)) * 100) if m.sum() >= 30 else None
            z[f"mediana_{hz}"] = round(float(np.median(fut[m])) * 100) if m.sum() >= 30 else None
            z[f"dias_{hz}"] = int(m.sum())
            ix = np.flatnonzero(m)
            z[f"episodios_{hz}"] = int(1 + np.sum(np.diff(ix) > 30)) if len(ix) else 0   # rachas separadas por más de 30 días
        zs.append(z)
    return zs


def alt(rows, comps, t_btc, Pc):
    """Termometro de una alt: cuantiles de su historia, zonas del medidor medidas desde 2019 (ciclo de BTC sin mirar el
    futuro) y sus ultimos 1500 cierres diarios (el analisis en vivo trae menos dias de los que necesita la media)."""
    t = np.array([b[0] for b in rows], float); c = np.array([b[4] for b in rows], float)
    T, hist = temperatura_historica(c, comps)
    pc_dia = {int(x // 86400000): p for x, p in zip(t_btc, Pc)}
    pc = np.array([pc_dia.get(int(x // 86400000), np.nan) for x in t])
    S = PESO_VALUACION * (1 - T / 100) + (1 - PESO_VALUACION) * pc
    return {"componentes": list(comps), "ath": float(c.max()), "zonas": zonas_medidor(S, c, t >= 1546300800000),
            "q": {k: [round(float(x), 8) for x in np.quantile(np.array(hist[k]), np.linspace(0, 1, 201))] for k in comps},
            "cierres": [[int(x // 86400000), float(v)] for x, v in zip(t[-1500:], c[-1500:])]}


def onchain(t, c, path):
    """MVRV y Puell de cada dia (log, np.nan si falta) y lo que necesita el analisis en vivo para estimarlos hoy."""
    import datetime as dt
    O = json.load(open(path))
    dia = (t // 86400000).astype(int)
    def serie(k):
        m = {int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp() // 86400): v for d, v in O.get(k) or []}
        return np.array([m.get(x, np.nan) for x in dia]), m
    mvrv, m_mvrv = serie("cm_CapMVRVCur"); iss, m_iss = serie("cm_IssTotUSD")
    _, m_cap = serie("cm_CapMrktCurUSD"); _, m_sup = serie("cm_SplyCur")
    ma = np.array([np.nanmean(iss[i - 364:i + 1]) if i >= 364 and np.isfinite(iss[i - 364:i + 1]).sum() > 330 else np.nan for i in range(len(iss))])
    M = {"mvrv": np.log(mvrv), "puell": np.log(iss / ma)}
    u = max(d for d in m_mvrv if d in m_cap and d in m_sup and d in m_iss)
    rp = lambda d: m_cap[d] / m_mvrv[d] / m_sup[d]                 # precio realizado: costo promedio de cada BTC
    precio = {int(x // 86400000): v for x, v in zip(t, c)}
    dias_iss = [d for d in range(u - 29, u + 1) if d in m_iss and d in precio]
    vivo = {"dia": u, "rp": rp(u), "rp_pend": (rp(u) - rp(u - 30)) / 30 if (u - 30) in m_mvrv else 0.0,
            "btc_dia": float(np.mean([m_iss[d] / precio[d] for d in dias_iss])),
            "iss_suma364": float(sum(m_iss.get(d, 0.0) for d in range(u - 363, u + 1)))}
    # bandas de desvio extremo del MVRV (Checkonchain): media y desvio del MVRV de toda la historia (desde 2011) y el
    # precio realizado de cada semana desde 2017, para dibujarlas (precio realizado x (media + k desvios)).
    # Medido (medir_mvrv_bandas.py): ver termometro.MVRV_BANDAS
    hist = [m_mvrv[d] for d in sorted(m_mvrv) if d >= 14975]
    vivo["mvrv_media"], vivo["mvrv_desvio"] = float(np.mean(hist)), float(np.std(hist))
    vivo["rp_sem"] = [[d, round(rp(d), 2)] for d in sorted(m_mvrv) if d >= 17167 and (d - 17167) % 7 == 0 and d in m_cap and d in m_sup] + [[u, round(rp(u), 2)]]
    # zonas de compra y de venta del ciclo (zonas_ciclo.py, medidas): con toda la historia diaria de CoinMetrics
    import zonas_ciclo
    _, m_adr = serie("cm_AdrActCnt")
    ds = sorted(d for d in m_cap if d in m_sup and m_sup[d] > 0 and d >= 14809)        # desde el 18/7/2010
    _, m_hr = serie("cm_HashRate"); _, m_usdt = serie("cm_usdt_SplyCur"); _, m_usdc = serie("cm_usdc_SplyCur")
    st = np.array([(m_usdt.get(d, 0.0) + m_usdc.get(d, 0.0)) or np.nan for d in ds])
    # looknode y bitcoin-data (datos_entrenamiento.onchain_extra): si no bajaron, esas zonas se omiten (nunca rompen la corrida)
    extra = {}
    for zid, k in (("cvdd", "lk_CVDD"), ("balanceado", "lk_balancedPrice"), ("sth", "lk_sthCostPriceV2"), ("rhodl", "lk_rhodl"),
                   ("asopr", "lk_ASOPR"), ("perdida", "lk_realizedLos"), ("ganancia", "bg_supplyProfit")):
        try:
            _, m = serie(k)
            if m:
                extra[zid] = np.array([m.get(d, np.nan) / (m_sup[d] if zid == "ganancia" else 1.0) for d in ds])
        except Exception as e:
            print(f"(zona {zid}: {type(e).__name__})")
    vivo["zonas"] = zonas_ciclo.calcular(np.array(ds), np.array([m_cap[d] / m_sup[d] for d in ds]), np.array([m_sup[d] for d in ds]),
                                         np.array([m_iss.get(d, np.nan) for d in ds]), np.array([m_adr.get(d, np.nan) for d in ds]),
                                         np.array([m_hr.get(d, np.nan) for d in ds]) if m_hr else None, st if m_usdt else None, extra)
    # % de la oferta en ganancia: bitcoin-data limita los pedidos; si esta semana no bajo, queda el ultimo valor (hasta 45 dias)
    if not any(z["id"] == "ganancia" for z in vivo["zonas"]):
        try:
            previo = next(z for z in json.load(open("JavascriptVersion/termometro.json", encoding="utf-8"))["onchain"]["zonas"] if z["id"] == "ganancia")
            if ds[-1] - previo["dia"] <= 45:
                vivo["zonas"].append(previo)
        except Exception:
            pass
    return M, vivo


def _ms(año):
    return (np.datetime64(f"{año}-01-01") - np.datetime64("1970-01-01")).astype("timedelta64[ms]").astype(float)


def medir_cortos(S, c, t, tramos=None):
    """¿La zona del medidor anticipa el dia, la semana y el mes? (el analisis la sumaba a la direccion de 4 horas a 1
    mes). Cada dia en cada zona, con el medidor sin mirar el futuro (desde 2019): % de veces que BTC fue para el lado
    de la zona a 1, 7 y 30 dias contra lo normal de ese tramo. Los dias se pisan: n efectivo = dias / horizonte."""
    print("\n===== ¿La zona del medidor anticipa el día, la semana y el mes? =====")
    tramos = tramos or (("2019-22", 1546300800000, 1672531200000), ("2023-26", 1672531200000, 4102444800000))
    grupos = [("COMPRA (las dos zonas)", S >= 0.60, 1), ("CARO O VENTA (las dos zonas)", S < 0.60, -1)]
    grupos += [(nom, (S >= lo) & (S < hi), 1 if lo >= 0.60 else -1) for lo, hi, nom in ZONAS_S]
    for hz in (1, 7, 30):
        fut = np.r_[c[hz:] / c[:-hz] - 1, np.full(hz, np.nan)]
        for nom, m, lado in grupos:
            txt = f"  {hz:>2} d  {nom:<30}"
            for tn, a, b in tramos:
                ok = np.isfinite(S) & np.isfinite(fut) & (t >= a) & (t < b)
                sel = ok & m
                if sel.sum() < 30:
                    txt += f" | {tn}: pocos ({int(sel.sum())})"
                    continue
                base = float(np.mean(fut[ok] > 0)); base = base if lado > 0 else 1 - base
                ac = float(np.mean((fut[sel] > 0) == (lado > 0)))
                z = (ac - base) / np.sqrt(max(1e-9, base * (1 - base) / max(1.0, sel.sum() / hz)))
                txt += f" | {tn}: {int(sel.sum())} d, fue para ese lado {100 * ac:.1f}% (normal {100 * base:.1f}%, z {z:+.1f})"
            print(txt, flush=True)


def main():
    B = json.load(open(sys.argv[1])); t = np.array([b[0] for b in B], float); c = np.array([b[4] for b in B], float)
    fng = None
    if len(sys.argv) > 2:
        fv = {int(d["timestamp"]) * 1000: int(d["value"]) for d in json.load(open(sys.argv[2]))["data"]}
        fng = np.array([fv.get(int(x), np.nan) for x in t])
    M = metricas(c)
    comps, vivo = COMP, None
    if len(sys.argv) > 4:
        Mo, vivo = onchain(t, c, sys.argv[4])
        M.update(Mo); comps = COMP + ONCHAIN
    # temperatura de cada dia con la historia que habia hasta ese dia (sin mirar el futuro), para medir las zonas
    hist = {k: [] for k in comps}; T = np.full(len(c), np.nan)
    for i in range(len(c)):
        p = []
        for k in comps:
            v = M[k][i]
            if np.isfinite(v):
                if len(hist[k]) >= 365: p.append(bisect.bisect_left(hist[k], v) / len(hist[k]) * 100)
                bisect.insort(hist[k], v)
        if len(p) == len(comps): T[i] = temperatura(p)
    # medidor: mitad valuacion (1 - temperatura) y mitad ciclo; zonas medidas año por año desde 2019 sin mirar el futuro
    from sklearn.linear_model import LogisticRegression
    import datetime as dt
    años = np.array([dt.datetime.fromtimestamp(x / 1000, dt.timezone.utc).year for x in t])
    fut365 = np.r_[c[365:] / c[:-365] - 1, np.full(365, np.nan)]; fut180 = np.r_[c[180:] / c[:-180] - 1, np.full(180, np.nan)]
    Xc = X_ciclo(años, [avance_año(x) for x in t]); okc = t >= 1325376000000          # ciclo desde 2012
    Pc = np.full(len(c), np.nan)
    for Y in range(2019, int(años[-1]) + 1):
        a = dt.datetime(Y, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000
        tr = okc & np.isfinite(fut365) & (t + 365 * 86400000 < a); te = okc & (años == Y)
        if tr.sum() > 300 and te.any():
            Pc[te] = LogisticRegression(max_iter=4000).fit(Xc[tr], fut365[tr] > 0).predict_proba(Xc[te])[:, 1]
    S = PESO_VALUACION * (1 - T / 100) + (1 - PESO_VALUACION) * Pc
    zonas_s = []
    for lo, hi, nom in ZONAS_S:
        z = {"desde": lo, "hasta": hi, "nombre": nom}
        for hz, fut in ((180, fut180), (365, fut365)):
            m = np.isfinite(S) & (S >= lo) & (S < hi) & np.isfinite(fut)
            z[f"sube_{hz}"] = round(float(np.mean(fut[m] > 0)) * 100) if m.sum() >= 30 else None
            z[f"mediana_{hz}"] = round(float(np.median(fut[m])) * 100) if m.sum() >= 30 else None
            z[f"dias_{hz}"] = int(m.sum())
        zonas_s.append(z)
    medir_cortos(S, c, t)
    # lo mismo con el ciclo entrenado año por año desde 2015 (mas ciclos: 2015-18, 2019-22 y 2023-26)
    Pl = np.full(len(c), np.nan)
    for Y in range(2015, int(años[-1]) + 1):
        tr = okc & (años < Y) & np.isfinite(fut365) & (t + 365 * 86400000 < _ms(Y))
        te = okc & (años == Y)
        if tr.sum() > 300 and te.sum() and len(set((fut365[tr] > 0).tolist())) == 2:
            Pl[te] = LogisticRegression(max_iter=4000).fit(Xc[tr], fut365[tr] > 0).predict_proba(Xc[te])[:, 1]
    medir_cortos(PESO_VALUACION * (1 - T / 100) + (1 - PESO_VALUACION) * Pl, c, t,
                 (("2015-18", _ms(2015), _ms(2019)), ("2019-22", _ms(2019), _ms(2023)), ("2023-26", _ms(2023), _ms(2100))))
    trf = okc & np.isfinite(fut365)
    fin = LogisticRegression(max_iter=4000).fit(Xc[trf], fut365[trf] > 0)
    modelo = {"intercepto": round(float(fin.intercept_[0]), 6), "pesos": [round(float(w), 6) for w in fin.coef_[0]],
              "peso_valuacion": PESO_VALUACION, "funding": FUNDING, "zonas": zonas_s}
    # las zonas se miden desde 2019: antes la media de 200 semanas tenia menos de un ciclo de historia para comparar
    # (en 2016-17 casi todo salia "caro" en plena suba)
    desde = 1546300800000
    zonas = []
    for lo, hi, nom in ZONAS:
        z = {"desde": lo, "hasta": min(hi, 100), "nombre": nom}
        for hz in (180, 365):
            fut = np.r_[c[hz:] / c[:-hz] - 1, np.full(hz, np.nan)]
            m = (T >= lo) & (T < hi) & np.isfinite(fut) & (t >= desde)
            z[f"sube_{hz}"] = round(float(np.mean(fut[m] > 0)) * 100) if m.sum() >= 30 else None
            z[f"mediana_{hz}"] = round(float(np.median(fut[m])) * 100) if m.sum() >= 30 else None
            z[f"dias_{hz}"] = int(m.sum())
        zonas.append(z)
    out = {"medidor": modelo, "ciclo": ciclo(t, c, fng), "hasta": int(t[-1]), "zonas_desde": desde, "ath": float(c.max()), "componentes": list(comps), "zonas": zonas,
           "q": {k: [round(float(x), 6) for x in np.quantile(np.array(hist[k]), np.linspace(0, 1, 201))] for k in comps}}
    if vivo:
        out["onchain"] = vivo
    json.dump(out, open("JavascriptVersion/termometro.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    if len(sys.argv) > 3:
        A = json.load(open(sys.argv[3]))
        out["alts"] = {m: alt(A[m], cs, t, Pc) for m, cs in ALTS.items() if len(A.get(m) or []) > 1500}
        json.dump(out, open("JavascriptVersion/termometro.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        out["piso"] = piso_modelo({"BTC": B, **{m: A[m] for m in ("SOL", "XRP", "ZEC") if len(A.get(m) or []) > 600}}, t, T)
        json.dump(out, open("JavascriptVersion/termometro.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        print("piso: vol de hoy", out["piso"]["vol"])
        for m, v in out["alts"].items():
            print(m, [(z["nombre"], z["sube_365"], z["mediana_365"], z["dias_365"]) for z in v["zonas"]])
    print(json.dumps(zonas_s, ensure_ascii=False, indent=1)); print("hoy: temperatura", round(float(T[-1]), 1), "ciclo", modelo["intercepto"], modelo["pesos"])


if __name__ == "__main__":
    main()
