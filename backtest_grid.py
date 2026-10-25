"""
Backtester del bot de grilla neutral (grid_bot_zec.py) sobre datos historicos reales de BingX.

Uso:
    .venv\\Scripts\\python.exe backtest_grid.py                       # 365 dias, velas de 1h
    .venv\\Scripts\\python.exe backtest_grid.py --tf 15m --days 90    # mas detalle, menos historia
    .venv\\Scripts\\python.exe backtest_grid.py --refresh    # vuelve a bajar los datos

Que hace:
- Baja velas y el historial de funding de ZEC/USDT perpetuo (API publica, sin keys)
  y los guarda en data/ para no volver a bajarlos.
- Simula la grilla con comisiones maker/taker, slippage en los stops y funding cada 8h.
- Prueba muchas configuraciones (rango, grillas, sizing, filtro de lateralidad) y separa los
  datos en ENTRENAMIENTO (primeros 2/3) y PRUEBA (ultimo 1/3). Elegi configuraciones que
  anden bien en las dos partes: si solo anda en entrenamiento, es casualidad (sobreajuste).

Limitaciones (el resultado real va a ser algo peor):
- Dentro de cada vela se asume el recorrido apertura -> minimo -> maximo -> cierre (o al reves).
- Una orden limite se considera llena apenas el precio toca el nivel (sin cola de ordenes).
- No modela liquidacion; con stop y apalancamiento bajo no deberia ocurrir.
"""

import argparse
import csv
import itertools
import os
import time
from dataclasses import dataclass

import ccxt

# ===================== CONFIGURACION =====================
SYMBOL = "ZEC/USDT:USDT"
TIMEFRAME = "1h"             # BingX da ~1 año en 1h pero solo ~90 dias en 15m (--tf 15m --days 90)
CAPITAL_USDT = 100.0
MAKER_FEE = 0.0002           # 0.02% BingX perpetuos (ordenes limite)
TAKER_FEE = 0.0005           # 0.05% (cierres a mercado)
STOP_SLIPPAGE = 0.0005       # 0.05% de deslizamiento extra al cerrar a mercado
LIQUIDATION_FRACTION = 0.05  # con menos de este % del capital la cuenta se da por liquidada y deja de operar
QTY_STEP = 0.001             # precision de cantidad; se reemplaza por la del mercado al cargar los datos
MIN_QTY = 0.002
TRAIN_FRACTION = 2 / 3
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
# =========================================================

HOUR_MS = 3_600_000


@dataclass(frozen=True)
class Config:
    range_mode: str = "pct"      # pct = +/- %, atr = +/- k * ATR(1h), hl = maximo/minimo de los ultimos N dias
    range_val: float = 8.0
    grids: int = 20
    sizing: str = "fixed"        # fixed = como el bot (capital*apalancamiento/grillas), risk = perdida maxima por stop acotada
    leverage: float = 3.0
    risk_pct: float = 3.0        # con sizing=risk: % del capital que se pierde si salta el stop
    stop_buffer_pct: float = 2.0
    adx_max: float = 0.0         # 0 = sin filtro; si no, solo arma la grilla con ADX(1h) por debajo de este valor
    adx_exit: float = 0.0        # 0 = nunca; si no, cierra todo cuando ADX(1h) supera este valor
    cooldown_h: float = 12.0     # horas de espera despues de un stop antes de volver a armar

    def label(self):
        rng = {"pct": f"+/-{self.range_val:g}%", "atr": f"{self.range_val:g}xATR",
               "hl": f"HL{self.range_val:g}d"}[self.range_mode]
        size = f"fijo x{self.leverage:g}" if self.sizing == "fixed" else f"riesgo {self.risk_pct:g}%"
        filt = f"ADX<{self.adx_max:g}" if self.adx_max else "sin filtro"
        if self.adx_exit:
            filt += f" sale>{self.adx_exit:g}"
        return f"{rng:>9} {self.grids:>3}g  {size:<11} {filt}"


# ---------- datos ----------
def _cache_path(name):
    return os.path.join(DATA_DIR, f"{SYMBOL.split(':')[0].replace('/', '_')}_{name}.csv")


def _retry(fn, *args, **kwargs):
    for attempt in range(5):
        try:
            return fn(*args, **kwargs)
        except (ccxt.DDoSProtection, ccxt.RateLimitExceeded):
            raise                   # bloqueo por exceso de pedidos: reintentar solo alarga la sancion
        except (ccxt.NetworkError, ccxt.OperationFailed) as e:  # cortes temporales
            if attempt == 4:
                raise
            print(f"  BingX: {e}; reintento en {2 ** attempt * 2}s")
            time.sleep(2 ** attempt * 2)


