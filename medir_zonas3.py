"""Zonas de PISO y TECHO (estilo Glassnode, on-chain y atencion) medidas como ZONAS, con el metodo de medir_zonas2.py.

Candidatos: CVDD, precio balanceado, SOPR y aSOPR (7 y 30 d), RHODL, plata joven (bandas 1-3 de realCapHODL), precio contra
las lineas de costo de los tenedores de corto plazo (sthCostPrice v1..v4, sthCostPriceV2, sthTwoPrice), ganancia y perdida
realizada (pico de 7 d contra el ultimo año), % de la oferta en ganancia (bitcoin-data), atencion de Wikipedia, reserva y
netflow de exchanges, SSR, liquidez neta de la Fed (13 semanas) y VIX (nivel y VIX / VIX3M).

Metodo (igual que medir_zonas2.py):
  - Zona por percentil de la propia historia hasta cada dia (rank_exp de medir_zonas, sin mirar el futuro; 15/85 y 10/90) y
    zonas clasicas de umbral fijo. Se miden los DOS lados (baja y alta) porque una zona puede servir al reves de su fama.
  - Cada dia dentro de la zona: ¿BTC estaba mas arriba 365 dias despues? contra un dia cualquiera del mismo tramo.
    COMPRA si en los dos tramos sube 10 puntos o mas que lo normal; VENTA si 10 o mas menos. Tramos 2012-19 y 2020-25; si la
    serie empieza despues de 2013-06 (como en medir_zonas2): 2019-21 y 2022-25.
  - "Suma al puntaje de las 9 zonas": puntaje = zonas de compra - zonas de venta de las 9 de medir_zonas2 (MVRV, Puell, Mayer,
    2 años, 200 semanas, Golden, Pi, ley de potencia, Metcalfe); ¿el candidato (con su signo medido) mejora el AUC de "sube a 365
    y a 180 dias" en cada tramo, o al menos no lo empeora?
  - ESTADOS (informativo): con las etiquetas de medir_diarios (etiquetas_estados): P(piso | zona de compra prendida), P(piso
    extremo | ...) y P(techo | zona de venta prendida) contra la tasa base del tramo; z con bloques de 90 dias (igual que
    evaluar_estados de medir_diarios).
  - Un dato se usa desde el dia siguiente a su fecha (como medir_onchain_ciclo; zonas2 no hace ese retraso: es mas estricto).

Datos sin clave: looknode, bitcoin-data.com (UN pedido: supply-profit, con cache local), CoinMetrics, Wikipedia, CBOE, NY Fed, FiscalData.
Uso: python medir_zonas3.py
     python medir_zonas3.py --prueba      (sin internet: series sinteticas para probar el codigo de punta a punta)
"""
import bisect
import json
import math
import random
import sys
import zlib
from datetime import date

import medir_diarios as md                     # etiquetas, fetchers y alinear (comparte argv: --prueba)
import medir_onchain_ciclo as oc               # fetchers de looknode y bitcoin-data, cache, helpers
from medir_zonas import rank_exp, sma          # percentil sin mirar el futuro y media simple (igual que zonas2)

PRUEBA = "--prueba" in sys.argv
CACHE = "cache_zonas3.json"
# copiados de medir_zonas2.py (no se importa: arrastra numpy y noticias)
TRAMOS_LARGOS = (("2012-19", "2012-01-01", "2020-01-01"), ("2020-25", "2020-01-01", "2100-01-01"))
TRAMOS_CORTOS = (("2019-21", "2019-01-01", "2022-01-01"), ("2022-25", "2022-01-01", "2100-01-01"))
PTS = 0.10                  # diferencia minima contra un dia cualquiera (10 puntos)
TOL_AUC = -0.003            # "no empeora": la peor diferencia de AUC no baja de esto
G = {}


def pctl(vals, p):
    """percentil p (0-100) con interpolacion lineal, como numpy."""
    v = sorted(vals)
    if not v:
        return None
    k = (len(v) - 1) * p / 100
    a, b = int(math.floor(k)), int(math.ceil(k))
    return v[a] + (v[b] - v[a]) * (k - a)


def fnum(x):
    return f"{x:.4g}".replace(".", ",")


