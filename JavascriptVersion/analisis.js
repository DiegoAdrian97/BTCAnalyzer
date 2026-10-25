/*
 * El analisis completo, como analisis_btc.py: recibe velas y datos del momento y devuelve las filas que
 * dibuja el dashboard. No pide nada a la red (eso lo hace datos.js), asi se puede comparar con Python.
 */
(function (root) {
  'use strict';
  const Ind = root.Ind || (typeof require !== 'undefined' ? require('./indicadores.js') : null);
  const Apr = root.Apr || (typeof require !== 'undefined' ? require('./aprendizaje.js') : null);
  const { ar, rnd, roundEven } = Ind;

  const MIN_SAMPLES = 40;
  const CHART_BARS = 300;
  const SCENARIO_STEPS = 12;
  const HOUR_MS = 3600000;
  const DAY_MS = 86400000;
  // temporalidad: [dias de historia, horizontes de probabilidad en velas]
  const TIMEFRAMES = { '5m': [30, [3, 12]], '15m': [90, [4, 16]], '30m': [180, [4, 16]], '1h': [365, [4, 24]], '4h': [730, [3, 6]], '1d': [1500, [3, 7]] };
  const TF_MS = { '5m': 300000, '15m': 900000, '30m': 1800000, '1h': 3600000, '4h': 14400000, '1d': 86400000 };
  const TF_TXT = { '5m': '5 min', '15m': '15 min', '30m': '30 min', '1h': '1 hora', '4h': '4 horas', '1d': 'diario' };
  const NICE_STEPS = [25, 50, 100, 250, 500, 1000, 2500, 5000, 10000];

  // ---------- formato ----------
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

  function outcomes(closes, idxs, h) {
    const rets = idxs.filter((i) => i + h < closes.length).map((i) => closes[i + h] / closes[i] - 1).sort((a, b) => a - b);
    if (!rets.length) return null;
    return { n: rets.length, up: (rets.filter((r) => r > 0).length / rets.length) * 100, p10: quantile(rets, 0.1) * 100, p90: quantile(rets, 0.9) * 100 };
  }

  /** Camino tipico/alcista/bajista: el camino real mas parecido a la mediana y a los percentiles 75/25. */
  function scenarios(bars, idxs, price, tfMs) {
    const closes = bars.map((b) => b[4]);
    const usable = idxs.filter((j) => j + SCENARIO_STEPS < bars.length);
    if (usable.length < 10) return [[], []];
    const paths = new Map(usable.map((j) => {
      const p = [];
      for (let k = 1; k <= SCENARIO_STEPS; k++) p.push(closes[j + k] / closes[j] - 1);
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
      const base = closes[best], s = price / base;
      for (let k = 1; k <= SCENARIO_STEPS; k++) {
        const [, o, h, l, c] = bars[best + k];
        candles.push({ tabla: 'escenario', tf: null, escenario: name, paso: k, t: t0 + k * tfMs,
          o: rnd(o * s, 1), h: rnd(h * s, 1), l: rnd(l * s, 1), c: rnd(c * s, 1), desde: utcDate(bars[best][0]) });
      }
    });
    const p10 = q(0.1), p50 = q(0.5), p90 = q(0.9);
    for (let k = 0; k < SCENARIO_STEPS; k++) {
      cone.push({ tabla: 'cono', tf: null, paso: k + 1, t: t0 + (k + 1) * tfMs,
        p10: rnd(price * (1 + p10[k]), 1), p50: rnd(price * (1 + p50[k]), 1), p90: rnd(price * (1 + p90[k]), 1) });
    }
    return [candles, cone];
  }

  /** Probabilidad de TOCAR precios redondos antes de 'when', y precio mas probable a esa hora. */
  function targets(bars, idxs, price, h, when, f = 1, unitIn = null, pfAp = null) {
    const usable = idxs.filter((j) => j + h < bars.length);
    if (usable.length < 10) return [[], null];
    const c = bars.map((b) => b[4]);
    const highs = usable.map((j) => { let m = -Infinity; for (let k = j + 1; k <= j + h; k++) m = Math.max(m, bars[k][2]); return m / c[j] - 1; });
    const lows = usable.map((j) => { let m = Infinity; for (let k = j + 1; k <= j + h; k++) m = Math.min(m, bars[k][3]); return m / c[j] - 1; });
    const ends = usable.map((j) => c[j + h] / c[j] - 1).sort((a, b) => a - b);
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
    const upLvl = roundEven((price + unit) / 10) * 10, dnLvl = roundEven((price - unit) / 10) * 10;
    const rel = unit / price;
    const first = [];
    usable.forEach((j) => {
      for (let k = 1; k <= h; k++) {
        const a = bars[j + k][2] / c[j] - 1 >= rel, b = bars[j + k][3] / c[j] - 1 <= -rel;
        if (a || b) { first.push(a && b ? 0.5 : a ? 1 : 0); break; }
      }
    });
    const pf = first.length ? first.reduce((s, x) => s + x, 0) / first.length : null;
    const close = {
      mediana: rnd(price * (1 + q(0.5)), 1), p25: rnd(price * (1 + q(0.25)), 1), p75: rnd(price * (1 + q(0.75)), 1), hora: when,
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
      ranking: g('ranking', []).join(',') }];
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
    const o = outcomes(s.closes, sample, h), b = outcomes(s.closes, s.base, h);
    // la probabilidad de subir la da el equipo que aprende; sin historia suficiente, los casos parecidos
    const up = fit.p_sube !== null && fit.p_sube !== undefined ? fit.p_sube * 100 : f === 1 ? o.up : Apr.ajustar(o.up / 100, f) * 100;
    // contra la tasa normal moderada igual que la prediccion: si aprendio que no hay ventaja (confianza 0), es moneda
    const edge = up - (fit.p_sube !== null && fit.p_sube !== undefined ? Apr.ajustar(b.up / 100, f) * 100 : b.up);
    // margen de error del 95%: con pocos casos, una diferencia chica contra la tasa normal es ruido
    const margin = 196 * Math.sqrt(((o.up / 100) * (1 - o.up / 100)) / o.n) * f;
    const verdict = Math.abs(edge) < Math.max(3, margin) ? 'Casi moneda' : edge > 0 ? 'Sesgo alcista' : 'Sesgo bajista';
    const whenMs = s.bars[s.bars.length - 1][0] + (h + 1) * s.tfMs;
    const when = fmtLocal(whenMs);
    const L = fit.learn || {};
    const [tg, close] = targets(s.bars, sample, price, h, when, f, L.distancia === undefined ? null : L.distancia, fit.p_primero === undefined ? null : fit.p_primero);
    return [{
      tf, horizonte: label(h * s.tfMin), velas: h, sube: rnd(up, 1), baja: rnd(100 - up, 1), base: rnd(b.up, 1),
      sube_crudo: rnd(o.up, 1), receta: fit.receta, factor: f,
      veredicto: verdict, n: o.n, dias: s.days, hora: when, t_hasta: whenMs, margen: rnd(margin, 1), pocos_casos: o.n < 100,
      min: rnd(price * (1 + o.p10 / 100), 1), max: rnd(price * (1 + o.p90 / 100), 1), ...(close || NO_CLOSE),
    }, tg];
  }

  // ---------- contexto actual (datos crudos de Binance) ----------
  function context(raw, closes1h) {
    const rows = [];
    const add = (key, title, value, signal, detail) => rows.push({ tabla: 'contexto', clave: key, titulo: title, valor: value, senal: signal, detalle: detail });
    const oi = raw.oi;
    [1, 4, 24].forEach((hrs) => {
      const dOi = pct(oi[oi.length - 1], oi[oi.length - 1 - hrs]);
      const dPx = pct(closes1h[closes1h.length - 1], closes1h[closes1h.length - 1 - hrs]);
      let why, sig;
      if (Math.abs(dOi) < 0.5) [why, sig] = ['Posicionamiento estable', 'neutral'];
      else if (dPx >= 0) [why, sig] = dOi > 0 ? ['Entran longs nuevos: suba con fuerza', 'alcista'] : ['Cierran shorts: suba sin dinero nuevo', 'neutral'];
      else [why, sig] = dOi > 0 ? ['Entran shorts nuevos: baja con fuerza', 'bajista'] : ['Cierran o liquidan longs: baja por descarga', 'neutral'];
      add(`oi_${hrs}h`, `Open interest ${hrs} h`, `${arp(dOi)} con precio ${arp(dPx)}`, sig, why);
    });
    const buy = raw.taker.reduce((s, x) => s + x.buy, 0), sell = raw.taker.reduce((s, x) => s + x.sell, 0);
    [['1 h', raw.taker[raw.taker.length - 1].ratio], ['4 h', buy / sell]].forEach(([name, r]) => {
      const sig = r > 1.1 ? 'alcista' : r < 0.9 ? 'bajista' : 'neutral';
      add(`flujo_${name}`, `Compras vs ventas a mercado ${name}`, ar(r, 2), sig,
        sig === 'alcista' ? 'Dominan los compradores agresivos' : sig === 'bajista' ? 'Dominan los vendedores agresivos' : 'Flujo equilibrado');
    });
    const nowLs = raw.ls[raw.ls.length - 1], prevLs = raw.ls[0];
    let crowd, sig;
    if (nowLs > 2) [crowd, sig] = ['Mayoría long: si cae, puede haber cascada de liquidaciones', 'bajista'];
    else if (nowLs < 0.9) [crowd, sig] = ['Mayoría short: si sube, puede haber squeeze', 'alcista'];
    else [crowd, sig] = ['Posicionamiento parejo', 'neutral'];
    add('long_short', 'Cuentas long / short', `${ar(nowLs, 2)} (24 h antes ${ar(prevLs, 2)}, top traders ${ar(raw.top, 2)})`, sig, crowd);
    const fr = raw.funding || 0;
    add('funding', 'Funding Binance', arp(fr * 100, 4) + ' cada 8 h', fr > 0.0003 ? 'bajista' : fr < 0 ? 'alcista' : 'neutral',
      fr > 0.0003 ? 'Longs pagando caro: euforia' : fr < 0 ? 'Shorts pagan: miedo' : 'Normal');
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
    return Ind.mapaLiquidaciones(priceByHour, raw.oi, new Map(raw.ls), after);
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
  function patterns(tf, bars, pivots, e20, horizon, tfMin, partial) {
    const o = bars.map((b) => b[1]), h = bars.map((b) => b[2]), l = bars.map((b) => b[3]), c = bars.map((b) => b[4]);
    const atr = Ind.dmi(h, l, c)[3];
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
      g.lineas.slice(0, 2).forEach((ln, n) => Object.assign(lines, { [`l${n + 1}_t`]: ln[0], [`l${n + 1}_p`]: rnd(ln[1], 1), [`l${n + 1}_m`]: ln[2], [`l${n + 1}_nombre`]: ln[3] }));
      g.puntos.slice(0, 5).forEach((pt, n) => Object.assign(lines, { [`pt${n + 1}_t`]: pt[0], [`pt${n + 1}_p`]: rnd(pt[1], 1), [`pt${n + 1}_nombre`]: pt[2] }));
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
  const SHORT_CTX = { 'flujo_1 h': 'Compras a mercado 1 h', 'flujo_4 h': 'Compras a mercado 4 h', oi_1h: 'Open interest 1 h',
    oi_4h: 'Open interest 4 h', oi_24h: 'Open interest 24 h', long_short: 'Long/short', libros: 'Libros de órdenes', funding: 'Funding' };

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
      const target = p.objetivo ? ` → ${ar(p.objetivo)}` : '';
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
        `Elliott ${TF_TXT[sigTfs[sigTfs.length - 1]]}: ${mLast.elliott_corto.split(':')[0]} → ${ar(mLast.elliott_objetivo)}`]);
    }
    const sma = get('nivel').find((n) => n.nombre === 'Media 200 días');
    if (sma && name === '1 día') {
      signals.push([6, price > sma.precio ? 'alcista' : 'bajista', price > sma.precio ? 'Arriba de la media de 200 días' : 'Debajo de la media de 200 días']);
    }
    signals.sort((a, b) => a[0] - b[0]);

    const up = main.obj_arriba, dn = main.obj_abajo, pu = main.primero_arriba, mg = main.margen_primero || 0;
    const nUp = signals.filter((s) => s[1] === 'alcista').length, nDn = signals.length - nUp;
    let bias, head;
    if (pu !== null && pu - 50 > Math.max(5, mg)) {
      bias = 'alcista';
      head = `Hasta las ${hh} h, es más probable que BTC suba a ${ar(up)} (${ar(pu)}%) antes que baje a ${ar(dn)}.`;
    } else if (pu !== null && 50 - pu > Math.max(5, mg)) {
      bias = 'bajista';
      head = `Hasta las ${hh} h, es más probable que BTC baje a ${ar(dn)} (${ar(100 - pu)}%) antes que suba a ${ar(up)}.`;
    } else {
      bias = 'neutral';
      head = `Hasta las ${hh} h, sin dirección clara: lo esperable es que BTC se mueva entre ${ar(dn)} y ${ar(up)}.`;
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
    if (res) out.push(row(k, 'vigilar', 'alcista', `Resistencia ${ar(res.precio)} (${lc1(res.nombre)})`, res.precio));
    if (sup) out.push(row(k + 1, 'vigilar', 'bajista', `Soporte ${ar(sup.precio)} (${lc1(sup.nombre)})`, sup.precio));
    let inval;
    if (bias === 'alcista' && sup) inval = `Si una vela de ${candle} cierra debajo de ${ar(sup.precio)}, la idea deja de valer.`;
    else if (bias === 'bajista' && res) inval = `Si una vela de ${candle} cierra arriba de ${ar(res.precio)}, la idea deja de valer.`;
    else inval = `La dirección la marca la primera vela de ${candle} que cierre fuera de ${ar(dn)} a ${ar(up)}.`;
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

  /** Suma las predicciones nuevas al registro y mide cuantas acertaron (solo con velas cerradas). */
  function logAndScore(log, entries, closesByTf) {
    const seen = new Set(log.map((r) => `${r[0]}|${r[1]}|${r[2]}`));
    entries.forEach(([t, tf, h, p, pr]) => {
      if (!seen.has(`${t}|${tf}|${h}`)) log.push([t, tf, h, rnd(p, 1), rnd(pr, 1)]);
    });
    const score = new Map();
    log.forEach(([t, tf, h, p, pr]) => {
      const future = closesByTf[tf] && closesByTf[tf].get(t + h * TF_MS[tf]);
      const prob = pr / 100;
      if (future === undefined || prob === 0.5) return;
      const up = future > p;
      const key = `${tf}|${h}`;
      const [n, hits, brier] = score.get(key) || [0, 0, 0];
      score.set(key, [n + 1, hits + ((prob > 0.5) === up ? 1 : 0), brier + (prob - (up ? 1 : 0)) ** 2]);
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
      const [indRows, summary, overlays] = Ind.calificar(bars);
      const e20 = Ind.ema(closes, 20), e50 = Ind.ema(closes, 50), e200 = Ind.ema(closes, 200);
      const rsi = Ind.rsi(closes);
      const [ml, ms, mh] = Ind.macd(closes);
      const warmup = Math.min(200, Math.floor(bars.length / 3));
      const feats = Apr.rasgos(bars, tfMin, e50, e200, rsi, mh);
      const X = Apr.continuos(bars, tfMin, e50, e200, rsi, mh, partial);
      const base = [];
      for (let j = warmup; j < bars.length - 1 - Math.max(...horizons); j++) base.push(j);
      series[tf] = { bars, closes, base, tfMs, tfMin, days, closed: candles[tf], feats, combo: Apr.combos(feats), X, warmup,
        last: bars.length - 1 - Math.max(...horizons, SCENARIO_STEPS), similar: new Map(), fit: new Map() };
      const mainFit = tune(tf, series[tf], horizons[0]);
      const idxs = mainFit.idxs, keep = mainFit.keep;
      const i = bars.length - 1;
      const trend = trendWord(closes[i], e20[i], e50[i], e200[i]);
      byTf[tf] = { summary, trend };
      const pivots = Ind.zigzag(bars);
      const [waveLabels, waveDesc, waveTarget, waveNow, waveShort] = Ind.elliott(pivots, bars);
      // cruce del MACD con su senal en la ultima o la anteultima vela
      const cross = [i, i - 1].map((k) => (mh[k] > 0 && mh[k - 1] <= 0 ? 'alcista' : mh[k] < 0 && mh[k - 1] >= 0 ? 'bajista' : null)).find((x) => x) || null;
      rows.push({ tabla: 'marco', tf, tendencia: trend, ...summary, ema50: rnd(e50[i], 1), ema200: rnd(e200[i], 1), similares: idxs.length,
        criterio: keep ? Apr.recetaTxt(mainFit.receta, keep) : '',
        elliott: waveDesc, elliott_objetivo: waveTarget === null ? null : rnd(waveTarget, 1), elliott_curso: waveNow, elliott_corto: waveShort,
        macd_cruce: cross });
      indRows.forEach((r) => rows.push({ tabla: 'indicador', tf, ...r }));
      const tail = pivots.slice(-10);
      const offset = tail.length - waveLabels.length;
      tail.forEach(([kind, k, p], n) => rows.push({ tabla: 'giro', tf, t: bars[k][0], precio: rnd(p, 1), tipo: kind,
        onda: n >= offset ? waveLabels[n - offset] : '', en_curso: n === tail.length - 1 }));
      Ind.fvg(bars).forEach((z) => rows.push({ tabla: 'fvg', tf, tipo: z.tipo, t: z.t, bajo: rnd(z.bajo, 1), alto: rnd(z.alto, 1) }));
      patterns(tf, bars, pivots, e20, horizons[0], tfMin, partial).forEach((r) => rows.push(r));
      Ind.divergencias(bars, pivots).forEach((d) => rows.push({ tabla: 'divergencia', tf, ...d, p1: rnd(d.p1, 1), p2: rnd(d.p2, 1) }));

      horizons.forEach((h) => {
        const [prob, tg] = horizonStats(tf, series[tf], h, price, tune(tf, series[tf], h));
        rows.push({ tabla: 'probabilidad', ...prob });
        tg.forEach((t) => rows.push({ tabla: 'objetivo', tf, horizonte: prob.horizonte, hora: prob.hora, ...t }));
        entries.push([bars[i][0] + tfMs, tf, h, closes[i], prob.sube]);
      });

      const [sc, cone] = scenarios(bars, idxs, price, tfMs);
      sc.concat(cone).forEach((r) => { r.tf = tf; rows.push(r); });
      for (let k = Math.max(0, i - CHART_BARS + 1); k <= i; k++) {
        const [t, o, h, l, c, v] = bars[k];
        rows.push({ tabla: 'vela', tf, t, o, h, l, c, v: rnd(v, 2), en_curso: partial && k === i,
          ema20: rnd(overlays.ema20[k], 1), ema50: rnd(overlays.ema50[k], 1), bb_up: rnd(overlays.bb_up[k], 1), bb_lo: rnd(overlays.bb_lo[k], 1),
          rsi: rnd(rsi[k], 1), macd: rnd(ml[k], 2), macd_senal: rnd(ms[k], 2), macd_hist: rnd(mh[k], 2) });
      }
    });

    // una prediccion por plazo, cada una con la temporalidad que mas casos tiene para ese plazo
    PLAZOS.forEach(([name, tf, h]) => {
      const fit = tune(tf, series[tf], h);
      const [prob, tg] = horizonStats(tf, series[tf], h, price, fit);
      rows.push({ tabla: 'plazo', plazo: name, ...prob });
      learningRows(name, tf, h, fit).forEach((r) => rows.push(r));
      tg.forEach((t) => rows.push({ tabla: 'objetivo_plazo', plazo: name, ...t }));
      if (!entries.some((e) => e[1] === tf && e[2] === h)) {
        const s = series[tf];
        entries.push([s.bars[s.bars.length - 1][0] + s.tfMs, tf, h, s.closes[s.closes.length - 1], prob.sube]);
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
    const lo30 = lowOf(h1.slice(-720)), hi30 = highOf(h1.slice(-720));
    [0.236, 0.382, 0.5, 0.618, 0.786].forEach((f) => levels.push([`Fibonacci ${ar(f * 100, 1)}% (30 d)`, hi30 - (hi30 - lo30) * f]));
    const closesD = d1.map((b) => b[4]);
    const sma200d = closesD.slice(-200).reduce((s, x) => s + x, 0) / 200;
    const ema200d = Ind.ema(closesD, 200);
    levels.push(['Media 200 días', sma200d], ['EMA 200 diaria', ema200d[ema200d.length - 1]]);
    levels.forEach(([name, v]) => rows.push({ tabla: 'nivel', nombre: name, precio: rnd(v, 1), tipo: v > price ? 'resistencia' : 'soporte', distancia: rnd(pct(v, price), 2) }));

    let funding = null;
    if (input.ctxRaw) {
      const [ctx, fr] = context(input.ctxRaw, h1.map((b) => b[4]));
      ctx.forEach((r) => rows.push(r));
      funding = fr;
    } else {
      rows.push({ tabla: 'contexto', clave: 'error', titulo: 'Contexto no disponible', valor: '', senal: 'neutral', detalle: 'No se pudo leer: Binance no respondió' });
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
      .forEach(([tf, h, [n, hits, brier]]) => rows.push({ tabla: 'acierto', tf, horizonte: label(h * (TF_MS[tf] / 60000)), pronosticos: n,
        aciertos: rnd((hits / n) * 100, 1), brier: rnd(brier / n, 3) }));

    const explanation = [];
    PLAZOS.forEach((spec) => explain(rows, price, spec).forEach((e) => explanation.push(e)));
    explanation.forEach((e) => rows.push(e));
    const takeaway = explanation.find((e) => e.plazo === '1 hora' && e.tipo === 'titular').texto;
    rows.unshift({ tabla: 'resumen', fecha: isoLocal(now), hora_local: fmtLocal(now), precio: rnd(price, 1),
      cambio_24h: rnd(changeSince(candles['5m'], now, price, 24), 2), cambio_7d: rnd(changeSince(candles['5m'], now, price, 168), 2),
      sma200d: rnd(sma200d, 1), sma200d_dist: rnd(pct(price, sma200d), 2), funding: funding === null ? null : rnd(funding * 100, 4),
      rating_1h: byTf['1h'].summary.rating, rating_1d: byTf['1d'].summary.rating, lectura: takeaway, nota_claude: '' });
    return { rows, log };
  }

  const Analisis = { analizar, TIMEFRAMES, TF_MS, PLAZOS, formingFrom5m, explain, similar, outcomes, horizonStats, scenarios, targets };
  root.Analisis = Analisis;
  if (typeof module !== 'undefined' && module.exports) module.exports = Analisis;
})(typeof self !== 'undefined' ? self : globalThis);
