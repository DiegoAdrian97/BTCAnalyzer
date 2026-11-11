/*
 * Une la pagina del dashboard con el analisis que corre en el telefono: le da a la pagina el objeto `dash`
 * que usa en claude.ai, y le pasa cada analisis nuevo que manda el worker.
 */
(function () {
  'use strict';
  // ?v= de la pagina (generar_pagina.py): el worker y sus archivos se piden con la misma version
  const VER = document.currentScript && document.currentScript.src.includes('?') ? document.currentScript.src.slice(document.currentScript.src.indexOf('?')) : '';
  let rows = null;
  const fns = [];
  // el activo que se analiza (cada uno con su ultimo analisis: en memoria y guardado en el telefono para mostrarlo al toque)
  const MONEDAS = ['BTC', 'ZEC', 'SOL', 'XRP', 'BABA', 'NVDA', 'GOOGL', 'AMD', 'AAPL', 'MSFT', 'AMZN', 'SPCX', 'META', 'TSLA', 'QQQ', 'SPY', 'MSTR', 'MELI'];
  let moneda = 'BTC';
  try { const g = localStorage.getItem('app-moneda'); moneda = MONEDAS.includes(g) ? g : 'BTC'; } catch (e) { /* sin almacenamiento */ }
  // Contexto del activo (como un Context de React, sin React): una sola fuente de verdad de que activo se esta mirando.
  // Las partes de la pagina se suscriben y se enteran cuando cambia; el worker lo usa para priorizar ese analisis.
  const subs = new Set();
  window.abActivo = {
    get: () => moneda,
    todos: () => MONEDAS.slice(),
    set: (m) => elegir(m),
    subscribe(fn) { subs.add(fn); return () => subs.delete(fn); },
    listo: (m) => !!(porMoneda[m] || crudo[m]),      // si ya tiene analisis en memoria (elegirlo es instantaneo)
    precio: (m) => {                    // precio y apertura de 24 h del ultimo analisis (para mostrar algo al toque)
      const r = porMoneda[m] ? porMoneda[m].find((x) => x.tabla === 'resumen') : resumenCrudo[m];
      if (!r || !(+r.precio > 0)) return null;
      const c = +r.precio, ch = +r.cambio_24h;
      return { c, o: Number.isFinite(ch) ? c / (1 + ch / 100) : c };
    },
  };
  Object.defineProperty(window, 'abMoneda', { get: () => moneda, configurable: true });
  const porMoneda = {}, horaMoneda = {};
  // los analisis de fondo llegan como texto (JSON armado en el worker): copiar un texto es casi gratis y armar los
  // objetos en el hilo de la pantalla (unas 3.000 filas) se hace recien al elegir ese activo. Antes cada analisis de
  // fondo trababa la pantalla un poco aunque nadie lo mirara
  const crudo = {}, resumenCrudo = {};
  const filasDe = (m) => {
    if (!porMoneda[m] && crudo[m]) { try { porMoneda[m] = JSON.parse(crudo[m]); } catch (e) { /* texto roto: se espera el proximo */ } delete crudo[m]; }
    return porMoneda[m] || null;
  };
  const redraw = () => fns.forEach((f) => f());
  window.abLive = true;            // la pagina se conecta sola al WebSocket de Binance para los ticks
  window.abPosicionesApi = 'api/posiciones';   // BingX en vivo (solo lectura): ver api/posiciones.js
  // tema: el elegido con el boton (guardado en este navegador) o el del sistema. Se aplica antes de pintar.
  try { const tm = localStorage.getItem('ab-tema'); if (tm === 'dark' || tm === 'light') document.documentElement.dataset.theme = tm; } catch (e) { /* idem */ }
  window.abOscuro = () => { const tm = document.documentElement.dataset.theme; return tm ? tm === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches; };
  // paletas validadas para daltonismo y contraste (claro y oscuro)
  const COLORES = { oscuro: ['#4a8af4', '#bf7f1a', '#9270f0', '#14a394', '#f08bb4', '#a3e635', '#fb923c', '#94a3b8'],
    claro: ['#2563eb', '#d97706', '#7c3aed', '#0f9488', '#d1477e', '#4d7c0f', '#c2410c', '#64748b'] };
  window.dash = {
    get colors() { return window.abOscuro() ? COLORES.oscuro : COLORES.claro; },
    data: () => (rows ? { status: 'ok', data: rows, columns: [], meta: [], refreshing: false }
      : { status: 'loading', data: [], columns: [], meta: [], refreshing: false }),
    onData: (fn) => { fns.push(fn); fn(); },
    params: () => ({}), setParams() {}, resetParams() {}, setLink() {}, refresh() {},
  };
  let t = null;
  window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(redraw, 150); });

  const estado = (texto, error) => {
    const el = document.getElementById('estado-app');
    if (!el) return;
    el.hidden = !texto;
    el.classList.toggle('es-error', !!error);
    el.querySelector('span').textContent = texto || '';
  };

  try { localStorage.removeItem('ab-velocidad'); } catch (e) { /* lo que guardaba la seccion Velocidad (ya no esta) */ }

  // El worker se arranca despues de pedir sus archivos todos juntos: el importScripts del worker los baja de a uno (6
  // viajes seguidos la primera vez despues de cada version). Con la cache inmutable (vercel.json) despues salen del
  // telefono al instante. Mientras tanto, lo que se le manda queda en cola
  let worker = null;
  const cola = [], aWorker = (m) => (worker ? worker.postMessage(m) : cola.push(m));
  const ARCHIVOS = ['worker.js', 'indicadores.js', 'aprendizaje.js', 'fuerte.js', 'analisis.js', 'datos.js'];
  const arrancar = () => {
    if (worker) return;
    worker = new Worker(`worker.js${VER}`);
    worker.onmessage = alMensaje;
    cola.splice(0).forEach((m) => worker.postMessage(m));
  };
  if (VER) {
    Promise.all(ARCHIVOS.map((f) => fetch(f + VER).then((r) => r.blob()).catch(() => null))).then(arrancar);
    setTimeout(arrancar, 8000);           // si algun pedido se cuelga, el worker arranca igual
  } else setTimeout(arrancar, 0);
  const sym = () => `${moneda}USDT`;
  function elegir(m) {
    if (m === moneda || !MONEDAS.includes(m)) return;
    moneda = m;
    try { localStorage.setItem('app-moneda', m); } catch (e) { /* idem */ }
    const sel = document.getElementById('app-moneda-sel'); if (sel && sel.value !== m) sel.value = m;
    rows = filasDe(m);
    if (!rows) estado(`Preparando el análisis de ${m}…`);
    else { const min = Math.round((Date.now() - (horaMoneda[m] || Date.now())) / 60000); estado(min >= 1 ? `Análisis de hace ${min} min (hecho en segundo plano) · actualizando…` : ''); }
    aWorker({ tipo: 'seguir', sym: sym() });
    subs.forEach((fn) => { try { fn(m); } catch (e) { /* una parte que falle no frena a las demas */ } });
    redraw();
  }
  document.addEventListener('DOMContentLoaded', () => {
    // el desplegable queda oculto (lo usa el panel lateral para los nombres y grupos); se elige desde el panel
    const sw = document.getElementById('app-moneda');
    if (!sw) return;
    const sel = document.getElementById('app-moneda-sel');
    sel.value = moneda;
    sel.addEventListener('change', () => elegir(sel.value));
  });
  // el elegido primero; los demas se van analizando en segundo plano (worker.js)
  aWorker({ tipo: 'seguir', sym: sym(), todos: MONEDAS });
  // "Reproducir" pide al worker las predicciones guardadas (window.abRegistro(tf, desde, hasta) -> promesa)
  const registros = new Map(); let regId = 0;
  window.abRegistro = (tf, desde, hasta) => new Promise((ok) => {
    const id = ++regId; registros.set(id, ok);
    aWorker({ tipo: 'registro', id, sym: sym(), tf, desde, hasta });
    setTimeout(() => { if (registros.has(id)) { registros.delete(id); ok([]); } }, 8000);
  });
  function alMensaje(ev) {
    const m = ev.data;
    if (m.tipo === 'registro') { const ok = registros.get(m.id); if (ok) { registros.delete(m.id); ok(m.log || []); } return; }
    if (m.sym && m.sym !== sym() && m.tipo !== 'analisis') return;
    if (m.tipo === 'analisis') {
      const mon = (m.sym || 'BTCUSDT').replace('USDT', '');
      if (m.guardado && (porMoneda[mon] || crudo[mon])) return;           // ya hay uno nuevo: el guardado no hace falta
      if (m.json) {                                        // de fondo, como texto
        delete porMoneda[mon]; crudo[mon] = m.json; resumenCrudo[mon] = m.resumen || null; horaMoneda[mon] = m.hora || Date.now();
        if (m.sym === sym()) { rows = filasDe(mon); redraw(); }   // justo lo eligieron mientras se hacia
        return;
      }
      delete crudo[mon];
      porMoneda[mon] = m.rows; horaMoneda[mon] = m.guardado ? m.hora : Date.now();
      if (m.sym && m.sym !== sym()) return;                // de fondo: queda listo para cuando lo elijan
      rows = m.rows;
      window.abAnalyses = m.numero;
      if (m.guardado) {
        const min = Math.max(1, Math.round((Date.now() - m.hora) / 60000));
        estado(`Último análisis guardado (hace ${min < 60 ? `${min} min` : `${Math.round(min / 60)} h`}) · actualizando…`);
      } else estado(m.fuente === 'bybit' ? 'Binance limitó los pedidos: por ahora las velas salen de Bybit.' : '');
      redraw();
    } else if (m.tipo === 'progreso' && !rows) {
      estado(`Preparando el primer análisis… ${m.texto}`);
    } else if (m.tipo === 'error') {
      estado(rows ? `No se pudo actualizar (${m.texto}). Se reintenta solo.` : `No se pudo preparar el análisis: ${m.texto}. Se reintenta solo.`, true);
    }
  }

  // con la app en segundo plano no se analiza: ahorra bateria y datos
  document.addEventListener('visibilitychange', () => { aWorker(document.hidden ? { tipo: 'pausa' } : { tipo: 'seguir', sym: sym() }); if (!document.hidden) nuevaVersion(); });
  // el iPhone deja la app "dormida" con el codigo viejo aunque haya una version nueva publicada: al volver a la app
  // (y cada 5 min) se compara con version.txt y, si cambio, se recarga sola
  async function nuevaVersion() {
    if (!window.AB_PAGINA) return;
    try {
      const v = (await (await fetch(`version.txt?t=${Date.now()}`, { cache: 'no-store' })).text()).trim();
      if (/^[0-9a-f]{10}$/.test(v) && v !== window.AB_PAGINA) location.reload();
    } catch (e) { /* sin conexion: se prueba la proxima vez */ }
  }
  setInterval(() => { if (!document.hidden) nuevaVersion(); }, 5 * 60000);
  // service worker (sw.js): abre sin conexion y sin volver a bajar lo que no cambio
  if ('serviceWorker' in navigator && (location.protocol === 'https:' || /[?&]sw\b/.test(location.search))) {
    window.addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => { /* sin service worker: anda igual */ }));
  }
  document.addEventListener('DOMContentLoaded', () => { if (!rows) estado('Preparando el análisis…'); });
})();
