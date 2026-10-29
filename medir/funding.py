"""Funding historico de Binance (perpetuos USDT) 2023-2025: suma por año y por mes. python medir/funding.py carpeta"""
import csv, io, json, sys, urllib.request, zipfile
out = {}
for sym in ("BTCUSDT", "ZECUSDT", "SOLUSDT", "XRPUSDT"):
    filas = []
    for y in (2023, 2024, 2025):
        for m in range(1, 13):
            u = f"https://data.binance.vision/data/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{y}-{m:02d}.zip"
            try:
                z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(u, timeout=60).read()))
                for r in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))):
                    if r and r[0].isdigit():
                        filas.append([int(r[0]), float(r[-1])])
            except Exception as e:
                print(sym, y, m, type(e).__name__, flush=True)
    out[sym] = filas
    print(sym, len(filas), flush=True)
json.dump(out, open(f"{sys.argv[1]}/funding.json", "w"))
