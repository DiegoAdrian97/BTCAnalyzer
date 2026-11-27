"""Zonas de compra y de venta del ciclo de BTC (medidas con medir_zonas.py, nov. 2026).

Criterio: estando en la zona (aunque dure meses), a un año BTC subio 10 puntos o mas que un dia cualquiera (zona de
compra) o 10 o menos (venta), en 2012-19 y en 2020-25. Un dia cualquiera: subio a un año 78% (2012-19) y 60% (2020-25).
No marcan el punto exacto: marcan zonas. Quedaron afuera porque no separaron en los dos tramos: Delta Price, hash
ribbons, Fear & Greed y el RSI semanal como zona de venta; NUPL es el MVRV escrito de otra forma (no se repite).

armar_termometro.py llama a calcular() cada semana y guarda el resultado en termometro.json ("zonas"); la pagina lo
termina con el precio de ahora: para los que dependen del precio guarda un multiplicador (valor = precio x k).
"""

import numpy as np

# id, nombre, como se calcula, zona de compra, zona de venta, lo medido (a 365 dias: % que subio en 2012-19 / 2020-25)
# zona: ("<=", numero) umbral clasico, ("p", 15) percentil de su historia, None: no sirvio para ese lado;
# ("p>=", 85) en compra y ("p<=", 15) en venta: la zona es cuando el valor esta ALTO (compra) o BAJO (venta)
ZONAS = (
    ("puell", "Puell (emisión del día / media del año)", ("<=", 0.5), ("p", 85), "96–99%", "30–50%"),
    ("mayer", "Mayer (precio / media de 200 días)", None, (">=", 2.4), None, "38–47%"),
    ("ma2a", "Media de 2 años", ("<=", 1.0), ("p", 85), "94–100%", "10–49%"),
    ("ma200s", "Media de 200 semanas", ("<=", 1.0), (">=", 4.0), "100%", "21–39%"),
    ("golden", "Golden Ratio (precio / media de 350 días)", ("<=", 0.8), (">=", 3.0), "83–89%", "19–45%"),
    ("pi", "Pi Cycle (media de 111 / 2 × media de 350)", ("<=", 0.35), ("p", 85), "100%", "0%"),
    ("potencia", "Ley de potencia (desvío del ajuste)", ("p", 15), ("p", 85), "89–100%", "15–33%"),
    ("metcalfe", "Metcalfe (precio contra direcciones activas)", None, ("p", 85), None, "39–48%"),
    # lo descartado, medido otra vez como zonas (medir_zonas2.py, nov. 2026): sirven solas y no empeoran el conjunto
    ("dias_max", "Días desde el máximo histórico", ("p>=", 85), None, "100%", None),          # mucho tiempo sin maximo: compra
    ("thermocap", "Thermocap (capitalización / emisión acumulada)", None, ("p", 85), None, "17–50%"),
    ("hash", "Hash ribbons (hashrate 30 / 60 días)", ("p", 10), None, "70–100%", None),        # mineros capitulando: compra
    ("stable", "Emisión de stablecoins (90 días)", ("p", 10), None, "+28 a +34", None),       # casi no se emiten: compra
    # on-chain de looknode y bitcoin-data (medir_zonas3.py, nov. 2026): pasaron la regla en los dos tramos y no empeoran el conjunto
    ("cvdd", "CVDD (precio / CVDD)", ("<=", 1.2), None, "100%", None),
    ("balanceado", "Precio balanceado (precio / balanced price)", ("p", 10), ("p", 90), "96–100%", "29–34%"),
    ("rhodl", "RHODL (ratio de plata de 1 semana contra 1–2 años)", ("p", 15), None, "99–100%", None),
    ("ganancia", "% de la oferta en ganancia", ("<=", 0.5), None, "91–100%", None),
    ("sth", "Precio realizado de corto plazo (STH)", None, ("p<=", 15), None, "33–45%"),      # precio bajo el costo de los compradores recientes: venta
    ("asopr", "aSOPR (30 días)", None, ("p", 85), None, "22–46%"),
    ("perdida", "Pérdida realizada (pico de 7 días contra el año)", ("p", 10), ("p", 90), "90–92%", "44–59%"),
)


