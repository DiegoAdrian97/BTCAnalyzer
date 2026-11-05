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
  const MONEDAS = ['BTC', 'ZEC', 'SOL', 'XRP', 'BABA', 'NVDA', 'GOOGL', 'AMD', 'AAPL', 'MSFT', 'AMZN', 'SPCX', 'META', 'TSLA', 'QQQ', 'SPY', 'MELI'];
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
    listo: (m) => !!porMoneda[m],      // si ya tiene analisis en memoria (elegirlo es instantaneo)
    precio: (m) => {                    // precio y apertura de 24 h del ultimo analisis (para mostrar algo al toque)
      const r = porMoneda[m] && porMoneda[m].find((x) => x.tabla === 'resumen');
      if (!r || !(+r.precio > 0)) return null;
      const c = +r.precio, ch = +r.cambio_24h;
      return { c, o: Number.isFinite(ch) ? c / (1 + ch / 100) : c };
    },
  };
  Object.defineProperty(window, 'abMoneda', { get: () => moneda, configurable: true });
  const porMoneda = {}, horaMoneda = {};
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

  const worker = new Worker(`worker.js${VER}`);
  const sym = () => `${moneda}USDT`;
  function elegir(m) {
    if (m === moneda || !MONEDAS.includes(m)) return;
    moneda = m;
    try { localStorage.setItem('app-moneda', m); } catch (e) { /* idem */ }
    const sel = document.getElementById('app-moneda-sel'); if (sel && sel.value !== m) sel.value = m;
    rows = porMoneda[m] || null;
    if (!rows) estado(`Preparando el análisis de ${m}…`);
    else { const min = Math.round((Date.now() - (horaMoneda[m] || Date.now())) / 60000); estado(min >= 1 ? `Análisis de hace ${min} min (hecho en segundo plano) · actualizando…` : ''); }
    worker.postMessage({ tipo: 'seguir', sym: sym() });
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
  worker.postMessage({ tipo: 'seguir', sym: sym(), todos: MONEDAS });
  worker.onmessage = (ev) => {
    const m = ev.data;
    if (m.sym && m.sym !== sym() && m.tipo !== 'analisis') return;
    if (m.tipo === 'analisis') {
      const mon = (m.sym || 'BTCUSDT').replace('USDT', '');
      if (m.guardado && porMoneda[mon]) return;           // ya hay uno nuevo: el guardado no hace falta
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
  };
  // con la app en segundo plano no se analiza: ahorra bateria y datos
  document.addEventListener('visibilitychange', () => { worker.postMessage(document.hidden ? { tipo: 'pausa' } : { tipo: 'seguir', sym: sym() }); if (!document.hidden) nuevaVersion(); });
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
  document.addEventListener('DOMContentLoaded', () => { if (!rows) estado('Preparando el análisis…'); });
})();
