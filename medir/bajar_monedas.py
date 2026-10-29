"""Baja velas de 1 hora de futuros perpetuos USDT de Binance (data.binance.vision, archivos mensuales) desde 2020.
python medir/bajar_monedas.py SIMBOLO carpeta"""
import io, json, sys, urllib.request, zipfile, csv, datetime as dt
sym, out = sys.argv[1], sys.argv[2]
rows = []
y, m = 2020, 1
hoy = dt.date.today()
while (y, m) < (hoy.year, hoy.month):
    u = f"https://data.binance.vision/data/futures/um/monthly/klines/{sym}/1h/{sym}-1h-{y}-{m:02d}.zip"
    try:
        z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(u, timeout=60).read()))
        for r in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))):
            if r[0].isdigit():
                rows.append([int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
    except Exception as e:
        print(sym, y, m, type(e).__name__)
    m += 1
    if m == 13: y, m = y + 1, 1
# dias del mes en curso
d = dt.date(hoy.year, hoy.month, 1)
while d < hoy:
    u = f"https://data.binance.vision/data/futures/um/daily/klines/{sym}/1h/{sym}-1h-{d}.zip"
    try:
        z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(u, timeout=60).read()))
        for r in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))):
            if r[0].isdigit():
                rows.append([int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
    except Exception as e:
        print(sym, d, type(e).__name__)
    d += dt.timedelta(days=1)
rows = sorted({r[0]: r for r in rows}.values())
json.dump(rows, open(f"{out}/{sym}.json", "w"), separators=(",", ":"))
print(sym, len(rows))
