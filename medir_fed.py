"""¿La decision de tasa de la Fed mejora el analisis? (medir antes de sumar)

Todas las decisiones de tasa de la Fed 2021-2026 (calendario de TradingView: dato real, previsto y anterior) y BTC
(velas de 1 hora) despues del anuncio:
- Fuerza: ¿cuanto se movio en 1, 4 y 24 h contra lo normal de esa hora? (para la seccion "movimiento fuerte")
- Direccion: segun lo que hizo (bajo, subio o mantuvo la tasa) y segun la sorpresa (contra lo previsto), ¿subio o bajo
  en 1, 24 y 72 h? (lo que hoy dice la app: "mas baja: bueno para BTC; mas alta: malo")
Uso: python medir_fed.py velas_1h.json
"""
import json, statistics, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
H = 3_600_000


def decisiones():
    out, a = {}, datetime(2020, 12, 1, tzinfo=timezone.utc)
    fin = datetime.now(timezone.utc)
    while a < fin:
        b = min(fin, a + timedelta(days=30))
        u = ("https://economic-calendar.tradingview.com/events?from=" + a.strftime("%Y-%m-%dT%H:%M:%S.000Z") +
             "&to=" + b.strftime("%Y-%m-%dT%H:%M:%S.000Z") + "&countries=US")
        req = urllib.request.Request(u, headers={"User-Agent": UA, "Origin": "https://www.tradingview.com", "Referer": "https://www.tradingview.com/"})
        for k in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    for e in json.loads(r.read().decode("utf-8", "replace")).get("result", []):
                        t = (e.get("title") or "")
                        if "interest rate decision" in t.lower() and e.get("actual") is not None:
                            ms = int(datetime.fromisoformat(e["date"].replace("Z", "+00:00")).timestamp() * 1000)
                            out[ms] = (float(e["actual"]), e.get("forecast"), e.get("previous"))
                break
            except Exception:
                time.sleep(5)
        a = b
        time.sleep(1)
    return sorted(out.items())


def main():
    B = json.load(open(sys.argv[1]))
    idx = {b[0]: i for i, b in enumerate(B)}
    D = decisiones()
    print(f"{len(D)} decisiones de la Fed con dato")
    filas = []
    for t, (act, fc, prev) in D:
        i = idx.get(t // H * H)
        if i is None or i < 24 * 60 or i + 73 >= len(B):
            continue
        p0 = B[i][1]
        r = {h: B[i + h - 1][4] / p0 - 1 for h in (1, 4, 24, 72)}
        # movimiento de la hora del anuncio contra la mediana de la misma hora de los 60 dias anteriores
        mov = (B[i][2] - B[i][3]) / p0
        normal = statistics.median((B[i - 24 * k][2] - B[i - 24 * k][3]) / B[i - 24 * k][1] for k in range(1, 61))
        mov24 = (max(b[2] for b in B[i:i + 24]) - min(b[3] for b in B[i:i + 24])) / p0
        normal24 = statistics.median((max(b[2] for b in B[i - 24 * k:i - 24 * k + 24]) - min(b[3] for b in B[i - 24 * k:i - 24 * k + 24])) / B[i - 24 * k][1] for k in range(1, 61))
        hizo = "bajó" if prev is not None and act < float(prev) else "subió" if prev is not None and act > float(prev) else "mantuvo"
        sorpresa = "como se esperaba" if fc is None or abs(act - float(fc)) < 1e-9 else ("más baja" if act < float(fc) else "más alta")
        filas.append((t, hizo, sorpresa, r, mov / normal if normal else None, mov24 / normal24 if normal24 else None))
        print(f"  {datetime.fromtimestamp(t / 1000, timezone.utc):%Y-%m-%d} {hizo:<8} {sorpresa:<17} 1 h {100 * r[1]:+.1f}% · 24 h {100 * r[24]:+.1f}% · 72 h {100 * r[72]:+.1f}% · hora ×{mov / normal:.1f} · 24 h ×{mov24 / normal24:.1f}")
    print("\nFUERZA: la hora del anuncio y las 24 h siguientes contra lo normal (mediana de los 60 dias anteriores)")
    xs = [f[4] for f in filas if f[4]]; ys = [f[5] for f in filas if f[5]]
    print(f"  hora del anuncio: mediana ×{statistics.median(xs):.2f} · más del doble {100 * sum(x > 2 for x in xs) / len(xs):.0f}% ({len(xs)} decisiones)")
    print(f"  24 h siguientes: mediana ×{statistics.median(ys):.2f} · más del doble {100 * sum(y > 2 for y in ys) / len(ys):.0f}%")
    print("\nDIRECCION: % de veces que BTC subio despues")
    for clave, k in (("hizo", 1), ("sorpresa", 2)):
        grupos = {}
        for f in filas:
            grupos.setdefault(f[k], []).append(f[3])
        for g, rs in sorted(grupos.items()):
            print(f"  {clave} {g:<17} {len(rs):>3} veces · subió en 1 h {100 * sum(r[1] > 0 for r in rs) / len(rs):.0f}% · 24 h {100 * sum(r[24] > 0 for r in rs) / len(rs):.0f}% · 72 h {100 * sum(r[72] > 0 for r in rs) / len(rs):.0f}% · media 72 h {100 * statistics.mean(r[72] for r in rs):+.1f}%")


if __name__ == "__main__":
    main()
