/*
 * Modo holograma: el grafico de BTC, SOL o XRP en 3D, con brillo de neon, como un holograma.
 *
 * - Ventana 3D: con "Seguir mi cabeza", la camara ve donde estas y la escena se dibuja con la perspectiva de una
 *   ventana real (proyeccion fuera de eje): el grafico parece salir de la pantalla y flotar delante.
 * - Reflejo: para una pantalla acostada con una lamina transparente a 45° encima (efecto Pepper's ghost). Fondo
 *   negro puro (en una pantalla OLED no emite luz), y la imagen se puede espejar y rotar.
 * - Manos: ver manos.js. Sin camara, se maneja con el dedo o el mouse.
 * - Datos publicos de Binance Futures (Bybit si Binance no responde). La prediccion de BTC sale del mismo analisis
 *   de la app: si el holograma esta abierto dentro de la app, se la pasa la pagina; si no, corre worker.js.
 */
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { Line2 } from 'three/addons/lines/Line2.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';
import { Manos } from './manos.js';

const $ = (s) => document.querySelector(s);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const Q = new URLSearchParams(location.search);
const EMBED = Q.has('embed');

// ---------- ajustes (quedan guardados en este navegador) ----------
const DEF = { modo: 'ventana', diag: 15.3, cabeza: false, cam: 'arriba', espejoH: true, espejoV: false, rot: 0, tema: 'holo',
  lados: true, pred: true, fx: true, asset: 'BTCUSDT', tf: '15m' };
const CFG = { ...DEF };
try { Object.assign(CFG, JSON.parse(localStorage.getItem('holo-ajustes') || '{}')); } catch (e) { /* sin almacenamiento */ }
if (Q.get('modo') === 'reflejo') { CFG.modo = 'reflejo'; CFG.diag = 6.1; }
const save = () => { try { localStorage.setItem('holo-ajustes', JSON.stringify(CFG)); } catch (e) { /* idem */ } };

const ASSETS = [{ sym: 'BTCUSDT', name: 'BTC' }, { sym: 'SOLUSDT', name: 'SOL' }, { sym: 'XRPUSDT', name: 'XRP' }];
const TFS = ['1m', '5m', '15m', '1h', '4h', '1d'];
const TF_MS = { '1m': 6e4, '5m': 3e5, '15m': 9e5, '1h': 36e5, '4h': 144e5, '1d': 864e5 };
const TF_LBL = { '1m': '1m', '5m': '5m', '15m': '15m', '1h': '1h', '4h': '4h', '1d': '1D' };
const BYBIT_TF = { '1m': '1', '5m': '5', '15m': '15', '1h': '60', '4h': '240', '1d': 'D' };
const PLAZO_TF = { '1m': '5 min', '5m': '5 min', '15m': '15 min', '1h': '1 hora', '4h': '4 horas', '1d': '1 día' };
const TEMAS = {
  holo: { up: '#19ffd1', dn: '#ff2e88', acc: '#2ad8ff', e20: '#ffe14d', e50: '#b06cff' },
  clasico: { up: '#2bff6a', dn: '#ff3b3b', acc: '#4db8ff', e20: '#ffd23f', e50: '#c77dff' },
  fuego: { up: '#ffd23f', dn: '#ff3d2e', acc: '#ff9a1f', e20: '#fff3b0', e50: '#ff6b9a' },
};
const T = () => TEMAS[CFG.tema] || TEMAS.holo;
const dec = (p) => (p >= 1000 ? 1 : p >= 10 ? 2 : 4);
const fmt = (v, d) => (v === null || v === undefined || !Number.isFinite(v) ? '—'
  : Number(v).toLocaleString('es-AR', { minimumFractionDigits: d, maximumFractionDigits: d }));
const fpct = (v) => (v > 0 ? '+' : '') + fmt(v, 2) + '%';
const nameOf = (sym) => (ASSETS.find((a) => a.sym === sym) || ASSETS[0]).name;

// ---------- datos ----------
const D = { bars: [], src: '', tick: {}, rows: null, anim: 0, loadId: 0 };
async function getJSON(url) {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(`error ${r.status}`);
  return r.json();
}
async function loadBars(sym, tf, limit = 500) {
  try {
    const rows = await getJSON(`https://fapi.binance.com/fapi/v1/klines?symbol=${sym}&interval=${tf}&limit=${limit}`);
    return { src: 'Binance', bars: rows.map((r) => [r[0], +r[1], +r[2], +r[3], +r[4], +r[5]]) };
  } catch (e) {
    const j = await getJSON(`https://api.bybit.com/v5/market/kline?category=linear&symbol=${sym}&interval=${BYBIT_TF[tf]}&limit=${Math.min(limit, 1000)}`);
    return { src: 'Bybit', bars: j.result.list.map((r) => [+r[0], +r[1], +r[2], +r[3], +r[4], +r[5]]).sort((a, b) => a[0] - b[0]) };
  }
}
async function loadTicker(sym) {
  try {
    const j = await getJSON(`https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=${sym}`);
    return { last: +j.lastPrice, pct: +j.priceChangePercent, qv: +j.quoteVolume, hi: +j.highPrice, lo: +j.lowPrice };
  } catch (e) {
    const j = (await getJSON(`https://api.bybit.com/v5/market/tickers?category=linear&symbol=${sym}`)).result.list[0];
    return { last: +j.lastPrice, pct: +j.price24hPcnt * 100, qv: +j.turnover24h, hi: +j.highPrice24h, lo: +j.lowPrice24h };
  }
}
async function refreshTickers() {
  await Promise.all(ASSETS.map(async (a) => { try { D.tick[a.sym] = await loadTicker(a.sym); } catch (e) { /* queda el anterior */ } }));
  panelsDirty = true;
}

async function setAsset(sym, announce = true) {
  CFG.asset = sym; save(); syncButtons();
  const id = ++D.loadId;
  status('Cargando ' + nameOf(sym) + '/USDT…');
  try {
    const { src, bars } = await loadBars(sym, CFG.tf);
    if (id !== D.loadId) return;
    D.bars = bars; D.src = src; D.anim = 0; V.offset = 0; dirty = true; panelsDirty = true;
    status('');
    if (announce) flash(`${nameOf(sym)}/USDT · ${TF_LBL[CFG.tf]}`);
  } catch (e) {
    if (id === D.loadId) status('No se pudieron bajar las velas: ' + e.message + '. Se reintenta solo.', true);
    setTimeout(() => { if (id === D.loadId) setAsset(sym, false); }, 5000);
    return;
  }
  connectLive(); predWorker();
}
function setTf(tf) { CFG.tf = tf; save(); setAsset(CFG.asset); }
function stepAsset(dir) { const i = ASSETS.findIndex((a) => a.sym === CFG.asset); setAsset(ASSETS[(i + dir + ASSETS.length) % ASSETS.length].sym); }
function stepTf(dir) { const i = TFS.indexOf(CFG.tf); setTf(TFS[clamp(i + dir, 0, TFS.length - 1)]); }

// precio en vivo por WebSocket (la ruta /market/ws/ es la que manda datos); si se corta, se pide cada pocos segundos
let ws = null, wsKey = '', lastMsg = 0;
function onBar(b) {
  const bars = D.bars; if (!bars.length) return;
  const last = bars[bars.length - 1];
  if (b[0] === last[0]) bars[bars.length - 1] = b;
  else if (b[0] > last[0]) { bars.push(b); if (bars.length > 800) bars.shift(); }
  else return;
  const t = D.tick[CFG.asset];
  if (t) t.last = b[4];
  dirty = true; priceDirty = true;
}
function connectLive() {
  const key = CFG.asset + CFG.tf;
  if (ws && wsKey === key) return;
  if (ws) { ws.onclose = null; try { ws.close(); } catch (e) { /* ya cerrado */ } }
  wsKey = key; lastMsg = Date.now();
  try {
    const sock = new WebSocket(`wss://fstream.binance.com/market/ws/${CFG.asset.toLowerCase()}@kline_${CFG.tf}`);
    ws = sock;
    sock.onmessage = (ev) => {
      const k = JSON.parse(ev.data).k;
      if (!k || wsKey !== key) return;
      lastMsg = Date.now();
      onBar([k.t, +k.o, +k.h, +k.l, +k.c, +k.v]);
    };
    sock.onclose = () => { if (ws === sock) { ws = null; setTimeout(() => { if (!ws) connectLive(); }, 3000); } };
  } catch (e) { ws = null; }
}
setInterval(async () => {
  if (document.hidden || !D.bars.length || Date.now() - lastMsg < 8000) return;
  try { const { bars } = await loadBars(CFG.asset, CFG.tf, 2); bars.forEach(onBar); } catch (e) { /* proximo intento */ }
}, 4000);
setInterval(() => { if (!document.hidden) refreshTickers(); }, 20000);

