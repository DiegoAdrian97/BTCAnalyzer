"""¿Qué indicadores on-chain marcan pisos y techos del mercado, y suman al termómetro? (medir antes de sumar). Nov. 2026.

Reusa de medir_diarios.py (sin tocarlo): etiquetas de estado (piso, piso extremo, techo, rally en curso, indecisión),
P(estado | señal) contra la tasa base con z en bloques de 90 días, AUC (Mann-Whitney) por tramo, la prueba logística de
"valor agregado sobre el termómetro" (ajusta en un tramo, prueba en el otro, las dos direcciones) y el puntaje del termómetro.

Datos (todos públicos, sin clave):
  - looknode.com/api/<id>: sopr, ASOPR, balancedPrice, CVDD, realizePrice, mCapRealizedRatio (MVRV), rhodl, realCapHODL (bandas
    de edad, v1..vN, la más joven primero), NUPL, sthCostPrice (v1..v4), sthTwoPrice, sthCostPriceV2, realizedLos, realizedProfitUsd.
  - bitcoin-data.com (BGeometrics, 10 pedidos/hora: se hacen 3 como mucho + 1 reintento): supply-profit (historia completa;
    % de la oferta en ganancia = supplyProfitBtc / SplyCur), sth-mvrv y nupl-sth (solo desde 2022-11: descriptivo, no pueden
    pasar la regla de los dos tramos).
  - CoinMetrics comunidad: PriceUSD, SplyCur.
Sin mirar el futuro: umbrales y percentiles solo con los 4 años previos (1460 días, mínimo 365); un dato se usa desde el día
siguiente a su fecha (no se sabe si el punto del día es cierre del mismo día o del anterior: se asume lo peor).
Tramo 1 = hasta el corte (por defecto 2021-12-31), tramo 2 = desde el corte (2022-01-01). Los techos son raros (2013, 2017, 2021,
quizá 2024-25): se cuentan los episodios independientes por estado y tramo y se avisa si hay menos de 3.
SE REPITE: z >= 2 del mismo lado en los dos tramos. SUMA AL TERMÓMETRO: mejora de AUC >= +0,01 en las dos direcciones.
Uso: python medir_onchain_ciclo.py [corte [desde]]   (p. ej. 2024-01-01 2022-01-01: solo 2022-2026, partido en 2022-23 y 2024-26)
     python medir_onchain_ciclo.py --prueba           (sin internet: series sintéticas para probar el código de punta a punta)
"""
import json
import math
import random
import re
import statistics
import sys
import time
import urllib.request
import zlib
from datetime import date, datetime, timezone

import medir_diarios as md          # comparte argv: mismos [corte desde] y --prueba

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
PRUEBA = "--prueba" in sys.argv
CORTE = ARGS[0] if ARGS else "2022-01-01"
DESDE = ARGS[1] if len(ARGS) > 1 else "2012-01-01"
W4A, MIN4A = 1460, 365                                   # percentil contra los 4 años previos
CACHE = "cache_onchain.json"
UA_NAV = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
G = {}
SENS, VARS = [], []                                      # señales (nombre, on) y variables continuas (nombre, var, pct)
PEDIDOS_BGEO = {"n": 0}


# ---------------------------------------------------------------- bajada de datos
def parse_look(j):
    """JSON de looknode -> {fecha UTC: [v1..vN]}. 't' puede venir en ms o en segundos*1000 (floats): se normaliza a fecha UTC."""
    if j.get("code") != 100:
        raise ValueError(f"code {j.get('code')}")
    out = {}
    for r in j.get("data") or []:
        t = r.get("t")
        if t is None:
            continue
        t = float(t)
        d = datetime.fromtimestamp(t / 1000 if t > 1e11 else t, timezone.utc).date().isoformat()
        if r.get("v") is not None:
            vals = [r["v"]]
        else:
            ks = sorted((k for k in r if re.fullmatch(r"v\d+", k)), key=lambda k: int(k[1:]))
            vals = [r[k] for k in ks]
        try:
            vals = [None if v is None else float(v) for v in vals]
        except (TypeError, ValueError):
            continue
        if vals and any(v is not None for v in vals):
            out[d] = vals
    if not out:
        raise ValueError("sin filas")
    return out


