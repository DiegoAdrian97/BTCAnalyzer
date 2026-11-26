"""¿Lo que espera el mercado de la Fed anticipa a BTC? ¿A que plazo? (medir antes de sumar). Nov. 2026.

La idea (de Diego): si el mercado espera una suba de tasas, BTC cae antes; si espera una baja, sube antes; si hay
indecision, reacciona segun el resultado. Aca no se fija el plazo: se prueban todos, de 1 dia a 8 semanas, antes y despues.
- Decisiones programadas de la Fed 2015-2026 (calendario de TradingView; fuera las de emergencia de marzo de 2020).
- Lo esperado = la prevision del calendario contra la tasa anterior. Antes de 2022 el calendario no trae prevision: se
  toma lo que hizo (en reuniones programadas la Fed practicamente nunca sorprendio a los futuros la semana antes).
- BTC diario de CoinMetrics (PriceUSD, desde 2015). Antes: del cierre de k dias antes al del dia antes de la decision.
  Despues: del cierre del dia antes de la decision al de k dias despues (incluye la reaccion al anuncio).
- Contra lo normal del mismo tramo (todas las ventanas de k dias): retorno medio (z) y % de veces que subio.
- Dosis: correlacion entre el cambio esperado (puntos basicos, de -75 a +75) y el retorno, en cada plazo.
- Dos tramos: 2015-2021 y 2022-2026. SE REPITE: z >= 2 del mismo lado en los dos tramos.
Se hacen muchas pruebas: al azar, cada una pasa los dos tramos ~0,1% de las veces (se cuenta al final).
Uso: python medir_fed_plazos.py [corte desde]   (p. ej. 2024-01-01 2022-01-01: solo 2022-2026, partido en 2022-23 y 2024-26)
"""
import json
import sys
import math
import statistics
import urllib.request
from datetime import date, datetime, timedelta, timezone

import medir_fed

CAB = {"User-Agent": "analista-btc-medicion"}
CORTE = sys.argv[1] if len(sys.argv) > 1 else "2022-01-01"
DESDE = sys.argv[2] if len(sys.argv) > 2 else "2015-01-01"
PLAZOS = (1, 2, 3, 5, 7, 10, 14, 21, 28, 42, 56)
EMERGENCIA = ("2020-03-03", "2020-03-15", "2020-03-16")


def precios():
    out, u = {}, ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=PriceUSD"
                  "&frequency=1d&page_size=10000&start_time=2014-06-01")
    while u:
        j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=CAB), timeout=90).read())
        for r in j.get("data", []):
            if r.get("PriceUSD") not in (None, ""):
                out[r["time"][:10]] = float(r["PriceUSD"])
        u = j.get("next_page_url")
    return out


def rangos(xs):
    o = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and xs[o[j + 1]] == xs[o[i]]:
            j += 1
        for k in range(i, j + 1):
            r[o[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(x, y):
    if len(x) < 6 or len(set(x)) < 2:
        return None, None
    rx, ry = rangos(x), rangos(y)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx)); sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if not sx or not sy:
        return None, None
    r = sxy / (sx * sy)
    return r, r * math.sqrt(len(x) - 1)                       # z aproximado


