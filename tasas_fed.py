"""Lo que espera el mercado de la Fed (como el FedWatch de CME), con datos gratis. Nov. 2026.

FedWatch sale de los futuros de Fed Funds a 30 dias (CBOT, "ZQ"): cada contrato paga 100 menos la tasa efectiva (EFFR)
promedio de su mes. En el mes de una reunion ese promedio mezcla la tasa de antes (hasta el dia de la decision) y la de
despues, asi que se despeja la tasa que el mercado espera despues de la reunion:
    despues = (promedio del mes - d/N * antes) / ((N - d)/N)          d = dia de la decision, N = dias del mes
Si el mes siguiente no tiene reunion, su contrato ya es la tasa de despues (mas preciso). La diferencia con la tasa de
hoy, en pasos de 0,25, da las probabilidades (p. ej. -0,06 = 24% de bajar 0,25 y 76% de mantener). Igual que CME.
Fuentes: precios de los contratos en Yahoo Finance (ZQZ26.CBT...) y la EFFR del dia en la Fed de Nueva York.
"""
import calendar
import json
import urllib.request
from datetime import date, datetime, timezone

# Decisiones de tasa (segundo dia de cada reunion), de federalreserve.gov/monetarypolicy/fomccalendars.htm.
# 2027: fechas tentativas hasta que cada reunion confirma la siguiente. Hay que agregar las de 2028 a fin de 2027.
REUNIONES = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
             "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15", "2027-10-27", "2027-11-17"]
LETRA = "FGHJKMNQUVXZ"                     # meses de los futuros: F = enero ... Z = diciembre
PASO = 0.25


def ticker(y, m):
    return f"ZQ{LETRA[m - 1]}{y % 100:02d}.CBT"


def _mes_sig(y, m):
    return (y + 1, 1) if m == 12 else (y, m + 1)


def proximas(hoy, n=2):
    """Las proximas n decisiones (date) desde hoy (date), incluida la de hoy."""
    return [d for d in (date.fromisoformat(x) for x in REUNIONES) if d >= hoy][:n]


def contratos(hoy, n=2):
    """Tickers que hacen falta para las proximas n reuniones: el del mes de cada una y el del mes siguiente."""
    out = []
    for d in proximas(hoy, n):
        for ym in ((d.year, d.month), _mes_sig(d.year, d.month)):
            t = ticker(*ym)
            if t not in out:
                out.append(t)
    return out


def probabilidades(effr, precios, hoy, n=2):
    """effr: tasa efectiva de hoy (%). precios: {ticker: precio del futuro}. Devuelve una lista (una por reunion) con la
    tasa que espera el mercado despues, el cambio en puntos basicos y las probabilidades de cada resultado.
    Para la segunda reunion, el cambio es contra la tasa esperada despues de la primera (acumulado aparte)."""
    meses_con = {(d.year, d.month) for d in (date.fromisoformat(x) for x in REUNIONES)}
    antes, out = effr, []
    for d in proximas(hoy, n):
        N = calendar.monthrange(d.year, d.month)[1]
        sig = _mes_sig(d.year, d.month)
        p_mes, p_sig = precios.get(ticker(d.year, d.month)), precios.get(ticker(*sig))
        if sig not in meses_con and p_sig:
            despues = 100 - p_sig
        elif p_mes and d.day < N:
            despues = (100 - p_mes - d.day / N * antes) / ((N - d.day) / N)
        else:
            break
        cambio = despues - antes
        k = abs(cambio) / PASO
        piso, frac = int(k), k - int(k)
        signo = -1 if cambio < 0 else 1
        prob = {}
        for pasos, pr in ((piso, 1 - frac), (piso + 1, frac)):
            if pr < 0.005:
                continue
            clave = 0 if pasos == 0 else signo * pasos * 25          # en puntos basicos: -25 = baja 0,25
            prob[clave] = prob.get(clave, 0) + pr
        out.append({"fecha": d.isoformat(), "dias": (d - hoy).days, "antes": round(antes, 3), "despues": round(despues, 3),
                    "cambio_pb": round(cambio * 100, 1), "prob": {k: round(v, 3) for k, v in sorted(prob.items())},
                    "acumulado_pb": round((despues - effr) * 100, 1)})
        antes = despues
    return out


CAB = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
       "Accept": "application/json"}


def _json(url, timeout=15):
    with urllib.request.urlopen(urllib.request.Request(url, headers=CAB), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def effr_hoy():
    """(tasa efectiva %, piso del rango, techo del rango, fecha) de la Fed de Nueva York."""
    r = _json("https://markets.newyorkfed.org/api/rates/unsecured/effr/last/1.json")["refRates"][0]
    return float(r["percentRate"]), float(r["targetRateFrom"]), float(r["targetRateTo"]), r["effectiveDate"]


def _tv(tk):
    """ZQZ26.CBT -> CBOT:ZQZ2026 (como lo nombra TradingView)."""
    return f"CBOT:{tk[:3]}20{tk[3:5]}"


def precios_tradingview(tks):
    """Precios de varios contratos de una vez en el buscador de TradingView (el mismo sitio del calendario economico)."""
    cuerpo = json.dumps({"symbols": {"tickers": [_tv(t) for t in tks]}, "columns": ["close"]}).encode()
    req = urllib.request.Request("https://scanner.tradingview.com/futures/scan", data=cuerpo,
                                 headers={**CAB, "Content-Type": "application/json", "Origin": "https://www.tradingview.com",
                                          "Referer": "https://www.tradingview.com/"})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    por = {x["s"]: x["d"][0] for x in d.get("data", []) if x.get("d") and x["d"][0] is not None}
    return {t: float(por[_tv(t)]) for t in tks if _tv(t) in por}


def precio_futuro(tk):
    m = _json(f"https://query2.finance.yahoo.com/v8/finance/chart/{tk}?interval=1d&range=5d")["chart"]["result"][0]["meta"]
    return float(m["regularMarketPrice"])


def precios(tks):
    """TradingView primero; lo que falte, de Yahoo."""
    out = {}
    try:
        out = precios_tradingview(tks)
    except Exception:
        pass
    for tk in tks:
        if tk not in out:
            try:
                out[tk] = precio_futuro(tk)
            except Exception:
                pass
    return out


def traer(hoy=None, n=2):
    """Lo que espera el mercado para las proximas n reuniones, con datos de hoy. None si falta algo."""
    hoy = hoy or datetime.now(timezone.utc).date()
    effr, desde, hasta, fecha = effr_hoy()
    ps = precios(contratos(hoy, n))
    r = probabilidades(effr, ps, hoy, n)
    return {"effr": effr, "rango": [desde, hasta], "effr_fecha": fecha, "precios": ps, "reuniones": r} if r else None


if __name__ == "__main__":
    print(json.dumps(traer(), indent=1))
