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
import unicodedata
import urllib.parse
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
# ---------- acciones (perpetuos de BABA, NVDA, GOOGL, AMD, AAPL, MSFT, AMZN, SPCX, META, TSLA, QQQ y MELI) ----------
# Nada de cripto. Para cada una: la empresa, su pais o region (la economia que la mueve), su sector si tiene uno claro
# y la bolsa. Un titular de un rival solo (sin la empresa) entra al sector como neutral. Igual que contexto.js.
BOLSA = r"\bmercados?\b|\bmarkets?\b|wall street|s&p ?500|\bnasdaq\b|dow jones|\bdow\b|hang seng|\bbolsas?\b|stock market|\bstocks?\b|\bacciones\b|\bnyse\b|\bvix\b|equities|mercado burs[aá]til|[ií]ndices burs|merval|ibovespa|bovespa"
CHINA = r"\bchina\b|chinese|\bchin[oa]s?\b|beijing|pek[ií]n|xi jinping|pboc|banco popular de china|\byuan\b|renminbi|hong kong|shanghai|shenzhen|taiw[aá]n"
CHINA_SOLO = r"xi jinping|pboc|banco popular de china|beijing|pek[ií]n|\byuan\b|renminbi"
EEUU = r"reserva federal|federal reserve|\bfed\b|powell|\bfomc\b|inflaci[oó]n|inflation|\bcpi\b|\bipc\b|payrolls?|n[oó]minas|jobs report|empleo|desempleo|unemployment|jobless|treasury|tesoro|bonos|yields?|rendimientos?|arancel|tariff|recesi[oó]n|recession|\bgdp\b|\bpib\b|consumer|consumo|shutdown|trump|casa blanca|white house|ee\.? ?uu|estados unidos|\bu\.s\.|\bus\b|american"
EEUU_SOLO = r"reserva federal|federal reserve|\bfed\b|powell|\bfomc\b|\bcpi\b|payrolls?|n[oó]minas no agr|jobs report|treasury yields|bonos del tesoro"
LATAM = r"argentin|milei|caputo|\bbcra\b|brasil|brazil|lula|haddad|\bselic\b|banco central do brasil|copom|m[eé]xico|banxico|sheinbaum|latinoam|latin america|am[eé]rica latina|colombia|chile|uruguay|\bperu\b|per[uú]\b|riesgo pa[ií]s"
LATAM_SOLO = r"milei|caputo|\bbcra\b|\bselic\b|banco central do brasil|copom|banxico|riesgo pa[ií]s"
ECON = r"econom|arancel|tariff|inflaci|inflation|tasas?\b|\brates?\b|comercio|\btrade\b|bolsa|\bstocks?\b|mercados?|markets?|recesi|recession|empleo|\bjobs?\b|\bpib\b|\bgdp\b|deuda|\bdebt|d[eé]ficit|impuesto|\btax|est[ií]mulo|stimulus|banco central|central bank|\bpeso\b|\breal\b|d[oó]lar|dollar|chips?\b|semiconduct|exporta|importa|\bexport|\bimport|blacklist|lista negra|sanci|regula|gobierno|government|presidente|president|ministr|acuerdo|\bdeal\b|yields?|rendimiento|bonos|consumo|consumer|ventas|sales|industria|manufactur|crecimiento|growth"
CHIPS_IA = r"semiconduct|\bchips?\b|chipmakers?|\bgpus?\b|inteligencia artificial|\bai\b|\bia\b|data ?cent|centros? de datos|\btsmc\b|\bhbm\b|export controls|controles (?:a las )?exportaci|\bsox\b"
TEC_IA = r"inteligencia artificial|\bai\b|\bia\b|big tech|gigantes tecnol|antimonopol|antitrust|publicidad digital|digital ad|buscador|search engine|\bcloud\b|la nube|openai|chatgpt|tech stocks|tecnol[oó]gicas"
AUTOS_EV = r"autos? el[eé]ctric|veh[ií]culos? el[eé]ctric|electric vehicles?|\bevs?\b|bater[ií]as?|batter(?:y|ies)|automotriz|automotive|carmakers?|automakers?|robotaxis?|conducci[oó]n aut[oó]noma|self-driving|autonomous|\bfsd\b"
ESPACIO = r"espacial|\bespacio\b|\bspace\b|sat[eé]lites?|satellites?|cohetes?|rockets?|\bnasa\b|\borbit|[oó]rbita|lanzamiento|launch|defensa|defense|pent[aá]gono|pentagon|\bfaa\b"
MEGA_TEC = TEC_IA + r"|\bapple\b|nvidia|microsoft|amazon|alphabet|google|meta platforms|tesla|broadcom|magn[ií]ficos|magnificent seven|\bmag 7\b"
NUNCA = r"\b\B"          # sin rivales
_GN = lambda q: GN + q + "+when:1d"
_GN_EN = lambda q: GN_EN + q + "+when:1d"
BOLSA_FEEDS = [_GN("%22Wall+Street%22+OR+%22S%26P+500%22+OR+Nasdaq"), _GN_EN("%22stock+market%22+OR+%22Wall+Street%22+OR+Nasdaq")]
EEUU_FEEDS = [_GN("%22Reserva+Federal%22+OR+%22inflaci%C3%B3n+en+EE.UU.%22+OR+aranceles+OR+%22bonos+del+Tesoro%22"),
              _GN_EN("%22Federal+Reserve%22+OR+inflation+OR+tariffs+OR+%22jobs+report%22+OR+%22Treasury+yields%22")]
