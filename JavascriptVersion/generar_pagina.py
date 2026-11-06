"""Arma JavascriptVersion/index.html a partir de dashboard/index.html, la misma pagina que usa la version en Python.

Correrlo cada vez que cambie dashboard/index.html:  python JavascriptVersion/generar_pagina.py

El estilo y el codigo de la pagina van en archivos aparte con su huella en el nombre (p-<huella>.css / .js), guardados
un año en el telefono (vercel.json): el HTML queda chico (antes 310 KB que se revalidaban en cada visita) y en las
visitas siguientes solo baja si cambio. Los scripts van con defer: la pagina se pinta sin esperar a d3 ni al grafico.
lib/d3-7.9-reducido.min.js es d3 con solo lo que usa la pagina (select, scaleLinear, extent, area, line,
curveMonotoneX, arc, formatLocale): 20 KB comprimido en vez de 92. Se arma con esbuild desde los modulos d3-*.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "..", "dashboard", "index.html")
OUT = os.path.join(HERE, "index.html")

SHELL = """<!doctype html>
<!-- Generado por generar_pagina.py desde dashboard/index.html: no editar a mano -->
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Analista BTC</title>
<meta name="description" content="Análisis de BTC/USDT en vivo, calculado en el teléfono.">
<meta name="theme-color" content="#0a0c10">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Analista BTC">
<link rel="manifest" href="manifest.json">
<link rel="apple-touch-icon" href="icono-180.png">
<link rel="icon" type="image/png" href="icono-192.png">
<style>
:root { --color-fg: #1d2129; --color-fg-muted: #6a7180; --color-bg: #f3f4f6; --color-panel: #ffffff;
  --color-border-line: #e2e5ea; --color-ok: #138a5b; --color-warn: #b7791f; --color-bad: #c8423a;
  --font-anthropic-sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-anthropic-serif: Georgia, "Times New Roman", serif;
  --cds-font-size-caption: .78rem; --cds-font-size-body: .95rem; --cds-font-size-heading: 1.08rem; --cds-font-size-title: 1.6rem;
  --cds-font-weight-medium: 600; --cds-gap-xs: 4px; --cds-gap-sm: 8px; --cds-gap-md: 14px; --cds-gap-lg: 22px; --cds-gap-xl: 32px;
  --cds-pad-xs: 4px; --cds-pad-sm: 8px; --cds-pad-md: 12px; --cds-pad-lg: 18px; --cds-pad-xl: 28px; --cds-radius: 8px;
  --cds-chart-grid: #eceef2; --cds-surface-popover: #ffffff; --cds-border: #dde1e7; --cds-shadow-popover: 0 6px 24px rgba(20,24,32,.12);
  --cds-text-secondary: #6a7180; --cds-ease-out: cubic-bezier(.2,.8,.2,1); --cds-dur-slow: .4s; color-scheme: light; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --color-fg: #e8eaee; --color-fg-muted: #949bab; --color-bg: #121418; --color-panel: #1b1e24;
  --color-border-line: #2b3038; --color-ok: #3cc58a; --color-warn: #e0a64a; --color-bad: #f0645a; --cds-chart-grid: #252a31;
  --cds-surface-popover: #22262d; --cds-border: #343a43; --cds-shadow-popover: 0 6px 24px rgba(0,0,0,.45); --cds-text-secondary: #949bab; color-scheme: dark; } }
:root[data-theme="dark"] { --color-fg: #e8eaee; --color-fg-muted: #949bab; --color-bg: #121418; --color-panel: #1b1e24;
  --color-border-line: #2b3038; --color-ok: #3cc58a; --color-warn: #e0a64a; --color-bad: #f0645a; --cds-chart-grid: #252a31;
  --cds-surface-popover: #22262d; --cds-border: #343a43; --cds-shadow-popover: 0 6px 24px rgba(0,0,0,.45); --cds-text-secondary: #949bab; color-scheme: dark; }
html { -webkit-text-size-adjust: 100%; touch-action: manipulation; }   /* sin zoom por doble toque */
body { margin: 0; background: var(--color-bg); color: var(--color-fg); font: 14px var(--font-anthropic-sans); }
/* abierta desde la pantalla de inicio del iPhone: respeta la isla y la barra de abajo */
#dash-root { padding-top: max(24px, calc(env(safe-area-inset-top) + 22px)); padding-bottom: max(40px, calc(env(safe-area-inset-bottom) + 56px));
  padding-left: max(16px, var(--dash-gutter, 24px), env(safe-area-inset-left)); padding-right: max(16px, var(--dash-gutter, 24px), env(safe-area-inset-right)); }
#estado-app { position: fixed; left: 50%; transform: translateX(-50%); bottom: max(14px, env(safe-area-inset-bottom)); z-index: 20;
  display: flex; align-items: center; gap: 8px; max-width: min(34rem, calc(100vw - 32px)); padding: 9px 14px; border-radius: 999px;
  background: var(--cds-surface-popover); border: 1px solid var(--cds-border); box-shadow: var(--cds-shadow-popover);
  font-size: .8rem; line-height: 1.35; color: var(--color-fg); }
