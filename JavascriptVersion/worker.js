/*
 * El analisis corre aca, en segundo plano, para que la pantalla no se trabe mientras calcula.
 * Prioridad: el activo que se esta mirando se rehace cada INTERVALO ms. En los huecos entre un ciclo y otro se
 * analizan los demas activos de a uno (cada uno a lo sumo cada FONDO_CADA ms), en version liviana (sin libros ni
 * mapa de liquidaciones): al cambiar de activo ya esta su analisis (y su grafico) y no hay que esperar. Todo se pausa
 * con la app en segundo plano. Si en un ciclo no cambio nada (sin vela nueva, precio casi igual, mismos datos del
 * momento), no se recalcula: se ahorra CPU y bateria (como mucho pasa REHACER sin recalcular).
 */
importScripts(...['indicadores.js', 'aprendizaje.js', 'fuerte.js', 'analisis.js', 'datos.js'].map((f) => f + self.location.search));

const INTERVALO = 12000;            // el activo a la vista
const FONDO_CADA = 15 * 60000;      // cada uno de los demas (antes 10 min)
const FONDO_PAUSA = 8000;           // entre dos analisis de fondo (Binance cobra peso por cada pedido de velas)
const TOPE = 90000;                 // un ciclo colgado (red del celular) no frena a los siguientes
const REHACER = 60000;              // aunque no cambie nada, se recalcula al menos cada tanto
const MOVIDA = 0.0003;              // con el precio a menos de 0,03% del ultimo analisis y lo demas igual, no se recalcula
const GUARDAR_CADA = 5 * 60000;     // el ultimo analisis en el telefono (y siempre al salir de la app)
let pausado = true, ACTIVO = 'BTCUSDT', todos = [], numero = 0, proximo = 0, ultimoFondo = 0;
let corriendo = false, pedirActivo = false, despertar = null, interrumpir = null;
const hecho = {}, guardado = {}, mostrado = {};
let previo = null, sinGuardar = null;     // lo que se uso en el ultimo analisis del activo a la vista; filas por guardar

/** En los textos del analisis dice BTC: para otro activo se cambia el nombre. */
function renombrar(rows, mon) {
  if (mon === 'BTC') return rows;
  return rows.map((r) => {
    const o = {};
    for (const [k, v] of Object.entries(r)) o[k] = typeof v === 'string' ? v.replace(/\bBTC\b/g, mon) : v;
    return o;
  });
}

/** Al abrir la app o elegir otro activo: el ultimo analisis guardado en el telefono, al toque (despues llega el nuevo). */
async function mostrarGuardado(sym) {
  if (mostrado[sym]) return;
  mostrado[sym] = true;
  try {
    const u = await Datos.ultimo(sym);
    if (u && u.rows && sym === ACTIVO) postMessage({ tipo: 'analisis', rows: u.rows, numero: 0, guardado: true, hora: u.hora, sym });
  } catch (e) { /* sin guardado */ }
}