CHIPS_FEEDS = [_GN_EN("semiconductor+OR+%22chip+stocks%22+OR+%22AI+chips%22+OR+%22export+controls%22")]
ACCIONES = {
    "BABA": {"empresa": "Alibaba", "rx": r"alibaba|\bbaba\b|jack ma|alipay|ant group|taobao|tmall|aliexpress|\bqwen\b|aliyun|eddie wu|joe tsai",
             "region": "China", "region_rx": CHINA, "region_solo": CHINA_SOLO, "sector": None, "sector_rx": None,
             "rivales": r"\bjd\.com|jingdong|pinduoduo|\bpdd\b|\btemu\b|tencent|meituan|baidu",
             "feeds": [_GN("China+(econom%C3%ADa+OR+Pek%C3%ADn+OR+aranceles+OR+yuan+OR+%22Xi+Jinping%22+OR+est%C3%ADmulos)"),
                       _GN_EN("China+(economy+OR+stimulus+OR+PBOC+OR+Beijing+OR+tariffs+OR+%22Xi+Jinping%22+OR+%22tech+stocks%22)"),
                       _GN("%22Wall+Street%22+OR+%22S%26P+500%22+OR+Nasdaq+OR+%22Hang+Seng%22"),
                       _GN_EN("%22stock+market%22+OR+%22Wall+Street%22+OR+Nasdaq+OR+%22Hang+Seng%22"),
                       _GN("Alibaba"), _GN_EN("Alibaba+OR+%22BABA+stock%22")]},
    "NVDA": {"empresa": "Nvidia", "rx": r"nvidia|\bnvda\b|jensen huang|blackwell|geforce|\bcuda\b",
             "region": "Economía de EE.UU.", "region_rx": EEUU, "region_solo": EEUU_SOLO, "sector": "Chips e IA", "sector_rx": CHIPS_IA,
             "rivales": r"\bamd\b|advanced micro|intel\b|broadcom|qualcomm|huawei|cerebras|\barm\b",
             "feeds": [_GN("Nvidia"), _GN_EN("Nvidia+OR+%22NVDA+stock%22")] + CHIPS_FEEDS + EEUU_FEEDS + BOLSA_FEEDS},
    "GOOGL": {"empresa": "Alphabet", "rx": r"alphabet|google|youtube|waymo|gemini|deepmind|sundar pichai|\bgoogl?\b|android",
              "region": "Economía de EE.UU.", "region_rx": EEUU, "region_solo": EEUU_SOLO, "sector": "IA y tecnología", "sector_rx": TEC_IA,
              "rivales": r"microsoft|openai|chatgpt|\bmeta\b|amazon|apple|perplexity|anthropic|\bbing\b",
              "feeds": [_GN("Google+OR+Alphabet"), _GN_EN("Alphabet+OR+Google+(stock+OR+shares+OR+antitrust+OR+earnings+OR+AI)")] + EEUU_FEEDS + BOLSA_FEEDS},
    "AMD": {"empresa": "AMD", "rx": r"\bamd\b|advanced micro devices|lisa su|ryzen|\bepyc\b|radeon|instinct mi|xilinx",
            "region": "Economía de EE.UU.", "region_rx": EEUU, "region_solo": EEUU_SOLO, "sector": "Chips e IA", "sector_rx": CHIPS_IA,
            "rivales": r"nvidia|intel\b|qualcomm|broadcom|\barm\b|huawei",
            "feeds": [_GN("AMD+(acciones+OR+chips+OR+%22Lisa+Su%22)"), _GN_EN("AMD+(stock+OR+shares+OR+chips+OR+%22Lisa+Su%22)")] + CHIPS_FEEDS + EEUU_FEEDS + BOLSA_FEEDS},
    "AAPL": {"empresa": "Apple", "rx": r"\bapple\b|iphone|\bipad|macbook|\bmac\b|tim cook|app store|apple intelligence|vision pro|\baapl\b|airpods|\bios\b",
             "region": "Economía de EE.UU.", "region_rx": EEUU, "region_solo": EEUU_SOLO, "sector": "IA y tecnología", "sector_rx": TEC_IA,
             "rivales": r"samsung|huawei|xiaomi|google|alphabet|microsoft|\bmeta\b|openai|android",
             "feeds": [_GN("Apple+(iPhone+OR+acciones+OR+%22Tim+Cook%22)"), _GN_EN("Apple+(stock+OR+shares+OR+iPhone+OR+earnings+OR+%22Tim+Cook%22)")] + EEUU_FEEDS + BOLSA_FEEDS},
    "MSFT": {"empresa": "Microsoft", "rx": r"microsoft|\bmsft\b|satya nadella|nadella|\bazure\b|copilot|windows|xbox|linkedin|\bbing\b",
             "region": "Economía de EE.UU.", "region_rx": EEUU, "region_solo": EEUU_SOLO, "sector": "IA y tecnología", "sector_rx": TEC_IA,
             "rivales": r"google|alphabet|amazon|\baws\b|apple|oracle|salesforce|\bmeta\b|anthropic",
             "feeds": [_GN("Microsoft"), _GN_EN("Microsoft+(stock+OR+shares+OR+Azure+OR+earnings+OR+OpenAI)")] + EEUU_FEEDS + BOLSA_FEEDS},
    "AMZN": {"empresa": "Amazon", "rx": r"amazon|\bamzn\b|\baws\b|andy jassy|jassy|jeff bezos|prime video|\balexa\b|kuiper|whole foods",
             "region": "Economía de EE.UU.", "region_rx": EEUU, "region_solo": EEUU_SOLO, "sector": "IA y tecnología", "sector_rx": TEC_IA,
             "rivales": r"walmart|shopify|\btemu\b|shein|alibaba|microsoft|azure|google cloud|mercado ?libre|starlink",
             "feeds": [_GN("Amazon+(acciones+OR+AWS+OR+Jassy)"), _GN_EN("Amazon+(stock+OR+shares+OR+AWS+OR+earnings+OR+Jassy)")] + EEUU_FEEDS + BOLSA_FEEDS},
    "SPCX": {"empresa": "SpaceX", "rx": r"spacex|\bspcx\b|starlink|starship|falcon 9|falcon heavy|\bdragon\b|gwynne shotwell|shotwell|elon musk|\bmusk\b|\bxai\b",
             "region": "Economía de EE.UU.", "region_rx": EEUU, "region_solo": EEUU_SOLO, "sector": "Espacio y defensa", "sector_rx": ESPACIO,
             "rivales": r"blue origin|rocket lab|kuiper|united launch|\bula\b|boeing|arianespace|oneweb|eutelsat",
             "feeds": [_GN("SpaceX+OR+Starlink"), _GN_EN("SpaceX+OR+Starlink+OR+Starship+OR+%22SPCX+stock%22"), _GN_EN("%22space+industry%22+OR+satellite+OR+NASA+launch+OR+Pentagon+contract")] + EEUU_FEEDS + BOLSA_FEEDS},
    "META": {"empresa": "Meta", "rx": r"meta platforms|facebook|instagram|whatsapp|zuckerberg|\bthreads\b|\bllama\b|reality labs|\bmeta[' ]s\b|acciones de meta|\bmeta (?:ai|stock|shares|acciones|earnings|lanza|anuncia|presenta|compra|despide|invierte|recorta|planea|gana|pierde|sube|cae|supera|launch|announc|unveil|buy|cut|plan|beat|miss|report|rais|lay|hir|spend|invest|sign|win|los|surg|jump|fall|drop|slid|rall|tops|tumbl|soar|sink|plung|hit)",
             "region": "Economía de EE.UU.", "region_rx": EEUU, "region_solo": EEUU_SOLO, "sector": "IA y tecnología", "sector_rx": TEC_IA,
             "rivales": r"tiktok|bytedance|snap\b|snapchat|google|alphabet|youtube|\bx\.com\b|openai|apple",
             "feeds": [_GN("%22Meta+Platforms%22+OR+Zuckerberg+OR+Instagram+OR+WhatsApp"), _GN_EN("%22Meta+Platforms%22+OR+%22Meta+stock%22+OR+Zuckerberg")] + EEUU_FEEDS + BOLSA_FEEDS},
    "TSLA": {"empresa": "Tesla", "rx": r"tesla|\btsla\b|elon musk|\bmusk\b|cybertruck|robotaxi|optimus|model [3ysx]\b|gigafactory|autopilot|\bfsd\b",
             "region": "Economía de EE.UU.", "region_rx": EEUU, "region_solo": EEUU_SOLO, "sector": "Autos eléctricos", "sector_rx": AUTOS_EV,
             "rivales": r"\bbyd\b|rivian|lucid|waymo|\bnio\b|xpeng|\bford\b|general motors|\bgm\b|volkswagen|toyota|xiaomi",
             "feeds": [_GN("Tesla+OR+%22Elon+Musk%22"), _GN_EN("Tesla+(stock+OR+shares+OR+deliveries+OR+robotaxi+OR+earnings)"), _GN_EN("%22electric+vehicles%22+OR+%22EV+sales%22+OR+robotaxi")] + EEUU_FEEDS + BOLSA_FEEDS},
    "QQQ": {"empresa": "Nasdaq 100", "rx": r"nasdaq|\bqqq\b|\bndx\b",
            "region": "Economía de EE.UU.", "region_rx": EEUU, "region_solo": EEUU_SOLO, "sector": "Grandes tecnológicas", "sector_rx": MEGA_TEC,
            "rivales": NUNCA,
            "feeds": [_GN("Nasdaq+OR+%22Wall+Street%22+OR+%22acciones+tecnol%C3%B3gicas%22"), _GN_EN("Nasdaq+OR+QQQ+OR+%22tech+stocks%22+OR+%22Magnificent+Seven%22")] + EEUU_FEEDS + BOLSA_FEEDS},
    "MELI": {"empresa": "Mercado Libre", "rx": r"mercado ?libre|\bmeli\b|mercado pago|galperin|szarfsztejn",
             "region": "Latinoamérica", "region_rx": LATAM, "region_solo": LATAM_SOLO, "sector": None, "sector_rx": None,
             "rivales": r"amazon|shopee|\btemu\b|shein|magalu|nubank|ual[aá]",
             "feeds": [_GN("%22Mercado+Libre%22+OR+%22Mercado+Pago%22"), _GN_EN("MercadoLibre+OR+%22Mercado+Libre%22"),
                       _GN("Argentina+(econom%C3%ADa+OR+BCRA+OR+Milei+OR+d%C3%B3lar+OR+inflaci%C3%B3n)"),
                       _GN("Brasil+(econom%C3%ADa+OR+Selic+OR+Lula+OR+inflaci%C3%B3n)"), _GN("M%C3%A9xico+(econom%C3%ADa+OR+Banxico+OR+aranceles)")] + BOLSA_FEEDS},
}
for _k, _c in ACCIONES.items():
    _c["feeds"] = [("accion:" + _k, u) for u in _c["feeds"]]
