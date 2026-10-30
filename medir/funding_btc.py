"""Funding historico de BTCUSDT perpetuo de Binance desde 2019-09 (todo lo publicado). python medir/funding_btc.py carpeta"""
import csv, io, json, sys, urllib.request, zipfile
filas = []
for y in range(2019, 2027):
    for m in range(1, 13):
        u = f"https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-{y}-{m:02d}.zip"
        try:
            z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(u, timeout=60).read()))
            for r in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))):
                if r and r[0].isdigit():
                    filas.append([int(r[0]), float(r[-1])])
        except Exception as e:
            print(y, m, type(e).__name__, flush=True)
filas.sort()
print(len(filas), filas[0], filas[-1], flush=True)
json.dump(filas, open(f"{sys.argv[1]}/funding_btc.json", "w"))
