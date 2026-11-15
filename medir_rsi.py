"""¿El RSI en sobrecompra o sobreventa anticipa la vuelta del precio? (medir antes de sumar)

En cada temporalidad (15 min, 1 h y 4 h con velas de Binance 2021-2026; diario y semanal con CoinMetrics 2011-2026),
cuando el RSI 14 esta en sobrecompra se espera que baje y en sobreventa que suba. Variantes:
  - en la zona: RSI >= 70 / <= 30, y la mas extrema >= 80 / <= 20
  - al salir de la zona (el gatillo clasico): el RSI vuelve a cruzar 70 hacia abajo (baja) o 30 hacia arriba (sube)
Horizontes: los plazos de la app que mira cada grafico (15 min → 1 y 4 h; 1 h → 1, 4 y 24 h; 4 h → 4 h, 1 y 7 dias;
diario → 1, 7 y 30 dias; semanal → 7, 30 y 90 dias). Acierta si el precio fue para el lado esperado; se compara con
lo que pasa en un momento cualquiera del mismo tramo, en dos tramos (2021-24 y 2025-26; en diario y semanal, 2012-19
y 2020-26). Los momentos se pisan (una señal de 30 dias se cuenta muchos dias seguidos): el z usa n / horizonte.
Uso: python medir_rsi.py
"""
import math

import indicadores as ind
import medir_nuevo as mn
from medir_senales import velas
from medir_zonas import cm

HZ = {"15m": (1, 4), "1h": (1, 4, 24), "4h": (4, 24, 168), "1d": (24, 168, 720), "1w": (168, 720, 2160)}   # horas
TF_H = {"15m": 0.25, "1h": 1, "4h": 4, "1d": 24, "1w": 168}


def senales(r):
    """{nombre: [(i, lado), ...]} lado +1 = se espera suba, -1 = baja."""
    S = {k: [] for k in ("RSI >= 70 (sobrecompra)", "RSI <= 30 (sobreventa)", "RSI >= 80", "RSI <= 20", "sale de sobrecompra (cruza 70 hacia abajo)",
                         "sale de sobreventa (cruza 30 hacia arriba)")}
    for i in range(1, len(r)):
        if r[i] is None or r[i - 1] is None:
            continue
        if r[i] >= 70: S["RSI >= 70 (sobrecompra)"].append((i, -1))
        if r[i] <= 30: S["RSI <= 30 (sobreventa)"].append((i, 1))
        if r[i] >= 80: S["RSI >= 80"].append((i, -1))
        if r[i] <= 20: S["RSI <= 20"].append((i, 1))
        if r[i - 1] >= 70 > r[i]: S["sale de sobrecompra (cruza 70 hacia abajo)"].append((i, -1))
        if r[i - 1] <= 30 < r[i]: S["sale de sobreventa (cruza 30 hacia arriba)"].append((i, 1))
    return S


def medir(tf, t, c, corte):
    r = ind.rsi(c)
    r = [None if i < 30 else v for i, v in enumerate(r)]
    S = senales(r)
    n = len(c)
    out = []
    print(f"\n=== RSI 14 en velas de {tf} ({n} velas) ===", flush=True)
    for hz in HZ[tf]:
        k = max(1, round(hz / TF_H[tf]))
        base = {}
        for tramo in (0, 1):
            idx = [i for i in range(30, n - k) if (t[i] < corte) == (tramo == 0)]
            base[tramo] = sum(c[i + k] > c[i] for i in idx) / max(1, len(idx))
        for nom, ev in S.items():
            txt, zs, difs = f"  {hz:>4} h | {nom:<44}", [], []
            for tramo in (0, 1):
                sel = [(i, l) for i, l in ev if i + k < n and (t[i] < corte) == (tramo == 0)]
                if len(sel) < 15:
                    txt += f" | tramo {tramo + 1}: pocos ({len(sel)})"
                    zs.append(None); difs.append(None)
                    continue
                ok = sum((c[i + k] > c[i]) == (l > 0) for i, l in sel) / len(sel)
                b = base[tramo] if sel[0][1] > 0 else 1 - base[tramo]
                # n efectivo: las señales seguidas se pisan; como mucho una cada "k" velas
                ne = max(1.0, min(len(sel), len({i // k for i, _ in sel})))
                z = (ok - b) / math.sqrt(max(1e-9, b * (1 - b) / ne))
                txt += f" | tramo {tramo + 1}: {len(sel):>5} · acierta {100 * ok:4.1f}% (normal {100 * b:4.1f}%, z {z:+.1f})"
                zs.append(z); difs.append(ok - b)
            ver = ("A FAVOR (revierte)" if all(z is not None and z >= 2 for z in zs) else
                   "AL REVÉS (sigue)" if all(z is not None and z <= -2 for z in zs) else "~ no anticipa")
            print(txt + f"  →  {ver}", flush=True)
            out.append((tf, hz, nom, ver, difs))
    return out


def main():
    res = []
    for tf in ("15m", "1h", "4h"):
        B = velas(tf)
        res += medir(tf, [b[0] for b in B], [b[4] for b in B], mn.CORTE)
    px = cm("PriceUSD")
    dias = sorted(d for d in px if d >= "2011-01-01")
    from datetime import date
    tms = [int(date.fromisoformat(d).toordinal() - date(1970, 1, 1).toordinal()) * 86400000 for d in dias]
    c = [px[d] for d in dias]
    corte = int(date(2020, 1, 1).toordinal() - date(1970, 1, 1).toordinal()) * 86400000
    res += medir("1d", tms, c, corte)
    sem = list(range(len(c) - 1, -1, -7))[::-1]          # cierre de cada semana (cada 7 dias hasta hoy)
    res += medir("1w", [tms[i] for i in sem], [c[i] for i in sem], corte)
    print("\n=== resumen (A FAVOR = revierte en los dos tramos, z >= 2) ===")
    for tf, hz, nom, ver, difs in res:
        if ver != "~ no anticipa":
            print(f"  {tf:<4} {hz:>4} h  {nom:<44} {ver}  ({' / '.join('—' if d is None else f'{100 * d:+.1f} pts' for d in difs)})")
    print("  (lo que no aparece: ~50%, no anticipa)")


if __name__ == "__main__":
    main()