FEEDS_BABA = ACCIONES["BABA"]["feeds"]
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
IMPACTO = {"Hackeo de exchange": 3, "Fed y tasas": 3, "Guerras grandes": 3, "Gobierno de EE.UU.": 3, "Grandes gobiernos": 2, "ETF": 2, "Hackeo o quiebra": 2, "Mercado bursátil": 2, "Cripto": 1}
for _c in ACCIONES.values():
    IMPACTO[_c["empresa"]] = 3
    IMPACTO[_c["region"]] = 3
    if _c["sector"]:
        IMPACTO[_c["sector"]] = 2

# ---------- si un titular es bueno o malo para el activo (BTC o una accion) ----------
# Lectura del titular por reglas, no un modelo. En orden:
# 1. Lo que viene despues de "pese a / despite / aunque / pero" no cuenta: manda lo primero.
# 2. Si el titular dice que el activo (o la bolsa, para una accion) sube o baja, eso manda.
# 3. Si no: frases fuertes (pesan 2: tasas, estimulos, aranceles nuevos, resultados, recomendaciones, multas, ETF,
#    hackeos...) y despues las palabras de direccion de cada parte del titular. Si esa parte habla de algo que es malo
#    que suba (inflacion, tasas, rendimientos, dolar, desempleo, riesgo pais, aranceles, petroleo), la direccion se da
#    vuelta: "sube la inflacion" es malo, "bajan las tasas" es bueno.
# 4. Una accion: un titular que habla de un rival (el rival va primero, o la empresa ni aparece) es neutral.
# Medido con pruebas/titulares.json (pruebas/sesgo.py). Igual que contexto.js.
SUBE = r"\bsube|\bsuben|subi[oó]|subieron|\bsubir|al alza|en alza|avanza|trepa|se dispara|dispar[oó]|r[eé]cord|m[aá]ximos? hist|m[aá]ximo de|rall(?:y|ies|ied)|\brises?\b|\brose\b|\brising\b|surg(?:e|es|ed|ing)\b|soar|jump|climb|\bgains?\b|gained|rebound|rebota|repunt|recupera|\bhigher\b|advanc|se fortalece|fortalec|strengthen|\bcrece|grows?\b|growth|\bacelera|\baccelerat|expand|alcanza|hits? (?:a )?(?:record|high)|all-time high"
BAJA = r"\bcae\b|\bcaen\b|cay[oó]|cayeron|ca[ií]da|a la baja|en baja|\bbaja\b|\bbajan\b|baj[oó]|retroced|pierde|perdi[oó]|desplom|derrumb|se hunde|hund|plung|tumbl|\bfalls?\b|\bfell\b|\bdrops?\b|dropped|slid|slip|\bsinks?\b|\bsank\b|declin|\blower\b|sell-?off|venta masiva|slump|crash|retreat|se desacelera|desaceler|se modera|modera|cools?\b|eases?\b|\bslows?\b|slowdown|se debilita|debilit|weak|golpea|hits? (?:a )?low|m[ií]nimo"
COMPARA_SUBE = r"m[aá]s alt[oa]s? de lo (?:esperado|previsto)|m[aá]s de lo (?:esperado|previsto)|higher than expected|above (?:expectations|forecasts|estimates)|por encima de lo (?:esperado|previsto)|faster than expected|hotter than expected|m[aá]s r[aá]pido de lo"
COMPARA_BAJA = r"m[aá]s baj[oa]s? de lo (?:esperado|previsto)|menos de lo (?:esperado|previsto)|lower than expected|below (?:expectations|forecasts|estimates)|por debajo de lo (?:esperado|previsto)|slower than expected|softer than expected|cooler than expected|m[aá]s lent[oa] de lo"
MALO_SI_SUBE = r"inflaci|inflation|\bipc\b|\bcpi\b|\bpce\b|precios al consumidor|consumer prices|rendimiento|yields?\b|\btasas?\b|\brates?\b|tipos de inter|interest rate|\bselic\b|desemple|unemploy|jobless|d[oó]lar|dollar|\bdxy\b|\bvix\b|volatilid|riesgo pa[ií]s|arancel|tariff|petr[oó]leo|\boil\b|crudo|deuda|\bdebt\b|costos|costs|despidos|layoffs"
CONTRASTE = r"\b(?:pese a|a pesar de|despite|aunque|although|even as|but|pero|sin embargo|however|mientras que|while)\b"
PARTES = r"\b(?:tras|luego de|despu[eé]s de|after|por|on|as|amid|en medio de|ante|following|impulsad[oa]s? por|driven by|due to|debido a|and|y|e|with|con)\b|[,;:]"
SUJETO_BTC = r"bitcoin|\bbtc\b|cripto|crypto|\bether|ethereum|altcoins?|stablecoin"
SUJETO_BOLSA = r"\bacciones\b|\bshares?\b|\bstocks?\b|wall street|s&p|nasdaq|\bdow\b|hang seng|merval|ibovespa|bovespa|[ií]ndices?|\bbolsas?\b|equities|tecnol[oó]gicas|semiconductores|chipmakers"
SECTOR_AMPLIO = r"chip stocks|semiconductor stocks|semiconductores|chipmakers|\bsector\b|tech stocks|tecnol[oó]gicas|big tech"
# frases fuertes (pesan 2): buenas y malas para todos
FUERTE_BUENO = [r"(?:cuts?|recorta|recort[oó]|reduce|baja|bajan)(?: the| la| el| su| sus| las| its)?(?: key| benchmark| de referencia)?(?: interest| selic)? (?:rates?|tasas?|tipos|selic)|recort(?:a|an|e|es|ar|[oó])(?: de)?(?: las| la| sus| los)? (?:tasas?|tipos)|rate cuts?|cuts? (?:interest )?rates|baja(?:n|r)? (?:de )?(?:las |la )?(?:tasas?|tipos)|rebaja de (?:tasas|tipos)|dovish|paloma",
                r"est[ií]mulos?|stimulus|rescate|bailout|recorta (?:el )?encaje|reserve requirement|\brrr\b",
                r"alto el fuego|ceasefire|tregua|truce|acuerdo de paz|peace deal|acuerdo comercial|trade deal|trade truce|tregua comercial|suspende (?:los )?aranceles|tariff relief|elimina (?:los )?aranceles|lifts? tariffs|bajan? los aranceles|reduce (?:los )?aranceles",
                r"soft landing|aterrizaje suave"]