def _paginate(fetch, since, step_ms, until, skip_ms=None):
    out = []
    while since < until:
        batch = [r for r in _retry(fetch, since) if not out or r[0] > out[-1][0]]
        if not batch:
            if out or not skip_ms:
                return out
            since += skip_ms  # el exchange no tiene datos tan viejos: avanzar
            continue
        out += batch
        since = out[-1][0] + step_ms
    return out


def _fetch_funding(ex, since, until):
    """BingX solo respeta 'since' si tambien va endTime: se pide en ventanas de 60 dias."""
    window = 60 * 24 * HOUR_MS
    out = {}
    for start in range(since, until, window):
        batch = _retry(ex.fetch_funding_rate_history, SYMBOL, since=start, limit=1000,
                       params={"endTime": min(start + window, until)})
        out.update((int(r["timestamp"]), float(r["fundingRate"])) for r in batch)
    return sorted((t, r) for t, r in out.items() if since <= t <= until)


def load_data(days, refresh):
    global QTY_STEP, MIN_QTY
    # el funding se guarda junto a las velas de cada timeframe porque cubre el mismo periodo
    candles_file, funding_file, meta_file = (_cache_path(TIMEFRAME), _cache_path(f"{TIMEFRAME}_funding"),
                                             _cache_path("meta"))
    if not refresh and all(os.path.exists(p) for p in (candles_file, funding_file, meta_file)):
        with open(candles_file) as f:
            candles = [[int(r[0])] + [float(x) for x in r[1:]] for r in csv.reader(f)]
        with open(funding_file) as f:
            funding = [(int(r[0]), float(r[1])) for r in csv.reader(f)]
        with open(meta_file) as f:
            QTY_STEP, MIN_QTY = (float(x) for x in next(csv.reader(f)))
        if candles and candles[0][0] <= candles[-1][0] - (days - 1) * 24 * HOUR_MS:
            cutoff = candles[-1][0] - days * 24 * HOUR_MS
            return [c for c in candles if c[0] >= cutoff], funding

    ex = ccxt.bingx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    ex.load_markets()
    market = ex.market(SYMBOL)
    QTY_STEP = float(market["precision"]["amount"])
    MIN_QTY = float(market["limits"]["amount"]["min"] or QTY_STEP)
    now = ex.milliseconds()
    since = now - days * 24 * HOUR_MS
    tf_ms = ex.parse_timeframe(TIMEFRAME) * 1000
    print(f"Bajando {days} dias de velas {TIMEFRAME} de {SYMBOL}...")
    candles = _paginate(lambda s: ex.fetch_ohlcv(SYMBOL, TIMEFRAME, since=s, limit=1000),
                        since, tf_ms, now, skip_ms=500 * tf_ms)
    candles = [c for c in candles if c[0] + tf_ms <= now]  # descarta la vela en curso
    if len(candles) < 500:
        raise SystemExit(f"BingX devolvio solo {len(candles)} velas {TIMEFRAME}; proba con --tf 1h o menos --days")
    print("Bajando historial de funding...")
    funding = _fetch_funding(ex, since, now)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(candles_file, "w", newline="") as f:
        csv.writer(f).writerows(candles)
    with open(funding_file, "w", newline="") as f:
        csv.writer(f).writerows(funding)
    with open(meta_file, "w", newline="") as f:
        csv.writer(f).writerow([QTY_STEP, MIN_QTY])
    return candles, funding


# ---------- indicadores (sobre velas de 1h, sin mirar el futuro) ----------
def resample_1h(candles):
    hours = {}
    for ts, o, h, l, c, v in candles:
        k = ts // HOUR_MS * HOUR_MS
        if k not in hours:
            hours[k] = [k, o, h, l, c]
        else:
            bar = hours[k]
            bar[2], bar[3], bar[4] = max(bar[2], h), min(bar[3], l), c
    return [hours[k] for k in sorted(hours)]


def wilder(values, n):
    out, avg = [None] * len(values), None
    for i, v in enumerate(values):
        if v is None:
            continue
        avg = v if avg is None else (avg * (n - 1) + v) / n
        out[i] = avg
    return out


