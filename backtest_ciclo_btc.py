"""
Backtest de estrategias para un ciclo alcista de BTC, con velas diarias de Binance desde 2017.

Uso:
    .venv\\Scripts\\python.exe backtest_ciclo_btc.py
    .venv\\Scripts\\python.exe backtest_ciclo_btc.py --refresh

Idea: si 2027-2029 se parecen a ciclos anteriores, miramos como le fue a cada estrategia en
2019-2021 y 2023-2025 (ciclos alcistas) y tambien en 2018, 2022 y 2026 (por si la tesis falla).

Cada estrategia reparte el capital en "baldes" independientes:
- nucleo:    BTC spot comprado al inicio y nunca vendido
- tendencia: BTC spot solo mientras el precio cierra por encima de la media de N dias; si no, USDT
- satelite:  long en perpetuo con margen AISLADO; si lo liquidan se pierde solo ese balde
La senal se calcula con el cierre del dia y se ejecuta en la apertura del dia siguiente.
"""

import argparse
import csv
import os
from dataclasses import dataclass

import ccxt

# ===================== CONFIGURACION =====================
CAPITAL_USDT = 1000.0
SPOT_FEE = 0.001             # 0.1% spot
PERP_FEE = 0.0005            # 0.05% perpetuo (taker)
FUNDING_YEAR = 0.11          # costo anual del long en perpetuo (0.01% cada 8h); en euforia suele ser mayor
MAINT_MARGIN = 0.005
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "BTC_USDT_binance_1d.csv")
# =========================================================

DAY_MS = 86_400_000


@dataclass(frozen=True)
class Strategy:
    name: str
    core: float = 0.0            # fraccion del capital en el balde nucleo
    trend: float = 0.0           # fraccion en el balde tendencia
    sat: float = 0.0             # fraccion en el balde satelite
    sat_lev: float = 1.0
    sat_trend: bool = True       # satelite solo con tendencia a favor (False = siempre abierto)
    sma: int = 200


STRATEGIES = [
    Strategy("Comprar y mantener (spot)", core=1.0),
    Strategy("Tendencia spot (SMA200)", trend=1.0),
    Strategy("70% spot + 30% long x3 c/tendencia", core=0.7, sat=0.3, sat_lev=3),
    Strategy("50% spot + 50% long x2 c/tendencia", core=0.5, sat=0.5, sat_lev=2),
    Strategy("100% long x2 c/tendencia", sat=1.0, sat_lev=2),
    Strategy("100% long x2 siempre abierto", sat=1.0, sat_lev=2, sat_trend=False),
    Strategy("100% long x3 siempre abierto", sat=1.0, sat_lev=3, sat_trend=False),
    Strategy("80% spot + 20% long x2 siempre", core=0.8, sat=0.2, sat_lev=2, sat_trend=False),
    Strategy("80% spot + 20% long x3 siempre", core=0.8, sat=0.2, sat_lev=3, sat_trend=False),
]

# ciclo 2023-2025 entrando antes o despues del piso (nov-2022): hoy no sabemos si el piso ya paso
ENTRY_TEST = (["2022-04-01", "2022-07-01", "2022-10-01", "2023-01-01", "2023-07-01", "2024-01-01"], "2025-12-31")

PERIODS = [
    ("Ciclo alcista 2019-2021", "2019-01-01", "2021-12-31"),
    ("Ciclo alcista 2023-2025", "2023-01-01", "2025-12-31"),
    ("Bajista 2018", "2018-01-01", "2018-12-31"),
    ("Bajista 2022", "2022-01-01", "2022-12-31"),
    ("2026 hasta hoy", "2026-01-01", None),
    ("Todo (2018 a hoy)", "2018-01-01", None),
]


def load_candles(refresh):
    if not refresh and os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return [[int(r[0])] + [float(x) for x in r[1:]] for r in csv.reader(f)]
    ex = ccxt.binance({"enableRateLimit": True})
    since, out = ex.parse8601("2017-08-01T00:00:00Z"), []
    print("Bajando velas diarias de BTC/USDT de Binance desde 2017...")
    while True:
        batch = [c for c in ex.fetch_ohlcv("BTC/USDT", "1d", since=since, limit=1000) if not out or c[0] > out[-1][0]]
        if not batch:
            break
        out += batch
        since = out[-1][0] + DAY_MS
    out = [c for c in out if c[0] + DAY_MS <= ex.milliseconds()]  # sin la vela del dia en curso
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", newline="") as f:
        csv.writer(f).writerows(out)
    return out


def sma(values, n):
    out, acc = [None] * len(values), 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= n:
            acc -= values[i - n]
        if i >= n - 1:
            out[i] = acc / n
    return out