// la prediccion del analista (solo BTC): la manda la app si el holograma esta adentro; si no, corre su worker
let worker = null;
function predWorker() {
  const want = CFG.pred && CFG.asset === 'BTCUSDT' && !EMBED;
  if (want && !worker) {
    try {
      worker = new Worker('worker.js');
      worker.onmessage = (ev) => { if (ev.data.tipo === 'analisis') { D.rows = ev.data.rows; dirty = true; panelsDirty = true; } };
    } catch (e) { worker = null; }
  }
  if (worker) worker.postMessage({ tipo: want && !document.hidden ? 'seguir' : 'pausa' });
}
window.addEventListener('message', (ev) => {
  if (ev.origin !== location.origin || !ev.data) return;
  if (ev.data.tipo === 'analisis') { D.rows = ev.data.rows; dirty = true; panelsDirty = true; }
});

// ---------- escena ----------
const canvas = $('#gl'), hud = $('#hud'), stage = $('#stage');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
renderer.setClearColor(0x000000, 1);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(40, 1, 1, 20000);
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(512, 512), 0.8, 0.4, 0.5);
composer.addPass(bloom);
// lineas de barrido, parpadeo leve y un poco de aberracion de color: lo que hace que parezca proyectado
const holoPass = new ShaderPass({
  uniforms: { tDiffuse: { value: null }, time: { value: 0 }, lines: { value: 400 }, amount: { value: 1 } },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
  fragmentShader: `uniform sampler2D tDiffuse; uniform float time; uniform float lines; uniform float amount; varying vec2 vUv;
    void main(){
      vec2 uv = vUv; float ca = 0.0014 * amount;
      vec4 c = vec4(texture2D(tDiffuse, uv + vec2(ca, 0.0)).r, texture2D(tDiffuse, uv).g, texture2D(tDiffuse, uv - vec2(ca, 0.0)).b, 1.0);
      float scan = 0.86 + 0.14 * sin(uv.y * lines * 3.14159 + time * 4.0);
      float flick = 0.975 + 0.025 * sin(time * 47.0) * sin(time * 11.0);
      float band = 1.0 + 0.18 * amount * smoothstep(0.035, 0.0, abs(fract(uv.y * 0.7 - time * 0.09) - 0.5));
      c.rgb *= mix(1.0, scan * flick * band, amount);
      gl_FragColor = c;
    }`,
});
composer.addPass(holoPass);
composer.addPass(new OutputPass());

const lineMats = [];
function line(color, width, opts = {}) {
  const mat = new LineMaterial({ color, linewidth: width, transparent: true, opacity: opts.opacity ?? 1, dashed: !!opts.dash,
    dashSize: opts.dash || 1, gapSize: opts.gap || 0.5, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false });
  lineMats.push(mat);
  const l = new Line2(new LineGeometry(), mat);
  l.frustumCulled = false;
  l.userData.set = (pts) => {
    if (pts.length < 6) { l.visible = false; return; }
    l.visible = true;
    l.geometry.dispose(); l.geometry = new LineGeometry(); l.geometry.setPositions(pts);
    if (opts.dash) l.computeLineDistances();
  };
  return l;
}
/** Un plano con texto dibujado en un canvas (brilla porque se suma a lo de atras: lo negro no se ve). */
function textPlane(w, h, draw, ppu = 128) {
  const cw = Math.min(2048, Math.round(w * ppu)), ch = Math.min(2048, Math.round(h * ppu));
  const c = document.createElement('canvas'); c.width = cw; c.height = ch;
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
  const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false });
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), mat);
  m.userData.draw = (...args) => { const ctx = c.getContext('2d'); ctx.clearRect(0, 0, cw, ch); draw(ctx, cw, ch, ...args); tex.needsUpdate = true; };
  return m;
}
const glowText = (ctx, txt, x, y, size, color, weight = 700, align = 'left', blur = 0.12) => {
  ctx.font = `${weight} ${size}px system-ui, -apple-system, "Segoe UI", sans-serif`;
  ctx.textAlign = align; ctx.textBaseline = 'middle';
  ctx.shadowColor = color; ctx.shadowBlur = size * blur; ctx.fillStyle = color;
  ctx.fillText(txt, x, y); ctx.shadowBlur = 0;
  return ctx.measureText(txt).width;
};

// medidas del grafico (en unidades de la escena; despues se escala a la pantalla)
const CW = 16, CH = 9, VOLH = 1.5;
const root = new THREE.Group(); scene.add(root);
const chart = new THREE.Group(); root.add(chart);

// panel de vidrio, marco y esquinas
const glass = new THREE.Mesh(new THREE.PlaneGeometry(CW + 0.6, CH + 0.6), new THREE.ShaderMaterial({
  transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  uniforms: { color: { value: new THREE.Color(T().acc) } },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
  fragmentShader: `uniform vec3 color; varying vec2 vUv;
    void main(){ float e = min(min(vUv.x, 1.0 - vUv.x), min(vUv.y, 1.0 - vUv.y));
      float a = 0.012 + 0.07 * smoothstep(0.05, 0.0, e) + 0.01 * (1.0 - vUv.y);
      gl_FragColor = vec4(color * a, a); }`,
}));
glass.position.z = -0.4; chart.add(glass);
const frame = line(T().acc, 2, { opacity: 0.9 }); chart.add(frame);
function frameShape() {
  // marco redondeado alrededor del grafico
  const w = CW / 2 + 0.3, h = CH / 2 + 0.3, r = 0.45, pts = [];
  [[w - r, h - r, 0], [-w + r, h - r, 90], [-w + r, -h + r, 180], [w - r, -h + r, 270]].forEach(([cx, cy, a0]) => {
    for (let k = 0; k <= 8; k++) { const a = (a0 + k * 90 / 8) * Math.PI / 180; pts.push(cx + r * Math.cos(a), cy + r * Math.sin(a), -0.3); }
  });
  pts.push(pts[0], pts[1], pts[2]);
  frame.userData.set(pts);
}
frameShape();
// esquinas mas gruesas, cada una con su propia linea
const cornerLines = [0, 1, 2, 3].map(() => { const l = line(T().acc, 4.5); chart.add(l); return l; });
(function placeCorners() {
  const w = CW / 2 + 0.3, h = CH / 2 + 0.3, L = 1.4;
  [[-1, 1], [1, 1], [1, -1], [-1, -1]].forEach(([sx, sy], k) => cornerLines[k].userData.set([sx * w, sy * (h - L), -0.2, sx * w, sy * h, -0.2, sx * (w - L), sy * h, -0.2]));
})();

// grilla de precios
const grid = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: T().acc, transparent: true, opacity: 0.16, blending: THREE.AdditiveBlending, depthWrite: false }));
grid.frustumCulled = false; chart.add(grid);