#estado-app[hidden] { display: none; }
#estado-app i { flex: none; width: 8px; height: 8px; border-radius: 50%; background: var(--color-ok); animation: ea 1.1s infinite alternate; }
#estado-app.es-error i { background: var(--color-bad); animation: none; }
@keyframes ea { to { opacity: .25; } }
</style>
<link rel="preconnect" href="https://fapi.binance.com" crossorigin>
<link rel="preconnect" href="https://api.bybit.com" crossorigin>
<link rel="stylesheet" href="__CSS__">
<script>window.AB_PAGINA = "__PAG__";</script>
<script defer src="app.js?v=__VER__"></script>
<script defer src="lib/d3-7.9-reducido.min.js"></script>
<script defer src="lib/lightweight-charts-5.1.0.js"></script>
<script defer src="__JS__"></script>
</head><body><div id="dash-root">
__PAGE__
</div>
<div id="estado-app" role="status" aria-live="polite"><i></i><span>Preparando el primer análisis…</span></div>
</body></html>
"""

# lo que en la version JS es distinto: BingX no se puede leer desde una pagina web
CAMBIOS = [
    ("Son órdenes esperando, no posiciones: pueden retirarse. BingX no entra en el total porque publica mucho más volumen que el resto.",
     "Son órdenes esperando, no posiciones: pueden retirarse."),
    ("Datos públicos de Binance Futures, Bybit, OKX, Bitget y BingX.",
     "Datos públicos de Binance Futures, Bybit, OKX y Bitget, calculados en este teléfono."),
]


def version():
    """Huella del codigo de la app: va en ?v= de cada archivo, asi el iPhone no se queda con una version vieja guardada."""
    import hashlib
    h = hashlib.sha1()
    for f in ("app.js", "worker.js", "analisis.js", "datos.js", "indicadores.js", "aprendizaje.js", "fuerte.js"):
        with open(os.path.join(HERE, f), "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:10]


def main():
    with open(PAGE, encoding="utf-8") as f:
        page = f.read()
    for old, new in CAMBIOS:
        if old not in page:
            raise SystemExit(f"No encontre en dashboard/index.html el texto a cambiar: {old[:60]}...")
        page = page.replace(old, new)
    # el plan de compras NO va en esta pagina (es publica): lo entrega api/posiciones, solo con la contraseña de BingX,
    # desde el repositorio privado DiegoAdrian97/BTCAnalyzer-plan
    import hashlib, re, glob
    # el estilo y el codigo, a archivos con huella (se borran los de versiones anteriores)
    m_css = re.search(r"<style>\n?(.*?)</style>", page, re.S)
    m_js = re.search(r"<script>\n?(.*?)</script>", page, re.S)
    if not m_css or not m_js or page.count("<script") != 1 or page.count("<style") != 1:
        raise SystemExit("dashboard/index.html tiene que tener un solo <style> y un solo <script>")
    css, js = m_css.group(1), m_js.group(1)
    nombres = {}
    for ext, cuerpo in (("css", css), ("js", js)):
        nombres[ext] = f"p-{hashlib.sha1(cuerpo.encode('utf-8')).hexdigest()[:10]}.{ext}"
        for viejo in glob.glob(os.path.join(HERE, f"p-*.{ext}")):
            if os.path.basename(viejo) != nombres[ext]:
                os.remove(viejo)
        with open(os.path.join(HERE, nombres[ext]), "w", encoding="utf-8", newline="\n") as f:
            f.write(cuerpo)
    page = page.replace(m_css.group(0), "").replace(m_js.group(0), "")
    html = SHELL.replace("__PAGE__", page).replace("__VER__", version()).replace("__CSS__", nombres["css"]).replace("__JS__", nombres["js"])
    pag = hashlib.sha1(html.encode("utf-8")).hexdigest()[:10]      # huella de la pagina entera (incluye las de css y js)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(html.replace("__PAG__", pag))
    # la app abierta en el iPhone compara su huella con esta: si hay una version nueva, se recarga sola
    with open(os.path.join(HERE, "version.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(pag + "\n")
    print("listo:", OUT, pag)


if __name__ == "__main__":
    main()
