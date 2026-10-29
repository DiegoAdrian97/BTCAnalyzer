"""Abre y cierra las entradas de avisos.py solas, SOLO en la cuenta demo de BingX (VST, plata de prueba).

Se activa en Render con OPERAR=demo y las claves BINGX_API_KEY / BINGX_API_SECRET (variables de entorno, nunca en el
codigo). La demo de BingX usa las mismas claves que la cuenta real, por eso este modulo fuerza siempre el modo demo
(set_sandbox_mode) y se niega a operar si no lo esta. No hay modo real.

Cada entrada: margen aislado, apalancamiento del aviso, orden a mercado con TP y SL pegados (se ejecutan en BingX
aunque el servidor se caiga). El cierre por tiempo (72 h) lo hace el vigia con close_position.
"""
import os

import ccxt

_ex = None


def activo():
    return (os.environ.get("OPERAR", "").strip().lower() == "demo" and bool(os.environ.get("BINGX_API_KEY"))
            and bool(os.environ.get("BINGX_API_SECRET")))


def _bingx():
    global _ex
    if _ex is None:
        ex = ccxt.bingx({"apiKey": os.environ["BINGX_API_KEY"], "secret": os.environ["BINGX_API_SECRET"],
                         "enableRateLimit": True, "options": {"defaultType": "swap"}})
        ex.set_sandbox_mode(True)
        ex.load_markets()
        _ex = ex
    if not _ex.options.get("sandboxMode") or "vst" not in str(_ex.urls.get("api")):
        raise RuntimeError("BingX no está en modo demo: no opero")
    return _ex


def _posiciones(ex, sym):
    return [p for p in ex.fetch_positions([sym]) if abs(float(p.get("contracts") or 0)) > 0]


def _hedge(ex, sym):
    try:
        return bool(ex.fetch_position_mode(sym).get("hedged"))
    except Exception:
        return True                     # BingX viene en modo cobertura (largo y corto por separado) por defecto


def precio(sym):
    return float(_bingx().fetch_ticker(sym)["last"])


def abrir(sym, d, qty, sl, tp, lev, t0=None):
    """Abre la posicion. Devuelve dict con lo ejecutado; lanza excepcion con el motivo si no se pudo."""
    ex = _bingx()
    if _posiciones(ex, sym):
        raise RuntimeError("ya hay una posición abierta en ese par")
    hedged = _hedge(ex, sym)
    try:
        ex.set_margin_mode("isolated", sym)
    except Exception as e:              # si ya estaba en aislado BingX contesta error: solo se sigue si es eso
        if "isolated" not in str(e).lower() and "same" not in str(e).lower() and "no need" not in str(e).lower():
            raise
    lado = ("LONG" if d > 0 else "SHORT") if hedged else "BOTH"
    ex.set_leverage(lev, sym, {"side": lado})
    m = ex.market(sym)
    amount = float(ex.amount_to_precision(sym, qty))
    minimo = (m.get("limits", {}).get("amount", {}) or {}).get("min") or 0
    if amount <= 0 or amount < minimo:
        raise RuntimeError(f"cantidad {qty} menor que el mínimo del par ({minimo})")
    lado_c = "sell" if d > 0 else "buy"
    orden = ex.create_order(sym, "market", "buy" if d > 0 else "sell", amount, None, {"hedged": hedged})
    pos = _posiciones(ex, sym)
    if not pos:
        raise RuntimeError(f"mandé la orden (id {orden.get('id')}) pero no veo la posición")
    entrada = float(pos[0].get("entryPrice") or 0)
    # TP y SL como ordenes aparte (reduce only) sobre la posicion ya abierta, y se verifica que esten en BingX
    puestas = []
    try:
        for clave, px in (("stopLossPrice", sl), ("takeProfitPrice", tp)):
            extra = {} if t0 is None else {"clientOrderId": _marca(sym, clave[0], t0)}
            o = ex.create_order(sym, "market", lado_c, amount, None,
                                {"hedged": hedged, "reduceOnly": True, clave: float(ex.price_to_precision(sym, px)), **extra})
            puestas.append(o.get("id"))
        abiertas = {str(o.get("id")) for o in ex.fetch_open_orders(sym)}
        if not all(str(i) in abiertas for i in puestas):
            raise RuntimeError("BingX no muestra las órdenes de TP/SL")
    except Exception as e:              # sin stop no se queda abierta: se cierra por seguridad
        cerrar(sym)
        raise RuntimeError(f"no pude poner TP/SL ({type(e).__name__}: {str(e)[:120]}); la cerré por seguridad")
    return {"id": orden.get("id"), "cantidad": amount, "entrada": entrada, "abierta": True, "tp_sl": puestas}


