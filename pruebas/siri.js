// Prueba de /api/siri con velas simuladas (sin red): node pruebas/siri.js
// Corre el analisis entero como en el servidor y revisa que la frase para Siri tenga precio, direccion y nivel.
const assert = require('assert');
const TF = { '5m': 3e5, '15m': 9e5, '30m': 18e5, '1h': 36e5, '4h': 144e5, '1d': 864e5 };
const LIST = Date.UTC(2019, 8, 8);
const f = (t) => { const d = (t - LIST) / 864e5; let x = 0; for (let k = 1; k <= 14; k++) x += Math.sin(d / (0.02 * Math.pow(2.3, k)) + k * 1.7) * Math.pow(1.45, k) * 0.004; return 40000 * Math.exp(0.25 * x + d * 0.00022); };
let pedidos = 0;
global.fetch = async (url) => {
  pedidos++;
  const u = new URL(String(url));
  if (!/fapi\/v1\/klines/.test(u.pathname)) return { ok: false, status: 404, json: async () => ({}), text: async () => '' };
  const ms = TF[u.searchParams.get('interval')] || 36e5, lim = +u.searchParams.get('limit') || 500;
  let t = Math.max(Math.ceil((+u.searchParams.get('startTime') || Date.now() - lim * ms) / ms) * ms, Math.ceil(LIST / ms) * ms); const out = [];
  for (; t < Date.now() && out.length < lim; t += ms) { const o = f(t), c = f(t + ms), a = Math.abs(Math.sin(t / 7e5)) * 0.002; out.push([t, `${o}`, `${Math.max(o, c) * (1 + a)}`, `${Math.min(o, c) * (1 - a)}`, `${c}`, '120', t + ms - 1, '1', 1, '1', '1', '0']); }
  return { ok: true, status: 200, headers: { get: () => null }, json: async () => out, text: async () => JSON.stringify(out) };
};
const siri = require('../JavascriptVersion/api/siri.js');
const llamar = (url) => new Promise((ok) => {
  const res = { h: {}, setHeader(k, v) { this.h[k] = v; }, status(c) { this.c = c; return this; }, send(b) { ok({ c: this.c, b, h: this.h }); } };
  siri({ url, headers: { host: 'ejemplo.vercel.app' } }, res);
});
(async () => {
  const t0 = Date.now();
  const r = await llamar('/api/siri');
  const ms = Date.now() - t0;
  console.log(r.b); console.log(`${ms} ms, ${pedidos} pedidos`);
  assert.strictEqual(r.c, 200);
  assert.match(r.b, /^Bitcoin está en [\d.]+ dólares, (sube|baja) [\d,]+ por ciento en 24 horas\./);
  assert.match(r.b, /Para la próxima hora, la app (ve más probable que (suba|baje)|no ve una dirección clara: neutral)\./);
  assert.match(r.b, /(El soporte más cercano|La resistencia más cercana) está en [\d.]+, a [\d,]+ por ciento\./);
  assert.match(r.h['Cache-Control'], /s-maxage=60/);
  // la segunda vez, con las velas en memoria, solo pide lo nuevo
  const p1 = pedidos, t1 = Date.now(); await llamar('/api/siri'); console.log(`segunda: ${Date.now() - t1} ms, ${pedidos - p1} pedidos`);
  assert.ok(pedidos - p1 < p1 / 2);
  // frases con filas armadas a mano
  const fr = siri.frases([{ tabla: 'resumen', precio: 70647, cambio_24h: -1.14 }, { tabla: 'central', plazo: '1 hora', direccion: 'neutral', soporte: 69665, resistencia: 71307 }]);
  assert.strictEqual(fr, 'Bitcoin está en 70.647 dólares, baja 1,1 por ciento en 24 horas. Para la próxima hora, la app no ve una dirección clara: neutral. La resistencia más cercana está en 71.307, a 0,9 por ciento.');
  console.log('Siri: bien');
})().catch((e) => { console.error(e); process.exit(1); });
