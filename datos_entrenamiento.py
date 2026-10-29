"""Baja lo que necesita entrenar_fuerte.py: velas de 1 hora de BTCUSDT perpetuo de Binance desde 2021
(data.binance.vision, archivos publicos) y las horas de los datos de importancia alta de EE.UU. (TradingView).
Lo usa la tarea mensual de GitHub (.github/workflows/reentrenar.yml). Escribe velas_1h.json y eventos.json.
"""
import csv, io, json, time, urllib.request, zipfile
from datetime import date, datetime, timedelta, timezone

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def _zip(u):
    for k in range(3):
        try:
            z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(u, timeout=60).read()))
            return [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
                    for r in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))) if r[0].isdigit()]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []
            time.sleep(5)
        except Exception:
            time.sleep(5)
    return []


def velas(sym="BTCUSDT"):
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
    return [r for r in rows if r[0] + 3600000 <= ahora]         # solo velas cerradas


def eventos():
    out, a = set(), datetime(2020, 12, 1, tzinfo=timezone.utc)
    fin = datetime.now(timezone.utc) + timedelta(days=8)
    while a < fin:
        b = min(fin, a + timedelta(days=30))
        u = ("https://economic-calendar.tradingview.com/events?from=" + a.strftime("%Y-%m-%dT%H:%M:%S.000Z") +
             "&to=" + b.strftime("%Y-%m-%dT%H:%M:%S.000Z") + "&countries=US")
        req = urllib.request.Request(u, headers={"User-Agent": UA, "Origin": "https://www.tradingview.com",
                                                 "Referer": "https://www.tradingview.com/"})
        for k in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    for e in json.loads(r.read().decode("utf-8", "replace")).get("result", []):
                        if e.get("importance") == 1 and e.get("date"):
                            out.add(int(datetime.fromisoformat(e["date"].replace("Z", "+00:00")).timestamp() * 1000))
                break
            except Exception:
                time.sleep(5)
        a = b
        time.sleep(1)
    return sorted(out)


def diario_largo():
    """BTC diario desde 2011 (Bitstamp, API publica): para el termometro de compra/venta (armar_termometro.py)."""
    out, start = {}, 1315000000
    while True:
        u = f"https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=86400&limit=1000&start={start}"
        d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=60).read())["data"]["ohlc"]
        if not d:
            break
        for x in d:
            out[int(x["timestamp"])] = [int(x["timestamp"]) * 1000, float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), float(x["volume"])]
        nxt = max(int(x["timestamp"]) for x in d) + 86400
        if nxt <= start or len(d) < 1000:
            break
        start = nxt
        time.sleep(1)
    return [out[k] for k in sorted(out)]


if __name__ == "__main__":
    B, E = velas(), eventos()
    assert len(B) > 40000, f"pocas velas: {len(B)}"
    assert len(E) > 300, f"pocos eventos: {len(E)}"
    hueco = max(b[0] - a[0] for a, b in zip(B, B[1:]))
    assert hueco <= 6 * 3600000, f"hueco de {hueco / 3600000:.0f} h en las velas"
    json.dump(B, open("velas_1h.json", "w"), separators=(",", ":"))
    json.dump(E, open("eventos.json", "w"))
    L = diario_largo()
    assert len(L) > 5000, f"pocas velas diarias: {len(L)}"
    json.dump(L, open("btc_diario.json", "w"))
    print(f"velas {len(B)} hasta {datetime.fromtimestamp(B[-1][0] / 1000, timezone.utc)} · eventos {len(E)}")
