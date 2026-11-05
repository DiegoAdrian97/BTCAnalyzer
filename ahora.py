import json, urllib.request
UA = {"User-Agent": "Mozilla/5.0"}
out = {}
for sym in ("DX-Y.NYB", "DX=F"):
    try:
        j = json.loads(urllib.request.urlopen(urllib.request.Request(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=1262304000&period2=1794000000&interval=1d", headers=UA), timeout=60).read())
        r = j["chart"]["result"][0]; out[sym] = [[t, c] for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if c]
    except Exception as e:
        out[sym] = "error " + str(e)[:150]
print(json.dumps(out))
