"""¿Cuanto pesa cada medicion en la prediccion de CADA plazo? (medir antes de sumar). Nov. 2026.

La idea (de Diego): TODO lo que se mide tiene que alimentar la prediccion del plazo elegido, con el peso que los datos justifiquen PARA
ESE PLAZO (si estamos en pisos de mercado, el dia / la semana / el mes se inclinan a "compra", pero con el peso medido). medir_estado.py
ya dice si la etiqueta acierta a 90 d y 365 d; aca se mide a lo que usa la app: 1, 7 y 30 dias (90 de referencia) y se convierte en
puntos para el sistema de analisis_btc.central() (la direccion se decide con ±2,5 puntos).

Que se mide (BTC diario de CoinMetrics; ningun dato mira el futuro; un dato on-chain / publicado se usa desde el dia siguiente):
  1. ESTADOS: para cada dia, la etiqueta de medir_estado (REGLAS FINALES fijas: kpe=6, k1=2, k2=3, r=0,10; piso extremo tambien con
     precio/CVDD <= 1,2 o MVRV <= 1; rally = precio > costo STH y > media 200 d y retorno 90 d > 10%; "zona neutral" = la indecision).
     A 1, 7, 30 y 90 dias (cierre de hoy al cierre de h dias despues): % que sube y retorno medio de cada estado contra un dia normal del
     MISMO tramo; z con n efectivo = bloques no solapados de h dias (i // h). Tambien Z continuo (Spearman) y la tendencia sola.
  2. SEÑALES INDIVIDUALES, cada una con su lado esperado y el mismo metodo: MVRV (bandas en desvios con media y desvio expansivos, y
     percentil <= 15 / >= 85), VIX (nivel en el 10% de arriba del año, salto de 1 dia > +20%, VIX > VIX3M; los dos lados, miedo ->
     compra o -> venta, y se reporta cual), flujos de los ETF de BTC (Farside; diario y suma de 5 ruedas, 10% de arriba / abajo; los
     dos lados), Fear & Greed (<= 25 / >= 75 y <= 10 / >= 90), cada una de las zonas del puntaje Z (zona de compra prendida -> sube;
     de venta -> baja; incluye CVDD, precio balanceado, RHODL, % oferta en ganancia, costo STH, aSOPR y perdida realizada), SOPR 7 d / 30 d
     bajo / alto (p10 / p90 de los 2 años previos), NUPL < 0 / > 0,75, y los casi-pasaron: liquidez neta de la Fed (cambio 13 semanas en el
     20% de arriba / abajo de 3 años) y atencion de Wikipedia 7 d / 365 d en el 10% de arriba.
  3. PESO por (señal o estado, plazo), conservador: ventaja = el MENOR entre los dos tramos de (% que sube con la señal - % normal), en
     puntos, con el signo del lado esperado. Peso 0 si la ventaja no es del lado esperado en los dos tramos o si el z mas bajo de los dos
     tramos (incluye al tramo mas chico) es < 1; si no: 0,5 si la ventaja es de 2 a 4 puntos, 1 de 4 a 8, 1,5 de 8 a 12, 2 si pasa de 12.
     Plazos de la app: 1 dia -> 1 d, 1 semana -> 7 d, 1 mes -> 30 d. 4 horas: se informa la ventaja de 1 d / 6 y el peso es 0,5 solo si la
     ventaja de 1 d pasa de 6 puntos en los dos tramos con z >= 1; 5 min, 15 min y 1 hora: 0.
     Una señal con historia corta (ETF, Fear & Greed...) usa sus PROPIOS dos tramos (la mitad de su historia cada uno, se muestran); con menos
     de 2 años de datos: peso 0 ("historia corta").
  4. Sobre el estado: de cada señal que no es una zona (las zonas YA estan dentro del estado) se mide si SUMA dentro del mismo estado
     (% que sube con vs sin la señal, estratificado por estado) y se pesa igual ("peso_sobre_estado").
  5. Redundancias (para no contar dos veces lo mismo): Spearman |r| >= 0,8 entre las versiones continuas, >= 80% de superposicion de los
     dias prendidos (mismo lado), o >= 80% de los dias de la señal dentro de un estado del mismo lado. Recomendacion combinada: peso del
     estado + solo extras no redundantes con peso (el menor entre el peso solo y el peso sobre el estado).
  6. No se mide aca cuanto coincide el estado con la llamada actual de corto plazo de la app (eso solo se ve en vivo, medir_central.py).
  Salida: tablas compactas, "PESOS PARA EL ANALISIS" (a: pesos por estado; b: registro de cada señal x plazo; dict de Python y objeto de JS)
  y HOY.

Uso: python medir_peso_ciclo.py [corte [desde]]    (por defecto 2020-01-01 y 2013-01-01: tramos 2013-19 y 2020-26)
     python medir_peso_ciclo.py 2024-01-01 2022-01-01      (solo 2022-2026, partido en 2022-23 y 2024-26; el Z se calcula igual
                                                           con toda la historia, solo se mide en esa ventana)
     python medir_peso_ciclo.py --prueba     (sin internet: series sinteticas para probar el codigo de punta a punta)
"""
import json
import math
import pprint
import random
import statistics
import sys
import zlib
from datetime import date, timedelta

import medir_diarios as md                     # fetchers (liquidez, Wikipedia, VIX), percentil trailing, Spearman (comparte argv)
import medir_estado as me                      # etiquetas, Z, tendencia y reglas finales
import medir_onchain_ciclo as oc               # looknode (SOPR, NUPL), cache
from medir_zonas import rank_exp

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
PRUEBA = "--prueba" in sys.argv
CORTE = ARGS[0] if ARGS else "2020-01-01"
DESDE = ARGS[1] if len(ARGS) > 1 else "2013-01-01"
CACHE = "cache_estado.json"
HS = (1, 7, 30, 90)
PLAZOS = {"1 día": 1, "1 semana": 7, "1 mes": 30}                # plazos de la app con medicion directa
REF = "90 días (ref.)"
CORTOS = ("5 min", "15 min", "1 hora", "4 horas")
Q_FINAL = {**me.DEF, "kpe": 6, "k1": 2, "k2": 3, "r": 0.10}      # REGLAS FINALES de medir_estado (fijas)
NOM = {me.PISO_X: "piso extremo", me.TECHO: "posible techo", me.PISO: "cerca de un piso", me.RALLY: "rally alcista en curso",
       me.INDEC: "zona neutral", me.SIN: "zona neutral"}