def main():
    P = precios()
    dias = sorted(P)
    print(f"BTC diario: {dias[0]} a {dias[-1]} ({len(dias)} días)", flush=True)
    pos = {d: i for i, d in enumerate(dias)}
    c = [P[d] for d in dias]
    dec = medir_fed.decisiones(desde=datetime(2015, 1, 1, tzinfo=timezone.utc))
    print(f"{len(dec)} decisiones de la Fed en el calendario", flush=True)
    filas, salteadas, antes_hizo = [], {}, None
    for t, (act, fc, prev) in dec:
        dia = datetime.fromtimestamp(t / 1000, timezone.utc).date().isoformat()
        i = pos.get(dia)
        motivo = ("antes del tramo" if dia < DESDE else "sin precio" if i is None or i < 60 else "sin tasa anterior" if prev in (None, "") else
                  "de emergencia" if dia in EMERGENCIA else None)
        if motivo:
            salteadas[motivo] = salteadas.get(motivo, 0) + 1
            continue
        prev = float(prev)
        con_prev = fc not in (None, "")
        fc = float(fc) if con_prev else act
        cambio = round((fc - prev) * 100)
        esp = "baja" if cambio < 0 else "suba" if cambio > 0 else "mantener"
        hizo = "baja" if act < prev - 1e-9 else "suba" if act > prev + 1e-9 else "mantener"
        sorpresa = "no" if abs(act - fc) < 1e-9 else ("mas baja" if act < fc else "mas alta")
        giro = antes_hizo is not None and hizo != antes_hizo            # primera suba, primera baja o primera pausa
        antes_hizo = hizo
        p0 = c[i - 1]
        ant = {k: p0 / c[i - 1 - k] - 1 for k in PLAZOS}
        des = {k: c[i - 1 + k] / p0 - 1 for k in PLAZOS if i - 1 + k < len(c)}
        filas.append({"dia": dia, "esp": esp, "cambio": cambio, "hizo": hizo, "sorpresa": sorpresa, "giro": giro,
                      "con_prev": con_prev, "antes": ant, "despues": des, "tramo": 0 if dia < CORTE else 1})
    print("salteadas:", salteadas, "· usadas:", len(filas), flush=True)
    for tr in (0, 1):
        g = [f for f in filas if f["tramo"] == tr]
        print(f"  tramo {tr}: {len(g)} decisiones · se esperaba suba {sum(f['esp'] == 'suba' for f in g)}, baja "
              f"{sum(f['esp'] == 'baja' for f in g)}, mantener {sum(f['esp'] == 'mantener' for f in g)} · con previsión "
              f"{sum(f['con_prev'] for f in g)} · sorpresas {sum(f['sorpresa'] != 'no' for f in g)}")

    normales = {}

    def normal(tramo, k):
        if (tramo, k) not in normales:
            rs = [c[j] / c[j - k] - 1 for j in range(k, len(c)) if (dias[j] < CORTE) == (tramo == 0) and dias[j] >= DESDE]
            normales[(tramo, k)] = (sum(r > 0 for r in rs) / len(rs), statistics.mean(rs), statistics.pstdev(rs))
        return normales[(tramo, k)]

    pruebas, repetidas = 0, []

    def bloque(titulo, grupos, lado):
        nonlocal pruebas
        print(f"\n=== {titulo} ===")
        print(f"  {'grupo':<22} {'plazo':>6} | {'tramo 1 (hasta ' + CORTE + ')':^44} | {'tramo 2 (desde ' + CORTE + ')':^44} |")
        for nom, filt in grupos:
            for k in PLAZOS:
                txt, zs = f"  {nom:<22} {k:>4} d", []
                for tr in (0, 1):
                    rs = [f[lado][k] for f in filas if f["tramo"] == tr and filt(f) and k in f[lado]]
                    if len(rs) < 4:
                        txt += f" | {'pocos (' + str(len(rs)) + ')':^44}"; zs.append(None); continue
                    pb, mb, sd = normal(tr, k)
                    m = statistics.mean(rs)
                    z = (m - mb) / (sd / math.sqrt(len(rs)))
                    zs.append(z)
                    txt += f" | {len(rs):>2} · media {100 * m:+6.1f}% (normal {100 * mb:+5.1f}%) z {z:+4.1f} · subió {100 * sum(r > 0 for r in rs) / len(rs):3.0f}%"
                if all(z is not None for z in zs):
                    pruebas += 1
                ver = ("SE REPITE ▲" if all(z is not None and z >= 2 for z in zs) else
                       "SE REPITE ▼" if all(z is not None and z <= -2 for z in zs) else "")
                if ver:
                    repetidas.append((titulo, nom, k, zs))
                print(txt + f" | {ver}", flush=True)

    grupos = [("se esperaba suba", lambda f: f["esp"] == "suba"), ("se esperaba baja", lambda f: f["esp"] == "baja"),
              ("se esperaba mantener", lambda f: f["esp"] == "mantener"), ("todas", lambda f: True),
              ("cambio de rumbo", lambda f: f["giro"])]
    bloque("ANTES de la decisión (lo que hizo BTC los k días previos)", grupos, "antes")
    bloque("DESPUÉS (desde el día antes hasta k días después)", grupos + [
        ("sorpresa: más baja", lambda f: f["sorpresa"] == "mas baja"), ("sorpresa: más alta", lambda f: f["sorpresa"] == "mas alta")], "despues")

    print("\n=== DOSIS: más suba esperada, ¿peor para BTC? (Spearman entre el cambio esperado en pb y el retorno) ===")
    for lado in ("antes", "despues"):
        for k in PLAZOS:
            txt, zs = f"  {lado:<8} {k:>3} d", []
            for tr in (0, 1):
                g = [f for f in filas if f["tramo"] == tr and k in f[lado]]
                r, z = spearman([f["cambio"] for f in g], [f[lado][k] for f in g])
                zs.append(z)
                txt += f" | n {len(g):>2} · r {r:+.2f} (z {z:+.1f})" if r is not None else " | sin datos"
            if all(z is not None for z in zs):
                pruebas += 1
            ver = ("SE REPITE (más suba esperada = BTC mejor)" if all(z is not None and z >= 2 for z in zs) else
                   "SE REPITE (más suba esperada = BTC peor)" if all(z is not None and z <= -2 for z in zs) else "")
            if ver:
                repetidas.append(("dosis", lado, k, zs))
            print(txt + f" | {ver}", flush=True)

    print("\n=== cada decisión (cambio esperado y BTC 2 semanas antes / 2 semanas después) ===")
    for f in filas:
        print(f"  {f['dia']} esp {f['esp']:<8} ({f['cambio']:+d} pb{'' if f['con_prev'] else ', por lo que hizo'}) hizo {f['hizo']:<8}"
              f"{' GIRO' if f['giro'] else '     '} sorpresa {f['sorpresa']:<8} antes 14 d {100 * f['antes'][14]:+6.1f}%"
              + (f" · después 14 d {100 * f['despues'][14]:+6.1f}%" if 14 in f["despues"] else ""))

    print(f"\n=== RESUMEN: {pruebas} pruebas con los dos tramos; al azar pasarían ~{pruebas * 0.0011:.1f} ===")
    if not repetidas:
        print("  ninguna se repite en los dos tramos")
    for tit, nom, k, zs in repetidas:
        print(f"  {tit[:30]:<30} {nom:<22} {k:>3} d  z {zs[0]:+.1f} / {zs[1]:+.1f}")


if __name__ == "__main__":
    main()
