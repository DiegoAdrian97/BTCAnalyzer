"""BTC diario desde 2011 (Bitstamp, API publica) para medir la media de 200 semanas con varios ciclos."""
import json, time, urllib.request
out, start = {}, 1315000000
while True:
    u = f"https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=86400&limit=1000&start={start}"
    d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read())["data"]["ohlc"]
    if not d: break
    for x in d: out[int(x["timestamp"])] = [int(x["timestamp"]) * 1000, float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), float(x["volume"])]
    nxt = max(int(x["timestamp"]) for x in d) + 86400
    print(len(out), flush=True)
    if nxt <= start or len(d) < 1000: break
    start = nxt; time.sleep(1)
json.dump([out[k] for k in sorted(out)], open("medir/monedas/btc_bitstamp_1d.json", "w"))
