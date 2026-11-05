import json, urllib.request
def get(u):
    try:
        return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "analista"}), timeout=15).read())
    except Exception as e:
        return {"error": str(e)[:150]}
DESDE = 1793577600000   # inicio del dia del plan (02/11/2026 UTC)
out = {}
for m in ["BTC", "SOL", "XRP", "ZEC"]:
    d = {}
    k = get(f"https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol={m}-USDT&interval=1h&startTime={DESDE}&limit=1000")
    if isinstance(k, dict) and isinstance(k.get("data"), list) and k["data"]:
        v = k["data"]; d["bingx"] = {"n": len(v), "bajo": min(float(x["low"]) for x in v), "alto": max(float(x["high"]) for x in v),
                                     "ultimo": sorted(v, key=lambda x: int(x["time"]))[-1]}
    else: d["bingx"] = k
    t = get(f"https://open-api.bingx.com/openApi/swap/v2/quote/price?symbol={m}-USDT")
    d["bingx_precio"] = t.get("data", t)
    pr = get(f"https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex?symbol={m}-USDT")
    d["bingx_marca"] = pr.get("data", pr)
    b = get(f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={m}USDT&productType=usdt-futures&granularity=1H&endTime={DESDE+200*3600000}&limit=200")
    b2 = get(f"https://api.bitget.com/api/v2/mix/market/candles?symbol={m}USDT&productType=usdt-futures&granularity=1H&limit=200")
    filas = [r for r in (b.get("data") or []) + (b2.get("data") or []) if int(r[0]) >= DESDE]
    d["bitget"] = {"n": len(filas), "bajo": min(float(r[3]) for r in filas), "alto": max(float(r[2]) for r in filas), "ultimo": max(filas)[4]} if filas else [b, b2]
    out[m] = d
print(json.dumps(out, indent=1))