def _marca(sym, tipo, t0):
    """Id propio de las ordenes de TP/SL del vigia: permite reconocer sus operaciones despues de un reinicio."""
    return f"ab{sym.split('/')[0].lower()}{tipo}{int(t0)}"


def recuperar(sym):
    """Despues de un reinicio: si hay una operacion abierta por el vigia en el par, (d, entrada, sl, tp, t0, qty).
    Las posiciones abiertas a mano (sin las ordenes marcadas) no se tocan."""
    ex = _bingx()
    pos = _posiciones(ex, sym)
    if not pos:
        return None
    pre = f"ab{sym.split('/')[0].lower()}"
    sl = tp = t0 = None
    for o in ex.fetch_open_orders(sym):
        cid = str(o.get("clientOrderId") or (o.get("info") or {}).get("clientOrderID") or (o.get("info") or {}).get("clientOrderId") or "")
        if not cid.startswith(pre) or not cid[len(pre) + 1:].isdigit():
            continue
        t0 = int(cid[len(pre) + 1:])
        px = o.get("stopLossPrice") or o.get("takeProfitPrice") or o.get("triggerPrice") or (o.get("info") or {}).get("stopPrice")
        if cid[len(pre)] == "s":
            sl = float(px)
        else:
            tp = float(px)
    if t0 is None or sl is None or tp is None:
        return None
    p = pos[0]
    d = 1 if str(p.get("side")).lower() == "long" else -1
    return d, float(p.get("entryPrice")), sl, tp, t0, abs(float(p.get("contracts")))


def describir(sym):
    """Texto con lo que hay abierto en el par (para entender un 'ya hay posicion')."""
    ex = _bingx()
    return "; ".join(f"{p.get('side')} {p.get('contracts')} a {p.get('entryPrice')}" for p in _posiciones(ex, sym)) or "nada"


def saldo():
    b = _bingx().fetch_balance()
    for k in ("VST", "USDT"):
        if (b.get(k) or {}).get("total") is not None:
            return f"{b[k]['total']:.2f} {k}"
    return "?"


def cerrar(sym):
    """Cierra a mercado lo que haya en el par y borra las ordenes de TP/SL que queden. True si cerro algo."""
    ex = _bingx()
    habia = bool(_posiciones(ex, sym))
    if habia:
        ex.close_position(sym)
    try:
        ex.cancel_all_orders(sym)
    except Exception:
        pass
    return habia


def prueba(sym, d=1):
    """Operacion minima de prueba en demo: abre con TP y SL a ±3%, mira que este todo y la cierra. Devuelve texto."""
    import time
    ex = _bingx()
    p = precio(sym)
    m = ex.market(sym)
    minimo = (m.get("limits", {}).get("amount", {}) or {}).get("min") or 0
    costo = (m.get("limits", {}).get("cost", {}) or {}).get("min") or 0
    qty = max(minimo, (max(costo, 6) / p) * 1.2)       # un poco mas que el minimo del par (BingX pide ~5 USDT)
    try:
        r = abrir(sym, d, qty, p * (1 - 0.03 * d), p * (1 + 0.03 * d), 2)
    except RuntimeError as e:
        if "ya hay" in str(e):
            return f"{sym}: no probé porque ya hay una posición abierta en la demo ({describir(sym)})"
        raise
    time.sleep(3)
    ordenes = ex.fetch_open_orders(sym)
    cerro = cerrar(sym)
    time.sleep(2)
    queda = _posiciones(ex, sym)
    return (f"{sym}: abrió {r['cantidad']} a {r['entrada']} (orden {r['id']}), TP/SL puestos y verificados en BingX "
            f"({len(ordenes)} órdenes), cerró: {'sí' if cerro and not queda else 'NO, revisá'}")
