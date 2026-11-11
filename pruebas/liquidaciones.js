// Prueba de /api/liquidaciones con respuestas simuladas de Binance, Bybit y OKX (sin red): node pruebas/liquidaciones.js
// Y del modelo del mapa (simular) con esos datos: que haya cortos arriba y largos abajo, y que lo cruzado se apague.
const assert = require('assert');
const H = 36e5, ahora = Math.floor(Date.now() / H) * H, P = (t) => 70000 + 1500 * Math.sin(t / (36 * H));
let falla = new Set();
global.fetch = async (url) => {
  const u = new URL(url), q = u.searchParams, ok = (j) => ({ ok: true, status: 200, json: async () => j });
  if ([...falla].some((f) => u.host.includes(f))) return { ok: false, status: 403, json: async () => ({}) };
  if (u.pathname === '/fapi/v1/klines') { const fin = +(q.get('endTime') || Date.now()), out = []; for (let t = Math.floor(fin / H) * H - 1499 * H; t <= Math.min(fin, ahora); t += H) out.push([t, P(t), P(t) * 1.004, P(t) * 0.996, P(t + H), 1]); return ok(out); }
  if (u.pathname === '/futures/data/openInterestHist') return ok(Array.from({ length: 500 }, (_, i) => ({ timestamp: ahora - (499 - i) * H, sumOpenInterestValue: 5e9 + i * 2e6 })));
  if (u.pathname === '/futures/data/globalLongShortAccountRatio') return ok(Array.from({ length: 500 }, (_, i) => ({ timestamp: ahora - (499 - i) * H, longAccount: 0.6 })));
  if (u.pathname === '/v5/market/open-interest') { const c = +(q.get('cursor') || 0); return ok({ result: { list: Array.from({ length: 200 }, (_, i) => ({ timestamp: String(ahora - (c * 200 + i) * H), openInterest: String(50000 - (c * 200 + i) * 10) })), nextPageCursor: c < 3 ? String(c + 1) : '' } }); }
  if (u.pathname === '/v5/market/account-ratio') return ok({ result: { list: Array.from({ length: 500 }, (_, i) => ({ timestamp: String(ahora - i * H), buyRatio: '0.55' })) } });
  if (u.pathname === '/api/v5/rubik/stat/contracts/open-interest-volume') return ok({ data: Array.from({ length: 300 }, (_, i) => [String(ahora - i * H), String(3e9 + (300 - i) * 1e6), '0']) });
  if (u.pathname === '/api/v5/public/instruments') return ok({ data: [{ ctVal: '0.01' }] });
  if (u.pathname === '/api/v5/public/liquidation-orders') return ok({ data: [{ details: q.get('after') ? [] : [{ ts: String(ahora - 2 * H), posSide: 'long', bkPx: '69000', sz: '100' }] }] });
  return { ok: false, status: 404, json: async () => ({}) };
};
const api = require('../JavascriptVersion/api/liquidaciones.js');
const llamar = (url) => new Promise((ok) => { const res = { h: {}, setHeader(k, v) { this.h[k] = v; }, status(c) { this.c = c; return this; }, send(b) { ok({ c: this.c, j: JSON.parse(b), h: this.h }); } }; api({ url }, res); });
(async () => {
  let r = await llamar('/api/liquidaciones?moneda=BTC&tf=1h');
  assert.strictEqual(r.c, 200); assert.ok(r.j.ok);
  assert.strictEqual(r.j.velas.length, 736); assert.strictEqual(r.j.fuentes.velas, 'Binance');
  assert.ok(r.j.oi.binance.length === 500 && r.j.oi.bybit.length > 500 && r.j.oi.okx.length === 300, JSON.stringify(r.j.fuentes));
  assert.deepStrictEqual(r.j.liq[0].slice(1), ['l', 69000, 69000]);             // 100 contratos x 0,01 BTC x 69.000
  assert.match(r.h['Cache-Control'], /s-maxage=300/);
  r = await llamar('/api/liquidaciones?moneda=XXX&tf=1h'); assert.strictEqual(r.c, 400);
  falla = new Set(['bybit.com', 'okx.com']);
  r = await llamar('/api/liquidaciones?moneda=BTC&tf=1h');
  assert.ok(r.j.ok && r.j.oi.binance.length && !r.j.oi.bybit.length && r.j.fuentes.errores.length >= 3);
  falla = new Set();
  // el modelo de la pagina, sacado del HTML
  const html = require('fs').readFileSync(require('path').join(__dirname, '../dashboard/index.html'), 'utf8');
  const a = html.indexOf('  const LiqMapa = (function () {'), b = html.indexOf('  })();', a) + 7;
  const LiqMapa = new Function(`${html.slice(a, b)}; return LiqMapa;`)();
  r = await llamar('/api/liquidaciones?moneda=BTC&tf=1h');
  const m = LiqMapa.simular(r.j, 'todo'), ultimo = m.V[m.V.length - 1][4];
  let arriba = 0, abajo = 0, malL = 0, malS = 0;
  for (let k = 0; k < m.NB; k++) { const p = m.precioBin(k); arriba += m.S[k]; abajo += m.L[k]; if (m.L[k] && p > ultimo) malL += m.L[k]; if (m.S[k] && p < ultimo) malS += m.S[k]; }
  assert.ok(arriba > 0 && abajo > 0, 'hay liquidez estimada a los dos lados');
  assert.ok(malL === 0 && malS === 0, 'largos solo abajo del precio y cortos solo arriba');
  const sc = LiqMapa.simular(r.j, 'scalping'), sw = LiqMapa.simular(r.j, 'swing');
  const lejos = (mm) => { let s = 0, w = 0; for (let k = 0; k < mm.NB; k++) { const v = mm.L[k] + mm.S[k]; s += v * Math.abs(mm.precioBin(k) / ultimo - 1); w += v; } return s / w; };
  assert.ok(lejos(sc) < lejos(sw), 'scalping queda mas cerca del precio que swing');
  if (process.argv[2]) require('fs').writeFileSync(process.argv[2], JSON.stringify(r.j));
  console.log(`liquidaciones: todo bien (arriba ${Math.round(arriba / 1e6)} M, abajo ${Math.round(abajo / 1e6)} M)`);
})().catch((e) => { console.error(e); process.exit(1); });
