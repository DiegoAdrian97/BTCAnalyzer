"""Estados GENERALES del mercado en vez del dia exacto: "cerca de un piso", "piso extremo", "posible techo", "rally alcista en curso",
"zona de indecision". Reglas simples, legibles, MEDIDAS: ¿cuantas veces acerto cada etiqueta?

Predecir el dia exacto es casi tirar una moneda; cuando las señales de corto plazo no son claras, la app tiene que decir algo mas
general y confiable. Aca se arma un juego chico de reglas que traduce los datos de hoy a UNA etiqueta y se mide fuera de muestra.

Entradas (todas diarias, sin mirar el futuro; un dato on-chain se usa desde el dia siguiente a su fecha):
  - Puntaje de zonas Z = zonas de compra prendidas - zonas de venta prendidas. Percentiles de la propia historia hasta cada dia
    (medir_zonas.rank_exp). Zonas del panel (zonas_ciclo.ZONAS: puell, mayer, 2 años, 200 semanas, golden, pi, potencia,
    metcalfe, dias desde el maximo, thermocap, hash ribbons, stablecoins) + las on-chain que pasaron en medir_zonas3: precio/CVDD
    <= 1,2 (compra), precio/precio balanceado p10 compra / p90 venta, RHODL p15 compra, % de la oferta en ganancia <= 0,5 compra,
    precio/costo de los tenedores de corto plazo (sthCostPriceV2, linea v2) p15 VENTA (precio por debajo del costo de los
    compradores recientes = oso), aSOPR 30 d p85 venta, pico de pérdida realizada 7 d contra el año: p10 compra / p90 venta.
  - Termometro: temperatura de armar_termometro (md.puntaje_termometro; si no se puede, proxy de MVRV).
  - Tendencia: precio contra costo STH, contra media de 200 d, retornos de 30 y 90 d.
  - Respuesta (con futuro, SOLO como respuesta): md.etiquetas_estados (piso, piso extremo, techo, rally en curso, indecisión).

Metodo:
  - Reglas (prioridad en este orden): PISO EXTREMO, POSIBLE TECHO, CERCA DE UN PISO, RALLY ALCISTA EN CURSO, ZONA DE INDECISION.
  - Umbrales elegidos en UN tramo con una grilla chica (coordenada por coordenada, 2 pasadas) para maximizar el lift
    P(estado | etiqueta) / tasa base, con minimo 60 dias y 3 episodios independientes (rachas separadas por mas de 30 dias).
  - Se prueban SIN CAMBIAR en el otro tramo, en las dos direcciones (ajusto 2012-19 y pruebo 2020-26; ajusto 2020-26 y pruebo 2012-19).
  - SIRVE = lift > 1 con z >= 2 (bloques de 90 d) en las dos direcciones. Etiquetas raras (piso extremo, techo) con menos de 4
    episodios: "pocos casos" y se muestran los numeros crudos.
  - Para cada etiqueta tambien: retorno a 365 y a 90 dias (mediana, % que sube), contra un dia cualquiera del tramo.
  - Regla final = ajuste sobre los dos tramos juntos (en muestra: el veredicto honesto es el de las dos direcciones de arriba).
Uso: python medir_estado.py
     python medir_estado.py --prueba      (sin internet: series sinteticas para probar el codigo de punta a punta)
"""
import math
import statistics
import sys
from datetime import date

import medir_diarios as md                     # etiquetas, termometro, alinear, fetchers (comparte argv: --prueba)
import medir_onchain_ciclo as oc               # fetchers de looknode / bitcoin-data, cache, helpers
import medir_zonas3 as z3                      # _sintetico (modo prueba) y pctl
from medir_zonas import rank_exp, sma          # percentil sin mirar el futuro y media simple

PRUEBA = "--prueba" in sys.argv
CACHE = "cache_estado.json"
TRAMOS = (("2012-19", "2012-01-01", "2020-01-01"), ("2020-26", "2020-01-01", "2100-01-01"))
MIN_DIAS, MIN_EP, HUECO = 60, 3, 30
G = {}

