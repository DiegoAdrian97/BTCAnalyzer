/*
 * Aprendizaje automatico del analista: traduccion 1:1 de aprendizaje.py (mismas cuentas, mismos numeros).
 *
 * Para cada plazo repasa las ultimas REPASO predicciones que habria hecho (cada una solo con lo que se sabia en
 * ese momento) y las compara con lo que paso. Junta un equipo de expertos (las recetas de "casos parecidos", un
 * modelo que aprende solo con cada vela y la tasa base) y aprende cuanto creerle a cada uno (pesos exponenciales
 * con reparto fijo). Cada resultado se usa para aprender recien cuando se conoce, y cada prediccion se juzga con
 * lo que habia ANTES de conocer el resultado: la medicion es honesta. Ver aprendizaje.py.
 */
(function (root) {
  'use strict';
  const Ind = root.Ind || (typeof require !== 'undefined' ? require('./indicadores.js') : null);

  const MIN_CASOS = 40;
  const MIN_EXPERIENCIA = 300;
  const REPASO = 1000;
  const ARRANQUE = 60;
  const HISTERESIS = 0.004;
  const VENTANA = 150;
  const PUNTOS_CURVA = 30;
  const VOL_N = 100;
  const FACTORES = [1.0, 0.75, 0.5, 0.25, 0.0, 1.25, 1.5];
  // escalones "redondos" de 1, 2,5 y 5 por cada potencia de 10 (como en Python)
  const NICE_STEPS = [];
  for (let k = -4; k < 6; k++) for (const m of [1, 2.5, 5]) NICE_STEPS.push(m * 10 ** k);
  const ETA = 2.0;          // cuanto castiga Hedge cada error
  const REPARTO = 0.05;     // parte del peso que se reparte entre todos en cada paso (adaptarse a cambios)
  const TASA = 0.0005;      // paso de aprendizaje del modelo
  const L2 = 0.001;         // freno del modelo
  const SEGURA = 0.08;      // "se anima": probabilidad al menos 8 puntos lejos del 50%
  const RASGOS = ['precio vs EMA 50', 'precio vs EMA 200', 'RSI', 'movimiento del último día', 'MACD', 'volatilidad', 'Bollinger'];
  const NIVELES = [2, 2, 4, 3, 2, 2, 4];
  const RECETAS = [[0, 1, 2, 3], [0, 2, 4], [1, 3, 5], [2, 6, 5], [4, 6, 0, 3], [3, 5, 2], [0, 1, 5, 6], [2, 4, 3, 5]];
  const COMBOS = NIVELES.reduce((a, v) => a * v, 1);
  const MODELO = RECETAS.length, BASE = RECETAS.length + 1, EXPERTOS = RECETAS.length + 2;

  const combo1 = (f) => f.reduce((k, x, i) => k * NIVELES[i] + x, 0);
  function decodificar(k) {
    const f = [];
    for (let i = NIVELES.length - 1; i >= 0; i--) { f.push(k % NIVELES[i]); k = Math.floor(k / NIVELES[i]); }
    return f.reverse();
  }
  const codigo = (f, idx) => idx.reduce((k, i) => k * NIVELES[i] + f[i], 0);
  const TODAS = Array.from({ length: COMBOS }, (_, k) => decodificar(k));
  const PROY = RECETAS.map((r) => r.map((_, n) => TODAS.map((f) => codigo(f, r.slice(0, n + 1)))));
  const TAM = RECETAS.map((r) => r.map((_, n) => codigo(NIVELES.map((v) => v - 1), r.slice(0, n + 1)) + 1));

  const lista = (n) => (n.length === 1 ? n[0] : n.slice(0, -1).join(', ') + ' y ' + n[n.length - 1]);
  const recetaTxt = (r, n = null) => lista(RECETAS[r].slice(0, n === null ? RECETAS[r].length : n).map((i) => RASGOS[i]));
  function expertoTxt(e) {
    if (e === MODELO) return 'el modelo que aprende solo';
    if (e === BASE) return 'la tasa base';
    return 'casos parecidos por ' + recetaTxt(e);
  }
  function confianzaTxt(f) {
    if (f === 1) return 'Usa sus probabilidades tal cual';
    if (f === 0) return 'No encontró ventaja: lo trata como una moneda';
    if (f < 1) return `Modera sus probabilidades al ${Math.trunc(f * 100)}%: venían exageradas`;
    return `Refuerza sus probabilidades al ${Math.trunc(f * 100)}%: venían tímidas`;
  }

  /** Los rasgos de cada vela (enteros) o null mientras arrancan los indicadores. */
  function rasgos(bars, tfMin, e50, e200, rsi, mh) {
    const n = bars.length, c = bars.map((b) => b[4]);
    const atr = Ind.dmi(bars.map((b) => b[2]), bars.map((b) => b[3]), c)[3];
    const [mid, bu, bl] = Ind.bollinger(c);
    const look = Math.max(1, Math.floor(1440 / tfMin));
    const vol = new Array(n).fill(null);
    let acc = 0;
    for (let i = 1; i < n; i++) {
      acc += atr[i];
      if (i > VOL_N) acc -= atr[i - VOL_N];
      if (i >= VOL_N) vol[i] = atr[i] > acc / VOL_N ? 1 : 0;
    }
    const out = [];
    for (let i = 0; i < n; i++) {
      const r = rsi[i];
      if (r === null || i < look || vol[i] === null || bu[i] === null) { out.push(null); continue; }
      const move = c[i] / c[i - look] - 1;
      const bb = c[i] > bu[i] ? 3 : c[i] >= mid[i] ? 2 : c[i] >= bl[i] ? 1 : 0;
      out.push([c[i] > e50[i] ? 1 : 0, c[i] > e200[i] ? 1 : 0, r < 35 ? 0 : r < 50 ? 1 : r < 65 ? 2 : 3,
        move < -0.02 ? 0 : move <= 0.02 ? 1 : 2, mh[i] > 0 ? 1 : 0, vol[i], bb]);
    }
    return out;
  }

  const corte = (x, a = 4) => (x < -a ? -a : x > a ? a : x);

  /** Lo que mira el modelo en cada vela: 20 numeros chicos (o null mientras arrancan los indicadores). */
  function continuos(bars, tfMin, e50, e200, rsi, mh, parcial = false) {
    const n = bars.length;
    const o = bars.map((b) => b[1]), h = bars.map((b) => b[2]), l = bars.map((b) => b[3]), c = bars.map((b) => b[4]), v = bars.map((b) => b[5]);
    const atr = Ind.dmi(h, l, c)[3];
    const [mid, bu] = Ind.bollinger(c);
    const look = Math.max(1, Math.floor(1440 / tfMin));
    let raiz = 1;
    while ((raiz + 1) * (raiz + 1) <= look) raiz += 1;
    const out = new Array(n).fill(null);
    let accA = 0, accV = 0;
    const nn = (x) => x !== null && x !== undefined;
    for (let i = 0; i < n; i++) {
      accA += nn(atr[i]) ? atr[i] : 0;
      if (i >= VOL_N) accA -= nn(atr[i - VOL_N]) ? atr[i - VOL_N] : 0;
      accV += v[i];
      if (i >= 20) accV -= v[i - 20];
      const a = atr[i];
      if (i < Math.max(VOL_N, look, 12) || !nn(a) || a <= 0 || !nn(rsi[i]) || !nn(bu[i]) || !nn(mh[i])) continue;
      const avgA = accA / VOL_N, avgV = accV / 20;
      const rango = h[i] - l[i];
      const hora = Math.floor(bars[i][0] / 3600000) % 24;
      const dia = (Math.floor(bars[i][0] / 86400000) + 3) % 7;
      const franja = Math.floor(hora / 4);
      const x = [corte((c[i] - c[i - 1]) / a),
        corte((c[i] - c[i - 3]) / a / 1.7),
        corte((c[i] - c[i - 12]) / a / 3.5),
        corte((c[i] - c[i - look]) / a / raiz),
        corte((c[i] - e50[i]) / a / 3),
        corte((c[i] - e200[i]) / a / 6),
        (rsi[i] - 50) / 15,
        corte((mh[i] / a) * 3),
        bu[i] > mid[i] ? corte((c[i] - mid[i]) / (bu[i] - mid[i])) : 0,
        avgA > 0 ? corte(a / avgA - 1) : 0,
        (parcial && i === n - 1) || avgV <= 0 ? 0 : corte(v[i] / avgV - 1, 3),
        corte(rango / a - 1),
        rango > 0 ? ((c[i] - l[i]) / rango - 0.5) * 2 : 0,
        corte((c[i] - o[i]) / a)];
      for (let k = 0; k < 6; k++) x.push(franja === k ? 1 : 0);
      x.push(dia >= 5 ? 1 : 0);
      out[i] = x;
    }
    return out;
  }

  const estados = (feats, r) => feats.map((f) => (f === null ? null : RECETAS[r].map((i) => f[i])));
  const combos = (feats) => feats.map((f) => (f === null ? null : combo1(f)));
  const ajustar = (p, f) => (f === 1 ? p : Math.min(1, Math.max(0, 0.5 + f * (p - 0.5))));

  /** e elevado a x (x <= 0) solo con sumas y productos: identico en Python y en JavaScript. */
  function expo(x) {
    if (x < -60) x = -60;
    const y = x / 1024;
    let r = 1 + y * (1 + (y / 2) * (1 + (y / 3) * (1 + (y / 4) * (1 + y / 5))));
    for (let k = 0; k < 10; k++) r = r * r;
    return r;
  }
  function sigmoide(z) {
    if (z >= 0) return 1 / (1 + expo(-z));
    const e = expo(z);
    return e / (1 + e);
  }
  /** Intervalo del 95% de una proporcion (en %). */
  function wilson(k, n) {
    if (!n) return [null, null];
    const z2 = 1.96 * 1.96, p = k / n;
    const centro = (p + z2 / (2 * n)) / (1 + z2 / n);
    const radio = (1.96 * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))) / (1 + z2 / n);
    return [(centro - radio) * 100, (centro + radio) * 100];
  }

  /** Regresion logistica en linea: un pasito de descenso por cada resultado nuevo. */
  class Logistica {
    constructor(d) { this.w = new Array(d + 1).fill(0); }
    prob(x) {
      const w = this.w;
      let z = w[w.length - 1];
      for (let k = 0; k < x.length; k++) z += w[k] * x[k];
      return sigmoide(z);
    }
    aprender(x, y) {
      const w = this.w, g = this.prob(x) - y;
      for (let k = 0; k < x.length; k++) w[k] -= TASA * (g * x[k] + L2 * w[k]);
      w[w.length - 1] -= TASA * g;
    }
  }

  const base = (tot) => [tot[0] ? tot[1] / tot[0] : 0.5, tot[3] ? tot[2] / tot[3] : 0.5];
  function receta(tabs, tot, r, k) {
    for (let L = RECETAS[r].length - 1; L >= 0; L--) {
      const [tn, tu, ts, tf] = tabs[r][L], p = PROY[r][L][k];
      if (tn[p] >= MIN_CASOS) return [tu[p] / tn[p], tf[p] ? ts[p] / tf[p] : 0.5];
    }
    return base(tot);
  }
  function equipo(tabs, tot, mSube, mPrim, k, x) {
    if (k === null || k === undefined) return null;
    const preds = [];
    for (let r = 0; r < RECETAS.length; r++) preds.push(receta(tabs, tot, r, k));
    preds.push(x ? [mSube.prob(x), mPrim.prob(x)] : base(tot));
    preds.push(base(tot));
    return preds;
  }
  function mezclar(pesos, preds) {
    let ps = 0, pf = 0;
    for (let e = 0; e < EXPERTOS; e++) { ps += pesos[e] * preds[e][0]; pf += pesos[e] * preds[e][1]; }
    return [ps, pf];
  }
  /** La prediccion de ahora (sube, toca primero arriba), con lo aprendido hasta la ultima vela cerrada. */
  function prediccion(res, k, x) {
    if (!res || k === null || k === undefined) return [null, null];
    const st = res._estado, preds = equipo(st.tabs, st.tot, st.mSube, st.mPrim, k, x);
    const [ps, pf] = mezclar(res.pesos, preds);
    return [ajustar(ps, res.factor), ajustar(pf, res.factor)];
  }

  function aprender(bars, combo, h, warmup, X = null) {
    const n = bars.length, c = bars.map((b) => b[4]);
    const end = n - 1 - h;
    const t0 = Math.max(warmup + MIN_EXPERIENCIA, end - REPASO + 1);
    if (end - t0 + 1 < 2 * ARRANQUE) return null;
    if (!X) X = new Array(combo.length).fill(null);
    const ends = [];
    for (let j = warmup; j <= end; j++) ends.push(c[j + h] / c[j] - 1);
    ends.sort((a, b) => a - b);
    const q = (p) => ends[Math.min(Math.trunc(p * ends.length), ends.length - 1)];
    const price = c[n - 1];
    const spread = (q(0.9) - q(0.1)) * price;
    const unit = NICE_STEPS.reduce((best, s) => (Math.abs(s - spread / 4) < Math.abs(best - spread / 4) ? s : best));
    const rel = unit / price;

    const sube = new Array(n).fill(0), prim = new Array(n).fill(null);
    for (let j = warmup; j <= end; j++) {
      sube[j] = c[j + h] > c[j] ? 1 : 0;
      for (let k = 1; k <= h; k++) {
        const a = bars[j + k][2] / c[j] - 1 >= rel, b = bars[j + k][3] / c[j] - 1 <= -rel;
        if (a || b) { prim[j] = a && b ? 0.5 : a ? 1 : 0; break; }
      }
    }

    const first = X.find((x) => x);
    const d = first ? first.length : 0;
    const mSube = new Logistica(d), mPrim = new Logistica(d);

    const cn = new Array(COMBOS).fill(0), cu = new Array(COMBOS).fill(0), cs = new Array(COMBOS).fill(0), cf = new Array(COMBOS).fill(0);
    const tot = [0, 0, 0, 0];
    for (let j = warmup; j <= t0 - h; j++) {
      const x = X[j];
      if (x) { mSube.aprender(x, sube[j]); if (prim[j] !== null) mPrim.aprender(x, prim[j]); }
      const k = combo[j];
      if (k === null) continue;
      cn[k] += 1; cu[k] += sube[j]; tot[0] += 1; tot[1] += sube[j];
      if (prim[j] !== null) { cs[k] += prim[j]; cf[k] += 1; tot[2] += prim[j]; tot[3] += 1; }
    }
    const tabs = RECETAS.map((r, ri) => r.map((_, L) => {
      const size = TAM[ri][L], proy = PROY[ri][L];
      const tn = new Array(size).fill(0), tu = new Array(size).fill(0), ts = new Array(size).fill(0), tf = new Array(size).fill(0);
      for (let k = 0; k < COMBOS; k++) {
        if (cn[k]) { const p = proy[k]; tn[p] += cn[k]; tu[p] += cu[k]; ts[p] += cs[k]; tf[p] += cf[k]; }
      }
      return [tn, tu, ts, tf];
    }));

    const sumar = (j) => {
      const x = X[j], pj = prim[j];
      if (x) { mSube.aprender(x, sube[j]); if (pj !== null) mPrim.aprender(x, pj); }
      const k = combo[j];
      if (k === null) return;
      tot[0] += 1; tot[1] += sube[j];
      if (pj !== null) { tot[2] += pj; tot[3] += 1; }
      for (let r = 0; r < RECETAS.length; r++) {
        for (let L = 0; L < RECETAS[r].length; L++) {
          const [tn, tu, ts, tf] = tabs[r][L], p = PROY[r][L][k];
          tn[p] += 1; tu[p] += sube[j];
          if (pj !== null) { ts[p] += pj; tf[p] += 1; }
        }
      }
    };
    const equipoT = (t) => equipo(tabs, tot, mSube, mPrim, combo[t], X[t]);

    const E = EXPERTOS, K = FACTORES.length;
    const pesos = new Array(E).fill(1 / E);
    const score = new Array(K).fill(0);
    let factor = 0, cambios = 0, lider = null, m = 0;
    const pend = new Map();
    const ap = [0, 0, 0, 0], og = [0, 0, 0, 0], bs = [0, 0, 0, 0], seg = [0, 0], sep = [0, 0, 0, 0], serie = [];

    const error = (ps, pf, os, of) => {
      let e = (ps - os) * (ps - os);
      if (of !== null) e += (pf - of) * (pf - of);
      return e;
    };
    const medir = (st, ps, pf, os, of) => {
      const e = error(ps, pf, os, of);
      st[0] += e;
      st[1] += of === null ? 1 : 2;
      let hit = null;
      if (of !== null && of !== 0.5 && pf !== 0.5) {
        hit = (pf > 0.5) === (of === 1) ? 1 : 0;
        st[2] += hit; st[3] += 1;
      }
      return [e, hit];
    };
    const resolver = (t) => {
      const got = pend.get(t);
      if (got === undefined) return;
      pend.delete(t);
      const [preds, mix] = got, os = sube[t], of = prim[t];
      let totW = 0;
      for (let e = 0; e < E; e++) { pesos[e] *= expo(-ETA * error(preds[e][0], preds[e][1], os, of)); totW += pesos[e]; }
      for (let e = 0; e < E; e++) pesos[e] = ((1 - REPARTO) * pesos[e]) / totW + REPARTO / E;
      for (let k = 0; k < K; k++) { const f = FACTORES[k]; score[k] += error(ajustar(mix[0], f), ajustar(mix[1], f), os, of); }
    };

    for (let t = t0; t <= end; t++) {
      resolver(t - h);
      if (m >= ARRANQUE) {
        let best = 0;
        for (let k = 0; k < K; k++) if (score[k] < score[best]) best = k;
        if (best !== factor && score[best] < score[factor] * (1 - HISTERESIS)) factor = best;
      }
      const preds = equipoT(t);
      if (preds !== null) {
        const mix = mezclar(pesos, preds);
        if (m >= ARRANQUE) {
          const f = FACTORES[factor], ps = ajustar(mix[0], f), pf = ajustar(mix[1], f), os = sube[t], of = prim[t];
          const [eAp, hAp] = medir(ap, ps, pf, os, of);
          const [eOg] = medir(og, preds[0][0], preds[0][1], os, of);
          const [eBs] = medir(bs, preds[BASE][0], preds[BASE][1], os, of);
          if (hAp !== null && (pf - 0.5 >= SEGURA || 0.5 - pf >= SEGURA)) { seg[0] += hAp; seg[1] += 1; }
          if (of !== null && of !== 0.5) {
            const pb = preds[BASE][1], pm = mix[1];
            if (pm > pb) { sep[0] += 1; sep[1] += of; } else if (pm < pb) { sep[2] += 1; sep[3] += of; }
          }
          serie.push([eAp, eOg, eBs]);
          let top = 0;
          for (let e = 0; e < E; e++) if (pesos[e] > pesos[top]) top = e;
          if (lider !== null && top !== lider) cambios += 1;
          lider = top;
        }
        pend.set(t, [preds, mix]);
        m += 1;
      }
      sumar(t + 1 - h);
    }
    for (let t = end + 1 - h; t <= end; t++) resolver(t);
    for (let j = end + 2 - h; j <= end; j++) sumar(j);

    const curva = [];
    if (serie.length >= VENTANA) {
      const paso = Math.max(1, Math.floor((serie.length - VENTANA) / (PUNTOS_CURVA - 1)));
      const idxs = [];
      for (let i = VENTANA - 1; i < serie.length; i += paso) idxs.push(i);
      if (idxs[idxs.length - 1] !== serie.length - 1) idxs.push(serie.length - 1);
      idxs.forEach((i) => {
        let a = 0, o = 0, b = 0;
        for (let j = i - VENTANA + 1; j <= i; j++) { a += serie[j][0]; o += serie[j][1]; b += serie[j][2]; }
        curva.push([i + 1, b > 0 ? (1 - a / b) * 100 : null, b > 0 ? (1 - o / b) * 100 : null]);
      });
    }

    const [lo, hi] = wilson(ap[2] / h, ap[3] / h);
    const sepArriba = sep[0] ? (sep[1] / sep[0]) * 100 : null, sepAbajo = sep[2] ? (sep[3] / sep[2]) * 100 : null;
    let margenSep = null;
    if (sep[0] >= h && sep[2] >= h && sepArriba !== null && sepAbajo !== null) {
      const p1 = sepArriba / 100, p2 = sepAbajo / 100;
      margenSep = 196 * Math.sqrt((p1 * (1 - p1)) / (sep[0] / h) + (p2 * (1 - p2)) / (sep[2] / h));
    }
    const orden = (list) => list.sort((a, b) => (pesos[b] - pesos[a]) || (a - b));
    const recetas = orden(Array.from({ length: RECETAS.length }, (_, r) => r));
    const ranking = orden(Array.from({ length: E }, (_, e) => e));
    const br = (st) => (st[1] ? st[0] / st[1] : null);
    const pct = (a, b) => (b ? (a / b) * 100 : null);
    return {
      receta: recetas[0], factor: FACTORES[factor], repasadas: m, desde: bars[t0][0], hasta: bars[end][0], cambios, distancia: unit,
      brier_aprendido: br(ap), brier_original: br(og), brier_base: br(bs),
      habilidad: br(ap) !== null && br(bs) ? (1 - br(ap) / br(bs)) * 100 : null,
      habilidad_original: br(og) !== null && br(bs) ? (1 - br(og) / br(bs)) * 100 : null,
      aciertos_aprendido: pct(ap[2], ap[3]), decisivas_aprendido: ap[3],
      aciertos_original: pct(og[2], og[3]), decisivas_original: og[3],
      ic_bajo: lo, ic_alto: hi, independientes: Math.floor(ap[3] / h),
      aciertos_seguro: pct(seg[0], seg[1]), decisivas_seguro: seg[1],
      sep_arriba: sepArriba, sep_abajo: sepAbajo, margen_sep: margenSep,
      pesos: pesos.slice(), ranking, medidas: serie.length, curva,
      _estado: { tabs, tot, mSube, mPrim },
    };
  }

  const cache = new Map();
  /** aprender() solo cuando cerro una vela nueva: mientras tanto el resultado es el mismo. */
  function aprendido(clave, bars, combo, h, warmup, X = null) {
    const stamp = `${bars.length}|${bars[bars.length - 1][0]}|${h}|${warmup}`;
    const hit = cache.get(clave);
    if (hit && hit[0] === stamp) return hit[1];
    const res = aprender(bars, combo, h, warmup, X);
    cache.set(clave, [stamp, res]);
    return res;
  }

  const Apr = { rasgos, continuos, estados, combos, ajustar, aprender, aprendido, prediccion, recetaTxt, expertoTxt, confianzaTxt, expo, sigmoide, wilson,
    RECETAS, RASGOS, FACTORES, MODELO, BASE, EXPERTOS };
  root.Apr = Apr;
  if (typeof module !== 'undefined' && module.exports) module.exports = Apr;
})(typeof self !== 'undefined' ? self : globalThis);
