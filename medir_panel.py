"""Panel de monedas: lo que con BTC solo no alcanza para decidir en plazos largos (nov. 2026).

BTC tiene ~100 meses independientes: a 7 y 30 dias casi nada llega a z 2. Con 30 monedas (velas diarias de Binance
spot, 2018-2026) hay muchos mas casos y, si una señal repite en monedas distintas, es mas creible.
Señales del grafico diario (las mismas funciones de la app): resumen de indicadores, RSI extremo, Keltner, MFI,
cruce del MACD, figuras, divergencias, Elliott. A 7 y 30 dias, en 2018-21 y 2022-26:
  ABSOLUTO  ¿la moneda subio/bajo para el lado de la señal? (contra lo normal de ese tramo)
  RELATIVO  ¿le fue mejor/peor que a la mediana de las demas monedas en esos dias? (normal 50%; saca el efecto "todo sube")
Las monedas se mueven juntas: el z no cuenta casos sino MESES (el promedio de cada bloque de 30 dias es un dato).
A FAVOR / AL REVES: z >= 2 (o <= -2) en los dos tramos.
Uso: python medir_panel.py
"""
import math
from collections import defaultdict
from datetime import date

import indicadores as ind
import medir_nuevo as mn
from medir_estructura import senales as estructura

MONEDAS = ("BTC ETH BNB XRP ADA DOGE SOL LTC LINK DOT AVAX TRX XLM ATOM ETC BCH UNI FIL NEAR ALGO AAVE EOS XTZ ZEC DASH "
           "VET THETA ICP SAND MATIC").split()
CORTE = (date(2022, 1, 1) - date(1970, 1, 1)).days
D = 86400000
V = 400
HZ = (7, 30)


def diarias(m):
    ms = lambda x: int(x) // (1000 if int(x) > 10**14 else 1)
    out = []
    for y, mm in mn.meses(desde=(2018, 1)):
        out += mn._zip(f"https://data.binance.vision/data/spot/monthly/klines/{m}USDT/1d/{m}USDT-1d-{y}-{mm:02d}.zip",
                       f"pd_{m}_{y}-{mm:02d}.json", lambda r: [ms(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
    out.sort(key=lambda b: b[0])
    return out


def senales(win):
    out = {}
    rows, res = ind.calificar(win)[:2]
    if abs(res["rating"]) > 0.1:
        out["RESUMEN de indicadores"] = 1 if res["rating"] > 0 else -1
    if abs(res["rating"]) > 0.5:
        out["RESUMEN fuerte"] = 1 if res["rating"] > 0 else -1
    R = {r["indicador"]: r for r in rows}
    c = [b[4] for b in win]
    r = ind.rsi(c)[-1]
    if r >= 70:
        out["RSI >= 70: sigue subiendo"] = 1
    if r <= 30:
        out["RSI <= 30: rebota"] = 1
    for nom, txt in (("Canal de Keltner", "KELTNER: fuera del canal, sigue"), ("SuperTrend (10,3)", "SUPERTREND"), ("Nube de Ichimoku", "ICHIMOKU nube"),
                     ("SMA 200", "SMA 200"), ("SMA 50", "SMA 50")):
        x = R.get(nom)
        if x and x["senal"] in ("compra", "venta"):
            out[txt] = 1 if x["senal"] == "compra" else -1
    x = R.get("MFI 14")
    if x and x["senal"] in ("compra", "venta"):
        out["MFI extremo: sigue (al revés de la regla)"] = -1 if x["senal"] == "compra" else 1
    for k, v in estructura(win, 3).items():
        if not k.startswith("  ") and "VELAS" not in k:
            out[k] = v
    return out


def main():
    S = {}
    for m in MONEDAS:
        B = diarias(m)
        if len(B) >= V + 200:
            S[m] = B
        print(f"{m}: {len(B)} velas", flush=True)
    cierre = {m: {b[0] // D: b[4] for b in B} for m, B in S.items()}
    ev = defaultdict(list)                       # señal -> [(dia, moneda, lado)]
    for m, B in S.items():
        for i in range(V - 1, len(B) - 1, 2):
            for nom, lado in senales(B[i - V + 1:i + 1]).items():
                ev[nom].append((B[i][0] // D, m, lado))
        print(f"  {m}: listo", flush=True)
    # retorno a h dias de cada moneda y la mediana del dia
    R = {}
    for h in HZ:
        ret = defaultdict(dict)
        for m, cd in cierre.items():
            for d, p in cd.items():
                q = cd.get(d + h)
                if q:
                    ret[d][m] = q / p - 1
        med = {d: sorted(x.values())[len(x) // 2] for d, x in ret.items() if len(x) >= 8}
        R[h] = (ret, med)
    print(f"\n{len(S)} monedas. z por bloques de 30 días.", flush=True)
    resumen = []
    for nom in sorted(ev):
        for h in HZ:
            ret, med = R[h]
            for modo in ("ABSOLUTO", "RELATIVO"):
                txt, zs = f"  {nom:<46} {h:>2} d {modo:<8}", []
                for tr in (0, 1):
                    en = lambda d: (d < CORTE) == (tr == 0)
                    if modo == "ABSOLUTO":
                        tot = [(x > 0) for d, mm in ret.items() if en(d) for x in mm.values()]
                        base_up = sum(tot) / max(1, len(tot))
                    bl = defaultdict(list)
                    for d, m, l in ev[nom]:
                        x = ret.get(d, {}).get(m)
                        if x is None or not en(d) or (modo == "RELATIVO" and d not in med):
                            continue
                        if modo == "ABSOLUTO":
                            bl[d // 30].append(((x > 0) == (l > 0)) - (base_up if l > 0 else 1 - base_up))
                        else:
                            bl[d // 30].append(((x > med[d]) == (l > 0)) - 0.5)
                    n = sum(len(v) for v in bl.values())
                    if len(bl) < 12 or n < 100:
                        txt += f" | pocos ({n})"; zs.append(None); continue
                    mb = [sum(v) / len(v) for v in bl.values()]
                    mu = sum(mb) / len(mb); sd = math.sqrt(sum((x - mu) ** 2 for x in mb) / (len(mb) - 1))
                    z = mu / (sd / math.sqrt(len(mb) / max(1, h / 30))) if sd > 0 else 0
                    tot_mu = sum(sum(v) for v in bl.values()) / n
                    zs.append(z)
                    txt += f" | {n:>6} casos, {len(bl):>3} meses · {100 * tot_mu:+5.1f} pts sobre lo normal (z {z:+.1f})"
                ver = "A FAVOR" if all(x is not None and x >= 2 for x in zs) else "AL REVÉS" if all(x is not None and x <= -2 for x in zs) else "~"
                print(txt + f"  → {ver}", flush=True)
                resumen.append((nom, h, modo, ver, zs))
    print("\n=== lo que pasó ===")
    for nom, h, modo, ver, zs in resumen:
        if ver != "~":
            print(f"  {nom:<46} {h:>2} d {modo:<8} {ver}  z {' / '.join('—' if z is None else f'{z:+.1f}' for z in zs)}")


if __name__ == "__main__":
    main()
