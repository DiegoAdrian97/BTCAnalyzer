"""Baja historia de noticias (GDELT: tono y cantidad de notas por hora) y el calendario economico de EE.UU.
(alta importancia) desde 2021, para medir si ayudan a predecir a BTC. Corre en GitHub Actions."""
import csv, json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

OUT = sys.argv[1] if len(sys.argv) > 1 else "datos"
os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
T0 = datetime(2020, 12, 1, tzinfo=timezone.utc)
T1 = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


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


# ---------- GDELT: tono promedio y cantidad de notas, por tramos de 7 dias ----------
QUERIES = {"btc": "bitcoin", "guerra": '(war OR missile OR airstrike OR invasion OR "military strike")',
           "fed": '("Federal Reserve" OR "interest rates" OR inflation)'}
def gdelt(q, mode, a, b):
    u = ("https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode({
        "query": q, "mode": mode, "format": "json", "startdatetime": a.strftime("%Y%m%d%H%M%S"),
        "enddatetime": b.strftime("%Y%m%d%H%M%S")}))
    txt = get(u)
    time.sleep(5.5)
    if not txt:
        return []
    try:
        j = json.loads(txt)
    except json.JSONDecodeError:
        print("  no json:", txt[:150], flush=True)
        return []
    out = []
    for serie in j.get("timeline", []):
        for p in serie.get("data", []):
            out.append((p["date"], p.get("value"), p.get("norm")))
    return out

for key, q in QUERIES.items():
    for mode in ("timelinetone", "timelinevolraw"):
        path = os.path.join(OUT, f"gdelt_{key}_{mode}.csv")
        if os.path.exists(path):
            continue
        rows, a = [], T0
        while a < T1:
            b = min(T1, a + timedelta(days=7))
            pts = gdelt(q, mode, a, b)
            rows += pts
            print(key, mode, a.date(), len(pts), flush=True)
            a = b
        with open(path, "w", newline="") as f:
            w = csv.writer(f); w.writerow(["fecha", "valor", "norm"]); w.writerows(rows)

# ---------- calendario economico de EE.UU., alta importancia ----------
# TradingView (JSON publico) y, si responde, Investing.com
cal, a = [], T0
while a < T1:
    b = min(T1, a + timedelta(days=30))
    u = ("https://economic-calendar.tradingview.com/events?" + urllib.parse.urlencode({
        "from": a.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "to": b.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "countries": "US"}))
    txt = get(u, headers={"Origin": "https://www.tradingview.com", "Referer": "https://www.tradingview.com/"}, tries=3)
    n = 0
    if txt:
        try:
            for e in json.loads(txt).get("result", []):
                cal.append({"fuente": "tradingview", "fecha": e.get("date"), "titulo": e.get("title"), "importancia": e.get("importance"),
                            "actual": e.get("actual"), "previsto": e.get("forecast"), "anterior": e.get("previous")})
                n += 1
        except json.JSONDecodeError:
            print("  tv no json", txt[:150])
    print("calendario tv", a.date(), n, flush=True)
    a = b
    time.sleep(1)
with open(os.path.join(OUT, "calendario_tv.json"), "w") as f:
    json.dump(cal, f)

inv = get("https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",
          data=urllib.parse.urlencode([("country[]", "5"), ("importance[]", "3"), ("dateFrom", "2024-01-01"), ("dateTo", "2024-01-31"),
                                       ("timeZone", "0"), ("timeFilter", "timeOnly"), ("currentTab", "custom"), ("limit_from", "0")]).encode(),
          headers={"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/x-www-form-urlencoded",
                   "Referer": "https://www.investing.com/economic-calendar/"}, tries=2)
with open(os.path.join(OUT, "investing_prueba.txt"), "w") as f:
    f.write((inv or "SIN RESPUESTA")[:3000])
print("listo", flush=True)
