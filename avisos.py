"""
Avisos al celular (WhatsApp y notificacion) desde el servidor de Render, que mira el mercado las 24 horas.

Que avisa (solo lo que se probo con velas reales de BTC):
- "Se viene movimiento fuerte": cuando el mercado se despierta (la volatilidad de las ultimas velas de 5 min pasa
  1,8 veces la habitual). Probado 2021-2026: la hora siguiente se mueve 2,3 veces lo normal (mediana) y mas del
  doble de lo normal el 59% de las veces (en una hora cualquiera, 15%). Unos 3 o 4 avisos por semana. No dice para
  donde: eso no se pudo predecir.
- "Zona grande de liquidaciones cerca": cuando el precio queda a menos de 0,4% de la zona mas grande de
  liquidaciones estimadas de cada lado (dentro de 3%). Es informativo: alli el movimiento se puede acelerar.

Por donde (variables de entorno de Render; nunca en el codigo ni en el repositorio):
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

_estado = {"mov": 0.0, "liq": {}, "arranque": False}


def _ar(x, d=0):
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def configurado():
    return bool(os.environ.get("NTFY_TEMA") or (os.environ.get("WHATSAPP_TEL") and os.environ.get("WHATSAPP_CLAVE")))


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


def revisar(rows):
    """Mira el ultimo analisis y manda los avisos que correspondan."""
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
               f"Te aviso cuando se venga movimiento fuerte o el precio se acerque a una zona grande de liquidaciones. "
               f"BTC ahora: {_ar(price, 1)}.")
    liq = [r for r in rows if r["tabla"] == "liquidacion"]

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
