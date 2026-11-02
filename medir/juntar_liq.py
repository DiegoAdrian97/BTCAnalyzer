"""Junta las liquidaciones reales de OKX (BTC-USDT perpetuo). OKX publica solo el ultimo dia: corre cada 6 horas
(.github/workflows/juntarliq.yml) y va sumando a medir/monedas/liq_okx.csv.gz, para poder medir mas adelante si
las barridas anticipan algo. Columnas: ms, lado liquidado (long/short), BTC, precio."""
import csv, gzip, io, json, os, sys, time, urllib.request
ARCH = os.path.join(sys.argv[1], "liq_okx.csv.gz")
vistos = set()
if os.path.exists(ARCH):
    with gzip.open(ARCH, "rt") as f:
        vistos = {tuple(r) for r in csv.reader(f)}
nuevas, after = set(), None
for _ in range(60):
    u = "https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&instFamily=BTC-USDT&state=filled&limit=100" + (f"&after={after}" if after else "")
    j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read())
    det = [d for g in j.get("data") or [] for d in g.get("details") or []]
    if not det:
        break
    nuevas |= {(d["ts"], d["posSide"], f"{float(d['sz']) * 0.01:.4f}", d["bkPx"]) for d in det}
    nuevo = min(int(d["ts"]) for d in det)
    if after and nuevo >= after:
        break
    after = nuevo; time.sleep(0.3)
todo = sorted(vistos | nuevas, key=lambda r: int(r[0]))
with gzip.open(ARCH, "wt", newline="") as f:
    csv.writer(f).writerows(todo)
print(f"{len(nuevas - vistos)} nuevas, {len(todo)} en total desde {time.strftime('%Y-%m-%d', time.gmtime(int(todo[0][0]) / 1000)) if todo else '-'}")
