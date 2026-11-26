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


if __name__ == "__main__":
    print("=== bitcoin-data.com ===", flush=True)
    bgeometrics()
    print("\n=== looknode.com ===", flush=True)
    try:
        looknode()
    except Exception as e:
        print("  looknode no:", repr(e)[:300])