def indicators(bars, n=14):
    """ATR y ADX de Wilder por barra de 1h (None mientras no hay datos suficientes)."""
    tr, pdm, mdm = [None], [None], [None]
    for prev, bar in zip(bars, bars[1:]):
        up, down = bar[2] - prev[2], prev[3] - bar[3]
        tr.append(max(bar[2] - bar[3], abs(bar[2] - prev[4]), abs(bar[3] - prev[4])))
        pdm.append(up if up > down and up > 0 else 0.0)
        mdm.append(down if down > up and down > 0 else 0.0)
    atr, apdm, amdm = wilder(tr, n), wilder(pdm, n), wilder(mdm, n)
    dx = []
    for a, p, m in zip(atr, apdm, amdm):
        if not a:
            dx.append(None)
            continue
        pdi, mdi = 100 * p / a, 100 * m / a
        dx.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0.0)
    adx = wilder(dx, n)
    warmup = 3 * n
    return [(atr[i], adx[i]) if i >= warmup else (None, None) for i in range(len(bars))]


class Market:
    """Velas de 15m con los indicadores de la ultima hora completa al cierre de cada vela."""

    def __init__(self, candles, funding):
        self.candles, self.funding = candles, funding
        self.tf_ms = candles[1][0] - candles[0][0]
        bars = resample_1h(candles)
        ind = indicators(bars)
        hour_idx = {b[0]: i for i, b in enumerate(bars)}
        self.atr, self.adx, self.hi_lo = [], [], []
        for ts, *_ in candles:
            i = hour_idx.get((ts + self.tf_ms) // HOUR_MS * HOUR_MS - HOUR_MS)
            if i is None:
                self.atr.append(None), self.adx.append(None), self.hi_lo.append(None)
                continue
            self.atr.append(ind[i][0])
            self.adx.append(ind[i][1])
            self.hi_lo.append(i)
        self.bars = bars

    def range_hl(self, i, days):
        j = self.hi_lo[i]
        n = int(days * 24)
        if j is None or j + 1 < n:
            return None
        window = self.bars[j + 1 - n:j + 1]
        return min(b[3] for b in window), max(b[2] for b in window)


# ---------- simulacion ----------
class Sim:
    def __init__(self, cfg, mkt):
        self.cfg, self.mkt = cfg, mkt
        self.cash, self.pos = CAPITAL_USDT, 0.0
        self.grid = None
        self.cooldown_until = 0
        self.fees = self.funding_paid = 0.0
        self.cycles = self.stops = self.trend_exits = self.starts = 0
        self.max_notional_x = 0.0
        self.liquidated = False

    def equity(self, price):
        return self.cash + self.pos * price

    def _trade(self, side, qty, price, fee):
        notional = qty * price
        self.cash += -notional if side == "buy" else notional
        self.pos += qty if side == "buy" else -qty
        self.cash -= notional * fee
        self.fees += notional * fee

    def close_all(self, price, adverse):
        if self.pos:
            px = price * (1 - STOP_SLIPPAGE) if self.pos > 0 else price * (1 + STOP_SLIPPAGE)
            if not adverse:
                px = price
            self._trade("sell" if self.pos > 0 else "buy", abs(self.pos), px, TAKER_FEE)
        self.grid = None

    def try_start(self, i, price):
        cfg, mkt = self.cfg, self.mkt
        if cfg.range_mode == "pct":
            lower, upper = price * (1 - cfg.range_val / 100), price * (1 + cfg.range_val / 100)
        elif cfg.range_mode == "atr":
            if mkt.atr[i] is None:
                return
            lower, upper = price - cfg.range_val * mkt.atr[i], price + cfg.range_val * mkt.atr[i]
        else:
            hl = mkt.range_hl(i, cfg.range_val)
            if hl is None:
                return
            lower, upper = hl
            # precio pegado a un borde = grilla desbalanceada; esperar
            if not lower + 0.2 * (upper - lower) <= price <= upper - 0.2 * (upper - lower):
                return
        if lower <= 0 or (upper - lower) / price < 0.02:
            return

        step = (upper - lower) / cfg.grids
        levels = [round(lower + k * step, 2) for k in range(cfg.grids + 1)]
        empty = min(range(len(levels)), key=lambda k: abs(levels[k] - price))
        lo_stop = levels[0] * (1 - cfg.stop_buffer_pct / 100)
        hi_stop = levels[-1] * (1 + cfg.stop_buffer_pct / 100)
        n_side = max(empty, cfg.grids - empty)
        eq = self.equity(price)

        if cfg.sizing == "fixed":
            qty = eq * cfg.leverage / cfg.grids / price  # como el bot, pero con el margen que queda
        else:
            loss_down = sum(levels[k] - lo_stop * (1 - STOP_SLIPPAGE) for k in range(empty))
            loss_up = sum(hi_stop * (1 + STOP_SLIPPAGE) - levels[k] for k in range(empty + 1, len(levels)))
            qty = cfg.risk_pct / 100 * eq / max(loss_down, loss_up)
            qty = min(qty, eq * cfg.leverage / (n_side * price))
        qty = int(qty / QTY_STEP) * QTY_STEP
        if qty < MIN_QTY:
            return

        orders = {k: ("buy" if k < empty else "sell", False) for k in range(len(levels)) if k != empty}
        self.grid = {"levels": levels, "orders": orders, "qty": qty, "lo_stop": lo_stop, "hi_stop": hi_stop}
        self.starts += 1

    def _fill(self, k):
        g = self.grid
        side, counter = g["orders"].pop(k)
        self._trade(side, g["qty"], g["levels"][k], MAKER_FEE)
        if counter:
            self.cycles += 1
        nxt = k + 1 if side == "buy" else k - 1
        if 0 <= nxt < len(g["levels"]) and nxt not in g["orders"]:
            g["orders"][nxt] = ("sell" if side == "buy" else "buy", True)
        self.max_notional_x = max(self.max_notional_x, abs(self.pos) * g["levels"][k] / CAPITAL_USDT)

    def segment(self, a, b):
        """Recorre el precio de a hasta b llenando ordenes en orden. Devuelve True si salto el stop."""
        g = self.grid
        lv = g["levels"]
        if b < a:
            stop = b <= g["lo_stop"]
            for k in sorted((k for k, (s, _) in g["orders"].items() if s == "buy" and b <= lv[k] <= a), reverse=True):
                if k in g["orders"]:
                    self._fill(k)
            if stop:
                self.close_all(g["lo_stop"], adverse=True)
        else:
            stop = b >= g["hi_stop"]
            for k in sorted(k for k, (s, _) in g["orders"].items() if s == "sell" and a <= lv[k] <= b):
                if k in g["orders"]:
                    self._fill(k)
            if stop:
                self.close_all(g["hi_stop"], adverse=True)
        return stop

    def run(self, start, end):
        mkt, cfg = self.mkt, self.cfg
        candles, funding = mkt.candles, mkt.funding
        fi = 0
        while fi < len(funding) and funding[fi][0] < candles[start][0]:
            fi += 1
        peak, max_dd = CAPITAL_USDT, 0.0
        daily, last_day = [], None
        bars_in_market = 0

        for i in range(start, end):
            ts, o, h, l, c, _ = candles[i]
            while fi < len(funding) and funding[fi][0] < ts + mkt.tf_ms:
                pay = self.pos * o * funding[fi][1]   # longs pagan funding positivo, shorts cobran
                self.cash -= pay
                self.funding_paid += pay
                fi += 1

            if self.grid:
                bars_in_market += 1
                path = (o, l, h, c) if c >= o else (o, h, l, c)
                for a, b in zip(path, path[1:]):
                    if self.segment(a, b):
                        self.stops += 1
                        self.cooldown_until = ts + mkt.tf_ms + cfg.cooldown_h * HOUR_MS
                        break

            if self.equity(min(l, c) if self.pos > 0 else max(h, c)) <= CAPITAL_USDT * LIQUIDATION_FRACTION:
                self.close_all(c, adverse=True)
                self.liquidated = True
                daily.append(self.cash)
                break

            adx = mkt.adx[i]
            if self.grid and cfg.adx_exit and adx is not None and adx > cfg.adx_exit:
                self.close_all(c, adverse=True)
                self.trend_exits += 1
            if (not self.grid and ts + mkt.tf_ms >= self.cooldown_until and adx is not None
                    and (not cfg.adx_max or adx < cfg.adx_max)):
                self.try_start(i, c)

            eq = self.equity(c)
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak)
            day = ts // (24 * HOUR_MS)
            if day != last_day:
                daily.append(eq)
                last_day = day
            else:
                daily[-1] = eq

        self.close_all(candles[end - 1][4], adverse=False)
        final = max(self.cash, 0.0)
        days_up = sum(1 for p, q in zip([CAPITAL_USDT] + daily, daily) if q > p + 1e-9)
        days_down = sum(1 for p, q in zip([CAPITAL_USDT] + daily, daily) if q < p - 1e-9)
        return {
            "ret": (final / CAPITAL_USDT - 1) * 100,
            "dd": max_dd * 100,
            "cycles": self.cycles,
            "stops": self.stops,
            "trend_exits": self.trend_exits,
            "fees": self.fees,
            "funding": self.funding_paid,
            "days_up": days_up,
            "days_down": days_down,
            "days": len(daily),
            "in_mkt": bars_in_market / (end - start) * 100,
            "max_x": self.max_notional_x,
            "liquidated": self.liquidated,
        }


