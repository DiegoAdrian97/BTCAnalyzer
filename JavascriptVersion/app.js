/*
 * Une la pagina del dashboard con el analisis que corre en el telefono: le da a la pagina el objeto `dash`
 * que usa en claude.ai, y le pasa cada analisis nuevo que manda el worker.
 */
(function () {
  'use strict';
  let rows = null;
  const fns = [];
  const redraw = () => fns.forEach((f) => f());
  window.abLive = true;            // la pagina se conecta sola al WebSocket de Binance para los ticks
  const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  window.dash = {
    colors: dark ? ['#7aa7ff', '#e0a64a', '#c78bff', '#4fd1c5', '#f08bb4', '#a3e635', '#fb923c', '#94a3b8']
      : ['#2f6fde', '#b7791f', '#8b4fd6', '#0f9488', '#d1477e', '#4d7c0f', '#c2410c', '#64748b'],
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

  // ---------- interruptor Web | Holograma: el holograma se abre encima, en la misma pagina ----------
  let holo = null;
  const sendHolo = () => { if (holo && rows) holo.contentWindow.postMessage({ tipo: 'analisis', rows }, location.origin); };
  const markMode = (m) => document.querySelectorAll('#app-modo button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.app === m)));
  function openHolo() {
    if (holo) return;
    holo = document.createElement('iframe');
    holo.src = 'holograma.html?embed=1';
    holo.title = 'Holograma';
    holo.allow = 'camera; fullscreen; autoplay';
    holo.style.cssText = 'position:fixed;inset:0;width:100vw;height:100dvh;border:0;z-index:100;background:#000';
    document.body.append(holo);
    document.documentElement.style.overflow = 'hidden';
    markMode('holo');
    try { localStorage.setItem('app-modo', 'holo'); } catch (e) { /* sin almacenamiento */ }
  }
  function closeHolo() {
    if (!holo) return;
    holo.remove(); holo = null;
    document.documentElement.style.overflow = '';
    markMode('web');
    try { localStorage.setItem('app-modo', 'web'); } catch (e) { /* idem */ }
    redraw();
  }
  window.addEventListener('message', (ev) => {
    if (ev.origin !== location.origin || !ev.data) return;
    if (ev.data.tipo === 'holo-salir') closeHolo();
    else if (ev.data.tipo === 'holo-listo') sendHolo();
  });
  document.addEventListener('DOMContentLoaded', () => {
    const sw = document.getElementById('app-modo');
    if (!sw) return;
    sw.hidden = false;
    sw.addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) (b.dataset.app === 'holo' ? openHolo : closeHolo)(); });
    let saved = null;
    try { saved = localStorage.getItem('app-modo'); } catch (e) { /* idem */ }
    if (saved === 'holo' || new URLSearchParams(location.search).get('modo') === 'holograma') openHolo();
  });

  const worker = new Worker('worker.js');
  worker.onmessage = (ev) => {
    const m = ev.data;
    if (m.tipo === 'analisis') {
      rows = m.rows;
      window.abAnalyses = m.numero;
      estado(m.fuente === 'bybit' ? 'Binance limitó los pedidos: por ahora las velas salen de Bybit.' : '');
      if (holo) sendHolo(); else redraw();      // con el holograma abierto, la pagina de abajo no se redibuja
    } else if (m.tipo === 'progreso' && !rows) {
      estado(`Preparando el primer análisis… ${m.texto}`);
    } else if (m.tipo === 'error') {
      estado(rows ? `No se pudo actualizar (${m.texto}). Se reintenta solo.` : `No se pudo preparar el análisis: ${m.texto}. Se reintenta solo.`, true);
    }
  };
  // con la app en segundo plano no se analiza: ahorra bateria y datos
  document.addEventListener('visibilitychange', () => worker.postMessage({ tipo: document.hidden ? 'pausa' : 'seguir' }));
  document.addEventListener('DOMContentLoaded', () => { if (!rows) estado('Preparando el primer análisis… bajando el historial de velas'); });
})();