def f_look(id_):
    cab = {"User-Agent": UA_NAV, "Referer": "https://www.looknode.com/zh/chart/", "Accept": "application/json"}
    for intento in (0, 1):
        try:
            txt = urllib.request.urlopen(urllib.request.Request(f"https://www.looknode.com/api/{id_}", headers=cab),
                                         timeout=90).read().decode("utf-8", "replace")
            d = parse_look(json.loads(txt))
            time.sleep(1)                                # amables: 1 s entre pedidos
            return d
        except Exception:
            if intento:
                time.sleep(1)
                raise
            time.sleep(3)


def f_bgeo(slug, reintentar=False):
    """CSV de bitcoin-data.com (d,unixTs,valor) -> {fecha: valor}. Máximo ~4 pedidos en toda la corrida (10/hora)."""
    for intento in (0, 1 if reintentar else 0):
        PEDIDOS_BGEO["n"] += 1
        try:
            txt = md.http(f"https://bitcoin-data.com/v1/{slug}/csv", ua=UA_NAV)
            d = md.csv_fechas(txt, 2)
            if len(d) < 30:
                raise ValueError(f"solo {len(d)} filas (¿límite de pedidos? {txt[:80]!r})")
            time.sleep(2)
            return d
        except Exception:
            if intento == (1 if reintentar else 0):
                raise
            time.sleep(10)


def cargar_cache():
    try:
        with open(CACHE) as f:
            c = json.load(f)
        if c.get("dia") == date.today().isoformat():
            return c
    except Exception:
        pass
    return {"dia": date.today().isoformat(), "look": {}, "bgeo": {}}


def guardar_cache(c):
    try:
        with open(CACHE, "w") as f:
            json.dump(c, f)
    except Exception:
        pass


def bajar_look(c, id_):
    if id_ in c["look"]:
        d = c["look"][id_]
        print(f"  looknode {id_}: de la cache ({len(d)} filas)", flush=True)
        return d
    d = md.intentar(f"looknode {id_}", F_LOOK, id_)
    if d:
        c["look"][id_] = d
        guardar_cache(c)
        k = sorted(d)
        print(f"      última fila {k[-1]}: {[None if v is None else float(f'{v:.5g}') for v in d[k[-1]]]}", flush=True)
    return d


def bajar_bgeo(c, slug, reintentar=False):
    if slug in c["bgeo"]:
        print(f"  bitcoin-data {slug}: de la cache", flush=True)
        return c["bgeo"][slug]
    d = md.intentar(f"bitcoin-data {slug}", F_BGEO, slug, reintentar)
    if d:
        c["bgeo"][slug] = d
        guardar_cache(c)
    return d


def columna(d, k):
    return {f: v[k] for f, v in d.items() if len(v) > k and v[k] is not None}


# ---------------------------------------------------------------- armado de variables
def A(d, lag=1, vence=5):
    return md.alinear(d, G["o"], lag, vence)


def logrel(P, linea):
    return [None if p is None or l is None or l <= 0 or p <= 0 else math.log(p / l) for p, l in zip(P, linea)]


def media_rodada(x, w):
    return md.rodar(x, w, statistics.fmean)


def pico_vs_año(x, w=7, base=365):
    """Suma de w días / (promedio diario de los `base` días previos a esa ventana * w). Solo pasado. Pico > 1 = más de lo normal."""
    pre, cnt = [0.0], [0]
    for v in x:
        pre.append(pre[-1] + (abs(v) if v is not None else 0.0))
        cnt.append(cnt[-1] + (v is not None))
    out = [None] * len(x)
    for i in range(w + base - 1, len(x)):
        if cnt[i + 1] - cnt[i + 1 - w] < w:
            continue
        nb = cnt[i + 1 - w] - cnt[i + 1 - w - base]
        if nb < 0.8 * base:
            continue
        b = (pre[i + 1 - w] - pre[i + 1 - w - base]) / nb * w
        if b > 0:
            out[i] = (pre[i + 1] - pre[i + 1 - w]) / b
    return out


