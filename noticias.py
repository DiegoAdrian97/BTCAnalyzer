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
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

UA = "Mozilla/5.0 (compatible; AnalistaBTC/1.0)"
GN = "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q="
GN_EN = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="
FEEDS = [
    ("mundo", GN + "guerra+OR+misiles+OR+ataque+OR+Trump+OR+%22Casa+Blanca%22+OR+%22Reserva+Federal%22+OR+aranceles+OR+China+OR+Rusia+OR+Ir%C3%A1n+when:1d"),
    ("mundo", GN_EN + "war+OR+missile+OR+Trump+OR+%22White+House%22+OR+%22Federal+Reserve%22+OR+tariffs+OR+China+when:1d"),
    ("cripto", GN + "bitcoin+when:1d"),
    ("cripto", GN_EN + "(hack+OR+hacked+OR+breach+OR+exploit+OR+drained+OR+stolen)+(Binance+OR+Coinbase+OR+Kraken+OR+OKX+OR+Bybit+OR+Bitget+OR+BingX+OR+KuCoin+OR+Tether+OR+exchange)+when:1d"),
    ("cripto", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
]
FARSIDE = "https://farside.co.uk/bitcoin-etf-flow-all-data/"
# Solo lo que de verdad mueve a BTC (pedido de Diego): guerras grandes (con una potencia o una zona caliente de por
# medio), el gobierno de EE.UU. (Casa Blanca, Congreso, Fed, Tesoro, SEC, aranceles) y los gobiernos grandes (China,
# Union Europea, Japon, Reino Unido, Rusia, India, G7, OPEP), los ETF de BTC, los hackeos o quiebras y las noticias
# cripto. El resto (deportes, empresas comunes, policiales...) se descarta.
ACTOR_GRANDE = r"ee\.? ?uu|estados unidos|\bu\.s\.|\busa\b|washington|pent[aá]gono|pentagon|rusia|russia|putin|kremlin|ucrania|ukrain|zelensk|israel|netanyahu|ir[aá]n\b|iranian|israeli|russian|ukrainian|chinese|american|\bus\b|teher[aá]n|tehran|china|beijing|pek[ií]n|taiw[aá]n|corea del norte|north korea|\botan\b|\bnato\b|india|pakist[aá]n|hezbol|hamas|gaza"
GUERRA = r"guerra|\bwar\b|misil|missile|ataque|attack|invasi|invade|bombard|airstrike|\bstrikes?\b|ofensiva|offensive|escalad|tropas|troops|nuclear|militar|military|\bdrones?\b|alto el fuego|ceasefire|tregua|truce"
CRIPTO = r"bitcoin|\bbtc\b|cripto|crypto|ethereum|stablecoin|binance|coinbase|tether|blockchain"
# gobiernos grandes: sus instituciones o lideres, o el pais junto a una palabra de politica o economia (asi
# "la China Suarez" no cuenta)
INSTITUCION = r"xi jinping|beijing|pek[ií]n|uni[oó]n europea|european union|comisi[oó]n europea|\bbce\b|\becb\b|lagarde|\bboj\b|banco de jap[oó]n|bank of england|banco de inglaterra|putin|kremlin|\bmodi\b|\bg7\b|\bg20\b|\bopep\b|\bopec\b|pboc|banco popular de china"
PAIS = r"\bchina\b|jap[oó]n|japan|reino unido|\buk\b|rusia|russia|\bindia\b|arabia saudita|saudi"
POLITICA = r"gobierno|government|presidente|president|primer ministro|prime minister|ministr|banco central|central bank|tasas|\brates?\b|sanci|arancel|tariff|\bley\b|\blaw\b|prohib|\bban\b|regula|econom|inflaci|cumbre|summit|acuerdo|\bdeal\b|tratado|treaty|elecci|election|parlament|exporta|importa|comercio|\btrade\b|yuan|\byen\b|bolsa|\bstocks?\b|mercados?|markets?|bitcoin|cripto|crypto|militar|military"
# en las noticias de guerra: si hay ataques es malo para BTC aunque se nombre un alto el fuego; paz sin ataques, bueno
VIOLENTO = r"ataque|attack|\bstrikes?\b|drones?|misil|missile|bombard|ofensiva|offensive|escalad|invade|invasi|muertos|killed|dead|explosi|disparo|fire[sd]? on|amenaza|threat"
PAZ = r"acuerdo de paz|peace (?:deal|agreement|talks)|fin de la guerra|end (?:of )?the war|alto el fuego|ceasefire|tregua|truce|negociaci|negotiat|retirada de tropas|withdraw"
# la Fed va primero siempre: si baja las tasas mas de lo previsto es bueno para BTC; si las sube, malo
# hackeos: un exchange grande (o Tether) hackeado es de lo peor que le puede pasar a BTC (miedo, ventas, retiros):
# tema propio, impacto maximo y siempre bajista, aunque el titular diga que los fondos estan a salvo
HACK = r"\bhack(?:s|ed|eo|eos|eado|eada|earon|ean)?\b|hackers? (?:steal|stole|drain|rob)|breach|exploit|drain(?:ed|s|ing)?\b|stolen|robad|robo de|roban|robaron|comprometid|compromised|security incident|incidente de seguridad|(?:halts?|suspends?|suspende|pausa|pauses?|freezes?) (?:all )?(?:withdrawals|retiros)|retiros (?:suspendidos|congelados)"
EXCHANGE = r"binance|coinbase|kraken|\bokx\b|bybit|bitget|bingx|kucoin|bitfinex|gemini|crypto\.com|\bhtx\b|huobi|upbit|bitstamp|gate\.io|\bmexc\b|tether|\busdt\b|robinhood"
COMO_SE_ESPERABA = r"as expected|como se esperaba|como se preve[ií]a|en l[ií]nea con lo (?:esperado|previsto)|in line with expectations"
FED = r"reserva federal|federal reserve|\bfed\b|powell|\bfomc\b"
TEMAS = [
    ("Gobierno de EE.UU.", r"trump|casa blanca|white house|congreso de (?:ee|estados)|congress|senado de (?:ee|estados)|\bsenate\b|reserva federal|federal reserve|\bfed\b|powell|tesoro de (?:ee|estados)|treasury|bessent|\bsec\b|\bcftc\b|arancel|tariff|shutdown|gobierno de (?:ee\.? ?uu|estados unidos)|biden|vance|orden ejecutiva|executive order|\bcpi\b|payroll|n[oó]minas no agr"),
    ("ETF", r"\betfs?\b|blackrock|\bibit\b|fidelity|grayscale|fondos cotizados"),
    ("Hackeo o quiebra", HACK + r"|quiebra|bankrupt|insolven|congela|freez"),
]
# si el titular es bueno o malo para BTC: frases fuertes (pesan 2) y palabras (pesan 1). Las frases van primero
# porque cambian el sentido ("baja de tasas" es bueno aunque diga "baja"). Es una lectura del titular, no un modelo.
SESGO = [
    (-2, r"fewer rate cuts|menos recortes|no (?:recorta|baja)|sin recorte|holds? rates|pausa|pause|halc[oó]n|hawkish|m[aá]s alt[ao]s? de lo (?:esperado|previsto)|higher than expected|sube(?:n)? (?:las |la )?tasas m[aá]s|recorte menor|smaller cut|sub(?:e|en|ir|a)(?: de)? (?:las |la )?tasas|rate hikes?|hike rates|raises? (?:interest )?rates|eleva(?:n)? (?:las |la )?tasas|declara(?:ci[oó]n de)? (?:la )?guerra|invade|invasi[oó]n|prohibe|proh[ií]be|bans? (?:bitcoin|crypto)|" + HACK),
    (2, r"recorte mayor|bigger(?:-than-expected)? cut|m[aá]s baj[ao]s? de lo (?:esperado|previsto)|lower than expected|paloma|dovish|recorte de tasas|recorta(?:n)? (?:las |la )?tasas|rate cuts?|cuts? rates|baja(?:n|r)? (?:de )?(?:las |la )?tasas|baja(?:n)? la inflaci|inflaci[oó]n (?:baja|cae|se desacelera|se modera)|inflation (?:cools|eases|slows)|cooler|cut rates|alto el fuego|ceasefire|tregua|acuerdo de paz|peace deal|reserva estrat[eé]gica|strategic reserve|aprueba (?:el |los )?etf|etf approv"),
    (1, r"\bsube|\bsuben|subida|se dispar|r[eé]cord|m[aá]ximo hist|rall|surge|soar|jump|rebot|rebound|recupera|entradas|inflows?|aprueb|approv|adopt|compra|\bbuys?\b|acumula|dovish|acuerdo|\bdeal\b|alivio|optimis"),
    (-1, r"\bcae\b|\bcaen\b|ca[ií]da|desplom|derrumb|hund|pierde|retroced|plunge|\bdrops?\b|\bfalls?\b|crash|slump|tumble|sell-?off|venta masiva|liquidac|liquidat|quiebra|bankrupt|demanda|lawsuit|investiga|salidas|outflows?|guerra|\bwar\b|misil|missile|ataque|attack|\bstrikes?\b|bombard|escalad|sanci|arancel|tariff|hawkish|recesi|recession|shutdown|miedo|\bfear\b|p[aá]nico|panic|temor|slides?|slips?"),
]
IMPACTO = {"Hackeo de exchange": 3, "Fed y tasas": 3, "Guerras grandes": 3, "Gobierno de EE.UU.": 3, "Grandes gobiernos": 2, "ETF": 2, "Hackeo o quiebra": 2, "Cripto": 1}


def sesgo(titulo, tm=None):
    """alcista, bajista o neutral para BTC, segun las palabras del titular."""
    t, score = titulo.lower(), 0
    # la Fed haciendo lo que el mercado ya esperaba no sorprende: neutral
    if tm == "Fed y tasas" and re.search(COMO_SE_ESPERABA, t):
        return "neutral"
    if tm == "Hackeo de exchange":
        return "bajista"
    if tm == "Guerras grandes":
        return "bajista" if re.search(VIOLENTO, t) or not re.search(PAZ, t) else "alcista"
    for peso, rx in SESGO:
        n = len(re.findall(rx, t))
        score += peso * n
        if abs(peso) == 2 and n:
            t = re.sub(rx, " ", t)          # la frase ya conto: sus palabras no vuelven a contar
    return "alcista" if score > 0 else "bajista" if score < 0 else "neutral"


def _get(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def tema(titulo, feed):
    """De que habla un titular (guerra grande, gobierno de EE.UU. o grande, ETF, hackeo, cripto). None: se descarta."""
    t = titulo.lower()
    if re.search(HACK, t) and re.search(EXCHANGE, t):
        return "Hackeo de exchange"
    if re.search(FED, t):
        return "Fed y tasas"
    if re.search(GUERRA, t) and re.search(ACTOR_GRANDE, t):
        return "Guerras grandes"
    for name, rx in TEMAS:
        if re.search(rx, t):
            return name
        if name == "Gobierno de EE.UU." and (re.search(INSTITUCION, t) or (re.search(PAIS, t) and re.search(POLITICA, t))):
            return "Grandes gobiernos"
    return "Cripto" if re.search(CRIPTO, t) else None


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
            out.append({"tabla": "noticia", "t": t, "titulo": title[:220], "fuente": fuente[:60], "url": link, "tema": tm,
                        "sesgo": sesgo(title, tm), "impacto": IMPACTO[tm]})
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


# ---------- calendario economico de EE.UU. (importancia alta) ----------
# Medido 2021-2026 con BTC: la hora en la que sale uno de estos datos se movio 1,6 a 1,8 veces lo normal y fue un
# movimiento fuerte (mas del doble de lo normal) 23% a 29% de las veces, contra 10% a 12% en las demas horas.
# No dice para donde: para la direccion no sirvio. Fuente: calendario de TradingView (Investing.com no deja leerlo
# de forma automatica: respondio solo algunos meses).
NOMBRES = [
    ("Non Farm Payrolls", "Empleo: nóminas no agrícolas"),
    ("Unemployment Rate", "Tasa de desempleo"),
    ("Core Inflation Rate YoY", "Inflación núcleo (IPC) anual"),
    ("Core Inflation Rate MoM", "Inflación núcleo (IPC) mensual"),
    ("Inflation Rate YoY", "Inflación (IPC) anual"),
    ("Inflation Rate MoM", "Inflación (IPC) mensual"),
    ("Core PCE Price Index", "Inflación PCE núcleo"),
    ("PCE Price Index", "Inflación PCE"),
    ("PPI", "Precios mayoristas (PPI)"),
    ("Fed Interest Rate Decision", "Decisión de tasas de la Fed"),
    ("Fed Press Conference", "Conferencia de prensa de la Fed"),
    ("FOMC Minutes", "Minutas de la Fed"),
    ("Powell", "Habla Powell (Fed)"),
    ("Retail Sales", "Ventas minoristas"),
    ("GDP", "PIB"),
    ("ISM Manufacturing", "ISM manufacturero"),
    ("ISM Services", "ISM de servicios"),
    ("JOLTs", "Vacantes laborales (JOLTS)"),
    ("Michigan", "Confianza del consumidor (Michigan)"),
    ("Durable Goods", "Pedidos de bienes durables"),
    ("Personal Income", "Ingresos personales"),
    ("Personal Spending", "Gasto personal"),
    ("Initial Jobless Claims", "Pedidos de subsidio por desempleo"),
    ("Balance of Trade", "Balanza comercial"),
    ("Building Permits", "Permisos de construcción"),
    ("Housing Starts", "Inicio de viviendas"),
    ("Existing Home Sales", "Ventas de viviendas usadas"),
    ("New Home Sales", "Ventas de viviendas nuevas"),
    ("ADP", "Empleo privado (ADP)"),
]


def nombre_es(titulo):
    for en, es in NOMBRES:
        if en.lower() in (titulo or "").lower():
            return es
    return titulo


def parse_calendario(txt):
    """Datos de importancia alta de EE.UU.: hora (ms UTC), nombre en español, previsto, anterior y actual."""
    out = []
    for e in json.loads(txt).get("result", []):
        if e.get("importance") != 1 or not e.get("date"):
            continue
        t = int(datetime.fromisoformat(e["date"].replace("Z", "+00:00")).timestamp() * 1000)
        out.append({"tabla": "evento", "t": t, "titulo": nombre_es(e.get("title")), "original": (e.get("title") or "")[:80],
                    "previsto": e.get("forecast"), "anterior": e.get("previous"), "actual": e.get("actual")})
    out.sort(key=lambda r: r["t"])
    return out


def _calendario(now_ms):
    a = datetime.fromtimestamp(now_ms / 1000 - 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    b = datetime.fromtimestamp(now_ms / 1000 + 8 * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    req = urllib.request.Request("https://economic-calendar.tradingview.com/events?from=" + a + "&to=" + b + "&countries=US",
                                 headers={"User-Agent": UA, "Origin": "https://www.tradingview.com", "Referer": "https://www.tradingview.com/"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return parse_calendario(r.read().decode("utf-8", "replace"))


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
        cal = pool.submit(intento, "calendario economico", lambda: _calendario(now_ms))
        rows = juntar([x.result() or [] for x in feeds]) + (etf.result() or []) + (cal.result() or [])
        if pr and pr.result():
            rows.append(pr.result())
    return rows


if __name__ == "__main__":
    for r in externo():
        print(r)