// velas en 3D (cuerpo, mecha y volumen), y velas fantasma del escenario que espera el analista
const MAXI = 420;
const box = new THREE.BoxGeometry(1, 1, 1);
const inst = (opacity) => {
  const m = new THREE.InstancedMesh(box, new THREE.MeshBasicMaterial({ transparent: true, opacity, toneMapped: false, depthWrite: opacity > 0.9 }), MAXI);
  m.instanceMatrix.setUsage(THREE.DynamicDrawUsage); m.count = 0; m.frustumCulled = false;
  m.setColorAt(0, new THREE.Color());
  return m;
};
const bodies = inst(0.95), wicks = inst(0.95), vols = inst(0.32), gBodies = inst(0.22), gWicks = inst(0.5);
vols.material.blending = gBodies.material.blending = gWicks.material.blending = THREE.AdditiveBlending;
chart.add(vols, wicks, bodies, gWicks, gBodies);
const ema20 = line(T().e20, 2.2, { opacity: 0.95 }), ema50 = line(T().e50, 2.2, { opacity: 0.95 });
const priceLine = line(T().acc, 1.6, { dash: 0.35, gap: 0.25, opacity: 0.9 });
const coneMid = line('#ffffff', 1.8, { dash: 0.3, gap: 0.25, opacity: 0.7 });
chart.add(ema20, ema50, priceLine, coneMid);
const cone = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({ color: T().acc, transparent: true, opacity: 0.14, side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false }));
cone.frustumCulled = false; chart.add(cone);
const dot = new THREE.Mesh(new THREE.SphereGeometry(0.16, 20, 14), new THREE.MeshBasicMaterial({ color: '#ffffff', toneMapped: false }));
const halo = new THREE.Mesh(new THREE.RingGeometry(0.22, 0.32, 40), new THREE.MeshBasicMaterial({ color: T().acc, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }));
chart.add(dot, halo);
const scanBar = new THREE.Mesh(new THREE.PlaneGeometry(CW + 0.4, 0.06), new THREE.MeshBasicMaterial({ color: T().acc, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false }));
scanBar.position.z = 0.6; chart.add(scanBar);