def agregar(nom, var, fijas=(), nota=""):
    """Registra la variable continua y sus señales: p90/p10 de los 4 años previos + umbrales fijos [(texto, f(x) -> bool)]."""
    if not any(x is not None for x in var):
        print(f"  {nom}: sin datos, se saltea", flush=True)
        return
    p = md.pct_trailing(var, W4A, MIN4A)
    VARS.append((nom, var, p))
    for txt, fn in fijas:
        SENS.append((f"{nom} {txt}", [None if x is None else fn(x) for x in var]))
    SENS.append((f"{nom} p90 4a (alto)", [None if x is None else x >= 0.9 for x in p]))
    SENS.append((f"{nom} p10 4a (bajo)", [None if x is None else x <= 0.1 for x in p]))
    ix = [i for i, x in enumerate(var) if x is not None]
    nt = [sum(1 for i in range(len(var)) if G["tr"][i] == t and var[i] is not None) for t in (0, 1)]
    print(f"  + {nom}: datos {G['dias'][ix[0]]} a {G['dias'][ix[-1]]} · días en tramo 1/2: {nt[0]}/{nt[1]}"
          f"{' · ' + nota if nota else ''}", flush=True)


def armar_variables(c):
    P = G["P"]
    print("\nBajando series de looknode:", flush=True)
    L = {i: bajar_look(c, i) for i in ("mCapRealizedRatio", "realizePrice", "CVDD", "balancedPrice", "NUPL", "sopr", "ASOPR", "rhodl",
                                      "realCapHODL", "sthCostPrice", "sthTwoPrice", "sthCostPriceV2", "realizedLos", "realizedProfitUsd")}

    def bloque(nombre, fn):
        try:
            fn()
        except Exception as e:
            print(f"  bloque {nombre} no: {type(e).__name__}: {e}", flush=True)

    # --- MVRV (referencia: ya está dentro del termómetro)
    def b_mvrv():
        mv = L["mCapRealizedRatio"]
        if mv:
            m = A(columna(mv, 0))
            origen = "looknode"
        else:
            m = A(md.intentar("BTC CapMVRVCur", md.f_cm, "btc", "CapMVRVCur", "2011-01-01"))
            origen = "CoinMetrics"
        G["mvrv"] = m
        lm = [None if x is None or x <= 0 else math.log(x) for x in m]
        G["lmvrv"] = lm
        agregar("log MVRV (ref. termómetro)", lm, [("MVRV<1 [clásico]", lambda x: x < 0), ("MVRV>3,5 [clásico]", lambda x: x > math.log(3.5))],
                f"fuente {origen}")
        if L["realizePrice"]:
            rp = A(columna(L["realizePrice"], 0))
            chk = [(a, b) for a, b in zip(logrel(P, rp), lm) if a is not None and b is not None]
            if chk:
                r, _ = md.pearson([a for a, _ in chk], [b for _, b in chk])
                print(f"    control: log(precio/precio realizado) vs log MVRV: r {r:+.3f} (debería ser ~1)", flush=True)
    bloque("MVRV", b_mvrv)

    # --- modelos de piso clásicos
    def b_pisos():
        if L["CVDD"]:
            agregar("log P/CVDD", logrel(P, A(columna(L["CVDD"], 0))), [("P<=1,1xCVDD [clásico]", lambda x: x <= math.log(1.1))])
        if L["balancedPrice"]:
            agregar("log P/precio balanceado", logrel(P, A(columna(L["balancedPrice"], 0))), [("P<=balanceado [clásico]", lambda x: x <= 0)])
    bloque("CVDD y balanceado", b_pisos)

    # --- costo de los tenedores de corto plazo: cada vK es una línea candidata (significado exacto desconocido)
    def b_sth():
        for id_, tag in (("sthCostPrice", "sthC"), ("sthCostPriceV2", "sthC2"), ("sthTwoPrice", "sthTwo")):
            d = L[id_]
            if not d:
                continue
            ult = d[max(d)]
            print(f"    {id_}: {len(ult)} líneas; precio actual / cada línea: "
                  + " · ".join(f"v{k + 1}={'—' if v is None or v <= 0 or not P[-1] else f'{P[-1] / v:.2f}'}" for k, v in enumerate(ult)), flush=True)
            for k in range(len(ult)):
                col = columna(d, k)
                if col:
                    agregar(f"log P/{tag}.v{k + 1}", logrel(P, A(col)), [("P<línea [regla fija]", lambda x: x < 0)])
    bloque("costo de corto plazo", b_sth)

    # --- NUPL (≈ 1 - 1/MVRV: se chequea la redundancia más abajo)
    def b_nupl():
        if not L["NUPL"]:
            return
        col = columna(L["NUPL"], 0)
        if col and max(abs(v) for v in col.values()) > 1.5:
            print("    NUPL parece venir en %: se divide por 100", flush=True)
            col = {k: v / 100 for k, v in col.items()}
        agregar("NUPL", A(col), [("NUPL<0 [clásico]", lambda x: x < 0), ("NUPL>0,75 [clásico]", lambda x: x > 0.75)])
    bloque("NUPL", b_nupl)

    # --- SOPR y aSOPR
    def b_sopr():
        for id_, tag in (("sopr", "SOPR"), ("ASOPR", "aSOPR")):
            if not L[id_]:
                continue
            x = A(columna(L[id_], 0))
            for w in (7, 30):
                agregar(f"{tag} media {w}d", media_rodada(x, w), [("<1 [clásico]", lambda v: v < 1)])
    bloque("SOPR", b_sopr)

    # --- RHODL y ondas HODL
    def b_rhodl():
        if L["rhodl"]:
            r = A(columna(L["rhodl"], 0))
            agregar("log RHODL", [None if v is None or v <= 0 else math.log(v) for v in r], nota="sin umbral fijo: la escala cambia por era")
        d = L["realCapHODL"]
        if d:
            ult = d[max(d)]
            print(f"    HODL waves: {len(ult)} bandas; última fila (joven -> vieja): {[round(v, 4) if v is not None else None for v in ult]} "
                  f"(suma {sum(v for v in ult if v is not None):.3f})", flush=True)
            if len(ult) >= 4:
                bandas = [A(columna(d, k)) for k in range(len(ult))]
                joven = [None if any(b[i] is None for b in bandas[:3]) else sum(b[i] for b in bandas[:3]) for i in range(len(P))]
                vieja = [None if any(b[i] is None for b in bandas[-2:]) else sum(b[i] for b in bandas[-2:]) for i in range(len(P))]
                agregar("HODL jóvenes (v1+v2+v3)", joven, nota="alto = plata nueva/techo, bajo = piso")
                agregar(f"HODL viejas (v{len(ult) - 1}+v{len(ult)})", vieja)
    bloque("RHODL y HODL waves", b_rhodl)

    # --- realized loss / profit: picos de 7 días contra el último año
    def b_realizado():
        for id_, tag in (("realizedLos", "pérdida realizada"), ("realizedProfitUsd", "ganancia realizada")):
            if L[id_]:
                r = pico_vs_año(A(columna(L[id_], 0)))
                agregar(f"log {tag} 7d/1a", [None if v is None else math.log(max(v, 1e-6)) for v in r], nota="1 = normal; pico = capitulación/distribución")
    bloque("realized", b_realizado)

    # --- % de la oferta en ganancia (bitcoin-data)
    def b_ganancia():
        sp = bajar_bgeo(c, "supply-profit", reintentar=True)
        sup = md.intentar("BTC SplyCur", md.f_cm, "btc", "SplyCur", "2011-01-01")
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
        med = statistics.median(frac.values())
        print(f"    % oferta en ganancia: mediana {100 * med:.0f}%, última {100 * frac[max(frac)]:.0f}% ({max(frac)})", flush=True)
        if not 0.2 < med < 1.0:
            raise ValueError("el cociente no parece una fracción (revisar unidades)")
        agregar("% oferta en ganancia", A(frac), [("<50% [clásico]", lambda x: x < 0.5), (">95% [clásico]", lambda x: x > 0.95)])
    bloque("oferta en ganancia", b_ganancia)

    # --- solo desde 2022-11 (descriptivo)
    G["cortas"] = []
    for slug, nom in (("sth-mvrv", "MVRV de STH"), ("nupl-sth", "NUPL de STH")):
        try:
            d = bajar_bgeo(c, slug)
            if d:
                G["cortas"].append((nom, A(d)))
        except Exception as e:
            print(f"  {nom} no: {e}", flush=True)


