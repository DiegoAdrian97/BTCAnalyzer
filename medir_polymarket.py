"""¿Las probabilidades de la gente en Polymarket sobre BTC anticipan mejor que el azar? (medir antes de usarlas). Nov. 2026.

Datos publicos, sin clave: Gamma (gamma-api.polymarket.com: eventos y mercados cerrados) y CLOB (clob.polymarket.com/prices-history).
ENFOQUE PRINCIPAL (estados de mediano plazo: ¿cerca de un piso, techo posible, rally, indecision?): las escaleras LARGAS,
 (c) "Will Bitcoin reach $X in <mes/año>?" y "Will Bitcoin dip to $Y in <mes/año>?" (P de tocar un maximo / un minimo en el
     periodo) y (b) "Bitcoin above $X on <fecha>", a 30 y 7 dias (y 180 en los de año) antes de resolver. Con cada escalera se
     arma la distribucion que implica la gente (mediana e intervalo 80% del maximo / minimo / cierre) y se chequea la cobertura
     contra lo que paso con las velas de Binance (ideal: 10% debajo del q10, 80% adentro, 10% arriba del q90).
     En los "hit" no se cuentan los strikes que ya estaban tocados al medir (P >= 0,97): no tienen nada que predecir.
Familias cortas (se mantienen):
 (a) "Bitcoin Up or Down" (por hora / 4 h / diario): P(Up) del token Up a la apertura de la ventana y 1 h despues
     (el +1 h solo si la ventana dura mas de 2 h) contra lo que paso (Up o Down segun el precio de resolucion).
 (b) "Bitcoin above $X on <fecha>" (escaleras diarias/semanales): P(arriba de X) 24 h y 7 dias antes de resolver.
Por familia: Brier contra el Brier de la tasa base (Brier skill score), acierto del favorito cuando P >= 0,6 o <= 0,4,
calibracion por deciles, y todo partido en dos tramos por fecha de resolucion (mitad de los mercados cada uno).
SIRVE: skill > 0 con z >= 2 en los DOS tramos. z de las diferencias pareadas por mercado, agrupadas por dia
(los mercados del mismo dia no son independientes: el n efectivo es la cantidad de dias).
Solo para (a): vs una base de momentum con el precio de BTC solo (P(up) = 0,5 + b1*ret1h + b2*ret24h, ajustada en el
tramo 1, velas de 1 h de data.binance.vision): ¿Polymarket agrega algo que el precio no diga?
La tasa base y el momentum se calculan con la misma muestra del tramo (le da ventaja al rival: es la vara dura).
Limites: max. ~3400 mercados, ~10000 peticiones y 70 min de bajada, con pausas; si un mercado falla, sigue con el que viene.
Uso: python medir_polymarket.py            (en Actions)
     python medir_polymarket.py --prueba   (sintetico, sin internet: corre todo de punta a punta)
"""
import io
import json
import math
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import csv
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

PRUEBA = "--prueba" in sys.argv
CAB = {"User-Agent": "analista-btc-medicion"}
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
MAX_MERCADOS = 3400          # mercados a los que se les baja historia (repartidos entre familias)
MAX_PETICIONES = 10000
TOPE_CORTA, TOPE_LARGA = 300, 600   # por familia; las largas van primero
TIEMPO_MAX = 70 * 60         # segundos: despues de esto no se baja mas historia (el job tiene 90 min)
PAUSA = 0.0 if PRUEBA else 0.2
NIVEL_FAV = 0.6              # favorito: P >= 0,6 o P <= 0,4
PET = {"n": 0}
VISTAS = set()               # para imprimir las claves del primer objeto de cada tipo


# ---------------------------------------------------------------- red
def http_json(url, params=None):
    """GET que devuelve JSON o None. Cuenta peticiones, pausa y reintenta (429/5xx)."""
    if PRUEBA or PET["n"] >= MAX_PETICIONES:
        return None
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for intento in range(3):
        PET["n"] += 1
        try:
            time.sleep(PAUSA)
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=CAB), timeout=40).read())
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            time.sleep(4 * (intento + 1))
        except Exception:
            time.sleep(2 * (intento + 1))
    return None


def claves(tipo, obj):
    if tipo not in VISTAS and isinstance(obj, dict):
        VISTAS.add(tipo)
        print(f"  [forma] {tipo}: {sorted(obj.keys())}", flush=True)


def jlist(x):
    """Gamma manda listas como string JSON ('["Up","Down"]'); acepta las dos formas."""
    if isinstance(x, str):
        try:
            x = json.loads(x)
        except Exception:
            return []
    return x if isinstance(x, list) else []


def ts(s):
    """ISO o epoch -> segundos epoch (o None)."""
    if s in (None, ""):
        return None
    try:
        if isinstance(s, (int, float)):
            return float(s) / (1000 if s > 1e11 else 1)
        return datetime.fromisoformat(str(s).replace("Z", "+00:00").replace(" ", "T")).astimezone(timezone.utc).timestamp() \
            if "T" in str(s).replace(" ", "T") and not str(s).replace(".", "").isdigit() else float(s)
    except Exception:
        try:
            return datetime.fromisoformat(str(s)[:10]).replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            return None


# ---------------------------------------------------------------- descubrir mercados
RE_UPDOWN = re.compile(r"bitcoin\s+up\s+or\s+down", re.I)
RE_ABOVE = re.compile(r"(?:bitcoin|btc)\s+(?:be\s+)?above\s+\$?\s*([\d][\d,\.]*)\s*([km])?", re.I)
RE_HIT = re.compile(r"(?:bitcoin|btc)\s+(reach|hit|touch|dip\s+to|drop\s+to|fall\s+to)\s+\$?\s*([\d][\d,\.]*)\s*([km])?", re.I)
MESES = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
RE_MES = re.compile(r"\b(" + "|".join(MESES) + r")\b", re.I)
RE_ANIO = re.compile(r"\b(20\d\d)\b")


