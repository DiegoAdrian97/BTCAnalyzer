"""Tabla de 'movimiento fuerte en la proxima hora' (como MOV_TABLA de analisis_btc.py) para una cripto, con velas de
5 min de futuros de Binance 2021-2026. python medir/tabla_mov.py SIMBOLO salida.json"""
import csv, io, json, math, sys, urllib.request, zipfile, datetime as dt
sym, out = sys.argv[1], sys.argv[2]
rows = []
y, m = 2021, 1
hoy = dt.date.today()
while (y, m) < (hoy.year, hoy.month):
    u = f"https://data.binance.vision/data/futures/um/monthly/klines/{sym}/5m/{sym}-5m-{y}-{m:02d}.zip"
    try:
        z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(u, timeout=120).read()))
        for r in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))):
            if r[0].isdigit(): rows.append((int(r[0]), float(r[2]), float(r[3]), float(r[4])))
    except Exception as e:
        print(sym, y, m, type(e).__name__, flush=True)
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
rows.sort(); n = len(rows); print(sym, n, flush=True)
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
