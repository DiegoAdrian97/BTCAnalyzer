/*
 * Funcion del servidor de Vercel para el widget de iPhone (Scriptable): capital total y PnL no realizado, nada mas.
 * Misma contraseña que /api/posiciones (POSICIONES_CLAVE, en el encabezado x-clave; nunca en la direccion) y las mismas
 * claves de BingX de solo lectura. Respuesta chica y sin cache: el widget la pide cada vez que iOS lo actualiza.
 */
const P = require('./posiciones.js');

module.exports = async (req, res) => {
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store, private');
  const { BINGX_API_KEY: key, BINGX_API_SECRET: secret, POSICIONES_CLAVE: clave } = process.env;
  if (!key || !secret || !clave) { res.status(503).send(JSON.stringify({ ok: false, error: 'Faltan las variables de BingX en Vercel' })); return; }
  if (!P.claveOk(req.headers['x-clave'], clave)) { res.status(401).send(JSON.stringify({ ok: false, error: 'Contraseña incorrecta' })); return; }
  try {
    const [pos, cap] = await Promise.all([P.pedir('/openApi/swap/v2/user/positions', {}, key, secret), P.capital(key, secret).catch(() => null)]);
    const ps = P.posiciones(pos), r2 = (x) => Math.round(x * 100) / 100;
    let pnl = 0, margen = 0;
    const por = Object.entries(ps).map(([m, p]) => { pnl += p.resultado || 0; margen += p.margen || 0; return [m, r2(p.resultado || 0)]; })
      .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
    res.status(200).send(JSON.stringify({ ok: true, hora: Date.now(), capital: cap ? cap.total : null, futuros: cap ? cap.futuros : null,
      otras: cap ? cap.otras : null, parcial: !cap || cap.parcial, pnl: r2(pnl), margen: r2(margen), pnl_pct: margen ? r2((pnl / margen) * 100) : null, por }));
  } catch (e) {
    res.status(502).send(JSON.stringify({ ok: false, error: String(e.message || e).slice(0, 200) }));
  }
};