def pnum(num, suf):
    try:
        v = float(num.replace(",", "").rstrip("."))
    except ValueError:
        return None
    return v * {"k": 1e3, "m": 1e6}.get((suf or "").lower(), 1)


def periodo(preg, fin):
    """('mes'|'año'|None, inicio del periodo en epoch) segun el texto; el fin es el de la resolucion."""
    d = datetime.fromtimestamp(fin - 3600, timezone.utc)
    if RE_MES.search(preg):
        return "mes", datetime(d.year, d.month, 1, tzinfo=timezone.utc).timestamp()
    if RE_ANIO.search(preg):
        return "año", datetime(d.year, 1, 1, tzinfo=timezone.utc).timestamp()
    return None, None
RE_RANGO = re.compile(r"\d{1,2}(:\d\d)?\s*(am|pm)\s*(et)?\s*[-–]\s*\d{1,2}", re.I)


def descubrir_real():
    """Eventos cerrados de Bitcoin por varias consultas; devuelve mercados crudos (con el evento pegado), sin repetir."""
    vistos, mercados = set(), []

    def agregar(ev, etiqueta, cont):
        claves("evento", ev)
        for m in ev.get("markets") or []:
            claves("mercado", m)
            k = m.get("id") or m.get("conditionId")
            if k in vistos:
                continue
            vistos.add(k)
            m["_ev"] = {"title": ev.get("title"), "slug": ev.get("slug"), "startTime": ev.get("startTime"),
                        "eventStartTime": ev.get("startTime") or m.get("eventStartTime")}
            mercados.append(m)
            cont[0] += 1

    for q in ("What price will Bitcoin hit", "Will Bitcoin reach", "Will Bitcoin dip to", "Bitcoin above on December 31",
              "Bitcoin above on", "What price will Bitcoin hit in 2025", "What price will Bitcoin hit in 2026"):
        ev_n, nuevos = 0, [0]
        for pg in range(1, 16):
            j = http_json(f"{GAMMA}/public-search", {"q": q, "page": pg, "limit_per_type": 50, "keep_closed_markets": 1})
            evs = j.get("events") if isinstance(j, dict) else None
            if not evs:
                break
            ev_n += len(evs)
            for ev in evs:
                if isinstance(ev, dict):
                    agregar(ev, q, nuevos)
            if not (j.get("pagination") or {}).get("hasMore"):
                break
        print(f"  consulta búsqueda '{q}': {ev_n} eventos, {nuevos[0]} mercados nuevos", flush=True)
    consultas = [("events tag=bitcoin closed", f"{GAMMA}/events",
                  {"closed": "true", "tag_slug": "bitcoin", "order": "endDate", "ascending": "false"}, 80),
                 ("events tag=crypto closed", f"{GAMMA}/events",
                  {"closed": "true", "tag_slug": "crypto", "order": "endDate", "ascending": "false"}, 40)]
    for nom, url, par, paginas in consultas:
        ev_n, nuevos = 0, [0]
        for pg in range(paginas):
            j = http_json(url, dict(par, limit=100, offset=pg * 100))
            if not isinstance(j, list) or not j:
                break
            ev_n += len(j)
            for ev in j:
                if isinstance(ev, dict):
                    t = f"{ev.get('title', '')} {ev.get('slug', '')}"
                    if "bitcoin" in t.lower() or "btc" in t.lower():
                        agregar(ev, nom, nuevos)
        print(f"  consulta '{nom}': {ev_n} eventos, {nuevos[0]} mercados nuevos de bitcoin", flush=True)
    for q in ("Bitcoin Up or Down",):
        ev_n, nuevos = 0, [0]
        for pg in range(1, 21):
            j = http_json(f"{GAMMA}/public-search", {"q": q, "page": pg, "limit_per_type": 50, "keep_closed_markets": 1})
            evs = j.get("events") if isinstance(j, dict) else None
            if not evs:
                break
            ev_n += len(evs)
            for ev in evs:
                if isinstance(ev, dict):
                    agregar(ev, q, nuevos)
            if not (j.get("pagination") or {}).get("hasMore"):
                break
        print(f"  consulta búsqueda '{q}': {ev_n} eventos, {nuevos[0]} mercados nuevos", flush=True)
    return mercados


