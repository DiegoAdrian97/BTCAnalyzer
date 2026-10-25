"""
Aprendizaje automatico del analista: aprende de sus propias predicciones acertadas y erradas.

Para cada plazo repasa las ultimas REPASO predicciones que habria hecho (cada una calculada solo con lo que se
sabia en ese momento, sin mirar el futuro), las compara con lo que paso de verdad y ajusta dos cosas:

1. La receta: que rasgos usar para buscar "situaciones parecidas" (medias, RSI, MACD, volatilidad, Bollinger...).
   Prueba RECETAS distintas en paralelo y se queda con la que mejor viene prediciendo.
2. La confianza: si sus probabilidades vienen exageradas las modera; si vienen tímidas, las refuerza.

Aprende en linea, como lo haria una persona: cada prediccion se juzga con la receta y la confianza que habia
elegido ANTES de conocer el resultado. Asi la comparacion contra el metodo original es honesta. Cada vela nueva
que cierra suma experiencia y el ajuste se recalcula solo. Como todo sale de las velas (no de un archivo), no
se pierde aunque Render borre el disco al dormirse.

Traduccion 1:1 en JavascriptVersion/aprendizaje.js: mismas cuentas, mismos numeros.
"""

import indicadores as ind

MIN_CASOS = 40          # casos parecidos minimos para usar una situacion (como en el analisis)
MIN_EXPERIENCIA = 300   # velas de historia antes de la primera prediccion repasada
REPASO = 600            # predicciones que se repasan por plazo (las mas recientes)
ARRANQUE = 60           # predicciones repasadas antes de animarse a cambiar de receta
HISTERESIS = 0.004      # cambia de idea solo si lo nuevo viene al menos 0,4% mejor (no por ruido)
VENTANA = 120           # predicciones por punto de la curva de aprendizaje
PUNTOS_CURVA = 30
VOL_N = 100             # velas para el ATR promedio (volatilidad alta o baja)
# confianza en las propias probabilidades: 1 = tal cual, menos = las modera hacia 50%, mas = las refuerza.
# El orden decide los empates: ante la duda, sin cambios.
FACTORES = (1.0, 0.75, 0.5, 0.25, 0.0, 1.25, 1.5)
NICE_STEPS = (25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)

RASGOS = ("precio vs EMA 50", "precio vs EMA 200", "RSI", "movimiento del último día", "MACD", "volatilidad",
          "Bollinger")
NIVELES = (2, 2, 4, 3, 2, 2, 4)      # valores posibles de cada rasgo
# la primera es la receta original del analista; si no aparece algo mejor, se queda con ella
RECETAS = ((0, 1, 2, 3), (0, 2, 4), (1, 3, 5), (2, 6, 5), (4, 6, 0, 3), (3, 5, 2), (0, 1, 5, 6), (2, 4, 3, 5))

COMBOS = 1
for _v in NIVELES:
    COMBOS *= _v


def _combo(f):
    k = 0
    for v, x in zip(NIVELES, f):
        k = k * v + x
    return k


def _decodificar(k):
    f = []
    for v in reversed(NIVELES):
        f.append(k % v)
        k //= v
    return tuple(reversed(f))


def _codigo(f, idx):
    k = 0
    for i in idx:
        k = k * NIVELES[i] + f[i]
    return k


# para cada receta y cada largo de receta (de 1 rasgo a todos): la situacion de cada combinacion de rasgos
_TODAS = [_decodificar(k) for k in range(COMBOS)]
PROY = [[[_codigo(f, receta[:n]) for f in _TODAS] for n in range(1, len(receta) + 1)] for receta in RECETAS]
TAM = [[_codigo(tuple(v - 1 for v in NIVELES), receta[:n]) + 1 for n in range(1, len(receta) + 1)] for receta in RECETAS]


def lista(nombres):
    return nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1]


def receta_txt(r, n=None):
    receta = RECETAS[r]
    return lista([RASGOS[i] for i in receta[:len(receta) if n is None else n]])


def confianza_txt(f):
    if f == 1.0:
        return "Usa sus probabilidades tal cual"
    if f == 0.0:
        return "No encontró ventaja: lo trata como una moneda"
    if f < 1.0:
        return f"Modera sus probabilidades al {int(f * 100)}%: venían exageradas"
    return f"Refuerza sus probabilidades al {int(f * 100)}%: venían tímidas"


