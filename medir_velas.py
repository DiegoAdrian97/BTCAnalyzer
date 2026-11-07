"""Medir antes de sumar, segunda tanda: senales que salen de las velas (sin datos nuevos en vivo, salvo ETH).

Mismo metodo que medir_contexto.py (el analista como corre en vivo, ventana por ventana, aprendizaje desde cero y repaso
de 1.000 predicciones sin mirar el futuro): cada idea se suma al modelo que aprende solo y se compara con el actual.
Entra al analisis solo lo que gana en 2023-24 y tambien en 2025-26 (|z| > 2 por dia, en los dos tramos).

Ideas:
- rango 24 h y 7 dias: donde esta el precio dentro del rango del ultimo dia y de la ultima semana, y cuanto le falta
  (en ATR) para el maximo y el minimo de la semana (rupturas, techos y pisos recientes).
- compresion: el ancho de las Bollinger contra su promedio de las ultimas ~2 semanas (despues de comprimirse suele
  venir un movimiento).
- dia de la semana: lunes a domingo como un ciclo (seno y coseno), ademas del fin de semana que ya mira.
- apertura de EE.UU.: las 2 horas despues de que abre Wall Street (13:30 UTC; 14:30 en invierno) en dias habiles.
- ETH: cuanto se movio ETH en la ultima vela, 3 y 12 velas (en sus ATR) y ETH/BTC contra su promedio de 24 h: si ETH
  se adelanta, BTC lo sigue.

Uso: python medir_velas.py [carpeta de datos, por defecto datos_medicion]   (PLAZOS="1 hora,4 horas" para algunos)
"""
import bisect, json, math, os, sys, time
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

import medir_contexto as mc
import indicadores as ind

NOMBRES = ("rango 24 h", "rango 7 d", "al max 7 d", "al min 7 d", "compresion", "dia sen", "dia cos", "apertura EE.UU.",
           "ETH 1 vela", "ETH 3 velas", "ETH 12 velas", "ETH/BTC 24 h")
GRUPOS = {"rango 24 h y 7 días": (0, 1, 2, 3), "compresión (Bollinger)": (4,), "día de la semana": (5, 6),
          "apertura de EE.UU.": (7,), "ETH": (8, 9, 10, 11), "todas juntas (velas)": tuple(range(12))}
H1, H24 = mc.H1, mc.H24


def _dst(t):
    """Horario de verano de EE.UU. (aprox.: de mediados de marzo a principios de noviembre)."""
    import datetime as dt
    d = dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc)
    return (d.month, d.day) >= (3, 10) and (d.month, d.day) < (11, 3)