PISO_X, TECHO, PISO, RALLY, INDEC, SIN = ("piso extremo", "posible techo", "cerca de un piso", "rally alcista en curso",
                                          "zona de indecisión", "sin señal")
ETIQ = (PISO_X, TECHO, PISO, RALLY, INDEC)                      # prioridad
ESTADO_DE = {PISO_X: "piso extremo", TECHO: "techo", PISO: "piso", RALLY: "rally en curso", INDEC: "indecisión"}
RARAS = (PISO_X, TECHO)
DEF = dict(kpe=4, k1=2, k2=2, tt=None, rs=None, r=0.20, s=None)
GRILLA = {
    PISO_X: [dict(kpe=k) for k in (3, 4, 5, 6)],
    TECHO: [dict(k2=k, tt=t, rs=r) for k in (1, 2, 3, 4) for t in (None, 85, 95) for r in (None, 1.3, 1.6)],
    PISO: [dict(k1=k) for k in (1, 2, 3, 4)],
    RALLY: [dict(r=r) for r in (0.10, 0.20, 0.30, 0.40)],
    INDEC: [dict(s=s) for s in (None, 0.05, 0.10)],
}
CERCA_STH = 0.15                                                # "cerca del costo STH" para la indecision estricta


def pct(x, d=0):
    return "—" if x is None else f"{100 * x:.{d}f}%"


def num(x, d=2):
    return "—" if x is None else f"{x:.{d}f}".replace(".", ",")


def zf(z):
    return "—" if z is None else f"{z:+.1f}".replace(".", ",")


def signed(x, d=0):
    return "—" if x is None else f"{100 * x:+.{d}f}%"


# ---------------------------------------------------------------- zonas (cada una +1 compra, -1 venta, 0 neutra, None sin dato)
def cumple(spec, v, rk):
    if spec is None:
        return False
    op, t = spec
    return {"<=": lambda: v <= t, ">=": lambda: v >= t, "rk<=": lambda: rk <= t, "rk>=": lambda: rk >= t}[op]()


def texto_spec(spec, vals):
    if spec is None:
        return "—"
    op, t = spec
    if op in ("<=", ">="):
        return f"{op} {t:g}"
    u = z3.pctl(vals, t)
    return f"percentil {t} (valor {'<=' if op == 'rk<=' else '>='} {u:.4g})"


def armar_zona(nom, x, compra, venta):
    primero = next((G["dias"][i] for i, v in enumerate(x) if v is not None), "2100")
    r = rank_exp(x, minimo=365 if primero >= "2017" else 730)
    z = []
    for v, rk in zip(x, r):
        if v is None or rk is None:
            z.append(None)
        else:
            z.append(1 if cumple(compra, v, rk) else -1 if cumple(venta, v, rk) else 0)
    return dict(nom=nom, x=x, r=r, z=z, compra=compra, venta=venta, desde=primero)


def potencia(dias, P):
    n = len(dias)
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
    return pl