# ---------------------------------------------------------------- informes propios
def episodios(lab, t, hueco=90):
    """Cantidad de episodios independientes: días con la etiqueta prendida, separados por más de `hueco` días = otro episodio."""
    n, ult = 0, None
    for i in range(len(lab)):
        if G["tr"][i] == t and lab[i]:
            if ult is None or i - ult > hueco:
                n += 1
            ult = i
    return n


def informe_episodios(labs):
    print("\nEpisodios independientes por estado (días prendidos separados por más de 90 d = otro episodio; < 3 = poco confiable):")
    for e in md.ESTADOS:
        ns = [episodios(labs[e], t) for t in (0, 1)]
        av = "  ⚠ MENOS DE 3 EN ALGÚN TRAMO" if min(ns) < 3 else ""
        print(f"  {e:<15} tramo 1: {ns[0]:>2} · tramo 2: {ns[1]:>2}{av}")


def redundancia():
    lm = G.get("lmvrv")
    if not lm:
        return
    print("\n--- REDUNDANCIA con log MVRV (Spearman, un día de cada 7; |r| >= 0,9 = casi la misma información que el termómetro ya usa) ---")
    for nom, var, _ in VARS:
        if nom.startswith("log MVRV"):
            continue
        txt, rs = f"  {nom:<34}", []
        for t in (0, 1):
            ix = [i for i in range(0, len(var), 7) if G["tr"][i] == t and var[i] is not None and lm[i] is not None]
            r, _ = md.spearman([var[i] for i in ix], [lm[i] for i in ix]) if len(ix) >= 30 else (None, None)
            rs.append(r)
            txt += f" | tramo {t + 1}: " + (f"r {r:+.2f}" if r is not None else "sin datos").ljust(9)
        print(txt + ("  REDUNDANTE" if all(r is not None and abs(r) >= 0.9 for r in rs) else ""))


