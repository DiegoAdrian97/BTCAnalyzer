/*
 * Los datos del mercado, pedidos directo desde el telefono (APIs publicas, sin claves).
 * - Velas de Binance Futures; si Binance limita los pedidos, de Bybit hasta que se libere.
 * - El historial de velas queda guardado en el telefono (IndexedDB): la primera vez se baja todo y
 *   despues solo lo nuevo.
 * - Lo que cambia lento se pide con cache: contexto y libros cada 60 s, liquidaciones cada 5 min.
 * - Los activos que no se estan mirando van "livianos" (ver recolectar): sin libros, mapa de liquidaciones ni opciones.
 * BingX no se usa: su API rechaza los pedidos que vienen de paginas web (y de OKX solo las liquidaciones, por lo mismo).
 */
(function (root) {
  'use strict';
  const { TIMEFRAMES, TF_MS } = root.Analisis;
  const DAY = 86400000;
  const BINANCE = 'https://fapi.binance.com';
  const BYBIT_TF = { '5m': '5', '15m': '15', '30m': '30', '1h': '60', '4h': '240', '1d': 'D' };
  // lo que no cotiza en Binance (MELI): velas de Bitget, que si deja leer desde el telefono
  const SOLO_BITGET = new Set(['MELIUSDT']);
  const ACCIONES_APP = new Set(['BABAUSDT', 'NVDAUSDT', 'GOOGLUSDT', 'AMDUSDT', 'AAPLUSDT', 'MSFTUSDT', 'AMZNUSDT', 'SPCXUSDT', 'METAUSDT', 'TSLAUSDT', 'QQQUSDT', 'SPYUSDT', 'MSTRUSDT', 'MELIUSDT']);
  const BITGET_TF = { '5m': '5m', '15m': '15m', '30m': '30m', '1h': '1H', '4h': '4H', '1d': '1D' };
  const bitgetVelas = (d) => (d || []).map((r) => [+r[0], +r[1], +r[2], +r[3], +r[4], +r[5]]).sort((a, b) => a[0] - b[0]);
  const banned = {};      // exchange -> hasta cuando (ms) no se le pide nada
  const memo = {};        // cache en memoria: clave -> [cuando, valor]
  // Lo de BTC se guarda con las claves de siempre; lo demas, con el simbolo adelante.
  const prefijo = (sym) => (sym === 'BTCUSDT' ? '' : `${sym}:`);

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
    try {
      const d = await db();
      await new Promise((resolve, reject) => {
        const tx = d.transaction('kv', 'readwrite');
        tx.objectStore('kv').put(value, key);
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error);
      });
    } catch (e) { memStore.set(key, value); /* sin almacenamiento: queda en memoria */ }
  }

  // ---------- pedidos ----------
  const isBanned = (eid) => (banned[eid] || 0) > Date.now();

  /** Pedido a un exchange. Si limito los pedidos, no se le vuelve a pedir nada hasta que venza la pausa. */
  // tiempo maximo por pedido: sin esto, un pedido colgado (red del celular, la app en segundo plano) dejaba la
  // pantalla "cargando velas" para siempre, porque el ciclo siguiente espera a que termine el anterior
  const ESPERA_MS = 15000;
  // Ritmo por exchange: con 17 activos analizandose de fondo, Bitget cortaba (sus limites son por segundo: ~20
  // pedidos/s para velas y libros, y 1 por segundo para el flujo de compras y ventas). Cada grupo espera su turno.
  const RITMO = { bitget: 80, 'bitget-flujo': 1100 };      // ms minimos entre dos pedidos del mismo grupo
  const turno = {};
  async function esperarTurno(eid) {
    const gap = RITMO[eid];
    if (!gap) return;
    const ahora = Date.now(), t = Math.max(ahora, turno[eid] || 0);
    turno[eid] = t + gap;
    if (t > ahora) await new Promise((r) => setTimeout(r, t - ahora));
  }
  async function pedir(eid, url) {
    if (isBanned(eid)) throw new Error(`${eid} en pausa por exceso de pedidos`);
    await esperarTurno(eid);
    if (isBanned(eid)) throw new Error(`${eid} en pausa por exceso de pedidos`);
    let res;
    const ctl = new AbortController(), tm = setTimeout(() => ctl.abort(), ESPERA_MS);
    try {
      res = await fetch(url, { cache: 'no-store', signal: ctl.signal });
    } catch (e) {
      clearTimeout(tm);
      throw new Error(ctl.signal.aborted ? `${eid}: no respondió en ${ESPERA_MS / 1000} s` : `${eid}: sin conexión`);
    }
    clearTimeout(tm);
    if ([418, 429, 403, 451].includes(res.status)) {
      let until = Date.now() + (eid.startsWith('bitget') ? 30000 : 120000);   // sin fecha: pausa (Bitget limita por segundo: 30 s)
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

  // cache con un solo pedido en vuelo por clave; si falla, no se reintenta hasta 2 min despues (antes una fuente
  // caida se volvia a pedir en cada ciclo y cada ciclo la esperaba)
  const enVuelo = {}, fallo = {}, sinDato = {}, velasEnVuelo = {}, liqHora = {};
  // Velas en memoria de los 2 ultimos activos analizados (el que estas mirando y el de fondo de turno): antes, cada 12 s
  // se leian de IndexedDB ~40.000 velas (una copia entera por temporalidad). El analisis no las modifica (probado con
  // las velas congeladas); IndexedDB sigue guardando todo para la proxima vez que se abre la app.
  // El que se esta mirando no sale nunca (antes, dos analisis de fondo seguidos lo sacaban y habia que releerlo).
  const memVelas = new Map();
  let fijo = null;
  function memDe(sym, fijar = false) {
    if (fijar) fijo = sym;
    let m = memVelas.get(sym);
    if (m) memVelas.delete(sym); else m = new Map();
    memVelas.set(sym, m);                                    // queda al final: el mas reciente
    while (memVelas.size > 2) memVelas.delete([...memVelas.keys()].find((k) => k !== fijo));
    return m;
  }
  const firmaLog = (l) => (l.length ? `${l.length}|${l[0].join()}|${l[l.length - 1].join()}` : '0');
  async function cached(key, ttl, fn) {
    const hit = memo[key];
    if (hit && Date.now() - hit[0] < ttl) return hit[1];
    if (fallo[key] && Date.now() - fallo[key] < Math.min(ttl, 120000)) { if (hit) return hit[1]; throw new Error(`${key}: falló hace poco`); }
    if (!enVuelo[key]) {
      enVuelo[key] = (async () => {
        try { const value = await fn(); memo[key] = [Date.now(), value]; delete fallo[key]; return value; }
        catch (e) { fallo[key] = Date.now(); throw e; }
        finally { delete enVuelo[key]; }
      })();
    }
    return enVuelo[key];
  }
  /** Lo que no es imprescindible no frena el analisis: si no llega a tiempo, va lo ultimo que se tenia (o nada) y
   *  el pedido sigue en segundo plano para el ciclo siguiente. */
  function aTiempo(p, key, ms, def) {
    const viejo = () => (memo[key] ? memo[key][1] : def);
    return Promise.race([p.catch(() => viejo()), new Promise((r) => setTimeout(() => r(viejo()), ms))]);
  }

  // Todo lo que depende del activo vive en una "fabrica" por simbolo: asi el analisis de un activo en segundo plano
  // (o un pedido que sigue en vuelo de un ciclo anterior) no puede mezclarse con el del activo que se esta mirando.
  function fuentes(SYM) {
    const pre = () => prefijo(SYM);
    // ---------- velas ----------
    async function klines(src, tf, start, limit) {
      if (src === 'bitget') {      // velas viejas de a 200, hasta endTime (de la mas vieja a la mas nueva)
        const end = start + limit * TF_MS[tf] - 1;
        const j = await pedir('bitget', `https://api.bitget.com/api/v2/mix/market/history-candles?symbol=${SYM}&productType=USDT-FUTURES&granularity=${BITGET_TF[tf]}&limit=${limit}&endTime=${end}`);
        return bitgetVelas(j.data).filter((r) => r[0] >= start);
      }
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
      if (src === 'bitget') {
        const j = await pedir('bitget', `https://api.bitget.com/api/v2/mix/market/candles?symbol=${SYM}&productType=USDT-FUTURES&granularity=${BITGET_TF[tf]}&limit=2`);
        return bitgetVelas(j.data);
      }
      if (src === 'binance') {
        const rows = await pedir('binance', `${BINANCE}/fapi/v1/klines?symbol=${SYM}&interval=${tf}&limit=2`);
        return rows.map((r) => [r[0], +r[1], +r[2], +r[3], +r[4], +r[5]]);
      }
      const j = await pedir('bybit', `https://api.bybit.com/v5/market/kline?category=linear&symbol=${SYM}&interval=${BYBIT_TF[tf]}&limit=2`);
      return j.result.list.map((r) => [+r[0], +r[1], +r[2], +r[3], +r[4], +r[5]]).sort((a, b) => a[0] - b[0]);
    }

    /** Velas cerradas: lo guardado en el telefono mas lo nuevo. */
    // Si otro ciclo ya esta bajando las mismas velas (el analisis de fondo cortado al elegir ese activo), se espera ese
    // pedido en vez de repetirlo: antes se bajaban dos veces y las dos escrituras se pisaban.
    function updateCandles(src, tf, days, now) {
      const key = `${pre()}velas:${src}:${tf}`;
      if (!velasEnVuelo[key]) velasEnVuelo[key] = bajarVelas(key, src, tf, days, now).finally(() => { delete velasEnVuelo[key]; });
      return velasEnVuelo[key];
    }
    async function bajarVelas(key, src, tf, days, now) {
      const tfMs = TF_MS[tf], limit = src === 'binance' ? 1500 : src === 'bitget' ? 200 : 1000, mem = memDe(SYM);
      let candles = mem.get(key) || (await dbGet(key)) || [];
      const before = candles.length, ultAntes = before ? candles[before - 1][0] : 0;
      let since = candles.length ? candles[candles.length - 1][0] + tfMs : now - days * DAY;
      while (since + tfMs <= now) {
        const falta = Math.ceil((now - since) / tfMs) + 1;
        let batch;
        if (src !== 'bitget' && falta > limit) {
          // varias paginas (la primera vez, o despues de dias sin abrir): todas juntas. Antes iban una detras de otra:
          // en el 5m eran 6 viajes seguidos, y en el 3G del celu cada viaje tarda medio segundo o mas
          const inicios = [];
          for (let t = since; t + tfMs <= now && inicios.length < 8; t += limit * tfMs) inicios.push(t);
          const paginas = await Promise.all(inicios.map((t) => klines(src, tf, t, limit)));
          const visto = new Set();
          batch = paginas.flat().filter((c) => c[0] >= since && c[0] + tfMs <= now && !visto.has(c[0]) && visto.add(c[0])).sort((a, b) => a[0] - b[0]);
        } else batch = (await klines(src, tf, since, src === 'bitget' ? limit : Math.min(limit, Math.max(2, falta)))).filter((c) => c[0] >= since && c[0] + tfMs <= now);
        if (!batch.length) {
          // Bitget no salta solo al primer dia que cotiza: se avanza de a una ventana hasta encontrar velas
          if (src === 'bitget' && since + limit * tfMs < now) { since += limit * tfMs; continue; }
          break;
        }
        candles = candles.concat(batch);
        since = candles[candles.length - 1][0] + tfMs;
      }
      if (candles.length && candles[0][0] < now - days * DAY) candles = candles.filter((c) => c[0] >= now - days * DAY);
      // se guarda si llego alguna vela (antes solo si cambiaba el largo: con la ventana llena entra una y sale otra, el
      // largo queda igual y el telefono se quedaba con las velas viejas; al abrir la app habia que bajar todo lo que faltaba)
      if (candles.length !== before || (candles.length && candles[candles.length - 1][0] !== ultAntes)) await dbSet(key, candles);
      mem.set(key, candles);
      return candles;
    }

    // ---------- datos del momento: open interest, long/short y funding de Bybit, flujo de Bitget y top traders de Binance ----------
    // (si Bybit no tiene el par, como pasa con algunas acciones: OI y long/short de Binance, funding y base de Bitget)
    // (el servidor usa OKX y BingX, que el navegador no deja leer). Cada parte que falle se saltea.
    const bybitOi = async (limit) => (await pedir('bybit', `https://api.bybit.com/v5/market/open-interest?category=linear&symbol=${SYM}&intervalTime=1h&limit=${limit}`))
      .result.list.map((x) => [+x.timestamp, +x.openInterest]).sort((x, y) => x[0] - y[0]);
    const bybitLs = async (limit) => (await pedir('bybit', `https://api.bybit.com/v5/market/account-ratio?category=linear&symbol=${SYM}&period=1h&limit=${limit}`))
      .result.list.filter((x) => +x.sellRatio > 0).map((x) => [+x.timestamp, +x.buyRatio / +x.sellRatio]).sort((x, y) => x[0] - y[0]);
    const intento = (p) => p.catch(() => null);
    // respaldo cuando Bybit no tiene el par (acciones): mismos datos de Binance (MELI no esta en Binance)
    const binanceOi = async (limit) => (await pedir('binance-datos', `${BINANCE}/futures/data/openInterestHist?symbol=${SYM}&period=1h&limit=${limit}`))
      .map((x) => [+x.timestamp, +x.sumOpenInterest]).sort((x, y) => x[0] - y[0]);
    const binanceLs = async (limit) => (await pedir('binance-datos', `${BINANCE}/futures/data/globalLongShortAccountRatio?symbol=${SYM}&period=1h&limit=${limit}`))
      .map((x) => [+x.timestamp, +x.longShortRatio]).sort((x, y) => x[0] - y[0]);
    const conRespaldo = (a, b) => a().then((r) => { if (!r.length) throw new Error('sin datos'); return r; })
      .catch((e) => { if (SOLO_BITGET.has(SYM)) throw e; return b(); });
    const oiSerie = (n) => conRespaldo(() => bybitOi(n), () => binanceOi(n));
    const lsSerie = (n) => conRespaldo(() => bybitLs(n), () => binanceLs(n));

    // funding actual y promedio de los ultimos 7 dias (21 cobros de 8 h): el promedio entra en el termometro.
    // De Bybit: BingX no manda el permiso CORS y el navegador siempre lo bloqueaba (2 pedidos fallidos cada 3 h).
    const prom = (xs) => (xs.length >= 15 ? xs.reduce((a, x) => a + x, 0) / xs.length : null);
    async function fundingRaw() {
      const [t, h] = await Promise.all([
        pedir('bybit', `https://api.bybit.com/v5/market/tickers?category=linear&symbol=${SYM}`),
        pedir('bybit', `https://api.bybit.com/v5/market/funding/history?category=linear&symbol=${SYM}&limit=21`).catch(() => null)]);
      return { tasa: +t.result.list[0].fundingRate, f7: h ? prom(h.result.list.map((x) => +x.fundingRate)) : null, fuente: 'Bybit' };
    }
    const BG = 'https://api.bitget.com/api/v2/mix/market';
    async function fundingBitget() {
      const [t, h] = await Promise.all([
        pedir('bitget', `${BG}/current-fund-rate?symbol=${SYM}&productType=usdt-futures`),
        pedir('bitget', `${BG}/history-fund-rate?symbol=${SYM}&productType=usdt-futures&pageSize=21`).catch(() => null)]);
      return { tasa: +t.data[0].fundingRate, f7: h ? prom(h.data.map((x) => +x.fundingRate)) : null, fuente: 'Bitget' };
    }
    // compras y ventas a mercado de las ultimas 4 horas (la ultima, en curso) y top traders. El servidor los saca de
    // OKX, pero esos endpoints de OKX no mandan el permiso CORS: en el navegador fallaban siempre y las senales de
    // flujo nunca entraban en la explicacion. Bitget y Binance si dejan leerlos desde una pagina.
    const bitgetTaker = async () => {
      const k = `${pre()}sin-flujo-bitget`;
      if (Date.now() - (sinDato[k] || 0) < 86400000) throw new Error('Bitget no tiene el flujo de este par');
      try {
        return (await pedir('bitget-flujo', `https://api.bitget.com/api/v2/mix/market/taker-buy-sell?symbol=${SYM}&productType=usdt-futures&period=1h`))
          .data.map((x) => ({ t: +x.ts, buy: +x.buyVolume, sell: +x.sellVolume })).sort((a, b) => a.t - b.t).slice(-4).map(({ buy, sell }) => ({ buy, sell }));
      } catch (e) {
        if (/error 400/.test(e.message)) sinDato[k] = Date.now();      // NVDA, GOOGL, BABA, MELI...: no se vuelve a pedir en un dia
        throw e;
      }
    };
    // Bitget no tiene este dato para varias acciones (NVDA, GOOGL, BABA, MELI): respaldo en Binance
    const binanceTaker = async () => (await pedir('binance-datos', `${BINANCE}/futures/data/takerlongshortRatio?symbol=${SYM}&period=1h&limit=4`))
      .map((x) => ({ t: +x.timestamp, buy: +x.buyVol, sell: +x.sellVol })).sort((a, b) => a.t - b.t).map(({ buy, sell }) => ({ buy, sell }));
    // con su propio nombre: si Binance limita este pedido, las velas siguen saliendo de Binance
    // perpetuo contra spot: precio de marca e indice de Bybit (cada minuto, con el resto del contexto)
    const bybitBase = async () => { const t = (await pedir('bybit', `https://api.bybit.com/v5/market/tickers?category=linear&symbol=${SYM}`)).result.list[0];
      return { mark: +t.markPrice, index: +t.indexPrice }; };
    const bitgetBase = async () => { const t = (await pedir('bitget', `${BG}/symbol-price?symbol=${SYM}&productType=usdt-futures`)).data[0];
      return { mark: +t.markPrice, index: +t.indexPrice }; };
    // opciones de BTC (Deribit, publico y con permiso CORS): libro de opciones y DVOL de 30 dias, cada 10 min
    async function opcionesRaw() {
      const now = Date.now(), D = 'https://www.deribit.com/api/v2/public';
      const [libro, dv] = await Promise.all([pedir('deribit', `${D}/get_book_summary_by_currency?currency=BTC&kind=option`),
        pedir('deribit', `${D}/get_volatility_index_data?currency=BTC&start_timestamp=${now - 30 * DAY}&end_timestamp=${now}&resolution=3600`)]);
      return { libro: libro.result, dvol: dv.result.data.map((x) => [+x[0] + 3600000, +x[4]]) };
    }
    const binanceTop = async () => +(await pedir('binance-datos', `${BINANCE}/futures/data/topLongShortPositionRatio?symbol=${SYM}&period=1h&limit=1`))[0].longShortRatio;

    // liquidaciones reales de OKX de la ultima hora (como liq_okx de analisis_btc.py): [ms, lado, usd]
    // Lo de la ultima hora queda en memoria y en cada vuelta se piden solo las nuevas: antes se bajaba la hora entera
    // cada minuto (hasta 6 paginas de 100); ahora casi siempre alcanza con una.
    async function liqOkx(now) {
      const hora = now - 3600000, prev = (liqHora[SYM] || []).filter((x) => x[0] >= hora);
      const tope = prev.length ? Math.max(...prev.map((x) => x[0])) : 0;
      const out = []; let after = null;
      for (let k = 0; k < 6; k++) {
        const j = await pedir('okx', `https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&instFamily=BTC-USDT&state=filled&limit=100${after ? `&after=${after}` : ''}`);
        const det = (j.data || []).flatMap((g) => g.details || []);
        if (!det.length) break;
        det.forEach((d) => out.push([+d.ts, d.posSide, +d.sz * 0.01 * +d.bkPx]));
        after = Math.min(...det.map((d) => +d.ts));
        if (after < hora || (tope && after <= tope)) break;     // ya se llego a lo que se tenia
      }
      // lo nuevo (desde la mas nueva hasta after) y, de lo que se tenia, lo anterior a eso: sin repetidas
      const res = out.concat(after === null ? prev : prev.filter((x) => x[0] < after)).filter((x) => x[0] >= hora);
      liqHora[SYM] = res;
      return res;
    }

    async function contextRaw() {
      const now = Date.now();
      const liqP = SYM === 'BTCUSDT' ? intento(liqOkx(now)) : Promise.resolve(null);
      const [oi, ls, taker, top, fr, base] = await Promise.all([
        intento(oiSerie(30)), intento(lsSerie(25)), intento(bitgetTaker().catch((e) => { if (SOLO_BITGET.has(SYM)) throw e; return binanceTaker(); })), SOLO_BITGET.has(SYM) ? null : intento(binanceTop()),
        intento(cached(`${pre()}funding`, 3 * 3600000, () => fundingRaw().catch(fundingBitget))), intento(bybitBase().catch(bitgetBase)),
      ]);
      if (!oi && !ls && !taker && !fr) throw new Error('sin datos del momento');
      return { oi, ls: ls && ls.map((x) => x[1]), taker, top, funding: fr ? fr.tasa : null, funding7: fr ? fr.f7 : null, fundingFuente: fr ? fr.fuente : null,
        liq: await liqP, liqT: now, base };
    }

    async function liqRaw() {
      const [oi, ls] = await Promise.all([oiSerie(200), lsSerie(200)]);
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
    return { updateCandles, lastTwo, contextRaw, liqRaw, booksRaw, opcionesRaw };
  }

  /** Junta todo lo que necesita el analisis. onProgress recibe textos para la pantalla de espera. */
  // Lo que se tenia guardado de una clave, si es de hace menos de ms (para los activos de fondo)
  const reciente = (key, ms, def) => (memo[key] && Date.now() - memo[key][0] < ms ? memo[key][1] : def);
  /**
   * Todo lo que necesita el analisis de un activo. Con { liviano: true } (los activos que no se estan mirando) no se
   * piden los libros (unos 100 KB de 4 exchanges), el mapa de liquidaciones ni las opciones: se usa lo que hubiera de
   * hace poco o nada. Ese analisis solo se ve un instante al elegir el activo, hasta que llega el completo (1-3 s).
   */
  async function recolectar(onProgress, sym = 'BTCUSDT', { liviano = false } = {}) {
    const { updateCandles, lastTwo, contextRaw, liqRaw, booksRaw, opcionesRaw } = fuentes(sym), pre = () => prefijo(sym);
    const now = Date.now();
    const src = SOLO_BITGET.has(sym) ? 'bitget' : isBanned('binance') ? 'bybit' : 'binance';
    const mem = memDe(sym, !liviano);
    // libros cada 60 s (antes 20 s): son lo mas pesado de cada ciclo y los muros no cambian tan rapido
    const booksP = liviano ? Promise.resolve(reciente(`${pre()}libros`, 15 * 60000, [])) : cached(`${pre()}libros`, 60000, booksRaw).catch(() => []);
    const ctxP = cached(`${pre()}contexto`, 60000, contextRaw).catch(() => null);
    // noticias, ETF y prima de Coinbase: las junta la funcion del servidor (las paginas no pueden leer esas fuentes)
    // cada accion tiene sus propias noticias (empresa, region, sector y bolsa); las criptos comparten las de BTC
    const accion = ACCIONES_APP.has(sym) ? sym.replace('USDT', '') : null, extK = accion ? `externo:${accion}` : 'externo';
    const extP = cached(extK, liviano ? 30 * 60000 : 600000, async () => {
      const ctl = new AbortController(), tm = setTimeout(() => ctl.abort(), ESPERA_MS);
      try { const r = await fetch(accion ? `api/contexto?moneda=${accion}` : 'api/contexto', { cache: 'no-store', signal: ctl.signal }); if (!r.ok) throw new Error(r.status); return r.json(); } finally { clearTimeout(tm); }
    }).catch(() => null);
    const liqP = liviano ? Promise.resolve(reciente(`${pre()}liquidaciones`, 30 * 60000, null)) : cached(`${pre()}liquidaciones`, 300000, liqRaw).catch(() => null);
    const opcP = sym !== 'BTCUSDT' ? Promise.resolve(null) : liviano ? Promise.resolve(reciente('opciones', 30 * 60000, null)) : cached('opciones', 600000, opcionesRaw).catch(() => null);
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
    // el registro de predicciones (hasta 20.000) queda en memoria: antes se leia de IndexedDB en cada ciclo (y se
    // volvia a escribir entero), cada 12 s
    let log = mem.get('log');
    if (!log) { log = (await dbGet(`${pre()}predicciones`)) || []; mem.set('log', log); mem.set('logFirma', firmaLog(log)); }
    // con las velas listas, el resto tiene 3 s mas: lo que falte va con lo ultimo que se tenia
    const p = pre(), [ctxR, booksR, liqR, extR, opcR] = await Promise.all([aTiempo(ctxP, `${p}contexto`, 3000, null),
      aTiempo(booksP, `${p}libros`, 3000, []), aTiempo(liqP, `${p}liquidaciones`, 3000, null), aTiempo(extP, extK, 3000, null),
      aTiempo(opcP, 'opciones', 3000, null)]);
    return { candles, live5m, price, now, ctxRaw: ctxR, booksRaw: booksR, liqRaw: liqR, externo: extR, opcionesRaw: opcR, log, fuente: src };
  }

  // el ultimo analisis de cada activo, guardado en el telefono: al abrir la app se muestra al toque mientras se calcula
  const ultimo = (sym) => dbGet(`ultimo:${sym}`);
  const guardarUltimo = (sym, rows) => dbSet(`ultimo:${sym}`, { hora: Date.now(), rows });
  /** Se guarda solo si cambio (entran predicciones nuevas con cada vela cerrada, no en cada ciclo). Solo se agregan
   *  al final y se recortan del principio: con el largo, la primera y la ultima alcanza para saberlo. */
  function guardarLog(log, sym = 'BTCUSDT') {
    const mem = memDe(sym), f = firmaLog(log);
    mem.set('log', log);
    if (mem.get('logFirma') === f) return Promise.resolve();
    mem.set('logFirma', f);
    return dbSet(`${prefijo(sym)}predicciones`, log);
  }
  const Datos = { recolectar, ultimo, guardarUltimo, guardarLog, isBanned };
  root.Datos = Datos;
})(typeof self !== 'undefined' ? self : globalThis);
