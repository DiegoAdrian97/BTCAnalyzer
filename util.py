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


# ---------- plan de compras de Diego (privado) ----------
PLAN_LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plan_compras.json")
_plan_cache = [0.0, None]


def leer_plan():
    """El plan de compras. Es privado: no esta en este repositorio sino en uno privado (PLAN_REPO, por defecto
    DiegoAdrian97/BTCAnalyzer-plan) que se lee con un token de GitHub de SOLO LECTURA en la variable de entorno
    PLAN_GITHUB_TOKEN (Render). Sin token, el archivo plan_compras.json de esta carpeta si existe (en tu PC).
    Cinco minutos en memoria; si GitHub falla, queda el ultimo que se leyo."""
    tok = os.environ.get("PLAN_GITHUB_TOKEN")
    if tok:
        if _plan_cache[1] is not None and time.time() - _plan_cache[0] < 300:
            return _plan_cache[1]
        import json
        import urllib.request
        repo = os.environ.get("PLAN_REPO", "DiegoAdrian97/BTCAnalyzer-plan")
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/contents/plan_compras.json", headers={
            "Authorization": f"Bearer {tok}", "Accept": "application/vnd.github.raw+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "AnalistaBTC"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                plan = json.loads(r.read())
            _plan_cache[:] = [time.time(), plan]
            return plan
        except Exception as e:
            print(f"(plan privado: {type(e).__name__})", flush=True)
            return _plan_cache[1]
    if os.path.exists(PLAN_LOCAL):
        import json
        with open(PLAN_LOCAL, encoding="utf-8") as f:
            return json.load(f)
    return None

