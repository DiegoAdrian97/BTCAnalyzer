/*
 * El analisis completo, como analisis_btc.py: recibe velas y datos del momento y devuelve las filas que
 * dibuja el dashboard. No pide nada a la red (eso lo hace datos.js), asi se puede comparar con Python.
 */
(function (root) {
  'use strict';
  const Ind = root.Ind || (typeof require !== 'undefined' ? require('./indicadores.js') : null);
  const Apr = root.Apr || (typeof require !== 'undefined' ? require('./aprendizaje.js') : null);
  const { ar, rnd, roundEven } = Ind;
  // precio redondeado con los decimales que pide su tamaño (como analisis_btc.py): 1 BTC, 2 desde 100, 3 desde 10, 4 XRP
  const decPrecio = (x) => { const a = Math.abs(x); return a >= 1000 ? 1 : a >= 100 ? 2 : a >= 10 ? 3 : 4; };
  const rp = (x) => (x === null || x === undefined ? null : rnd(x, decPrecio(x)));

  const MIN_SAMPLES = 40;
  const CHART_BARS = 300;
  const SCENARIO_STEPS = 12;
  const HOUR_MS = 3600000;
  const DAY_MS = 86400000;
  // temporalidad: [dias de historia, horizontes de probabilidad en velas]
  const TIMEFRAMES = { '5m': [30, [3, 12]], '15m': [90, [4, 16]], '30m': [180, [4, 16]], '1h': [365, [4, 24]], '4h': [730, [3, 6]], '1d': [1500, [3, 7]] };
  const DIAS_LARGOS = 3000;      // historia diaria para la semanal y la mensual (como DIAS_LARGOS de Python)
  const TF_MS = { '5m': 300000, '15m': 900000, '30m': 1800000, '1h': 3600000, '4h': 14400000, '1d': 86400000 };
  const TF_TXT = { '5m': '5 min', '15m': '15 min', '30m': '30 min', '1h': '1 hora', '4h': '4 horas', '1d': 'diario', '1w': 'semanal', '1M': 'mensual' };
  const NICE_STEPS = [];      // como en Python: 1, 2,5 y 5 por cada potencia de 10
  for (let k = -4; k < 6; k++) for (const m of [1, 2.5, 5]) NICE_STEPS.push(m * 10 ** k);

  // ---------- formato ----------
  const ap = (x) => ar(x, Math.abs(x) >= 1000 ? 0 : Math.abs(x) >= 10 ? 2 : 4);     // precio: con decimales si vale menos de 1.000 (4 debajo de 10)
  const arp = (x, d = 1) => (x > 0 ? '+' : '') + ar(x, d) + '%';
  const pct = (a, b) => (a / b - 1) * 100;
  const lc1 = (s) => s.slice(0, 1).toLowerCase() + s.slice(1);   // sin tocar siglas como R1 u onda C
  const TZ_MS = -3 * HOUR_MS;                                      // Argentina, sin horario de verano
  const pad = (n, w = 2) => String(n).padStart(w, '0');
  const local = (ms) => new Date(ms + TZ_MS);
  const fmtLocal = (ms) => { const d = local(ms); return `${pad(d.getUTCDate())}/${pad(d.getUTCMonth() + 1)} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`; };
  const isoLocal = (ms) => {
    const d = local(ms);
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}.${pad(ms % 1000, 3)}-03:00`;
  };
  const utcDate = (ms) => new Date(ms).toISOString().slice(0, 10);

  function trendWord(c, e20, e50, e200) {
    if (c > e20 && e20 > e50 && e50 > e200) return 'Alcista fuerte';
    if (c < e20 && e20 < e50 && e50 < e200) return 'Bajista fuerte';
    if (c > e200) return c < e50 ? 'Alcista con dudas' : 'Alcista';
    return c > e50 ? 'Bajista con rebote' : 'Bajista';
  }

  function label(minutes) {
    if (minutes < 60) return `${minutes} min`;
    if (minutes < 1440) return `${Math.floor(minutes / 60)} h`;
    return `${Math.floor(minutes / 1440)} d`;
  }

  // ---------- situaciones parecidas ----------
  // la situacion de cada vela (que rasgos se comparan) la elige el aprendizaje: ver aprendizaje.js
  function similar(st, last, warmup) {
    const now = st[st.length - 1];
    let idxs = [], keep = 0;
    for (keep of [4, 3, 2, 1]) {
      idxs = [];
      for (let j = warmup; j < last; j++) {
        const s = st[j];
        if (s && s.slice(0, keep).every((x, k) => x === now[k])) idxs.push(j);
      }
      if (idxs.length >= MIN_SAMPLES) break;
    }
    return [idxs, keep];
  }

  const quantile = (sorted, p) => sorted[Math.min(Math.trunc(p * sorted.length), sorted.length - 1)];

  // ---------- movimiento fuerte en la proxima hora (como movimiento() de Python) ----------
  const MOV_CORTES = [0.8, 1.0, 1.3, 1.6, 2.0, 2.5];
  const MOV_TABLA = { BTC: { prob: [8, 12, 19, 32, 43, 60, 68], veces: [0.8, 0.96, 1.18, 1.53, 1.75, 2.3, 3.0], base: 14 },
    ZEC: { prob: [7, 8, 14, 24, 35, 50, 69], veces: [0.87, 0.94, 1.11, 1.38, 1.6, 2.0, 3.7], base: 11 },
    SOL: { prob: [7, 9, 16, 26, 40, 61, 76], veces: [0.84, 0.94, 1.14, 1.41, 1.77, 2.39, 3.52], base: 12 },
    XRP: { prob: [9, 11, 18, 29, 39, 53, 87], veces: [0.84, 0.94, 1.13, 1.43, 1.68, 2.15, 4.96], base: 14 },
    // BABA: perpetuo de la accion de Alibaba (como analisis_btc.py)
    BABA: { prob: [13, 24, 24, 48, 65, 86, 100], veces: [0.75, 1.15, 1.17, 1.94, 2.56, 3.56, 4.57], base: 22 },
    // NVDA, GOOGL y AMD (como analisis_btc.py)
    NVDA: { prob: [7, 26, 34, 46, 69, 89, 100], veces: [0.71, 1.29, 1.55, 1.85, 2.56, 3.48, 7.52], base: 22 },
    GOOGL: { prob: [10, 25, 36, 50, 58, 96, 100], veces: [0.78, 1.13, 1.55, 1.95, 2.41, 4.17, 3.31], base: 23 },
    AMD: { prob: [7, 20, 31, 40, 69, 79, 100], veces: [0.69, 1.17, 1.42, 1.77, 2.56, 3.43, 4.13], base: 20 },
    // AAPL, MSFT, AMZN, SPCX, META, TSLA y QQQ: futuros de Binance (como analisis_btc.py)
    AAPL: { prob: [10,  23,  33,  54,  72,  93,  100], veces: [0.76,  1.15,  1.41,  2.21,  2.99,  3.75,  4.1], base: 22 },
    MSFT: { prob: [9,  22,  34,  40,  75,  91,  100], veces: [0.75,  1.2,  1.44,  1.79,  2.8,  4.43,  4.33], base: 22 },
    AMZN: { prob: [9,  24,  34,  55,  66,  93,  94], veces: [0.73,  1.23,  1.5,  2.14,  2.67,  3.87,  4.18], base: 22 },
    SPCX: { prob: [9,  33,  41,  60,  67,  84,  92], veces: [0.62,  1.34,  1.68,  2.41,  2.73,  4.48,  4.03], base: 24 },
    META: { prob: [11,  28,  36,  52,  78,  92,  100], veces: [0.75,  1.27,  1.55,  2.13,  3.18,  4.94,  6.39], base: 25 },
    TSLA: { prob: [9,  29,  40,  57,  82,  89,  100], veces: [0.71,  1.37,  1.72,  2.23,  3.48,  4.71,  6.85], base: 25 },
    QQQ: { prob: [5,  15,  25,  50,  61,  61,  50], veces: [0.72,  1.11,  1.35,  2.01,  2.31,  2.5,  2.4], base: 18 },
    SPY: { prob: [5, 15, 24, 48, 63, 70, 100], veces: [0.77, 1.03, 1.32, 1.94, 2.36, 2.43, 2.33], base: 17 },
    // MELI: velas de Bitget (como analisis_btc.py)
    MELI: { prob: [20, 25, 36, 54, 59, 92, 0], veces: [0.95, 1.36, 1.56, 2.14, 2.68, 4.1, 1.79], base: 28 } };
  function percentil(v, q) {
    if (v <= q[0]) return 0;
    if (v >= q[q.length - 1]) return 100;
    for (let i = 1; i < q.length; i++) {
      if (v <= q[i]) { const lo = q[i - 1], hi = q[i], f = hi === lo ? 0 : (v - lo) / (hi - lo); return ((i - 1 + f) / (q.length - 1)) * 100; }
    }
    return 100;
  }
  function fase(y) { return y % 4 === 2 ? 'bajista' : `alcista ${(((y - 3) % 4) + 4) % 4 + 1}`; }
  // minimo probable en los proximos 6 meses (como piso de termometro.py)
  const ACCIONES_PISO = new Set(['BABA', 'NVDA', 'GOOGL', 'AMD', 'AAPL', 'MSFT', 'AMZN', 'SPCX', 'META', 'TSLA', 'QQQ', 'SPY', 'MSTR', 'MELI']);
  function interpCdf(x, xs, ys) {
    if (x <= xs[0]) return 0;
    if (x >= xs[xs.length - 1]) return 1;
    for (let i = 1; i < xs.length; i++) {
      if (x <= xs[i]) { const lo = xs[i - 1], hi = xs[i]; return hi === lo ? ys[i - 1] : ys[i - 1] + ((ys[i] - ys[i - 1]) * (x - lo)) / (hi - lo); }
    }
    return 1;
  }
  /** Probabilidad de que el minimo de los proximos 180 dias quede debajo de exp(x) veces el precio de hoy. */
  function pisoProb(P, moneda, x, vol) {
    const own = P.own[moneda], pz = interpCdf(x / vol, P.z, P.grid);
    return own ? 0.5 * pz + 0.5 * interpCdf(x, own, P.grid) : pz;
  }
  const decPiso = (v) => (v >= 1000 ? 0 : v >= 10 ? 2 : 4);
  function piso(moneda, closesD, price, T, nowMs = Date.now()) {
    const P = T && T.piso;
    if (!P || price <= 0 || closesD.length < 366) return null;
    const lr = []; for (let i = closesD.length - 365; i < closesD.length; i++) lr.push(Math.log(closesD[i] / closesD[i - 1]));
    let med = 0; lr.forEach((v) => { med += v; }); med /= 365;
    let sq = 0; lr.forEach((v) => { sq += (v - med) ** 2; });
    const vol = Math.sqrt(sq / 365) * Math.sqrt(P.dias);
    if (!(vol > 0)) return null;
    const niveles = [50, 80, 90, 95].map((conf) => {
      let lo = -6, hi = 1;
      for (let k = 0; k < 60; k++) { const mid = (lo + hi) / 2; if (pisoProb(P, moneda, mid, vol) < 1 - conf / 100) lo = mid; else hi = mid; }
      const v = price * Math.exp((lo + hi) / 2);
      return [conf, rnd(v, decPiso(v))];
    });
    // años anteriores desde esta misma fecha (bajistas y alcistas): cuanto cayo en los 180 dias siguientes
    const d = new Date(nowMs), doy = Math.floor((Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) - Date.UTC(d.getUTCFullYear(), 0, 1)) / 86400000) + 1;
    const anterioresDe = (m) => {
      const out = [];
      Object.keys((P.analogos || {})[m] || {}).sort().forEach((y) => {
        const fila = P.analogos[m][y];
        let mejor = fila[0]; fila.forEach((e) => { if (Math.abs(e[0] - doy) < Math.abs(mejor[0] - doy)) mejor = e; });
        if (Math.abs(mejor[0] - doy) <= 4) out.push([+y, fase(+y), mejor[1]]);
      });
      return out;
    };
    const todas = {}; Object.keys(P.analogos || {}).sort().forEach((m) => { todas[m] = anterioresDe(m); });
    const anteriores = todas[moneda] || [];
    return { tabla: 'piso', moneda, dias: P.dias, precio: price, vol: rnd(vol * 100, 1), niveles, anteriores,
      modelo: { grid: P.grid, z: P.z, own: P.own, vol: { ...P.vol, [moneda]: rnd(vol, 6) }, anteriores: todas } };
  }
  /** Medidor de XRP o SOL (como termometro_alt de termometro.py): su barato o caro y el ciclo de BTC. */
  function termometroAlt(moneda, velasD, price, T, nowMs = Date.now()) {
    const A = T && T.alts && T.alts[moneda], md = T && T.medidor;
    if (!A || !md || price <= 0) return null;
    const hoy = Math.floor(nowMs / 86400000), dias = new Map(A.cierres.map(([d, c]) => [d, c]));
    velasD.forEach((b) => dias.set(Math.floor(b[0] / 86400000), b[4]));
    const closes = [...dias.keys()].filter((d) => d < hoy).sort((a, b) => a - b).map((d) => dias.get(d));
    const comps = A.componentes, conWma = comps.includes('wma200');
    if (closes.length < (conWma ? 1400 : 365)) return null;
    let s = 0; if (conWma) for (const x of closes.slice(-1400)) s += x;
    const wma = conWma ? s / 1400 : null;
    const ath = Math.max(A.ath, Math.max(...closes), price), c365 = closes[closes.length - 365];
    const med = { dd_ath: price / ath - 1, ret365: Math.log(price / c365) };
    if (wma) med.wma200 = Math.log(price / wma);
    const p = {}; comps.forEach((k) => { p[k] = percentil(med[k], A.q[k]); });
    const temp = comps.reduce((a, k) => a + p[k], 0) / comps.length;
    const y = new Date(nowMs).getUTCFullYear(), av = (Math.floor((nowMs - Date.UTC(y, 0, 1)) / 86400000)) / 366;
    const ph = (((y - 2) % 4) + 4) % 4, x = [+(ph === 1), +(ph === 2), +(ph === 3), (ph === 0) * av, (ph === 3) * av];
    let lg = md.intercepto; md.pesos.forEach((w, i) => { lg += w * x[i]; });
    const prob = 1 / (1 + Math.exp(-lg));
    const S = md.peso_valuacion * (1 - temp / 100) + (1 - md.peso_valuacion) * prob;
    const zm = A.zonas.find((q) => q.desde <= S && S < q.hasta), z = T.zonas.find((q) => temp < q.hasta || q.hasta >= 100);
    return { tabla: 'termometro', moneda, medidor: rnd(Math.min(100, Math.max(0, (1 - S) * 100)), 1), medidor_zona: zm.nombre,
      m_sube_180: zm.sube_180, m_mediana_180: zm.mediana_180, m_sube_365: zm.sube_365, m_mediana_365: zm.mediana_365, avance: Math.round(av * 100),
      funding7: null, funding_ajuste: 0, p_ciclo: Math.round(prob * 100), m_zonas: A.zonas.map((q) => [q.nombre, q.sube_365, q.mediana_365]),
      temp: rnd(temp, 1), zona: z.nombre, año: y, fase: fase(y), fng: null, regla: null, reglas: {}, años: [], ciclos: [],
      p_wma200: wma ? rnd(p.wma200, 1) : null, p_dd_ath: rnd(p.dd_ath, 1), p_ret365: rnd(p.ret365, 1), wma200: wma ? rnd(wma, 4) : null,
      sobre_wma: wma ? rnd((price / wma - 1) * 100, 1) : null, caida_ath: rnd(med.dd_ath * 100, 1), ath: rnd(ath, 4), ret_anual: rnd((price / c365 - 1) * 100, 1) };
  }
  /** MVRV y Puell de hoy (como onchain_hoy de termometro.py), con lo ultimo de CoinMetrics. {} si no hay datos. */
  function onchainHoy(T, price, nowMs = Date.now()) {
    const o = T.onchain;
    if (!o || price <= 0) return {};
    const hoy = Math.floor(nowMs / 86400000), rp = o.rp + o.rp_pend * Math.max(0, Math.min(45, hoy - o.dia)), iss = o.btc_dia * price;
    return { mvrv: price / rp, puell: iss / ((o.iss_suma364 + iss) / 365), precio_realizado: rp };
  }
  function ajusteFunding(md, f7) {   // +1 funding de 7 dias negativo (miedo), -1 si es 0,03% o mas (euforia), 0 si no
    const fu = md && md.funding;
    if (!fu || f7 === null || f7 === undefined || Number.isNaN(f7)) return 0;
    return f7 < fu.bajo ? 1 : f7 >= fu.alto ? -1 : 0;
  }
  function termometro(closesD, price, T, fng = null, nowMs = Date.now(), f7 = null) {
    if (closesD.length < 1400 || price <= 0) return null;
    let s = 0; for (const x of closesD.slice(-1400)) s += x;
    const wma = s / 1400, ath = Math.max(T.ath, Math.max(...closesD), price), c365 = closesD[closesD.length - 365];
    const med = { wma200: Math.log(price / wma), dd_ath: price / ath - 1, ret365: Math.log(price / c365) };
    const oc = onchainHoy(T, price, nowMs);
    ['mvrv', 'puell'].forEach((k) => { if (oc[k] !== undefined) med[k] = Math.log(oc[k]); });
    const p = {}; T.componentes.forEach((k) => { if (med[k] !== undefined) p[k] = percentil(med[k], T.q[k]); });
    const pk = Object.keys(p), temp = pk.reduce((a, k) => a + p[k], 0) / pk.length;
    const z = T.zonas.find((x) => temp < x.hasta || x.hasta >= 100);
    const y = new Date(nowMs).getUTCFullYear(), fs = fase(y);
    let regla = null;
    if (fng !== null && fng !== undefined) {
      regla = fng < 25 && fs === 'bajista' ? 'miedo_bajista' : fng > 75 && fs === 'alcista 3' ? 'codicia_alcista3'
        : fng > 75 && (fs === 'alcista 1' || fs === 'alcista 2') ? 'codicia_alcista12' : null;
    }
    const cic = T.ciclo || {};
    const d0 = new Date(nowMs), av = (Math.floor((d0 - Date.UTC(y, 0, 1)) / 86400000)) / 366, md = T.medidor;
    let posM = null, zm = null, prob = null;
    const adj = ajusteFunding(md, f7);
    if (md) {
      const ph = (((y - 2) % 4) + 4) % 4, x = [+(ph === 1), +(ph === 2), +(ph === 3), (ph === 0) * av, (ph === 3) * av];
      let lg = md.intercepto; md.pesos.forEach((w, i) => { lg += w * x[i]; });
      prob = 1 / (1 + Math.exp(-lg));
      const S = md.peso_valuacion * (1 - temp / 100) + (1 - md.peso_valuacion) * prob + ((md.funding && md.funding.peso) || 0) * adj;
      zm = md.zonas.find((q) => q.desde <= S && S < q.hasta);
      posM = Math.min(100, Math.max(0, (1 - S) * 100));
    }
    return { tabla: 'termometro', medidor: posM === null ? null : rnd(posM, 1), medidor_zona: zm ? zm.nombre : null,
      m_sube_180: zm ? zm.sube_180 : null, m_mediana_180: zm ? zm.mediana_180 : null, m_sube_365: zm ? zm.sube_365 : null, m_mediana_365: zm ? zm.mediana_365 : null,
      avance: Math.round(av * 100), funding7: f7 === null || f7 === undefined ? null : rnd(f7 * 100, 4), funding_ajuste: adj, p_ciclo: prob === null ? null : Math.round(prob * 100), m_zonas: md ? md.zonas.map((q) => [q.nombre, q.sube_365, q.mediana_365]) : [],
      temp: rnd(temp, 1), zona: z.nombre, año: y, fase: fs, fng: fng === undefined ? null : fng, regla,
      reglas: cic.reglas || {}, años: cic.años || [], ciclos: cic.ciclos || [], p_wma200: rnd(p.wma200, 1), p_dd_ath: rnd(p.dd_ath, 1), p_ret365: rnd(p.ret365, 1),
      p_mvrv: p.mvrv === undefined ? null : rnd(p.mvrv, 1), p_puell: p.puell === undefined ? null : rnd(p.puell, 1),
      mvrv: oc.mvrv === undefined ? null : rnd(oc.mvrv, 3), puell: oc.puell === undefined ? null : rnd(oc.puell, 3),
      precio_realizado: oc.precio_realizado === undefined ? null : rnd(oc.precio_realizado, 1),
      wma200: rnd(wma, 1), sobre_wma: rnd((price / wma - 1) * 100, 1), caida_ath: rnd(med.dd_ath * 100, 1), ath: rnd(ath, 1),
      ret_anual: rnd((price / c365 - 1) * 100, 1), sube_180: z.sube_180, mediana_180: z.mediana_180, sube_365: z.sube_365, mediana_365: z.mediana_365,
      zonas: T.zonas.map((x) => [x.desde, x.hasta, x.nombre, x.sube_365, x.mediana_365]) };
  }
  function movimiento(c5, price, moneda = 'BTC') {
    if (c5.length < 300) return null;
    const af = 2 / 21, as = 2 / 201;
    let ef = null, es = null;
    const serie = [];
    for (const b of c5) {
      const r = (b[2] - b[3]) / b[4], v = r * r;
      ef = ef === null ? v : ef + af * (v - ef);
      es = es === null ? v : es + as * (v - es);
      serie.push(es > 0 ? Math.sqrt(ef / es) : 1);
    }
    const vol = serie[serie.length - 1], rangos = [];
    for (let j = c5.length - 13; j >= 0 && rangos.length < 720; j -= 12) {
      let hi = -Infinity, lo = Infinity;
      for (let k = j + 1; k < j + 13; k++) { hi = Math.max(hi, c5[k][2]); lo = Math.min(lo, c5[k][3]); }
      rangos.push((hi - lo) / c5[j][4]);
    }
    rangos.sort((a, b) => a - b);
    const normal = rangos[Math.floor(rangos.length / 2)], k = MOV_CORTES.filter((x) => vol >= x).length, t = MOV_TABLA[moneda];
    if (!t) return null;     // MSTR: pocas semanas de historia, sin tabla medida (no se inventa)
    const nivel = vol < 0.8 ? 'Calma' : vol < 1.3 ? 'Normal' : vol < 1.8 ? 'Agitado' : 'Se despertó';
    return { tabla: 'movimiento', volatilidad: rnd(vol, 2), nivel, prob_fuerte: t.prob[k], prob_normal: t.base, veces: t.veces[k],
      normal_pct: rnd(normal * 100, 2), esperado_pct: rnd(normal * t.veces[k] * 100, 2), normal_usd: rp(normal * price),
      esperado_usd: rp(normal * t.veces[k] * price), despierto: vol > 1.8 && serie[serie.length - 7] <= 1.8 };
  }


  // ---------- analisis central: todo converge en 5 puntos, en cada temporalidad (ver central en analisis_btc.py) ----------
  const CENTRAL_TF = ['5m', '15m', '30m', '1h', '4h', '1d', '1w', '1M'];
  const CENTRAL_PLAZO = { '5m': '5 min', '15m': '15 min', '1h': '1 hora', '4h': '4 horas', '1d': '1 día' };
  const CENTRAL_HORAS = { '5m': 1, '15m': 1, '30m': 2, '1h': 2, '4h': 8, '1d': 24, '1w': 72, '1M': 168 };
  const nz = (x) => (x === undefined ? null : x);
  const ok = (x) => x !== null && x !== undefined;
  function central(rows, price, candles, now) {
    const pick = (t) => rows.filter((r) => r.tabla === t);
    const mv = pick('movimiento')[0] || null, hs = pick('horas')[0] || null, tm = pick('termometro')[0] || null;
    const liq = pick('liquidacion'), libros = pick('libro'), niveles = pick('nivel');
    const fu = pick('contexto').find((c) => c.clave === 'funding') || null;
    const iv = pick('contexto').find((c) => c.clave === 'opciones_iv') || null;
    const eventos = pick('evento').filter((r) => r.t && r.t > now).map((r) => r.t).sort((a, b) => a - b);
    // decision de tasa de la Fed (medir_fed.py): la hora del anuncio se movio ~3,2 veces lo normal; la direccion, ~50/50
    const fed = pick('evento').filter((r) => r.t && r.t > now && ['interest rate decision', 'fomc decision', 'interest rate fomc'].some((k) => (r.original || '').toLowerCase().includes(k))).map((r) => r.t).sort((a, b) => a - b);
    const out = [];
    for (const tf of CENTRAL_TF) {
      const marco = pick('marco').find((m) => m.tf === tf);
      if (!marco) continue;
      const nombrePlazo = CENTRAL_PLAZO[tf];
      const p = nombrePlazo ? pick('plazo').find((r) => r.plazo === nombrePlazo) || null : null;
      const ind = {};
      rows.forEach((r) => { if (r.tabla === 'indicador' && r.tf === tf) ind[r.indicador] = r; });
      const F = [], cf = (punto, lado, peso, texto) => F.push([punto, lado, peso, texto]);
      const corto = tf === '5m' || tf === '15m' || tf === '30m' || tf === '1h';
      // ----- fuerza -----
      let prob = null, base = null;
      if (mv) {
        if (tf === '4h' && ok(mv.modelo_4h)) { prob = mv.modelo_4h; base = mv.modelo_base_4h; }
        else if (corto && ok(mv.modelo_1h)) { prob = mv.modelo_1h; base = mv.modelo_base_1h; }
        else if (corto) { prob = mv.prob_fuerte; base = mv.prob_normal; }
      }
      if (ok(prob) && base) {
        const R0 = roundEven(prob), B0 = roundEven(base);
        if (prob >= 40) cf('fuerza', 1, 3, `Modelo de movimiento fuerte: ${R0}% (lo normal ${B0}%)`);
        else if (prob >= 25) cf('fuerza', 1, 2, `Modelo de movimiento fuerte: ${R0}% (lo normal ${B0}%)`);
        else if (prob >= 1.5 * base) cf('fuerza', 1, 1, `Modelo de movimiento fuerte: ${R0}%, más que lo normal (${B0}%)`);
        else if (prob <= 0.6 * base) cf('fuerza', -1, 1, `Modelo de movimiento fuerte: ${R0}%, menos que lo normal (${B0}%)`);
      }
      if (mv && corto) {
        if (mv.despierto) cf('fuerza', 1, 2, 'El mercado se despertó: la volatilidad corta pasó 1,8 veces la habitual');
        else if (mv.volatilidad >= 1.3) cf('fuerza', 1, 1, `Mercado agitado: volatilidad ${ar(mv.volatilidad, 1)}× la habitual`);
        else if (mv.volatilidad < 0.8) cf('fuerza', -1, 1, `Mercado en calma: volatilidad ${ar(mv.volatilidad, 1)}× la habitual`);
      }
      const comp = candles[tf] ? compresion(candles[tf]) : null;
      if (comp && comp.comprimida) cf('fuerza', 1, 1, `Bollinger comprimidas (entre el ${roundEven(Math.max(1, comp.percentil))}% más angosto de sus últimas 720 velas): suele venir una expansión`);
      // volatilidad implicita (solo BTC). Medido (medir_dvol.py): DVOL en su 20% mas alto de 30 dias -> 4 h siguientes fuertes 18-26% (normal 12-13%)
      if (iv && ok(iv.dvol_pct) && ['15m', '30m', '1h', '4h', '1d'].includes(tf)) {
        if (iv.dvol_pct >= 80) cf('fuerza', 1, 1, `Las opciones esperan movimiento: volatilidad implícita más alta que el ${roundEven(iv.dvol_pct)}% de 30 días`);
        else if (iv.dvol_pct <= 20) cf('fuerza', -1, 1, `Las opciones esperan calma: volatilidad implícita en el ${roundEven(iv.dvol_pct)}% más bajo de 30 días`);
      }
      const vr = ind['Volumen relativo'];
      if (vr && ok(vr.valor) && vr.valor >= 2) cf('fuerza', 1, 1, `Volumen ${ar(vr.valor, 1)} veces el promedio`);
      const adx = ind['ADX 14'];
      if (adx && ok(adx.valor) && adx.valor >= 25) cf('fuerza', 1, 0.5, `ADX ${roundEven(adx.valor)}: tendencia con fuerza`);
      if (hs && corto) {
        if (hs.ahora_f >= 1.25) cf('fuerza', 1, 1, `Hora de mucho movimiento (×${ar(hs.ahora_f, 2)} de una hora típica)`);
        else if (hs.ahora_f <= 0.7) cf('fuerza', -1, 1, `Hora tranquila (×${ar(hs.ahora_f, 2)} de una hora típica)`);
      }
      const ventana = CENTRAL_HORAS[tf] * 3600000, prox = eventos.filter((t) => t - now <= ventana);
      const proxFed = fed.filter((t) => t - now <= ventana), cortoEv = tf !== '1d' && tf !== '1w' && tf !== '1M';
      if (proxFed.length && cortoEv) cf('fuerza', 1, 3, `Decisión de la Fed dentro de ${Math.max(1, roundEven((proxFed[0] - now) / 60000))} min: esa hora se mueve ~3 veces lo normal (medido)`);
      else if (prox.length && cortoEv) cf('fuerza', 1, 2, `Dato fuerte de EE.UU. dentro de ${Math.max(1, roundEven((prox[0] - now) / 60000))} min`);
      if (corto && liq.some((x) => Math.abs(x.precio / price - 1) <= 0.01 && x.longs + x.shorts >= 5)) cf('fuerza', 1, 1, 'Liquidaciones acumuladas a menos de 1%: si llega, el movimiento se puede acelerar');
      // ----- direccion -----
      if (p) {
        const tit = rows.find((e) => e.tabla === 'explicacion' && e.plazo === nombrePlazo && e.tipo === 'titular');
        const sesgo = tit ? tit.sesgo : 'neutral';
        if (sesgo !== 'neutral') {
          const w = p.sin_ventaja || p.factor === 0 ? 1 : 3, pu = nz(p.primero_arriba);
          const txt = `Casos parecidos y aprendizaje: ${sesgo === 'alcista' ? 'sube' : 'baja'}` + (pu !== null ? ` (${roundEven(sesgo === 'alcista' ? pu : 100 - pu)}% toca primero ese lado)` : '');
          cf('direccion', sesgo === 'alcista' ? 1 : -1, w, txt);
        }
        rows.forEach((e) => {
          if (e.tabla === 'explicacion' && e.plazo === nombrePlazo && e.tipo === 'senal' && (e.sesgo === 'alcista' || e.sesgo === 'bajista')
            && !e.texto.startsWith('Indicadores de') && !e.texto.startsWith('Casos parecidos')) cf('direccion', e.sesgo === 'alcista' ? 1 : -1, 1, e.texto);
        });
      } else {
        pick('patron').forEach((x) => { if (x.tf === tf && (x.sesgo === 'alcista' || x.sesgo === 'bajista')) cf('direccion', x.sesgo === 'alcista' ? 1 : -1, 1, `${x.nombre} (${x.estado})`); });
        pick('divergencia').forEach((x) => { if (x.tf === tf && (x.tipo === 'alcista' || x.tipo === 'bajista')) cf('direccion', x.tipo === 'alcista' ? 1 : -1, 1, `Divergencia ${x.tipo} en ${x.indicador}`); });
      }
      if (p && nombrePlazo === '1 hora' && (p.coinciden === 'alcista' || p.coinciden === 'bajista'))     // medido: 54,0% contra 51,5%
        cf('direccion', p.coinciden === 'alcista' ? 1 : -1, 1, '15 min, 1 hora y 4 horas apuntan para el mismo lado (medido: acierta 54% contra 51,5%)');
      // medido (medir_direccion.py): a 1 y 4 h los indicadores de tendencia aciertan menos que una moneda (46-48%): en 4 h o
      // menos cuentan al reves (peso 1, solo el resumen); en diario o mas, a favor (sin medir)
      const r_ = marco.rating, largoTf = tf === '1d' || tf === '1w' || tf === '1M';
      if (ok(r_) && Math.abs(r_) > 0.1) {
        if (!largoTf) cf('direccion', r_ > 0 ? -1 : 1, 1, `Indicadores ${marco.rating_txt.toLowerCase()}: en las próximas horas suele corregir (medido: a favor aciertan 46–48%)`);
        else cf('direccion', r_ > 0 ? 1 : -1, 2,
          `Indicadores: ${marco.rating_txt.toLowerCase()} (medias ${marco.ma_compra}↑ ${marco.ma_venta}↓, osciladores ${marco.osc_compra}↑ ${marco.osc_venta}↓)`);
      }
      const el = marco.elliott || '', cur = marco.elliott_curso;
      if (cur && !F.some((f) => f[3].startsWith('Elliott'))) {    // el de la explicacion ya esta
        const alc = el.split(';')[0].includes('alcista');
        const sube = el.startsWith('Impulso') ? (['1', '3', '5', 'B'].includes(cur)) === alc : (cur === 'B') === alc;
        cf('direccion', sube ? 1 : -1, 1, `Elliott: onda ${cur} en curso (${el.split(';')[0].toLowerCase()})`);
      }
      [['SuperTrend (10,3)', 'SuperTrend'], ['Nube de Ichimoku', 'Nube de Ichimoku'], ['VWAP del dia', 'VWAP del día'], ['OBV', 'OBV'],
        ['Chaikin Money Flow 20', 'Chaikin'], ['Parabolic SAR', 'Parabolic SAR']].forEach(([nombre, txt]) => {
        if (!largoTf) return;                                  // en 4 h o menos dicen lo mismo que el resumen (medido: al reves)
        const x = ind[nombre];
        if (x && (x.senal === 'compra' || x.senal === 'venta')) cf('direccion', x.senal === 'compra' ? 1 : -1, 0.5,
          `${txt}: ${x.senal === 'compra' ? 'a favor de la suba' : 'a favor de la baja'}` + (x.detalle ? ` (${x.detalle})` : ''));
      });
      const bb = ind['Bandas de Bollinger %B'];
      if (bb && ok(bb.valor) && (bb.valor >= 100 || bb.valor <= 0)) cf('direccion', bb.valor >= 100 ? -1 : 1, largoTf ? 0.5 : 1,   // medido: vuelve adentro 56-59%
        `Precio ${bb.valor >= 100 ? 'arriba de la banda superior' : 'debajo de la banda inferior'} de Bollinger: suele volver adentro`);
      let arriba = 0, abajo = 0;
      liq.forEach((x) => { if (x.precio / price - 1 > 0 && x.precio / price - 1 <= 0.03) arriba += x.shorts; if (1 - x.precio / price > 0 && 1 - x.precio / price <= 0.03) abajo += x.longs; });
      if (arriba + abajo >= 10) {
        if (arriba >= 1.5 * abajo) cf('direccion', 1, 1, `Más liquidaciones arriba (${ar(arriba, 0)} M de shorts) que abajo (${ar(abajo, 0)} M): imán hacia arriba`);
        else if (abajo >= 1.5 * arriba) cf('direccion', -1, 1, `Más liquidaciones abajo (${ar(abajo, 0)} M de longs) que arriba (${ar(arriba, 0)} M): imán hacia abajo`);
      }
      if (libros.length && corto) {
        let d = 0; libros.forEach((x) => { d += x.desequilibrio; }); d /= libros.length;
        if (Math.abs(d) >= 15) cf('direccion', d > 0 ? 1 : -1, 0.5, `Libros de órdenes: ${d > 0 ? 'más compras' : 'más ventas'} cerca del precio (${ar(d, 0)}%)`);
      }
      const largo = tf === '4h' || tf === '1d' || tf === '1w' || tf === '1M';
      if (tm && largo) {
        const z = tm.medidor_zona, zl = z.toLowerCase();
        if (zl.includes('compra')) cf('direccion', 1, 1, `Ciclo: ${zl}`);
        else if (zl.includes('venta') || zl.includes('caro')) cf('direccion', -1, 1, `Ciclo: ${zl}`);
      }
      if (fu && ok(fu.f7) && largo) {
        if (fu.f7 < 0) cf('direccion', 1, 0.5, 'Funding negativo: hay miedo (a meses suele ser bueno)');
        else if (fu.f7 >= 0.0003) cf('direccion', -1, 0.5, 'Funding alto: hay euforia');
      }
      // ----- totales -----
      let fz = 0, dr = 0, aFavor = 0, enContra = 0;
      F.forEach((f) => { if (f[0] === 'fuerza') fz += f[1] * f[2]; else { dr += f[1] * f[2]; if (f[1] > 0) aFavor += f[2]; else enContra += f[2]; } });
      const fuerza = fz >= 4 ? 'alta' : fz >= 2 ? 'media' : 'baja';
      const lado = dr >= 2.5 ? 'sube' : dr <= -2.5 ? 'baja' : 'neutral';
      // ----- alcance y niveles -----
      let sop = null, res = null;
      niveles.forEach((n) => { if (n.precio < price && (sop === null || n.precio > sop)) sop = n.precio; if (n.precio > price && (res === null || n.precio < res)) res = n.precio; });
      const inv = p ? rows.find((e) => e.tabla === 'explicacion' && e.plazo === nombrePlazo && e.tipo === 'invalida') : null;
      // ----- riesgo -----
      const R = [], rsi = ind['RSI 14'];
      if (rsi && ok(rsi.valor) && rsi.valor >= 75) R.push(`RSI ${roundEven(rsi.valor)}: sobrecompra`);
      else if (rsi && ok(rsi.valor) && rsi.valor <= 25) R.push(`RSI ${roundEven(rsi.valor)}: sobreventa`);
      if (eventos.length && eventos[0] - now <= 24 * 3600000) R.push(`Dato fuerte de EE.UU. en ${Math.max(1, roundEven((eventos[0] - now) / 3600000))} h: el precio se mueve más`);
      if (fuerza === 'alta') R.push('Se viene movimiento fuerte: revisá stops y tamaño');
      if ((lado === 'sube' && enContra >= 0.6 * aFavor) || (lado === 'baja' && aFavor >= 0.6 * enContra)) R.push('Hay señales en contra casi tan fuertes: dirección poco firme');
      out.push({ tabla: 'central', tf, plazo: p ? nombrePlazo : null, fuerza, fuerza_puntos: fz, prob_fuerte: nz(prob), prob_normal: nz(base),
        direccion: lado, direccion_puntos: dr, a_favor: aFavor, en_contra: enContra, prob_sube: p ? nz(p.primero_arriba) : null,
        rango_min: p ? p.min : null, rango_max: p ? p.max : null, hasta: p ? p.hora : null, obj_arriba: p ? p.obj_arriba : null, obj_abajo: p ? p.obj_abajo : null,
        toca_arriba: p ? nz(p.toca_arriba) : null, toca_abajo: p ? nz(p.toca_abajo) : null, esperado_usd: mv && corto ? mv.esperado_usd : null,
        elliott_objetivo: nz(marco.elliott_objetivo), soporte: sop, resistencia: res, invalida: inv ? inv.texto : null, riesgo: R, factores: F });
    }
    return out;
  }
  // ---------- cuando se mueve: horas de la semana (como perfil_horas de analisis_btc.py) ----------
  // Medido con BTC (medir_fuerza.py): la forma se mantiene (2021-24 contra 2025-26: correlacion 0,93); las 20 franjas mas
  // movidas segun 2021-24 se movieron 1,5 veces lo de una hora tipica en 2025-26 (las 20 menos: 0,48).
  const HORAS_N = 24 * 365, HORAS_MIN = 24 * 7 * 8;
  const mediana = (xs) => { const s = xs.slice().sort((a, b) => a - b), n = s.length; return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2; };
  function perfilHoras(c1h) {
    if (!c1h || c1h.length < HORAS_MIN) return null;
    const bars = c1h.slice(-HORAS_N), H_ = 3600000, S_ = 7 * 86400000, suma = new Map(), cuenta = new Map();
    for (const b of bars) { const w = Math.floor(b[0] / S_); suma.set(w, (suma.get(w) || 0) + (b[2] - b[3]) / b[1]); cuenta.set(w, (cuenta.get(w) || 0) + 1); }
    const franjas = Array.from({ length: 168 }, () => []);
    const fr = (t) => (Math.floor(t / H_) % 24) + 24 * ((Math.floor(t / 86400000) + 3) % 7);
    for (const b of bars) {
      const w = Math.floor(b[0] / S_), m = suma.get(w) / cuenta.get(w);
      if (m > 0) franjas[fr(b[0])].push((b[2] - b[3]) / b[1] / m);
    }
    const med = franjas.map((f) => (f.length ? mediana(f) : null)), vals = med.filter((x) => x !== null);
    if (vals.length < 168) return null;
    let s = 0; for (const x of vals) s += x;
    const prom = s / vals.length, t0 = bars[bars.length - 1][0] + H_, prox = [];
    for (let k = 0; k < 24; k++) { const t = t0 + k * H_; prox.push([t, rnd(med[fr(t)] / prom, 2)]); }
    let mx = prox[0], mn = prox[0];
    for (const p of prox) { if (p[1] > mx[1]) mx = p; if (p[1] < mn[1]) mn = p; }
    return { tabla: 'horas', proximas: prox, max_t: mx[0], max_f: mx[1], min_t: mn[0], min_f: mn[1], ahora_f: prox[0][1], corr: 0.93, top_x: 1.5 };
  }

  // ---------- compresion de las Bollinger (velas de 1 hora cerradas; ver compresion en analisis_btc.py) ----------
  // Medido con BTC 2021-2026 (medir_compresion.py): con el ancho entre el 10% mas angosto de 30 dias, el rango de las 24 h
  // siguientes fue en mediana 1,6-1,7 veces el de las 24 h anteriores y mas del doble el 32-43% de las veces (una hora
  // cualquiera: x1,0 y 12-15%). Contra lo habitual de largo plazo, las horas siguientes son MAS tranquilas: el movimiento
  // sale de una base muy chica. No dice para donde. En el modelo de movimiento fuerte no mejoro (ya lo ve por la volatilidad).
  const COMP_N = 720, COMP_CORTE = 10;
  function compresion(c1h) {
    if (!c1h || c1h.length < COMP_N + 20) return null;
    const ancho = [];
    for (let i = c1h.length - COMP_N; i < c1h.length; i++) {
      let s = 0, s2 = 0;
      for (let k = i - 19; k <= i; k++) { s += c1h[k][4]; s2 += c1h[k][4] * c1h[k][4]; }
      const mu = s / 20, sd = Math.sqrt(Math.max(0, s2 / 20 - mu * mu));
      ancho.push(4 * sd / mu);
    }
    const hoy = ancho[ancho.length - 1], pct = (ancho.filter((x) => x < hoy).length / ancho.length) * 100;
    let hi = -Infinity, lo = Infinity;
    for (let k = c1h.length - 24; k < c1h.length; k++) { hi = Math.max(hi, c1h[k][2]); lo = Math.min(lo, c1h[k][3]); }
    return { tabla: 'compresion', ancho_pct: rnd(hoy * 100, 2), percentil: rnd(pct, 1), comprimida: pct <= COMP_CORTE,
      rango_24h: rp(hi - lo), expande: 1.6, mas_doble: 40, mas_doble_normal: 13 };
  }

  // ---------- volatilidad prevista (ver vol_escala en analisis_btc.py) ----------
  const VOL_RAPIDA = 20, VOL_LENTA = 200, VOL_PESO = 0.5, VOL_MIN_FRANJA = 20;
  /** Por cuanto multiplicar el movimiento de cada caso del pasado para llevarlo a la volatilidad de ahora. */
  function volEscala(bars, tfMin, h, partial) {
    const n = bars.length, tfMs = tfMin * 60000, slots = tfMin < 1440 ? Math.floor(1440 / tfMin) : 1;
    const af = 2 / (VOL_RAPIDA + 1), as = 2 / (VOL_LENTA + 1);
    let ef = null, es = null, tm = 0, tc = 0, sNow = null;
    const sm = new Array(slots).fill(0), sc = new Array(slots).fill(0), S = new Array(n).fill(0);
    const now = partial && n > 1 ? n - 2 : n - 1;
    const franjas = (desde) => {
      if (slots === 1 || !tc) return 1;
      const k0 = Math.floor(bars[desde][0] / tfMs);
      let acc = 0;
      for (let k = 1; k <= h; k++) { const x = (k0 + k) % slots; acc += sc[x] >= VOL_MIN_FRANJA ? (sm[x] / sc[x]) / (tm / tc) : 1; }
      return acc / h;
    };
    for (let i = 0; i < n; i++) {
      const r = (bars[i][2] - bars[i][3]) / bars[i][4], v = r * r;
      ef = ef === null ? v : ef + af * (v - ef);
      es = es === null ? v : es + as * (v - es);
      const base = Math.sqrt(VOL_PESO * ef + (1 - VOL_PESO) * es);
      if (i <= now) { const x = Math.floor(bars[i][0] / tfMs) % slots; sm[x] += r; sc[x] += 1; tm += r; tc += 1; }
      S[i] = base * franjas(i);
      if (i === now) sNow = base * franjas(n - 1);
    }
    return S.map((x) => (x > 0 ? sNow / x : 1));
  }
  function volFactor(s, h) {
    if (s.tfMin > 60) return null;      // con velas de 4 h o diarias no mejoro en la prueba con datos reales
    if (!s.vol.has(h)) s.vol.set(h, volEscala(s.bars, s.tfMin, h, s.partial));
    return s.vol.get(h);
  }

  // los retornos van en Float64Array: su sort() es numerico y mucho mas rapido que sort((a, b) => a - b), con el mismo orden
  function outcomes(closes, idxs, h, F = null) {
    let n = 0; for (const i of idxs) if (i + h < closes.length) n++;
    if (!n) return null;
    const rets = new Float64Array(n); let k = 0, up = 0;
    for (const i of idxs) if (i + h < closes.length) { const r = (closes[i + h] / closes[i] - 1) * (F ? F[i] : 1); rets[k++] = r; if (r > 0) up++; }
    rets.sort();
    return { n, up: (up / n) * 100, p10: quantile(rets, 0.1) * 100,
      p50: quantile(rets, 0.5) * 100, p90: quantile(rets, 0.9) * 100 };
  }

  // ---------- rango del 80% honesto (calibracion "conformal" con su propio pasado; ver analisis_btc.py) ----------
  const CAL_PUNTOS = 200, CAL_MIN = 60, CAL_K = [0.6, 2.0];
  const desdeIdx = (xs, v) => { let a = 0, b = xs.length; while (a < b) { const m = (a + b) >> 1; if (xs[m] < v) a = m + 1; else b = m; } return a; };
  const hastaIdx = (xs, v) => { let a = 0, b = xs.length; while (a < b) { const m = (a + b) >> 1; if (xs[m] <= v) a = m + 1; else b = m; } return a; };
  /** [[vela, puntaje]] de las ultimas `puntos` predicciones del pasado: donde termino el precio, en anchos de rango. */
  /** Velas de cada situacion (con 4, 3, 2 y 1 rasgos), en orden. No depende del horizonte: una vez por receta. */
  function rangoGrupos(st, warmup, jMax) {
    const grupos = new Map();
    for (let i = warmup; i <= jMax; i++) {
      const e = st[i];
      if (!e) continue;
      let k = '';
      for (let keep = 1; keep <= 4; keep++) {         // la misma clave que e.slice(0, keep).join(',')
        if (keep <= e.length) k = keep === 1 ? String(e[0]) : `${k},${e[keep - 1]}`;
        const key = `${keep}|${k}`, g = grupos.get(key);
        if (g) g.push(i); else grupos.set(key, [i]);
      }
    }
    return grupos;
  }
  function rangoPuntajes(closes, st, F, h, warmup, jMax, puntos = CAL_PUNTOS, ventana = null, gruposHechos = null) {
    const grupos = gruposHechos || rangoGrupos(st, warmup, jMax);
    const out = [];
    for (let j = jMax; j >= warmup && out.length < puntos; j -= h) {
      const e = st[j];
      if (!e) continue;
      const desde = ventana ? Math.max(warmup, j - ventana) : warmup;
      let lst = [], a = 0, b = 0;
      for (const keep of [4, 3, 2, 1]) {           // como similar(): la situacion mas completa con casos suficientes
        lst = grupos.get(`${keep}|${e.slice(0, keep).join(',')}`) || [];
        a = desdeIdx(lst, desde); b = hastaIdx(lst, j - h);
        if (b - a >= MIN_SAMPLES) break;
      }
      if (b - a < 10) continue;
      const fj = F ? F[j] : 1, rets = new Float64Array(b - a);
      for (let q = a; q < b; q++) { const i = lst[q]; rets[q - a] = (closes[i + h] / closes[i] - 1) * (F ? F[i] / fj : 1); }
      rets.sort();
      const q10 = quantile(rets, 0.1), q50 = quantile(rets, 0.5), q90 = quantile(rets, 0.9);
      const r = closes[j + h] / closes[j] - 1, ancho = r >= q50 ? q90 - q50 : q50 - q10;
      if (ancho > 0) out.push([j, Math.abs(r - q50) / ancho]);
    }
    return out;
  }
  /** El factor que deja adentro al 80% (entre CAL_K) y cuantas veces el rango sin ajustar acerto (en %). */
  function rangoFactor(puntajes) {
    if (!puntajes.length) return { k: 1, cobertura: null, casos: 0 };
    const xs = puntajes.map((p) => p[1]).sort((a, b) => a - b);
    const cob = (xs.filter((x) => x <= 1).length / xs.length) * 100;
    if (xs.length < CAL_MIN) return { k: 1, cobertura: cob, casos: xs.length };
    return { k: Math.min(CAL_K[1], Math.max(CAL_K[0], quantile(xs, 0.8))), cobertura: cob, casos: xs.length };
  }
  /** rangoFactor de una temporalidad, una receta y un horizonte (una sola vez por analisis). Con velas de 4 h o
   *  diarias no mejoro en la medicion (medir_contexto.py): ahi solo se mide (k = 1). */
  // solo depende de las velas cerradas: se recalcula cuando cierra una nueva (como el aprendizaje)
  const CAL_CACHE = new Map();
  function calibracion(s, receta, h) {
    const key = `${receta}|${h}`;
    if (!s.cal.has(key)) {
      const last = s.closes.length - (s.partial ? 2 : 1), c = s.closed[s.closed.length - 1];
      const clave = `${s.tfMs}|${key}`, sello = `${s.closed.length}|${c[0]}|${c[4]}|${s.warmup}`;   // con el precio: BTC y ZEC tienen las mismas horas
      const hit = CAL_CACHE.get(clave);
      let cal;
      if (hit && hit[0] === sello) cal = hit[1];
      else {
        if (!s.grupos) s.grupos = new Map();
        if (!s.grupos.has(receta)) { const st = Apr.estados(s.feats, receta); s.grupos.set(receta, [st, rangoGrupos(st, s.warmup, last)]); }
        const [st, gr] = s.grupos.get(receta);
        cal = rangoFactor(rangoPuntajes(s.closes, st, volFactor(s, h), h, s.warmup, last - h, CAL_PUNTOS, null, gr));
        if (s.tfMin > 60) cal.k = 1;
        CAL_CACHE.set(clave, [sello, cal]);
      }
      s.cal.set(key, cal);
    }
    return s.cal.get(key);
  }

  /** Camino tipico/alcista/bajista: el camino real mas parecido a la mediana y a los percentiles 75/25. */
  function scenarios(bars, idxs, price, tfMs, F = null, ancho = 1) {
    const closes = bars.map((b) => b[4]);
    const usable = idxs.filter((j) => j + SCENARIO_STEPS < bars.length);
    if (usable.length < 10) return [[], []];
    const paths = new Map(usable.map((j) => {
      const p = [];
      for (let k = 1; k <= SCENARIO_STEPS; k++) p.push((closes[j + k] / closes[j] - 1) * (F ? F[j] : 1));
      return [j, p];
    }));
    const cols = [];
    for (let k = 0; k < SCENARIO_STEPS; k++) cols.push([...paths.values()].map((p) => p[k]).sort((a, b) => a - b));
    const q = (p) => cols.map((c) => quantile(c, p));
    const targets = [['tipico', q(0.5)], ['alcista', q(0.75)], ['bajista', q(0.25)]];
    const t0 = bars[bars.length - 1][0];
    const candles = [], cone = [];
    targets.forEach(([name, target]) => {
      let best = null, bestD = Infinity;
      paths.forEach((p, j) => {
        let d = 0;
        p.forEach((x, k) => { d += Math.abs(x - target[k]); });
        if (d < bestD) { bestD = d; best = j; }
      });
      const base = closes[best], fj = F ? F[best] : 1;
      const z = (x) => price * (1 + (x / base - 1) * fj);     // el camino real, al precio y la volatilidad de ahora
      for (let k = 1; k <= SCENARIO_STEPS; k++) {
        const [, o, h, l, c] = bars[best + k];
        candles.push({ tabla: 'escenario', tf: null, escenario: name, paso: k, t: t0 + k * tfMs,
          o: rp(z(o)), h: rp(z(h)), l: rp(z(l)), c: rp(z(c)), desde: utcDate(bars[best][0]) });
      }
    });
    const p10 = q(0.1), p50 = q(0.5), p90 = q(0.9);
    for (let k = 0; k < SCENARIO_STEPS; k++) {
      // el cono, ensanchado o angostado alrededor de la mediana con el ajuste del rango (calibracion)
      cone.push({ tabla: 'cono', tf: null, paso: k + 1, t: t0 + (k + 1) * tfMs,
        p10: rp(price * (1 + p50[k] - ancho * (p50[k] - p10[k]))), p50: rp(price * (1 + p50[k])), p90: rp(price * (1 + p50[k] + ancho * (p90[k] - p50[k]))) });
    }
    return [candles, cone];
  }

  /** Probabilidad de TOCAR precios redondos antes de 'when', y precio mas probable a esa hora. */
  function targets(bars, idxs, price, h, when, f = 1, unitIn = null, pfAp = null, F = null) {
    const usable = idxs.filter((j) => j + h < bars.length);
    if (usable.length < 10) return [[], null];
    const c = bars.map((b) => b[4]);
    const v = (j) => (F ? F[j] : 1);      // cada caso, a la volatilidad de ahora
    const highs = usable.map((j) => { let m = -Infinity; for (let k = j + 1; k <= j + h; k++) m = Math.max(m, bars[k][2]); return (m / c[j] - 1) * v(j); });
    const lows = usable.map((j) => { let m = Infinity; for (let k = j + 1; k <= j + h; k++) m = Math.min(m, bars[k][3]); return (m / c[j] - 1) * v(j); });
    const ends = Float64Array.from(usable, (j) => (c[j + h] / c[j] - 1) * v(j)).sort();
    const q = (p) => quantile(ends, p);
    const spread = (q(0.9) - q(0.1)) * price;
    // la distancia la fija el aprendizaje (es la que viene midiendo); si no hay, la de los casos parecidos
    const unit = unitIn || NICE_STEPS.reduce((best, s) => (Math.abs(s - spread / 4) < Math.abs(best - spread / 4) ? s : best));
    const rows = [];
    // el primer nivel de cada lado queda al menos a medio escalon: uno pegado al precio se toca siempre
    const firstUp = (Math.floor((price + unit / 2) / unit) + 1) * unit;
    const firstDn = Math.floor((price - unit / 2) / unit) * unit;
    for (let k = 0; k < 4; k++) {
      [['arriba', firstUp + k * unit], ['abajo', firstDn - k * unit]].forEach(([side, level]) => {
        const rel = level / price - 1;
        const hits = side === 'arriba' ? highs.filter((x) => x >= rel).length : lows.filter((x) => x <= rel).length;
        rows.push({ precio: level, lado: side, prob: rnd((hits / usable.length) * 100, 1) });
      });
    }
    // cual se toco PRIMERO entre dos niveles A LA MISMA DISTANCIA del precio (precio +/- un escalon)
    const q10 = unit >= 10 ? 10 : unit / 10;      // criptos de precio chico: a la decima parte del escalon
    const upLvl = unit >= 10 ? roundEven((price + unit) / 10) * 10 : roundEven((price + unit) / q10) * q10;
    const dnLvl = unit >= 10 ? roundEven((price - unit) / 10) * 10 : roundEven((price - unit) / q10) * q10;
    const rel = unit / price;
    const first = [];
    usable.forEach((j) => {
      for (let k = 1; k <= h; k++) {
        const a = (bars[j + k][2] / c[j] - 1) * v(j) >= rel, b = (bars[j + k][3] / c[j] - 1) * v(j) <= -rel;
        if (a || b) { first.push(a && b ? 0.5 : a ? 1 : 0); break; }
      }
    });
    const pf = first.length ? first.reduce((s, x) => s + x, 0) / first.length : null;
    const close = {
      mediana: rp(price * (1 + q(0.5))), p25: rp(price * (1 + q(0.25))), p75: rp(price * (1 + q(0.75))), hora: when,
      obj_arriba: upLvl, obj_abajo: dnLvl, distancia: unit,
      toca_arriba: rnd((highs.filter((x) => x >= rel).length / usable.length) * 100, 1),
      toca_abajo: rnd((lows.filter((x) => x <= -rel).length / usable.length) * 100, 1),
      // lo que dice el equipo que aprende (o la cruda con la confianza aprendida); la cruda queda aparte
      primero_arriba: pfAp !== null ? rnd(pfAp * 100, 1) : pf === null ? null : rnd(Apr.ajustar(pf, f) * 100, 1),
      primero_crudo: pf === null ? null : rnd(pf * 100, 1),
      margen_primero: pf === null ? null : rnd(196 * Math.sqrt((pf * (1 - pf)) / first.length) * f, 1),
      ninguno: rnd((1 - first.length / usable.length) * 100, 1),
    };
    return [rows, close];
  }

  const NO_CLOSE = { mediana: null, p25: null, p75: null, obj_arriba: null, obj_abajo: null, distancia: null, toca_arriba: null,
    toca_abajo: null, primero_arriba: null, primero_crudo: null, margen_primero: null, ninguno: null };

  /** Lo aprendido para predecir h velas de esta temporalidad, y los casos parecidos segun la receta aprendida. */
  function tune(tf, s, h) {
    if (s.fit.has(h)) return s.fit.get(h);
    const learn = Apr.aprendido(`${tf}|${h}`, s.closed, s.combo, h, s.warmup, s.X);
    const [pSube, pPrim] = Apr.prediccion(learn, s.combo[s.combo.length - 1], s.X[s.X.length - 1]);
    const r = learn ? learn.receta : 0;
    if (!s.similar.has(r)) s.similar.set(r, similar(Apr.estados(s.feats, r), s.last, s.warmup));
    const [idxs, keep] = s.similar.get(r);
    const fit = { learn, receta: r, factor: learn ? learn.factor : 1, idxs, keep, sample: idxs.length ? idxs : s.base, p_sube: pSube, p_primero: pPrim };
    s.fit.set(h, fit);
    return fit;
  }

  /** Que aprendio el analista para un plazo y como le fue, con la curva de aciertos a lo largo del repaso. */
  function learningRows(name, tf, h, fit) {
    const L = fit.learn || {};
    const g = (k, d) => (L[k] === undefined ? d : L[k]);
    const r2 = (k, d) => (L[k] === undefined || L[k] === null ? null : rnd(L[k], d));
    const rows = [{ tabla: 'aprendizaje', plazo: name, tf, velas: h, receta: fit.receta, receta_txt: Apr.recetaTxt(fit.receta), factor: fit.factor,
      confianza: Apr.confianzaTxt(fit.factor), repasadas: g('repasadas', 0), desde: g('desde', null), hasta: g('hasta', null), cambios: g('cambios', 0),
      distancia: g('distancia', null), medidas: g('medidas', 0),
      brier_aprendido: r2('brier_aprendido', 4), brier_original: r2('brier_original', 4),
      aciertos_aprendido: r2('aciertos_aprendido', 1), aciertos_original: r2('aciertos_original', 1),
      decisivas_aprendido: g('decisivas_aprendido', 0), decisivas_original: g('decisivas_original', 0),
      habilidad: r2('habilidad', 2), habilidad_original: r2('habilidad_original', 2),
      ic_bajo: r2('ic_bajo', 1), ic_alto: r2('ic_alto', 1), independientes: g('independientes', 0),
      aciertos_seguro: r2('aciertos_seguro', 1), decisivas_seguro: g('decisivas_seguro', 0),
      sep_arriba: r2('sep_arriba', 1), sep_abajo: r2('sep_abajo', 1), margen_sep: r2('margen_sep', 1),
      peso_modelo: L.pesos ? rnd(L.pesos[Apr.MODELO] * 100, 1) : null, peso_base: L.pesos ? rnd(L.pesos[Apr.BASE] * 100, 1) : null,
      lider: L.ranking ? Apr.expertoTxt(L.ranking[0]) : '',
      ranking: g('ranking', []).join(','), calibracion: g('calibracion', []) }];
    g('curva', []).forEach(([k, a, o]) => rows.push({ tabla: 'aprendizaje_curva', plazo: name, paso: k,
      aprendido: a === null ? null : rnd(a, 2), original: o === null ? null : rnd(o, 2) }));
    return rows;
  }

  /** Cambio % contra el precio de hace exactamente `hours` horas (cierre de la vela de 5m de ese momento). */
  function changeSince(closed5m, nowMs, price, hours) {
    const ref = nowMs - hours * HOUR_MS;
    for (let k = closed5m.length - 1; k >= 0; k--) if (closed5m[k][0] + 300000 <= ref) return pct(price, closed5m[k][4]);
    return null;
  }

  /** Todo lo que se puede decir de las proximas h velas a partir de las situaciones parecidas (ya con lo aprendido). */
  function horizonStats(tf, s, h, price, fit) {
    const sample = fit.sample, f = fit.factor;
    const F = volFactor(s, h);
    const o = outcomes(s.closes, sample, h, F), b = outcomes(s.closes, s.base, h);
    // la probabilidad de subir la da el equipo que aprende; sin historia suficiente, los casos parecidos
    const up = fit.p_sube !== null && fit.p_sube !== undefined ? fit.p_sube * 100 : f === 1 ? o.up : Apr.ajustar(o.up / 100, f) * 100;
    // contra la tasa normal moderada igual que la prediccion: si aprendio que no hay ventaja (confianza 0), es moneda
    const edge = up - (fit.p_sube !== null && fit.p_sube !== undefined ? Apr.ajustar(b.up / 100, f) * 100 : b.up);
    // margen de error del 95%: con pocos casos, una diferencia chica contra la tasa normal es ruido
    const margin = 196 * Math.sqrt(((o.up / 100) * (1 - o.up / 100)) / o.n) * f;
    const L = fit.learn || {};
    // si en su repaso honesto no le gano a la tasa base, una diferencia contra lo normal no es una ventaja: es ruido
    const sinVentaja = L.habilidad !== undefined && L.habilidad !== null && L.habilidad <= 0;
    const verdict = sinVentaja || Math.abs(edge) < Math.max(3, margin) ? 'Casi moneda' : edge > 0 ? 'Sesgo alcista' : 'Sesgo bajista';
    const whenMs = s.bars[s.bars.length - 1][0] + (h + 1) * s.tfMs;
    const when = fmtLocal(whenMs);
    const [tg, close] = targets(s.bars, sample, price, h, when, f, L.distancia === undefined ? null : L.distancia, fit.p_primero === undefined ? null : fit.p_primero, F);
    const cal = calibracion(s, fit.receta, h), k = cal.k;
    const lo = o.p50 - k * (o.p50 - o.p10), hi = o.p50 + k * (o.p90 - o.p50);
    return [{
      tf, horizonte: label(h * s.tfMin), velas: h, sube: rnd(up, 1), baja: rnd(100 - up, 1), base: rnd(b.up, 1),
      sube_crudo: rnd(o.up, 1), receta: fit.receta, factor: f,
      veredicto: verdict, sin_ventaja: sinVentaja, n: o.n, dias: s.days, hora: when, t_hasta: whenMs, margen: rnd(margin, 1), pocos_casos: o.n < 100,
      min: rp(price * (1 + lo / 100)), max: rp(price * (1 + hi / 100)),
      rango_k: rnd(k, 2), rango_cobertura: cal.cobertura === null ? null : rnd(cal.cobertura, 1), rango_casos: cal.casos, ...(close || NO_CLOSE),
    }, tg];
  }

  // liquidaciones reales de OKX (como liq_reales de analisis_btc.py): contexto y barridas, sin peso en las probabilidades
  const BARRIDA_USD = 2000000;
  function liqReales(det, now) {
    const suma = (lado, mins) => det.reduce((a, [t, s, u]) => a + (s === lado && t >= now - mins * 60000 ? u : 0), 0);
    const l60 = suma('long', 60), s60 = suma('short', 60), l15 = suma('long', 15), s15 = suma('short', 15);
    const barrida = l15 >= BARRIDA_USD && l15 > 3 * s15 ? 'longs' : s15 >= BARRIDA_USD && s15 > 3 * l15 ? 'shorts' : null;
    const m = (x) => ar(x / 1e6, x < 1e7 ? 1 : 0);
    const det_ = barrida ? `Barrida de ${barrida}: ${m(barrida === 'longs' ? l15 : s15)} M USD liquidados en 15 min solo en OKX. Suele pasar en movimientos bruscos y a veces marca el final del tirón.`
      : l60 > 2 * s60 && l60 > 2e5 ? 'Más longs liquidados: el precio barrió stops abajo' : s60 > 2 * l60 && s60 > 2e5 ? 'Más shorts liquidados: el precio barrió stops arriba' : 'Sin barridas';
    return { tabla: 'contexto', clave: 'liq_reales', titulo: 'Liquidaciones reales 1 h (OKX)', valor: `longs ${m(l60)} M · shorts ${m(s60)} M USD`, senal: 'neutral', detalle: det_,
      longs_1h: rnd(l60), shorts_1h: rnd(s60), longs_15m: rnd(l15), shorts_15m: rnd(s15), barrida };
  }
  // perpetuo contra spot (como base_perp de analisis_btc.py): contexto, sin peso en las probabilidades
  const BASE_ALTA = 0.05, BASE_BAJA = -0.07;
  function basePerp(mark, index, fuente) {
    const b = (mark / index - 1) * 100;
    const [sig, det] = b >= BASE_ALTA ? ['bajista', 'Perpetuo caro contra el spot: compras apalancadas, calentamiento']
      : b <= BASE_BAJA ? ['alcista', 'Perpetuo con descuento: ventas apalancadas o coberturas, miedo'] : ['neutral', 'Perpetuo y spot parejos'];
    return { tabla: 'contexto', clave: 'base_perp', titulo: `Perpetuo vs spot (${fuente})`, valor: arp(b, 3), senal: sig,
      detalle: `${det}. Es contexto: no entra en las probabilidades.`, base: rnd(b, 4) };
  }

  // ---------- opciones de BTC (Deribit; como opciones() de analisis_btc.py): contexto ----------
  const MESES_EN = Object.fromEntries('JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC'.split(' ').map((m, i) => [m, i]));
  function vence(nombre) {          // BTC-13NOV26-83000-P -> [ms del vencimiento (08:00 UTC), strike, 'C' o 'P']
    const p = String(nombre).split('-');
    if (p.length !== 4) return null;
    const d = p[1], dia = parseInt(d.slice(0, -5), 10), mes = MESES_EN[d.slice(-5, -2)], anio = 2000 + parseInt(d.slice(-2), 10), k = parseFloat(p[2]);
    if (Number.isNaN(dia) || mes === undefined || Number.isNaN(anio) || Number.isNaN(k)) return null;
    return [Date.UTC(anio, mes, dia, 8), k, p[3]];
  }
  function opciones(libro, dvol, precio, ahoraMs) {
    const rows = [];
    const add = (key, title, value, detail, num = {}) => rows.push({ tabla: 'contexto', clave: key, titulo: title, valor: value, senal: 'neutral', detalle: detail, ...num });
    const dv = dvol.slice().sort((a, b) => a[0] - b[0]).map((x) => x[1]);
    if (dv.length >= 25) {
      const ahora = dv[dv.length - 1], antes = dv[dv.length - 25], pc = (dv.filter((v) => v < ahora).length / dv.length) * 100;
      add('opciones_iv', 'Volatilidad implícita (DVOL)', `${ar(ahora, 1)} (24 h ${arp(ahora - antes, 1).replace('%', '')})`,
        `Lo que las opciones esperan que se mueva BTC: ≈ ±${ar(ahora / Math.sqrt(365), 1)}% por día. Más alta que el ${ar(pc)}% de los últimos 30 días. Alta: miedo o coberturas; baja: calma.`,
        { dvol: rnd(ahora, 2), dvol_24h: rnd(ahora - antes, 2), dvol_pct: rnd(pc, 1) });
    }
    const ops = [];
    libro.forEach((o) => {
      const v = vence(o.instrument_name || '');
      if (v && v[0] > ahoraMs && (o.open_interest || 0) > 0) ops.push([v[0], v[1], v[2], +o.open_interest, o.mark_iv]);
    });
    if (!ops.length || precio <= 0) return rows;
    const suma = (xs, tipo) => xs.reduce((a, x) => a + (x[2] === tipo ? x[3] : 0), 0);
    const oiC = suma(ops, 'C'), oiP = suma(ops, 'P');
    const viernes = [...new Set(ops.filter((x) => new Date(x[0]).getUTCDay() === 5).map((x) => x[0]))].sort((a, b) => a - b);
    if (viernes.length) {
      const vto = viernes[0], vs = ops.filter((x) => x[0] === vto), vc = suma(vs, 'C'), vp = suma(vs, 'P');
      const strikes = [...new Set(vs.map((x) => x[1]))].sort((a, b) => a - b);
      const dolorDe = (K) => vs.reduce((a, x) => a + x[3] * (x[2] === 'C' ? Math.max(0, K - x[1]) : Math.max(0, x[1] - K)), 0);
      let dolor = strikes[0], mejor = dolorDe(dolor);
      strikes.forEach((K) => { const v = dolorDe(K); if (v < mejor) { mejor = v; dolor = K; } });
      const cuando = fmtLocal(vto);
      if (oiC > 0) add('opciones_pc', 'Opciones: puts / calls', `${ar(oiP / oiC, 2)} (vence ${cuando.slice(0, 5)}: ${vc ? ar(vp / vc, 2) : '—'})`,
        'Contratos abiertos de puts por cada call. Más de 1: coberturas o apuestas a la baja; menos: apuestas a la suba.',
        { ratio: rnd(oiP / oiC, 3), ratio_vto: vc ? rnd(vp / vc, 3) : null });
      add('opciones_dolor', `Dolor máximo (vence ${cuando} h)`, `${ap(dolor)} (${arp(pct(dolor, precio), 1)})`,
        'El precio donde más opciones de ese viernes vencen sin valor. Cerca del vencimiento a veces atrae al precio.',
        { precio: dolor, vence: vto, distancia: rnd(pct(dolor, precio), 2) });
    }
    // sesgo: puts 5-15% abajo contra calls 5-15% arriba, en el primer vencimiento a 7 dias o mas
    const lejos = [...new Set(ops.filter((x) => x[0] - ahoraMs >= 7 * DAY_MS).map((x) => x[0]))].sort((a, b) => a - b);
    if (lejos.length) {
      const vs = ops.filter((x) => x[0] === lejos[0] && x[4]);
      const ivp = vs.filter((x) => x[2] === 'P' && x[1] >= 0.85 * precio && x[1] <= 0.95 * precio).map((x) => x[4]);
      const ivc = vs.filter((x) => x[2] === 'C' && x[1] >= 1.05 * precio && x[1] <= 1.15 * precio).map((x) => x[4]);
      if (ivp.length && ivc.length) {
        const sk = ivp.reduce((a, x) => a + x, 0) / ivp.length - ivc.reduce((a, x) => a + x, 0) / ivc.length;
        add('opciones_sesgo', 'Opciones: puts vs calls (IV)', `${sk > 0 ? '+' : ''}${ar(sk, 1)} puntos`,
          'Volatilidad implícita de los puts 5-15% abajo menos la de los calls 5-15% arriba (vencimiento a 7 días o más). Positivo: pagan más por protegerse de una baja.',
          { sesgo: rnd(sk, 2) });
      }
    }
    return rows;
  }

  // ---------- contexto actual (como analisis_btc.py; en el navegador las fuentes son Bybit, Bitget y Binance) ----------
  function context(raw, h1) {
    const rows = [];
    const add = (key, title, value, signal, detail, num = {}) => rows.push({ tabla: 'contexto', clave: key, titulo: title, valor: value, senal: signal, detalle: detail, ...num });
    const closes1h = h1.map((b) => b[4]);
    if (raw.oi) {   // open interest en monedas: se pasa a USD con el cierre de cada hora
      const closeAt = new Map(h1.map((b) => [b[0] + HOUR_MS, b[4]]));
      const oi = raw.oi.filter((x) => closeAt.has(x[0])).map((x) => x[1] * closeAt.get(x[0]));
      if (oi.length > 25) {
        [1, 4, 24].forEach((hrs) => {
          const dOi = pct(oi[oi.length - 1], oi[oi.length - 1 - hrs]);
          const dPx = pct(closes1h[closes1h.length - 1], closes1h[closes1h.length - 1 - hrs]);
          let why, sig;
          if (Math.abs(dOi) < 0.5) [why, sig] = ['Posicionamiento estable', 'neutral'];
          else if (dPx >= 0) [why, sig] = dOi > 0 ? ['Entran longs nuevos: suba con fuerza', 'alcista'] : ['Cierran shorts: suba sin dinero nuevo', 'neutral'];
          else [why, sig] = dOi > 0 ? ['Entran shorts nuevos: baja con fuerza', 'bajista'] : ['Cierran o liquidan longs: baja por descarga', 'neutral'];
          add(`oi_${hrs}h`, `Open interest ${hrs} h`, `${arp(dOi)} con precio ${arp(dPx)}`, sig, why, { d_oi: rnd(dOi, 2), d_px: rnd(dPx, 2) });
        });
      }
    }
    if (raw.taker && raw.taker.length) {
      const last = raw.taker[raw.taker.length - 1];
      const buy = raw.taker.reduce((s, x) => s + x.buy, 0), sell = raw.taker.reduce((s, x) => s + x.sell, 0);
      [['1 h', last.buy / last.sell], ['4 h', buy / sell]].forEach(([name, r]) => {
        const sig = r > 1.1 ? 'alcista' : r < 0.9 ? 'bajista' : 'neutral';
        add(`flujo_${name}`, `Compras vs ventas a mercado ${name}`, ar(r, 2), sig,
          sig === 'alcista' ? 'Dominan los compradores agresivos' : sig === 'bajista' ? 'Dominan los vendedores agresivos' : 'Flujo equilibrado', { ratio: rnd(r, 3) });
      });
    }
    if (raw.ls && raw.ls.length) {
      const nowLs = raw.ls[raw.ls.length - 1], prevLs = raw.ls[0];
      let crowd, sig;
      if (nowLs > 2) [crowd, sig] = ['Mayoría long: si cae, puede haber cascada de liquidaciones', 'bajista'];
      else if (nowLs < 0.9) [crowd, sig] = ['Mayoría short: si sube, puede haber squeeze', 'alcista'];
      else [crowd, sig] = ['Posicionamiento parejo', 'neutral'];
      const top = raw.top == null || Number.isNaN(raw.top) ? '' : `, top traders ${ar(raw.top, 2)}`;
      add('long_short', 'Cuentas long / short', `${ar(nowLs, 2)} (24 h antes ${ar(prevLs, 2)}${top})`, sig, crowd);
    }
    if (raw.base) rows.push(basePerp(raw.base.mark, raw.base.index, 'Bybit'));
    if (raw.liq) rows.push(liqReales(raw.liq, raw.liqT));
    if (raw.funding == null || Number.isNaN(raw.funding)) return [rows, null];
    const fr = raw.funding, f7 = raw.funding7 == null || Number.isNaN(raw.funding7) ? null : raw.funding7;
    add('funding', `Funding ${raw.fundingFuente || 'BingX'}`, arp(fr * 100, 4) + ' cada 8 h' + (f7 === null ? '' : ` (7 días ${arp(f7 * 100, 4)})`), fr > 0.0003 ? 'bajista' : fr < 0 ? 'alcista' : 'neutral',
      fr > 0.0003 ? 'Longs pagando caro: euforia' : fr < 0 ? 'Shorts pagan: miedo' : 'Normal', f7 === null ? {} : { f7 });
    return [rows, fr];
  }

  const BOOK_BAND = 0.001;     // +/-0.1%: el rango que cubren todos los libros publicos
  const WALL_BIN = 25;         // USD por escalon al buscar muros

  /** Ordenes limite esperando en los libros: desequilibrio por exchange y libros sumados para buscar muros. */
  function books(raw) {
    const per = [], mergedBids = new Map(), mergedAsks = new Map(), rows = [];
    raw.forEach(({ name, bids, asks }) => {
      if (!bids.length || !asks.length) return;
      const mid = (bids[0][0] + asks[0][0]) / 2;
      const b = bids.filter(([p]) => p >= mid * (1 - BOOK_BAND)).reduce((s, [, q]) => s + q, 0);
      const a = asks.filter(([p]) => p <= mid * (1 + BOOK_BAND)).reduce((s, [, q]) => s + q, 0);
      const wallB = bids.reduce((m, x) => (x[1] > m[1] ? x : m)), wallA = asks.reduce((m, x) => (x[1] > m[1] ? x : m));
      rows.push({ tabla: 'libro', exchange: name, compras: rnd(b, 2), ventas: rnd(a, 2), desequilibrio: b + a ? rnd(((b - a) / (b + a)) * 100, 1) : 0,
        muro_compra: wallB[0], muro_compra_btc: rnd(wallB[1], 2), muro_venta: wallA[0], muro_venta_btc: rnd(wallA[1], 2), en_total: true });
      per.push([b, a]);
      [[mergedBids, bids], [mergedAsks, asks]].forEach(([side, src]) => src.forEach(([p, q]) => {
        const k = roundEven(p / WALL_BIN) * WALL_BIN;
        side.set(k, (side.get(k) || 0) + q);
      }));
    });
    return [rows, per, mergedBids, mergedAsks];
  }

  /** Liquidaciones pendientes estimadas con open interest nuevo y ratio long/short de la ultima semana. */
  function liquidationMap(raw, h1, hours = 168) {
    const bars = h1.slice(-(hours + 2));
    const priceByHour = new Map(bars.map((b) => [b[0] + HOUR_MS, b[4]]));
    const sufLo = new Map(), sufHi = new Map();
    let lo = Infinity, hi = 0;
    for (let k = bars.length - 1; k >= 0; k--) {
      sufLo.set(bars[k][0], lo); sufHi.set(bars[k][0], hi);
      lo = Math.min(lo, bars[k][3]); hi = Math.max(hi, bars[k][2]);
    }
    const after = (t) => [sufLo.has(t - HOUR_MS) ? sufLo.get(t - HOUR_MS) : Infinity, sufHi.has(t - HOUR_MS) ? sufHi.get(t - HOUR_MS) : 0];
    // open interest de Bybit en monedas: a USD con el cierre de cada hora (como liquidation_map_bybit)
    const oi = raw.oi.filter((x) => priceByHour.has(x[0])).map((x) => [x[0], x[1] * priceByHour.get(x[0])]).slice(-hours);
    return Ind.mapaLiquidaciones(priceByHour, oi, new Map(raw.ls), after);
  }

  /** Vela en curso de cualquier temporalidad, armada con las velas de 5m desde que abrio. */
  function formingFrom5m(closed5m, live5m, tf, lastClosedT) {
    const start = lastClosedT + TF_MS[tf];
    const parts = closed5m.filter((c) => c[0] >= start);
    if (live5m && live5m[0] >= start) parts.push(live5m);
    if (!parts.length) return null;
    return [start, parts[0][1], Math.max(...parts.map((c) => c[2])), Math.min(...parts.map((c) => c[3])), parts[parts.length - 1][4], parts.reduce((s, c) => s + c[5], 0)];
  }

  const NO_LINES = { l1_t: null, l1_p: null, l1_m: null, l1_nombre: null, l2_t: null, l2_p: null, l2_m: null, l2_nombre: null };
  [1, 2, 3, 4, 5].forEach((k) => ['t', 'p', 'nombre'].forEach((f) => { NO_LINES[`pt${k}_${f}`] = null; }));

  /** Patron de velas en las ultimas dos velas (con su historial de aciertos) y figura del grafico vigente. */
  // Velas semanales y mensuales armadas con las diarias (como velas_largas / analisis_largo de analisis_btc.py).
  // Llevan grafico, indicadores, giros, Elliott, FVG, patrones y divergencias; no prediccion (pocas velas para repasarla).
  const TF_LARGOS = { '1w': 7 * 1440, '1M': 30 * 1440 };
  function inicioLargo(t, tf) {
    const k = Math.floor(t / 86400000);
    if (tf === '1w') return (k - ((k + 3) % 7)) * 86400000;
    const d = new Date(t); return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1);
  }
  function velasLargas(d1, tf, ultimaEnCurso = false) {
    let grupos = [];
    d1.forEach((b) => {
      const k = inicioLargo(b[0], tf), g = grupos[grupos.length - 1];
      if (g && g[0] === k) { g[2] = Math.max(g[2], b[2]); g[3] = Math.min(g[3], b[3]); g[4] = b[4]; g[5] += b[5]; }
      else grupos.push([k, b[1], b[2], b[3], b[4], b[5], b[0]]);
    });
    if (grupos.length && grupos[0][6] > grupos[0][0]) grupos = grupos.slice(1);
    if (!grupos.length) return [[], false];
    const ult = grupos[grupos.length - 1][0], sig = inicioLargo(ult + (tf === '1M' ? 32 : 7) * 86400000, tf);
    return [grupos.map((g) => g.slice(0, 6)), ultimaEnCurso || sig > d1[d1.length - 1][0] + 86400000];
  }
  // calificar solo mira la ultima vela: con las ultimas 2.000 alcanza (la media de 200 ya olvido el arranque) y en 5m-1h
  // (8.640 velas) tarda 4 veces menos. Las curvas vuelven con el largo de bars (como calificar_ultimas de Python)
  const CALIF_VELAS = 2000;
  function calificarUltimas(bars) {
    if (bars.length <= CALIF_VELAS) return Ind.calificar(bars);
    const off = bars.length - CALIF_VELAS, [rows, summary, overlays] = Ind.calificar(bars.slice(off)), ov = {};
    // el OBV es acumulado: su valor (no su señal) depende de desde donde se suma; va el de toda la historia
    const ob = Ind.obv(bars.map((b) => b[4]), bars.map((b) => b[5]));
    rows.forEach((r) => { if (r.indicador === 'OBV') r.valor = rnd(ob[ob.length - 1], 2); });
    Object.entries(overlays).forEach(([k, v]) => { ov[k] = new Array(off).fill(null).concat(v); });
    return [rows, summary, ov];
  }
  function analisisLargo(d1, tf, price, ultimaEnCurso = false) {
    const [bars, partial] = velasLargas(d1, tf, ultimaEnCurso);
    if (bars.length < 30) return [];
    const tfMin = TF_LARGOS[tf], closes = bars.map((b) => b[4]);
    const [indRows, summary, overlays] = Ind.calificar(bars);
    const e20 = Ind.ema(closes, 20), e50 = Ind.ema(closes, 50), e200 = Ind.ema(closes, 200);
    const rsi = Ind.rsi(closes), [ml, ms, mh] = Ind.macd(closes), i = bars.length - 1;
    const reg = Apr.regimenes(bars, e200), pivots = Ind.zigzag(bars);
    const [waveLabels, waveDesc, waveTarget, waveNow, waveShort] = Ind.elliott(pivots, bars);
    const cross = [i, i - 1].map((k) => (mh[k] > 0 && mh[k - 1] <= 0 ? 'alcista' : mh[k] < 0 && mh[k - 1] >= 0 ? 'bajista' : null)).find((x) => x) || null;
    const rows = [{ tabla: 'marco', tf, tendencia: trendWord(closes[i], e20[i], e50[i], e200[i]), ...summary, macd_cruce: cross, ema50: rp(e50[i]),
      ema200: bars.length >= 200 ? rp(e200[i]) : null, similares: 0, criterio: '', elliott: waveDesc, elliott_objetivo: rp(waveTarget), elliott_curso: waveNow,
      elliott_corto: waveShort, regimen: reg[i] === null ? null : Apr.REGIMENES[reg[i]], velas: bars.length, sin_prediccion: true }];
    indRows.forEach((r) => rows.push({ tabla: 'indicador', tf, ...r }));
    const tail = pivots.slice(-10), offset = tail.length - waveLabels.length;
    tail.forEach(([kind, k, p], n) => rows.push({ tabla: 'giro', tf, t: bars[k][0], precio: rp(p), tipo: kind, onda: n >= offset ? waveLabels[n - offset] : '', en_curso: n === tail.length - 1 }));
    Ind.fvg(bars).forEach((z) => rows.push({ tabla: 'fvg', tf, tipo: z.tipo, t: z.t, bajo: rp(z.bajo), alto: rp(z.alto) }));
    patterns(tf, bars, pivots, e20, 3, tfMin, partial).forEach((r) => rows.push(r));
    Ind.divergencias(bars, pivots).forEach((d) => rows.push({ tabla: 'divergencia', tf, ...d, p1: rp(d.p1), p2: rp(d.p2) }));
    for (let k = Math.max(0, i - CHART_BARS + 1); k <= i; k++) {
      const [t, o, h, l, c, v] = bars[k];
      rows.push({ tabla: 'vela', tf, t, o, h, l, c, v: rnd(v, 2), en_curso: partial && k === i,
        ema20: rp(overlays.ema20[k]), ema50: rp(overlays.ema50[k]), ema200: k >= 199 ? rp(e200[k]) : null, bb_up: rp(overlays.bb_up[k]), bb_lo: rp(overlays.bb_lo[k]),
        rsi: rnd(rsi[k], 1), macd: rnd(ml[k], decPrecio(price) + 1), macd_senal: rnd(ms[k], decPrecio(price) + 1), macd_hist: rnd(mh[k], decPrecio(price) + 1) });
    }
    return rows;
  }
  function patterns(tf, bars, pivots, e20, horizon, tfMin, partial) {
    const o = bars.map((b) => b[1]), h = bars.map((b) => b[2]), l = bars.map((b) => b[3]), c = bars.map((b) => b[4]);
    const atr = Ind.atrW(h, l, c);
    const i = bars.length - 1;
    const rows = [];
    for (const k of [i, i - 1]) {
      const found = Ind.patronesVelas(o, h, l, c, atr, e20, k);
      if (!found.length) continue;
      const [name, bias] = found[0];
      const [n, ok] = Ind.estadisticaVelas(o, h, l, c, atr, e20, horizon)[name] || [0, 0];
      const rate = n ? rnd((ok / n) * 100, 1) : null;
      let desc;
      if (bias === 'neutral') desc = 'Indecisión: compradores y vendedores quedaron parejos en esa vela.';
      else if (rate === null) desc = 'Sin casos anteriores para medir si funciona en esta temporalidad.';
      else desc = `Después de este patrón, BTC fue hacia ${bias === 'alcista' ? 'arriba' : 'abajo'} en ${ar(rate)}% de ${n} casos (${label(horizon * tfMin)} después)`
        + (rate >= 55 ? ': funcionó más de lo que falló.' : rate >= 45 ? ': casi como tirar una moneda.' : ': falló más de lo que funcionó.');
      rows.push({ tabla: 'patron', tf, clase: 'vela', nombre: name, sesgo: bias, t: bars[k][0],
        estado: k === i ? (partial ? 'vela en curso' : 'última vela') : 'vela anterior', objetivo: null, exito: rate, casos: n,
        plazo: label(horizon * tfMin), descripcion: desc, ...NO_LINES });
      break;
    }
    // una figura clasica y, aparte, un esquema de Wyckoff si lo hay
    [Ind.patronGrafico(bars, pivots, atr[i]), Ind.wyckoff(bars, pivots, atr[i])].forEach((g) => {
      if (!g) return;
      const lines = { ...NO_LINES };
      g.lineas.slice(0, 2).forEach((ln, n) => Object.assign(lines, { [`l${n + 1}_t`]: ln[0], [`l${n + 1}_p`]: rp(ln[1]), [`l${n + 1}_m`]: ln[2], [`l${n + 1}_nombre`]: ln[3] }));
      g.puntos.slice(0, 5).forEach((pt, n) => Object.assign(lines, { [`pt${n + 1}_t`]: pt[0], [`pt${n + 1}_p`]: rp(pt[1]), [`pt${n + 1}_nombre`]: pt[2] }));
      rows.push({ tabla: 'patron', tf, clase: 'grafico', nombre: g.nombre, sesgo: g.sesgo, t: bars[i][0], estado: g.estado, objetivo: g.objetivo,
        exito: null, casos: null, plazo: null, descripcion: g.descripcion, ...lines });
    });
    return rows;
  }

  // plazo: [temporalidad con mas casos para ese plazo, velas, temporalidades cuyas senales pesan,
  //         datos del momento que pesan, vela que confirma o invalida]
  const PLAZOS = [
    ['5 min', '5m', 1, ['5m'], ['libros', 'flujo_1 h'], '5 min'],
    ['15 min', '5m', 3, ['5m', '15m'], ['libros', 'flujo_1 h'], '5 min'],
    ['1 hora', '5m', 12, ['15m', '1h'], ['flujo_1 h', 'flujo_4 h', 'oi_1h'], '15 min'],
    ['4 horas', '30m', 8, ['1h', '4h'], ['flujo_4 h', 'oi_4h', 'oi_24h', 'long_short'], '1 hora'],
    ['1 día', '4h', 6, ['4h', '1d'], ['oi_24h', 'long_short', 'funding'], '4 horas'],
  ];
  // Fibonacci del swing de 90 dias en 4 h (como analisis_btc.py: el unico que mostro ventaja) y su rebote medido
  const FIB_REBOTE = { 0.236: 58, 0.382: 59, 0.5: 59, 0.618: 42, 0.786: 62 };
  function fibonacci(h4, velas = 540) {
    const w = h4.slice(-velas);
    if (w.length < 100) return [];
    const hs = w.map((b) => b[2]), ls = w.map((b) => b[3]), hi = Math.max(...hs), lo = Math.min(...ls);
    const sube = hs.indexOf(hi) > ls.indexOf(lo);
    return Object.keys(FIB_REBOTE).map(Number).sort((a, b) => a - b).map((f) => [f, sube ? hi - (hi - lo) * f : lo + (hi - lo) * f]);
  }
  /** Los dos extremos del swing (como fib_tramo de analisis_btc.py): inicio (nivel 1) y fin (nivel 0). */
  function fibTramo(h4, velas = 540) {
    const w = h4.slice(-velas);
    if (w.length < 100) return null;
    const hs = w.map((b) => b[2]), ls = w.map((b) => b[3]), ih = hs.indexOf(Math.max(...hs)), il = ls.indexOf(Math.min(...ls));
    const [a, b] = ih > il ? [[w[il][0], w[il][3]], [w[ih][0], w[ih][2]]] : [[w[ih][0], w[ih][2]], [w[il][0], w[il][3]]];
    return { t_inicio: a[0], p_inicio: a[1], t_fin: b[0], p_fin: b[1] };
  }
  const SHORT_CTX = { 'flujo_1 h': 'Compras a mercado 1 h', 'flujo_4 h': 'Compras a mercado 4 h', oi_1h: 'Open interest 1 h',
    oi_4h: 'Open interest 4 h', oi_24h: 'Open interest 24 h', long_short: 'Long/short', libros: 'Libros de órdenes', funding: 'Funding' };

  // cuando 15 min, 1 hora y 4 horas van para el mismo lado (como coinciden de analisis_btc.py; medido 2023-2026)
  const COINCIDEN = { si: 54.0, no: 51.5 };
  function coinciden(rows) {
    const p = {}; rows.forEach((r) => { if (r.tabla === 'plazo') p[r.plazo] = r.sube; });
    const xs = ['15 min', '1 hora', '4 horas'].map((k) => p[k]);
    if (xs.some((x) => x === null || x === undefined)) return null;
    return xs.every((x) => x > 50) ? 'alcista' : xs.every((x) => x < 50) ? 'bajista' : null;
  }

  /** La conclusion de un plazo en pocas palabras: prediccion, hasta 4 razones de cada lado, niveles e invalidacion. */
  function explain(rows, price, spec) {
    const [name, , , sigTfs, ctxKeys, candle] = spec;
    const get = (t, kw = {}) => rows.filter((r) => r.tabla === t && Object.entries(kw).every(([k, v]) => r[k] === v));
    const main = get('plazo', { plazo: name })[0];
    const hh = main.hora.slice(-5);
    const signals = [];      // [prioridad, sesgo, texto corto]
    sigTfs.forEach((tf, n) => {
      const m = get('marco', { tf })[0];
      if (Math.abs(m.rating) > 0.1) signals.push([[2, 3][n], m.rating > 0 ? 'alcista' : 'bajista', `Indicadores de ${TF_TXT[tf]}: ${m.rating_txt.toLowerCase()}`]);
    });
    // RSI y MACD de cada temporalidad, como los mira un trader
    sigTfs.forEach((tf) => {
      const m = get('marco', { tf })[0];
      if (m.rsi >= 70) signals.push([4, 'bajista', `RSI de ${TF_TXT[tf]} en sobrecompra (${ar(m.rsi)})`]);
      else if (m.rsi <= 30) signals.push([4, 'alcista', `RSI de ${TF_TXT[tf]} en sobreventa (${ar(m.rsi)})`]);
      if (m.macd_cruce) signals.push([4, m.macd_cruce, `MACD de ${TF_TXT[tf]} cruzó ${m.macd_cruce === 'alcista' ? 'al alza' : 'a la baja'}`]);
    });
    get('patron').forEach((p) => {
      if (!sigTfs.includes(p.tf) || p.sesgo === 'neutral') return;
      const target = p.objetivo ? ` → ${ap(p.objetivo)}` : '';
      if (p.clase === 'grafico') signals.push([p.estado === 'confirmado' ? 1 : 4, p.sesgo, `${p.nombre} en ${TF_TXT[p.tf]}${target}`]);
      else if (p.exito !== null && p.exito >= 55 && p.casos >= 20) signals.push([5, p.sesgo, `${p.nombre} en ${TF_TXT[p.tf]} (funcionó ${ar(p.exito)}%)`]);
    });
    const divs = new Map();
    get('divergencia').forEach((d) => {
      if (!sigTfs.includes(d.tf)) return;
      const k = `${d.tf}|${d.tipo}`;
      if (!divs.has(k)) divs.set(k, [d.tf, d.tipo, []]);
      divs.get(k)[2].push(d.indicador);
    });
    divs.forEach(([tf, tipo, names]) => signals.push([3, tipo, `Divergencia ${tipo} en ${names.join(' y ')} (${TF_TXT[tf]})`]));
    get('contexto').forEach((c) => {
      if ((c.senal === 'alcista' || c.senal === 'bajista') && ctxKeys.includes(c.clave)) {
        signals.push([3, c.senal, `${SHORT_CTX[c.clave]}: ${lc1(c.detalle.split('.')[0].split(':')[0])}`]);
      }
    });
    if (main.veredicto !== 'Casi moneda') {
      signals.push([2, main.veredicto === 'Sesgo alcista' ? 'alcista' : 'bajista', `Casos parecidos: cerró arriba ${ar(main.sube)}% (normal ${ar(main.base)}%)`]);
    }
    const mLast = get('marco', { tf: sigTfs[sigTfs.length - 1] })[0];
    if (mLast.elliott_objetivo) {
      signals.push([7, mLast.elliott_objetivo > price ? 'alcista' : 'bajista',
        `Elliott ${TF_TXT[sigTfs[sigTfs.length - 1]]}: ${mLast.elliott_corto.split(':')[0]} → ${ap(mLast.elliott_objetivo)}`]);
    }
    if (sigTfs.includes('4h')) {   // tocando un Fibonacci de 90 dias que rebota mas que un nivel cualquiera
      const fz = get('nivel').filter((n) => n.fib && n.rebote >= 55 && Math.abs(n.distancia) <= 0.4);
      if (fz.length) {
        const n = fz.reduce((a, b) => (Math.abs(b.distancia) < Math.abs(a.distancia) ? b : a));
        signals.push([3, n.tipo === 'soporte' ? 'alcista' : 'bajista', `En el Fibonacci ${ar(n.fib * 100, 1)}% de 90 días (${ap(n.precio)}): ahí rebotó ${n.rebote}% de las veces`]);
      }
    }
    if (main.coinciden) signals.push([2, main.coinciden, `15 min, 1 hora y 4 horas van para el mismo lado: así acertó ${ar(COINCIDEN.si, 1)}% (2023-26; ${ar(COINCIDEN.no, 1)}% cuando no)`]);
    const sma = get('nivel').find((n) => n.nombre === 'Media simple 200 días');
    if (sma && name === '1 día') {
      signals.push([6, price > sma.precio ? 'alcista' : 'bajista', price > sma.precio ? 'Arriba de la media simple de 200 días' : 'Debajo de la media simple de 200 días']);
    }
    signals.sort((a, b) => a[0] - b[0]);

    const up = main.obj_arriba, dn = main.obj_abajo, mg = main.margen_primero || 0;
    const pu = main.sin_ventaja ? null : main.primero_arriba;     // sin ventaja medida, "que toca primero" tampoco es una prediccion
    const nUp = signals.filter((s) => s[1] === 'alcista').length, nDn = signals.length - nUp;
    let bias, head;
    if (pu !== null && pu - 50 > Math.max(5, mg)) {
      bias = 'alcista';
      head = `Hasta las ${hh} h, es más probable que BTC suba a ${ap(up)} (${ar(pu)}%) antes que baje a ${ap(dn)}.`;
    } else if (pu !== null && 50 - pu > Math.max(5, mg)) {
      bias = 'bajista';
      head = `Hasta las ${hh} h, es más probable que BTC baje a ${ap(dn)} (${ar(100 - pu)}%) antes que suba a ${ap(up)}.`;
    } else {
      bias = 'neutral';
      // el rango real: donde termino el 80% de los casos parecidos (los niveles +/- un escalon se pasan seguido)
      const lo = main.min, hi = main.max;
      const rango = lo && hi ? `8 de cada 10 veces terminó entre ${ap(lo)} y ${ap(hi)}` : `lo más cerca está ${ap(dn)} o ${ap(up)}`;
      const motivo = main.sin_ventaja ? ' (en su repaso no le ganó a la tasa base)' : '';
      head = `Hasta las ${hh} h, sin dirección clara${motivo}: ${rango}.`;
    }
    const agree = bias === 'alcista' ? nUp : nDn;
    let why;
    if (!signals.length) why = 'No hay señales fuertes en este plazo.';
    else if (bias === 'neutral') why = `Las señales están repartidas: ${nUp} alcistas y ${nDn} bajistas.`;
    else if (agree * 2 > signals.length) why = `Lo acompañan ${agree} de ${signals.length} señales.`;
    else why = `Ojo: solo ${agree} de ${signals.length} señales acompañan. Convicción baja.`;

    const row = (orden, tipo, sesgo, texto, precio = null) => ({ tabla: 'explicacion', plazo: name, orden, tipo, sesgo, texto, precio });
    const out = [row(0, 'titular', bias, head), row(1, 'porque', bias, why)];
    signals.forEach(([, s, txt], k) => out.push(row(k + 2, 'senal', s, txt)));
    // niveles que importan para este plazo: ni pegados al precio ni mas cerca de lo que se mueve en ese tiempo
    const gap = Math.max(0.0015, (0.5 * (main.distancia || 0)) / price);
    const levels = get('nivel').slice().sort((a, b) => a.precio - b.precio);
    const res = levels.find((n) => n.precio > price * (1 + gap));
    const sup = levels.slice().reverse().find((n) => n.precio < price * (1 - gap));
    const k = out.length;
    if (res) out.push(row(k, 'vigilar', 'alcista', `Resistencia ${ap(res.precio)} (${lc1(res.nombre)})`, res.precio));
    if (sup) out.push(row(k + 1, 'vigilar', 'bajista', `Soporte ${ap(sup.precio)} (${lc1(sup.nombre)})`, sup.precio));
    let inval;
    if (bias === 'alcista' && sup) inval = `Si una vela de ${candle} cierra debajo de ${ap(sup.precio)}, la idea deja de valer.`;
    else if (bias === 'bajista' && res) inval = `Si una vela de ${candle} cierra arriba de ${ap(res.precio)}, la idea deja de valer.`;
    else inval = `La dirección la marca la primera vela de ${candle} que cierre fuera de ${ap(dn)} a ${ap(up)}.`;
    out.push(row(k + 2, 'invalida', bias, inval));
    out.push(row(k + 3, 'aprendizaje', bias, learningText(get('aprendizaje', { plazo: name })[0])));
    return out;
  }

  /** En una o dos frases: que aprendio para este plazo y si le esta sirviendo. */
  function learningText(a) {
    if (!a.repasadas) return 'Todavía junta experiencia para este plazo: por ahora usa el método original.';
    let txt = `Repasó sus últimas ${ar(a.repasadas)} predicciones con un equipo de expertos; hoy pesa más ${a.lider}. ${a.confianza}.`;
    const hab = a.habilidad;
    if (hab !== null) {
      if (hab >= 0.5) txt += ` Le gana a la tasa base: ${ar(hab, 1)}% menos error que decir siempre lo normal.`;
      else if (hab > -0.5) txt += ` Todavía no le gana a la tasa base en forma clara (${ar(hab, 1)}%): sus probabilidades quedan cerca de lo normal.`;
      else txt += ` Viene peor que la tasa base (${ar(hab, 1)}%): por eso modera sus probabilidades.`;
    }
    const ap = a.aciertos_aprendido, lo = a.ic_bajo, hi = a.ic_alto;
    if (ap !== null && lo !== null) txt += ` Acertó ${ar(ap)}% qué tocaba primero (con el margen de error, entre ${ar(lo)}% y ${ar(hi)}%).`;
    return txt;
  }

  /**
   * Suma las predicciones nuevas al registro y mide cuantas acertaron (solo con velas cerradas). Cada una guarda
   * tambien su rango del 80% (registros viejos: sin rango), para medir si el precio termina adentro.
   */
  function logAndScore(log, entries, closesByTf) {
    const seen = new Set(log.map((r) => `${r[0]}|${r[1]}|${r[2]}`));
    entries.forEach(([t, tf, h, p, pr, lo, hi]) => {
      if (!seen.has(`${t}|${tf}|${h}`)) log.push([t, tf, h, rp(p), rnd(pr, 1)].concat(lo === null || lo === undefined || hi === null || hi === undefined ? [] : [rp(lo), rp(hi)]));
    });
    const score = new Map();      // tf|h -> [casos, aciertos, brier, con rango, adentro del rango]
    log.forEach(([t, tf, h, p, pr, lo, hi]) => {
      const future = closesByTf[tf] && closesByTf[tf].get(t + h * TF_MS[tf]);
      if (future === undefined) return;
      const key = `${tf}|${h}`;
      const sc = score.get(key) || [0, 0, 0, 0, 0];
      score.set(key, sc);
      if (lo !== undefined && hi !== undefined) { sc[3] += 1; sc[4] += lo <= future && future <= hi ? 1 : 0; }
      const prob = pr / 100;
      if (prob === 0.5) return;
      const up = future > p;
      sc[0] += 1; sc[1] += (prob > 0.5) === up ? 1 : 0; sc[2] += (prob - (up ? 1 : 0)) ** 2;
    });
    return score;
  }

  /**
   * El analisis completo. input: { candles: {tf: velas cerradas}, live5m, price, now, ctxRaw, booksRaw, liqRaw, log }.
   * Devuelve { rows, log } con el registro de predicciones actualizado.
   */
  function analizar(input) {
    const { candles, live5m, price, now } = input;
    const log = (input.log || []).slice(-20000);
    const full = {};
    Object.keys(TIMEFRAMES).forEach((tf) => {
      const closed = candles[tf];
      const bar = tf === '5m' ? live5m : formingFrom5m(candles['5m'], live5m, tf, closed[closed.length - 1][0]);
      full[tf] = bar ? closed.concat([bar]) : closed;
    });
    const rows = [], entries = [], byTf = {}, series = {};

    Object.entries(TIMEFRAMES).forEach(([tf, [days, horizons]]) => {
      const bars = full[tf];
      const partial = bars.length > candles[tf].length;
      const tfMs = TF_MS[tf], tfMin = tfMs / 60000;
      const closes = bars.map((b) => b[4]);
      const [indRows, summary, overlays] = calificarUltimas(bars);
      const e20 = Ind.ema(closes, 20), e50 = Ind.ema(closes, 50), e200 = Ind.ema(closes, 200);
      const rsi = Ind.rsi(closes);
      const [ml, ms, mh] = Ind.macd(closes);
      const warmup = Math.min(200, Math.floor(bars.length / 3));
      const feats = Apr.rasgos(bars, tfMin, e50, e200, rsi, mh);
      const X = Apr.continuos(bars, tfMin, e50, e200, rsi, mh, partial);
      const base = [];
      for (let j = warmup; j < bars.length - 1 - Math.max(...horizons); j++) base.push(j);
      series[tf] = { bars, closes, base, tfMs, tfMin, days, closed: candles[tf], feats, combo: Apr.combos(feats), X, warmup,
        last: bars.length - 1 - Math.max(...horizons, SCENARIO_STEPS), similar: new Map(), fit: new Map(), vol: new Map(), cal: new Map(), partial };
      const mainFit = tune(tf, series[tf], horizons[0]);
      const idxs = mainFit.idxs, keep = mainFit.keep;
      const i = bars.length - 1;
      const trend = trendWord(closes[i], e20[i], e50[i], e200[i]);
      const reg = Apr.regimenes(bars, e200);
      byTf[tf] = { summary, trend };
      const pivots = Ind.zigzag(bars);
      const [waveLabels, waveDesc, waveTarget, waveNow, waveShort] = Ind.elliott(pivots, bars);
      // cruce del MACD con su senal en la ultima o la anteultima vela
      const cross = [i, i - 1].map((k) => (mh[k] > 0 && mh[k - 1] <= 0 ? 'alcista' : mh[k] < 0 && mh[k - 1] >= 0 ? 'bajista' : null)).find((x) => x) || null;
      rows.push({ tabla: 'marco', tf, tendencia: trend, ...summary, ema50: rp(e50[i]), ema200: rp(e200[i]), similares: idxs.length,
        criterio: keep ? Apr.recetaTxt(mainFit.receta, keep) : '',
        elliott: waveDesc, elliott_objetivo: rp(waveTarget), elliott_curso: waveNow, elliott_corto: waveShort,
        macd_cruce: cross, regimen: reg[i] === null ? null : Apr.REGIMENES[reg[i]] });   // dato a la vista (no entra en el modelo: no mejoro)
      indRows.forEach((r) => rows.push({ tabla: 'indicador', tf, ...r }));
      const tail = pivots.slice(-10);
      const offset = tail.length - waveLabels.length;
      tail.forEach(([kind, k, p], n) => rows.push({ tabla: 'giro', tf, t: bars[k][0], precio: rp(p), tipo: kind,
        onda: n >= offset ? waveLabels[n - offset] : '', en_curso: n === tail.length - 1 }));
      Ind.fvg(bars).forEach((z) => rows.push({ tabla: 'fvg', tf, tipo: z.tipo, t: z.t, bajo: rp(z.bajo), alto: rp(z.alto) }));
      patterns(tf, bars, pivots, e20, horizons[0], tfMin, partial).forEach((r) => rows.push(r));
      Ind.divergencias(bars, pivots).forEach((d) => rows.push({ tabla: 'divergencia', tf, ...d, p1: rp(d.p1), p2: rp(d.p2) }));

      horizons.forEach((h) => {
        const [prob, tg] = horizonStats(tf, series[tf], h, price, tune(tf, series[tf], h));
        rows.push({ tabla: 'probabilidad', ...prob });
        tg.forEach((t) => rows.push({ tabla: 'objetivo', tf, horizonte: prob.horizonte, hora: prob.hora, ...t }));
        entries.push([bars[i][0] + tfMs, tf, h, closes[i], prob.sube, prob.min, prob.max]);
      });

      // escenarios y cono del futuro: la pagina ya no los dibuja (SIN_FUTURO); la app los pide sin escenarios y se ahorra
      // armarlos y su calibracion. Por defecto se arman, como en Python
      if (input.escenarios !== false) {
        const [sc, cone] = scenarios(bars, idxs, price, tfMs, volFactor(series[tf], SCENARIO_STEPS), calibracion(series[tf], mainFit.receta, SCENARIO_STEPS).k);
        sc.concat(cone).forEach((r) => { r.tf = tf; rows.push(r); });
      }
      for (let k = Math.max(0, i - CHART_BARS + 1); k <= i; k++) {
        const [t, o, h, l, c, v] = bars[k];
        rows.push({ tabla: 'vela', tf, t, o, h, l, c, v: rnd(v, 2), en_curso: partial && k === i,
          ema20: rp(overlays.ema20[k]), ema50: rp(overlays.ema50[k]), ema200: k >= 199 ? rp(e200[k]) : null, bb_up: rp(overlays.bb_up[k]), bb_lo: rp(overlays.bb_lo[k]),
          rsi: rnd(rsi[k], 1), macd: rnd(ml[k], decPrecio(price) + 1), macd_senal: rnd(ms[k], decPrecio(price) + 1), macd_hist: rnd(mh[k], decPrecio(price) + 1) });
      }
    });

    // semanal y mensual: con toda la historia diaria si la hay (input.d1Largo), mas la vela diaria en curso
    const d1Largo = input.d1Largo ? input.d1Largo.concat(full['1d'].slice(candles['1d'].length)) : full['1d'];
    Object.keys(TF_LARGOS).forEach((tf) => analisisLargo(d1Largo, tf, price, full['1d'].length > candles['1d'].length).forEach((r) => rows.push(r)));

    // una prediccion por plazo, cada una con la temporalidad que mas casos tiene para ese plazo
    PLAZOS.forEach(([name, tf, h]) => {
      const fit = tune(tf, series[tf], h);
      const [prob, tg] = horizonStats(tf, series[tf], h, price, fit);
      rows.push({ tabla: 'plazo', plazo: name, ...prob });
      learningRows(name, tf, h, fit).forEach((r) => rows.push(r));
      tg.forEach((t) => rows.push({ tabla: 'objetivo_plazo', plazo: name, ...t }));
      if (!entries.some((e) => e[1] === tf && e[2] === h)) {
        const s = series[tf];
        entries.push([s.bars[s.bars.length - 1][0] + s.tfMs, tf, h, s.closes[s.closes.length - 1], prob.sube, prob.min, prob.max]);
      }
    });

    // niveles clave
    const h1 = candles['1h'], d1 = candles['1d'];
    const lowOf = (bs) => Math.min(...bs.map((b) => b[3])), highOf = (bs) => Math.max(...bs.map((b) => b[2]));
    const levels = [];
    [['24 h', 24], ['7 días', 168], ['30 días', 720]].forEach(([n, k]) => {
      levels.push([`Mínimo ${n}`, lowOf(h1.slice(-k))], [`Máximo ${n}`, highOf(h1.slice(-k))]);
    });
    Ind.pivotes(d1[d1.length - 1]).forEach(([k, v]) => levels.push([`Pivote ${k}`, v]));
    const closesD = d1.map((b) => b[4]);
    const sma200d = closesD.slice(-200).reduce((s, x) => s + x, 0) / 200;
    const ema200d = Ind.ema(closesD, 200);
    levels.push(['Media simple 200 días', sma200d], ['EMA 200 diaria', ema200d[ema200d.length - 1]]);
    levels.forEach(([name, v]) => rows.push({ tabla: 'nivel', nombre: name, precio: rp(v), tipo: v > price ? 'resistencia' : 'soporte', distancia: rnd(pct(v, price), 2) }));
    fibonacci(candles['4h']).forEach(([f, v]) => rows.push({ tabla: 'nivel', nombre: `Fibonacci ${ar(f * 100, 1)}% (90 d) · rebotó ${FIB_REBOTE[f]}%`, precio: rp(v),
      tipo: v > price ? 'resistencia' : 'soporte', distancia: rnd(pct(v, price), 2), fib: f, rebote: FIB_REBOTE[f] }));
    const tramo = fibTramo(candles['4h']);
    if (tramo) rows.push({ tabla: 'fib_tramo', t_inicio: tramo.t_inicio, p_inicio: rp(tramo.p_inicio), t_fin: tramo.t_fin, p_fin: rp(tramo.p_fin) });

    let funding = null;
    if (input.ctxRaw) {
      const [ctx, fr] = context(input.ctxRaw, h1);
      ctx.forEach((r) => rows.push(r));
      funding = fr;
    } else {
      rows.push({ tabla: 'contexto', clave: 'error', titulo: 'Contexto no disponible', valor: '', senal: 'neutral', detalle: 'No se pudo leer: Bybit, Bitget y Binance no respondieron' });
    }
    // opciones de BTC (Deribit): volatilidad implicita, puts/calls, dolor maximo del viernes. Contexto, solo BTC
    if (input.opcionesRaw && (input.moneda || 'BTC') === 'BTC') opciones(input.opcionesRaw.libro, input.opcionesRaw.dvol, price, now).forEach((r) => rows.push(r));
    // noticias, ETF y prima de Coinbase (las trae api/contexto.js): para explicar los movimientos fuertes
    if (input.externo && Array.isArray(input.externo.rows)) {
      input.externo.rows.filter((r) => r.clave !== 'prima_coinbase' || (input.moneda || 'BTC') === 'BTC').forEach((r) => rows.push(r));
    }
    const [bookRows, per, mb, ma] = books(input.booksRaw || []);
    bookRows.forEach((r) => rows.push(r));
    if (per.length) {
      const b = per.reduce((s, x) => s + x[0], 0), a = per.reduce((s, x) => s + x[1], 0);
      const imb = b + a ? ((b - a) / (b + a)) * 100 : 0;
      const sig = imb > 15 ? 'alcista' : imb < -15 ? 'bajista' : 'neutral';
      rows.push({ tabla: 'contexto', clave: 'libros', titulo: `Libros de ${per.length} exchanges ±0,1%`,
        valor: `${ar(b)} BTC en compras vs ${ar(a)} en ventas (${arp(imb, 0)})`, senal: sig,
        detalle: (sig === 'alcista' ? 'Más compras esperando debajo' : sig === 'bajista' ? 'Más ventas esperando arriba' : 'Parejo') + '. Son órdenes, no posiciones: pueden retirarse.' });
      [['compra', mb, 'soporte'], ['venta', ma, 'resistencia']].forEach(([side, book, kind]) => {
        let best = null;
        book.forEach((q, p) => { if (Math.abs(p / price - 1) > 0.0005 && (best === null || q > best[1])) best = [p, q]; });  // lo pegado al precio no es un muro
        if (best) rows.push({ tabla: 'nivel', nombre: `Muro de ${side} (${ar(best[1])} BTC en libros)`, precio: best[0], tipo: kind, distancia: rnd(pct(best[0], price), 2) });
      });
    }
    if (input.liqRaw) {
      const heat = liquidationMap(input.liqRaw, h1);
      heat.forEach((x) => rows.push({ tabla: 'liquidacion', ...x }));
      [['longs', 'soporte'], ['shorts', 'resistencia']].forEach(([side, kind]) => {
        const near = heat.filter((x) => (x.precio < price) === (side === 'longs') && x[side] > 0);
        if (!near.length) return;
        const top = near.reduce((m, x) => (x[side] > m[side] ? x : m));
        rows.push({ tabla: 'nivel', nombre: `Liquidaciones de ${side} (est.)`, precio: top.precio, tipo: kind, distancia: rnd(pct(top.precio, price), 2) });
      });
    }

    const closesByTf = {};
    Object.entries(candles).forEach(([tf, cs]) => { closesByTf[tf] = new Map(cs.map((c) => [c[0] + TF_MS[tf], c[4]])); });
    const score = logAndScore(log, entries, closesByTf);
    [...score.entries()].map(([key, v]) => { const [tf, h] = key.split('|'); return [tf, Number(h), v]; })
      .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] - b[1]))
      .filter(([, , [n, , , nr]]) => n || nr)     // sin casos medibles no hay nada que mostrar
      .forEach(([tf, h, [n, hits, brier, nr, adentro]]) => rows.push({ tabla: 'acierto', tf, horizonte: label(h * (TF_MS[tf] / 60000)), pronosticos: n,
        aciertos: n ? rnd((hits / n) * 100, 1) : null, brier: n ? rnd(brier / n, 3) : null,
        // el rango del 80% es honesto si el precio termina adentro ~80% de las veces
        con_rango: nr, en_rango: nr ? rnd((adentro / nr) * 100, 1) : null }));

    const comp = compresion(candles['1h']);
    if (comp) rows.push(comp);
    const hs = perfilHoras(candles['1h']);
    if (hs) rows.push(hs);
    const mov = movimiento(candles['5m'], price, input.moneda || 'BTC');
    if (mov) {
      // movimiento fuerte segun el modelo de arboles (fuerte.js, como fuerte.py): BTC y, con modelo propio, SOL, XRP y ZEC
      const mon = input.moneda || 'BTC', MF = mon === 'BTC' ? root.MODELO_FUERTE : (root.MODELOS_FUERTE || {})[mon];
      const pf = MF && root.Fuerte ? root.Fuerte.prever(MF, candles['1h'], rows.filter((r) => r.tabla === 'evento').map((r) => r.t)) : null;
      if (pf) Object.assign(mov, { modelo_1h: pf['1h'], modelo_4h: pf['4h'], modelo_base_1h: pf.base_1h, modelo_base_4h: pf.base_4h,
        modelo_hasta: candles['1h'][candles['1h'].length - 1][0] + 2 * 3600000 });
      rows.push(mov);
    }
    // termometro de compra/venta del ciclo de BTC (como termometro.py). Solo BTC
    if ((input.moneda || 'BTC') === 'BTC' && root.TERMOMETRO) {
      const fg = rows.find((r) => r.tabla === 'contexto' && r.clave === 'miedo_codicia');
      const fr = rows.find((r) => r.tabla === 'contexto' && r.clave === 'funding');
      const tm = termometro(candles['1d'].map((b) => b[4]), price, root.TERMOMETRO, fg ? fg.fng : null, now, fr && fr.f7 !== undefined ? fr.f7 : null);
      if (tm) rows.push(tm);
    } else if (root.TERMOMETRO && root.TERMOMETRO.alts && root.TERMOMETRO.alts[input.moneda]) {   // XRP y SOL (ZEC no: ver armar_termometro.py)
      const tm = termometroAlt(input.moneda, candles['1d'], price, root.TERMOMETRO, now);
      if (tm) rows.push(tm);
    }
    if (root.TERMOMETRO && root.TERMOMETRO.piso && !ACCIONES_PISO.has(input.moneda || 'BTC')) {   // minimo probable a 6 meses
      const pi = piso(input.moneda || 'BTC', candles['1d'].map((b) => b[4]), price, root.TERMOMETRO, now);
      if (pi) rows.push(pi);
    }
    const lado = coinciden(rows);
    rows.forEach((r) => { if (r.tabla === 'plazo' && r.plazo === '1 hora') r.coinciden = lado; });
    const explanation = [];
    PLAZOS.forEach((spec) => explain(rows, price, spec).forEach((e) => explanation.push(e)));
    explanation.forEach((e) => rows.push(e));
    central(rows, price, candles, now).forEach((e) => rows.push(e));
    const takeaway = explanation.find((e) => e.plazo === '1 hora' && e.tipo === 'titular').texto;
    rows.unshift({ tabla: 'resumen', fecha: isoLocal(now), hora_local: fmtLocal(now), precio: rp(price),
      cambio_24h: rnd(changeSince(candles['5m'], now, price, 24), 2), cambio_7d: rnd(changeSince(candles['5m'], now, price, 168), 2),
      sma200d: rp(sma200d), sma200d_dist: rnd(pct(price, sma200d), 2),
      ema200d: rp(ema200d[ema200d.length - 1]), ema200d_dist: rnd(pct(price, ema200d[ema200d.length - 1]), 2), funding: funding === null ? null : rnd(funding * 100, 4),
      rating_1h: byTf['1h'].summary.rating, rating_1d: byTf['1d'].summary.rating, lectura: takeaway, nota_claude: '' });
    return { rows, log };
  }

  const Analisis = { piso, pisoProb, velasLargas, analisisLargo, TF_LARGOS, DIAS_LARGOS, analizar, context, liquidationMap, TIMEFRAMES, TF_MS, PLAZOS, formingFrom5m, explain, coinciden, logAndScore, basePerp, opciones, rangoPuntajes, rangoFactor, volEscala, similar, outcomes, horizonStats, scenarios, targets, termometro, termometroAlt, percentil, fibonacci, fibTramo, compresion, perfilHoras, central, liqReales, calificarUltimas };
  root.Analisis = Analisis;
  if (typeof module !== 'undefined' && module.exports) module.exports = Analisis;
})(typeof self !== 'undefined' ? self : globalThis);
