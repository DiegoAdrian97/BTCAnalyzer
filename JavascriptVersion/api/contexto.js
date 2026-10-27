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
  ['cripto', 'https://www.coindesk.com/arc/outboundfeeds/rss/'],
];
const FARSIDE = 'https://farside.co.uk/bitcoin-etf-flow-all-data/';
// Solo lo que de verdad mueve a BTC: guerras grandes (con una potencia o una zona caliente de por medio), el gobierno
// de EE.UU., los gobiernos grandes (China, UE, Japon, Reino Unido, Rusia, India, G7, OPEP), los ETF de BTC, los
// hackeos o quiebras y las noticias cripto. Igual que noticias.py.
const ACTOR_GRANDE = /ee\.? ?uu|estados unidos|\bu\.s\.|\busa\b|washington|pent[aá]gono|pentagon|rusia|russia|putin|kremlin|ucrania|ukrain|zelensk|israel|netanyahu|ir[aá]n\b|iranian|israeli|russian|ukrainian|chinese|american|\bus\b|teher[aá]n|tehran|china|beijing|pek[ií]n|taiw[aá]n|corea del norte|north korea|\botan\b|\bnato\b|india|pakist[aá]n|hezbol|hamas|gaza/;
const GUERRA = /guerra|\bwar\b|misil|missile|ataque|attack|invasi|invade|bombard|airstrike|\bstrikes?\b|ofensiva|offensive|escalad|tropas|troops|nuclear|militar|military|\bdrones?\b|alto el fuego|ceasefire|tregua|truce/;
const CRIPTO = /bitcoin|\bbtc\b|cripto|crypto|ethereum|stablecoin|binance|coinbase|tether|blockchain/;
const TEMAS = [
  ['Gobierno de EE.UU.', /trump|casa blanca|white house|congreso de (?:ee|estados)|congress|senado de (?:ee|estados)|\bsenate\b|reserva federal|federal reserve|\bfed\b|powell|tesoro de (?:ee|estados)|treasury|bessent|\bsec\b|\bcftc\b|arancel|tariff|shutdown|gobierno de (?:ee\.? ?uu|estados unidos)|biden|vance|orden ejecutiva|executive order|\bcpi\b|payroll|n[oó]minas no agr/],
  ['Grandes gobiernos', /china|xi jinping|beijing|pek[ií]n|uni[oó]n europea|european union|comisi[oó]n europea|\bbce\b|\becb\b|lagarde|jap[oó]n|japan|\bboj\b|banco de jap[oó]n|reino unido|\bu\.?k\.?\b|bank of england|banco de inglaterra|rusia|russia|putin|kremlin|india|\bmodi\b|\bg7\b|\bg20\b|\bopep\b|\bopec\b|arabia saudita|saudi/],
  ['ETF', /\betfs?\b|blackrock|\bibit\b|fidelity|grayscale|fondos cotizados/],
  ['Hackeo o quiebra', /hacke|hacked|robo de|roban|robaron|exploit|quiebra|bankrupt|insolven|congela|freez/],
];
// si el titular es bueno o malo para BTC: frases fuertes (pesan 2) y palabras (pesan 1), igual que noticias.py
const SESGO = [
  [-2, 'fewer rate cuts|menos recortes|sub(?:e|en|ir|a)(?: de)? (?:las |la )?tasas|rate hikes?|hike rates|raises? (?:interest )?rates|eleva(?:n)? (?:las |la )?tasas|declara(?:ci[oó]n de)? (?:la )?guerra|invade|invasi[oó]n|prohibe|proh[ií]be|bans? (?:bitcoin|crypto)|hacke|hacked|robo de|roban|robaron|exploit'],
  [2, 'recorte de tasas|recorta(?:n)? (?:las |la )?tasas|rate cuts?|cuts? rates|baja(?:n|r)? (?:de )?(?:las |la )?tasas|baja(?:n)? la inflaci|inflaci[oó]n (?:baja|cae|se desacelera|se modera)|inflation (?:cools|eases|slows)|cooler|cut rates|alto el fuego|ceasefire|tregua|acuerdo de paz|peace deal|reserva estrat[eé]gica|strategic reserve|aprueba (?:el |los )?etf|etf approv'],
  [1, '\\bsube|\\bsuben|subida|se dispar|r[eé]cord|m[aá]ximo hist|rall|surge|soar|jump|rebot|rebound|recupera|entradas|inflows?|aprueb|approv|adopt|compra|\\bbuys?\\b|acumula|dovish|acuerdo|\\bdeal\\b|alivio|optimis'],
  [-1, '\\bcae\\b|\\bcaen\\b|ca[ií]da|desplom|derrumb|hund|pierde|retroced|plunge|\\bdrops?\\b|\\bfalls?\\b|crash|slump|tumble|sell-?off|venta masiva|liquidac|liquidat|quiebra|bankrupt|demanda|lawsuit|investiga|salidas|outflows?|guerra|\\bwar\\b|misil|missile|ataque|attack|\\bstrikes?\\b|bombard|escalad|sanci|arancel|tariff|hawkish|recesi|recession|shutdown|miedo|\\bfear\\b|p[aá]nico|panic|temor|slides?|slips?'],
];
const IMPACTO = { 'Guerras grandes': 3, 'Gobierno de EE.UU.': 3, 'Grandes gobiernos': 2, ETF: 2, 'Hackeo o quiebra': 2, Cripto: 1 };
function sesgo(titulo) {
  let t = titulo.toLowerCase(), score = 0;
  for (const [peso, src] of SESGO) {
    const rx = new RegExp(src, 'g'), n = (t.match(rx) || []).length;
    score += peso * n;
    if (Math.abs(peso) === 2 && n) t = t.replace(rx, ' ');
  }
  return score > 0 ? 'alcista' : score < 0 ? 'bajista' : 'neutral';
}
const MESES = Object.fromEntries('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(' ').map((m, i) => [m, i + 1]));

async function get(url) {
  const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), 12000);
  try {
    const r = await fetch(url, { headers: { 'User-Agent': UA, Accept: '*/*' }, signal: ctl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.text();
  } finally { clearTimeout(t); }
}

const ENT = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };
const unesc = (s) => s.replace(/&(#x?[0-9a-f]+|\w+);/gi, (m, e) => (e[0] === '#'
  ? String.fromCodePoint(e[1].toLowerCase() === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10)) : ENT[e.toLowerCase()] ?? m));

