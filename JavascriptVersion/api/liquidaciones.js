/*
 * Datos para el "Mapa de liquidaciones" de la app (panel aparte): velas, interes abierto (open interest), proporcion de
 * cuentas largas y cortas y liquidaciones reales, de las fuentes publicas y gratis que hay. El mapa (donde se acumulan
 * las liquidaciones estimadas) lo arma la pagina con esto: ver "Mapa de liquidaciones" en dashboard/index.html.
 *
 * Por que aca y no en el telefono: Bybit, OKX y Binance no dejan a una pagina pedir todo esto (CORS o bloqueos), y asi
 * se piden juntas, una vez, y quedan 5 min en la cache de Vercel para todos (las zonas se recalculan cada tanto, como en
 * los mapas de Coinglass o mapaliquidaciones.com: no hace falta al segundo). Corre en Frankfurt (vercel.json).
 *
 * Fuentes (todas publicas, sin claves):
 *   velas          Binance Futures (si falla, Bybit)
 *   open interest  Binance (ultimos 30 dias), Bybit (de a 200, hacia atras) y OKX (todo OKX, 5m / 1H / 1D), en USD
 *   largos/cortos  Binance (cuentas) y Bybit (cuentas)
 *   liquidaciones  OKX (las reales de las ultimas horas)
 * Coinglass, Hyblock, Kingfisher y TradingDifferent no publican sus datos (API paga o ninguna).
 */
const TF_MS = { '5m': 3e5, '15m': 9e5, '1h': 36e5, '4h': 144e5, '1d': 864e5 };
const VER = { '5m': 288, '15m': 288, '1h': 336, '4h': 360, '1d': 900 };          // velas que se muestran
const PREVIAS = { '5m': 300, '15m': 300, '1h': 400, '4h': 300, '1d': 200 };      // antes, para que el mapa arranque cargado
const BYBIT_TF = { '5m': '5min', '15m': '15min', '1h': '1h', '4h': '4h', '1d': '1d' };
const BYBIT_K = { '5m': '5', '15m': '15', '1h': '60', '4h': '240', '1d': 'D' };
const OKX_TF = { '5m': '5m', '1h': '1H', '1d': '1D' };
const MONEDAS = new Set(['BTC', 'ETH', 'SOL', 'XRP', 'BNB', 'DOGE', 'ADA', 'AVAX', 'LINK', 'LTC', 'SUI', 'ZEC', 'TRX', 'DOT', 'NEAR', 'APT', 'ARB', 'OP', 'TON', 'HYPE']);

const pedir = async (url) => {
  const r = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0 (analista-btc)' }, signal: AbortSignal.timeout(9000) });
  if (!r.ok) throw new Error(`${new URL(url).host} ${r.status}`);
  return r.json();
};
const intento = (p) => p.catch((e) => ({ error: String(e.message || e).slice(0, 120) }));

async function velas(sym, tf, n) {
  const ms = TF_MS[tf], out = [];
  try {
    let fin = Date.now();
    while (out.length < n) {
      const k = await pedir(`https://fapi.binance.com/fapi/v1/klines?symbol=${sym}&interval=${tf}&limit=1500&endTime=${fin}`);
      if (!Array.isArray(k) || !k.length) break;
      out.unshift(...k.map((r) => [+r[0], +r[1], +r[2], +r[3], +r[4]]));
      fin = +k[0][0] - 1;
      if (k.length < 1500) break;
    }
    if (out.length) return { fuente: 'Binance', velas: out.slice(-n) };
  } catch (e) { /* Bybit */ }
  let fin = Date.now();
  while (out.length < n) {
    const j = await pedir(`https://api.bybit.com/v5/market/kline?category=linear&symbol=${sym}&interval=${BYBIT_K[tf]}&limit=1000&end=${fin}`);
    const l = (j.result && j.result.list) || [];
    if (!l.length) break;
    out.unshift(...l.map((r) => [+r[0], +r[1], +r[2], +r[3], +r[4]]).reverse());
    fin = +l[l.length - 1][0] - 1;
    if (l.length < 1000) break;
  }
  return { fuente: 'Bybit', velas: out.slice(-n).sort((a, b) => a[0] - b[0]) };
}

