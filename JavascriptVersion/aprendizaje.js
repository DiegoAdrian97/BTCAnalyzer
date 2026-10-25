/*
 * Aprendizaje automatico del analista: traduccion 1:1 de aprendizaje.py (mismas cuentas, mismos numeros).
 *
 * Para cada plazo repasa las ultimas REPASO predicciones que habria hecho (cada una solo con lo que se sabia en
 * ese momento), las compara con lo que paso y ajusta la receta de "situaciones parecidas" y cuanto confiar en
 * sus propias probabilidades. Aprende en linea: cada prediccion se juzga con lo que habia elegido ANTES de
 * conocer el resultado. Cada vela nueva que cierra suma experiencia.
 */
(function (root) {
  'use strict';
  const Ind = root.Ind || (typeof require !== 'undefined' ? require('./indicadores.js') : null);

  const MIN_CASOS = 40;
  const MIN_EXPERIENCIA = 300;
  const REPASO = 600;
  const ARRANQUE = 60;
  const HISTERESIS = 0.004;
  const VENTANA = 120;
  const PUNTOS_CURVA = 30;
  const VOL_N = 100;
  const FACTORES = [1.0, 0.75, 0.5, 0.25, 0.0, 1.25, 1.5];
  const NICE_STEPS = [25, 50, 100, 250, 500, 1000, 2500, 5000, 10000];
  const RASGOS = ['precio vs EMA 50', 'precio vs EMA 200', 'RSI', 'movimiento del último día', 'MACD', 'volatilidad', 'Bollinger'];
  const NIVELES = [2, 2, 4, 3, 2, 2, 4];
  const RECETAS = [[0, 1, 2, 3], [0, 2, 4], [1, 3, 5], [2, 6, 5], [4, 6, 0, 3], [3, 5, 2], [0, 1, 5, 6], [2, 4, 3, 5]];
  const COMBOS = NIVELES.reduce((a, v) => a * v, 1);

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

  const estados = (feats, r) => feats.map((f) => (f === null ? null : RECETAS[r].map((i) => f[i])));
  const combos = (feats) => feats.map((f) => (f === null ? null : combo1(f)));
  const ajustar = (p, f) => (f === 1 ? p : Math.min(1, Math.max(0, 0.5 + f * (p - 0.5))));

  function aprender(bars, combo, h, warmup) {
    const n = bars.length, c = bars.map((b) => b[4]);
    const end = n - 1 - h;
    const t0 = Math.max(warmup + MIN_EXPERIENCIA, end - REPASO + 1);
    if (end - t0 + 1 < 2 * ARRANQUE) return null;
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

    const cn = new Array(COMBOS).fill(0), cu = new Array(COMBOS).fill(0), cs = new Array(COMBOS).fill(0), cf = new Array(COMBOS).fill(0);
    const tot = [0, 0, 0, 0];
    for (let j = warmup; j <= t0 - h; j++) {
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
      const k = combo[j];
      if (k === null) return;
      const pj = prim[j];
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
    const predecir = (r, k) => {
      for (let L = RECETAS[r].length - 1; L >= 0; L--) {
        const [tn, tu, ts, tf] = tabs[r][L], p = PROY[r][L][k];
        if (tn[p] >= MIN_CASOS) return [tu[p] / tn[p], tf[p] ? ts[p] / tf[p] : 0.5];
      }
      return [tot[0] ? tot[1] / tot[0] : 0.5, tot[3] ? tot[2] / tot[3] : 0.5];
    };

    const R = RECETAS.length, K = FACTORES.length;
    const score = Array.from({ length: R }, () => new Array(K).fill(0));
    let elegida = [0, 0], cambios = 0, m = 0;
    const ap = [0, 0, 0, 0], og = [0, 0, 0, 0], serie = [];
    const medir = (st, ps, pf, os, of) => {
      let e = (ps - os) * (ps - os);
      st[1] += 1;
      let hit = null;
      if (of !== null) {
        e += (pf - of) * (pf - of);
        st[1] += 1;
        if (of !== 0.5 && pf !== 0.5) {
          hit = (pf > 0.5) === (of === 1) ? 1 : 0;
          st[2] += hit; st[3] += 1;
        }
      }
      st[0] += e;
      return hit;
    };

    for (let t = t0; t <= end; t++) {
      const k0 = combo[t];
      if (k0 !== null) {
        const preds = [];
        for (let r = 0; r < R; r++) preds.push(predecir(r, k0));
        const os = sube[t], of = prim[t];
        if (m >= ARRANQUE) {
          const r_ = elegida[0], f_ = FACTORES[elegida[1]];
          const hAp = medir(ap, ajustar(preds[r_][0], f_), ajustar(preds[r_][1], f_), os, of);
          const hOg = medir(og, preds[0][0], preds[0][1], os, of);
          serie.push([hAp, hOg]);
        }
        for (let r = 0; r < R; r++) {
          const [ps, pf] = preds[r], row = score[r];
          for (let k = 0; k < K; k++) {
            const f = FACTORES[k];
            const a = ajustar(ps, f) - os;
            let e = a * a;
            if (of !== null) { const b = ajustar(pf, f) - of; e += b * b; }
            row[k] += e;
          }
        }
        m += 1;
        if (m >= ARRANQUE) {
          let best = [0, 0];
          for (let r = 0; r < R; r++) for (let k = 0; k < K; k++) if (score[r][k] < score[best[0]][best[1]]) best = [r, k];
          const cur = score[elegida[0]][elegida[1]];
          if ((best[0] !== elegida[0] || best[1] !== elegida[1]) && score[best[0]][best[1]] < cur * (1 - HISTERESIS)) { cambios += 1; elegida = best; }
        }
      }
      sumar(t + 1 - h);
    }

    const curva = [];
    if (serie.length >= VENTANA) {
      const paso = Math.max(1, Math.floor((serie.length - VENTANA) / (PUNTOS_CURVA - 1)));
      const idxs = [];
      for (let i = VENTANA - 1; i < serie.length; i += paso) idxs.push(i);
      if (idxs[idxs.length - 1] !== serie.length - 1) idxs.push(serie.length - 1);
      idxs.forEach((i) => {
        const win = serie.slice(i - VENTANA + 1, i + 1);
        const vals = [0, 1].map((col) => {
          const dec = win.map((x) => x[col]).filter((x) => x !== null);
          return dec.length >= 20 ? (dec.reduce((s, x) => s + x, 0) / dec.length) * 100 : null;
        });
        curva.push([i + 1, vals[0], vals[1]]);
      });
    }

    const mejor = score.map((row) => Math.min(...row));
    const ranking = Array.from({ length: R }, (_, r) => r).sort((a, b) => (mejor[a] - mejor[b]) || (a - b));
    return {
      receta: elegida[0], factor: FACTORES[elegida[1]], repasadas: m, desde: bars[t0][0], hasta: bars[end][0], cambios, distancia: unit,
      brier_aprendido: ap[1] ? ap[0] / ap[1] : null, brier_original: og[1] ? og[0] / og[1] : null,
      aciertos_aprendido: ap[3] ? (ap[2] / ap[3]) * 100 : null, decisivas_aprendido: ap[3],
      aciertos_original: og[3] ? (og[2] / og[3]) * 100 : null, decisivas_original: og[3],
      medidas: serie.length, curva, ranking,
    };
  }

  const cache = new Map();
  /** aprender() solo cuando cerro una vela nueva: mientras tanto el resultado es el mismo. */
  function aprendido(clave, bars, combo, h, warmup) {
    const stamp = `${bars.length}|${bars[bars.length - 1][0]}|${h}|${warmup}`;
    const hit = cache.get(clave);
    if (hit && hit[0] === stamp) return hit[1];
    const res = aprender(bars, combo, h, warmup);
    cache.set(clave, [stamp, res]);
    return res;
  }

  const Apr = { rasgos, estados, combos, ajustar, aprender, aprendido, recetaTxt, confianzaTxt, RECETAS, RASGOS, FACTORES };
  root.Apr = Apr;
  if (typeof module !== 'undefined' && module.exports) module.exports = Apr;
})(typeof self !== 'undefined' ? self : globalThis);