function tema(titulo, feed) {
  const t = titulo.toLowerCase();
  if (GUERRA.test(t) && ACTOR_GRANDE.test(t)) return 'Guerras grandes';
  for (const [name, rx] of TEMAS) if (rx.test(t)) return name;
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
    if (tm) out.push({ tabla: 'noticia', t, titulo: title.slice(0, 220), fuente: fuente.slice(0, 60), url: link, tema: tm, sesgo: sesgo(title), impacto: IMPACTO[tm] });
  }
  return out;
}

function juntar(listas, maximo = 30) {
  const seen = new Set(), out = [];
  for (const r of listas.flat().sort((a, b) => b.t - a.t)) {
    const k = r.titulo.toLowerCase().replace(/[^a-z0-9áéíóúñ]+/g, '').slice(0, 60);
    if (seen.has(k)) continue;
    seen.add(k); out.push(r);
  }
  return out.slice(0, maximo);
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

async function externo(nowMs = Date.now()) {
  const listas = await Promise.all(FEEDS.map(([feed, url]) => get(url).then((x) => parseRss(x, feed, nowMs)).catch(() => [])));
  const rows = juntar(listas);
  const [etf, pr] = await Promise.all([get(FARSIDE).then(parseFarside).catch(() => []), prima().catch(() => null)]);
  rows.push(...etf);
  if (pr) rows.push(pr);
  return rows;
}

module.exports = async (req, res) => {
  let rows = [];
  try { rows = await externo(); } catch (e) { /* sin datos de afuera: la pagina igual funciona */ }
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'public, s-maxage=600, stale-while-revalidate=1800');
  res.status(200).send(JSON.stringify({ rows, hora: Date.now() }));
};
module.exports.externo = externo;
module.exports.parseRss = parseRss;
module.exports.parseFarside = parseFarside;
module.exports.juntar = juntar;
module.exports.primaCoinbase = primaCoinbase;
module.exports.sesgo = sesgo;
module.exports.tema = tema;
