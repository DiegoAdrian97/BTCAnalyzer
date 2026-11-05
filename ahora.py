import json, urllib.request, re
UA = {"User-Agent": "analista"}
def get(u, raw=False):
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read()
        return r.decode() if raw else json.loads(r)
    except Exception as e:
        return {"error": str(e)[:120]}
Q = ["DIA", "DJI", "DJIA", "US30", "DOW", "YM", "DJ30", "WS30", "SPY", "US500", "SPX500"]
out = {}
bg = get("https://api.bitget.com/api/v2/mix/market/contracts?productType=usdt-futures")
out["bitget"] = [{k: d.get(k) for k in ("symbol", "baseCoin", "launchTime", "symbolType", "fundInterval")} for d in (bg.get("data") or []) if any(d["symbol"].startswith(q) for q in Q)]
ok = get("https://www.okx.com/api/v5/public/instruments?instType=SWAP")
out["okx"] = [{k: d.get(k) for k in ("instId", "listTime", "instFamily", "ctVal", "ctValCcy")} for d in (ok.get("data") or []) if any(d["instId"].startswith(q + "-") for q in Q)]
bn = {}
for q in Q:
    x = get(f"https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/futures/um/daily/klines/{q}USDT/1d/", raw=True)
    keys = re.findall(r"<Key>([^<]+)</Key>", x) if isinstance(x, str) else []
    if keys: bn[q] = (keys[0].split("/")[-1], len(keys) // 2)
out["binance"] = bn
# precio actual de cada candidato en Binance (por data.binance.vision no; por Bitget ticker)
pr = {}
for d in out["bitget"]:
    t = get(f"https://api.bitget.com/api/v2/mix/market/ticker?symbol={d['symbol']}&productType=usdt-futures")
    if isinstance(t, dict) and t.get("data"): pr[d["symbol"]] = (t["data"][0].get("lastPr"), t["data"][0].get("usdtVolume"))
out["bitget_precio"] = pr
print(json.dumps(out, indent=0))
