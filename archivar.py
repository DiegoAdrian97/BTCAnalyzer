"""Archivo de datos que no tienen historia gratis, para poder medirlos en unos meses (nov. 2026).

Cada 4 horas (GitHub Actions, .github/workflows/archivar.yml) guarda en la rama 'archivo':
  archivo/opciones/<moneda>/<dia>.csv   t, vencimiento, strike, tipo, open interest, IV de marca, precio de marca, subyacente
                                        (toda la cadena de opciones de Deribit: de ahi salen skew, max pain, gamma)
  archivo/perp/<dia>.csv                t, exchange, moneda, precio, funding, open interest, volumen 24 h
                                        (Hyperliquid, OKX y Bybit: funding y open interest por exchange)
Cada fuente que falla se saltea (queda anotado en la salida). No usa claves: todo es publico.
Uso: python archivar.py <carpeta de la rama archivo>
"""
import json
import os
import sys
import time
import urllib.request

MONEDAS = ("BTC", "ETH", "SOL", "XRP", "ZEC")
CAB = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}


def pedir(url, cuerpo=None):
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode() if cuerpo else None, headers=CAB)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def agregar(ruta, cabecera, lineas):
    if not lineas:
        return
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    nuevo = not os.path.exists(ruta)
    with open(ruta, "a", encoding="utf-8") as f:
        if nuevo:
            f.write(cabecera + "\n")
        f.write("\n".join(lineas) + "\n")


def g(x):
    return "" if x is None else f"{float(x):.10g}"


def main(base):
    t = int(time.time() // 60 * 60)
    dia = time.strftime("%Y-%m-%d", time.gmtime(t))
    for m in ("BTC", "ETH"):
        try:
            res = pedir(f"https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency={m}&kind=option")["result"]
            L = []
            for x in res:
                p = x["instrument_name"].split("-")          # BTC-27DEC26-100000-C
                if len(p) == 4 and (x.get("open_interest") or 0) > 0:
                    L.append(",".join([str(t), p[1], p[2], p[3], g(x.get("open_interest")), g(x.get("mark_iv")), g(x.get("mark_price")), g(x.get("underlying_price"))]))
            agregar(f"{base}/archivo/opciones/{m}/{dia}.csv", "t,vencimiento,strike,tipo,oi,iv,marca,subyacente", L)
            print(f"opciones {m}: {len(L)}")
        except Exception as e:
            print(f"(opciones {m}: {type(e).__name__}: {e})")
    P = []
    try:
        meta, ctx = pedir("https://api.hyperliquid.xyz/info", {"type": "metaAndAssetCtxs"})
        for u, c in zip(meta["universe"], ctx):
            if u["name"] in MONEDAS:
                P.append(",".join([str(t), "hyperliquid", u["name"], g(c.get("markPx")), g(c.get("funding")), g(float(c["openInterest"]) * float(c["markPx"])), g(c.get("dayNtlVlm"))]))
    except Exception as e:
        print(f"(hyperliquid: {type(e).__name__}: {e})")
    for m in MONEDAS:
        try:
            i = f"{m}-USDT-SWAP"
            oi = pedir(f"https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId={i}")["data"][0]
            fr = pedir(f"https://www.okx.com/api/v5/public/funding-rate?instId={i}")["data"][0]
            tk = pedir(f"https://www.okx.com/api/v5/market/ticker?instId={i}")["data"][0]
            P.append(",".join([str(t), "okx", m, g(tk.get("last")), g(fr.get("fundingRate")), g(oi.get("oiUsd")), g(tk.get("volCcy24h"))]))
        except Exception as e:
            print(f"(okx {m}: {type(e).__name__}: {e})")
        try:
            x = pedir(f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={m}USDT")["result"]["list"][0]
            P.append(",".join([str(t), "bybit", m, g(x.get("lastPrice")), g(x.get("fundingRate")), g(x.get("openInterestValue")), g(x.get("turnover24h"))]))
        except Exception as e:
            print(f"(bybit {m}: {type(e).__name__}: {e})")
    agregar(f"{base}/archivo/perp/{dia}.csv", "t,exchange,moneda,precio,funding,oi_usd,volumen_24h", P)
    print(f"perp: {len(P)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