FUERTE_MALO = [r"(?:hikes?|raises?|eleva|sube|suben)(?: the| la| el| su| its)?(?: key| benchmark| de referencia)?(?: interest| selic)? (?:rates?|tasas?|tipos|selic)|sub(?:e|en|ir|i[oó]|a)(?: de)? (?:las |la )?(?:tasas?|tipos)|alza de (?:tasas|tipos)|rate hikes?|hikes? (?:interest )?rates|raises? (?:interest )?rates|eleva(?:n)? (?:las |la )?(?:tasas?|tipos)|hawkish|halc[oó]n|fewer rate cuts|menos recortes",
               r"nuevos aranceles|new tariffs|impone aranceles|imposes? tariffs|tariff hike|aranceles (?:de|del) \d|duplica los aranceles|amenaza con aranceles|threatens? tariffs",
               r"temores? de (?:una )?recesi[oó]n|recession fears|cae en recesi[oó]n|enters? recession|crisis|default|impago|quiebra|bankrupt",
               r"declara(?:ci[oó]n de)? (?:la )?guerra|invade|invasi[oó]n|sanciones|sanctions"]
FUERTE_BTC_BUENO = [r"\baprueb|\bapprov|tax cuts?|recorte de impuestos|baja de impuestos", r"\bbuys?\b|\bbought\b|\bcompra(?:n|r|ron)?\b|acumula|adquiere|\bacquires?\b", r"reserva estrat[eé]gica|strategic reserve|aprueba (?:el |los )?etf|etf approv|entradas r[eé]cord|record inflows|fuerte demanda|strong demand|record demand|inflows?|entradas"]
FUERTE_BTC_MALO = [HACK + r"|prohib|proh[ií]b|\bbans?\b|outflows?|salidas|presi[oó]n vendedora|sell(?:ing)? pressure|demanda (?:judicial|colectiva|contra|a\b)|demandan?\b|lawsuit|\bsues?\b|investiga|probe"]
FUERTE_ACCION_BUENO = [r"(?:wins?|gana) (?:dismissal|the case|lawsuit|appeal|ruling|el juicio|juicio|apelaci[oó]n)[^,;.]*|dismiss(?:es|ed)? [^,;.]*(?:case|lawsuit|suit|charges)|desestima[^,;.]*|rules? in (?:its )?favor[^,;.]*|fall[oó] a (?:su )?favor[^,;.]*", r"\bbeats?\b|beat (?:estimates|expectations)|supera (?:las |los )?(?:estimaciones|expectativas|previsiones|pron[oó]sticos)|super[oó] (?:las )?(?:estimaciones|expectativas)|tops? (?:estimates|expectations)",
                       r"rais(?:es|ed|ing) (?:its |full-year )?(?:guidance|forecast|outlook)|eleva (?:sus |su |la |el )?(?:previsi[oó]n|previsiones|perspectivas|pron[oó]stico|gu[ií]a)|mejora (?:sus |su )?(?:previsiones|perspectivas)",
                       r"(?:ingresos|ventas|ganancias|beneficios) r[eé]cord|record (?:revenue|sales|profit|earnings|quarter)",
                       r"upgrades?\b|upgraded|mejora (?:de )?(?:la )?recomendaci[oó]n|eleva (?:el )?precio objetivo|raises? (?:price )?target|price target (?:raised|hike)",
                       r"recompra|buyback|share repurchase|aumenta (?:el )?dividendo|dividend (?:hike|increase)",
                       r"wins? (?:a |an )?(?:\$?[\d,.]+ ?(?:billion|million|bn|mn)?[- ]?(?:dollar )?)?(?:[a-z.-]+ ){0,2}(?:contract|deal|order)|gana (?:un |el )?contrato|contrato (?:millonario|de \d)|multibillion|acuerdo (?:millonario|con)|alianza|partnership|se asocia|asociaci[oó]n con",
                       r"aprobaci[oó]n|approv|obtiene (?:la )?licencia|wins? (?:a )?license|licencia bancaria|autoriza"]
