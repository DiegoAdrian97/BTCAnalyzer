/*
 * Funcion del servidor de Vercel: titulares, flujos de los ETF de BTC y prima de Coinbase, para explicar los
 * movimientos fuertes. La pagina no puede leer esas fuentes directo (el navegador lo bloquea), el servidor si.
 * Misma logica que noticias.py (version Python): mismas fuentes, mismas filas. Fuentes publicas, sin claves.
 * Vercel guarda la respuesta 10 minutos: todos los telefonos comparten el mismo pedido.
 */
const UA = 'Mozilla/5.0 (compatible; AnalistaBTC/1.0)';
const GN = 'https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q=';
const FEEDS = [
  ['cripto', GN + 'bitcoin+OR+criptomonedas+OR+BTC+when:1d'],
  ['mundo', GN + 'guerra+OR+misiles+OR+ataque+OR+aranceles+OR+%22Reserva+Federal%22+OR+inflaci%C3%B3n+OR+Trump+when:1d'],
  ['cripto', 'https://www.coindesk.com/arc/outboundfeeds/rss/'],
];
const FARSIDE = 'https://farside.co.uk/bitcoin-etf-flow-all-data/';
// temas, en orden de prioridad: el primero que aparece en el titular manda
const TEMAS = [
  ['Guerra y geopolítica', /guerra|\bwar\b|misil|missile|ataque|attack|invasi|bombard|israel|ir[aá]n\b|rusia|russia|ucrania|ukrain|taiw[aá]n|\botan\b|\bnato\b|sancion|sanction|conflicto|militar/],
  ['Fed, tasas e inflación', /\bfed\b|reserva federal|federal reserve|powell|tasas? de inter|interest rate|rate cut|inflaci|inflation|\bcpi\b|\bipc\b|empleo|payroll|desempleo|recesi|recession/],
  ['Aranceles y política', /arancel|tariff|trump|shutdown|congreso|congress|elecci|election/],
  ['ETF', /\betfs?\b|blackrock|\bibit\b|fidelity|grayscale|fondos cotizados/],
  ['Regulación', /\bsec\b|regulac|regulat|\bley\b|\blaw\b|prohib|\bban\b|\bcftc\b|stablecoin bill|clarity act/],
  ['Hackeo o quiebra', /hack|robo\b|robaron|exploit|quiebra|bankrupt|insolven|congela|freez/],
  ['Ballenas y empresas', /ballena|whale|strategy|microstrategy|saylor|tesla|tesorer|treasury|reserva estrat|strategic reserve|mt\.? ?gox/],
  ['Liquidaciones', /liquidac|liquidat/],
];
const CRIPTO = /bitcoin|\bbtc\b|cripto|crypto/;
// si el titular es bueno o malo para BTC: frases fuertes (pesan 2) y palabras (pesan 1), igual que noticias.py
const SESGO = [
  [-2, 'fewer rate cuts|menos recortes|sub(?:e|en|ir|a)(?: de)? (?:las |la )?tasas|rate hikes?|hike rates|declara(?:ci[oó]n de)? (?:la )?guerra|invade|invasi[oó]n|prohibe|proh[ií]be|bans? (?:bitcoin|crypto)|hacke|hacked|robo de|roban|robaron|exploit'],
  [2, 'recorte de tasas|rate cuts?|baja(?:n|r)? (?:de )?(?:las |la )?tasas|baja(?:n)? la inflaci|inflaci[oó]n (?:baja|cae|se desacelera|se modera)|inflation (?:cools|eases|slows)|cooler|cut rates|alto el fuego|ceasefire|tregua|acuerdo de paz|peace deal|reserva estrat[eé]gica|strategic reserve|aprueba (?:el |los )?etf|etf approv'],
  [1, '\\bsube|\\bsuben|subida|dispar|r[eé]cord|m[aá]ximo hist|rall|surge|soar|jump|rebot|rebound|recupera|entradas|inflows?|aprueb|approv|adopt|compra|\\bbuys?\\b|acumula|dovish|acuerdo|\\bdeal\\b|alivio|optimis'],
  [-1, '\\bcae\\b|\\bcaen\\b|ca[ií]da|desplom|derrumb|hund|pierde|retroced|plunge|\\bdrops?\\b|\\bfalls?\\b|crash|slump|tumble|sell-?off|venta masiva|liquidac|liquidat|quiebra|bankrupt|demanda|lawsuit|investiga|salidas|outflows?|guerra|\\bwar\\b|misil|missile|ataque|attack|bombard|escalad|sanci|arancel|tariff|hawkish|recesi|recession|shutdown|miedo|\\bfear\\b|p[aá]nico|panic|temor|slides?|slips?'],
];
const IMPACTO = { 'Guerra y geopolítica': 3, 'Fed, tasas e inflación': 3, 'Hackeo o quiebra': 3, 'Aranceles y política': 2, ETF: 2,
  'Regulación': 2, 'Ballenas y empresas': 1, Liquidaciones: 1, Cripto: 1 };
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
  for (const [name, rx] of TEMAS) if (rx.test(t)) return name;
  return feed === 'cripto' && CRIPTO.test(t) ? 'Cripto' : null;
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
