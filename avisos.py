"""
Avisos al celular (WhatsApp y notificacion) desde el servidor de Render, que mira el mercado las 24 horas.

Que avisa (solo lo que se probo con velas reales de BTC):
- "Se viene movimiento fuerte": cuando el modelo de arboles (fuerte.py) da 40% o mas de chance de que la proxima hora
  se mueva mas del doble de lo habitual (probado sin mirar el futuro: ~2 avisos por semana, acierta 40-49%; una hora
  cualquiera, 12%). Si el modelo no esta, el aviso viejo: cuando el mercado se despierta (la volatilidad de las ultimas velas de 5 min pasa
  1,8 veces la habitual). Probado 2021-2026: la hora siguiente se mueve 2,3 veces lo normal (mediana) y mas del
  doble de lo normal el 59% de las veces (en una hora cualquiera, 15%). Unos 3 o 4 avisos por semana. No dice para
  donde: eso no se pudo predecir.
- "Noticia que puede mover a BTC": titulares nuevos de guerras grandes, del gobierno de EE.UU., de gobiernos grandes,
  de ETF o de hackeos que
  se leen como buenos o malos para BTC (lectura automatica del titular, ver noticias.py). Como mucho uno cada 20 min.
- "La Fed bajo/subio/mantuvo la tasa": apenas sale, comparada con lo previsto (mas baja: bueno para BTC; mas alta: malo).
- "Dato fuerte de EE.UU. en 30 minutos" (IPC, empleo, Fed...): medido 2021-2026, esa hora BTC se movio 1,7 veces lo normal
  y fue un movimiento fuerte 26% de las veces (11% en una hora cualquiera). No dice para donde.
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

DESPIERTA = 1.8            # volatilidad rapida / lenta para "se viene movimiento" (si no hay modelo)
MODELO_AVISO = 40.0        # chance (%) del modelo de movimiento fuerte para avisar
ESPERA_MOV = 4 * 3600      # no repetir el aviso de movimiento antes de 4 horas
CERCA_LIQ = 0.004          # 0,4% de la zona de liquidaciones
RANGO_LIQ = 0.03           # zonas dentro de 3% del precio
ESPERA_LIQ = 3 * 3600      # la misma zona no se avisa dos veces en 3 horas
NOTI_IMPACTO = 2           # se avisan: guerras grandes y gobierno de EE.UU. (3), gobiernos grandes, ETF y hackeos (2)
NOTI_FRESCA = 90 * 60      # solo titulares de los ultimos 90 minutos
ESPERA_NOTI = 20 * 60      # como mucho un aviso de noticias cada 20 minutos (junta hasta 3 titulares)
ANTES_DATO = 35 * 60       # aviso de dato economico fuerte de EE.UU.: unos 30 minutos antes

HORAS = 72
# capital para futuros (se puede cambiar con la variable CAPITAL_FUTUROS en Render) y riesgo por operacion
CAPITAL = float(os.environ.get("CAPITAL_FUTUROS", "9600"))
RIESGO = float(os.environ.get("RIESGO_PCT", "1")) / 100


# Gestion de riesgo de trader profesional (no mejora las señales: protege la cuenta de las rachas malas)
# Por Telegram solo las entradas de futuros (y su cierre). AVISOS=todos en Render vuelve a mandar movimiento
# fuerte, liquidaciones, noticias, datos de EE.UU. y la Fed.
SOLO_ENTRADAS = os.environ.get("AVISOS", "entradas").strip().lower() != "todos"
RIESGO_MAX_ABIERTO = 0.025    # riesgo total abierto (todas las operaciones juntas): 2,5% del capital
PERDIDA_DIA_MAX = 0.02        # si en el dia se pierde 2% del capital, no se abren entradas nuevas hasta el dia siguiente
RACHA_PAUSA = 3               # 3 perdidas seguidas: pausa de 24 h
COMISION = 0.0005             # comision de mercado por lado (0,05%: BingX/Binance taker)
DESLIZ_MAX = 0.3              # si al leer el aviso el precio ya se alejo mas de 0,3 R de la entrada, no entrar


def tamano(e, sl, tp, riesgo=None):
    """Cuanto operar: perder `riesgo` (por defecto RIESGO) del capital si toca el stop. Apalancamiento para que la
    liquidacion quede al menos a 3 veces la distancia del stop (y nunca mas de 10x); margen aislado."""
    capital = float(os.environ.get("CAPITAL_FUTUROS", CAPITAL))
    riesgo_usd = capital * (RIESGO if riesgo is None else riesgo)
    dist = abs(e - sl) / e
    qty = riesgo_usd / abs(e - sl)
    nocional = qty * e
    lev = max(1, min(10, int(1 / (3 * dist))))
    margen = nocional / lev
    gana = qty * abs(tp - e)
    return qty, nocional, lev, margen, riesgo_usd, gana, capital
_PIE = " Arriesgando 1% de la cuenta por operación: {cuenta}, peor caída {caida}. Es estadística del pasado, no una garantía."
SETUPS = {
    "BTC": {"ruptura": 55, "despierto": 1.5, "stop_atr": 2.5, "objetivo_r": 1.0, "simbolo": "BTC/USDT:USDT",
            "historial": "Historial 2021–2026 (con comisiones): 91 a 99 operaciones según la fuente de datos, ganó el "
                         "64–69%, +0,22 a +0,35 R por operación, positivo 5–6 de 6 años."
                         + _PIE.format(cuenta="+22% a +36%", caida="−3%"),
            "simple": "Con esta señal, entre 2021 y 2026 se ganó 2 de cada 3 veces. No es seguro: respetá el stop loss."},
    "ETH": {"ruptura": 55, "despierto": 1.5, "stop_atr": 2.5, "objetivo_r": 1.0, "simbolo": "ETH/USDT:USDT",
            "historial": "Historial 2021–2026 (con comisiones): 93 operaciones, ganó el 61%, +0,22 R por operación, "
                         "positivo 6 de 6 años." + _PIE.format(cuenta="+22%", caida="−3%"),
            "simple": "Con esta señal, entre 2021 y 2026 se ganó 6 de cada 10 veces. No es seguro: respetá el stop loss."},
    "ZEC": {"ruptura": 55, "despierto": 1.2, "stop_atr": 2.5, "objetivo_r": 1.5, "simbolo": "ZEC/USDT:USDT",
            "historial": "Historial 2021–2026 (con comisiones): 195 operaciones, ganó el 49% (el objetivo es 1,5 veces "
                         "el stop), +0,19 R por operación, positivo 6 de 6 años." + _PIE.format(cuenta="+44%", caida="−7%"),
            "simple": "Con esta señal, entre 2021 y 2026 se ganó 1 de cada 2 veces, pero cada ganancia es 1,5 veces lo "
                      "que se pierde cuando sale mal. No es seguro: respetá el stop loss."},
}

_estado = {"mov": 0.0, "liq": {}, "arranque": False, "setup_t": {}, "abierta": {}, "velas": {}, "precio": {},
           "registro": [], "pausa_hasta": 0.0,
           "noti": set(), "noti_t": 0.0, "noti_listo": False, "datos": set(), "fed": set()}


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


def _cerrar(nombre, op, salida, motivo, ahora):
    """Anota el resultado (en R y en USDT) y avisa con el registro acumulado y la gestion de riesgo."""
    d, e, sl, tp, t0 = op[:5]
    riesgo_usd = op[5] if len(op) > 5 else float(os.environ.get("CAPITAL_FUTUROS", CAPITAL)) * RIESGO
    r = (salida - e) / abs(e - sl) * d
    usd = r * riesgo_usd - 2 * COMISION * (riesgo_usd / abs(e - sl)) * e
    reg = _estado["registro"]
    reg.append((ahora, nombre, r, usd))
    hoy = time.strftime("%Y-%m-%d", time.gmtime(ahora - 3 * 3600))
    dia = sum(x[3] for x in reg if time.strftime("%Y-%m-%d", time.gmtime(x[0] - 3 * 3600)) == hoy)
    gan = sum(1 for x in reg if x[2] > 0)
    racha = 0
    for x in reversed(reg):
        if x[2] > 0:
            break
        racha += 1
    capital = float(os.environ.get("CAPITAL_FUTUROS", CAPITAL))
    nota = ""
    if racha >= RACHA_PAUSA:
        _estado["pausa_hasta"] = ahora + 24 * 3600
        nota = (f"\n⏸ {racha} pérdidas seguidas: pausa de 24 h sin entradas nuevas. Las rachas malas pasan (el historial las tuvo); "
                f"un profesional no las persigue para recuperar.")
    elif dia <= -PERDIDA_DIA_MAX * capital:
        manana = (int((ahora - 3 * 3600) // 86400) + 1) * 86400 + 3 * 3600
        _estado["pausa_hasta"] = max(_estado["pausa_hasta"], manana)
        nota = f"\n⏸ Hoy se perdió {_ar(-dia)} USDT (2% del capital o más): no hay entradas nuevas hasta mañana."
    titulo = {"tp": f"✅ {nombre}: take profit", "sl": f"❌ {nombre}: stop loss", "tiempo": f"⏱ {nombre}: pasaron 3 días, cerrá"}[motivo]
    txt = {"tp": f"Tocó {_fmt(tp)} USD: operación cerrada con ganancia.",
           "sl": f"Tocó {_fmt(sl)} USD: operación cerrada con la pérdida prevista. Es parte del sistema: no la persigas.",
           "tiempo": f"No tocó ni el stop ni el take profit en 72 h. Cerrala ahora a mercado (~{_fmt(salida)} USD)."}[motivo]
    enviar(titulo, f"{txt}\nResultado: {'+' if r >= 0 else ''}{_ar(r, 2)} R ≈ {'+' if usd >= 0 else ''}{_ar(usd)} USDT (con comisiones).\n"
                   f"Registro desde que arrancó el vigía: {len(reg)} operación{"es" if len(reg) > 1 else ""}, ganó {gan} ({_ar(gan / len(reg) * 100)}%), "
                   f"total {'+' if sum(x[3] for x in reg) >= 0 else ''}{_ar(sum(x[3] for x in reg))} USDT. "
                   f"En las pruebas se esperaba ganar 2 de cada 3 en BTC, 6 de cada 10 en ETH y 1 de cada 2 en ZEC.{nota}")


def _seguir(nombre, price, ahora):
    """Si hay un setup abierto de esa cripto, avisa cuando toca el objetivo o el stop (o vence)."""
    op = _estado["abierta"].get(nombre)
    if not op:
        return
    d, e, sl, tp, t0 = op[:5]
    if (price >= tp) if d > 0 else (price <= tp):
        _cerrar(nombre, _estado["abierta"].pop(nombre), tp, "tp", ahora)
    elif (price <= sl) if d > 0 else (price >= sl):
        _cerrar(nombre, _estado["abierta"].pop(nombre), sl, "sl", ahora)
    elif ahora - t0 > HORAS * 3600:
        _cerrar(nombre, _estado["abierta"].pop(nombre), price, "tiempo", ahora)


def niveles(h1, h4, cfg):
    """Donde se activaria el setup en la proxima vela de 1 hora: (direccion, nivel) si la tendencia de 4 horas
    acompana y el precio esta a menos de 1 ATR de romper el maximo (o minimo) de las ultimas 55 horas; si no, None."""
    import indicadores as ind
    N = cfg["ruptura"]
    if len(h1) < 260 or len(h4) < 210:
        return None
    c = [b[4] for b in h1]
    atr = ind.dmi([b[2] for b in h1], [b[3] for b in h1], c)[3][-1]
    e200 = ind.ema(c, 200)[-1]
    c4 = [b[4] for b in h4]
    tend = 1 if ind.ema(c4, 50)[-1] > ind.ema(c4, 200)[-1] else -1
    hi, lo = max(b[2] for b in h1[-N:]), min(b[3] for b in h1[-N:])
    v = volatilidad([(b[1], b[2], b[3], b[4]) for b in h1])[-1]
    if atr is None or v < 0.85 * cfg["despierto"]:      # mercado quieto: es muy probable que no se active
        return None
    if tend > 0 and hi > e200 and 0 < hi - c[-1] <= atr:
        return 1, hi
    if tend < 0 and lo < e200 and 0 < c[-1] - lo <= atr:
        return -1, lo
    return None


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


def _riesgo(nombre, d, rows, ahora):
    """Riesgo de esta operacion (fraccion del capital) y los motivos si se achica. Reglas de gestion de riesgo de
    un trader profesional: no cambian la señal, limitan cuanto se pierde en una mala racha."""
    r, notas = RIESGO, []
    otras = {k: v for k, v in _estado["abierta"].items() if k != nombre}
    if any(v[0] == d for v in otras.values()):
        r /= 2
        notas.append(f"ya hay otra operación en la misma dirección ({', '.join(k for k, v in otras.items() if v[0] == d)}): "
                     f"BTC, ETH y ZEC se mueven juntos, así que es casi la misma apuesta → mitad de riesgo")
    prox = [x for x in rows if x.get("tabla") == "evento" and 0 < x["t"] / 1000 - ahora <= 3600]
    if prox:
        r /= 2
        hora = time.strftime("%H:%M", time.gmtime(prox[0]["t"] / 1000 - 3 * 3600))
        notas.append(f"a las {hora} h sale {prox[0]['titulo']}: con un dato fuerte el precio puede saltar el stop → mitad de riesgo")
    capital = float(os.environ.get("CAPITAL_FUTUROS", CAPITAL))
    usado = sum((v[5] if len(v) > 5 else capital * RIESGO) for v in otras.values()) / capital
    if usado + r > RIESGO_MAX_ABIERTO:
        r = max(0.0, RIESGO_MAX_ABIERTO - usado)
        notas.append(f"ya tenés {_ar(usado * 100, 1)}% del capital en riesgo abierto; el tope es {_ar(RIESGO_MAX_ABIERTO * 100, 1)}%")
    return r, notas


def _contexto(d, rows):
    """Chequeo previo como lo haria un trader: que dice el resto del mercado. Es informacion, no filtro: en las
    pruebas, filtrar el setup con estas cosas no mejoro el resultado de forma confiable."""
    out = []
    mv = next((x for x in rows if x.get("tabla") == "movimiento"), None)
    if mv and mv.get("modelo_1h") is not None:
        out.append(f"Movimiento fuerte: {_ar(mv['modelo_1h'])}% en la próxima hora, {_ar(mv.get('modelo_4h') or 0)}% en 4 h "
                   f"(lo normal {_ar(mv.get('modelo_base_1h') or 0)}%)")
    ev = sorted((x for x in rows if x.get("tabla") == "evento" and x["t"] / 1000 > time.time()), key=lambda x: x["t"])
    if ev:
        t = ev[0]["t"] / 1000
        out.append(f"Próximo dato fuerte de EE.UU.: {ev[0]['titulo']}, {time.strftime('%d/%m %H:%M', time.gmtime(t - 3 * 3600))} h "
                   f"(en {_ar((t - time.time()) / 3600, 1)} h)")
    else:
        out.append("Sin datos fuertes de EE.UU. a la vista")
    nots = [x for x in rows if x.get("tabla") == "noticia" and x.get("impacto", 0) >= 2 and time.time() - x["t"] / 1000 <= 6 * 3600]
    if nots:
        a = sum(1 for x in nots if x["sesgo"] == "alcista"); b = sum(1 for x in nots if x["sesgo"] == "bajista")
        clima = "a favor" if (a - b) * d > 0 else "en contra" if (a - b) * d < 0 else "neutro"
        out.append(f"Noticias de peso (6 h): {a} a favor de suba, {b} a favor de baja → clima {clima} de la operación")
    head = next((x for x in rows if x.get("tabla") == "resumen"), None)
    if head and head.get("funding") is not None:
        f = head["funding"]
        lleno = (f > 0.03 and d > 0) or (f < -0.03 and d < 0)
        out.append(f"Funding: {_ar(f, 4)}% cada 8 h" + (" (lado lleno: la posición paga y hay riesgo de barrida)" if lleno
                   else " (vos cobrás)" if f * d < 0 else ""))
    return out


def _entrada(nombre, cfg, got, rows, ahora):
    """Arma y manda la entrada completa: gestion de riesgo, configuracion paso a paso y chequeo de contexto."""
    d, e, sl, tp = got
    lado = "LONG 📈 (compra)" if d > 0 else "SHORT 📉 (venta)"
    if ahora < _estado["pausa_hasta"]:
        enviar(f"{nombre}: señal en {lado}, pero NO entres",
               f"Se activó el setup (entrada {_fmt(e)}), pero estás en pausa por la gestión de riesgo hasta "
               f"{time.strftime('%d/%m %H:%M', time.gmtime(_estado['pausa_hasta'] - 3 * 3600))} h. "
               f"Después de una mala racha conviene frenar en vez de buscar recuperar.")
        return
    riesgo, notas = _riesgo(nombre, d, rows, ahora)
    if riesgo < 0.0025:
        enviar(f"{nombre}: señal en {lado}, pero NO entres", f"Se activó el setup (entrada {_fmt(e)}), pero ya tenés "
               f"el máximo de riesgo abierto ({_ar(RIESGO_MAX_ABIERTO * 100, 1)}% del capital). Esperá a que cierre otra.")
        return
    qty, nocional, lev, margen, perder, ganar, capital = tamano(e, sl, tp, riesgo)
    _estado["abierta"][nombre] = (d, e, sl, tp, ahora, perder)
    R = abs(e - sl)
    liq = e * (1 - d / lev + d * 0.005)                      # aislado, mantenimiento ~0,5%
    fee = 2 * COMISION * nocional
    limite = e + d * DESLIZ_MAX * R
    vence = time.strftime("%d/%m %H:%M", time.gmtime(ahora + HORAS * 3600 - 3 * 3600))
    q = _ar(qty, 4 if qty < 1 else 2)
    accion = "Buy / Long (Abrir largo)" if d > 0 else "Sell / Short (Abrir corto)"
    txt = (f"PLAN\n"
           f"• Entrada: {_fmt(e)} USD, a mercado ya. No entres si el precio ya pasó {_fmt(limite)} "
           f"(se comió 0,3 R del recorrido: la relación ganancia/riesgo deja de valer la pena).\n"
           f"• Stop loss: {_fmt(sl)} USD ({_ar(abs(sl / e - 1) * 100, 2)}%, {_ar(cfg['stop_atr'], 1)} ATR: fuera del ruido normal)\n"
           f"• Take profit: {_fmt(tp)} USD ({_ar(abs(tp / e - 1) * 100, 2)}%, {_ar(cfg['objetivo_r'], 1)} R)\n"
           f"• Cierre por tiempo: {vence} h (72 h) si no tocó ninguno\n"
           f"• Riesgo: {_ar(perder)} USDT ({_ar(riesgo * 100, 2)}% del capital de {_ar(capital)}) · "
           f"ganancia posible {_ar(ganar)} USDT · comisiones ~{_ar(fee, 1)} USDT\n"
           + "".join(f"  ⚠ {n}\n" for n in notas) +
           f"\nCÓMO CONFIGURARLA (BingX o Binance)\n"
           f"1. Futuros perpetuos → {nombre}USDT.\n"
           f"2. Modo de margen: Aislado (Isolated). Nunca cruzado: así esta operación no puede tocar el resto de tu cuenta.\n"
           f"3. Apalancamiento: {lev}x (largo y corto). Es solo para poner menos margen; el riesgo lo fija el stop, no el apalancamiento.\n"
           f"4. Tipo de orden: Mercado. Cantidad: {q} {nombre} (≈ {_ar(nocional)} USDT de posición; margen ≈ {_ar(margen)} USDT).\n"
           f"5. Tildá TP/SL en la misma orden: Take profit {_fmt(tp)} · Stop loss {_fmt(sl)}, disparo por «Último precio» (Last), "
           f"ejecución a mercado.\n"
           f"6. {accion}. Confirmá.\n"
           f"7. Revisá en Posiciones que figuren el TP y el SL. Precio de liquidación aprox. {_fmt(liq)} "
           f"(mucho más lejos que el stop: el stop salta antes).\n"
           f"8. Poné una alarma para el {vence} h: si sigue abierta, cerrala a mercado.\n"
           f"\nREGLAS MIENTRAS ESTÁ ABIERTA\n"
           f"• No muevas el stop en contra ni agregues a una posición perdedora.\n"
           f"• No cierres antes por miedo: el resultado del sistema depende de dejar correr cada operación hasta TP, SL o 72 h.\n"
           f"• Te aviso cuando toque el TP o el SL, o cuando venza el tiempo.\n"
           f"\nCONTEXTO (informativo, no cambia la entrada)\n" + "".join(f"• {c}\n" for c in _contexto(d, rows)) +
           f"\n{cfg['simple']}")
    enviar(f"{nombre}: entrada en {lado}", txt, urgente=True)


def _setups(velas, price_btc, liq, ahora, rows=()):
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
            if not got and not _estado["abierta"].get(nombre) and not SOLO_ENTRADAS:
                pre = niveles(h1, h4, cfg)
                clave = (nombre, pre[0]) if pre else None
                if pre and ahora - _estado.setdefault("pre", {}).get(clave, 0) > 12 * 3600:
                    _estado["pre"][clave] = ahora
                    d, nivel = pre
                    lado, verbo, quien = ("LONG (compra)", "por encima", "suba") if d > 0 else ("SHORT (venta)", "por debajo", "baje")
                    enviar(f"👀 {nombre}: atento a una posible entrada en {lado}",
                           f"Si una vela de 1 hora de {nombre} cierra {verbo} de {_fmt(nivel)} USD (ahora está en "
                           f"{_fmt(h1[-1][4])}), se puede activar una entrada en {lado}.\n"
                           f"No entres antes: esperá mi aviso al cierre de esa vela, con la entrada, el stop loss y el "
                           f"take profit. Si el mercado está muy quieto en ese momento, la entrada no se activa.\n"
                           f"Por qué: la tendencia de fondo (4 horas) es {'alcista' if d > 0 else 'bajista'} y el precio "
                           f"está cerca de romper el {'máximo' if d > 0 else 'mínimo'} de los últimos 2 días; esas "
                           f"rupturas a favor de la tendencia son las que mejor funcionaron.")
            if not got or _estado["abierta"].get(nombre):
                continue
            _entrada(nombre, cfg, got, rows, ahora)
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
    if not _estado["arranque"] and not SOLO_ENTRADAS:
        _estado["arranque"] = True
        enviar("Analista BTC: vigía activo",
               f"Te aviso cuando se venga movimiento fuerte, cuando el precio se acerque a una zona grande de "
               f"liquidaciones, cuando haya un setup de entrada en BTC, ETH o ZEC y cuando salga una noticia de peso "
               f"(guerras grandes, gobierno de EE.UU., gobiernos grandes, ETF o hackeos) y media hora antes de los datos "
               f"fuertes de EE.UU. (IPC, empleo, Fed). BTC ahora: {_ar(price, 1)}.")
    liq = [r for r in rows if r["tabla"] == "liquidacion"]

    # 0) setups de entrada (BTC, ETH y ZEC), una vez por vela de 1 hora cerrada, y seguimiento de los abiertos
    _setups(velas, price, liq, ahora, rows)
    if SOLO_ENTRADAS:
        return
    try:
        _mov_zec(ahora)
    except Exception as e:
        print(f"(movimiento ZEC: {type(e).__name__}: {e})", flush=True)

    # 1) se viene movimiento fuerte: con el modelo de arboles (fuerte.py) cuando marca 40% o mas para la proxima hora.
    # Probado sin mirar el futuro: ~2 avisos por semana y 40-49% de las veces la hora se movio mas del doble de lo
    # habitual (el aviso viejo, por volatilidad: 31-32% con la misma vara). Sin modelo, queda el aviso viejo.
    mv = next((r for r in rows if r["tabla"] == "movimiento"), None)
    velas = [(r["o"], r["h"], r["l"], r["c"]) for r in rows if r["tabla"] == "vela" and r["tf"] == "5m" and not r["en_curso"]]
    if mv and mv.get("modelo_1h") is not None:
        p1, prev = mv["modelo_1h"], _estado.get("p_mod", 0.0)
        _estado["p_mod"] = p1
        if p1 >= MODELO_AVISO and prev < MODELO_AVISO and ahora - _estado["mov"] > ESPERA_MOV:
            _estado["mov"] = ahora
            hasta = time.strftime("%H:%M", time.gmtime(mv["modelo_hasta"] / 1000 - 3 * 3600))
            txt = (f"BTC en {_ar(price, 1)}. El modelo da {_ar(p1)}% de chance de que hasta las {hasta} h se mueva más del doble "
                   f"de lo habitual (una hora cualquiera: {_ar(mv['modelo_base_1h'])}%); próximas 4 h: {_ar(mv['modelo_4h'])}%. "
                   f"Cuando marcó 40% o más, pasó 40–49% de las veces (probado 2023–2026). No indica para dónde: ojo con stops cerca.")
            cerca = _zonas(liq, price)
            if cerca:
                txt += " Liquidaciones grandes: " + "; ".join(cerca) + "."
            enviar("⚡ Se viene movimiento fuerte", txt, urgente=True)
    elif len(velas) >= 250:
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

    # 2) dato economico fuerte de EE.UU. en media hora
    try:
        _datos(rows, ahora, price)
    except Exception as e:
        print(f"(aviso de datos: {type(e).__name__}: {e})", flush=True)

    # 2b) decision de tasas de la Fed (prioridad)
    try:
        _fed(rows, price)
    except Exception as e:
        print(f"(aviso de la Fed: {type(e).__name__}: {e})", flush=True)

    # 2) noticias de peso nuevas
    try:
        _noticias(rows, ahora)
    except Exception as e:
        print(f"(aviso de noticias: {type(e).__name__}: {e})", flush=True)

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


def _noticias(rows, ahora):
    """Titulares nuevos de peso, leidos como buenos o malos para BTC. Al arrancar, los que ya estaban no se avisan."""
    ns = [r for r in rows if r.get("tabla") == "noticia"]
    clave = lambda r: (r.get("url") or r["titulo"])[:200]
    if not _estado["noti_listo"]:
        _estado["noti"].update(clave(r) for r in ns)
        _estado["noti_listo"] = bool(ns)
        return
    nuevas = [r for r in ns if clave(r) not in _estado["noti"] and r.get("impacto", 0) >= NOTI_IMPACTO
              and r.get("sesgo") in ("alcista", "bajista") and ahora - r["t"] / 1000 <= NOTI_FRESCA]
    if not nuevas or ahora - _estado["noti_t"] < ESPERA_NOTI:
        return
    nuevas.sort(key=lambda r: (-r["impacto"], -r["t"]))
    elegidas = nuevas[:3]
    _estado["noti"].update(clave(r) for r in elegidas)
    _estado["noti_t"] = ahora
    malas = sum(1 for r in elegidas if r["sesgo"] == "bajista")
    lado = "a la baja" if malas > len(elegidas) / 2 else "al alza" if malas < len(elegidas) / 2 else "para los dos lados"
    lineas = []
    for r in elegidas:
        mins = max(0, int((ahora - r["t"] / 1000) // 60))
        lineas.append(f"{'▼' if r['sesgo'] == 'bajista' else '▲'} {r['titulo']} ({r['fuente']}, hace {mins} min · {r['tema']}) {r['url']}")
    enviar(f"📰 Noticia que puede mover BTC {lado}",
           "\n".join(lineas) + "\nLectura automática del titular: confirmalo antes de operar. No es una señal de entrada.")


def _datos(rows, ahora, price):
    """Unos 30 minutos antes de un dato de importancia alta de EE.UU., una vez por horario."""
    por_hora = {}
    for r in rows:
        if r.get("tabla") == "evento":
            por_hora.setdefault(r["t"], []).append(r["titulo"])
    for t, nombres in sorted(por_hora.items()):
        falta = t / 1000 - ahora
        if 0 < falta <= ANTES_DATO and t not in _estado["datos"]:
            _estado["datos"].add(t)
            hora = time.strftime("%H:%M", time.gmtime(t / 1000 - 3 * 3600))
            lista = ", ".join(dict.fromkeys(nombres))
            enviar(f"📅 En {int(falta // 60)} min: dato fuerte de EE.UU.",
                   f"{lista} a las {hora} h (Argentina). BTC en {_ar(price, 1)}. En la hora en que salen datos así, BTC se movió "
                   f"1,7 veces lo normal y fue un movimiento fuerte 26% de las veces (11% en una hora cualquiera). "
                   f"Medido 2021–2026. No indica para dónde: ojo con stops muy cerca.", urgente=True)


def _fed(rows, price):
    """Cuando sale la decision de tasas de la Fed: mas baja de lo previsto es bueno para BTC, mas alta es malo."""
    ahora = time.time()
    for r in rows:
        if r.get("tabla") != "evento" or "interest rate decision" not in (r.get("original") or "").lower():
            continue
        if r.get("actual") is None or r["t"] in _estado["fed"] or not (0 <= ahora - r["t"] / 1000 <= 3 * 3600):
            continue
        _estado["fed"].add(r["t"])
        act, prev, ant = r["actual"], r.get("previsto"), r.get("anterior")
        mov = "" if ant is None else "bajó" if act < ant else "subió" if act > ant else "mantuvo"
        if prev is None:
            lado, txt = "", "Sin previsión para comparar."
        elif act < prev:
            lado, txt = "▲ positivo para BTC", "Más baja de lo que se esperaba: suele ser bueno para BTC."
        elif act > prev:
            lado, txt = "▼ negativo para BTC", "Más alta de lo que se esperaba: suele ser malo para BTC."
        else:
            lado, txt = "como se esperaba", "Era lo que se esperaba: el mercado ya lo tenía descontado; ojo con lo que diga Powell después."
        f = lambda v: f"{v:.2f}%".replace(".", ",")
        enviar(f"🏦 La Fed {mov + ' la tasa' if mov else 'decidió la tasa'}: {f(act)} ({lado})",
               f"Tasa de la Fed: {f(act)}" + (f", se esperaba {f(prev)}" if prev is not None else "") +
               (f", antes {f(ant)}" if ant is not None else "") + f". {txt} BTC en {_ar(price, 1)}.", urgente=True)


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
