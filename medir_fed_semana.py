"""¿BTC se mueve las semanas ANTES de la Fed segun lo que espera el mercado? (medir antes de sumar). Nov. 2026.

La idea (de Diego): cuando el mercado espera una suba de tasas, BTC cae unas semanas antes; cuando espera una baja, sube
unas semanas antes; cuando hay indecision, reacciona segun el resultado.
Lo esperado = la prevision del calendario de TradingView contra la tasa anterior (prevision mas baja = se esperaba una
baja). Antes de 2022 el calendario no trae prevision: ahi se toma lo que hizo, porque en reuniones programadas la Fed
practicamente nunca sorprendio a los futuros (FedWatch daba 90%+ a lo que hizo la semana antes). Fuera las de
emergencia (marzo de 2020), que nadie esperaba.
BTC en velas diarias de Binance spot (2017-2026). Para cada decision: cuanto subio o bajo en las 1, 2, 3 y 4 semanas
anteriores (hasta el cierre del dia antes de la decision) y en la semana siguiente. Contra lo normal del mismo tramo
(todas las ventanas del mismo largo): % de veces que subio y retorno medio. Dos tramos: hasta 2021 y 2022-2026.
A FAVOR de la idea: z >= 2 del lado esperado en los dos tramos.
Ademas prueba las fuentes en vivo (futuros de Fed Funds en Yahoo y la EFFR de la Fed de Nueva York).
Uso: python medir_fed_semana.py
"""
import math
import statistics
from datetime import datetime, timezone

import medir_fed
import medir_largos as ml
import tasas_fed

DIA = 86_400_000
SEMANAS = (1, 2, 3, 4)


def z_prop(k, n, p):
    return (k - n * p) / math.sqrt(max(1e-9, n * p * (1 - p)))


