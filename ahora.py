import json, urllib.request
out = {}
def get(u):
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "analista"}), timeout=15)
        return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)[:150]}
BG = "https://api.bitget.com/api/v2/mix/market"
BY = "https://api.bybit.com/v5/market"
for m in ["MELI", "NVDA", "GOOGL", "AMD", "BABA"]:
    s = m + "USDT"
    d = {}
    d["bybit_tickers"] = get(f"{BY}/tickers?category=linear&symbol={s}")
    d["bybit_oi"] = get(f"{BY}/open-interest?category=linear&symbol={s}&intervalTime=1h&limit=3")
    d["bybit_ls"] = get(f"{BY}/account-ratio?category=linear&symbol={s}&period=1h&limit=3")
    d["bg_fund"] = get(f"{BG}/current-fund-rate?symbol={s}&productType=usdt-futures")
    d["bg_fundhist"] = get(f"{BG}/history-fund-rate?symbol={s}&productType=usdt-futures&pageSize=3")
    d["bg_oi"] = get(f"{BG}/open-interest?symbol={s}&productType=usdt-futures")
    d["bg_price"] = get(f"{BG}/symbol-price?symbol={s}&productType=usdt-futures")
    d["bg_als"] = get(f"{BG}/account-long-short?symbol={s}&period=1h")
    d["bg_ls"] = get(f"{BG}/long-short?symbol={s}&period=1h")
    d["bg_pls"] = get(f"{BG}/position-long-short?symbol={s}&period=1h")
    d["bg_taker"] = get(f"{BG}/taker-buy-sell?symbol={s}&productType=usdt-futures&period=1h")
    d["bg_depth"] = get(f"{BG}/merge-depth?symbol={s}&productType=usdt-futures&limit=5")
    d["bg_ticker"] = get(f"{BG}/ticker?symbol={s}&productType=usdt-futures")
    out[m] = d
def corta(x, n=2):
    if isinstance(x, dict): return {k: corta(v, n) for k, v in list(x.items())[:12]}
    if isinstance(x, list): return [corta(v, n) for v in x[:n]] + ([f"...{len(x)}"] if len(x) > n else [])
    return x
print(json.dumps(corta(out), indent=1))