def _sma(x, n):
    c = np.cumsum(np.insert(np.nan_to_num(x), 0, 0.0))
    out = np.full(len(x), np.nan)
    out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def _ult(x, vence=5):
    """Posicion del ultimo dato finito, si es de los ultimos `vence` dias (None si no)."""
    ix = np.flatnonzero(np.isfinite(x))
    return int(ix[-1]) if len(ix) and len(x) - 1 - ix[-1] <= vence else None


def _media_min(x, w, minimo):
    """Media movil de w dias con al menos `minimo` datos en la ventana (np.nan si no)."""
    ok = np.isfinite(x)
    c = np.cumsum(np.insert(np.where(ok, x, 0.0), 0, 0.0))
    k = np.cumsum(np.insert(ok.astype(float), 0, 0.0))
    out = np.full(len(x), np.nan)
    if len(x) >= w:
        cnt = k[w:] - k[:-w]
        out[w - 1:] = np.where(cnt >= minimo, (c[w:] - c[:-w]) / np.maximum(cnt, 1), np.nan)
    return out


def _pico(x, w=7, base=365):
    """Suma de w dias / (promedio diario de los `base` dias previos a esa ventana x w). Solo pasado (igual que
    medir_onchain_ciclo.pico_vs_año): mas de 1 = mas de lo normal."""
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    pre = np.cumsum(np.insert(np.where(ok, np.abs(x), 0.0), 0, 0.0))
    cnt = np.cumsum(np.insert(ok.astype(float), 0, 0.0))
    out = np.full(len(x), np.nan)
    for i in range(w + base - 1, len(x)):
        if cnt[i + 1] - cnt[i + 1 - w] < w:
            continue
        nb = cnt[i + 1 - w] - cnt[i + 1 - w - base]
        if nb < 0.8 * base:
            continue
        b = (pre[i + 1 - w] - pre[i + 1 - w - base]) / nb * w
        if b > 0:
            out[i] = (pre[i + 1] - pre[i + 1 - w]) / b
    return out