FUERTE_ACCION_MALO = [r"\bmiss(?:es|ed)?\b|no alcanza (?:las )?(?:estimaciones|expectativas)|decepciona|disappoint|por debajo de (?:las )?(?:estimaciones|expectativas)",
                      r"cuts? (?:its |full-year )?(?:guidance|forecast|outlook)|recorta (?:sus |su |la |el )?(?:previsi[oó]n|previsiones|perspectivas|pron[oó]stico)|weak (?:guidance|outlook|forecast)|previsiones? d[eé]bil",
                      r"downgrades?\b|downgraded|rebaja (?:de )?(?:la )?recomendaci[oó]n|recorta (?:el )?precio objetivo|cuts? (?:price )?target|price target cut",
                      r"antitrust|antimonopol|probe|investigaci[oó]n|investiga|\bfines?\b|\bfined\b|multa|lawsuit|\bsues?\b|demanda (?:judicial|colectiva|contra)|demandan?\b|loses? (?:the )?(?:antitrust )?case|pierde (?:el )?juicio|breakup|desmembra",
                      r"blacklist|lista negra|entity list|export (?:controls|curbs|restrictions|ban)|restricciones? (?:a las )?exportaci|controles (?:a las )?exportaci|\bbans?\b|prohib|proh[ií]b|veto",
                      r"temores? de (?:una )?burbuja|bubble fears|burbuja|recall|retira del mercado|renuncia (?:el |la )?(?:ceo|director|presidente)|(?:ceo|cfo) (?:resigns|steps down|quits)|fraude|fraud|short seller|delist"]
