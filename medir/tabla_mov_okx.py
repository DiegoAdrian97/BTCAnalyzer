"""Tabla de movimiento (como tabla_mov.py) con velas de 5 min de OKX, para lo que no esta en Binance (MELI).
Tambien prueba el formato de las velas de Bitget (la app las usa para MELI). python medir/tabla_mov_okx.py SIM salida.json"""
import json, math, sys, time, urllib.request, datetime as dt
import ccxt
sym, out = sys.argv[1], sys.argv[2]
base = sym.replace("USDT", "")
ex = ccxt.okx({"enableRateLimit": True})
desde = int(time.time() * 1000) - 400 * 86400000
rows, t = [], desde
while True:
    k = ex.fetch_ohlcv(f"{base}/USDT:USDT", "5m", since=t, limit=100, params={"method": "publicGetMarketHistoryCandles"})
    k = [x for x in k if x[0] >= t]
    if not k:
        if t > time.time() * 1000 - 86400000: break
        t += 100 * 300000; continue
    rows += [(x[0], x[2], x[3], x[4]) for x in k]
    t = k[-1][0] + 300000
    if t > time.time() * 1000: break
rows = sorted(set(rows)); n = len(rows); print(sym, n, "desde", dt.datetime.utcfromtimestamp(rows[0][0] / 1000) if rows else None, flush=True)
prueba = {}
for nombre, u in (("candles", f"https://api.bitget.com/api/v2/mix/market/candles?symbol={sym}&productType=USDT-FUTURES&granularity=5m&limit=5"),
                  ("history", f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={sym}&productType=USDT-FUTURES&granularity=1D&limit=5&endTime={int(time.time()*1000) - 300 * 86400000}"),
                  ("candles_1d_1000", f"https://api.bitget.com/api/v2/mix/market/candles?symbol={sym}&productType=USDT-FUTURES&granularity=1D&limit=1000")):
    try:
        j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read())
        d = j.get("data") or []
        prueba[nombre] = {"code": j.get("code"), "n": len(d), "primero": d[:1], "ultimo": d[-1:]}
    except Exception as e:
        prueba[nombre] = str(e)[:200]
json.dump(prueba, open(out.replace(".json", "_bitget.json"), "w"), indent=1)
CORTES = (0.8, 1.0, 1.3, 1.6, 2.0, 2.5)
af, asl = 2 / 21, 2 / 201; ef = es = None; vr = [1.0] * n
for i, (_, h, l, c) in enumerate(rows):
    v = ((h - l) / c) ** 2; ef = v if ef is None else ef + af * (v - ef); es = v if es is None else es + asl * (v - es)
    vr[i] = math.sqrt(ef / es) if es > 0 else 1.0
rng = [None] * n
for i in range(n - 12):
    rng[i] = (max(x[1] for x in rows[i + 1:i + 13]) - min(x[2] for x in rows[i + 1:i + 13])) / rows[i][3]
cub = [[] for _ in range(7)]; todos = []
hist = []
for i in range(0, n - 12, 12):
    if len(hist) >= 720:
        med = sorted(hist[-720:])[360]
        r = rng[i] / med; k = sum(1 for x in CORTES if vr[i] >= x)
        cub[k].append(r); todos.append(r)
    if i >= 12 and rng[i - 12] is not None: hist.append(rng[i - 12])
tabla = {"prob": [round(100 * sum(r > 2 for r in c) / len(c)) if c else None for c in cub],
         "veces": [round(sorted(c)[len(c) // 2], 2) if c else None for c in cub],
         "base": round(100 * sum(r > 2 for r in todos) / len(todos)), "n": [len(c) for c in cub]}
json.dump(tabla, open(out, "w")); print(sym, tabla)
