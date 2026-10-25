"""
Bot de grilla neutral para ZEC/USDT perpetuo en BingX (modo DEMO / VST).

Uso:
    pip install ccxt
    export BINGX_API_KEY="tu_key_demo"
    export BINGX_API_SECRET="tu_secret_demo"
    python grid_bot_zec.py

IMPORTANTE:
- Pensado para la cuenta DEMO de BingX (fondos virtuales VST). Mantene DEMO = True.
- Sin testear contra la API en vivo: probalo primero con DRY_RUN = True y revisa los logs.
- Una grilla gana en mercado lateral y pierde si el precio sale del rango.
  No existe garantia de ganancias.
"""

import os
import time
import logging
import ccxt

# ===================== CONFIGURACION =====================
SYMBOL = "ZEC/USDT:USDT"     # perpetuo lineal en ccxt
DEMO = True                  # True = cuenta demo de BingX (VST)
demo_trading=True
DRY_RUN = True               # True = solo loguea, no envia ordenes. Pasalo a False cuando todo se vea bien

CAPITAL_USDT = 100.0         # margen que asignas al bot
LEVERAGE = 3                 # bajo a proposito
LOWER_PRICE = 0.0            # 0 = calcular automaticamente alrededor del precio actual
UPPER_PRICE = 0.0
AUTO_RANGE_PCT = 8.0         # si LOWER/UPPER = 0: rango = precio actual +/- este %
GRID_COUNT = 20              # cantidad de intervalos de la grilla
STOP_BUFFER_PCT = 2.0        # si el precio sale del rango por mas de este %, cierra todo y para
POLL_SECONDS = 5
# =========================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("grid")


def make_exchange():
    ex = ccxt.bingx({
        "apiKey": os.getenv("BINGX_API_KEY", ""),
        "secret": os.getenv("BINGX_API_SECRET", ""),
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    })
    if DEMO:
        ex.set_sandbox_mode(True)  # apunta al entorno demo (VST)
    ex.load_markets()
    return ex


def build_levels(lower, upper, n):
    step = (upper - lower) / n
    return [lower + i * step for i in range(n + 1)]


class GridBot:
    def __init__(self):
        self.ex = make_exchange()
        self.market = self.ex.market(SYMBOL)
        price = self.last_price()

        self.lower = LOWER_PRICE or price * (1 - AUTO_RANGE_PCT / 100)
        self.upper = UPPER_PRICE or price * (1 + AUTO_RANGE_PCT / 100)
        self.levels = [float(self.ex.price_to_precision(SYMBOL, p))
                       for p in build_levels(self.lower, self.upper, GRID_COUNT)]

        notional_per_grid = CAPITAL_USDT * LEVERAGE / GRID_COUNT
        self.qty = float(self.ex.amount_to_precision(SYMBOL, notional_per_grid / price))
        min_amt = (self.market.get("limits", {}).get("amount", {}) or {}).get("min")
        if self.qty <= 0 or (min_amt and self.qty < min_amt):
            raise SystemExit(
                f"Cantidad por grilla ({self.qty}) menor al minimo ({min_amt}). "
                f"Baja GRID_COUNT o sube capital/apalancamiento."
            )

        self.orders = {}  # order_id -> (level_index, side)
        self.stopped = False
        step_pct = (self.levels[1] / self.levels[0] - 1) * 100
        log.info("Rango %.4f - %.4f | %d grillas | paso ~%.2f%% | qty/grilla %s",
                 self.levels[0], self.levels[-1], GRID_COUNT, step_pct, self.qty)
        if step_pct < 0.25:
            log.warning("Paso menor a ~0.25%%: las comisiones pueden comerse la ganancia por ciclo.")

    # ---------- utilidades ----------
    def last_price(self):
        return float(self.ex.fetch_ticker(SYMBOL)["last"])

    def place(self, side, idx):
        price = self.levels[idx]
        if DRY_RUN:
            log.info("[DRY] %s limit %s @ %s", side, self.qty, price)
            oid = f"dry-{side}-{idx}-{time.time()}"
        else:
            o = self.ex.create_order(SYMBOL, "limit", side, self.qty, price,
                                     params={"positionSide": "BOTH"})
            oid = o["id"]
            log.info("%s limit %s @ %s (id %s)", side, self.qty, price, oid)
        self.orders[oid] = (idx, side)

    # ---------- arranque ----------
    def start(self):
        if not DRY_RUN:
            try:
                self.ex.set_leverage(LEVERAGE, SYMBOL, params={"side": "BOTH"})
            except Exception as e:
                log.warning("No se pudo fijar apalancamiento: %s", e)

        price = self.last_price()
        for i, lvl in enumerate(self.levels):
            if lvl < price * 0.999:
                self.place("buy", i)
            elif lvl > price * 1.001:
                self.place("sell", i)
        log.info("Grilla inicial colocada. Precio actual %.4f", price)

    # ---------- bucle ----------
    def check_fills(self):
        if DRY_RUN:
            return  # en dry-run no hay fills reales
        open_ids = {o["id"] for o in self.ex.fetch_open_orders(SYMBOL)}
        for oid, (idx, side) in list(self.orders.items()):
            if oid in open_ids:
                continue
            try:
                o = self.ex.fetch_order(oid, SYMBOL)
            except Exception as e:
                log.warning("No pude consultar %s: %s", oid, e)
                continue
            status = o.get("status")
            if status == "closed":
                del self.orders[oid]
                log.info("FILL %s nivel %d @ %s", side, idx, self.levels[idx])
                if side == "buy" and idx + 1 < len(self.levels):
                    self.place("sell", idx + 1)
                elif side == "sell" and idx - 1 >= 0:
                    self.place("buy", idx - 1)
            elif status in ("canceled", "expired", "rejected"):
                del self.orders[oid]
                log.warning("Orden %s %s; nivel %d queda sin orden", oid, status, idx)

    def check_stop(self):
        price = self.last_price()
        lo = self.levels[0] * (1 - STOP_BUFFER_PCT / 100)
        hi = self.levels[-1] * (1 + STOP_BUFFER_PCT / 100)
        if price < lo or price > hi:
            log.error("Precio %.4f fuera del rango. Cerrando todo.", price)
            self.shutdown()
            self.stopped = True

    def shutdown(self):
        if DRY_RUN:
            log.info("[DRY] cancelaria ordenes y cerraria posicion")
            return
        try:
            self.ex.cancel_all_orders(SYMBOL)
        except Exception as e:
            log.warning("Error cancelando ordenes: %s", e)
        try:
            for p in self.ex.fetch_positions([SYMBOL]):
                amt = abs(float(p.get("contracts") or 0))
                if amt > 0:
                    side = "sell" if p["side"] == "long" else "buy"
                    self.ex.create_order(SYMBOL, "market", side, amt,
                                         params={"positionSide": "BOTH", "reduceOnly": True})
                    log.info("Posicion cerrada: %s %s", side, amt)
        except Exception as e:
            log.error("Error cerrando posicion (revisa manualmente!): %s", e)

    def run(self):
        self.start()
        try:
            while not self.stopped:
                self.check_fills()
                self.check_stop()
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            log.info("Detenido por el usuario. Cancelando ordenes y cerrando posicion...")
            self.shutdown()


if __name__ == "__main__":
    GridBot().run()