# ---------------------------------------------------------------- las 9 zonas de hoy (igual que medir_zonas2.main)
def puntaje_nueve(dias, P, cm):
    """cm: dict nombre -> serie diaria ya alineada sobre el calendario (sin retraso). Devuelve el puntaje (compra +1, venta -1)."""
    n = len(dias)
    cap, mv, issu, adr = (cm[k] for k in ("CapMrktCurUSD", "CapMVRVCur", "IssTotUSD", "AdrActCnt"))

    def pct_zona(x, lo_p=None, hi_p=None, lo=None, hi=None):
        r = rank_exp(x)
        z = []
        for v, rk in zip(x, r):
            if v is None or rk is None:
                z.append(0)
                continue
            c = (lo is not None and v <= lo) or (lo_p is not None and rk <= lo_p)
            s = (hi is not None and v >= hi) or (hi_p is not None and rk >= hi_p)
            z.append(1 if c else -1 if s else 0)
        return z

    s_ = s2 = 0.0
    mvz = []
    for k, x in enumerate(mv):
        x = x or 0.0
        s_ += x
        s2 += x * x
        m = s_ / (k + 1)
        sd = math.sqrt(max(1e-12, s2 / (k + 1) - m * m))
        mvz.append((x - m) / sd)
    ZA = {"MVRV": [1 if z <= -0.5 else -1 if z >= 2 else 0 for z in mvz]}
    m365 = sma([x or 0.0 for x in issu], 365)
    puell = [None if not m365[i] or issu[i] is None else issu[i] / m365[i] for i in range(n)]
    ZA["Puell"] = pct_zona(puell, hi_p=85, lo=0.5)
    for nom, k, kw in (("Mayer", 200, {"hi": 2.4}), ("2 años", 730, {"lo": 1.0, "hi_p": 85}), ("200 semanas", 1400, {"lo": 1.0, "hi": 4.0}),
                       ("Golden", 350, {"lo": 0.8, "hi": 3.0})):
        m = sma(P, k)
        ZA[nom] = pct_zona([None if m[i] is None else P[i] / m[i] for i in range(n)], **kw)
    m111, m350 = sma(P, 111), sma(P, 350)
    ZA["Pi"] = pct_zona([None if m350[i] is None else m111[i] / (2 * m350[i]) for i in range(n)], lo=0.35, hi_p=85)
    gen = date(2009, 1, 3)
    lx = [math.log10((date.fromisoformat(d) - gen).days) for d in dias]
    ly = [math.log10(p) for p in P]
    pl, sx, a, b = [None] * n, [0.0] * 5, None, None
    for i in range(n):
        sx[0] += 1; sx[1] += lx[i]; sx[2] += ly[i]; sx[3] += lx[i] ** 2; sx[4] += lx[i] * ly[i]
        if i >= 730 and (i % 30 == 0 or a is None):
            den = sx[0] * sx[3] - sx[1] ** 2
            b = (sx[0] * sx[4] - sx[1] * sx[2]) / den
            a = (sx[2] - b * sx[1]) / sx[0]
        if a is not None:
            pl[i] = ly[i] - (a + b * lx[i])
    ZA["Ley de potencia"] = pct_zona(pl, lo_p=15, hi_p=85)
    a30 = sma([x or 0.0 for x in adr], 30)
    ZA["Metcalfe"] = pct_zona([None if not a30[i] or cap[i] is None else cap[i] / a30[i] ** 2 for i in range(n)], hi_p=85)
    return [sum(ZA[k][i] for k in ZA) for i in range(n)]


# ---------------------------------------------------------------- medicion
def fut(i, h):
    P, n = G["P"], len(G["P"])
    return P[i + h] > P[i] if i + h < n and P[i] is not None and P[i + h] is not None else None


