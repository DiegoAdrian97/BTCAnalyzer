/*
 * Indicadores tecnicos (los de TradingView / Binance / BingX) sobre listas de velas.
 * Traduccion directa de indicadores.py: mismas formulas y mismas reglas.
 *
 * Cada funcion recibe listas alineadas (open, high, low, close, volume) y devuelve listas del mismo
 * largo, con null mientras no hay datos suficientes. Una vela es [t, o, h, l, c, v].
 *
 * calificar(bars) arma el resumen tipo "Technical Ratings" de TradingView: cada media movil y cada
 * oscilador vota compra / venta / neutral con las reglas de TradingView, y se suman los votos.
 */
(function (root) {
  'use strict';

  // ---------- utilidades (con el mismo redondeo que Python) ----------
  /**
   * Redondeo a d decimales como Python: sobre el valor binario exacto y, en un empate exacto (62,5),
   * hacia el par. toFixed de JavaScript desempata siempre hacia arriba.
   */
  function fixedLikePython(x, d) {
    const exact = Math.abs(x).toFixed(Math.min(100, d + 30));    // los digitos exactos del valor binario
    const [ip, fp] = exact.split('.');
    if (/^50*$/.test(fp.slice(d)) && Number((ip + fp.slice(0, d)).slice(-1)) % 2 === 0) {
      return (x < 0 ? '-' : '') + ip + (d ? '.' + fp.slice(0, d) : '');   // empate exacto con par: se queda
    }
    return x.toFixed(d);
  }
  /** Numero con formato argentino: 80.757,25 */
  function ar(x, d = 0) {
    const s = fixedLikePython(Math.abs(x), d);
    const [int, dec] = s.split('.');
    return (x < 0 ? '-' : '') + int.replace(/\B(?=(\d{3})+(?!\d))/g, '.') + (dec !== undefined ? ',' + dec : '');
  }
  /** round(x, n) de Python para n >= 0. */
  const rnd = (x, n = 0) => (x === null || x === undefined ? null : Number(fixedLikePython(x, n)));
  /** round(x) de Python: los empates van al par. */
  function roundEven(x) {
    const r = Math.round(x);
    return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
  }
  const sum = (a) => a.reduce((s, x) => s + x, 0);
  const col = (bars, k) => bars.map((b) => b[k]);
  const firstIndex = (v) => { const i = v.findIndex((x) => x !== null); return i < 0 ? v.length : i; };
  const nulls = (n) => new Array(n).fill(null);

  // ---------- medias ----------
  function sma(v, n) {
    const out = nulls(v.length);
    let acc = 0;
    for (let i = 0; i < v.length; i++) {
      acc += v[i];
      if (i >= n) acc -= v[i - n];
      if (i >= n - 1) out[i] = acc / n;
    }
    return out;
  }

  function ema(v, n) {
    const out = nulls(v.length), k = 2 / (n + 1);
    let e = null;
    for (let i = 0; i < v.length; i++) {
      const x = v[i];
      if (x === null) continue;
      e = e === null ? x : x * k + e * (1 - k);
      out[i] = e;
    }
    return out;
  }

  /** Media de Wilder (la que usan RSI, ATR y ADX). */
  function rma(v, n) {
    const out = nulls(v.length);
    let a = null;
    for (let i = 0; i < v.length; i++) {
      const x = v[i];
      if (x === null) continue;
      a = a === null ? x : (a * (n - 1) + x) / n;
      out[i] = a;
    }
    return out;
  }

  function wma(v, n) {
    const out = nulls(v.length), w = (n * (n + 1)) / 2;
    for (let i = n - 1; i < v.length; i++) {
      const win = v.slice(i - n + 1, i + 1);
      if (win.includes(null)) continue;
      let s = 0;
      win.forEach((x, j) => { s += x * (j + 1); });
      out[i] = s / w;
    }
    return out;
  }

  function wmaSkip(v, n) {
    const first = firstIndex(v);
    return nulls(first).concat(wma(v.slice(first), n));
  }

  function hma(v, n) {
    const a = wma(v, Math.floor(n / 2)), b = wma(v, n);
    const diff = a.map((x, i) => (x === null || b[i] === null ? null : 2 * x - b[i]));
    return wmaSkip(diff, Math.floor(Math.sqrt(n)));
  }

  function vwma(c, vol, n) {
    const out = nulls(c.length);
    for (let i = n - 1; i < c.length; i++) {
      let vs = 0, pv = 0;
      for (let j = i - n + 1; j <= i; j++) { vs += vol[j]; pv += c[j] * vol[j]; }
      out[i] = vs ? pv / vs : c[i];
    }
    return out;
  }

  function rolling(v, n, fn) {
    return v.map((_, i) => (i < n - 1 ? null : fn(v.slice(i - n + 1, i + 1))));
  }
  const maxOf = (a) => Math.max(...a);
  const minOf = (a) => Math.min(...a);

  function smaSkip(v, n) {
    const first = firstIndex(v);
    return nulls(first).concat(sma(v.slice(first), n));
  }

  // ---------- osciladores ----------
  function rsi(c, n = 14) {
    const up = [null], dn = [null];
    for (let i = 1; i < c.length; i++) { up.push(Math.max(c[i] - c[i - 1], 0)); dn.push(Math.max(c[i - 1] - c[i], 0)); }
    const au = rma(up, n), ad = rma(dn, n);
    return au.map((u, i) => (u === null ? null : ad[i] === 0 ? 100 : 100 - 100 / (1 + u / ad[i])));
  }

  function stoch(h, l, c, n = 14, smooth = 3, d = 3) {
    const hh = rolling(h, n, maxOf), ll = rolling(l, n, minOf);
    const raw = c.map((x, i) => (hh[i] === null ? null : hh[i] === ll[i] ? 50 : ((x - ll[i]) / (hh[i] - ll[i])) * 100));
    const k = smaSkip(raw, smooth);
    return [k, smaSkip(k, d)];
  }

  function stochRsi(c, nRsi = 14, nSt = 14, k = 3, d = 3) {
    const r = rsi(c, nRsi);
    const first = firstIndex(r);
    const rr = r.slice(first);
    const [kk, dd] = stoch(rr, rr, rr, nSt, k, d);
    return [nulls(first).concat(kk), nulls(first).concat(dd)];
  }

  function cci(h, l, c, n = 20) {
    const tp = c.map((x, i) => (h[i] + l[i] + x) / 3);
    const m = sma(tp, n);
    const out = nulls(c.length);
    for (let i = n - 1; i < c.length; i++) {
      let md = 0;
      for (let j = i - n + 1; j <= i; j++) md += Math.abs(tp[j] - m[i]);
      md /= n;
      out[i] = md === 0 ? 0 : (tp[i] - m[i]) / (0.015 * md);
    }
    return out;
  }

  function williamsR(h, l, c, n = 14) {
    const hh = rolling(h, n, maxOf), ll = rolling(l, n, minOf);
    return c.map((x, i) => (hh[i] === null ? null : hh[i] === ll[i] ? -50 : ((hh[i] - x) / (hh[i] - ll[i])) * -100));
  }

  function momentum(c, n = 10) {
    return c.map((x, i) => (i < n ? null : x - c[i - n]));
  }

  function macd(c, fast = 12, slow = 26, sig = 9) {
    const ef = ema(c, fast), es = ema(c, slow);
    const line = ef.map((a, i) => a - es[i]);
    const signal = ema(line, sig);
    return [line, signal, line.map((a, i) => a - signal[i])];
  }

  function awesome(h, l) {
    const hl2 = h.map((a, i) => (a + l[i]) / 2);
    const a = sma(hl2, 5), b = sma(hl2, 34);
    return a.map((x, i) => (x === null || b[i] === null ? null : x - b[i]));
  }

  function bullBearPower(h, l, c, n = 13) {
    const e = ema(c, n);
    return h.map((a, i) => a - e[i] + l[i] - e[i]);
  }

  function ultimate(h, l, c, a = 7, b = 14, d = 28) {
    const bp = [0], tr = [0];
    for (let i = 1; i < c.length; i++) {
      const lo = Math.min(l[i], c[i - 1]), hi = Math.max(h[i], c[i - 1]);
      bp.push(c[i] - lo);
      tr.push(hi - lo);
    }
    const out = nulls(c.length);
    for (let i = d; i < c.length; i++) {
      const avg = (n) => sum(bp.slice(i - n + 1, i + 1)) / (sum(tr.slice(i - n + 1, i + 1)) || 1);
      out[i] = (100 * (4 * avg(a) + 2 * avg(b) + avg(d))) / 7;
    }
    return out;
  }

  /** ADX, +DI, -DI y ATR de Wilder. */
  function dmi(h, l, c, n = 14) {
    const tr = [null], pdm = [null], mdm = [null];
    for (let i = 1; i < c.length; i++) {
      const up = h[i] - h[i - 1], dn = l[i - 1] - l[i];
      tr.push(Math.max(h[i] - l[i], Math.abs(h[i] - c[i - 1]), Math.abs(l[i] - c[i - 1])));
      pdm.push(up > dn && up > 0 ? up : 0);
      mdm.push(dn > up && dn > 0 ? dn : 0);
    }
    const atr = rma(tr, n), ap = rma(pdm, n), am = rma(mdm, n);
    const pdi = ap.map((p, i) => (!atr[i] ? null : (100 * p) / atr[i]));
    const mdi = am.map((m, i) => (!atr[i] ? null : (100 * m) / atr[i]));
    const dx = pdi.map((p, i) => (p === null ? null : p + mdi[i] === 0 ? 0 : (100 * Math.abs(p - mdi[i])) / (p + mdi[i])));
    return [rma(dx, n), pdi, mdi, atr];
  }

  function mfi(h, l, c, vol, n = 14) {
    const tp = c.map((x, i) => (h[i] + l[i] + x) / 3);
    const out = nulls(c.length);
    for (let i = n; i < c.length; i++) {
      let pos = 0, neg = 0;
      for (let j = i - n + 1; j <= i; j++) {
        if (tp[j] > tp[j - 1]) pos += tp[j] * vol[j];
        else if (tp[j] < tp[j - 1]) neg += tp[j] * vol[j];
      }
      out[i] = neg === 0 ? 100 : 100 - 100 / (1 + pos / neg);
    }
    return out;
  }

  function cmf(h, l, c, vol, n = 20) {
    const mfv = c.map((x, i) => (h[i] === l[i] ? 0 : ((x - l[i] - (h[i] - x)) / (h[i] - l[i])) * vol[i]));
    const out = nulls(c.length);
    for (let i = n - 1; i < c.length; i++) {
      const vs = sum(vol.slice(i - n + 1, i + 1));
      out[i] = vs ? sum(mfv.slice(i - n + 1, i + 1)) / vs : 0;
    }
    return out;
  }

  function obv(c, vol) {
    const out = [0];
    let acc = 0;
    for (let i = 1; i < c.length; i++) {
      acc += c[i] > c[i - 1] ? vol[i] : c[i] < c[i - 1] ? -vol[i] : 0;
      out.push(acc);
    }
    return out;
  }

  // ---------- volatilidad / bandas ----------
  function bollinger(c, n = 20, k = 2) {
    const mid = sma(c, n);
    const up = nulls(c.length), lo = nulls(c.length);
    for (let i = n - 1; i < c.length; i++) {
      let s = 0;
      for (let j = i - n + 1; j <= i; j++) s += (c[j] - mid[i]) ** 2;
      const sd = Math.sqrt(s / n);
      up[i] = mid[i] + k * sd;
      lo[i] = mid[i] - k * sd;
    }
    return [mid, up, lo];
  }

  function keltner(h, l, c, n = 20, k = 2) {
    const mid = ema(c, n);
    const a = dmi(h, l, c, 10)[3];
    return [mid, mid.map((m, i) => (a[i] === null ? null : m + k * a[i])), mid.map((m, i) => (a[i] === null ? null : m - k * a[i]))];
  }

  function psar(h, l, step = 0.02, mx = 0.2) {
    const out = nulls(h.length);
    if (h.length < 2) return out;
    let up = h[1] > h[0], af = step;
    let sar = up ? l[0] : h[0], ep = up ? h[0] : l[0];
    for (let i = 1; i < h.length; i++) {
      sar = sar + af * (ep - sar);
      if (up) {
        sar = Math.min(sar, l[i - 1], i > 1 ? l[i - 2] : l[i - 1]);
        if (l[i] < sar) { up = false; sar = ep; ep = l[i]; af = step; }
        else if (h[i] > ep) { ep = h[i]; af = Math.min(af + step, mx); }
      } else {
        sar = Math.max(sar, h[i - 1], i > 1 ? h[i - 2] : h[i - 1]);
        if (h[i] > sar) { up = true; sar = ep; ep = h[i]; af = step; }
        else if (l[i] < ep) { ep = l[i]; af = Math.min(af + step, mx); }
      }
      out[i] = sar;
    }
    return out;
  }

  function supertrend(h, l, c, n = 10, k = 3) {
    const a = dmi(h, l, c, n)[3];
    const line = nulls(c.length), direction = nulls(c.length);
    let fu = null, fl = null, trend = 1;
    for (let i = 0; i < c.length; i++) {
      if (a[i] === null) continue;
      const prev = c[i - 1 >= 0 ? i - 1 : c.length - 1];      // como c[i - 1] en Python
      const hl2 = (h[i] + l[i]) / 2, bu = hl2 + k * a[i], bl = hl2 - k * a[i];
      fu = fu === null || bu < fu || prev > fu ? bu : fu;
      fl = fl === null || bl > fl || prev < fl ? bl : fl;
      if (trend === 1 && c[i] < fl) trend = -1;
      else if (trend === -1 && c[i] > fu) trend = 1;
      line[i] = trend === 1 ? fl : fu;
      direction[i] = trend;
    }
    return [line, direction];
  }

  function ichimoku(h, l, tenkan = 9, kijun = 26, senkou = 52) {
    const mid = (n) => h.map((_, i) => (i < n - 1 ? null : (maxOf(h.slice(i - n + 1, i + 1)) + minOf(l.slice(i - n + 1, i + 1))) / 2));
    const t = mid(tenkan), k = mid(kijun), sb = mid(senkou);
    const sa = t.map((a, i) => (a === null || k[i] === null ? null : (a + k[i]) / 2));
    // la nube que se ve HOY se calculo hace 26 velas
    const shift = (v) => (v.length > kijun ? nulls(kijun).concat(v.slice(0, v.length - kijun)) : nulls(v.length));
    return [t, k, shift(sa), shift(sb)];
  }

  function vwapSession(ts, h, l, c, vol, dayMs = 86400000) {
    const out = [];
    let pv = 0, vv = 0, day = null;
    ts.forEach((t, i) => {
      if (Math.floor(t / dayMs) !== day) { pv = 0; vv = 0; day = Math.floor(t / dayMs); }
      pv += ((h[i] + l[i] + c[i]) / 3) * vol[i];
      vv += vol[i];
      out.push(vv ? pv / vv : c[i]);
    });
    return out;
  }

  // ---------- calificacion tipo TradingView ----------
  const COMPRA = 'compra', VENTA = 'venta', NEUTRAL = 'neutral';
  const rising = (v, i) => v[i] !== null && v[i - 1] !== null && v[i] > v[i - 1];

  function ratingTxt(x) {
    // TradingView dice "compra/venta"; aca "alcista/bajista" para que no se lea como una orden
    return x <= -0.5 ? 'Bajista fuerte' : x < -0.1 ? 'Bajista' : x <= 0.1 ? 'Neutral' : x < 0.5 ? 'Alcista' : 'Alcista fuerte';
  }

  /** Divergencia simple: el precio hace un extremo nuevo y el RSI no lo confirma. */
  function divergencia(c, r, i, n = 30) {
    if (i < n || r[i - n] === null) return null;
    const winC = c.slice(i - n, i - 3), winR = r.slice(i - n, i - 3);
    if (c[i] > maxOf(winC) && r[i] < maxOf(winR)) return 'bajista';
    if (c[i] < minOf(winC) && r[i] > minOf(winR)) return 'alcista';
    return null;
  }

  /** Filas de indicadores, resumen y lineas para el grafico, para la ultima vela de bars. */
  function calificar(bars) {
    const ts = col(bars, 0), h = col(bars, 2), l = col(bars, 3), c = col(bars, 4), vol = col(bars, 5);
    const i = c.length - 1, px = c[i];
    const rows = [];
    const add = (group, name, value, signal, detail = '', rated = true) =>
      rows.push({ grupo: group, indicador: name, valor: value === null || value === undefined ? null : rnd(value, 2),
        senal: signal, detalle: detail, vota: rated });

    // medias moviles: precio encima = compra
    [['EMA', ema], ['SMA', sma]].forEach(([kind, fn]) => {
      [10, 20, 30, 50, 100, 200].forEach((n) => {
        const m = fn(c, n)[i];
        add('Medias móviles', `${kind} ${n}`, m, m === null ? NEUTRAL : px > m ? COMPRA : VENTA);
      });
    });
    const [t, k, sa, sb] = ichimoku(h, l);
    const base = k[i];
    add('Medias móviles', 'Ichimoku línea base (26)', base,
      base === null ? NEUTRAL : px > base && t[i] > base ? COMPRA : px < base && t[i] < base ? VENTA : NEUTRAL);
    const vw = vwma(c, vol, 20)[i];
    add('Medias móviles', 'VWMA 20', vw, px > vw ? COMPRA : VENTA);
    const hm = hma(c, 9)[i];
    add('Medias móviles', 'Hull MA 9', hm, hm === null ? NEUTRAL : px > hm ? COMPRA : VENTA);

    // osciladores, con las reglas de TradingView
    const r = rsi(c);
    add('Osciladores', 'RSI 14', r[i], r[i] < 30 && rising(r, i) ? COMPRA : r[i] > 70 && !rising(r, i) ? VENTA : NEUTRAL,
      r[i] < 30 ? 'sobreventa' : r[i] > 70 ? 'sobrecompra' : 'zona media');
    const [sk, sd] = stoch(h, l, c);
    add('Osciladores', 'Estocástico %K (14,3,3)', sk[i], sk[i] < 20 && sk[i] > sd[i] ? COMPRA : sk[i] > 80 && sk[i] < sd[i] ? VENTA : NEUTRAL);
    const cc = cci(h, l, c);
    add('Osciladores', 'CCI 20', cc[i], cc[i] < -100 && rising(cc, i) ? COMPRA : cc[i] > 100 && !rising(cc, i) ? VENTA : NEUTRAL);
    const [adx, pdi, mdi, atr] = dmi(h, l, c);
    add('Osciladores', 'ADX 14', adx[i],
      adx[i] > 20 && pdi[i] > mdi[i] && rising(adx, i) ? COMPRA : adx[i] > 20 && pdi[i] < mdi[i] && rising(adx, i) ? VENTA : NEUTRAL,
      `+DI ${pdi[i].toFixed(0)} / -DI ${mdi[i].toFixed(0)}` + (adx[i] > 25 ? ' (tendencia)' : ' (lateral)'));
    const ao = awesome(h, l);
    add('Osciladores', 'Awesome Oscillator', ao[i], ao[i] > 0 && rising(ao, i) ? COMPRA : ao[i] < 0 && !rising(ao, i) ? VENTA : NEUTRAL);
    const mo = momentum(c);
    add('Osciladores', 'Momentum 10', mo[i], rising(mo, i) ? COMPRA : VENTA);
    const [ml, ms, mh] = macd(c);
    add('Osciladores', 'MACD (12,26)', ml[i], ml[i] > ms[i] ? COMPRA : VENTA, `histograma ${mh[i] > mh[i - 1] ? 'subiendo' : 'bajando'}`);
    const [srk, srd] = stochRsi(c);
    add('Osciladores', 'Stoch RSI (3,3,14,14)', srk[i],
      srk[i] !== null && srk[i] < 20 && srk[i] > srd[i] ? COMPRA : srk[i] !== null && srk[i] > 80 && srk[i] < srd[i] ? VENTA : NEUTRAL);
    const wr = williamsR(h, l, c);
    add('Osciladores', 'Williams %R 14', wr[i], wr[i] < -80 && rising(wr, i) ? COMPRA : wr[i] > -20 && !rising(wr, i) ? VENTA : NEUTRAL);
    const bbp = bullBearPower(h, l, c);
    add('Osciladores', 'Bull Bear Power', bbp[i], bbp[i] > 0 && rising(bbp, i) ? COMPRA : bbp[i] < 0 && !rising(bbp, i) ? VENTA : NEUTRAL);
    const uo = ultimate(h, l, c);
    add('Osciladores', 'Ultimate Oscillator', uo[i], uo[i] > 70 ? COMPRA : uo[i] < 30 ? VENTA : NEUTRAL);

    // informativos (no votan): tendencia, volatilidad y volumen
    const [mid, up, lo] = bollinger(c);
    const pb = up[i] !== lo[i] ? ((px - lo[i]) / (up[i] - lo[i])) * 100 : 50;
    add('Volatilidad', 'Bandas de Bollinger %B', pb, pb > 100 ? VENTA : pb < 0 ? COMPRA : NEUTRAL,
      `ancho ${ar(((up[i] - lo[i]) / mid[i]) * 100, 2)}% del precio`, false);
    const [km, ku, kl] = keltner(h, l, c);
    add('Volatilidad', 'Canal de Keltner', km[i], px > ku[i] ? COMPRA : px < kl[i] ? VENTA : NEUTRAL,
      px > ku[i] || px < kl[i] ? 'fuera del canal' : 'dentro del canal', false);
    add('Volatilidad', 'ATR 14', atr[i], NEUTRAL, `${ar((atr[i] / px) * 100, 2)}% del precio por vela`, false);
    const dh = maxOf(h.slice(i - 19, i + 1)), dl = minOf(l.slice(i - 19, i + 1));
    add('Volatilidad', 'Donchian 20', (dh + dl) / 2, px >= dh ? COMPRA : px <= dl ? VENTA : NEUTRAL, `${ar(dl)} - ${ar(dh)}`, false);
    const sar = psar(h, l);
    add('Tendencia', 'Parabolic SAR', sar[i], px > sar[i] ? COMPRA : VENTA, px > sar[i] ? 'puntos debajo del precio' : 'puntos encima del precio', false);
    const [st, sdir] = supertrend(h, l, c);
    add('Tendencia', 'SuperTrend (10,3)', st[i], sdir[i] === 1 ? COMPRA : VENTA, '', false);
    const a1 = sa[i] || px, b1 = sb[i] || px;
    const cloudTop = Math.max(a1, b1), cloudBot = Math.min(a1, b1);
    add('Tendencia', 'Nube de Ichimoku', (cloudTop + cloudBot) / 2, px > cloudTop ? COMPRA : px < cloudBot ? VENTA : NEUTRAL,
      px > cloudTop ? 'precio encima de la nube' : px < cloudBot ? 'precio debajo de la nube' : 'precio dentro de la nube', false);
    const vwS = vwapSession(ts, h, l, c, vol)[i];
    add('Volumen', 'VWAP del dia', vwS, px > vwS ? COMPRA : VENTA,
      px > vwS ? 'precio sobre el promedio ponderado del día' : 'precio bajo el promedio ponderado del día', false);
    const ob = obv(c, vol), obEma = ema(ob, 20);
    add('Volumen', 'OBV', ob[i], ob[i] > obEma[i] ? COMPRA : VENTA,
      (ob[i] > obEma[i]) === (px > c[i - 20]) ? 'volumen acompaña' : 'volumen no acompaña', false);
    const mf = mfi(h, l, c, vol);
    add('Volumen', 'MFI 14', mf[i], mf[i] < 20 ? COMPRA : mf[i] > 80 ? VENTA : NEUTRAL, '', false);
    const cm = cmf(h, l, c, vol);
    add('Volumen', 'Chaikin Money Flow 20', cm[i], cm[i] > 0.05 ? COMPRA : cm[i] < -0.05 ? VENTA : NEUTRAL,
      cm[i] > 0 ? 'entra dinero' : 'sale dinero', false);
    const vrel = vol[i] / (sum(vol.slice(i - 20, i)) / 20 || 1);
    add('Volumen', 'Volumen relativo', vrel, NEUTRAL, `x${ar(vrel, 1)} del promedio de 20 velas`, false);
    const div = divergencia(c, r, i);
    if (div) add('Osciladores', 'Divergencia RSI', null, div === 'alcista' ? COMPRA : VENTA, `divergencia ${div} en las últimas 30 velas`, false);

    const score = (group) => {
      const g = rows.filter((x) => x.grupo === group && x.vota);
      const b = g.filter((x) => x.senal === COMPRA).length, s = g.filter((x) => x.senal === VENTA).length;
      return [(b - s) / g.length, b, s, g.length - b - s];
    };
    const ma = score('Medias móviles'), osc = score('Osciladores');
    const total = (ma[0] + osc[0]) / 2;
    const resumen = {
      rating: rnd(total, 3), rating_txt: ratingTxt(total),
      ma_rating: rnd(ma[0], 3), ma_compra: ma[1], ma_venta: ma[2], ma_neutral: ma[3],
      osc_rating: rnd(osc[0], 3), osc_compra: osc[1], osc_venta: osc[2], osc_neutral: osc[3],
      rsi: rnd(r[i], 1), adx: rnd(adx[i], 1), atr_pct: rnd((atr[i] / px) * 100, 3),
      vol_rel: rnd(vrel, 2), macd_sube: mh[i] > mh[i - 1],
    };
    const overlays = { ema20: ema(c, 20), ema50: ema(c, 50), bb_up: up, bb_lo: lo };
    return [rows, resumen, overlays];
  }

  /** Fair Value Gaps sin llenar: hueco entre la vela k-2 y la k que la vela k-1 dejo sin operar. */
  function fvg(bars, lookback = 200, keep = 6) {
    const h = col(bars, 2), l = col(bars, 3);
    const px = bars[bars.length - 1][4], start = Math.max(2, bars.length - lookback);
    const zones = [];
    for (let k = start; k < bars.length; k++) {
      if (l[k] > h[k - 2]) zones.push({ tipo: 'alcista', t: bars[k - 1][0], bajo: h[k - 2], alto: l[k], k });
      else if (h[k] < l[k - 2]) zones.push({ tipo: 'bajista', t: bars[k - 1][0], bajo: h[k], alto: l[k - 2], k });
    }
    const open = [];
    zones.forEach((z) => {
      const later = [];
      for (let j = z.k + 1; j < bars.length; j++) later.push(j);
      if (z.tipo === 'alcista') {
        const low = later.length ? Math.min(...later.map((j) => l[j])) : z.alto;
        if (low <= z.bajo) return;                       // el precio ya volvio y lleno el hueco
        z.alto = Math.min(z.alto, low);                  // parte ya cubierta
      } else {
        const high = later.length ? Math.max(...later.map((j) => h[j])) : z.bajo;
        if (high >= z.alto) return;
        z.bajo = Math.max(z.bajo, high);
      }
      if (z.alto > z.bajo) open.push(z);
    });
    open.sort((a, b) => Math.abs((a.alto + a.bajo) / 2 - px) - Math.abs((b.alto + b.bajo) / 2 - px));
    return open.slice(0, keep).map((z) => ({ tipo: z.tipo, t: z.t, bajo: z.bajo, alto: z.alto }));
  }

  /** Giros del precio: un nuevo pivote cuando se revierte mas de atrMult * ATR desde el ultimo extremo. */
  function zigzag(bars, atrMult = 2.5) {
    const h = col(bars, 2), l = col(bars, 3), c = col(bars, 4);
    const atr = dmi(h, l, c)[3];
    const pivots = [];
    let direction = 0, ext = 0, hiI = 0, loI = 0;
    for (let i = 1; i < bars.length; i++) {
      const a = atr[i] || h[i] - l[i];
      if (direction === 0) {                             // todavia sin tendencia: esperar el primer movimiento grande
        if (h[i] > h[hiI]) hiI = i;
        if (l[i] < l[loI]) loI = i;
        if (h[hiI] - l[loI] > atrMult * a) {
          if (hiI > loI) { pivots.push(['bajo', loI, l[loI]]); direction = 1; ext = hiI; }
          else { pivots.push(['alto', hiI, h[hiI]]); direction = -1; ext = loI; }
        }
      } else if (direction === 1) {
        if (h[i] >= h[ext]) ext = i;
        else if (h[ext] - l[i] > atrMult * a) { pivots.push(['alto', ext, h[ext]]); direction = -1; ext = i; }
      } else if (l[i] <= l[ext]) ext = i;
      else if (h[i] - l[ext] > atrMult * a) { pivots.push(['bajo', ext, l[ext]]); direction = 1; ext = i; }
    }
    // el extremo del tramo en curso, todavia sin confirmar
    if (direction) pivots.push([direction === 1 ? 'alto' : 'bajo', ext, direction === 1 ? h[ext] : l[ext]]);
    return pivots;
  }

  const SIGUE = { 1: '2', 2: '3', 3: '4', 4: '5', 5: 'A', A: 'B', B: 'C', C: '1' };
  const SIN_ELLIOTT = 'Sin conteo de Elliott claro: los últimos giros no cumplen las reglas';

  /**
   * Conteo de Elliott sobre los ultimos giros (como elliott() de Python): un ciclo es un impulso de 5 ondas (1-5)
   * y una correccion de 3 (A-B-C). Devuelve [etiquetas, descripcion, objetivo o null, onda en curso o null, corta].
   */
  function elliott(pivots, bars) {
    if (pivots.length < 3) return [[], SIN_ELLIOTT, null, null, ''];
    const p = pivots.map((x) => x[2]);
    const c = col(bars, 4);
    const atrLast = dmi(col(bars, 2), col(bars, 3), c)[3][bars.length - 1] || 0;
    const started = pivots[pivots.length - 1][1] < bars.length - 1 && Math.abs(c[c.length - 1] - p[p.length - 1]) >= atrLast;

    const impulso = (pts) => {
      const s = pts[1] > pts[0] ? 1 : -1;
      let w = [];
      for (let k = 0; k < pts.length - 1; k++) w.push(s * (pts[k + 1] - pts[k]));
      if (w.some((x, k) => (k % 2 === 0 ? x <= 0 : x >= 0))) return false;
      w = w.map(Math.abs);
      if (w.length >= 2 && !(w[1] / w[0] >= 0.15 && w[1] / w[0] < 1)) return false;          // onda 2
      if (w.length >= 3 && s * (pts[3] - pts[1]) <= 0) return false;                          // la 3 supera la 1
      if (w.length >= 4 && (s * (pts[4] - pts[1]) <= 0 || w[3] < 0.1 * w[2])) return false;   // la 4 no pisa la 1
      if (w.length >= 5 && (s * (pts[5] - pts[3]) <= 0 || w[2] < Math.min(w[0], w[4]))) return false;  // 5 y 3
      return true;
    };
    const correccion = (pts) => {
      const a = pts[1] - pts[0];
      if (a === 0) return false;
      if (pts.length >= 3) {
        const b = pts[2] - pts[1];
        if (b * a >= 0 || !(Math.abs(b) / Math.abs(a) >= 0.2 && Math.abs(b) / Math.abs(a) <= 1)) return false;
      }
      if (pts.length >= 4) {
        const cc = pts[3] - pts[2];
        if (cc * a <= 0 || (pts[3] - pts[1]) * a <= 0 || !(Math.abs(cc) >= 0.5 * Math.abs(a) && Math.abs(cc) <= 2.618 * Math.abs(a))) return false;
      }
      return true;
    };

    const imp = ['0', '1', '2', '3', '4', '5'];
    const cands = [imp.concat(['A', 'B', 'C']), imp.concat(['A', 'B']), imp.concat(['A']), imp, imp.slice(0, 5), imp.slice(0, 4),
      ['0', 'A', 'B', 'C'], ['0', 'A', 'B']];
    for (const names of cands) {
      const n = names.length;
      if (p.length < n) continue;
      const pts = p.slice(-n);
      if (names[1] === '1') {
        if (!impulso(pts.slice(0, 6)) || (n > 6 && !correccion(pts.slice(5)))) continue;
      } else {
        if (!correccion(pts)) continue;
        // una correccion suelta corrige un tramo mas grande que ella, y si es A-B la C ya tiene que haber arrancado
        if (p.length < n + 1 || Math.abs(pts[0] - p[p.length - n - 1]) <= Math.abs(pts[1] - pts[0]) || (n === 3 && !started)) continue;
      }
      const P = {};
      names.forEach((k, i) => { P[k] = pts[i]; });
      const last = names[n - 1];
      const cur = started ? SIGUE[last] : last;
      let s, sentido, head, w1 = 0;
      if (names[1] === '1') {
        s = P['1'] > P['0'] ? 1 : -1;
        sentido = s > 0 ? 'alcista' : 'bajista';
        const done5 = 'A' in P || (last === '5' && started);
        head = done5 ? `Impulso ${sentido} de 5 ondas completo` : `Impulso ${sentido} en formación`;
        if (last === 'C' && started) head += ' y corrección A-B-C completa';
        else if ('A' in P) head += ', con la corrección A-B-C en marcha';
        w1 = Math.abs(P['1'] - P['0']);
      } else {
        const a = P.A - P['0'];
        s = a > 0 ? -1 : 1;
        sentido = a > 0 ? 'alcista' : 'bajista';
        head = `Corrección A-B-C ${sentido}` + (last === 'C' && started ? ' completa' : ' en formación');
      }
      let target = null, what = '';
      const base = '5' in P ? P['5'] : P['0'];
      if (cur === '2') { target = P['1'] - s * 0.5 * w1; what = 'onda 2 en curso: retroceso de la 1, suele llegar a la mitad'; }
      else if (cur === '3') { target = P['2'] + s * 1.618 * w1; what = 'onda 3 en curso: suele ser la más larga y fuerte'; }
      else if (cur === '4') {
        target = P['3'] - s * 0.382 * Math.abs(P['3'] - P['2']);
        what = s > 0 ? 'onda 4 en curso: retroceso antes de la última suba' : 'onda 4 en curso: rebote antes de la última baja';
      } else if (cur === '5') { target = P['4'] + s * w1; what = 'onda 5 en curso: la última del impulso, suele medir como la 1'; }
      else if (cur === 'A') { target = P['5'] - s * 0.382 * Math.abs(P['5'] - P['0']); what = 'empieza la corrección (onda A)'; }
      else if (cur === 'B') { target = P.A - 0.5 * (P.A - base); what = 'onda B en curso: rebote dentro de la corrección'; }
      else if (cur === 'C') { target = P.B + (P.A - base); what = 'onda C en curso: la última de la corrección, suele medir como la A'; }
      else if (cur === '1') what = 'la corrección terminó: puede empezar un impulso nuevo';
      return [names, `${head}; ${what}`, target, cur, what];
    }
    return [[], SIN_ELLIOTT, null, null, ''];
  }

  /**
   * Estimacion de donde quedan liquidaciones pendientes (mismo enfoque que los heatmaps publicos).
   * priceByHour: Map ts -> precio; oiHist: [[ts, oiUsd]]; lsHist: Map ts -> ratio long/short;
   * afterExtremes(ts) -> [minimo, maximo] del precio despues de ts, para descartar lo ya liquidado.
   */
  function mapaLiquidaciones(priceByHour, oiHist, lsHist, afterExtremes, levWeights = null, band = 0.12, step = 0.0025) {
    levWeights = levWeights || [[10, 0.3], [25, 0.3], [50, 0.25], [100, 0.15]];
    const prices = [...priceByHour.values()];
    const ref = prices[prices.length - 1];
    const loEdge = ref * (1 - band), nBins = Math.trunc((2 * band) / step);
    const longs = new Array(nBins).fill(0), shorts = new Array(nBins).fill(0);
    for (let x = 1; x < oiHist.length; x++) {
      const [, oi0] = oiHist[x - 1], [t1, oi1] = oiHist[x];
      const nuevo = oi1 - oi0, entry = priceByHour.get(t1);
      if (nuevo <= 0 || entry === undefined) continue;
      const r = lsHist.has(t1) ? lsHist.get(t1) : 1;
      const shareLong = r / (1 + r);
      const [low, high] = afterExtremes(t1);
      levWeights.forEach(([lev, w]) => {
        [['long', nuevo * shareLong * w, entry * (1 - 1 / lev + 0.004)], ['short', nuevo * (1 - shareLong) * w, entry * (1 + 1 / lev - 0.004)]]
          .forEach(([side, size, liq]) => {
            if ((side === 'long' && low <= liq) || (side === 'short' && high >= liq)) return;   // ya ocurrio
            const k = Math.trunc((liq - loEdge) / (ref * step));
            if (k >= 0 && k < nBins) (side === 'long' ? longs : shorts)[k] += size;
          });
      });
    }
    const out = [];
    for (let k = 0; k < nBins; k++) {
      if (longs[k] || shorts[k]) out.push({ precio: rnd(loEdge + (k + 0.5) * ref * step, 1), longs: rnd(longs[k] / 1e6, 2), shorts: rnd(shorts[k] / 1e6, 2) });
    }
    return out;
  }

  /** Patrones de velas japonesas que terminan en la vela i, del mas fuerte al mas debil: [[nombre, sesgo]]. */
  function patronesVelas(o, h, l, c, atr, trend, i) {
    if (i < 3 || atr[i] === null) return [];
    const body = (k) => Math.abs(c[k] - o[k]);
    const rng = (k) => h[k] - l[k] || 1e-9;
    const green = (k) => c[k] > o[k], red = (k) => c[k] < o[k];
    const big = (k) => body(k) > 0.6 * rng(k) && rng(k) > 0.6 * atr[i];
    const up = trend[i - 1] !== null && c[i - 1] > trend[i - 1];
    const out = [];
    const three = [i - 2, i - 1, i];
    if (three.every((k) => green(k) && body(k) > 0.5 * rng(k)) && c[i] > c[i - 1] && c[i - 1] > c[i - 2] && body(i) > 0.4 * atr[i]) out.push(['Tres soldados blancos', 'alcista']);
    if (three.every((k) => red(k) && body(k) > 0.5 * rng(k)) && c[i] < c[i - 1] && c[i - 1] < c[i - 2] && body(i) > 0.4 * atr[i]) out.push(['Tres cuervos negros', 'bajista']);
    if (red(i - 2) && big(i - 2) && body(i - 1) < 0.3 * body(i - 2) && green(i) && c[i] > (o[i - 2] + c[i - 2]) / 2) out.push(['Estrella de la mañana', 'alcista']);
    if (green(i - 2) && big(i - 2) && body(i - 1) < 0.3 * body(i - 2) && red(i) && c[i] < (o[i - 2] + c[i - 2]) / 2) out.push(['Estrella vespertina', 'bajista']);
    if (red(i - 1) && green(i) && c[i] >= o[i - 1] && o[i] <= c[i - 1] && body(i) > body(i - 1) && body(i) > 0.5 * atr[i]) out.push(['Envolvente alcista', 'alcista']);
    if (green(i - 1) && red(i) && c[i] <= o[i - 1] && o[i] >= c[i - 1] && body(i) > body(i - 1) && body(i) > 0.5 * atr[i]) out.push(['Envolvente bajista', 'bajista']);
    if (big(i - 1) && body(i) < 0.5 * body(i - 1) && Math.max(o[i], c[i]) < Math.max(o[i - 1], c[i - 1]) && Math.min(o[i], c[i]) > Math.min(o[i - 1], c[i - 1])) {
      out.push(red(i - 1) ? ['Harami alcista', 'alcista'] : ['Harami bajista', 'bajista']);
    }
    if (rng(i) > 0.7 * atr[i]) {
      const b = body(i), lw = Math.min(o[i], c[i]) - l[i], uw = h[i] - Math.max(o[i], c[i]);
      if (b <= 0.1 * rng(i)) out.push(['Doji', 'neutral']);
      else if (lw >= 2 * b && uw <= 0.6 * b) out.push(up ? ['Hombre colgado', 'bajista'] : ['Martillo', 'alcista']);
      else if (uw >= 2 * b && lw <= 0.6 * b) out.push(up ? ['Estrella fugaz', 'bajista'] : ['Martillo invertido', 'alcista']);
    }
    return out;
  }

  /** Para cada patron: en cuantos casos del historial el precio fue hacia donde dice el patron en horizon velas. */
  function estadisticaVelas(o, h, l, c, atr, trend, horizon, start = 30) {
    const stats = {};
    for (let i = start; i < c.length - horizon; i++) {
      patronesVelas(o, h, l, c, atr, trend, i).forEach(([name, bias]) => {
        if (bias === 'neutral') return;
        const ret = c[i + horizon] / c[i] - 1;
        const [n, ok] = stats[name] || [0, 0];
        stats[name] = [n + 1, ok + ((ret > 0) === (bias === 'alcista') ? 1 : 0)];
      });
    }
    return stats;
  }

  /**
   * Figuras clasicas sobre los giros confirmados, o null. Lineas como [t, precio, pendiente por ms, nombre]
   * para dibujarlas extendidas, y puntos de la figura como [t, precio, nombre] para marcarlos sobre las velas.
   */
  function patronGrafico(bars, pivots, atrLast) {
    const P = pivots.slice(0, -1);                     // el ultimo giro todavia no esta confirmado
    if (P.length < 4) return null;
    const iLast = bars.length - 1, px = bars[iLast][4];
    if (P[P.length - 1][1] < iLast - 80) return null;  // sin giros recientes: ninguna figura vigente
    const t = (k) => bars[k][0];
    const tol = 0.8 * atrLast;
    const line = (a, b, name) => [t(a[1]), a[2], (b[2] - a[2]) / (t(b[1]) - t(a[1]) || 1), name];
    const flatLine = (a, name) => [t(a[1]), a[2], 0, name];
    const atNow = (ln) => ln[1] + ln[2] * (t(iLast) - ln[0]);
    const point = (p, name) => [t(p[1]), p[2], name];
    const highs = P.filter((p) => p[0] === 'alto'), lows = P.filter((p) => p[0] === 'bajo');
    const range = (a, b) => { const r = []; for (let j = a; j < b; j++) r.push(j); return r; };

    const result = (name, bias, lines, points, target, desc, broke) => ({
      nombre: name, sesgo: bias, estado: broke ? 'confirmado' : 'en formación',
      objetivo: target === null ? null : rnd(target, 1), descripcion: desc, lineas: lines, puntos: points,
    });

    /** Una figura se anula si despues el precio paso su extremo (en contra) o si ya confirmo y volvio. */
    const stillValid = (lastPoint, bias, extreme, neckAt) => {
      const after = range(lastPoint[1] + 1, bars.length);
      if (bias === 'alcista') {
        if (after.some((j) => bars[j][3] < extreme - tol)) return false;
        const fired = after.some((j) => bars[j][4] > neckAt(j));
        return !fired || px > neckAt(iLast);
      }
      if (after.some((j) => bars[j][2] > extreme + tol)) return false;
      const fired = after.some((j) => bars[j][4] < neckAt(j));
      return !fired || px < neckAt(iLast);
    };

    // hombro-cabeza-hombro (y su inverso) sobre los ultimos 5 giros
    const q = P.slice(-5);
    if (q.length === 5) {
      const k = q.map((p) => p[2]);
      const shoulders = [point(q[0], 'Hombro'), point(q[2], 'Cabeza'), point(q[4], 'Hombro')];
      const neckLine = line(q[1], q[3], 'Cuello');
      const neckAt = (j) => neckLine[1] + neckLine[2] * (t(j) - neckLine[0]);
      if (q[0][0] === 'alto' && k[2] > k[0] + tol && k[2] > k[4] + tol && Math.abs(k[0] - k[4]) < 1.5 * tol
          && stillValid(q[4], 'bajista', k[2], neckAt)) {
        const neck = line(q[1], q[3], 'Cuello'), nNow = atNow(neck);
        const target = nNow - (k[2] - (k[1] + k[3]) / 2), broke = px < nNow;
        const desc = broke ? `Tres máximos, el del medio más alto. BTC perdió el cuello en ${ar(nNow)}: objetivo ${ar(target)}.`
          : `Tres máximos, el del medio más alto. Si BTC cierra debajo del cuello (${ar(nNow)}), se confirma y el objetivo es ${ar(target)}.`;
        return result('Hombro-cabeza-hombro', 'bajista', [neck], shoulders, target, desc, broke);
      }
      if (q[0][0] === 'bajo' && k[2] < k[0] - tol && k[2] < k[4] - tol && Math.abs(k[0] - k[4]) < 1.5 * tol
          && stillValid(q[4], 'alcista', k[2], neckAt)) {
        const neck = line(q[1], q[3], 'Cuello'), nNow = atNow(neck);
        const target = nNow + ((k[1] + k[3]) / 2 - k[2]), broke = px > nNow;
        const desc = broke ? `Tres mínimos, el del medio más bajo. BTC superó el cuello en ${ar(nNow)}: objetivo ${ar(target)}.`
          : `Tres mínimos, el del medio más bajo. Si BTC cierra arriba del cuello (${ar(nNow)}), se confirma y el objetivo es ${ar(target)}.`;
        return result('Hombro-cabeza-hombro invertido', 'alcista', [neck], shoulders, target, desc, broke);
      }
    }
    // triangulos, cunas, canales y rangos: piden mas toques que un doble techo o piso, asi que van primero
    const linesFig = figuraLineas(bars, P, atrLast);
    if (linesFig) return linesFig;
    // doble techo / doble piso: dos extremos parecidos (hasta ~1%, como mucho dos velas normales) sin uno
    // mas extremo en el medio, aunque haya giros menores entre ellos; el cuello es el giro opuesto mas extremo
    const tol2 = Math.max(tol, Math.min(0.01 * px, 2 * atrLast));
    const findDouble = (pts, opp, tops) => {
      const beyond = tops ? (x, y) => x > y : (x, y) => x < y;          // "mas extremo que"
      for (let bi = pts.length - 1; bi > Math.max(-1, pts.length - 4); bi--) {
        const b = pts[bi];
        if (b[1] < iLast - 60 || pts.slice(bi + 1).some((p) => beyond(p[2], b[2]))) continue;
        for (let ai = bi - 1; ai > Math.max(-1, bi - 5); ai--) {
          const a = pts[ai];
          const edge = tops ? Math.min(a[2], b[2]) : Math.max(a[2], b[2]);       // el menos extremo de los dos
          if (Math.abs(a[2] - b[2]) > tol2 || pts.slice(ai + 1, bi).some((p) => beyond(p[2], edge))) continue;
          const mids = opp.filter((p) => a[1] < p[1] && p[1] < b[1]);
          if (!mids.length) continue;
          const neck = mids.reduce((m, p) => (tops ? p[2] < m[2] : p[2] > m[2]) ? p : m);
          if (Math.abs(edge - neck[2]) <= 2 * tol) continue;                    // muy poco profundo
          return [a, b, neck];
        }
      }
      return null;
    };
    let found = findDouble(highs, lows, true);
    if (found) {
      const [a, b, nk] = found;
      if (stillValid(b, 'bajista', Math.max(a[2], b[2]), () => nk[2])) {
        const neck = nk[2], top = (a[2] + b[2]) / 2, target = neck - (top - neck), broke = px < neck;
        const done = range(b[1] + 1, bars.length).some((j) => bars[j][3] <= target);   // ya llego al objetivo: terminada
        if (!done) {
          const desc = broke ? `Dos máximos que rechazaron la misma zona (${ar(a[2])} y ${ar(b[2])}). BTC perdió el cuello en ${ar(neck)}: objetivo ${ar(target)}.`
            : `Dos máximos que rechazaron la misma zona (${ar(a[2])} y ${ar(b[2])}). Si BTC cierra debajo del cuello (${ar(neck)}), se confirma y el objetivo es ${ar(target)}.`;
          return result('Doble techo', 'bajista', [flatLine(nk, 'Cuello')], [point(a, 'Techo 1'), point(b, 'Techo 2')], target, desc, broke);
        }
      }
    }
    found = findDouble(lows, highs, false);
    if (found) {
      const [a, b, nk] = found;
      if (stillValid(b, 'alcista', Math.min(a[2], b[2]), () => nk[2])) {
        const neck = nk[2], bot = (a[2] + b[2]) / 2, target = neck + (neck - bot), broke = px > neck;
        const done = range(b[1] + 1, bars.length).some((j) => bars[j][2] >= target);
        if (!done) {
          const desc = broke ? `Dos mínimos que defendieron la misma zona (${ar(a[2])} y ${ar(b[2])}). BTC superó el cuello en ${ar(neck)}: objetivo ${ar(target)}.`
            : `Dos mínimos que defendieron la misma zona (${ar(a[2])} y ${ar(b[2])}). Si BTC cierra arriba del cuello (${ar(neck)}), se confirma y el objetivo es ${ar(target)}.`;
          return result('Doble piso', 'alcista', [flatLine(nk, 'Cuello')], [point(a, 'Piso 1'), point(b, 'Piso 2')], target, desc, broke);
        }
      }
    }
    return null;
  }

  /** Recta por dos giros que deja a todos los demas del lado de adentro (o tocandola): [linea, toques] o null. */
  function envolvente(pts, top, tol, t) {
    let best = null;
    for (let bi = pts.length - 1; bi > 0; bi--) {
      for (let ai = bi - 1; ai >= 0; ai--) {
        const a = pts[ai], b = pts[bi];
        const m = (b[2] - a[2]) / (t(b[1]) - t(a[1]) || 1);
        const at = (q) => a[2] + m * (t(q[1]) - t(a[1]));
        if (pts.some((q) => (top ? q[2] > at(q) + tol : q[2] < at(q) - tol))) continue;
        const touches = pts.filter((q) => Math.abs(q[2] - at(q)) <= tol).length;
        if (best === null || touches > best[1]) best = [[t(a[1]), a[2], m], touches];
      }
    }
    return best;
  }

  const figura = (name, bias, lines, points, target, desc, broke) => ({
    nombre: name, sesgo: bias, estado: broke ? 'confirmado' : 'en formación',
    objetivo: target === null ? null : rnd(target, 1), descripcion: desc, lineas: lines, puntos: points,
  });

  /** Triangulos, cunas, canales y rangos (como figura_lineas de Python): solo si el precio respeto las dos lineas. */
  function figuraLineas(bars, P, atrLast) {
    const iLast = bars.length - 1, px = bars[iLast][4];
    const t = (k) => bars[k][0];
    const tol = 0.8 * atrLast;
    const val = (ln, k) => ln[1] + ln[2] * (t(k) - ln[0]);
    for (const n of [8, 7, 6, 5]) {
      if (P.length < n) continue;
      const W = P.slice(-n);
      const hs = W.filter((q) => q[0] === 'alto'), ls = W.filter((q) => q[0] === 'bajo');
      if (hs.length < 2 || ls.length < 2) continue;
      const eu = envolvente(hs, true, tol, t), el = envolvente(ls, false, tol, t);
      if (eu === null || el === null || eu[1] < 2 || el[1] < 2 || eu[1] + el[1] < 5) continue;
      const upL = eu[0].concat(['Techo']), loL = el[0].concat(['Piso']);
      const s0 = W[0][1], s1 = W[W.length - 1][1];
      if (iLast - s0 < 15 || s1 - s0 < 10) continue;
      let out = false;
      for (let k = s0; k <= s1; k++) if (bars[k][4] > val(upL, k) + tol || bars[k][4] < val(loL, k) - tol) { out = true; break; }
      if (out) continue;                              // el precio no respeto las lineas: no es una figura
      const w0 = val(upL, s0) - val(loL, s0), w1 = val(upL, iLast) - val(loL, iLast);
      if (w0 <= 2 * tol || w1 <= tol) continue;
      const span = t(iLast) - t(s0);
      const ru = upL[2] * span, rl = loL[2] * span;
      const flat = Math.max(tol, 0.15 * w0);
      const fu = Math.abs(ru) < flat, fl = Math.abs(rl) < flat;
      const conv = w1 < 0.8 * w0, par = Math.abs(w1 - w0) <= 0.25 * w0;
      let name, bias;
      if (fu && fl && par) [name, bias] = ['Rango lateral', 'neutral'];
      else if (fu && !fl && rl > 0 && conv) [name, bias] = ['Triángulo ascendente', 'alcista'];
      else if (fl && !fu && ru < 0 && conv) [name, bias] = ['Triángulo descendente', 'bajista'];
      else if (!fu && !fl && ru < 0 && rl > 0 && conv) [name, bias] = ['Triángulo simétrico', 'neutral'];
      else if (!fu && !fl && ru > 0 && rl > 0 && conv) [name, bias] = ['Cuña ascendente', 'bajista'];
      else if (!fu && !fl && ru < 0 && rl < 0 && conv) [name, bias] = ['Cuña descendente', 'alcista'];
      else if (!fu && !fl && ru > 0 && rl > 0 && par) [name, bias] = ['Canal alcista', 'alcista'];
      else if (!fu && !fl && ru < 0 && rl < 0 && par) [name, bias] = ['Canal bajista', 'bajista'];
      else continue;                                  // lineas que no forman ninguna figura clasica
      const uNow = val(upL, iLast), lNow = val(loL, iLast);
      const height = name.startsWith('Canal') || name === 'Rango lateral' ? Math.max(w0, w1) : w0;
      const art = name.startsWith('Cuña') ? 'una' : 'un';
      const touches = ` (${eu[1]} toques arriba y ${el[1]} abajo)`;
      const recent = [];
      for (let k = Math.max(s1, iLast - 20); k < iLast; k++) recent.push(k);
      if (px > uNow + tol) {
        if (!recent.some((k) => bars[k][4] <= val(upL, k))) return null;   // la ruptura fue hace mucho
        const target = uNow + height;
        return figura(`Ruptura alcista de ${name.toLowerCase()}`, 'alcista', [upL, loL], [], target,
          `BTC rompió hacia arriba el techo de ${art} ${name.toLowerCase()}${touches} en ${ar(uNow)}: el objetivo de la ruptura es ${ar(target)}.`, true);
      }
      if (px < lNow - tol) {
        if (!recent.some((k) => bars[k][4] >= val(loL, k))) return null;
        const target = lNow - height;
        return figura(`Ruptura bajista de ${name.toLowerCase()}`, 'bajista', [upL, loL], [], target,
          `BTC rompió hacia abajo el piso de ${art} ${name.toLowerCase()}${touches} en ${ar(lNow)}: el objetivo de la ruptura es ${ar(target)}.`, true);
      }
      const target = bias === 'alcista' ? uNow + height : bias === 'bajista' ? lNow - height : null;
      const side = bias === 'alcista' ? `suele romper hacia arriba; si supera ${ar(uNow)}, el objetivo es ${ar(target)}`
        : bias === 'bajista' ? `suele romper hacia abajo; si pierde ${ar(lNow)}, el objetivo es ${ar(target)}`
          : 'puede romper para cualquier lado: la dirección la da la ruptura';
      return figura(name, bias, [upL, loL], [], target, `BTC se mueve entre un piso en ${ar(lNow)} y un techo en ${ar(uNow)}${touches}; ${side}.`, false);
    }
    return null;
  }

  /** Acumulacion o distribucion de Wyckoff (como wyckoff() de Python), solo con sus eventos principales. */
  function wyckoff(bars, pivots, atrLast) {
    const P = pivots.slice(0, -1);
    const nBars = bars.length, iLast = nBars - 1, px = bars[iLast][4];
    const tol = 0.8 * atrLast;
    const t = (k) => bars[k][0];
    const vol = col(bars, 5);
    for (let m = Math.min(10, P.length); m > 3; m--) {
      const W = P.slice(-m);
      const acc = W[0][0] === 'bajo';
      const sc = W[0], arr = W[1], k0 = sc[1];
      if (iLast - k0 < 20 || iLast - k0 > 400 || k0 < 60) continue;
      const lo = acc ? sc[2] : arr[2], hi = acc ? arr[2] : sc[2];
      const height = hi - lo;
      if (height < 3 * atrLast) continue;
      const prev = bars.slice(k0 - 60, k0);
      if (acc && Math.max(...prev.map((b) => b[2])) < hi + 0.5 * height) continue;
      if (!acc && Math.min(...prev.map((b) => b[3])) > lo - 0.5 * height) continue;
      const avg = sum(vol.slice(k0 - 50, k0)) / 50;
      if (Math.max(...vol.slice(Math.max(0, k0 - 1), k0 + 2)) < 1.5 * avg) continue;
      const edge = acc ? lo : hi, other = acc ? hi : lo, sign = acc ? 1 : -1;
      let brk = null;
      for (let k = arr[1] + 1; k < nBars; k++) if (sign * (bars[k][4] - other) > 0) { brk = k; break; }
      const rest = W.slice(2).filter((q) => brk === null || q[1] < brk);
      const same = rest.filter((q) => q[0] === W[0][0]), opp = rest.filter((q) => q[0] !== W[0][0]);
      if (opp.some((q) => (acc ? q[2] > other + tol : q[2] < other - tol))) continue;
      if (same.some((q) => (acc ? q[2] < edge - 0.35 * height : q[2] > edge + 0.35 * height))) continue;
      const st = same.find((q) => Math.abs(q[2] - edge) <= Math.max(tol, 0.25 * height)) || null;
      let spring = null;
      same.forEach((q) => {
        if (sign * (edge - q[2]) > 0.1 * tol && (st === null || q[1] > st[1] || q === st)) {
          for (let k = q[1] + 1; k < Math.min(nBars, q[1] + 4); k++) if (sign * (bars[k][4] - edge) > 0) { spring = q; break; }
        }
      });
      if (st === null || spring === null || (spring === st && same.length < 2)) continue;
      if (sign * (edge - px) > 0.35 * height + tol) return null;     // perdio el spring (o el UTAD)
      const sos = brk, target = other + sign * height;
      if (sos !== null) {
        for (let k = sos; k < nBars; k++) if (sign * ((acc ? bars[k][2] : bars[k][3]) - target) >= 0) return null;   // ya llego
      }
      const nm = acc ? ['SC', 'AR', 'ST', 'Spring', 'SOS'] : ['BC', 'AR', 'ST', 'UTAD', 'SOW'];
      const points = [[t(sc[1]), sc[2], nm[0]], [t(arr[1]), arr[2], nm[1]]];
      if (st !== spring) points.push([t(st[1]), st[2], nm[2]]);
      points.push([t(spring[1]), spring[2], nm[3]]);
      const lines = [[t(k0), lo, 0, 'Piso del rango'], [t(k0), hi, 0, 'Techo del rango']];
      const name = acc ? 'Acumulación de Wyckoff' : 'Distribución de Wyckoff';
      const ev = acc ? nm[3].toLowerCase() : nm[3];
      if (sos !== null) {
        points.push([t(sos), bars[sos][4], nm[4]]);
        return figura(name, acc ? 'alcista' : 'bajista', lines, points, target,
          `Rango después de una ${acc ? 'caída' : 'suba'} con clímax de ${acc ? 'venta' : 'compra'}, prueba y ${ev}; BTC ya ${acc ? 'superó el techo' : 'perdió el piso'} (${ar(other)}): fase de ${acc ? 'suba' : 'baja'}, objetivo ${ar(target)}.`, true);
      }
      return figura(name, acc ? 'alcista' : 'bajista', lines, points, target,
        `Rango entre ${ar(lo)} y ${ar(hi)} después de una ${acc ? 'caída' : 'suba'} con clímax de ${acc ? 'venta' : 'compra'}. Ya hubo prueba y ${ev}: ${acc ? 'si cierra arriba de ' : 'si cierra debajo de '}${ar(other)}, se confirma y el objetivo es ${ar(target)}.`, false);
    }
    return null;
  }

  /**
   * Divergencias clasicas en RSI y MACD, como las busca un trader (igual que divergencias() de Python): el giro mas
   * reciente contra los anteriores, con el extremo propio del indicador cerca de cada giro y la linea del indicador
   * entre los dos puntos sin cruces. `pivots` ya no se usa (compatibilidad).
   */
  function divergencias(bars, pivots = null, maxAge = 30, minGap = 6, lookback = 60, left = 4, right = 2, win = 2) {
    const h = col(bars, 2), l = col(bars, 3), c = col(bars, 4);
    const n = bars.length, last = n - 1;
    const atr = dmi(h, l, c)[3];
    const series = [['RSI', rsi(c)], ['MACD', macd(c)[0]]];
    const out = [];
    ['alto', 'bajo'].forEach((kind) => {
      const top = kind === 'alto', src = top ? h : l;
      const piv = [];
      for (let i = left; i < n - right; i++) {
        let ok = true;
        for (let j = i - left; j < i && ok; j++) ok = top ? src[i] > src[j] : src[i] < src[j];
        for (let j = i + 1; j <= i + right && ok; j++) ok = top ? src[i] >= src[j] : src[i] <= src[j];
        if (ok) piv.push(i);
      }
      if (piv.length < 2 || last - piv[piv.length - 1] > maxAge) return;
      const b = piv[piv.length - 1];
      const aAtr = atr[b] || h[b] - l[b];
      series.forEach(([name, ser]) => {
        // el extremo del indicador cerca del giro: [valor, vela] (a igualdad de valor gana la vela mas nueva, como en Python)
        const ext = (k) => {
          let best = null;
          for (let j = Math.max(0, k - win); j < Math.min(n, k + win + 1); j++) {
            const v = ser[j];
            if (v === null) continue;
            if (best === null || (top ? v > best[0] || (v === best[0] && j > best[1]) : v < best[0] || (v === best[0] && j > best[1]))) best = [v, j];
          }
          return best;
        };
        const eb = ext(b);
        if (eb === null) return;
        const [vb, jb] = eb;
        for (let ai = piv.length - 2; ai >= 0; ai--) {
          const a = piv[ai];
          if (b - a < minGap) continue;
          if (b - a > lookback) break;
          if (!(top ? src[b] > src[a] : src[b] < src[a])) continue;
          const ea = ext(a);
          if (ea === null) continue;
          const [va, ja] = ea;
          const thr = name === 'RSI' ? 2.0 : 0.05 * Math.max(Math.abs(va), Math.abs(vb));
          if (!(top ? vb < va - thr : vb > va + thr) || jb <= ja) continue;
          let pull = top ? Infinity : -Infinity;
          for (let k = a; k <= b; k++) pull = top ? Math.min(pull, l[k]) : Math.max(pull, h[k]);
          const edge = top ? Math.min(src[a], src[b]) : Math.max(src[a], src[b]);
          if ((top ? edge - pull : pull - edge) < 0.8 * aAtr) continue;
          const tol = thr * 0.5;
          let clean = true;
          for (let k = ja + 1; k < jb && clean; k++) {
            const v = ser[k];
            if (v === null) continue;
            const ln = va + ((vb - va) * (k - ja)) / (jb - ja);
            if (top ? v > ln + tol : v < ln - tol) clean = false;
          }
          if (!clean) continue;
          out.push({ indicador: name, tipo: top ? 'bajista' : 'alcista', t1: bars[a][0], p1: src[a], t2: bars[b][0], p2: src[b],
            v1: rnd(va, 2), v2: rnd(vb, 2), ti1: bars[ja][0], ti2: bars[jb][0] });
          break;
        }
      });
    });
    return out;
  }

  function pivotes(prevDay) {
    const [, , h, l, c] = prevDay;
    const p = (h + l + c) / 3;
    return [['P', p], ['R1', 2 * p - l], ['S1', 2 * p - h], ['R2', p + (h - l)], ['S2', p - (h - l)],
      ['R3', h + 2 * (p - l)], ['S3', l - 2 * (h - p)]];
  }

  const Ind = {
    ar, rnd, roundEven, sma, ema, rma, wma, hma, vwma, rsi, stoch, stochRsi, cci, williamsR, momentum, macd,
    awesome, bullBearPower, ultimate, dmi, mfi, cmf, obv, bollinger, keltner, psar, supertrend, ichimoku,
    vwapSession, calificar, ratingTxt, divergencia, fvg, zigzag, elliott, mapaLiquidaciones, patronesVelas,
    estadisticaVelas, patronGrafico, figuraLineas, wyckoff, divergencias, pivotes,
  };
  root.Ind = Ind;
  if (typeof module !== 'undefined' && module.exports) module.exports = Ind;
})(typeof self !== 'undefined' ? self : globalThis);
