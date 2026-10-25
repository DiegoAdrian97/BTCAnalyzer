"""
Prueba la idea: "cada vez que ZEC baja 20 USD abro long; cada vez que sube 20 USD cierro el long
y abro short (y al reves)", sin stop loss, con los mismos datos que backtest_grid.py.

Uso:
    .venv\\Scripts\\python.exe backtest_idea_20usd.py            # paso de 20 USD
    .venv\\Scripts\\python.exe backtest_idea_20usd.py --step 50
"""

import argparse

import ccxt

import backtest_grid as bg


def run(candles, step, leverage, start, end):
    cash = bg.CAPITAL_USDT
    side, entry, qty = 0, None, 0.0   # side: +1 long, -1 short, 0 sin posicion
    ref = candles[start][1]
    wins = 0
    worst_eq, worst_ts = cash, candles[start][0]

    def open_pos(new_side, price):
        nonlocal side, entry, qty, cash
        qty = int(cash * leverage / price / bg.QTY_STEP) * bg.QTY_STEP
        side, entry = new_side, price
        cash -= qty * price * bg.MAKER_FEE

    def close_pos(price):
        nonlocal side, cash, wins
        pnl = side * (price - entry) * qty
        cash += pnl - qty * price * bg.MAKER_FEE
        wins += pnl > 0
        side = 0

    for ts, o, h, l, c, _ in candles[start:end]:
        path = (o, l, h, c) if c >= o else (o, h, l, c)
        for a, b in zip(path, path[1:]):
            # recorrer el segmento en saltos de 'step' para no perder disparos dentro de la vela
            lo, hi = min(a, b), max(a, b)
            while True:
                if side == 0:
                    if b < a and lo <= ref - step:
                        open_pos(+1, ref - step)
                    elif b > a and hi >= ref + step:
                        open_pos(-1, ref + step)
                    else:
                        break
                elif side == +1 and b > a and hi >= entry + step:
                    px = entry + step
                    close_pos(px)
                    open_pos(-1, px)
                elif side == -1 and b < a and lo <= entry - step:
                    px = entry - step
                    close_pos(px)
                    open_pos(+1, px)
                else:
                    break
            # peor momento de la posicion abierta en este tramo
            if side:
                eq = cash + side * ((lo if side > 0 else hi) - entry) * qty
                if eq < worst_eq:
                    worst_eq, worst_ts = eq, ts
                if eq <= bg.CAPITAL_USDT * bg.LIQUIDATION_FRACTION:
                    return {"final": 0.0, "wins": wins, "liq_ts": ts, "worst_eq": eq,
                            "worst_ts": ts, "side": side, "entry": entry}
    final = cash + (side * (candles[end - 1][4] - entry) * qty if side else 0.0)
    return {"final": final, "wins": wins, "liq_ts": None, "worst_eq": worst_eq,
            "worst_ts": worst_ts, "side": side, "entry": entry}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=float, default=20.0)
    ap.add_argument("--days", type=int, default=365)
    args = ap.parse_args()
    candles, _ = bg.load_data(args.days, False)
    day = lambda ts: ccxt.Exchange.iso8601(ts)[:10]
    print(f"ZEC {day(candles[0][0])} a {day(candles[-1][0])}: {candles[0][1]:.2f} -> {candles[-1][4]:.2f}")
    print(f"Idea: paso {args.step:g} USD, sin stop, capital {bg.CAPITAL_USDT:g} USDT\n")

    # arrancar en distintos momentos para no depender de un solo dia de entrada
    n = len(candles)
    for lev in (1, 3):
        print(f"Apalancamiento x{lev}:")
        for start in range(0, n - 24 * 30, n // 8):
            r = run(candles, args.step, lev, start, n)
            head = f"  arranca {day(candles[start][0])} (ZEC {candles[start][1]:7.2f}):"
            if r["liq_ts"]:
                closed = f"{r['wins']:3d} trades cerrados, TODOS ganadores" if r["wins"] else "  0 trades cerrados"
                print(f"{head} {closed} ... y LIQUIDADO el "
                      f"{day(r['liq_ts'])} con un {'long' if r['side'] > 0 else 'short'} abierto en {r['entry']:.2f}")
            else:
                print(f"{head} {r['wins']:3d} trades cerrados ganadores, final {r['final']:6.1f} USDT, "
                      f"peor momento {r['worst_eq']:6.1f} USDT ({day(r['worst_ts'])})")
        print()


if __name__ == "__main__":
    main()