// etiquetas: precios del eje, etiqueta del ultimo precio, fechas y la prediccion sobre el futuro
const axisLbls = Array.from({ length: 7 }, () => { const m = textPlane(2.2, 0.5, (ctx, w, h, txt) => glowText(ctx, txt, 8, h / 2, h * 0.62, '#9fe9ff', 600, 'left', 0.2)); m.visible = false; chart.add(m); return m; });
const timeLbls = Array.from({ length: 5 }, () => { const m = textPlane(2.4, 0.5, (ctx, w, h, txt) => glowText(ctx, txt, w / 2, h / 2, h * 0.58, '#9fe9ff', 600, 'center', 0.2)); m.visible = false; chart.add(m); return m; });
const priceTag = textPlane(2.5, 0.62, (ctx, w, h, txt, col) => {
  ctx.shadowColor = col; ctx.shadowBlur = h * 0.5; ctx.fillStyle = col;
  ctx.beginPath(); ctx.roundRect(4, 6, w - 8, h - 12, h * 0.22); ctx.fill(); ctx.shadowBlur = 0;
  ctx.globalCompositeOperation = 'destination-out';      // el texto queda calado: se ve el negro de atras
  ctx.font = `800 ${h * 0.56}px system-ui, sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(txt, w / 2, h / 2 + 1);
  ctx.globalCompositeOperation = 'source-over';
});
const futLbl = textPlane(5, 0.5, (ctx, w, h, txt) => glowText(ctx, txt, w - 6, h / 2, h * 0.5, '#ffffff', 700, 'right', 0.25));
chart.add(priceTag, futLbl);

// cabecera: par, precio grande y cambio
const header = textPlane(CW + 0.6, 2.3, (ctx, w, h) => {
  const t = D.tick[CFG.asset] || {}, last = D.bars.length ? D.bars[D.bars.length - 1][4] : t.last;
  const pct = t.pct ?? null, col = pct === null ? T().acc : pct >= 0 ? T().up : T().dn;
  glowText(ctx, `${nameOf(CFG.asset)}/USDT`, 10, h * 0.2, h * 0.2, T().acc, 800);
  glowText(ctx, `${TF_LBL[CFG.tf]} · ${D.src || '…'}`, w - 10, h * 0.2, h * 0.17, '#9fe9ff', 600, 'right', 0.05);
  const x = 10 + glowText(ctx, fmt(last, dec(last || 1)), 10, h * 0.64, h * 0.5, '#d8f7ff', 800, 'left', 0.05) + h * 0.2;
  if (pct !== null) glowText(ctx, `${fpct(pct)} en 24 h`, x, h * 0.68, h * 0.22, col, 800, 'left', 0.08);
});
root.add(header);

// costados: las tres criptos a la izquierda, datos e indicadores a la derecha
const tiles = ASSETS.map((a) => {
  const m = textPlane(3.6, 1.9, (ctx, w, h) => {
    const t = D.tick[a.sym] || {}, on = a.sym === CFG.asset, col = (t.pct ?? 0) >= 0 ? T().up : T().dn;
    ctx.strokeStyle = on ? T().acc : 'rgba(42,216,255,.4)'; ctx.lineWidth = on ? 5 : 3; ctx.shadowColor = T().acc; ctx.shadowBlur = on ? 12 : 0;
    ctx.fillStyle = on ? 'rgba(42,216,255,.07)' : 'rgba(42,216,255,.025)';
    ctx.beginPath(); ctx.roundRect(6, 6, w - 12, h - 12, 26); ctx.fill(); ctx.stroke(); ctx.shadowBlur = 0;
    glowText(ctx, `${a.name}/USDT`, 30, h * 0.27, h * 0.2, on ? T().acc : '#9fe9ff', 800, 'left', 0.05);
    glowText(ctx, fmt(t.last, dec(t.last || 1)), 30, h * 0.55, h * 0.26, '#f2fdff', 800, 'left', 0.08);
    if (t.pct !== undefined) glowText(ctx, fpct(t.pct), 30, h * 0.79, h * 0.18, col, 800);
  });
  m.userData.sym = a.sym;
  root.add(m);
  return m;
});
const stats = textPlane(4.0, 9.4, (ctx, w, h) => {
  ctx.strokeStyle = 'rgba(42,216,255,.5)'; ctx.lineWidth = 3; ctx.fillStyle = 'rgba(42,216,255,.05)';
  ctx.beginPath(); ctx.roundRect(6, 6, w - 12, h - 12, 26); ctx.fill(); ctx.stroke();
  const t = D.tick[CFG.asset] || {}, closes = D.bars.map((b) => b[4]), last = closes[closes.length - 1];
  const rsi = window.Ind && closes.length > 20 ? window.Ind.rsi(closes) : [];
  const e50 = window.Ind && closes.length > 50 ? window.Ind.ema(closes, 50) : [];
  const e200 = window.Ind && closes.length > 200 ? window.Ind.ema(closes, 200) : [];
  const r = rsi[rsi.length - 1], d = dec(last || 1);
  const rows = [['RSI 14', r === undefined || r === null ? '—' : fmt(r, 1), r >= 70 ? T().dn : r <= 30 ? T().up : '#cdeefa'],
    ['EMA 50', fmt(e50[e50.length - 1], d), last >= e50[e50.length - 1] ? T().up : T().dn],
    ['EMA 200', fmt(e200[e200.length - 1], d), last >= e200[e200.length - 1] ? T().up : T().dn],
    ['Máx 24 h', fmt(t.hi, d), '#cdeefa'], ['Mín 24 h', fmt(t.lo, d), '#cdeefa'],
    ['Volumen 24 h', t.qv ? `${fmt(t.qv / 1e9, 2)} mil M` : '—', '#cdeefa']];
  let y = 70;
  rows.forEach(([k, v, c]) => { glowText(ctx, k, 30, y, 34, '#7fd8f5', 600, 'left', 0.1); glowText(ctx, v, 30, y + 44, 50, c, 800, 'left', 0.08); y += 118; });
  // la prediccion del analista, si es BTC
  const p = predFor();
  if (p) {
    y += 6;
    ctx.strokeStyle = 'rgba(42,216,255,.35)'; ctx.beginPath(); ctx.moveTo(30, y - 30); ctx.lineTo(w - 30, y - 30); ctx.stroke();
    glowText(ctx, `Analista · ${p.plazo}`, 30, y, 32, T().acc, 700, 'left', 0.2);
    glowText(ctx, p.word, 30, y + 50, 52, p.col, 800, 'left', 0.12);
    glowText(ctx, p.sub, 30, y + 100, 30, '#d9f6ff', 600, 'left', 0.1);
    if (p.apr) glowText(ctx, p.apr, 30, y + 142, 28, '#7fd8f5', 600, 'left', 0.1);
  }
});
root.add(stats);

// emisor: el disco de luz de abajo y el haz que sube hasta el grafico
const fxGroup = new THREE.Group(); root.add(fxGroup);
const disc = new THREE.Mesh(new THREE.RingGeometry(1.2, 2.6, 64), new THREE.ShaderMaterial({
  transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
  uniforms: { color: { value: new THREE.Color(T().acc) }, time: { value: 0 } },
  vertexShader: 'varying vec2 vUv; varying vec3 vP; void main(){ vUv = uv; vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
  fragmentShader: `uniform vec3 color; uniform float time; varying vec3 vP;
    void main(){ float r = length(vP.xy); float a = atan(vP.y, vP.x);
      float rings = 0.55 + 0.45 * sin(r * 9.0 - time * 3.0);
      float ticks = step(0.75, fract(a * 6.0 / 3.14159 + time * 0.2));
      float alpha = (0.28 * rings + 0.35 * ticks * smoothstep(2.6, 2.2, r)) * smoothstep(1.2, 1.5, r) * smoothstep(2.6, 2.3, r);
      gl_FragColor = vec4(color * alpha * 2.0, alpha); }`,
}));
disc.rotation.x = -Math.PI / 2;
const core = new THREE.Mesh(new THREE.CircleGeometry(1.1, 48), new THREE.MeshBasicMaterial({ color: T().acc, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }));
core.rotation.x = -Math.PI / 2;
const beamH = 3.0;
const beam = new THREE.Mesh(new THREE.CylinderGeometry(CW * 0.5, 1.1, beamH, 64, 1, true), new THREE.ShaderMaterial({
  transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
  uniforms: { color: { value: new THREE.Color(T().acc) }, time: { value: 0 } },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
  fragmentShader: `uniform vec3 color; uniform float time; varying vec2 vUv;
    void main(){ float a = pow(1.0 - vUv.y, 1.6) * 0.1 + 0.01; a *= 0.75 + 0.25 * sin(vUv.x * 60.0 + time * 2.0);
      gl_FragColor = vec4(color * a, a); }`,
}));
fxGroup.add(beam, disc, core);
// particulas que suben, como polvo iluminado por el haz
const NP = 500;
const pPos = new Float32Array(NP * 3), pSpd = new Float32Array(NP);
for (let i = 0; i < NP; i++) { pPos[i * 3] = (Math.random() - 0.5) * (CW + 4); pPos[i * 3 + 1] = (Math.random() - 0.5) * (CH + 8); pPos[i * 3 + 2] = (Math.random() - 0.5) * 6; pSpd[i] = 0.2 + Math.random() * 0.6; }
const pGeo = new THREE.BufferGeometry(); pGeo.setAttribute('position', new THREE.BufferAttribute(pPos, 3));
const parts = new THREE.Points(pGeo, new THREE.PointsMaterial({ color: T().acc, size: 0.06, transparent: true, opacity: 0.45, blending: THREE.AdditiveBlending, depthWrite: false }));
parts.frustumCulled = false; root.add(parts);

function retheme() {
  const t = T();
  document.documentElement.style.setProperty('--acc', t.acc); document.documentElement.style.setProperty('--up', t.up); document.documentElement.style.setProperty('--dn', t.dn);
  [frame, ...cornerLines, priceLine].forEach((l) => l.material.color.set(t.acc));
  ema20.material.color.set(t.e20); ema50.material.color.set(t.e50);
  [grid, cone, halo, core, scanBar, parts].forEach((m) => m.material.color.set(t.acc));
  [glass, disc, beam].forEach((m) => m.material.uniforms.color.value.set(t.acc));
  dirty = true; panelsDirty = true;
}

// ---------- vista e interaccion ----------
const VDEF = { offset: 0, n: 80, yPan: 0, yZoom: 1, rotX: -0.08, rotY: 0, scale: 1 };
const V = { ...VDEF };
let dirty = true, panelsDirty = true, priceDirty = false;
const R = { lo: null, hi: null };
function act(a, remote = false) {
  if (!D.bars.length && !['asset', 'tf', 'sync'].includes(a.t)) return;
  if (a.t === 'pan') {
    V.offset = clamp(V.offset + a.dx * V.n * 1.25, 0, Math.max(0, D.bars.length - 20));
    V.yPan = clamp(V.yPan + a.dy * 1.3, -3, 3);
  } else if (a.t === 'zoom') V.n = clamp(V.n / a.f, 20, Math.min(300, D.bars.length || 300));
  else if (a.t === 'rot') { V.rotY = clamp(V.rotY + a.dx * 2.6, -1.1, 1.1); V.rotX = clamp(V.rotX + a.dy * 2.0, -0.8, 0.8); }
  else if (a.t === 'yzoom') V.yZoom = clamp(V.yZoom * a.f, 0.3, 4);
  else if (a.t === 'asset') stepAsset(a.dir);
  else if (a.t === 'tf') stepTf(a.dir);
  else if (a.t === 'reset') { Object.assign(V, VDEF); flash('Vista inicial'); }
  else if (a.t === 'sync') { if (a.tf && a.tf !== CFG.tf) CFG.tf = a.tf; if (a.asset) setAsset(a.asset); }
  dirty = true;
  if (!remote) link.send(a);
}

// ---------- armado del grafico ----------
const tmpM = new THREE.Matrix4(), tmpP = new THREE.Vector3(), tmpS = new THREE.Vector3(), Q0 = new THREE.Quaternion(), tmpC = new THREE.Color();
function predFor() {
  if (!CFG.pred || CFG.asset !== 'BTCUSDT' || !D.rows) return null;
  const name = PLAZO_TF[CFG.tf];
  const p = D.rows.find((r) => r.tabla === 'plazo' && r.plazo === name);
  const head = D.rows.find((r) => r.tabla === 'explicacion' && r.plazo === name && r.tipo === 'titular');
  const a = D.rows.find((r) => r.tabla === 'aprendizaje' && r.plazo === name);
  if (!p) return null;
  const bias = head ? head.sesgo : 'neutral', pu = p.primero_arriba;
  return { plazo: `a ${name}`, col: bias === 'alcista' ? T().up : bias === 'bajista' ? T().dn : '#ffffff',
    word: bias === 'alcista' ? `▲ Sube ${fmt(pu, 0)}%` : bias === 'bajista' ? `▼ Baja ${fmt(100 - pu, 0)}%` : '◆ Lateral',
    sub: `${fmt(p.obj_abajo, 0)} – ${fmt(p.obj_arriba, 0)} · hasta ${String(p.hora).slice(-5)} h`,
    apr: a && a.aciertos_aprendido !== null ? `Aprendido: acierta ${fmt(a.aciertos_aprendido, 1)}%` : '' };
}
function ghostsFor(lastT) {
  if (!CFG.pred || CFG.asset !== 'BTCUSDT' || !D.rows || CFG.tf === '1m') return { g: [], c: [] };
  const g = D.rows.filter((r) => r.tabla === 'escenario' && r.tf === CFG.tf && r.escenario === 'tipico').sort((a, b) => a.paso - b.paso);
  const c = D.rows.filter((r) => r.tabla === 'cono' && r.tf === CFG.tf).sort((a, b) => a.paso - b.paso);
  // el escenario sale del analisis de la ultima vela: si ya cerro otra, se corre
  const ok = g.length && g[0].t - TF_MS[CFG.tf] <= lastT + 1 && g[0].t > lastT - TF_MS[CFG.tf];
  return ok ? { g, c } : { g: [], c: [] };
}

function rebuild(dt) {
  const bars = D.bars;
  if (!bars.length) { bodies.count = wicks.count = vols.count = gBodies.count = gWicks.count = 0; return; }
  const n = Math.round(clamp(V.n, 20, Math.min(300, bars.length)));
  V.offset = clamp(V.offset, 0, bars.length - n);
  const end = bars.length - Math.round(V.offset), vis = bars.slice(end - n, end);
  const live = Math.round(V.offset) === 0;
  const { g: ghosts, c: cn } = live ? ghostsFor(vis[vis.length - 1][0]) : { g: [], c: [] };
  const slots = n + ghosts.length + (live ? 1 : 0), step = CW / slots, x0 = -CW / 2 + step / 2;
  const X = (i) => x0 + i * step;
  let lo = Infinity, hi = -Infinity;
  vis.forEach((b) => { lo = Math.min(lo, b[3]); hi = Math.max(hi, b[2]); });
  ghosts.forEach((b) => { lo = Math.min(lo, b.l); hi = Math.max(hi, b.h); });
  cn.forEach((c) => { lo = Math.min(lo, c.p10); hi = Math.max(hi, c.p90); });
  const pad = (hi - lo) * 0.07 || hi * 0.001; lo -= pad; hi += pad;
  const mid = (lo + hi) / 2, half = (hi - lo) / 2 * V.yZoom, sh = (hi - lo) * V.yPan;
  const tLo = mid - half + sh, tHi = mid + half + sh;
  R.tLo = tLo; R.tHi = tHi;
  // el rango se acomoda suave: el grafico no salta con cada tick
  const k = R.lo === null ? 1 : 1 - Math.pow(0.0015, dt);
  R.lo = R.lo === null ? tLo : R.lo + (tLo - R.lo) * k; R.hi = R.hi === null ? tHi : R.hi + (tHi - R.hi) * k;
  const yb = -CH / 2 + VOLH + 0.3, yt = CH / 2 - 0.15;
  const Y = (p) => yb + (p - R.lo) / (R.hi - R.lo || 1) * (yt - yb);
  const inY = (y) => clamp(y, yb - 0.05, yt + 0.05);
  const up = new THREE.Color(T().up), dn = new THREE.Color(T().dn), acc = new THREE.Color(T().acc);
  const bw = Math.max(0.03, step * 0.62), bd = Math.min(0.9, bw * 0.9), ww = Math.max(0.025, bw * 0.16);
  const vmax = Math.max(...vis.map((b) => b[5])) || 1;
  const grow = (i) => clamp((D.anim * 1.35 - i / n) * 5, 0, 1);       // las velas aparecen de izquierda a derecha
  vis.forEach((b, i) => {
    const [, o, h, l, c, v] = b, g = grow(i), x = X(i), isLast = live && i === n - 1;
    const col = tmpC.copy(c >= o ? up : dn).multiplyScalar(isLast ? 1.6 : 1.05);
    const y1 = inY(Y(Math.max(o, c))), y0 = inY(Y(Math.min(o, c)));
    tmpP.set(x, (y0 + y1) / 2, 0); tmpS.set(bw, Math.max(0.035, (y1 - y0)) * g + 0.0001, bd);
    bodies.setMatrixAt(i, tmpM.compose(tmpP, Q0, tmpS)); bodies.setColorAt(i, col);
    const w1 = inY(Y(h)), w0 = inY(Y(l));
    tmpP.set(x, (w0 + w1) / 2, 0); tmpS.set(ww, Math.max(0.02, w1 - w0) * g + 0.0001, ww);
    wicks.setMatrixAt(i, tmpM.compose(tmpP, Q0, tmpS)); wicks.setColorAt(i, col);
    const vh = (v / vmax) * VOLH * g;
    tmpP.set(x, -CH / 2 + vh / 2, -0.1); tmpS.set(bw, Math.max(0.01, vh), bd * 0.6);
    vols.setMatrixAt(i, tmpM.compose(tmpP, Q0, tmpS)); vols.setColorAt(i, tmpC.copy(c >= o ? up : dn));
  });
  bodies.count = wicks.count = vols.count = n;
  [bodies, wicks, vols].forEach((m) => { m.instanceMatrix.needsUpdate = true; m.instanceColor.needsUpdate = true; });
  // futuro: velas fantasma del escenario tipico y la zona donde termino el 80% de los casos parecidos
  ghosts.forEach((b, j) => {
    const x = X(n + j);
    const col = tmpC.copy(b.c >= b.o ? up : dn);
    const y1 = inY(Y(Math.max(b.o, b.c))), y0 = inY(Y(Math.min(b.o, b.c)));
    tmpP.set(x, (y0 + y1) / 2, 0); tmpS.set(bw, Math.max(0.035, y1 - y0), bd);
    gBodies.setMatrixAt(j, tmpM.compose(tmpP, Q0, tmpS)); gBodies.setColorAt(j, col);
    tmpP.set(x, (inY(Y(b.l)) + inY(Y(b.h))) / 2, 0); tmpS.set(ww, Math.max(0.02, inY(Y(b.h)) - inY(Y(b.l))), ww);
    gWicks.setMatrixAt(j, tmpM.compose(tmpP, Q0, tmpS)); gWicks.setColorAt(j, col);
  });
  gBodies.count = gWicks.count = ghosts.length;
  [gBodies, gWicks].forEach((m) => { m.instanceMatrix.needsUpdate = true; if (m.instanceColor) m.instanceColor.needsUpdate = true; });
  if (cn.length) {
    const lastX = X(n - 1), lastC = vis[n - 1][4], pos = [];
    const pts = [[lastX, Y(lastC), Y(lastC), Y(lastC)]].concat(cn.map((c, j) => [X(n + j), inY(Y(c.p10)), inY(Y(c.p90)), inY(Y(c.p50))]));
    for (let j = 0; j < pts.length - 1; j++) {
      const [xa, la, ha] = pts[j], [xb, lb, hb] = pts[j + 1];
      pos.push(xa, la, -0.2, xb, lb, -0.2, xb, hb, -0.2, xa, la, -0.2, xb, hb, -0.2, xa, ha, -0.2);
    }
    cone.geometry.dispose(); cone.geometry = new THREE.BufferGeometry(); cone.geometry.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    cone.visible = true;
    coneMid.userData.set(pts.flatMap((p) => [p[0], p[3], 0.1]));
    futLbl.visible = true; futLbl.position.set(CW / 2 - 2.4, CH / 2 - 0.4, 0.2);
    futLbl.userData.draw('FUTURO POSIBLE · ANALISTA');
  } else { cone.visible = false; coneMid.visible = false; futLbl.visible = false; }
  // medias, precio actual y grilla
  const closes = bars.map((b) => b[4]);
  const lineOf = (arr) => { const pts = []; for (let i = 0; i < n; i++) { const v = arr[end - n + i]; if (v !== null && v !== undefined) pts.push(X(i), clamp(Y(v), yb, yt), 0.15); } return pts; };
  if (window.Ind) { ema20.userData.set(lineOf(window.Ind.ema(closes, 20))); ema50.userData.set(lineOf(window.Ind.ema(closes, 50))); }
  const last = vis[n - 1], py = clamp(Y(last[4]), yb, yt);
  priceLine.userData.set([-CW / 2, py, 0.05, CW / 2 + 0.3, py, 0.05]);
  priceTag.position.set(CW / 2 + 1.55, py, 0.2);
  const tagTxt = fmt(last[4], dec(last[4]));
  if (priceTag.userData.txt !== tagTxt + T().acc) { priceTag.userData.txt = tagTxt + T().acc; priceTag.userData.draw(tagTxt, T().acc); }
  dot.position.set(X(n - 1), Y(last[4]), 0.5); halo.position.copy(dot.position); dot.visible = halo.visible = live;
  // marcas del eje de precios en numeros redondos
  const span = R.hi - R.lo, raw = span / 6, mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const unit = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((u) => u >= raw) || raw;
  const ticks = [];
  for (let v = Math.ceil(R.lo / unit) * unit; v <= R.hi && ticks.length < 7; v += unit) ticks.push(v);
  const gp = [];
  ticks.forEach((v) => { const y = Y(v); if (y < yb - 0.01 || y > yt) return; gp.push(-CW / 2, y, -0.25, CW / 2, y, -0.25); });
  grid.geometry.dispose(); grid.geometry = new THREE.BufferGeometry(); grid.geometry.setAttribute('position', new THREE.Float32BufferAttribute(gp, 3));
  axisLbls.forEach((m, j) => {
    const v = ticks[j];
    if (v === undefined || Y(v) < yb || Y(v) > yt || Math.abs(Y(v) - py) < 0.42) { m.visible = false; return; }
    m.visible = true; m.position.set(CW / 2 + 1.5, Y(v), 0.1);
    const txt = fmt(v, unit < 1 ? 4 : unit < 10 ? 2 : 0);
    if (m.userData.txt !== txt) { m.userData.txt = txt; m.userData.draw(txt); }
  });
  // fechas abajo
  const fmtT = (t) => new Date(t).toLocaleString('es-AR', CFG.tf === '1d' ? { day: '2-digit', month: '2-digit' } : { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  timeLbls.forEach((m, j) => {
    const i = Math.round((n - 1) * (j + 0.5) / timeLbls.length);
    if (!vis[i]) { m.visible = false; return; }
    m.visible = true; m.position.set(X(i), -CH / 2 - 0.55, 0.1);
    const txt = fmtT(vis[i][0]);
    if (m.userData.txt !== txt) { m.userData.txt = txt; m.userData.draw(txt); }
  });
}

// ---------- pantalla real, ojo y encuadre ----------
let SW = 33, SH = 21, popZ = 4;
const EYE = { x: 0, y: 0, z: 60 }, eyeT = { x: 0, y: 0, z: 60 };
let headSeen = 0;
function stageDims() {
  const rot = CFG.modo === 'reflejo' ? CFG.rot : 0, sideways = rot % 180 !== 0;
  return { w: sideways ? innerHeight : innerWidth, h: sideways ? innerWidth : innerHeight, rot };
}
function physical() {
  // centimetros de la pantalla a partir de su diagonal: asi la perspectiva coincide con la de una ventana real
  const { w, h } = stageDims();
  const sw = screen.width || w, sh = screen.height || h;
  const cmPerPx = (CFG.diag * 2.54) / Math.hypot(sw, sh);
  SW = w * cmPerPx; SH = h * cmPerPx;
  popZ = CFG.modo === 'ventana' ? 0.22 * Math.min(SW, SH) : 0;
  const zDef = Math.max(35, Math.hypot(SW, SH) * 1.15);
  if (!(CFG.cabeza && CFG.modo === 'ventana' && Date.now() - headSeen < 1500)) { eyeT.x = 0; eyeT.y = 0; eyeT.z = zDef; }
  return zDef;
}
function camOffset() {
  // donde esta la camara respecto del centro de la pantalla (cm), para pasar lo que ve la camara a la pantalla
  if (CFG.cam === 'abajo') return { x: 0, y: -(SH / 2 + 9) };
  if (CFG.cam === 'izquierda') return { x: -(SW / 2 + 12), y: -SH / 4 };
  if (CFG.cam === 'derecha') return { x: SW / 2 + 12, y: -SH / 4 };
  return { x: 0, y: SH / 2 + 1 };
}
const HFOV = 68 * Math.PI / 180;    // campo de vision aproximado de la camara de la MacBook
function onFace(f) {
  if (!CFG.cabeza || CFG.modo !== 'ventana') return;
  // el ancho de la cara (unos 15 cm) dice a que distancia estas; su centro, hacia donde
  const tanH = Math.tan(HFOV / 2), tanV = tanH * (f.vh / f.vw);
  const d = clamp(15 / (2 * tanH * Math.max(0.04, f.w)), 25, 400);
  const off = camOffset();
  eyeT.x = clamp((f.cx - 0.5) * 2 * tanH * d + off.x, -SW * 1.5, SW * 1.5);
  eyeT.y = clamp(-(f.cy - 0.5) * 2 * tanV * d + off.y, -SH * 1.5, SH * 1.5);
  eyeT.z = d;
  headSeen = Date.now();
}
function applyEye(dt) {
  const k = 1 - Math.pow(0.0008, dt);
  EYE.x += (eyeT.x - EYE.x) * k; EYE.y += (eyeT.y - EYE.y) * k; EYE.z += (eyeT.z - EYE.z) * k;
  const near = 1, far = 20000, z = Math.max(5, EYE.z);
  camera.position.set(EYE.x, EYE.y, z); camera.quaternion.identity(); camera.updateMatrixWorld();
  camera.projectionMatrix.makePerspective((-SW / 2 - EYE.x) * near / z, (SW / 2 - EYE.x) * near / z, (SH / 2 - EYE.y) * near / z, (-SH / 2 - EYE.y) * near / z, near, far);
  camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
}
function layout() {
  const zDef = physical();
  const wide = SW / SH > 1.25, sides = CFG.lados && wide;
  tiles.forEach((m, i) => { m.visible = sides; m.position.set(-CW / 2 - 2.6, CH / 2 - 1.1 - i * 2.2, 0.6); m.rotation.y = 0.38; });
  stats.visible = sides; stats.position.set(CW / 2 + 5.0, 0, 0.6); stats.rotation.y = -0.38;
  header.position.set(0, CH / 2 + 1.6, 0.2);
  const showFx = CFG.fx && CFG.modo === 'ventana';
  fxGroup.visible = showFx; parts.visible = CFG.fx;
  fxGroup.position.y = -CH / 2 - 0.9 - beamH; beam.position.y = beamH / 2; disc.position.y = 0.01; core.position.y = 0;
  // tamano del contenido y escala para que entre en la pantalla (lo que esta adelante de la pantalla se ve mas grande)
  const totalW = CW + 3.2 + (sides ? 2 * 4.4 + 1.2 : 0), top = CH / 2 + 2.8, bottom = CH / 2 + 1.0 + (showFx ? beamH + 0.4 : 0);
  const persp = (zDef - popZ) / zDef;
  const s = Math.min(0.9 * SW * persp / totalW, 0.88 * SH * persp / (top + bottom));
  root.userData.base = s;
  root.position.set(-1.3 * s, (bottom - top) / 2 * s, popZ);   // el eje de precios de la derecha corre el centro
  root.scale.setScalar(s * V.scale);
}
function resize() {
  const { w, h, rot } = stageDims();
  stage.style.width = w + 'px'; stage.style.height = h + 'px';
  const sx = CFG.modo === 'reflejo' && CFG.espejoH ? -1 : 1, sy = CFG.modo === 'reflejo' && CFG.espejoV ? -1 : 1;
  stage.style.transform = `translate(-50%, -50%) rotate(${rot}deg) scale(${sx}, ${sy})`;
  const big = w * h * (devicePixelRatio || 1) ** 2 > 5e6;
  const dpr = Math.min(devicePixelRatio || 1, big ? 1.25 : 2);
  renderer.setPixelRatio(dpr); renderer.setSize(w, h, false);
  composer.setPixelRatio(dpr); composer.setSize(w, h);
  bloom.resolution.set(w * dpr * 0.5, h * dpr * 0.5);
  holoPass.uniforms.lines.value = h * dpr / 3;
  lineMats.forEach((m) => m.resolution.set(w * dpr, h * dpr));
  hud.width = w * dpr; hud.height = h * dpr;
  layout(); dirty = true;
}
window.addEventListener('resize', resize);

// ---------- cuadro por cuadro ----------
let lastT = performance.now(), panelT = 0;
function frameLoop(now) {
  requestAnimationFrame(frameLoop);
  if (document.hidden) return;
  const real = (now - lastT) / 1000, dt = Math.min(0.1, real); lastT = now;
  const t = now / 1000;
  if (D.anim < 1) { D.anim = Math.min(1, D.anim + real * 0.9); dirty = true; }
  if (dirty || rangeMoving()) { dirty = false; rebuild(dt); }
  if ((panelsDirty || priceDirty) && now - panelT > 250) {
    panelT = now; header.userData.draw();
    if (panelsDirty) { tiles.forEach((m) => m.userData.draw()); stats.userData.draw(); }
    panelsDirty = priceDirty = false;
  }
  // el holograma respira: flota y se mece un poco
  const idle = CFG.modo === 'ventana' ? Math.sin(t * 0.35) * 0.06 : 0;
  root.rotation.x += (V.rotX - root.rotation.x) * Math.min(1, dt * 6);
  root.rotation.y += (V.rotY + idle - root.rotation.y) * Math.min(1, dt * 6);
  const base = root.userData.base || 1;
  root.scale.setScalar(base * V.scale);
  chart.position.y = Math.sin(t * 0.8) * 0.06;
  scanBar.position.y = -CH / 2 + ((t * 0.25) % 1) * CH;
  scanBar.material.opacity = 0.35 + 0.25 * Math.sin(t * 3);
  halo.scale.setScalar(1 + 0.35 * (0.5 + 0.5 * Math.sin(t * 4)));
  halo.material.opacity = 0.5 + 0.4 * Math.sin(t * 4);
  disc.material.uniforms.time.value = t; beam.material.uniforms.time.value = t; disc.rotation.z = t * 0.3;
  core.material.opacity = 0.4 + 0.2 * Math.sin(t * 2.2);
  if (parts.visible) {
    for (let i = 0; i < NP; i++) {
      pPos[i * 3 + 1] += pSpd[i] * dt;
      if (pPos[i * 3 + 1] > CH / 2 + 3) pPos[i * 3 + 1] = -CH / 2 - 4;
    }
    pGeo.attributes.position.needsUpdate = true;
  }
  holoPass.uniforms.time.value = t;
  applyEye(dt);
  composer.render(dt);
  drawHud(now);
}
function rangeMoving() {
  if (R.lo === null || R.tLo === undefined) return false;
  const eps = (R.tHi - R.tLo) * 1e-4;
  return Math.abs(R.lo - R.tLo) > eps || Math.abs(R.hi - R.tHi) > eps;
}

// ---------- manos en pantalla (HUD) ----------
let cursors = [], remoteCursors = [], holdP = 0;
function drawHud() {
  const ctx = hud.getContext('2d'), w = hud.width, h = hud.height;
  ctx.clearRect(0, 0, w, h);
  const list = cursors.concat(remoteCursors);
  if (!list.length) return;
  const acc = T().acc;
  ctx.lineCap = 'round';
  list.forEach((c) => {
    if (c.pts) {
      ctx.strokeStyle = acc; ctx.globalAlpha = 0.45; ctx.lineWidth = Math.max(2, w / 600);
      [[0, 1, 2, 3, 4], [0, 5, 6, 7, 8], [5, 9, 10, 11, 12], [9, 13, 14, 15, 16], [13, 17, 18, 19, 20], [0, 17]].forEach((ch) => {
        ctx.beginPath(); ch.forEach((k, i) => { const p = c.pts[k]; if (i) ctx.lineTo(p.x * w, p.y * h); else ctx.moveTo(p.x * w, p.y * h); }); ctx.stroke();
      });
      ctx.globalAlpha = 1;
    }
    const x = c.x * w, y = c.y * h, r = Math.max(10, w / 70) * (c.state === 'pinch' ? 0.7 : 1);
    ctx.shadowColor = acc; ctx.shadowBlur = 20;
    ctx.strokeStyle = c.state === 'pinch' ? '#ffffff' : acc; ctx.lineWidth = Math.max(3, w / 400);
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.stroke();
    if (c.state === 'pinch' || c.state === 'fist') { ctx.fillStyle = c.state === 'pinch' ? acc : T().e50; ctx.beginPath(); ctx.arc(x, y, r * 0.45, 0, Math.PI * 2); ctx.fill(); }
    if (c.state === 'open' && holdP > 0) {
      ctx.strokeStyle = '#ffffff'; ctx.beginPath(); ctx.arc(x, y, r * 1.8, -Math.PI / 2, -Math.PI / 2 + holdP * Math.PI * 2); ctx.stroke();
    }
    ctx.shadowBlur = 0;
  });
}

// ---------- camara y gestos ----------
const video = $('#cam');
const manos = new Manos({
  video,
  onAction: (a) => act(a),
  onCursor: (list) => { cursors = list; link.send({ t: 'cursor', list: list.map((c) => ({ x: c.x, y: c.y, state: c.state })) }); },
  onHold: (p) => { holdP = p; },
  onFace,
  onState: (txt, err) => status(txt, err),
});
async function toggleManos(on) {
  const btn = $('#b-manos');
  if (on) {
    btn.setAttribute('aria-pressed', 'true');
    try {
      await manos.start({ cara: CFG.cabeza && CFG.modo === 'ventana' });
      video.hidden = false;
      if (!sessionStorage.getItem('holo-ayuda')) { openSheet('ayuda'); sessionStorage.setItem('holo-ayuda', '1'); }
    } catch (e) {
      btn.setAttribute('aria-pressed', 'false'); video.hidden = true;
      status('No se pudo usar la cámara: ' + (e && e.message ? e.message : e), true);
    }
  } else { manos.stop(); video.hidden = true; cursors = []; btn.setAttribute('aria-pressed', 'false'); status(''); }
}

// ---------- dedo y mouse (sin camara) ----------
(function pointer() {
  const pts = new Map();
  let pinch = null, lastTap = 0;
  const sign = () => ({ x: CFG.modo === 'reflejo' && CFG.espejoH ? -1 : 1, y: CFG.modo === 'reflejo' && CFG.espejoV ? -1 : 1 });
  stage.addEventListener('pointerdown', (e) => {
    stage.setPointerCapture(e.pointerId);
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY, b: e.button, shift: e.shiftKey });
    if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2 }; }
    const now = Date.now();
    if (pts.size === 1 && now - lastTap < 300) act({ t: 'reset' });
    lastTap = now;
    wake();
  });
  stage.addEventListener('pointermove', (e) => {
    const p = pts.get(e.pointerId); if (!p) return;
    const dx = (e.clientX - p.x) / innerWidth, dy = (e.clientY - p.y) / innerHeight, s = sign();
    p.x = e.clientX; p.y = e.clientY;
    if (pts.size === 2 && pinch) {
      const [a, b] = [...pts.values()], d = Math.hypot(a.x - b.x, a.y - b.y), cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2;
      if (pinch.d > 20) act({ t: 'zoom', f: d / pinch.d });
      act({ t: 'rot', dx: ((cx - pinch.cx) / innerWidth) * s.x, dy: ((cy - pinch.cy) / innerHeight) * s.y });
      pinch = { d, cx, cy };
      return;
    }
    if (p.b === 2 || p.shift) act({ t: 'rot', dx: dx * s.x, dy: dy * s.y });
    else act({ t: 'pan', dx: dx * s.x, dy: dy * s.y });
  });
  const up = (e) => { pts.delete(e.pointerId); if (pts.size < 2) pinch = null; };
  stage.addEventListener('pointerup', up); stage.addEventListener('pointercancel', up);
  stage.addEventListener('contextmenu', (e) => e.preventDefault());
  stage.addEventListener('wheel', (e) => { e.preventDefault(); act({ t: 'zoom', f: e.deltaY > 0 ? 1 / 1.1 : 1.1 }); }, { passive: false });
  document.addEventListener('keydown', (e) => {
    const k = e.key;
    if (k === 'ArrowLeft') act({ t: 'pan', dx: 0.05, dy: 0 }); else if (k === 'ArrowRight') act({ t: 'pan', dx: -0.05, dy: 0 });
    else if (k === '+' || k === '=') act({ t: 'zoom', f: 1.2 }); else if (k === '-') act({ t: 'zoom', f: 1 / 1.2 });
    else if (k === 'r' || k === 'R') act({ t: 'reset' }); else if (k === 'Escape') closeSheets();
  });
})();

// ---------- enlace Mac -> iPhone (PeerJS: conexion directa entre los dos navegadores) ----------
const link = {
  conn: null, peer: null, lastCursor: 0,
  send(m) {
    if (!this.conn || !this.conn.open) return;
    if (m.t === 'cursor') { const now = Date.now(); if (now - this.lastCursor < 33) return; this.lastCursor = now; }
    try { this.conn.send(m); } catch (e) { /* conexion caida */ }
  },
};
const loadScript = (src) => new Promise((res, rej) => { const s = document.createElement('script'); s.src = src; s.onload = res; s.onerror = () => rej(new Error('no cargó ' + src)); document.head.append(s); });
const PEER = 'https://unpkg.com/peerjs@1.5.5/dist/peerjs.min.js';
const QR = 'https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.js';
const peerId = (code) => `analista-btc-holo-${code}`;
async function hostLink() {
  // la compu: muestra el codigo y se conecta al iPhone cuando abre el enlace
  openSheet('enlace');
  const code = Array.from({ length: 4 }, () => 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'[Math.floor(Math.random() * 31)]).join('');
  $('#code').textContent = code;
  const url = `${location.origin}${location.pathname.replace(/index\.html$/, '')}${location.pathname.endsWith('holograma.html') ? '' : 'holograma.html'}?modo=reflejo&par=${code}`;
  try {
    await Promise.all([window.qrcode ? null : loadScript(QR), window.Peer ? null : loadScript(PEER)]);
    const qr = window.qrcode(0, 'M'); qr.addData(url); qr.make(); $('#qr').innerHTML = qr.createSvgTag({ cellSize: 6, margin: 2, scalable: true });
  } catch (e) { $('#enlace-estado').textContent = 'No se pudo preparar el enlace (sin internet).'; return; }
  if (link.peer) link.peer.destroy();
  const peer = new window.Peer(); link.peer = peer;
  const tryConnect = () => {
    if (link.conn && link.conn.open) return;
    const c = peer.connect(peerId(code), { reliable: false });
    c.on('open', () => {
      link.conn = c; $('#enlace-estado').textContent = '✓ iPhone enlazado: tus manos mueven el gráfico del iPhone.';
      status('iPhone enlazado'); setTimeout(() => status(''), 3000);
      c.send({ t: 'sync', asset: CFG.asset, tf: CFG.tf });
      setTimeout(closeSheets, 1500);
    });
    c.on('close', () => { link.conn = null; status('Se cortó el enlace con el iPhone', true); });
  };
  peer.on('open', () => { tryConnect(); const iv = setInterval(() => { if (link.conn && link.conn.open) clearInterval(iv); else tryConnect(); }, 3000); });
  peer.on('error', (e) => { if (e.type !== 'peer-unavailable') $('#enlace-estado').textContent = 'Error del enlace: ' + e.type; });
}
async function joinLink(code) {
  // el iPhone: espera la conexion de la compu con el codigo del QR
  try { if (!window.Peer) await loadScript(PEER); } catch (e) { status('No se pudo enlazar (sin internet)', true); return; }
  const peer = new window.Peer(peerId(code)); link.peer = peer;
  status('Esperando a la compu… código ' + code);
  peer.on('connection', (c) => {
    c.on('open', () => { link.conn = c; status('✓ Enlazado con la compu'); setTimeout(() => status(''), 3000); });
    c.on('data', (m) => { if (m.t === 'cursor') remoteCursors = m.list; else act(m, true); });
    c.on('close', () => { remoteCursors = []; status('Se cortó el enlace con la compu', true); });
  });
  peer.on('error', (e) => status('Error del enlace: ' + e.type, true));
}

// ---------- interfaz ----------
let statusT = null;
function status(txt, err = false) {
  const el = $('#status'); el.classList.toggle('err', !!err);
  if (!txt) { el.replaceChildren(); return; }
  const i = document.createElement('i'); el.replaceChildren(i, txt);
  clearTimeout(statusT); if (!err) statusT = setTimeout(() => { if (el.textContent === txt) el.replaceChildren(); }, 6000);
}
let flashT = null;
function flash(txt) { const f = $('#flash'); f.textContent = txt; f.classList.add('on'); clearTimeout(flashT); flashT = setTimeout(() => f.classList.remove('on'), 1300); }
function seg(el, items, key, onPick) {
  el.replaceChildren(...items.map(([v, t]) => { const b = document.createElement('button'); b.type = 'button'; b.dataset.v = v; b.textContent = t; b.addEventListener('click', () => onPick(v)); return b; }));
}
seg($('#assets'), ASSETS.map((a) => [a.sym, a.name]), 'asset', (v) => { setAsset(v); link.send({ t: 'sync', asset: v, tf: CFG.tf }); });
seg($('#tfs'), TFS.map((t) => [t, TF_LBL[t]]), 'tf', (v) => { setTf(v); link.send({ t: 'sync', asset: CFG.asset, tf: v }); });
function syncButtons() {
  document.querySelectorAll('#assets button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === CFG.asset)));
  document.querySelectorAll('#tfs button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === CFG.tf)));
  document.querySelectorAll('#modos button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.modo === CFG.modo)));
  document.querySelectorAll('#temas button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.tema === CFG.tema)));
  $('#s-diag').value = String(CFG.diag); $('#s-cam').value = CFG.cam; $('#s-cabeza').checked = CFG.cabeza;
  $('#s-lados').checked = CFG.lados; $('#s-pred').checked = CFG.pred; $('#s-fx').checked = CFG.fx;
  $('#s-espejo-h').setAttribute('aria-pressed', String(CFG.espejoH)); $('#s-espejo-v').setAttribute('aria-pressed', String(CFG.espejoV));
  holoPass.uniforms.amount.value = CFG.modo === 'reflejo' ? 0.5 : 1;
}
function openSheet(id) { closeSheets(); $('#' + id).hidden = false; wake(true); }
function closeSheets() { document.querySelectorAll('.sheet').forEach((s) => { s.hidden = true; }); }
document.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', closeSheets));
$('#b-ayuda').addEventListener('click', () => openSheet('ayuda'));
$('#b-ajustes').addEventListener('click', () => openSheet('ajustes'));
$('#b-manos').addEventListener('click', () => toggleManos($('#b-manos').getAttribute('aria-pressed') !== 'true'));
$('#b-fs').addEventListener('click', () => {
  try { if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen().catch(() => status('Para pantalla completa en el iPhone: Compartir → Agregar a inicio')); }
  catch (e) { status('Para pantalla completa en el iPhone: Compartir → Agregar a inicio'); }
});
$('#b-enlazar').addEventListener('click', hostLink);
const change = (fn) => () => { fn(); save(); syncButtons(); resize(); };
document.querySelectorAll('#modos button').forEach((b) => b.addEventListener('click', change(() => { CFG.modo = b.dataset.modo; if (manos.running) manos.setFace(CFG.cabeza && CFG.modo === 'ventana'); })));
document.querySelectorAll('#temas button').forEach((b) => b.addEventListener('click', change(() => { CFG.tema = b.dataset.tema; retheme(); })));
$('#s-diag').addEventListener('change', change(() => { CFG.diag = Number($('#s-diag').value); }));
$('#s-cam').addEventListener('change', change(() => { CFG.cam = $('#s-cam').value; }));
$('#s-cabeza').addEventListener('change', change(async () => {
  CFG.cabeza = $('#s-cabeza').checked;
  if (CFG.cabeza && !manos.running) await toggleManos(true);
  else if (manos.running) manos.setFace(CFG.cabeza && CFG.modo === 'ventana');
}));
$('#s-lados').addEventListener('change', change(() => { CFG.lados = $('#s-lados').checked; }));
$('#s-pred').addEventListener('change', change(() => { CFG.pred = $('#s-pred').checked; predWorker(); dirty = true; panelsDirty = true; }));
$('#s-fx').addEventListener('change', change(() => { CFG.fx = $('#s-fx').checked; }));
$('#s-espejo-h').addEventListener('click', change(() => { CFG.espejoH = !CFG.espejoH; }));
$('#s-espejo-v').addEventListener('click', change(() => { CFG.espejoV = !CFG.espejoV; }));
$('#s-rot').addEventListener('click', change(() => { CFG.rot = (CFG.rot + 90) % 360; }));

// interruptor Web | Holograma: adentro de la app cierra la capa; suelto, vuelve a la pagina principal
document.querySelectorAll('#modo-app button').forEach((b) => b.addEventListener('click', () => {
  if (b.dataset.app !== 'web') return;
  try { localStorage.setItem('app-modo', 'web'); } catch (e) { /* idem */ }
  manos.stop();
  if (EMBED && window.parent !== window) window.parent.postMessage({ tipo: 'holo-salir' }, location.origin);
  else location.href = './';
}));

// la barra se esconde sola a los pocos segundos; se vuelve a ver al tocar o mover el mouse
let idleT = null;
function wake(stay = false) {
  document.body.classList.remove('idle'); clearTimeout(idleT);
  if (!stay) idleT = setTimeout(() => { if (document.querySelectorAll('.sheet:not([hidden])').length === 0) document.body.classList.add('idle'); }, 4500);
}
['pointermove', 'pointerdown', 'keydown'].forEach((ev) => document.addEventListener(ev, () => wake(), { passive: true }));
document.addEventListener('visibilitychange', () => { predWorker(); if (!document.hidden) { refreshTickers(); connectLive(); } });

// ---------- arranque ----------
retheme(); syncButtons(); resize(); wake();
requestAnimationFrame(frameLoop);
refreshTickers();
setAsset(CFG.asset, false);
if (Q.get('par')) joinLink(Q.get('par').toUpperCase());
if (EMBED && window.parent !== window) window.parent.postMessage({ tipo: 'holo-listo' }, location.origin);
window.__holo = { act, D, V, CFG, onFace, setCursors: (l) => { cursors = l; } };   // para probar