def clasificar(m):
    """Mercado crudo -> dict normalizado de la familia (a)/(b) o None. Anota por que se descarta en m['_motivo']."""
    preg = str(m.get("question") or m.get("groupItemTitle") or (m.get("_ev") or {}).get("title") or "")
    slug = str(m.get("slug") or "")
    fin = ts(m.get("endDate") or m.get("closedTime") or m.get("endDateIso"))
    outs = [str(o).lower() for o in jlist(m.get("outcomes"))]
    px = [float(x) for x in jlist(m.get("outcomePrices")) if str(x).replace(".", "", 1).replace("e-", "").isdigit()] \
        if m.get("outcomePrices") else []
    tok = jlist(m.get("clobTokenIds"))
    if fin is None:
        return None, "sin fecha de fin"
    if len(outs) != len(px) or len(px) < 2 or len(tok) != len(outs):
        return None, "sin outcomes/precios/tokens"
    idx = next((i for i, o in enumerate(outs) if o in ("up", "yes")), None)
    if idx is None:
        return None, "sin token Up/Yes"
    if max(px) < 0.95:
        return None, "no resuelto claro (precios finales < 0,95)"
    res = 1 if px[idx] > 0.5 else 0
    base = {"fin": fin, "token": str(tok[idx]), "o": res, "preg": preg[:70], "vol": float(m.get("volumeNum") or m.get("volume") or 0),
            "evt": str((m.get("_ev") or {}).get("title") or "")[:60]}
    if RE_UPDOWN.search(preg) or RE_UPDOWN.search(slug.replace("-", " ")):
        ini = ts(m.get("eventStartTime") or (m.get("_ev") or {}).get("eventStartTime") or m.get("gameStartTime"))
        if ini is not None and 0 < fin - ini <= 36 * 3600:
            dur = fin - ini
        elif RE_RANGO.search(preg):
            return None, "up/down por hora sin eventStartTime"
        else:
            ini, dur = fin - 86400, 86400
        fam = "UpDown 1h" if dur <= 5400 else "UpDown 4h" if dur <= 18000 else "UpDown diario"
        return dict(base, fam=fam, ini=fin - dur), None
    mh = RE_HIT.search(preg)
    if mh:
        per, p0 = periodo(preg, fin)
        k = pnum(mh.group(2), mh.group(3))
        if per is None or k is None:
            return None, "hit sin mes/año o strike"
        bajo = bool(re.match(r"dip|drop|fall", mh.group(1), re.I))
        return dict(base, fam=f"Hit {'bajo' if bajo else 'alto'} {per}", strike=k, per_ini=p0, tipo="F" if bajo else "S"), None
    mm = RE_ABOVE.search(preg)
    if mm:
        k = pnum(mm.group(1), mm.group(2))
        if k is None:
            return None, "above sin strike"
        return dict(base, fam="Above escalera", strike=k, tipo="S"), None
    return None, "otro (no es up/down ni above)"


# ---------------------------------------------------------------- precios de Polymarket
def precio_en(token, t, fino=True):
    """Ultimo precio del token con ts <= t (a lo sumo 2 h antes en fino, 8 h en grueso). None si no hay."""
    if PRUEBA:
        return SINT_HIST.get((token, round(t)))
    for fid, atras, tol in ((5, 1800, 1800), (60, 8 * 3600, 8 * 3600)) if fino else ((60, 8 * 3600, 8 * 3600),):
        j = http_json(f"{CLOB}/prices-history", {"market": token, "startTs": int(t - atras), "endTs": int(t + 120), "fidelity": fid})
        h = (j or {}).get("history") if isinstance(j, dict) else None
        if h:
            claves("prices-history punto", h[0])
            c = [x for x in h if isinstance(x, dict) and x.get("t") is not None and x.get("p") is not None and x["t"] <= t + 120]
            if c:
                u = max(c, key=lambda x: x["t"])
                if t - u["t"] <= tol:
                    return float(u["p"])
    if not fino:        # mercados viejos: a veces solo contesta interval=max
        j = http_json(f"{CLOB}/prices-history", {"market": token, "interval": "max", "fidelity": 720})
        h = (j or {}).get("history") if isinstance(j, dict) else None
        c = [x for x in (h or []) if isinstance(x, dict) and x.get("t") is not None and x.get("p") is not None and x["t"] <= t + 120]
        if c:
            u = max(c, key=lambda x: x["t"])
            if t - u["t"] <= 86400:
                return float(u["p"])
    return None