PALABRA_BUENA = r"optimis|alivio|relief|impuls|boost|fuerte demanda|strong demand|lanza|launch|unveil|presenta|expande|expands?\b|nuevas? ciudades|new cities|r[eé]cord"
PALABRA_MALA = r"miedo|\bfears?\b|temor|p[aá]nico|panic|guerra|\bwar\b|misil|missile|ataque|attack|\bstrikes?\b|bombard|escalad|amenaza|threat|incertidumbre|uncertainty|liquidac|liquidat|flee|huyen|preocupa|concern|shutdown|golpe|recesi|recession"


def _cuenta(rx, t):
    return len(re.findall(rx, t))


def _quita(rx, t):
    return re.sub(rx, " ", t)


def sesgo(titulo, tm=None, feed=""):
    """alcista, bajista o neutral para el activo del feed (BTC o una accion), segun el titular."""
    t = titulo.lower()
    c = ACCIONES.get(feed[7:]) if feed.startswith("accion:") else None
    if re.search(FED, t) and re.search(COMO_SE_ESPERABA, t):      # la Fed haciendo lo esperado no sorprende
        return "neutral"
    if tm == "Hackeo de exchange":
        return "bajista"
    if tm == "Guerras grandes":
        return "bajista" if re.search(VIOLENTO, t) or not re.search(PAZ, t) else "alcista"
    # 1. pese a / despite: manda lo de antes (o, si empieza asi, lo que sigue a la primera coma)
    m = re.search(CONTRASTE, t)
    if m:
        antes = t[:m.start()].strip(" ,.")
        t = antes if len(antes) > 8 else (t[t.index(",") + 1:] if "," in t[m.end():] and t.index(",") > m.start() else antes)
    # 4. una accion: un rival solo (sin la empresa ni la bolsa en general) es neutral
    if c and not re.search(SECTOR_AMPLIO, t):
        mr, me = re.search(c["rivales"], t), re.search(c["rx"], t)
        if mr and (not me or mr.start() < me.start()):     # el rival es de quien habla el titular
            return "neutral"
    sujeto = SUJETO_BTC if c is None else c["rx"] + "|" + SUJETO_BOLSA
    partes = [p for p in re.split(PARTES, t) if p and p.strip()]
    # 2. el activo sube o baja: manda
    mov = 0
    for p in partes:
        if re.search(sujeto, p) and not re.search(MALO_SI_SUBE, p):
            mov += _cuenta(SUBE, p) - _cuenta(BAJA, p)
    if mov:
        return "alcista" if mov > 0 else "bajista"
    # 3. frases fuertes y despues la direccion de cada parte
    score = 0
    buenas = FUERTE_BUENO + (FUERTE_BTC_BUENO if c is None else FUERTE_ACCION_BUENO)
    malas = FUERTE_MALO + (FUERTE_BTC_MALO if c is None else FUERTE_ACCION_MALO)
    for rx in buenas:
        if re.search(rx, t):
            score += 2; t = _quita(rx, t)
    for rx in malas:
        if re.search(rx, t):
            score -= 2; t = _quita(rx, t)
    for p in re.split(PARTES, t):
        if not p or not p.strip():
            continue
        d = 2 * (_cuenta(COMPARA_SUBE, p) - _cuenta(COMPARA_BAJA, p))
        p2 = _quita(COMPARA_BAJA, _quita(COMPARA_SUBE, p))
        d += _cuenta(SUBE, p2) - _cuenta(BAJA, p2)
        score += -d if re.search(MALO_SI_SUBE, p) else d
        score += _cuenta(PALABRA_BUENA, p2) - _cuenta(PALABRA_MALA, p2)
    return "alcista" if score > 0 else "bajista" if score < 0 else "neutral"


