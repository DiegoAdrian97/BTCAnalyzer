"""¿Las bandas de desvio extremo del MVRV marcan los mejores puntos de compra y de venta? (medir antes de sumar)

MVRV = precio / precio realizado (el costo promedio de todos los BTC). Las "MVRV Extreme Deviation Pricing Bands"
(Checkonchain) dibujan precios: precio realizado x (media del MVRV + k desvios), con la media y el desvio de toda la
historia. Arriba de +1,5 a +2,5 desvios: zona de venta; debajo de -0,5 a -1: zona de compra.

Aca, con CoinMetrics (gratis, diario desde 2010):
  1. Cada vez que el precio entra a una banda extrema (episodios separados por 90 dias), que paso despues: rendimiento
     a 30, 90, 180 y 365 dias, y que tan cerca estuvo del maximo (o minimo) del ciclo.
  2. Lo mismo con la media y el desvio "hasta ese dia" (sin mirar el futuro: lo que se podia saber en el momento) y
     con los de toda la historia (como el grafico que se ve en internet, que ya sabe como terminaron los ciclos).
  3. Comparado con un dia cualquiera: % de veces que BTC subio a 365 dias.
Uso: python medir_mvrv_bandas.py
"""
import json, math, urllib.request
from datetime import date, timedelta

CAB = {"User-Agent": "analista-btc-medicion"}


def serie(met):
    out, u = {}, (f"https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics={met}"
                  f"&frequency=1d&page_size=10000&start_time=2010-07-01")
    while u:
        j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=CAB), timeout=90).read())
        for r in j.get("data", []):
            if r.get(met) not in (None, ""):
                out[r["time"][:10]] = float(r[met])
        u = j.get("next_page_url")
    return out


def main():
    mv, px = serie("CapMVRVCur"), serie("PriceUSD")
    dias = sorted(d for d in mv if d in px and d >= "2011-01-01")
    M = [mv[d] for d in dias]
    P = [px[d] for d in dias]
    n = len(dias)
    print(f"{n} días: {dias[0]} a {dias[-1]}")
    # media y desvio: de toda la historia y "hasta ese dia" (expansivo, con al menos 2 años)
    mu_t = sum(M) / n
    sd_t = math.sqrt(sum((x - mu_t) ** 2 for x in M) / n)
    mu_e, sd_e, s, s2 = [], [], 0.0, 0.0
    for k, x in enumerate(M):
        s += x; s2 += x * x
        m = s / (k + 1)
        mu_e.append(m); sd_e.append(math.sqrt(max(0.0, s2 / (k + 1) - m * m)))
    print(f"MVRV de toda la historia: media {mu_t:.2f}, desvío {sd_t:.2f}  →  bandas: "
          + ", ".join(f"{k:+}σ = MVRV {mu_t + k * sd_t:.2f}" for k in (-1, -0.5, 0.5, 1, 1.5, 2, 2.5, 3)))
    hoy = M[-1]
    print(f"hoy ({dias[-1]}): MVRV {hoy:.2f} = {(hoy - mu_t) / sd_t:+.2f}σ (toda la historia) / {(hoy - mu_e[-1]) / sd_e[-1]:+.2f}σ (hasta hoy); "
          f"precio realizado {P[-1] / hoy:,.0f}; banda +2σ {P[-1] / hoy * (mu_t + 2 * sd_t):,.0f}; banda -0,5σ {P[-1] / hoy * (mu_t - 0.5 * sd_t):,.0f}")

    def ret(i, h):
        return P[i + h] / P[i] - 1 if i + h < n else None

    base = [ret(i, 365) for i in range(730, n) if ret(i, 365) is not None]
    print(f"\nUn día cualquiera (desde 2013): subió a 365 días el {100 * sum(r > 0 for r in base) / len(base):.0f}% "
          f"(mediana {100 * sorted(base)[len(base) // 2]:+.0f}%)")

    for modo in ("hasta ese día (sin mirar el futuro)", "toda la historia (como el gráfico de internet)"):
        print(f"\n===== media y desvío: {modo} =====")
        for k, lado in ((1.5, "venta"), (2.0, "venta"), (2.5, "venta"), (3.0, "venta"), (-0.5, "compra"), (-1.0, "compra")):
            eps, ult = [], -10**9
            for i in range(730, n):        # 2 años de historia para la media
                mu, sd = (mu_e[i], sd_e[i]) if modo.startswith("hasta") else (mu_t, sd_t)
                z = (M[i] - mu) / sd
                dentro = z >= k if lado == "venta" else z <= k
                if dentro:
                    if i - ult > 90:
                        eps.append(i)
                    ult = i
            print(f"\n  {lado} en {k:+}σ: {len(eps)} episodios")
            for i in eps:
                lo, hi = max(0, i - 365), min(n, i + 366)
                ext = max(P[lo:hi]) if lado == "venta" else min(P[lo:hi])
                cerca = P[i] / ext - 1
                r = [ret(i, h) for h in (30, 90, 180, 365)]
                fut = P[i:min(n, i + 366)]
                peor = (min(fut) / P[i] - 1) if lado == "venta" else (max(fut) / P[i] - 1)
                print(f"    {dias[i]}  precio {P[i]:>9,.0f}  "
                      + "  ".join(f"{h}d {'—' if x is None else f'{100 * x:+5.0f}%'}" for h, x in zip((30, 90, 180, 365), r))
                      + f"  | {'del máximo' if lado == 'venta' else 'del mínimo'} del ciclo (±1 año): {100 * cerca:+.0f}%"
                      + f"  | {'caída' if lado == 'venta' else 'suba'} máx. en 1 año: {100 * peor:+.0f}%")
            # cada dia dentro de la zona (no solo el primero): ¿cuanto subio a 365 dias?
            zona = []
            for i in range(730, n - 365):
                mu, sd = (mu_e[i], sd_e[i]) if modo.startswith("hasta") else (mu_t, sd_t)
                z = (M[i] - mu) / sd
                if (z >= k if lado == "venta" else z <= k):
                    zona.append(ret(i, 365))
            if zona:
                print(f"    días dentro de la zona: {len(zona)} · subió a 365 días el {100 * sum(r > 0 for r in zona) / len(zona):.0f}% "
                      f"(mediana {100 * sorted(zona)[len(zona) // 2]:+.0f}%)")


if __name__ == "__main__":
    main()
