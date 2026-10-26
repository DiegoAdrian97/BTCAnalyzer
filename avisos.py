"""
Avisos al celular (WhatsApp y notificacion) desde el servidor de Render, que mira el mercado las 24 horas.

Que avisa (solo lo que se probo con velas reales de BTC):
- "Se viene movimiento fuerte": cuando el mercado se despierta (la volatilidad de las ultimas velas de 5 min pasa
  1,8 veces la habitual). Probado 2021-2026: la hora siguiente se mueve 2,3 veces lo normal (mediana) y mas del
  doble de lo normal el 59% de las veces (en una hora cualquiera, 15%). Unos 3 o 4 avisos por semana. No dice para
  donde: eso no se pudo predecir.
- "Zona grande de liquidaciones cerca": cuando el precio queda a menos de 0,4% de la zona mas grande de
  liquidaciones estimadas de cada lado (dentro de 3%). Es informativo: alli el movimiento se puede acelerar.
- Setups de entrada (largo o corto) con stop y objetivo, en BTC, ETH y ZEC: ruptura de 55 velas de 1 hora a favor
  de la tendencia de 4 horas (EMA 50 vs 200) y de la EMA 200 de 1 hora, con el mercado despierto (volatilidad de 1
  hora sobre la habitual). Cierre si en 72 horas no toco ni el stop ni el objetivo. Elegidos con 2021-24 y
  verificados con 2025-26 (velas de futuros de Binance, con comisiones):
    BTC y ETH: despierto > 1,5, stop 2,5 ATR, objetivo 1R. BTC 64-69% de aciertos, +0,22 a +0,35 R por operacion;
               ETH 61%, +0,22 R. Positivos 6 de 6 anos.
    ZEC:       despierto > 1,2, stop 2,5 ATR, objetivo 1,5R (en ZEC conviene dejar correr): 49%, +0,19 R, 6 de 6 anos;
               las 43 variantes que ganaban en 2021-24 tambien ganaron en 2025-26.
  Despues avisa si toco el objetivo o el stop. Las velas de ETH y ZEC se piden a Bybit una vez por hora.

Por donde (variables de entorno de Render; nunca en el codigo ni en el repositorio):
- TELEGRAM_TOKEN y TELEGRAM_CHAT: el token del bot (de @BotFather) y tu numero de usuario (de @userinfobot).
- NTFY_TEMA: el nombre secreto del tema en ntfy.sh (la app ntfy del iPhone, suscripta a ese tema).
- WHATSAPP_TEL y WHATSAPP_CLAVE: el numero (con +54...) y la clave que da CallMeBot.
Sin esas variables no se manda nada. Los avisos se guardan en memoria para no repetirlos.
"""

import json
import math
import os
import threading
import time
import urllib.parse
import urllib.request

DESPIERTA = 1.8            # volatilidad rapida / lenta para "se viene movimiento"
ESPERA_MOV = 4 * 3600      # no repetir el aviso de movimiento antes de 4 horas
CERCA_LIQ = 0.004          # 0,4% de la zona de liquidaciones
RANGO_LIQ = 0.03           # zonas dentro de 3% del precio
ESPERA_LIQ = 3 * 3600      # la misma zona no se avisa dos veces en 3 horas

