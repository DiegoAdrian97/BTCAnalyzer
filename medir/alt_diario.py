"""Velas diarias de ZEC, SOL y XRP con toda la historia: Bitfinex (desde que cotiza) + Binance spot (data.binance.vision).
python medir/alt_diario.py carpeta"""
import csv, io, json, sys, time, urllib.request, zipfile
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read()
out = {}
for m in ("ZEC", "SOL", "XRP"):
    d = {}
    try:   # Bitfinex: [t, o, c, h, l, v]
        for k in json.loads(get(f"https://api-pub.bitfinex.com/v2/candles/trade:1D:t{m}USD/hist?limit=10000&sort=1")):
            d[k[0] // 86400000] = [k[0], k[1], k[3], k[4], k[2], k[5]]
        print(m, "bitfinex", len(d), flush=True)
    except Exception as e:
        print(m, "bitfinex", type(e).__name__, e, flush=True)
    nb = 0
    for y in range(2017, 2027):
        for mo in range(1, 13):
            u = f"https://data.binance.vision/data/spot/monthly/klines/{m}USDT/1d/{m}USDT-1d-{y}-{mo:02d}.zip"
            try:
                z = zipfile.ZipFile(io.BytesIO(get(u)))
                for r in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))):
                    if r and r[0].isdigit():
                        t = int(r[0]); t = t // 1000 if t > 1e14 else t      # 2025+: microsegundos
                        d[t // 86400000] = [t] + [float(x) for x in r[1:6]]; nb += 1
            except Exception:
                pass
    print(m, "binance", nb, flush=True)
    out[m] = [d[k] for k in sorted(d)]
    print(m, len(out[m]), time.strftime("%Y-%m-%d", time.gmtime(out[m][0][0] / 1000)), time.strftime("%Y-%m-%d", time.gmtime(out[m][-1][0] / 1000)), flush=True)
json.dump(out, open(f"{sys.argv[1]}/alt_diario.json", "w"))
