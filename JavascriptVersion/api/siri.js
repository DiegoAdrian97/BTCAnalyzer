/*
 * Funcion del servidor para el atajo de Siri ("¿Cómo está Bitcoin?"): devuelve una o dos frases en texto plano para
 * que Siri las lea: el precio y el cambio de 24 h, la direccion que ve la app para la proxima hora y el nivel mas cercano
 * (soporte o resistencia).
 * Corre el MISMO analisis que el telefono (indicadores.js, aprendizaje.js, fuerte.js, analisis.js y datos.js, cargados
 * como los carga worker.js) en version liviana, con las velas de Binance Futures (la funcion corre en Frankfurt:
 * vercel.json, "regions"; desde EE.UU. Binance no responde). Datos publicos, sin claves: no hace falta contraseña.
 * La respuesta queda 60 s en la cache de Vercel, asi varios pedidos seguidos no rehacen el analisis. Mientras la
 * instancia sigue viva, las velas quedan en memoria y solo se bajan las nuevas.
 * Diferencia con el telefono: el registro de predicciones (lo que la app fue aprendiendo con el uso) vive en el
 * telefono; aca arranca vacio, asi que el ajuste aprendido puede variar algo. La direccion y los niveles no dependen de eso.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const RAIZ = path.join(__dirname, '..');
const ARCHIVOS = ['indicadores.js', 'aprendizaje.js', 'fuerte.js', 'analisis.js', 'datos.js'];
let ctx = null, base = '';

/** Un "worker" en el servidor: un contexto aparte con self, fetch y los temporizadores, y los archivos de la app adentro. */
function contexto() {
  if (ctx) return ctx;
  const c = { console, setTimeout, clearTimeout, setInterval, clearInterval, AbortController, AbortSignal, URL, performance, structuredClone,
    queueMicrotask, TextEncoder, TextDecoder,
    // los pedidos relativos (api/contexto: noticias, ETF y prima de Coinbase) van a esta misma pagina
    fetch: (u, o) => fetch(/^https?:/.test(String(u)) ? u : `${base}/${String(u).replace(/^\//, '')}`, o) };
  c.self = c; c.globalThis = c;
  vm.createContext(c);
  ARCHIVOS.forEach((f) => vm.runInContext(fs.readFileSync(path.join(RAIZ, f), 'utf8'), c, { filename: f }));
  c.TERMOMETRO = JSON.parse(fs.readFileSync(path.join(RAIZ, 'termometro.json'), 'utf8'));
  c.MODELO_FUERTE = JSON.parse(fs.readFileSync(path.join(RAIZ, 'modelo_fuerte.json'), 'utf8'));
  c.MODELOS_FUERTE = {};
  ctx = c;
  return c;
}

// numeros como los diria una persona: "70.647", "1,1"
const miles = (x) => Math.round(x).toLocaleString('es-AR');
const dec = (x, d = 1) => Number(x).toLocaleString('es-AR', { minimumFractionDigits: d, maximumFractionDigits: d });
const precioTxt = (x) => (x >= 1000 ? miles(x) : dec(x, x >= 10 ? 2 : 4));

/** Las frases para Siri, a partir de las filas del analisis. Exportada para la prueba (pruebas/siri.js). */
function frases(rows, nombre = 'Bitcoin') {
  const r = rows.find((x) => x.tabla === 'resumen');
  if (!r || !r.precio) return 'No pude leer el precio ahora. Probá de nuevo en un rato.';
  const c = rows.find((x) => x.tabla === 'central' && x.plazo === '1 hora') || {};
  const ch = Number(r.cambio_24h);
  let t = `${nombre} está en ${precioTxt(r.precio)} dólares`;
  t += !isFinite(ch) ? '.' : Math.abs(ch) < 0.05 ? ', casi igual que hace 24 horas.' : `, ${ch > 0 ? 'sube' : 'baja'} ${dec(Math.abs(ch))} por ciento en 24 horas.`;
  const dir = c.direccion === 'sube' ? 'que suba' : c.direccion === 'baja' ? 'que baje' : null;
  if (c.direccion) t += dir ? ` Para la próxima hora, la app ve más probable ${dir}.` : ' Para la próxima hora, la app no ve una dirección clara: neutral.';
  const lv = [[c.soporte, 'El soporte'], [c.resistencia, 'La resistencia']].filter(([p]) => p).map(([p, n]) => [Number(p), n]);
  if (lv.length) {
    const [p, n] = lv.sort((a, b) => Math.abs(a[0] - r.precio) - Math.abs(b[0] - r.precio))[0];
    t += ` ${n} más cercano está en ${precioTxt(p)}, a ${dec((Math.abs(p - r.precio) / r.precio) * 100)} por ciento.`;
  }
  return t.replace('La resistencia más cercano', 'La resistencia más cercana');
}

const NOMBRES = { BTC: 'Bitcoin', ETH: 'Ethereum', SOL: 'Solana', XRP: 'XRP', ZEC: 'Zcash' };

async function handler(req, res) {
  res.setHeader('Content-Type', 'text/plain; charset=utf-8');
  // la cache de Vercel guarda la respuesta 60 s (y la sirve vieja hasta 4 min mas mientras rehace una nueva)
  res.setHeader('Cache-Control', 'public, s-maxage=60, stale-while-revalidate=240');
  try {
    const q = new URL(req.url || '/', 'http://x').searchParams;
    const mon = String(q.get('moneda') || 'BTC').toUpperCase().replace(/[^A-Z]/g, '').slice(0, 6) || 'BTC';
    const host = req.headers && (req.headers['x-forwarded-host'] || req.headers.host);
    base = host ? `https://${host}` : '';
    const c = contexto(), sym = `${mon}USDT`;
    const input = await c.Datos.recolectar(null, sym, { liviano: true });
    input.moneda = mon; input.escenarios = false;
    const { rows } = c.Analisis.analizar(input);
    res.status(200).send(frases(rows, NOMBRES[mon] || mon));
  } catch (e) {
    res.setHeader('Cache-Control', 'no-store');   // el error no queda en la cache
    res.status(200).send('No pude armar el análisis ahora: los exchanges no respondieron. Probá de nuevo en un minuto.');
    console.error('siri', e && e.stack ? e.stack : e);
  }
}
module.exports = handler;
module.exports.frases = frases;
module.exports.contexto = contexto;
