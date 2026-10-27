"""Lo que pasa fuera del grafico: titulares de las ultimas horas, flujos de los ETF de BTC y la prima de Coinbase.

Sirve para explicar los movimientos fuertes: si coinciden con una noticia (una guerra, la Fed, aranceles, un hackeo),
con entradas o salidas de los ETF, o con compras desde EE.UU. Fuentes publicas, sin claves:
- Google Noticias (RSS en español) y CoinDesk (RSS): titulares.
- Farside Investors: entradas y salidas diarias de los ETF de BTC de EE.UU. (millones de USD).
- Coinbase y Bybit: precio de BTC en dolares en EE.UU. contra el de USDT afuera.

La version JavaScript (Vercel) hace lo mismo en JavascriptVersion/api/contexto.js: mismas fuentes, mismas filas.
"""
import html
import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

UA = "Mozilla/5.0 (compatible; AnalistaBTC/1.0)"
GN = "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q="
FEEDS = [
    ("cripto", GN + "bitcoin+OR+criptomonedas+OR+BTC+when:1d"),
    ("mundo", GN + "guerra+OR+misiles+OR+ataque+OR+aranceles+OR+%22Reserva+Federal%22+OR+inflaci%C3%B3n+OR+Trump+when:1d"),
    ("cripto", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
]
FARSIDE = "https://farside.co.uk/bitcoin-etf-flow-all-data/"
# temas, en orden de prioridad: el primero que aparece en el titular manda
TEMAS = [
    ("Guerra y geopolítica", r"guerra|\bwar\b|misil|missile|ataque|attack|invasi|bombard|israel|ir[aá]n\b|rusia|russia|ucrania|ukrain|taiw[aá]n|\botan\b|\bnato\b|sancion|sanction|conflicto|militar"),
    ("Fed, tasas e inflación", r"\bfed\b|reserva federal|federal reserve|powell|tasas? de inter|interest rate|rate cut|inflaci|inflation|\bcpi\b|\bipc\b|empleo|payroll|desempleo|recesi|recession"),
    ("Aranceles y política", r"arancel|tariff|trump|shutdown|congreso|congress|elecci|election"),
    ("ETF", r"\betfs?\b|blackrock|\bibit\b|fidelity|grayscale|fondos cotizados"),
    ("Regulación", r"\bsec\b|regulac|regulat|\bley\b|\blaw\b|prohib|\bban\b|\bcftc\b|stablecoin bill|clarity act"),
    ("Hackeo o quiebra", r"hack|robo\b|robaron|exploit|quiebra|bankrupt|insolven|congela|freez"),
    ("Ballenas y empresas", r"ballena|whale|strategy|microstrategy|saylor|tesla|tesorer|treasury|reserva estrat|strategic reserve|mt\.? ?gox"),
    ("Liquidaciones", r"liquidac|liquidat"),
]
CRIPTO = r"bitcoin|\bbtc\b|cripto|crypto"


def _get(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def tema(titulo, feed):
    """De que habla un titular. None: no tiene que ver con lo que mueve a BTC (se descarta)."""
    t = titulo.lower()
    for name, rx in TEMAS:
        if re.search(rx, t):
            return name
    return "Cripto" if feed == "cripto" and re.search(CRIPTO, t) else None


def _tag(item, name):
    m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", item, re.S)
    if not m:
        return ""
    s = m.group(1).strip()
    s = re.sub(r"^<!\[CDATA\[(.*)\]\]>$", r"\1", s, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def parse_rss(xml, feed, now_ms, horas=24):
    """Titulares de un RSS: hora (ms), titulo, fuente, link y tema. Solo los de las ultimas `horas`."""
    out = []
    for item in re.findall(r"<item\b.*?</item>", xml, re.S):
        title, link, fuente = _tag(item, "title"), _tag(item, "link"), _tag(item, "source")
        try:
            t = int(parsedate_to_datetime(_tag(item, "pubDate")).timestamp() * 1000)
        except (TypeError, ValueError):
            continue
        if not title or t > now_ms + 600_000 or now_ms - t > horas * 3_600_000:
            continue
        # Google Noticias agrega " - Medio" al final del titulo
        if fuente and title.endswith(" - " + fuente):
            title = title[: -len(fuente) - 3].strip()
        if not fuente:
            m = re.match(r"https?://(?:www\.)?([^/]+)", link)
            fuente = m.group(1) if m else ""
        tm = tema(title, feed)
        if tm:
            out.append({"tabla": "noticia", "t": t, "titulo": title[:220], "fuente": fuente[:60], "url": link, "tema": tm})
    return out


def juntar(listas, maximo=30):
    """Une titulares de varias fuentes: sin repetidos, los mas nuevos primero."""
    seen, out = set(), []
    for r in sorted((x for xs in listas for x in xs), key=lambda x: -x["t"]):
        k = re.sub(r"[^a-z0-9áéíóúñ]+", "", r["titulo"].lower())[:60]
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out[:maximo]


MESES = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}


def parse_farside(page, dias=10):
    """Entradas (+) y salidas (-) netas de los ETF de BTC de EE.UU. por dia, en millones de USD."""
    out = []
    for tr in re.findall(r"<tr\b.*?</tr>", page, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", tr, re.S)]
        if len(cells) < 3:
            continue
        m = re.match(r"^(\d{1,2}) (\w{3}) (\d{4})$", cells[0])
        if not m or m.group(2) not in MESES:
            continue
        v = cells[-1].replace(",", "").strip()
        if v in ("", "-"):
            continue
        neg = v.startswith("(") and v.endswith(")")
        try:
            x = float(v.strip("()"))
        except ValueError:
            continue
        out.append({"tabla": "etf", "fecha": f"{m.group(3)}-{MESES[m.group(2)]:02d}-{int(m.group(1)):02d}", "neto": round(-x if neg else x, 1)})
    out.sort(key=lambda r: r["fecha"])
    return out[-dias:]


def prima_coinbase(cb_usd, spot_usdt, usdt_usd):
    """Cuanto mas se paga BTC en Coinbase (dolares, EE.UU.) que afuera (USDT), en %. Fila de contexto."""
    p = (cb_usd / (spot_usdt * (usdt_usd or 1.0)) - 1) * 100
    sig = "alcista" if p > 0.05 else "bajista" if p < -0.05 else "neutral"
    txt = ("En EE.UU. pagan más que afuera: compran desde EE.UU. (fondos, empresas)" if sig == "alcista" else
           "En EE.UU. pagan menos que afuera: venden desde EE.UU." if sig == "bajista" else "Parejo con el resto del mundo")
    return {"tabla": "contexto", "clave": "prima_coinbase", "titulo": "Prima de Coinbase", "valor": f"{p:+.3f}%".replace(".", ","),
            "senal": sig, "detalle": txt, "prima": round(p, 4)}


def _prima():
    cb = float(json.loads(_get("https://api.exchange.coinbase.com/products/BTC-USD/ticker"))["price"])
    ut = float(json.loads(_get("https://api.exchange.coinbase.com/products/USDT-USD/ticker"))["price"])
    by = json.loads(_get("https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT"))
    spot = float(by["result"]["list"][0]["lastPrice"])
    return prima_coinbase(cb, spot, ut)


def externo(now_ms=None, moneda="BTC"):
    """Todas las filas de afuera. Cada fuente es opcional: si una falla, el resto sirve."""
    now_ms = now_ms or int(time.time() * 1000)

    def intento(nombre, fn):
        try:
            return fn()
        except Exception as e:
            print(f"({nombre} no disponible: {type(e).__name__})")
            return None

    # todas las fuentes a la vez: si alguna tarda, no frena al resto
    with ThreadPoolExecutor(max_workers=6) as pool:
        feeds = [pool.submit(intento, f"noticias {url[:40]}", lambda f=feed, u=url: parse_rss(_get(u), f, now_ms)) for feed, url in FEEDS]
        etf = pool.submit(intento, "flujos de ETF", lambda: parse_farside(_get(FARSIDE)))
        pr = pool.submit(intento, "prima de Coinbase", _prima) if moneda == "BTC" else None
        rows = juntar([x.result() or [] for x in feeds]) + (etf.result() or [])
        if pr and pr.result():
            rows.append(pr.result())
    return rows


if __name__ == "__main__":
    for r in externo():
        print(r)
