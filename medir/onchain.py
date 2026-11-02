"""Datos on-chain y de stablecoins gratis, con toda la historia. python medir/onchain.py carpeta"""
import json, sys, time, urllib.request
UA = {"User-Agent": "Mozilla/5.0"}
def get(u):
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=90).read())
out, log = {}, []
# CoinMetrics community: probamos de a una cada metrica (algunas son pagas)
for met in ("CapMrktCurUSD", "CapRealUSD", "CapMVRVCur", "IssTotUSD", "HashRate", "FeeTotUSD", "SplyCur", "AdrActCnt", "TxTfrValAdjUSD", "NVTAdj"):
    try:
        rows, u = [], f"https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics={met}&frequency=1d&page_size=10000&start_time=2010-07-01"
        while u:
            j = get(u); rows += [[r["time"][:10], float(r[met])] for r in j.get("data", []) if r.get(met) not in (None, "")]
            u = j.get("next_page_url")
        out["cm_" + met] = rows; log.append(f"cm {met}: {len(rows)} {rows[0][0] if rows else ''} {rows[-1][0] if rows else ''}")
    except Exception as e:
        log.append(f"cm {met}: {type(e).__name__} {str(e)[:120]}")
for ch in ("hash-rate", "miners-revenue", "mvrv", "market-price", "transaction-fees-usd"):
    try:
        j = get(f"https://api.blockchain.info/charts/{ch}?timespan=all&format=json&sampled=false")
        out["bc_" + ch] = [[p["x"], p["y"]] for p in j["values"]]; log.append(f"bc {ch}: {len(j['values'])}")
    except Exception as e:
        log.append(f"bc {ch}: {type(e).__name__} {str(e)[:120]}")
try:
    j = get("https://stablecoins.llama.fi/stablecoincharts/all")
    out["stables"] = [[int(r["date"]), float((r.get("totalCirculatingUSD") or {}).get("peggedUSD") or 0)] for r in j]
    log.append(f"stables: {len(out['stables'])}")
except Exception as e:
    log.append(f"stables: {type(e).__name__} {str(e)[:120]}")
for nom, u in (("okx_liq", "https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&instFamily=BTC-USDT&state=filled&limit=100"),
               ("okx_liq_usd", "https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&instFamily=BTC-USD&state=filled&limit=100")):
    try:
        j = get(u); out[nom] = j; d = j.get("data") or []
        log.append(f"{nom}: code {j.get('code')} {len(d)} grupos, {sum(len(x.get('details', [])) for x in d)} detalles")
    except Exception as e:
        log.append(f"{nom}: {type(e).__name__} {str(e)[:120]}")
json.dump(out, open(f"{sys.argv[1]}/onchain.json", "w"))
open(f"{sys.argv[1]}/onchain_log.txt", "w").write("\n".join(log))
print("\n".join(log))
