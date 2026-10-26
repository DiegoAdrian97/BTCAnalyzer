"""
Aprendizaje automatico del analista: aprende de sus propias predicciones acertadas y erradas.

Para cada plazo repasa las ultimas REPASO predicciones que habria hecho (cada una calculada solo con lo que se
sabia en ese momento, sin mirar el futuro) y las compara con lo que paso de verdad. No se casa con un solo
metodo: junta un equipo de "expertos" y aprende cuanto creerle a cada uno.

Los expertos:
1. Las RECETAS de "situaciones parecidas": cada una compara rasgos distintos (medias, RSI, MACD, volatilidad,
   Bollinger...) y cuenta como terminaron los casos parecidos del pasado.
2. Un modelo que aprende solo (regresion logistica en linea): mira 20 numeros de cada vela (movimientos recientes
   medidos en ATR, distancia a las medias, RSI, MACD, Bollinger, volatilidad, volumen, hora del dia, fin de
   semana) y ajusta sus pesos un poquito con cada resultado nuevo, desde el principio de la historia.
3. La tasa base: lo que pasa normalmente, sin mirar nada. Es la vara contra la que se mide todo.

La mezcla: pesos exponenciales (Hedge) con "reparto fijo": cada resultado nuevo baja el peso de los expertos que
se equivocaron y sube el de los que acertaron; una pequena parte del peso se reparte siempre entre todos, para que
el equipo se adapte rapido cuando el mercado cambia de humor. Encima, una confianza aprendida: si las
probabilidades del equipo vienen exageradas las modera; si vienen timidas, las refuerza.

Medicion honesta: cada prediccion se juzga con los pesos y la confianza que habia ANTES de conocer el resultado,
y un resultado solo se usa para aprender cuando ya se conoce (h velas despues). Se compara contra la tasa base
(habilidad: cuanto mejor que "lo de siempre") y contra el metodo original, con el margen de error de los aciertos
(intervalo de Wilson del 95%), y aparte los aciertos cuando se anima (probabilidad lejos del 50%).

Todo sale de las velas (no de un archivo): no se pierde aunque Render borre el disco al dormirse. Las cuentas usan
solo sumas, restas, productos, divisiones y raices (nada de exp ni senos de la libreria), asi Python y JavaScript
dan exactamente los mismos numeros.

Traduccion 1:1 en JavascriptVersion/aprendizaje.js: mismas cuentas, mismos numeros.
"""

import indicadores as ind

MIN_CASOS = 40          # casos parecidos minimos para usar una situacion (como en el analisis)
MIN_EXPERIENCIA = 300   # velas de historia antes de la primera prediccion repasada
REPASO = 1000           # predicciones que se repasan por plazo (las mas recientes)
ARRANQUE = 60           # predicciones repasadas antes de empezar a medir (el equipo se acomoda)
HISTERESIS = 0.004      # cambia de confianza solo si lo nuevo viene al menos 0,4% mejor (no por ruido)
VENTANA = 150           # predicciones por punto de la curva de aprendizaje
PUNTOS_CURVA = 30
VOL_N = 100             # velas para el ATR promedio (volatilidad alta o baja)
# confianza en las propias probabilidades: 1 = tal cual, menos = las modera hacia 50%, mas = las refuerza.
# El orden decide los empates: ante la duda, sin cambios.
FACTORES = (1.0, 0.75, 0.5, 0.25, 0.0, 1.25, 1.5)
# escalones "redondos" de 1, 2,5 y 5 por cada potencia de 10: sirven para BTC (25, 50, 100...) y para ZEC (0,5, 1, 2,5...)
NICE_STEPS = tuple(m * 10.0 ** k for k in range(-4, 6) for m in (1, 2.5, 5))
ETA = 2.0               # cuanto castiga Hedge cada error (sobre el error cuadratico de las dos predicciones)
REPARTO = 0.05          # parte del peso que se reparte entre todos en cada paso (adaptarse a cambios)
TASA = 0.0005          # paso de aprendizaje del modelo (chico: con datos reales, mas grande se cree casualidades)
L2 = 0.001              # freno del modelo (que no se crea patrones de casualidad)
SEGURA = 0.08           # "se anima": probabilidad al menos 8 puntos lejos del 50%

RASGOS = ("precio vs EMA 50", "precio vs EMA 200", "RSI", "movimiento del último día", "MACD", "volatilidad",
          "Bollinger")
