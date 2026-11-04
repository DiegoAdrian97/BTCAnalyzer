/*
 * El analisis corre aca, en segundo plano, para que la pantalla no se trabe mientras calcula.
 * Repite cada INTERVALO ms mientras la app esta a la vista; se pausa cuando no.
 * Analiza BTC o ZEC (la app elige): mismas cuentas; en los textos, el nombre de la cripto.
 */
importScripts(...['indicadores.js', 'aprendizaje.js', 'fuerte.js', 'analisis.js', 'datos.js'].map((f) => f + self.location.search));

const INTERVALO = 12000;
let pausado = false, corriendo = false, timer = null, numero = 0, SYM = 'BTCUSDT', otraVez = false;

/** En los textos del analisis dice BTC: para otra cripto se cambia el nombre. */
function renombrar(rows, mon) {
  if (mon === 'BTC') return rows;
  return rows.map((r) => {
    const o = {};
    for (const [k, v] of Object.entries(r)) o[k] = typeof v === 'string' ? v.replace(/\bBTC\b/g, mon) : v;
    return o;
  });
}

let inicio = 0;
const guardado = {}, mostrado = {};
/** Al abrir la app o elegir otro activo: el ultimo analisis guardado en el telefono, al toque (despues llega el nuevo). */
async function mostrarGuardado(sym) {
  if (mostrado[sym]) return;
  mostrado[sym] = true;
  try {
    const u = await Datos.ultimo(sym);
    if (u && u.rows && sym === SYM) postMessage({ tipo: 'analisis', rows: u.rows, numero: 0, guardado: true, hora: u.hora, sym });
  } catch (e) { /* sin guardado */ }
}
async function ciclo(nueva = false) {
  // un ciclo que quedo colgado mas de 90 s (por ejemplo, la app paso a segundo plano en medio de un pedido) no
  // bloquea los siguientes
  if (corriendo && Date.now() - inicio < 90000) { if (nueva) otraVez = true; return; }
  corriendo = true; inicio = Date.now();
  clearTimeout(timer);
  const t0 = Date.now(), sym = SYM, mon = sym.replace('USDT', '');
  try {
    // los arboles del modelo de movimiento fuerte se bajan una vez
    // el termometro y el modelo se reentrenan una vez por mes: con la app abierta dias, se vuelven a pedir cada 6 h
    if (!self.TERMOMETRO || Date.now() - (self.JSON_T || 0) > 6 * 3600000) {
      try { self.TERMOMETRO = await (await fetch('termometro.json', { cache: 'no-store', signal: AbortSignal.timeout(15000) })).json(); } catch (e) { /* queda el anterior */ }
      try { self.MODELO_FUERTE = await (await fetch('modelo_fuerte.json', { cache: 'no-store', signal: AbortSignal.timeout(15000) })).json(); } catch (e) { /* queda el anterior o la tabla */ }
      self.JSON_T = Date.now();
    }
    const input = await Datos.recolectar((texto) => postMessage({ tipo: 'progreso', texto, sym }), sym);
    if (sym !== SYM) throw new Error('cambio');           // eligieron otro activo mientras bajaban los datos: no se calcula este
    input.moneda = mon;
    const { rows, log } = Analisis.analizar(input);
    Datos.guardarLog(log, sym);
    numero += 1;
    const salida = renombrar(rows, mon);
    if (sym === SYM) postMessage({ tipo: 'analisis', rows: salida, numero, ms: Date.now() - t0, fuente: input.fuente, sym });
    if (Date.now() - (guardado[sym] || 0) > 60000) { guardado[sym] = Date.now(); Datos.guardarUltimo(sym, salida); }
  } catch (e) {
    if (!(e && e.message === 'cambio')) postMessage({ tipo: 'error', texto: e && e.message ? e.message : String(e), sym });
  }
  corriendo = false;
  if (otraVez) { otraVez = false; if (!pausado) { ciclo(); return; } }     // pidieron otra cripto mientras calculaba
  if (!pausado) timer = setTimeout(ciclo, Math.max(2000, INTERVALO - (Date.now() - t0)));
}

onmessage = (ev) => {
  if (ev.data.tipo === 'pausa') {
    pausado = true;
    clearTimeout(timer);
  } else if (ev.data.tipo === 'seguir') {
    const cambio = !!ev.data.sym && ev.data.sym !== SYM;
    if (ev.data.sym) SYM = ev.data.sym;
    pausado = false;
    mostrarGuardado(SYM);
    ciclo(cambio);
  }
};

// el primer ciclo lo pide la app con el activo elegido ("seguir"): asi no se calcula BTC de mas al abrir otro
