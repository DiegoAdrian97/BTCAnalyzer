"""Que tan atras llega la historia de liquidaciones de OKX (paginando). python medir/liq_hist.py carpeta"""
import json, sys, time, urllib.request
def get(u):
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read())
out = {}
for fam in ("BTC-USDT", "BTC-USD"):
    after, n, filas, err = None, 0, [], None
    t0 = time.time()
    while n < 3000 and time.time() - t0 < 900:
        try:
            j = get("https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&instFamily=" + fam + "&state=filled&limit=100" + (f"&after={after}" if after else ""))
        except Exception as e:
            err = f"{type(e).__name__} {e}"; time.sleep(2); n += 1; continue
        det = [d for g in j.get("data") or [] for d in g.get("details") or []]
        if not det:
            err = f"vacio code={j.get('code')} msg={j.get('msg')}"; break
        filas += [[int(d["ts"]), d["posSide"], float(d["sz"]), float(d["bkPx"])] for d in det]
        nuevo = min(int(d["ts"]) for d in det)
        if after and nuevo >= after:
            err = "no avanza"; break
        after = nuevo; n += 1; time.sleep(0.25)
    out[fam] = {"paginas": n, "filas": len(filas), "desde": time.strftime("%Y-%m-%d %H:%M", time.gmtime(min(f[0] for f in filas) / 1000)) if filas else None,
                "hasta": time.strftime("%Y-%m-%d %H:%M", time.gmtime(max(f[0] for f in filas) / 1000)) if filas else None, "fin": err, "datos": filas}
    print(fam, {k: v for k, v in out[fam].items() if k != "datos"}, flush=True)
json.dump(out, open(f"{sys.argv[1]}/liq_hist.json", "w"))
