/*
 * Funcion del servidor de Vercel: tus posiciones abiertas y tus ordenes puestas en BingX, SOLO LECTURA, para que
 * "Mis posiciones" y "Proximas compras" se actualicen sin editar plan_compras.json.
 *
 * Las claves van en las variables de entorno de Vercel (Settings -> Environment Variables), nunca en el codigo:
 *   BINGX_API_KEY, BINGX_API_SECRET  una clave de API de BingX con permiso SOLO DE LECTURA (sin operar ni retirar)
 *   POSICIONES_CLAVE                 una contraseña tuya: la pagina la pide una vez y la manda en cada pedido
 * Sin las tres, o con la contraseña mal, no devuelve nada. La respuesta no se guarda en ningun cache.
 */
const crypto = require('crypto');

const BASE = 'https://open-api.bingx.com';
const UA = 'Mozilla/5.0 (compatible; AnalistaBTC/1.0)';

/** Firma de BingX: HMAC SHA256 de los parametros ordenados por nombre, con el timestamp al final. */
function firmar(params, secret, ts) {
  const q = Object.keys(params).sort().map((k) => `${k}=${params[k]}`).concat([`timestamp=${ts}`]).join('&');
  return `${q}&signature=${crypto.createHmac('sha256', secret).update(q).digest('hex')}`;
}

async function pedir(path, params, key, secret) {
  const r = await fetch(`${BASE}${path}?${firmar(params, secret, Date.now())}`, {
    headers: { 'X-BX-APIKEY': key, 'User-Agent': UA }, signal: AbortSignal.timeout(10000) });
  const j = await r.json();
  if (j.code !== 0) throw new Error(`BingX ${j.code}: ${j.msg || 'error'}`);
  return j.data;
}

/** Posiciones por cripto (BTC-USDT -> BTC), en el formato de plan_compras.json "posiciones" mas lo que da BingX. */
function posiciones(data) {
  const out = {};
  (Array.isArray(data) ? data : []).forEach((p) => {
    const cant = Math.abs(+p.positionAmt || 0);
    if (!cant) return;
    const m = String(p.symbol).split('-')[0];
    out[m] = { cantidad: cant, entrada: +p.avgPrice, margen: +(p.margin || p.initialMargin || 0), lado: p.positionSide,
      aislado: !!p.isolated, apalancamiento: +p.leverage || null, liquidacion: +p.liquidationPrice || null,
      resultado: +p.unrealizedProfit || 0, marca: +p.markPrice || null };
  });
  return out;
}

/** Ordenes de compra limite puestas, por cripto: [{precio, cantidad, valor}]. */
function ordenes(data) {
  const out = {};
  ((data && data.orders) || []).forEach((o) => {
    if (o.side !== 'BUY' || o.type !== 'LIMIT') return;
    const m = String(o.symbol).split('-')[0];
    (out[m] = out[m] || []).push({ precio: +o.price, cantidad: +o.origQty, valor: +o.price * +o.origQty });
  });
  return out;
}

function claveOk(dada, esperada) {
  const a = Buffer.from(String(dada || '')), b = Buffer.from(String(esperada || ''));
  return a.length === b.length && b.length >= 8 && crypto.timingSafeEqual(a, b);
}

module.exports = async (req, res) => {
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store, private');
  const { BINGX_API_KEY: key, BINGX_API_SECRET: secret, POSICIONES_CLAVE: clave } = process.env;
  if (!key || !secret || !clave) { res.status(503).send(JSON.stringify({ ok: false, error: 'Faltan las variables BINGX_API_KEY, BINGX_API_SECRET y POSICIONES_CLAVE en Vercel' })); return; }
  if (!claveOk(req.headers['x-clave'], clave)) { res.status(401).send(JSON.stringify({ ok: false, error: 'Contraseña incorrecta' })); return; }
  try {
    const [pos, ord] = await Promise.all([pedir('/openApi/swap/v2/user/positions', {}, key, secret),
      pedir('/openApi/swap/v2/trade/openOrders', {}, key, secret).catch(() => null)]);
    res.status(200).send(JSON.stringify({ ok: true, hora: Date.now(), posiciones: posiciones(pos), ordenes: ord ? ordenes(ord) : null }));
  } catch (e) {
    res.status(502).send(JSON.stringify({ ok: false, error: String(e.message || e).slice(0, 200) }));
  }
};
module.exports.firmar = firmar;
module.exports.posiciones = posiciones;
module.exports.ordenes = ordenes;
