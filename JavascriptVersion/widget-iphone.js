// Analista BTC: widget para iPhone (app Scriptable, gratis).
// Muestra tu capital total y el PnL no realizado de tus posiciones de BingX, en la pantalla de inicio o en la de bloqueo.
//
// Como se usa (tambien esta en la app, en "Mis posiciones"):
//   1. En Scriptable: + (script nuevo), pegar este codigo y llamarlo "Analista BTC".
//   2. Tocar ▶ una vez: pide la contraseña de BingX (la misma de la app, POSICIONES_CLAVE) y la guarda en el llavero
//      del iPhone. No queda en este archivo ni viaja en la direccion: va en un encabezado, como en la app.
//   3. Pantalla de inicio o de bloqueo: mantener apretado → Editar → + → Scriptable → elegir "Analista BTC".
//      En "Parameter": capital (capital grande), pnl (PnL grande) o vacio (los dos).
// iOS decide cuando actualizarlo (en general cada 5 a 15 minutos): no es al segundo como la app. Tocarlo abre la app.

const APP = 'https://btcanalyzerjs.vercel.app';
const LLAVE = 'analista-btc-clave';
const C = { fondo: new Color('#0d1626'), tinta: new Color('#e8eef7'), apagado: new Color('#8fa0bb'), sube: new Color('#22ab94'),
  baja: new Color('#f7525f'), linea: new Color('#22324d') };
const fm = FileManager.local();
const GUARDADO = fm.joinPath(fm.documentsDirectory(), 'analista-btc-widget.json');

// 12.345,67 (y − de verdad para los negativos)
function num(x, d = 2) {
  const [e, f] = Math.abs(x).toFixed(d).split('.');
  return `${x < 0 ? '−' : ''}${e.replace(/\B(?=(\d{3})+(?!\d))/g, '.')}${f ? `,${f}` : ''}`;
}
const conSigno = (x, d = 2) => `${x >= 0 ? '+' : ''}${num(x, d)}`;

async function clave() {
  if (Keychain.contains(LLAVE)) return Keychain.get(LLAVE);
  if (config.runsInWidget) return null;
  const a = new Alert();
  a.title = 'Analista BTC';
  a.message = 'Contraseña de BingX: la misma que pusiste en la app (POSICIONES_CLAVE). Queda en el llavero del iPhone.';
  a.addSecureTextField('Contraseña');
  a.addAction('Guardar');
  a.addCancelAction('Cancelar');
  if ((await a.presentAlert()) === -1) return null;
  const c = a.textFieldValue(0).trim();
  if (c) Keychain.set(LLAVE, c);
  return c || null;
}

async function leer() {
  const c = await clave();
  if (!c) return { error: 'Abrí Scriptable y tocá ▶ en "Analista BTC" para poner la contraseña.' };
  try {
    const r = new Request(`${APP}/api/widget`);
    r.headers = { 'x-clave': c };
    r.timeoutInterval = 20;
    const j = await r.loadJSON();
    if (r.response.statusCode === 401) {
      Keychain.remove(LLAVE);
      return { error: 'Contraseña incorrecta: abrí Scriptable y tocá ▶ para ponerla de nuevo.' };
    }
    if (!j.ok) throw new Error(j.error || `error ${r.response.statusCode}`);
    fm.writeString(GUARDADO, JSON.stringify(j));
    return { j };
  } catch (e) {
    // sin conexion o BingX caido: el ultimo dato, avisando que es viejo
    const viejo = fm.fileExists(GUARDADO) ? JSON.parse(fm.readString(GUARDADO)) : null;
    return { j: viejo, viejo: true, error: viejo ? null : `Sin datos: ${e.message}` };
  }
}

function texto(st, t, fuente, color, escala = 0.5) {
  const x = st.addText(t);
  x.font = fuente; x.textColor = color; x.minimumScaleFactor = escala; x.lineLimit = 1;
  return x;
}

function hora(st, j, viejo, fuente) {
  const fila = st.addStack(); fila.centerAlignContent();
  texto(fila, viejo ? '⚠ sin conexión · ' : '', fuente, viejo ? C.baja : C.apagado);
  const d = fila.addDate(new Date(j.hora)); d.applyRelativeStyle(); d.font = fuente; d.textColor = C.apagado; d.lineLimit = 1;
}

