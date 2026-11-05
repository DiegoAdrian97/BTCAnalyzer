import json, urllib.request, time
def get(u):
    try:
        return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "analista"}), timeout=20).read())
    except Exception as e:
        return {"error": str(e)[:150]}
DESDE = 1759276800000          # 01/10/2025
DIA = 86400000
out = {}
for m in ["BTC", "SOL", "XRP", "ZEC"]:
    filas = {}
    t = DESDE
    while t < time.time() * 1000:
        j = get(f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={m}USDT&productType=usdt-futures&granularity=1D&endTime={t + 90 * DIA}&limit=90")
        for r in (j.get("data") or []):
            filas[int(r[0])] = r
        t += 90 * DIA
    v = sorted(filas.values(), key=lambda r: int(r[0]))
    if not v: out[m] = "sin datos"; continue
    lo = min(v, key=lambda r: float(r[3])); hi = max(v, key=lambda r: float(r[2]))
    # minimos por mes
    meses = {}
    for r in v:
        k = time.strftime("%Y-%m", time.gmtime(int(r[0]) / 1000)); meses[k] = min(meses.get(k, 1e18), float(r[3]))
    out[m] = {"n": len(v), "desde": time.strftime("%Y-%m-%d", time.gmtime(int(v[0][0]) / 1000)), "hasta": time.strftime("%Y-%m-%d", time.gmtime(int(v[-1][0]) / 1000)),
              "minimo": [float(lo[3]), time.strftime("%Y-%m-%d", time.gmtime(int(lo[0]) / 1000))], "maximo": [float(hi[2]), time.strftime("%Y-%m-%d", time.gmtime(int(hi[0]) / 1000))], "min_mes": meses}
print(json.dumps(out, indent=1))
