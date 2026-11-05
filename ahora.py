import json, urllib.request, re
UA = {"User-Agent": "analista"}
def get(u, raw=False):
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read()
        return r.decode() if raw else json.loads(r)
    except Exception as e:
        return {"error": str(e)[:120]}
SYMS = ["AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "SPCX", "SPACEX", "META", "AVGO", "TSLA", "WMT", "MU", "AMD"]
out = {}
bg = get("https://api.bitget.com/api/v2/mix/market/contracts?productType=usdt-futures")
lst = [d["symbol"] for d in (bg.get("data") or [])] if isinstance(bg, dict) else []
out["bitget"] = {s: [x for x in lst if x.startswith(s) and x.endswith("USDT")] for s in SYMS}
ok = get("https://www.okx.com/api/v5/public/instruments?instType=SWAP")
lo = [d["instId"] for d in (ok.get("data") or [])] if isinstance(ok, dict) else []
out["okx"] = {s: [x for x in lo if x.split("-")[0] == s] for s in SYMS}
# Binance futuros (data.binance.vision): primer dia de velas diarias de cada par
bn = {}
for s in SYMS:
    x = get(f"https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/futures/um/daily/klines/{s}USDT/1d/", raw=True)
    keys = re.findall(r"<Key>([^<]+)</Key>", x) if isinstance(x, str) else []
    bn[s] = (keys[0].split("/")[-1], len(keys)) if keys else None
out["binance"] = bn
# historia en Bitget (primer vela diaria)
hist = {}
for s in SYMS:
    if out["bitget"].get(s):
        j = get(f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={s}USDT&productType=usdt-futures&granularity=1D&endTime=1800000000000&limit=200")
        d = j.get("data") if isinstance(j, dict) else None
        hist[s] = (min(int(r[0]) for r in d), len(d), sum(float(r[6]) for r in d[-30:]) / 30) if d else j
out["bitget_hist"] = hist
print(json.dumps(out, indent=1))
