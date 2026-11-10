"""¿Lo que Kronos mira y la app no, mejora las predicciones? (medir antes de sumar)

Kronos no usa indicadores: lee las velas crudas (apertura, maximo, minimo, cierre, volumen y monto) y la fecha. Casi todo eso
ya esta en las señales del modelo de movimiento fuerte (fuerte.NOMBRES). Lo que falta, en tres grupos:
  calendario: dia de la semana, dia del mes y si faltan 2 dias o menos para fin de mes
  mechas:     mecha de arriba y de abajo por separado (de la ultima vela y el promedio de las ultimas 6), sobre la volatilidad
  monto:      el monto en USDT (volumen x precio tipico) contra su ultima semana, y el de 24 h contra el de la semana
Se prueba cada grupo sumado a las señales de hoy, y los tres juntos, en dos cosas:
  movimiento fuerte (el objetivo de entrenar_fuerte.py) y para donde va (sube o baja), a 1 y 4 horas.
Prueba honesta: cada trimestre desde 2023 con un modelo entrenado solo con lo anterior (medir_compresion.honesto).
Entra si mejora en los tres tramos (2023-24, 2025 y 2026) con z por dia > 2.
Uso: python medir_ideas_kronos.py velas_1h.json eventos.json MONEDA
"""
import json, sys
import numpy as np
import entrenar_fuerte as ef
import medir_compresion as mcomp

H, D = 3_600_000, 86_400_000


def roll(x, w, f):
    return ef.roll(x, w, f)


def extras(B):
    t, o, h, l, c, v = (np.asarray(x, dtype=float) for x in zip(*B))
    lc = np.log(c); r1 = np.diff(lc, prepend=lc[0]); s = roll(r1, 168, np.std)
    dia = t // D
    # fecha UTC de cada vela (sin datetime por vela: dias desde 1970 -> año, mes, dia)
    fechas = dia.astype(np.int64).astype("datetime64[D]")
    dmes = (fechas - fechas.astype("datetime64[M]")).astype(int) + 1
    fin = ((fechas.astype("datetime64[M]") + 1).astype("datetime64[D]") - fechas).astype(int) - 1
    cal = np.column_stack([(dia + 3) % 7, dmes, (fin <= 2).astype(float)])
    sup = (h - np.maximum(o, c)) / c / s; inf = (np.minimum(o, c) - l) / c / s
    mech = np.column_stack([sup, inf, roll(sup, 6, np.mean), roll(inf, 6, np.mean)])
    m = v * (h + l + c) / 3; lm = np.log1p(m)
    mon = np.column_stack([(lm - roll(lm, 168, np.mean)) / roll(lm, 168, np.std), roll(m, 24, np.mean) / roll(m, 168, np.mean)])
    return {"calendario": cal, "mechas": mech, "monto": mon}


def direccion(lc, hz):
    n = len(lc); fut = np.full(n, np.nan); fut[:-hz] = lc[hz:] - lc[:-hz]
    return (fut > 0).astype(float), ~np.isnan(fut) & (np.arange(n) > 2 * hz)


def z_dia(t, d):
    dia = (t // D).astype(int)
    u, inv = np.unique(dia, return_inverse=True)
    m = np.bincount(inv, weights=d)
    return float(m.mean() / (m.std(ddof=1) / len(m) ** 0.5)) if len(m) > 20 and m.std() > 0 else float("nan")


def main():
    B = json.load(open(sys.argv[1])); evs = json.load(open(sys.argv[2])); mon = sys.argv[3] if len(sys.argv) > 3 else "BTC"
    t, lc, X = ef.señales(B, evs)
    E = extras(B)
    grupos = {**{k: np.column_stack([X, v]) for k, v in E.items()}, "los tres": np.column_stack([X] + list(E.values()))}
    res = []
    print(f"{mon}: {len(B)} velas de 1 h")
    for que, fn in (("movimiento fuerte", ef.objetivo), ("para donde", direccion)):
        for hz in (1, 4):
            y, ok = fn(lc, hz)
            P0, b0, g0 = mcomp.honesto(t, X, y, ok, hz)
            print(f"\n{mon} {hz} h · {que} (error de la probabilidad; ventaja sobre la tasa base)")
            for nom, XG in grupos.items():
                P1, _, g1 = mcomp.honesto(t, XG, y, ok, hz)
                zs = []
                for tramo, a, b in mcomp.TRAMOS:
                    s = g0 & g1 & (t >= a) & (t < b) & np.isfinite(P0) & np.isfinite(P1)
                    e0, e1, eb = (P0[s] - y[s]) ** 2, (P1[s] - y[s]) ** 2, (b0[s] - y[s]) ** 2
                    z = z_dia(t[s], e0 - e1); zs.append(z)
                    fila = {"moneda": mon, "que": que, "hz": hz, "idea": nom, "tramo": tramo, "horas": int(s.sum()),
                            "hoy": round(100 * (1 - e0.sum() / eb.sum()), 2), "con_idea": round(100 * (1 - e1.sum() / eb.sum()), 2), "z": round(z, 2)}
                    res.append(fila)
                    print(f"  + {nom:<10} {tramo}: hoy {fila['hoy']:+.2f}% · con la idea {fila['con_idea']:+.2f}%  z {z:+.1f}  ({fila['horas']} horas)", flush=True)
                print(f"  + {nom:<10} mejora en los tres tramos (z > 2): {'SI' if all(z > 2 for z in zs) else 'no'}")
    json.dump(res, open(f"resultado_ideas_{mon}.json", "w"), ensure_ascii=False, indent=0)


if __name__ == "__main__":
    main()