HORAS = 72
_PIE = " Arriesgando 1% de la cuenta por operación: {cuenta}, peor caída {caida}. Es estadística del pasado, no una garantía."
SETUPS = {
    "BTC": {"ruptura": 55, "despierto": 1.5, "stop_atr": 2.5, "objetivo_r": 1.0, "simbolo": "BTC/USDT:USDT",
            "historial": "Historial 2021–2026 (con comisiones): 91 a 99 operaciones según la fuente de datos, ganó el "
                         "64–69%, +0,22 a +0,35 R por operación, positivo 5–6 de 6 años."
                         + _PIE.format(cuenta="+22% a +36%", caida="−3%")},
    "ETH": {"ruptura": 55, "despierto": 1.5, "stop_atr": 2.5, "objetivo_r": 1.0, "simbolo": "ETH/USDT:USDT",
            "historial": "Historial 2021–2026 (con comisiones): 93 operaciones, ganó el 61%, +0,22 R por operación, "
                         "positivo 6 de 6 años." + _PIE.format(cuenta="+22%", caida="−3%")},
    "ZEC": {"ruptura": 55, "despierto": 1.2, "stop_atr": 2.5, "objetivo_r": 1.5, "simbolo": "ZEC/USDT:USDT",
            "historial": "Historial 2021–2026 (con comisiones): 195 operaciones, ganó el 49% (el objetivo es 1,5 veces "
                         "el stop), +0,19 R por operación, positivo 6 de 6 años." + _PIE.format(cuenta="+44%", caida="−7%")},
}

_estado = {"mov": 0.0, "liq": {}, "arranque": False, "setup_t": {}, "abierta": {}, "velas": {}, "precio": {}}


def _ar(x, d=0):
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def configurado():
    return bool(os.environ.get("NTFY_TEMA") or (os.environ.get("WHATSAPP_TEL") and os.environ.get("WHATSAPP_CLAVE"))
                or (os.environ.get("TELEGRAM_TOKEN") and os.environ.get("TELEGRAM_CHAT")))


def enviar(titulo, texto, urgente=False):
    """Manda el aviso por los canales configurados. Un canal que falla no frena al otro."""
    tema = os.environ.get("NTFY_TEMA")
    if tema:
        try:
            body = json.dumps({"topic": tema, "title": titulo, "message": texto, "priority": 4 if urgente else 3})
            req = urllib.request.Request("https://ntfy.sh/", data=body.encode("utf-8"), headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10).read()
        except Exception as e:
            print(f"(aviso por ntfy no enviado: {type(e).__name__})", flush=True)
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT")
    if token and chat:
        try:
            body = json.dumps({"chat_id": chat, "text": f"{titulo}\n{texto}", "disable_web_page_preview": True})
            req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body.encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as e:
            print(f"(aviso por Telegram no enviado: {type(e).__name__})", flush=True)
    tel, clave = os.environ.get("WHATSAPP_TEL"), os.environ.get("WHATSAPP_CLAVE")
    if tel and clave:
        try:
            q = urllib.parse.urlencode({"phone": tel, "text": f"*{titulo}*\n{texto}", "apikey": clave})
            urllib.request.urlopen(f"https://api.callmebot.com/whatsapp.php?{q}", timeout=15).read()
        except Exception as e:
            print(f"(aviso por WhatsApp no enviado: {type(e).__name__})", flush=True)


def volatilidad(velas):
    """Volatilidad rapida (20 velas) y lenta (200) del rango de las velas, como en la prueba. velas: [(o, h, l, c)]."""
    af, asl = 2 / 21, 2 / 201
    ef = es = None
    serie = []
    for o, h, l, c in velas:
        r = (h - l) / c
        v = r * r
        ef = v if ef is None else ef + af * (v - ef)
        es = v if es is None else es + asl * (v - es)
        serie.append(math.sqrt(ef / es) if es > 0 else 1.0)
    return serie


def setup(h1, h4, cfg=None):
    """El setup en la ultima vela de 1 hora cerrada: (direccion, entrada, stop, objetivo) o None.
    h1, h4: velas cerradas [t, o, h, l, c, v] de 1 hora y de 4 horas. cfg: los parametros de la cripto."""
    import indicadores as ind
    cfg = cfg or SETUPS["BTC"]
    N = cfg["ruptura"]
    if len(h1) < 260 or len(h4) < 210:
        return None
    c = [b[4] for b in h1]
    atr = ind.dmi([b[2] for b in h1], [b[3] for b in h1], c)[3]
    e200 = ind.ema(c, 200)
    c4 = [b[4] for b in h4]
    t50, t200 = ind.ema(c4, 50)[-1], ind.ema(c4, 200)[-1]
    tend = 1 if t50 > t200 else -1
    v = volatilidad([(b[1], b[2], b[3], b[4]) for b in h1])[-1]
    i = len(h1) - 1
    hi, lo = max(b[2] for b in h1[i - N:i]), min(b[3] for b in h1[i - N:i])
    d = 1 if c[i] > hi and c[i] > e200[i] else -1 if c[i] < lo and c[i] < e200[i] else 0
    if not d or d != tend or v <= cfg["despierto"] or atr[i] is None:
        return None
    e = c[i]
    sl = e - d * cfg["stop_atr"] * atr[i]
    return d, e, sl, e + d * cfg["objetivo_r"] * abs(e - sl)


