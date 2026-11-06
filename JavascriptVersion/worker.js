/*
 * El analisis corre aca, en segundo plano, para que la pantalla no se trabe mientras calcula.
 * Prioridad: el activo que se esta mirando se rehace cada INTERVALO ms. En los huecos entre un ciclo y otro se
 * analizan los demas activos de a uno (cada uno a lo sumo cada FONDO_CADA ms): al cambiar de activo ya esta su
 * analisis (y su grafico) y no hay que esperar. Todo se pausa con la app en segundo plano.
 */
importScripts(...['indicadores.js', 'aprendizaje.js', 'fuerte.js', 'analisis.js', 'datos.js'].map((f) => f + self.location.search));

const INTERVALO = 12000;            // el activo a la vista
const FONDO_CADA = 10 * 60000;      // cada uno de los demas
const FONDO_PAUSA = 8000;           // entre dos analisis de fondo (Binance cobra peso por cada pedido de velas)
const TOPE = 90000;                 // un ciclo colgado (red del celular) no frena a los siguientes
let pausado = true, ACTIVO = 'BTCUSDT', todos = [], numero = 0, proximo = 0, ultimoFondo = 0;
let corriendo = false, pedirActivo = false, despertar = null, interrumpir = null;
const hecho = {}, guardado = {}, mostrado = {};

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
const conTope = (p) => Promise.race([p, new Promise((_, no) => setTimeout(() => no(new Error('tardó demasiado')), TOPE))]);

function calcular(sym, input) {
  const mon = sym.replace('USDT', '');
  input.moneda = mon;
  const { rows, log } = Analisis.analizar(input);
  Datos.guardarLog(log, sym);
  return renombrar(rows, mon);
}

async function cicloActivo() {
  const t0 = Date.now(), sym = ACTIVO;
  try {
    // los modelos y las velas no dependen uno del otro: se bajan a la vez
    const [input] = await Promise.all([conTope(Datos.recolectar((texto) => postMessage({ tipo: 'progreso', texto, sym }), sym)), cargarModelos()]);
    if (sym !== ACTIVO) return;                    // eligieron otro activo mientras bajaban los datos: no se calcula este
    const rows = calcular(sym, input);
    numero += 1; hecho[sym] = Date.now();
    postMessage({ tipo: 'analisis', rows, numero, ms: Date.now() - t0, fuente: input.fuente, sym, lentos: Datos.lentos() });
    if (Date.now() - (guardado[sym] || 0) > 60000) { guardado[sym] = Date.now(); Datos.guardarUltimo(sym, rows); }
  } catch (e) {
    if (sym === ACTIVO) postMessage({ tipo: 'error', texto: e && e.message ? e.message : String(e), sym });
  }
}

/** Un activo que no se esta mirando. Si eligen otro activo mientras bajan sus datos, se deja (no frena al elegido). */
async function cicloFondo(sym) {
  hecho[sym] = Date.now(); ultimoFondo = Date.now();     // aunque falle, se reintenta en la proxima vuelta
  try {
    await cargarModelos();
    const corte = new Promise((r) => { interrumpir = r; });
    const input = await Promise.race([conTope(Datos.recolectar(null, sym)), corte.then(() => null)]);
    interrumpir = null;
    if (!input || pedirActivo) { hecho[sym] = 0; return; }
    const rows = calcular(sym, input);
    postMessage({ tipo: 'analisis', rows, numero: 0, fondo: true, hora: Date.now(), sym });
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
  if (d.tipo === 'pausa') {
    pausado = true;
    if (despertar) despertar();
  } else if (d.tipo === 'seguir') {
    if (d.todos) todos = d.todos.map((m) => `${m}USDT`);
    if (d.sym && d.sym !== ACTIVO) { ACTIVO = d.sym; if (interrumpir) interrumpir(); }
    pedirActivo = true;              // al volver a la app o cambiar de activo: el elegido primero
    pausado = false;
    mostrarGuardado(ACTIVO);
    if (despertar) despertar();
    bucle();
  }
};

// el primer ciclo lo pide la app con el activo elegido ("seguir"): asi no se calcula BTC de mas al abrir otro
