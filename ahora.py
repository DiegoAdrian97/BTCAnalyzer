import ccxt, json, time
out = {}
for eid in ("binanceusdm", "bybit", "bitget", "okx", "bingx"):
    try:
        ex = getattr(ccxt, eid)({"options": {"defaultType": "swap"}}); ms = ex.load_markets()
        out[eid] = sorted(s for s in ms if any(s.startswith(t + "/") for t in ("NVDA", "GOOGL", "GOOG", "AMD", "MELI", "AAPL", "MSFT", "AMZN", "META", "TSLA", "BABA")) and ":USDT" in s)
    except Exception as e:
        out[eid] = f"ERR {type(e).__name__} {str(e)[:80]}"
try:
    ex = ccxt.binanceusdm()
    for t in ("NVDA", "GOOGL", "AMD", "MELI", "BABA"):
        k = ex.fetch_ohlcv(f"{t}/USDT:USDT", "1d", since=1704067200000, limit=1000)
        out["binance_" + t] = [time.strftime("%Y-%m-%d", time.gmtime(k[0][0] / 1000)), len(k), k[-1][4]] if k else None
except Exception as e:
    out["binance_hist"] = f"ERR {e}"
print(json.dumps(out, indent=1))