def informe_cortas(labs):
    if not G.get("cortas"):
        return
    print("\n" + "=" * 100)
    print("=== SOLO 2022-26 (series que arrancan en 2022-11): UN solo tramo, no pueden pasar la regla de los dos tramos; solo descriptivo ===")
    for nom, x in G["cortas"]:
        ix = [i for i, v in enumerate(x) if v is not None]
        if not ix:
            print(f"  {nom}: sin datos")
            continue
        print(f"  {nom}: {G['dias'][ix[0]]} a {G['dias'][ix[-1]]} · hoy {x[ix[-1]]:.3f}")
        for e in ("piso", "piso extremo", "techo"):
            sel = [i for i in ix if G["tr"][i] is not None and labs[e][i] is not None]
            a, n1, n0 = md.auc([x[i] for i in sel], [labs[e][i] for i in sel]) if len(sel) >= 100 else (None, 0, 0)
            if a is None:
                print(f"    {e:<13} sin casos suficientes ({len(sel)} d, {n1} con el estado)")
                continue
            se = math.sqrt((n1 / 90 + n0 / 90 + 1) / (12 * max(n1 / 90, 1) * max(n0 / 90, 1)))
            print(f"    {e:<13} AUC {a:.3f} (z {(a - 0.5) / se:+.1f}) con {n1} d del estado de {len(sel)} · ¡una sola mini-época, no concluye!")