def senales(bars, tf_ms, eth):
    n, tf_min = len(bars), tf_ms // 60_000
    h = [b[2] for b in bars]; l = [b[3] for b in bars]; c = [b[4] for b in bars]
    a = ind.atr_w(h, l, c)
    mid, bu, bl = ind.bollinger(c)
    d1, d7 = max(1, H24 // tf_ms), max(1, 7 * H24 // tf_ms)
    ancho = [(bu[i] - bl[i]) / mid[i] if bu[i] is not None and mid[i] else None for i in range(n)]
    nb = max(20, 14 * H24 // tf_ms)
    acum = mc._acum(math.log(x) if x and x > 0 else 0.0 for x in ancho)
    cnt = mc._acum(1 if x and x > 0 else 0 for x in ancho)
    # ETH alineado por hora de apertura
    et = {b[0]: b for b in eth}
    ec = [et[b[0]][4] if b[0] in et else None for b in bars]
    eh = [et[b[0]][2] if b[0] in et else None for b in bars]
    el = [et[b[0]][3] if b[0] in et else None for b in bars]
    ea = ind.atr_w([x or 0 for x in eh], [x or 0 for x in el], [x or 0 for x in ec]) if eth else [None] * n
    ratio = [math.log(ec[i] / c[i]) if ec[i] and c[i] else None for i in range(n)]
    racum = mc._acum(r or 0.0 for r in ratio)
    out = []
    from collections import deque
    mx1, mn1, mx7, mn7 = deque(), deque(), deque(), deque()

    def empujar(dq, i, v, mayor):
        while dq and ((v[dq[-1]] <= v[i]) if mayor else (v[dq[-1]] >= v[i])):
            dq.pop()
        dq.append(i)

    for i in range(n):
        for dq, v, mayor, ven in ((mx1, h, True, d1), (mn1, l, False, d1), (mx7, h, True, d7), (mn7, l, False, d7)):
            empujar(dq, i, v, mayor)
            while dq[0] <= i - ven:
                dq.popleft()
        f = [None] * 12
        if a[i] and i >= d7:
            H1v, L1v, H7, L7 = h[mx1[0]], l[mn1[0]], h[mx7[0]], l[mn7[0]]
            f[0] = ((c[i] - L1v) / (H1v - L1v) - 0.5) * 2 if H1v > L1v else 0.0
            f[1] = ((c[i] - L7) / (H7 - L7) - 0.5) * 2 if H7 > L7 else 0.0
            f[2] = math.log1p((H7 - c[i]) / a[i])
            f[3] = math.log1p((c[i] - L7) / a[i])
        if ancho[i] and i >= nb and cnt[i + 1] - cnt[i + 1 - nb] > nb // 2:
            f[4] = math.log(ancho[i]) - (acum[i + 1] - acum[i + 1 - nb]) / (cnt[i + 1] - cnt[i + 1 - nb])
        T = bars[i][0] + tf_ms                                  # el cierre de la vela: lo que se sabe
        dia = (T // H24 + 3) % 7
        f[5], f[6] = math.sin(2 * math.pi * dia / 7), math.cos(2 * math.pi * dia / 7)
        ap = (13 if _dst(T) else 14) * 60 + 30
        mins = (T // 60_000) % 1440
        f[7] = 1.0 if dia < 5 and ap <= mins < ap + 120 else 0.0
        if ec[i] and ea[i] and i >= 12 and ec[i - 12] and ec[i - 3] and ec[i - 1]:
            f[8] = (ec[i] - ec[i - 1]) / ea[i]
            f[9] = (ec[i] - ec[i - 3]) / ea[i] / 1.7
            f[10] = (ec[i] - ec[i - 12]) / ea[i] / 3.5
        if ratio[i] is not None and i >= d1:
            f[11] = ratio[i] - (racum[i + 1] - racum[i + 1 - d1]) / d1
        out.append(f)
    return out


def escalar(F, bars):
    k_ = len(NOMBRES)
    est = []
    for k in range(k_):
        xs = [f[k] for f, b in zip(F, bars) if f[k] is not None and b[0] < mc.ESCALAS]
        mu = sum(xs) / len(xs) if xs else 0.0
        sd = (sum((x - mu) ** 2 for x in xs) / len(xs)) ** 0.5 if len(xs) > 1 else 1.0
        est.append((mu, sd or 1.0))
    return [[0.0 if f[k] is None else max(-4.0, min(4.0, (f[k] - est[k][0]) / est[k][1])) for k in range(k_)] for f in F]


def main():
    os.makedirs(mc.CACHE, exist_ok=True)
    t0 = time.time()
    D, E = {}, {}
    for tf in ("5m", "30m", "4h"):
        mc.SYM = "BTCUSDT"; D[tf] = mc.velas(tf)
        mc.SYM = "ETHUSDT"; E[tf] = mc.velas(tf)
    mc.SYM = "BTCUSDT"
    print("bajado en", round(time.time() - t0), "s:", {k: len(v) for k, v in D.items()}, flush=True)
    mc.GRUPOS, mc.VARIANTES = GRUPOS, ("actual",) + tuple(GRUPOS)
    R = {}
    with ProcessPoolExecutor(max(1, os.cpu_count() or 2)) as pool:
        for nombre, tf, h, W in mc.PLAZOS_M:
            if os.environ.get("PLAZOS") and nombre not in os.environ["PLAZOS"].split(","):
                continue
            t1 = time.time()
            bars = D[tf]
            ctx = escalar(senales(bars, mc.TF_MS[tf], E[tf]), bars)
            R[nombre], _ = mc.medir_plazo(nombre, tf, h, W, bars, ctx, pool)
            print(f"{nombre}: {len(R[nombre]['actual'])} predicciones repasadas en {round(time.time() - t1)} s", flush=True)
    resumen = {}
    print("\nVENTAJA SOBRE LA TASA BASE (% menos error; z: la diferencia con la actual, por dia; |z| > 2 es real)")
    for nombre in R:
        filas = mc.comparar(R[nombre])
        resumen[nombre] = filas
        print(f"\n  {nombre}")
        for v, tramo, n, hab, z in filas:
            print(f"    {v:<26} {tramo}  {n:>7} pred.  ventaja {hab:+.2f}%  z {z:+.1f}")
    with open(os.path.join(mc.CACHE, "resultado_velas.json"), "w") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