ESTADOS = ("piso extremo", "cerca de un piso", "posible techo", "rally alcista en curso", "zona neutral")
LADO = {"piso extremo": 1, "cerca de un piso": 1, "rally alcista en curso": 1, "posible techo": -1, "zona neutral": 0}
G = {}
SIG, CONT = [], {}                                                # señales individuales y series continuas (para redundancias)


# ---------------------------------------------------------------- utilidades de formato (las de medir_estado)
pct, num, zf, signed = me.pct, me.num, me.zf, me.signed


def pts(x, d=1):
    if x is not None and abs(x) < 0.5 * 10 ** -d:
        x = 0.0                                                  # evita "-0,0"
    return "—" if x is None else f"{x:+.{d}f}".replace(".", ",")


# ---------------------------------------------------------------- estadistica
def stats(sel, h):
    """Dias de `sel` con retorno a h dias: n, % que sube, retorno medio y bloques no solapados de h dias (n efectivo)."""
    R = G["R"][h]
    ix = [i for i in sel if R[i] is not None]
    if not ix:
        return None
    v = [R[i] for i in ix]
    return dict(n=len(v), up=sum(1 for x in v if x > 0) / len(v), med=statistics.fmean(v), ne=len({i // h for i in ix}))


def normal(t, h):
    if (t, h) not in G["normal"]:
        G["normal"][(t, h)] = stats([i for i in range(len(G["dias"])) if G["tr"][i] == t and G["lab"][i] is not None], h)
    return G["normal"][(t, h)]


def celda(sel, t, h, base=None, tr=None):
    """El conjunto de dias `sel` (en el tramo t) contra un dia normal del mismo tramo (o contra `base`): dif en puntos y z."""
    tr = tr or G["tr"]
    s = stats([i for i in sel if tr[i] == t], h)
    b = base if base is not None else normal(t, h)
    c = dict(s=s, b=b, edge=None, z=None)
    if s and b:
        c["edge"] = 100 * (s["up"] - b["up"])
        if s["ne"] >= 4 and 0 < b["up"] < 1:
            c["z"] = (s["up"] - b["up"]) / math.sqrt(b["up"] * (1 - b["up"]) / s["ne"])
    return c


def banda(e):
    return 0.0 if e < 2 else 0.5 if e < 4 else 1.0 if e < 8 else 1.5 if e <= 12 else 2.0


def peso_de(cs, lado, minimo=2.0):
    """(peso, motivo) con la regla conservadora: ventaja minima de los dos tramos en el lado esperado y z minimo >= 1."""
    if lado == 0:
        return 0.0, "sin lado esperado"
    if cs is None or any(c["edge"] is None or c["z"] is None for c in cs):
        return 0.0, "sin z (menos de 4 bloques o falta un tramo)"
    e = [lado * c["edge"] for c in cs]
    z = [lado * c["z"] for c in cs]
    if min(e) <= 0:
        return 0.0, "no repite el lado en los dos tramos"
    if min(z) < 1:
        return 0.0, f"z mínimo {zf(min(z))} < 1"
    if min(e) < minimo:
        return 0.0, f"ventaja mínima {pts(min(e))} pts < {minimo:g}"
    if min(z) < 2:                     # evidencia mas floja (z 1-2 en algun tramo): la mitad del peso, minimo 0,5
        return max(0.5, banda(min(e)) / 2), "ok (z < 2 en un tramo: mitad del peso)"
    return banda(min(e)), "ok"


def texto_celda(c):
    s, b = c["s"], c["b"]
    if not s or not b:
        return "sin datos"
    return (f"n {s['n']:>4} b{s['ne']:<3} sube {pct(s['up'])} vs {pct(b['up'])} ({pts(c['edge'])} pts z {zf(c['z'])}) "
            f"media {signed(s['med'], 1)} vs {signed(b['med'], 1)}")


def incremental(M, h, t, tr=None):
    """Con vs sin la señal DENTRO del mismo estado, estratificado por estado: dif en puntos, z y dias con la señal."""
    tr = tr or G["tr"]
    n = len(G["dias"])
    R = G["R"][h]
    num_, den, var, dias_m, ne_m = 0.0, 0.0, 0.0, 0, 0
    for e in ESTADOS:
        con = [i for i in range(n) if tr[i] == t and G["lab"][i] == e and M[i] is True and R[i] is not None]
        sin = [i for i in range(n) if tr[i] == t and G["lab"][i] == e and M[i] is False and R[i] is not None]
        a, b = stats(con, h), stats(sin, h)
        if not a or not b or a["ne"] < 2 or b["ne"] < 2:
            continue
        p = (sum(1 for i in con + sin if R[i] > 0) + 1) / (len(con) + len(sin) + 2)
        pq = max(p * (1 - p), 0.05)
        w = a["n"]
        num_ += w * (a["up"] - b["up"])
        den += w
        var += w * w * pq * (1 / a["ne"] + 1 / b["ne"])
        dias_m += a["n"]
        ne_m += a["ne"]
    if not den or not var:
        return dict(edge=None, z=None, n=0, ne=0)
    d = num_ / den
    return dict(edge=100 * d, z=d / (math.sqrt(var) / den), n=dias_m, ne=ne_m)


# ---------------------------------------------------------------- datos
def preparar():
    if PRUEBA:
        print("MODO PRUEBA: series sintéticas, sin internet")
        me.G["F_LOOK"], me.G["F_BGEO"] = me._sintetico()
        oc.F_LOOK, oc.F_BGEO = me.G["F_LOOK"], me.G["F_BGEO"]
        oc.guardar_cache = lambda *_: None
    else:
        me.G["F_LOOK"], me.G["F_BGEO"] = oc.f_look, oc.f_bgeo
        oc.F_LOOK, oc.F_BGEO = oc.f_look, oc.f_bgeo
        oc.CACHE = CACHE
    print("Fuentes:", flush=True)
    px = md.intentar("BTC PriceUSD", md.f_cm, "btc", "PriceUSD", "2010-07-01")
    if not px:
        return False
    o0, o1 = date.fromisoformat(min(px)).toordinal(), date.fromisoformat(max(px)).toordinal()
    o = list(range(o0, o1 + 1))
    dias = [date.fromordinal(x).isoformat() for x in o]
    P, u = [], None
    for d in dias:
        u = px.get(d, u)
        P.append(u)
    me.G.update(o=o, dias=dias, P=P)
    me.armar_datos()
    if not any(z is not None for z in me.G["Z"]):
        print("sin puntaje Z (menos de 5 zonas con dato): no se puede medir")
        return False
    G.update(o=o, dias=dias, P=P, normal={})
    G["tr"] = [None if d < DESDE else 0 if d < CORTE else 1 for d in dias]
    G["R"] = md.retornos(P, HS)
    G["tn"] = (f"{DESDE[:4]}-{str(int(CORTE[:4]) - 1)[2:]}", f"{CORTE[:4]}-{dias[-1][2:4]}")
    return True


def etiquetas():
    labs = me.etiquetar(Q_FINAL)
    G["labs"] = labs
    G["lab"] = [None if x is None else NOM[x] for x in labs]
    n = len(labs)
    sth, m200, r90 = me.G["sth"], me.G["m200"], me.G["ret90"]
    P = G["P"]
    G["rsth"] = sth
    G["rm200"] = [None if m200[i] is None else P[i] / m200[i] for i in range(n)]
    G["mom"] = {
        "precio > costo STH": None if not sth else [None if sth[i] is None else sth[i] > 1 for i in range(n)],
        "precio > media 200 d": [None if m200[i] is None else P[i] > m200[i] for i in range(n)],
        "retorno 90 d > 0": [None if r90[i] is None else r90[i] > 0 for i in range(n)],
    }
    for t, tn in enumerate(G["tn"]):
        ix = [i for i in range(n) if G["tr"][i] == t and G["lab"][i] is not None]
        print(f"  tramo {tn}: {G['dias'][ix[0]]} a {G['dias'][ix[-1]]} ({len(ix)} días con etiqueta) · " + " · ".join(
            f"{e} {sum(1 for i in ix if G['lab'][i] == e)}" for e in ESTADOS) if ix else f"  tramo {tn}: sin días con etiqueta", flush=True)


# ---------------------------------------------------------------- fetchers propios (con version de prueba)
def _dias_desde(ini):
    d = ini
    while d <= date.today():
        yield d
        d += timedelta(1)


def f_etf():
    """{fecha: flujo neto diario (millones de USD)} de los ETF de BTC de EE.UU. (Farside, historia completa)."""
    if PRUEBA:
        r = random.Random(11)
        return {d.isoformat(): r.gauss(100, 400) for d in _dias_desde(date(2024, 1, 11)) if d.weekday() < 5}
    import noticias
    filas = noticias.parse_farside(noticias._get(noticias.FARSIDE, 60), 10 ** 6)
    if not filas:
        raise ValueError("Farside sin filas (¿bloqueo?)")
    return {f["fecha"]: f["neto"] for f in filas}


def f_fng():
    if PRUEBA:
        r, x, out = random.Random(7), 50.0, {}
        for d in _dias_desde(date(2018, 2, 1)):
            x = min(100.0, max(0.0, x + r.gauss(0, 5) + (50 - x) * 0.03))
            out[d.isoformat()] = float(round(x))
        return out
    from medir_zonas import fng
    d = fng()
    if not d:
        raise ValueError("sin datos de Fear & Greed")
    return d


def liquidez_neta(o):
    A = md.intentar("Fed activos totales", md.f_fed_activos)
    T = md.intentar("TGA", md.f_tga)
    R = md.intentar("RRP", md.f_rrp)
    if not (A and T and R):
        raise ValueError("falta alguna pata de la liquidez neta (activos, TGA o RRP)")
    a, t, r = md.alinear(A, o, 2, 21), md.alinear(T, o, 2, 21), md.alinear(R, o, 1, 7)
    primero_r = date.fromisoformat(min(R)).toordinal()
    net = []
    for i in range(len(o)):
        rr = r[i] if r[i] is not None else (0.0 if o[i] < primero_r else None)      # antes de que existiera el RRP, cero
        net.append(None if a[i] is None or t[i] is None or rr is None else a[i] - t[i] - rr)
    return net


# ---------------------------------------------------------------- registro de señales
def reg(nom, grupo, serie, on, lado, desc, comp=False):
    """on: lista de True / False / None sobre el calendario de BTC. comp: la señal ya esta dentro del estado (zonas del puntaje Z)."""
    dias_on = sum(1 for x in on if x)
    if not dias_on:
        print(f"  {nom}: nunca prendida, se saltea", flush=True)
        return
    SIG.append(dict(nom=nom, grupo=grupo, serie=serie, on=on, lado=lado, desc=desc, comp=comp))


def umbral(x, f):
    return [None if v is None else bool(f(v)) for v in x]


def armar_senales():
    o, n = G["o"], len(G["o"])
    cr = oc.cargar_cache() if not PRUEBA else {"dia": "prueba", "look": {}, "bgeo": {}}

    def bloque(nombre, fn):
        try:
            fn()
        except Exception as e:
            print(f"  señales {nombre} no: {type(e).__name__}: {e}", flush=True)

    # ---- las zonas del puntaje Z (ya estan dentro del estado)
    def zonas():
        for zz in me.G["Zs"]:
            CONT["zona: " + zz["nom"]] = zz["x"]
            if zz["compra"] is not None:
                reg(f"zona de compra: {zz['nom']}", "zona del ciclo", "zona: " + zz["nom"], umbral(zz["z"], lambda v: v == 1), 1,
                    f"compra {me.texto_spec(zz['compra'], [t for t in zz['x'] if t is not None])}", comp=True)
            if zz["venta"] is not None:
                reg(f"zona de venta: {zz['nom']}", "zona del ciclo", "zona: " + zz["nom"], umbral(zz["z"], lambda v: v == -1), -1,
                    f"venta {me.texto_spec(zz['venta'], [t for t in zz['x'] if t is not None])}", comp=True)
    bloque("zonas", zonas)
    CONT["puntaje Z"] = me.G["Z"]

    # ---- MVRV: bandas en desvios (media y desvio expansivos) y percentil
    def mvrv():
        mv = me.G["mv"]
        if not mv:
            raise ValueError("sin MVRV")
        z, s, s2, k = [None] * n, 0.0, 0.0, 0
        for i, v in enumerate(mv):
            if v is None:
                continue
            s += v
            s2 += v * v
            k += 1
            if k >= 730:
                mu = s / k
                sd = math.sqrt(max(0.0, s2 / k - mu * mu))
                z[i] = (v - mu) / sd if sd > 0 else None
        CONT["MVRV en desvíos"] = z
        CONT["MVRV percentil"] = rank_exp(mv, minimo=730)
        for k_, lado, t in ((-0.5, 1, "<="), (-1.0, 1, "<="), (1.5, -1, ">="), (2.0, -1, ">=")):
            reg(f"MVRV {t} {k_:+g}σ".replace(".", ","), "MVRV", "MVRV en desvíos", umbral(z, (lambda v, k_=k_, t=t: v <= k_ if t == "<=" else v >= k_)), lado,
                f"MVRV {t} {k_:+g} desvíos (media y desvío hasta ese día)")
        rk = CONT["MVRV percentil"]
        reg("MVRV percentil <= 15", "MVRV", "MVRV percentil", umbral(rk, lambda v: v <= 15), 1, "MVRV en el 15% de abajo de su historia")
        reg("MVRV percentil >= 85", "MVRV", "MVRV percentil", umbral(rk, lambda v: v >= 85), -1, "MVRV en el 15% de arriba de su historia")
    bloque("MVRV", mvrv)

    # ---- VIX (los dos lados)
    def vix():
        vx = md.intentar("VIX", md.f_vix, "VIX")
        if not vx:
            raise ValueError("sin VIX")
        v3 = md.intentar("VIX3M", md.f_vix, "VIX3M")
        ks = sorted(vx)
        v = [vx[k] for k in ks]
        c1 = [None] + [v[i] / v[i - 1] - 1 if v[i - 1] else None for i in range(1, len(v))]
        pn = md.pct_trailing(v, 252)                                      # 252 ruedas ~ 1 año
        al = lambda lst: md.alinear(dict(zip(ks, lst)), o, 1, 6)
        nivel, pniv, jump = al(v), al(pn), al(c1)
        CONT["VIX nivel"] = nivel
        pares = [("VIX alto (10% de arriba del año)", umbral(pniv, lambda x: x >= 0.9), "VIX nivel"),
                 ("VIX salto de 1 día > +20%", umbral(jump, lambda x: x > 0.2), "VIX salto 1 d")]
        CONT["VIX salto 1 d"] = jump
        if v3:
            inv = md.alinear({k: vx[k] / v3[k] for k in vx if k in v3 and v3[k]}, o, 1, 6)
            CONT["VIX / VIX3M"] = inv
            pares.append(("VIX > VIX3M (estructura invertida)", umbral(inv, lambda x: x > 1), "VIX / VIX3M"))
        for nom, on, serie in pares:
            reg(nom + " -> compra (el miedo es piso)", "VIX", serie, on, 1, nom + "; lado: compra")
            reg(nom + " -> venta (el miedo sigue)", "VIX", serie, on, -1, nom + "; lado: venta")
    bloque("VIX", vix)

    # ---- flujos de ETF (Farside, desde 2024; los dos lados)
    def etf():
        d = md.intentar("ETF flujos (Farside)", f_etf)
        if not d:
            raise ValueError("sin flujos de ETF")
        ks = sorted(d)
        v = [d[k] for k in ks]
        s5 = [None] * 4 + [sum(v[i - 4:i + 1]) for i in range(4, len(v))]
        al = lambda lst: md.alinear(dict(zip(ks, lst)), o, 1, 1)          # solo el dia siguiente a la publicacion
        for tag, serie in (("diario", v), ("suma 5 ruedas", s5)):
            p = al(md.pct_trailing(serie, 252, 60))
            CONT[f"ETF flujo {tag}"] = al(serie)
            reg(f"ETF entrada {tag} en el 10% de arriba -> sube", "ETF", f"ETF flujo {tag}", umbral(p, lambda x: x >= 0.9), 1, "entran más que lo normal; lado: compra")
            reg(f"ETF entrada {tag} en el 10% de arriba -> baja", "ETF", f"ETF flujo {tag}", umbral(p, lambda x: x >= 0.9), -1, "entran más que lo normal; lado: venta (al revés)")
            reg(f"ETF salida {tag} en el 10% de abajo -> baja", "ETF", f"ETF flujo {tag}", umbral(p, lambda x: x <= 0.1), -1, "salen más que lo normal; lado: venta")
            reg(f"ETF salida {tag} en el 10% de abajo -> sube", "ETF", f"ETF flujo {tag}", umbral(p, lambda x: x <= 0.1), 1, "salen más que lo normal; lado: compra (al revés)")
    bloque("ETF", etf)

    # ---- Fear & Greed
    def fng():
        d = md.intentar("Fear & Greed", f_fng)
        if not d:
            raise ValueError("sin Fear & Greed")
        x = md.alinear(d, o, 1, 3)
        CONT["Fear & Greed"] = x
        for lim, lado, t in ((25, 1, "<="), (10, 1, "<="), (75, -1, ">="), (90, -1, ">=")):
            reg(f"Fear & Greed {t} {lim}", "Fear & Greed", "Fear & Greed", umbral(x, (lambda v, lim=lim, t=t: v <= lim if t == "<=" else v >= lim)), lado,
                f"índice {t} {lim}; lado: {'compra' if lado > 0 else 'venta'}")
    bloque("Fear & Greed", fng)

    # ---- SOPR y NUPL (looknode)
    def sopr():
        d = oc.bajar_look(cr, "sopr")
        if not d:
            raise ValueError("sin SOPR de looknode")
        x = md.alinear(oc.columna(d, 0), o, 1, 5)
        for w in (7, 30):
            m = md.rodar(x, w, statistics.fmean)
            p = md.pct_trailing(m, 730, 365)
            CONT[f"SOPR {w} d"] = m
            reg(f"SOPR {w} d bajo (p10 de 2 años)", "SOPR", f"SOPR {w} d", umbral(p, lambda q: q <= 0.10), 1, f"SOPR media {w} d en el 10% de abajo (capitulación)")
            reg(f"SOPR {w} d alto (p90 de 2 años)", "SOPR", f"SOPR {w} d", umbral(p, lambda q: q >= 0.90), -1, f"SOPR media {w} d en el 10% de arriba (euforia)")
    bloque("SOPR", sopr)

    def nupl():
        d = oc.bajar_look(cr, "NUPL")
        if not d:
            raise ValueError("sin NUPL de looknode")
        col = oc.columna(d, 0)
        if col and max(abs(v) for v in col.values()) > 1.5:
            col = {k: v / 100 for k, v in col.items()}
        x = md.alinear(col, o, 1, 5)
        CONT["NUPL"] = x
        reg("NUPL < 0", "NUPL", "NUPL", umbral(x, lambda v: v < 0), 1, "ganancia no realizada neta negativa")
        reg("NUPL > 0,75", "NUPL", "NUPL", umbral(x, lambda v: v > 0.75), -1, "ganancia no realizada neta muy alta")
    bloque("NUPL", nupl)

    # ---- casi-pasaron: liquidez de la Fed y atencion de Wikipedia
    def liquidez():
        v = md.cambio(liquidez_neta(o), 91)
        p = md.pct_trailing(v, 1095)
        CONT["liquidez neta 13 sem"] = v
        reg("liquidez Fed sube (13 sem, 20% de arriba)", "liquidez Fed", "liquidez neta 13 sem", umbral(p, lambda q: q >= 0.80), 1, "cambio de 13 semanas en el 20% de arriba de 3 años")
        reg("liquidez Fed cae (13 sem, 20% de abajo)", "liquidez Fed", "liquidez neta 13 sem", umbral(p, lambda q: q <= 0.20), -1, "cambio de 13 semanas en el 20% de abajo de 3 años")
    bloque("liquidez", liquidez)

    def atencion():
        w = md.intentar("Wikipedia pageviews Bitcoin", md.f_wiki)
        if not w:
            raise ValueError("sin pageviews")
        x = md.alinear(w, o, 1, 5)
        m7, m365 = md.rodar(x, 7, statistics.fmean), md.rodar(x, 365, statistics.fmean)
        ratio = [None if a is None or not b else a / b for a, b in zip(m7, m365)]
        p = md.pct_trailing(ratio, 365)
        CONT["atención Wikipedia 7d/365d"] = ratio
        reg("atención Wikipedia alta (10% de arriba)", "atención", "atención Wikipedia 7d/365d", umbral(p, lambda q: q >= 0.90), -1, "atención 7 d / 365 d en el 10% de arriba (euforia)")
    bloque("atención", atencion)


# ---------------------------------------------------------------- evaluacion de una señal
def tramos_de(on):
    """(tr, nombres, propios) para una señal: los tramos globales si los dos tienen >= 365 dias con dato; si no, la mitad de su historia
    cada uno (si tiene >= 730 dias); si no, None (historia corta)."""
    n = len(on)
    ix = [i for i in range(n) if on[i] is not None and G["tr"][i] is not None]
    if min(sum(1 for i in ix if G["tr"][i] == t) for t in (0, 1)) >= 365:
        return G["tr"], G["tn"], False, ix
    if len(ix) >= 730:
        mid = ix[len(ix) // 2]
        tr = [None] * n
        for i in ix:
            tr[i] = 0 if i < mid else 1
        d = G["dias"]
        return tr, (f"{d[ix[0]][:7]}..{d[mid - 1][:7]}", f"{d[mid][:7]}..{d[ix[-1]][:7]}"), True, ix
    return None, None, True, ix


def evaluar_senal(s):
    """Llena s['res'][h] = (celdas, peso, motivo) y s['inc'][h] = (celdas, peso, motivo) (sobre el estado, solo si no es zona)."""
    on = s["on"]
    tr, tn, propios, ix = tramos_de(on)
    s["tn"], s["propios"], s["res"], s["inc"], s["dias_on"] = tn, propios, {}, {}, [0, 0]
    if tr is None:
        s["corta"] = True
        return
    s["corta"] = False
    s["dias_on"] = [sum(1 for i in ix if on[i] and tr[i] == t) for t in (0, 1)]
    s["tr"] = tr
    for h in HS:
        cs = [celda([i for i in ix if on[i]], t, h, base=stats([i for i in ix if tr[i] == t], h), tr=tr) for t in (0, 1)]
        w, mot = peso_de(cs, s["lado"])
        s["res"][h] = (cs, w, mot)
        if not s["comp"]:
            ci = []
            for t in (0, 1):
                inc = incremental(on, h, t, tr)
                ci.append(dict(s=None, b=None, edge=inc["edge"], z=inc["z"], n=inc["n"], ne=inc["ne"]))
            s["inc"][h] = (ci, *peso_de(ci, s["lado"]))


def peso_registro(s, plazo, h=None):
    """Peso final de una señal en un plazo de la app."""
    if plazo in CORTOS:
        if plazo != "4 horas" or s["corta"] or s["lado"] == 0:
            return 0.0, "corto plazo: sin medición propia" if plazo != "4 horas" else "sin historia suficiente"
        cs = s["res"][1][0]
        if any(c["edge"] is None or c["z"] is None for c in cs):
            return 0.0, "sin z a 1 d"
        w, mot = peso_de(cs, s["lado"], minimo=6.0)
        return (0.5 if w > 0 else 0.0), ("ventaja de 1 d > 6 pts en los dos tramos" if w > 0 else "1 d: " + mot)
    if s["corta"]:
        return 0.0, "historia corta (< 2 años)"
    return s["res"][h][1], s["res"][h][2]


# ---------------------------------------------------------------- tablas
def tabla_estados():
    """RES[(h, estado)] = (celdas por tramo, peso, motivo)."""
    n = len(G["dias"])
    RES = {}
    print("\n" + "=" * 110)
    print("=== 1. ESTADO -> % que sube y retorno medio a h días, contra un día normal del mismo tramo "
          "(n = días, bK = bloques no solapados de h días) ===")
    for h in HS:
        print(f"\n--- a {h} d{' (referencia)' if h == 90 else ''} ---")
        for e in ESTADOS:
            sel = [i for i in range(n) if G["lab"][i] == e]
            cs = [celda(sel, t, h) for t in (0, 1)]
            w, mot = peso_de(cs, LADO[e])
            RES[(h, e)] = (cs, w, mot)
            print(f"  {e:<24}" + "".join(f" | {G['tn'][t]}: {texto_celda(c)}" for t, c in enumerate(cs))
                  + f" | peso {num(w, 1)} ({mot})", flush=True)
        for t in (0, 1):
            b = normal(t, h)
            print(f"  (normal {G['tn'][t]}: sube {pct(b['up']) if b else '—'} · media {signed(b['med'], 1) if b else '—'} · n {b['n'] if b else 0})")
    return RES


def tabla_z():
    print("\n" + "=" * 110)
    print("=== 2. PUNTAJE Z CONTINUO: Spearman con el retorno a h días (z con n efectivo = días // h) ===")
    n = len(G["dias"])
    Z = me.G["Z"]
    for h in HS:
        txt, zs = f"  a {h:>2} d", []
        for t in (0, 1):
            ix = [i for i in range(n) if G["tr"][i] == t and Z[i] is not None and G["R"][h][i] is not None]
            r, _ = md.spearman([Z[i] for i in ix], [G["R"][h][i] for i in ix]) if len(ix) >= 6 else (None, None)
            z = None if r is None else r * math.sqrt(max(len(ix) // h - 1, 1))
            zs.append(z)
            txt += f" | {G['tn'][t]}: n {len(ix):>4} r {'—' if r is None else f'{r:+.3f}'} z {zf(z)}"
        ok = all(z is not None for z in zs)
        v = ("mismo signo, ambos |z| >= 2" if ok and all(abs(z) >= 2 for z in zs) and zs[0] * zs[1] > 0 else
             "mismo signo, sin llegar a z 2" if ok and zs[0] * zs[1] > 0 else "signos distintos" if ok else "sin datos")
        print(txt + f" | {v}", flush=True)


def tabla_momentum():
    print("\n" + "=" * 110)
    print("=== 3. TENDENCIA SOLA (informativo, no suma peso: el rally ya es un estado) — % que sube contra un día normal ===")
    n = len(G["dias"])
    for nom, v in G["mom"].items():
        if v is None:
            print(f"  {nom}: sin datos")
            continue
        for h in HS:
            cs = [celda([i for i in range(n) if v[i] and G["lab"][i] is not None], t, h) for t in (0, 1)]
            print(f"  {nom:<22} a {h:>2} d" + "".join(f" | {G['tn'][t]}: {texto_celda(c)}" for t, c in enumerate(cs)), flush=True)


def tabla_senales():
    print("\n" + "=" * 110)
    print("=== 4. SEÑALES INDIVIDUALES (cada una contra un día normal del mismo tramo, dentro de los días con dato de esa señal) ===")
    print("  por plazo: ventaja mínima de los dos tramos en el lado esperado (pts) / z mínimo → peso; 'sobre el estado' = peso si se la mide dentro del mismo estado; * = con peso")
    for s in SIG:
        print(f"\n  [{s['grupo']}] {s['nom']} · lado {'sube' if s['lado'] > 0 else 'baja'}" + (" · YA ESTÁ DENTRO DEL ESTADO (zona del puntaje Z)" if s["comp"] else ""))
        if s["corta"]:
            ix = [i for i, x in enumerate(s["on"]) if x is not None]
            print(f"      historia corta: {len(ix)} días con dato → peso 0 en todos los plazos")
            continue
        print(f"      tramos {'PROPIOS' if s['propios'] else 'globales'}: {s['tn'][0]} y {s['tn'][1]} · días prendida {s['dias_on'][0]} / {s['dias_on'][1]}")
        for h in HS:
            cs, w, mot = s["res"][h]
            e = [s["lado"] * c["edge"] if c["edge"] is not None else None for c in cs]
            z = [s["lado"] * c["z"] if c["z"] is not None else None for c in cs]
            ok = None not in e
            ver = "" if not s["inc"] else f" | sobre el estado: peso {num(s['inc'][h][1], 1)} ({s['inc'][h][2]})"
            print(f"      a {h:>2} d: " + " · ".join(
                f"{s['tn'][t]} sube {pct(c['s']['up']) if c['s'] else '—'} vs {pct(c['b']['up']) if c['b'] else '—'} ({pts(c['edge'])} pts, z {zf(c['z'])}, b{c['s']['ne'] if c['s'] else 0})"
                for t, c in enumerate(cs)) + f" → mín {pts(min(e)) if ok else '—'} pts / z {zf(min(x for x in z if x is not None)) if None not in z else '—'} → peso {num(w, 1)}{'*' if w else ''}" + ver, flush=True)


# ---------------------------------------------------------------- redundancias
def redundancias():
    """Devuelve RED[nom] = dict(con=[nombres], contenida={estado: fraccion}); y las parejas de series continuas con |Spearman| >= 0,8."""
    n = len(G["dias"])
    on_ix = {s["nom"]: {i for i in range(n) if s["on"][i] and G["tr"][i] is not None} for s in SIG}
    RED = {s["nom"]: dict(con=[], contenida={}) for s in SIG}
    # continuas: Spearman entre series
    pares_c, claves = [], list(CONT)
    for a in range(len(claves)):
        for b in range(a + 1, len(claves)):
            x, y = CONT[claves[a]], CONT[claves[b]]
            ix = [i for i in range(n) if x[i] is not None and y[i] is not None and G["tr"][i] is not None]
            if len(ix) < 200:
                continue
            r, _ = md.spearman([x[i] for i in ix], [y[i] for i in ix])
            if r is not None and abs(r) >= 0.8:
                pares_c.append((claves[a], claves[b], r, len(ix)))
    por_serie = {}
    for a, b, r, _ in pares_c:
        por_serie.setdefault(a, set()).add(b)
        por_serie.setdefault(b, set()).add(a)
    for s in SIG:
        for t in SIG:
            if t is s or t["serie"] == s["serie"] and t["lado"] != s["lado"]:
                continue
            if t["serie"] != s["serie"] and t["serie"] in por_serie.get(s["serie"], ()) and t["lado"] == s["lado"] and len(on_ix[s["nom"]]) >= 30 and len(on_ix[t["nom"]]) >= 30:
                RED[s["nom"]]["con"].append(t["nom"] + " (Spearman >= 0,8)")
                continue
            a, b = on_ix[s["nom"]], on_ix[t["nom"]]
            if t["lado"] == s["lado"] and len(a) >= 30 and len(b) >= 30 and len(a & b) >= 0.8 * min(len(a), len(b)):
                RED[s["nom"]]["con"].append(t["nom"] + " (días prendidos >= 80%)")
        if on_ix[s["nom"]]:
            for e in ESTADOS:
                f = sum(1 for i in on_ix[s["nom"]] if G["lab"][i] == e) / len(on_ix[s["nom"]])
                if f >= 0.8 and LADO[e] == s["lado"]:
                    RED[s["nom"]]["contenida"][e] = round(f, 2)
    return RED, pares_c


def imprimir_redundancias(RED, pares_c):
    print("\n" + "=" * 110)
    print("=== 5. REDUNDANCIAS (para no contar dos veces lo mismo) ===")
    print("  series continuas con |Spearman| >= 0,8:")
    for a, b, r, k in sorted(pares_c, key=lambda p: -abs(p[2])):
        print(f"    {a} ~ {b}: r {r:+.2f} (n {k})")
    if not pares_c:
        print("    ninguna pareja")
    print("  señales redundantes con otra (>= 80% de días prendidos en común, mismo lado) o contenidas en un estado del mismo lado (>= 80% de sus días):")
    hay = False
    for s in SIG:
        r = RED[s["nom"]]
        if s["comp"] and not r["contenida"]:
            continue
        if r["con"] or r["contenida"]:
            hay = True
            print(f"    {s['nom']}: " + "; ".join(r["con"][:4] + [f"{100 * f:.0f}% de sus días en «{e}»" for e, f in r["contenida"].items()]))
    if not hay:
        print("    ninguna")
    print("  (todas las zonas del puntaje Z entran en el estado: no se suman encima de él)")


# ---------------------------------------------------------------- salida para la app
def armar_pesos_estado(RES):
    pesos, medido = {}, {}
    for p in CORTOS + tuple(PLAZOS):
        pesos[p], medido[p] = {}, {}
    for e in ESTADOS:
        cs1 = RES[(1, e)][0]
        for p in CORTOS:
            w = 0.0
            if p == "4 horas" and LADO[e] != 0:
                w = 0.5 if peso_de(cs1, LADO[e], minimo=6.0)[0] > 0 else 0.0
            pesos[p][e] = w
            medido[p][e] = {"edge_1d_entre_6": [None if c["edge"] is None else round(c["edge"] / 6, 1) for c in cs1]}
        for p, h in PLAZOS.items():
            cs, w, mot = RES[(h, e)]
            pesos[p][e] = w
            medido[p][e] = {"lado": LADO[e], "motivo": mot, "tramos": [
                {"tramo": G["tn"][t], "dias": c["s"]["n"] if c["s"] else 0, "sube_estado": None if not c["s"] else round(100 * c["s"]["up"], 1),
                 "sube_normal": None if not c["b"] else round(100 * c["b"]["up"], 1), "dif_pts": None if c["edge"] is None else round(c["edge"], 1),
                 "z": None if c["z"] is None else round(c["z"], 1)} for t, c in enumerate(cs)]}
    return pesos, medido


def armar_registro(RED):
    reg_ = {p: {} for p in CORTOS + tuple(PLAZOS) + (REF,)}
    for s in SIG:
        for p in reg_:
            h = PLAZOS.get(p, 90 if p == REF else None)
            w, mot = peso_registro(s, p, h)
            e = {"grupo": s["grupo"], "lado": s["lado"], "peso": w, "motivo": mot, "en_estado": s["comp"]}
            if h and not s["corta"]:
                cs = s["res"][h][0]
                e["tramos"] = [{"tramo": s["tn"][t], "dias_prendida": s["dias_on"][t],
                                "sube_con": None if not c["s"] else round(100 * c["s"]["up"], 1),
                                "sube_normal": None if not c["b"] else round(100 * c["b"]["up"], 1),
                                "dif_pts": None if c["edge"] is None else round(c["edge"], 1),
                                "z": None if c["z"] is None else round(c["z"], 1)} for t, c in enumerate(cs)]
                if s["inc"]:
                    e["peso_sobre_estado"] = s["inc"][h][1]
                    e["motivo_sobre_estado"] = s["inc"][h][2]
            reg_[p][s["nom"]] = e
    return reg_


def recomendar(pesos, registro, RED):
    """Por plazo: el estado + solo extras (no zonas) con peso, no redundantes entre si ni con un estado del mismo lado que ya pese."""
    rec = {}
    for p in tuple(PLAZOS) + ("4 horas",):
        cands = []
        for s in SIG:
            r = registro[p][s["nom"]]
            if s["comp"] or r["peso"] <= 0:
                continue
            w = min(r["peso"], r.get("peso_sobre_estado", r["peso"]))
            if w > 0:
                cands.append((w, min(abs(t["dif_pts"]) for t in r["tramos"]) if r.get("tramos") else 0, s))
        cands.sort(key=lambda c: (-c[0], -c[1]))
        ok, series, motivos = [], set(), {}
        for w, _, s in cands:
            nom = s["nom"]
            if any(LADO[e] == s["lado"] and pesos[p].get(e, 0) > 0 for e in RED[nom]["contenida"]):
                motivos[nom] = "contenida en un estado del mismo lado que ya pesa"
            elif (s["serie"], s["lado"]) in series:
                motivos[nom] = "misma serie y lado que otra elegida"
            elif {o["nom"] for o in ok} & {x.split(" (")[0] for x in RED[nom]["con"]}:
                motivos[nom] = "redundante con otra elegida"
            else:
                ok.append(s)
                series.add((s["serie"], s["lado"]))
                motivos[nom] = "elegida"
        rec[p] = dict(extras=[{"senal": s["nom"], "lado": s["lado"], "peso": min(registro[p][s["nom"]]["peso"], registro[p][s["nom"]].get("peso_sobre_estado", 9))}
                              for s in ok], descartadas={k: v for k, v in motivos.items() if v != "elegida"}, tope_sugerido_por_plazo=2.0)
    return rec


def hoy(RES, pesos, registro, rec):
    dias, n = G["dias"], len(G["dias"])
    i = n - 1
    e = G["lab"][i]
    print("\n" + "=" * 110)
    print(f"=== HOY ({dias[i]}) ===")
    Zi = me.G["Z"][i]
    rs, rm = G["rsth"][i] if G["rsth"] else None, G["rm200"][i]
    print(f"  Z {'—' if Zi is None else f'{Zi:+d}'} ({me.G['NZ'][i]} zonas) · precio/costo STH {num(rs)} · precio/media 200 d {num(rm)} · "
          f"retorno 90 d {signed(me.G['ret90'][i], 1)} · precio/CVDD {num(me.G['cvdd'][i]) if me.G['cvdd'] else '—'} · "
          f"MVRV {num(me.G['mv'][i]) if me.G['mv'] else '—'}")
    print(f"  >>> ESTADO DE HOY: {e.upper() if e else 'sin puntaje'} (lado esperado: "
          f"{'sube' if e and LADO[e] > 0 else 'baja' if e and LADO[e] < 0 else 'ninguno'})")
    act = [s for s in SIG if s["on"][i]]
    print("  señales prendidas hoy: " + ("; ".join(s["nom"] for s in act if not s["comp"]) or "ninguna (fuera de las zonas)")
          + " · zonas prendidas: " + (str(sum(1 for s in act if s["comp"])) if act else "0"))
    print("  qué implica por plazo (puntos para la dirección de analisis_btc.central(): +compra / -venta; la dirección se decide con ±2,5):")
    for p in CORTOS + tuple(PLAZOS):
        pe = pesos[p].get(e, 0.0) * LADO.get(e, 0) if e else 0.0
        ex = {x["senal"]: x["peso"] * x["lado"] for x in rec.get(p, {}).get("extras", []) if SIG_POR[x["senal"]]["on"][i]}
        tot = pe + sum(ex.values())
        det = f"estado {pts(pe)}" + "".join(f" · {k} {pts(v)}" for k, v in ex.items())
        print(f"    {p:<9} {pts(tot):>5} puntos (tope sugerido ±2: {pts(max(-2.0, min(2.0, tot)))}) ({det})")
    sin = [s["nom"] for s in SIG if s["on"][i] is None and not s["comp"]]
    if sin:
        print("  sin dato hoy: " + ", ".join(sin))


def imprimir_pesos(pesos, medido, registro, red, rec):
    print("\n" + "=" * 110)
    print("=== PESOS PARA EL ANÁLISIS ===")
    print("(a) PESOS POR ESTADO (puntos de dirección por plazo; el lado sale de LADO: +1 compra, -1 venta)")
    print(f"  {'':<24}" + "".join(f"{p:>10}" for p in pesos))
    for e in ESTADOS:
        print(f"  {e:<24}" + "".join(f"{num(pesos[p][e], 1):>10}" for p in pesos))
    print("\n(b) REGISTRO de cada señal individual x plazo (resumen: peso solo / peso sobre el estado)")
    cols = tuple(PLAZOS) + (REF,)
    print(f"  {'señal':<62}" + "".join(f"{p:>16}" for p in cols))
    for s in SIG:
        celdas = []
        for p in cols:
            r = registro[p][s["nom"]]
            celdas.append(f"{num(r['peso'], 1)}" + (f"/{num(r['peso_sobre_estado'], 1)}" if "peso_sobre_estado" in r else "") + ("  (en estado)" if s["comp"] and p == cols[0] else ""))
        print(f"  {s['nom'][:62]:<62}" + "".join(f"{c:>16}" for c in celdas))
    n_prueba = sum(1 for s in SIG if not s["corta"]) * 3
    con_peso = [(s["nom"], p) for s in SIG for p in PLAZOS if registro[p][s["nom"]]["peso"] > 0]
    print(f"\n  {n_prueba} pruebas (señal x plazo de 1, 7 y 30 d) con los dos tramos; con la regla (mismo lado, z >= 1 y >= 2 pts en los dos) al azar pasarían ~{n_prueba * 0.015:.1f} "
          f"(estimación gruesa: las señales de una misma serie están correlacionadas); pasaron {len(con_peso)}.")
    print("\n(c) RECOMENDACIÓN COMBINADA por plazo: peso del estado + solo extras no zonas, con peso, no redundantes (peso = el menor entre el solo y el sobre el estado)")
    for p, r in rec.items():
        print(f"  {p:<9} extras: " + (", ".join(f"{x['senal']} ({'+' if x['lado'] > 0 else '-'}{num(x['peso'], 1)})" for x in r["extras"]) or "ninguno")
              + (f" · descartadas: {len(r['descartadas'])}" if r["descartadas"] else ""))
    sal = {"PESOS": pesos, "LADO": LADO, "MEDIDO": medido, "REGISTRO": registro, "REDUNDANCIAS": red, "RECOMENDADO": rec}
    print("\n# --- Python (dict literal) ---")
    for k, v in sal.items():
        print(f"{k} = " + pprint.pformat(v, width=140, sort_dicts=False))
    print("\n// --- JS (objeto literal) ---")
    for k, v in sal.items():
        print(f"const {k} = " + json.dumps(v, ensure_ascii=False, separators=(",", ":")) + ";")


def main():
    print(f"Tramo 1: {DESDE} a {CORTE} (sin incluirlo) · tramo 2: desde {CORTE} · reglas finales fijas: "
          + " ".join(f"{k}={v}" for k, v in Q_FINAL.items() if v is not None), flush=True)
    if not preparar():
        return
    print("\nEtiquetas con las reglas finales:", flush=True)
    etiquetas()
    print("\nSeñales individuales:", flush=True)
    armar_senales()
    RES = tabla_estados()
    tabla_z()
    tabla_momentum()
    for s in SIG:
        evaluar_senal(s)
        SIG_POR[s["nom"]] = s
    tabla_senales()
    RED, pares_c = redundancias()
    imprimir_redundancias(RED, pares_c)
    print("\n  Nota: no se mide acá cuánto coincide el estado con la llamada actual de corto plazo de la app (eso solo se ve en vivo).")
    print("  Se hacen muchas pruebas con 2 tramos: un peso de 0,5 con z 1 puede ser azar; por eso el piso de 2 puntos y z >= 1 en los dos.")
    pesos, medido = armar_pesos_estado(RES)
    registro = armar_registro(RED)
    rec = recomendar(pesos, registro, RED)
    imprimir_pesos(pesos, medido, registro, RED, rec)
    hoy(RES, pesos, registro, rec)


SIG_POR = {}

if __name__ == "__main__":
    main()