def calcular(dia, P, sup, iss_usd, adr, hashrate=None, stable=None, extra=None):
    """dia: dias desde 1970 (int), P: precio, sup: BTC en circulacion, iss_usd: emision del dia en USD, adr: direcciones
    activas (np.nan si falta). extra: series alineadas a `dia` (np.nan si falta) de looknode y bitcoin-data: lineas
    "cvdd", "balanceado" y "sth" (precio de cada una), "rhodl", "asopr" y "perdida" (diarios) y "ganancia" (fraccion de
    la oferta en ganancia); lo que falte se omite. Devuelve la lista de zonas con lo que la pagina necesita para hoy."""
    P = np.asarray(P, float)
    n = len(P)
    out = []
    extra = extra or {}

    def umbral(serie, z):
        if z is None:
            return None
        if z[0] in ("p", "p>=", "p<="):
            v = serie[np.isfinite(serie)]
            return float(np.percentile(v, z[1])) if len(v) > 730 else None
        return float(z[1])

    for zid, nom, zc, zv, mc, mv in ZONAS:
        e = {"id": zid, "nombre": nom, "compra_medido": mc, "venta_medido": mv}
        if zid in ("mayer", "ma2a", "ma200s", "golden"):
            k = {"mayer": 200, "ma2a": 730, "ma200s": 1400, "golden": 350}[zid]
            m = _sma(P, k)
            serie = P / m
            e["k"] = 1.0 / float(m[-1])                      # valor de hoy = precio x k
        elif zid == "pi":
            serie = _sma(P, 111) / (2 * _sma(P, 350))
            e["valor"] = float(serie[-1])
        elif zid == "puell":
            ma = _sma(np.asarray(iss_usd, float), 365)
            serie = np.asarray(iss_usd, float) / ma
            # hoy: BTC emitidos por dia (promedio del ultimo mes) x precio / media del año en USD
            btc = np.nanmean((np.asarray(iss_usd, float) / P)[-30:])
            e["k"] = float(btc / ma[-1])
        elif zid == "metcalfe":
            a30 = _sma(np.asarray(adr, float), 30)
            serie = P * np.asarray(sup, float) / a30 ** 2
            e["k"] = float(sup[-1] / a30[-1] ** 2) if np.isfinite(a30[-1]) else None
        elif zid == "potencia":
            gen = 14247                                       # 3/1/2009 en dias desde 1970
            lx = np.log10(np.asarray(dia, float) - gen)
            ly = np.log10(P)
            ok = np.isfinite(lx) & np.isfinite(ly)
            b, a = np.polyfit(lx[ok], ly[ok], 1)
            serie = ly - (a + b * lx)
            e.update({"a": float(a), "b": float(b), "gen": gen})   # valor de hoy = log10(precio) - (a + b log10(dias))
        elif zid == "dias_max":
            mx = np.maximum.accumulate(P)
            ult = np.zeros(n)
            u = 0
            for i in range(n):
                if P[i] >= mx[i]:
                    u = i
                ult[i] = i - u
            serie = ult
            i_ath = int(np.argmax(P))
            e.update({"ath": float(P[i_ath]), "ath_dia": int(dia[i_ath])})   # hoy: dias desde ath_dia (0 si el precio lo supera)
        elif zid == "thermocap":
            acum = np.cumsum(np.nan_to_num(np.asarray(iss_usd, float)))
            serie = P * np.asarray(sup, float) / np.where(acum > 0, acum, np.nan)
            e["k"] = float(sup[-1] / acum[-1])
        elif zid == "hash" and hashrate is not None:
            h = np.asarray(hashrate, float)
            serie = _sma(h, 30) / _sma(h, 60)
            if not np.isfinite(serie[-1]):
                continue
            e["valor"] = float(serie[-1])
        elif zid == "stable" and stable is not None:
            st = np.asarray(stable, float)
            serie = np.full(n, np.nan)
            serie[90:] = st[90:] / st[:-90] - 1
            if not np.isfinite(serie[-1]):
                continue
            e["valor"] = float(serie[-1])
        elif zid in ("cvdd", "balanceado", "sth") and extra.get(zid) is not None:
            L = np.asarray(extra[zid], float)
            L = np.where(L > 0, L, np.nan)
            i = _ult(L)
            if i is None:
                continue
            serie = P / L
            e["k"] = 1.0 / float(L[i])                       # valor de hoy = precio x k (precio de ahora / la linea)
        elif zid in ("rhodl", "asopr", "perdida", "ganancia") and extra.get(zid) is not None:
            x = np.asarray(extra[zid], float)
            serie = {"rhodl": lambda: x, "asopr": lambda: _media_min(x, 30, 25), "perdida": lambda: _pico(x),
                     "ganancia": lambda: x}[zid]()
            i = _ult(serie, 10 if zid == "ganancia" else 5)
            if i is None:
                continue
            e["valor"] = float(serie[i])
            if zid == "ganancia":
                e["dia"] = int(dia[i])                       # se publica cada tanto: el valor es el ultimo publicado
        if e.get("k") is None and "valor" not in e and "a" not in e and "ath" not in e:
            continue
        e["compra"] = umbral(serie, zc)
        if zc is not None and zc[0] == "p>=":
            e["compra_dir"] = ">="                  # compra cuando el valor es ALTO (dias desde el maximo)
        e["venta"] = umbral(serie, zv)
        if zv is not None and zv[0] == "p<=":
            e["venta_dir"] = "<="                   # venta cuando el valor es BAJO (precio bajo el costo de los compradores recientes)
        v = serie[np.isfinite(serie)]
        e["min"], e["max"] = float(np.percentile(v, 1)), float(np.percentile(v, 99))   # la escala de la barra
        e["log"] = zid in ("ma2a", "ma200s", "golden", "mayer", "puell", "metcalfe", "thermocap", "cvdd", "balanceado", "sth", "rhodl", "perdida")     # razones: escala logaritmica
        out.append({k: (float(f"{x:.8g}") if isinstance(x, float) else x) for k, x in e.items()})
    return out