def simulate(st, candles, start, end):
    closes = [c[4] for c in candles]
    avg = sma(closes, st.sma)
    o0 = candles[start][1]

    core_btc = CAPITAL_USDT * st.core * (1 - SPOT_FEE) / o0
    trend_usdt, trend_btc = CAPITAL_USDT * st.trend, 0.0
    sat_usdt, sat = CAPITAL_USDT * st.sat, None   # sat = [margen, qty, entrada, precio_liq]
    liquidations = 0
    peak, max_dd, equity_curve = CAPITAL_USDT, 0.0, []

    for i in range(start, end):
        ts, o, h, l, c, _ = candles[i]
        up = i > 0 and avg[i - 1] is not None and closes[i - 1] > avg[i - 1]

        # --- ordenes en la apertura segun la senal de ayer ---
        if up and trend_usdt > 0:
            trend_btc, trend_usdt = trend_usdt * (1 - SPOT_FEE) / o, 0.0
        elif not up and trend_btc > 0:
            trend_usdt, trend_btc = trend_btc * o * (1 - SPOT_FEE), 0.0

        want_sat = up or not st.sat_trend
        if want_sat and sat is None and sat_usdt > 1.0:
            qty = sat_usdt * st.sat_lev / o
            margin = sat_usdt - qty * o * PERP_FEE
            sat = [margin, qty, o, o * (1 - 1 / st.sat_lev + MAINT_MARGIN)]
            sat_usdt = 0.0
        elif not want_sat and sat is not None:
            margin, qty, entry, _ = sat
            sat_usdt, sat = max(margin + qty * (o - entry) - qty * o * PERP_FEE, 0.0), None

        # --- durante el dia: liquidacion y funding del satelite ---
        if sat is not None:
            margin, qty, entry, liq = sat
            if l <= liq:
                sat, liquidations = None, liquidations + 1   # margen aislado perdido
            else:
                sat[0] -= qty * c * FUNDING_YEAR / 365
                if sat[0] + qty * (c - entry) <= 0:
                    sat, liquidations = None, liquidations + 1

        sat_value = sat[0] + sat[1] * (c - sat[2]) if sat else 0.0
        eq = core_btc * c + trend_btc * c + trend_usdt + sat_usdt + sat_value
        peak = max(peak, eq)
        max_dd = max(max_dd, 1 - eq / peak)
        equity_curve.append(eq)

    final = equity_curve[-1]
    years = (end - start) / 365
    return {
        "ret": (final / CAPITAL_USDT - 1) * 100,
        "cagr": ((final / CAPITAL_USDT) ** (1 / years) - 1) * 100 if final > 0 else -100.0,
        "dd": max_dd * 100,
        "liq": liquidations,
        "final": final,
    }


def index_of(candles, day):
    t = ccxt.Exchange.parse8601(day + "T00:00:00Z")
    return next(i for i, c in enumerate(candles) if c[0] >= t)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    candles = load_candles(args.refresh)
    day = lambda ts: ccxt.Exchange.iso8601(ts)[:10]
    print(f"{len(candles)} dias: {day(candles[0][0])} a {day(candles[-1][0])}. Capital {CAPITAL_USDT:g} USDT,"
          f" funding long {FUNDING_YEAR * 100:g}%/año, fees spot {SPOT_FEE * 100:g}% perp {PERP_FEE * 100:g}%")

    for name, d0, d1 in PERIODS:
        s = index_of(candles, d0)
        e = index_of(candles, d1) + 1 if d1 and d1 < day(candles[-1][0]) else len(candles)
        btc0, btc1 = candles[s][1], candles[e - 1][4]
        print(f"\n{name}  (BTC {btc0:,.0f} -> {btc1:,.0f}, {(btc1 / btc0 - 1) * 100:+.0f}%)")
        print(f"  {'estrategia':<38}{'resultado':>11}{'anual':>9}{'caida max':>11}{'liquid.':>9}")
        for st in STRATEGIES:
            r = simulate(st, candles, s, e)
            print(f"  {st.name:<38}{r['ret']:>+10.0f}%{r['cagr']:>+8.0f}%{r['dd']:>10.0f}%{r['liq']:>9d}")

    starts, end_day = ENTRY_TEST
    e = index_of(candles, end_day) + 1
    picks = [STRATEGIES[0], STRATEGIES[-2], STRATEGIES[-1], STRATEGIES[5], STRATEGIES[6]]
    print(f"\nCiclo 2023-2025 segun CUANDO entras (hasta {end_day}; BTC al final {candles[e - 1][4]:,.0f}):")
    print(f"  {'entrada':<12}{'BTC':>8}" + "".join(f"{p.name[:22]:>25}" for p in picks))
    for d in starts:
        s = index_of(candles, d)
        cells = []
        for p in picks:
            r = simulate(p, candles, s, e)
            cells.append(f"{r['ret']:+.0f}% dd{r['dd']:.0f}%" + (" LIQ" if r["liq"] else ""))
        print(f"  {d:<12}{candles[s][1]:>8,.0f}" + "".join(f"{x:>25}" for x in cells))

    print("\nSensibilidad de '70% spot + 30% long x3' a la media usada (Todo 2018 a hoy):")
    s = index_of(candles, "2018-01-01")
    for n in (50, 100, 150, 200, 250):
        r = simulate(Strategy("", core=0.7, sat=0.3, sat_lev=3, sma=n), candles, s, len(candles))
        print(f"  SMA{n:<4} {r['ret']:>+8.0f}%  anual {r['cagr']:+5.0f}%  caida max {r['dd']:3.0f}%  liquidaciones {r['liq']}")


if __name__ == "__main__":
    main()