def _get(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def tema_accion(t, c):
    """Tema de un titular para una accion (ACCIONES[...]): la empresa, su region, su sector o la bolsa. Sin cripto."""
    emp = re.search(c["rx"], t)
    if re.search(CRIPTO, t) and not emp:
        return None
    if emp:
        return c["empresa"]
    if c["sector"] and re.search(c["rivales"], t):        # un rival solo: entra al sector (como neutral)
        return c["sector"]
    if re.search(c["region_rx"], t) and (re.search(c["region_solo"], t) or re.search(ECON, t) or re.search(BOLSA, t)):
        return c["region"]
    if c["sector"] and re.search(c["sector_rx"], t):
        return c["sector"]
    if re.search(BOLSA, t):
        return "Mercado bursátil"
    return None


def tema(titulo, feed):
    """De que habla un titular (guerra grande, gobierno de EE.UU. o grande, ETF, hackeo, cripto). None: se descarta."""
    t = titulo.lower()
    if feed.startswith("accion:"):
        return tema_accion(t, ACCIONES[feed[7:]])
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
                        "sesgo": sesgo(title, tm, feed), "impacto": IMPACTO[tm]})
    return out


# ---------- misma noticia en varios medios: se muestra una sola vez ----------
VACIAS = set("""el la los las lo un una unos unas de del al y o e u en por para con sin que se su sus es son fue ser
tras sobre como mas pero ya le les hay entre hasta desde ante segun este esta estos estas ese esa eso the of to and in
for on with as after is are was were be been says said over from by at its it will amid into new than more about up
out could would has have had this that what why how a an or not no but can may might just now today vs bitcoin btc
cripto crypto criptomoneda criptomonedas dolar dolares dollar dollars usd precio price""".split())
EVENTO = {"Hackeo de exchange": EXCHANGE}           # mismo exchange hackeado en 12 h: es el mismo hecho


def claves(titulo):
    """Palabras que importan de un titular, sin tildes ni palabras vacias, recortadas a 5 letras (raiz)."""
    t = "".join(c for c in unicodedata.normalize("NFD", titulo.lower()) if unicodedata.category(c) != "Mn")
    t = re.sub(r"(?<=\d)[.,](?=\d)", "", t)
    return {w if w.isdigit() else w[:5] for w in re.findall(r"[a-z0-9]+", t) if w not in VACIAS and (len(w) > 2 or w.isdigit())}


def misma_noticia(a, b):
    """True si dos titulares cuentan el mismo hecho (en 12 horas)."""
    if abs(a["t"] - b["t"]) > 12 * 3_600_000:
        return False
    if a.get("tema") == b.get("tema") and a.get("tema") in EVENTO:
        ea, eb = re.findall(EVENTO[a["tema"]], a.get("original", a["titulo"]).lower()), re.findall(EVENTO[b["tema"]], b.get("original", b["titulo"]).lower())
        if set(ea) & set(eb):
            return True
    ka, kb = claves(a["titulo"]), claves(b["titulo"])
    comun = len(ka & kb)
    if not ka or not kb:
        return False
    if comun >= 3 and comun / min(len(ka), len(kb)) >= 0.5:
        return True
    return a.get("tema") == b.get("tema") and comun >= 2 and comun / min(len(ka), len(kb)) >= 0.6


def juntar(listas, maximo=30):
    """Une titulares de varias fuentes: la misma noticia en distintos medios aparece una sola vez (la primera que
    salio, con la cantidad de medios), los mas nuevos primero."""
    out = []
    for r in sorted((x for xs in listas for x in xs), key=lambda x: (x["t"], x["titulo"])):
        igual = next((o for o in out if misma_noticia(o, r)), None)
        if igual is None:
            out.append(dict(r, medios=1))
        else:
            igual["medios"] += 1
    return sorted(out, key=lambda x: -x["t"])[:maximo]


# ---------- traduccion de los titulares en ingles (Google Translate, gratis, sin clave) ----------
INGLES = set("the of to and in for on with as after is are says over from by at its will amid into than about could would has have this what why how approves approved hacked hack falls fell rises rose surges surged drops dropped plunges jumps hits record inflows outflows breaks slips soars tumbles rally rallies crash crashes sees amid week weeks year high low".split())
ESPANOL = set("el la los las de del y en por para con que se un una sus es son tras sobre como pero".split())
_TRAD = {}


def _palabras(titulo):
    return re.findall(r"[a-záéíóúñ']+", titulo.lower())


def en_ingles(titulo):
    w = _palabras(titulo)
    en, es = sum(x in INGLES for x in w), sum(x in ESPANOL for x in w)
    return en >= 1 and en > es


def en_espanol(titulo):
    w = _palabras(titulo)
    en, es = sum(x in INGLES for x in w), sum(x in ESPANOL for x in w)
    return (es >= 1 and es >= en) or bool(re.search(r"[áéíóúñ¿¡]", titulo.lower()))


# Google bloquea seguido el traductor gratis "gtx" desde servidores compartidos (error 429): primero el cliente
# "dict-chrome-ex" (un titular por consulta, en lotes), en dos servidores de Google, y despues MyMemory de a uno.
TRADUCTORES = ("https://translate.googleapis.com/translate_a/t?client=dict-chrome-ex&sl=en&tl=es",
               "https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=en&tl=es")


def _traducir_google(base, lista):
    i = 0
    while i < len(lista):
        lote, largo = [], 0
        while i < len(lista) and len(lote) < 20 and largo + len(urllib.parse.quote(lista[i])) < 6000:
            largo += len(urllib.parse.quote(lista[i])) + 3
            lote.append(lista[i])
            i += 1
        u = base + "&" + "&".join("q=" + urllib.parse.quote(q) for q in lote)
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=10) as resp:
            j = json.loads(resp.read().decode("utf-8"))
        if not isinstance(j, list) or len(j) != len(lote):
            continue
        for o, tr in zip(lote, j):
            tr = tr[0] if isinstance(tr, list) else tr
            if isinstance(tr, str) and tr.strip():
                _TRAD[o] = html.unescape(tr.strip())