def resumen():
    E = md.ESTADO
    ciclo = ("piso", "piso extremo", "techo")
    pe, pa, pi = E["pruebas_e"], E["pruebas_a"], E["pruebas_i"]
    print("\n" + "=" * 100)
    print(f"=== RESUMEN: {pe} pruebas de señal prendida con los dos tramos (al azar pasarían ~{pe * 0.0011:.1f}) · {pa} de AUC (~{pa * 0.0011:.1f}) ===")
    print("--- QUÉ SE REPITE en los dos tramos ---")
    for e, nom, zs in E["rep_e"]:
        print(f"  señal  {e:<15} {nom:<46} z {zs[0]:+.1f} / {zs[1]:+.1f}")
    for e, nom, zs in E["rep_a"]:
        print(f"  AUC    {e:<15} {nom:<46} z {zs[0]:+.1f} / {zs[1]:+.1f}")
    if not (E["rep_e"] or E["rep_a"]):
        print("  nada se repite en los dos tramos")
    print(f"--- QUÉ SUMA AL TERMÓMETRO ({pi} pruebas; umbral +0,01 de AUC en las dos direcciones) ---")
    for e, nom, ds in E["rep_i"]:
        print(f"  SUMA   {e:<15} {nom:<46} {ds[0]:+.3f} / {ds[1]:+.3f}")
    if not E["rep_i"]:
        print("  ninguna variable suma en las dos direcciones")
    ra = {(e, nom) for e, nom, _ in E["rep_a"] if e in ciclo}
    fin = [(e, nom) for e, nom, _ in E["rep_i"] if (e, nom) in ra]
    print("--- FINALISTAS: se repite el AUC en los dos tramos Y suma al termómetro (piso / piso extremo / techo) ---")
    for e, nom in fin:
        print(f"  {e:<15} {nom}")
    if not fin:
        print("  ninguna cumple las dos cosas")
    print("  (avisos: pocos episodios por tramo -> ver la tabla de episodios; los techos tienen 3-4 episodios en toda la historia;"
          " las variables de un mismo bloque están muy correlacionadas, así que las pruebas no son independientes)")


def informe_hoy(tabla, score, desc):
    L = len(G["o"]) - 1
    print("\n" + "=" * 100)
    print(f"=== HOY ({G['dias'][L]}; cada dato usable desde el día siguiente a su fecha) ===")
    if score and score[L] is not None:
        print(f"  puntaje del termómetro ({desc}): {score[L]:.0f}")
    for nom, var, pct in VARS:
        v, q = var[L], pct[L]
        print(f"  {nom:<34} valor {'sin dato' if v is None else f'{v:,.4g}':>10} · percentil 4a {'—' if q is None else f'{100 * q:.0f}%'}")
    for nom, x in G.get("cortas", []):
        ix = [i for i, v in enumerate(x) if v is not None]
        if ix:
            q = md.pct_trailing(x, W4A, 180)[ix[-1]]
            print(f"  {nom:<34} valor {x[ix[-1]]:>10,.4g} · percentil {'—' if q is None else f'{100 * q:.0f}%'} (solo desde 2022-11; {G['dias'][ix[-1]]})")
    on = [nom for nom, s in SENS if s[L]]
    print("  zonas prendidas hoy: " + ("; ".join(on) if on else "ninguna"))
    print("  qué implica cada una: P(estado | prendida) tramo 1 / tramo 2 y, entre paréntesis, la tasa base; * = SE REPITE:")
    for nom in on:
        partes = []
        for e in md.ESTADOS:
            cs = tabla.get((nom, e))
            if cs and all(c and c[2] is not None for c in cs):
                rep = "*" if md.veredicto([c[2] for c in cs]) else ""
                partes.append(f"{e} {100 * cs[0][0]:.0f}/{100 * cs[1][0]:.0f}% ({100 * cs[0][1]:.0f}/{100 * cs[1][1]:.0f}){rep}")
        print(f"    {nom}: " + (" · ".join(partes) if partes else "sin datos suficientes (pocos bloques en algún tramo)"))


