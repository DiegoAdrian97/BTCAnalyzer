(function () {
  const root = document.getElementById('analista');
  const MINI = document.getElementById('mini');   // barra con el precio al bajar (ver miniPintar)
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const ar = d3.formatLocale({ decimal: ',', thousands: '.', grouping: [3], currency: ['$', ''] });
  const f0 = ar.format(',.0f'), f1 = ar.format(',.1f'), f2 = ar.format(',.2f');
  const sg = (v, d = 2) => (v > 0 ? '+' : '') + ar.format(`,.${d}f`)(v) + '%';
  const num = (v) => (v === null || v === undefined || v === '' ? null : Number(v));
  const TF_TXT = { '5m': '5 min', '15m': '15 min', '30m': '30 min', '1h': '1 hora', '4h': '4 horas', '1d': 'Diario', '1w': 'Semanal', '1M': 'Mensual' };
  const SCEN_TXT = { tipico: 'típico', alcista: 'alcista', bajista: 'bajista' };
  const SIN_FUTURO = true;     // Diego pidio sacar del grafico la simulacion de futuro (tipico, alcista y bajista)
  const tz = { timeZone: 'America/Argentina/Buenos_Aires' };
  const fmtT = (t, tf) => new Date(Number(t)).toLocaleString('es-AR', tf === '1d' ? { ...tz, day: '2-digit', month: '2-digit' }
    : { ...tz, day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  // Indice de las filas por tabla, armado una vez por analisis: antes cada pick() recorria las ~3.000 filas (y hay unos 60
  // por dibujado). Devuelve una copia: hay quien la ordena.
  const IDX = new WeakMap();
  const pick = (rows, t, tf) => {
    let m = IDX.get(rows);
    if (!m) { m = new Map(); for (const r of rows) { let a = m.get(r.tabla); if (!a) m.set(r.tabla, a = []); a.push(r); } IDX.set(rows, m); }
    const a = m.get(t) || [];
    return tf === undefined ? a.slice() : a.filter((r) => r.tf === tf);
  };
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
  // precio en cifras de ancho fijo; con dir (1 sube, -1 baja) las que cambiaron entran rodando desde ese lado
  const QUIETO = matchMedia('(prefers-reduced-motion: reduce)');
  function ponerPrecio(pe, txt, dir) {
    let w = pe.querySelector('.ab-pd');
    if (!w) { w = el('span', 'ab-pd'); pe.prepend(w); }
    const viejo = w.textContent;
    if (viejo === txt) return;
    const cifra = (ch, extra) => el('span', (/\d/.test(ch) ? 'd' : '.,'.includes(ch) ? 'p' : '') + (extra ? ' ' + extra : ''), ch);
    if (!dir || QUIETO.matches || viejo.length !== txt.length) { w.replaceChildren(...[...txt].map((ch) => cifra(ch))); return; }
    const hijos = w.children;
    for (let i = 0; i < txt.length; i++) if (txt[i] !== viejo[i]) hijos[i].replaceWith(cifra(txt[i], dir > 0 ? 'r-up' : 'r-dn'));
    if (pe.closest('.ab-top')) try { ambPulso(dir); } catch (e) { /* el fondo todavia no esta listo */ }   // en el mismo cuadro que ruedan las cifras
  }
  const later = (fn) => (reduce ? fn() : requestAnimationFrame(() => requestAnimationFrame(fn)));
  // cada plazo se mira con las velas que mejor lo muestran
  const PLAZO_VIEW = { '5 min': '5m', '15 min': '15m', '1 hora': '1h', '4 horas': '4h', '1 día': '1d' };
  // grafico de velas (por defecto) o de linea: se recuerda en este navegador
  const LINEA_K = 'ab-grafico-linea';
  const lineaGuardada = (() => { try { return localStorage.getItem(LINEA_K) === '1'; } catch (e) { return false; } })();
  const S = { linea: lineaGuardada, plazo: '1 hora', tf: '1h', scen: 'tipico', hz: null, nbars: 90, offset: 0, yzoom: 1, ypan: 0, geom: null, rows: null, sum: null,
    layers: { ema: true, bb: true, fvg: true, patrones: true, ondas: true, fib: true, liq: true, osc: true, plan: true, opc: true, abanico: true, flujo: window.innerWidth >= 600, vp: true, ict: true, libro: window.innerWidth >= 600 }, log: false, medir: false, iman: false };
  const defBars = () => (window.innerWidth < 600 ? 50 : 90);  // en el telefono, menos para que se lean
  S.nbars = defBars();
  // en el celu arranca con lo esencial (velas, medias, patrones y liquidaciones); el resto se prende en "Capas"
  if (window.innerWidth < 600) Object.assign(S.layers, { bb: false, fvg: false, ondas: false, osc: false });
  const TF_MIN = { '5m': 5, '15m': 15, '30m': 30, '1h': 60, '4h': 240, '1d': 1440, '1w': 10080, '1M': 43200 };
  const dur = (min) => (min < 60 ? `${min} min` : min < 1440 ? `${Math.round(min / 60)} h` : `${Math.round(min / 1440)} d`);
  const M = (v) => `${f1(v)} M USD`;
  let ghostTimer = null, first = true, ghostK = 0;
  let liveBar = null, ws = null, wsTf = null, wsMon = null, ticks = 0;

  // ---------- controles ----------
  function seg(nav, attr, onPick) {
    const thumb = nav.querySelector('.ab-seg-thumb');
    const place = () => {
      const on = nav.querySelector('button[aria-pressed="true"]');
      if (!on || !thumb) return;
      thumb.style.left = on.offsetLeft + 'px'; thumb.style.width = on.offsetWidth + 'px';
    };
    nav.addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      nav.querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      place(); onPick(b.getAttribute(attr));
    });
    return place;
  }
  // al recargarse (el modo en vivo la recarga cuando cambia el diseno) vuelve a la misma vista
  try {
    const saved = JSON.parse(sessionStorage.getItem('ab-vista') || 'null');
    if (saved) {
      Object.assign(S, { plazo: saved.plazo, tf: saved.tf, scen: saved.scen, fs: !!saved.fs, log: !!saved.log, iman: !!saved.iman });
      Object.assign(S.layers, saved.layers || {});
      document.querySelectorAll('#scens button').forEach((x) => x.setAttribute('aria-pressed', String(x.dataset.scen === S.scen)));
    }
  } catch (e) { /* sin almacenamiento: arranca con la vista por defecto */ }
  const syncLayers = () => {
    document.querySelectorAll('#layers [data-layer]').forEach((x) => x.setAttribute('aria-pressed', String(!!S.layers[x.dataset.layer])));
    // "Mi plan" cuenta solo si hay plan (el chip se muestra en drawChart: aca PLAN_COMPRAS todavia no existe)
    const planChip = document.querySelector('#layers [data-layer="plan"]');
    const all = Object.keys(S.layers).filter((k) => k !== 'plan' || (planChip && !planChip.hidden));
    document.getElementById('capas-n').textContent = `${all.filter((k) => S.layers[k]).length}/${all.length}`;
  };
  syncLayers();
  // capas y zoom (en el celu se abren con "Capas") y ayuda de gestos
  const capasBtn = document.getElementById('capas-btn'), capas = document.getElementById('capas');
  capasBtn.addEventListener('click', () => {
    const on = !capas.classList.contains('is-open');
    capas.classList.toggle('is-open', on); capasBtn.setAttribute('aria-expanded', String(on));
  });
  const helpBtn = document.getElementById('help-btn'), help = document.getElementById('chart-help');
  helpBtn.addEventListener('click', () => { help.hidden = !help.hidden; helpBtn.setAttribute('aria-expanded', String(!help.hidden)); });
  document.getElementById('ex-box').open = false;   // el grafico es la escena: la explicacion se abre a pedido
  window.addEventListener('pagehide', () => {
    try { sessionStorage.setItem('ab-vista', JSON.stringify({ plazo: S.plazo, tf: S.tf, scen: S.scen, layers: S.layers, fs: S.fs, log: S.log, iman: S.iman })); } catch (e) { /* idem */ }
  });
  const placeTf = seg(document.getElementById('tfs'), 'data-tf', (v) => { S.tf = v; S.hz = null; S.offset = 0; draw(); });
  const placeSc = seg(document.getElementById('scens'), 'data-scen', (v) => { S.scen = v; draw(); });
  document.getElementById('layers').addEventListener('click', (e) => {
    const b = e.target.closest('[data-layer]'); if (!b) return;
    const k = b.dataset.layer; S.layers[k] = !S.layers[k]; syncLayers(); draw();
  });
  document.getElementById('replay').addEventListener('click', () => { ghostK += 1; draw(); });
  function setPlazo(name) { S.plazo = name; S.offset = 0; setTf(PLAZO_VIEW[name]); }
  function setTf(tf) {
    S.tf = tf; S.hz = null;
    document.querySelectorAll('#tfs button').forEach((x) => x.setAttribute('aria-pressed', String(x.dataset.tf === tf)));
    placeTf(); draw();
  }

  // ---------- pantalla completa ----------
  // en el iPhone Safari no deja poner un elemento en pantalla completa: el grafico pasa a ocupar toda la ventana
  // con CSS. Donde se puede (compu, Android) ademas se pide la pantalla completa real.
  // ---------- modo claro / oscuro ----------
  // Sin elegir, sigue al sistema. El boton fija claro u oscuro en este navegador (y lo recuerda) y todo se redibuja
  // con los colores de ese tema (el grafico se rehace solo porque cambia su fondo).
  const sisOscuro = window.matchMedia('(prefers-color-scheme: dark)');
  function oscuro() { const t = document.documentElement.dataset.theme; return t ? t === 'dark' : sisOscuro.matches; }
  if (!window.abOscuro) window.abOscuro = oscuro;
  const temaBtn = document.getElementById('tema-btn');
  const SOL = 'M12 4V2M12 22v-2M4 12H2M22 12h-2M5.6 5.6 4.2 4.2M19.8 19.8l-1.4-1.4M5.6 18.4l-1.4 1.4M19.8 4.2l-1.4 1.4M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z';
  const LUNA = 'M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z';
  function pintarTema() {
    const on = oscuro();
    temaBtn.setAttribute('aria-pressed', String(on));
    temaBtn.setAttribute('aria-label', on ? 'Pasar a modo claro' : 'Pasar a modo oscuro');
    temaBtn.title = on ? 'Modo claro' : 'Modo oscuro';
    document.getElementById('tema-ico').setAttribute('d', on ? SOL : LUNA);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', getComputedStyle(document.documentElement).getPropertyValue('--color-bg').trim() || (on ? '#000000' : '#ffffff'));
  }
  temaBtn.addEventListener('click', () => {
    const t = oscuro() ? 'light' : 'dark';
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem('ab-tema', t); } catch (e) { /* sin almacenamiento: vale hasta recargar */ }
    pintarTema(); if (S.rows) draw();
  });
  // sin eleccion propia, si el sistema cambia de tema tambien se redibuja
  sisOscuro.addEventListener('change', () => { if (!document.documentElement.dataset.theme) { pintarTema(); if (S.rows) draw(); } });
  try { const t = localStorage.getItem('ab-tema'); if (t === 'dark' || t === 'light') document.documentElement.dataset.theme = t; } catch (e) { /* idem */ }
  pintarTema();

  const card = document.getElementById('grafico'), fsBtn = document.getElementById('fs-btn');
  const exBox = document.getElementById('ex-box'), exFsBtn = document.getElementById('ex-fs-btn');
  let exAbierto = exBox.open;                     // como estaba "Que estas viendo" antes de la pantalla completa
  // abierto fuera de pantalla completa: se extiende hacia abajo y el grafico conserva su alto (la escena deja de estar
  // fija y la pagina se alarga, en vez de achicar el grafico)
  // el alto del grafico con "Que estas viendo" cerrado (se va midiendo; al abrirlo ya se achico)
  let altoGraf = 0;
  if ('ResizeObserver' in window) new ResizeObserver(() => {
    if (exBox.open || S.fs) return;
    const c = document.getElementById('chart'), ch = c.getBoundingClientRect().height; if (ch > 120) altoGraf = ch + (parseFloat(getComputedStyle(c).marginTop) || 0);   // la fila incluye el margen
  }).observe(document.getElementById('chart'));
  function exLargo() {
    const on = exBox.open && !S.fs, h = document.documentElement;
    if (on && altoGraf) h.style.setProperty('--graf-fijo', `${Math.round(altoGraf)}px`);
    h.classList.toggle('ab-ex-largo', on);
  }
  exBox.addEventListener('toggle', exLargo);
  // con el toque se cambia el modo ANTES de que se abra o cierre (mismo cuadro): si no, se veia un cuadro con el grafico
  // achicado y otro con el alto de vuelta (el "salto" al abrir)
  exBox.querySelector('summary').addEventListener('click', () => {
    if (S.fs) return;
    const h = document.documentElement, abrir = !exBox.open;
    if (abrir && altoGraf) h.style.setProperty('--graf-fijo', `${Math.round(altoGraf)}px`);
    h.classList.toggle('ab-ex-largo', abrir);
  });
  const exPanel = (on) => { card.classList.toggle('ab-fs-ex', on); exFsBtn.setAttribute('aria-expanded', String(on)); };
  exFsBtn.addEventListener('click', () => exPanel(!card.classList.contains('ab-fs-ex')));
  // en pantalla completa el titulo no pliega el panel: en el celular lo cierra
  exBox.querySelector('summary').addEventListener('click', (e) => { if (!S.fs) return; e.preventDefault(); if (window.innerWidth < 900) exPanel(false); });
  let exX = null;
  exBox.addEventListener('touchstart', (e) => { exX = S.fs && e.touches.length === 1 ? [e.touches[0].clientX, e.touches[0].clientY] : null; }, { passive: true });
  exBox.addEventListener('touchend', (e) => {
    if (!exX) return; const t = e.changedTouches[0], dx = t.clientX - exX[0], dy = t.clientY - exX[1]; exX = null;
    if (dx > 60 && Math.abs(dx) > 2 * Math.abs(dy) && window.innerWidth < 900) exPanel(false);       // deslizar a la derecha lo cierra
  }, { passive: true });
  function setFs(on, native = true) {
    if (on && !S.fs) exAbierto = exBox.open;
    S.fs = on;
    exBox.open = on ? true : exAbierto;
    if (!on) exPanel(false);
    card.classList.toggle('ab-fs', on);
    document.documentElement.classList.toggle('ab-fs-on', on);
    exLargo();
    fsBtn.setAttribute('aria-pressed', String(on));
    fsBtn.textContent = on ? '✕' : '⤢';
    fsBtn.setAttribute('aria-label', on ? 'Salir de pantalla completa' : 'Ver el gráfico en pantalla completa');
    if (native) {
      try {
        if (on && !document.fullscreenElement && document.documentElement.requestFullscreen) document.documentElement.requestFullscreen().catch(() => {});
        else if (!on && document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(() => {});
      } catch (e) { /* sin pantalla completa real: queda la de CSS */ }
    }
    S.hz = null;
    requestAnimationFrame(() => { if (S.rows) { drawChart(S.rows, S.sum); placeTf(); placeSc(); } });
  }
  fsBtn.addEventListener('click', () => setFs(!S.fs));
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (G.med || S.medir) { setMedir(false); return; }      // primero se borra la medicion
    if (S.fs && card.classList.contains('ab-fs-ex')) { exPanel(false); return; }   // despues, el panel de "Que estas viendo"
    if (S.fs) setFs(false);
  });
  document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement && S.fs) setFs(false, false); });
  if (S.fs) setFs(true, false);

  // botones de zoom: los gestos (arrastrar, pellizcar, estirar ejes, alto de paneles) los maneja el motor del grafico
  const defRange = () => {
    if (!G.chart || !G.d) return;
    const total = G.d.all.length + G.d.futN, nb = Math.min(total, defBars());
    G.chart.timeScale().setVisibleLogicalRange({ from: total - nb, to: total + 1 });
    G.chart.priceScale('right').applyOptions({ autoScale: true });
  };
  document.querySelectorAll('[data-zoom]').forEach((b) => b.addEventListener('click', () => {
    if (!G.chart) return;
    const ts = G.chart.timeScale(), r = ts.getVisibleLogicalRange(); if (!r) return;
    const len = Math.max(12, Math.min(600, (r.to - r.from) * (b.dataset.zoom === 'out' ? 1.4 : 1 / 1.4)));
    ts.setVisibleLogicalRange({ from: r.to - len, to: r.to });
  }));
  document.getElementById('fit').addEventListener('click', defRange);
  // escala logaritmica: en el diario y el de 4 h los movimientos grandes se comparan mejor en %
  const logBtn = document.getElementById('log-btn');
  function setLog(on) {
    S.log = on; logBtn.setAttribute('aria-pressed', String(on));
    if (G.chart) G.chart.priceScale('right').applyOptions({ mode: on ? LW.PriceScaleMode.Logarithmic : LW.PriceScaleMode.Normal });
  }
  logBtn.addEventListener('click', () => setLog(!S.log));
  logBtn.setAttribute('aria-pressed', String(S.log));
  // medir: % y velas entre dos puntos, como la regla de TradingView (con el mouse tambien Shift + arrastrar)
  const medirBtn = document.getElementById('medir-btn');
  function setMedir(on) {
    S.medir = on; medirBtn.setAttribute('aria-pressed', String(on));
    document.getElementById('chart').classList.toggle('is-midiendo', on);
    if (!on && G.med) { G.med = null; if (G.over) G.over.update(); }
  }
  medirBtn.addEventListener('click', () => setMedir(!S.medir));
  // iman (como en TradingView): la mira se pega a apertura/maximo/minimo/cierre y la regla tambien
  const imanBtn = document.getElementById('iman-btn');
  function setIman(on) {
    S.iman = on; imanBtn.setAttribute('aria-pressed', String(on));
    if (G.chart) G.chart.applyOptions({ crosshair: { mode: on ? LW.CrosshairMode.MagnetOHLC : LW.CrosshairMode.Normal } });
  }
  imanBtn.addEventListener('click', () => setIman(!S.iman));
  imanBtn.setAttribute('aria-pressed', String(S.iman));
  document.getElementById('foto-btn').addEventListener('click', () => foto());
  // teclas, con el mouse sobre el grafico (o en pantalla completa) y sin escribir en un campo
  document.addEventListener('keydown', (e) => {
    if (!G.chart || e.metaKey || e.ctrlKey || e.altKey || (!G.hoverBox && !S.fs)) return;
    const tg = e.target || {};
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(tg.tagName || '') || tg.isContentEditable) return;
    const ts = G.chart.timeScale(), r = ts.getVisibleLogicalRange();
    const tfs = ['5m', '15m', '30m', '1h', '4h', '1d', '1w', '1M'], k = e.key.toLowerCase();
    if ((k === 'arrowleft' || k === 'arrowright') && r) {
      const step = Math.max(1, (r.to - r.from) * 0.15) * (k === 'arrowleft' ? -1 : 1);
      ts.setVisibleLogicalRange({ from: r.from + step, to: r.to + step });
    } else if ((k === '+' || k === '=' || k === '-' || k === '_') && r) {
      const len = Math.max(12, Math.min(600, (r.to - r.from) * (k === '-' || k === '_' ? 1.4 : 1 / 1.4)));
      ts.setVisibleLogicalRange({ from: r.to - len, to: r.to });
    } else if (k === '0') defRange();
    else if (k === 'l') setLog(!S.log);
    else if (k === 'm') setMedir(!S.medir);
    else if (k === 'i') setIman(!S.iman);
    else if (k === 'f') setFs(!S.fs);
    else if (k >= '1' && k <= '6') setTf(tfs[Number(k) - 1]);
    else return;
    e.preventDefault();
  });

  document.querySelectorAll('.ab-more').forEach((d) => d.addEventListener('toggle', () => { if (d.open && S.rows) draw(); }));

  // ---------- en vivo (solo en la version local con --vivo: en claude.ai la pagina no puede conectarse a Binance) ----------
  function connectLive() {
    if (!window.abLive || (wsTf === S.tf && wsMon === MON())) return;
    if (ws) ws.close();
    wsTf = S.tf; wsMon = MON(); liveBar = null; S.lastTick = undefined;
    // MELI no cotiza en Binance: sus ticks salen de Bitget
    const bitget = MON() === 'MELI', BG_TF = { '5m': '5m', '15m': '15m', '30m': '30m', '1h': '1H', '4h': '4H', '1d': '1D', '1w': '1W', '1M': '1M' };
    const sock = new WebSocket(bitget ? 'wss://ws.bitget.com/v2/ws/public' : `wss://fstream.binance.com/market/ws/${MON().toLowerCase()}usdt@kline_${S.tf}`);
    ws = sock;
    if (bitget) {
      sock.onopen = () => sock.send(JSON.stringify({ op: 'subscribe', args: [{ instType: 'USDT-FUTURES', channel: `candle${BG_TF[S.tf]}`, instId: `${MON()}USDT` }] }));
      const ping = setInterval(() => { if (sock.readyState === 1) sock.send('ping'); else clearInterval(ping); }, 25000);
    }
    sock.onmessage = (ev) => {
      if (ev.data === 'pong') return;
      const m = JSON.parse(ev.data);
      let k = m.k;
      if (bitget) { const d = m.data && m.data[m.data.length - 1]; if (!d) return; k = { t: +d[0], o: d[1], h: d[2], l: d[3], c: d[4], v: d[5] }; }
      if (!k || sock !== ws || wsMon !== MON()) return;   // del activo anterior (mensaje tardio, o todavia no llego el analisis del nuevo)
      liveBar = { tf: wsTf, mon: wsMon, t: k.t, o: +k.o, h: +k.h, l: +k.l, c: +k.c, v: +k.v };
      ticks++;
      const pe = root.querySelector('.ab-price');
      if (pe && pe.firstChild) {
        const prev = S.lastTick;
        if (liveBar.c !== prev) ponerPrecio(pe, fp(liveBar.c), prev === undefined ? 0 : liveBar.c > prev ? 1 : -1);
        if (prev !== undefined && liveBar.c !== prev) {
          // sin forzar el calculo de la pagina (void offsetWidth, hasta 4 veces por segundo): el color no tiene animacion
          // que reiniciar, se ve igual
          const up = liveBar.c > prev; pe.classList.toggle('ab-tick-up', up); pe.classList.toggle('ab-tick-dn', !up);
          clearTimeout(S.tickT); S.tickT = setTimeout(() => pe.classList.remove('ab-tick-up', 'ab-tick-dn'), 350);
        }
        S.lastTick = liveBar.c;
      }
      // el titulo de la pestaña y el contador, una vez por segundo (los ticks llegan cada 250 ms)
      if (Date.now() - (S.estT || 0) > 1000) {
        S.estT = Date.now(); document.title = `${fp(liveBar.c)} · ${MON()}`;
        document.getElementById('live-state').textContent = `● en vivo · análisis #${f0(window.abAnalyses || 1)} · ${f0(ticks)} ticks`;
        if (MINI.classList.contains('on')) miniPintar();
      }
      liveTick();
    };
    sock.onclose = () => { if (ws === sock) { wsTf = null; setTimeout(connectLive, 3000); } };
  }

  // al agrandar o achicar un modulo se redibuja a su tamano nuevo (solo cuando cambia el tamano, no el contenido)
  (function watchSizes() {
    if (!window.ResizeObserver) return;
    const seen = new WeakMap();
    let t = null;
    const ro = new ResizeObserver((entries) => {
      let changed = false;
      entries.forEach((e) => {
        const w = Math.round(e.contentRect.width), h = Math.round(e.contentRect.height), prev = seen.get(e.target);
        const isChart = e.target.id === 'chart';
        if (prev && !isChart && Math.abs(prev.w - w) > 2) changed = true;
        seen.set(e.target, { w, h });
      });
      if (changed) { clearTimeout(t); t = setTimeout(() => { if (S.rows) draw(); }, 120); }
    });
    document.querySelectorAll('#analista .ab-card, #analista .ab-more, #chart').forEach((n) => ro.observe(n));
  })();


  // la cripto que se analiza (la version JS puede elegir ZEC) y precio con los decimales que hacen falta
  // el activo a la vista: del contexto de la app (app.js) o BTC en la pagina del servidor
  function MON() { return window.abActivo ? window.abActivo.get() : window.abMoneda || 'BTC'; }
  const ES_CRIPTO = (m) => ['BTC', 'ZEC', 'SOL', 'XRP'].includes(m);     // el plan de compras y las posiciones son solo de estas
  // ---------- foco en los paneles (activos, termometro, avisos): al abrir va al primer control, Tab da la vuelta adentro
  // y al cerrar vuelve al boton que lo abrio (con lector de pantalla o teclado no se pierde en la pagina de atras)
  function abFoco(panel, abierto) {
    if (abierto) {
      panel._prev = document.activeElement;
      const f = panel.querySelector('button, [href], input, select, [tabindex]:not([tabindex="-1"])');
      if (f) setTimeout(() => f.focus({ preventScroll: true }), 30);
    } else if (panel._prev && document.contains(panel._prev) && panel.contains(document.activeElement)) {
      panel._prev.focus({ preventScroll: true }); panel._prev = null;
    } else panel._prev = null;
  }
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const p = [...document.querySelectorAll('.ab-act-panel.on, .ab-tm-panel.on, .ab-nt-modal, .ab-repro:not([hidden])')].find((n) => !n.hidden && getComputedStyle(n).position === 'fixed');
    if (!p) return;
    const fs = [...p.querySelectorAll('button, [href], input, select, [tabindex]:not([tabindex="-1"])')].filter((n) => !n.disabled && n.offsetParent !== null);
    if (!fs.length) return;
    const [a, z] = [fs[0], fs[fs.length - 1]];
    if (!p.contains(document.activeElement)) { e.preventDefault(); a.focus(); }
    else if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
    else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
  });
  // ---------- panel lateral: todos los activos con su precio en vivo (solo en la app, que tiene varios activos) ----------
  (function panelActivos() {
    const A = window.abActivo, panel = document.getElementById('act-panel'), fondo = document.getElementById('act-fondo');
    const sel = document.getElementById('app-moneda-sel'), lista = document.getElementById('act-list'), btn = document.getElementById('act-btn');
    if (!A || !panel || !sel) return;
    btn.hidden = false;
    const borde = document.getElementById('act-borde'), chipT = document.getElementById('act-chip-t');
    borde.hidden = false;
    const ponerChip = () => { const o = [...sel.options].find((x) => x.value === A.get()); chipT.textContent = o ? o.textContent : A.get(); };
    ponerChip(); A.subscribe(ponerChip);
    borde.addEventListener('click', () => abrir());
    const P = {}, filas = {};               // precio y apertura de 24 h de cada activo; la fila de cada uno
    // los grupos y nombres salen del desplegable (asi lo que se agregue ahi aparece aca)
    const grupos = [{ titulo: 'Criptos', items: [] }];
    [...sel.children].forEach((ch) => {
      if (ch.tagName === 'OPTGROUP') grupos.push({ titulo: ch.label, items: [...ch.children] });
      else grupos[0].items.push(ch);
    });
    grupos.forEach((g) => {
      if (!g.items.length) return;
      lista.append(el('p', 'ab-act-g', g.titulo));
      g.items.forEach((o) => {
        const m = o.value, nombre = (o.textContent.split('·')[1] || '').trim();
        const b = el('button', 'ab-act-row'); b.type = 'button';
        const izq = el('span'); izq.append(el('b', '', m), el('i'), el('small', '', nombre));
        const pr = el('span', 'ab-act-p ab-esq', ''), ch = el('span', 'ab-act-c', '');
        b.append(izq, pr, ch);
        b.addEventListener('click', () => { if (!fijo) cerrar(); A.set(m); });
        lista.append(b); filas[m] = { b, pr, ch, listo: izq.querySelector('i') };
      });
    });
    // sin precio a los 15 s (sin conexion): el guion de siempre en vez del esqueleto
    setTimeout(() => Object.values(filas).forEach((f) => { if (f.pr.classList.contains('ab-esq')) { f.pr.classList.remove('ab-esq'); f.pr.textContent = '—'; } }), 15000);
    function pintar(m) {
      const f = filas[m], x = P[m];
      if (!f || !x) return;
      const antes = f.pr.dataset.v ? +f.pr.dataset.v : null;
      if (antes === x.c && f.o === x.o) return;            // el mismo precio: no se toca la pantalla
      f.o = x.o; f.pr.classList.remove('ab-esq'); f.pr.textContent = fp(x.c); f.pr.dataset.v = x.c;
      if (antes !== null && antes !== x.c) { f.pr.classList.remove('sube', 'baja'); f.pr.classList.add(x.c > antes ? 'sube' : 'baja'); clearTimeout(f.tm); f.tm = setTimeout(() => f.pr.classList.remove('sube', 'baja'), 700); }
      const c = x.o > 0 ? (x.c / x.o - 1) * 100 : null;
      f.ch.textContent = c === null ? '' : sg(c, 2); f.ch.className = 'ab-act-c' + (c > 0 ? ' up' : c < 0 ? ' dn' : '');
    }
    function marcar() {
      Object.entries(filas).forEach(([m, f]) => { f.b.setAttribute('aria-current', String(m === A.get())); f.listo.textContent = A.listo(m) ? '✓' : ''; });
    }
    // en vivo: Binance (un solo WebSocket con todos) y Bitget para MELI; si no llega nada, cada 15 s por pedido comun
    let ws = null, wsBg = null, ping = null, rep = null;
    const llegada = {};
    // los precios llegan de a uno (16 activos, varias veces por segundo): se pintan juntos, a lo sumo 3 veces por segundo
    // (antes ~140 cambios por segundo en la pantalla)
    const sucios = new Set(); let cuadro = 0;
    const nuevo = (m, c, o) => {
      if (!(c > 0)) return; P[m] = { c, o }; llegada[m] = Date.now(); sucios.add(m);
      if (!cuadro) cuadro = setTimeout(() => requestAnimationFrame(() => { cuadro = 0; sucios.forEach(pintar); sucios.clear(); }), 330);
    };
    async function porPedido(m) {
      try {
        if (m === 'MELI') { const d = (await (await fetch('https://api.bitget.com/api/v2/mix/market/ticker?symbol=MELIUSDT&productType=usdt-futures', { cache: 'no-store' })).json()).data[0]; nuevo(m, +d.lastPr, +d.open24h); }
        else { const d = await (await fetch(`https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=${m}USDT`, { cache: 'no-store' })).json(); nuevo(m, +d.lastPrice, +d.openPrice); }
      } catch (e) { /* se prueba en la proxima vuelta */ }
    }
    // todos los precios de Binance en un pedido (pesa 2; uno por activo eran 16 pedidos). El cambio de 24 h se calcula
    // contra la apertura que ya se tenia (del WebSocket o del ultimo analisis)
    async function porLote(ms) {
      try {
        const l = await (await fetch('https://fapi.binance.com/fapi/v2/ticker/price', { cache: 'no-store' })).json();
        const por = new Map((Array.isArray(l) ? l : []).map((x) => [x.symbol, +x.price]));
        ms.forEach((m) => { const c = por.get(`${m}USDT`), o = (P[m] && P[m].o) || (A.precio(m) || {}).o; if (c > 0) nuevo(m, c, o > 0 ? o : c); else porPedido(m); });
      } catch (e) { ms.forEach(porPedido); }
    }
    function conectar() {
      desconectar();                     // nunca dos conexiones a la vez (al pasar de celular a compu con el panel abierto)
      const syms = A.todos().filter((m) => m !== 'MELI').map((m) => `${m.toLowerCase()}usdt@miniTicker`).join('/');
      try {
        ws = new WebSocket(`wss://fstream.binance.com/market/stream?streams=${syms}`);
        ws.onmessage = (e) => { try { const d = JSON.parse(e.data).data; if (d && d.s) nuevo(d.s.replace('USDT', ''), +d.c, +d.o); } catch (x) { /* mensaje raro */ } };
      } catch (e) { ws = null; }
      try {
        wsBg = new WebSocket('wss://ws.bitget.com/v2/ws/public');
        wsBg.onopen = () => { wsBg.send(JSON.stringify({ op: 'subscribe', args: [{ instType: 'USDT-FUTURES', channel: 'ticker', instId: 'MELIUSDT' }] })); ping = setInterval(() => { try { wsBg.send('ping'); } catch (x) { /* cerrado */ } }, 25000); };
        wsBg.onmessage = (e) => { if (e.data === 'pong') return; try { const d = (JSON.parse(e.data).data || [])[0]; if (d && d.lastPr) nuevo('MELI', +d.lastPr, +d.open24h); } catch (x) { /* idem */ } };
      } catch (e) { wsBg = null; }
      const vuelta = () => {
        const viejos = A.todos().filter((m) => Date.now() - (llegada[m] || 0) > 15000), bn = viejos.filter((m) => m !== 'MELI');
        if (bn.length > 2) porLote(bn); else bn.forEach(porPedido);
        if (viejos.includes('MELI')) porPedido('MELI');
      };
      rep = setTimeout(function otra() { vuelta(); rep = setTimeout(otra, 15000); }, 3500);
    }
    function desconectar() {
      [ws, wsBg].forEach((w) => { try { if (w) w.close(); } catch (e) { /* ya cerrado */ } });
      ws = wsBg = null; clearInterval(ping); clearTimeout(rep);
    }
    const abierto = () => !panel.hidden;
    // en la compu: fijo a la derecha, siempre visible y con los precios en vivo (se cortan con la pestaña oculta)
    const MQ = window.matchMedia('(min-width: 1100px) and (pointer: fine)');
    let fijo = false;
    function ponerFijo() {
      const quiere = MQ.matches;
      if (quiere === fijo) return;
      fijo = quiere;
      document.documentElement.classList.toggle('ab-panel-fijo', fijo);
      if (fijo) {
        fondo.classList.remove('on'); fondo.hidden = true; borde.hidden = true; document.body.style.overflow = '';
        panel.setAttribute('role', 'complementary'); panel.removeAttribute('aria-modal');
        A.todos().forEach((m) => { if (!P[m]) { const r = A.precio(m); if (r) { P[m] = r; pintar(m); } } });
        marcar(); panel.hidden = false; panel.classList.add('on');
        if (!document.hidden) conectar();
      } else {
        panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true');
        panel.classList.remove('on'); panel.hidden = true; borde.hidden = false; desconectar();
      }
      window.dispatchEvent(new Event('resize'));        // el grafico y lo demas se acomodan al ancho nuevo
    }
    function abrir() {
      if (fijo) { const act = filas[A.get()]; if (act) { act.b.scrollIntoView({ block: 'nearest' }); act.b.focus({ preventScroll: true }); } return; }
      if (abierto()) return;
      // mientras llega el precio en vivo: el del ultimo analisis de cada uno
      A.todos().forEach((m) => { if (!P[m]) { const r = A.precio(m); if (r) { P[m] = r; pintar(m); } } });
      marcar(); panel.hidden = false; fondo.hidden = false; document.getElementById('act-borde').hidden = true;
      requestAnimationFrame(() => { panel.classList.add('on'); fondo.classList.add('on'); });
      document.body.style.overflow = 'hidden'; conectar(); abFoco(panel, true);
      const act = filas[A.get()]; if (act) act.b.scrollIntoView({ block: 'nearest' });
    }
    function cerrar() {
      if (fijo || !abierto()) return;
      abFoco(panel, false); panel.classList.remove('on'); fondo.classList.remove('on'); document.body.style.overflow = '';
      desconectar();
      setTimeout(() => { panel.hidden = true; fondo.hidden = true; document.getElementById('act-borde').hidden = false; }, 230);
    }
    btn.addEventListener('click', abrir);
    document.getElementById('act-x').addEventListener('click', cerrar);
    fondo.addEventListener('click', cerrar);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && abierto()) cerrar(); });
    document.addEventListener('visibilitychange', () => {
      if (fijo) { if (document.hidden) desconectar(); else if (!ws) conectar(); return; }
      if (document.hidden && abierto()) cerrar();
    });
    ponerFijo();
    if (MQ.addEventListener) MQ.addEventListener('change', ponerFijo); else MQ.addListener(ponerFijo);
    A.subscribe(marcar);
    // gesto: arrastrar desde el borde derecho hacia la izquierda abre; dentro del panel, hacia la derecha cierra
    let t0 = null;
    document.addEventListener('touchstart', (e) => {
      if (e.touches.length !== 1) { t0 = null; return; }
      const x = e.touches[0].clientX, y = e.touches[0].clientY;
      if (document.documentElement.classList.contains('ab-fs-on')) { t0 = null; return; }     // en pantalla completa el borde es del grafico
      if (!abierto() && x > window.innerWidth - 22) t0 = { x, y, modo: 'abrir' };
      else if (abierto() && panel.contains(e.target)) t0 = { x, y, modo: 'cerrar' };
      else t0 = null;
    }, { passive: true, capture: true });
    document.addEventListener('touchmove', (e) => {
      if (!t0) return;
      const dx = e.touches[0].clientX - t0.x, dy = e.touches[0].clientY - t0.y;
      if (Math.abs(dy) > 30 && Math.abs(dy) > Math.abs(dx)) { t0 = null; return; }    // es un scroll vertical
      if (t0.modo === 'abrir' && dx < -8) { e.preventDefault(); e.stopPropagation(); if (dx < -45) { t0 = null; abrir(); } }
      else if (t0.modo === 'cerrar' && dx > 60 && Math.abs(dx) > 2 * Math.abs(dy)) { t0 = null; cerrar(); }
    }, { passive: false, capture: true });
    document.addEventListener('touchend', () => { t0 = null; }, { passive: true, capture: true });
  })();
  function fp(x) { return x === null || x === undefined ? '—' : Math.abs(x) >= 1000 ? f0(x) : Math.abs(x) >= 10 ? ar.format(',.2f')(x) : ar.format(',.4f')(x); }

  function draw() {
    const res = dash.data('analisis');
    const chart = document.getElementById('chart');
    if (ghostTimer) { clearInterval(ghostTimer); ghostTimer = null; }
    if (res.status !== 'ok') {
      root.classList.add('ab-cargando');            // esqueletos tambien al elegir un activo que todavia no tiene analisis
      // el nombre del activo nuevo ya; el precio y las cifras del anterior quedan tapadas hasta que llegue su analisis
      document.getElementById('ab-title').textContent = `Analista ${MON()}`;
      const lbl = document.getElementById('moneda-lbl'); if (lbl) lbl.textContent = MON();
      chart.replaceChildren();
      if (res.status === 'error') { root.classList.remove('ab-cargando'); chart.classList.remove('dash-skeleton'); const f = el('div', 'ab-fail'); f.append(el('i'), 'No se pudo cargar el análisis. Revisá la conexión: se reintenta solo.'); chart.append(f); }
      return;
    }
    document.querySelectorAll('#analista .dash-skeleton').forEach((e) => e.classList.remove('dash-skeleton'));
    root.classList.remove('ab-cargando');
    const rows = res.data;
    const sum = pick(rows, 'resumen')[0];
    S.rows = rows; S.sum = sum;
    const nA = window.abAnalyses || 1;
    if (S.lastA && nA !== S.lastA) { root.classList.remove('ab-fresh'); void root.offsetWidth; root.classList.add('ab-fresh'); }
    S.lastA = nA;
    document.querySelectorAll('#tfs button').forEach((x) => x.setAttribute('aria-pressed', String(x.dataset.tf === S.tf)));
    root.style.setProperty('--ab-c0', dash.colors[0]); root.style.setProperty('--ab-c2', dash.colors[2]);
    drawHeader(rows, sum);
    drawPlazos(rows);
    drawStory(rows);
    drawPrediction(rows, sum);
    drawMovimiento(rows);
    try { drawCalendario(rows); } catch (e) { /* sin calendario: no frena lo demas */ }
    drawQuePasa(rows, sum);
    drawTermometro(rows);
    const pi = pick(rows, 'piso')[0];
    if (pi && pi.modelo) { PISO = pi.modelo; try { localStorage.setItem('ab-piso', JSON.stringify(PISO)); } catch (e) { /* sin almacenamiento */ } drawPosiciones(); }
    if (window.abNotif) window.abNotif.filas(rows);
    drawCompras();
    drawLearningSiCambia(rows);
    drawGauge(rows);
    drawChart(rows, sum);
    document.getElementById('prob-tf').textContent = `a ${S.plazo}`;
    document.getElementById('ond-tf').textContent = TF_TXT[S.tf]; document.getElementById('ind-tf').textContent = TF_TXT[S.tf];
    Object.keys(PEREZOSOS).forEach(perezoso);
    placeTf(); placeSc();
    connectLive();
    drawConclusion();
    drawCentro(rows, sum);
    plazosBordes(); if (MINI.classList.contains('on')) miniPintar();
    plegarNotas();
    if (first) { first = false; setTimeout(() => root.classList.remove('ab-first'), 1800); }
  }
  // En resumen: la prediccion de la proxima hora, los indicadores del marco elegido y el termometro (ciclo), juntos y
  // con su plazo. Si apuntan para lados distintos se dice por que, en vez de dejar que parezcan contradecirse.
  // ---------- analisis central (fila 'central' de analisis.js): 5 puntos en la temporalidad elegida ----------
  const CE_TFS = [['5m', '5m'], ['15m', '15m'], ['30m', '30m'], ['1h', '1h'], ['4h', '4h'], ['1d', '1D'], ['1w', '1S'], ['1M', '1M']];
  const CE_PLAZO = { '5m': '5 min', '15m': '15 min', '1h': '1 hora', '4h': '4 horas', '1d': '1 día' };
  const okv = (x) => x !== null && x !== undefined;
  function drawCentro(rows, sum) {
    const sec = document.getElementById('centro'), todas = pick(rows, 'central');
    const c = todas.find((x) => x.tf === S.tf) || todas.find((x) => x.tf === '1h');
    drawRespuesta(rows, sum, c); drawPartes(rows, c);
    sec.hidden = !c; if (!c) return;
    const tfs = document.getElementById('ce-tfs');
    tfs.replaceChildren(...CE_TFS.filter(([tf]) => todas.some((x) => x.tf === tf)).map(([tf, txt]) => {
      const b = el('button', '', txt); b.type = 'button'; b.setAttribute('aria-pressed', String(tf === c.tf));
      b.addEventListener('click', () => (CE_PLAZO[tf] ? setPlazo(CE_PLAZO[tf]) : setTf(tf)));
      return b;
    }));
    document.getElementById('ce-k').textContent = `${MON()} · ${TF_TXT[c.tf] || c.tf}${c.hasta ? ` · hasta las ${c.hasta.slice(-5)}\u00a0h` : ''}`;
    const lista = (punto) => {
      const fs = c.factores.filter((f) => f[0] === punto).slice().sort((a, b) => b[2] - a[2]);
      if (!fs.length) return null;
      const d = el('details'), ul = el('ul', 'ab-ce-f');
      d.append(el('summary', '', `Por qué (${fs.length} ${fs.length === 1 ? 'señal' : 'señales'})`), ul);
      fs.forEach(([, lado, peso, txt]) => { const li = el('li', punto === 'fuerza' ? (lado > 0 ? 'fuerte' : '') : lado > 0 ? 'sube' : 'baja'); li.append(el('span', '', txt), el('i', '', `${lado > 0 ? '+' : '−'}${String(peso).replace('.', ',')}`)); ul.append(li); });
      return d;
    };
    const bloque = (id, cls, k, lineas, extra) => {
      const b = document.getElementById(id); b.className = `ab-ce-p ${cls}`.trim();
      b.replaceChildren(el('h3', '', k), ...lineas.filter(Boolean).map((t) => el('span', '', t)), ...(extra || []).filter(Boolean));
    };
    // precios cortos para la fila de respuestas: 91,8k (de 10.000 para arriba), si no el precio comun
    const fk = (x) => (x >= 10000 ? `${f1(x / 1000)}k` : fp(x));
    const par = (a, b) => (a >= 10000 && b >= 10000 ? `${f1(a / 1000)}–${f1(b / 1000)}k` : `${fk(a)}–${fk(b)}`);
    const hs = pick(rows, 'horas')[0];
    // 0. la fila de respuestas
    const tira = document.getElementById('ce-tira');
    const celda = (k, cls, lbl, val, nota) => {
      const d = el('div', `ab-ce-c ${cls}`.trim()); d.setAttribute('role', 'listitem'); d.dataset.k = k;
      const b = el('b', '', val); if (nota) b.append(el('i', '', nota));
      d.append(el('small', '', lbl), b); return d;
    };
    tira.replaceChildren(
      celda('fz', c.fuerza === 'alta' ? 'fuerte' : '', 'Mov. fuerte', c.fuerza === 'alta' ? 'Sí' : c.fuerza === 'media' ? 'Puede' : 'No',
        okv(c.prob_fuerte) ? `${f0(num(c.prob_fuerte))}%` : ''),
      celda('dir', c.direccion === 'sube' ? 'sube' : c.direccion === 'baja' ? 'baja' : '', 'Dirección',
        c.direccion === 'sube' ? '▲ Sube' : c.direccion === 'baja' ? '▼ Baja' : 'Neutral'),
      celda('rng', '', 'Rango', okv(c.rango_min) ? par(num(c.rango_min), num(c.rango_max)) : '—'),
      celda('niv', '', 'Soporte–resist.', okv(c.soporte) && okv(c.resistencia) ? par(num(c.soporte), num(c.resistencia))
        : okv(c.soporte) ? `S ${fk(num(c.soporte))}` : okv(c.resistencia) ? `R ${fk(num(c.resistencia))}` : '—'));
    // 1. fuerza
    bloque('ce-fuerza', c.fuerza === 'alta' ? 'fuerte' : '', '¿Movimiento fuerte?', [
      okv(c.prob_fuerte) ? `Chance ${f0(num(c.prob_fuerte))}% (lo normal: ${f0(num(c.prob_normal))}%)` : 'Sin chance medida en este plazo',
      hs && hs.max_f - hs.min_f >= 0.3 && ['5m', '15m', '30m', '1h'].includes(c.tf) ? `Suele moverse más a las ${horaAR(hs.max_t)} h` : null], [lista('fuerza')]);
    // 2. direccion
    bloque('ce-dir', c.direccion === 'sube' ? 'sube' : c.direccion === 'baja' ? 'baja' : '', '¿Para dónde?', [
      `Señales: ${String(c.a_favor).replace('.', ',')} a favor de la suba, ${String(c.en_contra).replace('.', ',')} de la baja`,
      okv(c.prob_sube) ? `Toca primero arriba: ${f0(num(c.prob_sube))}%` : null], [lista('direccion')]);
    // 3. mapa de precios: rango, objetivos y niveles en una escalera, con el precio de ahora en su lugar
    const ahora = sum && okv(sum.precio) ? num(sum.precio) : null;
    const pts = [];
    const pon = (v, txt, cls) => { if (okv(v)) pts.push({ p: num(v), txt, cls }); };
    pon(c.rango_max, 'techo del rango', 'borde'); pon(c.rango_min, 'piso del rango', 'borde');
    pon(c.obj_arriba, `objetivo ▲${okv(c.toca_arriba) ? ` · ${f0(num(c.toca_arriba))}%` : ''}`, 'obj sube');
    pon(c.obj_abajo, `objetivo ▼${okv(c.toca_abajo) ? ` · ${f0(num(c.toca_abajo))}%` : ''}`, 'obj baja');
    pon(c.resistencia, 'resistencia', 'nivel'); pon(c.soporte, 'soporte', 'nivel');
    pon(c.elliott_objetivo, 'objetivo de Elliott', 'obj');
    if (ahora) pts.push({ p: ahora, txt: 'ahora', cls: 'ahora' });
    pts.sort((a, b) => b.p - a.p);
    const lo = okv(c.rango_min) ? num(c.rango_min) : -Infinity, hi = okv(c.rango_max) ? num(c.rango_max) : Infinity;
    const mapa = el('ol', 'ab-mapa');
    pts.forEach((x) => {
      const li = el('li', `${x.cls}${x.p >= lo && x.p <= hi && okv(c.rango_min) ? ' en' : ''}`);
      li.append(el('b', '', fp(x.p)), el('span', '', x.txt), el('i', '', x.cls === 'ahora' || !ahora ? '' : sg((x.p / ahora - 1) * 100, Math.abs(x.p / ahora - 1) < 0.01 ? 2 : 1)));
      mapa.append(li);
    });
    const mb = document.getElementById('ce-mapa'); mb.className = 'ab-ce-p ab-ce-mapa';
    mb.replaceChildren(el('h3', '', '¿Hasta dónde? · niveles'), mapa,
      ...[okv(c.rango_min) ? '8 de cada 10 veces terminó entre el piso y el techo.' : 'Sin rango medido en este plazo.',
        okv(c.esperado_usd) ? `En una hora suele moverse ~${num(c.esperado_usd) >= 100 ? f0(num(c.esperado_usd)) : fp(num(c.esperado_usd))} USD.` : null, c.invalida || null].filter(Boolean).map((t) => el('span', '', t)));
    // 5. riesgo
    const rz = document.getElementById('ce-riesgo');
    rz.hidden = !c.riesgo.length;
    rz.replaceChildren(el('b', '', '⚠ Atención: '), c.riesgo.join(' · '));
  }

  // ---------- la respuesta: el resultado final del analisis, una sola vez y arriba de todo ----------
  // Sale de la fila 'central' (donde convergen todos los calculos). El detalle de como se llego va en el analisis
  // completo, en 6 partes (ver PARTES), sin repetir la conclusion.
  const PLZ_CORTO = { '5 min': '5 min', '15 min': '15 min', '1 hora': '1 hora', '4 horas': '4 horas', '1 día': '1 día' };
  function drawRespuesta(rows, sum, c) {
    const sec = document.getElementById('respuesta'); sec.hidden = !c; if (!c) return;
    const ahora = sum && okv(sum.precio) ? num(sum.precio) : null;
    const plazo = CE_PLAZO[c.tf];
    document.getElementById('rs-t').textContent = plazo ? `En ${plazo === '1 hora' ? 'la próxima hora' : plazo === '1 día' ? 'el próximo día' : `los próximos ${plazo}`}` : `Velas de ${TF_TXT[c.tf] || c.tf}`;
    document.getElementById('rs-k').textContent = `${MON()}${c.hasta ? ` · hasta las ${c.hasta.slice(-5)} h` : ''}`;
    // los plazos: cambian la respuesta (y el grafico)
    const pl = document.getElementById('rs-plazos');
    pl.replaceChildren(...pick(rows, 'plazo').map((p) => {
      const b = el('button', 'ab-rs-pl', PLZ_CORTO[p.plazo] || p.plazo); b.type = 'button';
      b.setAttribute('aria-pressed', String(plazo === p.plazo)); b.addEventListener('click', () => setPlazo(p.plazo)); return b;
    }));
    // direccion: palabra grande y un dial con cuanta fuerza tiene (a favor menos en contra)
    const af = num(c.a_favor) || 0, ec = num(c.en_contra) || 0, sc = af + ec > 0 ? (af - ec) / (af + ec) : 0;
    const dir = c.direccion === 'sube' ? 'sube' : c.direccion === 'baja' ? 'baja' : '';
    const dw = document.getElementById('rs-dir'); dw.className = `ab-rs-dir ${dir}`.trim();
    dw.textContent = dir === 'sube' ? '▲ Sube' : dir === 'baja' ? '▼ Baja' : '◆ Lateral';
    const fuerzaTxt = Math.abs(sc) >= 0.6 ? 'con fuerza' : Math.abs(sc) >= 0.25 ? 'moderada' : 'sin fuerza';
    document.getElementById('rs-dir-k').textContent = dir ? `Dirección ${fuerzaTxt}` : 'Sin dirección clara';
    const ang = Math.PI * (1 - (sc + 1) / 2), nx = 32 + 24 * Math.cos(ang), ny = 32 - 24 * Math.sin(ang);
    document.getElementById('rs-dial').innerHTML = `<path d="M6 32 A26 26 0 0 1 58 32" fill="none" stroke="url(#rs-g)" stroke-width="6" stroke-linecap="round"/>
      <defs><linearGradient id="rs-g" x1="0" x2="1"><stop offset="0" stop-color="var(--color-bad)"/><stop offset=".5" stop-color="var(--line)"/><stop offset="1" stop-color="var(--color-ok)"/></linearGradient></defs>
      <line x1="32" y1="32" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="var(--ink)" stroke-width="2.4" stroke-linecap="round"/><circle cx="32" cy="32" r="3.2" fill="var(--ink)"/>`;
    document.getElementById('rs-dial').setAttribute('aria-label', `Fuerza de la dirección: ${fuerzaTxt}`);
    // movimiento fuerte: la chance contra lo normal, en una barra
    const pf = num(c.prob_fuerte), pn = num(c.prob_normal), mv = document.getElementById('rs-mov');
    mv.className = `ab-rs-mov${c.fuerza === 'alta' ? ' alta' : c.fuerza === 'media' ? ' media' : ''}`;
    if (okv(pf)) {
      const tope = Math.max(pf, (pn || 0) * 2, 10);
      mv.replaceChildren(el('small', '', 'Movimiento fuerte'), el('b', '', c.fuerza === 'alta' ? `⚡ ${f0(pf)}%` : `${f0(pf)}%`),
        Object.assign(el('span', 'ab-rs-bar'), { innerHTML: `<i style="width:${Math.min(100, pf / tope * 100).toFixed(1)}%"></i>${okv(pn) ? `<u style="left:${Math.min(100, pn / tope * 100).toFixed(1)}%"></u>` : ''}` }),
        el('span', 'ab-rs-sub', okv(pn) ? `lo normal: ${f0(pn)}%` : ''));
    } else mv.replaceChildren(el('small', '', 'Movimiento fuerte'), el('b', '', '—'));
    // rango: barra con el piso y el techo, el precio de ahora y el soporte y la resistencia mas cercanos
    const rg = document.getElementById('rs-rango'), lo = num(c.rango_min), hi = num(c.rango_max), so = num(c.soporte), re = num(c.resistencia);
    if (okv(lo) && okv(hi)) {
      const vals = [lo, hi, so, re, ahora].filter((x) => okv(x) && x > 0), mn = Math.min(...vals), mx = Math.max(...vals), w = mx - mn || 1;
      const x = (v) => `${((v - mn) / w * 92 + 4).toFixed(2)}%`;
      const bar = el('div', 'ab-rs-rbar');
      bar.innerHTML = `<i class="r" style="left:${x(lo)};width:calc(${x(hi)} - ${x(lo)})"></i>${okv(so) ? `<i class="s" style="left:${x(so)}"></i>` : ''}${okv(re) ? `<i class="e" style="left:${x(re)}"></i>` : ''}${ahora ? `<i class="a" style="left:${x(ahora)}"></i>` : ''}`;
      const et = el('div', 'ab-rs-rlbl');
      const lab = (cls, k, v) => { const s = el('span', cls); s.append(el('small', '', k), el('b', '', fp(v))); return s; };
      et.append(okv(so) ? lab('s', 'Soporte', so) : el('span'), lab('r', '8 de cada 10 veces entre', lo), lab('r2', 'y', hi), okv(re) ? lab('e', 'Resistencia', re) : el('span'));
      rg.replaceChildren(bar, et); rg.hidden = false;
    } else rg.hidden = true;
    // la frase que lo junta (la de la conclusion) y el aviso si hay riesgo
    const cc = document.getElementById('cc-txt');
    document.getElementById('rs-txt').textContent = cc ? cc.textContent.trim() : '';
    const rz = document.getElementById('rs-riesgo'); rz.hidden = !c.riesgo.length;
    rz.replaceChildren(el('b', '', '⚠ Atención: '), c.riesgo.join(' · '));
  }
  // ---------- el analisis completo: 6 partes, cada una con su resumen en una linea y el detalle al abrirla ----------
  const PARTES = [
    ['parte-dir', 'Cómo se llegó a la dirección', ['conclusion', 'ce-dir', 'sesgo', 'prediccion', ['que-espero', 'Todas las señales, una por una']]],
    ['parte-mov', 'Cuánto se puede mover', ['movimiento', 'ce-fuerza', 'tug-wrap', 'likely']],
    ['parte-niv', 'Niveles: hasta dónde', ['ce-mapa', 'niveles', 'probabilidades']],
    ['parte-ctx', 'Qué está pasando', ['que-pasa', 'fed-line', 'news-line', 'calendario', 'senales']],
    ['parte-conf', 'Cuánto le creo', ['apr-line', 'aprendizaje', 'aciertos']],
    ['parte-herr', 'Herramientas', ['lm-abrir', 'ondas', 'indicadores', 'siri-atajo']],
  ];
  (function armarPartes() {
    const hoja = document.getElementById('hoja'), $ = (id) => document.getElementById(id);
    // los que vivian adentro de otra tarjeta llevan un id para poder moverlos
    const pred = $('prediccion');
    const tug = pred.querySelector('.ab-tug-wrap'); if (tug) tug.id = 'tug-wrap';
    const lik = pred.querySelector('.ab-likely'); if (lik) lik.id = 'likely-box';
    const idx = el('nav', 'ab-partes-idx'); idx.id = 'partes-idx'; idx.setAttribute('aria-label', 'Partes del análisis completo');
    PARTES.forEach(([id, titulo, hijos], n) => {
      const d = el('details', 'ab-parte'); d.id = id;
      const s = el('summary'), t = el('span', 'ab-parte-t'); t.append(el('i', '', String(n + 1)), el('b', '', titulo));
      s.append(t, el('span', 'ab-parte-res')); d.append(s);
      const cuerpo = el('div', 'ab-parte-c'); d.append(cuerpo);
      hijos.forEach((h) => {
        const [hid, sub] = Array.isArray(h) ? h : [h, null], nodo = $(hid === 'likely' ? 'likely-box' : hid);
        if (!nodo) return;
        if (sub) { const w = el('details', 'ab-parte-sub'); w.append(el('summary', '', sub), nodo); cuerpo.append(w); } else cuerpo.append(nodo);
      });
      hoja.append(d);
      const b = el('button', 'ab-chipbtn', titulo); b.type = 'button';
      b.addEventListener('click', () => { d.open = true; d.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' }); });
      idx.append(b);
    });
    $('vista-btn').after(idx);
    const md = $('mas-detalle'); if (md) md.hidden = true;
    const sn = $('senales'); if (sn) { const sp = sn.querySelector('summary span'); if (sp) sp.textContent = 'Flujo de compras y libros de órdenes'; sn.addEventListener('toggle', () => { if (sn.open && typeof libroTic === 'function') libroTic(); }); }
  })();
  // el resumen de una linea de cada parte (lo que se ve con la parte cerrada)
  function drawPartes(rows, c) {
    const res = (id, t) => { const e = document.querySelector(`#${id} .ab-parte-res`); if (e) e.textContent = t || ''; };
    const txt = (id) => { const e = document.getElementById(id); return e ? e.textContent.replace(/\s+/g, ' ').trim() : ''; };
    if (c) {
      res('parte-dir', `Señales: ${String(c.a_favor).replace('.', ',')} a favor de la suba y ${String(c.en_contra).replace('.', ',')} de la baja · indicadores: ${txt('gauge-txt').toLowerCase() || '—'}`);
      res('parte-mov', okv(c.prob_fuerte) ? `Chance de movimiento fuerte ${f0(num(c.prob_fuerte))}% (lo normal: ${f0(num(c.prob_normal))}%)${okv(c.esperado_usd) ? ` · suele moverse ~${num(c.esperado_usd) >= 100 ? f0(num(c.esperado_usd)) : fp(num(c.esperado_usd))} USD` : ''}` : '');
      res('parte-niv', [okv(c.soporte) ? `Soporte ${fp(num(c.soporte))}` : '', okv(c.resistencia) ? `resistencia ${fp(num(c.resistencia))}` : ''].filter(Boolean).join(' · '));
    }
    const qp = txt('qp-res'), cal = document.querySelector('#calendario summary .ab-kicker');
    res('parte-ctx', [qp, cal ? cal.textContent.trim() : ''].filter(Boolean).join(' · '));
    res('parte-conf', txt('apr-line').replace(/^Confianza ahora:?\s*/i, ''));
    res('parte-herr', 'Mapa de liquidaciones, figuras, todos los indicadores y Siri');
  }

  // ---------- vista simple / completa ----------
  const VISTA_BTN = document.getElementById('vista-btn');
  function vista(completa, guardar) {
    document.documentElement.classList.toggle('ab-simple', !completa);
    VISTA_BTN.setAttribute('aria-expanded', String(completa));
    document.getElementById('vista-txt').textContent = completa ? 'Volver a la vista simple' : 'Ver el análisis completo';
    document.getElementById('vista-sub').textContent = completa ? 'solo la respuesta y el gráfico' : 'cómo se llegó, cuánto se puede mover, niveles, contexto y cuánto acierta';
    if (guardar) try { localStorage.setItem('ab-vista', completa ? 'completa' : 'simple'); } catch (e) { /* sin almacenamiento */ }
  }
  let vistaGuardada = null; try { vistaGuardada = localStorage.getItem('ab-vista'); } catch (e) { /* sin almacenamiento */ }
  vista(vistaGuardada === 'completa', false);
  VISTA_BTN.addEventListener('click', () => {
    const completa = document.documentElement.classList.contains('ab-simple');
    vista(completa, true);
    if (completa) document.getElementById('partes-idx').scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
  });
  // ---------- ordenar el analisis a gusto: el orden y lo oculto quedan guardados en este navegador (localStorage) ----------
  (function () {
    const $ = (id) => document.getElementById(id), hoja = $('hoja'), det = $('mas-detalle');
    // secciones de la hoja: algunas van juntas (el termometro con el resumen; los plazos con la prediccion)
    const HOJA = [['respuesta', ['respuesta', 'tm-tab']], ['compras'], ['posiciones']].concat(PARTES.map(([id]) => [id])).map(([id, ns]) => ({ id, ns: ns || [id] }));
    const COMPLETA = new Set(PARTES.map(([id]) => id));      // las partes del analisis completo (despues del boton)
    const NOM = { respuesta: 'La respuesta (arriba)', compras: 'Plan de compras', posiciones: 'Posiciones' };
    PARTES.forEach(([id, t]) => { NOM[id] = t; });
    const DEF_H = HOJA.map((u) => u.id), DEF_D = [...det.children].filter((n) => n.id).map((n) => n.id);
    const leer = () => { try { return JSON.parse(localStorage.getItem('ab-orden')) || {}; } catch (e) { return {}; } };
    const guardar = (g) => { try { localStorage.setItem('ab-orden', JSON.stringify(g)); } catch (e) { /* sin almacenamiento */ } };
    // lo guardado + lo nuevo que no estaba (en su lugar de siempre, despues de su anterior)
    function mezclar(guardado, def) {
      const out = (guardado || []).filter((id) => def.includes(id));
      def.forEach((id, k) => {
        if (out.includes(id)) return;
        let pos = 0; for (let j = k - 1; j >= 0; j--) { const q = out.indexOf(def[j]); if (q >= 0) { pos = q + 1; break; } }
        out.splice(pos, 0, id);
      });
      return out;
    }
    function aplicar() {
      const g = leer(), oc = new Set(g.ocultas || []);
      const oh = mezclar(g.hoja, DEF_H), od = mezclar(g.det, DEF_D);
      oh.forEach((id) => HOJA.find((u) => u.id === id).ns.forEach((n) => { const e = $(n); if (e) hoja.append(e); }));
      // "Ver el analisis completo" queda antes de la primera de las que solo se ven en la vista completa
      const prim = oh.find((id) => COMPLETA.has(id)), vb = $('vista-btn');
      if (prim) hoja.insertBefore(vb, $(prim)); else hoja.append(vb);
      vb.after($('partes-idx'));
      hoja.append($('orden-btn'));
      const cr = hoja.querySelector('.ab-credito'); if (cr) hoja.append(cr);     // el credito del grafico, al final
      od.forEach((id) => { const e = $(id); if (e) det.append(e); });
      HOJA.forEach((u) => u.ns.forEach((n) => { const e = $(n); if (e) e.classList.toggle('ab-oculta', oc.has(u.id)); }));
      DEF_D.forEach((id) => { const e = $(id); if (e) e.classList.toggle('ab-oculta', oc.has(id)); });
    }
    const nombre = (id, grupo) => {
      if (grupo === 'hoja') return NOM[id] || id;
      const e = $(id), s = e && (e.querySelector('summary span') || e.querySelector('span') || e.querySelector('summary'));
      return (s ? s.textContent : id).trim();
    };
    // el panel: dos listas; se arrastra desde ≡ (con el dedo o el mouse) o con las flechas; el ojo oculta
    const pan = $('orden'), fondo = $('orden-fondo');
    function fila(id, grupo, oc) {
      const li = el('li', 'ab-ord-li'); li.dataset.id = id;
      const asa = el('button', 'ab-ord-asa', '≡'); asa.type = 'button'; asa.setAttribute('aria-label', `Arrastrar ${nombre(id, grupo)}`);
      const n = el('span', 'ab-ord-n', nombre(id, grupo));
      const sub = el('button', 'ab-ord-b', '↑'), baj = el('button', 'ab-ord-b', '↓'); sub.type = baj.type = 'button';
      sub.setAttribute('aria-label', 'Subir'); baj.setAttribute('aria-label', 'Bajar'); sub.dataset.acc = 'sub'; baj.dataset.acc = 'baj';
      const ojo = el('button', 'ab-ord-ojo'); ojo.type = 'button'; ojo.dataset.acc = 'ojo'; ojo.setAttribute('aria-pressed', String(!oc));
      ojo.setAttribute('aria-label', oc ? 'Mostrar' : 'Ocultar'); ojo.title = oc ? 'Oculta: tocá para mostrarla' : 'Visible: tocá para ocultarla';
      ojo.innerHTML = oc ? '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M3 3l18 18M10.6 6.2A9.8 9.8 0 0 1 12 6c5 0 9 6 9 6a16 16 0 0 1-3.2 3.7M6.5 7.6C4.3 9.2 3 12 3 12s4 6 9 6a8.6 8.6 0 0 0 3.9-.9" stroke="currentColor" stroke-width="1.8" fill="none" stroke-linecap="round"/></svg>'
        : '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M3 12s4-6 9-6 9 6 9 6-4 6-9 6-9-6-9-6z" stroke="currentColor" stroke-width="1.8" fill="none"/><circle cx="12" cy="12" r="2.6" fill="currentColor"/></svg>';
      li.classList.toggle('es-oculta', oc);
      li.append(asa, n, sub, baj, ojo); return li;
    }
    function armar() {
      const g = leer(), oc = new Set(g.ocultas || []);
      const vis = (id) => { const e = $(id); return e && !e.hidden; };
      $('orden-hoja').replaceChildren(...mezclar(g.hoja, DEF_H).filter((id) => vis(id) || COMPLETA.has(id) || oc.has(id)).map((id) => fila(id, 'hoja', oc.has(id))));
      $('orden-det').replaceChildren(...mezclar(g.det, DEF_D).map((id) => fila(id, 'det', oc.has(id))));
      $('orden-det').hidden = !DEF_D.length; $('orden-det').previousElementSibling.hidden = !DEF_D.length;
    }
    function desdeListas() {
      const g = leer(), ids = (ol) => [...$(ol).children].map((li) => li.dataset.id);
      const oc = new Set(g.ocultas || []);
      // las que no se listaron (ahora sin datos) conservan su lugar relativo
      g.hoja = mezclar(ids('orden-hoja'), mezclar(g.hoja, DEF_H)); g.det = ids('orden-det');
      [...pan.querySelectorAll('.ab-ord-li')].forEach((li) => { if (li.classList.contains('es-oculta')) oc.add(li.dataset.id); else oc.delete(li.dataset.id); });
      g.ocultas = [...oc]; guardar(g); aplicar();
    }
    pan.addEventListener('click', (e) => {
      const b = e.target.closest('button[data-acc]'); if (!b) return;
      const li = b.closest('li');
      if (b.dataset.acc === 'sub' && li.previousElementSibling) li.parentNode.insertBefore(li, li.previousElementSibling);
      else if (b.dataset.acc === 'baj' && li.nextElementSibling) li.parentNode.insertBefore(li.nextElementSibling, li);
      else if (b.dataset.acc === 'ojo') { const oc = !li.classList.contains('es-oculta'); const nu = fila(li.dataset.id, li.parentNode.id === 'orden-hoja' ? 'hoja' : 'det', oc); li.replaceWith(nu); nu.querySelector('.ab-ord-ojo').focus(); }
      else return;
      if (b.dataset.acc !== 'ojo') b.focus();
      desdeListas();
    });
    // arrastrar: la fila sigue al dedo y las otras se corren
    let drag = null;
    pan.addEventListener('pointerdown', (e) => {
      const asa = e.target.closest('.ab-ord-asa'); if (!asa) return;
      const li = asa.closest('li'); e.preventDefault();
      drag = { li, y0: e.clientY, id: e.pointerId }; li.classList.add('arrastra');
      try { asa.setPointerCapture(e.pointerId); } catch (err) { /* idem */ }
    });
    pan.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const li = drag.li, ol = li.parentNode;
      li.style.transform = `translateY(${e.clientY - drag.y0}px)`;
      const r = li.getBoundingClientRect(), mid = r.top + r.height / 2;
      const prev = li.previousElementSibling, next = li.nextElementSibling;
      if (prev && mid < prev.getBoundingClientRect().top + prev.offsetHeight / 2) { const h = prev.offsetHeight; ol.insertBefore(li, prev); drag.y0 -= h; li.style.transform = `translateY(${e.clientY - drag.y0}px)`; }
      else if (next && mid > next.getBoundingClientRect().top + next.offsetHeight / 2) { const h = next.offsetHeight; ol.insertBefore(next, li); drag.y0 += h; li.style.transform = `translateY(${e.clientY - drag.y0}px)`; }
    });
    const soltar = () => { if (!drag) return; drag.li.classList.remove('arrastra'); drag.li.style.transform = ''; drag = null; desdeListas(); };
    pan.addEventListener('pointerup', soltar); pan.addEventListener('pointercancel', soltar);
    function abrir() { armar(); pan.hidden = false; fondo.hidden = false; document.documentElement.style.overflow = 'hidden'; abFoco(pan, true); }
    function cerrar() { if (pan.hidden) return; abFoco(pan, false); pan.hidden = true; fondo.hidden = true; document.documentElement.style.overflow = ''; }
    $('orden-btn').addEventListener('click', abrir);
    $('orden-x').addEventListener('click', cerrar); $('orden-listo').addEventListener('click', cerrar); fondo.addEventListener('click', cerrar);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !pan.hidden) cerrar(); });
    $('orden-reset').addEventListener('click', () => { guardar({}); aplicar(); armar(); });
    aplicar();
  })();


  // ---------- color del mercado: verde si en 24 h sube, rojo si baja (como Robinhood). Tine el acento de toda la app
  (function () {
    const c = document.getElementById('c24');
    const mira = () => {
      const v = parseFloat(String(c.textContent).replace('−', '-').replace(/[^0-9,.\-+]/g, '').replace(',', '.'));
      const m = !isFinite(v) ? '' : v > 0 ? 'up' : v < 0 ? 'down' : '';
      document.documentElement.style.setProperty('--amb-k', isFinite(v) ? (0.55 + 0.45 * Math.min(1, Math.abs(v) / 3)).toFixed(2) : '.55');
      if (document.documentElement.dataset.mkt !== m) {
        if (m) document.documentElement.dataset.mkt = m; else delete document.documentElement.dataset.mkt;
        try { if (G.ln && S.rows) drawChart(S.rows, S.sum); } catch (e) { /* el grafico todavia no existe: lo toma al dibujarse */ }
        const tc = document.querySelector('meta[name="theme-color"]');
        if (tc) tc.content = getComputedStyle(document.body).backgroundColor;
      }
    };
    new MutationObserver(mira).observe(c, { childList: true, characterData: true, subtree: true }); mira();
  })();

  // destello del ambiente: lo dispara ponerPrecio en el mismo momento en que cambian las cifras del precio de arriba
  // (sube = verde, baja = rojo). Cada cambio reinicia el destello: nunca va antes ni despues de los numeros
  const AMB = { b: document.querySelector('#amb b') };
  function ambPulso(dir) {
    if (!dir || document.hidden) return;
    AMB.b.style.setProperty('--pulso', cssv(dir > 0 ? '--color-ok' : '--color-bad'));
    AMB.b.classList.remove('on'); void AMB.b.offsetWidth; AMB.b.classList.add('on');
  }

  // ---------- modo radio (solo con la pantalla prendida): la app dice el precio y lo que ve, cada tanto y cuando
  // cambia algo (la direccion, un movimiento de mas de 1 % o una linea tuya que se toco). Voz del sistema (gratis, sin red)
  const RADIO = (function () {
    const R = { on: false, cada: 15, ult: 0, dir: null, precio: null, t: null, voz: null };
    const ok = 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
    const NOM = { BTC: 'Bitcoin', ETH: 'Ethereum', SOL: 'Solana', XRP: 'XRP', ZEC: 'Zcash', DOGE: 'Doge', BNB: 'BNB' };
    // numeros como se dicen: sin puntos de miles (la voz los lee mejor) y con coma decimal
    const num = (x) => (x >= 100 ? String(Math.round(x)) : String(Number(x.toFixed(x >= 1 ? 2 : 4))).replace('.', ','));
    const dec = (x) => String(Math.abs(x).toFixed(1)).replace('.', ',');
    function elegirVoz() {
      const vs = speechSynthesis.getVoices().filter((v) => /^es/i.test(v.lang));
      R.voz = vs.find((v) => /AR/i.test(v.lang)) || vs.find((v) => /419|US|MX/i.test(v.lang)) || vs[0] || null;
    }
    function texto(motivo) {
      const rows = S.rows || [], r = rows.find((x) => x.tabla === 'resumen');
      const c = rows.find((x) => x.tabla === 'central' && x.plazo === S.plazo) || rows.find((x) => x.tabla === 'central') || {};
      const precio = (G.d && G.d.price) || (r && r.precio); if (!precio) return null;
      let t = `${motivo ? `${motivo}. ` : ''}${NOM[MON()] || MON()}, ${num(precio)} dólares.`;
      const ch = r ? Number(r.cambio_24h) : NaN;
      if (isFinite(ch)) t += Math.abs(ch) < 0.05 ? ' Igual que hace 24 horas.' : ` ${ch > 0 ? 'Sube' : 'Baja'} ${dec(ch)} por ciento en 24 horas.`;
      if (c.direccion) t += ` Para ${String(c.plazo || S.plazo).replace(/^1 /, 'la próxima ')}, ${c.direccion === 'sube' ? 'más probable que suba' : c.direccion === 'baja' ? 'más probable que baje' : 'sin dirección clara'}.`;
      const lv = [[c.soporte, 'Soporte'], [c.resistencia, 'Resistencia']].filter(([p]) => p).map(([p, n]) => [Number(p), n]).sort((a, b) => Math.abs(a[0] - precio) - Math.abs(b[0] - precio));
      if (lv.length) t += ` ${lv[0][1]} más cerca en ${num(lv[0][0])}.`;
      return t;
    }
    // en un toque (activar o "Decir ahora") se habla en el momento: iOS solo habilita la voz asi. Despues, desde el
    // reloj: se limpia la cola, se "despierta" el motor (Safari y Chrome lo dejan en pausa) y se habla un instante despues
    // (cancelar y hablar seguido a veces se come la frase)
    function decir(t, enToque) {
      if (!ok || !t) return;
      if (!R.voz) elegirVoz();
      const ss = speechSynthesis;
      const hablar = () => {
        const u = new SpeechSynthesisUtterance(t); u.lang = R.voz ? R.voz.lang : 'es-AR'; if (R.voz) u.voice = R.voz; u.rate = 1.03; u.volume = 1;
        u.onstart = () => { R.empezo = Date.now(); estado(); };
        u.onend = () => { R.empezo = 0; estado(); };
        u.onerror = (e) => { R.empezo = 0; R.error = e.error || 'error'; estado(); };
        R.error = null; ss.resume(); ss.speak(u); R.ult = Date.now(); estado();
      };
      if (ss.speaking || ss.pending) ss.cancel();
      if (enToque) hablar(); else setTimeout(hablar, 120);
    }
    const hora = (ms) => new Date(ms).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'America/Argentina/Buenos_Aires' });
    function estado() {
      const e = document.getElementById('vigilia-est'); if (!e) return;
      if (!R.on) { e.textContent = 'Pantalla prendida'; return; }
      e.textContent = R.error ? `La voz no salió (${R.error})` : R.empezo ? 'Hablando…' : `Próxima: ${hora(R.ult + R.cada * 6e4)}`;
    }
    function anotar() {
      const rows = S.rows || [], c = rows.find((x) => x.tabla === 'central' && x.plazo === S.plazo) || {};
      R.dir = c.direccion || null; R.precio = (G.d && G.d.price) || null;
    }
    // cada 15 s: si toca por tiempo, o cambio la direccion, o se movio 1 % desde lo ultimo que dijo
    function mirar() {
      if (!R.on || document.hidden) return;
      estado();
      const rows = S.rows || [], c = rows.find((x) => x.tabla === 'central' && x.plazo === S.plazo) || {};
      const p = G.d && G.d.price;
      let motivo = null;
      if (R.dir && c.direccion && c.direccion !== R.dir) motivo = 'Cambió la dirección';
      else if (R.precio && p && Math.abs(p / R.precio - 1) >= 0.01) motivo = p > R.precio ? 'Subió más de uno por ciento' : 'Bajó más de uno por ciento';
      else if (Date.now() - R.ult >= R.cada * 6e4) motivo = '';
      if (motivo === null) return;
      if (R.empezo && Date.now() - R.empezo < 30000) return;     // sigue hablando (si quedo trabada mas de 30 s, se corta)
      decir(texto(motivo)); anotar();
    }
    const btn = document.getElementById('radio-btn'), sel = document.getElementById('radio-cada'), ya = document.getElementById('radio-ya');
    if (!ok) { btn.hidden = true; sel.hidden = true; }
    function poner(v) {
      R.on = v && ok; btn.setAttribute('aria-pressed', String(R.on)); sel.hidden = !R.on; ya.hidden = !R.on;
      clearInterval(R.t); R.error = null; R.empezo = 0;
      if (R.on) { decir(texto('Modo radio'), true); anotar(); R.t = setInterval(mirar, 5000); }   // la primera, dentro del toque: iOS lo exige
      else if (ok) speechSynthesis.cancel();
      estado();
    }
    btn.addEventListener('click', () => poner(!R.on));
    ya.addEventListener('click', () => { decir(texto(''), true); anotar(); });
    sel.addEventListener('change', () => { R.cada = +sel.value; estado(); });
    // al volver a la app se reanuda el reloj (con la pantalla prendida no deberia pasar, pero si se bloqueo con el boton)
    document.addEventListener('visibilitychange', () => { if (!document.hidden && R.on) estado(); });
    if (ok) { elegirVoz(); speechSynthesis.addEventListener && speechSynthesis.addEventListener('voiceschanged', elegirVoz); }
    window.abVoz = (t) => { if (R.on) decir(t); };
    return { apagar: () => poner(false) };
  })();
  // ---------- sin zoom de la pagina en el celu: el pellizco es para el grafico ----------
  // Safari no hace caso a user-scalable=no: se frena el gesto de zoom (gesturestart) y cualquier movimiento con dos
  // dedos. El grafico igual recibe los toques y hace su propio zoom (Lightweight Charts lee los dedos aunque la pagina
  // no se mueva), asi que un pellizco que empieza en el grafico y termina afuera ya no agranda la pagina.
  ['gesturestart', 'gesturechange', 'gestureend'].forEach((ev) => document.addEventListener(ev, (e) => e.preventDefault(), { passive: false }));
  document.addEventListener('touchmove', (e) => { if (e.touches.length > 1) e.preventDefault(); }, { passive: false });
  if (window.visualViewport && window.visualViewport.scale > 1.01) document.querySelector('meta[name="viewport"]')?.setAttribute('content', 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover');
  // ---------- pantalla siempre prendida: pide al sistema que no apague la pantalla (Wake Lock) y deja solo el precio,
  // el grafico y el fondo vivo. Si se bloquea el telefono con el boton, iOS apaga igual (ninguna app lo puede evitar):
  // al volver se vuelve a pedir. Sin Wake Lock (iOS viejo): un video mudo de 1 s en bucle, el truco de siempre
  (function () {
    const btn = document.getElementById('vigilia-btn'), bar = document.getElementById('vigilia-bar'), est = document.getElementById('vigilia-est');
    let lock = null, on = false, video = null;
    const VIDEO = 'data:video/mp4;base64,AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAMYbW9vdgAAAGxtdmhkAAAAAAAAAAAAAAAAAAAD6AAAA+gAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAkJ0cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAA+gAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAABAAAAAQAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAAPoAAAAAAABAAAAAAG6bWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAABAAAAAQABVxAAAAAAALWhkbHIAAAAAAAAAAHZpZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAABZW1pbmYAAAAUdm1oZAAAAAEAAAAAAAAAAAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQAAASVzdGJsAAAAwXN0c2QAAAAAAAAAAQAAALFhdmMxAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAABAAEABIAAAASAAAAAAAAAABFUxhdmM2MC4zMS4xMDIgbGlieDI2NAAAAAAAAAAAAAAAGP//AAAAN2F2Y0MBZAAK/+EAGWdkAAqscgRewEQAAAMABAAAAwAIPEiWEYABAAdo6EOBlLIs/fj4AAAAABBwYXNwAAAAAQAAAAEAAAAUYnRydAAAAAAAABYgAAAWIAAAABhzdHRzAAAAAAAAAAEAAAABAABAAAAAABxzdHNjAAAAAAAAAAEAAAABAAAAAQAAAAEAAAAUc3RzegAAAAAAAALEAAAAAQAAABRzdGNvAAAAAAAAAAEAAANIAAAAYnVkdGEAAABabWV0YQAAAAAAAAAhaGRscgAAAAAAAAAAbWRpcmFwcGwAAAAAAAAAAAAAAAAtaWxzdAAAACWpdG9vAAAAHWRhdGEAAAABAAAAAExhdmY2MC4xNi4xMDAAAAAIZnJlZQAAAsxtZGF0AAACrwYF//+r3EXpvebZSLeWLNgg2SPu73gyNjQgLSBjb3JlIDE2NCByMzEwOCAzMWUxOWY5IC0gSC4yNjQvTVBFRy00IEFWQyBjb2RlYyAtIENvcHlsZWZ0IDIwMDMtMjAyMyAtIGh0dHA6Ly93d3cudmlkZW9sYW4ub3JnL3gyNjQuaHRtbCAtIG9wdGlvbnM6IGNhYmFjPTEgcmVmPTE2IGRlYmxvY2s9MTowOjAgYW5hbHlzZT0weDM6MHgxMzMgbWU9dW1oIHN1Ym1lPTEwIHBzeT0xIHBzeV9yZD0xLjAwOjAuMDAgbWl4ZWRfcmVmPTEgbWVfcmFuZ2U9MjQgY2hyb21hX21lPTEgdHJlbGxpcz0yIDh4OGRjdD0xIGNxbT0wIGRlYWR6b25lPTIxLDExIGZhc3RfcHNraXA9MSBjaHJvbWFfcXBfb2Zmc2V0PS0yIHRocmVhZHM9MSBsb29rYWhlYWRfdGhyZWFkcz0xIHNsaWNlZF90aHJlYWRzPTAgbnI9MCBkZWNpbWF0ZT0xIGludGVybGFjZWQ9MCBibHVyYXlfY29tcGF0PTAgY29uc3RyYWluZWRfaW50cmE9MCBiZnJhbWVzPTggYl9weXJhbWlkPTIgYl9hZGFwdD0yIGJfYmlhcz0wIGRpcmVjdD0zIHdlaWdodGI9MSBvcGVuX2dvcD0wIHdlaWdodHA9MiBrZXlpbnQ9MjUwIGtleWludF9taW49MSBzY2VuZWN1dD00MCBpbnRyYV9yZWZyZXNoPTAgcmNfbG9va2FoZWFkPTYwIHJjPWNyZiBtYnRyZWU9MSBjcmY9NTEuMCBxY29tcD0wLjYwIHFwbWluPTAgcXBtYXg9NjkgcXBzdGVwPTQgaXBfcmF0aW89MS40MCBhcT0xOjEuMDAAgAAAAA1liIEAAr8SC1v/hIp/';
    async function pedir() {
      if (!on || document.hidden) return;
      try {
        if ('wakeLock' in navigator) { lock = await navigator.wakeLock.request('screen'); lock.addEventListener('release', () => { lock = null; }); est.textContent = 'Pantalla prendida'; return; }
      } catch (e) { /* sin permiso o sin bateria: probamos el video */ }
      try {
        if (!video) { video = document.createElement('video'); video.muted = true; video.loop = true; video.playsInline = true; video.setAttribute('playsinline', '');
          video.src = VIDEO; video.style.cssText = 'position:fixed;width:1px;height:1px;opacity:0;pointer-events:none'; document.body.append(video); }
        await video.play(); est.textContent = 'Pantalla prendida';
      } catch (e) { est.textContent = 'Este navegador no deja mantener la pantalla prendida'; }
    }
    function soltar() { if (lock) lock.release().catch(() => {}); lock = null; if (video) video.pause(); }
    function poner(v) {
      on = v; document.documentElement.classList.toggle('ab-vigilia', v); bar.hidden = !v;
      btn.setAttribute('aria-pressed', String(v));
      if (v) { pedir(); document.getElementById('vigilia-salir').focus({ preventScroll: true }); window.scrollTo(0, 0); }
      else { soltar(); RADIO.apagar(); btn.focus({ preventScroll: true }); }
      window.dispatchEvent(new Event('resize'));
    }
    btn.setAttribute('aria-pressed', 'false');
    btn.addEventListener('click', () => poner(!on));
    document.getElementById('vigilia-salir').addEventListener('click', () => poner(false));
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && on) poner(false); });
    // al volver a la app (despues de bloquear o cambiar de app) el sistema solto el permiso: se vuelve a pedir
    document.addEventListener('visibilitychange', () => { if (!document.hidden) pedir(); });
  })();
  // ---------- volver arriba (con el analisis completo la pagina es larga) ----------
  (function () {
    const b = document.getElementById('arriba-btn'); let raf = 0;
    const mira = () => { raf = 0; b.classList.toggle('on', window.scrollY > window.innerHeight * 1.5); };
    window.addEventListener('scroll', () => { if (!raf) raf = requestAnimationFrame(mira); }, { passive: true });
    b.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' });
      const t = document.getElementById('ab-title'); if (t) { t.tabIndex = -1; t.focus({ preventScroll: true }); }   // el foco tambien vuelve arriba
    });
    mira();
  })();
  // ---------- atajo de Siri: la direccion para pegar en Atajos ----------
  (function () {
    const url = `${location.origin}${location.pathname.replace(/[^/]*$/, '')}api/siri`, code = document.getElementById('siri-url');
    code.textContent = url;
    document.getElementById('siri-copiar').addEventListener('click', async (e) => {
      try { await navigator.clipboard.writeText(url); e.target.textContent = 'Copiada'; } catch (err) { e.target.textContent = 'Copiala de abajo'; }
      setTimeout(() => { e.target.textContent = 'Copiar la dirección'; }, 2500);
    });
  })();

  // ---------- barra con el precio al bajar ----------
  function miniPintar() {
    const pe = root.querySelector('.ab-price'), c = document.getElementById('c24');
    document.getElementById('mini-mon').textContent = MON();
    document.getElementById('mini-p').textContent = pe && pe.firstChild ? pe.firstChild.textContent : '—';
    const mc = document.getElementById('mini-c'); mc.textContent = c ? c.textContent : ''; mc.className = c ? c.className : '';
    const d = document.querySelector('#ce-tira [data-k="dir"] b'), f = document.querySelector('#ce-tira [data-k="fz"] b');
    document.getElementById('mini-h').textContent = d ? `${d.textContent}${f && !/^No/.test(f.textContent) ? ' · ⚡ fuerte' : ''}` : '';
  }
  if ('IntersectionObserver' in window) {
    const ojo = new IntersectionObserver(([e]) => {
      const on = !e.isIntersecting && e.boundingClientRect.top < 0;
      MINI.classList.toggle('on', on); MINI.tabIndex = on ? 0 : -1; MINI.setAttribute('aria-hidden', String(!on));
      if (on) miniPintar();
    });
    const pr = root.querySelector('.ab-price'); if (pr) ojo.observe(pr);
  }
  MINI.addEventListener('click', () => window.scrollTo({ top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }));
  // con la hoja (celu): el precio queda quieto atras, asi que la barra aparece cuando la hoja tapa la cabecera
  const HOJA = document.getElementById('hoja'), CEL = matchMedia('(max-width: 999.98px)');
  let miniRaf = 0;
  addEventListener('scroll', () => {
    if (miniRaf || !CEL.matches) return;
    miniRaf = requestAnimationFrame(() => {
      miniRaf = 0;
      const tope = HOJA.getBoundingClientRect().top, on = tope < 64;
      document.documentElement.classList.toggle('ab-hoja-arriba', tope < innerHeight * 0.55);
      if (on === MINI.classList.contains('on')) return;
      MINI.classList.toggle('on', on); MINI.tabIndex = on ? 0 : -1; MINI.setAttribute('aria-hidden', String(!on));
      if (on) miniPintar();
    });
  }, { passive: true });
  { const det = document.getElementById('widget-ios'), btn = document.getElementById('widget-copiar');
    let cod = null, pedido = null;
    const bajar = () => (pedido = pedido || fetch('widget-iphone.js', { cache: 'no-cache' }).then((r) => r.text()).then((t) => (cod = t)));
    det.addEventListener('toggle', () => { if (det.open) bajar().catch(() => { pedido = null; }); });
    btn.addEventListener('click', async () => {
      try {
        if (cod) await navigator.clipboard.writeText(cod);
        else await navigator.clipboard.write([new ClipboardItem({ 'text/plain': bajar().then((t) => new Blob([t], { type: 'text/plain' })) })]);
        btn.textContent = 'Copiado ✓';
      } catch (e) { btn.textContent = 'No se pudo copiar: abrí widget-iphone.js'; window.open('widget-iphone.js', '_blank', 'noopener'); }
      setTimeout(() => { btn.textContent = 'Copiar el código'; }, 3000);
    });
  }
  // plazos que no entran: desvanecido en el borde mientras quede algo a la derecha
  { const t = document.getElementById('tfs');
    const ver = () => t.classList.toggle('ab-desliza', t.scrollWidth - t.clientWidth - t.scrollLeft > 4);
    t.addEventListener('scroll', ver, { passive: true }); addEventListener('resize', ver); setTimeout(ver, 300); }
  // el asa: sube la hoja hasta arriba, o la vuelve a bajar si ya esta arriba
  document.getElementById('asa').addEventListener('click', () => {
    const top = HOJA.getBoundingClientRect().top;
    window.scrollTo({ top: top < 80 ? 0 : scrollY + top - 44, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  });
  // plazos en el celu: se marca por que lado hay mas tarjetas
  function plazosBordes() {
    const n = document.getElementById('plazos'); if (!n) return;
    const mas = n.scrollWidth - n.clientWidth > 4;
    n.classList.toggle('mas-izq', mas && n.scrollLeft > 4); n.classList.toggle('mas-der', mas && n.scrollLeft < n.scrollWidth - n.clientWidth - 4);
  }
  document.getElementById('plazos').addEventListener('scroll', plazosBordes, { passive: true });
  window.addEventListener('resize', plazosBordes, { passive: true });

  function drawConclusion() {
    const sec = document.getElementById('conclusion'), txt = (id) => { const e = document.getElementById(id); return e && !e.closest('[hidden]') ? e.textContent.trim() : ''; };
    const hora = txt('verdict-big').replace(/^[^\wÁÉÍÓÚÑáéíóúñ]+/, ''), ind = txt('gauge-txt'), tab = document.getElementById('tm-tab');
    const ciclo = tab && !tab.hidden ? txt('tm-zona') : '';
    if (!hora || hora === '—') { sec.hidden = true; return; }
    sec.hidden = false;
    const lado = (t) => (/sub|alcista|compra/i.test(t) ? 1 : /baj|cae|venta|vend/i.test(t) ? -1 : 0);
    const pon = (id, t) => { const e = document.getElementById(id); e.textContent = t || '—'; e.className = t ? (lado(t) > 0 ? 'sube' : lado(t) < 0 ? 'baja' : '') : ''; };
    pon('cc-hora', hora); pon('cc-ind', ind); pon('cc-ciclo', ciclo);
    document.getElementById('cc-ind-k').textContent = `Indicadores ${TF_TXT[S.tf] || ''}`.trim();
    // Los indicadores (medias y osciladores, ahora) y la prediccion (que paso despues en casos parecidos) miran la misma
    // hora de forma distinta; el ciclo mira meses. Se explica cada diferencia en vez de una frase generica.
    const [lh, li, lc] = [lado(hora), lado(ind), ciclo ? lado(ciclo) : 0], dir = (x) => (x > 0 ? 'al alza' : 'a la baja'), fr = [];
    if (li && lh === 0) fr.push(`Los indicadores marcan ${ind.toLowerCase()}, pero en casos parecidos del pasado el precio no tuvo una dirección clara en la próxima hora: por eso la predicción dice lateral.`);
    else if (li && lh && li !== lh) fr.push(`Los indicadores apuntan ${dir(li)}, pero en casos parecidos del pasado el precio terminó ${dir(lh)}: la predicción se basa en eso.`);
    else if (lh && li === lh) fr.push(`Indicadores y predicción coinciden ${dir(lh)} para la próxima hora.`);
    else if (lh && !li) fr.push(`Los indicadores están neutrales, pero en casos parecidos el precio terminó ${dir(lh)}.`);
    if (lc && (lh || li) && lc !== (lh || li)) fr.push(`El ciclo apunta ${dir(lc)}: no lo contradice, mira semanas o meses.`);
    else if (lc && lc === (lh || li)) fr.push(`El ciclo (semanas o meses) apunta para el mismo lado.`);
    else if (lc) fr.push(`El ciclo, que mira semanas o meses, apunta ${dir(lc)}.`);
    // en la vista simple queda solo la primera frase (la que explica la diferencia mas importante)
    const cc = document.getElementById('cc-txt');
    if (!fr.length) cc.textContent = 'Sin una dirección clara en ningún plazo.';
    else cc.replaceChildren(fr[0], ...fr.slice(1).map((x) => el('span', 'ab-cc-mas', ` ${x}`)));
  }

  // Las explicaciones largas (como se calcula, que significa) quedan en 2 lineas: se abren tocandolas. La pagina era muy
  // larga (4.300 px en la compu, 5.200 en el celu). Las que abriste quedan abiertas.
  const NOTA_ABIERTA = new Set();
  function plegarNotas() {
    root.querySelectorAll('.ab-card .ab-note:not([data-pl]), .ab-card .ab-hero-sub.ab-larga:not([data-pl])').forEach((n) => {
      n.dataset.pl = '1';
      const t = n.textContent.trim();
      if (t.length < 200 || n.closest('.ab-tm-panel, #compras, #posiciones, .ab-nt-modal')) return;
      n.classList.add('ab-plegable'); n.tabIndex = 0; n.setAttribute('role', 'button');
      const abierta = NOTA_ABIERTA.has(t.slice(0, 60));
      n.classList.toggle('abierta', abierta); n.setAttribute('aria-expanded', String(abierta));
    });
  }
  function alternarNota(n) {
    const t = n.textContent.trim().slice(0, 60), ab = !n.classList.contains('abierta');
    n.classList.toggle('abierta', ab); n.setAttribute('aria-expanded', String(ab));
    if (ab) NOTA_ABIERTA.add(t); else NOTA_ABIERTA.delete(t);
  }
  document.addEventListener('click', (e) => { const n = e.target.closest && e.target.closest('.ab-plegable'); if (n && !e.target.closest('a')) alternarNota(n); });
  document.addEventListener('keydown', (e) => { if ((e.key === 'Enter' || e.key === ' ') && e.target.classList && e.target.classList.contains('ab-plegable')) { e.preventDefault(); alternarNota(e.target); } });
  document.addEventListener('toggle', () => setTimeout(plegarNotas, 0), true);   // lo que se arma al abrir una seccion

  // Lo que esta dentro de un desplegable cerrado no se dibuja en cada analisis (cada 12 s): se dibuja al abrirlo y,
  // mientras siga abierto, con cada analisis. Antes se armaba todo aunque no se viera.
  const PEREZOSOS = { probabilidades: () => drawProbs(S.rows, S.sum), senales: () => drawSignals(S.rows), niveles: () => drawLevels(S.rows, S.sum),
    ondas: () => drawWaves(S.rows), indicadores: () => drawIndicators(S.rows), aciertos: () => drawHits(S.rows) };
  const pendiente = new Set();
  function perezoso(id) {
    const d = document.getElementById(id);
    if (d && !d.open) { pendiente.add(id); return; }
    pendiente.delete(id);
    try { PEREZOSOS[id](); } catch (e) { console.error(id, e); }
  }
  Object.keys(PEREZOSOS).forEach((id) => {
    const d = document.getElementById(id);
    if (d) d.addEventListener('toggle', () => { if (d.open && pendiente.has(id) && S.rows) perezoso(id); });
  });

  // "Como viene aprendiendo" cambia pocas veces por hora: se redibuja solo si cambiaron sus filas, el plazo, el ancho o el tema
  let aprFirma = '', aprAncho = window.innerWidth;
  window.addEventListener('resize', () => { aprAncho = window.innerWidth; });      // leerlo en medio del dibujado forzaba un re-layout
  function drawLearningSiCambia(rows) {
    const firma = JSON.stringify([S.plazo, aprAncho, window.abOscuro ? window.abOscuro() : 0, pick(rows, 'aprendizaje'), pick(rows, 'aprendizaje_curva')]);
    if (firma === aprFirma) return;
    aprFirma = firma; drawLearning(rows);
  }

  // ---------- que esta pasando: por que se mueve fuerte ----------
  // Cuando hay una suba o baja fuerte junta lo que coincide en el tiempo: liquidaciones o dinero nuevo en futuros,
  // compras o ventas a mercado, compras desde EE.UU. (prima de Coinbase), entradas o salidas de los ETF y las noticias
  // de esas horas (guerras, la Fed, aranceles, hackeos...). Son coincidencias, no pruebas de la causa.
  const TEMA_ORDEN = ['Hackeo de exchange', 'Fed y tasas', 'Guerras grandes', 'Gobierno de EE.UU.', 'Grandes gobiernos', 'ETF', 'Hackeo o quiebra', 'Alibaba', 'Nvidia', 'Alphabet', 'AMD', 'Apple', 'Microsoft', 'Amazon', 'SpaceX', 'Meta', 'Tesla', 'Nasdaq 100', 'S&P 500', 'Strategy', 'Mercado Libre', 'China', 'Economía de EE.UU.', 'Latinoamérica', 'Chips e IA', 'IA y tecnología', 'Grandes tecnológicas', 'Autos eléctricos', 'Espacio y defensa', 'Mercado bursátil', 'Cripto'];
  // acciones (perpetuos): de donde salen sus noticias y desde cuando hay velas
  const ACC_INFO = { BABA: ['Alibaba, China, Wall Street y Hang Seng', 'Binance', 'mediados de 2026'], NVDA: ['Nvidia, chips e IA, economía de EE.UU. y Wall Street', 'Binance', '2026'],
    GOOGL: ['Alphabet/Google, IA y tecnología, economía de EE.UU. y Wall Street', 'Binance', '2026'], AMD: ['AMD, chips e IA, economía de EE.UU. y Wall Street', 'Binance', '2026'],
    AAPL: ['Apple, IA y tecnología, economía de EE.UU. y Wall Street', 'Binance', 'abril de 2026'], MSFT: ['Microsoft, IA y tecnología, economía de EE.UU. y Wall Street', 'Binance', 'abril de 2026'],
    AMZN: ['Amazon (y AWS), IA y tecnología, economía de EE.UU. y Wall Street', 'Binance', 'febrero de 2026'], SPCX: ['SpaceX y Starlink, espacio y defensa, economía de EE.UU. y Wall Street', 'Binance', 'mayo de 2026'],
    META: ['Meta (Facebook, Instagram, WhatsApp), IA y tecnología, economía de EE.UU. y Wall Street', 'Binance', 'marzo de 2026'], TSLA: ['Tesla y Elon Musk, autos eléctricos, economía de EE.UU. y Wall Street', 'Binance', 'enero de 2026'],
    QQQ: ['el Nasdaq, las grandes tecnológicas, la economía de EE.UU. y Wall Street', 'Binance', 'abril de 2026'],
    SPY: ['el S&P 500, las grandes tecnológicas, la economía de EE.UU. y Wall Street', 'Binance', 'abril de 2026'],
    MSTR: ['Strategy (MicroStrategy) y el bitcoin que compra, Bitcoin, economía de EE.UU. y Wall Street', 'Binance', 'fines de octubre de 2026'],
    MELI: ['Mercado Libre, Latinoamérica (Brasil, Argentina, México) y Wall Street', 'Bitget', 'agosto de 2026'] };
  const haceTxt = (t) => {
    const m = Math.max(0, Math.round((Date.now() - t) / 60000));
    return m < 60 ? `hace ${m} min` : m < 1440 ? `hace ${Math.round(m / 60)} h` : `hace ${Math.round(m / 1440)} d`;
  };
  // clima de las noticias: cada titular suma (bueno) o resta (malo) segun su peso (guerras grandes y gobierno de EE.UU. 3;
  // gobiernos grandes, ETF y hackeos 2; cripto 1) y pierde la mitad de su peso cada 3 horas. Es una lectura del titular.
  function climaNoticias(rows, horas = 6) {
    const now = Date.now(), ns = pick(rows, 'noticia').filter((n) => now - num(n.t) <= horas * 3600000 && num(n.t) <= now + 600000);
    let score = 0; const malas = [], buenas = [];
    ns.forEach((n) => {
      const sgn = n.sesgo === 'alcista' ? 1 : n.sesgo === 'bajista' ? -1 : 0; if (!sgn) return;
      const w = (num(n.impacto) || 1) * Math.pow(0.5, (now - num(n.t)) / (3 * 3600000));
      score += sgn * w; (sgn > 0 ? buenas : malas).push(n);
    });
    const est = score >= 2 ? 'alcista' : score <= -2 ? 'bajista' : 'neutral';
    const temas = (xs) => [...new Set(xs.sort((a, b) => num(b.impacto) - num(a.impacto)).map((n) => n.tema.toLowerCase()))].slice(0, 2).join(', ');
    return { n: ns.length, score, est, buenas: buenas.length, malas: malas.length, tb: temas(buenas), tm: temas(malas) };
  }

  // ---------- proximas compras: el plan de plan_compras.json, con donde esta el precio y que ya se ejecuto ----------
  // el plan de compras: en la version del telefono llega del servidor (api/posiciones) recien con la contraseña de BingX;
  // ya no va adentro de la pagina publicada (generar_pagina.py solo lo mete si existe plan_compras.json en la carpeta)
  let PLAN_COMPRAS = /*PLAN*/null/*FIN*/;
  const PLAN_EMBEBIDO = PLAN_COMPRAS;          // al desconectar, el que vino del servidor se olvida
  // datos[m]: minimo, maximo y precio desde el plan; hist: cuando se bajaron las velas diarias; vivo[m]: ultimo precio en vivo
  const CMP = { datos: {}, hora: null, hist: 0, vivo: {} };
  // ---------- BingX en vivo (solo lectura; api/posiciones.js de Vercel): posiciones y ordenes reales ----------
  // Conectado, "Mis posiciones" sale de BingX (no del JSON) y una compra del plan esta "cargada" si hay una orden limite
  // de compra a ese precio. La contraseña (POSICIONES_CLAVE de Vercel) se guarda en este navegador.
  const BX = { ok: false, posiciones: null, ordenes: null, hora: null, error: null, autorizado: false };
  const BX_API = window.abPosicionesApi || null;       // solo la version del telefono (Vercel) tiene el servidor
  // Tu plan (Proximas compras), Mis posiciones, la capa "Mi plan" y sus avisos: solo para quien conecto BingX con la
  // contraseña de Vercel (POSICIONES_CLAVE) y el servidor la acepto. Sin el servidor de BingX (pagina de Render, que
  // ya pide su propia contraseña) se ven como antes.
  const PLAN_OK = () => (BX_API ? BX.autorizado : !!PLAN_COMPRAS);
  // Con BingX conectado, Proximas compras y Mis posiciones salen directo de BingX (ordenes limite de compra y posiciones
  // abiertas). El plan solo aporta las reglas (toma de ganancias, piramidado, mantenimiento, comision); si no llega, estas
  const REGLAS = { apalancamiento: 5, ganancias: { cada: 0.4, vender: 0.25, niveles: 4 }, piramidar: { cada: 0.15, liq_max: 0.75 } };
  const reglas = () => ({ ...REGLAS, ...(PLAN_COMPRAS || {}) });
  const ORDEN_MON = () => (window.abActivo ? window.abActivo.todos() : []);
  function monedasPlan() {
    const ms = BX.ok ? [...new Set([...Object.keys(BX.posiciones || {}), ...Object.keys(BX.ordenes || {})])]
      : PLAN_COMPRAS ? [...new Set(PLAN_COMPRAS.compras.map((c) => c.moneda))] : [];
    const o = ORDEN_MON(), k = (m) => (o.indexOf(m) < 0 ? 99 : o.indexOf(m));
    return ms.sort((a, b) => k(a) - k(b) || a.localeCompare(b));
  }
  const bxClave = () => { try { return localStorage.getItem('ab-bingx-clave'); } catch (e) { return null; } };
  async function bxLeer() {
    const clave = bxClave();
    if (!BX_API || !clave) { BX.ok = false; return; }
    BX.leido = Date.now();
    try {
      const r = await fetch(BX_API, { headers: { 'x-clave': clave }, cache: 'no-store' });
      if (r.status !== 401 && r.status !== 503) BX.autorizado = true;     // la contraseña paso (aunque BingX falle un rato)
      const j = await r.json();
      if (j.plan && typeof j.plan === 'object' && Array.isArray(j.plan.compras)) PLAN_COMPRAS = j.plan;   // el plan privado
      BX.planError = j.plan_error || null;
      if (j.ok) {
        Object.assign(BX, { ok: true, posiciones: j.posiciones || {}, ordenes: j.ordenes, hora: new Date(j.hora), error: null, capital: j.capital || null,
          pnlLeido: Object.values(j.posiciones || {}).reduce((a, p) => a + (p.resultado || 0), 0) });
        pnlRef();
      }
      else {
        Object.assign(BX, { ok: false, error: j.error || `error ${r.status}` });
        if (r.status === 401) { BX.autorizado = false; try { localStorage.removeItem('ab-bingx-clave'); } catch (e) { /* idem */ } }
      }
    } catch (e) { BX.error = 'sin conexión con el servidor'; }
    planVisible();
  }
  // orden puesta: con BingX, las que tienen su orden emparejada (comprasDe); sin BingX, lo que dice el plan
  const cargada = (c) => (c.deBingx ? true : BX.ok && BX.ordenes ? false : !!c.cargada);
  // Cada 15 s se redibuja con el precio en vivo (WebSocket, ver pnlConectar). Las velas diarias (minimo y maximo desde el
  // plan) se bajan cada 2 min, o antes si de una cripto no llega el precio en vivo. Antes eran 4 pedidos cada 15 s.
  const CMP_HIST = 120000, CMP_VIVO = 30000;
  function cmpVivo(m, p) {
    CMP.vivo[m] = Date.now();
    const d = CMP.datos[m]; if (!d || !(p > 0)) return;      // hasta que lleguen las velas diarias
    d.precio = p; if (p < d.bajo) d.bajo = p; if (p > d.alto) d.alto = p;
    d.minVivo = Math.min(d.minVivo === undefined ? p : d.minVivo, p);      // lo mas bajo entre vuelta y vuelta (avisos)
  }
  // si ya hay una vuelta en camino (al abrir la app se pedia dos veces: la del arranque y la de BingX recien leido), esa
  function cmpPrecios() { return CMP.vuelo || (CMP.vuelo = cmpPedir().finally(() => { CMP.vuelo = null; })); }
  async function cmpPedir() {
    if (!PLAN_OK()) return;                                // sin BingX conectado el plan no se muestra: no hace falta pedir nada
    const mons = monedasPlan(), ahora = Date.now(), hist = ahora - CMP.hist > CMP_HIST;
    const pedir = hist ? mons : mons.filter((m) => !CMP.datos[m] || ahora - (CMP.vivo[m] || 0) > CMP_VIVO);
    // desde el inicio del dia del plan: con la hora exacta, el primer dia (vela diaria abierta antes) no venia y quedaba vacio
    const d0 = PLAN_COMPRAS && PLAN_COMPRAS.desde ? PLAN_COMPRAS.desde : Date.now() - 30 * 86400000, desde = d0 - (d0 % 86400000);
    // solo los dias desde el plan: con limit=1500 Binance cobraba 10 de peso por pedido aunque vinieran 20 velas (4 criptos cada 15 s)
    const dias = Math.min(1500, Math.ceil((Date.now() - desde) / 86400000) + 2);
    const poner = (m, bajo, alto, precio) => {
      const v = ahora - (CMP.vivo[m] || 0) < 5000 && CMP.datos[m] ? CMP.datos[m].precio : null;   // el en vivo es mas nuevo
      CMP.datos[m] = { bajo: v ? Math.min(bajo, v) : bajo, alto: v ? Math.max(alto, v) : alto, precio: v || precio };
    };
    if (hist && mons.length) CMP.hist = ahora;
    await Promise.all(pedir.map(async (m) => {
      const s = `${m}USDT`;
      try {
        const k = await (await fetch(`https://fapi.binance.com/fapi/v1/klines?symbol=${s}&interval=1d&startTime=${desde}&limit=${dias}`)).json();
        if (!Array.isArray(k) || !k.length) throw new Error('vacio');
        poner(m, Math.min(...k.map((x) => +x[3])), Math.max(...k.map((x) => +x[2])), +k[k.length - 1][4]);
      } catch (e) {
        try {
          const j = await (await fetch(`https://api.bybit.com/v5/market/kline?category=linear&symbol=${s}&interval=D&start=${desde}&limit=${Math.min(1000, dias)}`)).json();
          const k = j.result.list;
          if (!k || !k.length) throw new Error('vacio');
          poner(m, Math.min(...k.map((x) => +x[3])), Math.max(...k.map((x) => +x[2])), +k[0][4]);
        } catch (e2) { /* sin datos de esa cripto: queda lo ultimo */ }
      }
    }));
    CMP.hora = new Date(); drawCompras(); drawPosiciones(); if (window.abNotif) window.abNotif.plan();
  }
  function drawCompras() {
    const sec = document.getElementById('compras'), body = document.getElementById('cmp-body');
    if (!PLAN_OK() || !ES_CRIPTO(MON())) { sec.hidden = true; return; }      // el plan es de criptos y solo con BingX conectado
    sec.hidden = false; body.replaceChildren();
    const mons = monedasPlan().filter((m) => comprasDe(m).length || !BX.ok);
    if (!mons.length) body.append(el('p', 'ab-note', 'No tenés órdenes límite de compra puestas en BingX.'));
    mons.forEach((m) => {
      const d = CMP.datos[m], cs = comprasDe(m).slice().sort((a, b) => b.precio - a.precio);
      const box = el('div', 'ab-cmp'), h = el('div', 'ab-cmp-h');
      const hechas = cs.filter((c) => cmpHecha(c, d)).length;
      h.append(el('b', '', m), el('span', '', !d ? 'cargando precio…' : BX.ok ? `ahora ${fp(d.precio)} · ${cs.length} ${cs.length === 1 ? 'orden' : 'órdenes'} en BingX` : `ahora ${fp(d.precio)} · ${hechas}/${cs.length} ejecutadas`));
      box.append(h);
      let marcado = false, prox = false;
      cs.forEach((c) => {
        const hecha = cmpHecha(c, d);
        if (d && !marcado && d.precio > c.precio) { box.append(el('div', 'ab-cmp-now', `ahora ${fp(d.precio)}`)); marcado = true; }
        const dist = d ? (d.precio / c.precio - 1) * 100 : null;
        let cls = 'ab-cmp-row', ic = '○', st = '';
        const conBx = !c.en_posicion && !!bxEjecutadas(m, d);
        if (hecha) { cls += ' ok'; ic = '✔'; st = c.en_posicion ? 'En tu posición' : conBx ? (c.extra_agregado ? 'Se ejecutó · en tu posición' : `Se ejecutó · sumá ${f0(c.extra)} de margen`) : c.cargada ? (c.extra_agregado ? 'Se ejecutó' : `Se ejecutó · sumá ${f0(c.extra)} de margen`) : 'Tocó el precio (sin orden)'; }
        // el precio paso por ahi, pero BingX no tiene la orden y la posicion no crecio (si la orden esta puesta, sigue esperando:
        // el minimo puede ser de antes de que la movieras)
        else if (conBx && tocada(c, d) && !cargada(c)) { ic = '⚠'; cls += ' carga'; st = 'Tocó el precio · revisá la orden'; }
        else if (!cargada(c)) { ic = '✎'; st = dist !== null && dist <= 3 ? `¡Cargá la orden! (a ${f1(dist)}%)` : 'Falta cargar la orden'; if (dist !== null && dist <= 3) cls += ' carga'; }
        else { ic = '⏳'; st = dist === null ? 'Orden puesta' : `Orden puesta · a ${f1(dist)}%`; }
        if (!hecha && !prox) { cls += ' prox'; prox = true; }
        const row = el('div', cls), mid = el('div');
        mid.append(el('b', '', `${nCompra(c)} · ${fp(c.precio)}`), el('em', '', c.deBingx && BX.ok ? `Orden ${f0(c.orden)} USDT · ${ar.format(',.4f')(c.cantidad)} ${m}` : `Orden ${f0(c.orden)} · margen extra ${f0(c.extra)}`));
        const stEl = el('span', 'st', st);
        if (ic === '⚠') stEl.title = 'El precio llegó a esta compra pero tu posición en BingX todavía no creció: la orden no se llenó, se movió o falta que BingX la refleje (se lee cada minuto).';
        row.append(el('span', '', ic), mid, stEl); box.append(row);
      });
      if (d && !marcado) box.append(el('div', 'ab-cmp-now', `ahora ${fp(d.precio)}`));
      body.append(box);
    });
    const hr = document.getElementById('cmp-hora');
    hr.textContent = CMP.hora ? `precios ${String(CMP.hora.getHours()).padStart(2, '0')}:${String(CMP.hora.getMinutes()).padStart(2, '0')}` : '—';
  }
  // ---------- mis posiciones (las mismas cuentas que posiciones.py) ----------
  // La compra ya se ejecuto: estaba en la posicion de BingX cuando se armo el plan, o:
  // - con BingX conectado: el precio llego Y la posicion crecio lo que suman las compras hasta esa (de la mas alta a la
  //   mas baja). Si el precio llego pero la posicion no crecio, no cuenta (la orden no se lleno o se movio).
  // - sin BingX: el precio la toco desde que se armo el plan.
  const tocada = (c, d) => !!(d && d.bajo <= c.precio);
  const nCompra = (c) => (typeof c.n === 'number' ? `#${c.n}` : String(c.n));     // "#3", o "extra 1" (una orden de BingX que no esta en el plan)
  // Las compras de cada cripto. Con BingX conectado, las pendientes salen de tus ordenes limite de compra de BingX (precio
  // y valor reales: si moves una orden alla, se ve aca sin tocar el plan). Se emparejan con las del plan que no estaban
  // en la posicion, de abajo hacia arriba: las que quedan arriba sin orden son las que ya se ejecutaron (si la posicion
  // crecio) o las que falta cargar. El numero y el margen extra salen del plan; una orden de BingX de mas va como "extra".
  const COMPRAS_MEMO = new Map();
  function comprasDe(m) {
    const ords = BX.ok && BX.ordenes ? BX.ordenes[m] || [] : null, memo = COMPRAS_MEMO.get(m);
    if (memo && memo.plan === PLAN_COMPRAS && memo.ords === ords && memo.directo === BX.ok) return memo.lista;   // los mismos objetos (cmpHecha los compara)
    if (BX.ok) {                                                // directo de BingX: tus ordenes limite de compra, de la mas alta a la mas baja
      const lista = (ords || []).slice().sort((a, b) => b.precio - a.precio).map((o, i) => ({ moneda: m, n: i + 1, precio: o.precio, orden: o.valor,
        cantidad: o.cantidad, extra: null, cargada: true, deBingx: true }));
      COMPRAS_MEMO.set(m, { plan: PLAN_COMPRAS, ords, lista, directo: true });
      return lista;
    }
    const plan = PLAN_COMPRAS ? PLAN_COMPRAS.compras.filter((c) => c.moneda === m) : [];
    let lista = plan;
    if (ords) {
      const os = ords.slice().sort((a, b) => b.precio - a.precio);
      const enPos = plan.filter((c) => c.en_posicion), resto = plan.filter((c) => !c.en_posicion).sort((a, b) => b.precio - a.precio);
      // cada orden con la compra del plan de precio mas parecido, sin cruzarse (de arriba hacia abajo): si cancelaste la de
      // mas abajo, la orden que queda sigue con su compra. Las compras sin orden quedan solas (ejecutadas o por cargar)
      const nPar = Math.min(os.length, resto.length);
      let mejor = null;
      const elegir = (desde, faltan, usados) => {       // combinaciones de compras (en orden) para las nPar ordenes de mas abajo
        if (!faltan) {
          const ords = os.slice(os.length - nPar), costo = usados.reduce((t, j, i) => t + Math.abs(Math.log(ords[i].precio / resto[j].precio)), 0);
          if (!mejor || costo < mejor.costo - 1e-12) mejor = { costo, usados: usados.slice() };
          return;
        }
        for (let j = desde; j <= resto.length - faltan; j++) { usados.push(j); elegir(j + 1, faltan - 1, usados); usados.pop(); }
      };
      elegir(0, nPar, []);
      const par = new Map((mejor ? mejor.usados : []).map((j, i) => [j, os[os.length - nPar + i]]));
      const extras = os.slice(0, os.length - nPar).map((o, i) => ({ moneda: m, n: `extra ${i + 1}`, extra: 0, extra_agregado: true,
        precio: o.precio, orden: o.valor, cargada: true, deBingx: true, precioPlan: null }));
      const res = resto.map((c, j) => (par.has(j) ? { ...c, precio: par.get(j).precio, orden: par.get(j).valor, cargada: true, deBingx: true, precioPlan: c.precio } : c));
      lista = enPos.concat(extras, res);
    }
    COMPRAS_MEMO.set(m, { plan: PLAN_COMPRAS, ords, lista, directo: false });
    return lista;
  }
  function bxEjecutadas(m, d) {
    const vivo = BX.ok ? (BX.posiciones || {})[m] : null, base = PLAN_COMPRAS && (PLAN_COMPRAS.posiciones || {})[m];
    if (!vivo || !base || !d) return null;
    const conOrdenes = !!BX.ordenes;
    const pend = comprasDe(m).filter((c) => !c.en_posicion).sort((a, b) => b.precio - a.precio);
    const out = new Set();
    let espera = base.cantidad;
    for (const c of pend) {
      if (c.deBingx) break;                                       // su orden sigue abierta en BingX: no se ejecuto
      if (!conOrdenes && !tocada(c, d)) break;                    // sin las ordenes de BingX: el precio tuvo que llegar
      const q = c.orden / c.precio; espera += q;
      if (vivo.cantidad >= espera - q * 0.1) out.add(c); else break;   // 10% de margen por el redondeo de BingX
    }
    return out;
  }
  const cmpHecha = (c, d) => {
    if (c.deBingx && BX.ok) return false;                     // una orden abierta en BingX todavia no se ejecuto
    if (c.en_posicion) return true;
    const ej = bxEjecutadas(c.moneda, d);
    return ej ? ej.has(c) : tocada(c, d);
  };
  function planEstado(m, d) {
    const P = reglas(), mt = P.mantenimiento || {}, r = mt[m] !== undefined ? mt[m] : (mt.otras !== undefined ? mt.otras : 0.01);
    const cs = comprasDe(m), vivo = BX.ok ? (BX.posiciones || {})[m] : undefined;
    const lev = (vivo && vivo.apalancamiento) || P.apalancamiento || 5;      // margen de las ordenes que falten: el de BingX
    const base = BX.ok ? vivo : (P.posiciones || {})[m];
    const hechas = cs.filter((c) => cmpHecha(c, d) && (BX.ok || c.en_posicion || c.cargada));
    const nuevas = BX.ok ? [] : base ? hechas.filter((c) => !c.en_posicion) : hechas;     // BingX ya incluye lo ejecutado
    const sum = (xs, f) => xs.reduce((s, c) => s + f(c), 0);
    let margen, nocional, cantidad;
    if (base) {
      margen = base.margen + sum(nuevas, (c) => c.orden / lev);
      nocional = base.cantidad * base.entrada + sum(nuevas, (c) => c.orden); cantidad = base.cantidad + sum(nuevas, (c) => c.orden / c.precio);
    } else {
      margen = sum(hechas, (c) => c.orden / lev) + sum(cs.filter((c) => c.extra_agregado), (c) => c.extra);
      nocional = sum(hechas, (c) => c.orden); cantidad = sum(hechas, (c) => c.orden / c.precio);
    }
    const liqDe = (n, q, mg) => (q > 0 ? Math.max(0, (n - mg) / (q * (1 - r))) : null);
    const out = { moneda: m, hechas: hechas.length, total: cs.length, precio: d ? d.precio : null, margen, base: !!base, bingx: !!vivo };
    if (cantidad <= 0 || !d) return out;
    const prom = nocional / cantidad, valor = cantidad * d.precio, liq = vivo && vivo.liquidacion ? vivo.liquidacion : liqDe(nocional, cantidad, margen);
    // Precio de equilibrio (como el de BingX): el que deja la posicion en cero contando comisiones y funding. Con BingX: el
    // suyo si lo da; si no, la entrada con lo ya realizado (comisiones pagadas y funding) y la comision de cerrar. Sin
    // BingX: la entrada mas la comision de abrir y la de cerrar (taker, 0,05% por defecto; "comision" en el plan)
    const fee = P.comision !== undefined ? P.comision : 0.0005;
    const eq = vivo && vivo.equilibrio ? vivo.equilibrio
      : vivo && vivo.realizado !== undefined ? (nocional - vivo.realizado) / (cantidad * (1 - fee))
        : (prom * (1 + fee)) / (1 - fee);
    // resultado: con BingX, el suyo (precio de marca) movido en vivo como el total de arriba; sin BingX, al precio de ahora
    const pnl = vivo ? pnlMoneda(m) : valor - nocional;
    Object.assign(out, { promedio: prom, equilibrio: eq, cantidad, nocional, valor, pnl, pnl_pct: (pnl / margen) * 100,
      apalancamiento_real: valor / (margen + valor - nocional), liquidacion: liq, dist_liq: liq ? (1 - liq / d.precio) * 100 : null });
    // si el precio baja hasta la liquidacion, antes se ejecutan las compras que faltan: la liquidacion de verdad es esta
    const pend = cs.filter((c) => !hechas.includes(c));
    if (pend.length) out.liq_plan = liqDe(nocional + sum(pend, (c) => c.orden), cantidad + sum(pend, (c) => c.orden / c.precio), margen + sum(pend, (c) => c.orden / lev));
    const g = P.ganancias;
    if (g) out.ganancias = Array.from({ length: g.niveles || 4 }, (_, i) => { const k = i + 1, px = eq * (1 + g.cada * k);    // sobre el equilibrio
      return { k, precio: px, vender: cantidad * g.vender, usdt: cantidad * g.vender * px, alcanzado: d.alto !== undefined && d.alto >= px }; });
    const pz = P.piramidar;
    if (pz) {
      const lmax = pz.liq_max * (cs.length ? Math.min(...cs.map((c) => c.precio)) : prom), k = lmax * (1 - r);
      let a = d.precio > k ? (k * cantidad - nocional + margen) / (1 - k / d.precio) : 0;
      a = Math.max(0, Math.min(a, lev * margen - nocional));
      out.piramidar = { disponible: d.precio >= eq * (1 + pz.cada), desde: eq * (1 + pz.cada), sumar: a, monedas: a / d.precio,
        liq_nueva: liqDe(nocional + a, cantidad + a / d.precio, margen), liq_max: lmax };
    }
    return out;
  }
  window.abPlanEstado = planEstado;
  // al cambiar de activo (contexto de app.js): mostrar u ocultar el plan y las posiciones
  if (window.abActivo) window.abActivo.subscribe(() => {
    drawCompras(); drawPosiciones();
    const chip = document.querySelector('#layers [data-layer="plan"]'), con = PLAN_OK() && ES_CRIPTO(MON());   // capa "Mi plan": solo criptos
    if (chip && chip.hidden === con) { chip.hidden = !con; syncLayers(); }
  });
  // minimo probable a 6 meses (modelo de armar_termometro.py, viene en la fila 'piso' del analisis; como analisis.js)
  let PISO = null;
  try { PISO = JSON.parse(localStorage.getItem('ab-piso')) || null; } catch (e) { PISO = null; }
  const pisoCdf = (x, xs, ys) => { if (x <= xs[0]) return 0; if (x >= xs[xs.length - 1]) return 1;
    for (let i = 1; i < xs.length; i++) if (x <= xs[i]) { const lo = xs[i - 1], hi = xs[i]; return hi === lo ? ys[i - 1] : ys[i - 1] + ((ys[i] - ys[i - 1]) * (x - lo)) / (hi - lo); }
    return 1; };
  function pisoProb(m, precio, nivel) {          // probabilidad (0-1) de que el minimo de 6 meses quede debajo de 'nivel'
    if (!PISO || !PISO.vol[m] || !(precio > 0) || !(nivel > 0)) return null;
    const x = Math.log(nivel / precio), pz = pisoCdf(x / PISO.vol[m], PISO.z, PISO.grid), own = PISO.own[m];
    return own ? 0.5 * pz + 0.5 * pisoCdf(x, own, PISO.grid) : pz;
  }
  function pisoNivel(m, precio, conf) {          // precio que no se rompe en 6 meses con 'conf' % de confianza
    if (!PISO || !PISO.vol[m]) return null;
    let lo = precio * Math.exp(-6), hi = precio * Math.E;
    for (let k = 0; k < 60; k++) { const mid = Math.sqrt(lo * hi); if (pisoProb(m, precio, mid) < 1 - conf / 100) lo = mid; else hi = mid; }
    return Math.sqrt(lo * hi);
  }
  function drawPosiciones() {
    const sec = document.getElementById('posiciones'), body = document.getElementById('pos-body');
    if (!PLAN_OK() || !ES_CRIPTO(MON())) { sec.hidden = true; if (typeof pnlConectar === 'function') pnlConectar(); return; }
    sec.hidden = false; body.replaceChildren();
    const sgn = (x, f = f0) => `${x >= 0 ? '+' : '−'}${f(Math.abs(x))}`;
    const monsP = BX.ok ? monedasPlan().filter((m) => (BX.posiciones || {})[m]) : monedasPlan();
    if (BX.ok && !monsP.length) body.append(el('p', 'ab-note', 'No tenés posiciones abiertas en BingX.'));
    monsP.forEach((m) => {
      const d = CMP.datos[m], e = planEstado(m, d), box = el('div', 'ab-cmp'), h = el('div', 'ab-cmp-h');
      h.append(el('b', '', m), el('span', '', !d ? 'cargando precio…' : BX.ok ? `ahora ${fp(d.precio)} · ${e.total ? `${e.total} ${e.total === 1 ? 'orden pendiente' : 'órdenes pendientes'}` : 'sin órdenes pendientes'}` : `ahora ${fp(d.precio)} · ${e.hechas}/${e.total} compras del plan`));
      box.append(h);
      if (e.cantidad === undefined) { box.append(el('p', 'ab-note', d ? `Ninguna compra ejecutada todavía. Margen ya puesto: ${f0(e.margen)} USDT.` : '')); body.append(box); return; }
      const kv = el('div', 'ab-pos-kv'), cell = (k, v, cls = '') => { const c = el('div'); c.append(el('small', '', k), el('b', cls, v)); kv.append(c); };
      cell('Cantidad', `${ar.format(',.4f')(e.cantidad)} ${m}`);
      { const c = el('div'), sm = el('small', '', 'Precio de equilibrio'); sm.title = 'El que deja la posición en cero con las comisiones de BingX (y el funding pagado): como el de BingX.';
        c.append(sm, el('b', '', fp(e.equilibrio)), el('small', '', `entrada ${fp(e.promedio)}`)); kv.append(c); }
      cell('Resultado', `${sgn(e.pnl)} USDT (${sgn(e.pnl_pct, f1)}%)`, e.pnl >= 0 ? 'ab-pos-ok' : 'ab-pos-bad');
      cell('Margen', `${f0(e.margen)} USDT`); cell('Posición', `${f0(e.valor)} USDT`); cell('Apalancamiento real', `${f1(e.apalancamiento_real)}x`);
      cell('Liquidación', e.liquidacion ? `${fp(e.liquidacion)} (${f0(e.dist_liq)}% abajo)` : 'no se liquida', e.liquidacion && e.dist_liq < 15 ? 'ab-pos-bad' : '');
      box.append(kv);
      const lr = e.liq_plan || e.liquidacion, pp = lr ? pisoProb(m, d.precio, lr) : null, n95 = pisoNivel(m, d.precio, 95), n90 = pisoNivel(m, d.precio, 90);
      if (n95) {
        const rg = el('div', 'ab-pos-rg');
        rg.style.setProperty('--rg-col', pp === null ? 'var(--color-ok)' : pp > 0.2 ? 'var(--color-bad)' : pp > 0.05 ? 'var(--color-warn)' : 'var(--color-ok)');
        if (pp !== null) {
          rg.append('Chance de tocar tu liquidación en los próximos 6 meses: ', el('b', '', `${pp < 0.01 ? 'menos de 1' : f0(pp * 100)}%`),
            e.liq_plan ? ` (contando las compras que faltan, que se ejecutarían en la bajada: liquidación en ${fp(e.liq_plan)}). ` : '. ');
        }
        else rg.append('Esta posición no se liquida. ');
        rg.append(`En 6 meses ${m} no baja de ${fp(n90)} con 90% de confianza, ni de ${fp(n95)} con 95%. Para que el riesgo sea de 5% o menos, la liquidación tiene que quedar debajo de ${fp(n95)}.`);
        const bj = ((PISO.anteriores || {})[m] || []).filter((a) => a[1] === 'bajista');
        if (bj.length) {
          const peor = bj.reduce((a, b) => (b[2] < a[2] ? b : a)), lv = d.precio * (1 + peor[2] / 100);
          rg.append(` En años bajistas anteriores, desde esta fecha cayó hasta ${bj.map((a) => `${f0(Math.abs(a[2]))}% (${a[0]})`).join(', ')}: con la peor, ${fp(lv)}, tu liquidación ${!lr || lr < lv ? 'aguantaría' : 'no aguantaría'}.`);
        }
        box.append(el('p', 'ab-pos-sec', 'Riesgo a 6 meses'), rg);
      }
      if (e.ganancias) {
        box.append(el('p', 'ab-pos-sec', 'Toma de ganancias (a spot)'));
        let prox = false;
        e.ganancias.forEach((g) => {
          let cls = 'ab-cmp-row'; if (g.alcanzado) cls += ' ok'; else if (!prox) { cls += ' prox'; prox = true; }
          const row = el('div', cls), mid = el('div');
          mid.append(el('b', '', `+${f0(g.k * reglas().ganancias.cada * 100)}% · ${fp(g.precio)}`), el('em', '', `Pasar ${ar.format(',.4f')(g.vender)} ${m} (~${f0(g.usdt)} USDT)`));
          row.append(el('span', '', g.alcanzado ? '✔' : '○'), mid, el('span', 'st', g.alcanzado ? 'Llegó: vendé' : `a ${f1((g.precio / d.precio - 1) * 100)}%`));
          box.append(row);
        });
      }
      if (e.piramidar) {
        const z = e.piramidar, pz = el('div', `ab-pos-pz${z.disponible ? ' on' : ''}`);
        pz.textContent = z.disponible
          ? `Piramidar: podés sumar ${f0(z.sumar)} USDT de posición (${ar.format(',.4f')(z.monedas)} ${m}) sin plata nueva: sacás margen y abrís más long. La liquidación quedaría en ${fp(z.liq_nueva)}.`
          : `Piramidar: se habilita cuando ${m} pase ${fp(z.desde)} (+${f0(reglas().piramidar.cada * 100)}% sobre tu equilibrio).`;
        box.append(el('p', 'ab-pos-sec', 'Piramidar'), pz);
      }
      body.append(box);
    });
    const hr = document.getElementById('pos-hora'), bxb = document.getElementById('bx-btn');
    hr.textContent = BX.ok ? `BingX en vivo · ${BX.hora.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}`
      : BX.error ? `BingX: ${BX.error}` : CMP.hora ? `en vivo · ${CMP.hora.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}` : '—';
    bxb.hidden = !BX_API; bxb.textContent = bxClave() ? 'Desconectar BingX' : 'Conectar BingX';
    document.getElementById('pos-bx-nota').hidden = !BX.ok;
    document.getElementById('pos-foot-plan').hidden = BX.ok;
    document.getElementById('cmp-foot-bx').hidden = !BX.ok; document.getElementById('cmp-foot-plan').hidden = BX.ok;
    pnlPintar(); pnlConectar();
  }
  // ---------- PnL no realizado de todas las posiciones abiertas, en vivo ----------
  // BingX da el resultado de cada posicion cuando se lee (cada minuto). Entre lectura y lectura se mueve con el precio de
  // marca en vivo (WebSocket de Binance, cada 1 s; si no anda, el precio de cada 15 s): resultado + cantidad × (precio de
  // ahora − precio al leer BingX). Al usar la diferencia desde la lectura, la distancia entre la marca de Binance y la de
  // BingX no suma error.
  const PNL = { marca: {}, ref: {}, ws: null, syms: '', t: 0, cuadro: 0 };
  const pnlAhora = (m) => PNL.marca[m] || (CMP.datos[m] && CMP.datos[m].precio) || null;
  function pnlRef() { PNL.ref = {}; Object.keys(BX.posiciones || {}).forEach((m) => { const a = pnlAhora(m); if (a) PNL.ref[m] = a; }); }
  function pnlMoneda(m) {           // el resultado de una posicion de BingX, en vivo (ver pnlVivo)
    const p = (BX.posiciones || {})[m]; if (!p) return 0;
    const a = pnlAhora(m); if (!PNL.ref[m] && a) PNL.ref[m] = a;
    return (p.resultado || 0) + (a && PNL.ref[m] ? (p.signo || 1) * p.cantidad * (a - PNL.ref[m]) : 0);
  }
  function pnlVivo() {
    const ps = BX.ok ? BX.posiciones || {} : {}, ms = Object.keys(ps);
    if (!ms.length) return null;
    let total = 0, margen = 0;
    const por = ms.map((m) => {
      const p = ps[m], a = pnlAhora(m);
      if (!PNL.ref[m] && a) PNL.ref[m] = a;                // si al leer BingX todavia no habia precio: el primero que llega
      const r0 = PNL.ref[m];
      const r = (p.resultado || 0) + (a && r0 ? (p.signo || 1) * p.cantidad * (a - r0) : 0);
      total += r; margen += p.margen || 0;
      return [m, r];
    }).sort((x, y) => Math.abs(y[1]) - Math.abs(x[1]));
    return { total, margen, pct: margen ? (total / margen) * 100 : null, por };
  }
  function pnlPintar() {
    const box = document.getElementById('pos-total'), v = pnlVivo();
    if (!box) return;
    box.hidden = !v || document.getElementById('posiciones').hidden;
    if (box.hidden) return;
    const sg = (x, f = f2) => `${x >= 0 ? '+' : '−'}${f(Math.abs(x))}`, b = document.getElementById('pnl-total');
    b.textContent = `${sg(v.total)} USDT`; b.className = v.total >= 0 ? 'ab-pos-ok' : 'ab-pos-bad';
    document.getElementById('pnl-pct').textContent = v.pct === null ? '' : `${sg(v.pct, f1)}% sobre ${f0(v.margen)} USDT de margen`;
    const por = document.getElementById('pnl-por'); por.replaceChildren();
    v.por.forEach(([m, r]) => { const s = el('span', r >= 0 ? 'ab-pos-ok' : 'ab-pos-bad', `${m} ${sg(r)}`); por.append(s); });
    document.getElementById('pnl-vivo').classList.toggle('quieto', !PNL.ws || Date.now() - PNL.t > 5000);
    // capital total: el de BingX al leer, mas lo que se movio el PnL desde entonces
    const cap = BX.capital, cb = document.getElementById('pos-cap');
    cb.hidden = !cap || !Number.isFinite(cap.total);
    if (!cb.hidden) {
      document.getElementById('cap-total').textContent = `${f2(cap.total + (v.total - (BX.pnlLeido || 0)))} USDT`;
      document.getElementById('cap-det').textContent = cap.parcial ? 'parcial: BingX no dio todas las cuentas'
        : `futuros ${f0(cap.futuros || 0)}${cap.otras ? ` · spot y otras ${f0(cap.otras)}` : ''}`;
    }
  }
  // Un solo WebSocket: precio de marca de las posiciones (para el PnL, con Mis posiciones a la vista) y ultimo precio de
  // las criptos del plan (para Proximas compras y los avisos, aunque estes mirando una accion).
  function pnlConectar() {
    const ms = BX.ok && !document.hidden && !document.getElementById('posiciones').hidden ? Object.keys(BX.posiciones || {}).filter((m) => m !== 'MELI') : [];
    const mc = PLAN_OK() && !document.hidden ? monedasPlan().filter((m) => m !== 'MELI') : [];
    const syms = ms.map((m) => `${m.toLowerCase()}usdt@markPrice@1s`).concat(mc.map((m) => `${m.toLowerCase()}usdt@miniTicker`)).join('/');
    if (syms === PNL.syms) return;
    PNL.syms = syms;
    if (PNL.ws) { try { PNL.ws.close(); } catch (e) { /* ya cerrado */ } PNL.ws = null; }
    if (!syms) return;
    try {
      const ws = new WebSocket(`wss://fstream.binance.com/market/stream?streams=${syms}`);
      PNL.ws = ws;
      ws.onmessage = (e) => {
        try {
          const d = JSON.parse(e.data).data; if (!d || !d.s) return;
          if (d.e === '24hrMiniTicker') return cmpVivo(d.s.replace('USDT', ''), +d.c);   // se dibuja en la vuelta de 15 s
          if (+d.p > 0) { PNL.marca[d.s.replace('USDT', '')] = +d.p; PNL.t = Date.now(); }
        } catch (x) { return; }
        if (!PNL.cuadro) PNL.cuadro = requestAnimationFrame(() => { PNL.cuadro = 0; pnlPintar(); });   // a lo sumo un repintado por cuadro
      };
      ws.onclose = () => { if (PNL.ws === ws) { PNL.ws = null; PNL.syms = ''; setTimeout(pnlConectar, 5000); } };
    } catch (e) { PNL.ws = null; }
  }
  document.addEventListener('visibilitychange', () => { if (document.hidden) { if (PNL.ws) { const w = PNL.ws; PNL.ws = null; PNL.syms = ''; try { w.close(); } catch (e) { /* idem */ } } } else pnlConectar(); });
  {                                                           // cmpPrecios no hace nada hasta que haya plan visible
    setTimeout(cmpPrecios, 500); setInterval(() => { if (!document.hidden) cmpPrecios(); }, 15000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) cmpPrecios(); });     // al volver a la app, al toque
  }
  // mostrar u ocultar todo lo del plan segun si BingX esta conectado (y la llave del encabezado para conectarlo)
  function planVisible() {
    const llave = document.getElementById('bx-llave');
    if (llave) llave.hidden = !BX_API || BX.autorizado;
    if (PLAN_OK() && !CMP.hora) cmpPrecios();               // recien conectado: los precios del plan al toque
    drawCompras(); drawPosiciones();
    const chip = document.querySelector('#layers [data-layer="plan"]'), con = PLAN_OK() && ES_CRIPTO(MON());
    if (chip && chip.hidden === con) { chip.hidden = !con; syncLayers(); if (S.rows) drawChart(S.rows, S.sum); }
  }
  if (BX_API) {
    const conectar = async () => {
      if (bxClave()) {                                     // desconectar: se olvida la contraseña y se oculta el plan
        try { localStorage.removeItem('ab-bingx-clave'); } catch (e) { /* idem */ }
        Object.assign(BX, { ok: false, error: null, autorizado: false, posiciones: null, ordenes: null }); PLAN_COMPRAS = PLAN_EMBEBIDO; planVisible(); return;
      }
      bxErr.hidden = true; bxPass.value = ''; bxDlg.showModal(); bxPass.focus();
    };
    const bxDlg = document.getElementById('bx-dlg'), bxPass = document.getElementById('bx-pass'), bxErr = document.getElementById('bx-err');
    const bxOk = document.getElementById('bx-ok');
    document.getElementById('bx-cancel').addEventListener('click', () => bxDlg.close());
    document.getElementById('bx-form').addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const c = bxPass.value.trim();
      if (!c) { bxErr.textContent = 'Escribí la contraseña.'; bxErr.hidden = false; bxPass.focus(); return; }
      try { localStorage.setItem('ab-bingx-clave', c); } catch (e) { /* sin almacenamiento: no se puede recordar */ }
      bxOk.disabled = true; bxOk.textContent = 'Conectando…';
      await bxLeer();
      bxOk.disabled = false; bxOk.textContent = 'Conectar';
      if (BX.autorizado) { bxDlg.close(); return; }
      bxErr.textContent = BX.error ? `No se pudo conectar: ${BX.error}` : 'No se pudo conectar con BingX. Revisá la contraseña.';
      bxErr.hidden = false; bxPass.select();
    });
    document.getElementById('bx-btn').addEventListener('click', conectar);
    document.getElementById('bx-llave').addEventListener('click', conectar);
    planVisible();
    // BingX (una llamada a la funcion de Vercel): cada minuto si alguna orden esta a 3% o menos (puede ejecutarse); si no,
    // cada 3 min; mirando una accion (no se ven las secciones), cada 5. El PnL igual se mueve en vivo con el WebSocket.
    const bxCerca = () => monedasPlan().some((m) => { const d = CMP.datos[m]; return !d || comprasDe(m).some((c) => d.precio / c.precio - 1 <= 0.03); });
    const bxCada = () => (!ES_CRIPTO(MON()) ? 300000 : bxCerca() ? 60000 : 180000);
    bxLeer(); setInterval(() => { if (!document.hidden && bxClave() && Date.now() - (BX.leido || 0) >= bxCada() - 1000) bxLeer(); }, 15000);
    // al volver a la app: posiciones y ordenes al toque (antes podian tener hasta un minuto)
    document.addEventListener('visibilitychange', () => { if (!document.hidden) bxLeer(); });
  }

  // ---------- notificaciones en la pagina (no por Telegram) ----------
  // Se arman en este dispositivo cuando cambia algo: zona del termometro, funding de 7 dias extremo, compras del plan
  // cerca o ejecutadas, liquidacion cerca, toma de ganancias alcanzada y piramidado disponible. Se guardan en este
  // navegador (las ultimas 60). La primera vez solo se anota como esta todo, sin avisar.
  window.abNotif = (function () {
    const LS = 'ab-notifs', LE = 'ab-notif-estado';
    const leer = (k, def) => { try { return JSON.parse(localStorage.getItem(k)) || def; } catch (e) { return def; } };
    const guardar = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* sin almacenamiento */ } };
    let lista = leer(LS, []), est = leer(LE, {});
    const btn = document.getElementById('nt-btn'), pop = document.getElementById('nt-pop'), listEl = document.getElementById('nt-list');
    const badge = document.getElementById('nt-badge'), modal = document.getElementById('nt-modal'), back = document.getElementById('nt-back');
    const hace = (t) => { const m = Math.round((Date.now() - t) / 60000); return m < 1 ? 'recién' : m < 60 ? `hace ${m} min` : m < 1440 ? `hace ${Math.round(m / 60)} h` : `hace ${Math.round(m / 1440)} d`; };
    function pintar() {
      const n = lista.filter((x) => !x.leida).length;
      badge.hidden = !n; badge.textContent = n > 9 ? '9+' : String(n);
      listEl.replaceChildren();
      if (!lista.length) { listEl.append(el('p', 'ab-nt-vacio', 'Sin notificaciones. Te aviso acá cuando cambie el termómetro, el funding se ponga extremo, se acerque o se ejecute una compra, se venga un movimiento fuerte, la liquidación quede cerca, llegue una toma de ganancias o se pueda piramidar.')); return; }
      lista.forEach((x) => {
        const b = el('button', `ab-nt-it${x.leida ? ' leida' : ''}`); b.type = 'button';
        const mid = el('span'); mid.append(el('b', '', x.titulo), el('small', '', `${x.resumen} · ${hace(x.t)}`));
        b.append(el('span', '', x.icono || '•'), mid, el('i'));
        b.addEventListener('click', () => abrir(x)); listEl.append(b);
      });
    }
    function nueva(id, icono, titulo, resumen, detalle, ir) {
      if (lista.some((x) => x.id === id)) return;
      lista.unshift({ id, icono, titulo, resumen, detalle, ir, t: Date.now(), leida: false });
      lista = lista.slice(0, 60); guardar(LS, lista); pintar();
    }
    // dispara cuando la condicion pasa de falsa a verdadera; la primera vez que se ve, solo se anota
    function cuando(clave, cond, fn) {
      const antes = est[clave]; est[clave] = cond ? 1 : 0;
      if (antes === 0 && cond) fn();
    }
    function cambio(clave, valor, fn) {
      const antes = est[clave]; est[clave] = valor;
      if (antes !== undefined && antes !== null && valor !== null && antes !== valor) fn(antes);
    }
    function abrir(x) {
      x.leida = true; guardar(LS, lista); pintar(); pop.hidden = true; btn.setAttribute('aria-expanded', 'false');
      document.getElementById('nt-m-k').textContent = `${x.icono || ''} ${new Date(x.t).toLocaleString('es-AR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}`;
      document.getElementById('nt-m-t').textContent = x.titulo;
      const body = document.getElementById('nt-m-body'); body.replaceChildren();
      const ul = el('ul'); (x.detalle || []).forEach((l) => ul.append(el('li', '', l))); body.append(ul);
      if (x.ir) {
        const go = el('button', 'ab-iconbtn', x.ir === 'termometro' ? 'Abrir el termómetro' : x.ir === 'posiciones' ? 'Ver mis posiciones' : 'Ver próximas compras');
        go.type = 'button'; go.style.justifySelf = 'start';
        go.addEventListener('click', () => { cerrar(); if (x.ir === 'termometro') document.getElementById('tm-tab').click(); else document.getElementById(x.ir).scrollIntoView({ behavior: 'smooth', block: 'start' }); });
        body.append(go);
      }
      modal.hidden = false; back.hidden = false; back.classList.add('on'); document.documentElement.style.overflow = 'hidden'; abFoco(modal, true);
    }
    function cerrar() { if (modal.hidden) return; abFoco(modal, false); modal.hidden = true; back.classList.remove('on'); back.hidden = true; document.documentElement.style.overflow = ''; }
    btn.addEventListener('click', (e) => { e.stopPropagation(); pop.hidden = !pop.hidden; btn.setAttribute('aria-expanded', String(!pop.hidden)); if (!pop.hidden) pintar(); });
    document.addEventListener('click', (e) => { if (!pop.hidden && !pop.contains(e.target) && e.target !== btn) { pop.hidden = true; btn.setAttribute('aria-expanded', 'false'); } });
    document.getElementById('nt-leer').addEventListener('click', () => { lista.forEach((x) => { x.leida = true; }); guardar(LS, lista); pintar(); });
    ['nt-m-x', 'nt-back'].forEach((id) => document.getElementById(id).addEventListener('click', cerrar));
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { cerrar(); pop.hidden = true; } });
    pintar();
    return {
      // con cada analisis: termometro y funding de la cripto que se esta viendo
      filas(rows) {
        const mon = window.abMoneda || 'BTC', hoy = new Date().toISOString().slice(0, 10);
        const t = pick(rows, 'termometro')[0];
        if (t) cambio(`tm:${mon}`, t.medidor_zona, (antes) => nueva(`tm:${mon}:${t.medidor_zona}:${hoy}`, '🌡', `Termómetro de ${mon}: ${t.medidor_zona}`,
          `${f0(num(t.medidor))}/100 (antes: ${antes})`, [`El medidor de ${mon} pasó de "${antes}" a "${t.medidor_zona}": ${f0(num(t.medidor))}/100.`,
            t.m_sube_365 === null ? 'Todavía no hay casos suficientes en esta zona.' : `Cuando estuvo en esta zona, 12 meses después ${mon} estaba más arriba el ${t.m_sube_365}% de las veces (mediana ${t.m_mediana_365 > 0 ? '+' : ''}${t.m_mediana_365}%).`,
            'Para semanas o meses, no para el próximo trade.'], 'termometro'));
        // se viene movimiento fuerte (modelo de arboles, como el aviso de Telegram: 40% o mas, no antes de 4 h)
        const mv = pick(rows, 'movimiento')[0];
        if (mv && mv.modelo_1h !== null && mv.modelo_1h !== undefined) {
          const p1 = num(mv.modelo_1h), bloque = Math.floor(Date.now() / (4 * 3600000));
          cambio(`mf:${mon}`, p1 >= 40, (antes) => { if (p1 >= 40) nueva(`mf:${mon}:${bloque}`, '⚡', `${mon}: se viene movimiento fuerte`,
            `${f0(p1)}% de chance en la próxima hora (lo normal ${f0(num(mv.modelo_base_1h))}%)`, [
              `El modelo de movimiento fuerte da ${f0(p1)}% de chance de que la próxima hora ${mon} se mueva más del doble de lo habitual (próximas 4 h: ${f0(num(mv.modelo_4h))}%).`,
              'Medido sin mirar el futuro: en el 10% de las horas que más marca, fue fuerte un 30–40% de las veces (una hora cualquiera, 11–12%).',
              'No dice para dónde: sirve para ajustar el tamaño o los stops, no la dirección.'], 'movimiento'); });
        }
        const lq = pick(rows, 'contexto').find((c) => c.clave === 'liq_reales');
        if (lq && lq.barrida) nueva(`lb:${lq.barrida}:${Math.floor(Date.now() / 3600000)}`, '💥', `Barrida de ${lq.barrida} en BTC`,
          `${f1(num(lq.barrida === 'longs' ? lq.longs_15m : lq.shorts_15m) / 1e6)} M USD en 15 min (OKX)`, [lq.detalle,
            `Última hora en OKX: longs ${f1(num(lq.longs_1h) / 1e6)} M · shorts ${f1(num(lq.shorts_1h) / 1e6)} M USD liquidados.`,
            'Son liquidaciones reales (no estimadas). No hay historia gratis para medir qué pasa después: tomalo como contexto.'], null);
        const fu = pick(rows, 'contexto').find((c) => c.clave === 'funding');
        if (fu && fu.f7 !== undefined && fu.f7 !== null) {
          const f7 = num(fu.f7), cl = f7 < 0 ? 'miedo' : f7 >= 0.0003 ? 'euforia' : 'normal';
          cambio(`fu:${mon}`, cl, () => { if (cl !== 'normal') nueva(`fu:${mon}:${cl}:${hoy}`, cl === 'miedo' ? '🟢' : '🔴', `Funding de ${mon} en ${cl}`,
            `promedio 7 días ${(f7 * 100).toFixed(4).replace('.', ',')}%`, [
              `El funding promedio de los últimos 7 días es ${(f7 * 100).toFixed(4).replace('.', ',')}% cada 8 h.`,
              cl === 'miedo' ? 'Negativo: los shorts pagan, hay miedo. Históricamente, a 1–3 meses BTC subió más de lo normal con funding negativo.'
                : 'Alto (0,03% o más): los longs pagan caro, hay euforia. Históricamente, a 1–3 meses BTC subió menos de lo normal.',
              'Ya está sumado al termómetro (±3 puntos).'], mon === 'BTC' ? 'termometro' : null); });
        }
        guardar(LE, est);
      },
      // con cada actualizacion de precios del plan: compras, liquidacion, ganancias y piramidado
      plan() {
        if (!PLAN_OK()) return;
        const hoy = new Date().toISOString().slice(0, 10);
        monedasPlan().forEach((m) => {
          const d = CMP.datos[m]; if (!d) return;
          // con BingX: cuando tu posicion crece se ejecuto una compra (y si baja, cerraste una parte); lo dice BingX
          const vivo = BX.ok ? (BX.posiciones || {})[m] : null;
          if (BX.ok) cambio(`bxq:${m}`, vivo ? +vivo.cantidad.toPrecision(8) : 0, (antes) => {
            const q = vivo ? vivo.cantidad : 0, dq = q - antes;
            if (Math.abs(dq) <= Math.max(antes, q) * 0.0005) return;
            if (dq > 0) nueva(`bx+:${m}:${Date.now()}`, '✅', `Se ejecutó una compra de ${m}`, `+${ar.format(',.4f')(dq)} ${m}`,
              [`Tu posición de ${m} en BingX pasó de ${ar.format(',.4f')(antes)} a ${ar.format(',.4f')(q)} ${m}${vivo ? `, con entrada ${fp(vivo.entrada)}` : ''}.`, 'Si tu plan lleva margen extra para esta compra, agregalo con ⊕ en BingX.'], 'posiciones');
            else nueva(`bx-:${m}:${Date.now()}`, '📤', q ? `Cerraste una parte de ${m}` : `Cerraste tu posición de ${m}`, `${ar.format(',.4f')(dq)} ${m}`,
              [`Tu posición de ${m} en BingX pasó de ${ar.format(',.4f')(antes)} a ${ar.format(',.4f')(q)} ${m}.`], 'posiciones');
          });
          comprasDe(m).forEach((c) => {
            const dist = (d.precio / c.precio - 1) * 100, hecha = cmpHecha(c, d);
            // "se acerca" (a 3% o menos): la primera vez que entra en la zona; despues, solo si salio de la zona y queda MAS
            // CERCA de la compra que nunca (al menos 0,3% mas abajo que lo mas bajo desde el aviso anterior, contando cada
            // precio en vivo, no solo el de la vuelta de 15 s: antes un minimo entre vueltas no se anotaba y el siguiente
            // rebote parecia un minimo nuevo).
            const id = c.deBingx && BX.ok ? `o${c.precio}` : c.n, zona = !hecha && dist <= 3, km = `cm:${m}:${id}`, sm = est[km];
            const avisar = () => { nueva(`cc:${m}:${id}:${Date.now()}`, '📌', `${m} se acerca a tu compra ${nCompra(c)}`, `a ${f1(dist)}% de ${fp(c.precio)}`,
              [`${m} está en ${fp(d.precio)}, a ${f1(dist)}% de tu compra ${nCompra(c)} en ${fp(c.precio)}.`, cargada(c) ? 'La orden límite ya está cargada.' : `Cargá la orden límite: precio ${fp(c.precio)}, valor de la orden ${f0(c.orden)} a ${reglas().apalancamiento || 5}x.`,
               ...(sm ? [`Nuevo mínimo: ${fp(d.precio)}, por debajo de ${fp(sm.min)} (lo más bajo desde el aviso anterior).`] : [])], 'compras');
              est[km] = { min: Math.min(d.precio, d.minVivo === undefined ? d.precio : d.minVivo), bp: d.bajo, fuera: false }; };
            if (!sm) cuando(`cc:${m}:${id}`, zona, avisar);
            else {
              // lo mas bajo desde el aviso: el precio de cada vuelta y, si el minimo del plan bajo, esa mecha
              const lo = Math.min(d.precio, d.minVivo === undefined ? d.precio : d.minVivo, d.bajo < sm.bp ? d.bajo : Infinity);
              if (!zona) sm.fuera = true;
              if (zona && sm.fuera && lo < sm.min * 0.997) avisar();
              else { sm.min = Math.min(sm.min, lo); sm.bp = Math.min(sm.bp, d.bajo); }
              est[`cc:${m}:${id}`] = zona ? 1 : 0;
            }
            if (!(c.deBingx && BX.ok)) cuando(`ch:${m}:${c.n}`, hecha, () => nueva(`ch:${m}:${c.n}`, '✅', `Se ejecutó tu compra ${nCompra(c)} de ${m}`, `${fp(c.precio)} · orden ${f0(c.orden)}`,
              [`${m} tocó ${fp(c.precio)}: tu orden de ${f0(c.orden)} USDT debería haberse ejecutado. Confirmalo en BingX.`, c.extra_agregado ? 'El margen extra ya lo tenías agregado.' : `Ahora agregá ${f0(c.extra)} USDT de margen (⊕ en la posición).`], 'posiciones'));
          });
          d.minVivo = d.precio;                                  // ya se uso: empieza de nuevo
          const e = planEstado(m, d);
          if (e.cantidad === undefined) return;
          cuando(`lq:${m}`, e.liquidacion && e.dist_liq < 10, () => nueva(`lq:${m}:${hoy}`, '⚠️', `${m}: liquidación a ${f1(e.dist_liq)}%`, `liquidación ${fp(e.liquidacion)}`,
            [`Tu posición de ${m} se liquida en ~${fp(e.liquidacion)} y el precio está en ${fp(d.precio)} (tendría que caer ${f1(e.dist_liq)}%).`, 'Si querés alejarla, agregá margen (⊕) en BingX. La liquidación exacta la muestra BingX.'], 'posiciones'));
          (e.ganancias || []).forEach((g) => cuando(`tp:${m}:${g.k}`, g.alcanzado, () => nueva(`tp:${m}:${g.k}`, '💰', `${m} llegó a tu toma de ganancias +${f0(g.k * reglas().ganancias.cada * 100)}%`,
            `${fp(g.precio)} · pasar ${ar.format(',.4f')(g.vender)} ${m}`, [`${m} llegó a ${fp(g.precio)}, +${f0(g.k * reglas().ganancias.cada * 100)}% sobre tu equilibrio.`, `Según tu plan: pasá ${ar.format(',.4f')(g.vender)} ${m} (~${f0(g.usdt)} USDT) a spot.`], 'posiciones')));
          if (e.piramidar) cuando(`pz:${m}`, e.piramidar.disponible && e.piramidar.sumar > 0, () => nueva(`pz:${m}:${hoy}`, '📈', `${m}: podés piramidar`, `sumar ~${f0(e.piramidar.sumar)} USDT de posición`,
            [`${m} pasó ${fp(e.piramidar.desde)}, 15% sobre tu equilibrio.`, `Podés sumar ${f0(e.piramidar.sumar)} USDT de posición (${ar.format(',.4f')(e.piramidar.monedas)} ${m}) sin plata nueva: sacás margen y abrís más long.`,
              `La liquidación quedaría en ${fp(e.piramidar.liq_nueva)} (tu límite: ${fp(e.piramidar.liq_max)}).`], 'posiciones'));
        });
        guardar(LE, est);
      },
    };
  })();

  // ---------- termometro de compra/venta (ciclo de BTC) ----------
  const TM_COL = ['var(--color-ok)', 'color-mix(in srgb, var(--color-ok) 55%, var(--color-fg-muted))',
    'color-mix(in srgb, var(--color-bad) 55%, var(--color-fg-muted))', 'var(--color-bad)'];
  (function tmInit() {
    const tab = document.getElementById('tm-tab'), pan = document.getElementById('tm-panel');
    const back = document.getElementById('tm-back');
    let cierre = null;
    const set = (open) => {
      clearTimeout(cierre);
      tab.setAttribute('aria-expanded', String(open)); document.documentElement.style.overflow = open ? 'hidden' : '';
      if (open) {
        pan.hidden = false; back.hidden = false; abFoco(pan, true);
        requestAnimationFrame(() => requestAnimationFrame(() => { pan.classList.add('on'); back.classList.add('on'); }));
      } else {
        if (pan.classList.contains('on')) abFoco(pan, false);
        pan.classList.remove('on'); back.classList.remove('on');
        cierre = setTimeout(() => { pan.hidden = true; back.hidden = true; }, matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 320);
      }
    };
    tab.addEventListener('click', () => set(!pan.classList.contains('on')));
    ['tm-x', 'tm-back'].forEach((id) => document.getElementById(id).addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); set(false); }));
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') set(false); });
  })();
  // etiquetas de las lineas de precio sin pisarse: el precio en vivo (y su cuenta regresiva debajo) y despues cada linea en
  // el orden en que se dibuja (soporte y resistencia, tu plan, opciones, objetivos). La que choca con una ya puesta pierde
  // la etiqueta del eje y el titulo, la linea se sigue viendo
  let ordenRaf = 0;
  function ordenarEtiquetas() {
    cancelAnimationFrame(ordenRaf);
    ordenRaf = requestAnimationFrame(() => {
      if (!G.c || !G.plines || !G.plines.length) return;
      const dd = G.c.data(), ult = dd.length ? dd[dd.length - 1] : null, alto = 18, ocup = [];
      const yv = ult && ult.close !== undefined ? G.c.priceToCoordinate(ult.close) : null;
      if (yv !== null) ocup.push(yv, yv + alto);              // precio y cuenta regresiva
      G.plines.forEach((pl) => {
        if (!pl._v) return;
        const y = G.c.priceToCoordinate(pl.options().price);
        const choca = y !== null && ocup.some((o) => Math.abs(o - y) < alto);
        if (!choca && y !== null) ocup.push(y);
        if (pl.options().axisLabelVisible === choca) pl.applyOptions({ axisLabelVisible: !choca, title: choca ? '' : pl._t });
      });
    });
  }
  // Fear & Greed Index: arco clasico de 5 colores y aguja
  function fngGauge(v, clase, ayer) {
    const NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 220 168'); svg.setAttribute('class', 'ab-fng'); svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `Fear & Greed Index ${v}, ${clase}`);
    const cx = 110, cy = 100, r = 86, pt = (val, rr) => { const a = Math.PI * (1 - val / 100); return [cx + rr * Math.cos(a), cy - rr * Math.sin(a)]; };
    const arc = (a, b, col) => { const [x1, y1] = pt(a, r), [x2, y2] = pt(b, r), p = document.createElementNS(NS, 'path');
      p.setAttribute('d', `M${x1},${y1} A${r},${r} 0 0 1 ${x2},${y2}`); p.setAttribute('fill', 'none'); p.setAttribute('stroke', col);
      p.setAttribute('stroke-width', '18'); svg.append(p); };
    [[0, 25, '#e5484d'], [25.6, 45, '#f5793a'], [45.6, 55, '#f5c84c'], [55.6, 75, '#9bd35a'], [75.6, 100, '#30a46c']].forEach(([a, b, c]) => arc(a, b, c));
    const [nx, ny] = pt(Math.max(0, Math.min(100, v)), r - 22), nd = document.createElementNS(NS, 'line');
    nd.setAttribute('x1', cx); nd.setAttribute('y1', cy); nd.setAttribute('x2', nx); nd.setAttribute('y2', ny);
    nd.setAttribute('stroke', 'currentColor'); nd.setAttribute('stroke-width', '4'); nd.setAttribute('stroke-linecap', 'round'); svg.append(nd);
    const hub = document.createElementNS(NS, 'circle'); hub.setAttribute('cx', cx); hub.setAttribute('cy', cy); hub.setAttribute('r', '7'); hub.setAttribute('fill', 'currentColor'); svg.append(hub);
    const tx = (x, y, s, w, txt, fill) => { const e = document.createElementNS(NS, 'text'); e.setAttribute('x', x); e.setAttribute('y', y); e.setAttribute('text-anchor', 'middle');
      e.setAttribute('font-size', s); e.setAttribute('font-weight', w); e.setAttribute('fill', fill || 'currentColor'); e.textContent = txt; svg.append(e); };
    tx(cx, cy + 42, 30, 650, String(v)); tx(cx, cy + 62, 13, 600, clase);
    tx(24, cy + 20, 10, 400, '0', 'var(--color-fg-muted)'); tx(196, cy + 20, 10, 400, '100', 'var(--color-fg-muted)');
    const box = el('div'); box.style.display = 'grid'; box.style.gap = '2px'; box.style.color = 'var(--ink)'; box.append(svg);
    if (ayer !== null && ayer !== undefined && Number(ayer) !== v) box.append(el('p', 'ab-note', `Ayer: ${ayer}`));
    return box;
  }
  // ciclo de 4 años: fase del año, maximos y pisos de cada ciclo, y la regla de Fear & Greed Index segun la fase
  function reglaFng(t) {
    const R = t.reglas || {}, txt = (r) => `12 meses después BTC estuvo más arriba el ${r.sube_365}% de las veces (mediana ${r.mediana_365 > 0 ? '+' : ''}${r.mediana_365}%)`;
    const call = (col, s) => { const p = el('p', 'ab-tm-call', s); p.style.setProperty('--tm-col2', col); return p; };
    if (t.regla === 'miedo_bajista' && R.miedo_bajista) return [call('var(--color-ok)', `Extreme Fear en año bajista: el miedo de los demás es oportunidad. ${txt(R.miedo_bajista)}; antes llegó a caer ${R.miedo_bajista.caida_mediana}% (mediana): conviene comprar de a partes.`)];
    if (t.regla === 'codicia_alcista3' && R.codicia_alcista3) return [call('var(--color-bad)', `Extreme Greed en el 3er año alcista: demasiada codicia, aviso de venta. ${txt(R.codicia_alcista3)}.`)];
    return [];
  }
  function drawTermometro(rows) {
    const tab = document.getElementById('tm-tab'), body = document.getElementById('tm-body');
    const t = pick(rows, 'termometro')[0];
    tab.hidden = !t; document.documentElement.classList.toggle('ab-tm-on', !!t);   // la pagina le deja lugar (no tapa las tarjetas)
    if (!t) { document.getElementById('tm-panel').hidden = true; document.getElementById('tm-back').hidden = true; document.documentElement.style.overflow = ''; return; }
    const v = num(t.medidor), zi = Math.max(0, t.m_zonas.findIndex((z) => z[0] === t.medidor_zona)), col = TM_COL[zi];
    tab.style.setProperty('--tm-col', col); document.getElementById('tm-panel').style.setProperty('--tm-col', col);
    const dot = document.getElementById('tm-dot');
    dot.style.left = `${v}%`; dot.style.bottom = '';   // fila horizontal dentro de la hoja
    document.getElementById('tm-num').textContent = f0(v);
    document.getElementById('tm-zona').textContent = t.medidor_zona;
    const mon = t.moneda || 'BTC';
    document.getElementById('tm-kick').textContent = mon === 'BTC' ? 'Ciclo de BTC · semanas o meses' : `${mon} · su precio frente a su historia y el ciclo de BTC · semanas o meses`;
    body.replaceChildren();
    const big = el('div', 'ab-tm-big'); big.append(el('b', '', f0(v)), el('span', 'ab-note', '/ 100'), el('span', 'ab-tm-zona', t.medidor_zona));
    const sc = el('div', 'ab-tm-scale'); sc.style.gridTemplateColumns = `repeat(${t.m_zonas.length}, minmax(0, 1fr))`;
    t.m_zonas.forEach((z, i) => { const c = el('div'); const bar = el('i', i === zi ? 'on' : ''); bar.style.background = TM_COL[i]; c.append(bar, el('span', '', z[0])); sc.append(c); });
    const pasado = el('p', 'ab-hero-sub'), pm = (x) => `${x > 0 ? '+' : ''}${x}%`;
    pasado.textContent = t.m_sube_365 === null ? 'Todavía no hay suficientes casos en esta zona para medir qué pasó después.'
      : `Cuando estuvo en esta zona (2019–2026), 12 meses después BTC estaba más arriba el ${t.m_sube_365}% de las veces (mediana ${pm(t.m_mediana_365)}); 6 meses después, el ${t.m_sube_180}% (mediana ${pm(t.m_mediana_180)}).`;
    const FASE = { bajista: (a) => (a >= 60 ? 'final del año bajista: en esta parte del ciclo suele formarse el piso' : 'año bajista: el miedo todavía puede llevar el precio más abajo'),
      'alcista 1': () => '1er año alcista: recuperación después del piso', 'alcista 2': () => '2º año alcista: suele ser el tramo más fuerte',
      'alcista 3': (a) => (a >= 60 ? 'final del 3er año alcista: en esta parte del ciclo suele formarse el techo' : '3er año alcista: la euforia se acerca al techo del ciclo') };
    const caro = (p) => (p >= 50 ? `más caro que el ${f0(p)}% de la historia` : `más barato que el ${f0(100 - p)}% de la historia`);
    const comp = el('ul', 'ab-tm-list');
    const li = (txt, sub) => { const x = el('li', '', txt); if (sub) x.append(' ', el('em', '', sub)); comp.append(x); };
    li(`Barato o caro (la mitad del medidor: cuanto más barato, más compra): ${f0(num(t.temp))}/100, ${t.zona.toLowerCase()}.`);
    if (t.wma200 !== null && t.wma200 !== undefined) li(`  · Precio vs media de 200 semanas (${fp(num(t.wma200))}): ${sg(num(t.sobre_wma), 1)}.`, caro(num(t.p_wma200)) + '.');
    li(`  · Caída desde el máximo histórico (${fp(num(t.ath))}): ${sg(num(t.caida_ath), 1)}.`, num(t.p_dd_ath) >= 50 ? `el ${f0(num(t.p_dd_ath))}% del tiempo estuvo todavía más lejos del máximo.` : `solo el ${f0(num(t.p_dd_ath))}% del tiempo estuvo tan lejos del máximo.`);
    li(`  · Último año: ${sg(num(t.ret_anual), 1)}.`, caro(num(t.p_ret365)) + '.');
    if (t.mvrv !== null && t.mvrv !== undefined) li(`  · MVRV: ${f2(num(t.mvrv))} (precio contra el costo promedio de todos los BTC, ${fp(num(t.precio_realizado))}; debajo de 1, en pérdida).`, caro(num(t.p_mvrv)) + '.');
    if (t.puell !== null && t.puell !== undefined) li(`  · Puell: ${f2(num(t.puell))} (lo que cobran los mineros por día contra su promedio del año).`, caro(num(t.p_puell)) + '.');
    if (t.funding7 !== null && t.funding7 !== undefined) {
      const fa = num(t.funding_ajuste), fv = `${num(t.funding7) > 0 ? '+' : ''}${num(t.funding7).toFixed(4).replace('.', ',')}% cada 8 h`;
      li(`Funding promedio 7 días: ${fv}.`, fa > 0 ? 'negativo (miedo, los shorts pagan): baja el medidor 3 puntos, hacia compra.'
        : fa < 0 ? 'alto (euforia, los longs pagan caro): sube el medidor 3 puntos, hacia venta.' : 'normal: no mueve el medidor.');
    }
    // contexto de corto plazo: se muestra, pero no entra en el termometro (no anticipo la direccion de forma pareja)
    const ctxL = el('ul', 'ab-tm-list'), li2 = (txt) => ctxL.append(el('li', '', txt));
    const fg = pick(rows, 'contexto').find((c) => c.clave === 'miedo_codicia');
    const nots = pick(rows, 'noticia').filter((n) => num(n.impacto) >= 2 && Date.now() - n.t <= 6 * 3600000);
    if (nots.length) { const a = nots.filter((n) => n.sesgo === 'alcista').length, b = nots.filter((n) => n.sesgo === 'bajista').length;
      li2(`Noticias de peso (6 h): ${a} a favor de suba, ${b} a favor de baja${nots.some((n) => n.tema === 'Hackeo de exchange') ? ' — ⚠ hackeo a un exchange grande' : ''}.`); }
    const mv = pick(rows, 'movimiento')[0];
    if (mv && mv.modelo_1h !== undefined && mv.modelo_1h !== null) li2(`Chance de movimiento fuerte en 4 h: ${f0(num(mv.modelo_4h))}% (lo normal ${f0(num(mv.modelo_base_4h))}%).`);
    const rs = pick(rows, 'resumen')[0];
    if (rs && rs.rating_1d !== undefined) li2(`Sesgo técnico diario: ${num(rs.rating_1d) > 0.1 ? 'compra' : num(rs.rating_1d) < -0.1 ? 'venta' : 'neutral'} (${ar.format('+.2f')(num(rs.rating_1d))}).`);
    const pis = pick(rows, 'piso')[0], pisoEls = [];
    if (pis) {
      const g = el('div', 'ab-piso');
      pis.niveles.forEach(([conf, v]) => { const c = el('div'); c.append(el('small', '', `${conf}%`), el('b', '', fp(num(v))), el('small', '', `${sg((num(v) / num(pis.precio) - 1) * 100, 0)}`)); g.append(c); });
      pisoEls.push(el('p', 'ab-tm-sec', 'Mínimo probable en 6 meses'), el('p', 'ab-hero-sub', `Con cada confianza, ${mon} no baja de ese precio en los próximos 6 meses (volatilidad de un año: ${f0(num(pis.vol))}%). Sirve para elegir el apalancamiento: tu liquidación debería quedar debajo del de 90–95%.`), g);
      const ant = pis.anteriores || [];
      if (ant.length) {
        const ch = el('div', 'ab-ant');
        ant.forEach(([y, fz, v]) => { const x = el('span', fz === 'bajista' ? 'baj' : '', `${y} ${fz === 'bajista' ? 'bajista' : fz.replace('alcista ', 'alc. ')} ${sg(num(v), 0)}`); x.title = `Desde esta fecha de ${y}: mínimo de los 6 meses siguientes`; ch.append(x); });
        const bj = ant.filter((a) => a[1] === 'bajista').map((a) => num(a[2]));
        const txt = bj.length ? `En los años bajistas anteriores, desde esta misma fecha cayó entre ${f0(Math.abs(Math.max(...bj)))}% y ${f0(Math.abs(Math.min(...bj)))}% en los 6 meses siguientes (hoy serían ${fp(num(pis.precio) * (1 + Math.max(...bj) / 100))} a ${fp(num(pis.precio) * (1 + Math.min(...bj) / 100))}). No entra en las probabilidades de arriba: separar por año del ciclo o por mes no mejoró la medición.` : '';
        pisoEls.push(el('p', 'ab-tm-sec', 'Desde esta fecha en años anteriores'), ch, ...(txt ? [el('p', 'ab-hero-sub', txt)] : []));
      }
    }
    const escala = el('p', 'ab-note', 'Escala: 0 = el mejor momento para comprar · 100 = para vender. Mira el ciclo (semanas o meses), no la próxima hora.');
    body.append(big, escala, sc, pasado, ...pisoEls, el('p', 'ab-tm-sec', 'Qué lo forma'), comp,
      el('p', 'ab-tm-sec', 'Momento del ciclo (la otra mitad)'), el('p', 'ab-hero-sub', `${t.año}, ${(FASE[t.fase] || (() => t.fase))(t.avance)}.`),
      ...reglaFng(t),
      ...(fg ? [el('p', 'ab-tm-sec', 'Fear & Greed Index'), fngGauge(num(fg.fng), fg.fng_clase || String(fg.valor).split(' · ')[1] || '', fg.fng_ayer)] : []),
      el('p', 'ab-tm-sec', 'Corto plazo (no entra en el termómetro)'), ctxL,
      el('p', 'ab-foot', (mon === 'BTC' ? '' : `${mon}: mismo medidor que BTC, con su propia historia (desde ${mon === 'XRP' ? '2017' : '2020'}) y el ciclo de 4 años de BTC. `) + 'Lógica inversa: cuando está barato y el ciclo está en su piso, comprar de a poco; cuando está caro y en el techo del ciclo, vender de a poco.'));
  }
  function drawQuePasa(rows, s) {
    const box = document.getElementById('que-pasa');
    const price = num(s.precio), mov = pick(rows, 'movimiento')[0];
    const c5 = pick(rows, 'vela', '5m').sort((a, b) => num(a.t) - num(b.t)), c1h = pick(rows, 'vela', '1h').sort((a, b) => num(a.t) - num(b.t));
    const back = (cs, k) => (cs.length > k ? num(cs[cs.length - 1 - k].c) : null);
    const chg = (ref) => (ref ? (price / ref - 1) * 100 : null);
    const normal = mov ? Math.max(0.15, num(mov.normal_pct)) : 0.6;
    const win = [
      { h: 1, txt: 'la última hora', ch: chg(back(c5, 12)), th: Math.max(2 * normal, 0.8), oi: 'oi_1h', fl: 'flujo_1 h' },
      { h: 4, txt: 'las últimas 4 horas', ch: chg(back(c1h, 4)), th: Math.max(4 * normal, 1.8), oi: 'oi_4h', fl: 'flujo_4 h' },
      { h: 24, txt: 'las últimas 24 horas', ch: num(s.cambio_24h), th: 5, oi: 'oi_24h', fl: 'flujo_4 h' },
    ].filter((w) => w.ch !== null && Number.isFinite(w.ch));
    const news = pick(rows, 'noticia').map((n) => ({ ...n, t: num(n.t) })).sort((a, b) => b.t - a.t);
    const etf = pick(rows, 'etf').sort((a, b) => (a.fecha < b.fecha ? -1 : 1));
    if (!win.length) { box.hidden = true; return; }
    box.hidden = false;
    const w = win.reduce((a, b) => (Math.abs(b.ch) / b.th > Math.abs(a.ch) / a.th ? b : a));
    const strong = Math.abs(w.ch) >= w.th, dir = w.ch >= 0 ? 1 : -1;
    const col = dir > 0 ? 'var(--color-ok)' : 'var(--color-bad)';
    box.classList.toggle('ab-qp-on', strong);
    box.style.setProperty('--qp-col', strong ? col : 'var(--color-fg-muted)');
    document.getElementById('qp-k').textContent = strong ? (dir > 0 ? 'ya subió fuerte' : 'ya cayó fuerte') : '';
    const big = document.getElementById('qp-big'); big.replaceChildren();
    const ctx = (k) => pick(rows, 'contexto').find((c) => c.clave === k);
    // lo que coincide con el movimiento: cada factor dice si empuja para el mismo lado (si) o no
    const F = [];
    // liquidaciones reales (OKX): una barrida se muestra siempre, haya o no movimiento fuerte
    const lq = ctx('liq_reales');
    if (lq && lq.barrida) F.push({ si: (lq.barrida === 'longs') === (dir < 0), siempre: true, ic: '💥', lbl: `una barrida de ${lq.barrida}`,
      txt: `Liquidaciones reales: ${lq.detalle}`, sub: `Última hora en OKX: longs ${f1(num(lq.longs_1h) / 1e6)} M · shorts ${f1(num(lq.shorts_1h) / 1e6)} M USD.` });
    const oi = ctx(w.oi), dOi = oi ? num(oi.d_oi) : null;
    if (dOi !== null && dOi !== undefined) {
      const down = dir < 0;
      if (down && dOi <= -1.5) F.push({ si: true, ic: '⚡', lbl: 'liquidaciones de longs', txt: `Se liquidaron o cerraron posiciones en largo: el interés abierto de futuros cayó ${f1(Math.abs(dOi))}%. Las ventas forzadas aceleran la baja (cascada de liquidaciones).` });
      else if (down && dOi >= 1) F.push({ si: true, ic: '⤓', lbl: 'shorts nuevos', txt: `Entraron apuestas nuevas a la baja: el interés abierto subió ${f1(dOi)}% mientras caía el precio.` });
      else if (!down && dOi <= -1.5) F.push({ si: true, ic: '⚡', lbl: 'un short squeeze', txt: `Se liquidaron o cerraron posiciones en corto (interés abierto −${f1(Math.abs(dOi))}%): para cerrarlas tienen que comprar, y eso empuja la suba.` });
      else if (!down && dOi >= 1) F.push({ si: true, ic: '⤒', lbl: 'dinero nuevo en futuros', txt: `Entra dinero nuevo apalancado en largo: el interés abierto subió ${f1(dOi)}%.` });
      else F.push({ si: false, ic: '≈', txt: `El apalancamiento casi no cambió (interés abierto ${sg(dOi, 1)}): el movimiento viene más de compras y ventas al contado que de futuros.` });
    }
    const fl = ctx(w.fl), r = fl ? num(fl.ratio) : null;
    if (r !== null && r !== undefined) {
      if (r >= 1.15 || r <= 0.87) {
        const buyers = r >= 1.15, si = buyers === dir > 0;
        F.push({ si, ic: buyers ? '▲' : '▼', lbl: si ? (buyers ? 'compradores agresivos' : 'vendedores agresivos') : null,
          txt: buyers ? `Dominaron los compradores a mercado: ${ar.format(',.2f')(r)} compras por cada venta.` : `Dominaron los vendedores a mercado: ${ar.format(',.2f')(1 / r)} ventas por cada compra.` });
      } else F.push({ si: false, ic: '≈', txt: `Compras y ventas a mercado parejas (${ar.format(',.2f')(r)}).` });
    }
    const pr = ctx('prima_coinbase'), pv = pr ? num(pr.prima) : null;
    if (pv !== null && pv !== undefined && Math.abs(pv) >= 0.05) {
      const si = (pv > 0) === (dir > 0);
      F.push({ si, ic: '$', lbl: si ? (pv > 0 ? 'compras desde EE.UU.' : 'ventas desde EE.UU.') : null,
        txt: pv > 0 ? `En EE.UU. (Coinbase) pagan ${ar.format(',.2f')(pv)}% más que afuera: están comprando fondos y empresas de EE.UU.`
          : `En EE.UU. (Coinbase) pagan ${ar.format(',.2f')(Math.abs(pv))}% menos que afuera: están vendiendo desde EE.UU.` });
    }
    if (etf.length) {
      const last = etf[etf.length - 1], v = num(last.neto), s5 = etf.slice(-5).reduce((a, x) => a + num(x.neto), 0);
      const d = String(last.fecha).split('-'), si = Math.abs(v) >= 150 && (v > 0) === (dir > 0);
      F.push({ si, ic: 'E', lbl: si ? (v > 0 ? 'entradas a los ETF' : 'salidas de los ETF') : null,
        txt: `ETF de BTC en EE.UU.: ${v >= 0 ? 'entraron' : 'salieron'} ${f0(Math.abs(v))} M USD el ${d[2]}/${d[1]} (en 5 días: ${s5 >= 0 ? '+' : '−'}${f0(Math.abs(s5))} M).`,
        sub: 'Se publican al día siguiente del cierre en EE.UU. (Farside Investors).' });
    }
    const fg = ctx('miedo_codicia'), fv = fg ? num(fg.fng) : null;
    if (fv !== null && fv !== undefined) {
      F.push({ si: false, ic: '◔', txt: `Fear & Greed Index: ${fg.valor}${fg.fng_ayer !== null && fg.fng_ayer !== undefined && num(fg.fng_ayer) !== fv ? ` (ayer ${fg.fng_ayer})` : ''}.` });
    }
    // la decision de tasas de la Fed tiene su propia linea (abajo): aca no se repite
    const salio = eventosAgrupados(rows).map((g) => ({ ...g, items: g.items.filter((x) => !(/interest rate decision|fomc decision|interest rate fomc/i.test(x.original || '') && x.actual !== null && x.actual !== undefined)) }))
      .map((g) => ({ ...g, nombres: [...new Set(g.items.map((x) => x.titulo))] })).filter((g) => g.items.length && g.t <= Date.now() && g.t >= Date.now() - (w.h + 1) * 3600000);
    if (salio.length) {
      const g = salio[salio.length - 1], e = g.items[0];
      const det = e.actual !== null && e.actual !== undefined ? ` (salió ${e.actual}${e.previsto !== null && e.previsto !== undefined ? `, se esperaba ${e.previsto}` : ''})` : '';
      F.unshift({ si: true, ic: '📅', lbl: `el dato de ${g.nombres[0].toLowerCase()}`, txt: `Salió un dato fuerte de EE.UU.: ${g.nombres.slice(0, 3).join(', ')}${det}, a las ${horaAR(g.t)} h. En la hora en que salen datos así, BTC se mueve 1,7 veces lo normal.` });
    }
    // noticias de esas horas (o de las ultimas 24 h si esta tranquilo), las de temas grandes primero
    const desde = Date.now() - (strong ? (w.h + 2) : 24) * 3600000;
    const rel = news.filter((n) => n.t >= desde).sort((a, b) => TEMA_ORDEN.indexOf(a.tema) - TEMA_ORDEN.indexOf(b.tema) || b.t - a.t).slice(0, strong ? 5 : 4);
    const hot = rel.filter((n) => n.tema !== 'Cripto');
    if (strong) {
      big.append(`${MON()} `, el('span', 'ab-qp-mv', `${dir > 0 ? 'sube' : 'cae'} ${f1(Math.abs(w.ch))}%`), ` en ${w.txt}`);
      const lbls = F.filter((f) => f.si && f.lbl).map((f) => f.lbl);
      // las noticias de liquidaciones repiten lo que ya dice el interes abierto
      const temas = [...new Set(hot.map((n) => n.tema.toLowerCase()))].slice(0, 2);
      const parts = lbls.slice(0, 4).concat(temas.map((t) => `noticias de ${t}`));
      const veces = ar.format(',.1f')(Math.abs(w.ch) / (w.th / (w.h === 1 ? 2 : w.h === 4 ? 4 : 1)));
      document.getElementById('qp-sum').textContent = (w.h === 24 ? 'Es un movimiento grande para un día. ' : `Es ${veces} veces lo que se mueve normalmente. `)
        + (parts.length ? `Coincide con ${parts.length > 1 ? parts.slice(0, -1).join(', ') + ' y ' + parts[parts.length - 1] : parts[0]}.`
          : 'No hay una causa clara en los datos: puede ser una orden grande o una reacción técnica.');
    } else {
      const w1 = win[0];
      big.append(`Sin movimientos fuertes: ${MON()} `, el('span', 'ab-qp-mv', sg(w1.ch, 1)), ` en ${w1.txt}`);
      document.getElementById('qp-sum').textContent = 'Se mueve dentro de lo normal. Cuando haya una suba o baja fuerte, acá aparece qué la explica.';
    }
    const ul = document.getElementById('qp-fact'); ul.replaceChildren();
    const fed = decisionFed(rows);
    if (fed) {
      const li = el('li', fed.sesgo !== 'neutral' ? 'ab-qp-si' : ''), t = el('span', '', fed.txt);
      t.append(el('small', '', `Decisión de las ${horaAR(fed.t)} h, ${diaAR(fed.t)}.`));
      li.append(el('i', '', '🏦'), t);
      if (fed.sesgo !== 'neutral') li.style.setProperty('--qp-col', fed.sesgo === 'alcista' ? 'var(--color-ok)' : 'var(--color-bad)');
      ul.append(li);
    }
    (strong ? F : F.filter((f) => f.ic === 'E' || f.ic === '$' || f.siempre)).forEach((f) => {
      const li = el('li', f.si ? 'ab-qp-si' : ''), t = el('span', '', f.txt);
      if (f.sub) t.append(el('small', '', f.sub));
      li.append(el('i', '', f.ic), t); ul.append(li);
    });
    const cl = climaNoticias(rows), cle = document.getElementById('qp-clima'); cle.replaceChildren();
    cle.hidden = !news.length;
    if (news.length) {
      const b = el('b', 'ab-qp-s ab-' + cl.est, cl.est === 'alcista' ? '▲ a favor de la suba' : cl.est === 'bajista' ? '▼ a favor de la baja' : '◆ neutral');
      cle.append('Clima de las noticias (6 h):', b,
        el('small', '', `${cl.buenas} buenas${cl.tb ? ` (${cl.tb})` : ''} · ${cl.malas} malas${cl.tm ? ` (${cl.tm})` : ''} · lectura automática de los titulares`));
    }
    const nb = document.getElementById('qp-news'); nb.replaceChildren();
    document.getElementById('qp-news-t').textContent = strong ? `Noticias de esas horas` : 'Noticias de las últimas 24 h';
    document.getElementById('qp-news-n').textContent = rel.length ? `${rel.length}` : '';
    if (!rel.length) nb.append(el('p', 'ab-note', news.length ? 'Sin noticias relevantes en esas horas.' : 'No se pudieron leer las noticias ahora.'));
    rel.forEach((n) => {
      const a = el('a', 'ab-qp-n'); a.href = n.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
      const meta = el('span');
      if (n.sesgo === 'alcista' || n.sesgo === 'bajista') meta.append(el('i', 'ab-qp-s ab-' + n.sesgo, n.sesgo === 'alcista' ? `▲ buena para ${MON()}` : `▼ mala para ${MON()}`));
      meta.append(el('i', 'ab-qp-tag' + (n.tema !== 'Cripto' ? ' ab-qp-hot' : ''), n.tema), `${n.fuente}${n.medios > 1 ? ` y ${n.medios - 1} medio${n.medios > 2 ? 's' : ''} más` : ''} · ${haceTxt(n.t)}`);
      a.append(el('b', '', n.titulo), meta); nb.append(a);
    });
    document.getElementById('qp-res').textContent = big.textContent;
    document.getElementById('qp-note').textContent = '';
  }

  // ---------- calendario economico de EE.UU. (importancia alta) ----------
  // Medido 2021-2026 con BTC: la hora en la que sale uno de estos datos se movio 1,6 a 1,8 veces lo normal y fue un
  // movimiento fuerte 23-29% de las veces (10-12% en las demas horas). No dice para donde.
  const horaAR = (t) => new Date(t).toLocaleTimeString('es-AR', { ...tz, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  const diaAR = (t) => {
    const f = (x) => new Date(x).toLocaleDateString('es-AR', { ...tz, day: '2-digit', month: '2-digit' });
    const hoy = f(Date.now()), man = f(Date.now() + 86400000);
    return f(t) === hoy ? 'hoy' : f(t) === man ? 'mañana' : `el ${f(t)}`;
  };
  const faltaTxt = (ms) => { const m = Math.max(0, Math.round(ms / 60000)); return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min`; };
  // decision de tasas de la Fed: lo que salio contra lo que se esperaba. Mas baja de lo previsto: bueno para BTC;
  // mas alta: malo; igual: ya estaba descontado
  function decisionFed(rows, horas = 48) {
    const now = Date.now();
    const e = pick(rows, 'evento').filter((x) => /interest rate decision|fomc decision|interest rate fomc/i.test(x.original || '') && x.actual !== null && x.actual !== undefined
      && now - num(x.t) <= horas * 3600000 && num(x.t) <= now).sort((a, b) => num(b.t) - num(a.t))[0];
    if (!e) return null;
    const act = num(e.actual), prev = e.previsto === null || e.previsto === undefined ? null : num(e.previsto), ant = e.anterior === null || e.anterior === undefined ? null : num(e.anterior);
    const mov = ant === null ? '' : act < ant ? 'bajó' : act > ant ? 'subió' : 'mantuvo';
    const sesgo = prev === null ? 'neutral' : act < prev ? 'alcista' : act > prev ? 'bajista' : 'neutral';
    const pc = (v) => `${ar.format(',.2f')(v)}%`;
    const txt = `La Fed ${mov ? mov + ' la tasa' : 'decidió la tasa'}: ${pc(act)}${prev !== null ? ` (se esperaba ${pc(prev)})` : ''}. `
      + (sesgo === 'alcista' ? 'Más baja de lo previsto: positivo para BTC.' : sesgo === 'bajista' ? 'Más alta de lo previsto: negativo para BTC.' : 'Como se esperaba: el mercado ya lo tenía descontado.');
    return { t: num(e.t), sesgo, txt };
  }
  /** Datos agrupados por hora: [{t, nombres, items}] */
  function eventosAgrupados(rows) {
    const g = new Map();
    pick(rows, 'evento').forEach((e) => { const t = num(e.t); if (!g.has(t)) g.set(t, []); g.get(t).push(e); });
    return [...g.entries()].sort((a, b) => a[0] - b[0]).map(([t, items]) => ({ t, items, nombres: [...new Set(items.map((e) => e.titulo))] }));
  }

  // ---------- calendario: lo que viene (solo lo futuro), en hora de Argentina ----------
  // Datos de EE.UU. de importancia alta (TradingView, via api/contexto) mas lo propio de las criptos, calculado:
  // vencimiento de opciones de Deribit (viernes 08:00 UTC; el ultimo del mes es el mensual, y en mar/jun/sep/dic el
  // trimestral, el mas grande) y cierres de vela semanal (lunes 00:00 UTC) y mensual. Lo que se movio BTC esas horas
  // es lo medido 2021-2026 (ver api/contexto.js y analisis_btc.py): no dice para donde.
  function eventosCripto(desde, hasta) {
    const out = [];
    for (let d = new Date(Date.UTC(new Date(desde).getUTCFullYear(), new Date(desde).getUTCMonth(), new Date(desde).getUTCDate())); d.getTime() <= hasta; d = new Date(d.getTime() + 864e5)) {
      const y = d.getUTCFullYear(), m = d.getUTCMonth(), dia = d.getUTCDate(), dow = d.getUTCDay();
      if (dow === 5) {
        const t = Date.UTC(y, m, dia, 8), ultimo = dia + 7 > new Date(Date.UTC(y, m + 1, 0)).getUTCDate(), trim = ultimo && m % 3 === 2;
        out.push({ t, titulo: trim ? 'Vencen opciones de BTC: trimestral' : ultimo ? 'Vencen opciones de BTC: mensual' : 'Vencen opciones de BTC (semanal)',
          tag: 'cripto', nota: trim || ultimo ? 'Deribit. El vencimiento grande: el precio suele quedar cerca del "dolor máximo" en los días previos.' : 'Deribit, el vencimiento chico de cada viernes.', fuerte: trim });
      }
      if (dow === 1) out.push({ t: Date.UTC(y, m, dia), titulo: 'Cierra la vela semanal', tag: 'cripto', nota: 'Las del gráfico semanal y sus medias se actualizan.' });
      if (dia === 1) out.push({ t: Date.UTC(y, m, 1), titulo: 'Cierra la vela mensual', tag: 'cripto', nota: 'Cambia la vela del gráfico mensual.' });
    }
    return out.filter((e) => e.t > desde && e.t <= hasta);
  }
  function drawCalendario(rows) {
    const now = Date.now(), FED = /interest rate decision|fomc decision|interest rate fomc/i;
    const eeuu = pick(rows, 'evento').filter((e) => num(e.t) > now).map((e) => {
      const fed = FED.test(e.original || ''), pv = e.previsto, an = e.anterior;
      const extra = [pv !== null && pv !== undefined && pv !== '' ? `se espera ${pv}` : '', an !== null && an !== undefined && an !== '' ? `antes ${an}` : ''].filter(Boolean).join(' · ');
      return { t: num(e.t), titulo: e.titulo, tag: 'EE.UU.', fuerte: fed,
        nota: (extra ? `${extra}. ` : '') + (fed ? 'La hora de la decisión BTC se movió ~3,2 veces lo normal, y más del doble el 78% de las veces.' : 'Esa hora BTC suele moverse 1,6–1,8 veces lo normal (fuerte 23–29% de las veces).') };
    });
    const hasta = eeuu.length ? Math.max(now + 7 * 864e5, ...eeuu.map((e) => e.t)) : now + 7 * 864e5;
    const todos = eeuu.concat(eventosCripto(now, hasta)).sort((a, b) => a.t - b.t);
    const box = document.getElementById('cal-list'), prox = document.getElementById('cal-prox');
    box.replaceChildren();
    if (!todos.length) { box.append(el('p', 'ab-note', 'Sin eventos en los próximos días.')); prox.textContent = ''; return; }
    const p0 = todos[0];
    prox.textContent = `próximo: ${p0.titulo.replace(/^Vencen opciones de BTC.*/, 'opciones')} en ${faltaTxt(p0.t - now)}`;
    const porDia = new Map();
    todos.forEach((e) => { const k = new Date(e.t).toLocaleDateString('es-AR', { ...tz, weekday: 'long', day: '2-digit', month: '2-digit' }); if (!porDia.has(k)) porDia.set(k, []); porDia.get(k).push(e); });
    porDia.forEach((evs, k) => {
      const d = el('div', 'ab-cal-dia'), dd = diaAR(evs[0].t);
      d.append(el('h3', '', dd === 'hoy' || dd === 'mañana' ? `${dd[0].toUpperCase()}${dd.slice(1)} · ${k}` : k[0].toUpperCase() + k.slice(1)));
      evs.forEach((e) => {
        const r = el('div', `ab-cal-ev${e.fuerte ? ' fuerte' : ''}`), tt = el('time', '', horaAR(e.t)); tt.dateTime = new Date(e.t).toISOString();
        const nm = el('span'); nm.append(el('b', '', e.titulo), el('span', 'ab-cal-tag', e.tag));
        r.append(tt, nm, el('small', '', `${e.nota}${e.t - now < 864e5 ? ` Falta ${faltaTxt(e.t - now)}.` : ''}`));
        d.append(r);
      });
      box.append(d);
    });
  }

  // ---------- movimiento fuerte en la proxima hora ----------
  function drawMovimiento(rows) {
    const m = pick(rows, 'movimiento')[0], box = document.getElementById('movimiento');
    box.hidden = !m; if (!m) return;
    // Bollinger comprimidas (velas de 1 hora): suele venir una expansion en las 24 h siguientes (medido, ver compresion())
    const cp = pick(rows, 'compresion')[0], cl = document.getElementById('mov-comp');
    cl.hidden = !(cp && cp.comprimida);
    if (cp && cp.comprimida) {
      const sp = el('span'); cl.replaceChildren(el('i', '', '↔'), sp);
      const r24 = num(cp.rango_24h), r24t = r24 >= 100 ? f0(r24) : fp(r24);
      sp.append(el('b', '', 'Bollinger comprimidas'), `: en las próximas 24 h suele moverse ~${String(cp.expande).replace('.', ',')}× lo de las últimas 24 h (${r24t} USD). No dice para dónde.`,
        el('span', 'ab-comp-largo', ` Ancho entre el ${f0(Math.max(1, num(cp.percentil)))}% más angosto de 30 días (1 h). Medido en BTC 2021–2026: más del doble el ${f0(cp.mas_doble)}% de las veces (normal: ${f0(cp.mas_doble_normal)}%).`));
      cl.setAttribute('data-where', 'tabla=compresion');
    }
    // cuando suele moverse en las proximas 24 h (medido: ver perfilHoras en analisis.js)
    const hs = pick(rows, 'horas')[0], hb = document.getElementById('mov-horas');
    hb.hidden = !hs || hs.max_f - hs.min_f < 0.3;            // sin diferencias claras entre horas, no se muestra
    if (hs) {
      const x = (v) => `×${String(v).replace('.', ',')}`, bars = document.getElementById('mov-horas-b');
      bars.replaceChildren(...hs.proximas.map(([t, f], k) => { const i = el('i', `${f >= 1.25 ? 'alta' : ''}${k === 0 ? ' ahora' : ''}`.trim());
        i.style.height = `${Math.max(8, Math.min(100, f / 2 * 100))}%`; i.title = `${horaAR(t)} h: ${x(f)} de una hora típica`; return i; }));
      bars.setAttribute('aria-label', `Próximas 24 horas: lo más movido a las ${horaAR(hs.max_t)} h, lo más quieto a las ${horaAR(hs.min_t)} h`);
      document.getElementById('mov-horas-t').replaceChildren(el('b', '', 'Cuándo suele moverse'),
        `: en las próximas 24 h, lo más movido suele ser a las ${horaAR(hs.max_t)} h (${x(hs.max_f)} de una hora típica) y lo más quieto a las ${horaAR(hs.min_t)} h (${x(hs.min_f)}). Ahora: ${x(hs.ahora_f)}.`);
      hb.dataset.corto = `Cuándo suele moverse: más a las ${horaAR(hs.max_t)} h, menos a las ${horaAR(hs.min_t)} h`;
      ['0', '12', '23'].forEach((k) => { document.getElementById(`mov-horas-${k}`).textContent = `${horaAR(hs.proximas[+k][0])} h`; });
    }
    // con el modelo de arboles (BTC) la chance sale de ahi; si no hay modelo (ZEC), de la tabla
    const mod = m.modelo_1h !== null && m.modelo_1h !== undefined;
    const prob = mod ? num(m.modelo_1h) : num(m.prob_fuerte);
    const on = m.nivel === 'Se despertó' || prob >= (mod ? 30 : 35);
    box.classList.toggle('ab-mov-on', on);
    document.getElementById('mov-k').textContent = mod ? `${MON()} · vela de 1 h en curso · cierra a las ${horaAR(num(m.modelo_hasta))}\u00a0h` : MON();
    document.getElementById('mov-nivel').textContent = m.nivel;
    document.getElementById('mov-vol').textContent = `volatilidad ${f1(num(m.volatilidad))}× la habitual`;
    document.getElementById('mov-prob').textContent = `${f0(prob)}%`;
    document.getElementById('mov-base').textContent = mod
      ? `en una hora cualquiera: ${f0(num(m.modelo_base_1h))}% · próximas 4 h: ${f0(num(m.modelo_4h))}%`
      : `en una hora cualquiera: ${f0(num(m.prob_normal))}%`;
    const fu = (x) => (num(S.sum && S.sum.precio) >= 1000 ? f0(x) : ar.format(',.2f')(x));
    document.getElementById('mov-rango').textContent = `~${fu(num(m.esperado_usd))}`;
    document.getElementById('mov-normal').textContent = `USD de punta a punta · normal ~${fu(num(m.normal_usd))} (${f1(num(m.normal_pct))}%)`;
    // proximo dato fuerte de EE.UU.
    const dv = document.getElementById('mov-dato'), now = Date.now();
    const prox = eventosAgrupados(rows).find((g) => g.t > now - 15 * 60000);
    dv.hidden = !prox; dv.replaceChildren(); dv.classList.remove('ab-pronto');
    if (prox) {
      const falta = prox.t - now, pronto = falta <= 60 * 60000, lista = prox.nombres.slice(0, 3).join(', ');
      const t = el('span');
      if (falta <= 0) t.append(el('b', '', `Acaba de salir: ${lista}`), ` (${horaAR(prox.t)} h).`);
      else t.append(el('b', '', `${pronto ? 'En ' + faltaTxt(falta) : 'Próximo dato fuerte de EE.UU.'}: ${lista}`), ` — ${diaAR(prox.t)} a las ${horaAR(prox.t)} h${pronto ? '' : ` (en ${faltaTxt(falta)})`}.`);
      t.append(el('small', '', 'En la hora en que salen datos así, BTC se movió 1,7 veces lo normal y fue un movimiento fuerte 26% de las veces (11% en una hora cualquiera). Medido 2021–2026; no dice para dónde.'));
      dv.append(el('i', '', '📅'), t); dv.classList.toggle('ab-pronto', pronto);
      if (pronto) box.classList.add('ab-mov-on');
    }
    document.getElementById('mov-txt').textContent = mod
      ? `"Movimiento fuerte" = se mueve más del doble de lo habitual, para cualquier lado. La chance la calcula un modelo de árboles entrenado con BTC 2021–2026 (velas de 1 hora, volatilidad, volumen, medias, hora del día y datos de EE.UU.). Probado sin mirar el futuro: en las horas que marca como más peligrosas fue fuerte 35–37% de las veces (una hora cualquiera: 12%), y cuando marca 40% o más, 40–49%. No dice para dónde.`
      : `"Movimiento fuerte" = la próxima hora se mueve más del doble de lo normal. Probabilidades medidas con ${ACC_INFO[MON()] ? `velas de ${MON()} desde ${ACC_INFO[MON()][2]} (historia corta: tomalo con cuidado)` : `${MON()} 2021–2026`} según qué tan agitado está el mercado${ACC_INFO[MON()] ? '' : '; se mantuvieron iguales en 2025–26'}. Dice cuánto se puede mover, no para dónde.`;
  }

  // ---------- cabecera y precio ----------
  function drawHeader(rows, s) {
    root.querySelector('[data-field="hora_local"]').textContent = s.hora_local + ' h';
    const hour = Number(String(s.hora_local).slice(-5, -3));
    const next = [0, 8, 12, 16, 20].find((h) => h > hour);
    document.getElementById('next-run').textContent = window.abLive ? 'se reanaliza solo'
      : `próximo análisis ${String(next === undefined ? 0 : next).padStart(2, '0')}:00 h`;
    { const pe = root.querySelector('.ab-price'); if (!pe.querySelector('.ab-pd')) pe.replaceChildren(el('span', 'ab-pd'), el('small', '', 'USDT')); ponerPrecio(pe, fp(num(s.precio)), 0); }
    document.title = `${fp(num(s.precio))} · ${MON()}`;
    document.getElementById('moneda-lbl').textContent = MON();
    document.getElementById('ab-title').textContent = `Analista ${MON()}`;
    document.getElementById('graf-t').textContent = `Dónde está ${MON()}`;
    const put = (id, v, d) => { const e = document.getElementById(id); e.textContent = v === null ? '—' : sg(v, d);
      e.classList.toggle('ab-up-t', v > 0); e.classList.toggle('ab-down-t', v < 0); };
    put('c24', num(s.cambio_24h), 2); put('c7', num(s.cambio_7d), 2); put('c200', num(s.sma200d_dist), 1); put('e200d', num(s.ema200d_dist), 1);
    const fu = num(s.funding); document.getElementById('fund').textContent = fu === null ? '—' : (fu > 0 ? '+' : '') + ar.format(',.4f')(fu) + '%';

    const bars = pick(rows, 'vela', '1h').map((r) => ({ t: num(r.t), c: num(r.c) })).sort((a, b) => a.t - b.t).slice(-48);
    const svg = d3.select('#spark'); svg.selectAll('*').remove();
    const box = document.getElementById('spark'); const W = Math.max(200, box.clientWidth), H = 64;
    svg.attr('viewBox', `0 0 ${W} ${H}`);
    if (bars.length < 2) return;
    const x = d3.scaleLinear([0, bars.length - 1], [0, W]);
    const y = d3.scaleLinear(d3.extent(bars, (b) => b.c), [H - 4, 6]);
    const upDay = bars[bars.length - 1].c >= bars[0].c;
    const col = upDay ? 'var(--color-ok)' : 'var(--color-bad)';
    const gid = 'ab-spark-g';
    const g = svg.append('defs').append('linearGradient').attr('id', gid).attr('x1', 0).attr('x2', 0).attr('y1', 0).attr('y2', 1);
    [[0, .28], [.5, .08], [1, 0]].forEach(([o, a]) => g.append('stop').attr('offset', o).style('stop-color', col).style('stop-opacity', a));
    svg.append('path').attr('d', d3.area().x((b, i) => x(i)).y0(H).y1((b) => y(b.c))(bars)).style('fill', `url(#${gid})`);
    svg.append('path').attr('class', 'ab-spark-line').attr('pathLength', 1).style('stroke-dasharray', 1)
      .attr('d', d3.line().x((b, i) => x(i)).y((b) => y(b.c))(bars)).style('fill', 'none').style('stroke', col).style('stroke-width', 2).style('stroke-linecap', 'round');
    svg.append('circle').attr('cx', x(bars.length - 1)).attr('cy', y(bars[bars.length - 1].c)).attr('r', 3.5).style('fill', col);
  }

  // ---------- resaltar en el grafico lo que se senala en "que estas viendo" ----------
  // con el dedo: mantener apretado sin mover lo muestra mientras se sostiene; un toque corto lo deja marcado
  // hasta volver a tocarlo. Si el dedo se mueve (o el navegador toma el gesto para desplazar la pagina) no pasa nada
  let hold = null;
  function exHold(key, e) {
    hold = { key, x: e.clientX, y: e.clientY, t: Date.now(), on: false };
    hold.timer = setTimeout(() => { if (hold) { hold.on = true; focusEx(key); } }, 220);
  }
  const endHold = (tap) => {
    if (!hold) return;
    clearTimeout(hold.timer);
    if (hold.on) { exSinClick = Date.now(); focusEx(null); }    // se solto despues de mantener: vuelve a como estaba (y no marca)
    hold = null;
  };
  document.addEventListener('pointermove', (e) => {
    if (hold && !hold.on && Math.hypot(e.clientX - hold.x, e.clientY - hold.y) > 10) { clearTimeout(hold.timer); hold = null; }
  }, { passive: true });
  document.addEventListener('pointerup', () => endHold(true));
  document.addEventListener('pointercancel', () => endHold(false));

  // Marcados (clic o toque corto, tipo interruptor: pueden ser varios) mas la vista previa (mouse encima o dedo apretado):
  // eso queda encendido en el grafico y el resto se apaga
  let exSinClick = 0;
  S.sel = new Set(); S.hoverEx = null;
  function focusEx(key) { S.hoverEx = key; refocus(); }
  function toggleEx(key) { if (S.sel.has(key)) S.sel.delete(key); else S.sel.add(key); refocus(); }
  function refocus() {
    const F = new Set(S.sel); if (S.hoverEx) F.add(S.hoverEx);
    S.focus = F.size ? F : null;
    applyFocus();
    document.querySelectorAll('#legend [data-ex]').forEach((n) => {
      const k = n.dataset.ex; n.classList.toggle('is-on', k === S.hoverEx); n.classList.toggle('is-sel', S.sel.has(k)); n.setAttribute('aria-pressed', String(S.sel.has(k)));
    });
    const lim = document.getElementById('ex-limpiar');
    if (lim) { lim.hidden = !S.sel.size; lim.textContent = `Quitar marcas (${S.sel.size})`; }
  }
  document.getElementById('ex-limpiar').addEventListener('click', () => { S.sel.clear(); refocus(); });

  // ---------- plazos ----------
  function drawPlazos(rows) {
    const nav = document.getElementById('plazos'), keep = nav.scrollLeft; nav.replaceChildren();
    pick(rows, 'plazo').forEach((p) => {
      const head = pick(rows, 'explicacion').find((e) => e.plazo === p.plazo && e.tipo === 'titular');
      const bias = head ? head.sesgo : 'neutral', pu = num(p.primero_arriba);
      const b = el('button', 'ab-plazo ab-' + bias); b.type = 'button'; b.setAttribute('aria-pressed', String(p.plazo === S.plazo));
      const word = bias === 'alcista' ? `▲ Sube ${f0(pu)}%` : bias === 'bajista' ? `▼ Baja ${f0(100 - pu)}%` : '◆ Lateral';
      b.append(el('small', '', `En ${p.plazo}`), el('b', '', word),
        el('span', '', `${fp(num(p.obj_abajo))} – ${fp(num(p.obj_arriba))} · hasta\u00a0${p.hora.slice(-5)}\u00a0h`));
      b.addEventListener('click', () => setPlazo(p.plazo));
      nav.append(b);
    });
    // en el telefono la tira se desliza: se respeta donde la dejo el usuario y solo se mueve si cambia el plazo
    nav.scrollLeft = keep;
    const on = nav.querySelector('[aria-pressed="true"]');
    if (on && S.plazoShown !== S.plazo && nav.scrollWidth > nav.clientWidth) nav.scrollLeft = on.offsetLeft - nav.offsetLeft - 8;
    S.plazoShown = S.plazo;
  }

  // ---------- que creo que va a pasar ----------
  function drawStory(rows) {
    const ex = pick(rows, 'explicacion').filter((e) => e.plazo === S.plazo).sort((a, b) => num(a.orden) - num(b.orden));
    const head = ex.find((e) => e.tipo === 'titular');
    const bias = head ? head.sesgo : 'neutral';
    const chip = document.getElementById('story-chip'); chip.replaceChildren();
    const b = el('span', 'ab-bias', bias === 'alcista' ? '▲ Escenario alcista' : bias === 'bajista' ? '▼ Escenario bajista' : '◆ Sin dirección clara');
    b.style.color = bias === 'alcista' ? 'var(--color-ok)' : bias === 'bajista' ? 'var(--color-bad)' : 'var(--color-fg-muted)';
    chip.append(b);
    // regimen de mercado (tendencia, rango o panico) de las velas del plazo: dato, no cambia las probabilidades
    const pz = pick(rows, 'plazo').find((r) => r.plazo === S.plazo), mk = pz ? pick(rows, 'marco', pz.tf)[0] : null;
    if (mk && mk.regimen) {
      const rg = el('span', 'ab-bias', ` · ${mk.regimen[0].toUpperCase()}${mk.regimen.slice(1)} (${TF_TXT[pz.tf].toLowerCase()})`);
      rg.style.color = 'var(--color-fg-muted)';
      rg.title = 'Régimen de mercado: tendencia (la media de 200 con pendiente clara y el precio de ese lado), pánico (volatilidad más del doble de lo normal con el precio cayendo) o rango. Es un dato: aprender pesos distintos por régimen no mejoró las predicciones (medido 2023-2026).';
      chip.append(rg);
    }
    const neutral = bias === 'neutral';
    document.getElementById('favor-t').textContent = neutral ? 'Señales alcistas' : 'A favor';
    document.getElementById('contra-t').textContent = neutral ? 'Señales bajistas' : 'En contra';
    const fill = (id, items) => {
      const ul = document.getElementById(id); ul.replaceChildren();
      if (!items.length) { ul.append(el('li', 'ab-empty', 'Ninguna por ahora.')); return; }
      items.forEach((e) => ul.append(el('li', 'ab-' + e.sesgo, e.texto)));
    };
    document.getElementById('titular').textContent = head ? head.texto : '—';
    const why = ex.find((e) => e.tipo === 'porque');
    document.getElementById('porque').textContent = why ? why.texto : '';
    // vienen ordenadas por importancia: alcanza con las 4 primeras de cada lado
    const sigs = ex.filter((e) => e.tipo === 'senal');
    const favorSide = neutral ? 'alcista' : bias;
    fill('favor', sigs.filter((e) => e.sesgo === favorSide).slice(0, 4));
    fill('contra', sigs.filter((e) => e.sesgo !== favorSide).slice(0, 4));
    fill('vigilar', ex.filter((e) => e.tipo === 'vigilar'));
    const inv = ex.find((e) => e.tipo === 'invalida');
    document.getElementById('inval').textContent = inv ? inv.texto : '';
  }

  // ---------- prediccion principal (1 h, primer plazo) ----------
  function drawPrediction(rows, s) {
    {
      const cl = climaNoticias(rows), nl = document.getElementById('news-line');
      nl.hidden = !pick(rows, 'noticia').length; nl.replaceChildren();
      const fed = decisionFed(rows), fl = document.getElementById('fed-line');
      fl.hidden = !fed; fl.replaceChildren();
      if (fed) { const sp = el('span', '', fed.txt); if (fed.sesgo !== 'neutral') sp.style.color = fed.sesgo === 'alcista' ? 'var(--color-ok)' : 'var(--color-bad)'; fl.append(el('b', '', '🏦 Fed'), sp); }
      if (!nl.hidden) nl.append(el('b', '', 'Noticias'), el('span', '', `${cl.est === 'alcista' ? 'clima a favor de la suba' : cl.est === 'bajista' ? 'clima a favor de la baja' : 'clima neutral'} (${cl.buenas} buenas, ${cl.malas} malas en 6 h)`));
    }
    const p = pick(rows, 'plazo').find((r) => r.plazo === S.plazo);
    if (!p) return;
    const head = pick(rows, 'explicacion').find((e) => e.plazo === S.plazo && e.tipo === 'titular');
    const bias = head ? head.sesgo : 'neutral';
    const price = num(s.precio), pu = num(p.primero_arriba);
    document.getElementById('pred-k').textContent = `Predicción a ${S.plazo} desde ahora · hasta las ${p.hora.slice(-5)}\u00a0h del ${p.hora.slice(0, 5)}`;
    document.getElementById('pred-n').textContent = `${f0(num(p.n))} casos parecidos`;
    const vb = document.getElementById('verdict-big');
    vb.className = 'ab-verdict-big ab-' + bias;
    vb.textContent = bias === 'alcista' ? '▲ Más probable que suba' : bias === 'bajista' ? '▼ Más probable que baje' : '◆ Lateral';
    // baja a la izquierda, sube a la derecha: el lado mas ancho es el que se toco primero mas veces
    const tug = document.getElementById('first-split'); tug.replaceChildren();
    if (pu !== null) {
      const d = el('div', 'ab-tug-d'), u = el('div', 'ab-tug-u');
      d.append(el('b', '', `${f0(100 - pu)}%`), el('span', '', `▼ baja a ${fp(num(p.obj_abajo))}`));
      u.append(el('span', '', `sube a ${fp(num(p.obj_arriba))} ▲`), el('b', '', `${f0(pu)}%`));
      d.style.flexBasis = '50%'; u.style.flexBasis = '50%';
      tug.append(d, u, el('i', 'ab-tug-mid'));
      later(() => { d.style.flexBasis = (100 - pu) + '%'; u.style.flexBasis = pu + '%'; });
      document.getElementById('first-mg').textContent = `${f0(num(p.distancia))} USD para cada lado` + (num(p.factor) === 0 ? ' · sin ventaja aprendida: 50/50'
        : p.sin_ventaja ? ' · en su repaso no le ganó a lo normal: no lo toma como predicción' : ` · ±${f0(num(p.margen_primero))} pts`);
    }
    const lo = num(p.min), hi = num(p.max), span = hi - lo || 1;
    const at = (v) => Math.max(0, Math.min(100, (v - lo) / span * 100));
    document.getElementById('likely').textContent = p.mediana === null ? '—' : fp(num(p.mediana));
    document.getElementById('r-lo').textContent = fp(lo); document.getElementById('r-hi').textContent = fp(hi);
    // el rango del 80% ajustado con su propio pasado (calibracion): cuanto acertaba sin ajustar y cuanto se movio
    const rc = document.getElementById('r-cal'), rk = num(p.rango_k), rcob = num(p.rango_cobertura), rn = num(p.rango_casos) || 0;
    rc.hidden = rcob === null || rn < 30;
    if (!rc.hidden) {
      rc.textContent = `Rango del 80%: en sus últimas ${f0(rn)} predicciones de este plazo el precio terminó adentro ${f1(rcob)}% de las veces`
        + (rk === null || Math.abs(rk - 1) < 0.03 ? ', así que queda como está.' : rk > 1 ? `: venía angosto, se ensancha ×${f2(rk)}.` : `: venía ancho, se angosta ×${f2(rk)}.`);
    }
    const iqr = document.getElementById('iqr'), med = document.getElementById('rmed'), now = document.getElementById('rnow');
    iqr.style.left = '50%'; iqr.style.width = '0'; med.style.left = '50%'; now.style.left = '50%';
    later(() => {
      if (p.p25 !== null) { iqr.style.left = at(num(p.p25)) + '%'; iqr.style.width = (at(num(p.p75)) - at(num(p.p25))) + '%'; }
      if (p.mediana !== null) med.style.left = `calc(${at(num(p.mediana))}% - 1.5px)`;
      now.style.left = at(price) + '%';
    });
  }

  // ---------- aprendizaje ----------
  function pctTxt(v) { return v === null || v === undefined ? '—' : `${f1(num(v))}%`; }
  function learnLine(a) {
    if (!a || !num(a.repasadas)) return 'Todavía junta experiencia para este plazo.';
    const hab = num(a.habilidad), ap = num(a.aciertos_aprendido), lo = num(a.ic_bajo), hi = num(a.ic_alto);
    const v = hab === null ? 'midiendo' : hab >= 0.5 ? `le gana a lo normal por ${f1(hab)}%` : hab > -0.5 ? 'sin ventaja clara sobre lo normal' : `peor que lo normal (${f1(hab)}%)`;
    return ap === null || lo === null ? `Aprendiendo · ${v}` : `Acierta ${f1(ap)}% (entre ${f0(lo)} y ${f0(hi)}%) · ${v}`;
  }
  // calibracion: si un 60% del repaso paso de verdad ~60% de las veces (solo se muestra: ya salen calibradas)
  function drawCalibracion(a) {
    const box = document.getElementById('apr-cal'); box.replaceChildren();
    const cal = (a && Array.isArray(a.calibracion) ? a.calibracion : []).filter((x) => num(x[2]) >= 20);
    if (!cal.length) return;
    const n = cal.reduce((s, x) => s + num(x[2]), 0), err = cal.reduce((s, x) => s + num(x[2]) * Math.abs(num(x[0]) - num(x[1])), 0) / n;
    const lo = Math.min(40, ...cal.map((x) => Math.min(num(x[0]), num(x[1])))), hi = Math.max(60, ...cal.map((x) => Math.max(num(x[0]), num(x[1]))));
    const pos = (v) => `calc(${((v - lo) / (hi - lo)) * 100}% - 1.5px)`;
    box.append(el('p', 'ab-tm-sec', '¿Las probabilidades son honestas?'),
      el('p', 'ab-note', `En el repaso a ${S.plazo}, agrupando lo que dijo: barra gris = lo que dijo, barra negra = lo que pasó. Error medio ${f1(err)} puntos ${err <= 2 ? '(bien calibradas)' : err <= 4 ? '(aceptable)' : '(ojo: se equivoca en los porcentajes)'}.`));
    const g = el('div', 'ab-cal');
    cal.forEach(([p, real, k]) => {
      const row = el('div', 'ab-cal-row'), bar = el('div', 'ab-cal-bar'), i = el('i'), b = el('b');
      i.style.left = pos(num(p)); b.style.left = pos(num(real)); bar.append(i, b);
      row.append(el('span', '', `Dijo ${f0(num(p))}% → ${f0(num(real))}%`), bar, el('span', 'ab-note', `${f0(num(k))} casos`)); g.append(row);
    });
    box.append(g);
  }
  // ---------- confianza segun el momento: de las predicciones pasadas de este plazo (historial del servidor + las del
  // telefono), las hechas en un momento parecido al de ahora (mismo lado, misma firmeza, misma agitacion del mercado y el
  // precio del mismo lado de la EMA 50) y cuantas acertaron la direccion. Si hay pocas (menos de 25), se afloja el
  // parecido: primero la EMA 50, despues la agitacion. Velas de Binance (1.500 de la temporalidad del plazo). Solo mira:
  // no cambia las probabilidades. Se rehace al cambiar de plazo o cada 10 min.
  const CONF = { clave: '', t: 0, txt: null, corriendo: false };
  const HIST_URL = 'https://raw.githubusercontent.com/DiegoAdrian97/BTCAnalyzer/historial/historial/BTC';
  async function historialServidor(tf, desde, hasta) {
    if (MON() !== 'BTC') return [];
    const dias = []; for (let d = Math.floor(desde / 864e5) * 864e5; d <= hasta; d += 864e5) dias.push(new Date(d).toISOString().slice(0, 10));
    const txt = await Promise.all(dias.slice(-40).map((d) => fetch(`${HIST_URL}/${tf}/${d}.csv`, { signal: AbortSignal.timeout(10000) }).then((r) => (r.ok ? r.text() : '')).catch(() => '')));
    const out = [];
    txt.forEach((t) => t.split('\n').slice(1).forEach((l) => { const c = l.split(','); if (c.length >= 5) out.push([+c[0], tf, +c[1], +c[2], +c[3]]); }));
    return out;
  }
  async function confianzaAhora(rows) {
    const line = document.getElementById('apr-line'), pz = pick(rows, 'plazo').find((r) => r.plazo === S.plazo);
    if (!pz || !pz.tf || !num(pz.velas)) { line.replaceChildren(); return; }
    const tf = pz.tf, h = num(pz.velas), m = TF_MIN[tf] * 6e4, pr = num(pz.sube), clave = `${MON()}|${S.plazo}|${pr >= 50}|${Math.floor(Math.abs(pr - 50) / 5)}`;
    if (CONF.txt && CONF.clave === clave && Date.now() - CONF.t < 10 * 6e4) { line.replaceChildren(...CONF.txt()); return; }
    if (CONF.corriendo) { CONF.otra = rows; return; }      // cambio el plazo mientras medía: se rehace al terminar
    CONF.corriendo = true;
    try {
      if (!line.childNodes.length) line.append(el('b', '', 'Confianza ahora'), el('span', '', 'midiendo en momentos parecidos…'));
      const hasta = Date.now(), desde = hasta - 1500 * m;
      const [k, hist, local] = await Promise.all([
        fetch(`https://fapi.binance.com/fapi/v1/klines?symbol=${MON()}USDT&interval=${tf}&limit=1500`, { signal: AbortSignal.timeout(10000) }).then((r) => r.json()).catch(() => null),
        historialServidor(tf, desde, hasta), window.abRegistro ? window.abRegistro(tf, desde, hasta) : []]);
      if (!Array.isArray(k) || k.length < 300) { line.replaceChildren(el('b', '', 'Confianza ahora'), el('span', '', 'no se pudieron bajar las velas para comparar.')); return; }
      const B = k.map((r) => ({ t: +r[0], h: +r[2], l: +r[3], c: +r[4] })), idx = new Map(B.map((b, i) => [b.t, i]));
      // EMA 50 y agitacion (rango medio de las ultimas 12 velas contra la mediana de las 288 anteriores) en cada vela
      const ema = [], agit = []; let e = B[0].c; const a = 2 / 51;
      B.forEach((b, i) => {
        e = a * b.c + (1 - a) * e; ema.push(e);
        if (i < 300) { agit.push(null); return; }
        const r = (j) => (B[j].h - B[j].l) / B[j].c;
        let s12 = 0; for (let j = i - 11; j <= i; j++) s12 += r(j);
        const ant = []; for (let j = i - 299; j <= i - 12; j++) ant.push(r(j)); ant.sort((x, y) => x - y);
        const v = s12 / 12 / ant[ant.length >> 1];
        agit.push(v < 0.8 ? 0 : v < 1.3 ? 1 : 2);
      });
      const firmeza = (x) => Math.min(2, Math.floor(Math.abs(x - 50) / 5));      // 0: menos de 5 puntos, 1: 5 a 10, 2: mas
      const rasgos = (i, x) => ({ lado: x > 50, fir: firmeza(x), ag: agit[i], ema: B[i].c > ema[i] });
      const ahora = rasgos(B.length - 1, pr);
      const una = new Map(); hist.concat(local).forEach((r) => { if (r[2] === h) una.set(r[0], r); });
      const casos = [];
      una.forEach(([t, , , p, x]) => {
        const i = idx.get(t - m), f = idx.get(t + (h - 1) * m);
        if (i === undefined || f === undefined || x === 50 || agit[i] === null) return;
        casos.push({ ...rasgos(i, x), ok: (x > 50) === (B[f].c > p) });
      });
      const pasos = [['lado', 'fir', 'ag', 'ema'], ['lado', 'fir', 'ag'], ['lado', 'fir']];
      let usados = null, sel = [];
      for (const ks of pasos) { sel = casos.filter((c) => ks.every((q) => c[q] === ahora[q])); usados = ks; if (sel.length >= 25) break; }
      const pc = (xs) => (xs.length ? xs.filter((c) => c.ok).length / xs.length : null);
      const AG = ['calmo', 'normal', 'agitado'], FI = ['casi pareja', 'con 55–60%', 'con más de 60%'];
      const desc = [`${ahora.lado ? 'suba' : 'baja'} ${FI[ahora.fir]}`].concat(usados.includes('ag') && ahora.ag !== null ? [`mercado ${AG[ahora.ag]}`] : [], usados.includes('ema') ? [`${ahora.ema ? 'sobre' : 'debajo de'} la EMA 50`] : []).join(', ');
      CONF.clave = clave; CONF.t = Date.now();
      CONF.txt = () => {
        if (casos.length < 10) return [el('b', '', 'Confianza ahora'), el('span', '', `todavía junta casos: ${casos.length} predicciones a ${S.plazo} ya terminadas. El historial del servidor va sumando cada día.`)];
        if (sel.length < 10) return [el('b', '', 'Confianza ahora'), el('span', '', `pocos momentos parecidos todavía (${sel.length}). En total acertó la dirección ${f0(pc(casos) * 100)}% de ${f0(casos.length)}.`)];
        const p = pc(sel), mg = 196 * Math.sqrt((p * (1 - p)) / sel.length);
        return [el('b', '', 'Confianza ahora'), el('span', '', `en momentos como este (${desc}) acertó la dirección ${f0(p * 100)}% de ${f0(sel.length)} veces (±${f0(mg)}). En total: ${f0(pc(casos) * 100)}% de ${f0(casos.length)}.`)];
      };
      line.replaceChildren(...CONF.txt());
    } finally {
      CONF.corriendo = false;
      if (CONF.otra) { const r = CONF.otra; CONF.otra = null; confianzaAhora(r); }
    }
  }
  setInterval(() => { if (!document.hidden && S.rows) confianzaAhora(S.rows); }, 10 * 6e4);
  function drawLearning(rows) {
    const all = pick(rows, 'aprendizaje'), a = all.find((r) => r.plazo === S.plazo);
    drawCalibracion(a);
    const line = document.getElementById('apr-line'); line.replaceChildren();
    confianzaAhora(rows);             // en lugar de "Aprendizaje": cuanto acierta en momentos como este (ver confianzaAhora)
    document.getElementById('apr-k').textContent = `a ${S.plazo}`;
    const put = (id, v, sub) => { document.getElementById(id).textContent = v; document.getElementById(id + '-n').textContent = sub; };
    if (!a || !num(a.repasadas)) {
      put('apr-ap', '—', ''); put('apr-og', '—', ''); put('apr-br', '—', '');
      document.getElementById('apr-txt').textContent = 'Todavía no hay historia suficiente para repasar predicciones en este plazo: usa el método original.';
    } else {
      const hab = num(a.habilidad), hog = num(a.habilidad_original), ap = num(a.aciertos_aprendido), lo = num(a.ic_bajo), hi = num(a.ic_alto);
      const sg = num(a.aciertos_seguro), ns = num(a.decisivas_seguro);
      const sgn = (x) => (x === null ? '—' : `${x > 0 ? '+' : ''}${f1(x)}%`);
      put('apr-ap', sgn(hab), hog === null ? '' : `método original ${sgn(hog)}`);
      put('apr-og', pctTxt(ap), lo !== null ? `entre ${f0(lo)} y ${f0(hi)}% · medido en ${f0(num(a.independientes))} casos` : num(a.factor) === 0 ? 'sin ventaja: 50/50' : '');
      put('apr-br', pctTxt(sg), ns ? `${f0(ns)} veces que dio 58% o más` : 'casi nunca se anima');
      const b = document.getElementById('apr-ap');
      if (hab !== null) b.style.color = hab >= 0.5 ? 'var(--color-ok)' : hab <= -0.5 ? 'var(--color-bad)' : null;
      const desde = new Date(num(a.desde)).toLocaleDateString('es-AR', { ...tz, day: '2-digit', month: '2-digit' });
      const su = num(a.sep_arriba), sd = num(a.sep_abajo), ms = num(a.margen_sep);
      const sepTxt = su === null || sd === null ? '' : ` Cuando le daba más chances arriba que lo normal, tocó arriba primero ${f0(su)}% de las veces; cuando le daba menos, ${f0(sd)}%${ms === null ? '' : ` (diferencia ${f0(su - sd)} puntos, ±${f0(ms)} de margen)`}.`;
      document.getElementById('apr-txt').textContent = `Repasó ${f0(num(a.repasadas))} predicciones desde el ${desde}. Hoy pesa más ${a.lider} (peso del modelo que aprende solo: ${f0(num(a.peso_modelo))}%; de lo normal: ${f0(num(a.peso_base))}%). ${a.confianza}.${sepTxt}`;
    }
    // curva: ventaja sobre lo normal en ventanas de 150 predicciones, a medida que repasaba
    const box = document.getElementById('apr-chart'); box.replaceChildren();
    const lg = document.getElementById('apr-legend'); lg.replaceChildren();
    const pts = pick(rows, 'aprendizaje_curva').filter((r) => r.plazo === S.plazo)
      .map((r) => ({ k: num(r.paso), a: num(r.aprendido), o: num(r.original) })).sort((p, q) => p.k - q.k);
    if (pts.length > 1) {
      const W = Math.max(260, box.clientWidth), H = 150, ml = 40, mr = 8, mt = 8, mb = 20;   // ml: que entre "+60%"
      const vals = pts.flatMap((p) => [p.a, p.o]).filter((v) => v !== null).concat([0]);
      const [lo, hi] = d3.extent(vals);
      const x = d3.scaleLinear(d3.extent(pts, (p) => p.k), [ml, W - mr]);
      const yy = d3.scaleLinear([Math.min(-1, Math.floor(lo - 0.5)), Math.max(1, Math.ceil(hi + 0.5))], [H - mb, mt]).nice();
      const svg = d3.select(box).append('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', 'Ventaja sobre lo normal a medida que aprende');
      yy.ticks(4).forEach((v) => {
        svg.append('line').attr('class', 'ab-gl').attr('x1', ml).attr('x2', W - mr).attr('y1', yy(v)).attr('y2', yy(v)).style('stroke-dasharray', v === 0 ? '3 3' : null);
        svg.append('text').attr('x', ml - 4).attr('y', yy(v)).attr('dy', '.32em').attr('text-anchor', 'end').text(`${v > 0 ? '+' : ''}${v}%`);
      });
      svg.append('text').attr('x', ml).attr('y', H - 4).text('predicciones repasadas →');
      svg.append('text').attr('x', W - mr).attr('y', H - 4).attr('text-anchor', 'end').text(f0(pts[pts.length - 1].k));
      [['o', 'var(--color-fg-muted)', '4 3'], ['a', dash.colors[0], null]].forEach(([k, c, da]) => {
        svg.append('path').attr('d', d3.line().defined((p) => p[k] !== null).curve(d3.curveMonotoneX).x((p) => x(p.k)).y((p) => yy(p[k]))(pts))
          .style('fill', 'none').style('stroke', c).style('stroke-width', k === 'a' ? 2.2 : 1.6).style('stroke-dasharray', da).style('stroke-linecap', 'round');
      });
      const last = pts[pts.length - 1];
      if (last.a !== null) svg.append('circle').attr('cx', x(last.k)).attr('cy', yy(last.a)).attr('r', 3.5).style('fill', dash.colors[0]);
      [[dash.colors[0], 'Equipo que aprende'], ['var(--color-fg-muted)', 'Método original'], ['transparent', 'Línea punteada: 0%, igual que lo normal']].forEach(([c, t]) => {
        const sp = el('span'); const i = el('i'); i.style.background = c; if (c === 'transparent') i.style.borderTop = '1.5px dashed var(--color-fg-muted)';
        sp.append(i, t); lg.append(sp);
      });
    }
    const tb = document.querySelector('#apr-tbl tbody'); tb.replaceChildren();
    all.forEach((r) => {
      const tr = el('tr'); if (r.plazo === S.plazo) tr.className = 'ab-sel';
      // quien pesa mas en el equipo, en corto
      const short = String(r.lider || '').replace('el modelo que aprende solo', 'pesa más: el modelo').replace('lo normal', 'pesa más: lo normal')
        .replace('casos parecidos por ', 'pesa más: ').replace(/precio vs /g, '').replace('movimiento del último día', 'mov.\u00a024\u00a0h').replace(/ y /, ', ');
      const c0 = el('td'); c0.append(el('span', '', r.plazo), el('small', '', num(r.repasadas) ? short : 'junta experiencia'));
      const hb = num(r.habilidad), ho = num(r.habilidad_original);
      const sg = (x) => (x === null ? '—' : `${x > 0 ? '+' : ''}${f1(x)}%`);
      const c1 = el('td', 'r', sg(hb));
      if (hb !== null) { c1.style.color = hb >= 0.5 ? 'var(--color-ok)' : hb <= -0.5 ? 'var(--color-bad)' : null; c1.style.fontWeight = '600'; }
      const f = num(r.factor);
      tr.append(c0, c1, el('td', 'r', sg(ho)), el('td', 'r', f === 0 ? '50/50' : `×${ar.format(',.2f')(f)}`));
      tr.addEventListener('click', () => setPlazo(r.plazo));
      tb.append(tr);
    });
  }

  // ---------- sesgo ----------
  function drawGauge(rows) {
    const marcos = pick(rows, 'marco');
    const cur = marcos.find((m) => m.tf === S.tf);
    document.getElementById('sesgo-tf').textContent = TF_TXT[S.tf];
    const svg = d3.select('#gauge'); svg.selectAll('*').remove();
    const cx = 110, cy = 104, arc = d3.arc().innerRadius(74).outerRadius(92).cornerRadius(3);
    // los tramos con los mismos cortes que el texto (neutral entre −0,1 y 0,1; fuerte desde ±0,5): antes eran 5 iguales y la
    // aguja podia estar en el gris con el texto diciendo "Bajista"
    const segs = [['var(--color-bad)', 1, -1, -0.5], ['var(--color-bad)', .5, -0.5, -0.1], ['var(--color-fg-muted)', .35, -0.1, 0.1], ['var(--color-ok)', .5, 0.1, 0.5], ['var(--color-ok)', 1, 0.5, 1]];
    const ang = (x) => ((x + 1) / 2) * Math.PI - Math.PI / 2;
    segs.forEach(([c, o, x0, x1]) => svg.append('path').attr('transform', `translate(${cx},${cy})`)
      .attr('d', arc({ startAngle: ang(x0) + .02, endAngle: ang(x1) - .02 })).style('fill', c).style('fill-opacity', o));
    [['Bajista', 12, 'start'], ['Neutral', cx, 'middle'], ['Alcista', 208, 'end']].forEach(([t, x0, anc], k) =>
      svg.append('text').attr('x', x0).attr('y', k === 1 ? 6 : 124).attr('text-anchor', anc).style('fill', 'var(--color-fg-muted)').style('font-size', '10px').text(t));
    const nd = svg.append('g').attr('class', 'ab-needle').style('transform', 'rotate(-90deg)');
    nd.append('path').attr('d', `M${cx - 4},${cy} L${cx},${cy - 66} L${cx + 4},${cy} Z`).style('fill', 'var(--color-fg)');
    svg.append('circle').attr('cx', cx).attr('cy', cy).attr('r', 8).style('fill', 'var(--color-fg)');
    svg.append('circle').attr('cx', cx).attr('cy', cy).attr('r', 3).style('fill', 'var(--color-panel)');
    if (cur) {
      later(() => nd.style('transform', `rotate(${num(cur.rating) * 90}deg)`));
      const t = document.getElementById('gauge-txt'); t.textContent = cur.rating_txt; t.setAttribute('data-where', `tabla=marco&tf=${S.tf}`);
      document.getElementById('gauge-votes').textContent = `Medias ${cur.ma_compra}↑ ${cur.ma_venta}↓ · osciladores ${cur.osc_compra}↑ ${cur.osc_venta}↓ · orden de las medias: ${cur.tendencia.toLowerCase()}`;
    }
    const strip = document.getElementById('strip'); strip.replaceChildren();
    marcos.forEach((m) => {
      const r = num(m.rating);
      const b = el('button'); b.type = 'button'; b.setAttribute('aria-pressed', String(m.tf === S.tf)); b.title = `${TF_TXT[m.tf]}: ${m.rating_txt}`;
      const i = el('i'); i.style.background = r > .1 ? 'var(--color-ok)' : r < -.1 ? 'var(--color-bad)' : 'var(--color-fg-muted)';
      i.style.opacity = String(.35 + Math.min(1, Math.abs(r) * 1.6) * .65);
      b.append(el('span', '', m.tf === '1w' ? '1S' : m.tf), i); b.addEventListener('click', () => setTf(m.tf)); strip.append(b);
    });
  }

  // ---------- grafico: el motor de TradingView (Lightweight Charts) con todas nuestras marcas encima ----------
  // El grafico se crea una vez y vive entre analisis: no pierde el zoom ni la posicion, y los ticks en vivo mueven
  // la ultima vela al instante. Arrastrar, pellizcar, estirar los ejes y cambiar el alto de los paneles los hace el motor.
  const LW = window.LightweightCharts;
  const TZ = -3 * 3600;                                    // Argentina (sin horario de verano): el eje muestra la hora de aca
  const T2 = (ms) => Math.round(ms / 1000) + TZ;
  const G = { chart: null };
  window.abGraf = G;                                       // para revisarlo desde la consola
  const cssv = (k) => getComputedStyle(document.documentElement).getPropertyValue(k).trim();
  function alpha(c, a) {
    if (!c) return `rgba(128,128,128,${a})`;
    if (c[0] === '#') {
      const h = c.length === 4 ? c.slice(1).split('').map((x) => x + x).join('') : c.slice(1, 7);
      return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
    }
    const m = c.match(/[\d.]+/g);
    return m && m.length >= 3 ? `rgba(${m[0]},${m[1]},${m[2]},${a})` : c;
  }
  // en modo linea la vela queda transparente (sigue ahi para la escala, los niveles y las etiquetas)
  const TRANSP = 'rgba(0,0,0,0)';
  const barra = (b) => (S.linea ? { ...b, color: TRANSP, wickColor: TRANSP, borderColor: TRANSP } : b);
  const mktCol = () => cssv(document.documentElement.dataset.mkt === 'down' ? '--color-bad' : document.documentElement.dataset.mkt === 'up' ? '--color-ok' : '--color-fg-muted');
  function pal() {
    const dark = oscuro();
    return { dark, up: cssv('--color-ok'), dn: cssv('--color-bad'), warn: cssv('--color-warn'), fg: cssv('--color-fg'), mute: cssv('--color-fg-muted'),
      panel: cssv('--color-panel'), line: cssv('--color-border-line'), grid: cssv('--cds-chart-grid'),
      c0: dash.colors[0], c1: dash.colors[1], c2: dash.colors[2], font: cssv('--font-anthropic-sans') || 'system-ui, sans-serif',
      lbl: dark ? '#2c2c31' : '#111111' };
  }
  const DIAS = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'];
  const p2 = (v) => String(v).padStart(2, '0');
  function fmtSec(s) {
    const d = new Date(s * 1000), dd = `${p2(d.getUTCDate())}/${p2(d.getUTCMonth() + 1)}`;
    return ['1d', '1w', '1M'].includes(S.tf) ? `${DIAS[d.getUTCDay()]} ${dd}/${String(d.getUTCFullYear()).slice(2)}` : `${DIAS[d.getUTCDay()]} ${dd} ${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`;
  }
  // una capa de dibujo propia sobre el grafico (canvas, en pixeles de pantalla); opcionalmente con una etiqueta en el eje
  class Capa {
    constructor(fn, z, axis) {
      this.fn = fn; this.z = z; this.axis = axis || null;
      const self = this;
      this.views = [{ zOrder: () => self.z, renderer: () => ({ draw: (target) => target.useMediaCoordinateSpace(({ context, mediaSize }) => {
        try { self.fn(context, mediaSize.width, mediaSize.height); } catch (e) { console.warn('capa', e); }
      }) }) }];
    }
    attached(p) { this.p = p; }
    detached() { this.p = null; }
    updateAllViews() {}
    paneViews() { return this.views; }
    priceAxisViews() { return this.axis ? [this.axis] : []; }
    update() { if (this.p) this.p.requestUpdate(); }
  }
  // coordenadas: x de cualquier hora (tambien del futuro, donde todavia no hay velas) e y de un precio
  const X = (t) => G.chart.timeScale().logicalToCoordinate((t - G.d.t0) / G.d.tfMs);
  const Y = (p, s = G.c) => (p === null || p === undefined ? null : s.priceToCoordinate(p));
  const dimA = (k) => (S.focus && !S.focus.has(k) ? 0.12 : 1);
  // ---------- Fibonacci: niveles, puntos y arrastre ----------
  const FIB_N = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
  let FIBU = {};                                           // los que ajustaste a mano, por activo: { BTC: { a: {t, p}, b: {t, p} } }
  try { FIBU = JSON.parse(localStorage.getItem('ab-fib')) || {}; } catch (e) { FIBU = {}; }
  const guardarFib = () => { try { localStorage.setItem('ab-fib', JSON.stringify(FIBU)); } catch (e) { /* sin almacenamiento */ } };
  const fibX = (pt) => X(pt.t);
  function fibNiveles(d) {
    const fb = d.fib; if (!fb) return [];
    return FIB_N.map((f) => {
      const p = fb.b.p + (fb.a.p - fb.b.p) * f, r = fb.mano ? null : d.fibReb[f], pc = `${f === 0 || f === 1 ? f0(f * 100) : f1(f * 100)}%`;
      return { f, p, extremo: f === 0 || f === 1, fuerte: r !== null && r !== undefined && r >= 55,
        txt: d.fibNarrow ? `Fib ${pc} ${fp(p)}` : `Fib ${pc} · ${fp(p)}${r !== null && r !== undefined ? ` · rebotó ${f0(r)}%` : ''}` };
    });
  }
  // que parte del fib hay bajo el puntero: un punto ('a' inicio, 'b' fin), la diagonal ('cuerpo') o nada
  function fibHit(x, y, tol) {
    const fb = G.d && G.d.fib; if (!fb) return null;
    const ax = fibX(fb.a), ay = Y(fb.a.p), bx = fibX(fb.b), by = Y(fb.b.p);
    if (ay === null || by === null) return null;
    if (Math.hypot(x - ax, y - ay) <= tol) return 'a';
    if (Math.hypot(x - bx, y - by) <= tol) return 'b';
    const L2 = (bx - ax) ** 2 + (by - ay) ** 2, u = L2 ? Math.max(0, Math.min(1, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / L2)) : 0;
    return Math.hypot(x - (ax + u * (bx - ax)), y - (ay + u * (by - ay))) <= tol * 0.6 ? 'cuerpo' : null;
  }
  // arrastrar un punto lo mueve (pegado a la vela; con el Iman, a su apertura, maximo, minimo o cierre); arrastrar la
  // diagonal mueve todo. Se toma antes que el motor del grafico (asi no mueve la vista) y antes que Medir
  function fibInput(box) {
    if (box.abFib) return;
    box.abFib = true;
    let drag = null;
    const local = (e) => { const r = box.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    const enPanel = (x, y) => { try { const ps = G.chart.paneSize(0); return x >= 0 && x <= ps.width && y >= 0 && y <= ps.height; } catch (err) { return false; } };
    const tol = (e) => (e.pointerType === 'mouse' ? 9 : 22);
    const punto = (x, y, e) => {
      const d = G.d, l = G.chart.timeScale().coordinateToLogical(x), p = G.c.coordinateToPrice(y);
      if (l === null || p === null) return null;
      const k = Math.round(l), b = k >= 0 && k < d.all.length ? d.all[k] : null;
      const pp = b && S.iman !== (e.ctrlKey || e.metaKey) ? [b.o, b.h, b.l, b.c].reduce((m, v) => (Math.abs(Y(v) - y) < Math.abs(Y(m) - y) ? v : m)) : p;
      return { t: d.t0 + k * d.tfMs, p: pp };
    };
    box.addEventListener('pointerdown', (e) => {
      if (!G.chart || !G.d || !G.d.fib || e.button !== 0 || S.medir || (e.shiftKey && e.pointerType === 'mouse') || (e.target.closest && e.target.closest('.ab-dib-bar'))) return;
      const [x, y] = local(e); if (!enPanel(x, y)) return;
      const k = fibHit(x, y, tol(e)); if (!k) return;
      const fb = G.d.fib;
      drag = { k, a0: { ...fb.a }, b0: { ...fb.b }, l0: G.chart.timeScale().coordinateToLogical(x), p0: G.c.coordinateToPrice(y) };
      G.fibDrag = k; e.preventDefault(); e.stopImmediatePropagation(); G.over.update();
    }, { capture: true });
    // el motor escucha mousedown y touchstart: mientras se arrastra el fib no les llegan (ni se mueve la pagina)
    const bloquear = (e) => { if (drag) { e.preventDefault(); e.stopImmediatePropagation(); } };
    ['mousedown', 'touchstart', 'touchmove'].forEach((ev) => box.addEventListener(ev, bloquear, { capture: true, passive: false }));
    window.addEventListener('pointermove', (e) => {
      if (!G.chart || !G.d || !G.d.fib) return;
      const [x, y] = local(e);
      if (!drag) {                                         // con el mouse: el cursor avisa que se puede arrastrar
        if (e.pointerType !== 'mouse') return;
        const k = enPanel(x, y) ? fibHit(x, y, 9) : null;
        if (k !== (G.fibHover || null)) { G.fibHover = k; box.style.cursor = k ? (k === 'cuerpo' ? 'move' : 'grab') : ''; G.over.update(); }
        return;
      }
      const fb = G.d.fib;
      if (drag.k === 'cuerpo') {
        const l = G.chart.timeScale().coordinateToLogical(x), p = G.c.coordinateToPrice(y);
        if (l === null || p === null || drag.l0 === null || drag.p0 === null) return;
        const dt = Math.round(l - drag.l0) * G.d.tfMs, dp = p - drag.p0;
        fb.a = { t: drag.a0.t + dt, p: drag.a0.p + dp }; fb.b = { t: drag.b0.t + dt, p: drag.b0.p + dp };
      } else { const pt = punto(x, y, e); if (!pt) return; fb[drag.k] = pt; }
      fb.mano = true; G.d.fibs = fibNiveles(G.d);
      G.under.update(); G.over.update();
    });
    const soltar = () => {
      if (!drag) return;
      drag = null; G.fibDrag = null;
      const fb = G.d && G.d.fib;
      if (fb && fb.mano) { FIBU[MON()] = { a: fb.a, b: fb.b }; guardarFib(); }
      if (S.rows) drawChart(S.rows, S.sum);               // la leyenda pasa a "ajustado a mano"
    };
    window.addEventListener('pointerup', soltar);
    window.addEventListener('pointercancel', soltar);
  }
  function pillC(ctx, x, y, text, col, solid, anchor, w) {
    ctx.font = `600 10.5px ${G.P.font}`;
    const tw = ctx.measureText(text).width + 14;
    let x0 = anchor === 'end' ? x - tw : anchor === 'middle' ? x - tw / 2 : x;
    x0 = Math.max(2, Math.min(x0, w - tw - 2));
    ctx.beginPath(); ctx.roundRect(x0, y - 9, tw, 18, 9);
    ctx.fillStyle = alpha(col, solid ? 0.22 : 0.12); ctx.fill();
    ctx.setLineDash(solid ? [] : [3, 2]); ctx.strokeStyle = alpha(col, solid ? 0.9 : 0.6); ctx.lineWidth = 1; ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = col; ctx.textBaseline = 'middle'; ctx.textAlign = 'left'; ctx.fillText(text, x0 + 7, y + 0.5);
  }
  const colOf = (s) => (s === 'alcista' ? G.P.up : s === 'bajista' ? G.P.dn : G.P.warn);

  // ---------- abanico de caminos: lo que paso despues en los casos REALMENTE parecidos al de ahora ----------
  // Usa las velas que la app ya guarda en el telefono (las del analisis: 30 dias en 5m ... 4 años en el diario; sin
  // pedir nada a la red). Un caso entra solo si cumple TODO a la vez (sin aflojar si son pocos):
  //   forma de las ultimas W velas (medida en volatilidad): correlacion >= 0,94 y error <= 0,25; las ultimas 8 velas
  //   (el impulso de ahora) con error <= 0,2; volatilidad relativa parecida (±35 %) y del mismo lado de la EMA 200.
  // Casos sin solaparse (separados al menos el horizonte). Con menos de 8, no se dibuja nada.
  // Los caminos se llevan a la volatilidad de hoy. "Subio/bajo fuerte" = mas que la mitad de los movimientos de ese
  // horizonte en toda la historia; se compara con lo que pasa en cualquier momento y solo se marca si se aparta (z >= 2).
  const ABA = { key: null, res: null, corre: null };
  const ABA_W = 36, ABA_MIN = 8, ABA_MAX = 30;
  function abaLeerVelas(mon, tf) {
    const pre = mon === 'BTC' ? '' : `${mon}USDT:`;
    const claves = ['binance', 'bybit', 'bitget'].flatMap((s) => [`${pre}velas:${s}:${tf}`].concat(tf === '1d' ? [`${pre}velas:${s}:${tf}:largo`] : []));
    return new Promise((ok) => {
      let req; try { req = indexedDB.open('analista-btc', 1); } catch (e) { ok([]); return; }
      req.onupgradeneeded = () => { try { req.result.createObjectStore('kv'); } catch (e) { /* ya estaba */ } };
      req.onerror = () => ok([]);
      req.onsuccess = () => {
        const db = req.result, out = [];
        let tx; try { tx = db.transaction('kv'); } catch (e) { ok([]); return; }
        claves.forEach((k) => { const q = tx.objectStore('kv').get(k); q.onsuccess = () => { if (Array.isArray(q.result)) out.push(q.result); }; });
        tx.oncomplete = () => { db.close(); ok(out.sort((a, b) => b.length - a.length)[0] || []); };
        tx.onerror = () => ok([]);
      };
    });
  }
  function abaCalcular(V, H) {
    const n = V.length, W = ABA_W, R8 = 8;
    if (n < W + H + 300) return { n, casos: [], falta: true };
    const lc = V.map((b) => Math.log(b[4])), r = new Float64Array(n);
    for (let i = 1; i < n; i++) r[i] = lc[i] - lc[i - 1];
    const s1 = new Float64Array(n + 1), s2 = new Float64Array(n + 1);
    for (let i = 0; i < n; i++) { s1[i + 1] = s1[i] + r[i]; s2[i + 1] = s2[i] + r[i] * r[i]; }
    const sig = new Float64Array(n);
    for (let i = W; i < n; i++) { const m = (s1[i + 1] - s1[i + 1 - W]) / W; sig[i] = Math.sqrt(Math.max(1e-12, (s2[i + 1] - s2[i + 1 - W]) / W - m * m)); }
    // volatilidad relativa: la de la ventana contra el promedio de las 300 velas anteriores
    const sg = new Float64Array(n + 1); for (let i = 0; i < n; i++) sg[i + 1] = sg[i] + sig[i];
    const vrel = (i) => sig[i] / Math.max(1e-12, (sg[i + 1] - sg[i + 1 - 300]) / 300);
    const ema = new Float64Array(n); const a = 2 / 201; ema[0] = V[0][4]; for (let i = 1; i < n; i++) ema[i] = ema[i - 1] + a * (V[i][4] - ema[i - 1]);
    const camino = (i) => { const d = sig[i] * Math.sqrt(W), o = new Float64Array(W); for (let k = 0; k < W; k++) o[k] = (lc[i - W + 1 + k] - lc[i]) / d; return o; };
    const cur = n - 1, pc = camino(cur), vc = vrel(cur), ladoC = Math.sign(V[cur][4] - ema[cur]);
    let mC = 0; for (let k = 0; k < W; k++) mC += pc[k]; mC /= W;
    let vC = 0; for (let k = 0; k < W; k++) vC += (pc[k] - mC) ** 2;
    const cand = [];
    for (let i = W + 300; i <= n - 1 - H; i++) {
      if (Math.sign(V[i][4] - ema[i]) !== ladoC) continue;
      if (Math.abs(Math.log(vrel(i) / vc)) > Math.log(1.35)) continue;
      const p = camino(i);
      let e2 = 0, e8 = 0, m = 0; for (let k = 0; k < W; k++) { const d = p[k] - pc[k]; e2 += d * d; if (k >= W - R8) e8 += d * d; m += p[k]; }
      const rm = Math.sqrt(e2 / W); if (rm > 0.25 || Math.sqrt(e8 / R8) > 0.2) continue;
      m /= W; let cv = 0, vp = 0; for (let k = 0; k < W; k++) { cv += (p[k] - m) * (pc[k] - mC); vp += (p[k] - m) ** 2; }
      const corr = cv / Math.sqrt(vp * vC || 1e-12); if (corr < 0.94) continue;
      cand.push({ i, rm, corr });
    }
    cand.sort((x, y) => x.rm - y.rm);
    const casos = [];
    for (const c of cand) { if (casos.length >= ABA_MAX) break; if (casos.every((o) => Math.abs(o.i - c.i) >= H)) casos.push(c); }
    // lo que paso despues, llevado a la volatilidad de hoy; y lo normal en cualquier momento (toda la historia)
    const esc = (i) => sig[cur] / sig[i];
    casos.forEach((c) => { const f = esc(c.i); c.t = V[c.i][0]; c.camino = Array.from({ length: H }, (_, k) => (lc[c.i + k + 1] - lc[c.i]) * f); c.fin = c.camino[H - 1]; });
    const finales = []; for (let i = W + 300; i <= n - 1 - H; i += 2) finales.push((lc[i + H] - lc[i]) * esc(i));
    const abs = finales.map(Math.abs).sort((x, y) => x - y), M = abs[Math.floor(abs.length / 2)] || 0;
    const base = { sube: finales.filter((x) => x > M).length / finales.length, baja: finales.filter((x) => x < -M).length / finales.length };
    const k = casos.length, sube = casos.filter((c) => c.fin > M).length / (k || 1), baja = casos.filter((c) => c.fin < -M).length / (k || 1);
    const z = (p, p0) => (p - p0) / Math.sqrt(Math.max(1e-9, p0 * (1 - p0) / Math.max(1, k)));
    const mediana = Array.from({ length: H }, (_, j) => { const v = casos.map((c) => c.camino[j]).sort((x, y) => x - y); return v.length ? v[Math.floor(v.length / 2)] : 0; });
    return { n, desde: V[0][0], casos, M, base, sube, baja, zSube: z(sube, base.sube), zBaja: z(baja, base.baja), mediana, base0: V[cur][4], t0: V[cur][0],
      parecido: k ? casos.reduce((s, c) => s + c.corr, 0) / k : 0 };
  }
  // se pide al dibujar: si cambio el activo, la temporalidad o cerro una vela, se recalcula (sin trabar: despues del dibujo)
  function abaPedir(tf) {
    if (!S.layers.abanico || !G.d || ['1w', '1M'].includes(tf)) return;
    const H = Math.max(4, Math.min(48, G.d.futN || 12)), lastT = G.d.all[G.d.all.length - 1].t, key = `${MON()}|${tf}|${H}|${lastT}`;
    if (ABA.key === key || ABA.corre === key) return;
    ABA.corre = key;
    const mon = MON();
    abaLeerVelas(mon, tf).then((V) => new Promise((ok) => setTimeout(() => ok(V), 30))).then((V) => {
      if (ABA.corre !== key) return;
      const res = V.length ? abaCalcular(V, H) : { n: 0, casos: [], falta: true };
      res.tf = tf; res.mon = mon; res.H = H; res.tfMs = G.d.tfMs;
      ABA.res = res; ABA.key = key; ABA.corre = null;
      if (S.rows && S.layers.abanico) drawChart(S.rows, S.sum);
    }).catch(() => { ABA.corre = null; });
  }
  const abaVigente = (tf) => S.layers.abanico && ABA.res && ABA.res.mon === MON() && ABA.res.tf === tf && ABA.res.casos.length >= ABA_MIN;
  function dibAbanico(ctx, w, h, tf) {
    if (!abaVigente(tf)) return;
    const a = ABA.res, P = G.P, x0 = X(a.t0), y0 = Y(a.base0); if (x0 === null || y0 === null) return;
    const xk = (k) => X(a.t0 + (k + 1) * a.tfMs);
    ctx.save(); ctx.lineJoin = 'round'; ctx.globalAlpha = dimA('abanico');
    a.casos.forEach((c) => {
      const col = c.fin > a.M ? P.up : c.fin < -a.M ? P.dn : P.mute;
      ctx.beginPath(); ctx.moveTo(x0, y0);
      c.camino.forEach((v, k) => { const x = xk(k), y = Y(a.base0 * Math.exp(v)); if (x !== null && y !== null) ctx.lineTo(x, y); });
      ctx.strokeStyle = alpha(col, 0.42); ctx.lineWidth = 1.1; ctx.stroke();
    });
    ctx.beginPath(); ctx.moveTo(x0, y0);
    a.mediana.forEach((v, k) => { const x = xk(k), y = Y(a.base0 * Math.exp(v)); if (x !== null && y !== null) ctx.lineTo(x, y); });
    ctx.setLineDash([5, 4]); ctx.strokeStyle = alpha(P.fg, 0.85); ctx.lineWidth = 1.8; ctx.stroke(); ctx.setLineDash([]);
    // la etiqueta, arriba del abanico donde termina lo que se ve (con poco futuro a la vista, igual queda legible)
    let kv = -1; for (let k = 0; k < a.H; k++) { const x = xk(k); if (x !== null && x <= w - 2) kv = k; }
    if (kv >= 0) {
      let yTop = Infinity; a.casos.forEach((c) => { const y = Y(a.base0 * Math.exp(c.camino[kv])); if (y !== null) yTop = Math.min(yTop, y); });
      const pc = (x) => `${Math.round(x * 100)}%`;
      if (isFinite(yTop)) pillC(ctx, xk(kv), Math.max(14, Math.min(h - 14, yTop - 14)), `${a.casos.length} casos · ↑${pc(a.sube)} ↓${pc(a.baja)}`, P.fg, true, 'end', w);
    }
    ctx.restore();
  }
  function abaLeyenda(tf) {
    if (!S.layers.abanico || ['1w', '1M'].includes(tf)) return null;
    const a = ABA.res;
    if (!a || a.mon !== MON() || a.tf !== tf) return ['Abanico de caminos:', 'buscando casos realmente parecidos en las velas guardadas…'];
    const dias = a.n ? Math.round((a.t0 - a.desde) / 864e5) : 0;
    if (a.falta) return ['Abanico de caminos:', 'todavía no hay suficientes velas guardadas de esta temporalidad para buscar casos parecidos.'];
    if (a.casos.length < ABA_MIN) return ['Abanico de caminos:', `en ${dias} días de historia hay ${a.casos.length === 0 ? 'ningún caso' : a.casos.length === 1 ? 'un solo caso' : `solo ${a.casos.length} casos`} realmente parecido${a.casos.length === 1 ? '' : 's'} al de ahora (hacen falta ${ABA_MIN}): no se dibuja, y no se aflojan los criterios para llegar.`];
    const pc = (x) => `${Math.round(x * 100)}%`, mv = `${f1(a.M * 100)}%`;
    const dif = a.zSube >= 2 ? `subieron fuerte más que lo normal (${pc(a.sube)} contra ${pc(a.base.sube)} en cualquier momento)`
      : a.zBaja >= 2 ? `bajaron fuerte más que lo normal (${pc(a.baja)} contra ${pc(a.base.baja)} en cualquier momento)`
        : `no se apartan de lo normal: ${pc(a.sube)} subió fuerte y ${pc(a.baja)} bajó fuerte (en cualquier momento: ${pc(a.base.sube)} y ${pc(a.base.baja)})`;
    const fechas = a.casos.slice().sort((x, y) => y.t - x.t).slice(0, 4).map((c) => new Date(c.t).toLocaleDateString('es-AR', { ...tz, day: 'numeric', month: 'short', year: '2-digit' }));
    return ['Abanico de caminos:', `lo que pasó en las ${a.H} velas siguientes en los ${a.casos.length} casos realmente parecidos de ${dias} días (forma de las últimas ${ABA_W} velas, impulso reciente, volatilidad y lado de la EMA 200; parecido promedio ${Math.round(a.parecido * 100)}%), llevados a la volatilidad de hoy. Verde: subió más de ${mv}; rojo: bajó más de ${mv}; gris: en el medio; la línea a rayas es la mediana. Esos casos ${dif}. Los más recientes: ${fechas.join(', ')}.`];
  }

  // debajo de las velas: zona del futuro, hora del plazo, Bollinger, FVG y el cono de lo que suele pasar
  function drawUnder(ctx, w, h) {
    const d = G.d, P = G.P, L = S.layers;
    if (!d) return;
    if (d.fib && d.fibs.length) {
      const x0 = Math.max(0, Math.min(fibX(d.fib.a), fibX(d.fib.b)));
      ctx.save(); ctx.globalAlpha = dimA('fib'); ctx.lineWidth = 1; ctx.setLineDash([2, 4]);
      if (x0 < w) d.fibs.forEach((f) => {
        const y = Y(f.p); if (y === null || y < 0 || y > h) return;
        ctx.strokeStyle = alpha(P.c2 || P.mute, f.extremo ? 0.6 : f.fuerte ? 0.55 : 0.32);
        ctx.beginPath(); ctx.moveTo(x0, Math.round(y) + 0.5); ctx.lineTo(w, Math.round(y) + 0.5); ctx.stroke();
      });
      const ya = Y(d.fib.a.p), yb = Y(d.fib.b.p);           // la diagonal del inicio al fin
      if (ya !== null && yb !== null) { ctx.setLineDash([5, 4]); ctx.strokeStyle = alpha(P.c2 || P.mute, 0.5); ctx.beginPath(); ctx.moveTo(fibX(d.fib.a), ya); ctx.lineTo(fibX(d.fib.b), yb); ctx.stroke(); }
      ctx.restore();
    }
    const half = (X(d.lastT + d.tfMs) - X(d.lastT)) / 2 || 3;
    if (L.libro) { ctx.save(); ctx.globalAlpha = dimA('libro'); dibLibro(ctx, w, h, d.all, d.tfMs, X, Y, half); ctx.restore(); }
    if (L.bb && d.bb.length > 1) {
      ctx.globalAlpha = dimA('bb'); ctx.beginPath();
      d.bb.forEach((b, i) => { const x = X(b.t), y = Y(b.u); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      for (let i = d.bb.length - 1; i >= 0; i--) ctx.lineTo(X(d.bb[i].t), Y(d.bb[i].l));
      ctx.closePath(); ctx.fillStyle = alpha(P.fg, 0.035); ctx.fill(); ctx.globalAlpha = 1;
    }
    if (L.fvg) d.fvgs.forEach((z) => {
      const x0 = X(z.t) - half, yt = Y(z.hi), yb = Y(z.lo);
      if (x0 === null || yt === null || yb === null || x0 > w) return;
      ctx.globalAlpha = dimA('fvg');
      ctx.fillStyle = alpha(z.up ? P.up : P.dn, 0.09); ctx.fillRect(x0, yt, w - x0, Math.max(2, yb - yt));
      ctx.fillStyle = alpha(z.up ? P.up : P.dn, 0.5); ctx.fillRect(x0, yt, 1.5, Math.max(2, yb - yt));
      ctx.globalAlpha = 1;
    });
    if (d.futN) {
      const xf = X(d.lastT) + half;
      if (xf < w) {
        ctx.globalAlpha = dimA('futuro');
        const g = ctx.createLinearGradient(xf, 0, w, 0); g.addColorStop(0, alpha(P.fg, 0.05)); g.addColorStop(1, alpha(P.fg, 0.012));
        ctx.fillStyle = g; ctx.fillRect(xf, 0, w - xf, h);
        ctx.fillStyle = alpha(P.fg, 0.14); ctx.fillRect(xf, 0, 1, h);
        ctx.font = `600 10px ${P.font}`;
        const txt = [`Futuro posible · ${SCEN_TXT[S.scen]}`, 'Futuro posible', 'Futuro'].find((s) => xf + ctx.measureText(s).width + 22 < w);
        if (txt) {
          const tw = ctx.measureText(txt).width + 14;
          // abajo, sobre el volumen: arriba esta la leyenda de la vela
          ctx.beginPath(); ctx.roundRect(xf + 6, h - 24, tw, 18, 9); ctx.fillStyle = alpha(P.fg, 0.08); ctx.fill();
          ctx.fillStyle = P.mute; ctx.textBaseline = 'middle'; ctx.textAlign = 'left'; ctx.fillText(txt.toUpperCase(), xf + 13, h - 14.5);
        }
        if (d.pz) {
          const xx = X(d.pz.t) - half;
          if (xx > xf && xx < w) {
            ctx.setLineDash([2, 4]); ctx.strokeStyle = alpha(P.fg, 0.45); ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(xx, 0); ctx.lineTo(xx, h - 30); ctx.stroke(); ctx.setLineDash([]);
            ctx.font = `600 10px ${P.font}`; ctx.fillStyle = P.mute; ctx.textAlign = 'right'; ctx.textBaseline = 'bottom';
            ctx.fillText(d.pz.txt.toUpperCase(), xx - 4, h - 32);
          }
        }
        // el cono: donde termino el 80% de los casos parecidos, y la linea del medio
        if (d.cone.length) {
          const pts = [{ t: d.lastT, lo: d.lastC, hi: d.lastC, mid: d.lastC }].concat(d.cone);
          const g2 = ctx.createLinearGradient(xf, 0, w, 0); g2.addColorStop(0, alpha(P.fg, 0.16)); g2.addColorStop(1, alpha(P.fg, 0.05));
          ctx.beginPath();
          pts.forEach((c, i) => { const x = X(c.t), y = Y(c.hi); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
          for (let i = pts.length - 1; i >= 0; i--) ctx.lineTo(X(pts[i].t), Y(pts[i].lo));
          ctx.closePath(); ctx.fillStyle = g2; ctx.fill();
          ctx.setLineDash([4, 4]); ctx.strokeStyle = alpha(P.fg, 0.45); ctx.lineWidth = 1.2; ctx.beginPath();
          pts.forEach((c, i) => { const x = X(c.t), y = Y(c.mid); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
          ctx.stroke(); ctx.setLineDash([]);
        }
        ctx.globalAlpha = 1;
      }
    }
    dibAbanico(ctx, w, h, S.tf);
    if (L.ict) { ctx.save(); ctx.globalAlpha = dimA('ict'); dibIct(ctx, w, h, d.icts, X, Y, P, half, d.narrow); ctx.restore(); }
    if (L.vp) { ctx.save(); ctx.globalAlpha = dimA('vp'); dibPerfil(ctx, w, h, perfilVisible(G.chart, d.all), Y, P, d.narrow); ctx.restore(); }
  }

  // encima de las velas: figuras, divergencias, ondas de Elliott y el mapa de liquidaciones al costado
  function drawOver(ctx, w, h) {
    const d = G.d, P = G.P, L = S.layers;
    if (!d) return;
    const narrow = w < 480;
    if (d.fib && d.fibs.length) {
      const col = P.c2 || P.mute, xl = Math.max(6, Math.min(fibX(d.fib.a), fibX(d.fib.b)) + 4);
      ctx.save(); ctx.globalAlpha = dimA('fib'); ctx.font = `500 10px ${P.font}`; ctx.textBaseline = 'bottom';
      const lh = G.leg ? G.leg.offsetTop + G.leg.offsetHeight + 2 : 0, lw = G.leg ? G.leg.offsetLeft + G.leg.offsetWidth : 0;
      if (xl < w - 40) d.fibs.forEach((f) => {
        const y = Y(f.p); if (y === null || y < 14 || y > h) return;
        if (y - 13 < lh && xl < lw) return;                  // debajo de la leyenda no se leia (la linea queda igual)
        const tw = ctx.measureText(f.txt).width;
        ctx.fillStyle = alpha(P.panel, 0.7); ctx.fillRect(xl - 3, y - 13, tw + 6, 12);          // fondo suave para leerlo sobre las velas
        ctx.fillStyle = alpha(col, f.extremo || f.fuerte ? 1 : 0.9); ctx.fillText(f.txt, xl, y - 2);
      });
      ['a', 'b'].forEach((k) => {                            // los dos puntos: se arrastran (como en TradingView)
        const x = fibX(d.fib[k]), y = Y(d.fib[k].p); if (y === null || x < -10 || x > w + 10 || y < -10 || y > h + 10) return;
        const r = G.fibDrag === k || G.fibHover === k ? 6.5 : 4.5;
        ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fillStyle = P.panel; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = col; ctx.stroke();
      });
      ctx.restore();
    }
    const usados = [];      // alturas de los nombres de figuras ya puestos: si dos caen juntos (p. ej. pegados al borde), el otro baja
    if (L.patrones) {
      d.figs.forEach((p) => {
        const col = colOf(p.sesgo), conf = p.estado === 'confirmado', key = `pat-grafico-${p.nombre}`;
        ctx.globalAlpha = dimA(key);
        let label = null;
        [1, 2].forEach((k) => {
          const t0 = num(p[`l${k}_t`]); if (t0 === null) return;
          const p0 = num(p[`l${k}_p`]), mm = num(p[`l${k}_m`]), val = (t) => p0 + mm * (t - t0);
          const ta = Math.max(t0, d.firstT), te = d.endT;
          ctx.setLineDash(conf ? [] : [6, 4]); ctx.strokeStyle = col; ctx.lineWidth = conf ? 2 : 1.4;
          ctx.beginPath(); ctx.moveTo(X(ta), Y(val(ta))); ctx.lineTo(X(te), Y(val(te))); ctx.stroke(); ctx.setLineDash([]);
          const name = p[`l${k}_nombre`] || '', now = val(d.lastT), yn = Y(now);
          const when = name === 'Cuello' && !conf ? (p.sesgo === 'alcista' ? ' · se confirma si lo supera' : ' · se confirma si lo pierde') : '';
          if (!narrow && yn !== null && yn > 10 && yn < h - 10) pillC(ctx, X(d.lastT) - 10, yn + (name === 'Piso' || yn < 56 ? 14 : -14), /* pegado arriba: debajo de la linea, sin meterse bajo la leyenda */ `${name} ${f0(now)}${when}`, col, false, 'end', w);
          if (!label) label = { x: X(ta) + 4, y: Y(val(ta)) + (name === 'Piso' ? 16 : -16) };
        });
        let first = null;
        [1, 2, 3, 4, 5].forEach((k) => {
          const t0 = num(p[`pt${k}_t`]); if (t0 === null) return;
          const b = d.byT.get(t0); if (!b) return;
          const pv = num(p[`pt${k}_p`]), below = Math.abs(pv - b.l) < Math.abs(pv - b.h), x = X(t0), y = Y(pv);
          ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fillStyle = P.panel; ctx.fill(); ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.stroke();
          ctx.font = `600 10.5px ${P.font}`; ctx.fillStyle = col; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText(p[`pt${k}_nombre`] || '', x, y + (below ? 15 : -13));
          if (!first) first = { x, y: y + (below ? 32 : -30) };
        });
        const head = first || label;
        const pn = narrow && p.nombre.length > 22 ? `${p.nombre.slice(0, 21).trim()}…` : p.nombre;
        if (head) {
          let y = Math.max(narrow ? 66 : 50, Math.min(h - 12, head.y));
          while (usados.some((u) => Math.abs(u - y) < 20) && y < h - 12) y += 20;
          usados.push(y);
          pillC(ctx, head.x, y, conf ? `✓ ${pn}` : `Posible ${pn.slice(0, 1).toLowerCase()}${pn.slice(1)}`, col, conf, first ? 'middle' : 'start', w);
        }
        ctx.globalAlpha = 1;
      });
      d.divs.forEach((v) => {
        const col = v.tipo === 'alcista' ? P.up : P.dn, off = v.tipo === 'bajista' ? -9 : 9;
        const x1 = X(v.t1), y1 = Y(v.p1), x2 = X(v.t2), y2 = Y(v.p2);
        if (y1 === null || y2 === null) return;
        ctx.globalAlpha = dimA(v.key);
        ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.lineCap = 'round';
        ctx.beginPath(); ctx.moveTo(x1, y1 + off); ctx.lineTo(x2, y2 + off); ctx.stroke();
        [[x1, y1], [x2, y2]].forEach(([x, y]) => { ctx.beginPath(); ctx.arc(x, y + off, 3, 0, Math.PI * 2); ctx.fillStyle = col; ctx.fill(); });
        pillC(ctx, (x1 + x2) / 2, (y1 + y2) / 2 + off + (v.tipo === 'bajista' ? -14 : 14), narrow ? `Div. ${v.tipo}` : `Div. ${v.tipo} · ${v.names.join(' + ')}`, col, true, 'middle', w);
        ctx.globalAlpha = 1;
      });
    }
    if (L.ondas && d.giros.length) {
      ctx.globalAlpha = dimA('ondas');
      ctx.setLineDash([1, 4]); ctx.lineCap = 'round'; ctx.strokeStyle = alpha(P.fg, 0.4); ctx.lineWidth = 1.2; ctx.beginPath();
      d.giros.forEach((g, i) => { const x = X(g.t), y = Y(g.p); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke(); ctx.setLineDash([]);
      const circle = (x, y, txt, dashed) => {
        ctx.beginPath(); ctx.arc(x, y, 7.5, 0, Math.PI * 2); ctx.fillStyle = P.panel; ctx.fill();
        ctx.setLineDash(dashed ? [2.5, 2] : []); ctx.strokeStyle = alpha(P.fg, 0.6); ctx.lineWidth = 1; ctx.stroke(); ctx.setLineDash([]);
        ctx.font = `700 9px ${P.font}`; ctx.fillStyle = P.fg; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(txt, x, y + 0.5);
      };
      const lastG = d.giros[d.giros.length - 1];
      d.giros.filter((g) => g.w).forEach((g) => circle(X(g.t), Math.max(12, Math.min(h - 12, Y(g.p) + (g.alto ? -13 : 13))), g.w, d.ondaCur && g === lastG && g.w === d.ondaCur));
      if (d.ondaCur && lastG && lastG.w && lastG.w !== d.ondaCur && d.live) {
        const x1 = X(d.lastT + Math.min(Math.max(d.futN, 3), 8) * d.tfMs), y1 = d.ondaObj === null ? Y(d.price) : Math.max(12, Math.min(h - 12, Y(d.ondaObj)));
        ctx.setLineDash([4, 4]); ctx.strokeStyle = alpha(P.fg, 0.5); ctx.lineWidth = 1.2; ctx.beginPath();
        ctx.moveTo(X(lastG.t), Y(lastG.p)); ctx.lineTo(X(d.lastT), Y(d.price)); ctx.lineTo(x1, y1); ctx.stroke(); ctx.setLineDash([]);
        circle(x1, y1, d.ondaCur, true);
      }
      ctx.globalAlpha = 1;
    }
    // liquidaciones: barras horizontales pegadas al eje de precios (rojas: longs que se liquidan si baja; verdes: shorts si sube)
    G.liqW = 0;
    if (L.liq && d.liq.length) {
      const lw = Math.min(narrow ? 46 : 80, w * 0.13), inR = d.liq.map((r) => ({ ...r, y: Y(r.p) })).filter((r) => r.y !== null && r.y > 0 && r.y < h);
      const mx = Math.max(1, ...inR.map((r) => Math.max(r.l, r.s)));
      const bh = Math.max(2, Math.abs(Y(d.price) - Y(d.price * 1.0025)) - 1);
      G.liqW = lw;
      ctx.globalAlpha = dimA('liq');
      inR.forEach((r) => [[r.l, P.dn], [r.s, P.up]].forEach(([v, c]) => {
        if (!(v > 0)) return;
        const bw = Math.max(3, Math.sqrt(v / mx) * (lw - 6));
        ctx.fillStyle = alpha(c, 0.12 + 0.55 * v / mx); ctx.fillRect(w - bw, r.y - bh / 2, bw, bh);
      }));
      ctx.font = `600 9.5px ${P.font}`; ctx.fillStyle = P.mute; ctx.textAlign = 'right'; ctx.textBaseline = 'top';
      ctx.fillText('LIQUID.', w - 3, narrow ? 54 : 40);
      ctx.globalAlpha = 1;
    }
    if (G.med) drawMed(ctx, w, h);
  }

  // la regla: caja entre los dos puntos, flecha y cuanto cambio (%, precio, velas y tiempo)
  function drawMed(ctx, w, h) {
    const m = G.med, ts = G.chart.timeScale(), P = G.P;
    const x1 = ts.logicalToCoordinate(m.a.l), x2 = ts.logicalToCoordinate(m.b.l), y1 = Y(m.a.p), y2 = Y(m.b.p);
    if ([x1, x2, y1, y2].some((v) => v === null)) return;
    const ch = (m.b.p / m.a.p - 1) * 100, col = ch >= 0 ? P.up : P.dn, n = Math.round(m.b.l - m.a.l);
    ctx.fillStyle = alpha(col, 0.13); ctx.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
    ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.setLineDash([]);
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    const ang = Math.atan2(y2 - y1, x2 - x1);
    ctx.beginPath(); ctx.moveTo(x2, y2);
    ctx.lineTo(x2 - 8 * Math.cos(ang - 0.45), y2 - 8 * Math.sin(ang - 0.45)); ctx.lineTo(x2 - 8 * Math.cos(ang + 0.45), y2 - 8 * Math.sin(ang + 0.45));
    ctx.closePath(); ctx.fillStyle = col; ctx.fill();
    [[m.a, x1, y1], [m.b, x2, y2]].forEach(([q, x, y]) => {
      if (!q.iman) return;
      ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fillStyle = col; ctx.fill();
      ctx.strokeStyle = P.panel; ctx.lineWidth = 2; ctx.stroke();
    });
    const mins = Math.abs(n) * TF_MIN[S.tf];
    const txt = `${sg(ch)} · ${m.b.p >= m.a.p ? '+' : '−'}${fp(Math.abs(m.b.p - m.a.p))} · ${Math.abs(n)} velas${mins ? ` · ${dur(mins)}` : ''}`;
    pillC(ctx, x2, Math.max(14, Math.min(h - 14, y2 + (y2 < y1 ? -16 : 16))), txt, col, true, 'middle', w);
  }

  // en los paneles de RSI y MACD: la franja 30-70 y las divergencias marcadas tambien en el indicador
  function drawOsc(name, s) {
    return (ctx, w) => {
      const d = G.d, P = G.P; if (!d) return;
      if (name === 'RSI') {
        const a = Y(70, s), b = Y(30, s);
        if (a !== null && b !== null) { ctx.fillStyle = alpha(P.c2, 0.06); ctx.fillRect(0, a, w, b - a); }
      }
      if (!S.layers.patrones) return;
      d.divs.forEach((v) => {
        const z = v.ind[name]; if (!z) return;
        const col = v.tipo === 'alcista' ? P.up : P.dn, x1 = X(z.t1), x2 = X(z.t2), y1 = Y(z.v1, s), y2 = Y(z.v2, s);
        if (y1 === null || y2 === null) return;
        ctx.globalAlpha = dimA(v.key); ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.lineCap = 'round';
        ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
        [[x1, y1], [x2, y2]].forEach(([x, y]) => { ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fillStyle = col; ctx.fill(); });
        ctx.globalAlpha = 1;
      });
    };
  }

  // con el dedo, el motor no estira el eje de precios: arrastrar arriba/abajo sobre el eje lo comprime o lo estira
  // (como en TradingView) y un doble toque lo vuelve a ajustar solo. Vale para el precio y para RSI y MACD.
  function axisTouch(box) {
    if (box.abAxisTouch) return;                       // el contenedor queda; el grafico se rehace adentro
    box.abAxisTouch = true;
    let t = null, lastTap = 0;
    const paneAt = (y) => {
      let top = 0;
      const n = G.chart.panes().length;
      for (let k = 0; k < n; k++) { const h = G.chart.paneSize(k).height; if (y < top + h) return k; top += h + 1; }
      return -1;
    };
    box.addEventListener('touchstart', (e) => {
      if (!G.chart || e.touches.length !== 1) { t = null; return; }
      const r = box.getBoundingClientRect(), x = e.touches[0].clientX - r.left, y = e.touches[0].clientY - r.top;
      if (x < G.chart.paneSize(0).width) { t = null; return; }
      const k = paneAt(y); if (k < 0) { t = null; return; }
      const ps = G.chart.panes()[k].priceScale('right'), vr = ps.getVisibleRange();
      if (!vr) { t = null; return; }
      const now = Date.now();
      if (now - lastTap < 320) { ps.setAutoScale(true); t = null; lastTap = 0; e.preventDefault(); return; }
      lastTap = now;
      t = { y: e.touches[0].clientY, ps, from: vr.from, to: vr.to };
      e.preventDefault();
    }, { passive: false, capture: true });
    box.addEventListener('touchmove', (e) => {
      if (!t) return;
      e.preventDefault(); e.stopPropagation();
      const f = Math.exp((e.touches[0].clientY - t.y) * 0.006), mid = (t.from + t.to) / 2, half = (t.to - t.from) / 2 * f;
      t.ps.setVisibleRange({ from: mid - half, to: mid + half });
    }, { passive: false, capture: true });
    const end = () => { t = null; };
    box.addEventListener('touchend', end, { capture: true });
    box.addEventListener('touchcancel', end, { capture: true });
  }

  // la regla: el arrastre se toma antes que el motor del grafico (asi no mueve la vista) y solo en el panel del precio
  function medirInput(box) {
    if (box.abMedir) return;                           // el contenedor queda; el grafico se rehace adentro
    box.abMedir = true;
    box.addEventListener('pointerenter', (e) => { if (e.pointerType === 'mouse') G.hoverBox = true; });
    box.addEventListener('pointerleave', (e) => { if (e.pointerType === 'mouse') G.hoverBox = false; });
    let on = false, tapada = false;
    const punto = (e) => {
      const r = box.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
      try {
        const ps = G.chart.paneSize(0);
        if (x < 0 || x > ps.width || y < 0 || y > ps.height) return null;
        const l = G.chart.timeScale().coordinateToLogical(x), p = G.c.coordinateToPrice(y);
        if (l === null || p === null) return null;
        return S.iman !== (e.ctrlKey || e.metaKey) ? pegar(l, y) || { l, p } : { l, p };
      } catch (err) { return null; }            // el grafico se esta rehaciendo
    };
    // la vela mas cercana (tambien las del escenario, a la derecha) y su apertura, maximo, minimo o cierre mas cerca en pixeles
    const pegar = (l, y) => {
      const d = G.d, k = Math.round(l);
      const b = k >= 0 && k < d.all.length ? d.all[k] : d.ghosts.find((g) => g.k === k - d.lastIdx);
      if (!b) return null;
      const p = [b.o, b.h, b.l, b.c].reduce((m, v) => (Math.abs(Y(v) - y) < Math.abs(Y(m) - y) ? v : m));
      return { l: k, p, iman: true };
    };
    const bloquear = (e) => { if (tapada) { e.preventDefault(); e.stopPropagation(); } };
    box.addEventListener('pointerdown', (e) => {
      tapada = false;
      if (!G.chart || e.button !== 0 || (e.target.closest && e.target.closest('.ab-dib-bar'))) return;
      const quiere = S.medir || (e.shiftKey && e.pointerType === 'mouse');
      if (!quiere) { if (G.med) { G.med = null; G.over.update(); } return; }   // un clic normal borra la medicion
      const pt = punto(e); if (!pt) return;
      on = true; tapada = true; G.med = { a: pt, b: pt };
      e.preventDefault(); e.stopPropagation(); G.over.update();
    }, { capture: true });
    // el motor escucha mousedown y touchstart: tambien se frenan mientras se mide
    ['mousedown', 'touchstart'].forEach((ev) => box.addEventListener(ev, bloquear, { capture: true, passive: false }));
    window.addEventListener('pointermove', (e) => {
      if (!on) return;
      const pt = punto(e); if (pt) { G.med.b = pt; G.over.update(); }
    });
    const fin = () => {
      if (!on) return;
      on = false;
      if (G.med && Math.abs(G.med.b.l - G.med.a.l) < 0.3 && Math.abs(G.med.b.p - G.med.a.p) < 1e-12) { G.med = null; G.over.update(); }
    };
    window.addEventListener('pointerup', fin);
    window.addEventListener('pointercancel', fin);
  }

  // ---------- dibujar en el grafico: lineas horizontales, de tendencia, rayos y zonas, como en TradingView ----------
  // Se guardan por activo (en este telefono) con la hora en ms, asi se ven igual en cualquier temporalidad. Se
  // seleccionan tocandolas (o con clic): se mueven, se estiran de las puntas, cambian de color, se borran y las lineas
  // pueden avisar cuando el precio las toca (una vez; con voz si esta el modo radio).
  const DIB = { modo: false, herr: null, sel: null, nuevo: null, espera: false, lado: {}, todos: {} };
  try { DIB.todos = JSON.parse(localStorage.getItem('ab-dibujos')) || {}; } catch (e) { DIB.todos = {}; }
  const DIB_COL = ['#2962ff', '#f23645', '#089981', '#ff9800', '#9c27b0'];
  const DIB_NOM = { h: 'Línea horizontal', t: 'Línea de tendencia', r: 'Rayo', z: 'Zona' };
  const dibLista = () => DIB.todos[MON()] || (DIB.todos[MON()] = []);
  window.abDib = DIB;                                     // para las pruebas
  const dibGuardar = () => { try { localStorage.setItem('ab-dibujos', JSON.stringify(DIB.todos)); } catch (e) { /* sin almacenamiento */ } };
  const dibSel = () => dibLista().find((x) => x.id === DIB.sel) || null;
  const dibPint = () => { if (G.dib) G.dib.update(); dibBarra(); };
  // el precio de una linea en un momento (en escala log, la recta va en log, como se ve)
  function dibValor(d, t) {
    if (d.tipo === 'h') return d.a.p;
    if (d.b.t === d.a.t) return null;
    const f = (t - d.a.t) / (d.b.t - d.a.t);
    return S.log && d.a.p > 0 && d.b.p > 0 ? Math.exp(Math.log(d.a.p) + (Math.log(d.b.p) - Math.log(d.a.p)) * f) : d.a.p + (d.b.p - d.a.p) * f;
  }
  // puntas de la recta hasta el borde (rayo: desde a, pasando por b)
  function dibRayo(xa, ya, xb, yb, w, h) {
    const dx = xb - xa, dy = yb - ya; if (!dx && !dy) return [xb, yb];
    let k = 1e9;
    if (dx > 0) k = Math.min(k, (w - xa) / dx); else if (dx < 0) k = Math.min(k, -xa / dx);
    if (dy > 0) k = Math.min(k, (h - ya) / dy); else if (dy < 0) k = Math.min(k, -ya / dy);
    k = Math.max(1, k); return [xa + dx * k, ya + dy * k];
  }
  function drawDib(ctx, w, h) { drawDibCon(ctx, w, h, X, Y, true); }
  // xf / yf: de hora y precio a pixeles (el segundo grafico pasa los suyos; ahi no se editan)
  function drawDibCon(ctx, w, h, xf, yf, editable) {
    if (!G.d) return;
    const lista = dibLista().slice(); if (DIB.nuevo && editable) lista.push(DIB.nuevo);
    if (!lista.length) return;
    const fino = matchMedia('(pointer: coarse)').matches ? 6.5 : 4.5;
    ctx.save(); ctx.lineCap = 'round';
    lista.forEach((d) => {
      const sel = editable && (d.id === DIB.sel || d === DIB.nuevo), ya = yf(d.a.p), xa = xf(d.a.t);
      if (ya === null) return;
      ctx.strokeStyle = d.col; ctx.lineWidth = sel ? 2.2 : 1.5; ctx.setLineDash(d === DIB.nuevo && DIB.espera ? [5, 4] : []);
      const pts = [];
      if (d.tipo === 'h') {
        ctx.beginPath(); ctx.moveTo(0, Math.round(ya) + 0.5); ctx.lineTo(w, Math.round(ya) + 0.5); ctx.stroke();
        const txt = `${d.aviso ? '🔔 ' : ''}${fp(d.a.p)}`;
        ctx.font = `600 11px ${G.P.font}`; const tw = ctx.measureText(txt).width + 12;
        ctx.setLineDash([]); ctx.fillStyle = d.col; ctx.beginPath(); ctx.roundRect(w - tw - 4, ya - 9, tw, 18, 5); ctx.fill();
        ctx.fillStyle = '#fff'; ctx.textBaseline = 'middle'; ctx.textAlign = 'left'; ctx.fillText(txt, w - tw + 2, ya + 0.5);
        if (sel) pts.push([Math.min(w - tw - 16, Math.max(16, w * 0.5)), ya]);
      } else {
        const yb = yf(d.b.p), xb = xf(d.b.t); if (yb === null || xa === null || xb === null) return;
        if (d.tipo === 'z') {
          const x0 = Math.min(xa, xb), y0 = Math.min(ya, yb), ww = Math.abs(xb - xa), hh = Math.abs(yb - ya);
          ctx.fillStyle = alpha(d.col, sel ? 0.2 : 0.13); ctx.fillRect(x0, y0, ww, hh); ctx.strokeRect(x0 + 0.5, y0 + 0.5, ww, hh);
          const pc = (Math.max(d.a.p, d.b.p) / Math.min(d.a.p, d.b.p) - 1) * 100;
          if (ww > 46 && hh > 16) { ctx.font = `600 10.5px ${G.P.font}`; ctx.fillStyle = d.col; ctx.textBaseline = 'top'; ctx.textAlign = 'left'; ctx.fillText(`${f1(pc)}%`, x0 + 5, y0 + 4); }
          if (sel) pts.push([xa, ya], [xb, yb], [xa, yb], [xb, ya]);
        } else {
          const [xe, ye] = d.tipo === 'r' ? dibRayo(xa, ya, xb, yb, w, h) : [xb, yb];
          ctx.beginPath(); ctx.moveTo(xa, ya); ctx.lineTo(xe, ye); ctx.stroke();
          if (d.aviso) { ctx.font = '11px sans-serif'; ctx.textBaseline = 'bottom'; ctx.textAlign = 'center'; ctx.fillText('🔔', xb, yb - 6); }
          if (sel) pts.push([xa, ya], [xb, yb]);
        }
      }
      ctx.setLineDash([]);
      pts.forEach(([x, y]) => { ctx.beginPath(); ctx.arc(x, y, fino, 0, 2 * Math.PI); ctx.fillStyle = G.P.panel || '#fff'; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = d.col; ctx.stroke(); });
    });
    ctx.restore();
  }
  // que se toco: una punta de la seleccionada, o el cuerpo de alguna (la de arriba primero)
  function dibHit(x, y, tol) {
    const ps = G.chart.paneSize(0), w = ps.width, h = ps.height, lista = dibLista();
    const s = dibSel();
    if (s && s.tipo !== 'h') {
      const xa = X(s.a.t), ya = Y(s.a.p), xb = X(s.b.t), yb = Y(s.b.p);
      const pts = [['a', xa, ya], ['b', xb, yb]];
      if (s.tipo === 'z') pts.push(['ab', xa, yb], ['ba', xb, ya]);
      for (const [k, px, py] of pts) if (px !== null && py !== null && Math.hypot(px - x, py - y) <= tol + 3) return { d: s, k };
    }
    const dSeg = (x1, y1, x2, y2) => { const dx = x2 - x1, dy = y2 - y1, L = dx * dx + dy * dy; const u = L ? Math.max(0, Math.min(1, ((x - x1) * dx + (y - y1) * dy) / L)) : 0; return Math.hypot(x - x1 - u * dx, y - y1 - u * dy); };
    for (let i = lista.length - 1; i >= 0; i--) {
      const d = lista[i], ya = Y(d.a.p); if (ya === null) continue;
      if (d.tipo === 'h') { if (Math.abs(y - ya) <= tol) return { d, k: 'cuerpo' }; continue; }
      const xa = X(d.a.t), xb = X(d.b.t), yb = Y(d.b.p); if (xa === null || xb === null || yb === null) continue;
      if (d.tipo === 'z') {
        const x0 = Math.min(xa, xb) - tol, x1 = Math.max(xa, xb) + tol, y0 = Math.min(ya, yb) - tol, y1 = Math.max(ya, yb) + tol;
        if (x >= x0 && x <= x1 && y >= y0 && y <= y1) return { d, k: 'cuerpo' }; continue;
      }
      const [xe, ye] = d.tipo === 'r' ? dibRayo(xa, ya, xb, yb, w, h) : [xb, yb];
      if (dSeg(xa, ya, xe, ye) <= tol) return { d, k: 'cuerpo' };
    }
    return null;
  }
  // barras flotantes: herramientas (con "Dibujar" prendido) y lo de la seleccionada (color, aviso, borrar)
  function dibArmarBarras() {
    if (DIB.bar) return;
    const ico = {
      h: '<path d="M3 12h18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
      t: '<path d="M4 19 20 5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="4" cy="19" r="2.2" fill="currentColor"/><circle cx="20" cy="5" r="2.2" fill="currentColor"/>',
      r: '<path d="M4 19 21 4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="4" cy="19" r="2.2" fill="currentColor"/><path d="m15 4 6 0 0 6" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
      z: '<rect x="4" y="7" width="16" height="10" rx="1.5" stroke="currentColor" stroke-width="2" fill="currentColor" fill-opacity=".18"/>',
    };
    const svg = (p) => `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">${p}</svg>`;
    DIB.bar = el('div', 'ab-dib-bar'); DIB.bar.setAttribute('role', 'toolbar'); DIB.bar.setAttribute('aria-label', 'Herramientas de dibujo'); DIB.bar.hidden = true;
    Object.keys(ico).forEach((k) => { const b = el('button', 'ab-dib-b'); b.type = 'button'; b.dataset.h = k; b.innerHTML = svg(ico[k]); b.title = DIB_NOM[k]; b.setAttribute('aria-label', DIB_NOM[k]); b.setAttribute('aria-pressed', 'false'); DIB.bar.append(b); });
    const borrarT = el('button', 'ab-dib-b ab-dib-txt', 'Borrar todo'); borrarT.type = 'button'; borrarT.dataset.acc = 'todo';
    const listo = el('button', 'ab-dib-b ab-dib-txt ab-dib-listo', 'Listo'); listo.type = 'button'; listo.dataset.acc = 'listo';
    DIB.bar.append(el('span', 'ab-dib-sep'), borrarT, listo);
    DIB.bar.addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.dataset.h) { DIB.herr = DIB.herr === b.dataset.h ? null : b.dataset.h; DIB.nuevo = null; DIB.espera = false; DIB.sel = null; dibPint(); return; }
      if (b.dataset.acc === 'listo') { setDib(false); return; }
      if (b.dataset.acc === 'todo') {
        if (!dibLista().length) return;
        if (b.dataset.seguro !== '1') { b.dataset.seguro = '1'; b.textContent = '¿Borrar todas?'; setTimeout(() => { b.dataset.seguro = ''; b.textContent = 'Borrar todo'; }, 2500); return; }
        DIB.todos[MON()] = []; DIB.sel = null; dibGuardar(); b.dataset.seguro = ''; b.textContent = 'Borrar todo'; dibPint();
      }
    });
    DIB.selBar = el('div', 'ab-dib-bar ab-dib-sel'); DIB.selBar.hidden = true; DIB.selBar.setAttribute('role', 'toolbar'); DIB.selBar.setAttribute('aria-label', 'Dibujo seleccionado');
    DIB_COL.forEach((c) => { const b = el('button', 'ab-dib-col'); b.type = 'button'; b.dataset.col = c; b.style.background = c; b.setAttribute('aria-label', `Color ${c}`); DIB.selBar.append(b); });
    const av = el('button', 'ab-dib-b ab-dib-txt', 'Avisar'); av.type = 'button'; av.dataset.acc = 'aviso'; av.title = 'Avisar cuando el precio toque la línea (una vez)';
    const del = el('button', 'ab-dib-b ab-dib-txt', 'Borrar'); del.type = 'button'; del.dataset.acc = 'borrar';
    DIB.selBar.append(el('span', 'ab-dib-sep'), av, del);
    DIB.selBar.addEventListener('click', (e) => {
      const b = e.target.closest('button'), d = dibSel(); if (!b || !d) return;
      if (b.dataset.col) { d.col = b.dataset.col; DIB.ultCol = d.col; }
      else if (b.dataset.acc === 'borrar') { DIB.todos[MON()] = dibLista().filter((x) => x !== d); DIB.sel = null; }
      else if (b.dataset.acc === 'aviso') {
        d.aviso = !d.aviso; delete DIB.lado[d.id];
        if (d.aviso && 'Notification' in window && Notification.permission === 'default') Notification.requestPermission().catch(() => {});
      }
      dibGuardar(); dibPint();
    });
  }
  function dibBarra() {
    if (!DIB.bar) return;
    DIB.bar.hidden = !DIB.modo;
    [...DIB.bar.querySelectorAll('[data-h]')].forEach((b) => b.setAttribute('aria-pressed', String(DIB.herr === b.dataset.h)));
    const d = dibSel(); DIB.selBar.hidden = !d;
    DIB.selBar.classList.toggle('ab-dib-sola', !DIB.modo);
    if (d) {
      [...DIB.selBar.querySelectorAll('[data-col]')].forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.col === d.col)));
      const av = DIB.selBar.querySelector('[data-acc="aviso"]'); av.hidden = d.tipo === 'z'; av.setAttribute('aria-pressed', String(!!d.aviso)); av.textContent = d.aviso ? 'Avisa' : 'Avisar';
    }
    if (DIB.box) { DIB.box.classList.toggle('is-dibujando', !!DIB.herr); DIB.box.style.touchAction = DIB.herr ? 'none' : ''; }
  }
  const dibBtn = document.getElementById('dib-btn');
  function setDib(on) {
    DIB.modo = on; if (!on) { DIB.herr = null; DIB.nuevo = null; DIB.espera = false; }
    dibBtn.setAttribute('aria-pressed', String(on)); dibPint();
  }
  dibBtn.addEventListener('click', () => setDib(!DIB.modo));
  // teclado: Escape cancela/suelta, Suprimir borra la seleccionada, D prende y apaga (antes que los otros atajos)
  window.addEventListener('keydown', (e) => {
    const tg = e.target || {}; if (/^(INPUT|TEXTAREA|SELECT)$/.test(tg.tagName || '') || tg.isContentEditable || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'Escape' && (DIB.herr || DIB.sel || DIB.modo)) {
      if (DIB.nuevo || DIB.herr) { DIB.nuevo = null; DIB.espera = false; DIB.herr = null; } else if (DIB.sel) DIB.sel = null; else setDib(false);
      dibPint(); e.stopImmediatePropagation(); e.preventDefault();
    } else if ((e.key === 'Delete' || e.key === 'Backspace') && DIB.sel) {
      DIB.todos[MON()] = dibLista().filter((x) => x.id !== DIB.sel); DIB.sel = null; dibGuardar(); dibPint(); e.preventDefault(); e.stopImmediatePropagation();
    } else if (e.key.toLowerCase() === 'd' && (G.hoverBox || S.fs)) { setDib(!DIB.modo); e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
  function dibInput(box) {
    dibArmarBarras(); DIB.box = box;
    box.append(DIB.bar, DIB.selBar); dibBarra();
    if (box.abDib) return;
    box.abDib = true;
    let drag = null;
    const local = (e) => { const r = box.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    const enPanel = (x, y) => { try { const ps = G.chart.paneSize(0); return x >= 0 && x <= ps.width && y >= 0 && y <= ps.height; } catch (err) { return false; } };
    const tol = (e) => (e.pointerType === 'mouse' ? 7 : 16);
    // un punto del grafico: hora de la vela mas cercana (tambien en el futuro) y el precio; con el iman, pegado a la vela
    const punto = (x, y, e, libre) => {
      const d = G.d, l = G.chart.timeScale().coordinateToLogical(x), p = G.c.coordinateToPrice(y);
      if (l === null || p === null) return null;
      const k = Math.round(l), b = k >= 0 && k < d.all.length ? d.all[k] : null;
      const pp = !libre && b && S.iman !== !!(e.ctrlKey || e.metaKey) ? [b.o, b.h, b.l, b.c].reduce((m, v) => (Math.abs(Y(v) - y) < Math.abs(Y(m) - y) ? v : m)) : p;
      return { t: d.t0 + k * d.tfMs, p: pp };
    };
    const terminar = () => {
      const n = DIB.nuevo; DIB.nuevo = null; DIB.espera = false; DIB.herr = null;
      if (n && (n.tipo === 'h' || n.a.t !== n.b.t || n.a.p !== n.b.p)) { dibLista().push(n); DIB.sel = n.id; dibGuardar(); }
      dibPint();
    };
    box.addEventListener('pointerdown', (e) => {
      if (!G.chart || !G.d || e.button !== 0 || S.medir || (e.target.closest && e.target.closest('.ab-dib-bar'))) return;
      const [x, y] = local(e); if (!enPanel(x, y)) return;
      const tomar = () => { e.preventDefault(); e.stopImmediatePropagation(); try { box.setPointerCapture(e.pointerId); } catch (err) { /* ya no esta */ } };
      if (DIB.herr) {                                       // dibujando: el primer toque fija la punta (o el segundo, si fue un toque)
        const pt = punto(x, y, e); if (!pt) return;
        if (DIB.nuevo && DIB.espera) { DIB.nuevo.b = pt; drag = { k: 'crear', x, y }; tomar(); G.dib.update(); return; }
        DIB.nuevo = { id: `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`, tipo: DIB.herr, a: pt, b: { ...pt }, col: DIB.ultCol || DIB_COL[0], aviso: false };
        drag = { k: 'crear', x, y }; tomar(); G.dib.update(); return;
      }
      const hit = dibHit(x, y, tol(e));
      if (!hit) { if (DIB.sel) { DIB.sel = null; dibPint(); } return; }
      DIB.sel = hit.d.id;
      const d = hit.d;
      drag = { k: hit.k, d, a0: { ...d.a }, b0: { ...d.b }, l0: G.chart.timeScale().coordinateToLogical(x), p0: G.c.coordinateToPrice(y), y0: Y(d.a.p) - y, movio: false };
      tomar(); dibPint();
    }, { capture: true });
    const bloquear = (e) => { if (drag) { e.preventDefault(); e.stopImmediatePropagation(); } };
    ['mousedown', 'touchstart', 'touchmove'].forEach((ev) => box.addEventListener(ev, bloquear, { capture: true, passive: false }));
    window.addEventListener('pointermove', (e) => {
      if (!G.chart || !G.d) return;
      const [x, y] = local(e);
      if (!drag) {
        if (e.pointerType !== 'mouse') return;
        if (DIB.nuevo && DIB.espera) { const pt = punto(x, y, e); if (pt) { DIB.nuevo.b = pt; G.dib.update(); } return; }
        const h = !DIB.herr && enPanel(x, y) ? dibHit(x, y, 7) : null;
        const c = DIB.herr ? 'crosshair' : h ? (h.k === 'cuerpo' ? 'move' : 'grab') : '';
        if (box.style.cursor !== c && (c || box.dataset.dibCursor)) { box.style.cursor = c; box.dataset.dibCursor = c ? '1' : ''; }
        return;
      }
      e.preventDefault();
      if (drag.k === 'crear') {
        const pt = punto(x, y, e); if (!pt) return;
        if (DIB.nuevo.tipo === 'h') DIB.nuevo.a = pt; else DIB.nuevo.b = pt;
        G.dib.update(); return;
      }
      const d = drag.d; drag.movio = true;
      if (drag.k === 'cuerpo') {
        const l = G.chart.timeScale().coordinateToLogical(x), p = G.c.coordinateToPrice(y);
        if (l === null || p === null || drag.l0 === null || drag.p0 === null) return;
        if (d.tipo === 'h') {                               // la horizontal se pega a la vela con el iman
          const pt = punto(x, y + drag.y0, e); if (pt) d.a = { t: drag.a0.t, p: pt.p };
        } else {
          const dt = Math.round(l - drag.l0) * G.d.tfMs, dp = p - drag.p0;
          d.a = { t: drag.a0.t + dt, p: drag.a0.p + dp }; d.b = { t: drag.b0.t + dt, p: drag.b0.p + dp };
        }
      } else {
        const pt = punto(x, y, e); if (!pt) return;
        if (drag.k === 'ab') { d.a = { t: pt.t, p: d.a.p }; d.b = { t: d.b.t, p: pt.p }; }
        else if (drag.k === 'ba') { d.b = { t: pt.t, p: d.b.p }; d.a = { t: d.a.t, p: pt.p }; }
        else d[drag.k] = pt;
      }
      delete DIB.lado[d.id];
      G.dib.update();
    }, { passive: false });
    const soltar = () => {
      if (!drag) return;
      const k = drag.k; drag = null;
      if (k === 'crear') {
        const n = DIB.nuevo; if (!n) return;
        // toque sin arrastrar en una de dos puntas: queda esperando la segunda (con el mouse se ve venir; en el celu, al tocar)
        const sinMover = n.tipo !== 'h' && Math.abs(X(n.b.t) - X(n.a.t)) < 6 && Math.abs(Y(n.b.p) - Y(n.a.p)) < 6;
        if (sinMover && !DIB.espera) { DIB.espera = true; G.dib.update(); return; }
        terminar(); return;
      }
      dibGuardar(); dibPint();
    };
    window.addEventListener('pointerup', soltar);
    window.addEventListener('pointercancel', soltar);
  }
  // aviso cuando el precio cruza una linea con la campanita (una vez; despues se apaga sola)
  function dibAvisos(precio) {
    if (!(precio > 0)) return;
    const ahora = Date.now(); let cambio = false;
    dibLista().forEach((d) => {
      if (!d.aviso || d.tipo === 'z') return;
      if (d.tipo !== 'h' && ahora < Math.min(d.a.t, d.b.t)) return;
      const v = dibValor(d, ahora); if (!(v > 0)) return;
      const lado = Math.sign(precio - v), antes = DIB.lado[d.id];
      DIB.lado[d.id] = lado || antes;
      if (antes === undefined || !lado || lado === antes) return;
      d.aviso = false; cambio = true;
      const txt = `${MON()} tocó tu ${DIB_NOM[d.tipo].toLowerCase()} en ${fp(v)}`;
      avisoApp(txt, d.col);
    });
    if (cambio) { dibGuardar(); dibPint(); }
  }
  // un aviso en la app (y en el sistema si diste permiso; con voz si esta el modo radio)
  function avisoApp(txt, col) {
    let t = document.getElementById('ab-toast');
    if (!t) { t = el('div', 'ab-toast'); t.id = 'ab-toast'; t.setAttribute('role', 'status'); document.body.append(t); }
    t.textContent = txt; t.style.setProperty('--toast-col', col || 'var(--senal)'); t.classList.add('on');
    clearTimeout(t.abT); t.abT = setTimeout(() => t.classList.remove('on'), 7000);
    try { navigator.vibrate && navigator.vibrate([120, 60, 120]); } catch (e) { /* sin vibracion */ }
    try {
      const ac = new (window.AudioContext || window.webkitAudioContext)(), o = ac.createOscillator(), g = ac.createGain();
      o.frequency.value = 880; g.gain.setValueAtTime(0.0001, ac.currentTime); g.gain.exponentialRampToValueAtTime(0.18, ac.currentTime + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + 0.5);
      o.connect(g).connect(ac.destination); o.start(); o.stop(ac.currentTime + 0.55); setTimeout(() => ac.close(), 800);
    } catch (e) { /* sin sonido */ }
    if ('Notification' in window && Notification.permission === 'granted' && document.hidden) {
      const n = { body: txt, icon: 'icono-192.png', tag: 'ab-dibujo' };
      (navigator.serviceWorker && navigator.serviceWorker.controller ? navigator.serviceWorker.ready.then((r) => r.showNotification('Analista BTC', n)) : Promise.resolve(new Notification('Analista BTC', n))).catch(() => {});
    }
    if (window.abVoz) window.abVoz(txt);
  }

  // ---------- varios graficos: la misma moneda en otras temporalidades (2 o 4 a la vez) ----------
  // Usan las velas que ya trae el analisis (5m a 1D: sin pedir nada mas), se mueven con el precio en vivo, muestran tus
  // dibujos y la mira va sincronizada en todos (la vela que contiene ese momento). En la compu van lado a lado (2) o en
  // 2 x 2 (4) y el analisis pasa abajo, en dos columnas; en el celu, uno debajo del otro. Queda guardado.
  const MG = { n: 1, tfs: ['4h', '1d', '15m'], sec: [] };
  try {
    const g = JSON.parse(localStorage.getItem('ab-multi') || 'null');
    if (g) { MG.n = [1, 2, 4].includes(g.n) ? g.n : g.on ? 2 : 1; if (Array.isArray(g.tfs)) g.tfs.forEach((t, i) => { if (i < 3 && t) MG.tfs[i] = t; }); else if (g.tf) MG.tfs[0] = g.tf; }
  } catch (e) { /* sin almacenamiento */ }
  const MG_TFS = ['5m', '15m', '30m', '1h', '4h', '1d'], MG_MS = { '5m': 3e5, '15m': 9e5, '30m': 18e5, '1h': 36e5, '4h': 144e5, '1d': 864e5 };
  const MG_TXT = { '5m': '5m', '15m': '15m', '30m': '30m', '1h': '1h', '4h': '4h', '1d': '1D' };
  const mgGuardar = () => { try { localStorage.setItem('ab-multi', JSON.stringify({ n: MG.n, tfs: MG.tfs })); } catch (e) { /* idem */ } };
  const mgVis = () => MG.sec.filter((s) => s.i < MG.n - 1);
  MG.sec = [0, 1, 2].map((i) => {
    const box = el('div', 'ab-chart2'); box.id = `chart${i + 2}-box`; box.hidden = true;
    const h = el('div', 'ab-chart2-h'), leg = el('span', 'ab-chart2-leg'), nav = el('nav', 'ab-chart2-tfs'), c = el('div', 'ab-chart2-c');
    nav.setAttribute('aria-label', `Temporalidad del gráfico ${i + 2}`);
    MG_TFS.forEach((tf) => { const b = el('button', 'ab-chipbtn', MG_TXT[tf]); b.type = 'button'; b.dataset.tf = tf; nav.append(b); });
    h.append(leg, nav); box.append(h, c);
    const sec = { i, box, c, leg, nav, ch: null, s: null, bars: [], key: '', tema: '' };
    nav.addEventListener('click', (e) => { const b = e.target.closest('[data-tf]'); if (!b) return; MG.tfs[i] = b.dataset.tf; mgGuardar(); sec.key = ''; mgPintarUno(sec, true); });
    return sec;
  });
  { let ant = document.getElementById('chart'); MG.sec.forEach((s) => { ant.after(s.box); ant = s.box; }); }
  // controles: el grupo 1 / 2 / 4 (en Capas) y el boton de la barra (en la compu) que pasa de uno al otro
  const mgSeg = document.getElementById('multi-seg'), mgBtn = document.getElementById('multi-btn');
  const MG_ICO = { 1: '<rect x="4" y="5" width="16" height="14" rx="2"/>', 2: '<rect x="3" y="5" width="8" height="14" rx="1.5"/><rect x="13" y="5" width="8" height="14" rx="1.5"/>',
    4: '<rect x="3" y="4" width="8" height="7" rx="1.5"/><rect x="13" y="4" width="8" height="7" rx="1.5"/><rect x="3" y="13" width="8" height="7" rx="1.5"/><rect x="13" y="13" width="8" height="7" rx="1.5"/>' };
  function mgControles() {
    [...mgSeg.querySelectorAll('[data-n]')].forEach((b) => b.setAttribute('aria-pressed', String(+b.dataset.n === MG.n)));
    mgBtn.innerHTML = `<svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8">${MG_ICO[MG.n]}</svg>`;
    mgBtn.setAttribute('aria-label', `Gráficos a la vez: ${MG.n} (tocá para cambiar)`); mgBtn.title = `Gráficos a la vez: ${MG.n} → ${MG.n === 1 ? 2 : MG.n === 2 ? 4 : 1}`;
    mgBtn.setAttribute('aria-pressed', String(MG.n > 1));
  }
  mgSeg.addEventListener('click', (e) => { const b = e.target.closest('[data-n]'); if (b) mgPoner(+b.dataset.n); });
  mgBtn.addEventListener('click', () => mgPoner(MG.n === 1 ? 2 : MG.n === 2 ? 4 : 1));
  function mgPoner(n) {
    MG.n = n; mgGuardar(); mgControles();
    const h = document.documentElement;
    if (n > 1 && typeof altoGraf !== 'undefined' && altoGraf) h.style.setProperty('--graf-fijo', `${Math.round(altoGraf)}px`);
    h.classList.toggle('ab-multi', n > 1); h.classList.toggle('ab-multi-4', n === 4);
    MG.sec.forEach((s) => { const v = s.i < n - 1; s.box.hidden = !v; if (!v && s.ch) { s.ch.remove(); s.ch = null; s.s = null; s.key = ''; } });
    m2Pintar(true);
    window.dispatchEvent(new Event('resize'));
  }
  const mgX = (s) => (t) => (s.ch && s.bars.length ? s.ch.timeScale().logicalToCoordinate((t - s.bars[0].t) / MG_MS[MG.tfs[s.i]]) : null);
  const mgY = (s) => (p) => (s.s && p !== null && p !== undefined ? s.s.priceToCoordinate(p) : null);
  // la mira en todos menos en el que se esta mirando (cada uno en su vela que contiene ese momento)
  function mgMira(desde, ms, precio) {
    MG.sec.forEach((s) => {
      if (s === desde || !s.ch || s.box.hidden || !s.bars.length) return;
      if (ms === null) { try { s.ch.clearCrosshairPosition(); } catch (e) { /* idem */ } mgLeyenda(s, null); return; }
      const m = MG_MS[MG.tfs[s.i]], t = Math.min(Math.floor(ms / m) * m, s.bars[s.bars.length - 1].t);
      try { s.ch.setCrosshairPosition(precio, T2(t), s.s); } catch (e) { /* fuera del rango */ }
      mgLeyenda(s, T2(t));
    });
    if (desde && G.chart && G.d) {
      if (ms === null) { try { G.chart.clearCrosshairPosition(); } catch (e) { /* idem */ } return; }
      const t1 = Math.min(Math.floor((ms - G.d.t0) / G.d.tfMs) * G.d.tfMs + G.d.t0, G.d.all[G.d.all.length - 1].t);
      try { G.chart.setCrosshairPosition(precio, T2(t1), G.c); } catch (e) { /* fuera del rango */ }
    }
  }
  function mgArmar(s) {
    const P = G.P || pal(), tema = `${P.up}${P.dn}${P.mute}|${!!S.layers.osc}|${!!S.layers.flujo}`;
    if (s.ch && s.tema === tema) return;
    if (s.ch) s.ch.remove();
    s.tema = tema; s.key = '';
    const cross = { color: alpha(P.mute, 0.7), width: 1, style: LW.LineStyle.Dashed, labelBackgroundColor: P.lbl };
    s.ch = LW.createChart(s.c, { autoSize: true, layout: { background: { type: 'solid', color: 'rgba(0,0,0,0)' }, textColor: P.mute, fontFamily: P.font, fontSize: 11, attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } }, crosshair: { mode: LW.CrosshairMode.Normal, vertLine: cross, horzLine: cross },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.08 }, minimumWidth: 58 },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 3, barSpacing: 6, minBarSpacing: 1 },
      localization: { locale: 'es-AR', timeFormatter: (t) => fmtSec(t) }, handleScroll: { vertTouchDrag: false }, kineticScroll: { touch: true, mouse: false } });
    const pf = { type: 'custom', formatter: (v) => fp(v), minMove: 0.0001 }, quiet = { lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false, priceFormat: pf };
    s.bbU = s.ch.addSeries(LW.LineSeries, { ...quiet, color: alpha(P.mute, 0.4), lineWidth: 1 });
    s.vwap = s.ch.addSeries(LW.LineSeries, { ...quiet, color: VWAP_COL, lineWidth: 1.5 });
    s.bbL = s.ch.addSeries(LW.LineSeries, { ...quiet, color: alpha(P.mute, 0.4), lineWidth: 1 });
    s.e20 = s.ch.addSeries(LW.LineSeries, { ...quiet, color: P.c0, lineWidth: 1 });
    s.e50 = s.ch.addSeries(LW.LineSeries, { ...quiet, color: P.c1, lineWidth: 1 });
    s.e200 = s.ch.addSeries(LW.LineSeries, { ...quiet, color: alpha(P.fg, 0.7), lineWidth: 2 });
    s.s = s.ch.addSeries(LW.CandlestickSeries, { priceFormat: pf, upColor: P.up, downColor: P.dn, borderVisible: false, wickUpColor: P.up, wickDownColor: P.dn, priceLineStyle: LW.LineStyle.Dotted, priceLineWidth: 1 });
    const xf = mgX(s), yf = mgY(s), sobre = mgOver(s);
    s.capaU = new Capa(mgUnder(s), 'bottom'); s.s.attachPrimitive(s.capaU);
    s.capa = new Capa((ctx, w, h) => { sobre(ctx, w, h); drawDibCon(ctx, w, h, xf, yf, false); }, 'top'); s.s.attachPrimitive(s.capa);
    s.marks = LW.createSeriesMarkers(s.s, []); s.plines = [];
    // RSI y MACD abajo, como en el principal (si esa capa esta prendida)
    s.rsi = s.hist = s.macd = s.sig = null;
    if (S.layers.osc) {
      s.rsi = s.ch.addSeries(LW.LineSeries, { priceFormat: { type: 'custom', formatter: (v) => f1(v), minMove: 0.1 }, color: P.c2, lineWidth: 1, priceLineVisible: false, crosshairMarkerVisible: false,
        autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) }, 1);
      [70, 30].forEach((v) => s.rsi.createPriceLine({ price: v, color: alpha(P.mute, 0.5), lineWidth: 1, lineStyle: LW.LineStyle.Dashed, axisLabelVisible: false }));
      const mf = { type: 'custom', formatter: (v) => (Math.abs(v) >= 100 ? f0(v) : Math.abs(v) >= 1 ? f1(v) : ar.format(',.4f')(v)), minMove: 0.0001 };
      s.hist = s.ch.addSeries(LW.HistogramSeries, { priceFormat: mf, lastValueVisible: false, priceLineVisible: false }, 2);
      s.macd = s.ch.addSeries(LW.LineSeries, { priceFormat: mf, color: P.c0, lineWidth: 1, priceLineVisible: false, crosshairMarkerVisible: false }, 2);
      s.sig = s.ch.addSeries(LW.LineSeries, { priceFormat: mf, color: P.c1, lineWidth: 1, priceLineVisible: false, crosshairMarkerVisible: false }, 2);
      try { const pn = s.ch.panes(); pn[0].setStretchFactor(3); pn[1].setStretchFactor(1); pn[2].setStretchFactor(1); } catch (e) { /* sin paneles */ }
    }
    s.fl = S.layers.flujo ? flujoPaneles(s.ch, S.layers.osc ? 3 : 1, P) : null;
    if (s.fl) try { const pn = s.ch.panes(); pn[0].setStretchFactor(3); pn.slice(1).forEach((p, i) => p.setStretchFactor(S.layers.osc && i < 2 ? 1 : 0.85)); } catch (e) { /* idem */ }
    s.ch.subscribeCrosshairMove((q) => {
      mgLeyenda(s, q && q.time !== undefined ? q.time : null);
      if (!q || !q.sourceEvent) return;
      if (q.time === undefined || !q.point) { mgMira(s, null, null); return; }
      const p = s.s.coordinateToPrice(q.point.y); if (p !== null) mgMira(s, (q.time - TZ) * 1000, p);
    });
  }
  // del principal a los demas
  function m2DesdeMain(q) {
    if (MG.n === 1 || !q || !q.sourceEvent) return;
    if (q.time === undefined || !q.point) { mgMira(null, null, null); return; }
    const p = G.c.coordinateToPrice(q.point.y); if (p !== null) mgMira(null, (q.time - TZ) * 1000, p);
  }
  function mgLeyenda(s, t) {
    if (!s.bars.length) { s.leg.textContent = ''; return; }
    const b = (t !== null && s.bars.find((x) => T2(x.t) === t)) || s.bars[s.bars.length - 1], ch = b.o ? (b.c / b.o - 1) * 100 : 0;
    s.leg.replaceChildren(el('b', '', `${MON()} · ${TF_TXT[MG.tfs[s.i]]}`), ` C ${fp(b.c)} `);
    const sp = el('span', '', `${ch >= 0 ? '+' : ''}${f1(ch)}%`); sp.style.color = ch >= 0 ? G.P.up : G.P.dn; s.leg.append(sp);
  }
  function mgPintarUno(s, ajustar) {
    if (s.box.hidden || !S.rows) return;
    mgArmar(s);
    const tf = MG.tfs[s.i];
    [...s.nav.children].forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.tf === tf)));
    const rows = pick(S.rows, 'vela', tf).map((r) => ({ t: num(r.t), o: num(r.o), h: num(r.h), l: num(r.l), c: num(r.c), e20: num(r.ema20), e50: num(r.ema50), e200: num(r.ema200),
      v: num(r.v), bu: num(r.bb_up), bl: num(r.bb_lo), rsi: num(r.rsi), macd: num(r.macd), sig: num(r.macd_senal), hist: num(r.macd_hist) }))
      .filter((b) => b.t !== null && b.c !== null).sort((a, b) => a.t - b.t);
    // la clave: velas nuevas, capas prendidas, y las lineas de precio y el fib del principal (si cambian, se rehacen)
    const capas = Object.keys(S.layers).filter((k) => S.layers[k]).join(','), extra = `${(G.plines || []).length}|${G.d && G.d.fib ? `${G.d.fib.a.t}${G.d.fib.b.p}` : ''}|${G.d ? G.d.dolor : ''}`;
    const key = `${MON()}|${tf}|${rows.length}|${rows.length ? rows[rows.length - 1].t : 0}|${capas}|${extra}`;
    if (key === s.key && !ajustar) { s.capa.update(); s.capaU.update(); return; }
    const nuevo = key.split('|').slice(0, 2).join('|') !== s.key.split('|').slice(0, 2).join('|');
    s.key = key; s.bars = rows;
    s.s.setData(rows.map((b) => ({ time: T2(b.t), open: b.o, high: b.h, low: b.l, close: b.c })));
    const linea = (k) => (S.layers.ema ? rows.filter((b) => b[k] !== null).map((b) => ({ time: T2(b.t), value: b[k] })) : []);
    s.e20.setData(linea('e20')); s.e50.setData(linea('e50')); s.e200.setData(linea('e200'));
    const lin = (k, on) => (on ? rows.filter((b) => b[k] !== null).map((b) => ({ time: T2(b.t), value: b[k] })) : []);
    s.bbU.setData(lin('bu', S.layers.bb)); s.bbL.setData(lin('bl', S.layers.bb));
    s.vwap.setData(S.layers.vp ? vwapSerie(rows, MG_MS[tf] / 6e4) : []);
    if (s.rsi) {
      s.rsi.setData(lin('rsi', true)); s.macd.setData(lin('macd', true)); s.sig.setData(lin('sig', true));
      s.hist.setData(rows.filter((b) => b.hist !== null).map((b) => ({ time: T2(b.t), value: b.hist, color: alpha(b.hist >= 0 ? G.P.up : G.P.dn, 0.45) })));
    }
    mgDatos(s, rows, tf); mgAbanico(s);
    if (s.fl) flujoSet(s.fl, flujoSeries(flujoDe(MON(), tf, () => { s.key = ''; mgPintarUno(s, false); }), rows, G.P));
    s.ch.timeScale().applyOptions({ rightOffset: S.layers.abanico ? 14 : 3 });
    s.capa.update(); s.capaU.update();
    if (nuevo || ajustar) { const n = rows.length, nb = Math.min(n, window.innerWidth < 600 ? 50 : 90); s.ch.timeScale().setVisibleLogicalRange({ from: n - nb, to: n + 2 }); }
    mgLeyenda(s, null);
  }
  // ---------- las capas del principal tambien en los otros graficos (cada uno con los datos de su temporalidad) ----------
  // Los datos se arman una sola vez por vela nueva o cambio de capas (s.capKey); lo que se dibuja en cada cuadro es poco.
  function mgDatos(s, bars, tf) {
    const L = S.layers, R = S.rows, byT = new Map(bars.map((b) => [b.t, b]));
    const dvg = {};
    if (L.patrones) pick(R, 'divergencia', tf).forEach((v) => {
      const k = `${v.t1}-${v.t2}-${v.tipo}`, g = (dvg[k] = dvg[k] || { tipo: v.tipo, t1: num(v.t1), t2: num(v.t2), p1: num(v.p1), p2: num(v.p2), names: [] });
      g.names.push(v.indicador);
    });
    s.cap = {
      byT, firstT: bars.length ? bars[0].t : 0, lastT: bars.length ? bars[bars.length - 1].t : 0, ms: MG_MS[tf],
      bb: L.bb ? bars.filter((b) => b.bu !== null).map((b) => ({ t: b.t, u: b.bu, l: b.bl })) : [],
      fvgs: L.fvg ? pick(R, 'fvg', tf).map((r) => ({ up: r.tipo === 'alcista', t: num(r.t), lo: num(r.bajo), hi: num(r.alto) })) : [],
      figs: L.patrones ? pick(R, 'patron', tf).filter((p) => p.clase === 'grafico') : [],
      divs: Object.values(dvg),
      giros: L.ondas ? pick(R, 'giro', tf).map((r) => ({ t: num(r.t), p: num(r.precio), w: r.onda, alto: r.tipo === 'alto' })).filter((g) => byT.has(g.t)) : [],
      icts: L.ict ? pick(R, 'ict', tf) : [],
    };
    // flechitas de patrones de velas (sin texto: el grafico es mas chico)
    s.marks.setMarkers(L.patrones ? pick(R, 'patron', tf).filter((p) => p.clase === 'vela' && byT.has(num(p.t))).map((p) => ({
      time: T2(num(p.t)), position: p.sesgo === 'alcista' ? 'belowBar' : 'aboveBar', color: colOf(p.sesgo),
      shape: p.sesgo === 'alcista' ? 'arrowUp' : p.sesgo === 'bajista' ? 'arrowDown' : 'circle' })).sort((a, b) => a.time - b.time) : []);
    // niveles del plazo y tu plan: las mismas lineas de precio que el principal
    (s.plines || []).forEach((pl) => { try { s.s.removePriceLine(pl); } catch (e) { /* ya no estaba */ } });
    s.plines = (G.plines || []).map((pl) => { try { return s.s.createPriceLine({ ...pl.options(), axisLabelVisible: true }); } catch (e) { return null; } }).filter(Boolean);
  }
  function mgUnder(s) {
    return (ctx, w, h) => {
      const c = s.cap, P = G.P, d = G.d; if (!c || !P) return;
      const xf = mgX(s), yf = mgY(s), half = Math.max(2, (s.ch.timeScale().options().barSpacing || 6) / 2);
      if (d && d.fib && d.fibs && d.fibs.length) {
        const xa = xf(d.fib.a.t), xb = xf(d.fib.b.t), x0 = Math.max(0, Math.min(xa === null ? 0 : xa, xb === null ? 0 : xb));
        ctx.save(); ctx.lineWidth = 1; ctx.setLineDash([2, 4]);
        if (x0 < w) d.fibs.forEach((f) => { const y = yf(f.p); if (y === null || y < 0 || y > h) return; ctx.strokeStyle = alpha(P.c2 || P.mute, f.extremo ? 0.6 : 0.35); ctx.beginPath(); ctx.moveTo(x0, Math.round(y) + 0.5); ctx.lineTo(w, Math.round(y) + 0.5); ctx.stroke(); });
        ctx.restore();
      }
      if (c.bb.length > 1) {
        ctx.beginPath(); c.bb.forEach((b, i) => { const x = xf(b.t), y = yf(b.u); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
        for (let i = c.bb.length - 1; i >= 0; i--) ctx.lineTo(xf(c.bb[i].t), yf(c.bb[i].l));
        ctx.closePath(); ctx.fillStyle = alpha(P.fg, 0.035); ctx.fill();
      }
      if (S.layers.libro) dibLibro(ctx, w, h, s.bars, MG_MS[MG.tfs[s.i]], xf, yf, half);
      if (S.layers.ict) dibIct(ctx, w, h, c.icts, xf, yf, P, half, true);
      if (S.layers.vp) dibPerfil(ctx, w, h, perfilVisible(s.ch, s.bars), yf, P, true);
      c.fvgs.forEach((z) => {
        const x0 = xf(z.t), yt = yf(z.hi), yb = yf(z.lo); if (x0 === null || yt === null || yb === null || x0 - half > w) return;
        ctx.fillStyle = alpha(z.up ? P.up : P.dn, 0.09); ctx.fillRect(x0 - half, yt, w - x0 + half, Math.max(2, yb - yt));
        ctx.fillStyle = alpha(z.up ? P.up : P.dn, 0.5); ctx.fillRect(x0 - half, yt, 1.5, Math.max(2, yb - yt));
      });
    };
  }
  function mgOver(s) {
    return (ctx, w, h) => {
      const c = s.cap, P = G.P, d = G.d, L = S.layers; if (!c || !P) return;
      const xf = mgX(s), yf = mgY(s);
      c.figs.forEach((p) => {
        const col = colOf(p.sesgo), conf = p.estado === 'confirmado';
        [1, 2].forEach((k) => {
          const t0 = num(p[`l${k}_t`]); if (t0 === null) return;
          const p0 = num(p[`l${k}_p`]), mm = num(p[`l${k}_m`]), val = (t) => p0 + mm * (t - t0), ta = Math.max(t0, c.firstT), te = c.lastT + 3 * c.ms;
          const x1 = xf(ta), y1 = yf(val(ta)), x2 = xf(te), y2 = yf(val(te)); if ([x1, y1, x2, y2].some((v) => v === null)) return;
          ctx.setLineDash(conf ? [] : [6, 4]); ctx.strokeStyle = col; ctx.lineWidth = conf ? 1.8 : 1.3;
          ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); ctx.setLineDash([]);
        });
        let first = null;
        [1, 2, 3, 4, 5].forEach((k) => {
          const t0 = num(p[`pt${k}_t`]); if (t0 === null) return;
          const b = c.byT.get(t0); if (!b) return;
          const pv = num(p[`pt${k}_p`]), x = xf(t0), y = yf(pv); if (x === null || y === null) return;
          ctx.beginPath(); ctx.arc(x, y, 3.5, 0, Math.PI * 2); ctx.fillStyle = P.panel; ctx.fill(); ctx.strokeStyle = col; ctx.lineWidth = 1.8; ctx.stroke();
          if (!first) first = { x, y: y + (Math.abs(pv - b.l) < Math.abs(pv - b.h) ? 22 : -20) };
        });
        if (first) pillC(ctx, first.x, Math.max(14, Math.min(h - 12, first.y)), `${conf ? '✓ ' : ''}${p.nombre}`, col, conf, 'middle', w);
      });
      c.divs.forEach((v) => {
        const col = v.tipo === 'alcista' ? P.up : P.dn, off = v.tipo === 'bajista' ? -8 : 8, x1 = xf(v.t1), y1 = yf(v.p1), x2 = xf(v.t2), y2 = yf(v.p2);
        if ([x1, y1, x2, y2].some((q) => q === null)) return;
        ctx.strokeStyle = col; ctx.lineWidth = 1.8; ctx.lineCap = 'round'; ctx.beginPath(); ctx.moveTo(x1, y1 + off); ctx.lineTo(x2, y2 + off); ctx.stroke();
      });
      if (c.giros.length) {
        ctx.setLineDash([1, 4]); ctx.lineCap = 'round'; ctx.strokeStyle = alpha(P.fg, 0.4); ctx.lineWidth = 1.1; ctx.beginPath();
        c.giros.forEach((g, i) => { const x = xf(g.t), y = yf(g.p); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.stroke(); ctx.setLineDash([]);
        c.giros.filter((g) => g.w).forEach((g) => {
          const x = xf(g.t), y0 = yf(g.p); if (x === null || y0 === null) return;
          const y = Math.max(10, Math.min(h - 10, y0 + (g.alto ? -12 : 12)));
          ctx.beginPath(); ctx.arc(x, y, 6.5, 0, Math.PI * 2); ctx.fillStyle = P.panel; ctx.fill(); ctx.strokeStyle = alpha(P.fg, 0.6); ctx.lineWidth = 1; ctx.stroke();
          ctx.font = `700 8.5px ${P.font}`; ctx.fillStyle = P.fg; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(g.w, x, y + 0.5);
        });
      }
      // liquidaciones estimadas al costado y el dolor maximo de opciones: son por precio, las mismas del principal
      if (L.liq && d && d.liq && d.liq.length) {
        const lw = Math.min(46, w * 0.13), inR = d.liq.map((r) => ({ ...r, y: yf(r.p) })).filter((r) => r.y !== null && r.y > 0 && r.y < h);
        const mx = Math.max(1, ...inR.map((r) => Math.max(r.l, r.s))), y0 = yf(d.price), y1 = yf(d.price * 1.0025), bh = y0 !== null && y1 !== null ? Math.max(2, Math.abs(y0 - y1) - 1) : 2;
        inR.forEach((r) => [[r.l, P.dn], [r.s, P.up]].forEach(([v, col]) => { if (!(v > 0)) return; const bw = Math.max(3, Math.sqrt(v / mx) * (lw - 6)); ctx.fillStyle = alpha(col, 0.12 + 0.55 * v / mx); ctx.fillRect(w - bw, r.y - bh / 2, bw, bh); }));
      }
      if (d && d.dolor !== null && d.dolor !== undefined) {
        const y = yf(d.dolor);
        if (y !== null && y > 0 && y < h) { ctx.setLineDash([8, 5]); ctx.strokeStyle = alpha(P.c2 || P.mute, 0.7); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(0, Math.round(y) + 0.5); ctx.lineTo(w, Math.round(y) + 0.5); ctx.stroke(); ctx.setLineDash([]); }
      }
      // abanico de caminos de esta temporalidad (se calcula aparte, solo con casos realmente parecidos)
      const a = s.aba;
      if (L.abanico && a && a.casos && a.casos.length >= ABA_MIN && a.tf === MG.tfs[s.i] && a.mon === MON()) {
        const x0 = xf(a.t0), y0 = yf(a.base0); if (x0 === null || y0 === null) return;
        a.casos.forEach((cs) => {
          ctx.beginPath(); ctx.moveTo(x0, y0);
          cs.camino.forEach((v, k) => { const x = xf(a.t0 + (k + 1) * a.tfMs), y = yf(a.base0 * Math.exp(v)); if (x !== null && y !== null) ctx.lineTo(x, y); });
          ctx.strokeStyle = alpha(cs.fin > a.M ? P.up : cs.fin < -a.M ? P.dn : P.mute, 0.42); ctx.lineWidth = 1; ctx.stroke();
        });
      }
    };
  }
  function mgAbanico(s) {
    const tf = MG.tfs[s.i];
    if (!S.layers.abanico || !s.bars.length) { s.aba = null; return; }
    const key = `${MON()}|${tf}|${s.bars[s.bars.length - 1].t}`;
    if (s.abaKey === key || s.abaCorre === key) return;
    s.abaCorre = key;
    const mon = MON();
    abaLeerVelas(mon, tf).then((V) => {
      if (s.abaCorre !== key) return;
      const r = V.length ? abaCalcular(V, 12) : { casos: [] };
      r.tf = tf; r.mon = mon; r.H = 12; r.tfMs = MG_MS[tf];
      s.aba = r; s.abaKey = key; s.abaCorre = null; if (s.capaU) s.capaU.update(); if (s.capa) s.capa.update();
    }).catch(() => { s.abaCorre = null; });
  }
  function m2Pintar(ajustar) { if (MG.n > 1) mgVis().forEach((s) => mgPintarUno(s, ajustar)); }
  // el precio en vivo mueve la ultima vela de cada uno (o abre la siguiente si ya cerro)
  function m2Vivo(precio) {
    if (MG.n === 1 || !(precio > 0)) return;
    const ahora = Date.now();
    mgVis().forEach((s) => {
      if (!s.s || !s.bars.length) return;
      const m = MG_MS[MG.tfs[s.i]], ult = s.bars[s.bars.length - 1];
      let b = ult;
      if (ahora >= ult.t + m) { b = { t: Math.floor(ahora / m) * m, o: ult.c, h: ult.c, l: ult.c, c: ult.c }; s.bars.push(b); }
      b.c = precio; b.h = Math.max(b.h, precio); b.l = Math.min(b.l, precio);
      try { s.s.update({ time: T2(b.t), open: b.o, high: b.h, low: b.l, close: b.c }); } catch (e) { /* la serie se rehizo */ }
      if (!G.hover) mgLeyenda(s, null);
    });
  }
  mgControles();
  if (MG.n > 1) { document.documentElement.classList.add('ab-multi'); document.documentElement.classList.toggle('ab-multi-4', MG.n === 4); MG.sec.forEach((s) => { s.box.hidden = s.i >= MG.n - 1; }); }

  // imagen del grafico (con las marcas, sin la mira) y una linea de encabezado; en el iPhone se comparte, en la compu se baja.
  // Se arma sincronico (toDataURL) para llamar a share dentro del toque: Safari no deja compartir despues de esperar
  function foto() {
    if (!G.chart || !G.d) return;
    const shot = G.chart.takeScreenshot(true, false), P = G.P, k = shot.width / Math.max(1, G.box.clientWidth);
    const head = Math.round(30 * k), cv = document.createElement('canvas');
    cv.width = shot.width; cv.height = shot.height + head;
    const ctx = cv.getContext('2d');
    ctx.fillStyle = P.panel; ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.drawImage(shot, 0, head);
    ctx.font = `600 ${Math.round(13 * k)}px ${P.font}`; ctx.fillStyle = P.fg; ctx.textBaseline = 'middle';
    ctx.fillText(`${MON()}USDT · ${TF_TXT[S.tf]} · ${fp(G.d.price)} · ${fmtT(Date.now(), '1h')} (hora Argentina)`, Math.round(10 * k), head / 2);
    const name = `${MON()}-${S.tf}-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-')}.png`;
    const b64 = atob(cv.toDataURL('image/png').split(',')[1]), bytes = new Uint8Array(b64.length);
    for (let i = 0; i < b64.length; i++) bytes[i] = b64.charCodeAt(i);
    const blob = new Blob([bytes], { type: 'image/png' }), file = new File([blob], name, { type: 'image/png' });
    const bajar = () => {
      const a = el('a'); a.href = URL.createObjectURL(blob); a.download = name;
      document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    };
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      navigator.share({ files: [file], title: `${MON()} · ${TF_TXT[S.tf]}` }).catch((e) => { if (!e || e.name !== 'AbortError') bajar(); });
    } else bajar();
  }

  // "»": aparece si la ultima vela quedo fuera de la vista, abajo del panel del precio y a la izquierda de las liquidaciones
  function botonPresente() {
    const r = G.chart && G.d ? G.chart.timeScale().getVisibleLogicalRange() : null;
    const lejos = !!r && r.to < G.d.lastIdx - 0.5;
    if (lejos) {
      try { G.nowBtn.style.top = `${G.chart.paneSize(0).height - 44}px`; G.nowBtn.style.right = `${G.chart.priceScale('right').width() + (G.liqW || 0) + 10}px`; } catch (e) { /* sin medidas todavia */ }
    }
    G.nowBtn.hidden = !lejos;
  }

  // ---------- flujo: delta por vela, CVD de perpetuos y de spot, e interes abierto (paneles debajo del grafico) ----------
  // Delta = lo que se compro a mercado menos lo que se vendio a mercado en esa vela (en USD), de las velas de Binance
  // (traen el volumen comprador); el CVD es la suma desde la primera vela del grafico. Perpetuos y spot por separado: si
  // sube el precio con el CVD spot subiendo, compran de verdad; si solo empujan los perpetuos, es apalancamiento.
  // Se pide por activo y temporalidad, se guarda en memoria y se refresca la ultima parte cada 30 s (sin trabar el dibujo).
  const FLUJO = { cache: {}, corre: {} };
  const FL_OI_TF = new Set(['5m', '15m', '30m', '1h', '4h', '1d']);
  const usdC = (x) => { const a = Math.abs(x), s = x < 0 ? '−' : x > 0 ? '+' : ''; return a >= 1e9 ? `${s}${f1(a / 1e9)} mil M` : a >= 1e6 ? `${s}${f1(a / 1e6)} M` : a >= 1e3 ? `${s}${f0(a / 1e3)} mil` : `${s}${f0(a)}`; };
  async function flujoBajar(mon, tf) {
    const sym = `${mon}USDT`, k = `${mon}|${tf}`, previo = FLUJO.cache[k];
    const lim = previo ? 3 : 1000;
    const kl = (url) => fetch(url, { signal: AbortSignal.timeout(9000) }).then((r) => (r.ok ? r.json() : [])).catch(() => []);
    const [fu, sp, oi] = await Promise.all([
      kl(`https://fapi.binance.com/fapi/v1/klines?symbol=${sym}&interval=${tf}&limit=${lim}`),
      kl(`https://api.binance.com/api/v3/klines?symbol=${sym}&interval=${tf}&limit=${lim}`),
      FL_OI_TF.has(tf) ? kl(`https://fapi.binance.com/futures/data/openInterestHist?symbol=${sym}&period=${tf}&limit=${previo ? 3 : 500}`) : Promise.resolve([]),
    ]);
    const e = previo || { dp: new Map(), ds: new Map(), oi: new Map() };
    // delta en USD: (comprado - vendido) * cierre; comprado = volumen comprador (r[9]), vendido = volumen - comprado
    const delta = (r) => (2 * +r[9] - +r[5]) * +r[4];
    (Array.isArray(fu) ? fu : []).forEach((r) => e.dp.set(+r[0], delta(r)));
    (Array.isArray(sp) ? sp : []).forEach((r) => e.ds.set(+r[0], delta(r)));
    (Array.isArray(oi) ? oi : []).forEach((x) => { const m = TF_MIN[tf] * 6e4; e.oi.set(Math.floor(+x.timestamp / m) * m, +x.sumOpenInterestValue); });
    e.t = Date.now(); e.hayPerp = e.dp.size > 0; e.haySpot = e.ds.size > 0; e.hayOi = e.oi.size > 0;
    FLUJO.cache[k] = e;
    return e;
  }
  /** Lo guardado (puede ser null); si esta viejo, lo pide y llama a listo() cuando llega. */
  function flujoDe(mon, tf, listo) {
    if (!ES_CRIPTO(mon)) return null;
    const k = `${mon}|${tf}`, e = FLUJO.cache[k];
    if ((!e || Date.now() - e.t > 30000) && !FLUJO.corre[k]) {
      FLUJO.corre[k] = flujoBajar(mon, tf).then(() => { if (listo) listo(); }).catch(() => {}).finally(() => { delete FLUJO.corre[k]; });
    }
    return e || null;
  }
  /** Las series del panel para unas velas: delta por vela y CVD desde la primera (perp y spot), e interes abierto. */
  function flujoSeries(e, bars, P) {
    const out = { delta: [], cvdP: [], cvdS: [], oi: [], ult: null };
    if (!e) return out;
    let cp = 0, cs = 0;
    bars.forEach((b) => {
      const time = T2(b.t), dp = e.dp.get(b.t), ds = e.ds.get(b.t), oi = e.oi.get(b.t);
      if (dp !== undefined) { out.delta.push({ time, value: dp, color: alpha(dp >= 0 ? P.up : P.dn, 0.6) }); cp += dp; out.cvdP.push({ time, value: cp }); }
      if (ds !== undefined) { cs += ds; out.cvdS.push({ time, value: cs }); }
      if (oi !== undefined) out.oi.push({ time, value: oi });
      if (dp !== undefined || ds !== undefined) out.ult = { t: b.t, dp: dp ?? null, ds: ds ?? null, cp, cs, oi: oi ?? (out.oi.length ? out.oi[out.oi.length - 1].value : null) };
    });
    return out;
  }
  const FL_SPOT = '#38bdf8', FL_OI = '#f59e0b';
  /** Agrega los dos paneles a un grafico (el principal o uno de los otros). base = indice del primer panel. */
  function flujoPaneles(chart, base, P) {
    const fmt = { type: 'custom', formatter: (v) => usdC(v), minMove: 1 }, q = { lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false, priceFormat: fmt };
    const s = {
      delta: chart.addSeries(LW.HistogramSeries, { ...q }, base),
      cvdP: chart.addSeries(LW.LineSeries, { ...q, color: alpha(P.fg, 0.85), lineWidth: 1.5 }, base + 1),
      cvdS: chart.addSeries(LW.LineSeries, { ...q, color: FL_SPOT, lineWidth: 1.5, priceScaleId: 'cvds' }, base + 1),
      oi: chart.addSeries(LW.LineSeries, { ...q, color: FL_OI, lineWidth: 1.5, priceScaleId: 'oi' }, base + 1),
    };
    try { s.cvdS.priceScale().applyOptions({ visible: false, scaleMargins: { top: 0.12, bottom: 0.12 } }); s.oi.priceScale().applyOptions({ visible: false, scaleMargins: { top: 0.12, bottom: 0.12 } }); } catch (e) { /* idem */ }
    return s;
  }
  function flujoSet(s, f) {
    if (!s) return;
    s.delta.setData(f.delta); s.cvdP.setData(f.cvdP); s.cvdS.setData(f.cvdS); s.oi.setData(f.oi);
  }

  // ---------- VWAP y perfil de volumen (POC, VAH, VAL) ----------
  // VWAP: el precio promedio pesado por volumen desde el inicio de la sesion (dia UTC en las temporalidades de hasta 4 h,
  // mes en el diario, año en la semanal y la mensual): arriba del VWAP manda la compra del dia, abajo la venta.
  // Perfil: cuanto volumen se opero en cada precio de las velas que estas viendo (como el "volume profile" de TradingView):
  // POC = el precio con mas volumen; VAH y VAL = los bordes de la zona donde se opero el 70 %.
  function vwapSerie(bars, tfMin) {
    const sesion = (t) => { const d = new Date(t); return tfMin < 1440 ? Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) : tfMin < 10080 ? Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1) : Date.UTC(d.getUTCFullYear(), 0, 1); };
    const out = []; let s0 = null, pv = 0, vv = 0;
    bars.forEach((b) => {
      if (b.v === null || b.v === undefined) return;
      const se = sesion(b.t); if (se !== s0) { s0 = se; pv = 0; vv = 0; out.push({ corte: true }); }
      pv += ((b.h + b.l + b.c) / 3) * b.v; vv += b.v;
      if (vv > 0) out.push({ time: T2(b.t), value: pv / vv });
    });
    // un hueco entre sesiones (whitespace) para que la linea no una el final de un dia con el comienzo del siguiente
    return out.map((x, i) => (x.corte ? (i && out[i + 1] ? { time: out[i + 1].time } : null) : x)).filter(Boolean).filter((x, i, a) => !i || x.time !== a[i - 1].time);
  }
  function perfilVol(bars, n = 48) {
    const bs = bars.filter((b) => b.v > 0 && b.h >= b.l); if (bs.length < 5) return null;
    let lo = Infinity, hi = -Infinity; bs.forEach((b) => { lo = Math.min(lo, b.l); hi = Math.max(hi, b.h); });
    if (!(hi > lo)) return null;
    const paso = (hi - lo) / n, vol = new Float64Array(n);
    bs.forEach((b) => {
      const k0 = Math.max(0, Math.min(n - 1, Math.floor((b.l - lo) / paso))), k1 = Math.max(0, Math.min(n - 1, Math.floor((b.h - lo) / paso)));
      const parte = b.v / (k1 - k0 + 1); for (let k = k0; k <= k1; k++) vol[k] += parte;
    });
    let poc = 0; for (let k = 1; k < n; k++) if (vol[k] > vol[poc]) poc = k;
    const tot = vol.reduce((a, v) => a + v, 0); let a = poc, z = poc, acc = vol[poc];
    while (acc < tot * 0.7 && (a > 0 || z < n - 1)) { const va = a > 0 ? vol[a - 1] : -1, vz = z < n - 1 ? vol[z + 1] : -1; if (vz >= va) acc += vol[++z]; else acc += vol[--a]; }
    const p = (k) => lo + (k + 0.5) * paso;
    return { lo, paso, n, vol, max: vol[poc], poc: p(poc), vah: lo + (z + 1) * paso, val: lo + a * paso, a, z };
  }
  /** El perfil dibujado a la izquierda del panel (barras horizontales), y las lineas POC / VAH / VAL. */
  function dibPerfil(ctx, w, h, pr, yf, P, chico) {
    if (!pr) return;
    const ancho = Math.min(chico ? 70 : 120, w * 0.22);
    for (let k = 0; k < pr.n; k++) {
      const y1 = yf(pr.lo + (k + 1) * pr.paso), y0 = yf(pr.lo + k * pr.paso); if (y1 === null || y0 === null) continue;
      const bw = pr.vol[k] / pr.max * ancho, dentro = k >= pr.a && k <= pr.z;
      ctx.fillStyle = alpha(dentro ? P.c2 || P.mute : P.mute, dentro ? 0.22 : 0.12); ctx.fillRect(0, Math.min(y0, y1) + 0.5, bw, Math.max(1, Math.abs(y0 - y1) - 1));
    }
    [[pr.poc, 'POC', 0.9, []], [pr.vah, 'VAH', 0.6, [4, 4]], [pr.val, 'VAL', 0.6, [4, 4]]].forEach(([v, t, a, dash]) => {
      const y = yf(v); if (y === null || y < 0 || y > h) return;
      ctx.setLineDash(dash); ctx.strokeStyle = alpha(P.c2 || P.mute, a); ctx.lineWidth = t === 'POC' ? 1.4 : 1;
      ctx.beginPath(); ctx.moveTo(0, Math.round(y) + 0.5); ctx.lineTo(w, Math.round(y) + 0.5); ctx.stroke(); ctx.setLineDash([]);
      ctx.font = `600 9.5px ${P.font}`; ctx.fillStyle = alpha(P.c2 || P.mute, 0.95); ctx.textAlign = 'left'; ctx.textBaseline = 'bottom'; ctx.fillText(`${t} ${fp(v)}`, 4, y - 2);
    });
  }
  // el perfil de lo que se ve: se rehace al mover o hacer zoom (una vez por cuadro como mucho)
  function perfilVisible(chart, bars) {
    const r = chart.timeScale().getVisibleLogicalRange(); if (!r || !bars.length) return null;
    const a = Math.max(0, Math.floor(r.from)), z = Math.min(bars.length - 1, Math.ceil(r.to));
    const k = `${bars.length}|${a}|${z}|${bars[bars.length - 1].c}`;
    if (bars.__vpK === k) return bars.__vp;
    bars.__vpK = k; bars.__vp = z > a ? perfilVol(bars.slice(a, z + 1)) : null; return bars.__vp;
  }

  const VWAP_COL = '#d946ef';
  // ---------- conceptos ICT en el grafico: zonas (order blocks, breakers, IFVG), barridas y Power of Three ----------
  const ICT_CORTO = { ob: 'OB', breaker: 'Breaker', ifvg: 'IFVG', barrida: 'Barrida', po3: 'PO3' };
  function dibIct(ctx, w, h, items, xf, yf, P, half, chico) {
    if (!items || !items.length) return;
    ctx.save();
    items.forEach((z) => {
      const col = z.sesgo === 'alcista' ? P.up : P.dn, lo = num(z.bajo), hi = num(z.alto);
      const yt = yf(hi), yb = yf(lo); if (yt === null || yb === null) return;
      const pc = z.exito !== null && z.exito !== undefined ? ` ${z.exito}%` : '';
      if (z.tipo === 'barrida') {
        const x = xf(num(z.t)); if (x === null || x > w) return;
        ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.setLineDash([3, 3]);
        ctx.beginPath(); ctx.moveTo(Math.max(0, x - 40), yt); ctx.lineTo(Math.min(w, x + 12), yt); ctx.stroke(); ctx.setLineDash([]);
        pillC(ctx, x, yt + (z.sesgo === 'alcista' ? 14 : -14), `${z.sesgo === 'alcista' ? '↑' : '↓'} Barrida${chico ? '' : pc}`, col, false, 'middle', w);
        return;
      }
      if (z.tipo === 'po3') {
        const x1 = xf(num(z.t)), x0 = xf(Math.floor(num(z.t) / 864e5) * 864e5);
        if (x1 === null) return;
        const xa = x0 === null ? 0 : Math.max(0, x0);
        ctx.fillStyle = alpha(P.mute, 0.06); ctx.fillRect(xa, yt, x1 - xa, Math.max(2, yb - yt));
        ctx.strokeStyle = alpha(P.mute, 0.5); ctx.lineWidth = 1; ctx.setLineDash([2, 3]); ctx.strokeRect(xa + 0.5, yt + 0.5, x1 - xa, Math.max(2, yb - yt)); ctx.setLineDash([]);
        pillC(ctx, x1, z.sesgo === 'alcista' ? yb + 14 : yt - 14, `PO3 ${z.sesgo === 'alcista' ? '↑' : '↓'}${chico ? '' : pc}`, col, true, 'middle', w);
        return;
      }
      const t0 = num(z.t_rompe !== null && z.t_rompe !== undefined ? z.t_rompe : z.t), x0 = xf(t0); if (x0 === null || x0 > w) return;
      const xa = Math.max(0, x0 - half), alto = Math.max(2, yb - yt);
      ctx.fillStyle = alpha(col, z.tipo === 'ob' ? 0.13 : 0.07); ctx.fillRect(xa, yt, w - xa, alto);
      ctx.strokeStyle = alpha(col, 0.7); ctx.lineWidth = 1;
      if (z.tipo === 'breaker') ctx.setLineDash([5, 4]); else if (z.tipo === 'ifvg') ctx.setLineDash([1.5, 3]);
      ctx.beginPath(); ctx.moveTo(xa, yt + 0.5); ctx.lineTo(w, yt + 0.5); ctx.moveTo(xa, yt + alto - 0.5); ctx.lineTo(w, yt + alto - 0.5); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = alpha(col, 0.85); ctx.fillRect(xa, yt, 2, alto);
      if (alto >= 9 || !chico) { ctx.font = `700 9.5px ${P.font}`; ctx.fillStyle = col; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(`${ICT_CORTO[z.tipo]}${chico ? '' : pc}`, xa + 5, yt + alto / 2); }
    });
    ctx.restore();
  }

  // ---------- libro de ordenes: presion, deslizamiento, profundidad y mapa de calor en el tiempo ----------
  // Fotos del libro de Binance y Bybit (perpetuos) cada 15 s mientras miras (se guardan en el telefono hasta 3 dias,
  // una por minuto) y, para BTC, las del servidor cada 5 min las 24 h (historial/BTC/libro). Cada foto: lo que hay
  // esperando en escalones de ~0,1% del precio hasta 4%; el mapa pinta mas brillante donde habia mas plata.
  const LIBRO = { fotos: {}, ahora: null, t: null, srv: {}, cargado: {}, corre: false };
  const libPaso = (p) => { const x = p * 0.001, e = Math.pow(10, Math.floor(Math.log10(x))); return [1, 2, 5, 10].map((m) => m * e).find((v) => v >= x * 0.7); };
  async function libroBajar(mon) {
    const sym = `${mon}USDT`, q = (u) => fetch(u, { signal: AbortSignal.timeout(8000) }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const [bi, by] = await Promise.all([q(`https://fapi.binance.com/fapi/v1/depth?symbol=${sym}&limit=1000`), q(`https://api.bybit.com/v5/market/orderbook?category=linear&symbol=${sym}&limit=500`)]);
    const L = [];
    const par = (a) => (a || []).map((r) => [+r[0], +r[1]]);
    if (bi && bi.bids) L.push([par(bi.bids), par(bi.asks)]);
    if (by && by.result && by.result.b) L.push([par(by.result.b), par(by.result.a)]);
    return L;
  }
  /** Presion a ±0,5%, profundidad por distancia y deslizamiento de una compra/venta a mercado (de los libros juntos). */
  function libroMedir(L) {
    const bids = L.flatMap((x) => x[0]).sort((a, b) => b[0] - a[0]), asks = L.flatMap((x) => x[1]).sort((a, b) => a[0] - b[0]);
    if (!bids.length || !asks.length) return null;
    const medio = (bids[0][0] + asks[0][0]) / 2;
    const suma = (lado, pct) => lado.reduce((s, [p, qq]) => (Math.abs(p / medio - 1) <= pct ? s + p * qq : s), 0);
    const prof = [0.0025, 0.005, 0.01, 0.02].map((d) => ({ d, b: suma(bids, d), a: suma(asks, d) }));
    const b5 = prof[1].b, a5 = prof[1].a, presion = b5 + a5 ? (b5 - a5) / (b5 + a5) * 100 : 0;
    // deslizamiento: cuanto se aleja el precio promedio al comprar (o vender) ese monto de una
    const desl = (lado, usd) => { let r = usd, costo = 0, q = 0; for (const [p, qq] of lado) { const v = Math.min(r, p * qq); costo += v; q += v / p; r -= v; if (r <= 0) break; } return r > 0 ? null : Math.abs(costo / q / medio - 1) * 1e4; };
    return { medio, presion, prof, compra: [1e5, 1e6].map((u) => desl(asks, u)), venta: [1e5, 1e6].map((u) => desl(bids, u)) };
  }
  function libroFoto(L, medio, t) {
    const paso = libPaso(medio), lados = [new Map(), new Map()];
    L.forEach(([b, a]) => [b, a].forEach((filas, n) => filas.forEach(([p, qq]) => {
      if (Math.abs(p / medio - 1) > 0.04 || !(qq > 0)) return;
      const k = Math.round(p / paso); lados[n].set(k, (lados[n].get(k) || 0) + p * qq);
    })));
    const niv = new Map();
    lados.forEach((m) => [...m.entries()].sort((x, y) => y[1] - x[1]).slice(0, 60).forEach(([k, v]) => niv.set(k, (niv.get(k) || 0) + Math.round(v / 1000))));
    return { t, medio, paso, niv };
  }
  function libroGuardar(mon) {
    const f = LIBRO.fotos[mon] || [], corte = Date.now() - 3 * 864e5, porMin = new Map();
    f.forEach((x) => { if (x.t >= corte && !x.srv) porMin.set(Math.floor(x.t / 6e4), x); });
    const arr = [...porMin.values()].map((x) => [x.t, x.medio, x.paso, [...x.niv.entries()]]);
    try {
      const req = indexedDB.open('analista-btc', 1);
      req.onupgradeneeded = () => { try { req.result.createObjectStore('kv'); } catch (e) { /* ya estaba */ } };
      req.onsuccess = () => { try { const tx = req.result.transaction('kv', 'readwrite'); tx.objectStore('kv').put(arr, `libro:${mon}`); tx.oncomplete = () => req.result.close(); } catch (e) { /* sin lugar */ } };
    } catch (e) { /* sin almacenamiento */ }
  }
  function libroCargar(mon) {
    if (LIBRO.cargado[mon]) return; LIBRO.cargado[mon] = true;
    try {
      const req = indexedDB.open('analista-btc', 1);
      req.onupgradeneeded = () => { try { req.result.createObjectStore('kv'); } catch (e) { /* ya estaba */ } };
      req.onsuccess = () => { try { const g = req.result.transaction('kv').objectStore('kv').get(`libro:${mon}`); g.onsuccess = () => {
        const arr = Array.isArray(g.result) ? g.result : []; const f = LIBRO.fotos[mon] || (LIBRO.fotos[mon] = []);
        arr.forEach(([t, medio, paso, niv]) => f.push({ t, medio, paso, niv: new Map(niv) })); f.sort((a, b) => a.t - b.t); libroRedibujar(); }; } catch (e) { /* idem */ } };
    } catch (e) { /* idem */ }
    // BTC: lo del servidor (cada 5 min, las 24 h) de hoy y ayer
    if (mon === 'BTC') {
      const dias = [Date.now() - 864e5, Date.now()].map((t) => new Date(t).toISOString().slice(0, 10));
      Promise.all(dias.map((d) => fetch(`${HIST_URL}/libro/${d}.csv`, { signal: AbortSignal.timeout(10000) }).then((r) => (r.ok ? r.text() : '')).catch(() => ''))).then((txts) => {
        const f = LIBRO.fotos.BTC || (LIBRO.fotos.BTC = []);
        txts.forEach((tx) => tx.split('\n').slice(1).forEach((l) => {
          const [t, medio, paso, niv] = l.split(','); if (!niv) return;
          f.push({ t: +t, medio: +medio, paso: +paso, srv: true, niv: new Map(niv.split(';').map((x) => x.split(':').map(Number))) });
        }));
        f.sort((a, b) => a.t - b.t); libroRedibujar();
      });
    }
  }
  let libroRedibujarT = 0;
  function libroRedibujar() { LIBRO.cols = {}; if (!libroRedibujarT) libroRedibujarT = requestAnimationFrame(() => { libroRedibujarT = 0; if (G.under) G.under.update(); mgVis().forEach((s) => s.capaU && s.capaU.update()); libroPanel(); }); }
  async function libroTic() {
    const mon = MON();
    if (document.hidden || !ES_CRIPTO(mon) || LIBRO.corre) return;
    const ver = S.layers.libro || (document.getElementById('senales') || {}).open;
    if (!ver) return;
    LIBRO.corre = true;
    try {
      libroCargar(mon);
      const L = await libroBajar(mon); if (!L.length || mon !== MON()) return;
      const m = libroMedir(L); if (!m) return;
      LIBRO.ahora = m; LIBRO.t = Date.now();
      const f = LIBRO.fotos[mon] || (LIBRO.fotos[mon] = []); f.push(libroFoto(L, m.medio, Date.now()));
      if (f.length > 6000) f.splice(0, f.length - 6000);
      if (!LIBRO.ult || Date.now() - LIBRO.ult > 5 * 6e4) { LIBRO.ult = Date.now(); libroGuardar(mon); }
      libroRedibujar();
    } finally { LIBRO.corre = false; }
  }
  setInterval(libroTic, 15000); setTimeout(libroTic, 4000);
  // columnas del mapa: por cada vela, lo mas cargado de cada escalon en las fotos de esa vela
  function libroColumnas(bars, tfMs) {
    const f = LIBRO.fotos[MON()] || []; if (!f.length || !bars.length) return null;
    const k = `${MON()}|${tfMs}|${f.length}|${bars.length}|${bars[0].t}`;
    LIBRO.cols = LIBRO.cols || {}; if (LIBRO.cols[tfMs] && LIBRO.cols[tfMs].k === k) return LIBRO.cols[tfMs];
    const cols = new Map(); let mx = 0, j = 0;
    const t0 = bars[0].t;
    for (const x of f) {
      if (x.t < t0) continue;
      const bt = t0 + Math.floor((x.t - t0) / tfMs) * tfMs;
      let c = cols.get(bt); if (!c) cols.set(bt, (c = { paso: x.paso, m: new Map() }));
      x.niv.forEach((v, kk) => { const p = kk * x.paso; const prev = c.m.get(p) || 0; if (v > prev) { c.m.set(p, v); if (v > mx) mx = v; } });
      j++;
    }
    LIBRO.cols[tfMs] = { k, cols, mx, n: j };
    return LIBRO.cols[tfMs];
  }
  function dibLibro(ctx, w, h, bars, tfMs, xf, yf, half) {
    const L = libroColumnas(bars, tfMs); if (!L || !L.mx) return;
    ctx.save();
    L.cols.forEach((c, bt) => {
      const x = xf(bt); if (x === null || x < -2 * half || x > w + 2 * half) return;
      c.m.forEach((v, p) => {
        const y0 = yf(p + c.paso / 2), y1 = yf(p - c.paso / 2); if (y0 === null || y1 === null || y1 < 0 || y0 > h) return;
        const u = Math.pow(v / L.mx, 0.6); if (u < 0.12) return;
        ctx.fillStyle = `rgba(${Math.round(40 + 215 * u)},${Math.round(120 + 80 * u)},${Math.round(255 - 200 * u)},${(0.08 + 0.5 * u).toFixed(3)})`;
        ctx.fillRect(x - half, y0, half * 2, Math.max(1, y1 - y0));
      });
    });
    ctx.restore();
  }
  // lo de ahora, en "Flujo de compras y libros de ordenes"
  function libroPanel() {
    const box = document.getElementById('libro-ahora'); if (!box) return;
    const m = LIBRO.ahora; if (!m) { box.hidden = true; return; }
    box.hidden = false;
    const bps = (x) => (x === null ? 'más que el libro' : `${f1(x)} pb`);
    const pr = m.presion;
    box.replaceChildren(
      el('div', 'ab-lib-t', `Presión del libro a ±0,5%: ${pr >= 0 ? '+' : ''}${f0(pr)}% ${Math.abs(pr) < 10 ? '(pareja)' : pr > 0 ? '(más compras esperando)' : '(más ventas esperando)'}`),
      Object.assign(el('div', 'ab-lib-bar'), { innerHTML: `<i style="width:${(50 + pr / 2).toFixed(1)}%"></i>` }),
      el('div', 'ab-lib-k', `Comprar a mercado mueve el precio: 100 mil USD ${bps(m.compra[0])} · 1 M USD ${bps(m.compra[1])}. Vender: ${bps(m.venta[0])} · ${bps(m.venta[1])} (pb = centésimos de 1%).`),
      el('div', 'ab-lib-k', `Esperando cerca del precio (compras / ventas): ${m.prof.map((x) => `±${String(x.d * 100).replace('.', ',')}%: ${usdC(x.b).replace('+', '')} / ${usdC(x.a).replace('+', '')}`).join(' · ')}.`));
  }

  function buildChart(box, P) {
    if (G.chart) { try { G.chart.remove(); } catch (e) { /* ya no estaba */ } }
    clearInterval(G.cdTimer);
    box.replaceChildren();
    const narrow = box.clientWidth < 520;
    const cross = { color: alpha(P.mute, 0.7), width: 1, style: LW.LineStyle.Dashed, labelBackgroundColor: P.lbl };
    const chart = LW.createChart(box, {
      autoSize: true,
      layout: { background: { type: 'solid', color: 'rgba(0,0,0,0)' }, textColor: P.mute, fontFamily: P.font, fontSize: 11, attributionLogo: false,   // la atribucion va en el pie
        panes: { separatorColor: P.line, separatorHoverColor: alpha(P.fg, 0.12), enableResize: true } },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      crosshair: { mode: S.iman ? LW.CrosshairMode.MagnetOHLC : LW.CrosshairMode.Normal, vertLine: cross, horzLine: cross },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: narrow ? 0.09 : 0.11, bottom: 0.2 }, minimumWidth: narrow ? 58 : 70 },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 4, barSpacing: narrow ? 6 : 8, minBarSpacing: 1,
        shiftVisibleRangeOnNewBar: true },
      localization: { locale: 'es-AR', timeFormatter: (t) => fmtSec(t) },
      handleScroll: { vertTouchDrag: !!S.fs }, kineticScroll: { touch: true, mouse: false },
    });
    const quiet = { lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false };
    G.bbU = chart.addSeries(LW.LineSeries, { priceFormat: { type: 'custom', formatter: (v) => fp(v), minMove: 0.0001 }, ...quiet, color: alpha(P.mute, 0.4), lineWidth: 1 });
    G.bbL = chart.addSeries(LW.LineSeries, { priceFormat: { type: 'custom', formatter: (v) => fp(v), minMove: 0.0001 }, ...quiet, color: alpha(P.mute, 0.4), lineWidth: 1 });
    G.vol = chart.addSeries(LW.HistogramSeries, { ...quiet, priceScaleId: 'vol', priceFormat: { type: 'volume' } });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.84, bottom: 0 }, visible: false });
    G.vwap = chart.addSeries(LW.LineSeries, { priceFormat: { type: 'custom', formatter: (v) => fp(v), minMove: 0.0001 }, ...quiet, color: VWAP_COL, lineWidth: 1.5 });
    G.e20 = chart.addSeries(LW.LineSeries, { priceFormat: { type: 'custom', formatter: (v) => fp(v), minMove: 0.0001 }, ...quiet, color: P.c0, lineWidth: 1 });
    G.e50 = chart.addSeries(LW.LineSeries, { priceFormat: { type: 'custom', formatter: (v) => fp(v), minMove: 0.0001 }, ...quiet, color: P.c1, lineWidth: 1 });
    G.e200 = chart.addSeries(LW.LineSeries, { priceFormat: { type: 'custom', formatter: (v) => fp(v), minMove: 0.0001 }, ...quiet, color: alpha(P.fg, 0.7), lineWidth: 2 });
    G.ghost = chart.addSeries(LW.CandlestickSeries, { priceFormat: { type: 'custom', formatter: (v) => fp(v), minMove: 0.0001 }, ...quiet, upColor: alpha(P.up, 0.25), downColor: alpha(P.dn, 0.25), borderVisible: true,
      borderUpColor: alpha(P.up, 0.85), borderDownColor: alpha(P.dn, 0.85), wickUpColor: alpha(P.up, 0.6), wickDownColor: alpha(P.dn, 0.6) });
    // linea con area, en el color del mercado (el cambio de 24 h): las velas siguen abajo, invisibles, asi niveles,
    // figuras y etiquetas funcionan igual en los dos modos
    G.ln = chart.addSeries(LW.AreaSeries, { priceFormat: { type: 'custom', formatter: (v) => fp(v), minMove: 0.0001 }, ...quiet, lineWidth: 2,
      crosshairMarkerVisible: true, crosshairMarkerRadius: 4, lineType: 0 });
    G.c = chart.addSeries(LW.CandlestickSeries, { priceFormat: { type: 'custom', formatter: (v) => fp(v), minMove: 0.0001 }, upColor: P.up, downColor: P.dn, borderVisible: false, wickUpColor: P.up, wickDownColor: P.dn,
      priceLineStyle: LW.LineStyle.Dotted, priceLineWidth: 1 });
    G.markers = LW.createSeriesMarkers(G.c, []);
    G.under = new Capa(drawUnder, 'bottom');
    // cuanto falta para que cierre la vela, debajo de la etiqueta del precio (como en TradingView)
    G.cd = '';
    G.over = new Capa(drawOver, 'top', {
      coordinate: () => { const y = G.d ? Y(G.d.price) : null; return y === null ? -100 : y + 19; },
      text: () => G.cd, textColor: () => '#ffffff', backColor: () => (G.d ? G.d.nowCol : P.mute), visible: () => !!G.cd && !!G.d && G.d.live,
      tickVisible: () => false,
    });
    G.c.attachPrimitive(G.under); G.c.attachPrimitive(G.over);
    G.dib = new Capa(drawDib, 'top'); G.c.attachPrimitive(G.dib);
    G.rsi = G.hist = G.macd = G.sig = null;
    if (S.layers.osc) {
      G.rsi = chart.addSeries(LW.LineSeries, { priceFormat: { type: 'custom', formatter: (v) => f1(v), minMove: 0.1 }, color: P.c2, lineWidth: 1, priceLineVisible: false, crosshairMarkerVisible: false,
        autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) }, 1);
      [70, 30].forEach((v) => G.rsi.createPriceLine({ price: v, color: alpha(P.mute, 0.5), lineWidth: 1, lineStyle: LW.LineStyle.Dashed, axisLabelVisible: false }));
      G.rsi.attachPrimitive(new Capa(drawOsc('RSI', G.rsi), 'bottom'));
      G.hist = chart.addSeries(LW.HistogramSeries, { priceFormat: { type: 'custom', formatter: (v) => (Math.abs(v) >= 100 ? f0(v) : Math.abs(v) >= 1 ? f1(v) : ar.format(',.4f')(v)), minMove: 0.0001 }, ...quiet }, 2);
      G.macd = chart.addSeries(LW.LineSeries, { priceFormat: { type: 'custom', formatter: (v) => (Math.abs(v) >= 100 ? f0(v) : Math.abs(v) >= 1 ? f1(v) : ar.format(',.4f')(v)), minMove: 0.0001 }, color: P.c0, lineWidth: 1, priceLineVisible: false, crosshairMarkerVisible: false }, 2);
      G.sig = chart.addSeries(LW.LineSeries, { priceFormat: { type: 'custom', formatter: (v) => (Math.abs(v) >= 100 ? f0(v) : Math.abs(v) >= 1 ? f1(v) : ar.format(',.4f')(v)), minMove: 0.0001 }, color: P.c1, lineWidth: 1, priceLineVisible: false, crosshairMarkerVisible: false }, 2);
      G.macd.attachPrimitive(new Capa(drawOsc('MACD', G.macd), 'top'));
      const pn = chart.panes(); pn[0].setStretchFactor(3.2); pn[1].setStretchFactor(1); pn[2].setStretchFactor(1);
    }
    G.fl = S.layers.flujo ? flujoPaneles(chart, S.layers.osc ? 3 : 1, P) : null;
    if (G.fl) { const pn = chart.panes(); pn[0].setStretchFactor(3.2); pn.slice(1).forEach((p, i) => p.setStretchFactor(S.layers.osc && i < 2 ? 1 : 0.85)); }
    // leyendas arriba a la izquierda de cada panel, como en TradingView
    G.leg = el('div', 'ab-ohlc'); G.legO = []; box.append(G.leg);
    if (S.layers.osc) ['rsi', 'macd'].forEach((k) => { const e = el('div', 'ab-ohlc ab-ohlc-pane'); e.dataset.k = k; box.append(e); G.legO.push(e); });
    if (S.layers.flujo) ['delta', 'cvd'].forEach((k) => { const e = el('div', 'ab-ohlc ab-ohlc-pane'); e.dataset.k = k; box.append(e); G.legO.push(e); });
    G.tip = el('div', 'ab-tip'); G.tip.hidden = true; box.append(G.tip);
    chart.subscribeCrosshairMove(onCross);
    chart.subscribeCrosshairMove((q) => m2DesdeMain(q));
    if (S.log) chart.priceScale('right').applyOptions({ mode: LW.PriceScaleMode.Logarithmic });
    // si te fuiste al pasado, un boton te trae de vuelta a la ultima vela (con el mismo zoom)
    G.nowBtn = el('button', 'ab-iconbtn ab-round ab-now-btn', '»');
    Object.assign(G.nowBtn, { type: 'button', title: 'Volver a la última vela', hidden: true });
    G.nowBtn.setAttribute('aria-label', 'Volver a la última vela');
    G.nowBtn.addEventListener('click', () => {
      const ts = chart.timeScale(), r = ts.getVisibleLogicalRange(); if (!r || !G.d) return;
      const total = G.d.all.length + G.d.futN, len = r.to - r.from;
      ts.setVisibleLogicalRange({ from: total + 1 - len, to: total + 1 });
    });
    box.append(G.nowBtn);
    chart.timeScale().subscribeVisibleLogicalRangeChange(() => ordenarEtiquetas());
    chart.timeScale().subscribeVisibleLogicalRangeChange((r) => {
      if (r) document.getElementById('zoom-info').textContent = `${Math.max(1, Math.round(r.to - r.from))} velas`;
      if (!G.dibujando) botonPresente();               // mientras se redibuja, el rango pasa por estados intermedios
    });
    axisTouch(box);
    dibInput(box);
    fibInput(box);
    medirInput(box);
    G.cdTimer = setInterval(() => {
      if (!G.d || !G.d.live) return;
      const left = Math.max(0, Math.round((G.d.closeAt - Date.now()) / 1000));
      const hh = Math.floor(left / 3600), mi = Math.floor((left % 3600) / 60), se = left % 60;
      G.cd = hh >= 24 ? `${Math.floor(hh / 24)} d ${hh % 24} h` : hh ? `${hh}:${p2(mi)}:${p2(se)}` : `${p2(mi)}:${p2(se)}`;
      G.over.update();
    }, 1000);
    Object.assign(G, { chart, box, P, tf: null, anim: null });
  }

  // leyenda de la vela bajo la mira (sin mira: la ultima), con medias, volumen, RSI y MACD
  function legend(i) {
    const d = G.d; if (!d) return;
    let b = null, fut = false;
    if (i !== null && i !== undefined && i >= 0) {
      if (i < d.all.length) b = d.all[i];
      else { const k = i - d.lastIdx; b = d.ghosts.find((g) => g.k === k) || null; fut = !!b; }
    }
    if (!b) b = d.all[d.all.length - 1];
    const P = G.P, col = b.c >= b.o ? P.up : P.dn;
    const kv = (k, v, c) => { const sp = el('span'); const bb = el('b', '', v); bb.style.color = c || col; sp.append(k, bb); return sp; };
    const row1 = el('div', 'ab-ohlc-r');
    const head = fut ? `Futura ${b.k} · ${SCEN_TXT[S.scen]}` : `${MON()}USDT · ${TF_TXT[S.tf]}`;
    row1.append(el('span', 'ab-ohlc-t', head));
    const ch = el('b', '', sg((b.c / b.o - 1) * 100)); ch.style.color = col;
    if (d.narrow) row1.append(kv('C', fp(b.c)), ch);
    else row1.append(kv('A', fp(b.o)), kv('Máx', fp(b.h)), kv('Mín', fp(b.l)), kv('C', fp(b.c)), ch);
    const rows = [row1], toca = i !== null && i !== undefined && i >= 0;
    if (d.narrow && !toca) { G.leg.replaceChildren(row1); return legendOsc(b, fut); }
    if (d.narrow && !fut) { const r = el('div', 'ab-ohlc-r'); r.append(kv('Máx', fp(b.h)), kv('Mín', fp(b.l))); rows.push(r); }
    if (!fut) {
      const r2 = el('div', 'ab-ohlc-r');
      if (S.layers.ema && b.e20 !== null) r2.append(kv('EMA 20 ', fp(b.e20), P.c0), kv('EMA 50 ', b.e50 === null ? '—' : fp(b.e50), P.c1), ...(b.e200 === null || b.e200 === undefined ? [] : [kv('EMA 200 ', fp(b.e200), alpha(P.fg, 0.75))]));
      r2.append(kv('Vol ', `${f1(b.v)}`, alpha(col, 1)));
      rows.push(r2);
    }
    G.leg.replaceChildren(...rows);
    legendOsc(b, fut);
  }
  function legendOsc(b, fut) {
    const d = G.d, P = G.P;
    const kv = (k, v, c) => { const sp = el('span'); const bb = el('b', '', v); bb.style.color = c; sp.append(k, bb); return sp; };
    if (G.legO.length) {
      const ob = fut ? null : b.rsi !== null && b.rsi !== undefined ? b : d.lastOsc;
      // arriba de cada panel: la suma de los altos de los paneles de arriba (y 1 px por cada separador)
      const hgt = G.legO.map((_, k) => { try { return G.chart.paneSize(k).height; } catch (e) { return 0; } }).concat(0);
      G.legO.forEach((e, j) => {
        const k = j + 1;
        e.style.top = `${hgt.slice(0, k).reduce((a, b) => a + b, 0) + k + 5}px`;
        if (e.dataset.k === 'delta' || e.dataset.k === 'cvd') { legendFlujo(e, b, fut); return; }
        if (e.dataset.k === 'rsi') {
          const rv = ob ? ob.rsi : null;
          e.replaceChildren(el('span', 'ab-ohlc-t', 'RSI 14'), kv('', rv === null ? '—' : f1(rv), P.c2),
            el('span', '', rv === null ? '' : rv >= 70 ? 'sobrecompra' : rv <= 30 ? 'sobreventa' : ''));
        } else {
          const fM = (v) => (v === null || v === undefined ? '—' : v === 0 ? '0' : Math.abs(v) >= 100 ? f0(v) : Math.abs(v) >= 1 ? f1(v) : ar.format(',.4f')(v));
          const parts = [el('span', 'ab-ohlc-t', 'MACD 12 26 9')];
          if (ob) parts.push(kv('', fM(ob.macd), P.c0), kv('', fM(ob.sig), P.c1), kv('', fM(ob.hist), ob.hist >= 0 ? P.up : P.dn));
          if (ob === d.lastOsc && d.cruce) parts.push(el('span', '', d.cruce));
          e.replaceChildren(...parts);
        }
      });
    }
  }

  // leyendas de los paneles de flujo: el valor de la vela que se mira (o el ultimo)
  function legendFlujo(e, b, fut) {
    const f = G.flS, P = G.P; if (!f) return;
    const kv = (k, v, c) => { const sp = el('span'); const bb = el('b', '', v); bb.style.color = c; sp.append(k, bb); return sp; };
    const en = (arr) => { if (!arr.length) return null; if (fut || !b) return arr[arr.length - 1].value; const t = T2(b.t), x = arr.find((q) => q.time === t); return x ? x.value : null; };
    if (e.dataset.k === 'delta') {
      const v = en(f.delta);
      e.replaceChildren(el('span', 'ab-ohlc-t', 'Delta'), kv('', v === null ? '—' : `${usdC(v)} USD`, v === null ? P.mute : v >= 0 ? P.up : P.dn),
        el('span', '', v === null ? 'sin datos de Binance' : v >= 0 ? 'compraron más a mercado' : 'vendieron más a mercado'));
    } else {
      const cp = en(f.cvdP), cs = en(f.cvdS), oi = en(f.oi);
      e.replaceChildren(el('span', 'ab-ohlc-t', 'CVD'), kv('perp ', cp === null ? '—' : usdC(cp), alpha(P.fg, 0.9)), kv('spot ', cs === null ? '—' : usdC(cs), FL_SPOT),
        kv('OI ', oi === null ? '—' : usdC(oi).replace('+', ''), FL_OI));
    }
  }
  function onCross(p) {
    const d = G.d; if (!d) return;
    G.hover = !!(p && p.point);
    if (!p || !p.point || p.logical === undefined) { legend(null); G.tip.hidden = true; return; }
    legend(Math.round(p.logical));
    // sobre las barras de liquidaciones: cuantos USD se liquidan en ese precio
    const pw = G.chart.paneSize(0).width;
    if (S.layers.liq && G.liqW && (p.paneIndex === 0 || p.paneIndex === undefined) && p.point.x > pw - G.liqW) {
      const pr = G.c.coordinateToPrice(p.point.y);
      const r = pr === null ? null : d.liq.reduce((a, z) => (!a || Math.abs(z.p - pr) < Math.abs(a.p - pr) ? z : a), null);
      if (r && Math.abs(r.p - pr) / pr < 0.004) {
        const g = el('div', 'ab-tip-g');
        g.append(el('span', 'ab-tip-d', 'Longs que se liquidan'), el('span', '', M(r.l)), el('span', 'ab-tip-d', 'Shorts que se liquidan'), el('span', '', M(r.s)));
        G.tip.replaceChildren(el('div', 'ab-tip-d', `Si ${MON()} llega a ≈ ${fp(r.p)} (${sg((r.p / d.price - 1) * 100, 1)})`), g,
          el('div', 'ab-tip-d', 'Estimación con open interest de la última semana'));
        G.tip.hidden = false;
        G.tip.style.left = `${Math.max(4, p.point.x - G.tip.offsetWidth - 14)}px`; G.tip.style.top = `${Math.max(4, p.point.y - 30)}px`;
        return;
      }
    }
    G.tip.hidden = true;
  }

  // el foco de "Que estas viendo": lo señalado queda encendido y el resto se apaga
  function applyFocus() {
    if (!G.chart || !G.d) return;
    const k = S.focus, P = G.P;                       // lo encendido: un Set de claves (o null)
    const set = new Set(); if (k && S.exCandles) k.forEach((x) => { if (S.exCandles[x]) S.exCandles[x].forEach((t) => set.add(t)); });
    const dim = (c, key) => (k && !k.has(key) ? alpha(c, 0.15) : c);
    if (k || G.wasFocus) {
      G.c.setData(G.d.cdata.map((b) => barra(!k || set.has(b.ms) ? b.bar
        : { ...b.bar, color: alpha(b.bar.close >= b.bar.open ? P.up : P.dn, 0.15), wickColor: alpha(b.bar.close >= b.bar.open ? P.up : P.dn, 0.15) })));
      G.wasFocus = !!k;
    }
    G.e20.applyOptions({ color: dim(P.c0, 'ema') }); G.e50.applyOptions({ color: dim(P.c1, 'ema') }); G.e200.applyOptions({ color: dim(alpha(P.fg, 0.7), 'ema') });
    G.bbU.applyOptions({ color: dim(alpha(P.mute, 0.4), 'bb') }); G.bbL.applyOptions({ color: dim(alpha(P.mute, 0.4), 'bb') });
    G.ghost.applyOptions({ visible: !k || k.has('futuro') });
    G.under.update(); G.over.update();
  }

  // EMA 20, 50 y 200 de la vela en curso con su precio de ahora (como el grafico del exchange): la de la vela anterior
  // ya cerrada mas el cierre de ahora. Antes quedaban con el precio del ultimo analisis, y en una vela nueva no habia
  // EMA hasta el analisis siguiente (la linea terminaba una vela antes)
  function emaVivo(prev, c) {
    const o = {};
    [['e20', 20], ['e50', 50], ['e200', 200]].forEach(([k, n]) => {
      if (prev && prev[k] !== null && prev[k] !== undefined) o[k] = c * 2 / (n + 1) + prev[k] * (1 - 2 / (n + 1));
    });
    return o;
  }

  (function () {
    const b = document.getElementById('tipo-btn');
    const pinta = () => { b.setAttribute('aria-pressed', String(S.linea)); b.setAttribute('aria-label', S.linea ? 'Ver velas' : 'Ver línea');
      b.title = S.linea ? 'Ver velas' : 'Ver línea'; document.getElementById('grafico').classList.toggle('ab-modo-linea', S.linea); };
    pinta();
    b.addEventListener('click', () => {
      S.linea = !S.linea; try { localStorage.setItem(LINEA_K, S.linea ? '1' : '0'); } catch (e) { /* sin almacenamiento */ }
      pinta(); if (S.rows) drawChart(S.rows, S.sum);
    });
  })();

  // ---------- reproducir: rebobina el lapso elegido y pasa las velas en camara rapida con lo que decia la app ----------
  // Las predicciones: las del historial constante del servidor (Render analiza cada 20 s y las sube a la rama historial
  // del repositorio: historial.py; solo BTC) mas las que guardo este telefono (worker.js, "registro"). Cada una: la
  // chance de que suba en h velas, el rango del 80%, el precio mas probable y los objetivos de arriba y de abajo con
  // su chance de tocarlos (las guardadas antes de nov 2026 traen solo chance y rango). La ficha muestra lo que dijo y
  // lo que va pasando: a que objetivo llego y cuando, maximo, minimo y cierre. Solo se mira: no cambia el analisis.
  (function () {
    const btn = document.getElementById('repro-btn'), pan = document.getElementById('repro'), fondo = document.getElementById('repro-fondo');
    const $ = (id) => document.getElementById(id);
    const LAPSOS = [['hoy', 'Hoy'], ['6h', '6 h'], ['12h', '12 h'], ['24h', '24 h'], ['3d', '3 días'], ['7d', '7 días'], ['30d', '30 días'], ['elegir', 'Elegir…']];
    const HORAS = { '6h': 6, '12h': 12, '24h': 24, '3d': 72, '7d': 168, '30d': 720 };
    const TFS = ['5m', '15m', '30m', '1h', '4h', '1d'], MAX_VELAS = 1000;
    const HIST = 'https://raw.githubusercontent.com/DiegoAdrian97/BTCAnalyzer/historial/historial/BTC';
    const R = { ch: null, serie: null, marcas: null, lineas: [], B: [], preds: [], i: 0, play: true, vel: 1, timer: 0, lapso: '24h', tf: '15m', fija: null, carga: 0 };
    const opt = { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' };
    const hhmm = (ms, conDia) => new Date(ms).toLocaleString('es-AR', conDia ? { day: '2-digit', month: '2-digit', ...opt } : opt);
    const enLocal = (ms) => new Date(ms - new Date(ms).getTimezoneOffset() * 6e4).toISOString().slice(0, 16);
    const plazoTxt = (min) => (min < 60 ? `${min} min` : min % 1440 === 0 ? `${min / 1440} día${min > 1440 ? 's' : ''}` : `${Math.round(min / 60)} h`);
    const pct = (a, b) => `${a >= b ? '+' : '−'}${ar.format('.2f')(Math.abs((a / b - 1) * 100))}%`;
    const ms = () => TF_MIN[R.tf] * 6e4;
    const conDia = () => TF_MIN[R.tf] >= 60 || R.B.length && new Date(R.B[0].t).toDateString() !== new Date().toDateString();

    $('repro-lapsos').append(...LAPSOS.map(([k, t]) => { const b = el('button', 'ab-chipbtn', t); b.type = 'button'; b.dataset.k = k; b.setAttribute('aria-pressed', 'false'); return b; }));

    const tfAuto = (desde, hasta) => TFS.find((tf) => (hasta - desde) / (TF_MIN[tf] * 6e4) <= 200) || '1d';
    function rango(k) {
      const hasta = Date.now();
      if (k === 'hoy') return [Math.min(new Date().setHours(0, 0, 0, 0), hasta - 36e5), hasta];
      return [hasta - HORAS[k] * 36e5, hasta];
    }

    // velas del lapso: de Binance (cualquier lapso, de a 1500); si no responde, las que tiene el analisis (300 por temporalidad)
    async function velas(tf, desde, hasta) {
      const m = TF_MIN[tf] * 6e4, sym = `${MON()}USDT`, out = [];
      try {
        for (let t = Math.floor(desde / m) * m; t < hasta && out.length < MAX_VELAS + 1500;) {
          const k = await (await fetch(`https://fapi.binance.com/fapi/v1/klines?symbol=${sym}&interval=${tf === '1d' ? '1d' : tf}&startTime=${t}&endTime=${hasta}&limit=1500`, { signal: AbortSignal.timeout(10000) })).json();
          if (!Array.isArray(k) || !k.length) break;
          k.forEach((r) => out.push({ t: +r[0], o: +r[1], h: +r[2], l: +r[3], c: +r[4] }));
          t = +k[k.length - 1][0] + m;
          if (k.length < 1500) break;
        }
      } catch (e) { out.length = 0; }
      if (out.length) return out;
      return pick(S.rows, 'vela', tf).map((r) => ({ t: num(r.t), o: num(r.o), h: num(r.h), l: num(r.l), c: num(r.c) }))
        .filter((b) => b.t >= desde - m && b.t <= hasta).sort((a, b) => a.t - b.t);
    }
    // historial del servidor: un archivo por temporalidad y dia (UTC). Columnas: t,h,precio,sube,min,max,mediana,obj_arriba,obj_abajo,toca_arriba,toca_abajo,primero_arriba,fuerte,prob_fuerte,prob_normal,umbral_fuerte
    async function historial(tf, desde, hasta) {
      if (MON() !== 'BTC') return [];
      const dias = [];
      for (let d = Math.floor(desde / 864e5) * 864e5; d <= hasta; d += 864e5) dias.push(new Date(d).toISOString().slice(0, 10));
      const txt = await Promise.all(dias.slice(-62).map((d) => fetch(`${HIST}/${tf}/${d}.csv`, { signal: AbortSignal.timeout(10000) }).then((r) => (r.ok ? r.text() : '')).catch(() => '')));
      const n = (x) => (x === '' || x === undefined ? null : +x), out = [];
      txt.forEach((t) => t.split('\n').slice(1).forEach((l) => {
        const c = l.split(','); if (c.length < 6) return;
        out.push([+c[0], tf, +c[1], +c[2], +c[3], n(c[4]), n(c[5]), c.length > 6 ? { m: n(c[6]), a: n(c[7]), b: n(c[8]), ta: n(c[9]), tb: n(c[10]), pa: n(c[11]), f: c[12] || null, pf: n(c[13]), pn: n(c[14]), u: n(c[15]) } : undefined]);
      }));
      return out;
    }

    function armarGrafico() {
      if (R.ch) return;
      const P = G.P || pal();
      R.ch = LW.createChart($('repro-chart'), { autoSize: true, layout: { background: { type: 'solid', color: 'rgba(0,0,0,0)' }, textColor: P.mute, fontFamily: cssv('--font-anthropic-sans'), attributionLogo: false },
        grid: { vertLines: { visible: false }, horzLines: { visible: false } }, rightPriceScale: { borderVisible: false }, crosshair: { mode: 0 },
        timeScale: { borderVisible: false, timeVisible: true, shiftVisibleRangeOnNewBar: false, rightOffset: 0 }, handleScroll: false, handleScale: false,
        localization: { priceFormatter: (v) => fp(v), timeFormatter: (t) => hhmm(t * 1000, true) } });
      R.serie = R.ch.addSeries(LW.CandlestickSeries, { upColor: P.up, downColor: P.dn, wickUpColor: P.up, wickDownColor: P.dn, borderVisible: false,
        priceLineVisible: false, lastValueVisible: true, autoscaleInfoProvider: () => (R.min ? { priceRange: { minValue: R.lo, maxValue: R.hi } } : null) });
      R.marcas = LW.createSeriesMarkers(R.serie, []);
      // tocar el grafico elige la prediccion mas cercana (de las que ya se ven)
      R.ch.subscribeClick((pr) => {
        if (!pr || pr.time === undefined) return;
        const t = pr.time * 1000, vis = R.preds.filter((q) => q.i <= R.i);
        if (!vis.length) return;
        R.fija = vis.reduce((a, q) => (Math.abs(R.B[q.i].t - t) < Math.abs(R.B[a.i].t - t) ? q : a));
        dibujar();
      });
    }

    async function cargar(desde, hasta, tfElegido) {
      armarGrafico(); pausar();
      const n = ++R.carga;
      R.tf = tfElegido || tfAuto(desde, hasta);
      const m = ms();
      let nota = '';
      if ((hasta - desde) / m > MAX_VELAS) { desde = hasta - MAX_VELAS * m; nota = `Con velas de ${R.tf} se muestran las últimas ${MAX_VELAS} (desde ${hhmm(desde, true)}).`; }
      $('repro-hora').textContent = 'Cargando…'; $('repro-nota').textContent = ''; $('rf-grid').replaceChildren(); $('rf-tit').textContent = '—'; $('rf-est').textContent = '';
      const [B, hist, local] = await Promise.all([velas(R.tf, desde, hasta), historial(R.tf, desde - m, hasta + m),
        window.abRegistro ? window.abRegistro(R.tf, desde - m, hasta + m) : []]);
      if (n !== R.carga) return;                     // eligieron otro lapso mientras cargaba
      R.B = B.filter((b) => b.t >= desde - m && b.t <= hasta);
      if (!R.B.length) { $('repro-hora').textContent = 'No hay velas de ese lapso.'; return; }
      if (R.B[0].t > desde + m) nota = `Con velas de ${R.tf} hay datos desde ${hhmm(R.B[0].t, true)}: se muestra desde ahí.`;
      R.min = Math.min(...R.B.map((b) => b.l)); R.max = Math.max(...R.B.map((b) => b.h)); R.lo = R.min; R.hi = R.max;
      // las del servidor y las del telefono juntas (la misma vela y horizonte una sola vez: gana la que trae objetivos)
      const una = new Map();
      hist.concat(local).forEach((r) => { const k = `${r[0]}|${r[2]}`, ya = una.get(k); if (!ya || (!ya[7] && r[7])) una.set(k, r); });
      const log = [...una.values()], idx = new Map(R.B.map((b, i) => [b.t, i]));
      // un solo horizonte (el que mas predicciones tiene; si empatan, el mas corto): mezclados no se entienden
      const porH = new Map(); log.forEach((r) => porH.set(r[2], (porH.get(r[2]) || 0) + 1));
      R.hMin = [...porH.entries()].sort((a, b) => b[1] - a[1] || a[0] - b[0]).map((x) => x[0])[0] || 0;
      // [t, tf, h, precio, % sube, rango bajo, rango alto, extras]: hecha al cierre de la vela que abre en t - ms
      R.preds = log.filter((r) => r[2] === R.hMin && idx.has(r[0] - m)).map((r) => {
        const i = idx.get(r[0] - m), fin = idx.get(r[0] + (r[2] - 1) * m), x = r[7] || {};
        return { i, fin: fin === undefined ? null : fin, h: r[2], p: r[3], pr: r[4], lo: r[5], hi: r[6], m: x.m, a: x.a, b: x.b, ta: x.ta, tb: x.tb, pa: x.pa,
          f: x.f || null, pf: x.pf, pn: x.pn, u: x.u };
      }).sort((a, b) => a.i - b.i);
      R.nota = nota + (R.preds.length ? '' : ' En este lapso no hay predicciones guardadas: se ven solo las velas.');
      $('repro-sub').textContent = `${R.B.length} velas de ${R.tf} · ${hhmm(R.B[0].t, true)} → ${hhmm(R.B[R.B.length - 1].t + m, true)} · ${R.preds.length === 1 ? '1 predicción' : `${R.preds.length} predicciones`}`;
      $('repro-pos').max = R.B.length - 1;
      R.ch.timeScale().applyOptions({ timeVisible: TF_MIN[R.tf] < 1440 });
      R.fija = null; R.i = 0; dibujar();
      reproducir();
    }

    // lo que fue pasando con una prediccion hasta la vela i: maximo, minimo, cuando toco cada objetivo, cierre
    function seguir(q, i) {
      const hasta = Math.min(i, q.fin === null ? R.B.length - 1 : q.fin);
      let hi = -Infinity, lo = Infinity, tA = null, tB = null;
      for (let k = q.i + 1; k <= hasta; k++) {
        const b = R.B[k]; hi = Math.max(hi, b.h); lo = Math.min(lo, b.l);
        if (q.a && tA === null && b.h >= q.a) tA = k;
        if (q.b && tB === null && b.l <= q.b) tB = k;
      }
      const listo = q.fin !== null && q.fin <= i, cierre = hasta > q.i ? R.B[hasta].c : null;
      return { listo, hasta, hi, lo, tA, tB, cierre, velas: hasta - q.i, acerto: listo && q.pr !== 50 ? (q.pr > 50) === (cierre > q.p) : null };
    }
    // movimiento fuerte: en la hora siguiente a la prediccion, ¿el rango (maximo - minimo) paso el doble del normal (u)?
    // Con velas de mas de 1 h no se ve esa hora sola: no se juzga
    function fuerte(q, i) {
      if (!q.f || !q.u) return null;
      const m = ms(), t0 = R.B[q.i].t + m, t1 = t0 + 36e5;
      if (m > 36e5) return { f: q.f, sinVer: true };
      let hi = -Infinity, lo = Infinity, ult = null;
      for (let k = q.i + 1; k < R.B.length && R.B[k].t + m <= t1; k++) { if (k > i) break; hi = Math.max(hi, R.B[k].h); lo = Math.min(lo, R.B[k].l); ult = k; }
      const fin = R.B.findIndex((b) => b.t + m >= t1), listo = fin !== -1 && fin <= i;
      const mov = ult === null ? null : ((hi - lo) / q.p) * 100, hubo = mov !== null && mov >= q.u;
      const acerto = !listo && !hubo ? null : q.f === 'media' ? null : (q.f === 'alta') === hubo;
      return { f: q.f, mov, hubo, listo: listo || hubo, acerto: listo || hubo ? acerto : null, fin };
    }
    const celda = (cls, ...hijos) => { const e = el('span', cls); hijos.forEach((h) => e.append(typeof h === 'string' ? document.createTextNode(h) : h)); return e; };
    function ficha(q, i) {
      const g = $('rf-grid'), m = ms();
      g.replaceChildren();
      if (!q) {
        $('rf-tit').textContent = R.preds.length ? 'Todavía sin predicción en este lapso' : 'Sin predicciones guardadas';
        $('rf-est').textContent = R.preds.length ? 'Aparece cuando la reproducción llega a la primera.' : 'Se ven solo las velas.';
        return;
      }
      const f = seguir(q, i), plazo = plazoTxt(q.h * TF_MIN[R.tf]);
      $('rf-tit').textContent = `Predicción de las ${hhmm(R.B[q.i].t + m, conDia())} · a ${plazo}`;
      $('rf-est').textContent = f.listo ? `Terminó a las ${hhmm(R.B[q.fin].t + m, conDia())}` : f.velas > 0 ? `En curso: van ${f.velas} de ${q.h} velas` : 'Recién hecha';
      const fila = (k, v, r, cls) => g.append(celda('k', k), celda('v', ...v), celda(`r ${cls || ''}`, ...r));
      const B_ = (x) => el('b', '', x);
      fila('Precio al predecir', [B_(fp(q.p))], f.cierre !== null ? [f.listo ? 'Cerró en ' : 'Ahora ', B_(fp(f.cierre)), ` (${pct(f.cierre, q.p)})`] : ['—'], 'va');
      const lado = q.pr > 50 ? 'suba' : q.pr < 50 ? 'baje' : null;
      fila('Dirección', [B_(`${ar.format('.0f')(lado === 'baje' ? 100 - q.pr : q.pr)}%`), lado ? ` de que ${lado}` : ' (pareja)'],
        f.acerto === null ? [f.listo ? 'Sin dirección que juzgar' : 'Se sabe al final del plazo'] : [f.acerto ? '✓ Acertó: terminó ' : '✗ Terminó ', f.cierre > q.p ? 'arriba' : 'abajo'],
        f.acerto === null ? 'va' : f.acerto ? 'si' : 'no');
      if (q.m) fila('Precio más probable', [B_(fp(q.m))], f.listo ? ['Cerró a ', B_(pct(f.cierre, q.m).replace(/^[+−]/, '')), ' de ese precio'] : ['—'], 'va');
      if (q.lo) {
        const adentro = f.listo ? f.cierre >= q.lo && f.cierre <= q.hi : null;
        fila('Rango del 80%', [B_(`${fp(q.lo)}–${fp(q.hi)}`)], adentro === null ? ['Se sabe al final del plazo'] : [adentro ? '✓ Cerró adentro' : '✗ Cerró afuera'], adentro === null ? 'va' : adentro ? 'si' : 'no');
      }
      const obj = (nombre, nivel, chance, t, extremo, arriba) => {
        if (!nivel) return;
        const r = t !== null ? ['✓ Llegó a las ', B_(hhmm(R.B[t].t, conDia()))]
          : f.velas > 0 ? [f.listo ? '✗ No llegó: ' : 'Todavía no: ', `${arriba ? 'máximo' : 'mínimo'} `, B_(fp(extremo)), ` (le falta ${pct(nivel, extremo).replace(/^[+−]/, '')})`] : ['—'];
        fila(nombre, [B_(fp(nivel)), chance !== null && chance !== undefined ? ` · chance de tocarlo ${ar.format('.0f')(chance)}%` : ''], r, t !== null ? 'si' : f.listo ? 'no' : 'va');
      };
      obj('Objetivo ↑', q.a, q.ta, f.tA, f.hi, true);
      obj('Objetivo ↓', q.b, q.tb, f.tB, f.lo, false);
      if (q.pa !== null && q.pa !== undefined && q.a && q.b) {
        const pri = f.tA !== null && (f.tB === null || f.tA < f.tB) ? 'arriba' : f.tB !== null && (f.tA === null || f.tB < f.tA) ? 'abajo' : f.tA !== null ? 'los dos en la misma vela' : null;
        const decia = q.pa >= 50 ? 'arriba' : 'abajo';
        fila('Qué tocaba primero', [B_(`${decia} ${ar.format('.0f')(Math.max(q.pa, 100 - q.pa))}%`)],
          pri ? [pri === decia ? '✓ ' : pri.startsWith('los') ? '' : '✗ ', `Tocó primero ${pri}`] : [f.listo ? 'No tocó ninguno' : 'Todavía ninguno'],
          pri ? (pri === decia ? 'si' : pri.startsWith('los') ? 'va' : 'no') : 'va');
      }
      const fz = fuerte(q, i);
      if (fz) {
        const dijo = fz.f === 'alta' ? 'Sí' : fz.f === 'media' ? 'Puede' : 'No';
        const r = fz.sinVer ? ['Con velas de más de 1 h no se ve la hora siguiente']
          : fz.mov === null ? ['—']
          : fz.hubo ? [fz.acerto === true ? '✓ ' : fz.acerto === false ? '✗ ' : '', 'Hubo: se movió ', B_(`${ar.format('.2f')(fz.mov)}%`), ` (fuerte desde ${ar.format('.2f')(q.u)}%)`]
          : fz.listo ? [fz.acerto === true ? '✓ ' : fz.acerto === false ? '✗ ' : '', 'No hubo: se movió ', B_(`${ar.format('.2f')(fz.mov)}%`), ` (fuerte desde ${ar.format('.2f')(q.u)}%)`]
          : ['Va ', B_(`${ar.format('.2f')(fz.mov)}%`), ` de ${ar.format('.2f')(q.u)}%`];
        fila('Movimiento fuerte (1 h)', [B_(dijo), q.pf !== null && q.pf !== undefined ? ` · chance ${ar.format('.0f')(q.pf)}%${q.pn ? ` (lo normal ${ar.format('.0f')(q.pn)}%)` : ''}` : ''], r,
          fz.acerto === true ? 'si' : fz.acerto === false ? 'no' : 'va');
      }
      if (q.a === undefined) g.append(el('span', 'ab-rf-vacia', 'Guardada antes de que se anotaran los objetivos y el movimiento fuerte: solo chance y rango.'));
      else if (!q.f) g.append(el('span', 'ab-rf-vacia', 'Guardada antes de que se anotara el movimiento fuerte.'));
    }

    function dibujar() {
      const i = R.i, P = G.P || pal(), m = ms();
      const vistas = R.preds.filter((q) => q.i <= i);
      const sel = R.fija && R.fija.i <= i ? R.fija : vistas[vistas.length - 1];
      if (R.fija && R.fija.i > i) R.fija = null;
      $('rf-auto').hidden = !R.fija;
      // la escala: el lapso y los niveles de la prediccion elegida
      const niv = sel ? [sel.a, sel.b, sel.lo, sel.hi].filter((x) => x) : [];
      R.lo = Math.min(R.min, ...niv); R.hi = Math.max(R.max, ...niv);
      R.serie.setData(R.B.slice(0, i + 1).map((b) => ({ time: b.t / 1000, open: b.o, high: b.h, low: b.l, close: b.c })));
      R.ch.timeScale().setVisibleLogicalRange({ from: -1, to: R.B.length });
      $('repro-pos').value = i;
      // marcas: las que se jugaban (55% o mas para un lado), a lo sumo unas 40 repartidas; la elegida siempre, mas grande,
      // y donde toco sus objetivos
      const jug = R.preds.filter((q) => q.pr >= 55 || q.pr <= 45), cada = Math.max(1, Math.ceil(jug.length / 40));
      const mk = vistas.filter((q) => q === sel || ((q.pr >= 55 || q.pr <= 45) && jug.indexOf(q) % cada === 0)).map((q) => {
        const f = seguir(q, i), sube = q.pr >= 55, baja = q.pr <= 45;
        return { time: R.B[q.i].t / 1000, position: sube ? 'belowBar' : 'aboveBar', shape: sube ? 'arrowUp' : baja ? 'arrowDown' : 'circle', size: q === sel ? 1.3 : 0.6,
          color: f.acerto === null ? (sube ? P.up : baja ? P.dn : P.mute) : f.acerto ? P.up : P.dn, text: q === sel ? (f.acerto === null ? 'esta' : f.acerto ? '✓ esta' : '✗ esta') : f.acerto === null ? '' : f.acerto ? '✓' : '✗' };
      });
      // donde avisaba movimiento fuerte (el primer aviso de cada racha), con lo que paso
      let antes = null;
      vistas.forEach((q) => {
        if (q.f === 'alta' && antes !== 'alta') {
          const fz = fuerte(q, i);
          mk.push({ time: R.B[q.i].t / 1000, position: 'aboveBar', shape: 'square', size: 0.5, color: cssv('--color-warn'),
            text: fz && fz.acerto === true ? '⚡✓' : fz && fz.acerto === false ? '⚡✗' : '⚡' });
        }
        antes = q.f;
      });
      if (sel) {
        const f = seguir(sel, i);
        if (f.tA !== null) mk.push({ time: R.B[f.tA].t / 1000, position: 'aboveBar', shape: 'circle', size: 0.7, color: P.up, text: 'obj ↑' });
        if (f.tB !== null) mk.push({ time: R.B[f.tB].t / 1000, position: 'belowBar', shape: 'circle', size: 0.7, color: P.dn, text: 'obj ↓' });
      }
      R.marcas.setMarkers(mk.sort((a, b) => a.time - b.time));
      R.lineas.forEach((l) => R.serie.removePriceLine(l)); R.lineas = [];
      if (sel) {
        const linea = (price, color, title, st) => price && R.lineas.push(R.serie.createPriceLine({ price, color, lineWidth: 1, lineStyle: st, axisLabelVisible: true, title }));
        linea(sel.p, alpha(P.ink || cssv('--color-fg'), 0.7), 'entrada', LW.LineStyle.Dotted);
        linea(sel.a, P.up, 'obj ↑', LW.LineStyle.Dashed); linea(sel.b, P.dn, 'obj ↓', LW.LineStyle.Dashed);
        linea(sel.lo, alpha(P.mute, 0.8), '80%', LW.LineStyle.SparseDotted); linea(sel.hi, alpha(P.mute, 0.8), '80%', LW.LineStyle.SparseDotted);
      }
      const b = R.B[i];
      $('repro-hora').textContent = `${hhmm(b.t + m, conDia())} · ${fp(b.c)}`;
      const res = R.preds.filter((q) => q.fin !== null && q.fin <= i && q.pr !== 50), bien = res.filter((q) => seguir(q, i).acerto).length;
      $('repro-nota').textContent = R.nota || '';
      $('repro-res').replaceChildren();
      if (res.length) $('repro-res').append('Hasta acá: acertó la dirección en ', el('b', '', `${bien} de ${res.length}`), ` (${ar.format('.0f')((bien / res.length) * 100)}%) de las predicciones a ${plazoTxt(R.hMin * TF_MIN[R.tf])} que ya terminaron.`);
      // movimiento fuerte: una vez por hora (todas las de la misma hora dicen lo mismo)
      if (ms() <= 36e5) {
        const porHora = new Map();
        R.preds.forEach((q) => { if (q.f && q.u && q.i <= i) { const k = Math.floor((R.B[q.i].t + ms()) / 36e5); if (!porHora.has(k)) porHora.set(k, q); } });
        const js = [...porHora.values()].map((q) => [q, fuerte(q, i)]).filter(([, z]) => z && z.listo);
        const hubo = js.filter(([, z]) => z.hubo), aviso = js.filter(([q]) => q.f === 'alta');
        if (js.length) {
          const sin = hubo.filter(([q]) => q.f !== 'alta').length, puede = hubo.filter(([q]) => q.f === 'media').length;
          $('repro-res').append(el('br'), 'Movimiento fuerte: hubo en ', el('b', '', `${hubo.length} de ${js.length}`), ` hora${js.length === 1 ? '' : 's'}; `,
            ...(aviso.length ? ['avisó ', el('b', '', String(aviso.length)), ` ${aviso.length === 1 ? 'vez' : 'veces'} y acertó ${aviso.filter(([, z]) => z.hubo).length}`] : ['no avisó ninguna']),
            sin ? `; ${sin === 1 ? 'uno vino' : `${sin} vinieron`} sin aviso${puede ? ` (${puede} con "Puede")` : ''}.` : '.');
        }
      }
      ficha(sel, i);
    }
    function paso() {
      if (R.i >= R.B.length - 1) { pausar(); return; }
      R.i += 1; dibujar();
      R.timer = setTimeout(paso, Math.max(35, Math.min(400, 12000 / R.B.length)) / R.vel);
    }
    function reproducir() {
      if (!R.B.length) return;
      if (R.i >= R.B.length - 1) { R.i = 0; R.fija = null; dibujar(); }
      R.play = true; $('repro-play').textContent = '❚❚'; $('repro-play').setAttribute('aria-label', 'Pausar');
      clearTimeout(R.timer); R.timer = setTimeout(paso, reduce ? 600 : 250);
    }
    function pausar() { R.play = false; clearTimeout(R.timer); $('repro-play').textContent = '▶'; $('repro-play').setAttribute('aria-label', 'Reproducir'); }
    function elegirLapso(k) {
      R.lapso = k;
      [...$('repro-lapsos').children].forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.k === k)));
      $('repro-elegir').hidden = k !== 'elegir';
      if (k === 'elegir') {
        if (!$('repro-hasta').value) { $('repro-hasta').value = enLocal(Date.now()); $('repro-desde').value = enLocal(Date.now() - 864e5); }
        $('repro-hasta').max = $('repro-desde').max = enLocal(Date.now());
        return;
      }
      cargar(...rango(k));
    }
    // anterior / siguiente: entre las predicciones que ya se ven (con la reproduccion terminada, todas)
    function mover(d) {
      const vis = R.preds.filter((q) => q.i <= R.i);
      if (!vis.length) return;
      const act = R.fija || vis[vis.length - 1], k = Math.max(0, Math.min(vis.length - 1, vis.indexOf(act) + d));
      R.fija = vis[k]; dibujar();
    }
    function abrir() {
      if (!S.rows) return;
      pan.hidden = false; fondo.hidden = false; document.documentElement.style.overflow = 'hidden'; abFoco(pan, true);
      elegirLapso(R.lapso);
    }
    function cerrar() {
      if (pan.hidden) return;
      pausar(); abFoco(pan, false); pan.hidden = true; fondo.hidden = true; document.documentElement.style.overflow = '';
    }
    btn.addEventListener('click', abrir);
    $('repro-x').addEventListener('click', cerrar); fondo.addEventListener('click', cerrar);
    document.addEventListener('keydown', (e) => {
      if (pan.hidden) return;
      if (e.key === 'Escape') cerrar();
      else if (e.key === 'ArrowLeft' && !e.target.closest('input, select')) mover(-1);
      else if (e.key === 'ArrowRight' && !e.target.closest('input, select')) mover(1);
    });
    $('repro-lapsos').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) elegirLapso(b.dataset.k); });
    $('repro-ver').addEventListener('click', () => {
      const d = new Date($('repro-desde').value).getTime(), h = Math.min(Date.now(), new Date($('repro-hasta').value).getTime());
      if (!(d < h)) { $('repro-hora').textContent = '"Desde" tiene que ser antes que "Hasta".'; return; }
      cargar(d, h, $('repro-tf').value || null);
    });
    $('repro-play').addEventListener('click', () => (R.play ? pausar() : reproducir()));
    $('repro-pos').addEventListener('input', (e) => { pausar(); R.i = +e.target.value; dibujar(); });
    $('rf-prev').addEventListener('click', () => mover(-1));
    $('rf-next').addEventListener('click', () => mover(1));
    $('rf-auto').addEventListener('click', () => { R.fija = null; dibujar(); });
    $('repro-vel').addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      R.vel = +b.dataset.v; [...$('repro-vel').children].forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      if (R.play) { clearTimeout(R.timer); R.timer = setTimeout(paso, 50); }
    });
    // con el tema cambia la paleta: el grafico se rearma al abrir de nuevo
    new MutationObserver(() => { if (R.ch && pan.hidden) { R.ch.remove(); R.ch = null; } }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  })();

  // ---------- mapa de liquidaciones (panel aparte), al estilo de Coinglass / mapaliquidaciones.com ----------
  // Estimacion propia con datos publicos (api/liquidaciones.js: open interest de Binance, Bybit y OKX, largos/cortos de
  // Binance y Bybit, liquidaciones reales de OKX). Cada vez que sube el open interest, lo nuevo se reparte entre largos y
  // cortos (segun la proporcion de cuentas) y entre apalancamientos tipicos, al precio medio de esa vela; cada posicion
  // tiene su precio de liquidacion (entrada x (1 -/+ 1/apalancamiento), con 0,5% de margen de mantenimiento). Cuando una
  // vela cruza ese precio, se liquida y la franja se corta; cuando el open interest baja, se cierran en proporcion; y
  // con el tiempo se van cerrando solas (vida media). El color compara cada nivel con el mas cargado de la vista: azul,
  // cian, verde, amarillo, rojo. Cortos arriba del precio, largos abajo. No es una prediccion ni consejo financiero.
  const LiqMapa = (function () {
    const MS = { '5m': 3e5, '15m': 9e5, '1h': 36e5, '4h': 144e5, '1d': 864e5 };
    const VIDA = { '5m': 864e5, '15m': 2 * 864e5, '1h': 5 * 864e5, '4h': 20 * 864e5, '1d': 120 * 864e5 };
    // los apalancamientos de TradingDifferent, con cuanto del open interest nuevo se lleva cada uno (aprox.: el grueso
    // entre 10x y 50x). Se eligen cuales mostrar; los que no, no se suman (no se reparte de nuevo)
    const NIVELES = [[3, 0.06], [5, 0.1], [10, 0.22], [25, 0.27], [50, 0.2], [100, 0.15]];
    const COLOR_X = { 3: '#7dd3fc', 5: '#60a5fa', 10: '#a78bfa', 25: '#f472b6', 50: '#fb923c', 100: '#facc15' };
    const NB0 = 320, MANT = 0.005;
    function serieEn(pares, ms) {     // [[t, valor]] -> valor en cada apertura de vela (el dato de esa vela, o el de la anterior)
      const m = new Map(); pares.forEach(([t, v]) => { m.set(Math.floor(t / ms) * ms, v); });
      return m;
    }
    function simular(d, elegidos) {
      const V = d.velas, n = V.length, ms = MS[d.tf], ver = Math.min(d.ver, n - 1), ini = n - ver;
      let lo = Infinity, hi = -Infinity;
      for (let j = ini; j < n; j++) { lo = Math.min(lo, V[j][3]); hi = Math.max(hi, V[j][2]); }
      const tiers = NIVELES.filter(([x]) => !Array.isArray(elegidos) || elegidos.includes(x)), T = tiers.length;
      // la vista (vLo-vHi) es la de antes; la grilla se estira hasta donde caen los apalancamientos elegidos (3x queda a
      // ~33 %: para verlo hay que arrastrar el eje de precios), con el mismo paso, asi no pierde detalle
      const pad = (hi - lo) * 0.45 + hi * 0.004, vLo = lo - pad, vHi = hi + pad, paso = (vHi - vLo) / NB0;
      const lejos = T ? Math.min(0.36, 1 / Math.min(...tiers.map(([x]) => x)) + 0.01) : 0;
      const gLo = Math.min(vLo, lo * (1 - lejos)), gHi = Math.max(vHi, hi * (1 + lejos));
      const NB = Math.min(2400, Math.ceil((gHi - gLo) / paso));
      const bin = (p) => Math.floor((p - gLo) / paso), precioBin = (k) => gLo + (k + 0.5) * paso;
      const fuentes = Object.values(d.oi).filter((s) => s.length > 1).map((s) => serieEn(s, ms));
      const lsF = Object.values(d.ls).filter((s) => s.length).map((s) => serieEn(s, ms));
      // por apalancamiento (para el perfil apilado): Lt[i] / St[i]; L y S2 son la suma
      const Lt = tiers.map(() => new Float64Array(NB)), St = tiers.map(() => new Float64Array(NB));
      const L = new Float64Array(NB), S2 = new Float64Array(NB), grid = new Float32Array(ver * NB), liqEst = new Float64Array(ver);
      const dec = Math.pow(0.5, ms / VIDA[d.tf]);
      let lsUlt = 0.5;
      for (let j = 1; j < n; j++) {
        const [t, , h, l, c] = V[j], tp = V[j - 1][0];
        // 1) lo que cruzo esta vela se liquida (largos con su precio arriba del minimo, cortos debajo del maximo)
        let quemado = 0;
        const kl = Math.max(0, bin(l)), ks = Math.min(NB - 1, bin(h));
        for (let i = 0; i < T; i++) {
          for (let k = kl; k < NB; k++) { quemado += Lt[i][k]; Lt[i][k] = 0; }
          for (let k = 0; k <= ks; k++) { quemado += St[i][k]; St[i][k] = 0; }
        }
        // 2) cambio del open interest, sumando cada exchange (cada uno con su propio cambio)
        let delta = 0, total = 0;
        fuentes.forEach((f) => { const a = f.get(t), b = f.get(tp); if (a !== undefined && b !== undefined) { delta += a - b; total += b; } });
        const f = dec * (delta < 0 && total > 0 ? Math.max(0, 1 + delta / total) : 1);
        for (let i = 0; i < T; i++) for (let k = 0; k < NB; k++) { Lt[i][k] *= f; St[i][k] *= f; }
        // 3) lo nuevo: largos y cortos segun las cuentas, en cada apalancamiento, al precio medio de la vela
        if (delta > 0) {
          const v = lsF.map((m) => m.get(t)).filter((x) => x !== undefined);
          if (v.length) lsUlt = v.reduce((a, b) => a + b, 0) / v.length;
          const e = (h + l + c) / 3;
          tiers.forEach(([lev, w], i) => {
            const pl = e * (1 - 1 / lev + MANT), ps = e * (1 + 1 / lev - MANT), kL = bin(pl), kS = bin(ps);
            if (pl < l && kL >= 0 && kL < NB) Lt[i][kL] += delta * lsUlt * w;
            if (ps > h && kS >= 0 && kS < NB) St[i][kS] += delta * (1 - lsUlt) * w;
          });
        }
        if (j >= ini) {
          const o = (j - ini) * NB;
          for (let k = 0; k < NB; k++) { let v = 0; for (let i = 0; i < T; i++) v += Lt[i][k] + St[i][k]; grid[o + k] = v; }
          liqEst[j - ini] = quemado;
        }
      }
      for (let k = 0; k < NB; k++) for (let i = 0; i < T; i++) { L[k] += Lt[i][k]; S2[k] += St[i][k]; }
      return { V: V.slice(ini), grid, NB, gLo, gHi: gLo + NB * paso, vLo, vHi, paso, ver, L, S: S2, Lt, St, tiers: tiers.map(([x]) => x), liqEst, precioBin, ms };
    }
    // zonas brillantes sobre violeta oscuro, como TradingDifferent: violeta -> magenta -> rojo coral -> naranja ->
    // amarillo -> casi blanco en lo mas cargado; x de 0 a 1
    const STOPS = [[0, [40, 16, 84]], [0.18, [84, 24, 128]], [0.36, [146, 38, 146]], [0.54, [214, 64, 112]], [0.7, [246, 116, 60]],
      [0.84, [252, 186, 52]], [0.94, [253, 230, 110]], [1, [255, 250, 205]]];
    function color(x) {
      for (let i = 1; i < STOPS.length; i++) if (x <= STOPS[i][0]) {
        const [a, ca] = STOPS[i - 1], [b, cb] = STOPS[i], u = (x - a) / (b - a);
        return ca.map((v, k) => Math.round(v + (cb[k] - v) * u));
      }
      return STOPS[STOPS.length - 1][1];
    }
    // cada columna, difuminada entre niveles vecinos (gaussiana de ~1,6 niveles): franjas continuas en vez de rayas de un
    // pixel. Solo para dibujar: los numeros (al pasar el dedo, el perfil, los totales) salen del mapa sin difuminar
    // el mapa como franjas nitidas (sin difuminar ni escalar una imagen): por cada nivel de precio, tramos de velas
    // seguidas con el mismo tono (Q tonos); se dibujan como rectangulos en pixeles reales de la pantalla
    const Q = 56;
    const TONOS = Array.from({ length: Q + 1 }, (_, q) => { const [r, g, b] = color(q / Q); return [r, g, b]; });
    function imagen(m, minimo) {
      const g = m.grid;
      // el brillo compara con lo mas cargado de la vista inicial (lo lejano de 3x-5x no apaga lo de cerca)
      const k0 = Math.max(0, Math.floor((m.vLo - m.gLo) / m.paso)), k1 = Math.min(m.NB, Math.ceil((m.vHi - m.gLo) / m.paso));
      let mx = 0; for (let c = 0; c < m.ver; c++) for (let k = k0; k < k1; k++) { const v = g[c * m.NB + k]; if (v > mx) mx = v; }
      // estilos por tono: color de la escala y transparencia que sube desde el minimo elegido (sin bordes duros)
      const estilo = TONOS.map(([r, gg, b], q) => { const x = q / Q, u = Math.min(1, Math.max(0, (x - minimo) / Math.max(0.05, 1 - minimo)));
        return `rgba(${r},${gg},${b},${Math.min(0.97, 0.03 + 0.94 * Math.pow(u, 1.35)).toFixed(3)})`; });
      const filas = [];                                              // [k, [c0, c1, tono, ...]]
      if (mx > 0) for (let k = 0; k < m.NB; k++) {
        const tr = []; let c0 = -1, t0 = 0;
        for (let c = 0; c <= m.ver; c++) {
          let t = 0;
          if (c < m.ver) { const x = Math.min(1, Math.pow(g[c * m.NB + k] / mx, 0.8)); if (x > minimo) t = Math.max(1, Math.round(x * Q)); }
          if (t !== t0) { if (t0) tr.push(c0, c - 1, t0); c0 = c; t0 = t; }
        }
        if (tr.length) filas.push([k, tr]);
      }
      return { filas, estilo, mx };
    }
    return { simular, imagen, color, MS, NIVELES, COLOR_X };
  })();

  (function () {
    const $ = (id) => document.getElementById(id), pan = $('lm'), fondo = $('lm-fondo');
    const MON_LM = ['BTC', 'ETH', 'SOL', 'XRP', 'BNB', 'DOGE', 'ADA', 'AVAX', 'LINK', 'LTC', 'SUI', 'ZEC', 'TRX', 'DOT', 'NEAR', 'APT', 'ARB', 'OP', 'TON', 'HYPE'];
    const LM = { tf: '1h', niveles: [3, 5, 10, 25, 50, 100], minimo: 0.15, perfil: true, datos: null, m: null, img: null, ch: null, serie: null, carga: 0, mon: 'BTC' };
    const sel = $('lm-mon'); sel.append(...MON_LM.map((m) => { const o = el('option', '', m); o.value = m; return o; }));
    const usd = (x) => (x >= 1e9 ? `${ar.format(',.2f')(x / 1e9)} mil M` : x >= 1e6 ? `${ar.format(',.1f')(x / 1e6)} M` : x >= 1e3 ? `${f0(x / 1e3)} mil` : x > 0 ? 'menos de mil' : '0');
    // liquidaciones en vivo: t, lado ('l' largos liquidados, 's' cortos), precio, USD, exchange, cuando llego (para animar)
    const VIVO = { items: [], socks: [], gen: 0, t: 0, quieto: matchMedia('(prefers-reduced-motion: reduce)').matches, raf: 0, lista: 0 };
    // la capa del mapa, detras de las velas (primitiva de Lightweight Charts)
    const capa = {
      _vista: null,
      attached({ chart, series }) { this._ch = chart; this._s = series; },
      updateAllViews() {},
      paneViews() {
        const self = this;
        return [{ zOrder: () => 'bottom', renderer: () => ({ draw() {}, drawBackground(target) {
          if (!LM.img || !LM.m) return;
          const ts = self._ch.timeScale(), m = LM.m, V = m.V;
          const x0 = ts.timeToCoordinate(V[0][0] / 1000), x1 = ts.timeToCoordinate(V[V.length - 1][0] / 1000);
          if (x0 === null || x1 === null) return;
          const bw = V.length > 1 ? (x1 - x0) / (V.length - 1) : 6, tUlt = V[V.length - 1][0];
          // con la vela en vivo, lo que sigue cargado al final se estira hasta ella
          const extra = VIVO.t > tUlt ? Math.round((VIVO.t - tUlt) / m.ms) : 0;
          // franjas en pixeles del dispositivo, redondeadas: bordes nitidos, sin escalar ni difuminar
          target.useBitmapCoordinateSpace(({ context: ctx, bitmapSize, horizontalPixelRatio: hr, verticalPixelRatio: vr }) => {
            const Wb = bitmapSize.width, Hb = bitmapSize.height, img = LM.img;
            let ult = null;
            img.filas.forEach(([k, tr]) => {
              const ya = self._s.priceToCoordinate(m.gLo + (k + 1) * m.paso), yb = self._s.priceToCoordinate(m.gLo + k * m.paso);
              if (ya === null || yb === null) return;
              const a = Math.round(ya * vr), h = Math.max(1, Math.round(yb * vr) - a);
              if (a > Hb || a + h < 0) return;
              for (let i = 0; i < tr.length; i += 3) {
                const fin = tr[i + 1] === m.ver - 1 ? tr[i + 1] + extra : tr[i + 1];
                const xa = Math.max(0, Math.round((x0 + (tr[i] - 0.5) * bw) * hr)), xb = Math.min(Wb, Math.round((x0 + (fin + 0.5) * bw) * hr));
                if (xb <= xa) continue;
                const st = img.estilo[tr[i + 2]]; if (st !== ult) { ctx.fillStyle = st; ult = st; }
                ctx.fillRect(xa, a, xb - xa, h);
              }
            });
          });
          target.useMediaCoordinateSpace(({ context: ctx }) => {
            ctx.save();
            // liquidaciones reales (OKX): circulos, rojo = largos liquidados, verde = cortos
            const P = G.P || pal();
            (LM.datos.liq || []).forEach(([t, lado, p, u]) => {
              if (t < V[0][0] || u < 2e4) return;
              const x = ts.timeToCoordinate(Math.floor(t / m.ms) * m.ms / 1000), y = self._s.priceToCoordinate(p);
              if (x === null || y === null) return;
              ctx.beginPath(); ctx.arc(x, y, Math.max(2, Math.min(14, Math.sqrt(u / 2e4) * 2)), 0, 2 * Math.PI);
              ctx.fillStyle = alpha(lado === 'l' ? P.dn : P.up, 0.55); ctx.strokeStyle = '#fff'; ctx.lineWidth = 0.8; ctx.fill(); ctx.stroke();
            });
            // en vivo (Binance, Bybit, OKX): en su momento y su precio; al llegar crecen y dejan un anillo que se abre
            const ahora = performance.now();
            VIVO.items.forEach((it) => {
              const x = x1 + (it.t - tUlt - m.ms / 2) / m.ms * bw, y = self._s.priceToCoordinate(it.p);
              if (y === null || x < -20) return;
              const r = Math.max(2.5, Math.min(18, Math.sqrt(it.u / 1e4) * 2.2)), a = VIVO.quieto ? 1 : Math.min(1, (ahora - it.nace) / 900);
              const c = it.lado === 'l' ? P.dn : P.up, e = 1 - Math.pow(1 - a, 3);
              if (a < 1) { ctx.beginPath(); ctx.arc(x, y, r * (1 + 1.6 * e), 0, 2 * Math.PI); ctx.strokeStyle = alpha(c, 0.7 * (1 - a)); ctx.lineWidth = 2; ctx.stroke(); }
              ctx.beginPath(); ctx.arc(x, y, r * (0.5 + 0.5 * e), 0, 2 * Math.PI);
              ctx.fillStyle = alpha(c, 0.75); ctx.strokeStyle = 'rgba(255,255,255,.9)'; ctx.lineWidth = 1; ctx.fill(); ctx.stroke();
            });
            ctx.restore();
          });
        } }) }];
      },
    };
    function armar() {
      if (LM.ch) return;
      const P = G.P || pal();
      LM.ch = LW.createChart($('lm-chart'), { autoSize: true, layout: { background: { type: 'solid', color: 'rgba(0,0,0,0)' }, textColor: '#9aa3b5', fontFamily: cssv('--font-anthropic-sans'), attributionLogo: false },
        grid: { vertLines: { visible: false }, horzLines: { visible: false } }, rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.04, bottom: 0.04 } },
        timeScale: { borderVisible: false, timeVisible: true, rightOffset: 2 }, crosshair: { mode: 0 },
        localization: { priceFormatter: (v) => fp(v), timeFormatter: (t) => new Date(t * 1000).toLocaleString('es-AR', { ...tz, day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }) } });
      LM.serie = LM.ch.addSeries(LW.CandlestickSeries, { upColor: '#22ab94', downColor: '#f7525f', wickUpColor: '#22ab94', wickDownColor: '#f7525f', borderVisible: false, priceLineVisible: false,
        autoscaleInfoProvider: (orig) => { const r = orig(); if (!r || !LM.m) return r; const pad = (LM.m.vHi - LM.m.vLo) * 0.18; return { priceRange: { minValue: Math.max(LM.m.vLo, r.priceRange.minValue - pad), maxValue: Math.min(LM.m.vHi, r.priceRange.maxValue + pad) } }; } });
      LM.serie.attachPrimitive(capa);
      // al pasar el dedo: cuanto hay estimado en ese precio y en ese momento
      LM.ch.subscribeCrosshairMove((p) => {
        const info = $('lm-punto');
        if (!p || !p.point || p.time === undefined || !LM.m) { info.textContent = ''; return; }
        const m = LM.m, c = m.V.findIndex((b) => b[0] / 1000 === p.time), pr = LM.serie.coordinateToPrice(p.point.y);
        if (c < 0 || pr === null) { info.textContent = ''; return; }
        const k = Math.floor((pr - m.gLo) / m.paso); if (k < 0 || k >= m.NB) { info.textContent = ''; return; }
        let v = 0; for (let q = Math.max(0, k - 1); q <= Math.min(m.NB - 1, k + 1); q++) v += m.grid[c * m.NB + q];
        info.textContent = `${fp(pr)}: ~${usd(v)} USD en liquidaciones estimadas (${pr > m.V[c][4] ? 'cortos' : 'largos'})`;
      });
    }
    // espacio a la derecha de la ultima vela del ancho del perfil: lo nuevo (vela y burbujas en vivo) no queda tapado
    function hueco() {
      if (!LM.ch) return;
      const ts = LM.ch.timeScale(), w = LM.perfil ? $('lm-perfil').clientWidth + 14 : 0;
      for (let i = 0; i < 2; i++) { ts.applyOptions({ rightOffset: Math.max(2, Math.ceil(w / ts.options().barSpacing)) }); ts.fitContent(); }
    }
    function perfil() {
      const cv = $('lm-perfil'), m = LM.m;
      cv.hidden = !LM.perfil || !m; if (cv.hidden) return;
      const W = cv.clientWidth, H = cv.clientHeight, dpr = window.devicePixelRatio || 1;
      cv.width = W * dpr; cv.height = H * dpr;
      const ctx = cv.getContext('2d'); ctx.scale(dpr, dpr); ctx.clearRect(0, 0, W, H);
      let mx = 0; for (let k = 0; k < m.NB; k++) mx = Math.max(mx, m.L[k], m.S[k]);
      if (!mx) return;
      const y = (p) => LM.serie.priceToCoordinate(p), P = G.P || pal(), ahora = m.V[m.V.length - 1][4];
      const crudo = Float64Array.from({ length: m.NB }, (_, k) => m.L[k] + m.S[k]), R = 2, perf = new Float64Array(m.NB);
      for (let k = 0; k < m.NB; k++) { let v = 0, w = 0; for (let q = -R; q <= R; q++) { const kk = k + q; if (kk >= 0 && kk < m.NB) { const f = 1 - Math.abs(q) / (R + 1); v += crudo[kk] * f; w += f; } } perf[k] = v / w; }
      mx = 0; for (let k = 0; k < m.NB; k++) mx = Math.max(mx, perf[k]);
      // lo mismo por apalancamiento (suavizado igual, asi las partes suman el total del nivel)
      const porX = m.tiers.map((_, i) => Float64Array.from({ length: m.NB }, (_, k) => { let v = 0, w = 0; for (let q = -R; q <= R; q++) { const kk = k + q; if (kk >= 0 && kk < m.NB) { const f = 1 - Math.abs(q) / (R + 1); v += (m.Lt[i][kk] + m.St[i][kk]) * f; w += f; } } return v / w; }));
      // "Liquidation profile": cada nivel, apilado por apalancamiento (cada uno con su color), de derecha a izquierda
      for (let k = 0; k < m.NB; k++) {
        const v = perf[k]; if (!v) continue;
        const pa = y(m.gLo + (k + 1) * m.paso), pb = y(m.gLo + k * m.paso); if (pa === null || pb === null || pb < 0 || pa > H) continue;
        const largo = Math.pow(v / mx, 0.85) * (W - 4);
        let x = W;
        m.tiers.forEach((lev, i) => {
          const parte = porX[i][k] / v * largo; if (parte <= 0) return;
          ctx.fillStyle = LiqMapa.COLOR_X[lev]; ctx.globalAlpha = 0.85; ctx.fillRect(x - parte, pa, parte, Math.max(1, pb - pa)); x -= parte;
        });
        ctx.globalAlpha = 1;
      }
      const ya = y(ahora); if (ya !== null) { ctx.fillStyle = P.mute; ctx.fillRect(0, ya, W, 1); }
    }
    function resumen() {
      const m = LM.m, d = LM.datos, ahora = m.V[m.V.length - 1][4];
      let arriba = 0, abajo = 0, kA = -1, kB = -1;
      for (let k = 0; k < m.NB; k++) {
        arriba += m.S[k]; abajo += m.L[k];
        if (m.S[k] && (kA < 0 || m.S[k] > m.S[kA])) kA = k;
        if (m.L[k] && (kB < 0 || m.L[k] > m.L[kB])) kB = k;
      }
      const dist = (p) => `${p >= ahora ? '+' : '−'}${ar.format('.1f')(Math.abs(p / ahora - 1) * 100)}%`;
      const box = $('lm-res'); box.replaceChildren();
      const fila = (k, ...v) => { const r = el('div', 'ab-lm-fila'), vv = el('span', 'v'); vv.append(...v.filter((x) => x !== '')); r.append(el('span', 'k', k), vv); box.append(r); };
      fila('Arriba (cortos)', `${usd(arriba)} USD estimados`, kA >= 0 ? ` · más cargado en ${fp(m.precioBin(kA))} (${dist(m.precioBin(kA))})` : '');
      fila('Abajo (largos)', `${usd(abajo)} USD estimados`, kB >= 0 ? ` · más cargado en ${fp(m.precioBin(kB))} (${dist(m.precioBin(kB))})` : '');
      // por apalancamiento: cuanto queda y donde esta lo mas cargado de cada uno (el mas cercano al precio de los dos lados)
      const px = el('div', 'ab-lm-px');
      m.tiers.forEach((lev, i) => {
        let tot = 0, kk = -1, mxv = 0;
        for (let k = 0; k < m.NB; k++) { const v = m.Lt[i][k] + m.St[i][k]; tot += v; if (v > mxv) { mxv = v; kk = k; } }
        const c = el('span', 'ab-lm-pxi'); const dot = el('i'); dot.style.background = LiqMapa.COLOR_X[lev];
        c.append(dot, el('b', '', `${lev}x`), ` ${usd(tot)}`, kk >= 0 ? el('small', '', ` · ${fp(m.precioBin(kk))}`) : '');
        px.append(c);
      });
      fila('Por apalancamiento', px);
      const lq = (d.liq || []), dsd = lq.length ? Math.min(...lq.map((x) => x[0])) : null;
      if (lq.length) {
        const sl = lq.filter((x) => x[1] === 'l').reduce((a, x) => a + x[3], 0), ss = lq.filter((x) => x[1] === 's').reduce((a, x) => a + x[3], 0);
        fila('Liquidaciones reales (OKX)', `largos ${usd(sl)} · cortos ${usd(ss)} USD desde las ${horaAR(dsd)}`);
      }
    }
    function pintar() {
      if (!LM.datos) return;
      LM.m = LiqMapa.simular(LM.datos, LM.niveles);
      LM.img = LiqMapa.imagen(LM.m, LM.minimo);
      LM.serie.setData(LM.m.V.map((b) => ({ time: b[0] / 1000, open: b[1], high: b[2], low: b[3], close: b[4] })));
      LM.ch.timeScale().applyOptions({ timeVisible: LM.tf !== '1d' });
      LM.ch.timeScale().fitContent();
      resumen(); requestAnimationFrame(() => { hueco(); perfil(); });
    }
    async function cargar() {
      armar();
      const n = ++LM.carga;
      $('lm-estado').textContent = 'Cargando el open interest y las velas…'; $('lm-estado').hidden = false;
      try {
        const r = await fetch(`api/liquidaciones?moneda=${LM.mon}&tf=${LM.tf}`, { signal: AbortSignal.timeout(30000) });
        const j = await r.json();
        if (n !== LM.carga) return;
        if (!j.ok) throw new Error(j.error || r.status);
        if (!Object.values(j.oi).some((s) => s.length > 1)) throw new Error('ningún exchange devolvió el open interest');
        LM.datos = j; $('lm-estado').hidden = true; pintar();
        if (!pan.hidden && !document.hidden) vivoAbrir();
      } catch (e) {
        if (n === LM.carga) $('lm-estado').textContent = `No se pudo armar el mapa (${e.message || e}). Probá de nuevo en un rato.`;
      }
    }
    // ---- en vivo: solo mientras el panel esta abierto y a la vista (no gasta bateria ni datos con el panel cerrado)
    function vivoCerrar() { VIVO.gen++; clearInterval(VIVO.oiT); clearTimeout(VIVO.rec); VIVO.rec = 0; VIVO.socks.forEach((w) => { try { w.close(); } catch (e) { /* ya cerrado */ } }); VIVO.socks = []; clearInterval(VIVO.ping); $('lm-vivo-dot').classList.remove('on'); }
    function vivoAbrir() {
      vivoCerrar();
      const gen = VIVO.gen, mon = LM.mon, tf = LM.tf, sym = `${mon}USDT`, on = new Set();
      if (VIVO.mon !== mon) { VIVO.items = []; VIVO.mon = mon; $('lm-feed').replaceChildren(); }
      VIVO.t = 0;
      const estado = () => { $('lm-vivo-dot').classList.toggle('on', on.size > 0); $('lm-vivo-est').textContent = on.size ? [...on].join(' · ') : 'conectando…'; };
      const con = (nombre, url, alAbrir, alMsg) => {
        if (gen !== VIVO.gen) return;
        let w; try { w = new WebSocket(url); } catch (e) { return; }
        VIVO.socks.push(w);
        w.onopen = () => { on.add(nombre); estado(); if (alAbrir) alAbrir(w); };
        w.onmessage = (e) => { if (gen !== VIVO.gen || typeof e.data !== 'string' || e.data === 'pong') return; try { alMsg(JSON.parse(e.data)); } catch (err) { /* mensaje raro */ } };
        w.onclose = () => { on.delete(nombre); VIVO.socks = VIVO.socks.filter((x) => x !== w); if (gen === VIVO.gen) { estado(); setTimeout(() => con(nombre, url, alAbrir, alMsg), 5000); } };
      };
      estado();
      // Binance: liquidaciones (la mayor de cada segundo) + la vela en curso de la temporalidad del mapa
      con('Binance', `wss://fstream.binance.com/stream?streams=${sym.toLowerCase()}@forceOrder/${sym.toLowerCase()}@kline_${tf}`, null, (j) => {
        const d = j.data || {};
        if (d.e === 'forceOrder') { const o = d.o; nueva(+o.T, o.S === 'SELL' ? 'l' : 's', +o.ap, +o.z * +o.ap, 'Binance'); }
        else if (d.e === 'kline') { VIVO.kBin = Date.now(); vela(+d.k.t, +d.k.o, +d.k.h, +d.k.l, +d.k.c); }
      });
      // Bybit: todas las liquidaciones (cada 500 ms); "Buy" = se liquido un largo
      // (y la vela en curso, por si Binance no llega desde donde estas)
      const KB = { '5m': '5', '15m': '15', '1h': '60', '4h': '240', '1d': 'D' }[tf];
      con('Bybit', 'wss://stream.bybit.com/v5/public/linear', (w) => w.send(JSON.stringify({ op: 'subscribe', args: [`allLiquidation.${sym}`, `kline.${KB}.${sym}`] })), (j) => {
        if (!Array.isArray(j.data)) return;
        if (/^kline/.test(j.topic || '')) { if (Date.now() - (VIVO.kBin || 0) > 5000) j.data.forEach((k) => vela(+k.start, +k.open, +k.high, +k.low, +k.close)); return; }
        j.data.forEach((x) => nueva(+x.T, x.S === 'Buy' ? 'l' : 's', +x.p, +x.v * +x.p, 'Bybit'));
      });
      // OKX: todas las de los contratos perpetuos; se queda con las de esta moneda (contratos a USD con el tamano de contrato)
      const ct = LM.datos && LM.datos.moneda === mon ? LM.datos.okxCt : 0;
      if (ct) con('OKX', 'wss://ws.okx.com:8443/ws/v5/public', (w) => w.send(JSON.stringify({ op: 'subscribe', args: [{ channel: 'liquidation-orders', instType: 'SWAP' }] })), (j) => {
        (j.data || []).forEach((x) => { if (x.instId === `${mon}-USDT-SWAP`) (x.details || []).forEach((dd) => nueva(+dd.ts, dd.posSide === 'long' || (dd.posSide === 'net' && dd.side === 'sell') ? 'l' : 's', +dd.bkPx, +dd.sz * ct * +dd.bkPx, 'OKX')); });
      });
      // BitMEX (solo BTC: el XBTUSD va en contratos de 1 USD): la orden de liquidacion; "Buy" = se liquido un corto
      if (mon === 'BTC') con('BitMEX', 'wss://ws.bitmex.com/realtime?subscribe=liquidation:XBTUSD', null, (j) => {
        if (j.table !== 'liquidation' || j.action !== 'insert') return;
        (j.data || []).forEach((x) => nueva(Date.now(), x.side === 'Buy' ? 's' : 'l', +x.price, +x.leavesQty, 'BitMEX'));
      });
      // Deribit (BTC y ETH perpetuos, montos en USD): las operaciones marcadas como liquidacion. T = la liquidada es la
      // que tomo (su lado es "direction"); M = la que esperaba (el lado contrario); MT = las dos
      if (mon === 'BTC' || mon === 'ETH') con('Deribit', 'wss://www.deribit.com/ws/api/v2', (w) => w.send(JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'public/subscribe', params: { channels: [`trades.${mon}-PERPETUAL.100ms`] } })), (j) => {
        const tr = j.params && j.params.data; if (!Array.isArray(tr)) return;
        tr.forEach((x) => {
          if (!x.liquidation) return;
          const lado = (dir) => (dir === 'buy' ? 's' : 'l'), otro = x.direction === 'buy' ? 'sell' : 'buy';
          if (/T/.test(x.liquidation)) nueva(+x.timestamp, lado(x.direction), +x.price, +x.amount, 'Deribit');
          if (/M/.test(x.liquidation)) nueva(+x.timestamp, lado(otro), +x.price, +x.amount, 'Deribit');
        });
      });
      // que no se corten por inactividad (Bybit y OKX piden ping)
      // el open interest de ahora (Binance), cada minuto: lo que entra mientras miras tambien suma zonas nuevas
      const oiAhora = async () => {
        try {
          const r = await fetch(`https://fapi.binance.com/fapi/v1/openInterest?symbol=${sym}`, { signal: AbortSignal.timeout(8000) }), j = await r.json();
          const d = LM.datos; if (gen !== VIVO.gen || !d || d.moneda !== mon || !(+j.openInterest > 0)) return;
          const pr = d.velas[d.velas.length - 1][4], serie = d.oi.binance || (d.oi.binance = []);
          if (serie.length > 1) { serie.push([+j.time || Date.now(), +j.openInterest * pr]); programar(); }
        } catch (e) { /* sin open interest en vivo: el mapa sigue con las velas */ }
      };
      clearInterval(VIVO.oiT); VIVO.oiT = setInterval(oiAhora, 60000); oiAhora();
      VIVO.ping = setInterval(() => VIVO.socks.forEach((w) => { if (w.readyState !== 1) return; if (/bybit/.test(w.url)) w.send('{"op":"ping"}'); else if (/okx|bitmex/.test(w.url)) w.send('ping'); else if (/deribit/.test(w.url)) w.send('{"jsonrpc":"2.0","id":9,"method":"public/test"}'); }), 20000);
    }
    // la vela en curso: se mueve al instante y el mapa se rehace cada pocos segundos con ella (lo que cruza se borra)
    function vela(t, o, h, l, c) {
      const d = LM.datos;
      if (!LM.m || !d || d.tf !== LM.tf || d.moneda !== LM.mon || ![t, o, h, l, c].every(isFinite)) return;
      const V = d.velas, ult = V[V.length - 1];
      if (t < ult[0]) return;
      if (t === ult[0]) V[V.length - 1] = [t, o, h, l, c]; else V.push([t, o, h, l, c]);
      try { LM.serie.update({ time: t / 1000, open: o, high: h, low: l, close: c }); VIVO.t = t; } catch (e) { /* vela vieja */ }
      programar();
    }
    function programar() { if (!VIVO.rec) VIVO.rec = setTimeout(refrescar, VIVO.cada || 2000); }
    function refrescar() {
      VIVO.rec = 0;
      if (!LM.datos || !LM.serie || pan.hidden) return;
      const t0 = performance.now();
      LM.m = LiqMapa.simular(LM.datos, LM.niveles); LM.img = LiqMapa.imagen(LM.m, LM.minimo);
      resumen(); perfil(); LM.serie.applyOptions({});
      // en un telefono lento (o con 3x, que estira la grilla) se espacia: nunca mas del 5 % del tiempo rehaciendo
      VIVO.cada = Math.min(10000, Math.max(2000, (performance.now() - t0) * 20));
    }
    function nueva(t, lado, p, u, ex) {
      if (!(p > 0) || !(u > 0) || !isFinite(t)) return;
      VIVO.items.push({ t, lado, p, u, ex, nace: performance.now() });
      const corte = Date.now() - 6 * 36e5; if (VIVO.items.length > 600 || VIVO.items[0].t < corte) VIVO.items = VIVO.items.filter((x) => x.t >= corte).slice(-600);
      animar(); if (!VIVO.lista) VIVO.lista = setTimeout(lista, 250);       // la lista se rehace como mucho 4 veces por segundo
    }
    // redibujar mientras haya burbujas animandose (y nada mas)
    function animar() {
      if (VIVO.raf || !LM.serie) return;
      VIVO.raf = requestAnimationFrame(() => {
        VIVO.raf = 0; if (!LM.serie || pan.hidden) return;
        LM.serie.applyOptions({});
        if (!VIVO.quieto && VIVO.items.some((x) => performance.now() - x.nace < 900)) animar();
      });
    }
    function lista() {
      VIVO.lista = 0;
      const ahora = Date.now(), r5 = VIVO.items.filter((x) => ahora - x.t < 5 * 6e4);
      const suma = (l) => r5.filter((x) => x.lado === l).reduce((a, x) => a + x.u, 0);
      const tot = $('lm-vivo-tot'); tot.replaceChildren();
      [['l', 'Largos liquidados'], ['s', 'Cortos liquidados']].forEach(([l, n]) => { const d = el('div', l); d.append(`${n} · 5 min`, el('b', '', `${usd(suma(l))} USD`)); tot.append(d); });
      // las ultimas 6 que pasan de mil USD (las chicas solo van al grafico); las grandes en negrita
      const ult = VIVO.items.filter((x) => x.u >= 1000).slice(-6).reverse(), ol = $('lm-feed'), vistos = new Set([...ol.children].map((li) => li.dataset.k));
      const grande = Math.max(1e5, ...VIVO.items.map((x) => x.u)) * 0.5;
      ol.replaceChildren(...ult.map((x) => {
        const k = `${x.ex}${x.t}${x.p}${x.u}`, li = el('li', `${x.lado}${x.u >= grande ? ' grande' : ''}${vistos.has(k) || VIVO.quieto ? '' : ' nuevo'}`); li.dataset.k = k;
        li.append(el('i'), el('span', '', `${x.lado === 'l' ? 'Largo' : 'Corto'} · ${usd(x.u)} USD`), el('span', '', fp(x.p)), el('small', '', `${x.ex} ${new Date(x.t).toLocaleTimeString('es-AR', { ...tz, hourCycle: 'h23' })}`));
        return li;
      }));
      if (!ult.length) ol.append(el('li', 'vacio', 'Todavía no llegó ninguna: aparecen acá y como burbujas en el gráfico.'));
    }
    document.addEventListener('visibilitychange', () => { if (pan.hidden) return; if (document.hidden) vivoCerrar(); else vivoAbrir(); });
    const marcar = (box, attr, v) => [...$(box).children].forEach((b) => b.setAttribute('aria-pressed', String(b.dataset[attr] === v)));
    function abrir() {
      pan.hidden = false; fondo.hidden = false; document.documentElement.style.overflow = 'hidden'; abFoco(pan, true);
      const m = MON(); if (MON_LM.includes(m) && m !== LM.mon && !LM.datos) LM.mon = m;
      sel.value = LM.mon; marcar('lm-tfs', 'tf', LM.tf); pintarX();
      if (!LM.datos || LM.datos.moneda !== LM.mon || Date.now() - LM.datos.hora > 5 * 6e4) cargar(); else { requestAnimationFrame(perfil); vivoAbrir(); }
      lista();
    }
    function cerrar() { if (pan.hidden) return; vivoCerrar(); abFoco(pan, false); pan.hidden = true; fondo.hidden = true; document.documentElement.style.overflow = ''; }
    $('lm-btn').addEventListener('click', abrir);
    $('lm-abrir').addEventListener('click', abrir);
    $('lm-x').addEventListener('click', cerrar); fondo.addEventListener('click', cerrar);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !pan.hidden) cerrar(); });
    sel.addEventListener('change', () => { LM.mon = sel.value; cargar(); });
    $('lm-tfs').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; LM.tf = b.dataset.tf; marcar('lm-tfs', 'tf', LM.tf); cargar(); });
    // apalancamientos: cada uno se prende y se apaga (al menos uno); "Todos" vuelve a los seis
    const xs = $('lm-x-sel');
    xs.append(...LiqMapa.NIVELES.map(([x]) => { const b = el('button', 'ab-chipbtn'); b.type = 'button'; b.dataset.x = x; b.append(el('i'), `${x}x`); b.querySelector('i').style.background = LiqMapa.COLOR_X[x]; return b; }),
      Object.assign(el('button', 'ab-chipbtn ab-lm-todos', 'Todos'), { type: 'button' }));
    function pintarX() { [...xs.children].forEach((b) => b.dataset.x && b.setAttribute('aria-pressed', String(LM.niveles.includes(+b.dataset.x)))); }
    xs.addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      if (!b.dataset.x) LM.niveles = LiqMapa.NIVELES.map(([x]) => x);
      else { const x = +b.dataset.x, ya = LM.niveles.includes(x); if (ya && LM.niveles.length === 1) return; LM.niveles = ya ? LM.niveles.filter((y) => y !== x) : LM.niveles.concat(x).sort((p, q) => p - q); }
      pintarX(); if (LM.datos) pintar();
    });
    pintarX();
    $('lm-min').addEventListener('input', (e) => { LM.minimo = +e.target.value / 100; if (LM.m) { LM.img = LiqMapa.imagen(LM.m, LM.minimo); LM.ch.timeScale().applyOptions({}); LM.serie.applyOptions({}); } });
    $('lm-perf').addEventListener('change', (e) => { LM.perfil = e.target.checked; hueco(); perfil(); });
    new ResizeObserver(() => requestAnimationFrame(perfil)).observe($('lm-chart'));
    // el perfil sigue a la escala de precios (zoom o arrastre)
    let rafP = 0; const seguir = () => { if (!rafP) rafP = requestAnimationFrame(() => { rafP = 0; perfil(); }); };
    ['pointermove', 'wheel', 'touchmove'].forEach((ev) => $('lm-chart').addEventListener(ev, seguir, { passive: true }));
    new MutationObserver(() => { if (LM.ch && pan.hidden) { LM.ch.remove(); LM.ch = null; LM.serie = null; } }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    window.abLiqMapa = LiqMapa;           // para la prueba (pruebas/mapa_liq.js)
  })();

  // un tick del WebSocket: mueve la ultima vela al instante, sin rehacer el grafico
  function liveTick() {
    if (liveBar && liveBar.mon === MON()) { dibAvisos(liveBar.c); m2Vivo(liveBar.c); }
    if (!G.chart || !G.d || G.tf !== S.tf || !liveBar || liveBar.tf !== S.tf || liveBar.mon !== MON() || G.mon !== MON()) return;
    const t = T2(liveBar.t), d = G.d;
    if (liveBar.t < d.all[d.all.length - 1].t) return;
    try {
      G.c.update(barra({ time: t, open: liveBar.o, high: liveBar.h, low: liveBar.l, close: liveBar.c }));
      if (S.linea) G.ln.update({ time: t, value: liveBar.c });
      G.vol.update({ time: t, value: liveBar.v, color: alpha(liveBar.c >= liveBar.o ? G.P.up : G.P.dn, 0.3) });
    } catch (e) { return; }
    d.price = liveBar.c; d.nowCol = liveBar.c >= liveBar.o ? G.P.up : G.P.dn;
    const last = d.all[d.all.length - 1], igual = liveBar.t === last.t;
    const e = emaVivo(igual ? d.all[d.all.length - 2] : last, liveBar.c);
    if (S.layers.ema) {
      try { [['e20', G.e20], ['e50', G.e50], ['e200', G.e200]].forEach(([k, se]) => { if (e[k] !== undefined) se.update({ time: t, value: e[k] }); }); } catch (er) { /* la serie puede estar vacia */ }
    }
    if (igual) Object.assign(last, { h: liveBar.h, l: liveBar.l, c: liveBar.c, v: liveBar.v }, e);
    if (!G.hover) legend(null);
  }

  function drawChart(rows, sum) {
    if (ghostTimer) { clearInterval(ghostTimer); ghostTimer = null; }
    const box = document.getElementById('chart');
    if (!LW) { box.replaceChildren(); const f = el('div', 'ab-fail'); f.append(el('i'), 'No se pudo cargar el gráfico'); box.append(f); return; }
    box.classList.toggle('ab-with-osc', !!S.layers.osc);
    const P = pal(), L = S.layers, tf = S.tf, tfMs = TF_MIN[tf] * 60000;
    const key = `${!!L.osc}|${!!L.flujo}|${P.panel}|${P.up}|${P.c0}`;
    if (!G.chart || G.key !== key || G.box !== box || !box.firstChild) { buildChart(box, P); G.key = key; }
    G.P = P;
    G.chart.applyOptions({ handleScroll: { vertTouchDrag: !!S.fs } });
    const all = pick(rows, 'vela', tf).map((r) => ({ t: num(r.t), o: num(r.o), h: num(r.h), l: num(r.l), c: num(r.c), v: num(r.v), en: !!r.en_curso,
      e20: num(r.ema20), e50: num(r.ema50), e200: num(r.ema200), bu: num(r.bb_up), bl: num(r.bb_lo),
      rsi: num(r.rsi), macd: num(r.macd), sig: num(r.macd_senal), hist: num(r.macd_hist) })).sort((a, b) => a.t - b.t);
    if (!all.length) return;
    const lastIdx = all.length - 1, lastA = all[lastIdx];         // la ultima vela del analisis: de ahi sale el futuro
    // la vela en vivo solo si es de este activo: al pasar de ZEC a BTC, la ultima vela de ZEC (1.300) se metia en el
    // grafico de BTC y la escala quedaba de 1.300 a 100.000
    const vivo = liveBar && liveBar.tf === tf && liveBar.mon === MON() ? liveBar : null;
    if (vivo) {
      if (liveBar.t === lastA.t) all[lastIdx] = { ...lastA, h: liveBar.h, l: liveBar.l, c: liveBar.c, v: liveBar.v, ...emaVivo(all[lastIdx - 1], liveBar.c) };
      else if (liveBar.t > lastA.t) all.push({ ...liveBar, e20: null, e50: null, e200: null, ...emaVivo(lastA, liveBar.c), bu: null, bl: null, rsi: null, macd: null, sig: null, hist: null });
    }
    const price = vivo ? vivo.c : num(sum.precio);
    const ghosts = SIN_FUTURO ? [] : pick(rows, 'escenario', tf).filter((r) => r.escenario === S.scen)
      .map((r) => ({ k: num(r.paso), o: num(r.o), h: num(r.h), l: num(r.l), c: num(r.c), desde: r.desde })).sort((a, b) => a.k - b.k)
      .map((g) => ({ ...g, t: lastA.t + g.k * tfMs }));
    const cone = SIN_FUTURO ? [] : pick(rows, 'cono', tf).map((r) => ({ k: num(r.paso), lo: num(r.p10), mid: num(r.p50), hi: num(r.p90) })).sort((a, b) => a.k - b.k)
      .map((c) => ({ ...c, t: lastA.t + c.k * tfMs }));
    const futN = Math.max(ghosts.length, cone.length);
    const fvgs = L.fvg ? pick(rows, 'fvg', tf).map((r) => ({ up: r.tipo === 'alcista', t: num(r.t), lo: num(r.bajo), hi: num(r.alto) })) : [];
    const byT = new Map(all.map((b) => [b.t, b]));
    const giros = pick(rows, 'giro', tf).map((r) => ({ t: num(r.t), p: num(r.precio), w: r.onda, alto: r.tipo === 'alto' })).filter((g) => byT.has(g.t));
    const liq = pick(rows, 'liquidacion').map((r) => ({ p: num(r.precio), l: num(r.longs), s: num(r.shorts) }));
    const mk = pick(rows, 'marco', tf)[0];
    const pzr = pick(rows, 'plazo').find((r) => r.plazo === S.plazo);
    const dvg = {};
    pick(rows, 'divergencia', tf).forEach((v) => {
      const k = `${v.t1}-${v.t2}-${v.tipo}`;
      const g = (dvg[k] = dvg[k] || { key: `div-${k}`, tipo: v.tipo, t1: num(v.t1), t2: num(v.t2), p1: num(v.p1), p2: num(v.p2), names: [], ind: {} });
      g.names.push(v.indicador);
      g.ind[v.indicador] = { t1: num(v.ti1 ?? v.t1), t2: num(v.ti2 ?? v.t2), v1: num(v.v1), v2: num(v.v2) };
    });
    const live = true;
    const lastOsc = [...all].reverse().find((b) => b.rsi !== null && b.macd !== null) || null;
    const narrow = box.clientWidth < 520;
    G.d = { all, lastIdx, t0: all[0].t, tfMs, lastT: lastA.t, lastC: lastA.c, firstT: all[0].t, endT: lastA.t + Math.max(futN, 1) * tfMs, price,
      nowCol: price >= all[all.length - 1].o ? P.up : P.dn, closeAt: all[all.length - 1].t + tfMs, live, futN, ghosts, cone, fvgs, giros, liq, byT,
      figs: L.patrones ? pick(rows, 'patron', tf).filter((p) => p.clase === 'grafico') : [], divs: Object.values(dvg),
      icts: L.ict ? pick(rows, 'ict', tf) : [],
      bb: all.filter((b) => b.bu !== null).map((b) => ({ t: b.t, u: b.bu, l: b.bl })),
      pz: pzr ? { t: num(pzr.t_hasta), txt: `${S.plazo} · ${pzr.hora.slice(-5)} h` } : null,
      ondaCur: mk ? mk.elliott_curso : null, ondaObj: mk ? num(mk.elliott_objetivo) : null, lastOsc, narrow,
      cruce: mk && mk.macd_cruce ? `cruzó ${mk.macd_cruce === 'alcista' ? 'al alza' : 'a la baja'}` : '' };
    const d = G.d;
    // datos de cada serie
    const ts = G.chart.timeScale();
    // la vista (zoom y desplazamiento) se conserva entre analisis del mismo activo y temporalidad; al cambiar de activo
    // se vuelve a la vista por defecto con la escala de precios automatica (antes quedaba el rango del activo anterior:
    // de ZEC a BTC, el eje seguia en ~1.300)
    const otroActivo = G.mon !== MON(), keep = G.tf === tf && !otroActivo ? ts.getVisibleLogicalRange() : null;
    if (G.tf !== tf || G.mon !== MON()) G.med = null;
    G.dibujando = true;
    d.cdata = all.map((b) => ({ ms: b.t, bar: { time: T2(b.t), open: b.o, high: b.h, low: b.l, close: b.c } }));
    G.c.setData(d.cdata.map((b) => barra(b.bar)));
    G.ln.applyOptions({ lineColor: mktCol(), topColor: alpha(mktCol(), P.dark ? 0.28 : 0.2), bottomColor: alpha(mktCol(), 0) });
    G.ln.setData(S.linea ? all.map((b) => ({ time: T2(b.t), value: b.c })) : []);
    // la etiqueta del precio en el eje: la de la linea (en el color del mercado) o la de la vela
    G.c.applyOptions({ lastValueVisible: !S.linea, priceLineVisible: !S.linea });
    G.ln.applyOptions({ lastValueVisible: S.linea, priceLineVisible: S.linea, priceLineColor: mktCol(), priceLineStyle: LW.LineStyle.Dotted, priceLineWidth: 1 });
    G.vol.setData(all.map((b) => ({ time: T2(b.t), value: b.v, color: alpha(b.c >= b.o ? P.up : P.dn, 0.3) })));
    const line = (k) => all.filter((b) => b[k] !== null).map((b) => ({ time: T2(b.t), value: b[k] }));
    G.e20.setData(L.ema ? line('e20') : []); G.e50.setData(L.ema ? line('e50') : []); G.e200.setData(L.ema ? line('e200') : []);
    G.bbU.setData(L.bb ? line('bu') : []); G.bbL.setData(L.bb ? line('bl') : []);
    G.vwap.setData(L.vp ? vwapSerie(all, TF_MIN[tf]) : []);
    if (G.fl) {
      const fe = flujoDe(MON(), tf, () => { if (S.rows && S.layers.flujo) drawChart(S.rows, S.sum); });
      G.flS = flujoSeries(fe, all, P); flujoSet(G.fl, G.flS);
    }
    if (G.rsi) {
      G.rsi.setData(line('rsi'));
      G.hist.setData(all.filter((b) => b.hist !== null).map((b) => ({ time: T2(b.t), value: b.hist, color: alpha(b.hist >= 0 ? P.up : P.dn, 0.45) })));
      G.macd.setData(line('macd')); G.sig.setData(line('sig'));
    }
    // velas del escenario: aparecen una por una la primera vez (o con "Repetir"); el resto del tiempo quedan quietas
    const fut = Array.from({ length: futN }, (_, j) => j + 1).map((k) => ({ k, time: T2(lastA.t + k * tfMs), g: ghosts.find((g) => g.k === k) }));
    const showGhosts = (n) => G.ghost.setData(fut.map((f) => (f.g && f.k <= n ? { time: f.time, open: f.g.o, high: f.g.h, low: f.g.l, close: f.g.c } : { time: f.time })));
    const animKey = `${tf}|${S.scen}|${ghostK}`;
    if (reduce || !ghosts.length || G.anim === animKey) showGhosts(Infinity);
    else {
      G.anim = animKey; let n = 0; showGhosts(0);
      ghostTimer = setInterval(() => { n += 1; showGhosts(n); if (n >= ghosts.length) { clearInterval(ghostTimer); ghostTimer = null; } }, 260);
    }
    // marcas de patrones de velas, como las flechitas de TradingView
    const marks = L.patrones ? pick(rows, 'patron', tf).filter((p) => p.clase === 'vela' && byT.has(num(p.t))).map((p) => ({
      time: T2(num(p.t)), position: p.sesgo === 'alcista' ? 'belowBar' : 'aboveBar', color: colOf(p.sesgo),
      shape: p.sesgo === 'alcista' ? 'arrowUp' : p.sesgo === 'bajista' ? 'arrowDown' : 'circle',
      text: narrow ? '' : `${p.nombre}${p.exito !== null ? ` · ${f0(num(p.exito))}%` : ''}` })).sort((a, b) => a.time - b.time) : [];
    G.markers.setMarkers(marks);
    // niveles: soporte y resistencia del plazo y objetivos de las figuras, como lineas de precio con su etiqueta en el eje
    // (si dos etiquetas quedan a menos de un renglon, se ve la que va primero; la otra queda como linea sola. Se recalcula
    // al mover o hacer zoom, asi al separarse vuelven las dos)
    (G.plines || []).forEach((pl) => { try { G.c.removePriceLine(pl); } catch (e) { /* ya no estaba */ } });
    G.plines = [];
    pick(rows, 'explicacion').filter((e) => e.plazo === S.plazo && e.tipo === 'vigilar' && e.precio !== null && e.precio !== undefined).forEach((e) => {
      G.plines.push(G.c.createPriceLine({ price: num(e.precio), color: alpha(e.sesgo === 'alcista' ? P.up : P.dn, 0.8), lineWidth: 1, lineStyle: LW.LineStyle.Dashed,
        axisLabelVisible: true, title: String(e.texto).replace(/\s*\d[\d.,]*.*$/, '') }));
    });
    // Fibonacci como en TradingView: del inicio del tramo (nivel 1) al fin (nivel 0), con todos los niveles. El automatico es
    // el swing de 90 dias en 4 h (el unico que mostro ventaja, con cuanto rebotó cada nivel). Si lo ajustaste arrastrando
    // sus puntos o la diagonal, va ese (guardado por activo en este navegador). Se ve en todas las temporalidades si la
    // capa esta prendida, y se dibuja en el grafico (lineas punteadas tenues con su texto), no en el eje de precios.
    const tr = pick(rows, 'fib_tramo')[0], fu = FIBU[MON()];
    d.fibReb = {}; pick(rows, 'nivel').forEach((n) => { if (n.fib !== undefined && n.fib !== null) d.fibReb[num(n.fib)] = num(n.rebote); });
    d.fibNarrow = narrow;
    // capa "Fibonacci": se prende y se apaga como las demas, en todos los activos y temporalidades
    d.fib = !L.fib ? null : fu ? { a: { ...fu.a }, b: { ...fu.b }, mano: true }
      : tr ? { a: { t: num(tr.t_inicio), p: num(tr.p_inicio) }, b: { t: num(tr.t_fin), p: num(tr.p_fin) }, mano: false } : null;
    d.fibs = fibNiveles(d);
    // tu plan (plan_compras.json): en tinta neutra para no confundirlo con las marcas del analisis
    d.plan = 0;
    const planChip = document.querySelector('#layers [data-layer="plan"]');
    const conPlan = PLAN_OK() && ES_CRIPTO(MON());          // la capa "Mi plan" tampoco va en las acciones (ni sin BingX conectado)
    if (planChip && planChip.hidden === conPlan) { planChip.hidden = !conPlan; syncLayers(); }
    if (L.plan && conPlan) {
      const m = MON(), dat = CMP.datos[m], line = (price, color, style, width, title) => {
        G.plines.push(G.c.createPriceLine({ price, color, lineWidth: width, lineStyle: style, axisLabelVisible: true, title })); d.plan += 1;
      };
      comprasDe(m).filter((c) => !cmpHecha(c, dat)).forEach((c) => line(c.precio, alpha(P.fg, cargada(c) ? 0.75 : 0.45),
        cargada(c) ? LW.LineStyle.Dashed : LW.LineStyle.Dotted, 1, narrow ? `${nCompra(c)}` : `Compra ${nCompra(c)}${cargada(c) ? '' : ' · sin orden'}`));
      const e = planEstado(m, dat);
      if (e.equilibrio) line(e.equilibrio, alpha(P.fg, 0.9), LW.LineStyle.Solid, 1, narrow ? 'Equil.' : 'Tu equilibrio');
      const g = e.ganancias && e.ganancias.find((x) => !x.alcanzado);
      if (g) line(g.precio, alpha(P.up, 0.85), LW.LineStyle.Dashed, 1, narrow ? `TP +${f0(g.k * reglas().ganancias.cada * 100)}%` : `Toma de ganancias +${f0(g.k * reglas().ganancias.cada * 100)}%`);
      if (e.liquidacion) line(e.liquidacion, P.dn, LW.LineStyle.Solid, 2, narrow ? 'Liq.' : 'Tu liquidación');
    }
    // opciones (Deribit, solo BTC): el dolor maximo del viernes, donde mas opciones vencen sin valor
    const dolor = L.opc ? pick(rows, 'contexto').find((c) => c.clave === 'opciones_dolor' && num(c.precio) !== null) : null;
    d.dolor = dolor ? num(dolor.precio) : null;
    if (dolor) G.plines.push(G.c.createPriceLine({ price: d.dolor, color: alpha(P.c2, 0.75), lineWidth: 1, lineStyle: LW.LineStyle.LargeDashed,
      axisLabelVisible: true, title: narrow ? 'Dolor máx.' : `Dolor máx. opciones (${String(dolor.titulo).replace(/^.*vence\s*/, '').replace(/\)$/, '').slice(0, 5)})` }));
    if (L.patrones) d.figs.forEach((p) => {
      const obj = num(p.objetivo); if (obj === null) return;
      G.plines.push(G.c.createPriceLine({ price: obj, color: colOf(p.sesgo), lineWidth: 1, lineStyle: LW.LineStyle.SparseDotted, axisLabelVisible: true,
        title: p.estado === 'confirmado' ? 'Objetivo' : 'Objetivo si se confirma' }));
    });
    G.plines.forEach((pl) => { if (pl._t === undefined) { pl._t = pl.options().title; pl._v = pl.options().axisLabelVisible; } });
    ordenarEtiquetas();
    if (keep) ts.setVisibleLogicalRange(keep);
    else {
      const total = all.length + futN, nb = Math.min(total, defBars());
      ts.setVisibleLogicalRange({ from: total - nb, to: total + 1 });
      G.chart.priceScale('right').applyOptions({ autoScale: true });
      if (otroActivo) try { G.chart.panes().forEach((pn) => pn.priceScale('right').applyOptions({ autoScale: true })); } catch (e) { /* sin paneles extra */ }
    }
    G.tf = tf; G.mon = MON();
    G.dibujando = false;
    requestAnimationFrame(botonPresente);
    legend(null);
    G.under.update(); G.over.update();
    abaPedir(tf);
    m2Pintar(false);

    // que estas viendo: una linea por cada cosa dibujada, solo de las capas activas
    const leg = document.getElementById('legend'); leg.replaceChildren();
    const item = (k, sw, title, text) => {
      const r = el('div', 'ab-ex-item ab-ex-link'), i = el('i'); Object.assign(i.style, sw);
      const t = el('span'); t.append(el('b', '', title), ' ', text); r.append(i, t); leg.append(r);
      r.dataset.ex = k; r.setAttribute('role', 'button'); r.tabIndex = 0;
      // mouse: al pasar por encima se ve; clic lo marca o desmarca. Dedo: mantener apretado lo muestra mientras se
      // sostiene (ver exHold); un toque corto lo marca o desmarca; deslizar no hace nada
      r.addEventListener('pointerenter', (e) => { if (e.pointerType === 'mouse') focusEx(k); });
      r.addEventListener('pointerleave', (e) => { if (e.pointerType === 'mouse') focusEx(null); });
      r.addEventListener('pointerdown', (e) => { if (e.pointerType !== 'mouse') exHold(k, e); });
      r.addEventListener('click', () => { if (Date.now() - exSinClick > 600) toggleEx(k); });
      r.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleEx(k); } });
      r.addEventListener('contextmenu', (e) => e.preventDefault());
    };
    const CC = (c) => ({ background: c }), DD = (c) => ({ background: 'transparent', border: `1.5px dashed ${c}` });
    d.figs.forEach((p) => item(`pat-grafico-${p.nombre}`, p.estado === 'confirmado' ? CC(colOf(p.sesgo)) : DD(colOf(p.sesgo)),
      `${p.estado === 'confirmado' ? '✓' : 'Posible'} ${p.nombre.toLowerCase()}:`, p.descripcion));
    if (L.patrones) d.divs.forEach((v) => item(v.key, CC(v.tipo === 'alcista' ? P.up : P.dn), `Divergencia ${v.tipo} (${v.names.join(' + ')}):`,
      v.tipo === 'bajista' ? `el precio hizo un máximo más alto (${fp(v.p1)} → ${fp(v.p2)}) pero ${v.names.join(' y ')} no acompañó: la suba pierde fuerza.`
        : `el precio hizo un mínimo más bajo (${fp(v.p1)} → ${fp(v.p2)}) pero ${v.names.join(' y ')} no acompañó: la baja pierde fuerza.`));
    if (L.patrones) pick(rows, 'patron', tf).filter((p) => p.clase === 'vela' && byT.has(num(p.t))).forEach((p) =>
      item(`pat-vela-${p.nombre}`, CC(colOf(p.sesgo)), `Flechita · ${p.nombre}:`, p.descripcion));
    if (G.plines.length) item('sr', DD(P.mute), 'Líneas punteadas con etiqueta en el eje:',
      `resistencia y soporte más cercanos para el plazo de ${S.plazo}${L.patrones && d.figs.some((p) => num(p.objetivo) !== null) ? ' y el objetivo de cada figura' : ''}.`);
    if (d.fib && d.fibs.length) {
      item('fib', { background: 'transparent', borderTop: `1.5px dotted ${P.c2}`, height: '0', marginTop: '.75em' }, `Líneas violetas punteadas (Fib${d.fib.mano ? ', ajustado a mano' : ''}):`,
        d.fib.mano ? 'el Fibonacci que acomodaste, del punto de inicio (100%) al de fin (0%). Arrastrá los puntos para cambiarlo o la diagonal para moverlo entero.'
          : 'Fibonacci del swing de 90 días, del inicio (100%) al fin (0%); el texto dice cuántas veces rebotó el precio en cada nivel (más fuerte si rebotó 55% o más). Arrastrá los puntos (o la diagonal) para ajustarlo, como en TradingView.');
      if (d.fib.mano) {
        const it = leg.querySelector('[data-ex="fib"] span'), bt = el('button', 'ab-ex-limpiar', 'Volver al automático'); bt.type = 'button';
        bt.style.margin = '4px 0 0'; bt.addEventListener('click', (e) => { e.stopPropagation(); delete FIBU[MON()]; guardarFib(); if (S.rows) drawChart(S.rows, S.sum); });
        if (it) it.append(document.createElement('br'), bt);
      }
    }
    if (d.dolor !== null) item('opc', DD(P.c2), 'Línea violeta a rayas largas:',
      'el "dolor máximo" de las opciones del viernes: el precio donde más opciones vencen sin valor. Cerca del vencimiento a veces atrae al precio.');
    if (d.plan) item('plan', DD(P.fg), 'Tu plan (líneas grises con nombre):',
      'compras que faltan (rayada: orden puesta; punteada: falta cargarla), tu precio promedio, la próxima toma de ganancias y la liquidación aproximada.');
    { const ab = abaLeyenda(tf); if (ab) item('abanico', DD(P.fg), ab[0], ab[1]); }
    if (ghosts.length) item('futuro', DD(P.mute), 'Velas transparentes a la derecha:',
      `un camino real del ${ghosts[0].desde.split('-').reverse().join('/')}, cuando ${MON()} estaba en una situación parecida, llevado al precio de hoy. La zona gris es donde terminó el 80% de esos casos y la línea vertical, la hora del plazo elegido.`);
    if (L.ondas && giros.some((g) => g.w)) item('ondas', { background: 'transparent', border: `1.5px solid ${P.fg}`, borderRadius: '50%', width: '10px', height: '10px' },
      'Círculos con letras o números:', `conteo de Elliott. ${mk ? mk.elliott : ''}.`);
    if (L.fvg && fvgs.length) item('fvg', CC(alpha(P.up, 0.35)), 'Franjas verdes o rojas:', 'huecos (FVG) que el precio dejó sin operar; suele volver a llenarlos.');
    if (L.ema) item('ema', { background: `linear-gradient(90deg, ${P.c0} 50%, ${P.c1} 50%)` }, 'Líneas azul y naranja:', 'medias móviles EMA 20 y EMA 50.');
    if (L.ema && d.all.some((b) => b.e200 !== null && b.e200 !== undefined)) item('ema', { background: alpha(P.fg, 0.7) }, 'Línea gris gruesa:', 'media móvil EMA 200 (la tendencia de fondo de esta temporalidad; en la mensual no hay 200 velas para calcularla).');
    if (L.ict) pick(rows, 'ict', tf).forEach((z, i) => item(`ict-${i}`, z.tipo === 'barrida' || z.tipo === 'po3' ? DD(colOf(z.sesgo)) : CC(alpha(colOf(z.sesgo), 0.5)),
      `${z.nombre} ${z.sesgo}:`, z.descripcion));
    if (L.libro) {
      const lc = libroColumnas(all, tfMs);
      item('libro', { background: 'linear-gradient(90deg, #2878ff, #ffc837)' }, 'Manchas azules y amarillas (mapa de calor del libro):',
        `dónde había órdenes esperando a cada momento (Binance y Bybit): más amarillo, más plata. Las zonas que se mantienen suelen frenar al precio; si desaparecen cuando el precio llega, eran de mentira.${lc && lc.n ? '' : ' Se va llenando mientras tenés la app abierta'}${MON() === 'BTC' ? ' (en BTC, además, el servidor guarda una foto cada 5 minutos las 24 h).' : '.'}`);
    }
    if (L.vp) {
      const pr = perfilVisible(G.chart, all), vw = all.length ? vwapSerie(all, TF_MIN[tf]).slice(-1)[0] : null, px = all.length ? all[all.length - 1].c : null;
      item('vp', CC(VWAP_COL), 'Línea fucsia y barras a la izquierda (VWAP y perfil de volumen):',
        `el VWAP es el precio promedio pesado por volumen desde que empezó la sesión${vw && vw.value && px ? `: está en ${fp(vw.value)}, y el precio ${px >= vw.value ? 'arriba (manda la compra)' : 'abajo (manda la venta)'}` : ''}. Las barras muestran cuánto se operó en cada precio de lo que estás viendo${pr ? `: el POC (el precio con más volumen) es ${fp(pr.poc)} y el 70 % se operó entre ${fp(pr.val)} (VAL) y ${fp(pr.vah)} (VAH)` : ''}. Esos precios suelen frenar al precio o atraerlo.`);
    }
    if (L.bb) item('bb', CC(alpha(P.fg, 0.12)), 'Banda gris:', 'Bollinger, el rango normal del precio en las últimas 20 velas.');
    if (L.liq && liq.length) item('liq', { background: `linear-gradient(90deg, ${P.dn}, ${P.up})` }, 'Barras junto al eje de precios:',
      'liquidaciones estimadas. Rojas: longs que se liquidan si baja; verdes: shorts si sube. Pasá el mouse o tocá ahí para ver los USD.');
    if (L.osc && lastOsc) {
      const rv = lastOsc.rsi;
      const rTxt = rv >= 70 ? 'en sobrecompra (arriba de 70): la suba está estirada y suele frenar' : rv <= 30 ? 'en sobreventa (debajo de 30): la baja está estirada y suele rebotar'
        : `en ${f0(rv)}, zona neutral (entre 30 y 70)`;
      const mTxt = mk && mk.macd_cruce ? `el MACD acaba de cruzar ${mk.macd_cruce === 'alcista' ? 'por encima de su señal: impulso a favor de la suba' : 'por debajo de su señal: impulso a favor de la baja'}`
        : lastOsc.macd >= lastOsc.sig ? 'el MACD está por encima de su señal (impulso alcista)' : 'el MACD está por debajo de su señal (impulso bajista)';
      item('osc', { background: `linear-gradient(90deg, ${P.c2} 50%, ${P.c0} 50%)` }, 'Paneles de abajo:',
        `RSI ${rTxt}; ${mTxt}. Las barras son la diferencia entre las dos líneas. Si hay divergencias, se marcan con la misma línea en el precio y en el indicador.`);
    }
    const nAca = leg.children.length;
    // en las otras temporalidades: todas las figuras, divergencias y patrones de velas que encontro el analisis.
    // Tocar uno lleva el grafico a esa temporalidad (ahi se dibuja)
    const otros = [];
    if (L.patrones || L.ict) ['5m', '15m', '30m', '1h', '4h', '1d', '1w', '1M'].filter((t2) => t2 !== tf).forEach((t2) => {
      const ps = L.patrones ? pick(rows, 'patron', t2) : [];
      ps.filter((p) => p.clase === 'grafico').forEach((p) => otros.push([t2, p.estado === 'confirmado' ? CC(colOf(p.sesgo)) : DD(colOf(p.sesgo)),
        `${p.estado === 'confirmado' ? '✓' : 'Posible'} ${p.nombre.toLowerCase()}:`, p.descripcion]));
      const dv = {};
      (L.patrones ? pick(rows, 'divergencia', t2) : []).forEach((v) => { const k = `${v.t1}-${v.t2}-${v.tipo}`; (dv[k] = dv[k] || { tipo: v.tipo, names: [], p1: num(v.p1), p2: num(v.p2) }).names.push(v.indicador); });
      Object.values(dv).forEach((v) => otros.push([t2, CC(v.tipo === 'alcista' ? P.up : P.dn), `Divergencia ${v.tipo} (${v.names.join(' + ')}):`,
        v.tipo === 'bajista' ? `el precio hizo un máximo más alto (${fp(v.p1)} → ${fp(v.p2)}) pero ${v.names.join(' y ')} no acompañó: la suba pierde fuerza.`
          : `el precio hizo un mínimo más bajo (${fp(v.p1)} → ${fp(v.p2)}) pero ${v.names.join(' y ')} no acompañó: la baja pierde fuerza.`]));
      ps.filter((p) => p.clase === 'vela').forEach((p) => otros.push([t2, CC(colOf(p.sesgo)), `Flechita · ${p.nombre}:`, p.descripcion]));
      if (L.ict) pick(rows, 'ict', t2).forEach((z) => otros.push([t2, CC(alpha(colOf(z.sesgo), 0.5)), `${z.nombre} ${z.sesgo}:`, z.descripcion]));
    });
    if (otros.length) {
      leg.append(el('p', 'ab-ex-sub', 'En otras temporalidades (tocá para verlo en el gráfico)'));
      otros.forEach(([t2, sw, title, text]) => {
        const r = el('div', 'ab-ex-item ab-ex-link ab-ex-otro'), i = el('i'); Object.assign(i.style, sw);
        const t = el('span'); t.append(el('em', 'ab-ex-tf', TF_TXT[t2] || t2), el('b', '', title), ' ', text); r.append(i, t);
        r.setAttribute('role', 'button'); r.tabIndex = 0; r.title = `Ver en ${TF_TXT[t2] || t2}`;
        const ir = () => setTf(t2);
        r.addEventListener('click', ir); r.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); ir(); } });
        leg.append(r);
      });
    }
    document.getElementById('ex-n').textContent = (nAca + otros.length) || '';
    document.getElementById('scen-note').textContent = ghosts.length || SIN_FUTURO ? '' : 'No hay suficientes situaciones parecidas para armar escenarios en esta temporalidad.';

    // que velas forman cada marca: se encienden al resaltarla
    const ex = {};
    pick(rows, 'patron', tf).forEach((p) => {
      if (p.clase === 'grafico') {
        const tt = ['l1_t', 'l2_t', 'pt1_t', 'pt2_t', 'pt3_t', 'pt4_t', 'pt5_t'].map((k) => num(p[k])).filter((v) => v !== null);
        const t0 = tt.length ? Math.min(...tt) : num(p.t);
        ex[`pat-grafico-${p.nombre}`] = new Set(all.filter((b) => b.t >= t0).map((b) => b.t));
      } else {
        const k = /^Tres|^Estrella de la|vespertina/.test(p.nombre) ? 3 : /^Envolvente|^Harami/.test(p.nombre) ? 2 : 1;
        ex[`pat-vela-${p.nombre}`] = new Set(Array.from({ length: k }, (_, j) => num(p.t) - j * tfMs));
      }
    });
    d.divs.forEach((v) => { ex[v.key] = new Set([v.t1, v.t2]); });
    ex.fvg = new Set(fvgs.flatMap((z) => [z.t - tfMs, z.t, z.t + tfMs]));
    ex.ondas = new Set(giros.filter((g) => g.w).map((g) => g.t));
    const srLv = pick(rows, 'explicacion').filter((e) => e.plazo === S.plazo && e.tipo === 'vigilar' && e.precio !== null && e.precio !== undefined).map((e) => num(e.precio));
    ex.sr = new Set(all.filter((b) => srLv.some((v) => b.l <= v && v <= b.h)).map((b) => b.t));
    ex.fib = new Set(all.filter((b) => (d.fibs || []).some((f) => b.l <= f.p && f.p <= b.h)).map((b) => b.t));
    S.exCandles = ex;
    // lo marcado que ya no esta en la lista (otra temporalidad, una capa apagada) se desmarca
    const hay = new Set([...document.querySelectorAll('#legend [data-ex]')].map((n) => n.dataset.ex));
    S.sel.forEach((x) => { if (!hay.has(x)) S.sel.delete(x); });
    if (S.hoverEx && !hay.has(S.hoverEx)) S.hoverEx = null;
    refocus();
  }

  // ---------- probabilidades ----------
  function drawProbs(rows, sum) {
    const p = pick(rows, 'plazo').find((r) => r.plazo === S.plazo);
    document.getElementById('prob-tf').textContent = `a ${S.plazo}`;
    if (!p) return;
    const up = num(p.sube), base = num(p.base), price = num(sum.precio);
    document.getElementById('prob-when').textContent = `Hasta las ${p.hora.slice(-5)} h del ${p.hora.slice(0, 5)}`;
    const split = document.getElementById('split'); split.replaceChildren();
    const u = el('div', 'ab-sp-u', `▲ Cierra arriba ${f0(up)}%`), d = el('div', 'ab-sp-d', `${f0(100 - up)}% abajo ▼`), bm = el('div', 'ab-sp-base');
    u.style.flexBasis = '50%'; d.style.flexBasis = '50%'; bm.style.left = '50%'; split.append(u, d, bm);
    later(() => { u.style.flexBasis = up + '%'; d.style.flexBasis = (100 - up) + '%'; bm.style.left = `calc(${base}% - 1px)`; });
    const v = document.getElementById('verdict'); v.textContent = `Al cierre: ${p.veredicto.toLowerCase()}`;
    v.style.color = p.veredicto === 'Sesgo alcista' ? 'var(--color-ok)' : p.veredicto === 'Sesgo bajista' ? 'var(--color-bad)' : 'var(--color-fg-muted)';
    document.getElementById('prob-base').textContent = (p.pocos_casos ? 'Pocos casos: poco confiable · ' : '')
      + `margen ±${f0(num(p.margen))} pts · línea = normal ${f0(base)}%`;

    const goals = pick(rows, 'objetivo_plazo').filter((t) => t.plazo === S.plazo).map((t) => ({ p: num(t.precio), prob: num(t.prob), up: t.lado === 'arriba' }));
    const items = goals.concat([{ p: price, now: true }]).sort((a, b) => b.p - a.p);
    const box = document.getElementById('ladder'); box.replaceChildren();
    const W = Math.max(240, box.clientWidth), rh = 26, H = items.length * rh + 6;
    const svg = d3.select(box).append('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', 'Probabilidad de tocar cada precio');
    const lx = 74, rx = W - 40, bx = d3.scaleLinear([0, 100], [0, rx - lx - 8]);
    const med = p.mediana === null ? null : num(p.mediana);
    items.forEach((it, k) => {
      const yy = k * rh + 4;
      const g = svg.append('g');
      if (it.now) {
        g.append('rect').attr('x', 0).attr('y', yy).attr('width', W).attr('height', rh - 4).attr('rx', 6).style('fill', 'var(--color-fg)');
        g.append('text').attr('x', 8).attr('y', yy + 15).style('fill', 'var(--color-bg)').style('font-weight', 600).text(fp(it.p));
        g.append('text').attr('x', lx).attr('y', yy + 15).style('fill', 'var(--color-bg)').text(`${MON()} ahora`);
        return;
      }
      const col = it.up ? 'var(--color-ok)' : 'var(--color-bad)';
      g.append('text').attr('x', 8).attr('y', yy + 15).style('fill', col).text(`${it.up ? '▲' : '▼'} ${fp(it.p)}`);
      g.append('rect').attr('x', lx).attr('y', yy + 5).attr('width', rx - lx - 8).attr('height', 10).attr('rx', 5).style('fill', 'var(--color-bg)');
      const bar = g.append('rect').attr('class', 'ab-lv-bar').attr('x', lx).attr('y', yy + 5).attr('height', 10).attr('rx', 5).style('fill', col)
        .style('fill-opacity', .35 + it.prob / 160).attr('width', 0).style('width', '0px');
      later(() => bar.style('width', bx(it.prob) + 'px'));
      g.append('text').attr('x', W - 4).attr('y', yy + 15).attr('text-anchor', 'end').style('font-weight', 600).text(`${f0(it.prob)}%`);
    });
    document.getElementById('prob-foot').textContent = `Probabilidad de que ${MON()} toque cada precio antes de esa hora, según ${f0(num(p.n))} casos parecidos de los últimos ${num(p.dias)} días.`
      + (med === null ? '' : ` Precio más probable al cierre: ${fp(med)}.`) + ` El 80% terminó entre ${fp(num(p.min))} y ${fp(num(p.max))}.`;
  }

  // ---------- senales ----------
  function drawSignals(rows) {
    const tiles = document.getElementById('tiles'); tiles.replaceChildren();
    pick(rows, 'contexto').forEach((c) => {
      const t = el('div', 'ab-tile ab-sig-' + c.senal);
      const h = el('div', 'ab-tile-t'); h.append(el('i'), c.titulo);
      t.append(h, el('div', 'ab-tile-v', c.valor), el('div', 'ab-tile-d', c.detalle)); tiles.append(t);
    });
    const books = document.getElementById('books'); books.replaceChildren();
    pick(rows, 'libro').forEach((b) => {
      const imb = num(b.desequilibrio), w = Math.min(50, Math.abs(imb) / 1.2);
      const row = el('div', 'ab-book' + (b.en_total ? '' : ' ab-off'));
      const tr = el('span', 'ab-book-tr'); const i = el('i'); i.style.background = imb >= 0 ? 'var(--color-ok)' : 'var(--color-bad)';
      i.style.left = '50%'; i.style.width = '0'; tr.append(i);
      row.append(el('span', '', b.exchange + (b.en_total ? '' : '*')), tr, el('span', '', sg(imb, 0))); row.lastChild.style.textAlign = 'right';
      books.append(row);
      later(() => { i.style.left = (imb >= 0 ? 50 : 50 - w) + '%'; i.style.width = w + '%'; });
    });
  }

  // ---------- niveles a escala ----------
  function drawLevels(rows, sum) {
    const box = document.getElementById('levels'); box.replaceChildren();
    const price = num(sum.precio);
    const lv = pick(rows, 'nivel').map((r) => ({ name: r.nombre, p: num(r.precio), d: num(r.distancia) })).filter((r) => Math.abs(r.d) <= 8);
    if (!lv.length) return;
    const W = Math.max(260, box.clientWidth), H = Math.max(360, lv.length * 19 + 40);
    const ext = d3.extent(lv.map((r) => r.p).concat([price]));
    const y = d3.scaleLinear(ext, [H - 14, 14]);
    const svg = d3.select(box).append('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', 'Niveles clave a escala');
    const axisX = Math.round(W * .52);
    svg.append('line').attr('x1', axisX).attr('x2', axisX).attr('y1', 8).attr('y2', H - 8).style('stroke', 'var(--color-border-line)').style('stroke-width', 2);
    svg.append('rect').attr('x', axisX - 3).attr('y', y(ext[1])).attr('width', 6).attr('height', Math.max(0, y(price) - y(ext[1]))).attr('rx', 3)
      .style('fill', 'var(--color-ok)').style('fill-opacity', .25);
    svg.append('rect').attr('x', axisX - 3).attr('y', y(price)).attr('width', 6).attr('height', Math.max(0, y(ext[0]) - y(price))).attr('rx', 3)
      .style('fill', 'var(--color-bad)').style('fill-opacity', .25);
    // separar etiquetas que se pisan (el precio actual ocupa su propio renglon, mas alto)
    const items = lv.concat([{ name: `${MON()} ahora`, p: price, d: 0, now: true }]).sort((a, b) => b.p - a.p)
      .map((r) => ({ ...r, y: y(r.p), ly: y(r.p), gap: r.now ? 26 : 17 }));
    const gapOf = (a, b) => (a.now || b.now ? 22 : 17);
    for (let k = 1; k < items.length; k++) if (items[k].ly - items[k - 1].ly < gapOf(items[k], items[k - 1])) items[k].ly = items[k - 1].ly + gapOf(items[k], items[k - 1]);
    const over = items.length ? items[items.length - 1].ly - (H - 10) : 0;
    if (over > 0) items.forEach((it) => { it.ly -= over; });
    for (let k = items.length - 2; k >= 0; k--) if (items[k + 1].ly - items[k].ly < gapOf(items[k], items[k + 1])) items[k].ly = items[k + 1].ly - gapOf(items[k], items[k + 1]);
    items.forEach((it) => {
      if (it.now) {
        const tg = svg.append('g');
        tg.append('path').attr('d', `M${axisX},${it.y} L${axisX},${it.ly}`).style('stroke', 'var(--color-fg)');
        tg.append('rect').attr('x', axisX - 50).attr('y', it.ly - 11).attr('width', 100).attr('height', 22).attr('rx', 11).style('fill', 'var(--color-fg)');
        tg.append('text').attr('x', axisX).attr('y', it.ly).attr('dy', '.34em').attr('text-anchor', 'middle').style('fill', 'var(--color-bg)').style('font-weight', 600).text(`Ahora ${fp(price)}`);
        return;
      }
      const col = it.p > price ? 'var(--color-ok)' : 'var(--color-bad)';
      const g = svg.append('g');
      g.append('circle').attr('cx', axisX).attr('cy', it.y).attr('r', 3.5).style('fill', col);
      g.append('path').attr('d', `M${axisX - 6},${it.y} L${axisX - 16},${it.ly} L${axisX - 22},${it.ly}`).style('fill', 'none').style('stroke', 'var(--color-border-line)');
      g.append('text').attr('x', axisX - 26).attr('y', it.ly).attr('dy', '.34em').attr('text-anchor', 'end').style('fill', 'var(--color-fg)').text(it.name.replace(/ \(estimada\)/, ''))
        .each(function () {      // se mide una vez y se corta en proporcion (antes, una medicion cada dos letras)
          const max = axisX - 30, s = this.textContent, L = this.getComputedTextLength();
          if (!(L > max)) return;
          let n = Math.max(4, Math.floor(s.length * max / L) - 1); this.textContent = s.slice(0, n) + '…';
          while (n > 4 && this.getComputedTextLength() > max) { n -= 2; this.textContent = s.slice(0, n) + '…'; }
        });
      g.append('text').attr('x', axisX + 12).attr('y', it.ly).attr('dy', '.34em').style('fill', col).style('font-weight', 600).text(fp(it.p));
      g.append('text').attr('x', W - 2).attr('y', it.ly).attr('dy', '.34em').attr('text-anchor', 'end').style('fill', 'var(--color-fg-muted)').text(sg(it.d, 1));
    });
  }

  // ---------- ondas y FVG ----------
  function drawWaves(rows) {
    const cur = pick(rows, 'marco', S.tf)[0];
    document.getElementById('ond-tf').textContent = TF_TXT[S.tf];
    const pats = document.getElementById('pats'); pats.replaceChildren();
    const list = pick(rows, 'patron', S.tf).sort((a, b) => (a.clase === 'grafico' ? -1 : 1));
    if (!list.length && !pick(rows, 'divergencia', S.tf).length) pats.append(el('p', 'ab-note', 'Sin figuras, patrones de velas ni divergencias claras en esta temporalidad.'));
    list.forEach((p) => {
      const card = el('div', 'ab-pat'); const top = el('div', 'ab-pat-top');
      const chip = el('span', 'ab-sigchip ab-' + (p.sesgo === 'alcista' ? 'compra' : p.sesgo === 'bajista' ? 'venta' : 'neutral'),
        `${p.sesgo === 'alcista' ? '▲' : p.sesgo === 'bajista' ? '▼' : '◆'} ${p.clase === 'grafico' ? 'Figura' : 'Vela'} · ${p.estado}`);
      top.append(el('b', '', p.nombre), chip); card.append(top);
      if (p.objetivo !== null) card.append(el('span', 'ab-target', `Objetivo ${fp(num(p.objetivo))} (${sg((num(p.objetivo) / num(pick(rows, 'resumen')[0].precio) - 1) * 100, 1)})`));
      card.append(el('p', '', p.descripcion));
      if (p.exito !== null) {
        const r = el('div', 'ab-pat-rate'); const tr = el('span'); const i = el('i');
        i.style.background = num(p.exito) >= 55 ? 'var(--color-ok)' : num(p.exito) >= 45 ? 'var(--color-fg-muted)' : 'var(--color-bad)';
        i.style.width = '0'; tr.append(i); r.append(tr, el('span', '', `${f0(num(p.exito))}% de ${num(p.casos)}`)); card.append(r);
        later(() => { i.style.width = num(p.exito) + '%'; });
      }
      pats.append(card);
    });
    const dg = {};
    pick(rows, 'divergencia', S.tf).forEach((d) => {
      const k = `${d.t1}-${d.t2}-${d.tipo}`; (dg[k] = dg[k] || { ...d, names: [] }).names.push(d.indicador);
    });
    Object.values(dg).forEach((d) => {
      const card = el('div', 'ab-pat'); const top = el('div', 'ab-pat-top');
      top.append(el('b', '', `Divergencia ${d.tipo}`), el('span', 'ab-sigchip ab-' + (d.tipo === 'alcista' ? 'compra' : 'venta'), d.names.join(' + ')));
      const hiLo = d.tipo === 'bajista' ? 'máximo más alto' : 'mínimo más bajo', mom = d.tipo === 'bajista' ? 'la suba pierde fuerza' : 'la baja pierde fuerza';
      card.append(top, el('p', '', `El precio hizo un ${hiLo} (${fp(num(d.p1))} → ${fp(num(d.p2))}) pero ${d.names.join(' y ')} no acompañó: ${mom}.`));
      pats.append(card);
    });
    const w = document.getElementById('wave'); w.setAttribute('data-where', `tabla=marco&tf=${S.tf}`);
    w.textContent = cur ? cur.elliott : '—';
    const tg = document.getElementById('wave-target'); tg.replaceChildren();
    if (cur && cur.elliott_objetivo !== null) tg.append('Objetivo de la onda', el('b', '', fp(num(cur.elliott_objetivo))));
    const box = document.getElementById('fvgs'); box.replaceChildren();
    const zones = pick(rows, 'fvg', S.tf);
    if (!zones.length) { box.append(el('p', 'ab-note', 'Sin zonas FVG abiertas cerca del precio.')); return; }
    zones.forEach((z) => {
      const r = el('div', 'ab-fvg'); const i = el('i');
      i.style.background = z.tipo === 'alcista' ? 'color-mix(in srgb, var(--color-ok) 45%, transparent)' : 'color-mix(in srgb, var(--color-bad) 45%, transparent)';
      r.append(i, el('span', '', `${fp(num(z.bajo))} – ${fp(num(z.alto))}`), el('span', '', z.tipo)); box.append(r);
    });
  }

  // ---------- indicadores ----------
  function drawIndicators(rows) {
    document.getElementById('ind-tf').textContent = TF_TXT[S.tf];
    const cur = pick(rows, 'marco', S.tf)[0];
    const votes = document.getElementById('votes'); votes.replaceChildren();
    if (cur) [['Medias móviles', cur.ma_compra, cur.ma_neutral, cur.ma_venta], ['Osciladores', cur.osc_compra, cur.osc_neutral, cur.osc_venta]].forEach(([name, b, nn, s]) => {
      const v = el('div', 'ab-vote'); const top = el('div', 'ab-vote-top');
      top.append(el('span', '', name), el('span', '', `${b} alcistas · ${nn} neutrales · ${s} bajistas`));
      const bar = el('div', 'ab-vote-bar'); const tot = b + nn + s || 1;
      const parts = [[b, 'var(--color-ok)'], [nn, 'var(--color-fg-muted)'], [s, 'var(--color-bad)']].map(([k, c]) => { const i = el('i'); i.style.background = c; if (c.includes('muted')) i.style.opacity = '.35'; bar.append(i); return [i, k]; });
      v.append(top, bar); votes.append(v);
      later(() => parts.forEach(([i, k]) => { i.style.flexBasis = (k / tot * 100) + '%'; }));
    });
    const tb = document.querySelector('#ind-table tbody'); tb.replaceChildren();
    let group = null;
    pick(rows, 'indicador', S.tf).forEach((r) => {
      if (r.grupo !== group) { group = r.grupo; const g = el('tr', 'ab-g'); const td = el('td', '', group); td.colSpan = 4; g.append(td); tb.append(g); }
      const tr = el('tr'); tr.dataset.key = `${encodeURIComponent(r.tf)},${encodeURIComponent(r.indicador)}`;
      const sig = el('td'); const chip = el('span', 'ab-sigchip ab-' + r.senal, r.senal === 'compra' ? '▲ Alcista' : r.senal === 'venta' ? '▼ Bajista' : '• Neutral'); sig.append(chip);
      const det = el('td', '', r.detalle); if (!r.vota) det.append(el('span', 'ab-novote', (r.detalle ? ' · ' : '') + 'no vota'));
      tr.append(el('td', '', r.indicador), el('td', 'r', r.valor === null ? '' : f2(num(r.valor))), sig, det); tb.append(tr);
    });
  }

  function drawHits(rows) {
    const box = document.getElementById('hits'); box.replaceChildren();
    const hits = pick(rows, 'acierto');
    if (!hits.length) { box.append(el('p', 'ab-note', 'Cada predicción queda registrada. Los aciertos aparecen cuando se cumple el plazo de cada una, desde las próximas corridas.')); return; }
    const tbl = el('table', 'ab-tbl'); tbl.setAttribute('data-source', 'analisis'); tbl.setAttribute('data-row-key', 'tf,horizonte');
    const hr = el('tr');
    [['tf', 'Velas'], ['horizonte', 'Plazo'], ['pronosticos', 'Casos'], ['aciertos', 'Aciertos'], ['brier', 'Brier'], ['en_rango', 'En rango 80%']].forEach(([f, t]) => { const th = el('th', '', t); th.setAttribute('data-field', f); hr.append(th); });
    const th = el('thead'); th.append(hr); const tb = el('tbody');
    const pc = (v) => (num(v) === null ? '—' : `${f1(num(v))}%`);
    hits.forEach((h) => { const tr = el('tr'); tr.dataset.key = `${encodeURIComponent(h.tf)},${encodeURIComponent(h.horizonte)}`;
      const er = num(h.en_rango), cr = num(h.con_rango) || 0;
      [h.tf, h.horizonte, h.pronosticos, pc(h.aciertos), num(h.brier) === null ? '—' : ar.format('.3f')(num(h.brier))].forEach((v) => tr.append(el('td', '', String(v))));
      // con menos de 10 casos el porcentaje no dice nada (2 de 2 es "100%"): se muestra apagado y se avisa
      if ((num(h.pronosticos) || 0) < 10) { tr.children[3].style.color = 'var(--mute)'; tr.children[3].title = 'Pocos casos todavía: el porcentaje no dice nada'; tr.children[3].textContent += ' · pocos'; }
      // el rango es honesto si queda cerca de 80%: muy por debajo, el cono es angosto; muy por arriba, exagera
      const td = el('td', '', er === null ? '—' : `${f1(er)}% (${cr})`);
      if (er !== null && cr >= 30) { td.style.color = Math.abs(er - 80) <= 7 ? 'var(--color-ok)' : 'var(--color-warn)'; td.title = Math.abs(er - 80) <= 7 ? 'Cerca del 80%: el rango es honesto' : er < 80 ? 'Debajo del 80%: el rango viene angosto' : 'Arriba del 80%: el rango viene ancho'; }
      tr.append(td); tb.append(tr); });
    tbl.append(th, tb); box.append(tbl, el('p', 'ab-note', 'Brier mide la calidad de las probabilidades: 0,250 es tirar una moneda; menos es mejor. "En rango 80%": cuántas veces el precio terminó dentro del rango que anunció (lo honesto es cerca de 80%).'));
  }
  dash.onData(draw);   // al final: todo lo de arriba (tambien el grafico) ya esta definido
})();
