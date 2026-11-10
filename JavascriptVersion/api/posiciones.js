/*
 * Funcion del servidor de Vercel: tus posiciones abiertas y tus ordenes puestas en BingX, SOLO LECTURA, para que
 * "Mis posiciones" y "Proximas compras" se actualicen sin editar plan_compras.json.
 *
 * Las claves van en las variables de entorno de Vercel (Settings -> Environment Variables), nunca en el codigo:
 *   BINGX_API_KEY, BINGX_API_SECRET  una clave de API de BingX con permiso SOLO DE LECTURA (sin operar ni retirar)
 *   POSICIONES_CLAVE                 una contraseña tuya: la pagina la pide una vez y la manda en cada pedido
 *   PLAN_GITHUB_TOKEN                token de GitHub de SOLO LECTURA del repositorio privado del plan (PLAN_REPO,
 *                                    por defecto DiegoAdrian97/BTCAnalyzer-plan): el plan de compras ya no esta en el
 *                                    repositorio publico ni en la pagina; se entrega aca, solo con la contraseña
 * Sin las tres primeras, o con la contraseña mal, no devuelve nada. La respuesta no se guarda en ningun cache.
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

/** Simbolo de BingX -> activo de la app: BTC-USDT -> BTC; acciones: NCSKMSTR2USD-USDT, NCSKMSTR-USDT o MSTR-USDT -> MSTR. */
function activo(symbol) {
  const b = String(symbol).toUpperCase().split('-')[0];
  const m = /^NCS[KIC]([A-Z0-9]+?)(?:2USD)?$/.exec(b);
  return m ? m[1] : b;
}

/** Posiciones por cripto (BTC-USDT -> BTC), en el formato de plan_compras.json "posiciones" mas lo que da BingX. */
function posiciones(data) {
  const out = {};
  (Array.isArray(data) ? data : []).forEach((p) => {
    const cant = Math.abs(+p.positionAmt || 0);
    if (!cant) return;
    const m = activo(p.symbol);
    // signo: 1 long, -1 short (en modo de una sola direccion, BingX lo da con el signo de positionAmt)
    const signo = p.positionSide === 'SHORT' || (p.positionSide !== 'LONG' && +p.positionAmt < 0) ? -1 : 1;
    out[m] = { cantidad: cant, signo, entrada: +p.avgPrice, margen: +(p.margin || p.initialMargin || 0), lado: p.positionSide,
      aislado: !!p.isolated, apalancamiento: +p.leverage || null, liquidacion: +p.liquidationPrice || null,
      resultado: +p.unrealizedProfit || 0, marca: +p.markPrice || null,
      // para el precio de equilibrio: lo ya realizado (comisiones pagadas y funding, negativo si costo) y, si BingX lo da, el suyo
      realizado: +p.realisedProfit || 0, equilibrio: +(p.breakEvenPrice || p.breakevenPrice || 0) || null };
  });
  return out;
}

/** Ordenes de compra limite puestas, por cripto: [{precio, cantidad, valor}]. */
function ordenes(data) {
  const out = {};
  ((data && data.orders) || []).forEach((o) => {
    if (o.side !== 'BUY' || o.type !== 'LIMIT') return;
    const m = activo(o.symbol);
    (out[m] = out[m] || []).push({ precio: +o.price, cantidad: +o.origQty, valor: +o.price * +o.origQty });
  });
  return out;
}

/** El plan de compras, del repositorio privado (un minuto en memoria). null si no hay token. */
let planCache = null;
async function leerPlan() {
  const tok = process.env.PLAN_GITHUB_TOKEN, repo = process.env.PLAN_REPO || 'DiegoAdrian97/BTCAnalyzer-plan';
  if (!tok) return null;
  if (planCache && Date.now() - planCache[0] < 300000) return planCache[1];   // 5 min: el plan cambia poco (antes, 1 pedido a GitHub por minuto)
  const r = await fetch(`https://api.github.com/repos/${repo}/contents/plan_compras.json`, { signal: AbortSignal.timeout(8000),
    headers: { Authorization: `Bearer ${tok}`, Accept: 'application/vnd.github.raw+json', 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': UA } });
  if (!r.ok) throw new Error(r.status === 404 ? 'plan privado: el token no tiene acceso al repositorio del plan (GitHub 404)'
    : r.status === 401 ? 'plan privado: el token es inválido o venció (GitHub 401)'
      : r.status === 403 ? 'plan privado: al token le falta el permiso Contents de lectura (GitHub 403)' : `plan privado: GitHub ${r.status}`);
  const plan = JSON.parse(await r.text());
  planCache = [Date.now(), plan];
  return plan;
}

/** Capital total en USDT: el patrimonio de futuros USDT-M (saldo + PnL no realizado, de /swap/v3/user/balance) mas el
 *  resto de las cuentas (spot, fondos, grid, copy trading...) del resumen de BingX en USDT (/account/v1/allAccountBalance).
 *  Si una de las dos falla, devuelve lo que haya con parcial: true; si fallan las dos, null. */
async function capital(key, secret) {
  const [fut, todas] = await Promise.all([
    pedir('/openApi/swap/v3/user/balance', {}, key, secret).catch(() => null),
    pedir('/openApi/account/v1/allAccountBalance', {}, key, secret).catch(() => null)]);
  const f = Array.isArray(fut) ? fut.find((x) => x && x.asset === 'USDT') || null : fut && fut.balance ? fut.balance : null;
  let futuros = f ? +f.equity || 0 : null, otras = null;
  const partes = {};
  if (Array.isArray(todas)) {
    otras = 0;
    todas.forEach((a) => {
      const v = +a.usdtBalance || 0;
      if (a.accountType === 'USDTMPerp') { if (futuros === null) futuros = v; return; }   // ya esta (con mas detalle) arriba
      if (v) { partes[a.accountType] = v; otras += v; }
    });
  }
  if (futuros === null && otras === null) return null;
  const r2 = (x) => Math.round(x * 100) / 100;
  return { total: r2((futuros || 0) + (otras || 0)), futuros: futuros === null ? null : r2(futuros), otras: otras === null ? null : r2(otras),
    partes, parcial: !f || otras === null, pnl: f ? r2(+f.unrealizedProfit || 0) : null };
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
  let planError = null;
  const planP = leerPlan().catch((e) => { planError = String(e.message || e).slice(0, 120); return planCache ? planCache[1] : null; });
  try {
    const [pos, ord, plan, cap] = await Promise.all([pedir('/openApi/swap/v2/user/positions', {}, key, secret),
      pedir('/openApi/swap/v2/trade/openOrders', {}, key, secret).catch(() => null), planP, capital(key, secret).catch(() => null)]);
    res.status(200).send(JSON.stringify({ ok: true, hora: Date.now(), posiciones: posiciones(pos), ordenes: ord ? ordenes(ord) : null, capital: cap, plan, plan_error: planError }));
  } catch (e) {
    // BingX fallo: el plan igual va (la contraseña ya se verifico)
    res.status(502).send(JSON.stringify({ ok: false, error: String(e.message || e).slice(0, 200), plan: await planP, plan_error: planError }));
  }
};
module.exports.firmar = firmar;
module.exports.pedir = pedir;
module.exports.capital = capital;
module.exports.claveOk = claveOk;
module.exports.posiciones = posiciones;
module.exports.ordenes = ordenes;