# ---------------------------------------------------------------- modo prueba (sin internet)
def _sintetico():
    md._sintetico()                                      # CoinMetrics, etc. de prueba (ya parcheados dentro de md)
    px = md.f_cm("btc", "PriceUSD", "2011-01-01")
    ks = sorted(px)
    lp = [math.log(px[k]) for k in ks]

    def ema(span, ini=None):
        a, x, out = 2 / (span + 1), lp[0] if ini is None else ini, []
        for v in lp:
            x += a * (v - x)
            out.append(x)
        return out

    def ruido(clave, s):
        r = random.Random(zlib.crc32(clave.encode()))
        return [r.gauss(0, s) for _ in ks]

    e30, e90, e155, e180, e365, e600, e1000 = ema(30), ema(90), ema(155), ema(180), ema(365), ema(600), ema(1000)
    ret = [0.0] + [lp[i] - lp[i - 1] for i in range(1, len(lp))]

    def f_look(id_):
        n = ruido(id_, 0.02)
        rp = [math.exp(e600[i] + n[i] * 0.2) for i in range(len(ks))]
        if id_ == "realizePrice":
            v = [[x] for x in rp]
        elif id_ == "mCapRealizedRatio":
            v = [[math.exp(lp[i]) / rp[i]] for i in range(len(ks))]
        elif id_ == "NUPL":
            v = [[1 - rp[i] / math.exp(lp[i])] for i in range(len(ks))]
        elif id_ == "CVDD":
            v = [[0.35 * math.exp(e1000[i])] for i in range(len(ks))]
        elif id_ == "balancedPrice":
            v = [[0.6 * math.exp(e600[i])] for i in range(len(ks))]
        elif id_ in ("sopr", "ASOPR"):
            v = [[1 + 0.4 * (lp[i] - e30[i]) + n[i] * (1 if id_ == "sopr" else 0.3)] for i in range(len(ks))]
        elif id_ == "rhodl":
            v = [[1000 * math.exp(e30[i] - e1000[i] + n[i])] for i in range(len(ks))]
        elif id_ == "realCapHODL":
            v = []
            for i in range(len(ks)):
                m = lp[i] - e180[i]
                w = [math.exp(a * m) for a in (1.5, 1.0, 0.5, 0.0, -0.5, -1.0)]
                s = sum(w)
                v.append([x / s for x in w])
        elif id_ == "sthCostPrice":
            v = [[math.exp(e[i]) * f for e, f in ((e90, 1.0), (e155, 1.0), (e180, 0.9), (e365, 1.1))] for i in range(len(ks))]
        elif id_ == "sthTwoPrice":
            v = [[math.exp(e90[i]), math.exp(e365[i])] for i in range(len(ks))]
        elif id_ == "sthCostPriceV2":
            v = [[math.exp(e155[i]) * 1.02, math.exp(e180[i]) * 0.97] for i in range(len(ks))]
        elif id_ == "realizedLos":
            v = [[1e9 * max(-ret[i], 0) * (1 + abs(n[i]) * 20)] for i in range(len(ks))]
        elif id_ == "realizedProfitUsd":
            v = [[1e9 * max(ret[i], 0) * (1 + abs(n[i]) * 20)] for i in range(len(ks))]
        else:
            raise ValueError("id de prueba desconocido")
        return {k: x for k, x in zip(ks, v)}

    sup = md.f_cm("btc", "SplyCur", "2011-01-01")

    def f_bgeo(slug, reintentar=False):
        if slug == "supply-profit":
            return {k: min(max(0.5 + 0.4 * math.tanh(3 * (lp[i] - e365[i])), 0.02), 1.0) * sup[k] for i, k in enumerate(ks)}
        i0 = next(i for i, k in enumerate(ks) if k >= "2022-11-01")
        mv = {k: math.exp(lp[i] - e155[i]) for i, k in enumerate(ks) if i >= i0}
        return mv if slug == "sth-mvrv" else {k: 1 - 1 / v for k, v in mv.items()}

    return f_look, f_bgeo


