"""Baja historia de noticias (GDELT: tono y cantidad de notas) y el calendario economico de EE.UU. (alta
importancia) desde fines de 2020, para medir si ayudan a predecir a BTC. Corre en GitHub Actions.

python medir/bajar.py medir/datos [prueba]
"""
import csv, json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
T0 = datetime(2020, 12, 1, tzinfo=timezone.utc)
QUERIES = {"btc": "bitcoin", "guerra": '(war OR missile OR airstrike OR invasion OR "military strike")',
           "fed": '("Federal Reserve" OR "interest rates" OR inflation)'}


def get(url, data=None, headers=None, tries=6, espera=6):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            print("  reintento", k, type(e).__name__, str(e)[:120], flush=True)
            time.sleep(espera * (k + 1))
    return None


def gdelt(q, mode, a, b):
    u = "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode({
        "query": q, "mode": mode, "format": "json", "startdatetime": a.strftime("%Y%m%d%H%M%S"),
        "enddatetime": b.strftime("%Y%m%d%H%M%S")})
    txt = get(u)
    time.sleep(5.5)                      # GDELT pide no mas de un pedido cada 5 segundos
    if not txt:
        return []
    try:
        j = json.loads(txt)
    except json.JSONDecodeError:
        print("  no json:", txt[:150], flush=True)
        return []
    return [(p["date"], p.get("value"), p.get("norm")) for s in j.get("timeline", []) for p in s.get("data", [])]


def bajar_gdelt(out, t1, dias=7):
    for key, q in QUERIES.items():
        for mode in ("timelinetone", "timelinevolraw"):
            path = os.path.join(out, f"gdelt_{key}_{mode}.csv")
            if os.path.exists(path):
                continue
            rows, a = [], T0
            while a < t1:
                b = min(t1, a + timedelta(days=dias))
                pts = gdelt(q, mode, a, b)
                rows += pts
                print(key, mode, a.date(), len(pts), flush=True)
                a = b
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["fecha", "valor", "norm"])
                w.writerows(rows)


def tradingview(a, b):
    u = "https://economic-calendar.tradingview.com/events?" + urllib.parse.urlencode({
        "from": a.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "to": b.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "countries": "US"})
    txt = get(u, headers={"Origin": "https://www.tradingview.com", "Referer": "https://www.tradingview.com/"}, tries=3)
    if not txt:
        return None
    try:
        return [{"fecha": e.get("date"), "titulo": e.get("title"), "importancia": e.get("importance"),
                 "actual": e.get("actual"), "previsto": e.get("forecast"), "anterior": e.get("previous")}
                for e in json.loads(txt).get("result", [])]
    except json.JSONDecodeError:
        print("  tv no json", txt[:150])
        return None


def bajar_calendario(out, t1):
    cal, a = [], T0
    while a < t1:
        b = min(t1, a + timedelta(days=30))
        ev = tradingview(a, b) or []
        cal += ev
        print("calendario", a.date(), len(ev), flush=True)
        a = b
        time.sleep(1)
    with open(os.path.join(out, "calendario_tv.json"), "w") as f:
        json.dump(cal, f)


def investing(desde, hasta):
    return get("https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",
               data=urllib.parse.urlencode([("country[]", "5"), ("importance[]", "3"), ("dateFrom", desde), ("dateTo", hasta),
                                            ("timeZone", "0"), ("timeFilter", "timeOnly"), ("currentTab", "custom"),
                                            ("limit_from", "0")]).encode(),
               headers={"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/x-www-form-urlencoded",
                        "Referer": "https://www.investing.com/economic-calendar/"}, tries=2)


def prueba(out):
    """Una muestra de cada fuente, para ver que devuelve y con que resolucion."""
    res = {}
    for ini, dias in ((datetime(2021, 3, 1, tzinfo=timezone.utc), 7), (datetime(2025, 3, 1, tzinfo=timezone.utc), 7),
                      (datetime(2025, 3, 1, tzinfo=timezone.utc), 30)):
        for mode in ("timelinetone", "timelinevolraw"):
            pts = gdelt(QUERIES["btc"], mode, ini, ini + timedelta(days=dias))
            res[f"{mode} {ini.date()} {dias}d"] = {"n": len(pts), "primeros": pts[:3], "ultimos": pts[-2:]}
    tv = tradingview(datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 1, 31, tzinfo=timezone.utc))
    res["tradingview 2024-01"] = {"n": None if tv is None else len(tv), "muestra": (tv or [])[:4]}
    inv = investing("2024-01-01", "2024-01-31")
    res["investing 2024-01"] = (inv or "SIN RESPUESTA")[:600]
    with open(os.path.join(out, "prueba.json"), "w") as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1)[:3000])


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "datos"
    os.makedirs(out, exist_ok=True)
    if len(sys.argv) > 2 and sys.argv[2] == "prueba":
        prueba(out)
    else:
        t1 = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        bajar_calendario(out, t1)
        bajar_gdelt(out, t1)
        print("listo", flush=True)
