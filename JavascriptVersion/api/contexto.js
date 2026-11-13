/*
 * Funcion del servidor de Vercel: titulares, flujos de los ETF de BTC y prima de Coinbase, para explicar los
 * movimientos fuertes. La pagina no puede leer esas fuentes directo (el navegador lo bloquea), el servidor si.
 * Misma logica que noticias.py (version Python): mismas fuentes, mismas filas. Fuentes publicas, sin claves.
 * Vercel guarda la respuesta 10 minutos: todos los telefonos comparten el mismo pedido.
 */
const UA = 'Mozilla/5.0 (compatible; AnalistaBTC/1.0)';
const GN = 'https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=';
const GN_EN = 'https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=';
const FEEDS = [
  ['mundo', GN + 'guerra+OR+misiles+OR+ataque+OR+Trump+OR+%22Casa+Blanca%22+OR+%22Reserva+Federal%22+OR+aranceles+OR+China+OR+Rusia+OR+Ir%C3%A1n+when:1d'],
  ['mundo', GN_EN + 'war+OR+missile+OR+Trump+OR+%22White+House%22+OR+%22Federal+Reserve%22+OR+tariffs+OR+China+when:1d'],
  ['cripto', GN + 'bitcoin+when:1d'],
  ['cripto', GN_EN + '(hack+OR+hacked+OR+breach+OR+exploit+OR+drained+OR+stolen)+(Binance+OR+Coinbase+OR+Kraken+OR+OKX+OR+Bybit+OR+Bitget+OR+BingX+OR+KuCoin+OR+Tether+OR+exchange)+when:1d'],
  ['cripto', 'https://www.coindesk.com/arc/outboundfeeds/rss/'],
];
// ---- reglas copiadas de noticias.py (generar_reglas.py): no editar a mano ----
const BOLSA = "\\bmercados?\\b|\\bmarkets?\\b|wall street|s&p ?500|\\bnasdaq\\b|dow jones|\\bdow\\b|hang seng|\\bbolsas?\\b|stock market|\\bstocks?\\b|\\bacciones\\b|\\bnyse\\b|\\bvix\\b|equities|mercado burs[aá]til|[ií]ndices burs|merval|ibovespa|bovespa";
const CHINA = "\\bchina\\b|chinese|\\bchin[oa]s?\\b|beijing|pek[ií]n|xi jinping|pboc|banco popular de china|\\byuan\\b|renminbi|hong kong|shanghai|shenzhen|taiw[aá]n";
const CHINA_SOLO = "xi jinping|pboc|banco popular de china|beijing|pek[ií]n|\\byuan\\b|renminbi";
const EEUU = "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|inflaci[oó]n|inflation|\\bcpi\\b|\\bipc\\b|payrolls?|n[oó]minas|jobs report|empleo|desempleo|unemployment|jobless|treasury|tesoro|bonos|yields?|rendimientos?|arancel|tariff|recesi[oó]n|recession|\\bgdp\\b|\\bpib\\b|consumer|consumo|shutdown|trump|casa blanca|white house|ee\\.? ?uu|estados unidos|\\bu\\.s\\.|\\bus\\b|american";
const EEUU_SOLO = "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|\\bcpi\\b|payrolls?|n[oó]minas no agr|jobs report|treasury yields|bonos del tesoro";
const LATAM = "argentin|milei|caputo|\\bbcra\\b|brasil|brazil|lula|haddad|\\bselic\\b|banco central do brasil|copom|m[eé]xico|banxico|sheinbaum|latinoam|latin america|am[eé]rica latina|colombia|chile|uruguay|\\bperu\\b|per[uú]\\b|riesgo pa[ií]s";
const LATAM_SOLO = "milei|caputo|\\bbcra\\b|\\bselic\\b|banco central do brasil|copom|banxico|riesgo pa[ií]s";
const ECON = "econom|arancel|tariff|inflaci|inflation|tasas?\\b|\\brates?\\b|comercio|\\btrade\\b|bolsa|\\bstocks?\\b|mercados?|markets?|recesi|recession|empleo|\\bjobs?\\b|\\bpib\\b|\\bgdp\\b|deuda|\\bdebt|d[eé]ficit|impuesto|\\btax|est[ií]mulo|stimulus|banco central|central bank|\\bpeso\\b|\\breal\\b|d[oó]lar|dollar|chips?\\b|semiconduct|exporta|importa|\\bexport|\\bimport|blacklist|lista negra|sanci|regula|gobierno|government|presidente|president|ministr|acuerdo|\\bdeal\\b|yields?|rendimiento|bonos|consumo|consumer|ventas|sales|industria|manufactur|crecimiento|growth";
const CHIPS_IA = "semiconduct|\\bchips?\\b|chipmakers?|\\bgpus?\\b|inteligencia artificial|\\bai\\b|\\bia\\b|data ?cent|centros? de datos|\\btsmc\\b|\\bhbm\\b|export controls|controles (?:a las )?exportaci|\\bsox\\b";
const TEC_IA = "inteligencia artificial|\\bai\\b|\\bia\\b|big tech|gigantes tecnol|antimonopol|antitrust|publicidad digital|digital ad|buscador|search engine|\\bcloud\\b|la nube|openai|chatgpt|tech stocks|tecnol[oó]gicas";
const AUTOS_EV = "autos? el[eé]ctric|veh[ií]culos? el[eé]ctric|electric vehicles?|\\bevs?\\b|bater[ií]as?|batter(?:y|ies)|automotriz|automotive|carmakers?|automakers?|robotaxis?|conducci[oó]n aut[oó]noma|self-driving|autonomous|\\bfsd\\b";
const ESPACIO = "espacial|\\bespacio\\b|\\bspace\\b|sat[eé]lites?|satellites?|cohetes?|rockets?|\\bnasa\\b|\\borbit|[oó]rbita|lanzamiento|launch|defensa|defense|pent[aá]gono|pentagon|\\bfaa\\b";
const MEGA_TEC = "inteligencia artificial|\\bai\\b|\\bia\\b|big tech|gigantes tecnol|antimonopol|antitrust|publicidad digital|digital ad|buscador|search engine|\\bcloud\\b|la nube|openai|chatgpt|tech stocks|tecnol[oó]gicas|\\bapple\\b|nvidia|microsoft|amazon|alphabet|google|meta platforms|tesla|broadcom|magn[ií]ficos|magnificent seven|\\bmag 7\\b";
const NUNCA = "\\b\\B";
const SUBE = "\\bsube|\\bsuben|subi[oó]|subieron|\\bsubir|al alza|en alza|avanza|trepa|se dispara|dispar[oó]|r[eé]cord|m[aá]ximos? hist|m[aá]ximo de|rall(?:y|ies|ied)|\\brises?\\b|\\brose\\b|\\brising\\b|surg(?:e|es|ed|ing)\\b|soar|jump|climb|\\bgains?\\b|gained|rebound|rebota|repunt|recupera|\\bhigher\\b|advanc|se fortalece|fortalec|strengthen|\\bcrece|grows?\\b|growth|\\bacelera|\\baccelerat|expand|alcanza|hits? (?:a )?(?:record|high)|all-time high";
const BAJA = "\\bcae\\b|\\bcaen\\b|cay[oó]|cayeron|ca[ií]da|a la baja|en baja|\\bbaja\\b|\\bbajan\\b|baj[oó]|retroced|pierde|perdi[oó]|desplom|derrumb|se hunde|hund|plung|tumbl|\\bfalls?\\b|\\bfell\\b|\\bdrops?\\b|dropped|slid|slip|\\bsinks?\\b|\\bsank\\b|declin|\\blower\\b|sell-?off|venta masiva|slump|crash|retreat|se desacelera|desaceler|se modera|modera|cools?\\b|eases?\\b|\\bslows?\\b|slowdown|se debilita|debilit|weak|golpea|hits? (?:a )?low|m[ií]nimo";
const COMPARA_SUBE = "m[aá]s alt[oa]s? de lo (?:esperado|previsto)|m[aá]s de lo (?:esperado|previsto)|higher than expected|above (?:expectations|forecasts|estimates)|por encima de lo (?:esperado|previsto)|faster than expected|hotter than expected|m[aá]s r[aá]pido de lo";
const COMPARA_BAJA = "m[aá]s baj[oa]s? de lo (?:esperado|previsto)|menos de lo (?:esperado|previsto)|lower than expected|below (?:expectations|forecasts|estimates)|por debajo de lo (?:esperado|previsto)|slower than expected|softer than expected|cooler than expected|m[aá]s lent[oa] de lo";
const MALO_SI_SUBE = "inflaci|inflation|\\bipc\\b|\\bcpi\\b|\\bpce\\b|precios al consumidor|consumer prices|rendimiento|yields?\\b|\\btasas?\\b|\\brates?\\b|tipos de inter|interest rate|\\bselic\\b|desemple|unemploy|jobless|d[oó]lar|dollar|\\bdxy\\b|\\bvix\\b|volatilid|riesgo pa[ií]s|arancel|tariff|petr[oó]leo|\\boil\\b|crudo|deuda|\\bdebt\\b|costos|costs|despidos|layoffs";
const CONTRASTE = "\\b(?:pese a|a pesar de|despite|aunque|although|even as|but|pero|sin embargo|however|mientras que|while)\\b";
const PARTES = "\\b(?:tras|luego de|despu[eé]s de|after|por|on|as|amid|en medio de|ante|following|impulsad[oa]s? por|driven by|due to|debido a|and|y|e|with|con)\\b|[,;:]";
const SUJETO_BTC = "bitcoin|\\bbtc\\b|cripto|crypto|\\bether|ethereum|altcoins?|stablecoin";
const SUJETO_BOLSA = "\\bacciones\\b|\\bshares?\\b|\\bstocks?\\b|wall street|s&p|nasdaq|\\bdow\\b|hang seng|merval|ibovespa|bovespa|[ií]ndices?|\\bbolsas?\\b|equities|tecnol[oó]gicas|semiconductores|chipmakers";
const SECTOR_AMPLIO = "chip stocks|semiconductor stocks|semiconductores|chipmakers|\\bsector\\b|tech stocks|tecnol[oó]gicas|big tech";
const FUERTE_BUENO = ["(?:cuts?|recorta|recort[oó]|reduce|baja|bajan)(?: the| la| el| su| sus| las| its)?(?: key| benchmark| de referencia)?(?: interest| selic)? (?:rates?|tasas?|tipos|selic)|recort(?:a|an|e|es|ar|[oó])(?: de)?(?: las| la| sus| los)? (?:tasas?|tipos)|rate cuts?|cuts? (?:interest )?rates|baja(?:n|r)? (?:de )?(?:las |la )?(?:tasas?|tipos)|rebaja de (?:tasas|tipos)|dovish|paloma", "est[ií]mulos?|stimulus|rescate|bailout|recorta (?:el )?encaje|reserve requirement|\\brrr\\b", "alto el fuego|ceasefire|tregua|truce|acuerdo de paz|peace deal|acuerdo comercial|trade deal|trade truce|tregua comercial|suspende (?:los )?aranceles|tariff relief|elimina (?:los )?aranceles|lifts? tariffs|bajan? los aranceles|reduce (?:los )?aranceles", "soft landing|aterrizaje suave"];
const FUERTE_MALO = ["(?:hikes?|raises?|eleva|sube|suben)(?: the| la| el| su| its)?(?: key| benchmark| de referencia)?(?: interest| selic)? (?:rates?|tasas?|tipos|selic)|sub(?:e|en|ir|i[oó]|a)(?: de)? (?:las |la )?(?:tasas?|tipos)|alza de (?:tasas|tipos)|rate hikes?|hikes? (?:interest )?rates|raises? (?:interest )?rates|eleva(?:n)? (?:las |la )?(?:tasas?|tipos)|hawkish|halc[oó]n|fewer rate cuts|menos recortes", "nuevos aranceles|new tariffs|impone aranceles|imposes? tariffs|tariff hike|aranceles (?:de|del) \\d|duplica los aranceles|amenaza con aranceles|threatens? tariffs", "temores? de (?:una )?recesi[oó]n|recession fears|cae en recesi[oó]n|enters? recession|crisis|default|impago|quiebra|bankrupt", "declara(?:ci[oó]n de)? (?:la )?guerra|invade|invasi[oó]n|sanciones|sanctions"];
const FUERTE_BTC_BUENO = ["\\baprueb|\\bapprov|tax cuts?|recorte de impuestos|baja de impuestos", "\\bbuys?\\b|\\bbought\\b|\\bcompra(?:n|r|ron)?\\b|acumula|adquiere|\\bacquires?\\b", "reserva estrat[eé]gica|strategic reserve|aprueba (?:el |los )?etf|etf approv|entradas r[eé]cord|record inflows|fuerte demanda|strong demand|record demand|inflows?|entradas"];
const FUERTE_BTC_MALO = ["\\bhack(?:s|ed|eo|eos|eado|eada|earon|ean)?\\b|hackers? (?:steal|stole|drain|rob)|breach|exploit|drain(?:ed|s|ing)?\\b|stolen|robad|robo de|roban|robaron|comprometid|compromised|security incident|incidente de seguridad|(?:halts?|suspends?|suspende|pausa|pauses?|freezes?) (?:all )?(?:withdrawals|retiros)|retiros (?:suspendidos|congelados)|prohib|proh[ií]b|\\bbans?\\b|outflows?|salidas|presi[oó]n vendedora|sell(?:ing)? pressure|demanda (?:judicial|colectiva|contra|a\\b)|demandan?\\b|lawsuit|\\bsues?\\b|investiga|probe"];
const FUERTE_ACCION_BUENO = ["(?:wins?|gana) (?:dismissal|the case|lawsuit|appeal|ruling|el juicio|juicio|apelaci[oó]n)[^,;.]*|dismiss(?:es|ed)? [^,;.]*(?:case|lawsuit|suit|charges)|desestima[^,;.]*|rules? in (?:its )?favor[^,;.]*|fall[oó] a (?:su )?favor[^,;.]*", "\\bbeats?\\b|beat (?:estimates|expectations)|supera (?:las |los )?(?:estimaciones|expectativas|previsiones|pron[oó]sticos)|super[oó] (?:las )?(?:estimaciones|expectativas)|tops? (?:estimates|expectations)", "rais(?:es|ed|ing) (?:its |full-year )?(?:guidance|forecast|outlook)|eleva (?:sus |su |la |el )?(?:previsi[oó]n|previsiones|perspectivas|pron[oó]stico|gu[ií]a)|mejora (?:sus |su )?(?:previsiones|perspectivas)", "(?:ingresos|ventas|ganancias|beneficios) r[eé]cord|record (?:revenue|sales|profit|earnings|quarter)", "upgrades?\\b|upgraded|mejora (?:de )?(?:la )?recomendaci[oó]n|eleva (?:el )?precio objetivo|raises? (?:price )?target|price target (?:raised|hike)", "recompra|buyback|share repurchase|aumenta (?:el )?dividendo|dividend (?:hike|increase)", "wins? (?:a |an )?(?:\\$?[\\d,.]+ ?(?:billion|million|bn|mn)?[- ]?(?:dollar )?)?(?:[a-z.-]+ ){0,2}(?:contract|deal|order)|gana (?:un |el )?contrato|contrato (?:millonario|de \\d)|multibillion|acuerdo (?:millonario|con)|alianza|partnership|se asocia|asociaci[oó]n con", "aprobaci[oó]n|approv|obtiene (?:la )?licencia|wins? (?:a )?license|licencia bancaria|autoriza"];
const FUERTE_ACCION_MALO = ["\\bmiss(?:es|ed)?\\b|no alcanza (?:las )?(?:estimaciones|expectativas)|decepciona|disappoint|por debajo de (?:las )?(?:estimaciones|expectativas)", "cuts? (?:its |full-year )?(?:guidance|forecast|outlook)|recorta (?:sus |su |la |el )?(?:previsi[oó]n|previsiones|perspectivas|pron[oó]stico)|weak (?:guidance|outlook|forecast)|previsiones? d[eé]bil", "downgrades?\\b|downgraded|rebaja (?:de )?(?:la )?recomendaci[oó]n|recorta (?:el )?precio objetivo|cuts? (?:price )?target|price target cut", "antitrust|antimonopol|probe|investigaci[oó]n|investiga|\\bfines?\\b|\\bfined\\b|multa|lawsuit|\\bsues?\\b|demanda (?:judicial|colectiva|contra)|demandan?\\b|loses? (?:the )?(?:antitrust )?case|pierde (?:el )?juicio|breakup|desmembra", "blacklist|lista negra|entity list|export (?:controls|curbs|restrictions|ban)|restricciones? (?:a las )?exportaci|controles (?:a las )?exportaci|\\bbans?\\b|prohib|proh[ií]b|veto", "temores? de (?:una )?burbuja|bubble fears|burbuja|recall|retira del mercado|renuncia (?:el |la )?(?:ceo|director|presidente)|(?:ceo|cfo) (?:resigns|steps down|quits)|fraude|fraud|short seller|delist"];
const PALABRA_BUENA = "optimis|alivio|relief|impuls|boost|fuerte demanda|strong demand|lanza|launch|unveil|presenta|expande|expands?\\b|nuevas? ciudades|new cities|r[eé]cord";
const PALABRA_MALA = "miedo|\\bfears?\\b|temor|p[aá]nico|panic|guerra|\\bwar\\b|misil|missile|ataque|attack|\\bstrikes?\\b|bombard|escalad|amenaza|threat|incertidumbre|uncertainty|liquidac|liquidat|flee|huyen|preocupa|concern|shutdown|golpe|recesi|recession";
const ACCIONES = {"BABA": {"empresa": "Alibaba", "rx": "alibaba|\\bbaba\\b|jack ma|alipay|ant group|taobao|tmall|aliexpress|\\bqwen\\b|aliyun|eddie wu|joe tsai", "region": "China", "region_rx": "\\bchina\\b|chinese|\\bchin[oa]s?\\b|beijing|pek[ií]n|xi jinping|pboc|banco popular de china|\\byuan\\b|renminbi|hong kong|shanghai|shenzhen|taiw[aá]n", "region_solo": "xi jinping|pboc|banco popular de china|beijing|pek[ií]n|\\byuan\\b|renminbi", "sector": null, "sector_rx": null, "rivales": "\\bjd\\.com|jingdong|pinduoduo|\\bpdd\\b|\\btemu\\b|tencent|meituan|baidu", "feeds": [["accion:BABA", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=China+(econom%C3%ADa+OR+Pek%C3%ADn+OR+aranceles+OR+yuan+OR+%22Xi+Jinping%22+OR+est%C3%ADmulos)+when:1d"], ["accion:BABA", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=China+(economy+OR+stimulus+OR+PBOC+OR+Beijing+OR+tariffs+OR+%22Xi+Jinping%22+OR+%22tech+stocks%22)+when:1d"], ["accion:BABA", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Wall+Street%22+OR+%22S%26P+500%22+OR+Nasdaq+OR+%22Hang+Seng%22+when:1d"], ["accion:BABA", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22stock+market%22+OR+%22Wall+Street%22+OR+Nasdaq+OR+%22Hang+Seng%22+when:1d"], ["accion:BABA", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=Alibaba+when:1d"], ["accion:BABA", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=Alibaba+OR+%22BABA+stock%22+when:1d"]]}, "NVDA": {"empresa": "Nvidia", "rx": "nvidia|\\bnvda\\b|jensen huang|blackwell|geforce|\\bcuda\\b", "region": "Economía de EE.UU.", "region_rx": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|inflaci[oó]n|inflation|\\bcpi\\b|\\bipc\\b|payrolls?|n[oó]minas|jobs report|empleo|desempleo|unemployment|jobless|treasury|tesoro|bonos|yields?|rendimientos?|arancel|tariff|recesi[oó]n|recession|\\bgdp\\b|\\bpib\\b|consumer|consumo|shutdown|trump|casa blanca|white house|ee\\.? ?uu|estados unidos|\\bu\\.s\\.|\\bus\\b|american", "region_solo": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|\\bcpi\\b|payrolls?|n[oó]minas no agr|jobs report|treasury yields|bonos del tesoro", "sector": "Chips e IA", "sector_rx": "semiconduct|\\bchips?\\b|chipmakers?|\\bgpus?\\b|inteligencia artificial|\\bai\\b|\\bia\\b|data ?cent|centros? de datos|\\btsmc\\b|\\bhbm\\b|export controls|controles (?:a las )?exportaci|\\bsox\\b", "rivales": "\\bamd\\b|advanced micro|intel\\b|broadcom|qualcomm|huawei|cerebras|\\barm\\b", "feeds": [["accion:NVDA", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=Nvidia+when:1d"], ["accion:NVDA", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=Nvidia+OR+%22NVDA+stock%22+when:1d"], ["accion:NVDA", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=semiconductor+OR+%22chip+stocks%22+OR+%22AI+chips%22+OR+%22export+controls%22+when:1d"], ["accion:NVDA", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Reserva+Federal%22+OR+%22inflaci%C3%B3n+en+EE.UU.%22+OR+aranceles+OR+%22bonos+del+Tesoro%22+when:1d"], ["accion:NVDA", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22Federal+Reserve%22+OR+inflation+OR+tariffs+OR+%22jobs+report%22+OR+%22Treasury+yields%22+when:1d"], ["accion:NVDA", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Wall+Street%22+OR+%22S%26P+500%22+OR+Nasdaq+when:1d"], ["accion:NVDA", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22stock+market%22+OR+%22Wall+Street%22+OR+Nasdaq+when:1d"]]}, "GOOGL": {"empresa": "Alphabet", "rx": "alphabet|google|youtube|waymo|gemini|deepmind|sundar pichai|\\bgoogl?\\b|android", "region": "Economía de EE.UU.", "region_rx": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|inflaci[oó]n|inflation|\\bcpi\\b|\\bipc\\b|payrolls?|n[oó]minas|jobs report|empleo|desempleo|unemployment|jobless|treasury|tesoro|bonos|yields?|rendimientos?|arancel|tariff|recesi[oó]n|recession|\\bgdp\\b|\\bpib\\b|consumer|consumo|shutdown|trump|casa blanca|white house|ee\\.? ?uu|estados unidos|\\bu\\.s\\.|\\bus\\b|american", "region_solo": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|\\bcpi\\b|payrolls?|n[oó]minas no agr|jobs report|treasury yields|bonos del tesoro", "sector": "IA y tecnología", "sector_rx": "inteligencia artificial|\\bai\\b|\\bia\\b|big tech|gigantes tecnol|antimonopol|antitrust|publicidad digital|digital ad|buscador|search engine|\\bcloud\\b|la nube|openai|chatgpt|tech stocks|tecnol[oó]gicas", "rivales": "microsoft|openai|chatgpt|\\bmeta\\b|amazon|apple|perplexity|anthropic|\\bbing\\b", "feeds": [["accion:GOOGL", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=Google+OR+Alphabet+when:1d"], ["accion:GOOGL", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=Alphabet+OR+Google+(stock+OR+shares+OR+antitrust+OR+earnings+OR+AI)+when:1d"], ["accion:GOOGL", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Reserva+Federal%22+OR+%22inflaci%C3%B3n+en+EE.UU.%22+OR+aranceles+OR+%22bonos+del+Tesoro%22+when:1d"], ["accion:GOOGL", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22Federal+Reserve%22+OR+inflation+OR+tariffs+OR+%22jobs+report%22+OR+%22Treasury+yields%22+when:1d"], ["accion:GOOGL", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Wall+Street%22+OR+%22S%26P+500%22+OR+Nasdaq+when:1d"], ["accion:GOOGL", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22stock+market%22+OR+%22Wall+Street%22+OR+Nasdaq+when:1d"]]}, "AMD": {"empresa": "AMD", "rx": "\\bamd\\b|advanced micro devices|lisa su|ryzen|\\bepyc\\b|radeon|instinct mi|xilinx", "region": "Economía de EE.UU.", "region_rx": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|inflaci[oó]n|inflation|\\bcpi\\b|\\bipc\\b|payrolls?|n[oó]minas|jobs report|empleo|desempleo|unemployment|jobless|treasury|tesoro|bonos|yields?|rendimientos?|arancel|tariff|recesi[oó]n|recession|\\bgdp\\b|\\bpib\\b|consumer|consumo|shutdown|trump|casa blanca|white house|ee\\.? ?uu|estados unidos|\\bu\\.s\\.|\\bus\\b|american", "region_solo": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|\\bcpi\\b|payrolls?|n[oó]minas no agr|jobs report|treasury yields|bonos del tesoro", "sector": "Chips e IA", "sector_rx": "semiconduct|\\bchips?\\b|chipmakers?|\\bgpus?\\b|inteligencia artificial|\\bai\\b|\\bia\\b|data ?cent|centros? de datos|\\btsmc\\b|\\bhbm\\b|export controls|controles (?:a las )?exportaci|\\bsox\\b", "rivales": "nvidia|intel\\b|qualcomm|broadcom|\\barm\\b|huawei", "feeds": [["accion:AMD", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=AMD+(acciones+OR+chips+OR+%22Lisa+Su%22)+when:1d"], ["accion:AMD", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=AMD+(stock+OR+shares+OR+chips+OR+%22Lisa+Su%22)+when:1d"], ["accion:AMD", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=semiconductor+OR+%22chip+stocks%22+OR+%22AI+chips%22+OR+%22export+controls%22+when:1d"], ["accion:AMD", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Reserva+Federal%22+OR+%22inflaci%C3%B3n+en+EE.UU.%22+OR+aranceles+OR+%22bonos+del+Tesoro%22+when:1d"], ["accion:AMD", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22Federal+Reserve%22+OR+inflation+OR+tariffs+OR+%22jobs+report%22+OR+%22Treasury+yields%22+when:1d"], ["accion:AMD", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Wall+Street%22+OR+%22S%26P+500%22+OR+Nasdaq+when:1d"], ["accion:AMD", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22stock+market%22+OR+%22Wall+Street%22+OR+Nasdaq+when:1d"]]}, "AAPL": {"empresa": "Apple", "rx": "\\bapple\\b|iphone|\\bipad|macbook|\\bmac\\b|tim cook|app store|apple intelligence|vision pro|\\baapl\\b|airpods|\\bios\\b", "region": "Economía de EE.UU.", "region_rx": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|inflaci[oó]n|inflation|\\bcpi\\b|\\bipc\\b|payrolls?|n[oó]minas|jobs report|empleo|desempleo|unemployment|jobless|treasury|tesoro|bonos|yields?|rendimientos?|arancel|tariff|recesi[oó]n|recession|\\bgdp\\b|\\bpib\\b|consumer|consumo|shutdown|trump|casa blanca|white house|ee\\.? ?uu|estados unidos|\\bu\\.s\\.|\\bus\\b|american", "region_solo": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|\\bcpi\\b|payrolls?|n[oó]minas no agr|jobs report|treasury yields|bonos del tesoro", "sector": "IA y tecnología", "sector_rx": "inteligencia artificial|\\bai\\b|\\bia\\b|big tech|gigantes tecnol|antimonopol|antitrust|publicidad digital|digital ad|buscador|search engine|\\bcloud\\b|la nube|openai|chatgpt|tech stocks|tecnol[oó]gicas", "rivales": "samsung|huawei|xiaomi|google|alphabet|microsoft|\\bmeta\\b|openai|android", "feeds": [["accion:AAPL", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=Apple+(iPhone+OR+acciones+OR+%22Tim+Cook%22)+when:1d"], ["accion:AAPL", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=Apple+(stock+OR+shares+OR+iPhone+OR+earnings+OR+%22Tim+Cook%22)+when:1d"], ["accion:AAPL", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Reserva+Federal%22+OR+%22inflaci%C3%B3n+en+EE.UU.%22+OR+aranceles+OR+%22bonos+del+Tesoro%22+when:1d"], ["accion:AAPL", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22Federal+Reserve%22+OR+inflation+OR+tariffs+OR+%22jobs+report%22+OR+%22Treasury+yields%22+when:1d"], ["accion:AAPL", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Wall+Street%22+OR+%22S%26P+500%22+OR+Nasdaq+when:1d"], ["accion:AAPL", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22stock+market%22+OR+%22Wall+Street%22+OR+Nasdaq+when:1d"]]}, "MSFT": {"empresa": "Microsoft", "rx": "microsoft|\\bmsft\\b|satya nadella|nadella|\\bazure\\b|copilot|windows|xbox|linkedin|\\bbing\\b", "region": "Economía de EE.UU.", "region_rx": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|inflaci[oó]n|inflation|\\bcpi\\b|\\bipc\\b|payrolls?|n[oó]minas|jobs report|empleo|desempleo|unemployment|jobless|treasury|tesoro|bonos|yields?|rendimientos?|arancel|tariff|recesi[oó]n|recession|\\bgdp\\b|\\bpib\\b|consumer|consumo|shutdown|trump|casa blanca|white house|ee\\.? ?uu|estados unidos|\\bu\\.s\\.|\\bus\\b|american", "region_solo": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|\\bcpi\\b|payrolls?|n[oó]minas no agr|jobs report|treasury yields|bonos del tesoro", "sector": "IA y tecnología", "sector_rx": "inteligencia artificial|\\bai\\b|\\bia\\b|big tech|gigantes tecnol|antimonopol|antitrust|publicidad digital|digital ad|buscador|search engine|\\bcloud\\b|la nube|openai|chatgpt|tech stocks|tecnol[oó]gicas", "rivales": "google|alphabet|amazon|\\baws\\b|apple|oracle|salesforce|\\bmeta\\b|anthropic", "feeds": [["accion:MSFT", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=Microsoft+when:1d"], ["accion:MSFT", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=Microsoft+(stock+OR+shares+OR+Azure+OR+earnings+OR+OpenAI)+when:1d"], ["accion:MSFT", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Reserva+Federal%22+OR+%22inflaci%C3%B3n+en+EE.UU.%22+OR+aranceles+OR+%22bonos+del+Tesoro%22+when:1d"], ["accion:MSFT", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22Federal+Reserve%22+OR+inflation+OR+tariffs+OR+%22jobs+report%22+OR+%22Treasury+yields%22+when:1d"], ["accion:MSFT", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Wall+Street%22+OR+%22S%26P+500%22+OR+Nasdaq+when:1d"], ["accion:MSFT", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22stock+market%22+OR+%22Wall+Street%22+OR+Nasdaq+when:1d"]]}, "AMZN": {"empresa": "Amazon", "rx": "amazon|\\bamzn\\b|\\baws\\b|andy jassy|jassy|jeff bezos|prime video|\\balexa\\b|kuiper|whole foods", "region": "Economía de EE.UU.", "region_rx": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|inflaci[oó]n|inflation|\\bcpi\\b|\\bipc\\b|payrolls?|n[oó]minas|jobs report|empleo|desempleo|unemployment|jobless|treasury|tesoro|bonos|yields?|rendimientos?|arancel|tariff|recesi[oó]n|recession|\\bgdp\\b|\\bpib\\b|consumer|consumo|shutdown|trump|casa blanca|white house|ee\\.? ?uu|estados unidos|\\bu\\.s\\.|\\bus\\b|american", "region_solo": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|\\bcpi\\b|payrolls?|n[oó]minas no agr|jobs report|treasury yields|bonos del tesoro", "sector": "IA y tecnología", "sector_rx": "inteligencia artificial|\\bai\\b|\\bia\\b|big tech|gigantes tecnol|antimonopol|antitrust|publicidad digital|digital ad|buscador|search engine|\\bcloud\\b|la nube|openai|chatgpt|tech stocks|tecnol[oó]gicas", "rivales": "walmart|shopify|\\btemu\\b|shein|alibaba|microsoft|azure|google cloud|mercado ?libre|starlink", "feeds": [["accion:AMZN", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=Amazon+(acciones+OR+AWS+OR+Jassy)+when:1d"], ["accion:AMZN", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=Amazon+(stock+OR+shares+OR+AWS+OR+earnings+OR+Jassy)+when:1d"], ["accion:AMZN", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Reserva+Federal%22+OR+%22inflaci%C3%B3n+en+EE.UU.%22+OR+aranceles+OR+%22bonos+del+Tesoro%22+when:1d"], ["accion:AMZN", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22Federal+Reserve%22+OR+inflation+OR+tariffs+OR+%22jobs+report%22+OR+%22Treasury+yields%22+when:1d"], ["accion:AMZN", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Wall+Street%22+OR+%22S%26P+500%22+OR+Nasdaq+when:1d"], ["accion:AMZN", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22stock+market%22+OR+%22Wall+Street%22+OR+Nasdaq+when:1d"]]}, "SPCX": {"empresa": "SpaceX", "rx": "spacex|\\bspcx\\b|starlink|starship|falcon 9|falcon heavy|\\bdragon\\b|gwynne shotwell|shotwell|elon musk|\\bmusk\\b|\\bxai\\b", "region": "Economía de EE.UU.", "region_rx": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|inflaci[oó]n|inflation|\\bcpi\\b|\\bipc\\b|payrolls?|n[oó]minas|jobs report|empleo|desempleo|unemployment|jobless|treasury|tesoro|bonos|yields?|rendimientos?|arancel|tariff|recesi[oó]n|recession|\\bgdp\\b|\\bpib\\b|consumer|consumo|shutdown|trump|casa blanca|white house|ee\\.? ?uu|estados unidos|\\bu\\.s\\.|\\bus\\b|american", "region_solo": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|\\bcpi\\b|payrolls?|n[oó]minas no agr|jobs report|treasury yields|bonos del tesoro", "sector": "Espacio y defensa", "sector_rx": "espacial|\\bespacio\\b|\\bspace\\b|sat[eé]lites?|satellites?|cohetes?|rockets?|\\bnasa\\b|\\borbit|[oó]rbita|lanzamiento|launch|defensa|defense|pent[aá]gono|pentagon|\\bfaa\\b", "rivales": "blue origin|rocket lab|kuiper|united launch|\\bula\\b|boeing|arianespace|oneweb|eutelsat", "feeds": [["accion:SPCX", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=SpaceX+OR+Starlink+when:1d"], ["accion:SPCX", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=SpaceX+OR+Starlink+OR+Starship+OR+%22SPCX+stock%22+when:1d"], ["accion:SPCX", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22space+industry%22+OR+satellite+OR+NASA+launch+OR+Pentagon+contract+when:1d"], ["accion:SPCX", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Reserva+Federal%22+OR+%22inflaci%C3%B3n+en+EE.UU.%22+OR+aranceles+OR+%22bonos+del+Tesoro%22+when:1d"], ["accion:SPCX", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22Federal+Reserve%22+OR+inflation+OR+tariffs+OR+%22jobs+report%22+OR+%22Treasury+yields%22+when:1d"], ["accion:SPCX", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Wall+Street%22+OR+%22S%26P+500%22+OR+Nasdaq+when:1d"], ["accion:SPCX", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22stock+market%22+OR+%22Wall+Street%22+OR+Nasdaq+when:1d"]]}, "META": {"empresa": "Meta", "rx": "meta platforms|facebook|instagram|whatsapp|zuckerberg|\\bthreads\\b|\\bllama\\b|reality labs|\\bmeta[' ]s\\b|acciones de meta|\\bmeta (?:ai|stock|shares|acciones|earnings|lanza|anuncia|presenta|compra|despide|invierte|recorta|planea|gana|pierde|sube|cae|supera|launch|announc|unveil|buy|cut|plan|beat|miss|report|rais|lay|hir|spend|invest|sign|win|los|surg|jump|fall|drop|slid|rall|tops|tumbl|soar|sink|plung|hit)", "region": "Economía de EE.UU.", "region_rx": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|inflaci[oó]n|inflation|\\bcpi\\b|\\bipc\\b|payrolls?|n[oó]minas|jobs report|empleo|desempleo|unemployment|jobless|treasury|tesoro|bonos|yields?|rendimientos?|arancel|tariff|recesi[oó]n|recession|\\bgdp\\b|\\bpib\\b|consumer|consumo|shutdown|trump|casa blanca|white house|ee\\.? ?uu|estados unidos|\\bu\\.s\\.|\\bus\\b|american", "region_solo": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|\\bcpi\\b|payrolls?|n[oó]minas no agr|jobs report|treasury yields|bonos del tesoro", "sector": "IA y tecnología", "sector_rx": "inteligencia artificial|\\bai\\b|\\bia\\b|big tech|gigantes tecnol|antimonopol|antitrust|publicidad digital|digital ad|buscador|search engine|\\bcloud\\b|la nube|openai|chatgpt|tech stocks|tecnol[oó]gicas", "rivales": "tiktok|bytedance|snap\\b|snapchat|google|alphabet|youtube|\\bx\\.com\\b|openai|apple", "feeds": [["accion:META", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Meta+Platforms%22+OR+Zuckerberg+OR+Instagram+OR+WhatsApp+when:1d"], ["accion:META", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22Meta+Platforms%22+OR+%22Meta+stock%22+OR+Zuckerberg+when:1d"], ["accion:META", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Reserva+Federal%22+OR+%22inflaci%C3%B3n+en+EE.UU.%22+OR+aranceles+OR+%22bonos+del+Tesoro%22+when:1d"], ["accion:META", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22Federal+Reserve%22+OR+inflation+OR+tariffs+OR+%22jobs+report%22+OR+%22Treasury+yields%22+when:1d"], ["accion:META", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Wall+Street%22+OR+%22S%26P+500%22+OR+Nasdaq+when:1d"], ["accion:META", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22stock+market%22+OR+%22Wall+Street%22+OR+Nasdaq+when:1d"]]}, "TSLA": {"empresa": "Tesla", "rx": "tesla|\\btsla\\b|elon musk|\\bmusk\\b|cybertruck|robotaxi|optimus|model [3ysx]\\b|gigafactory|autopilot|\\bfsd\\b", "region": "Economía de EE.UU.", "region_rx": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|inflaci[oó]n|inflation|\\bcpi\\b|\\bipc\\b|payrolls?|n[oó]minas|jobs report|empleo|desempleo|unemployment|jobless|treasury|tesoro|bonos|yields?|rendimientos?|arancel|tariff|recesi[oó]n|recession|\\bgdp\\b|\\bpib\\b|consumer|consumo|shutdown|trump|casa blanca|white house|ee\\.? ?uu|estados unidos|\\bu\\.s\\.|\\bus\\b|american", "region_solo": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|\\bcpi\\b|payrolls?|n[oó]minas no agr|jobs report|treasury yields|bonos del tesoro", "sector": "Autos eléctricos", "sector_rx": "autos? el[eé]ctric|veh[ií]culos? el[eé]ctric|electric vehicles?|\\bevs?\\b|bater[ií]as?|batter(?:y|ies)|automotriz|automotive|carmakers?|automakers?|robotaxis?|conducci[oó]n aut[oó]noma|self-driving|autonomous|\\bfsd\\b", "rivales": "\\bbyd\\b|rivian|lucid|waymo|\\bnio\\b|xpeng|\\bford\\b|general motors|\\bgm\\b|volkswagen|toyota|xiaomi", "feeds": [["accion:TSLA", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=Tesla+OR+%22Elon+Musk%22+when:1d"], ["accion:TSLA", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=Tesla+(stock+OR+shares+OR+deliveries+OR+robotaxi+OR+earnings)+when:1d"], ["accion:TSLA", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22electric+vehicles%22+OR+%22EV+sales%22+OR+robotaxi+when:1d"], ["accion:TSLA", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Reserva+Federal%22+OR+%22inflaci%C3%B3n+en+EE.UU.%22+OR+aranceles+OR+%22bonos+del+Tesoro%22+when:1d"], ["accion:TSLA", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22Federal+Reserve%22+OR+inflation+OR+tariffs+OR+%22jobs+report%22+OR+%22Treasury+yields%22+when:1d"], ["accion:TSLA", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Wall+Street%22+OR+%22S%26P+500%22+OR+Nasdaq+when:1d"], ["accion:TSLA", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22stock+market%22+OR+%22Wall+Street%22+OR+Nasdaq+when:1d"]]}, "QQQ": {"empresa": "Nasdaq 100", "rx": "nasdaq|\\bqqq\\b|\\bndx\\b", "region": "Economía de EE.UU.", "region_rx": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|inflaci[oó]n|inflation|\\bcpi\\b|\\bipc\\b|payrolls?|n[oó]minas|jobs report|empleo|desempleo|unemployment|jobless|treasury|tesoro|bonos|yields?|rendimientos?|arancel|tariff|recesi[oó]n|recession|\\bgdp\\b|\\bpib\\b|consumer|consumo|shutdown|trump|casa blanca|white house|ee\\.? ?uu|estados unidos|\\bu\\.s\\.|\\bus\\b|american", "region_solo": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|\\bcpi\\b|payrolls?|n[oó]minas no agr|jobs report|treasury yields|bonos del tesoro", "sector": "Grandes tecnológicas", "sector_rx": "inteligencia artificial|\\bai\\b|\\bia\\b|big tech|gigantes tecnol|antimonopol|antitrust|publicidad digital|digital ad|buscador|search engine|\\bcloud\\b|la nube|openai|chatgpt|tech stocks|tecnol[oó]gicas|\\bapple\\b|nvidia|microsoft|amazon|alphabet|google|meta platforms|tesla|broadcom|magn[ií]ficos|magnificent seven|\\bmag 7\\b", "rivales": "\\b\\B", "feeds": [["accion:QQQ", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=Nasdaq+OR+%22Wall+Street%22+OR+%22acciones+tecnol%C3%B3gicas%22+when:1d"], ["accion:QQQ", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=Nasdaq+OR+QQQ+OR+%22tech+stocks%22+OR+%22Magnificent+Seven%22+when:1d"], ["accion:QQQ", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Reserva+Federal%22+OR+%22inflaci%C3%B3n+en+EE.UU.%22+OR+aranceles+OR+%22bonos+del+Tesoro%22+when:1d"], ["accion:QQQ", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22Federal+Reserve%22+OR+inflation+OR+tariffs+OR+%22jobs+report%22+OR+%22Treasury+yields%22+when:1d"], ["accion:QQQ", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Wall+Street%22+OR+%22S%26P+500%22+OR+Nasdaq+when:1d"], ["accion:QQQ", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22stock+market%22+OR+%22Wall+Street%22+OR+Nasdaq+when:1d"]]}, "SPY": {"empresa": "S&P 500", "rx": "s&p ?500|\\bspy\\b|\\bspx\\b|standard (?:&|and) poor", "region": "Economía de EE.UU.", "region_rx": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|inflaci[oó]n|inflation|\\bcpi\\b|\\bipc\\b|payrolls?|n[oó]minas|jobs report|empleo|desempleo|unemployment|jobless|treasury|tesoro|bonos|yields?|rendimientos?|arancel|tariff|recesi[oó]n|recession|\\bgdp\\b|\\bpib\\b|consumer|consumo|shutdown|trump|casa blanca|white house|ee\\.? ?uu|estados unidos|\\bu\\.s\\.|\\bus\\b|american", "region_solo": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|\\bcpi\\b|payrolls?|n[oó]minas no agr|jobs report|treasury yields|bonos del tesoro", "sector": "Grandes tecnológicas", "sector_rx": "inteligencia artificial|\\bai\\b|\\bia\\b|big tech|gigantes tecnol|antimonopol|antitrust|publicidad digital|digital ad|buscador|search engine|\\bcloud\\b|la nube|openai|chatgpt|tech stocks|tecnol[oó]gicas|\\bapple\\b|nvidia|microsoft|amazon|alphabet|google|meta platforms|tesla|broadcom|magn[ií]ficos|magnificent seven|\\bmag 7\\b", "rivales": "\\b\\B", "feeds": [["accion:SPY", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22S%26P+500%22+OR+%22Wall+Street%22+when:1d"], ["accion:SPY", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22S%26P+500%22+OR+SPY+OR+%22stock+market%22+OR+%22Wall+Street%22+when:1d"], ["accion:SPY", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Reserva+Federal%22+OR+%22inflaci%C3%B3n+en+EE.UU.%22+OR+aranceles+OR+%22bonos+del+Tesoro%22+when:1d"], ["accion:SPY", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22Federal+Reserve%22+OR+inflation+OR+tariffs+OR+%22jobs+report%22+OR+%22Treasury+yields%22+when:1d"], ["accion:SPY", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Wall+Street%22+OR+%22S%26P+500%22+OR+Nasdaq+when:1d"], ["accion:SPY", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22stock+market%22+OR+%22Wall+Street%22+OR+Nasdaq+when:1d"]]}, "MSTR": {"empresa": "Strategy", "rx": "microstrategy|\\bmstr\\b|michael saylor|\\bsaylor\\b|strategy inc|\\bstrategy\\b.{0,40}(?:bitcoin|btc|shares|stock|acciones|preferred|stretch|strk|strf|strd|strc)|(?:bitcoin|btc).{0,40}\\bstrategy\\b|phong le", "region": "Economía de EE.UU.", "region_rx": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|inflaci[oó]n|inflation|\\bcpi\\b|\\bipc\\b|payrolls?|n[oó]minas|jobs report|empleo|desempleo|unemployment|jobless|treasury|tesoro|bonos|yields?|rendimientos?|arancel|tariff|recesi[oó]n|recession|\\bgdp\\b|\\bpib\\b|consumer|consumo|shutdown|trump|casa blanca|white house|ee\\.? ?uu|estados unidos|\\bu\\.s\\.|\\bus\\b|american", "region_solo": "reserva federal|federal reserve|\\bfed\\b|powell|\\bfomc\\b|\\bcpi\\b|payrolls?|n[oó]minas no agr|jobs report|treasury yields|bonos del tesoro", "sector": "Bitcoin", "sector_rx": "bitcoin|\\bbtc\\b|criptomonedas?|cryptocurrenc|\\bcrypto\\b|spot bitcoin etf|etf de bitcoin|coinbase|metaplanet|tesorer[ií]a", "rivales": "metaplanet|marathon|\\bmara\\b|riot|coinbase|bitmine|twenty one|semler|trump media", "feeds": [["accion:MSTR", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=MicroStrategy+OR+Strategy+OR+%22Michael+Saylor%22+when:1d"], ["accion:MSTR", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=MicroStrategy+OR+MSTR+OR+%22Michael+Saylor%22+OR+%22Strategy+Inc%22+when:1d"], ["accion:MSTR", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=bitcoin+(price+OR+ETF+OR+treasury)+when:1d"], ["accion:MSTR", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Reserva+Federal%22+OR+%22inflaci%C3%B3n+en+EE.UU.%22+OR+aranceles+OR+%22bonos+del+Tesoro%22+when:1d"], ["accion:MSTR", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22Federal+Reserve%22+OR+inflation+OR+tariffs+OR+%22jobs+report%22+OR+%22Treasury+yields%22+when:1d"], ["accion:MSTR", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Wall+Street%22+OR+%22S%26P+500%22+OR+Nasdaq+when:1d"], ["accion:MSTR", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22stock+market%22+OR+%22Wall+Street%22+OR+Nasdaq+when:1d"]]}, "MELI": {"empresa": "Mercado Libre", "rx": "mercado ?libre|\\bmeli\\b|mercado pago|galperin|szarfsztejn", "region": "Latinoamérica", "region_rx": "argentin|milei|caputo|\\bbcra\\b|brasil|brazil|lula|haddad|\\bselic\\b|banco central do brasil|copom|m[eé]xico|banxico|sheinbaum|latinoam|latin america|am[eé]rica latina|colombia|chile|uruguay|\\bperu\\b|per[uú]\\b|riesgo pa[ií]s", "region_solo": "milei|caputo|\\bbcra\\b|\\bselic\\b|banco central do brasil|copom|banxico|riesgo pa[ií]s", "sector": null, "sector_rx": null, "rivales": "amazon|shopee|\\btemu\\b|shein|magalu|nubank|ual[aá]", "feeds": [["accion:MELI", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Mercado+Libre%22+OR+%22Mercado+Pago%22+when:1d"], ["accion:MELI", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=MercadoLibre+OR+%22Mercado+Libre%22+when:1d"], ["accion:MELI", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=Argentina+(econom%C3%ADa+OR+BCRA+OR+Milei+OR+d%C3%B3lar+OR+inflaci%C3%B3n)+when:1d"], ["accion:MELI", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=Brasil+(econom%C3%ADa+OR+Selic+OR+Lula+OR+inflaci%C3%B3n)+when:1d"], ["accion:MELI", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=M%C3%A9xico+(econom%C3%ADa+OR+Banxico+OR+aranceles)+when:1d"], ["accion:MELI", "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=%22Wall+Street%22+OR+%22S%26P+500%22+OR+Nasdaq+when:1d"], ["accion:MELI", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=%22stock+market%22+OR+%22Wall+Street%22+OR+Nasdaq+when:1d"]]}};
const IMPACTO = {"Hackeo de exchange": 3, "Fed y tasas": 3, "Guerras grandes": 3, "Gobierno de EE.UU.": 3, "Grandes gobiernos": 2, "ETF": 2, "Hackeo o quiebra": 2, "Mercado bursátil": 2, "Cripto": 1, "Alibaba": 3, "China": 3, "Nvidia": 3, "Economía de EE.UU.": 3, "Chips e IA": 2, "Alphabet": 3, "IA y tecnología": 2, "AMD": 3, "Apple": 3, "Microsoft": 3, "Amazon": 3, "SpaceX": 3, "Espacio y defensa": 2, "Meta": 3, "Tesla": 3, "Autos eléctricos": 2, "Nasdaq 100": 3, "Grandes tecnológicas": 2, "S&P 500": 3, "Strategy": 3, "Bitcoin": 2, "Mercado Libre": 3, "Latinoamérica": 3};
// ---- fin de las reglas copiadas ----
const R = (src) => new RegExp(src);
const RG = (src) => new RegExp(src, 'g');
/** Tema de un titular para una accion (ACCIONES[...]): la empresa, su region, su sector o la bolsa. Sin cripto. */
function temaAccion(t, c) {
  const emp = R(c.rx).test(t);
  if (CRIPTO.test(t) && !emp) return null;
  if (emp) return c.empresa;
  if (c.sector && R(c.rivales).test(t)) return c.sector;            // un rival solo: entra al sector (como neutral)
  if (R(c.region_rx).test(t) && (R(c.region_solo).test(t) || R(ECON).test(t) || R(BOLSA).test(t))) return c.region;
  if (c.sector && R(c.sector_rx).test(t)) return c.sector;
  if (R(BOLSA).test(t)) return 'Mercado bursátil';
  return null;
}
const FARSIDE = 'https://farside.co.uk/bitcoin-etf-flow-all-data/';
// Solo lo que de verdad mueve a BTC: guerras grandes (con una potencia o una zona caliente de por medio), el gobierno
// de EE.UU., los gobiernos grandes (China, UE, Japon, Reino Unido, Rusia, India, G7, OPEP), los ETF de BTC, los
// hackeos o quiebras y las noticias cripto. Igual que noticias.py.
const ACTOR_GRANDE = /ee\.? ?uu|estados unidos|\bu\.s\.|\busa\b|washington|pent[aá]gono|pentagon|rusia|russia|putin|kremlin|ucrania|ukrain|zelensk|israel|netanyahu|ir[aá]n\b|iranian|israeli|russian|ukrainian|chinese|american|\bus\b|teher[aá]n|tehran|china|beijing|pek[ií]n|taiw[aá]n|corea del norte|north korea|\botan\b|\bnato\b|india|pakist[aá]n|hezbol|hamas|gaza/;
const GUERRA = /guerra|\bwar\b|misil|missile|ataque|attack|invasi|invade|bombard|airstrike|\bstrikes?\b|ofensiva|offensive|escalad|tropas|troops|nuclear|militar|military|\bdrones?\b|alto el fuego|ceasefire|tregua|truce/;
const CRIPTO = /bitcoin|\bbtc\b|cripto|crypto|ethereum|stablecoin|binance|coinbase|tether|blockchain/;
// gobiernos grandes: sus instituciones o lideres, o el pais junto a una palabra de politica o economia (asi
// "la China Suarez" no cuenta)
const INSTITUCION = /xi jinping|beijing|pek[ií]n|uni[oó]n europea|european union|comisi[oó]n europea|\bbce\b|\becb\b|lagarde|\bboj\b|banco de jap[oó]n|bank of england|banco de inglaterra|putin|kremlin|\bmodi\b|\bg7\b|\bg20\b|\bopep\b|\bopec\b|pboc|banco popular de china/;
const PAIS = /\bchina\b|jap[oó]n|japan|reino unido|\buk\b|rusia|russia|\bindia\b|arabia saudita|saudi/;
const POLITICA = /gobierno|government|presidente|president|primer ministro|prime minister|ministr|banco central|central bank|tasas|\brates?\b|sanci|arancel|tariff|\bley\b|\blaw\b|prohib|\bban\b|regula|econom|inflaci|cumbre|summit|acuerdo|\bdeal\b|tratado|treaty|elecci|election|parlament|exporta|importa|comercio|\btrade\b|yuan|\byen\b|bolsa|\bstocks?\b|mercados?|markets?|bitcoin|cripto|crypto|militar|military/;
// en las noticias de guerra: si hay ataques es malo para BTC aunque se nombre un alto el fuego; paz sin ataques, bueno
const VIOLENTO = /ataque|attack|\bstrikes?\b|drones?|misil|missile|bombard|ofensiva|offensive|escalad|invade|invasi|muertos|killed|dead|explosi|disparo|fire[sd]? on|amenaza|threat/;
const PAZ = /acuerdo de paz|peace (?:deal|agreement|talks)|fin de la guerra|end (?:of )?the war|alto el fuego|ceasefire|tregua|truce|negociaci|negotiat|retirada de tropas|withdraw/;
// la Fed va primero siempre: si baja las tasas mas de lo previsto es bueno para BTC; si las sube, malo
// hackeos: un exchange grande (o Tether) hackeado: tema propio, impacto maximo y siempre bajista. Igual que noticias.py.
const HACK_SRC = '\\bhack(?:s|ed|eo|eos|eado|eada|earon|ean)?\\b|hackers? (?:steal|stole|drain|rob)|breach|exploit|drain(?:ed|s|ing)?\\b|stolen|robad|robo de|roban|robaron|comprometid|compromised|security incident|incidente de seguridad|(?:halts?|suspends?|suspende|pausa|pauses?|freezes?) (?:all )?(?:withdrawals|retiros)|retiros (?:suspendidos|congelados)';
const HACK = new RegExp(HACK_SRC);
const EXCHANGE = /binance|coinbase|kraken|\bokx\b|bybit|bitget|bingx|kucoin|bitfinex|gemini|crypto\.com|\bhtx\b|huobi|upbit|bitstamp|gate\.io|\bmexc\b|tether|\busdt\b|robinhood/;
const COMO_SE_ESPERABA = /as expected|como se esperaba|como se preve[ií]a|en l[ií]nea con lo (?:esperado|previsto)|in line with expectations/;
const FED = /reserva federal|federal reserve|\bfed\b|powell|\bfomc\b/;
const TEMAS = [
  ['Gobierno de EE.UU.', /trump|casa blanca|white house|congreso de (?:ee|estados)|congress|senado de (?:ee|estados)|\bsenate\b|reserva federal|federal reserve|\bfed\b|powell|tesoro de (?:ee|estados)|treasury|bessent|\bsec\b|\bcftc\b|arancel|tariff|shutdown|gobierno de (?:ee\.? ?uu|estados unidos)|biden|vance|orden ejecutiva|executive order|\bcpi\b|payroll|n[oó]minas no agr/],
  ['ETF', /\betfs?\b|blackrock|\bibit\b|fidelity|grayscale|fondos cotizados/],
  ['Hackeo o quiebra', new RegExp(HACK_SRC + '|quiebra|bankrupt|insolven|congela|freez')],
];
const cuenta = (src, t) => (t.match(RG(src)) || []).length;
const quita = (src, t) => t.replace(RG(src), ' ');
const partes = (t) => t.split(R(PARTES)).filter((p) => p && p.trim());
/** alcista, bajista o neutral para el activo del feed (BTC o una accion), segun el titular (como sesgo de noticias.py). */
function sesgo(titulo, tm = null, feed = '') {
  let t = titulo.toLowerCase();
  const c = feed.startsWith('accion:') ? ACCIONES[feed.slice(7)] : null;
  if (FED.test(t) && COMO_SE_ESPERABA.test(t)) return 'neutral';       // la Fed haciendo lo esperado no sorprende
  if (tm === 'Hackeo de exchange') return 'bajista';
  if (tm === 'Guerras grandes') return VIOLENTO.test(t) || !PAZ.test(t) ? 'bajista' : 'alcista';
  // 1. pese a / despite: manda lo de antes (o, si empieza asi, lo que sigue a la primera coma)
  const m = R(CONTRASTE).exec(t);
  if (m) {
    const antes = t.slice(0, m.index).replace(/^[ ,.]+|[ ,.]+$/g, '');
    t = antes.length > 8 ? antes : (t.slice(m.index + m[0].length).includes(',') && t.indexOf(',') > m.index ? t.slice(t.indexOf(',') + 1) : antes);
  }
  // 4. una accion: si el titular habla de un rival (va primero, o la empresa ni aparece) es neutral
  if (c && !R(SECTOR_AMPLIO).test(t)) {
    const mr = R(c.rivales).exec(t), me = R(c.rx).exec(t);
    if (mr && (!me || mr.index < me.index)) return 'neutral';
  }
  const sujeto = c ? `${c.rx}|${SUJETO_BOLSA}` : SUJETO_BTC;
  // 2. el activo sube o baja: manda
  let mov = 0;
  for (const p of partes(t)) if (R(sujeto).test(p) && !R(MALO_SI_SUBE).test(p)) mov += cuenta(SUBE, p) - cuenta(BAJA, p);
  if (mov) return mov > 0 ? 'alcista' : 'bajista';
  // 3. frases fuertes y despues la direccion de cada parte
  let score = 0;
  for (const rx of FUERTE_BUENO.concat(c ? FUERTE_ACCION_BUENO : FUERTE_BTC_BUENO)) if (R(rx).test(t)) { score += 2; t = quita(rx, t); }
  for (const rx of FUERTE_MALO.concat(c ? FUERTE_ACCION_MALO : FUERTE_BTC_MALO)) if (R(rx).test(t)) { score -= 2; t = quita(rx, t); }
  for (const p of partes(t)) {
    let d = 2 * (cuenta(COMPARA_SUBE, p) - cuenta(COMPARA_BAJA, p));
    const p2 = quita(COMPARA_BAJA, quita(COMPARA_SUBE, p));
    d += cuenta(SUBE, p2) - cuenta(BAJA, p2);
    score += R(MALO_SI_SUBE).test(p) ? -d : d;
    score += cuenta(PALABRA_BUENA, p2) - cuenta(PALABRA_MALA, p2);
  }
  return score > 0 ? 'alcista' : score < 0 ? 'bajista' : 'neutral';
}
const MESES = Object.fromEntries('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(' ').map((m, i) => [m, i + 1]));

// Vercel corta la funcion a los ~10 s: todo tiene que terminar antes de LIMITE (si no, la funcion fallaba entera y la app
// la volvia a esperar en cada ciclo)
let LIMITE = Infinity;
async function get(url) {
  const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), Math.max(500, Math.min(12000, LIMITE - Date.now())));
  try {
    const r = await fetch(url, { headers: { 'User-Agent': UA, Accept: '*/*' }, signal: ctl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.text();
  } finally { clearTimeout(t); }
}

const ENT = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };
const unesc = (s) => s.replace(/&(#x?[0-9a-f]+|\w+);/gi, (m, e) => (e[0] === '#'
  ? String.fromCodePoint(e[1].toLowerCase() === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10)) : ENT[e.toLowerCase()] ?? m));

// opinion, cartas de lectores, editoriales, podcasts y videos: no son un hecho ni una decision (como NO_ES_NOTICIA de Python)
const NO_ES_NOTICIA = /^\W*(?:opini[oó]n|opinion|op-ed|carta|cartas|letters?(?: to the editor)?|editorial|columna|column|commentary|comentario|podcast|video|watch|listen|fotos?|photos?|quiz)\s*[:|]/;

function tema(titulo, feed) {
  const t = titulo.toLowerCase();
  if (feed.startsWith('accion:')) return temaAccion(t, ACCIONES[feed.slice(7)]);
  if (NO_ES_NOTICIA.test(t)) return null;
  if (HACK.test(t) && EXCHANGE.test(t)) return 'Hackeo de exchange';
  if (FED.test(t)) return 'Fed y tasas';
  if (GUERRA.test(t) && ACTOR_GRANDE.test(t)) return 'Guerras grandes';
  for (const [name, rx] of TEMAS) {
    if (rx.test(t)) return name;
    if (name === 'Gobierno de EE.UU.' && (INSTITUCION.test(t) || (PAIS.test(t) && POLITICA.test(t)))) return 'Grandes gobiernos';
  }
  return CRIPTO.test(t) ? 'Cripto' : null;
}

function tag(item, name) {
  const m = item.match(new RegExp(`<${name}[^>]*>([\\s\\S]*?)</${name}>`));
  if (!m) return '';
  let s = m[1].trim().replace(/^<!\[CDATA\[([\s\S]*)\]\]>$/, '$1');
  return unesc(s.replace(/<[^>]+>/g, '')).trim();
}

function parseRss(xml, feed, nowMs, horas = 24) {
  const out = [];
  for (const item of xml.match(/<item\b[\s\S]*?<\/item>/g) || []) {
    let title = tag(item, 'title'), fuente = tag(item, 'source');
    const link = tag(item, 'link'), t = Date.parse(tag(item, 'pubDate'));
    if (!title || !Number.isFinite(t) || t > nowMs + 600000 || nowMs - t > horas * 3600000) continue;
    if (fuente && title.endsWith(' - ' + fuente)) title = title.slice(0, -fuente.length - 3).trim();   // Google agrega " - Medio"
    if (!fuente) { const m = link.match(/^https?:\/\/(?:www\.)?([^/]+)/); fuente = m ? m[1] : ''; }
    const tm = tema(title, feed);
    if (tm) out.push({ tabla: 'noticia', t, titulo: title.slice(0, 220), fuente: fuente.slice(0, 60), url: link, tema: tm, sesgo: sesgo(title, tm, feed), impacto: IMPACTO[tm] });
  }
  return out;
}

// ---------- misma noticia en varios medios: se muestra una sola vez (igual que noticias.py) ----------
const VACIAS = new Set(`el la los las lo un una unos unas de del al y o e u en por para con sin que se su sus es son fue ser
tras sobre como mas pero ya le les hay entre hasta desde ante segun este esta estos estas ese esa eso the of to and in
for on with as after is are was were be been says said over from by at its it will amid into new than more about up
out could would has have had this that what why how a an or not no but can may might just now today vs bitcoin btc
cripto crypto criptomoneda criptomonedas dolar dolares dollar dollars usd precio price`.split(/\s+/));
const EVENTO = { 'Hackeo de exchange': EXCHANGE };

function claves(titulo) {
  const t = titulo.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/(?<=\d)[.,](?=\d)/g, '');
  const out = new Set();
  for (const w of t.match(/[a-z0-9]+/g) || []) {
    if (VACIAS.has(w)) continue;
    const dig = /^\d+$/.test(w);
    if (w.length > 2 || dig) out.add(dig ? w : w.slice(0, 5));
  }
  return out;
}

function mismaNoticia(a, b) {
  if (Math.abs(a.t - b.t) > 12 * 3600000) return false;
  if (a.tema === b.tema && EVENTO[a.tema]) {
    const g = new RegExp(EVENTO[a.tema].source, 'g');
    const ea = new Set(((a.original || a.titulo).toLowerCase().match(g)) || []);
    const eb = ((b.original || b.titulo).toLowerCase().match(g)) || [];
    if (eb.some((x) => ea.has(x))) return true;
  }
  const ka = claves(a.titulo), kb = claves(b.titulo);
  if (!ka.size || !kb.size) return false;
  let comun = 0; for (const x of ka) if (kb.has(x)) comun++;
  const m = Math.min(ka.size, kb.size);
  if (comun >= 3 && comun / m >= 0.5) return true;
  return a.tema === b.tema && comun >= 2 && comun / m >= 0.6;
}

function juntar(listas, maximo = 30) {
  const out = [];
  const todos = listas.flat().sort((a, b) => a.t - b.t || (a.titulo < b.titulo ? -1 : a.titulo > b.titulo ? 1 : 0));
  for (const r of todos) {
    const igual = out.find((o) => mismaNoticia(o, r));
    if (igual) igual.medios += 1; else out.push({ ...r, medios: 1 });
  }
  return out.sort((a, b) => b.t - a.t).slice(0, maximo);
}

// ---------- traduccion de los titulares en ingles (Google Translate, gratis, sin clave) ----------
const INGLES = new Set('the of to and in for on with as after is are says over from by at its will amid into than about could would has have this what why how approves approved hacked hack falls fell rises rose surges surged drops dropped plunges jumps hits record inflows outflows breaks slips soars tumbles rally rallies crash crashes sees amid week weeks year high low'.split(' '));
const ESPANOL = new Set('el la los las de del y en por para con que se un una sus es son tras sobre como pero'.split(' '));
const TRAD = new Map();
const palabras = (titulo) => titulo.toLowerCase().match(/[a-z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1']+/g) || [];
function enIngles(titulo) {
  const w = palabras(titulo);
  const en = w.filter((x) => INGLES.has(x)).length, es = w.filter((x) => ESPANOL.has(x)).length;
  return en >= 1 && en > es;
}
function enEspanol(titulo) {
  const w = palabras(titulo);
  const en = w.filter((x) => INGLES.has(x)).length, es = w.filter((x) => ESPANOL.has(x)).length;
  return es >= 1 && es >= en || /[\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1\u00bf\u00a1]/.test(titulo.toLowerCase());
}
// Google bloquea seguido el traductor gratis "gtx" desde los servidores compartidos (error 429): primero el cliente
// "dict-chrome-ex" (un titular por consulta, en lotes), en dos servidores de Google, y despues MyMemory de a uno.
const TRADUCTORES = ['https://translate.googleapis.com/translate_a/t?client=dict-chrome-ex&sl=en&tl=es',
  'https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=en&tl=es'];
// Vercel corta la funcion a los ~10 s: la traduccion tiene hasta HASTA_MS (lo que no llega, no se muestra)
const HASTA_MS = 6000;
async function traducirGoogle(base, lista, limite) {
  for (let i = 0; i < lista.length && Date.now() < limite;) {
    const lote = [];
    let largo = 0;
    while (i < lista.length && lote.length < 20 && largo + encodeURIComponent(lista[i]).length < 6000) { largo += encodeURIComponent(lista[i]).length + 3; lote.push(lista[i]); i += 1; }
    const r = await fetch(`${base}&${lote.map((q) => `q=${encodeURIComponent(q)}`).join('&')}`, { headers: { 'User-Agent': UA }, signal: AbortSignal.timeout(Math.max(500, limite - Date.now())) });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();
    if (!Array.isArray(j) || j.length !== lote.length) continue;
    lote.forEach((o, k) => { const tr = Array.isArray(j[k]) ? j[k][0] : j[k]; if (typeof tr === 'string' && tr.trim()) TRAD.set(o, unesc(tr.trim())); });
  }
}
async function traducirMyMemory(lista, limite) {
  for (const o of lista.slice(0, 15)) {
    if (Date.now() >= limite) break;
    const r = await fetch(`https://api.mymemory.translated.net/get?langpair=en|es&q=${encodeURIComponent(o.slice(0, 450))}`, { signal: AbortSignal.timeout(Math.max(500, limite - Date.now())) });
    const j = await r.json();
    const tr = j && j.responseData && j.responseData.translatedText;
    if (j.quotaFinished || !tr || /MYMEMORY WARNING/i.test(tr)) break;
    TRAD.set(o, unesc(tr.trim()));
  }
}
/** Pasa al español los titulares en ingles (guarda el original). feedIngles: el feed es en ingles, asi que se traduce
 *  todo lo que no este claramente en español. Lo que no se pudo traducir no se muestra (las noticias van siempre en
 *  español), salvo el hackeo de un exchange: se avisa igual, con el nombre del exchange. Igual en noticias.py. */
async function traducir(rows, feedIngles = false) {
  const hay = (t) => (feedIngles ? !enEspanol(t) : enIngles(t));
  const pend = [...new Set(rows.filter((r) => hay(r.titulo) && !TRAD.has(r.titulo)).map((r) => r.titulo))];
  const limite = Math.min(Date.now() + HASTA_MS, LIMITE);
  for (const base of TRADUCTORES) {
    const faltan = pend.filter((t) => !TRAD.has(t));
    if (!faltan.length || Date.now() >= limite) break;
    try { await traducirGoogle(base, faltan, limite); } catch (e) { /* el siguiente */ }
  }
  try { await traducirMyMemory(pend.filter((t) => !TRAD.has(t)), limite); } catch (e) { /* sin traductor: se descartan */ }
  const out = [];
  for (const r of rows) {
    if (TRAD.has(r.titulo)) { r.original = r.titulo; r.titulo = TRAD.get(r.titulo); out.push(r); continue; }
    if (!hay(r.titulo)) { out.push(r); continue; }
    if (r.tema === 'Hackeo de exchange') {
      const ex = (r.titulo.toLowerCase().match(EXCHANGE) || [''])[0];
      r.original = r.titulo;
      r.titulo = `Posible hackeo en ${ex ? ex[0].toUpperCase() + ex.slice(1) : 'un exchange'} (titular de ${r.fuente || 'un medio'} en inglés, sin traducir)`;
      out.push(r);
    }
  }
  return out;
}

function parseFarside(page, dias = 10) {
  const out = [];
  for (const tr of page.match(/<tr\b[\s\S]*?<\/tr>/g) || []) {
    const cells = [...tr.matchAll(/<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/g)].map((c) => unesc(c[1].replace(/<[^>]+>/g, '')).trim());
    if (cells.length < 3) continue;
    const m = cells[0].match(/^(\d{1,2}) (\w{3}) (\d{4})$/);
    if (!m || !MESES[m[2]]) continue;
    const v = cells[cells.length - 1].replace(/,/g, '').trim();
    if (v === '' || v === '-') continue;
    const neg = v.startsWith('(') && v.endsWith(')'), x = parseFloat(v.replace(/[()]/g, ''));
    if (!Number.isFinite(x)) continue;
    out.push({ tabla: 'etf', fecha: `${m[3]}-${String(MESES[m[2]]).padStart(2, '0')}-${m[1].padStart(2, '0')}`, neto: Math.round((neg ? -x : x) * 10) / 10 });
  }
  return out.sort((a, b) => (a.fecha < b.fecha ? -1 : 1)).slice(-dias);
}

function primaCoinbase(cbUsd, spotUsdt, usdtUsd) {
  const p = (cbUsd / (spotUsdt * (usdtUsd || 1)) - 1) * 100;
  const sig = p > 0.05 ? 'alcista' : p < -0.05 ? 'bajista' : 'neutral';
  const txt = sig === 'alcista' ? 'En EE.UU. pagan más que afuera: compran desde EE.UU. (fondos, empresas)'
    : sig === 'bajista' ? 'En EE.UU. pagan menos que afuera: venden desde EE.UU.' : 'Parejo con el resto del mundo';
  return { tabla: 'contexto', clave: 'prima_coinbase', titulo: 'Prima de Coinbase', valor: `${p >= 0 ? '+' : ''}${p.toFixed(3).replace('.', ',')}%`,
    senal: sig, detalle: txt, prima: Math.round(p * 10000) / 10000 };
}

async function prima() {
  const [cb, ut, by] = await Promise.all([
    get('https://api.exchange.coinbase.com/products/BTC-USD/ticker').then(JSON.parse),
    get('https://api.exchange.coinbase.com/products/USDT-USD/ticker').then(JSON.parse),
    get('https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT').then(JSON.parse),
  ]);
  return primaCoinbase(+cb.price, +by.result.list[0].lastPrice, +ut.price);
}

// ---------- calendario economico de EE.UU. (importancia alta), igual que noticias.py ----------
// Medido 2021-2026: la hora en la que sale uno de estos datos se movio 1,6 a 1,8 veces lo normal y fue fuerte 23-29%
// de las veces (10-12% en las demas). No dice para donde. Fuente: TradingView (Investing.com bloquea la lectura automatica).
const NOMBRES = [
  ['Non Farm Payrolls', 'Empleo: nóminas no agrícolas'],
  ['Unemployment Rate', 'Tasa de desempleo'],
  ['Core Inflation Rate YoY', 'Inflación núcleo (IPC) anual'],
  ['Core Inflation Rate MoM', 'Inflación núcleo (IPC) mensual'],
  ['Inflation Rate YoY', 'Inflación (IPC) anual'],
  ['Inflation Rate MoM', 'Inflación (IPC) mensual'],
  ['Core PCE Price Index MoM', 'Inflación PCE núcleo mensual'],
  ['Core PCE Price Index YoY', 'Inflación PCE núcleo anual'],
  ['PCE Price Index MoM', 'Inflación PCE mensual'],
  ['PCE Price Index YoY', 'Inflación PCE anual'],
  ['Core PCE Price Index', 'Inflación PCE núcleo'],
  ['PCE Price Index', 'Inflación PCE'],
  ['Core PPI MoM', 'Precios mayoristas núcleo (PPI) mensual'],
  ['Core PPI YoY', 'Precios mayoristas núcleo (PPI) anual'],
  ['PPI MoM', 'Precios mayoristas (PPI) mensual'],
  ['PPI YoY', 'Precios mayoristas (PPI) anual'],
  ['PPI', 'Precios mayoristas (PPI)'],
  ['Fed Interest Rate Decision', 'Decisión de tasas de la Fed'],
  ['Fed Press Conference', 'Conferencia de prensa de la Fed'],
  ['FOMC Minutes', 'Minutas de la Fed'],
  ['Powell', 'Habla Powell (Fed)'],
  ['Fed Chair', 'Habla el presidente de la Fed'],
  ['Retail Sales Ex Autos', 'Ventas minoristas sin autos'],
  ['Retail Sales', 'Ventas minoristas'],
  ['GDP', 'PIB'],
  ['ISM Manufacturing', 'ISM manufacturero'],
  ['ISM Services', 'ISM de servicios'],
  ['JOLTs', 'Vacantes laborales (JOLTS)'],
  ['Michigan 5 Year Inflation Expectations', 'Expectativa de inflación a 5 años (Michigan)'],
  ['Michigan Inflation Expectations', 'Expectativa de inflación (Michigan)'],
  ['Michigan', 'Confianza del consumidor (Michigan)'],
  ['Average Hourly Earnings', 'Salario por hora'],
  ['CB Consumer Confidence', 'Confianza del consumidor (Conference Board)'],
  ['Philadelphia Fed', 'Industria de Filadelfia (Fed)'],
  ['Durable Goods', 'Pedidos de bienes durables'],
  ['Personal Income', 'Ingresos personales'],
  ['Personal Spending', 'Gasto personal'],
  ['Initial Jobless Claims', 'Pedidos de subsidio por desempleo'],
  ['Balance of Trade', 'Balanza comercial'],
  ['Building Permits', 'Permisos de construcción'],
  ['Housing Starts', 'Inicio de viviendas'],
  ['Existing Home Sales', 'Ventas de viviendas usadas'],
  ['New Home Sales', 'Ventas de viviendas nuevas'],
  ['ADP', 'Empleo privado (ADP)'],
];
const nombreEs = (titulo) => { const t = (titulo || '').toLowerCase(); const m = NOMBRES.find(([en]) => t.includes(en.toLowerCase())); return m ? m[1] : titulo; };
// como lee el mercado cada dato (igual que SENTIDO en noticias.py: ahi esta explicado)
const SENTIDO = [
  ['inflation expectations', -1], ['inflation', -1], ['cpi', -1], ['pce', -1], ['ppi', -1], ['price index', -1], ['prices', -1],
  ['unemployment rate', 1], ['jobless claims', 1], ['continuing claims', 1],
  ['interest rate', -1], ['payrolls', -1], ['adp', -1], ['jolts', -1], ['employment', -1], ['hourly earnings', -1],
  ['retail sales', -1], ['gdp', -1], ['ism', -1], ['pmi', -1], ['durable goods', -1], ['industrial production', -1],
  ['consumer confidence', 1], ['sentiment', 1],
];
const sentido = (titulo) => { const t = (titulo || '').toLowerCase(); const m = SENTIDO.find(([k]) => t.includes(k)); return m ? m[1] : 0; };
function efecto(titulo, actual, previsto, anterior) {
  const s = sentido(titulo), ref = previsto ?? anterior;
  if (!s || actual === null || actual === undefined || ref === null || ref === undefined) return null;
  const d = Number(actual) - Number(ref);
  if (!Number.isFinite(d)) return null;
  if (Math.abs(d) < 1e-12) return 'neutral';
  return d * s > 0 ? 'positivo' : 'negativo';
}
// lo que se muestra en el calendario: lo que Investing marca con 3 estrellas en EE.UU., por nombre exacto y con cualquier
// importancia de TradingView (igual que INVESTING_ALTA en noticias.py: ahi esta explicado)
const INVESTING_ALTA = new RegExp('^(?:' + [
  'non farm payrolls|unemployment rate|average hourly earnings mom|adp employment change|jolts job openings',
  'initial jobless claims|(core )?inflation rate (mom|yoy)|(core )?ppi mom|core pce price index (mom|yoy)|pce price index yoy',
  'retail sales (mom|ex autos mom)|gdp growth rate qoq( adv| 2nd est| 3rd est| final)?|ism (manufacturing|services) pmi',
  'fed interest rate decision|fomc minutes|fed press conference|fed chair .+|.*powell.*|cb consumer confidence',
  'michigan consumer sentiment( prel| final)?|michigan inflation expectations( prel| final)?|durable goods orders mom',
  'philadelphia fed manufacturing index'].join('|') + ')$', 'i');
const esAlta = (e) => INVESTING_ALTA.test((e.title || '').trim());
/** Igual que parse_calendario en noticias.py. */
function parseCalendario(txt, nowMs = null) {
  const out = [], cal = [];
  for (const e of JSON.parse(txt).result || []) {
    const alta = esAlta(e);
    if (!(alta || e.importance === 1) || !e.date) continue;   // al calendario: lo de 3 estrellas; al analisis: lo de siempre
    const t = Date.parse(e.date), tit = e.title || '', act = e.actual ?? null, prv = e.forecast ?? null, ant = e.previous ?? null;
    if (e.importance === 1 && (nowMs === null || t >= nowMs - 86400000)) out.push({ tabla: 'evento', t, titulo: nombreEs(tit), original: tit.slice(0, 80), previsto: prv, anterior: ant, actual: act });
    if (alta) cal.push({ tabla: 'calendario', t, titulo: nombreEs(tit), original: tit.slice(0, 80), importancia: 3,
      actual: act, previsto: prv, anterior: ant, unidad: e.unit || '', escala: e.scale || '', periodo: e.period || '', efecto: efecto(tit, act, prv, ant) });
  }
  out.sort((a, b) => a.t - b.t);
  cal.sort((a, b) => a.t - b.t || b.importancia - a.importancia || (a.original < b.original ? -1 : a.original > b.original ? 1 : 0));
  return out.concat(cal);
}
async function calendario(nowMs) {
  const iso = (ms) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, '.000Z');
  const ctl = new AbortController(), tm = setTimeout(() => ctl.abort(), Math.max(500, Math.min(12000, LIMITE - Date.now())));
  try {
    const r = await fetch(`https://economic-calendar.tradingview.com/events?from=${iso(nowMs - 7 * 86400000)}&to=${iso(nowMs + 8 * 86400000)}&countries=US`,
      { headers: { 'User-Agent': UA, Origin: 'https://www.tradingview.com', Referer: 'https://www.tradingview.com/' }, signal: ctl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return parseCalendario(await r.text(), nowMs);
  } finally { clearTimeout(tm); }
}

// ---------- Fear & Greed Index (alternative.me, gratis). Igual que noticias.py ----------
const FNG_ES = { 'Extreme Fear': 'Miedo extremo', Fear: 'Miedo', Neutral: 'Neutral', Greed: 'Codicia', 'Extreme Greed': 'Codicia extrema' };
function miedoCodicia(data) {
  const d = data.data, v = parseInt(d[0].value, 10), ayer = d.length > 1 ? parseInt(d[1].value, 10) : null;
  const clase = d[0].value_classification || '';
  const txt = (FNG_ES[clase] || clase) + (ayer !== null && ayer !== v ? ` (ayer ${ayer})` : '');
  return { tabla: 'contexto', clave: 'miedo_codicia', titulo: 'Fear & Greed Index', valor: `${v} · ${clase}`, senal: 'neutral',
    detalle: txt, fng: v, fng_ayer: ayer, fng_clase: clase };
}

async function externo(nowMs = Date.now(), limiteMs = Infinity, moneda = 'BTC') {
  LIMITE = limiteMs;
  if (ACCIONES[moneda]) {             // una accion: sus noticias (empresa, region, sector y bolsa) y el calendario
    const [listas, cal] = await Promise.all([
      Promise.all(ACCIONES[moneda].feeds.map(([feed, url]) => get(url).then((x) => traducir(parseRss(x, feed, nowMs), /hl=en/.test(url))).catch(() => []))),
      calendario(nowMs).catch(() => [])]);
    return juntar(listas).concat(cal);
  }
  // todo en paralelo (antes las noticias y despues el resto: podia pasar los 10 s de Vercel)
  const [listas, etf, pr, cal, fng] = await Promise.all([
    Promise.all(FEEDS.map(([feed, url]) => get(url).then((x) => traducir(parseRss(x, feed, nowMs), /hl=en|coindesk/.test(url))).catch(() => []))),
    get(FARSIDE).then(parseFarside).catch(() => []), prima().catch(() => null),
    calendario(nowMs).catch(() => []), get('https://api.alternative.me/fng/?limit=2').then((x) => miedoCodicia(JSON.parse(x))).catch(() => null)]);
  const rows = juntar(listas);
  rows.push(...etf, ...cal);
  if (pr) rows.push(pr);
  if (fng) rows.push(fng);
  return rows;
}

module.exports = async (req, res) => {
  // solo el calendario, casi al instante (la pagina lo pide cada minuto alrededor de un dato): cache de 20 s
  if (req.query && req.query.solo === 'calendario') {
    let filas = [];
    try { filas = await calendario(Date.now()); } catch (e) { /* sin calendario */ }
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.setHeader('Cache-Control', 'public, s-maxage=20, stale-while-revalidate=40');
    res.status(200).send(JSON.stringify({ rows: filas, hora: Date.now() }));
    return;
  }
  let rows = [];
  const moneda = /^[A-Z]{2,6}$/.test(String((req.query && req.query.moneda) || '')) ? req.query.moneda : 'BTC';
  try { rows = await externo(Date.now(), Date.now() + 8000, moneda); } catch (e) { /* sin datos de afuera: la pagina igual funciona */ }
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'public, s-maxage=600, stale-while-revalidate=1800');
  res.status(200).send(JSON.stringify({ rows, hora: Date.now() }));
};
module.exports.externo = externo;
module.exports.parseRss = parseRss;
module.exports.parseFarside = parseFarside;
module.exports.juntar = juntar;
module.exports.claves = claves;
module.exports.mismaNoticia = mismaNoticia;
module.exports.enIngles = enIngles;
module.exports.miedoCodicia = miedoCodicia;
module.exports.primaCoinbase = primaCoinbase;
module.exports.parseCalendario = parseCalendario;
module.exports.sesgo = sesgo;
module.exports.tema = tema;
module.exports.ACCIONES = ACCIONES;