// el termometro y el modelo de movimiento fuerte: una vez, y cada 6 h con la app abierta dias
async function cargarModelos() {
  if (self.TERMOMETRO && Date.now() - (self.JSON_T || 0) < 6 * 3600000) return;
  // 'no-cache': se pregunta si cambiaron (una vez por semana los reentrena GitHub) y si no, sale del telefono.
  // Con 'no-store' se bajaban enteros (unos 180 KB comprimidos) cada vez que se abria la app.
  // los dos a la vez (antes, uno detras del otro)
  await Promise.all([
    fetch('termometro.json', { cache: 'no-cache', signal: AbortSignal.timeout(15000) }).then((r) => r.json()).then((j) => { self.TERMOMETRO = j; }).catch(() => { /* queda el anterior */ }),
    fetch('modelo_fuerte.json', { cache: 'no-cache', signal: AbortSignal.timeout(15000) }).then((r) => r.json()).then((j) => { self.MODELO_FUERTE = j; }).catch(() => { /* queda el anterior o la tabla */ }),
  ]);
  self.JSON_T = Date.now();
}
// modelo propio de movimiento fuerte de SOL, XRP y ZEC (medido: les va mejor que la tabla y que el de BTC); se baja
// solo el de la cripto que se analiza, y se vuelve a preguntar cada 6 h
const CON_MODELO = new Set(['SOL', 'XRP', 'ZEC']);
self.MODELOS_FUERTE = {}; const modeloT = {};
async function modeloDe(mon) {
  if (!CON_MODELO.has(mon) || Date.now() - (modeloT[mon] || 0) < 6 * 3600000) return;
  modeloT[mon] = Date.now();
  await fetch(`modelo_fuerte_${mon}.json`, { cache: 'no-cache', signal: AbortSignal.timeout(15000) })
    .then((r) => (r.ok ? r.json() : null)).then((j) => { if (j) self.MODELOS_FUERTE[mon] = j; }).catch(() => { modeloT[mon] = 0; });
}
const conTope = (p) => Promise.race([p, new Promise((_, no) => setTimeout(() => no(new Error('tardó demasiado')), TOPE))]);

function calcular(sym, input) {
  const mon = sym.replace('USDT', '');
  input.moneda = mon;
  input.escenarios = false;          // la simulacion de futuro no se muestra (SIN_FUTURO en la pagina): no se arma
  const { rows, log } = Analisis.analizar(input);
  Datos.guardarLog(log, sym);
  return renombrar(rows, mon);
}

/** Lo que mira el analisis para saber si hace falta rehacerlo. Los datos del momento (contexto, libros, noticias...)
 *  salen de una cache: mientras no se vuelven a pedir son el mismo objeto. */
function firma(sym, input) {
  const velas = Object.keys(input.candles).map((tf) => { const c = input.candles[tf]; return c.length ? c[c.length - 1][0] : 0; }).join();
  return { sym, t: Date.now(), precio: input.price, velas, vivo: input.live5m ? input.live5m[0] : 0, fuente: input.fuente, modelos: self.JSON_T,
    datos: [input.ctxRaw, input.booksRaw, input.liqRaw, input.externo, input.opcionesRaw, self.MODELOS_FUERTE[sym.replace('USDT', '')]] };
}
function igual(a, b) {
  return !!a && a.sym === b.sym && b.t - a.t < REHACER && a.velas === b.velas && a.vivo === b.vivo && a.fuente === b.fuente
    && a.modelos === b.modelos && Math.abs(b.precio / a.precio - 1) < MOVIDA && a.datos.every((x, i) => x === b.datos[i]);
}
function guardarFilas() {
  if (!sinGuardar) return;
  const { sym, rows } = sinGuardar;
  sinGuardar = null; guardado[sym] = Date.now(); Datos.guardarUltimo(sym, rows);
}

async function cicloActivo() {
  const t0 = Date.now(), sym = ACTIVO;
  try {
    // los modelos y las velas no dependen uno del otro: se bajan a la vez
    const [input] = await Promise.all([conTope(Datos.recolectar((texto) => postMessage({ tipo: 'progreso', texto, sym }), sym)), cargarModelos(), modeloDe(sym.replace('USDT', ''))]);
    if (sym !== ACTIVO) return;                    // eligieron otro activo mientras bajaban los datos: no se calcula este
    const f = firma(sym, input);
    hecho[sym] = Date.now();
    if (igual(previo, f)) return;                  // nada nuevo: la pantalla ya tiene este analisis
    const rows = calcular(sym, input);
    previo = f; numero += 1;
    postMessage({ tipo: 'analisis', rows, numero, ms: Date.now() - t0, fuente: input.fuente, sym });
    sinGuardar = { sym, rows };
    if (Date.now() - (guardado[sym] || 0) > GUARDAR_CADA) guardarFilas();
  } catch (e) {
    if (sym === ACTIVO) { previo = null; postMessage({ tipo: 'error', texto: e && e.message ? e.message : String(e), sym }); }   // el proximo que salga bien borra el aviso
  }
}

