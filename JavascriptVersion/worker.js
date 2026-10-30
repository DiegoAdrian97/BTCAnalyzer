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

async function ciclo(nueva = false) {
  if (corriendo) { if (nueva) otraVez = true; return; }
  corriendo = true;
  clearTimeout(timer);
  const t0 = Date.now(), sym = SYM, mon = sym.replace('USDT', '');
  try {
    // los arboles del modelo de movimiento fuerte se bajan una vez
    if (!self.TERMOMETRO) { try { self.TERMOMETRO = await (await fetch('termometro.json', { cache: 'no-store' })).json(); } catch (e) { /* sin termometro */ } }
    if (!self.MODELO_FUERTE) { try { self.MODELO_FUERTE = await (await fetch('modelo_fuerte.json', { cache: 'no-store' })).json(); } catch (e) { /* sin modelo: queda la tabla */ } }
    const input = await Datos.recolectar((texto) => postMessage({ tipo: 'progreso', texto, sym }), sym);
    input.moneda = mon;
    const { rows, log } = Analisis.analizar(input);
    Datos.guardarLog(log, sym);
    numero += 1;
    if (sym === SYM) postMessage({ tipo: 'analisis', rows: renombrar(rows, mon), numero, ms: Date.now() - t0, fuente: input.fuente, sym });
  } catch (e) {
    postMessage({ tipo: 'error', texto: e && e.message ? e.message : String(e), sym });
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
    ciclo(cambio);
  }
};

ciclo();