NIVELES = (2, 2, 4, 3, 2, 2, 4)      # valores posibles de cada rasgo
# la primera es la receta original del analista
RECETAS = ((0, 1, 2, 3), (0, 2, 4), (1, 3, 5), (2, 6, 5), (4, 6, 0, 3), (3, 5, 2), (0, 1, 5, 6), (2, 4, 3, 5))
MODELO = len(RECETAS)                # indice del experto "modelo" en la lista de expertos
BASE = len(RECETAS) + 1              # indice del experto "tasa base"
EXPERTOS = len(RECETAS) + 2

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


def experto_txt(e):
    if e == MODELO:
        return "el modelo que aprende solo"
    if e == BASE:
        return "la tasa base"
    return "casos parecidos por " + receta_txt(e)


def confianza_txt(f):
    if f == 1.0:
        return "Usa sus probabilidades tal cual"
    if f == 0.0:
        return "No encontró ventaja: lo trata como una moneda"
    if f < 1.0:
        return f"Modera sus probabilidades al {int(f * 100)}%: venían exageradas"
    return f"Refuerza sus probabilidades al {int(f * 100)}%: venían tímidas"


def expo(x):
    """e elevado a x (x <= 0) solo con sumas y productos: identico en Python y en JavaScript."""
    if x < -60.0:
        x = -60.0
    y = x / 1024.0
    r = 1.0 + y * (1.0 + y / 2.0 * (1.0 + y / 3.0 * (1.0 + y / 4.0 * (1.0 + y / 5.0))))
    for _ in range(10):
        r = r * r
    return r


def sigmoide(z):
    if z >= 0:
        return 1.0 / (1.0 + expo(-z))
    e = expo(z)
    return e / (1.0 + e)


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


def _corte(x, a=4.0):
    return -a if x < -a else a if x > a else x