# ---------------------------------------------------------------- BTC de Binance
def btc_horas(t0, t1):
    """{epoch_s de apertura de la vela de 1 h: open} de data.binance.vision spot, cubriendo [t0, t1]."""
    if PRUEBA:
        return SINT_BTC
    out = {}
    ms = lambda x: int(x) // (1000 if int(x) > 10**14 else 1)

    def bajar(url):
        for _ in range(2):
            try:
                z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(urllib.request.Request(url, headers=CAB), timeout=60).read()))
                for r in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))):
                    if r and r[0][:1].isdigit():
                        out[ms(r[0]) // 1000] = float(r[1])
                        BTC_HI[ms(r[0]) // 1000], BTC_LO[ms(r[0]) // 1000] = float(r[2]), float(r[3])
                return True
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return False
            except Exception:
                pass
            time.sleep(2)
        return False

    d0, d1 = datetime.fromtimestamp(t0, timezone.utc).date(), datetime.fromtimestamp(t1, timezone.utc).date()
    y, m = d0.year, d0.month
    hoy = date.today()
    while (y, m) <= (d1.year, d1.month):
        if (y, m) < (hoy.year, hoy.month):
            bajar(f"https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-{y}-{m:02d}.zip")
        else:
            d = date(y, m, 1)
            while d < hoy:
                bajar(f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1h/BTCUSDT-1h-{d.isoformat()}.zip")
                d += timedelta(days=1)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def retorno(btc, t, h):
    a, b = btc.get(int(t // 3600 * 3600)), btc.get(int(t // 3600 * 3600) - h * 3600)
    return (a / b - 1) if a and b else None


# ---------------------------------------------------------------- estadistica
def dia_de(t):
    return datetime.fromtimestamp(t, timezone.utc).date().isoformat()


def z_cluster(difs):
    """difs = [(cluster, d)]. Media y z con error estandar robusto por cluster (n efectivo = dias)."""
    if len(difs) < 8:
        return None, None, 0
    g = defaultdict(list)
    for c, d in difs:
        g[c].append(d)
    N = len(difs)
    media = sum(d for _, d in difs) / N
    if len(g) < 5:
        return media, None, len(g)
    var = sum((sum(v) - media * len(v)) ** 2 for v in g.values()) / N ** 2
    return media, (media / math.sqrt(var) if var > 0 else None), len(g)


def brier(ps, os_):
    return sum((p - o) ** 2 for p, o in zip(ps, os_)) / len(ps)


def mitades(filas):
    """Parte por fecha de resolucion: mitad de los mercados cada tramo. Devuelve (tramo1, tramo2, fecha_corte)."""
    f = sorted(filas, key=lambda r: r["fin"])
    h = len(f) // 2
    return f[:h], f[h:], (dia_de(f[h]["fin"]) if f else "-")


def analizar_tramo(g):
    """Brier, skill vs tasa base del tramo, z por dia, acierto del favorito."""
    if len(g) < 8:
        return None
    ps, os_ = [r["p"] for r in g], [r["o"] for r in g]
    base = sum(os_) / len(os_)
    b_p, b_0 = brier(ps, os_), brier([base] * len(os_), os_)
    difs = [(dia_de(r["fin"]), (base - r["o"]) ** 2 - (r["p"] - r["o"]) ** 2) for r in g]
    _, z, ndias = z_cluster(difs)
    fav = [r for r in g if r["p"] >= NIVEL_FAV or r["p"] <= 1 - NIVEL_FAV]
    acierto = sum((r["p"] >= 0.5) == bool(r["o"]) for r in fav) / len(fav) if fav else None
    return {"n": len(g), "dias": ndias, "base": base, "brier": b_p, "brier0": b_0,
            "skill": 1 - b_p / b_0 if b_0 > 1e-12 else None, "z": z, "nfav": len(fav), "acc": acierto}


def tabla_calibracion(g):
    print(f"    calibración (P dicha → % que pasó): ", end="")
    cub = defaultdict(list)
    for r in g:
        cub[min(int(r["p"] * 10), 9)].append(r)
    print(" | ".join(f"{b / 10:.1f}-{(b + 1) / 10:.1f}: {100 * sum(x['o'] for x in v) / len(v):3.0f}% (n {len(v)}, P media {100 * sum(x['p'] for x in v) / len(v):2.0f}%)"
                     for b, v in sorted(cub.items())), flush=True)


def fmt(a):
    if a is None:
        return "pocos mercados"
    if a["skill"] is None:
        return f"n {a['n']} · todos con el mismo resultado (sin skill calculable)"
    z = "  s/z" if a["z"] is None else f"{a['z']:+5.1f}"
    acc = "sin favoritos" if a["acc"] is None else f"{100 * a['acc']:3.0f}% (n {a['nfav']})"
    return (f"n {a['n']:>4} ({a['dias']:>3} días) · tasa base {100 * a['base']:3.0f}% · Brier {a['brier']:.4f} vs base {a['brier0']:.4f} · "
            f"skill {100 * a['skill']:+5.1f}% z {z} · acierta favorito {acc}")


def ajustar_momentum(g1):
    """Minimos cuadrados de (o - 0,5) sobre ret1h y ret24h (tramo 1) sin constante: P = 0,5 + b1*r1 + b2*r24."""
    xs = [(r["r1"], r["r24"], r["o"] - 0.5) for r in g1 if r.get("r1") is not None and r.get("r24") is not None]
    if len(xs) < 30:
        return None
    a11 = sum(x * x for x, _, _ in xs); a12 = sum(x * y for x, y, _ in xs); a22 = sum(y * y for _, y, _ in xs)
    c1 = sum(x * o for x, _, o in xs); c2 = sum(y * o for _, y, o in xs)
    det = a11 * a22 - a12 * a12
    return ((c1 * a22 - c2 * a12) / det, (a11 * c2 - a12 * c1) / det) if abs(det) > 1e-18 else None


def p_mom(b, r):
    return min(0.98, max(0.02, 0.5 + b[0] * r["r1"] + b[1] * r["r24"]))


# ---------------------------------------------------------------- recoleccion
def momentos(r):
    """(etiqueta, instante) a medir segun la familia."""
    if r["fam"] == "Above escalera":
        return [("24h antes", r["fin"] - 86400), ("7d antes", r["fin"] - 7 * 86400), ("30d antes", r["fin"] - 30 * 86400)]
    if r["fam"].startswith("Hit"):
        return [("30d antes", r["fin"] - 30 * 86400), ("7d antes", r["fin"] - 7 * 86400)] + \
               ([("180d antes", r["fin"] - 180 * 86400)] if r["fam"].endswith("año") else [])
    ms = [("apertura", r["ini"])]
    if r["fin"] - r["ini"] > 7200:
        ms.append(("+1h", r["ini"] + 3600))
    return ms


def repartir(cands, tope):
    """Quita mercados parejo en el tiempo hasta quedar en `tope`."""
    cands = sorted(cands, key=lambda r: r["fin"])
    if len(cands) <= tope:
        return cands
    if cands[0]["fam"] != "UpDown 1h" and not cands[0]["fam"].startswith("UpDown"):
        # escaleras: se eligen escaleras COMPLETAS (mismo fin), parejas en el tiempo, para poder armar la distribucion
        lad = defaultdict(list)
        for r in cands:
            lad[r["fin"]].append(r)
        fins, out = sorted(lad), []
        k = max(1, round(len(fins) * tope / len(cands)))
        for i in range(k):
            out += lad[fins[int(i * len(fins) / k)]]
        return out
    paso = len(cands) / tope
    return [cands[int(i * paso)] for i in range(tope)]


def main():
    print(f"Polymarket vs azar para BTC · {'PRUEBA sintetica' if PRUEBA else 'datos reales (Gamma + CLOB)'} · {date.today()}", flush=True)
    crudos = sintetico_mercados() if PRUEBA else descubrir_real()
    print(f"{len(crudos)} mercados de bitcoin crudos", flush=True)
    cl, motivos = [], defaultdict(int)
    for m in crudos:
        try:
            r, mot = clasificar(m)
        except Exception as e:
            r, mot = None, f"error al clasificar ({type(e).__name__})"
        if r:
            cl.append(r)
        else:
            motivos[mot] += 1
    print("descartados:", dict(motivos), flush=True)
    por_fam = defaultdict(list)
    for r in cl:
        por_fam[r["fam"]].append(r)
    print("familias:", {k: len(v) for k, v in por_fam.items()}, flush=True)
    for k, v in por_fam.items():
        if v:
            print(f"  ej. {k}: '{v[0]['preg']}' fin {dia_de(v[0]['fin'])}", flush=True)
    if not cl:
        print("no hay mercados para medir (¿cambió la forma de la API? mirar las [forma] de arriba)")
        return

    filas = defaultdict(list)       # (familia, momento) -> filas
    fallos = defaultdict(int)
    t_ini = time.time()
    largas_primero = sorted(por_fam.items(), key=lambda kv: kv[0].startswith("UpDown"))
    for fam, v in largas_primero:
        elegidos = repartir(v, TOPE_CORTA if fam.startswith("UpDown") else TOPE_LARGA)
        print(f"{fam}: {len(v)} mercados, se bajan {len(elegidos)}", flush=True)
        for i, r in enumerate(elegidos):
            try:
                for et, t in momentos(r):
                    p = precio_en(r["token"], t, fino=fam.startswith("UpDown"))
                    if p is None:
                        fallos[(fam, et)] += 1
                        continue
                    filas[(fam, et)].append(dict(r, p=p, t=t, mom=et))
            except Exception as e:
                fallos[(fam, "error")] += 1
            if (i + 1) % 200 == 0:
                print(f"    ... {i + 1}/{len(elegidos)} · {PET['n']} peticiones · {time.time() - t_ini:.0f}s", flush=True)
            if PET["n"] >= MAX_PETICIONES or time.time() - t_ini > TIEMPO_MAX:
                print("  tope de peticiones o de tiempo alcanzado: se corta la bajada de esta familia", flush=True)
                break
    print("sin precio / fallos:", {f"{a} {b}": n for (a, b), n in fallos.items()}, f"· peticiones: {PET['n']}", flush=True)

    # BTC: momentum (Up/Down) y lo realizado de las escaleras largas
    btc = {}
    todas = [r for g in filas.values() for r in g]
    ud = [r for r in todas if r["fam"].startswith("UpDown")]
    if todas:
        try:
            btc = btc_horas(min(min(r["t"], r.get("per_ini") or r["t"]) for r in todas) - 2 * 86400,
                            max(r["fin"] for r in todas) + 3600)
            print(f"BTC 1 h de Binance: {len(btc)} velas", flush=True)
        except Exception as e:
            print(f"BTC de Binance no disponible ({type(e).__name__}): se saltea el momentum y la cobertura", flush=True)
    for r in ud:
        r["r1"], r["r24"] = (retorno(btc, r["t"], 1), retorno(btc, r["t"], 24)) if btc else (None, None)

    resumen, pruebas = [], 0
    for (fam, et), g_todo in sorted(filas.items(), key=lambda kv: (kv[0][0].startswith("UpDown"), kv[0])):
        g = [r for r in g_todo if not (r["fam"].startswith("Hit") and r["p"] >= 0.97)]
        print(f"\n=== {fam} · {et} · {len(g)} mercados ===" + (f" (sin {len(g_todo) - len(g)} ya tocados)" if len(g) != len(g_todo) else ""), flush=True)
        t1, t2, corte = mitades(g)
        a1, a2 = analizar_tramo(t1), analizar_tramo(t2)
        print(f"  tramo 1 (hasta {corte}): {fmt(a1)}")
        print(f"  tramo 2 (desde {corte}): {fmt(a2)}")
        tabla_calibracion(g)
        ok = all(a and a["skill"] is not None and a["skill"] > 0 and a["z"] is not None and a["z"] >= 2 for a in (a1, a2))
        if a1 and a2:
            pruebas += 1
        ver = "SIRVE" if ok else "no sirve (no se repite)"
        print(f"  → {ver}", flush=True)
        extra = ""
        if fam.startswith("UpDown") and btc:
            b = ajustar_momentum([r for r in t1 if r.get("r1") is not None])
            if b is None:
                print("  momentum: sin datos suficientes para ajustar")
            else:
                cuent = []
                for nom, g_ in (("tramo 1 (ajuste)", t1), ("tramo 2 (fuera de muestra)", t2)):
                    gg = [r for r in g_ if r.get("r1") is not None and r.get("r24") is not None]
                    if len(gg) < 8:
                        cuent.append(None)
                        print(f"  momentum {nom}: pocos")
                        continue
                    os_ = [r["o"] for r in gg]
                    bm, bp = brier([p_mom(b, r) for r in gg], os_), brier([r["p"] for r in gg], os_)
                    b0 = brier([sum(os_) / len(os_)] * len(os_), os_)
                    _, z, _ = z_cluster([(dia_de(r["fin"]), (p_mom(b, r) - r["o"]) ** 2 - (r["p"] - r["o"]) ** 2) for r in gg])
                    zs = "s/z" if z is None else f"{z:+.1f}"
                    print(f"  momentum {nom}: Brier momentum {bm:.4f} · Polymarket {bp:.4f} · base {b0:.4f} · "
                          f"Polymarket mejor que momentum z {zs} (b1 {b[0]:+.1f}, b2 {b[1]:+.1f})")
                    cuent.append(z)
                if cuent[1] is not None and cuent[1] >= 2:
                    extra = " · agrega info más allá del precio"
                elif cuent[1] is not None:
                    extra = " · NO se distingue del momentum"
        elif fam.startswith("UpDown"):
            print("  momentum: sin precios de BTC (se saltea)")
        if not fam.startswith("UpDown"):
            cob = cobertura(g_todo, btc)
            if cob:
                extra += f" · cobertura 80% {cob}"
        resumen.append((fam, et, ver + extra, a1, a2))

    print(f"\n=== RESUMEN ({pruebas} pruebas con los dos tramos; SIRVE = skill > 0 y z >= 2 en ambos; primero las escaleras largas) ===")
    if not resumen:
        print("  nada que resumir (no se pudo bajar historia de precios)")
    for fam, et, ver, a1, a2 in resumen:
        s = lambda a: "s/d" if not a or a["skill"] is None else f"{100 * a['skill']:+.1f}% (z {'s/z' if a['z'] is None else format(a['z'], '+.1f')}, n {a['n']})"
        print(f"  {fam:<16} {et:<11} tramo 1 {s(a1):<26} tramo 2 {s(a2):<26} → {ver}")
    print("  Ojo: la tasa base se mide con la misma muestra (vara dura) y los mercados con poca liquidez tienen precios ruidosos.")

    print("\n=== HOY: escaleras abiertas de mes/año (probabilidades y rango implícito 80%) ===")
    lad = sintetico_hoy_largas() if PRUEBA else abiertos_largas()
    if not lad:
        print("  no se pudieron traer (o no hay)")
    for e in lad[:6]:
        print(f"  {e['titulo']} · cierra {e['fin']} · vol ${e['vol']:,.0f}")
        print(f"     {e['tipo']}: " + " · ".join(f"{k:,.0f}: {100 * p:.0f}%" for k, p in e["pts"][:12]))
        print(f"     implícito (q10 / mediana / q90): " + (" / ".join(f"{q:,.0f}" for q in e["q"]) if e["q"] else "no se puede (la escalera no cruza 10-90%)"))

    print("\n=== HOY: mercados abiertos de BTC (top 5 por volumen) ===")
    hoy = sintetico_hoy() if PRUEBA else abiertos_hoy()
    if not hoy:
        print("  no se pudieron traer (o no hay)")
    for m in hoy[:5]:
        print(f"  {m['preg']:<70} · {m['probs']} · vol ${m['vol']:,.0f} · cierra {m['fin']}")


def cruce(pts, nivel):
    """Strike (interpolado en log) donde la P cruza `nivel`; pts = [(strike, P)] ordenado por strike."""
    for (x0, p0), (x1, p1) in zip(pts, pts[1:]):
        if (p0 - nivel) * (p1 - nivel) <= 0 and p0 != p1 and x0 > 0 and x1 > 0:
            return math.exp(math.log(x0) + (nivel - p0) / (p1 - p0) * (math.log(x1) - math.log(x0)))
    return None


def cuantiles(pts, tipo):
    """Distribucion implicita de una escalera. tipo 'S': P(X >= strike) decreciente (maximo, cierre); 'F': P(X <= strike)
    creciente (minimo). Devuelve (q10, q50, q90) o None si no cruza. Primero se alisa a monotona."""
    pts = sorted(pts)
    if len(pts) < 4:
        return None
    xs, ps = [x for x, _ in pts], []
    for _, p in pts:
        ps.append(min(p, ps[-1]) if ps and tipo == "S" else max(p, ps[-1]) if ps else p)
    niv = (0.9, 0.5, 0.1) if tipo == "S" else (0.1, 0.5, 0.9)
    q = [cruce(list(zip(xs, ps)), n) for n in niv]
    return tuple(q) if all(q) else None


def realizado(r, btc):
    """Lo que paso: maximo / minimo del periodo (velas de 1 h de Binance) o cierre en la fecha."""
    if r["fam"] == "Above escalera":
        return btc.get(int(r["fin"] // 3600 * 3600))
    hs = [h for h in range(int(r["per_ini"] // 3600 * 3600), int(r["fin"] // 3600 * 3600), 3600)]
    v = [(BTC_HI if r["fam"].startswith("Hit alto") else BTC_LO).get(h) for h in hs]
    v = [x for x in v if x]
    if len(v) < 0.9 * len(hs):
        return None
    return max(v) if r["fam"].startswith("Hit alto") else min(v)


def cobertura(g, btc):
    """Por escalera (mismo fin): cuantiles implicitos vs realizado. Imprime y devuelve un texto corto para el RESUMEN."""
    if not btc:
        return None
    lad = defaultdict(list)
    for r in g:
        lad[r["fin"]].append(r)
    res = []
    for fin, rs in sorted(lad.items()):
        q = cuantiles([(r["strike"], r["p"]) for r in rs], rs[0]["tipo"])
        x = realizado(rs[0], btc) if q else None
        if q and x:
            res.append((fin, q, x))
    print(f"  distribución implícita: {len(res)} de {len(lad)} escaleras con cruce 10-90% y dato de Binance")
    if len(res) < 4:
        return None
    txt = []
    for nom, rr in (("todas", res), ("tramo 1", res[:len(res) // 2]), ("tramo 2", res[len(res) // 2:])):
        if not rr:
            continue
        n = len(rr)
        deb, den, enc = (sum(x < q[0] for _, q, x in rr), sum(q[0] <= x <= q[2] for _, q, x in rr), sum(x > q[2] for _, q, x in rr))
        med = sum(x > q[1] for _, q, x in rr)
        anc = statistics.median(q[2] / q[0] for _, q, _ in rr)
        print(f"    {nom:<8} n {n:>3}: debajo del q10 {100 * deb / n:3.0f}% (ideal 10) · adentro {100 * den / n:3.0f}% (ideal 80) · "
              f"arriba del q90 {100 * enc / n:3.0f}% (ideal 10) · arriba de la mediana {100 * med / n:3.0f}% (ideal 50) · ancho q90/q10 {anc:.2f}")
        if nom == "todas":
            txt.append(f"{100 * den / n:.0f}% adentro (n {n})")
    ult = res[-3:]
    for fin, q, x in ult:
        print(f"    ej. {dia_de(fin)}: q10 {q[0]:,.0f} · mediana {q[1]:,.0f} · q90 {q[2]:,.0f} → realizado {x:,.0f}")
    return " ".join(txt)


def abiertos_largas():
    """Eventos abiertos de mes/año ('reach'/'dip to' y 'above'): P de cada strike y rango implicito."""
    evs, vistos = [], set()
    for par in ({"closed": "false", "active": "true", "tag_slug": "bitcoin", "order": "volume", "ascending": "false", "limit": 100},):
        j = http_json(f"{GAMMA}/events", par)
        evs += [e for e in j if isinstance(e, dict)] if isinstance(j, list) else []
    for q in ("What price will Bitcoin hit", "Bitcoin above on"):
        j = http_json(f"{GAMMA}/public-search", {"q": q, "limit_per_type": 30})
        evs += [e for e in (j.get("events") or []) if isinstance(e, dict)] if isinstance(j, dict) else []
    out = []
    for ev in evs:
        if ev.get("id") in vistos or ev.get("closed"):
            continue
        vistos.add(ev.get("id"))
        lad = defaultdict(list)
        vol, fin = 0.0, None
        for m in ev.get("markets") or []:
            try:
                preg = str(m.get("question") or "")
                outs = [str(o).lower() for o in jlist(m.get("outcomes"))]
                px = jlist(m.get("outcomePrices"))
                if m.get("closed") or "yes" not in outs or len(px) != len(outs):
                    continue
                mh, ma = RE_HIT.search(preg), RE_ABOVE.search(preg)
                mt = mh or ma
                if not mt or (mh and periodo(preg, ts(m.get("endDate")) or 0)[0] is None):
                    continue
                k = pnum(mt.group(2), mt.group(3)) if mh else pnum(mt.group(1), mt.group(2))
                if k is None:
                    continue
                tipo = ("bajo (mínimo)", "F") if mh and re.match(r"dip|drop|fall", mh.group(1), re.I) else \
                       ("alto (máximo)", "S") if mh else ("cierre (above)", "S")
                lad[tipo].append((k, float(px[outs.index("yes")])))
                vol += float(m.get("volumeNum") or m.get("volume") or 0)
                fin = str(m.get("endDate") or "")[:10]
            except Exception:
                continue
        for (nom, tipo), pts in lad.items():
            pts = sorted(pts)
            if len(pts) >= 3:
                out.append({"titulo": str(ev.get("title") or "")[:60], "fin": fin, "vol": vol, "tipo": nom, "pts": pts,
                            "q": cuantiles(pts, tipo)})
    return sorted(out, key=lambda e: -e["vol"])


def abiertos_hoy():
    vistos, out = set(), []
    j = http_json(f"{GAMMA}/events", {"closed": "false", "active": "true", "tag_slug": "bitcoin", "order": "volume",
                                       "ascending": "false", "limit": 50})
    for ev in j if isinstance(j, list) else []:
        for m in (ev.get("markets") or []) if isinstance(ev, dict) else []:
            try:
                k = m.get("id") or m.get("conditionId")
                if k in vistos or m.get("closed"):
                    continue
                vistos.add(k)
                outs, px = jlist(m.get("outcomes")), jlist(m.get("outcomePrices"))
                q = str(m.get("question") or ev.get("title") or "")
                if "bitcoin" not in q.lower() and "btc" not in q.lower():
                    continue
                out.append({"preg": q[:70], "vol": float(m.get("volumeNum") or m.get("volume") or 0),
                            "probs": ", ".join(f"{o} {100 * float(p):.0f}%" for o, p in zip(outs, px)),
                            "fin": str(m.get("endDate") or "")[:16]})
            except Exception:
                continue
    return sorted(out, key=lambda m: -m["vol"])


# ---------------------------------------------------------------- datos sinteticos (--prueba)
SINT_HIST, SINT_BTC = {}, {}
BTC_HI, BTC_LO = {}, {}      # maximos y minimos de cada vela de 1 h (para lo realizado de las escaleras largas)


def sintetico_mercados():
    """Mercados con la misma forma que Gamma, un BTC de caminata al azar y precios de Polymarket con algo de habilidad."""
    rnd = random.Random(7)
    t0 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    horas = 420 * 24
    p = 90000.0
    for h in range(horas + 24):
        SINT_BTC[t0 + h * 3600] = p
        p *= math.exp(rnd.gauss(0, 0.004))
    px = lambda t: SINT_BTC[int(t // 3600 * 3600)]
    ms, n = [], 0

    def nuevo(fam, preg, ini, fin, o, p_by_time, strike=None):
        nonlocal n
        n += 1
        tok_si, tok_no = f"T{n}Y", f"T{n}N"
        for t, pp in p_by_time:
            SINT_HIST[(tok_si, round(t))] = pp
        ms.append({"id": str(n), "question": preg, "slug": preg.lower().replace(" ", "-"), "endDate": datetime.fromtimestamp(fin, timezone.utc).isoformat().replace("+00:00", "Z"),
                   "eventStartTime": datetime.fromtimestamp(ini, timezone.utc).isoformat().replace("+00:00", "Z") if ini else None,
                   "outcomes": '["Up","Down"]' if "Up" in preg else '["Yes","No"]',
                   "outcomePrices": '["1","0"]' if o else '["0","1"]', "clobTokenIds": json.dumps([tok_si, tok_no]),
                   "volumeNum": rnd.random() * 1e5, "_ev": {"title": preg}})

    # Up/Down por hora (muchos por dia), por 4 h y diarios
    for h in range(30, horas - 2, 1):
        ini = t0 + h * 3600
        for dur, nom, cada in ((3600, "1h", 3), (4 * 3600, "4h", 8), (86400, "dia", 24)):
            if h % cada:
                continue
            fin = ini + dur
            o = 1 if px(fin) > px(ini) else 0
            sk = 0.07 if nom != "dia" else 0.0                  # habilidad chica en las cortas, ninguna en la diaria
            pa = min(0.95, max(0.05, 0.5 + sk * (2 * o - 1) * rnd.random() + rnd.gauss(0, 0.04)))
            p1 = min(0.95, max(0.05, 0.5 + 1.5 * sk * (2 * o - 1) * rnd.random() + rnd.gauss(0, 0.04)))
            nuevo("ud", f"Bitcoin Up or Down - {nom} {h}", ini if nom != "dia" else None, fin, o,
                  [(ini, pa), (ini + 3600, p1)])
            ms[-1]["question"] = f"Bitcoin Up or Down" + (f" on day {h}" if nom == "dia" else f" {h}")
            if nom == "dia":
                ms[-1]["eventStartTime"] = None
    # escaleras "above"
    for d in range(32, 416, 1):
        fin = t0 + d * 86400
        for k in (-0.2, -0.1, -0.04, -0.02, 0, 0.02, 0.04, 0.1, 0.2):
            strike = round(px(fin - 86400) * (1 + k), -2)
            o = 1 if px(fin) > strike else 0
            true = 0.5 * math.erfc(-(math.log(px(fin - 86400) / strike)) / (0.02 * math.sqrt(2)))
            p24 = min(0.98, max(0.02, true + rnd.gauss(0, 0.05)))
            p7 = min(0.98, max(0.02, 0.5 + 0.3 * (p24 - 0.5) + rnd.gauss(0, 0.08)))
            p30 = min(0.98, max(0.02, 0.5 * (1 - math.erf(math.log(strike / px(fin - 30 * 86400)) / (0.11 * math.sqrt(2)))) + rnd.gauss(0, 0.05)))
            nuevo("ab", f"Will Bitcoin be above ${strike:,.0f} on day {d}?", None, fin, o,
                  [(fin - 86400, p24), (fin - 7 * 86400, p7), (fin - 30 * 86400, p30)])
    # escaleras "reach"/"dip to" por mes (P de tocar con GBM + ruido) y un par de años
    for h in range(horas + 24):
        BTC_HI[t0 + h * 3600] = max(SINT_BTC[t0 + h * 3600], SINT_BTC.get(t0 + (h + 1) * 3600, 0))
        BTC_LO[t0 + h * 3600] = min(SINT_BTC[t0 + h * 3600], SINT_BTC.get(t0 + (h + 1) * 3600, 1e18))
    Phi = lambda z: 0.5 * math.erfc(-z / math.sqrt(2))
    for mes in range(2, 13):
        i0, i1 = datetime(2026, mes, 1, tzinfo=timezone.utc), datetime(2026 + mes // 12, mes % 12 + 1, 1, tzinfo=timezone.utc)
        fin = int(i1.timestamp())
        ini = int(i0.timestamp())
        if fin - 30 * 86400 < t0 or fin > t0 + horas * 3600:
            continue
        hs = range(ini, fin, 3600)
        mx, mn_ = max(BTC_HI[h] for h in hs), min(BTC_LO[h] for h in hs)
        s0 = px(fin - 30 * 86400)
        for tipo, ks in (("reach", (0.03, 0.06, 0.1, 0.15, 0.2, 0.3)), ("dip to", (0.03, 0.06, 0.1, 0.15, 0.2, 0.3))):
            for k in ks:
                X = round(s0 * (1 + k if tipo == "reach" else 1 - k), -3)
                o = 1 if (mx >= X if tipo == "reach" else mn_ <= X) else 0
                pts = []
                for dias in (30, 7):
                    tt = fin - dias * 86400
                    St, sig = px(tt), 0.004 * math.sqrt(dias * 24)
                    z = abs(math.log(X / St)) / sig
                    pp = min(0.98, max(0.02, 2 * (1 - Phi(z)) + rnd.gauss(0, 0.04)))
                    done = (max(BTC_HI[h] for h in range(ini, tt, 3600)) >= X) if tipo == "reach" and tt > ini else \
                           (min(BTC_LO[h] for h in range(ini, tt, 3600)) <= X) if tt > ini else False
                    pts.append((tt, 0.99 if done else pp))
                nuevo("hit", f"Will Bitcoin {tipo} ${X:,.0f} in {MESES[mes - 1].title()}?", None, fin, o, pts)
                ms[-1]["eventStartTime"] = None
    # algunos mercados rotos para probar la defensa
    ms.append({"id": "x1", "question": "Bitcoin Up or Down", "endDate": None})
    ms.append({"id": "x2", "question": "Will Bitcoin hit $200k?", "endDate": "2026-05-01T00:00:00Z", "outcomes": "[]"})
    return ms


def sintetico_hoy_largas():
    pts = [(80000 + 5000 * i, max(0.02, 0.99 - 0.14 * i)) for i in range(8)]
    pts2 = [(50000 + 5000 * i, min(0.98, 0.02 + 0.14 * i)) for i in range(8)]
    return [{"titulo": "What price will Bitcoin hit in December? (sintético)", "fin": "2026-12-31", "vol": 5e6, "tipo": "alto (máximo)", "pts": pts,
             "q": cuantiles(pts, "S")},
            {"titulo": "What price will Bitcoin hit in December? (sintético)", "fin": "2026-12-31", "vol": 4e6, "tipo": "bajo (mínimo)", "pts": pts2,
             "q": cuantiles(pts2, "F")}]


def sintetico_hoy():
    return [{"preg": f"Bitcoin Up or Down (sintético {i})", "vol": 1e5 / (i + 1), "probs": "Up 52%, Down 48%", "fin": "2026-11-27T17:00"} for i in range(3)]


if __name__ == "__main__":
    main()