/** Un activo que no se esta mirando. Si eligen otro activo mientras bajan sus datos, se deja (no frena al elegido). */
async function cicloFondo(sym) {
  hecho[sym] = Date.now(); ultimoFondo = Date.now();     // aunque falle, se reintenta en la proxima vuelta
  try {
    await cargarModelos();
    const corte = new Promise((r) => { interrumpir = r; });
    const [input] = await Promise.all([Promise.race([conTope(Datos.recolectar(null, sym, { liviano: true })), corte.then(() => null)]), modeloDe(sym.replace('USDT', ''))]);
    interrumpir = null;
    if (!input || pedirActivo) { hecho[sym] = 0; return; }
    const rows = calcular(sym, input);
    // como texto: en la pantalla solo se arman los objetos si eligen este activo (ver app.js)
    const r = rows.find((x) => x.tabla === 'resumen');
    postMessage({ tipo: 'analisis', json: JSON.stringify(rows), resumen: r ? { precio: r.precio, cambio_24h: r.cambio_24h } : null, numero: 0, fondo: true, hora: Date.now(), sym });
    guardado[sym] = Date.now(); Datos.guardarUltimo(sym, rows);
  } catch (e) { /* se reintenta en la proxima vuelta */ }
  interrumpir = null;
}

function siguienteFondo() {
  const ahora = Date.now();
  return todos.filter((s) => s !== ACTIVO && ahora - (hecho[s] || 0) > FONDO_CADA).sort((a, b) => (hecho[a] || 0) - (hecho[b] || 0))[0] || null;
}
const dormir = (ms) => new Promise((r) => { despertar = r; setTimeout(r, ms); });

async function bucle() {
  if (corriendo) return;
  corriendo = true;
  while (!pausado) {
    if (pedirActivo || Date.now() >= proximo) {
      pedirActivo = false;
      await cicloActivo();
      proximo = Date.now() + INTERVALO;
      continue;
    }
    const s = Date.now() - ultimoFondo >= FONDO_PAUSA && proximo - Date.now() > 2500 ? siguienteFondo() : null;
    if (s) { await cicloFondo(s); continue; }
    await dormir(Math.max(250, Math.min(proximo, ultimoFondo + FONDO_PAUSA) - Date.now()));
  }
  corriendo = false;
}

onmessage = (ev) => {
  const d = ev.data;
  if (d.tipo === 'registro') {          // "Reproducir": las predicciones guardadas de una temporalidad entre dos horas
    Datos.leerLog(d.sym).then((log) => postMessage({ tipo: 'registro', id: d.id, sym: d.sym,
      log: log.filter((r) => r[1] === d.tf && r[0] >= d.desde && r[0] <= d.hasta) }))
      .catch(() => postMessage({ tipo: 'registro', id: d.id, sym: d.sym, log: [] }));
    return;
  }
  if (d.tipo === 'pausa') {
    pausado = true;
    guardarFilas();                  // al salir de la app: el ultimo analisis queda para la proxima vez que se abra
    if (despertar) despertar();
  } else if (d.tipo === 'seguir') {
    if (d.todos) todos = d.todos.map((m) => `${m}USDT`);
    if (d.sym && d.sym !== ACTIVO) { guardarFilas(); ACTIVO = d.sym; previo = null; if (interrumpir) interrumpir(); }
    pedirActivo = true;              // al volver a la app o cambiar de activo: el elegido primero
    pausado = false;
    mostrarGuardado(ACTIVO);
    if (despertar) despertar();
    bucle();
  }
};

// el primer ciclo lo pide la app con el activo elegido ("seguir"): asi no se calcula BTC de mas al abrir otro
