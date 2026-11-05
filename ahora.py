import json, urllib.request, csv, io
UA = {"User-Agent": "Mozilla/5.0"}
def raw(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read().decode()
out = {}
for nom, sid in (("fred_broad", "DTWEXBGS"), ("fred_major", "DTWEXM"), ("fred_afe", "DTWEXAFEGS")):
    try:
        rows = [r for r in csv.reader(io.StringIO(raw(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}")))][1:]
        out[nom] = [[r[0], float(r[1])] for r in rows if len(r) > 1 and r[1] not in (".", "")]
    except Exception as e:
        out[nom] = "error " + str(e)[:150]
try:
    j = json.loads(raw("https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?range=max&interval=1d"))
    r = j["chart"]["result"][0]; out["yahoo_dxy"] = [[t, c] for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if c]
except Exception as e:
    out["yahoo_dxy"] = "error " + str(e)[:150]
try:
    rows = list(csv.reader(io.StringIO(raw("https://stooq.com/q/d/l/?s=dx.f&i=d"))))[1:]
    out["stooq_dxy"] = [[r[0], float(r[4])] for r in rows if len(r) > 4]
except Exception as e:
    out["stooq_dxy"] = "error " + str(e)[:150]
print(json.dumps(out))