def rasgos(bars, tf_min, e50, e200, rsi, mh):
    """Los rasgos de cada vela (enteros) o None mientras arrancan los indicadores. Solo usan datos hasta esa vela."""
    n = len(bars)
    c = [b[4] for b in bars]
    atr_ = ind.dmi([b[2] for b in bars], [b[3] for b in bars], c)[3]
    mid, bu, bl = ind.bollinger(c)
    look = max(1, 1440 // tf_min)
    vol, acc = [None] * n, 0.0
    for i in range(1, n):
        acc += atr_[i]
        if i > VOL_N:
            acc -= atr_[i - VOL_N]
        if i >= VOL_N:
            vol[i] = 1 if atr_[i] > acc / VOL_N else 0
    out = []
    for i in range(n):
        r = rsi[i]
        if r is None or i < look or vol[i] is None or bu[i] is None:
            out.append(None)
            continue
        move = c[i] / c[i - look] - 1
        bb = 3 if c[i] > bu[i] else 2 if c[i] >= mid[i] else 1 if c[i] >= bl[i] else 0
        out.append((1 if c[i] > e50[i] else 0, 1 if c[i] > e200[i] else 0,
                    0 if r < 35 else 1 if r < 50 else 2 if r < 65 else 3,
                    0 if move < -0.02 else 1 if move <= 0.02 else 2, 1 if mh[i] > 0 else 0, vol[i], bb))
    return out


def estados(feats, r):
    """La situacion de cada vela segun una receta: lo que compara el analisis para buscar casos parecidos."""
    receta = RECETAS[r]
    return [None if f is None else tuple(f[i] for i in receta) for f in feats]


def combos(feats):
    return [None if f is None else _combo(f) for f in feats]


def ajustar(p, f):
    """Probabilidad con la confianza aprendida (entre 0 y 1)."""
    return p if f == 1.0 else min(1.0, max(0.0, 0.5 + f * (p - 0.5)))


def aprender(bars, combo, h, warmup):
    """Repasa las ultimas predicciones a h velas y devuelve la receta y la confianza aprendidas, o None.

    bars: velas cerradas. combo: combos(rasgos(...)) de esas velas (o de mas, se usan las primeras).
    Se juzgan dos predicciones: si cierra mas arriba dentro de h velas y que toca primero, +distancia o -distancia
    (la distancia tipica del plazo, como en el analisis).
    """
    n = len(bars)
    c = [b[4] for b in bars]
    end = n - 1 - h                       # ultima vela con resultado conocido
    t0 = max(warmup + MIN_EXPERIENCIA, end - REPASO + 1)
    if end - t0 + 1 < 2 * ARRANQUE:
        return None
    ends = sorted(c[j + h] / c[j] - 1 for j in range(warmup, end + 1))
    q = lambda p: ends[min(int(p * len(ends)), len(ends) - 1)]
    price = c[-1]
    spread = (q(0.9) - q(0.1)) * price
    unit = min(NICE_STEPS, key=lambda s: abs(s - spread / 4))
    rel = unit / price

    sube, prim = [0] * n, [None] * n
    for j in range(warmup, end + 1):
        sube[j] = 1 if c[j + h] > c[j] else 0
        for k in range(1, h + 1):
            a = bars[j + k][2] / c[j] - 1 >= rel
            b = bars[j + k][3] / c[j] - 1 <= -rel
            if a or b:
                prim[j] = 0.5 if a and b else 1.0 if a else 0.0
                break

    # experiencia: cuantas veces se vio cada situacion y como termino (por receta y por largo de receta)
    cn, cu, cs, cf = [0] * COMBOS, [0] * COMBOS, [0.0] * COMBOS, [0] * COMBOS
    tot = [0, 0, 0.0, 0]
    for j in range(warmup, t0 - h + 1):
        k = combo[j]
        if k is None:
            continue
        cn[k] += 1
        cu[k] += sube[j]
        tot[0] += 1
        tot[1] += sube[j]
        if prim[j] is not None:
            cs[k] += prim[j]
            cf[k] += 1
            tot[2] += prim[j]
            tot[3] += 1
    tabs = []
    for r in range(len(RECETAS)):
        per = []
        for L in range(len(RECETAS[r])):
            size, proy = TAM[r][L], PROY[r][L]
            tn, tu, ts, tf = [0] * size, [0] * size, [0.0] * size, [0] * size
            for k in range(COMBOS):
                if cn[k]:
                    p = proy[k]
                    tn[p] += cn[k]
                    tu[p] += cu[k]
                    ts[p] += cs[k]
                    tf[p] += cf[k]
            per.append((tn, tu, ts, tf))
        tabs.append(per)

    def sumar(j):
        k = combo[j]
        if k is None:
            return
        pj = prim[j]
        tot[0] += 1
        tot[1] += sube[j]
        if pj is not None:
            tot[2] += pj
            tot[3] += 1
        for r in range(len(RECETAS)):
            for L in range(len(RECETAS[r])):
                tn, tu, ts, tf = tabs[r][L]
                p = PROY[r][L][k]
                tn[p] += 1
                tu[p] += sube[j]
                if pj is not None:
                    ts[p] += pj
                    tf[p] += 1

    def predecir(r, k):
        for L in range(len(RECETAS[r]) - 1, -1, -1):
            tn, tu, ts, tf = tabs[r][L]
            p = PROY[r][L][k]
            if tn[p] >= MIN_CASOS:
                return tu[p] / tn[p], (ts[p] / tf[p] if tf[p] else 0.5)
        return (tot[1] / tot[0] if tot[0] else 0.5), (tot[2] / tot[3] if tot[3] else 0.5)

    R, K = len(RECETAS), len(FACTORES)
    score = [[0.0] * K for _ in range(R)]
    elegida, cambios, m = (0, 0), 0, 0
    # aprendiz y original: suma de Brier, predicciones medidas, aciertos y decisivas en "que toca primero"
    ap, og = [0.0, 0, 0, 0], [0.0, 0, 0, 0]
    serie = []

    def medir(st, ps, pf, os_, of):
        e = (ps - os_) * (ps - os_)
        st[1] += 1
        hit = None
        if of is not None:
            e += (pf - of) * (pf - of)
            st[1] += 1
            if of != 0.5 and pf != 0.5:
                hit = 1 if (pf > 0.5) == (of == 1.0) else 0
                st[2] += hit
                st[3] += 1
        st[0] += e
        return hit

    for t in range(t0, end + 1):
        k0 = combo[t]
        if k0 is not None:
            preds = [predecir(r, k0) for r in range(R)]
            os_, of = sube[t], prim[t]
            if m >= ARRANQUE:      # desde aca el aprendiz ya pudo elegir distinto que el original
                r_, f_ = elegida[0], FACTORES[elegida[1]]
                h_ap = medir(ap, ajustar(preds[r_][0], f_), ajustar(preds[r_][1], f_), os_, of)
                h_og = medir(og, preds[0][0], preds[0][1], os_, of)
                serie.append((h_ap, h_og))
            for r in range(R):
                ps, pf = preds[r]
                row = score[r]
                for k in range(K):
                    f = FACTORES[k]
                    a = ajustar(ps, f) - os_
                    e = a * a
                    if of is not None:
                        b = ajustar(pf, f) - of
                        e += b * b
                    row[k] += e
            m += 1
            if m >= ARRANQUE:
                best = (0, 0)
                for r in range(R):
                    for k in range(K):
                        if score[r][k] < score[best[0]][best[1]]:
                            best = (r, k)
                cur = score[elegida[0]][elegida[1]]
                if best != elegida and score[best[0]][best[1]] < cur * (1 - HISTERESIS):
                    cambios += 1
                    elegida = best
        sumar(t + 1 - h)

    # curva: aciertos en "que toca primero" en ventanas moviles de VENTANA predicciones
    curva = []
    if len(serie) >= VENTANA:
        paso = max(1, (len(serie) - VENTANA) // (PUNTOS_CURVA - 1))
        idxs = list(range(VENTANA - 1, len(serie), paso))
        if idxs[-1] != len(serie) - 1:
            idxs.append(len(serie) - 1)
        for i in idxs:
            win = serie[i - VENTANA + 1:i + 1]
            vals = []
            for col in (0, 1):
                dec = [x[col] for x in win if x[col] is not None]
                vals.append(sum(dec) / len(dec) * 100 if len(dec) >= 20 else None)
            curva.append((i + 1, vals[0], vals[1]))

    r_, k_ = elegida
    mejor = [min(row) for row in score]
    return {"receta": r_, "factor": FACTORES[k_], "repasadas": m, "desde": bars[t0][0], "hasta": bars[end][0],
            "cambios": cambios, "distancia": unit,
            "brier_aprendido": ap[0] / ap[1] if ap[1] else None, "brier_original": og[0] / og[1] if og[1] else None,
            "aciertos_aprendido": ap[2] / ap[3] * 100 if ap[3] else None, "decisivas_aprendido": ap[3],
            "aciertos_original": og[2] / og[3] * 100 if og[3] else None, "decisivas_original": og[3],
            "medidas": len(serie), "curva": curva,
            "ranking": sorted(range(R), key=lambda r: (mejor[r], r))}


_CACHE = {}


def aprendido(clave, bars, combo, h, warmup):
    """aprender() solo cuando cerro una vela nueva: mientras tanto el resultado es el mismo."""
    stamp = (len(bars), bars[-1][0], h, warmup)
    hit = _CACHE.get(clave)
    if hit and hit[0] == stamp:
        return hit[1]
    res = aprender(bars, combo, h, warmup)
    _CACHE[clave] = (stamp, res)
    return res