async function oiBinance(sym, tf) {
  {
    const j = await pedir(`https://fapi.binance.com/futures/data/openInterestHist?symbol=${sym}&period=${tf}&limit=500`);
    return j.map((x) => [+x.timestamp, +x.sumOpenInterestValue]).sort((a, b) => a[0] - b[0]);
  }
  return [];
}
async function oiBybit(sym, tf, n, precioDe) {
  const out = []; let cursor = '';
  for (let k = 0; k < Math.ceil(n / 200) && k < 6; k++) {
    const j = await pedir(`https://api.bybit.com/v5/market/open-interest?category=linear&symbol=${sym}&intervalTime=${BYBIT_TF[tf]}&limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`);
    const l = (j.result && j.result.list) || [];
    l.forEach((x) => { const t = +x.timestamp, p = precioDe(t); if (p) out.push([t, +x.openInterest * p]); });
    cursor = j.result && j.result.nextPageCursor;
    if (!cursor || l.length < 200) break;
  }
  return out.sort((a, b) => a[0] - b[0]);
}
async function oiOkx(mon, tf) {
  if (!OKX_TF[tf]) return [];
  const j = await pedir(`https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume?ccy=${mon}&period=${OKX_TF[tf]}`);
  return (j.data || []).map((x) => [+x[0], +x[1]]).sort((a, b) => a[0] - b[0]);
}
async function lsBinance(sym, tf) {
  const j = await pedir(`https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=${sym}&period=${tf}&limit=500`);
  return j.map((x) => [+x.timestamp, +x.longAccount]).sort((a, b) => a[0] - b[0]);
}
async function lsBybit(sym, tf) {
  const j = await pedir(`https://api.bybit.com/v5/market/account-ratio?category=linear&symbol=${sym}&period=${BYBIT_TF[tf]}&limit=500`);
  return ((j.result && j.result.list) || []).map((x) => [+x.timestamp, +x.buyRatio]).sort((a, b) => a[0] - b[0]);
}
async function liqOkx(mon) {
  // tamano de cada contrato (BTC 0,01, ETH 0,1, SOL 1...) para pasar los contratos a USD
  const ins = await pedir(`https://www.okx.com/api/v5/public/instruments?instType=SWAP&instId=${mon}-USDT-SWAP`);
  const ct = +((ins.data && ins.data[0] && ins.data[0].ctVal) || 0);
  if (!ct) return [];
  const out = []; let after = '';
  for (let k = 0; k < 5; k++) {
    const j = await pedir(`https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&instFamily=${mon}-USDT&state=filled&limit=100${after ? `&after=${after}` : ''}`);
    const det = (j.data && j.data[0] && j.data[0].details) || [];
    if (!det.length) break;
    // posSide: el lado de la posicion liquidada; sz en contratos: a USD con el precio de quiebra
    det.forEach((d) => out.push([+d.ts, d.posSide === 'long' ? 'l' : 's', +d.bkPx, Math.round(+d.sz * ct * +d.bkPx)]));
    after = Math.min(...det.map((d) => +d.ts));
  }
  return out;
}

module.exports = async (req, res) => {
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'public, s-maxage=300, stale-while-revalidate=600');
  try {
    const q = new URL(req.url || '/', 'http://x').searchParams;
    const mon = String(q.get('moneda') || 'BTC').toUpperCase(), tf = String(q.get('tf') || '1h');
    if (!MONEDAS.has(mon) || !TF_MS[tf]) { res.setHeader('Cache-Control', 'no-store'); res.status(400).send(JSON.stringify({ ok: false, error: 'moneda o temporalidad desconocida' })); return; }
    const sym = `${mon}USDT`, n = VER[tf] + PREVIAS[tf];
    const v = await velas(sym, tf, n);
    const cierre = new Map(v.velas.map((b) => [b[0], b[4]]));
    const precioDe = (t) => cierre.get(t) || cierre.get(t - TF_MS[tf]) || null;
    const [bin, byb, okx, lsb, lsy, liq] = await Promise.all([intento(oiBinance(sym, tf)), intento(oiBybit(sym, tf, n, precioDe)), intento(oiOkx(mon, tf)),
      intento(lsBinance(sym, tf)), intento(lsBybit(sym, tf)), intento(liqOkx(mon))]);
    const ok = (x) => (Array.isArray(x) ? x : []), err = (x) => (Array.isArray(x) ? null : x.error);
    const fuentes = { velas: v.fuente, oi: { binance: ok(bin).length, bybit: ok(byb).length, okx: ok(okx).length }, ls: { binance: ok(lsb).length, bybit: ok(lsy).length },
      liquidaciones: { okx: ok(liq).length }, errores: [['Binance OI', err(bin)], ['Bybit OI', err(byb)], ['OKX OI', err(okx)], ['Binance L/S', err(lsb)], ['Bybit L/S', err(lsy)], ['OKX liq.', err(liq)]].filter((x) => x[1]) };
    res.status(200).send(JSON.stringify({ ok: true, moneda: mon, tf, ver: VER[tf], hora: Date.now(), velas: v.velas,
      oi: { binance: ok(bin), bybit: ok(byb), okx: ok(okx) }, ls: { binance: ok(lsb), bybit: ok(lsy) }, liq: ok(liq), fuentes }));
  } catch (e) {
    res.setHeader('Cache-Control', 'no-store');
    res.status(502).send(JSON.stringify({ ok: false, error: String(e.message || e).slice(0, 200) }));
  }
};
