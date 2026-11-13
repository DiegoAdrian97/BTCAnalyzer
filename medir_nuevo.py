"""¿Lo nuevo mejora la prediccion? (medir antes de sumar) Mide, con años de historia de BTC:

  1. Calendario economico: despues de un dato de EE.UU. que la app marca "positivo" o "negativo" para el mercado
     (noticias.efecto: la sorpresa contra lo previsto), ¿BTC fue para ese lado en la hora y en las 4 horas siguientes?
  2. Mapa de liquidaciones (el modelo nuevo, el de indicadores.liq_perfil, con el open interest de Binance): cuando
     hay mas liquidaciones de un lado a menos de 3% ("iman"), ¿el precio va para ese lado? ¿toca primero ese lado?
  3. Cuentas largas/cortas y top traders (Binance) en extremos de 30 dias, y open interest con precio (entran largos,
     entran cortos, cierres): ¿anticipan la direccion?

Datos publicos: data.binance.vision (velas de 1 hora y de 5 minutos, y las "metrics" de 5 minutos desde 2021-12:
open interest, cuentas y top traders) y el calendario de TradingView. Cada señal se mide aparte en 2021-24 y en
2025-26: entra a la app solo lo que gana en los dos (z >= 2, el mismo lado). Lo que no tiene historia gratis (libros de
ordenes, Gate, Bitget, Hyperliquid, MEXC, Coinbase por exchange) no se puede medir: se dice.
Uso: python medir_nuevo.py   (baja todo a datos_medicion/nuevo, se reusa)
"""
import csv, io, json, math, os, time, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import numpy as np

import noticias

CAB = {"User-Agent": "analista-btc-medicion"}
DIR = os.path.join("datos_medicion", "nuevo")
CORTE = 1735689600000                                   # 2025-01-01
H = 3_600_000


def _zip(url, archivo, fila):
    os.makedirs(DIR, exist_ok=True)
    f = os.path.join(DIR, archivo)
    if os.path.exists(f):
        return json.load(open(f))
    for _ in range(3):
        try:
            z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(urllib.request.Request(url, headers=CAB), timeout=60).read()))
            rows = [fila(r) for r in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))) if r and r[0][:1].isdigit()]
            rows = [r for r in rows if r]
            json.dump(rows, open(f, "w"))
            return rows
        except urllib.error.HTTPError as e:
            if e.code == 404:
                json.dump([], open(f, "w"))
                return []
            time.sleep(2)
        except Exception:
            time.sleep(2)
    return []


def meses(desde=(2021, 1)):
    y, m = desde
    hoy = date.today()
    while (y, m) < (hoy.year, hoy.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def velas(tf):
    ms = lambda x: int(x) // (1000 if int(x) > 10**14 else 1)
    out = []
    for y, m in meses():
        out += _zip(f"https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/{tf}/BTCUSDT-{tf}-{y}-{m:02d}.zip",
                    f"k{tf}_{y}-{m:02d}.json", lambda r: [ms(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])])
    return out


def metricas():
    """Cada 5 min: [t, open interest USD, parte larga de las cuentas, parte larga de los top traders (cuentas)]."""
    def fila(r):
        try:
            t = int(datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)
            ls, top = float(r[6]), float(r[4])
            return [t, float(r[3]), ls / (1 + ls), top / (1 + top)]
        except (ValueError, IndexError):
            return None
    dias, d = [], date(2021, 12, 1)
    while d < date.today():
        dias.append(d)
        d += timedelta(days=1)
    bajar = lambda d: _zip(f"https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-{d.isoformat()}.zip",
                           f"m_{d.isoformat()}.json", fila)
    with ThreadPoolExecutor(8) as pool:
        partes = list(pool.map(bajar, dias))
    return sorted(x for p in partes for x in p)


def calendario():
    """Datos de EE.UU. de importancia media y alta (TradingView), mes a mes desde 2021."""
    f = os.path.join(DIR, "calendario.json")
    if os.path.exists(f) and time.time() - os.path.getmtime(f) < 20 * 86400:
        return json.load(open(f))
    out = []
    for y, m in meses():
        a = datetime(y, m, 1, tzinfo=timezone.utc)
        b = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
        u = ("https://economic-calendar.tradingview.com/events?from=" + a.strftime("%Y-%m-%dT%H:%M:%S.000Z") + "&to="
             + b.strftime("%Y-%m-%dT%H:%M:%S.000Z") + "&countries=US")
        for _ in range(3):
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Origin": "https://www.tradingview.com", "Referer": "https://www.tradingview.com/"})
                txt = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
                out += [r for r in noticias.parse_calendario(txt) if r["tabla"] == "calendario"]
                break
            except Exception as e:
                print(f"  (calendario {y}-{m:02d}: {type(e).__name__})", flush=True)
                time.sleep(3)
        time.sleep(0.6)
    os.makedirs(DIR, exist_ok=True)
    json.dump(out, open(f, "w"))
    return out


