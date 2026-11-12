// Prueba del "abanico de caminos" (dashboard/index.html): que solo entren casos realmente parecidos, que no se
// solapen, que con pocos no dibuje y que detecte cuando los parecidos se apartan de lo normal.  node pruebas/abanico.js
const assert = require('assert');
const html = require('fs').readFileSync(require('path').join(__dirname, '../dashboard/index.html'), 'utf8');
const a = html.indexOf('  const ABA = {'), b = html.indexOf('  // se pide al dibujar', a);
const { abaCalcular, ABA_MIN } = new Function(`${html.slice(a, b)}; return { abaCalcular, ABA_MIN };`)();
let semilla = 7; const azar = () => { semilla = (semilla * 16807) % 2147483647; return semilla / 2147483647; };
const normal = () => Math.sqrt(-2 * Math.log(azar() + 1e-12)) * Math.cos(2 * Math.PI * azar());
const H = 24, ms = 36e5;
function serie(n, plantar) {
  const lc = [Math.log(60000)];
  for (let i = 1; i < n; i++) lc.push(lc[i - 1] + normal() * 0.004);
  const forma = Array.from({ length: 36 }, (_, k) => Math.sin(k / 5) * 0.02 + k * 0.0006);      // la forma de "ahora"
  if (plantar) {
    // 12 copias de la forma (con un poco de ruido), cada una seguida de una suba fuerte
    for (let c = 0; c < 12; c++) {
      const ini = 500 + c * 600, base = lc[ini];
      for (let k = 0; k < 36; k++) lc[ini + k] = base + forma[k] + normal() * 0.0005;
      for (let k = 1; k <= H; k++) lc[ini + 35 + k] = lc[ini + 35] + 0.0025 * k + normal() * 0.001;
      for (let i = ini + 36 + H; i < n; i++) lc[i] = lc[i - 1] + normal() * 0.004;
    }
    const base = lc[n - 36]; for (let k = 0; k < 36; k++) lc[n - 36 + k] = base + forma[k];
  }
  return lc.map((l, i) => { const c = Math.exp(l); return [i * ms, c, c * 1.001, c * 0.999, c, 1]; });
}
// 1) camino al azar: casi nunca hay 8 casos tan parecidos
const r1 = abaCalcular(serie(9000, false), H);
assert.ok(r1.casos.length < ABA_MIN, `al azar no deberia alcanzar (${r1.casos.length})`);
// 2) forma plantada 12 veces seguida de suba: los encuentra, son parecidos de verdad y se apartan de lo normal
const r2 = abaCalcular(serie(9000, true), H);
assert.ok(r2.casos.length >= ABA_MIN, `encuentra los plantados (${r2.casos.length})`);
r2.casos.forEach((c) => { assert.ok(c.corr >= 0.94 && c.rm <= 0.25, 'solo casos muy parecidos'); assert.strictEqual(c.camino.length, H); });
const idx = r2.casos.map((c) => c.i).sort((x, y) => x - y);
for (let k = 1; k < idx.length; k++) assert.ok(idx[k] - idx[k - 1] >= H, 'casos sin solaparse');
assert.ok(r2.zSube >= 2 && r2.sube > r2.base.sube, `se aparta hacia arriba (${r2.sube} vs ${r2.base.sube})`);
assert.ok(Math.abs(r2.base.sube - 0.25) < 0.08 && Math.abs(r2.base.baja - 0.25) < 0.08, 'lo normal ronda 25 % y 25 %');
// 3) pocas velas: no calcula
assert.ok(abaCalcular(serie(200, false), H).falta);
console.log(`abanico: todo bien (al azar ${r1.casos.length} casos; plantados ${r2.casos.length}, sube ${Math.round(r2.sube * 100)}% contra ${Math.round(r2.base.sube * 100)}%)`);
