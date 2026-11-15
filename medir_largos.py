"""¿Los indicadores del grafico diario y semanal anticipan el dia, la semana y el mes? (lo que faltaba medir)

En velas de 15 min, 1 h y 4 h el resumen de indicadores va al reves (medir_senales.py). En el diario o mas la app lo
cuenta A FAVOR con peso 2 "sin medir". Aca, con velas diarias de Binance spot (agosto de 2017 a hoy) y semanales
armadas con ellas (lunes a domingo): el resumen (medias y osciladores, indicadores.calificar) y cada indicador, cuando
marcan alcista o bajista, ¿el precio fue para ese lado?
  diario → 1, 7 y 30 dias          semanal → 7 y 30 dias
Dos tramos: hasta 2021 y 2022-2026. Las señales que se pisan cuentan una vez por horizonte. A FAVOR / AL REVES: z >= 2
(o <= -2) en los dos tramos.
Uso: python medir_largos.py
"""
import math
from collections import defaultdict
from datetime import date

import indicadores as ind
import medir_nuevo as mn

CORTE = (date(2022, 1, 1) - date(1970, 1, 1)).days * 86400000


def diarias():
    ms = lambda x: int(x) // (1000 if int(x) > 10**14 else 1)
    out = []
    for y, m in mn.meses(desde=(2017, 8)):
        out += mn._zip(f"https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-{y}-{m:02d}.zip",
                       f"sd1_{y}-{m:02d}.json", lambda r: [ms(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
    out.sort(key=lambda b: b[0])
    return out


def semanales(D):
    out = []
    for b in D:
        lunes = (b[0] // 86400000 + 3) % 7 == 0          # el 1/1/1970 fue jueves
        if lunes or not out:
            out.append(list(b))
        else:
            w = out[-1]
            w[2], w[3], w[4], w[5] = max(w[2], b[2]), min(w[3], b[3]), b[4], w[5] + b[5]
    return out


def medir(nombre, B, ventana, horizontes, paso):
    """horizontes en velas de B."""
    n = len(B)
    c = [b[4] for b in B]
    acum = defaultdict(list)          # nombre -> [(i, lado)]
    for i in range(ventana - 1, n - 1):
        rows, res = ind.calificar(B[i - ventana + 1:i + 1])[:2]
        if abs(res["rating"]) > 0.1:
            acum["RESUMEN (medias y osciladores)"].append((i, 1 if res["rating"] > 0 else -1))
        if abs(res["rating"]) > 0.5:
            acum["RESUMEN fuerte (más de 0,5)"].append((i, 1 if res["rating"] > 0 else -1))
        if abs(res.get("ma_rating", 0) or 0) > 0.1:
            acum["  solo medias"].append((i, 1 if res["ma_rating"] > 0 else -1))
        if abs(res.get("osc_rating", 0) or 0) > 0.1:
            acum["  solo osciladores"].append((i, 1 if res["osc_rating"] > 0 else -1))
        for r in rows:
            if r["senal"] in ("compra", "venta"):
                acum[r["indicador"]].append((i, 1 if r["senal"] == "compra" else -1))
    print(f"\n=== {nombre}: {n} velas, {n - ventana} momentos ===", flush=True)
    res_out = []
    for nom in sorted(acum, key=lambda k: (not k.startswith(("RESUMEN", "  solo")), k)):
        ev = acum[nom]
        for h in horizontes:
            zs, txt = [], f"  {nom:<34} {h * paso:>3} d"
            for tramo in (0, 1):
                idx = [i for i in range(ventana - 1, n - h) if (B[i][0] < CORTE) == (tramo == 0)]
                base = sum(c[i + h] > c[i] for i in idx) / max(1, len(idx))
                sel = [(i, l) for i, l in ev if i + h < n and (B[i][0] < CORTE) == (tramo == 0)]
                if len(sel) < 20:
                    txt += " | pocos"; zs.append(None); continue
                ok = sum((c[i + h] > c[i]) == (l > 0) for i, l in sel) / len(sel)
                ps = sum(1 for _, l in sel if l > 0) / len(sel)
                b = ps * base + (1 - ps) * (1 - base)
                z = (ok - b) / math.sqrt(max(1e-9, b * (1 - b) / max(1, len({i // h for i, _ in sel}))))
                zs.append(z)
                txt += f" | {len(sel):>4} · acierta {100 * ok:4.1f}% (normal {100 * b:4.1f}%, z {z:+.1f})"
            ver = "A FAVOR" if all(x is not None and x >= 2 for x in zs) else "AL REVÉS" if all(x is not None and x <= -2 for x in zs) else "~"
            print(txt + f"  → {ver}", flush=True)
            res_out.append((nombre, nom, h * paso, ver, zs))
    return res_out


def main():
    D = diarias()
    print(f"{len(D)} velas diarias (spot)", flush=True)
    R = medir("DIARIO", D, 400, (1, 7, 30), 1)
    W = semanales(D)
    R += medir("SEMANAL", W, 150, (1, 4), 7)
    print("\n=== resumen ===")
    for nombre, nom, d, ver, zs in R:
        if ver != "~" or nom.startswith(("RESUMEN", "  solo")):
            print(f"  {nombre:<8} {nom:<34} {d:>3} d  {ver:<9} z {' / '.join('—' if z is None else f'{z:+.1f}' for z in zs)}")


if __name__ == "__main__":
    main()