function armar({ j, viejo, error }, fam, modo) {
  const w = new ListWidget();
  w.url = APP;
  w.refreshAfterDate = new Date(Date.now() + 5 * 60 * 1000);   // pedido: cada 5 min (iOS puede estirarlo)
  const bloqueo = fam.startsWith('accessory');
  if (!bloqueo) { w.backgroundColor = C.fondo; w.setPadding(14, 14, 12, 14); }
  if (!j) { texto(w, error || 'Sin datos', Font.mediumSystemFont(bloqueo ? 12 : 13), bloqueo ? Color.white() : C.tinta, 0.6).lineLimit = 4; return w; }
  const pnlCol = j.pnl >= 0 ? C.sube : C.baja;
  const pnlTxt = `${conSigno(j.pnl)}${j.pnl_pct === null || j.pnl_pct === undefined ? '' : ` (${conSigno(j.pnl_pct, 1)}%)`}`;
  const capTxt = j.capital === null || j.capital === undefined ? '—' : num(j.capital, 0);

  if (fam === 'accessoryInline') { w.addText(`PnL ${conSigno(j.pnl, 0)} · ${capTxt} USDT`); return w; }
  if (fam === 'accessoryCircular') {
    w.addSpacer();
    const a = w.addText('PnL'); a.font = Font.mediumSystemFont(10); a.centerAlignText();
    const b = w.addText(j.pnl_pct === null ? conSigno(j.pnl, 0) : `${conSigno(j.pnl_pct, 0)}%`);
    b.font = Font.boldRoundedSystemFont(15); b.minimumScaleFactor = 0.5; b.centerAlignText();
    w.addSpacer(); return w;
  }
  if (fam === 'accessoryRectangular') {
    const t = w.addText(`Capital ${capTxt}`); t.font = Font.boldRoundedSystemFont(15); t.minimumScaleFactor = 0.6;
    const p = w.addText(`PnL ${pnlTxt}`); p.font = Font.semiboldSystemFont(13); p.minimumScaleFactor = 0.6;
    const h = w.addDate(new Date(j.hora)); h.applyRelativeStyle(); h.font = Font.systemFont(11);
    return w;
  }

  const grande = modo === 'pnl'
    ? { k: 'PnL no realizado', v: conSigno(j.pnl), col: pnlCol, sub: [`${j.pnl_pct === null ? '' : `${conSigno(j.pnl_pct, 1)}% · `}capital ${capTxt}`, C.apagado] }
    : { k: j.parcial ? 'Capital total (parcial)' : 'Capital total', v: capTxt, col: C.tinta, sub: [`PnL ${pnlTxt}`, pnlCol] };
  const izq = fam === 'small' ? w : w.addStack();
  if (fam !== 'small') { izq.layoutHorizontally(); izq.topAlignContent(); }
  const col1 = fam === 'small' ? w : izq.addStack();
  if (fam !== 'small') col1.layoutVertically();
  texto(col1, grande.k, Font.mediumSystemFont(12), C.apagado);
  col1.addSpacer(2);
  texto(col1, grande.v, Font.heavyRoundedSystemFont(fam === 'small' ? 30 : 34), grande.col, 0.4);
  texto(col1, 'USDT', Font.semiboldSystemFont(11), C.apagado);
  col1.addSpacer(6);
  texto(col1, grande.sub[0], Font.semiboldSystemFont(13), grande.sub[1], 0.6);

  if (fam !== 'small' && Array.isArray(j.por) && j.por.length) {
    izq.addSpacer();
    const col2 = izq.addStack(); col2.layoutVertically();
    texto(col2, 'Por moneda', Font.mediumSystemFont(12), C.apagado);
    col2.addSpacer(4);
    j.por.slice(0, fam === 'medium' ? 4 : 8).forEach(([m, r]) => {
      const f = col2.addStack(); f.size = new Size(130, 0);
      texto(f, m, Font.semiboldSystemFont(13), C.tinta);
      f.addSpacer();
      texto(f, conSigno(r, 0), Font.semiboldMonospacedSystemFont(13), r >= 0 ? C.sube : C.baja);
    });
  }
  w.addSpacer();
  hora(w, j, viejo, Font.systemFont(11));
  return w;
}

const modo = String(args.widgetParameter || '').trim().toLowerCase();
const familia = config.widgetFamily || 'medium';
const w = armar(await leer(), familia, modo);
if (config.runsInWidget || config.runsInAccessoryWidget) Script.setWidget(w);
else await w.presentMedium();
Script.complete();