def _traducir_mymemory(lista):
    for o in lista[:15]:
        u = "https://api.mymemory.translated.net/get?langpair=en|es&q=" + urllib.parse.quote(o[:450])
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=8) as resp:
            j = json.loads(resp.read().decode("utf-8"))
        tr = (j.get("responseData") or {}).get("translatedText")
        if j.get("quotaFinished") or not tr or "MYMEMORY WARNING" in tr.upper():
            break
        _TRAD[o] = html.unescape(tr.strip())


def traducir(rows, feed_ingles=False):
    """Pasa al español los titulares en ingles (guarda el original). feed_ingles: el feed es en ingles, asi que se
    traduce todo lo que no este claramente en español. Lo que no se pudo traducir no se muestra (las noticias van
    siempre en español), salvo el hackeo de un exchange: se avisa igual, con el nombre del exchange. Igual en JS."""
    hay = (lambda t: not en_espanol(t)) if feed_ingles else en_ingles
    pend = list(dict.fromkeys(r["titulo"] for r in rows if hay(r["titulo"]) and r["titulo"] not in _TRAD))
    for base in TRADUCTORES:
        faltan = [t for t in pend if t not in _TRAD]
        if not faltan:
            break
        try:
            _traducir_google(base, faltan)
        except Exception as e:
            print(f"(traductor {base[8:30]} no disponible: {type(e).__name__})")
    try:
        _traducir_mymemory([t for t in pend if t not in _TRAD])
    except Exception as e:
        print(f"(traductor MyMemory no disponible: {type(e).__name__})")
    out = []
    for r in rows:
        if r["titulo"] in _TRAD:
            r["original"], r["titulo"] = r["titulo"], _TRAD[r["titulo"]]
            out.append(r)
        elif not hay(r["titulo"]):
            out.append(r)
        elif r.get("tema") == "Hackeo de exchange":
            m = re.search(EXCHANGE, r["titulo"].lower())
            ex = m.group(0).capitalize() if m else "un exchange"
            r["original"], r["titulo"] = r["titulo"], f"Posible hackeo en {ex} (titular de {r.get('fuente') or 'un medio'} en inglés, sin traducir)"
            out.append(r)
    return out


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


# ---------- Fear & Greed Index (alternative.me, gratis) ----------
# Termometro del animo del mercado (0 = miedo extremo, 100 = codicia extrema). Medido 2018-2026 con BTC: no anticipa
# la direccion de forma confiable (la codicia extrema fue alcista en 2018-21 y bajista en 2024-26; el miedo extremo,
# mixto), asi que se muestra como contexto, no como señal.
FNG_ES = {"Extreme Fear": "Miedo extremo", "Fear": "Miedo", "Neutral": "Neutral", "Greed": "Codicia", "Extreme Greed": "Codicia extrema"}


def miedo_codicia(data):
    """Fila de contexto con el Fear & Greed Index de hoy y el de ayer (respuesta de api.alternative.me/fng/?limit=2)."""
    d = data["data"]
    v, ayer = int(d[0]["value"]), (int(d[1]["value"]) if len(d) > 1 else None)
    clase = d[0].get("value_classification") or ""
    txt = FNG_ES.get(clase, clase) + (f" (ayer {ayer})" if ayer is not None and ayer != v else "")
    return {"tabla": "contexto", "clave": "miedo_codicia", "titulo": "Fear & Greed Index", "valor": f"{v} · {clase}",
            "senal": "neutral", "detalle": txt, "fng": v, "fng_ayer": ayer, "fng_clase": clase}


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

    if moneda in ACCIONES:               # una accion: sus noticias (empresa, region, sector y bolsa) y el calendario
        with ThreadPoolExecutor(max_workers=8) as pool:
            feeds = [(pool.submit(intento, f"noticias {url[:40]}", lambda f=feed, u=url: parse_rss(_get(u), f, now_ms)),
                      bool(re.search(r"hl=en", url))) for feed, url in ACCIONES[moneda]["feeds"]]
            cal = pool.submit(intento, "calendario economico", lambda: _calendario(now_ms))
            return juntar([traducir(x.result() or [], ing) for x, ing in feeds]) + (cal.result() or [])
    # todas las fuentes a la vez: si alguna tarda, no frena al resto
    with ThreadPoolExecutor(max_workers=6) as pool:
        feeds = [(pool.submit(intento, f"noticias {url[:40]}", lambda f=feed, u=url: parse_rss(_get(u), f, now_ms)),
                  bool(re.search(r"hl=en|coindesk", url))) for feed, url in FEEDS]
        etf = pool.submit(intento, "flujos de ETF", lambda: parse_farside(_get(FARSIDE)))
        pr = pool.submit(intento, "prima de Coinbase", _prima) if moneda == "BTC" else None
        cal = pool.submit(intento, "calendario economico", lambda: _calendario(now_ms))
        fng = pool.submit(intento, "miedo y codicia", lambda: miedo_codicia(json.loads(_get("https://api.alternative.me/fng/?limit=2"))))
        rows = juntar([traducir(x.result() or [], ing) for x, ing in feeds]) + (etf.result() or []) + (cal.result() or [])
        if pr and pr.result():
            rows.append(pr.result())
        if fng.result():
            rows.append(fng.result())
    return rows


if __name__ == "__main__":
    for r in externo():
        print(r)
