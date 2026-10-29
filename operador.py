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


def abrir(sym, d, qty, sl, tp, lev):
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
    gat = {"type": "STOP_MARKET", "triggerPrice": float(ex.price_to_precision(sym, sl)), "workingType": "CONTRACT_PRICE"}
    obj = {"type": "TAKE_PROFIT_MARKET", "triggerPrice": float(ex.price_to_precision(sym, tp)), "workingType": "CONTRACT_PRICE"}
    orden = ex.create_order(sym, "market", "buy" if d > 0 else "sell", amount, None,
                            {"hedged": hedged, "stopLoss": gat, "takeProfit": obj})
    pos = _posiciones(ex, sym)
    entrada = float(pos[0].get("entryPrice") or 0) if pos else float(orden.get("average") or 0)
    return {"id": orden.get("id"), "cantidad": amount, "entrada": entrada, "abierta": bool(pos)}


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
    r = abrir(sym, d, qty, p * (1 - 0.03 * d), p * (1 + 0.03 * d), 2)
    time.sleep(3)
    pos = _posiciones(ex, sym)
    ordenes = ex.fetch_open_orders(sym)
    cerro = cerrar(sym)
    time.sleep(2)
    queda = _posiciones(ex, sym)
    return (f"{sym}: abrió {r['cantidad']} a {r['entrada']}, posición vista: {'sí' if pos else 'NO'}, "
            f"órdenes TP/SL en BingX: {len(ordenes)}, cerró: {'sí' if cerro and not queda else 'NO, revisá'}")
