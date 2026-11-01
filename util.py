"""Utilidades comunes del analista (antes salian de backtest_grid.py, que es otra herramienta y no se toca)."""
import os
import time

import ccxt

HOUR_MS = 3_600_000
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def reintentar(fn, *args, **kwargs):
    """Pedido a un exchange con reintentos ante cortes de red. Un bloqueo por exceso de pedidos no se reintenta."""
    for intento in range(5):
        try:
            return fn(*args, **kwargs)
        except (ccxt.DDoSProtection, ccxt.RateLimitExceeded):
            raise                   # reintentar solo alarga la sancion
        except (ccxt.NetworkError, ccxt.OperationFailed) as e:      # cortes temporales
            if intento == 4:
                raise
            print(f"  {e}; reintento en {2 ** intento * 2}s")
            time.sleep(2 ** intento * 2)