def main():
    D = ml.diarias()
    print(f"{len(D)} velas diarias de BTC", flush=True)
    idx = {b[0] // DIA: i for i, b in enumerate(D)}
    c = [b[4] for b in D]
    dec = medir_fed.decisiones(desde=datetime(2016, 12, 1, tzinfo=timezone.utc))
    print(f"{len(dec)} decisiones de la Fed con dato", flush=True)
    filas, salteadas = [], {}
    for t, (act, fc, prev) in dec:
        i = idx.get(t // DIA)
        dia = datetime.fromtimestamp(t / 1000, timezone.utc).date().isoformat()
        motivo = ("sin velas" if i is None or i < 30 else "sin tasa anterior" if prev in (None, "") else
                  "de emergencia" if dia in ("2020-03-03", "2020-03-15", "2020-03-16") else None)
        if motivo:
            salteadas[motivo] = salteadas.get(motivo, 0) + 1
            continue
        prev = float(prev)
        fc = float(fc) if fc not in (None, "") else act
        esp = "baja" if fc < prev - 1e-9 else "suba" if fc > prev + 1e-9 else "mantener"
        hizo = "baja" if act < prev - 1e-9 else "suba" if act > prev + 1e-9 else "mantener"
        sorpresa = "no" if abs(act - fc) < 1e-9 else ("mas baja" if act < fc else "mas alta")
        p0 = c[i - 1]                                                    # cierre del dia antes de la decision
        antes = {s: p0 / c[i - 1 - 7 * s] - 1 for s in SEMANAS}
        despues = c[i + 6] / p0 - 1 if i + 6 < len(c) else None          # la semana desde la decision
        tramo = 0 if t < ml.CORTE else 1
        filas.append((t, esp, hizo, sorpresa, antes, despues, tramo))
        print(f"  {datetime.fromtimestamp(t / 1000, timezone.utc):%Y-%m-%d} se esperaba {esp:<8} hizo {hizo:<8} sorpresa {sorpresa:<8} "
              + " · ".join(f"{s} sem antes {100 * antes[s]:+.1f}%" for s in SEMANAS)
              + (f" · semana después {100 * despues:+.1f}%" if despues is not None else ""), flush=True)

    print("salteadas:", salteadas, "· usadas:", len(filas), flush=True)

    def normal(tramo, dias):
        rs = [c[j] / c[j - dias] - 1 for j in range(dias, len(c)) if (D[j][0] < ml.CORTE) == (tramo == 0)]
        return sum(r > 0 for r in rs) / len(rs), statistics.mean(rs), statistics.pstdev(rs)

    print("\n=== ANTES de la decision, segun lo que se esperaba (sube = % de veces que subio) ===")
    res = []
    for esp, lado in (("suba", -1), ("baja", 1), ("mantener", 0)):
        for s in SEMANAS:
            txt, zs = f"  se esperaba {esp:<8} {s} sem", []
            for tramo in (0, 1):
                rs = [f[4][s] for f in filas if f[1] == esp and f[6] == tramo]
                if len(rs) < 3:
                    txt += f" | pocos ({len(rs)})"; zs.append(None); continue
                pb, mb, sd = normal(tramo, 7 * s)
                k = sum(r > 0 for r in rs)
                zp = z_prop(k, len(rs), pb)
                zm = (statistics.mean(rs) - mb) / (sd / math.sqrt(len(rs)))
                zs.append(zm)
                txt += (f" | {len(rs):>2} veces · subió {100 * k / len(rs):3.0f}% (normal {100 * pb:3.0f}%, z {zp:+.1f})"
                        f" · media {100 * statistics.mean(rs):+5.1f}% (normal {100 * mb:+4.1f}%, z {zm:+.1f})")
            ver = "~"
            if lado and all(z is not None and z * lado >= 2 for z in zs):
                ver = "A FAVOR de la idea"
            elif lado and all(z is not None and z * lado <= -2 for z in zs):
                ver = "AL REVES de la idea"
            print(txt + f"  → {ver}", flush=True)
            res.append((esp, s, ver, zs))

    print("\n=== la semana DESPUES, segun la sorpresa (contra lo previsto) ===")
    for sor in ("mas baja", "no", "mas alta"):
        for tramo in (0, 1):
            rs = [f[5] for f in filas if f[3] == sor and f[6] == tramo and f[5] is not None]
            if not rs:
                continue
            pb, mb, sd = normal(tramo, 7)
            print(f"  sorpresa {sor:<8} tramo {tramo}: {len(rs):>2} veces · subió {100 * sum(r > 0 for r in rs) / len(rs):3.0f}% "
                  f"(normal {100 * pb:3.0f}%) · media {100 * statistics.mean(rs):+5.1f}% (normal {100 * mb:+4.1f}%)")

    print("\n=== resumen ===")
    for esp, s, ver, zs in res:
        print(f"  {esp:<8} {s} sem antes: {ver:<20} z de la media {' / '.join('—' if z is None else f'{z:+.1f}' for z in zs)}")

    print("\n=== fuentes en vivo (como FedWatch) ===")
    try:
        print("  EFFR:", tasas_fed.effr_hoy())
    except Exception as e:
        print("  EFFR no:", repr(e)[:300])
    hoy = datetime.now(timezone.utc).date()
    tks = tasas_fed.contratos(hoy)
    try:
        print("  TradingView:", tasas_fed.precios_tradingview(tks))
    except Exception as e:
        print("  TradingView no:", repr(e)[:300])
    for tk in tks:
        try:
            print(f"  Yahoo {tk}: {tasas_fed.precio_futuro(tk)}")
        except Exception as e:
            print(f"  Yahoo {tk} no:", repr(e)[:300])
    try:
        cme = tasas_fed._json("https://www.cmegroup.com/CmeWS/mvc/Quotes/Future/305/G")
        print("  CME:", [(q.get("expirationMonth"), q.get("last"), q.get("priorSettle")) for q in cme.get("quotes", [])[:4]])
    except Exception as e:
        print("  CME no:", repr(e)[:300])
    try:
        print(tasas_fed.traer())
    except Exception as e:
        print("  no se pudo:", repr(e)[:300])


if __name__ == "__main__":
    main()