def backtest(cfg, mkt, start, end):
    return Sim(cfg, mkt).run(start, end)


def all_configs():
    ranges = [("pct", 5), ("pct", 8), ("pct", 12), ("pct", 16),
              ("atr", 10), ("atr", 20), ("hl", 3), ("hl", 7), ("hl", 14)]
    sizings = [("fixed", 3.0), ("risk", 3.0)]
    filters = [(0, 0), (20, 0), (25, 0), (20, 35), (25, 40)]
    for (rm, rv), grids, (sz, val), (amax, aexit) in itertools.product(ranges, [10, 20, 40], sizings, filters):
        if sz == "fixed":
            yield Config(rm, rv, grids, "fixed", leverage=val, adx_max=amax, adx_exit=aexit)
        else:
            yield Config(rm, rv, grids, "risk", risk_pct=val, adx_max=amax, adx_exit=aexit)


def fmt(r):
    return (f"{r['ret']:+7.1f}% dd {r['dd']:5.1f}%  ciclos {r['cycles']:4d}  stops {r['stops']:2d}"
            f"+{r['trend_exits']:<2d} dias +{r['days_up']}/-{r['days_down']}  en mercado {r['in_mkt']:3.0f}%"
            + ("  ** LIQUIDADO **" if r["liquidated"] else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--refresh", action="store_true", help="volver a bajar los datos")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--tf", default=TIMEFRAME, help="timeframe de las velas (1h, 15m)")
    ap.add_argument("--symbol", default=SYMBOL, help="ej. BTC/USDT:USDT")
    ap.add_argument("--capital", type=float, default=CAPITAL_USDT,
                    help="USDT; en BTC usa 1000+ para que la orden minima no distorsione el sizing")
    args = ap.parse_args()
    globals().update(TIMEFRAME=args.tf, SYMBOL=args.symbol, CAPITAL_USDT=args.capital)
    base = SYMBOL.split("/")[0]

    candles, funding = load_data(args.days, args.refresh)
    mkt = Market(candles, funding)
    n = len(candles)
    split = int(n * TRAIN_FRACTION)
    day = lambda ts: ccxt.Exchange.iso8601(ts)[:10]
    print(f"\n{n} velas {TIMEFRAME}: {day(candles[0][0])} a {day(candles[-1][0])}")
    print(f"  entrenamiento: {day(candles[0][0])} a {day(candles[split - 1][0])}"
          f"  | {base} {candles[0][1]:.2f} -> {candles[split - 1][4]:.2f}"
          f" ({(candles[split - 1][4] / candles[0][1] - 1) * 100:+.1f}%)")
    print(f"  prueba:        {day(candles[split][0])} a {day(candles[-1][0])}"
          f"  | {base} {candles[split][1]:.2f} -> {candles[-1][4]:.2f}"
          f" ({(candles[-1][4] / candles[split][1] - 1) * 100:+.1f}%)")
    print(f"  capital {CAPITAL_USDT:g} USDT, maker {MAKER_FEE * 100:g}%, taker {TAKER_FEE * 100:g}%"
          f" + slippage {STOP_SLIPPAGE * 100:g}% en stops\n")

    baseline = Config()  # lo que hace hoy grid_bot_zec.py
    print("CONFIG ACTUAL DEL BOT:", baseline.label())
    print("  entrenamiento", fmt(backtest(baseline, mkt, 0, split)))
    print("  prueba       ", fmt(backtest(baseline, mkt, split, n)))
    print("  periodo total", fmt(backtest(baseline, mkt, 0, n)))

    configs = list(all_configs())
    print(f"\nProbando {len(configs)} configuraciones...")
    results = []
    for cfg in configs:
        tr = backtest(cfg, mkt, 0, split)
        results.append((cfg, tr))

    # orden por retorno ajustado por caida maxima en entrenamiento
    score = lambda r: r["ret"] / max(r["dd"], 1.0)
    results.sort(key=lambda x: score(x[1]), reverse=True)
    print(f"\nTOP {args.top} EN ENTRENAMIENTO (ordenado por retorno / caida maxima) y como les fue en PRUEBA:")
    for cfg, tr in results[:args.top]:
        te = backtest(cfg, mkt, split, n)
        print(f"\n  {cfg.label()}")
        print(f"    entrenamiento {fmt(tr)}")
        print(f"    prueba        {fmt(te)}  | fees {te['fees']:.2f} funding {te['funding']:+.2f}"
              f" exposicion max {te['max_x']:.1f}x")

    positives = sum(1 for _, r in results if r["ret"] > 0)
    print(f"\n{positives}/{len(results)} configuraciones ganaron en entrenamiento.")


if __name__ == "__main__":
    main()
