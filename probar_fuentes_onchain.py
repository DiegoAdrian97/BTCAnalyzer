"""Prueba de fuentes on-chain gratis (corre en GitHub Actions): que historia dan y como se piden. Nov. 2026.
- bitcoin-data.com (BGeometrics, gratis sin clave: 10 pedidos por hora, ultimos 4 anos): CSV de cada metrica.
- looknode.com (graficos gratis): que pedidos hace la pagina para traer los datos de un grafico (con un navegador).
Uso: python probar_fuentes_onchain.py
"""
import time
import urllib.request

CAB = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
METRICAS = ["sth-realized-price", "lth-realized-price", "supply-profit", "nupl-sth", "sth-mvrv"]


def bgeometrics():
    for m in METRICAS:
        for u in (f"https://bitcoin-data.com/v1/{m}/csv", f"https://bitcoin-data.com/v1/{m}"):
            try:
                with urllib.request.urlopen(urllib.request.Request(u, headers=CAB), timeout=60) as r:
                    t = r.read().decode("utf-8", "replace")
                lineas = t.strip().splitlines()
                print(f"  {u}: {len(t)} bytes, {len(lineas)} lineas · primera {lineas[:2]} · ultima {lineas[-1:]}"[:600], flush=True)
                break
            except Exception as e:
                print(f"  {u} no: {e!r}"[:300], flush=True)
        time.sleep(3)


def looknode():
    from playwright.sync_api import sync_playwright
    vistos = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()

        def resp(r):
            try:
                ct = r.headers.get("content-type", "")
                if r.request.resource_type in ("xhr", "fetch") or "json" in ct:
                    cuerpo = r.text() if ("json" in ct or "text" in ct) else ""
                    vistos.append((r.request.method, r.url, r.status, ct, len(cuerpo), cuerpo[:300], r.request.post_data))
            except Exception as e:
                vistos.append(("?", r.url, "err", repr(e)[:80], 0, "", None))
        pg.on("response", resp)
        pg.goto("https://looknode.com/zh/chart/", wait_until="networkidle", timeout=90000)
        print("  titulo:", pg.title(), flush=True)
        for nombre in ("短期持有者已实现价格", "长期持有者已实现价格"):
            try:
                pg.get_by_text(nombre, exact=True).first.click(timeout=15000)
                pg.wait_for_timeout(6000)
                print(f"  clic en {nombre}: url {pg.url}", flush=True)
            except Exception as e:
                print(f"  no pude hacer clic en {nombre}: {e!r}"[:200], flush=True)
        b.close()
    for m, u, s, ct, n, cu, pd in vistos:
        print(f"  {m} {s} {u[:200]} · {ct[:40]} · {n} bytes · post {str(pd)[:200]} · {cu[:200]!r}", flush=True)


def _get_json(u):
    import json
    with urllib.request.urlopen(urllib.request.Request(u, headers={**CAB, "Referer": "https://www.looknode.com/zh/chart/"}), timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def looknode_api():
    """Sin navegador: la lista de graficos (api/chartInfo) y la serie de cada uno (api/<chart_id>)."""
    info = _get_json("https://www.looknode.com/api/chartInfo")["data"]
    graficos = []

    def recorrer(x, camino):
        if isinstance(x, dict):
            if "chart_id" in x:
                graficos.append((camino, x.get("chart_id"), {k: v for k, v in x.items() if k not in ("chart_id",) and isinstance(v, (str, int, float))}))
            for k, v in x.items():
                recorrer(v, camino + [k])
        elif isinstance(x, list):
            for v in x:
                recorrer(v, camino)
    recorrer(info, [])
    print(f"  {len(graficos)} graficos", flush=True)
    for cam, cid, meta in graficos:
        print(f"  {'/'.join(cam)[:40]:<40} {cid:<40} {str(meta)[:220]}", flush=True)
    claves = ("sth", "lth", "short", "long", "realized", "real", "nupl", "sopr", "profit", "mvrv", "rhodl", "cvdd", "balanced", "delta")
    for cam, cid, meta in graficos:
        if not any(k in str(cid).lower() for k in claves):
            continue
        try:
            d = _get_json(f"https://www.looknode.com/api/{cid}")
            s = d.get("data")
            if isinstance(s, list) and s:
                print(f"  OK {cid}: {len(s)} puntos · primero {str(s[0])[:120]} · ultimo {str(s[-1])[:120]}", flush=True)
            else:
                print(f"  {cid}: {str(d)[:300]}", flush=True)
        except Exception as e:
            print(f"  {cid} no: {e!r}"[:300], flush=True)
        time.sleep(1)


if __name__ == "__main__":
    print("=== looknode.com (api) ===", flush=True)
    try:
        looknode_api()
    except Exception as e:
        print("  looknode api no:", repr(e)[:300])