_BYBIT = None


def _bybit():
    global _BYBIT
    if _BYBIT is None:
        import ccxt
        _BYBIT = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    return _BYBIT


def _velas(nombre, ahora):
    """Velas cerradas de 1 hora y de 4 horas de ETH o ZEC (Bybit, 1000 de cada una), una sola vez por hora."""
    hora = int(ahora // 3600)
    got = _estado["velas"].get(nombre)
    if got and got[0] == hora:
        return got[1], got[2]
    ex, sym = _bybit(), SETUPS[nombre]["simbolo"]
    h1 = [list(x) for x in ex.fetch_ohlcv(sym, "1h", limit=1000) if x[0] + 3_600_000 <= ahora * 1000]
    h4 = [list(x) for x in ex.fetch_ohlcv(sym, "4h", limit=1000) if x[0] + 14_400_000 <= ahora * 1000]
    _estado["velas"][nombre] = (hora, h1, h4)
    return h1, h4


def _precio(nombre, ahora, btc):
    if nombre == "BTC":
        return btc
    got = _estado["precio"].get(nombre)
    if got and ahora - got[0] < 60:
        return got[1]
    p = float(_bybit().fetch_ticker(SETUPS[nombre]["simbolo"])["last"])
    _estado["precio"][nombre] = (ahora, p)
    return p


def _seguir(nombre, price, ahora):
    """Si hay un setup abierto de esa cripto, avisa cuando toca el objetivo o el stop (o vence)."""
    op = _estado["abierta"].get(nombre)
    if not op:
        return
    d, e, sl, tp, t0 = op
    lado = "LARGO" if d > 0 else "CORTO"
    rr = SETUPS[nombre]["objetivo_r"]
    if (price >= tp) if d > 0 else (price <= tp):
        enviar(f"✅ {nombre} {lado}: objetivo alcanzado", f"{nombre} llegó a {_fmt(tp)} (entrada {_fmt(e)}). +{_ar(rr, 1)}R.")
        _estado["abierta"].pop(nombre)
    elif (price <= sl) if d > 0 else (price >= sl):
        enviar(f"❌ {nombre} {lado}: tocó el stop", f"{nombre} llegó a {_fmt(sl)} (entrada {_fmt(e)}). −1R.")
        _estado["abierta"].pop(nombre)
    elif ahora - t0 > HORAS * 3600:
        r = (price - e) / abs(e - sl) * d
        enviar(f"⏱ {nombre} {lado}: pasaron 72 h", f"No tocó ni el stop ni el objetivo. Según la regla, se cierra en "
               f"{_fmt(price)} ({'+' if r >= 0 else ''}{_ar(r, 2)} R).")
        _estado["abierta"].pop(nombre)


def _fmt(x):
    """Precio con los decimales que hacen falta (BTC sin decimales, ZEC con dos)."""
    return _ar(x, 0 if x >= 1000 else 2 if x >= 10 else 4)


def _mov_zec(ahora):
    """Se viene movimiento fuerte en ZEC (velas de 5 min de Bybit, una vez cada 5 min). Probado con ZEC 2021-2026:
    la hora siguiente se movio 2,1 veces lo normal y mas del doble el 52% de las veces (11% en una hora cualquiera)."""
    tramo = int(ahora // 300)
    if _estado.get("zec5_t") == tramo:
        return
    _estado["zec5_t"] = tramo
    raw = _bybit().fetch_ohlcv(SETUPS["ZEC"]["simbolo"], "5m", limit=1000)
    c5 = [x for x in raw if x[0] + 300_000 <= ahora * 1000]
    if len(c5) < 300:
        return
    v = volatilidad([(x[1], x[2], x[3], x[4]) for x in c5])
    if not (v[-1] > DESPIERTA and v[-7] < DESPIERTA and ahora - _estado.get("mov_zec", 0) > ESPERA_MOV):
        return
    _estado["mov_zec"] = ahora
    price = c5[-1][4]
    rangos = sorted((max(x[2] for x in c5[i + 1:i + 13]) - min(x[3] for x in c5[i + 1:i + 13])) / c5[i][4]
                    for i in range(len(c5) - 13, -1, -12))
    normal = rangos[len(rangos) // 2] * price
    enviar("⚡ ZEC: se viene movimiento fuerte",
           f"El mercado de ZEC se despertó: precio {_fmt(price)}. En situaciones así, la hora siguiente se movió 2,1 veces "
           f"lo normal y más del doble el 52% de las veces. Movimiento normal en una hora: ~{_fmt(normal)} USD; "
           f"esperable ahora: ~{_fmt(normal * 2.1)} USD. No indica para dónde.", urgente=True)


def _setups(velas, price_btc, liq, ahora):
    for nombre, cfg in SETUPS.items():
        try:
            if nombre == "BTC":
                if not (velas and velas.get("1h") and velas.get("4h")):
                    continue
                h1, h4 = velas["1h"], velas["4h"]
            else:
                h1, h4 = _velas(nombre, ahora)
            price = _precio(nombre, ahora, price_btc) if (_estado["abierta"].get(nombre) or nombre == "BTC") else h1[-1][4]
            _seguir(nombre, price, ahora)
            if not h1 or h1[-1][0] == _estado["setup_t"].get(nombre):
                continue
            _estado["setup_t"][nombre] = h1[-1][0]
            got = setup(h1, h4, cfg)
            if not got or _estado["abierta"].get(nombre):
                continue
            d, e, sl, tp = got
            lado = "LARGO 📈" if d > 0 else "CORTO 📉"
            _estado["abierta"][nombre] = (d, e, sl, tp, ahora)
            txt = (f"Ruptura de 55 horas a favor de la tendencia, con el mercado despierto.\n"
                   f"Entrada: ~{_fmt(e)}\n"
                   f"Stop: {_fmt(sl)} ({_ar(abs(sl / e - 1) * 100, 2)}%)\n"
                   f"Objetivo: {_fmt(tp)} ({_ar(abs(tp / e - 1) * 100, 2)}%)\n"
                   f"Si en 72 h no tocó ninguno, se cierra.\n{cfg['historial']}")
            if nombre == "BTC":
                cerca = _zonas(liq, price_btc)
                if cerca:
                    txt += "\nLiquidaciones grandes: " + "; ".join(cerca) + "."
            enviar(f"Setup {lado} {nombre}", txt, urgente=True)
        except Exception as e:      # una cripto que falla no frena a las otras
            print(f"(setup {nombre}: {type(e).__name__}: {e})", flush=True)


def revisar(rows, velas=None):
    """Mira el ultimo analisis y manda los avisos que correspondan. velas: velas cerradas por temporalidad."""
    if not configurado():
        return
    ahora = time.time()
    head = next((r for r in rows if r["tabla"] == "resumen"), None)
    if head is None:
        return
    price = head["precio"]
    if not _estado["arranque"]:
        _estado["arranque"] = True
        enviar("Analista BTC: vigía activo",
               f"Te aviso cuando se venga movimiento fuerte, cuando el precio se acerque a una zona grande de "
               f"liquidaciones y cuando haya un setup de entrada en BTC, ETH o ZEC. BTC ahora: {_ar(price, 1)}.")
    liq = [r for r in rows if r["tabla"] == "liquidacion"]

    # 0) setups de entrada (BTC, ETH y ZEC), una vez por vela de 1 hora cerrada, y seguimiento de los abiertos
    _setups(velas, price, liq, ahora)
    try:
        _mov_zec(ahora)
    except Exception as e:
        print(f"(movimiento ZEC: {type(e).__name__}: {e})", flush=True)

    # 1) se viene movimiento fuerte (velas de 5 min cerradas)
    velas = [(r["o"], r["h"], r["l"], r["c"]) for r in rows if r["tabla"] == "vela" and r["tf"] == "5m" and not r["en_curso"]]
    if len(velas) >= 250:
        v = volatilidad(velas)
        if v[-1] > DESPIERTA and v[-7] < DESPIERTA and ahora - _estado["mov"] > ESPERA_MOV:
            _estado["mov"] = ahora
            rangos = sorted((max(x[1] for x in velas[i:i + 12]) - min(x[2] for x in velas[i:i + 12])) / velas[i][3]
                            for i in range(0, len(velas) - 12, 12))
            normal = rangos[len(rangos) // 2] * price
            txt = (f"El mercado se despertó: BTC en {_ar(price, 1)}. En situaciones así, la hora siguiente se movió "
                   f"2,3 veces lo normal (mediana) y más del doble el 59% de las veces. Movimiento normal en una hora: "
                   f"~{_ar(normal)} USD; esperable ahora: ~{_ar(normal * 2.3)} USD. No indica para dónde.")
            cerca = _zonas(liq, price)
            if cerca:
                txt += " Liquidaciones grandes: " + "; ".join(cerca) + "."
            enviar("⚡ Se viene movimiento fuerte", txt, urgente=True)

    # 2) zona grande de liquidaciones cerca
    for lado, campo, arriba in (("longs", "longs", False), ("shorts", "shorts", True)):
        zonas = [r for r in liq if r[campo] > 0 and (r["precio"] > price) == arriba and abs(r["precio"] / price - 1) <= RANGO_LIQ]
        if not zonas:
            continue
        top = max(zonas, key=lambda r: r[campo])
        if abs(top["precio"] / price - 1) <= CERCA_LIQ and ahora - _estado["liq"].get((lado, top["precio"]), 0) > ESPERA_LIQ:
            _estado["liq"][(lado, top["precio"])] = ahora
            sentido = "si sube" if arriba else "si baja"
            enviar(f"🎯 Liquidaciones de {lado} a {_ar(abs(top['precio'] / price - 1) * 100, 1)}%",
                   f"BTC en {_ar(price, 1)}. La zona más grande de liquidaciones de {lado} ({sentido}) está en "
                   f"{_ar(top['precio'])}: ~{_ar(top[campo], 1)} M USD estimados. Si el precio la alcanza, el movimiento "
                   f"puede acelerarse. Es una estimación con open interest y long/short, no un pronóstico.")


def _zonas(liq, price):
    out = []
    for campo, arriba, nombre in (("shorts", True, "shorts arriba"), ("longs", False, "longs abajo")):
        z = [r for r in liq if r[campo] > 0 and (r["precio"] > price) == arriba and abs(r["precio"] / price - 1) <= RANGO_LIQ]
        if z:
            t = max(z, key=lambda r: r[campo])
            out.append(f"{nombre} en {_ar(t['precio'])} (~{_ar(t[campo], 1)} M USD)")
    return out


def mantener_despierto():
    """Render gratis se duerme sin visitas: el servidor se visita solo cada 10 minutos para seguir mirando."""
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        return

    def loop():
        while True:
            time.sleep(600)
            try:
                urllib.request.urlopen(url.rstrip("/") + "/salud", timeout=20).read()
            except Exception:
                pass

    threading.Thread(target=loop, daemon=True).start()
