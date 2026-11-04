"""Tabla de movimiento (como tabla_mov.py) con velas de 5 min de OKX, para lo que no esta en Binance (MELI).
Tambien prueba el formato de las velas de Bitget (la app las usa para MELI). python medir/tabla_mov_okx.py SIM salida.json"""
import json, math, sys, time, traceback, urllib.request, datetime as dt
sym, out = sys.argv[1], sys.argv[2]
base = sym.replace("USDT", "")
get = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read())
rows, after, err = [], None, None
try:      # OKX: velas viejas de a 100, de la mas nueva a la mas vieja
    for _ in range(3000):
        j = get(f"https://www.okx.com/api/v5/market/history-candles?instId={base}-USDT-SWAP&bar=5m&limit=100" + (f"&after={after}" if after else ""))
        d = j.get("data") or []
        if not d:
            err = f"fin: code {j.get('code')} {j.get('msg')}"; break
        rows += [(int(x[0]), float(x[2]), float(x[3]), float(x[4])) for x in d]
        after = min(int(x[0]) for x in d); time.sleep(0.12)
except Exception:
    err = traceback.format_exc()[-500:]
rows = sorted(set(rows)); n = len(rows); print(sym, n, "desde", dt.datetime.utcfromtimestamp(rows[0][0] / 1000) if rows else None, err, flush=True)
prueba = {"okx_filas": n, "okx_desde": rows[0][0] if rows else None, "okx_fin": err}
for nombre, u in (("candles", f"https://api.bitget.com/api/v2/mix/market/candles?symbol={sym}&productType=USDT-FUTURES&granularity=5m&limit=5"),
                  ("candles_1d", f"https://api.bitget.com/api/v2/mix/market/candles?symbol={sym}&productType=USDT-FUTURES&granularity=1D&limit=1000"),
                  ("history_5m", f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={sym}&productType=USDT-FUTURES&granularity=5m&limit=200&endTime={int(time.time()*1000) - 30 * 86400000}")):
    try:
        j = get(u); d = j.get("data") or []
        prueba[nombre] = {"code": j.get("code"), "n": len(d), "primero": d[:1], "ultimo": d[-1:]}
    except Exception as e:
        prueba[nombre] = str(e)[:200]
json.dump(prueba, open(out.replace(".json", "_bitget.json"), "w"), indent=1)
if n < 2000:
    sys.exit(0)
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