def _autotest():
    j = {"code": 100, "data": [{"t": 1262304000000, "v": 1.5}, {"t": 1262390400000.0, "v1": 0.1, "v2": 0.9},
                               {"t": 1262476800.0 * 1000, "v": None, "v1": 2, "v2": None}]}
    assert parse_look(j) == {"2010-01-01": [1.5], "2010-01-02": [0.1, 0.9], "2010-01-03": [2.0, None]}, parse_look(j)
    assert columna(parse_look(j), 1) == {"2010-01-02": 0.9}
    txt = "d,unixTs,supplyProfitBtc\n2020-01-01,1577836800,12000000\n2020-01-02,1577923200,12100000\n"
    assert md.csv_fechas(txt, 2) == {"2020-01-01": 12000000.0, "2020-01-02": 12100000.0}
    assert pico_vs_año([1.0] * 400 + [5.0] * 7)[-1] == 5.0
    print("  autotest de lectores de formato: ok", flush=True)


# ---------------------------------------------------------------- principal
def main():
    global F_LOOK, F_BGEO
    F_LOOK, F_BGEO = f_look, f_bgeo
    if PRUEBA:
        print("MODO PRUEBA: series sintéticas, sin internet")
        F_LOOK, F_BGEO = _sintetico()
        _autotest()
        c = {"dia": "prueba", "look": {}, "bgeo": {}}
        globals()["guardar_cache"] = lambda *_: None      # la prueba no escribe cache
    else:
        c = cargar_cache()
    print(f"Tramo 1: {DESDE} a {CORTE} (sin incluirlo) · tramo 2: desde {CORTE}", flush=True)
    print("Fuentes:", flush=True)
    px = md.intentar("BTC PriceUSD", md.f_cm, "btc", "PriceUSD", "2011-01-01")
    if not px:
        print("sin precio de BTC no se puede medir nada")
        return
    o0, o1 = date.fromisoformat(min(px)).toordinal(), date.fromisoformat(max(px)).toordinal()
    o = list(range(o0, o1 + 1))
    dias = [date.fromordinal(x).isoformat() for x in o]
    P = [px.get(d) for d in dias]
    G.update(o=o, dias=dias, P=P, tr=[None if d < DESDE else (0 if d < CORTE else 1) for d in dias])
    for t in (0, 1):
        ix = [i for i, x in enumerate(G["tr"]) if x == t]
        if ix:
            print(f"  tramo {t + 1}: {dias[ix[0]]} a {dias[ix[-1]]} ({len(ix)} días)", flush=True)
    armar_variables(c)
    print(f"\nVariables continuas: {len(VARS)} · señales: {len(SENS)} · pedidos a bitcoin-data: {PEDIDOS_BGEO['n']}", flush=True)
    if not VARS:
        print("ninguna variable disponible")
        return
    md.HOY["vars"], md.HOY["senales"] = list(VARS), list(SENS)    # evaluar_estados de medir_diarios lee de ahí
    labs = md.etiquetas_estados(P)
    score, desc = md.puntaje_termometro(o, P)
    tabla = {}
    try:
        tabla = md.evaluar_estados(labs, G["tr"], score, desc)
    except Exception as e:
        print(f"\n=== sección de estados no: {type(e).__name__}: {e} ===", flush=True)
    informe_episodios(labs)
    for f, a in ((redundancia, ()), (informe_cortas, (labs,))):
        try:
            f(*a)
        except Exception as e:
            print(f"\n=== {f.__name__} no: {type(e).__name__}: {e} ===", flush=True)
    resumen()
    informe_hoy(tabla, score, desc)


if __name__ == "__main__":
    main()