def continuos(bars, tf_min, e50, e200, rsi, mh, parcial=False):
    """Lo que mira el modelo en cada vela: 20 numeros chicos (o None mientras arrancan los indicadores).

    Movimientos medidos en ATR (asi valen igual con BTC a 20.000 o a 100.000), distancia a las medias, RSI, MACD,
    posicion en las Bollinger, volatilidad y volumen contra su promedio, rango y cierre de la vela, franja horaria
    (UTC, de a 4 horas) y fin de semana. parcial: la ultima vela todavia no cerro (su volumen va neutro).
    """
    n = len(bars)
    o = [b[1] for b in bars]
    h = [b[2] for b in bars]
    l = [b[3] for b in bars]
    c = [b[4] for b in bars]
    v = [b[5] for b in bars]
    atr_ = ind.dmi(h, l, c)[3]
    mid, bu, bl = ind.bollinger(c)
    look = max(1, 1440 // tf_min)
    raiz = 1.0
    while (raiz + 1.0) * (raiz + 1.0) <= look:
        raiz += 1.0
    out = [None] * n
    acc_a, acc_v = 0.0, 0.0
    for i in range(n):
        acc_a += atr_[i] if atr_[i] is not None else 0.0
        if i >= VOL_N:
            acc_a -= atr_[i - VOL_N] if atr_[i - VOL_N] is not None else 0.0
        acc_v += v[i]
        if i >= 20:
            acc_v -= v[i - 20]
        a = atr_[i]
        if i < max(VOL_N, look, 12) or a is None or a <= 0 or rsi[i] is None or bu[i] is None or mh[i] is None:
            continue
        avg_a, avg_v = acc_a / VOL_N, acc_v / 20
        rango = h[i] - l[i]
        hora = (bars[i][0] // 3_600_000) % 24
        dia = (bars[i][0] // 86_400_000 + 3) % 7          # 0 = lunes
        franja = hora // 4
        x = [_corte((c[i] - c[i - 1]) / a),
             _corte((c[i] - c[i - 3]) / a / 1.7),
             _corte((c[i] - c[i - 12]) / a / 3.5),
             _corte((c[i] - c[i - look]) / a / raiz),
             _corte((c[i] - e50[i]) / a / 3.0),
             _corte((c[i] - e200[i]) / a / 6.0),
             (rsi[i] - 50.0) / 15.0,
             _corte(mh[i] / a * 3.0),
             _corte((c[i] - mid[i]) / (bu[i] - mid[i])) if bu[i] > mid[i] else 0.0,
             _corte(a / avg_a - 1.0) if avg_a > 0 else 0.0,
             0.0 if (parcial and i == n - 1) or avg_v <= 0 else _corte(v[i] / avg_v - 1.0, 3.0),
             _corte(rango / a - 1.0),
             ((c[i] - l[i]) / rango - 0.5) * 2.0 if rango > 0 else 0.0,
             _corte((c[i] - o[i]) / a)]
        x += [1.0 if franja == k else 0.0 for k in range(6)]
        x.append(1.0 if dia >= 5 else 0.0)
        out[i] = x
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


def wilson(k, n):
    """Intervalo del 95% de una proporcion (en %): con pocos casos es ancho, con muchos se achica."""
    if not n:
        return None, None
    z2 = 1.96 * 1.96
    p = k / n
    centro = (p + z2 / (2 * n)) / (1 + z2 / n)
    radio = 1.96 * (p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5 / (1 + z2 / n)
    return (centro - radio) * 100, (centro + radio) * 100


class _Logistica:
    """Regresion logistica en linea (una por cosa a predecir): un pasito de descenso por cada resultado nuevo."""

    def __init__(self, d):
        self.w = [0.0] * (d + 1)

    def prob(self, x):
        w = self.w
        z = w[-1]
        for k in range(len(x)):
            z += w[k] * x[k]
        return sigmoide(z)

    def aprender(self, x, y):
        w = self.w
        g = self.prob(x) - y
        for k in range(len(x)):
            w[k] -= TASA * (g * x[k] + L2 * w[k])
        w[-1] -= TASA * g


def _base(tot):
    return (tot[1] / tot[0] if tot[0] else 0.5), (tot[2] / tot[3] if tot[3] else 0.5)


def _receta(tabs, tot, r, k):
    """Lo que dice una receta: como terminaron los casos parecidos (si son pocos, con menos rasgos)."""
    for L in range(len(RECETAS[r]) - 1, -1, -1):
        tn, tu, ts, tf = tabs[r][L]
        p = PROY[r][L][k]
        if tn[p] >= MIN_CASOS:
            return tu[p] / tn[p], (ts[p] / tf[p] if tf[p] else 0.5)
    return _base(tot)


def _equipo(tabs, tot, m_sube, m_prim, k, x):
    """Lo que dice cada experto para una vela (None si esa vela no tiene rasgos)."""
    if k is None:
        return None
    preds = [_receta(tabs, tot, r, k) for r in range(len(RECETAS))]
    preds.append((m_sube.prob(x), m_prim.prob(x)) if x is not None else _base(tot))
    preds.append(_base(tot))
    return preds


def _mezclar(pesos, preds):
    ps, pf = 0.0, 0.0
    for e in range(EXPERTOS):
        ps += pesos[e] * preds[e][0]
        pf += pesos[e] * preds[e][1]
    return ps, pf


def prediccion(res, k, x):
    """La prediccion de ahora (sube, toca primero arriba) para la vela en curso, con lo aprendido hasta la ultima
    vela cerrada. Es liviana: aprender() se rehace solo cuando cierra una vela."""
    if not res or k is None:
        return None, None
    st = res["_estado"]
    preds = _equipo(st["tabs"], st["tot"], st["m_sube"], st["m_prim"], k, x)
    ps, pf = _mezclar(res["pesos"], preds)
    return ajustar(ps, res["factor"]), ajustar(pf, res["factor"])


def aprender(bars, combo, h, warmup, X=None):
    """Repasa las ultimas predicciones a h velas y devuelve lo aprendido, o None si falta historia.

    bars: velas cerradas. combo: combos(rasgos(...)) y X: continuos(...) de esas velas; pueden traer una vela mas
    al final (la que esta en curso): con ella se arma la prediccion de ahora.
    Se juzgan dos predicciones: si cierra mas arriba dentro de h velas y que toca primero, +distancia o -distancia
    (la distancia tipica del plazo, como en el analisis).
    """
    n = len(bars)
    c = [b[4] for b in bars]
    end = n - 1 - h                       # ultima vela con resultado conocido
    t0 = max(warmup + MIN_EXPERIENCIA, end - REPASO + 1)
    if end - t0 + 1 < 2 * ARRANQUE:
        return None
    if X is None:
        X = [None] * len(combo)
    ends = sorted(c[j + h] / c[j] - 1 for j in range(warmup, end + 1))
    q = lambda p: ends[min(int(p * len(ends)), len(ends) - 1)]
    price = c[-1]
    spread = (q(0.9) - q(0.1)) * price
    unit = min(NICE_STEPS, key=lambda s: abs(s - spread / 4))
    unit = int(unit) if unit >= 1 else unit
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

    d = next((len(x) for x in X if x is not None), 0)
    m_sube, m_prim = _Logistica(d), _Logistica(d)

    # experiencia: cuantas veces se vio cada situacion y como termino (por receta y por largo de receta)
    cn, cu, cs, cf = [0] * COMBOS, [0] * COMBOS, [0.0] * COMBOS, [0] * COMBOS
    tot = [0, 0, 0.0, 0]
    for j in range(warmup, t0 - h + 1):
        x = X[j]
        if x is not None:
            m_sube.aprender(x, sube[j])
            if prim[j] is not None:
                m_prim.aprender(x, prim[j])
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
        x = X[j]
        pj = prim[j]
        if x is not None:
            m_sube.aprender(x, sube[j])
            if pj is not None:
                m_prim.aprender(x, pj)
        k = combo[j]
        if k is None:
            return
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

    def equipo(t):
        return _equipo(tabs, tot, m_sube, m_prim, combo[t], X[t])

    E, K = EXPERTOS, len(FACTORES)
    pesos = [1.0 / E] * E
    score = [0.0] * K                     # error de cada confianza sobre la mezcla
    factor = 0
    pend = {}                             # predicciones esperando su resultado: t -> (expertos, mezcla)
    cambios, lider, m = 0, None, 0
    # aprendido, original (receta 0 tal cual) y tasa base: suma del error cuadratico, predicciones medidas,
    # aciertos y decisivas en "que toca primero"
    ap, og, bs = [0.0, 0, 0, 0], [0.0, 0, 0, 0], [0.0, 0, 0, 0]
    seg = [0, 0]                          # aciertos y casos cuando se anima
    sep = [0, 0.0, 0, 0.0]                # mas chances arriba que lo normal: casos y arriba; menos: casos y arriba
    serie = []                            # por prediccion medida: error aprendido, original y tasa base

    def error(ps, pf, os_, of):
        e = (ps - os_) * (ps - os_)
        if of is not None:
            e += (pf - of) * (pf - of)
        return e

    def medir(st, ps, pf, os_, of):
        e = error(ps, pf, os_, of)
        st[0] += e
        st[1] += 1 if of is None else 2
        hit = None
        if of is not None and of != 0.5 and pf != 0.5:
            hit = 1 if (pf > 0.5) == (of == 1.0) else 0
            st[2] += hit
            st[3] += 1
        return e, hit

    def resolver(t):
        """El resultado de la prediccion de la vela t ya se conoce: ajustar pesos y confianza."""
        got = pend.pop(t, None)
        if got is None:
            return
        preds, mix = got
        os_, of = sube[t], prim[t]
        tot_w = 0.0
        for e in range(E):
            pesos[e] *= expo(-ETA * error(preds[e][0], preds[e][1], os_, of))
            tot_w += pesos[e]
        for e in range(E):
            pesos[e] = (1.0 - REPARTO) * pesos[e] / tot_w + REPARTO / E
        for k in range(K):
            f = FACTORES[k]
            score[k] += error(ajustar(mix[0], f), ajustar(mix[1], f), os_, of)

    for t in range(t0, end + 1):
        resolver(t - h)                   # el resultado de t - h se conoce al cerrar la vela t
        if m >= ARRANQUE:
            best = 0
            for k in range(K):
                if score[k] < score[best]:
                    best = k
            if best != factor and score[best] < score[factor] * (1 - HISTERESIS):
                factor = best
        preds = equipo(t)
        if preds is not None:
            mix = _mezclar(pesos, preds)
            if m >= ARRANQUE:             # desde aca se mide: el equipo ya tuvo tiempo de acomodarse
                f_ = FACTORES[factor]
                ps, pf = ajustar(mix[0], f_), ajustar(mix[1], f_)
                os_, of = sube[t], prim[t]
                e_ap, h_ap = medir(ap, ps, pf, os_, of)
                e_og, _ = medir(og, preds[0][0], preds[0][1], os_, of)
                e_bs, _ = medir(bs, preds[BASE][0], preds[BASE][1], os_, of)
                if h_ap is not None and (pf - 0.5 >= SEGURA or 0.5 - pf >= SEGURA):
                    seg[0] += h_ap
                    seg[1] += 1
                if of is not None and of != 0.5:
                    # separa bien? (con la mezcla antes de la confianza: aunque la modere a 50%, se ve si sabe algo)
                    pb, pm = preds[BASE][1], mix[1]
                    if pm > pb:
                        sep[0] += 1
                        sep[1] += of
                    elif pm < pb:
                        sep[2] += 1
                        sep[3] += of
                serie.append((e_ap, e_og, e_bs))
                top = 0
                for e in range(E):
                    if pesos[e] > pesos[top]:
                        top = e
                if lider is not None and top != lider:
                    cambios += 1
                lider = top
            pend[t] = (preds, mix)
            m += 1
        sumar(t + 1 - h)

    # para la prediccion de ahora: con todo lo que se sabe hasta la ultima vela cerrada
    for t in range(end + 1 - h, end + 1):
        resolver(t)
    for j in range(end + 2 - h, end + 1):
        sumar(j)

    # curva: ventaja sobre la tasa base (cuanto menos error, en %) en ventanas moviles de VENTANA predicciones
    curva = []
    if len(serie) >= VENTANA:
        paso = max(1, (len(serie) - VENTANA) // (PUNTOS_CURVA - 1))
        idxs = list(range(VENTANA - 1, len(serie), paso))
        if idxs[-1] != len(serie) - 1:
            idxs.append(len(serie) - 1)
        for i in idxs:
            a = o = b = 0.0
            for x in serie[i - VENTANA + 1:i + 1]:
                a += x[0]
                o += x[1]
                b += x[2]
            curva.append((i + 1, (1 - a / b) * 100 if b > 0 else None, (1 - o / b) * 100 if b > 0 else None))

    # margenes de error honestos: predicciones a h velas que se pisan comparten resultado, asi que cuentan
    # como 1 de cada h (con h = 12, 600 predicciones valen como 50 independientes)
    lo, hi = wilson(ap[2] / h, ap[3] / h)
    sep_arriba = sep[1] / sep[0] * 100 if sep[0] else None
    sep_abajo = sep[3] / sep[2] * 100 if sep[2] else None
    margen_sep = None
    if sep[0] >= h and sep[2] >= h and sep_arriba is not None and sep_abajo is not None:
        p1, p2 = sep_arriba / 100, sep_abajo / 100
        margen_sep = 196 * (p1 * (1 - p1) / (sep[0] / h) + p2 * (1 - p2) / (sep[2] / h)) ** 0.5
    recetas = sorted(range(len(RECETAS)), key=lambda e: (-pesos[e], e))
    ranking = sorted(range(E), key=lambda e: (-pesos[e], e))
    br = lambda st: st[0] / st[1] if st[1] else None
    pct = lambda a, b: a / b * 100 if b else None
    return {"receta": recetas[0], "factor": FACTORES[factor], "repasadas": m, "desde": bars[t0][0],
            "hasta": bars[end][0], "cambios": cambios, "distancia": unit,
            "brier_aprendido": br(ap), "brier_original": br(og), "brier_base": br(bs),
            "habilidad": (1 - br(ap) / br(bs)) * 100 if br(ap) is not None and br(bs) else None,
            "habilidad_original": (1 - br(og) / br(bs)) * 100 if br(og) is not None and br(bs) else None,
            "aciertos_aprendido": pct(ap[2], ap[3]), "decisivas_aprendido": ap[3],
            "aciertos_original": pct(og[2], og[3]), "decisivas_original": og[3],
            "ic_bajo": lo, "ic_alto": hi, "independientes": ap[3] // h,
            "aciertos_seguro": pct(seg[0], seg[1]), "decisivas_seguro": seg[1],
            "sep_arriba": sep_arriba, "sep_abajo": sep_abajo, "margen_sep": margen_sep,
            "pesos": pesos[:], "ranking": ranking, "medidas": len(serie), "curva": curva,
            "_estado": {"tabs": tabs, "tot": tot, "m_sube": m_sube, "m_prim": m_prim}}


_CACHE = {}


def aprendido(clave, bars, combo, h, warmup, X=None):
    """aprender() solo cuando cerro una vela nueva: mientras tanto el resultado es el mismo."""
    stamp = (len(bars), bars[-1][0], h, warmup)
    hit = _CACHE.get(clave)
    if hit and hit[0] == stamp:
        return hit[1]
    res = aprender(bars, combo, h, warmup, X)
    _CACHE[clave] = (stamp, res)
    return res
