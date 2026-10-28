/*
 * ¿Se viene un movimiento fuerte? Traduccion de fuerte.py: mismas señales, mismos arboles (modelo_fuerte.json),
 * mismos numeros. "Movimiento fuerte" = en la proxima hora (o 4) BTC se mueve mas del doble de lo habitual.
 */
(function (root) {
  'use strict';
  const H = 3600000;
  const NOMBRES = ['ret1', 'ret2', 'ret4', 'ret8', 'ret12', 'ret24', 'ret48', 'ret72', 'ret168', 'ret336',
    'vol6', 'vol24', 'vol72', 'vol168', 'vol720', 'volratio', 'volratio2', 'rango', 'cuerpo',
    'ema20', 'ema50', 'ema200', 'ema800', 'rsi14', 'rsi56', 'macdh', 'volz', 'vol24_168',
    'pos24', 'dd24', 'pos168', 'dd168', 'pos720', 'dd720', 'hora_s', 'hora_c', 'finde', 'evento_prox', 'evento_ult'];
  const MINIMO = 900;

  function std(xs) {
    let m = 0; for (const x of xs) m += x; m /= xs.length;
    let s = 0; for (const x of xs) s += (x - m) ** 2;
    return Math.sqrt(s / xs.length);
  }
  function emaLast(xs, span) { const a = 2 / (span + 1); let m = xs[0]; for (const x of xs) m = a * x + (1 - a) * m; return m; }
  function emaSeries(xs, span) { const a = 2 / (span + 1); let m = xs[0]; return xs.map((x) => (m = a * x + (1 - a) * m)); }
  function rsiLast(c, p) {
    const a = 1 / p; let up = 0, dn = 0;
    for (let i = 1; i < c.length; i++) {
      const d = c[i] - c[i - 1];
      up = a * (d > 0 ? d : 0) + (1 - a) * up;
      dn = a * (d < 0 ? -d : 0) + (1 - a) * dn;
    }
    return 100 - 100 / (1 + up / Math.max(dn, 1e-12));
  }
  const sum = (xs) => { let s = 0; for (const x of xs) s += x; return s; };

  /** bars: velas de 1 hora cerradas [t, o, h, l, c, v]. eventos: horas (ms UTC) de los datos fuertes de EE.UU. */
  function senales(bars, eventos = []) {
    if (bars.length < MINIMO) return null;
    const t = bars.map((b) => b[0]), o = bars.map((b) => b[1]), h = bars.map((b) => b[2]), l = bars.map((b) => b[3]);
    const c = bars.map((b) => b[4]), v = bars.map((b) => b[5]);
    const n = c.length, i = n - 1;
    const lc = c.map(Math.log);
    const r1 = [0]; for (let k = 1; k < n; k++) r1.push(lc[k] - lc[k - 1]);
    const f = {};
    for (const k of [1, 2, 4, 8, 12, 24, 48, 72, 168, 336]) f[`ret${k}`] = lc[i] - lc[i - k];
    for (const w of [6, 24, 72, 168, 720]) f[`vol${w}`] = std(r1.slice(i - w + 1, i + 1));
    const s = f.vol168;
    f.volratio = f.vol6 / s; f.volratio2 = f.vol24 / f.vol720;
    f.rango = (h[i] - l[i]) / c[i] / s; f.cuerpo = (c[i] - o[i]) / c[i] / s;
    for (const span of [20, 50, 200, 800]) f[`ema${span}`] = (c[i] / emaLast(c, span) - 1) / s;
    f.rsi14 = rsiLast(c, 14); f.rsi56 = rsiLast(c, 56);
    const e12 = emaSeries(c, 12), e26 = emaSeries(c, 26), macd = e12.map((x, k) => x - e26[k]);
    f.macdh = (macd[i] - emaLast(macd, 9)) / c[i] / s;
    const lv = v.slice(i - 167, i + 1).map(Math.log1p);
    f.volz = (lv[lv.length - 1] - sum(lv) / 168) / std(lv);
    f.vol24_168 = (sum(v.slice(i - 23, i + 1)) / 24) / (sum(v.slice(i - 167, i + 1)) / 168);
    for (const w of [24, 168, 720]) {
      let hi = -Infinity, lo = Infinity;
      for (let k = i - w + 1; k <= i; k++) { if (h[k] > hi) hi = h[k]; if (l[k] < lo) lo = l[k]; }
      f[`pos${w}`] = (c[i] - lo) / Math.max(hi - lo, 1e-9); f[`dd${w}`] = c[i] / hi - 1;
    }
    const hr = Math.floor(t[i] / H) % 24;
    f.hora_s = Math.sin(2 * Math.PI * hr / 24); f.hora_c = Math.cos(2 * Math.PI * hr / 24);
    f.finde = ((Math.floor(t[i] / (24 * H)) + 3) % 7) >= 5 ? 1 : 0;
    const cierre = t[i] + H;
    f.evento_prox = eventos.some((e) => cierre <= e && e <= cierre + 4 * H) ? 1 : 0;
    f.evento_ult = eventos.some((e) => cierre - 2 * H <= e && e < cierre) ? 1 : 0;
    return NOMBRES.map((k) => f[k]);
  }

  function arbol(nodo, x) {
    while (Array.isArray(nodo)) nodo = x[nodo[0]] <= nodo[1] ? nodo[2] : nodo[3];
    return nodo;
  }
  function probabilidad(modelo, x) {
    let z = 0; for (const a of modelo.arboles) z += arbol(a, x);
    return 1 / (1 + Math.exp(-z));
  }
  // redondeo igual a Python (round de 1 decimal): lo da indicadores.js
  const r1d = (x) => (root.Ind ? root.Ind.rnd(x * 100, 1) : Math.round(x * 1000) / 10);
  /** Probabilidad (0-100) de movimiento fuerte en la proxima hora y en las proximas 4, o null. */
  function prever(modelo, bars, eventos = []) {
    if (!modelo) return null;
    const x = senales(bars, eventos);
    if (!x) return null;
    return { '1h': r1d(probabilidad(modelo['1h'], x)), '4h': r1d(probabilidad(modelo['4h'], x)), base_1h: modelo['1h'].base, base_4h: modelo['4h'].base };
  }

  const Fuerte = { senales, probabilidad, prever, NOMBRES, MINIMO };
  root.Fuerte = Fuerte;
  if (typeof module !== 'undefined' && module.exports) module.exports = Fuerte;
})(typeof self !== 'undefined' ? self : globalThis);
