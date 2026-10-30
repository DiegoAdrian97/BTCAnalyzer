import ccxt, json, time
import indicadores as ind
ex = ccxt.kraken({"enableRateLimit": True})
out = {}
for tf in ("5m", "15m", "30m", "1h", "4h", "1d"):
    b = ex.fetch_ohlcv("BTC/USD", tf, limit=720)
    if tf == "1d":
        b = ex.fetch_ohlcv("BTC/USD", tf, since=int(time.time()*1000) - 719*86400000)
    c = [x[4] for x in b]; i = len(c) - 1
    e20, e50, e200 = ind.ema(c, 20)[i], ind.ema(c, 50)[i], ind.ema(c, 200)[i]
    rsi = ind.rsi(c); ml, ms, mh = ind.macd(c)
    _, summ, _ = ind.calificar(b)
    piv = ind.zigzag(b)
    div = ind.divergencias(b, piv)
    lo = min(x[3] for x in b[-60:]); lot = [x[0] for x in b[-60:] if x[3] == lo][0]
    out[tf] = {"n": len(b), "precio": c[i], "ema20": round(e20), "ema50": round(e50), "ema200": round(e200),
               "rsi": round(rsi[i], 1), "rsi_prev": [round(x, 1) for x in rsi[-6:]],
               "macd_hist": [round(x, 1) for x in mh[-6:]], "resumen": summ, "div": div,
               "min60": lo, "min60_t": time.strftime("%d/%m %H:%M", time.gmtime(lot / 1000)),
               "pivots": [(k, time.strftime("%d/%m %H:%M", time.gmtime(b[j][0] / 1000)), p) for k, j, p in piv[-6:]]}
print(json.dumps(out, default=str, ensure_ascii=False, indent=0))