def armar_datos():
    """Baja todo y arma: zonas, termometro, tendencia, CVDD, MVRV. Cada bloque que falla avisa y se saltea."""
    o, P, dias = G["o"], G["P"], G["dias"]
    n = len(dias)
    Zs = []

    def bloque(nombre, fn):
        try:
            fn()
        except Exception as e:
            print(f"  bloque {nombre} no: {type(e).__name__}: {e}", flush=True)

    def zona(nom, x, compra, venta):
        if x is None or not any(v is not None for v in x):
            print(f"  {nom}: sin datos, se saltea", flush=True)
            return
        zz = armar_zona(nom, x, compra, venta)
        Zs.append(zz)
        print(f"  + zona {nom}: desde {zz['desde']}", flush=True)

    cm = {}
    for k in ("CapMrktCurUSD", "CapMVRVCur", "IssTotUSD", "AdrActCnt", "HashRate"):
        d = md.intentar(f"BTC {k}", md.f_cm, "btc", k, "2010-07-01")
        if d:
            cm[k] = md.alinear(d, o, 0, 10 ** 6)
    mv = cm.get("CapMVRVCur")
    cap, issu, adr, hr = cm.get("CapMrktCurUSD"), cm.get("IssTotUSD"), cm.get("AdrActCnt"), cm.get("HashRate")
    ratio = lambda lin: [None if p is None or l is None or l <= 0 else p / l for p, l in zip(P, lin)]

    # ---- zonas del panel (zonas_ciclo.ZONAS)
    def b_panel():
        if issu:
            m365 = sma([x or 0.0 for x in issu], 365)
            zona("Puell", [None if not m365[i] or issu[i] is None else issu[i] / m365[i] for i in range(n)], ("<=", 0.5), ("rk>=", 85))
        for nom, k, c, v in (("Mayer (200 d)", 200, None, (">=", 2.4)), ("Media de 2 años", 730, ("<=", 1.0), ("rk>=", 85)),
                             ("Media de 200 semanas", 1400, ("<=", 1.0), (">=", 4.0)), ("Golden Ratio (350 d)", 350, ("<=", 0.8), (">=", 3.0))):
            m = sma(P, k)
            zona(nom, [None if m[i] is None else P[i] / m[i] for i in range(n)], c, v)
        m111, m350 = sma(P, 111), sma(P, 350)
        zona("Pi Cycle", [None if m350[i] is None else m111[i] / (2 * m350[i]) for i in range(n)], ("<=", 0.35), ("rk>=", 85))
        zona("Ley de potencia", potencia(dias, P), ("rk<=", 15), ("rk>=", 85))
        if cap and adr:
            a30 = sma([x or 0.0 for x in adr], 30)
            zona("Metcalfe", [None if not a30[i] or cap[i] is None else cap[i] / a30[i] ** 2 for i in range(n)], None, ("rk>=", 85))
        mx, dmx, dsm = 0.0, 0, []
        for i, p in enumerate(P):
            if p >= mx:
                mx, dmx = p, i
            dsm.append(float(i - dmx))
        zona("Días desde el máximo", dsm, ("rk>=", 85), None)
        if cap and issu:
            ac, th = 0.0, []
            for i in range(n):
                ac += issu[i] or 0.0
                th.append(None if not ac or cap[i] is None else cap[i] / ac)
            zona("Thermocap", th, None, ("rk>=", 85))
        if hr:
            h30, h60 = sma([x or 0.0 for x in hr], 30), sma([x or 0.0 for x in hr], 60)
            zona("Hash ribbons (30/60)", [None if not h60[i] else h30[i] / h60[i] for i in range(n)], ("rk<=", 10), None)
    bloque("panel", b_panel)

    def b_stable():
        usdt = md.intentar("USDT SplyCur", md.f_cm, "usdt", "SplyCur", "2014-01-01")
        if usdt is None:
            partes = [d for d in (md.intentar(f"{a} SplyCur", md.f_cm, a, "SplyCur", "2014-01-01") for a in ("usdt_eth", "usdt_trx", "usdt_omni")) if d]
            usdt = {}
            for dd in partes:
                for k, v in dd.items():
                    usdt[k] = usdt.get(k, 0.0) + v
        usdc = md.intentar("USDC SplyCur", md.f_cm, "usdc", "SplyCur", "2014-01-01")
        if not (usdt or usdc):
            raise ValueError("sin stablecoins")
        st = {}
        for dd in (usdt or {}, usdc or {}):
            for k, v in dd.items():
                st[k] = st.get(k, 0.0) + v
        s = md.alinear(st, o, 0, 10 ** 6)
        zona("Emisión de stablecoins (90 d)", [None if i < 90 or not s[i] or not s[i - 90] else s[i] / s[i - 90] - 1 for i in range(n)], ("rk<=", 10), None)
    bloque("stablecoins", b_stable)

    # ---- on-chain nuevas (medir_zonas3); un dato se usa desde el dia siguiente
    al = lambda d, lag=1, vence=5: md.alinear(d, o, lag, vence)
    cr = oc.cargar_cache() if not PRUEBA else {"dia": "prueba", "look": {}, "bgeo": {}}
    print("\nBajando looknode:", flush=True)
    L = {i: oc.bajar_look(cr, i) for i in ("CVDD", "balancedPrice", "ASOPR", "rhodl", "sthCostPriceV2", "realizedLos")}
    cvdd = sth = None

    def b_chain():
        nonlocal cvdd, sth
        if L["CVDD"]:
            cvdd = ratio(al(oc.columna(L["CVDD"], 0)))
            zona("Precio / CVDD", cvdd, ("<=", 1.2), None)
        if L["balancedPrice"]:
            zona("Precio / precio balanceado", ratio(al(oc.columna(L["balancedPrice"], 0))), ("rk<=", 10), ("rk>=", 90))
        if L["rhodl"]:
            zona("RHODL", al(oc.columna(L["rhodl"], 0)), ("rk<=", 15), None)
        d = L["sthCostPriceV2"]
        if d and any(len(v) > 1 for v in d.values()):
            sth = ratio(al(oc.columna(d, 1)))
            zona("Precio / costo STH (sthCostPriceV2 v2)", sth, None, ("rk<=", 15))
        if L["ASOPR"]:
            zona("aSOPR media 30 d", oc.media_rodada(al(oc.columna(L["ASOPR"], 0)), 30), None, ("rk>=", 85))
        if L["realizedLos"]:
            zona("Pérdida realizada (pico 7 d / año)", oc.pico_vs_año(al(oc.columna(L["realizedLos"], 0))), ("rk<=", 10), ("rk>=", 90))
    bloque("on-chain looknode", b_chain)

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
        med = sorted(frac.values())[len(frac) // 2]
        if not 0.2 < med < 1.0:
            raise ValueError("el cociente no parece una fracción (revisar unidades)")
        zona("% de la oferta en ganancia", al(frac), ("<=", 0.5), None)
    bloque("oferta en ganancia", b_ganancia)

    # ---- puntaje Z
    Z, NZ = [], []
    for i in range(n):
        v = [zz["z"][i] for zz in Zs if zz["z"][i] is not None]
        NZ.append(len(v))
        Z.append(sum(v) if len(v) >= 5 else None)
    G["Zs"], G["Z"], G["NZ"] = Zs, Z, NZ

    # ---- termometro y tendencia
    try:
        T, desc = md.puntaje_termometro(o, P)
    except Exception as e:
        print(f"  termómetro no: {type(e).__name__}: {e}", flush=True)
        T, desc = [None] * n, "sin termómetro"
    G["T"], G["Tdesc"] = T, desc
    m200 = sma(P, 200)
    G["up200"] = [None if m200[i] is None else P[i] > m200[i] for i in range(n)]
    G["m200"] = m200
    G["ret30"] = [None if i < 30 else P[i] / P[i - 30] - 1 for i in range(n)]
    G["ret90"] = [None if i < 90 else P[i] / P[i - 90] - 1 for i in range(n)]
    G["sth"], G["cvdd"] = sth, cvdd
    G["mv"] = mv
    G["fw365"] = [None if i + 365 >= n else P[i + 365] / P[i] - 1 for i in range(n)]
    G["fw90"] = [None if i + 90 >= n else P[i + 90] / P[i] - 1 for i in range(n)]


# ---------------------------------------------------------------- reglas
def etiquetar(q):
    """Etiqueta de cada dia con los umbrales q (None si no hay puntaje Z). Solo mira datos de ese dia y el pasado."""
    n = len(G["dias"])
    Z, T, sth, cv, mv = G["Z"], G["T"], G["sth"], G["cvdd"], G["mv"]
    up200, r30, r90 = G["up200"], G["ret30"], G["ret90"]
    out = [None] * n
    for i in range(n):
        z = Z[i]
        if z is None:
            continue
        rs = sth[i] if sth else None
        if z >= q["kpe"] or (cv and cv[i] is not None and cv[i] <= 1.2) or (mv and mv[i] is not None and mv[i] <= 1.0):
            out[i] = PISO_X
            continue
        extra = []
        if q["tt"] is not None:
            extra.append(T[i] is not None and T[i] >= q["tt"])
        if q["rs"] is not None:
            extra.append(rs is not None and rs >= q["rs"])
        if z <= -q["k2"] or (extra and all(extra)):
            out[i] = TECHO
        elif z >= q["k1"]:
            out[i] = PISO
        elif (rs is None or rs > 1) and up200[i] and r90[i] is not None and r90[i] > q["r"]:
            out[i] = RALLY
        elif q["s"] is None or (r30[i] is not None and abs(r30[i]) <= q["s"] and (rs is None or abs(rs - 1) <= CERCA_STH)):
            out[i] = INDEC
        else:
            out[i] = SIN
    return out


def texto_regla(q):
    tec = ""
    if q["tt"] is not None or q["rs"] is not None:
        c = ([f"temperatura >= {q['tt']}"] if q["tt"] is not None else []) + ([f"precio/costo STH >= {q['rs']:g}"] if q["rs"] is not None else [])
        tec = " o (" + " y ".join(c) + ")"
    ind = "todo lo demás" if q["s"] is None else f"|retorno 30 d| <= {100 * q['s']:.0f}% y precio a menos de {100 * CERCA_STH:.0f}% del costo STH (si no: sin señal)"
    return {
        PISO_X: f"Z >= {q['kpe']} o precio/CVDD <= 1,2 o MVRV <= 1",
        TECHO: f"Z <= -{q['k2']}{tec}",
        PISO: f"Z >= {q['k1']} (y no es piso extremo ni techo)",
        RALLY: f"precio > costo STH (si hay dato) y > media 200 d y retorno 90 d > {100 * q['r']:.0f}% (y no es techo ni piso)",
        INDEC: ind,
    }


# ---------------------------------------------------------------- medicion
def episodios(sel):
    n, ult = 0, None
    for i in sel:
        if ult is None or i - ult > HUECO:
            n += 1
        ult = i
    return n


def fwd(sel, k):
    v = sorted(G[k][i] for i in sel if G[k][i] is not None)
    if not v:
        return None
    q = lambda p: v[min(len(v) - 1, int(p * (len(v) - 1) + 0.5))]
    return dict(n=len(v), med=statistics.median(v), p25=q(0.25), p75=q(0.75), up=sum(1 for x in v if x > 0) / len(v))


def medir(labs, etiqueta, tset, est=None):
    """Estadisticas de una etiqueta en los tramos tset (conjunto de 0/1)."""
    est = est or G["est"][ESTADO_DE[etiqueta]]
    tr = G["tr"]
    idx = [i for i in range(len(labs)) if tr[i] in tset and labs[i] is not None and est[i] is not None]
    sel = [i for i in idx if labs[i] == etiqueta]
    r = dict(dias=len(sel), ep=episodios(sel), nidx=len(idx), sel=sel)
    r["base"] = sum(est[i] for i in idx) / len(idx) if idx else None
    r["p"] = sum(est[i] for i in sel) / len(sel) if sel else None
    b, p = r["base"], r["p"]
    r["lift"] = p / b if p is not None and b else None
    r["ne"] = len({i // 90 for i in sel})
    r["z"] = (p - b) / math.sqrt(b * (1 - b) / r["ne"]) if p is not None and b and 0 < b < 1 and r["ne"] >= 4 else None
    r["f365"], r["f90"] = fwd(sel, "fw365"), fwd(sel, "fw90")
    return r


def base_fwd(tset):
    ix = [i for i in range(len(G["dias"])) if G["tr"][i] in tset and G["Z"][i] is not None]
    return fwd(ix, "fw365"), fwd(ix, "fw90")


def elegible(r):
    return r["dias"] >= MIN_DIAS and r["ep"] >= MIN_EP and r["lift"] is not None


def ajustar(tset):
    """Grilla coordenada por coordenada (2 pasadas): por etiqueta, el umbral de mayor lift con >= 60 dias y >= 3 episodios."""
    q, sin_elegir = dict(DEF), set()
    for _ in range(2):
        for et in ETIQ:
            mejor = None
            for cand in GRILLA[et]:
                qq = {**q, **cand}
                r = medir(etiquetar(qq), et, tset)
                if elegible(r) and (mejor is None or (r["lift"], r["dias"]) > (mejor[1]["lift"], mejor[1]["dias"])):
                    mejor = (cand, r)
            if mejor:
                q.update(mejor[0])
                sin_elegir.discard(et)
            else:
                sin_elegir.add(et)
    return q, sin_elegir


def linea(et, tn, r, prefijo="  "):
    if r["dias"] == 0:
        return f"{prefijo}{et:<24} {tn:<8} sin días con esta etiqueta"
    z = f"z {zf(r['z'])}"
    s = (f"{prefijo}{et:<24} {tn:<8} {r['dias']:>4} d, {r['ep']:>2} ep | P({ESTADO_DE[et]}) {pct(r['p'])} (base {pct(r['base'])}) "
         f"lift {num(r['lift'])} {z} [b{r['ne']}]")
    for k, t in (("f365", "365d"), ("f90", "90d")):
        f = r[k]
        s += f" | {t}: " + ("sin datos" if f is None else f"med {signed(f['med'])} sube {pct(f['up'])} (n {f['n']})")
    return s


def linea_base(tn, tset):
    b365, b90 = base_fwd(tset)
    s = f"  un día cualquiera {tn:<8}"
    for f, t in ((b365, "365d"), (b90, "90d")):
        s += f" | {t}: " + ("sin datos" if f is None else f"med {signed(f['med'])} sube {pct(f['up'])} (n {f['n']})")
    return s


def veredicto(a, b, et):
    """a: ajuste en 2012-19, prueba en 2020-26; b: ajuste en 2020-26, prueba en 2012-19."""
    if a["dias"] == 0 or b["dias"] == 0:
        return "pocos casos (sin días en un sentido)"
    if et in RARAS and (a["ep"] < 4 or b["ep"] < 4):
        return f"pocos casos (episodios {a['ep']} y {b['ep']}; números crudos arriba)"
    if a["z"] is None or b["z"] is None:
        return "pocos casos (menos de 4 bloques de 90 d)"
    if all(r["lift"] is not None and r["lift"] > 1 and r["z"] >= 2 for r in (a, b)):
        return "SIRVE"
    return "NO SIRVE"


# ---------------------------------------------------------------- informe
def informe(qs1, qs2, f1, f2):
    print("\n" + "=" * 100)
    print("Tasas base de los estados (con futuro, solo como respuesta), en los días con puntaje Z:")
    for e in ESTADO_DE.values():
        partes = []
        for k, (tn, _, _) in enumerate(TRAMOS):
            xs = [G["est"][e][i] for i in range(len(G["dias"])) if G["tr"][i] == k and G["Z"][i] is not None and G["est"][e][i] is not None]
            partes.append(f"{tn}: {pct(sum(xs) / len(xs)) if xs else '—'} de {len(xs)} d")
        print(f"  {e:<15} " + " · ".join(partes))
    res = {}
    for titulo, q, fit, test, nf in (("AJUSTE 2012-19 -> PRUEBA 2020-26", qs1, 0, 1, f1), ("AJUSTE 2020-26 -> PRUEBA 2012-19", qs2, 1, 0, f2)):
        print("\n" + "=" * 100)
        print(f"=== {titulo} (umbrales elegidos solo en {TRAMOS[fit][0]}; se prueban sin cambiar en {TRAMOS[test][0]}) ===")
        print("  umbrales: " + " · ".join(f"{k}={v}" for k, v in q.items()) + (f" · SIN umbral elegible (quedó el de partida): {', '.join(sorted(nf))}" if nf else ""))
        labs = etiquetar(q)
        print("  días por etiqueta (todo el período con Z): " + " · ".join(f"{e} {sum(1 for l in labs if l == e)}" for e in ETIQ + (SIN,)))
        for et in ETIQ:
            print(f"  [{et}] regla: {texto_regla(q)[et]}")
            print(linea(et, TRAMOS[fit][0] + " (ajuste)", medir(labs, et, {fit}), "    "))
            r = medir(labs, et, {test})
            print(linea(et, TRAMOS[test][0] + " (PRUEBA)", r, "    "))
            res[(et, fit)] = r
        print(linea_base(TRAMOS[test][0], {test}))
    print("\n" + "=" * 100)
    print("=== VEREDICTO por etiqueta (fuera de muestra, las dos direcciones; SIRVE = lift > 1 y z >= 2 en ambas) ===")
    ver = {}
    for et in ETIQ:
        a, b = res[(et, 0)], res[(et, 1)]          # a: ajuste 1, prueba en tramo 2; b: ajuste 2, prueba en tramo 1
        ver[et] = veredicto(a, b, et)
        print(f"  {et:<24} 1→2: lift {num(a['lift'])} z {zf(a['z'])} ({a['dias']} d, {a['ep']} ep) · "
              f"2→1: lift {num(b['lift'])} z {zf(b['z'])} ({b['dias']} d, {b['ep']} ep) → {ver[et]}")
    G["res_cruz"], G["ver"] = res, ver


def final():
    q, nf = ajustar({0, 1})
    labs = etiquetar(q)
    print("\n" + "=" * 100)
    print("=== REGLAS FINALES (umbrales ajustados con los DOS tramos juntos; en muestra, el veredicto honesto es el de arriba) ===")
    print("  umbrales: " + " · ".join(f"{k}={v}" for k, v in q.items()) + (f" · sin umbral elegible: {', '.join(sorted(nf))}" if nf else ""))
    txt = texto_regla(q)
    for et in ETIQ:
        print(f"  {et:<24} {txt[et]} → veredicto fuera de muestra: {G['ver'][et]}")
        for k, (tn, _, _) in enumerate(TRAMOS):
            print(linea(et, tn, medir(labs, et, {k}), "      "))
    for k, (tn, _, _) in enumerate(TRAMOS):
        print(linea_base(tn, {k}))

    # ---- tabla para el README
    print("\n" + "=" * 100)
    print("=== TABLA PARA EL README (lift y z fuera de muestra: ajusto 2012-19 y pruebo 2020-26 / ajusto 2020-26 y pruebo 2012-19) ===")
    print("| Etiqueta | Regla | Fuera de muestra (lift · z) | A 1 año (todo, mediana · % que sube) | Veredicto |")
    print("|---|---|---|---|---|")
    todo = {0, 1}
    for et in ETIQ:
        a, b = G["res_cruz"][(et, 0)], G["res_cruz"][(et, 1)]
        fz = lambda r: "sin casos" if r["dias"] == 0 else f"{num(r['lift'])}× · z {zf(r['z'])} ({r['dias']} d, {r['ep']} ep)"
        r = medir(labs, et, todo)
        f = r["f365"]
        print(f"| {et} | {txt[et]} | 1→2: {fz(a)}; 2→1: {fz(b)} | " + ("—" if f is None else f"{signed(f['med'])} · {pct(f['up'])}") + f" | {G['ver'][et].split(' (')[0]} |")
    b365, _ = base_fwd(todo)
    print(f"| (un día cualquiera) | — | — | {signed(b365['med'])} · {pct(b365['up'])} | — |" if b365 else "| (un día cualquiera) | — | — | — | — |")

    # ---- HOY
    dias, n = G["dias"], len(G["dias"])
    i = n - 1
    print("\n" + "=" * 100)
    print(f"=== HOY ({dias[i]}; datos on-chain usables desde el día siguiente a su fecha) ===")
    print(f"  Puntaje Z = {G['Z'][i] if G['Z'][i] is None else f'{G['Z'][i]:+d}'} con {G['NZ'][i]} zonas con dato (compra +1, venta -1)")
    for zz in G["Zs"]:
        iu = max((j for j, v in enumerate(zz["x"]) if v is not None), default=None)
        if iu is None:
            continue
        v, rk, zv = zz["x"][iu], zz["r"][iu], zz["z"][iu]
        vals = [t for t in zz["x"] if t is not None]
        est = "sin percentil todavía" if zv is None else "EN ZONA DE COMPRA" if zv == 1 else "EN ZONA DE VENTA" if zv == -1 else "neutra"
        obs = f" (último dato {dias[iu]})" if iu != i else ""
        print(f"    {zz['nom']:<42} valor {v:>10.4g}{obs} · pctl {'—' if rk is None else f'{rk:.0f}'} · {est:<20} · compra: {texto_spec(zz['compra'], vals)} · venta: {texto_spec(zz['venta'], vals)}")
    T = G["T"][i]
    print(f"  Termómetro: {'—' if T is None else f'{T:.0f}'} (0 barato, 100 caro; {G['Tdesc']})")
    px = G["P"][i]
    rs = G["sth"][i] if G["sth"] else None
    print(f"  Tendencia: precio {px:,.0f} · precio/costo STH {num(rs)} ({'arriba' if rs and rs > 1 else 'abajo' if rs else 'sin dato'}) · "
          f"{'arriba' if G['up200'][i] else 'abajo' if G['up200'][i] is not None else 'sin dato'} de la media de 200 d ({'—' if G['m200'][i] is None else f'{G['m200'][i]:,.0f}'}) · "
          f"retorno 30 d {signed(G['ret30'][i], 1)} · 90 d {signed(G['ret90'][i], 1)}"
          f" · precio/CVDD {num(G['cvdd'][i]) if G['cvdd'] else '—'} · MVRV {num(G['mv'][i]) if G['mv'] else '—'}")
    et = labs[i]
    print(f"\n  >>> ETIQUETA DE HOY: {et.upper() if et else 'sin puntaje'}")
    if et in ETIQ:
        print(f"      regla: {txt[et]} · veredicto fuera de muestra: {G['ver'][et]}")
        print("      lo que pasó históricamente después de esta etiqueta:")
        for k, (tn, _, _) in enumerate(TRAMOS):
            print(linea(et, tn, medir(labs, et, {k}), "        "))
        print(linea(et, "todo", medir(labs, et, todo), "        "))
        for (e2, fit), r in sorted(G["res_cruz"].items(), key=lambda kv: kv[0][1]):
            if e2 == et:
                print(linea(et, f"fuera de muestra (ajuste {TRAMOS[fit][0]})", r, "        "))
        print(linea_base("todo", todo))
    elif et == SIN:
        print("      (sin señal: no se muestra ninguna etiqueta general)")


# ---------------------------------------------------------------- modo prueba / principal
def _sintetico():
    f_look, f_bgeo = z3._sintetico()
    cm0 = md.f_cm
    import random
    import zlib

    def cm(activo, met, desde="2013-01-01"):
        if activo == "btc" and met == "HashRate":
            px = cm0("btc", "PriceUSD", desde)
            r = random.Random(zlib.crc32(met.encode()))
            return {k: 1e8 * (i + 1) ** 0.5 * math.exp(r.gauss(0, 0.05)) for i, k in enumerate(sorted(px))}
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
    tr = [None if d < TRAMOS[0][1] else 0 if d < TRAMOS[1][1] else 1 for d in dias]
    G.update(o=o, dias=dias, P=P, tr=tr)
    armar_datos()
    Z, NZ = G["Z"], G["NZ"]
    print("\nZonas con dato / puntaje Z: " + " · ".join(
        f"{d}: {NZ[dias.index(d)]} zonas, Z {Z[dias.index(d)]}" for d in ("2013-01-01", "2015-01-01", "2019-12-31", "2023-01-01") if d in dias)
        + f" · {dias[-1]}: {NZ[-1]} zonas, Z {Z[-1]}", flush=True)
    if not any(z is not None for z in Z):
        print("sin puntaje Z (menos de 5 zonas con dato): no se puede medir")
        return
    G["est"] = md.etiquetas_estados(P)
    print("\nAjustando (grilla chica, 2 pasadas por ajuste)...", flush=True)
    qs1, nf1 = ajustar({0})
    qs2, nf2 = ajustar({1})
    informe(qs1, qs2, nf1, nf2)
    final()


if __name__ == "__main__":
    main()