def z_de(ok, n):
    return (ok / n - 0.5) / math.sqrt(0.25 / n) if n else 0.0


def linea(nombre, eventos, resultado, horizontes):
    """eventos: [(t, lado)]; resultado(t, lado, h) -> True/False/None. Imprime % y z por tramo."""
    txt = f"  {nombre:<46}"
    for hz in horizontes:
        for a, b, et in ((0, CORTE, "21-24"), (CORTE, 10**15, "25-26")):
            r = [resultado(t, s, hz) for t, s in eventos if a <= t < b]
            r = [x for x in r if x is not None]
            ok = sum(r)
            txt += f" | {hz} {et}: {len(r):>5} · {100 * ok / max(1, len(r)):5.1f}% (z {z_de(ok, len(r)):+5.1f})"
    print(txt, flush=True)


def main():
    K1 = velas("1h")
    T1 = np.array([k[0] for k in K1], dtype=np.int64)
    O1, H1, L1, C1 = (np.array([k[i] for k in K1]) for i in (1, 2, 3, 4))
    idx = {int(t): i for i, t in enumerate(T1)}
    print(f"{len(K1)} velas de 1 h", flush=True)

    def dir_h(t, lado, hz):
        """La vela que abre en t (o la hora siguiente): ¿el cierre hz horas despues quedo del lado esperado?"""
        i = idx.get(t)
        if i is None or i + hz >= len(C1):
            return None
        return (C1[i + hz] > C1[i]) == (lado > 0)

    # ---------- 1. calendario ----------
    print("\n1. Calendario economico (la marca positivo/negativo de la app)", flush=True)
    try:
        cal = calendario()
        K5 = velas("5m")
        T5 = np.array([k[0] for k in K5], dtype=np.int64)
        O5, C5 = np.array([k[1] for k in K5]), np.array([k[4] for k in K5])
        print(f"  {len(cal)} datos; {len(K5)} velas de 5 min", flush=True)

        def tras_dato(t, lado, minutos):
            i = int(np.searchsorted(T5, t))           # la vela de 5 min en la que sale el dato
            j = i + minutos // 5
            if i >= len(T5) or j >= len(T5) or T5[i] - t > 300_000:
                return None
            return (C5[j] > O5[i]) == (lado > 0)
        for imp, nom in ((3, "importancia alta"), (2, "importancia media"), (0, "todos")):
            ev = [(e["t"], 1 if e["efecto"] == "positivo" else -1) for e in cal
                  if e.get("efecto") in ("positivo", "negativo") and (imp == 0 or e["importancia"] == imp)]
            # varios datos a la misma hora: se suman sus marcas (si se anulan, no cuenta)
            por = {}
            for t, s in ev:
                por[t] = por.get(t, 0) + s
            ev = [(t, 1 if s > 0 else -1) for t, s in sorted(por.items()) if s]
            linea(f"dato {nom}", ev, tras_dato, (15, 60, 240))
        for clave, nom in (("inflation", "inflación (IPC, PCE)"), ("payrolls", "nóminas"), ("unemployment", "desempleo"), ("jobless", "subsidios"),
                           ("interest rate", "tasa de la Fed")):
            ev = [(e["t"], 1 if e["efecto"] == "positivo" else -1) for e in cal if e.get("efecto") in ("positivo", "negativo") and clave in e["original"].lower()]
            linea(f"  {nom}", sorted(set(ev)), tras_dato, (60, 240))
    except Exception as e:
        print(f"  calendario no disponible: {type(e).__name__}: {e}", flush=True)

    # ---------- metricas de Binance (cada 5 min) a cada hora ----------
    M = metricas()
    print(f"\n{len(M)} metricas de 5 min (open interest, cuentas, top traders)", flush=True)
    mh = {}
    for t, oi, ls, top in M:
        if t % H == 0:
            mh[t] = (oi, ls, top)

    # ---------- 2. mapa de liquidaciones (el modelo nuevo, paso a paso) ----------
    print("\n2. Mapa de liquidaciones (modelo nuevo, open interest de Binance)", flush=True)
    NIV = [(3, 0.06), (5, 0.1), (10, 0.22), (25, 0.27), (50, 0.2), (100, 0.15)]
    MANT, PASO, P0 = 0.005, 0.0025, 8000.0
    NB = int(math.log(250000 / P0) / PASO) + 1
    binf = lambda p: int(math.floor(math.log(p / P0) / PASO))
    Lt, St = np.zeros((len(NIV), NB)), np.zeros((len(NIV), NB))
    dec = 0.5 ** (1 / 120)                                      # vida media 5 dias en velas de 1 h
    iman, ls_ult = [], 0.5
    for i in range(1, len(T1)):
        t, tp = int(T1[i]), int(T1[i - 1])
        Lt[:, max(0, binf(L1[i])):] = 0
        St[:, :min(NB, binf(H1[i]) + 1)] = 0
        a, b = mh.get(t), mh.get(tp)
        if a is None or b is None:
            continue
        delta = a[0] - b[0]
        fac = dec * (max(0.0, 1 + delta / b[0]) if delta < 0 and b[0] > 0 else 1.0)
        Lt *= fac
        St *= fac
        if delta > 0:
            ls_ult = a[1]
            e = (H1[i] + L1[i] + C1[i]) / 3
            for k, (lev, w) in enumerate(NIV):
                pl, ps = e * (1 - 1 / lev + MANT), e * (1 + 1 / lev - MANT)
                if pl < L1[i]:
                    Lt[k, binf(pl)] += delta * ls_ult * w
                if ps > H1[i]:
                    St[k, binf(ps)] += delta * (1 - ls_ult) * w
        c = C1[i]
        abajo = Lt[:, binf(c * 0.97):binf(c) + 1].sum()
        arriba = St[:, binf(c):binf(c * 1.03) + 1].sum()
        if arriba + abajo > 0:
            if arriba >= 1.5 * abajo:
                iman.append((int(T1[i]) + H, 1))
            elif abajo >= 1.5 * arriba:
                iman.append((int(T1[i]) + H, -1))

    def primero(t, lado, pct):
        """¿Toca primero +pct (lado>0) o -pct? en 48 h."""
        i = idx.get(t)
        if i is None:
            return None
        ref = O1[i]
        for j in range(i, min(len(C1), i + 48)):
            up, dn = H1[j] >= ref * (1 + pct), L1[j] <= ref * (1 - pct)
            if up and dn:
                return None
            if up or dn:
                return up == (lado > 0)
        return None
    linea("más liquidaciones de un lado (iman)", iman, dir_h, (1, 4, 24))
    linea("  toca primero ese lado (±1% / ±2%)", iman, lambda t, s, p: primero(t, s, p / 100), (1, 2))

    # ---------- 3. cuentas, top traders y open interest ----------
    print("\n3. Cuentas, top traders y open interest (Binance)", flush=True)
    ts = sorted(mh)
    vals = {k: np.array([mh[t][k] for t in ts]) for k in (1, 2)}
    for k, nom in ((1, "cuentas"), (2, "top traders")):
        ev_alto, ev_bajo = [], []
        for n in range(720, len(ts)):
            v = vals[k][n - 720:n + 1]
            q10, q90 = np.quantile(v, 0.1), np.quantile(v, 0.9)
            if vals[k][n] >= q90:
                ev_alto.append((ts[n], -1))                 # muchos largos: a la contra, baja
            elif vals[k][n] <= q10:
                ev_bajo.append((ts[n], 1))
        linea(f"{nom}: muy largas (30 d) -> baja", ev_alto, dir_h, (1, 4, 24))
        linea(f"{nom}: muy cortas (30 d) -> sube", ev_bajo, dir_h, (1, 4, 24))
    ev = {"entran largos (OI y precio suben 4 h)": [], "entran cortos (OI sube, precio baja)": [], "cierran cortos (OI baja, precio sube)": [], "cierran largos (OI baja, precio baja)": []}
    for t in ts:
        i, a, b = idx.get(t), mh.get(t), mh.get(t - 4 * H)
        if i is None or i < 5 or not b or not (b[0] > 0) or not (a[0] > 0):
            continue
        doi, dpx = a[0] / b[0] - 1, C1[i - 1] / C1[i - 5] - 1
        if abs(doi) < 0.01:
            continue
        clave = ("entran largos (OI y precio suben 4 h)" if dpx > 0 else "entran cortos (OI sube, precio baja)") if doi > 0 else \
                ("cierran cortos (OI baja, precio sube)" if dpx > 0 else "cierran largos (OI baja, precio baja)")
        ev[clave].append((t, 1 if dpx > 0 else -1))           # ¿sigue para el lado del precio?
    for nom, e in ev.items():
        linea(f"{nom}: sigue", e, dir_h, (1, 4, 24))
    print("\nSin historia gratis (no se pueden medir): libros de ordenes y muros, trades por exchange de Bybit, OKX y Coinbase,"
          " y el open interest de Gate, Bitget, Hyperliquid y MEXC de mas de unas semanas.", flush=True)


if __name__ == "__main__":
    main()