def auc(score, idx, h):
    pos = [score[i] for i in idx if fut(i, h)]
    neg = [score[i] for i in idx if fut(i, h) is False]
    if not pos or not neg:
        return None
    todos = sorted(pos + neg)
    rk, i = {}, 0
    while i < len(todos):
        j = i
        while j < len(todos) and todos[j] == todos[i]:
            j += 1
        rk[todos[i]] = (i + j + 1) / 2
        i = j
    sp = sum(rk[v] for v in pos)
    return (sp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def episodios(sel, hueco=90):
    n, ult = 0, None
    for i in sel:
        if ult is None or i - ult > hueco:
            n += 1
        ult = i
    return n


def celda_estado(on, lab, a0, b0):
    """P(estado | zona prendida) contra la tasa base del tramo, z con bloques de 90 dias (como evaluar_estados de medir_diarios)."""
    dias = G["dias"]
    idx = [i for i in range(len(dias)) if a0 <= dias[i] < b0 and on[i] is not None and lab[i] is not None]
    sel = [i for i in idx if on[i]]
    ne = len({i // 90 for i in sel})
    if len(idx) < 100 or ne < 4:
        return f"pocos (b {ne})", None
    base = sum(lab[i] for i in idx) / len(idx)
    p = sum(lab[i] for i in sel) / len(sel)
    if not 0 < base < 1:
        return "base 0/1", None
    z = (p - base) / math.sqrt(base * (1 - base) / ne)
    return f"{100 * p:.0f}% (base {100 * base:.0f}%) z {z:+.1f} [b{ne}]", z


def variantes(x, r, clasicas):
    """[(nombre, spec, zona)] con zona +1 = baja, -1 = alta, 0 = nada (como zonas2)."""
    out = []
    for lo_p, hi_p in ((15, 85), (10, 90)):
        out.append((f"percentil {lo_p}/{hi_p}", ("p", lo_p, hi_p),
                    [0 if rk is None else 1 if rk <= lo_p else -1 if rk >= hi_p else 0 for rk in r]))
    for lo, hi in clasicas:
        nom = "clásica (" + " / ".join(t for t in (f"<= {fnum(lo)}" if lo is not None else "", f">= {fnum(hi)}" if hi is not None else "") if t) + ")"
        out.append((nom, ("f", lo, hi), [0 if v is None else 1 if lo is not None and v <= lo else -1 if hi is not None and v >= hi else 0 for v in x]))
    return out


def evaluar_candidato(c, base_tr, puntaje, labs):
    nom, x = c["nom"], c["x"]
    dias, n = G["dias"], len(G["dias"])
    primero = next((dias[i] for i, v in enumerate(x) if v is not None), "2100")
    tramos = TRAMOS_LARGOS if primero < "2013-06-01" else TRAMOS_CORTOS
    r = rank_exp(x, minimo=365 if primero >= "2017" else 730)
    c.update(primero=primero, tramos=tramos, r=r)
    print(f"\n=== {nom} (desde {primero}; tramos {tramos[0][0]} y {tramos[1][0]}"
          f"{'; serie corta: tramos de medir_zonas2 para series que empiezan despues de 2013-06' if tramos is TRAMOS_CORTOS else ''}) ===", flush=True)
    if c.get("nota"):
        print(f"  ({c['nota']})")
    base = {}
    for tn, a0, b0 in tramos:
        idx = [i for i in range(n) if a0 <= dias[i] < b0 and fut(i, 365) is not None]
        base[tn] = sum(fut(i, 365) for i in idx) / len(idx) if idx else None
    print("  un día cualquiera a 1 año: " + " · ".join(f"{tn} sube {'—' if base[tn] is None else f'{100 * base[tn]:.0f}%'}" for tn, _, _ in tramos))
    res = []
    for vn, spec, zona in variantes(x, r, c["clasicas"]):
        lados, ups, difs_z = {}, {}, {}
        for lado, val in (("baja", 1), ("alta", -1)):
            difs, partes, up_t = [], [], []
            for tn, a0, b0 in tramos:
                idx = [i for i in range(n) if a0 <= dias[i] < b0 and fut(i, 365) is not None]
                sel = [i for i in idx if zona[i] == val]
                if len(sel) < 20 or base[tn] is None:
                    difs.append(None)
                    up_t.append(None)
                    partes.append(f"{tn}: pocos ({len(sel)} d)")
                    continue
                up = sum(fut(i, 365) for i in sel) / len(sel)
                difs.append(up - base[tn])
                up_t.append(up)
                partes.append(f"{tn}: sube {100 * up:.0f}% ({100 * (up - base[tn]):+.0f} pts; {len(sel)} d, {episodios(sel)} ep)")
            v = "COMPRA" if all(d is not None and d >= PTS for d in difs) else "VENTA" if all(d is not None and d <= -PTS for d in difs) else "—"
            lados[lado], ups[lado], difs_z[lado] = v, up_t, difs
            print(f"  [{vn}] zona {lado}: " + " · ".join(partes) + f" → {v}")
        signo = {l: 1 if lados[l] == "COMPRA" else -1 if lados[l] == "VENTA" else 0 for l in lados}
        # suma al puntaje de las 9 zonas
        aucs, dif_auc = [], []
        if any(signo.values()) and puntaje is not None:
            nuevo = [puntaje[i] + (signo["baja"] if zona[i] == 1 else signo["alta"] if zona[i] == -1 else 0) for i in range(n)]
            for tn, a0, b0 in tramos:
                for h in (180, 365):
                    idx = [i for i in range(n) if a0 <= dias[i] < b0 and fut(i, h) is not None]
                    a1, a2 = auc(puntaje, idx, h), auc(nuevo, idx, h)
                    if a1 is not None and a2 is not None:
                        aucs.append(f"{tn} {h}d {a1:.3f}→{a2:.3f}")
                        dif_auc.append(a2 - a1)
            sv = "MEJORA" if dif_auc and min(dif_auc) > 0 else "NO EMPEORA" if dif_auc and min(dif_auc) >= TOL_AUC else "EMPEORA" if dif_auc else "sin datos"
            print(f"    suma a las 9 zonas: {' · '.join(aucs)} → {sv}")
        else:
            sv = "no aplica"
            print("    suma a las 9 zonas: " + ("no aplica (no marca zona en los dos tramos)" if puntaje is not None else "sin puntaje de las 9 zonas"))
        # estados: zona de compra = lado COMPRA medido (si no, la hipotesis); zona de venta = lado VENTA medido (si no, la hipotesis)
        lado_c = next((l for l in ("baja", "alta") if lados[l] == "COMPRA"), None)
        lado_v = next((l for l in ("baja", "alta") if lados[l] == "VENTA"), None)
        hip_c, hip_v = lado_c is None, lado_v is None
        lado_c, lado_v = lado_c or c["compra"], lado_v or c["venta"]
        val = {"baja": 1, "alta": -1, None: None}
        for tit, lado, hip, ests in (("compra", lado_c, hip_c, ("piso", "piso extremo")), ("venta", lado_v, hip_v, ("techo",))):
            if lado is None:
                continue
            on = [None if (r[i] if spec[0] == "p" else x[i]) is None else zona[i] == val[lado] for i in range(n)]
            partes = []
            for e in ests:
                cel = []
                for tn, a0, b0 in tramos:
                    cel.append(f"{tn} " + celda_estado(on, labs[e], a0, b0)[0])
                partes.append(f"P({e}) " + " · ".join(cel))
            print(f"    estados zona de {tit} ({lado}{', hipótesis' if hip else ', medida'}): " + " | ".join(partes))
        res.append(dict(vn=vn, spec=spec, zona=zona, lados=lados, ups=ups, difs=difs_z, sv=sv, dif_auc=dif_auc))
    # mejor variante: la que tiene veredicto y mejor peor-diferencia de AUC (como zonas2); si ninguna suma, la de mejor veredicto
    con = [v for v in res if any(l != "—" for l in v["lados"].values())]
    mejor = None
    for v in con:
        if mejor is None or (min(v["dif_auc"]) if v["dif_auc"] else -9) > (min(mejor["dif_auc"]) if mejor["dif_auc"] else -9):
            mejor = v
    c["res"], c["mejor"] = res, mejor
    ver = "no"
    if mejor:
        cs, vs = "COMPRA" in mejor["lados"].values(), "VENTA" in mejor["lados"].values()
        ver = "SIRVE compra y venta" if cs and vs else "SIRVE compra" if cs else "SIRVE venta"
    c["ver"] = ver
    print(f"  >>> VEREDICTO {nom}: {ver}" + (f" · [{mejor['vn']}] suma a las 9 zonas: {mejor['sv']}" if mejor else ""))
    return c


# ---------------------------------------------------------------- armado de candidatos
def armar(cand_out):
    o, P = G["o"], G["P"]
    al = lambda d, lag=1, vence=5: md.alinear(d, o, lag, vence)

    def cand(nom, x, compra, venta, clasicas=(), nota=""):
        if x is None or not any(v is not None for v in x):
            print(f"  {nom}: sin datos, se saltea", flush=True)
            return
        cand_out.append(dict(nom=nom, x=x, compra=compra, venta=venta, clasicas=list(clasicas), nota=nota))
        ix = [i for i, v in enumerate(x) if v is not None]
        print(f"  + {nom}: {G['dias'][ix[0]]} a {G['dias'][ix[-1]]}", flush=True)

    def bloque(nombre, fn):
        try:
            fn()
        except Exception as e:
            print(f"  bloque {nombre} no: {type(e).__name__}: {e}", flush=True)

    cr = oc.cargar_cache() if not PRUEBA else {"dia": "prueba", "look": {}, "bgeo": {}}
    print("\nBajando looknode:", flush=True)
    L = {i: oc.bajar_look(cr, i) for i in ("CVDD", "balancedPrice", "sopr", "ASOPR", "rhodl", "realCapHODL", "sthCostPrice",
                                           "sthTwoPrice", "sthCostPriceV2", "realizedLos", "realizedProfitUsd")}
    ratio = lambda lin: [None if p is None or l is None or l <= 0 else p / l for p, l in zip(P, lin)]

    def b_pisos():
        if L["CVDD"]:
            cand("Precio / CVDD", ratio(al(oc.columna(L["CVDD"], 0))), "baja", "alta", [(1.1, None), (1.2, None)])
        if L["balancedPrice"]:
            cand("Precio / precio balanceado", ratio(al(oc.columna(L["balancedPrice"], 0))), "baja", "alta", [(1.0, None)])
    bloque("CVDD y balanceado", b_pisos)

    def b_sopr():
        for id_, tag in (("sopr", "SOPR"), ("ASOPR", "aSOPR")):
            if L[id_]:
                x = al(oc.columna(L[id_], 0))
                for w in (7, 30):
                    cand(f"{tag} media {w}d", oc.media_rodada(x, w), "baja", "alta", [(1.0, None)])
    bloque("SOPR", b_sopr)

    def b_rhodl():
        if L["rhodl"]:
            cand("RHODL", al(oc.columna(L["rhodl"], 0)), "baja", "alta", nota="sin umbral fijo: la escala cambia por era")
        d = L["realCapHODL"]
        if d:
            ult = d[max(d)]
            if len(ult) >= 4:
                bandas = [al(oc.columna(d, k)) for k in range(3)]
                joven = [None if any(b[i] is None for b in bandas) else sum(b[i] for b in bandas) for i in range(len(P))]
                cand("Plata joven (realCapHODL bandas 1-3, < ~3 meses)", joven, "baja", "alta", nota="alto = plata nueva/techo, bajo = piso")
    bloque("RHODL y HODL", b_rhodl)

    def b_sth():
        for id_, tag in (("sthCostPrice", "sthCostPrice"), ("sthCostPriceV2", "sthCostPriceV2"), ("sthTwoPrice", "sthTwoPrice")):
            d = L[id_]
            if not d:
                continue
            ult = d[max(d)]
            print(f"    {id_}: {len(ult)} líneas; precio actual / cada línea: "
                  + " · ".join(f"v{k + 1}={'—' if v is None or v <= 0 or not P[-1] else f'{P[-1] / v:.2f}'}" for k, v in enumerate(ult)), flush=True)
            for k in range(len(ult)):
                col = oc.columna(d, k)
                if col:
                    cand(f"Precio / {tag} v{k + 1}", ratio(al(col)), "baja", "alta", [(1.0, None)], "línea de costo de tenedores de corto plazo")
    bloque("costo de corto plazo", b_sth)

    def b_real():
        if L["realizedProfitUsd"]:
            cand("Ganancia realizada (pico 7d / año)", oc.pico_vs_año(al(oc.columna(L["realizedProfitUsd"], 0))), None, "alta",
                 nota="pico de ganancia = distribución = venta")
        if L["realizedLos"]:
            cand("Pérdida realizada (pico 7d / año)", oc.pico_vs_año(al(oc.columna(L["realizedLos"], 0))), "alta", None,
                 nota="pico de pérdida = capitulación = compra")
    bloque("realizado", b_real)

    def b_ganancia():
        oc.F_LOOK, oc.F_BGEO = G["F_LOOK"], G["F_BGEO"]
        sp = oc.bajar_bgeo(cr, "supply-profit", reintentar=False)       # UN pedido (limite 10/hora, 15/dia)
        sup = md.intentar("BTC SplyCur", md.f_cm, "btc", "SplyCur", "2010-07-01")
        if not sp or not sup:
            raise ValueError("falta supply-profit o SplyCur")
        sk = sorted(sup)
        frac, j, ult = {}, 0, None
        for f in sorted(sp):
            while j < len(sk) and sk[j] <= f:
                ult = sup[sk[j]]
                j += 1
            if ult:
                frac[f] = sp[f] / ult
        vals = sorted(frac.values())
        med = vals[len(vals) // 2]
        print(f"    % oferta en ganancia: mediana {100 * med:.0f}%, última {100 * frac[max(frac)]:.0f}% ({max(frac)})", flush=True)
        if not 0.2 < med < 1.0:
            raise ValueError("el cociente no parece una fracción (revisar unidades)")
        cand("% de la oferta en ganancia", al(frac), "baja", "alta", [(0.5, 0.95), (0.55, None)])
    bloque("oferta en ganancia", b_ganancia)

    # ---- de medir_diarios
    def b_atencion():
        w = md.intentar("Wikipedia pageviews Bitcoin", md.f_wiki)
        if not w:
            raise ValueError("sin pageviews")
        x = al(w)
        m7, m365 = md.rodar(x, 7, lambda v: sum(v) / len(v)), md.rodar(x, 365, lambda v: sum(v) / len(v))
        cand("Atención de Wikipedia (7d / 365d)", [None if a is None or not b else a / b for a, b in zip(m7, m365)], "baja", "alta",
             nota="desde 2015-07")
    bloque("atención", b_atencion)

    def b_exchanges():
        fin = md.intentar("BTC FlowInExNtv", md.f_cm, "btc", "FlowInExNtv", "2010-07-01")
        fout = md.intentar("BTC FlowOutExNtv", md.f_cm, "btc", "FlowOutExNtv", "2010-07-01")
        res = md.intentar("BTC SplyExNtv", md.f_cm, "btc", "SplyExNtv", "2010-07-01")
        if fin and fout:
            nf = {d: fin[d] - fout[d] for d in fin if d in fout}
            cand("Netflow de exchanges 30d (+ = entradas)", md.rodar(al(nf), 30, sum), "baja", "alta", nota="salidas = acumulación (compra)")
        if res:
            cand("Reserva en exchanges (cambio 90d)", md.cambio(al(res), 90), "baja", "alta", nota="baja = acumulación (compra)")
    bloque("exchanges", b_exchanges)

    def b_ssr():
        cap = md.intentar("BTC CapMrktCurUSD", md.f_cm, "btc", "CapMrktCurUSD", "2010-07-01")
        usdt = md.intentar("USDT SplyCur", md.f_cm, "usdt", "SplyCur", "2014-01-01")
        if usdt is None:
            partes = [d for d in (md.intentar(f"{a} SplyCur", md.f_cm, a, "SplyCur", "2014-01-01") for a in ("usdt_eth", "usdt_trx", "usdt_omni")) if d]
            usdt = {}
            for dd in partes:
                for k, v in dd.items():
                    usdt[k] = usdt.get(k, 0.0) + v
        usdc = md.intentar("USDC SplyCur", md.f_cm, "usdc", "SplyCur", "2014-01-01")
        if not cap or not (usdt or usdc):
            raise ValueError("falta cap de BTC o stablecoins")
        st = {}
        for dd in (usdt or {}, usdc or {}):
            for k, v in dd.items():
                st[k] = st.get(k, 0.0) + v
        c_, s_ = al(cap), al(st)
        cand("SSR (cap BTC / USDT+USDC)", [None if a is None or not b else a / b for a, b in zip(c_, s_)], "baja", "alta",
             nota="bajo = mucha pólvora (compra)")
    bloque("SSR", b_ssr)

    def b_liq():
        A = md.intentar("Fed activos totales", md.f_fed_activos)
        T = md.intentar("TGA", md.f_tga)
        R = md.intentar("RRP", md.f_rrp)
        if not (A and T and R):
            raise ValueError("falta alguna pata de la liquidez neta")
        a, t, r_ = al(A, 2, 21), al(T, 2, 21), al(R, 1, 7)
        primero_r = date.fromisoformat(min(R)).toordinal()
        net = []
        for i in range(len(o)):
            rr = r_[i] if r_[i] is not None else (0.0 if o[i] < primero_r else None)
            net.append(None if a[i] is None or t[i] is None or rr is None else a[i] - t[i] - rr)
        cand("Liquidez neta de la Fed (cambio 13 semanas)", md.cambio(net, 91), "alta", "baja", nota="NY Fed SOMA - TGA - RRP, desde 2014; sube = compra")
    bloque("liquidez", b_liq)

    def b_vix():
        vix = md.intentar("VIX", md.f_vix, "VIX")
        if not vix:
            raise ValueError("sin VIX")
        v3 = md.intentar("VIX3M", md.f_vix, "VIX3M")
        cand("VIX (nivel)", al(vix, 1, 6), "alta", "baja", [(None, 30.0), (None, 40.0)], "miedo alto = compra?")
        if v3:
            cand("VIX / VIX3M (>= 1: estructura invertida)", al({k: vix[k] / v3[k] for k in vix if k in v3 and v3[k]}, 1, 6), "alta", "baja",
                 [(None, 1.0)], "miedo alto = compra?")
    bloque("VIX", b_vix)


# ---------------------------------------------------------------- informes
def rango(ups):
    v = [100 * u for u in ups if u is not None]
    if not v or len(v) < len(ups):
        return None
    a, b = round(min(v)), round(max(v))
    return f"{a}%" if a == b else f"{a}–{b}%"


def spec_txt(vn, spec, lados):
    if spec[0] == "p":
        partes = []
        if "COMPRA" in lados.values() or "VENTA" in lados.values():
            if lados["baja"] != "—":
                partes.append(f"percentil ≤ {spec[1]}")
            if lados["alta"] != "—":
                partes.append(f"percentil ≥ {spec[2]}")
        return " / ".join(partes)
    partes = []
    if spec[1] is not None and lados["baja"] != "—":
        partes.append(f"≤ {fnum(spec[1])}")
    if spec[2] is not None and lados["alta"] != "—":
        partes.append(f"≥ {fnum(spec[2])}")
    return " / ".join(partes)


def tabla_readme(C):
    print("\n" + "=" * 100)
    print("=== TABLA PARA EL README (mismo formato que 'Zonas del ciclo'; % = a 1 año subió, en los dos tramos de cada serie) ===")
    print("| Indicador | Zona de compra (a 1 año subió) | Zona de venta (a 1 año subió) |")
    print("|---|---|---|")
    no = []
    for c in C:
        m = c["mejor"]
        if not m:
            no.append(c["nom"])
            continue
        cc = ve = "—"
        for lado, v in m["lados"].items():
            if v == "COMPRA":
                cc = rango(m["ups"][lado]) or "—"
            elif v == "VENTA":
                ve = rango(m["ups"][lado]) or "—"
        sp = spec_txt(m["vn"], m["spec"], m["lados"])
        corta = " (2019–21 y 2022–25)" if c["tramos"] is TRAMOS_CORTOS else ""
        extra = {"MEJORA": "; mejora el puntaje", "NO EMPEORA": "; no empeora el puntaje", "EMPEORA": "; empeora el puntaje"}.get(m["sv"], "")
        print(f"| {c['nom']} ({sp}){corta}{extra} | {cc} | {ve} |")
    if no:
        print("| " + ", ".join(no) + " | no sirvieron | |")


def hoy(C):
    dias, n = G["dias"], len(G["dias"])
    print("\n" + "=" * 100)
    print(f"=== HOY ({dias[-1]}; cada dato usable desde el día siguiente a su fecha) · valor, percentil de su propia historia, zona y umbrales ===")
    print("    Umbrales en la sintaxis de zonas_ciclo.py: ('<=', x) / ('>=', x) fijo; ('p', q) percentil q de la historia (compra: <=, venta: >=); ('p>=', q) compra cuando es ALTO.")
    for c in C:
        x, r = c["x"], c["r"]
        iu = max((i for i, v in enumerate(x) if v is not None), default=None)
        if iu is None:
            continue
        v, rk = x[iu], r[iu]
        obs = f" (último dato {dias[iu]})" if iu != n - 1 else ""
        base = f"  {c['nom']:<48} valor {v:>10.4g}{obs} · percentil {'—' if rk is None else f'{rk:.0f}'}"
        m = c["mejor"]
        if not m:
            print(base + " · no marca zona")
            continue
        vals = [t for t in x if t is not None]
        txt, estado = [], "ninguna"
        for lado, val in (("baja", 1), ("alta", -1)):
            ver = m["lados"][lado]
            if ver == "—":
                continue
            tipo = "compra" if ver == "COMPRA" else "venta"
            sp = m["spec"]
            if sp[0] == "p":
                q = sp[1] if lado == "baja" else sp[2]
                umb = pctl(vals, q)
                z = ("p", q) if (tipo == "venta" and lado == "alta") or (tipo == "compra" and lado == "baja") else ("p>=", q) if tipo == "compra" else None
            else:
                umb = sp[1] if lado == "baja" else sp[2]
                z = ("<=" if lado == "baja" else ">=", umb)
            if m["zona"][iu] == val:
                estado = f"EN ZONA DE {tipo.upper()}"
            ops = "<=" if lado == "baja" else ">="
            soporta = "" if z is not None else "  [zonas_ciclo.py no soporta venta cuando es BAJO]"
            txt.append(f"{tipo}: valor {ops} {umb:.5g} → {z if z else '—'}{soporta}")
        print(base + f" · hoy: {estado} · [{m['vn']}] " + " · ".join(txt))


# ---------------------------------------------------------------- modo prueba (sin internet)
def _sintetico():
    f_look, f_bgeo = oc._sintetico()               # parchea md (f_cm, fed, tga, rrp, wiki, vix) y da looknode / bitcoin-data de prueba
    cm0 = md.f_cm

    def cm(activo, met, desde="2013-01-01"):
        if activo == "btc" and met in ("IssTotUSD", "AdrActCnt"):
            px = cm0("btc", "PriceUSD", desde)
            r = random.Random(zlib.crc32(met.encode()))
            return {k: (v * 900 if met == "IssTotUSD" else 5e5) * math.exp(r.gauss(0, 0.1)) for k, v in px.items()}
        return cm0(activo, met, desde)

    md.f_cm = cm
    return f_look, f_bgeo


def main():
    if PRUEBA:
        print("MODO PRUEBA: series sintéticas, sin internet")
        G["F_LOOK"], G["F_BGEO"] = _sintetico()
        oc.F_LOOK, oc.F_BGEO = G["F_LOOK"], G["F_BGEO"]
        oc.guardar_cache = lambda *_: None
    else:
        G["F_LOOK"], G["F_BGEO"] = oc.f_look, oc.f_bgeo
        oc.F_LOOK, oc.F_BGEO = oc.f_look, oc.f_bgeo
        oc.CACHE = CACHE
    print("Fuentes:", flush=True)
    px = md.intentar("BTC PriceUSD", md.f_cm, "btc", "PriceUSD", "2010-07-01")
    if not px:
        print("sin precio de BTC no se puede medir nada")
        return
    o0, o1 = date.fromisoformat(min(px)).toordinal(), date.fromisoformat(max(px)).toordinal()
    o = list(range(o0, o1 + 1))
    dias = [date.fromordinal(x).isoformat() for x in o]
    P, u = [], None
    for d in dias:
        u = px.get(d, u)
        P.append(u)
    G.update(o=o, dias=dias, P=P)
    n = len(dias)

    # puntaje de las 9 zonas (sin retraso, como zonas2)
    puntaje = None
    try:
        cm = {}
        for k in ("CapMrktCurUSD", "CapMVRVCur", "IssTotUSD", "AdrActCnt"):
            d = md.intentar(f"BTC {k}", md.f_cm, "btc", k, "2010-07-01")
            if not d:
                raise ValueError(f"falta {k}")
            cm[k] = md.alinear(d, o, 0, 10 ** 6)
        puntaje = puntaje_nueve(dias, P, cm)
        print(f"  puntaje de las 9 zonas hoy: {puntaje[-1]:+d} (compra +1 por zona, venta -1)", flush=True)
    except Exception as e:
        print(f"  puntaje de las 9 zonas no: {type(e).__name__}: {e} (se saltea la prueba de suma)", flush=True)

    C = []
    armar(C)
    if not C:
        print("ningún candidato disponible")
        return
    labs = md.etiquetas_estados(P)
    print("\n" + "=" * 100)
    print("Etiquetas de estado (con futuro, solo como respuesta): " + " · ".join(
        f"{e}: {100 * sum(v for v in labs[e] if v) / max(1, sum(1 for v in labs[e] if v is not None)):.0f}% de los días" for e in ("piso", "piso extremo", "techo")))
    for c in C:
        try:
            evaluar_candidato(c, None, puntaje, labs)
        except Exception as e:
            print(f"  {c['nom']} no: {type(e).__name__}: {e}", flush=True)
            c.update(mejor=None, res=[], ver="error")
            c.setdefault("r", [None] * n)
            c.setdefault("tramos", TRAMOS_LARGOS)
    C = [c for c in C if "res" in c]
    print("\n" + "=" * 100)
    print("=== RESUMEN: veredicto a 1 año (en los dos tramos, 10 puntos o más) y suma al puntaje de las 9 zonas ===")
    for c in C:
        m = c["mejor"]
        print(f"  {c['nom']:<50} {c['ver']:<22}" + (f" [{m['vn']}] suma: {m['sv']}" if m else ""))
    tabla_readme(C)
    hoy(C)


if __name__ == "__main__":
    main()
