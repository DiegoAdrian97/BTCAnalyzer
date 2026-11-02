"""Busca historia gratis de liquidaciones de BTC. python medir/liq_hist.py carpeta"""
import json, sys, urllib.request
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
def get(u):
    r = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60); return r.status, r.read()
pruebas = {
 "cm_exasset": "https://community-api.coinmetrics.io/v4/timeseries/exchange-asset-metrics?exchange_assets=binance-btc&metrics=liquidations_reported_future_buy_usd_1d,liquidations_reported_future_sell_usd_1d&frequency=1d&page_size=10000",
 "cm_asset": "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=liquidations_reported_future_buy_usd_1d,liquidations_reported_future_sell_usd_1d&frequency=1d&page_size=10000",
 "cm_market": "https://community-api.coinmetrics.io/v4/timeseries/market-metrics?markets=binance-BTCUSDT-future&metrics=liquidations_reported_future_buy_usd_1d,liquidations_reported_future_sell_usd_1d&frequency=1d&page_size=10000",
 "cm_liq_raw": "https://community-api.coinmetrics.io/v4/timeseries/market-liquidations?markets=binance-BTCUSDT-future&page_size=100",
 "cm_catalog": "https://community-api.coinmetrics.io/v4/catalog-all/exchange-asset-metrics?metrics=liquidations_reported_future_buy_usd_1d",
 "coinglass_open": "https://open-api.coinglass.com/public/v2/liquidation_history?time_type=h1&symbol=BTC",
 "coinglass_v4": "https://open-api-v4.coinglass.com/api/futures/liquidation/aggregated-history?symbol=BTC&interval=1d",
 "cmc_data_api": "https://api.coinmarketcap.com/data-api/v3/derivatives/liquidation/chart?range=ALL",
}
out = {}
for k, u in pruebas.items():
    try:
        st, b = get(u); out[k] = {"status": st, "len": len(b), "inicio": b[:600].decode("utf-8", "replace")}
        if k.startswith("cm_") and st == 200:
            out[k]["datos"] = json.loads(b).get("data", [])[-3:] + json.loads(b).get("data", [])[:2]; out[k]["n"] = len(json.loads(b).get("data", []))
    except Exception as e:
        out[k] = {"error": f"{type(e).__name__} {str(e)[:200]}"}
json.dump(out, open(f"{sys.argv[1]}/liq_hist.json", "w"), indent=1)
