// Prueba de /api/widget y del capital de /api/posiciones con BingX simulado (sin red): node pruebas/widget_api.js
const assert = require('assert');
process.env.BINGX_API_KEY = 'k'; process.env.BINGX_API_SECRET = 's'; process.env.POSICIONES_CLAVE = 'clave-de-prueba';
let falla = new Set();
const RESP = {
  '/openApi/swap/v2/user/positions': [
    { symbol: 'BTC-USDT', positionAmt: '0.0808', positionSide: 'LONG', avgPrice: '77241', margin: '2807', leverage: 5, unrealizedProfit: '1450.5' },
    { symbol: 'XRP-USDT', positionAmt: '2377', positionSide: 'LONG', avgPrice: '1.2027', margin: '1807', leverage: 5, unrealizedProfit: '-120.25' }],
  '/openApi/swap/v3/user/balance': [{ asset: 'USDT', balance: '6000', equity: '7330.25', unrealizedProfit: '1330.25' }],
  '/openApi/account/v1/allAccountBalance': [{ accountType: 'sopt', usdtBalance: '2500.5' }, { accountType: 'USDTMPerp', usdtBalance: '7300' }, { accountType: 'grid', usdtBalance: '0' }],
  '/openApi/swap/v2/trade/openOrders': { orders: [] },
};
global.fetch = async (url) => {
  const path = new URL(url).pathname;
  if (falla.has(path)) return { json: async () => ({ code: 100001, msg: 'sin permiso' }) };
  return { json: async () => ({ code: 0, data: RESP[path] }) };
};
const llamar = async (fn, clave) => new Promise((ok) => {
  const res = { h: {}, setHeader(k, v) { this.h[k] = v; }, status(c) { this.c = c; return this; }, send(b) { ok({ c: this.c, j: JSON.parse(b), h: this.h }); } };
  fn({ headers: { 'x-clave': clave } }, res);
});
(async () => {
  const widget = require('../JavascriptVersion/api/widget.js'), pos = require('../JavascriptVersion/api/posiciones.js');
  let r = await llamar(widget, 'mal');
  assert.strictEqual(r.c, 401); assert.strictEqual(r.j.capital, undefined);
  r = await llamar(widget, 'clave-de-prueba');
  assert.strictEqual(r.c, 200); assert.strictEqual(r.h['Cache-Control'], 'no-store, private');
  assert.strictEqual(r.j.capital, 9830.75, 'capital = patrimonio de futuros + otras cuentas (sin contar dos veces futuros)');
  assert.strictEqual(r.j.pnl, 1330.25); assert.strictEqual(r.j.margen, 4614); assert.strictEqual(r.j.parcial, false);
  assert.deepStrictEqual(r.j.por, [['BTC', 1450.5], ['XRP', -120.25]]);
  falla = new Set(['/openApi/account/v1/allAccountBalance']);
  r = await llamar(widget, 'clave-de-prueba');
  assert.strictEqual(r.j.capital, 7330.25); assert.strictEqual(r.j.parcial, true);
  falla = new Set(['/openApi/swap/v3/user/balance']);
  r = await llamar(widget, 'clave-de-prueba');
  assert.strictEqual(r.j.capital, 9800.5, 'sin el detalle de futuros, usa el del resumen'); assert.strictEqual(r.j.parcial, true);
  falla = new Set(['/openApi/swap/v2/user/positions']);
  r = await llamar(widget, 'clave-de-prueba');
  assert.strictEqual(r.c, 502); assert.strictEqual(r.j.ok, false);
  falla = new Set();
  r = await llamar(pos, 'clave-de-prueba');
  assert.strictEqual(r.c, 200); assert.strictEqual(r.j.capital.total, 9830.75); assert.ok(r.j.posiciones.BTC);
  // simbolos de acciones de BingX -> activo de la app (MSTR)
  const ps = pos.posiciones([{ symbol: 'NCSKMSTR2USD-USDT', positionAmt: '2', avgPrice: '300' }, { symbol: 'MSTR-USDT', positionAmt: '-1', avgPrice: '1' },
    { symbol: '1000PEPE-USDT', positionAmt: '1', avgPrice: '1' }]);
  assert.deepStrictEqual(Object.keys(ps).sort(), ['1000PEPE', 'MSTR']);
  console.log('widget_api: todo bien');
})().catch((e) => { console.error(e); process.exit(1); });
