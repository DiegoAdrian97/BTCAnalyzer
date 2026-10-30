/*
 * Los datos del mercado, pedidos directo desde el telefono (APIs publicas, sin claves).
 * - Velas de Binance Futures; si Binance limita los pedidos, de Bybit hasta que se libere.
 * - El historial de velas queda guardado en el telefono (IndexedDB): la primera vez se baja todo y
 *   despues solo lo nuevo.
 * - Lo que cambia lento se pide con cache: contexto cada 60 s, liquidaciones cada 5 min, libros cada 20 s.
 * BingX no se usa: su API rechaza los pedidos que vienen de paginas web.
 */
(function (root) {
  'use strict';
  const { TIMEFRAMES, TF_MS } = root.Analisis;
  const DAY = 86400000;
  const BINANCE = 'https://fapi.binance.com';
  const BYBIT_TF = { '5m': '5', '15m': '15', '30m': '30', '1h': '60', '4h': '240', '1d': 'D' };
  const banned = {};      // exchange -> hasta cuando (ms) no se le pide nada
  const memo = {};        // cache en memoria: clave -> [cuando, valor]
  // la cripto que se analiza (BTC o ZEC). Lo de BTC se guarda con las claves de siempre; lo demas, con el simbolo adelante.
  let SYM = 'BTCUSDT';
  const pre = () => (SYM === 'BTCUSDT' ? '' : `${SYM}:`);

  // ---------- almacenamiento en el telefono (si no hay, se trabaja en memoria) ----------
  let dbPromise = null;
  const memStore = new Map();
  function db() {
    if (!dbPromise) {
      dbPromise = new Promise((resolve, reject) => {
        const req = indexedDB.open('analista-btc', 1);
        req.onupgradeneeded = () => req.result.createObjectStore('kv');
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
    }
    return dbPromise;
  }
  async function dbGet(key) {
    try {
      const d = await db();
      return await new Promise((resolve, reject) => {
        const q = d.transaction('kv').objectStore('kv').get(key);
        q.onsuccess = () => resolve(q.result);
        q.onerror = () => reject(q.error);
      });
    } catch (e) {
      return memStore.get(key);
    }
  }
  async function dbSet(key, value) {
    memStore.set(key, value);
    try {
      const d = await db();
      await new Promise((resolve, reject) => {
        const tx = d.transaction('kv', 'readwrite');
        tx.objectStore('kv').put(value, key);
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error);
      });
    } catch (e) { /* sin almacenamiento: queda en memoria */ }
  }

  // ---------- pedidos ----------
  const isBanned = (eid) => (banned[eid] || 0) > Date.now();

  /** Pedido a un exchange. Si limito los pedidos, no se le vuelve a pedir nada hasta que venza la pausa. */
  async function pedir(eid, url) {
    if (isBanned(eid)) throw new Error(`${eid} en pausa por exceso de pedidos`);
    let res;
    try {
      res = await fetch(url, { cache: 'no-store' });
    } catch (e) {
      throw new Error(`${eid}: sin conexión`);
    }
    if ([418, 429, 403, 451].includes(res.status)) {
      let until = Date.now() + 120000;                        // sin fecha: dos minutos de pausa
      const body = await res.text().catch(() => '');
      const m = /banned until (\d+)/.exec(body);
      if (m) until = Number(m[1]);
      if (res.status === 403 || res.status === 451) until = Date.now() + 3600000;   // bloqueado desde esta conexion
      banned[eid] = until;
      throw new Error(`${eid} limitó los pedidos`);
    }
    if (!res.ok) throw new Error(`${eid}: error ${res.status}`);
    return res.json();
  }

  async function cached(key, ttl, fn) {
    const hit = memo[key];
    if (hit && Date.now() - hit[0] < ttl) return hit[1];
    const value = await fn();
    memo[key] = [Date.now(), value];
    return value;
  }

  // ---------- velas ----------
  async function klines(src, tf, start, limit) {
    if (src === 'binance') {
      const rows = await pedir('binance', `${BINANCE}/fapi/v1/klines?symbol=${SYM}&interval=${tf}&startTime=${start}&limit=${limit}`);
      return rows.map((r) => [r[0], +r[1], +r[2], +r[3], +r[4], +r[5]]);
    }
    // Bybit devuelve las mas nuevas primero y, si la ventana es grande, solo las ultimas: se pide una ventana justa
    const end = start + limit * TF_MS[tf] - 1;
    const j = await pedir('bybit', `https://api.bybit.com/v5/market/kline?category=linear&symbol=${SYM}&interval=${BYBIT_TF[tf]}&start=${start}&end=${end}&limit=${limit}`);
    return j.result.list.map((r) => [+r[0], +r[1], +r[2], +r[3], +r[4], +r[5]]).sort((a, b) => a[0] - b[0]);
  }

  async function lastTwo(src, tf) {
    if (src === 'binance') {
      const rows = await pedir('binance', `${BINANCE}/fapi/v1/klines?symbol=${SYM}&interval=${tf}&limit=2`);
      return rows.map((r) => [r[0], +r[1], +r[2], +r[3], +r[4], +r[5]]);
    }
    const j = await pedir('bybit', `https://api.bybit.com/v5/market/kline?category=linear&symbol=${SYM}&interval=${BYBIT_TF[tf]}&limit=2`);
    return j.result.list.map((r) => [+r[0], +r[1], +r[2], +r[3], +r[4], +r[5]]).sort((a, b) => a[0] - b[0]);
  }

  /** Velas cerradas: lo guardado en el telefono mas lo nuevo. */
  async function updateCandles(src, tf, days, now) {
    const key = `${pre()}velas:${src}:${tf}`, tfMs = TF_MS[tf], limit = src === 'binance' ? 1500 : 1000;
    let candles = (await dbGet(key)) || [];
    const before = candles.length;
    let since = candles.length ? candles[candles.length - 1][0] + tfMs : now - days * DAY;
    while (since + tfMs <= now) {
      const batch = (await klines(src, tf, since, limit)).filter((c) => c[0] >= since && c[0] + tfMs <= now);
      if (!batch.length) break;
      candles = candles.concat(batch);
      since = candles[candles.length - 1][0] + tfMs;
    }
    candles = candles.filter((c) => c[0] >= now - days * DAY);
    if (candles.length !== before) await dbSet(key, candles);
    return candles;
  }

  // ---------- datos del momento: open interest y long/short de Bybit, flujo y top traders de OKX, funding de BingX ----------
  // (igual que el servidor: a Binance no se le piden). Cada parte que falle se saltea.
  const okxId = () => SYM.replace('USDT', '-USDT-SWAP');
  const bybitOi = async (limit) => (await pedir('bybit', `https://api.bybit.com/v5/market/open-interest?category=linear&symbol=${SYM}&intervalTime=1h&limit=${limit}`))
    .result.list.map((x) => [+x.timestamp, +x.openInterest]).sort((x, y) => x[0] - y[0]);
  const bybitLs = async (limit) => (await pedir('bybit', `https://api.bybit.com/v5/market/account-ratio?category=linear&symbol=${SYM}&period=1h&limit=${limit}`))
    .result.list.filter((x) => +x.sellRatio > 0).map((x) => [+x.timestamp, +x.buyRatio / +x.sellRatio]).sort((x, y) => x[0] - y[0]);
  const intento = (p) => p.catch(() => null);

  // funding actual y promedio de los ultimos 7 dias (21 cobros de 8 h): el promedio entra en el termometro
  const prom = (xs) => (xs.length >= 15 ? xs.reduce((a, x) => a + x, 0) / xs.length : null);
  async function fundingRaw() {
    try {
      const s = SYM.replace('USDT', '-USDT');
      const [j, h] = await Promise.all([
        pedir('bingx', `https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex?symbol=${s}`),
        pedir('bingx', `https://open-api.bingx.com/openApi/swap/v2/quote/fundingRate?symbol=${s}&limit=21`).catch(() => null)]);
      return { tasa: +j.data.lastFundingRate, f7: h && Array.isArray(h.data) ? prom(h.data.slice(0, 21).map((x) => +x.fundingRate)) : null, fuente: 'BingX' };
    } catch (e) {   // si el navegador no puede leer BingX: el de Bybit
      const [t, h] = await Promise.all([
        pedir('bybit', `https://api.bybit.com/v5/market/tickers?category=linear&symbol=${SYM}`),
        pedir('bybit', `https://api.bybit.com/v5/market/funding/history?category=linear&symbol=${SYM}&limit=21`).catch(() => null)]);
      return { tasa: +t.result.list[0].fundingRate, f7: h ? prom(h.result.list.map((x) => +x.fundingRate)) : null, fuente: 'Bybit' };
    }
  }

  async function contextRaw() {
    const [oi, ls, taker, top, fr] = await Promise.all([
      intento(bybitOi(30)), intento(bybitLs(25)),
      intento(pedir('okx', `https://www.okx.com/api/v5/rubik/stat/taker-volume-contract?instId=${okxId()}&period=1H&limit=4`)
        .then((j) => j.data.slice(0, 4).reverse().map((x) => ({ buy: +x[2], sell: +x[1] })))),
      intento(pedir('okx', `https://www.okx.com/api/v5/rubik/stat/contracts/long-short-position-ratio-contract-top-trader?instId=${okxId()}&period=1H&limit=1`)
        .then((j) => +j.data[0][1])),
      intento(cached(`${pre()}funding`, 3 * 3600000, fundingRaw)),
    ]);
    if (!oi && !ls && !taker && !fr) throw new Error('sin datos del momento');
    return { oi, ls: ls && ls.map((x) => x[1]), taker, top, funding: fr ? fr.tasa : null, funding7: fr ? fr.f7 : null, fundingFuente: fr ? fr.fuente : null };
  }

  async function liqRaw() {
    const [oi, ls] = await Promise.all([bybitOi(200), bybitLs(200)]);
    return { oi, ls };
  }

  /** Libros de ordenes de 4 exchanges, en BTC. El que falle se saltea. */
  async function booksRaw() {
    const num = (rows, f = 1) => rows.map((r) => [+r[0], +r[1] * f]);
    const sources = [
      ['binance', 'Binance', async () => { const j = await pedir('binance', `${BINANCE}/fapi/v1/depth?symbol=${SYM}&limit=1000`); return [num(j.bids), num(j.asks)]; }],
      ['bybit', 'Bybit', async () => { const j = (await pedir('bybit', `https://api.bybit.com/v5/market/orderbook?category=linear&symbol=${SYM}&limit=500`)).result; return [num(j.b), num(j.a)]; }],
      // OKX cotiza en contratos de 0,01 BTC (solo BTC: en las demas el tamano del contrato es otro)
      SYM === 'BTCUSDT' && ['okx', 'OKX', async () => { const j = (await pedir('okx', 'https://www.okx.com/api/v5/market/books?instId=BTC-USDT-SWAP&sz=400')).data[0]; return [num(j.bids, 0.01), num(j.asks, 0.01)]; }],
      ['bitget', 'Bitget', async () => { const j = (await pedir('bitget', `https://api.bitget.com/api/v2/mix/market/merge-depth?symbol=${SYM}&productType=usdt-futures&limit=max`)).data; return [num(j.bids), num(j.asks)]; }],
    ];
    const got = await Promise.all(sources.filter(Boolean).map(async ([eid, name, fn]) => {
      try { const [bids, asks] = await fn(); return { eid, name, bids, asks }; } catch (e) { return null; }
    }));
    return got.filter(Boolean);
  }

  /** Junta todo lo que necesita el analisis. onProgress recibe textos para la pantalla de espera. */
  async function recolectar(onProgress, sym = 'BTCUSDT') {
    SYM = sym;
    const now = Date.now();
    const src = isBanned('binance') ? 'bybit' : 'binance';
    const booksP = cached(`${pre()}libros`, 20000, booksRaw).catch(() => []);
    const ctxP = cached(`${pre()}contexto`, 60000, contextRaw).catch(() => null);
    // noticias, ETF y prima de Coinbase: las junta la funcion del servidor (las paginas no pueden leer esas fuentes)
    const extP = cached('externo', 600000, async () => { const r = await fetch('api/contexto', { cache: 'no-store' }); if (!r.ok) throw new Error(r.status); return r.json(); }).catch(() => null);
    const liqP = cached(`${pre()}liquidaciones`, 300000, liqRaw).catch(() => null);
    const candles = {};
    let done = 0;
    await Promise.all(Object.entries(TIMEFRAMES).map(async ([tf, [days]]) => {
      candles[tf] = await updateCandles(src, tf, days, now);
      done += 1;
      if (onProgress) onProgress(`Velas listas: ${done} de 6 temporalidades`);
    }));
    let live5m = null;
    try {
      const last = candles['5m'][candles['5m'].length - 1][0];
      live5m = (await lastTwo(src, '5m')).filter((c) => c[0] > last && c[0] + TF_MS['5m'] > Date.now()).pop() || null;
    } catch (e) { /* sin la vela en curso, el analisis igual sirve con las cerradas */ }
    const price = live5m ? live5m[4] : candles['5m'][candles['5m'].length - 1][4];
    const log = (await dbGet(`${pre()}predicciones`)) || [];
    return { candles, live5m, price, now, ctxRaw: await ctxP, booksRaw: await booksP, liqRaw: await liqP, externo: await extP, log, fuente: src };
  }

  const Datos = { recolectar, guardarLog: (log, sym = 'BTCUSDT') => dbSet(`${sym === 'BTCUSDT' ? '' : `${sym}:`}predicciones`, log), isBanned };
  root.Datos = Datos;
})(typeof self !== 'undefined' ? self : globalThis);
