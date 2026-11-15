"""¿Cada indicador marca bien para donde va? (medir antes de cambiar una regla)

La tabla "Todos los indicadores" dice alcista o bajista por indicador (reglas de TradingView, indicadores.calificar), y
la explicacion de cada plazo suma ademas el RSI extremo y el cruce del MACD. Aca se mide, con velas de BTC 2021-2026 de
15 min, 1 h y 4 h (cada 4 horas, sin mirar el futuro), si el precio fue para el lado que marca cada uno:

  1. Cada indicador de calificar(), solo, cuando marca compra o venta.
  2. Las señales de la explicacion: RSI >= 70 (cuenta bajista), RSI <= 30 (alcista) y el cruce del MACD (a favor).
  3. Reglas alternativas para los que dan dudas: ADX con +DI/-DI, Momentum con signo, MACD con el cero, RSI contra 50.

Cada uno en 2021-24 y en 2025-26: a favor si gana en los dos (z >= 2), al reves si pierde en los dos (z <= -2), y si
no, ~50%: no sirve para la direccion. Datos: data.binance.vision (velas de futuros con volumen).
Uso: python medir_senales.py   (baja a datos_medicion/nuevo, se reusa)
"""
import math
from collections import defaultdict

import indicadores as ind
import medir_nuevo as mn

CORTE = mn.CORTE
VENTANA = 1000           # calificar mira la ultima vela: con 1.000 la media de 200 ya olvido el arranque (e^-9)
TF_MIN = {"15m": 15, "1h": 60, "4h": 240}
HORIZ = {"15m": (1, 4), "1h": (1, 4), "4h": (4, 24)}     # horas


def velas(tf):
    ms = lambda x: int(x) // (1000 if int(x) > 10**14 else 1)
    out = []
    for y, m in mn.meses():
        out += mn._zip(f"https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/{tf}/BTCUSDT-{tf}-{y}-{m:02d}.zip",
                       f"kv{tf}_{y}-{m:02d}.json", lambda r: [ms(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
    out.sort(key=lambda b: b[0])
    return out


def senales(win):
    """{nombre: +1/-1} de lo que marca la ultima vela de win."""
    rows, res = ind.calificar(win)[:2]
    out = {}
    for r in rows:
        if r["senal"] in ("compra", "venta"):
            out[r["indicador"]] = 1 if r["senal"] == "compra" else -1
    if abs(res["rating"]) > 0.1:
        out["RESUMEN (medias y osciladores)"] = 1 if res["rating"] > 0 else -1
    h, l, c = [b[2] for b in win], [b[3] for b in win], [b[4] for b in win]
    i = len(c) - 1
    r = ind.rsi(c)
    if r[i] >= 70:
        out["EXPL: RSI >= 70 (cuenta bajista)"] = -1
    elif r[i] <= 30:
        out["EXPL: RSI <= 30 (cuenta alcista)"] = 1
    ml, ms, mh = ind.macd(c)
    for k in (i, i - 1):
        if mh[k] > 0 >= mh[k - 1]:
            out["EXPL: cruce del MACD"] = 1
            break
        if mh[k] < 0 <= mh[k - 1]:
            out["EXPL: cruce del MACD"] = -1
            break
    # alternativas
    adx, pdi, mdi, _ = ind.dmi(h, l, c)
    if adx[i] > 20:
        out["ALT: ADX > 20 con +DI/-DI"] = 1 if pdi[i] > mdi[i] else -1
    if adx[i] > 25:
        out["ALT: ADX > 25 con +DI/-DI"] = 1 if pdi[i] > mdi[i] else -1
    mo = ind.momentum(c)
    if mo[i] > 0 and mo[i] > mo[i - 1]:
        out["ALT: Momentum > 0 y subiendo"] = 1
    elif mo[i] < 0 and mo[i] < mo[i - 1]:
        out["ALT: Momentum < 0 y bajando"] = -1
    if ml[i] > 0 and ml[i] > ms[i]:
        out["ALT: MACD sobre cero y sobre la señal"] = 1
    elif ml[i] < 0 and ml[i] < ms[i]:
        out["ALT: MACD bajo cero y bajo la señal"] = -1
    out["ALT: RSI contra 50"] = 1 if r[i] > 50 else -1
    return out


def z_de(ok, n):
    return (ok / n - 0.5) / math.sqrt(0.25 / n) if n else 0.0


def main():
    resumen = []
    for tf in ("1h", "15m", "4h"):
        B = velas(tf)
        paso = max(1, 240 // TF_MIN[tf])
        c = [b[4] for b in B]
        acum = defaultdict(lambda: defaultdict(lambda: [0, 0]))    # nombre -> (hz, tramo) -> [ok, n]
        hz_v = {hz: hz * 60 // TF_MIN[tf] for hz in HORIZ[tf]}
        n_mom = 0
        for i in range(VENTANA + 50, len(B) - max(hz_v.values()) - 1, paso):
            s = senales(B[i - VENTANA + 1:i + 1])
            tramo = "21-24" if B[i][0] < CORTE else "25-26"
            n_mom += 1
            for hz, k in hz_v.items():
                sube = c[i + k] > c[i]
                for nom, lado in s.items():
                    a = acum[nom][(hz, tramo)]
                    a[0] += (lado > 0) == sube
                    a[1] += 1
            if n_mom % 2000 == 0:
                print(f"  {tf}: {n_mom} momentos", flush=True)
        print(f"\n=== velas de {tf} ({n_mom} momentos, cada 4 h) ===")
        for nom in sorted(acum):
            txt, zs = f"  {nom:<40}", []
            for hz in HORIZ[tf]:
                for tramo in ("21-24", "25-26"):
                    ok, n = acum[nom][(hz, tramo)]
                    z = z_de(ok, n)
                    zs.append(z)
                    txt += f" | {hz:>2} h {tramo}: {n:>5} · {100 * ok / max(1, n):5.1f}% (z {z:+5.1f})"
            # veredicto por horizonte: gana o pierde en los dos tramos
            v = []
            for k, hz in enumerate(HORIZ[tf]):
                a, b = zs[2 * k], zs[2 * k + 1]
                v.append(f"{hz} h: " + ("A FAVOR" if a >= 2 and b >= 2 else "AL REVÉS" if a <= -2 and b <= -2 else "~50%"))
            print(txt + "  →  " + ", ".join(v), flush=True)
            resumen.append((tf, nom, v))
    print("\n=== resumen ===")
    for tf, nom, v in resumen:
        print(f"  {tf:<4} {nom:<40} {' · '.join(v)}")


if __name__ == "__main__":
    main()
