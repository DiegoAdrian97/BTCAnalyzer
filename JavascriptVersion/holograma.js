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
  lados: true, pred: true, fx: true, asset: 'BTCUSDT', tf: '15m', brillo: 0, barrido: false, vista: 'frente', v: 2 };
const CFG = { ...DEF };
try { Object.assign(CFG, JSON.parse(localStorage.getItem('holo-ajustes') || '{}')); } catch (e) { /* sin almacenamiento */ }
if (CFG.v !== 2) Object.assign(CFG, { brillo: 0, barrido: false, v: 2 });   // los ajustes viejos tenian brillo: ahora arranca nitido
if (Q.get('modo') === 'reflejo') { CFG.modo = 'reflejo'; CFG.diag = 6.1; }
const save = () => { try { localStorage.setItem('holo-ajustes', JSON.stringify(CFG)); } catch (e) { /* idem */ } };

const ASSETS = [{ sym: 'BTCUSDT', name: 'BTC' }, { sym: 'SOLUSDT', name: 'SOL' }, { sym: 'XRPUSDT', name: 'XRP' }, { sym: 'ZECUSDT', name: 'ZEC' }];
const TFS = ['1m', '5m', '15m', '1h', '4h', '1d'];
const TF_MS = { '1m': 6e4, '5m': 3e5, '15m': 9e5, '1h': 36e5, '4h': 144e5, '1d': 864e5 };
const TF_LBL = { '1m': '1m', '5m': '5m', '15m': '15m', '1h': '1h', '4h': '4h', '1d': '1D' };
const BYBIT_TF = { '1m': '1', '5m': '5', '15m': '15', '1h': '60', '4h': '240', '1d': 'D' };
const PLAZO_TF = { '1m': '5 min', '5m': '5 min', '15m': '15 min', '1h': '1 hora', '4h': '4 horas', '1d': '1 día' };
const TEMAS = {
  holo: { up: '#19ffd1', dn: '#ff2e88', acc: '#2ad8ff', e20: '#ffe14d', e50: '#b06cff' },
  clasico: { up: '#2bff6a', dn: '#ff3b3b', acc: '#4db8ff', e20: '#ffd23f', e50: '#c77dff' },
  fuego: { up: '#ffd23f', dn: '#ff3d2e', acc: '#ff9a1f', e20: '#fff3b0', e50: '#ff6b9a' },
  naranja: { up: '#4fd8ff', dn: '#ff9f43', acc: '#3aa8ff', e20: '#ffb15c', e50: '#7fe3ff' },
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

/**
 * Cambia de cripto o de temporalidad. Con `turn` ({ axis: 'y' | 'x', dir }) el grafico gira como un cubo de vidrio:
 * de costado para la cripto, hacia arriba o abajo para la temporalidad. Los datos nuevos se bajan antes de girar y
 * se ponen en la cara que entra, a mitad de giro.
 */
async function load(sym, tf, announce = true, turn = null) {
  const id = ++D.loadId;
  status(`Cargando ${nameOf(sym)}/USDT · ${TF_LBL[tf]}…`);
  let got;
  try { got = await loadBars(sym, tf); } catch (e) {
    if (id === D.loadId) status('No se pudieron bajar las velas: ' + e.message + '. Se reintenta solo.', true);
    setTimeout(() => { if (id === D.loadId) load(sym, tf, false); }, 5000);
    return;
  }
  if (id !== D.loadId) return;
  status('');
  const apply = () => {
    CFG.asset = sym; CFG.tf = tf; save(); syncButtons();
    D.bars = got.bars; D.src = got.src; D.anim = 0; V.offset = 0; VS.offset = 0; V.manual = null; R.lo = R.hi = null; PIN = null;
    dirty = true; panelsDirty = true;
    if (announce) flash(`${nameOf(sym)}/USDT · ${TF_LBL[tf]}`);
    connectLive(); predWorker();
  };
  if (turn && D.bars.length && !document.hidden) startTurn(turn, apply); else apply();
}
function setAsset(sym, announce = true, turn = null) { return load(sym, CFG.tf, announce, turn); }
function setTf(tf, turn = null) { return load(CFG.asset, tf, true, turn); }
function stepAsset(dir) {
  const i = ASSETS.findIndex((a) => a.sym === CFG.asset);
  setAsset(ASSETS[(i + dir + ASSETS.length) % ASSETS.length].sym, true, { axis: 'y', dir });
}
function stepTf(dir) {
  const i = TFS.indexOf(CFG.tf), j = clamp(i + dir, 0, TFS.length - 1);
  if (j !== i) setTf(TFS[j], { axis: 'x', dir });
}

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
// el brillo (bloom) se calcula aparte y solo con lo que esta en la capa GLOW: velas, lineas, marco y luces.
// Los textos y numeros no brillan: quedan nitidos.
const GLOW = 1;
const glowOn = (...objs) => objs.forEach((o) => o.layers.enable(GLOW));
const bloomComposer = new EffectComposer(renderer, new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType }));
bloomComposer.renderToScreen = false;
bloomComposer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(512, 512), 0.8, 0.35, 0.0);
bloomComposer.addPass(bloom);
// la imagen final: la escena con antialiasing 4x (MSAA), mas el brillo encima
const composer = new EffectComposer(renderer, new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: 4 }));
composer.addPass(new RenderPass(scene, camera));
const mixPass = new ShaderPass({
  uniforms: { tDiffuse: { value: null }, bloomTex: { value: null } },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
  // la cola del brillo (lo muy tenue que se desparrama por el fondo) se corta: el fondo queda negro puro
  fragmentShader: `uniform sampler2D tDiffuse; uniform sampler2D bloomTex; varying vec2 vUv;
    void main(){ vec3 b = max(texture2D(bloomTex, vUv).rgb - vec3(0.012), vec3(0.0)) * 1.15;
      vec4 c = texture2D(tDiffuse, vUv); c.rgb += b; c.rgb = max(c.rgb - vec3(0.0015), vec3(0.0)); gl_FragColor = c; }`,
});
composer.addPass(mixPass);
// lineas de barrido y un parpadeo muy leve: lo que hace que parezca proyectado, sin desenfocar
const holoPass = new ShaderPass({
  uniforms: { tDiffuse: { value: null }, time: { value: 0 }, lines: { value: 400 }, amount: { value: 1 } },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
  fragmentShader: `uniform sampler2D tDiffuse; uniform float time; uniform float lines; uniform float amount; varying vec2 vUv;
    void main(){
      vec4 c = texture2D(tDiffuse, vUv);
      float scan = 1.0 - 0.07 * (0.5 + 0.5 * sin(vUv.y * lines * 3.14159 + time * 3.0));
      float flick = 0.985 + 0.015 * sin(time * 47.0) * sin(time * 11.0);
      float band = 1.0 + 0.1 * smoothstep(0.03, 0.0, abs(fract(vUv.y * 0.7 - time * 0.09) - 0.5));
      c.rgb *= mix(1.0, scan * flick * band, amount);
      gl_FragColor = c;
    }`,
});
composer.addPass(holoPass);
composer.addPass(new OutputPass());
function render(dt) {
  const glow = CFG.brillo > 0;
  mixPass.enabled = glow; holoPass.enabled = CFG.barrido;
  if (glow) {
    camera.layers.set(GLOW);
    bloomComposer.render(dt);
    camera.layers.set(0);
    mixPass.uniforms.bloomTex.value = bloomComposer.readBuffer.texture;
  }
  composer.render(dt);
}

const lineMats = [];
function line(color, width, opts = {}) {
  const mat = new LineMaterial({ color, linewidth: width, transparent: true, opacity: opts.opacity ?? 1, dashed: !!opts.dash,
    dashSize: opts.dash || 1, gapSize: opts.gap || 0.5, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false });
  lineMats.push(mat);
  const l = new Line2(new LineGeometry(), mat);
  l.frustumCulled = false;
  if (!opts.noGlow) glowOn(l);
  l.userData.set = (pts) => {
    if (pts.length < 6) { l.visible = false; return; }
    l.visible = true;
    l.geometry.dispose(); l.geometry = new LineGeometry(); l.geometry.setPositions(pts);
    if (opts.dash) l.computeLineDistances();
  };
  return l;
}
/**
 * Un plano con texto dibujado en un canvas (brilla porque se suma a lo de atras: lo negro no se ve).
 * La textura tiene los mismos pixeles que ocupa el plano en la pantalla (PPU): 1 a 1, nitida y sin niveles de
 * mipmap que podrian quedar con el texto anterior. Si cambia el tamano de la pantalla, se rehace.
 */
let PPU = 160;
const planes = [];
function textPlane(w, h, draw) {
  const c = document.createElement('canvas');
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  tex.generateMipmaps = false; tex.minFilter = THREE.LinearFilter; tex.magFilter = THREE.LinearFilter;
  const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, toneMapped: false });
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), mat);
  let args = null, ppu = 0;
  const size = () => {
    if (ppu === PPU) return;
    ppu = PPU; c.width = Math.min(4096, Math.round(w * ppu)); c.height = Math.min(4096, Math.round(h * ppu));
    mat.map.dispose(); mat.map = new THREE.CanvasTexture(c); Object.assign(mat.map, { colorSpace: THREE.SRGBColorSpace, generateMipmaps: false, minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter });
  };
  m.userData.draw = (...a) => {
    args = a; size();
    c.width = c.width;                   // borra todo (contenido y estado): mas seguro que clearRect en algunos navegadores
    const ctx = c.getContext('2d');
    draw(ctx, c.width, c.height, ...a); mat.map.needsUpdate = true;
  };
  m.userData.redraw = () => { if (args) m.userData.draw(...args); };
  planes.push(m);
  return m;
}
/** Un panel de vidrio: oscuro y semitransparente, con un reflejo suave arriba y un borde fino. */
function glassRect(ctx, x, y, w, h, r, edge = 'rgba(150, 205, 255, .42)', alpha = 0.62) {
  const g = ctx.createLinearGradient(0, y, 0, y + h);
  g.addColorStop(0, `rgba(30, 52, 78, ${alpha})`); g.addColorStop(0.5, `rgba(14, 28, 46, ${alpha})`); g.addColorStop(1, `rgba(8, 16, 28, ${alpha})`);
  ctx.fillStyle = g; ctx.beginPath(); ctx.roundRect(x, y, w, h, r); ctx.fill();
  const shine = ctx.createLinearGradient(x, y, x + w * 0.6, y + h * 0.6);
  shine.addColorStop(0, 'rgba(255, 255, 255, .07)'); shine.addColorStop(0.35, 'rgba(255, 255, 255, 0)');
  ctx.fillStyle = shine; ctx.fill();
  ctx.strokeStyle = edge; ctx.lineWidth = Math.max(1.5, h / 260); ctx.stroke();
}
/** Texto nitido con un halo muy suave alrededor (el halo va aparte y tenue para no desenfocar las letras). */
const glowText = (ctx, txt, x, y, size, color, weight = 700, align = 'left', blur = 0.12) => {
  ctx.font = `${weight} ${size}px system-ui, -apple-system, "Segoe UI", sans-serif`;
  ctx.textAlign = align; ctx.textBaseline = 'middle'; ctx.fillStyle = color;
  if (blur > 0 && CFG.brillo > 0) {
    ctx.save(); ctx.globalAlpha = 0.3; ctx.shadowColor = color; ctx.shadowBlur = size * Math.min(0.25, blur * 1.5);
    ctx.fillText(txt, x, y); ctx.restore();
  }
  ctx.fillText(txt, x, y);
  return ctx.measureText(txt).width;
};

// medidas del grafico (en unidades de la escena; despues se escala a la pantalla)
const CW = 16, CH = 9, VOLH = 1.5;
const root = new THREE.Group(); scene.add(root);
const spin = new THREE.Group(); root.add(spin);            // el cubo de vidrio: gira para cambiar de cripto o temporalidad
const chart = new THREE.Group(); spin.add(chart);

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
glass.position.z = -0.4; chart.add(glass); glass.visible = false;   // no se ve: solo sirve para ubicar la mira
// el panel de vidrio donde esta dibujado el grafico
const chartGlass = textPlane(CW + 1.0, CH + 1.0, (ctx, w, h) => glassRect(ctx, 3, 3, w - 6, h - 6, h * 0.03, 'rgba(150, 205, 255, .5)', 0.55));
chartGlass.position.z = -0.6; chartGlass.renderOrder = -10; chart.add(chartGlass);
// capas de vidrio mas atras, con el panorama largo y el volumen: dan profundidad cuando el grafico gira
const backA = textPlane(CW * 0.78, CH * 0.62, (ctx, w, h) => {
  glassRect(ctx, 3, 3, w - 6, h - 6, h * 0.05, 'rgba(150, 205, 255, .3)', 0.42);
  const cl = D.bars.map((b) => b[4]); if (cl.length < 2) return;
  const lo = Math.min(...cl), hi = Math.max(...cl), px = (i) => w * 0.06 + (i / (cl.length - 1)) * w * 0.88, py = (v) => h * 0.85 - ((v - lo) / (hi - lo || 1)) * h * 0.62;
  ctx.strokeStyle = 'rgba(150, 205, 255, .12)'; ctx.lineWidth = 1;
  for (let k = 1; k < 5; k++) { ctx.beginPath(); ctx.moveTo(w * 0.06, h * 0.18 + k * h * 0.14); ctx.lineTo(w * 0.94, h * 0.18 + k * h * 0.14); ctx.stroke(); }
  ctx.strokeStyle = T().acc; ctx.globalAlpha = 0.7; ctx.lineWidth = Math.max(2, h / 140); ctx.beginPath();
  cl.forEach((v, i) => (i ? ctx.lineTo(px(i), py(v)) : ctx.moveTo(px(i), py(v)))); ctx.stroke(); ctx.globalAlpha = 1;
  glowText(ctx, `${nameOf(CFG.asset)}/USDT · últimas ${cl.length} velas de ${TF_LBL[CFG.tf]}`, w * 0.06, h * 0.11, h * 0.06, 'rgba(190, 225, 255, .75)', 600, 'left', 0);
});
backA.position.set(-CW * 0.2, CH * 0.36, -3.2); root.add(backA);
const backB = textPlane(6.2, 3.2, (ctx, w, h) => {
  glassRect(ctx, 3, 3, w - 6, h - 6, h * 0.08, 'rgba(150, 205, 255, .3)', 0.45);
  const bs = D.bars.slice(-48); if (!bs.length) return;
  const vm = Math.max(...bs.map((b) => b[5])) || 1, bw = (w * 0.86) / bs.length;
  bs.forEach((b, i) => {
    const bh = (b[5] / vm) * h * 0.55;
    ctx.fillStyle = b[4] >= b[1] ? T().up : T().dn; ctx.globalAlpha = 0.55;
    ctx.fillRect(w * 0.07 + i * bw, h * 0.88 - bh, bw * 0.7, bh);
  });
  ctx.globalAlpha = 1;
  glowText(ctx, 'Volumen', w * 0.07, h * 0.16, h * 0.11, 'rgba(190, 225, 255, .75)', 600, 'left', 0);
});
backB.position.set(CW * 0.36, -CH * 0.22, -2.2); root.add(backB);
[backA, backB].forEach((m) => { m.renderOrder = -20; });
const frame = line(T().acc, 1.2, { opacity: 0.55 }); chart.add(frame);
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
const cornerLines = [0, 1, 2, 3].map(() => { const l = line(T().acc, 4.5); l.visible = false; return l; });   // estetica de vidrio: sin esquinas
(function placeCorners() {
  const w = CW / 2 + 0.3, h = CH / 2 + 0.3, L = 1.4;
  [[-1, 1], [1, 1], [1, -1], [-1, -1]].forEach(([sx, sy], k) => { cornerLines[k].userData.set([sx * w, sy * (h - L), -0.2, sx * w, sy * h, -0.2, sx * (w - L), sy * h, -0.2]); cornerLines[k].visible = false; });
})();

// el cubo de vidrio que se ve mientras gira: aristas finas y caras apenas visibles
function glassBox(w, h, d) {
  const g = new THREE.Group();
  const geo = new THREE.BoxGeometry(w, h, d);
  g.add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: '#7fbfff', transparent: true, opacity: 0.05, side: THREE.DoubleSide, depthWrite: false })));
  g.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color: '#a8d8ff', transparent: true, opacity: 0.5, depthWrite: false })));
  g.visible = false;
  return g;
}
const DEPTH = { y: CW + 1, x: CH + 1 };                     // profundidad del cubo segun el eje en que gira
const boxes = { y: glassBox(CW + 1, CH + 1, DEPTH.y), x: glassBox(CW + 1, CH + 1, DEPTH.x) };
spin.add(boxes.y, boxes.x);
let TURN = null;
let PIN = null;                                            // la cruz fija que deja el clic: { t, price }
function startTurn(turn, apply) {
  if (TURN) { TURN.apply(); finishTurn(); }
  const d = DEPTH[turn.axis];
  spin.position.z = -d / 2; chart.position.z = d / 2;      // el centro de giro queda en el medio del cubo
  boxes[turn.axis].visible = true;
  TURN = { axis: turn.axis, sgn: (turn.axis === 'y' ? 1 : -1) * Math.sign(turn.dir || 1), start: performance.now(), apply, swapped: false, d };
}
function finishTurn() {
  if (!TURN) return;
  spin.rotation.set(0, 0, 0); spin.position.z = 0; chart.position.set(0, 0, 0); chart.rotation.set(0, 0, 0);
  boxes.x.visible = boxes.y.visible = false;
  TURN = null; dirty = true;
}
function animTurn(now) {
  if (!TURN) return;
  if (TURN.hold != null) TURN.start = now - TURN.hold * 800;     // para las pruebas: congelar el giro
  const k = clamp((now - TURN.start) / 800, 0, 1), e = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
  const ang = e * (Math.PI / 2) * TURN.sgn, half = TURN.d / 2;
  if (TURN.axis === 'y') spin.rotation.set(0, ang, 0); else spin.rotation.set(ang, 0, 0);
  if (!TURN.swapped && e >= 0.5) {
    // a mitad de giro: los datos nuevos, en la cara que entra
    TURN.swapped = true; TURN.apply();
    if (TURN.axis === 'y') { chart.position.set(-TURN.sgn * half, chart.position.y, 0); chart.rotation.set(0, -TURN.sgn * Math.PI / 2, 0); }
    else { chart.position.set(0, TURN.sgn * half, 0); chart.rotation.set(-TURN.sgn * Math.PI / 2, 0, 0); }
  }
  const m = boxes[TURN.axis].children;
  m[1].material.opacity = 0.55 * Math.sin(k * Math.PI); m[0].material.opacity = 0.06 * Math.sin(k * Math.PI);
  if (k >= 1) finishTurn();
}

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
glowOn(bodies, wicks, gBodies, gWicks);
// columna de liquidaciones estimadas (BTC): rojas = longs que se liquidan si baja, verdes = shorts si sube
let LQW = 0, LIQ = [];
const liqMesh = new THREE.InstancedMesh(box, new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.8, toneMapped: false, depthWrite: false }), 240);
liqMesh.count = 0; liqMesh.frustumCulled = false; liqMesh.setColorAt(0, new THREE.Color()); chart.add(liqMesh);
const liqLbl = textPlane(1.6, 0.42, (ctx, w, h) => glowText(ctx, 'Liquidac.', w / 2, h / 2, h * 0.55, '#9fd8f0', 600, 'center', 0));
chart.add(liqLbl); liqLbl.visible = false;
const ema20 = line(T().e20, 2.2, { opacity: 0.95 }), ema50 = line(T().e50, 2.2, { opacity: 0.95 });
const priceLine = line(T().acc, 1.6, { dash: 0.35, gap: 0.25, opacity: 0.9, noGlow: true });
const coneMid = line('#ffffff', 1.8, { dash: 0.3, gap: 0.25, opacity: 0.7 });
chart.add(ema20, ema50, priceLine, coneMid);
const cone = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({ color: T().acc, transparent: true, opacity: 0.14, side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false }));
cone.frustumCulled = false; chart.add(cone);
const dot = new THREE.Mesh(new THREE.SphereGeometry(0.16, 20, 14), new THREE.MeshBasicMaterial({ color: '#ffffff', toneMapped: false }));
const halo = new THREE.Mesh(new THREE.RingGeometry(0.22, 0.32, 40), new THREE.MeshBasicMaterial({ color: T().acc, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }));
chart.add(dot, halo);
glowOn(dot, halo);
const scanBar = new THREE.Mesh(new THREE.PlaneGeometry(CW + 0.4, 0.06), new THREE.MeshBasicMaterial({ color: T().acc, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false }));
scanBar.position.z = 0.6; chart.add(scanBar); glowOn(scanBar);

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
const crossV = line('#ffffff', 1.2, { opacity: 0.55, noGlow: true }), crossH = line('#ffffff', 1.2, { opacity: 0.55, noGlow: true });
chart.add(crossV, crossH);
const crossLbl = textPlane(CW, 0.6, (ctx, w, h, parts) => {
  ctx.fillStyle = 'rgba(0, 12, 20, 0.0)';
  let x = 14;
  parts.forEach(([txt, col, bold]) => { x += glowText(ctx, txt, x, h / 2, h * 0.5, col, bold ? 800 : 600, 'left', 0.05) + h * 0.35; });
});
const crossTag = textPlane(2.5, 0.62, (ctx, w, h, txt) => {
  ctx.fillStyle = '#e8fbff'; ctx.beginPath(); ctx.roundRect(4, 6, w - 8, h - 12, h * 0.22); ctx.fill();
  // texto oscuro (no calado) para que tape la etiqueta del eje que quede detras
  ctx.fillStyle = '#04141c'; ctx.font = `800 ${h * 0.56}px system-ui, sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(txt, w / 2, h / 2 + 1);
});
chart.add(crossLbl, crossTag);
[crossV, crossH, crossLbl, crossTag].forEach((o) => { o.visible = false; });
const futLbl = textPlane(5, 0.5, (ctx, w, h, txt) => glowText(ctx, txt, w - 6, h / 2, h * 0.5, '#ffffff', 700, 'right', 0.25));
chart.add(priceTag, futLbl);

/** Varios textos seguidos (con su color) alineados a la derecha. */
function rightParts(ctx, parts, xr, y, size) {
  const gap = size * 0.4, ws = parts.map(([t, , b]) => { ctx.font = `${b ? 800 : 600} ${size}px system-ui, -apple-system, "Segoe UI", sans-serif`; return ctx.measureText(t).width; });
  let x = xr - ws.reduce((a, b) => a + b, 0) - gap * (parts.length - 1);
  parts.forEach(([t, col, b], k) => { glowText(ctx, t, x, y, size, col, b ? 800 : 600, 'left', 0); x += ws[k] + gap; });
}
// cabecera: par, precio grande y cambio
const header = textPlane(CW + 0.6, 2.3, (ctx, w, h) => {
  const t = D.tick[CFG.asset] || {}, last = D.bars.length ? D.bars[D.bars.length - 1][4] : t.last;
  const pct = t.pct ?? null, col = pct === null ? T().acc : pct >= 0 ? T().up : T().dn;
  glowText(ctx, `${nameOf(CFG.asset)}/USDT`, 10, h * 0.2, h * 0.2, T().acc, 800);
  glowText(ctx, `${TF_LBL[CFG.tf]} · ${D.src || '…'}`, w - 10, h * 0.2, h * 0.17, '#9fe9ff', 600, 'right', 0.05);
  // la vela bajo el dedo o la cruz (la ultima si no hay ninguna): apertura, maximo, minimo, cierre y cambio
  const hb = HOVER ? HOVER.b : D.bars[D.bars.length - 1];
  if (hb) {
    const d = dec(hb[4]), cc = hb[4] >= hb[1] ? T().up : T().dn, fs = h * 0.135;
    const when = new Date(hb[0]).toLocaleString('es-AR', CFG.tf === '1d' ? { weekday: 'short', day: '2-digit', month: '2-digit' } : { weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
    rightParts(ctx, [['A', '#7fd8f5'], [fmt(hb[1], d), cc, 1], ['Máx', '#7fd8f5'], [fmt(hb[2], d), cc, 1]], w - 10, h * 0.43, fs);
    rightParts(ctx, [['Mín', '#7fd8f5'], [fmt(hb[3], d), cc, 1], ['C', '#7fd8f5'], [fmt(hb[4], d), cc, 1]], w - 10, h * 0.61, fs);
    rightParts(ctx, [[HOVER && HOVER.g ? 'Futuro posible' : HOVER ? when : `Última · ${when}`, '#9fe9ff'], [fpct((hb[4] / hb[1] - 1) * 100), cc, 1]], w - 10, h * 0.79, fs);
  }
  const x = 10 + glowText(ctx, fmt(last, dec(last || 1)), 10, h * 0.64, h * 0.5, '#d8f7ff', 800, 'left', 0.05) + h * 0.2;
  if (pct !== null) glowText(ctx, `${fpct(pct)} en 24 h`, x, h * 0.68, h * 0.22, col, 800, 'left', 0.08);
});
root.add(header);

// costados: las tres criptos a la izquierda, datos e indicadores a la derecha
const tiles = ASSETS.map((a) => {
  const m = textPlane(3.6, 1.9, (ctx, W, H) => {
    const k = W / 460, w = 460, h = H / k;
    ctx.setTransform(k, 0, 0, k, 0, 0);
    const t = D.tick[a.sym] || {}, on = a.sym === CFG.asset, col = (t.pct ?? 0) >= 0 ? T().up : T().dn;
    glassRect(ctx, 6, 6, w - 12, h - 12, 26, on ? T().acc : 'rgba(150, 205, 255, .35)', on ? 0.75 : 0.55);
    glowText(ctx, `${a.name}/USDT`, 30, h * 0.27, h * 0.2, on ? T().acc : '#9fe9ff', 800, 'left', 0.05);
    glowText(ctx, fmt(t.last, dec(t.last || 1)), 30, h * 0.55, h * 0.26, '#f2fdff', 800, 'left', 0.08);
    if (t.pct !== undefined) glowText(ctx, fpct(t.pct), 30, h * 0.79, h * 0.18, col, 800);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
  });
  m.userData.sym = a.sym;
  root.add(m);
  return m;
});
const stats = textPlane(4.0, 9.4, (ctx, W, H) => {
  // se dibuja en una grilla de 512 px de ancho y se escala a la resolucion real de la textura
  const k = W / 512, w = 512, h = H / k;
  ctx.setTransform(k, 0, 0, k, 0, 0);
  glassRect(ctx, 6, 6, w - 12, h - 12, 26, 'rgba(150, 205, 255, .4)', 0.6);
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
  ctx.setTransform(1, 0, 0, 1, 0, 0);
});
root.add(stats);

function retheme() {
  const t = T();
  document.documentElement.style.setProperty('--acc', t.acc); document.documentElement.style.setProperty('--up', t.up); document.documentElement.style.setProperty('--dn', t.dn);
  [frame, ...cornerLines, priceLine].forEach((l) => l.material.color.set(t.acc));
  ema20.material.color.set(t.e20); ema50.material.color.set(t.e50);
  [grid, cone, halo, scanBar].forEach((m) => m.material.color.set(t.acc));
  dirty = true; panelsDirty = true;
}

// ---------- vista e interaccion ----------
const VDEF = { offset: 0, n: 92, yPan: 0, yZoom: 1, rotX: -0.08, rotY: 0, scale: 1, manual: null };
const V = { ...VDEF };
const VS = { offset: 0 };                // lo que se muestra: sigue a V.offset con un suavizado corto
let dirty = true, panelsDirty = true, priceDirty = false;
const R = { lo: null, hi: null };
function act(a, remote = false) {
  if (!D.bars.length && !['asset', 'tf', 'sync'].includes(a.t)) return;
  if (a.t === 'pan') {
    V.offset = clamp(V.offset + a.dx * V.n, 0, LAY ? LAY.total - LAY.nv : 0);
    if (a.dy) { const m = V.manual || { lo: R.lo, hi: R.hi }, sh = a.dy * (m.hi - m.lo); V.manual = { lo: m.lo + sh, hi: m.hi + sh }; }
  } else if (a.t === 'grab') grab(a);
  else if (a.t === 'zoom') {
    V.n = clamp(V.n / a.f, 20, 300);
    if (V.manual) { const c = (V.manual.lo + V.manual.hi) / 2, hf = (V.manual.hi - V.manual.lo) / 2 / a.f; V.manual = { lo: c - hf, hi: c + hf }; }
  }
  else if (a.t === 'rot') { V.rotY = clamp(V.rotY + a.dx * 2.6, -1.1, 1.1); V.rotX = clamp(V.rotX + a.dy * 2.0, -0.8, 0.8); }
  else if (a.t === 'yzoom') V.yZoom = clamp(V.yZoom * a.f, 0.3, 4);
  else if (a.t === 'asset' || a.t === 'tf') {
    // con la mano abierta tambien cambia, pero solo si el gesto empieza fuera del grafico
    if (a.x !== undefined && ['grafico', 'precios', 'fechas'].includes(region(a.x, a.y))) return;
    if (a.t === 'asset') stepAsset(a.dir); else stepTf(a.dir);
  }
  else if (a.t === 'reset') {
    // doble toque: sobre un eje lo deja como estaba; en el resto, la vista inicial
    const reg = a.x !== undefined ? region(a.x, a.y) : 'grafico';
    if (reg === 'precios') { V.manual = null; V.yZoom = 1; flash('Precios automáticos'); }
    else if (reg === 'fechas') { V.n = VDEF.n; flash('Ancho de velas inicial'); }
    else { Object.assign(V, VDEF); V.manual = null; PIN = null; flash('Vista inicial'); }
  }
  else if (a.t === 'point') { POINT = a.x === null ? null : { x: a.x, y: a.y }; return; }
  else if (a.t === 'pin') { PIN = a.pin || null; return; }
  else if (a.t === 'click') { clickAt(a.x, a.y, !remote && a.hand !== false); return; }
  else if (a.t === 'sync') { if ((a.asset && a.asset !== CFG.asset) || (a.tf && a.tf !== CFG.tf)) load(a.asset || CFG.asset, a.tf || CFG.tf, true, a.asset !== CFG.asset ? assetTurn(a.asset) : tfTurn(a.tf)); }
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
  // cada vela del futuro va en el lugar que le toca segun su hora (si el analisis quedo una vela atras, se corre)
  const tfMs = TF_MS[CFG.tf], at = (r) => ({ ...r, k: Math.round((r.t - lastT) / tfMs) });
  const gg = g.map(at).filter((r) => r.k >= 1), cc = c.map(at).filter((r) => r.k >= 1);
  return gg.length && gg[0].k === 1 ? { g: gg, c: cc } : { g: [], c: [] };
}

let LAY = null, POINT = null, GRAB = null;
const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(), plane = new THREE.Plane(), hitP = new THREE.Vector3(), nrm = new THREE.Vector3();
/** De un punto de la pantalla (0..1) al plano del grafico: coordenadas locales del grafico, o null. */
function chartAt(x, y) {
  ndc.set(x * 2 - 1, -(y * 2 - 1));
  ray.setFromCamera(ndc, camera);
  chart.updateWorldMatrix(true, false);
  nrm.set(0, 0, 1).transformDirection(chart.matrixWorld);
  plane.setFromNormalAndCoplanarPoint(nrm, hitP.setFromMatrixPosition(chart.matrixWorld));
  if (!ray.ray.intersectPlane(plane, hitP)) return null;
  return chart.worldToLocal(hitP.clone());
}
/** Una de las criptos de la izquierda, si el punto cae sobre ella. */
function tileAt(x, y) {
  ndc.set(x * 2 - 1, -(y * 2 - 1)); ray.setFromCamera(ndc, camera);
  const hit = ray.intersectObjects(tiles.filter((m) => m.visible))[0];
  return hit ? hit.object.userData.sym : null;
}
/**
 * Que hay en un punto de la pantalla: el grafico, el eje de precios (con las liquidaciones), el de fechas,
 * una cripto de la izquierda o nada (fuera del grafico).
 */
function region(x, y) {
  if (tileAt(x, y)) return 'cripto';
  const p = chartAt(x, y);
  if (!p) return 'fuera';
  const inX = Math.abs(p.x) <= CW / 2 + 0.3, inY = Math.abs(p.y) <= CH / 2 + 0.3;
  if (inX && inY) return 'grafico';
  if (inY && p.x > CW / 2 && p.x < CW / 2 + LQW + 3.0) return 'precios';
  if (inX && p.y < -CH / 2 && p.y > -CH / 2 - 1.1) return 'fechas';
  return 'fuera';
}
function grab(a) {
  if (a.phase === 'start') {
    const p = chartAt(a.x, a.y), reg = region(a.x, a.y);
    GRAB = { x: a.x, y: a.y, t: Date.now(), moved: 0, p, reg, n: V.n, done: false };
    if (reg === 'precios' && LAY) GRAB.range = { ...(V.manual || { lo: LAY.lo, hi: LAY.hi }) };
    if (reg === 'grafico' && LAY) {
      // la vela y el precio que quedaron bajo los dedos
      GRAB.slot = LAY.start + (p.x - LAY.x0) / LAY.step;
      GRAB.price = LAY.lo + (p.y - LAY.yb) / (LAY.yt - LAY.yb) * (LAY.hi - LAY.lo);
      V.manual = { lo: LAY.lo, hi: LAY.hi };
    }
    return;
  }
  if (!GRAB) return;
  GRAB.moved = Math.max(GRAB.moved, Math.hypot(a.x - GRAB.x, a.y - GRAB.y));
  const dx = a.x - GRAB.x, dy = a.y - GRAB.y;
  if (a.phase === 'move' && GRAB.reg === 'precios' && GRAB.range) {
    // arrastrar sobre los precios estira o achica el grafico en vertical (abajo: entra mas rango; arriba: zoom)
    const r = GRAB.range, c = (r.lo + r.hi) / 2, half = (r.hi - r.lo) / 2 * Math.exp(dy * 3.2);
    V.manual = { lo: c - half, hi: c + half }; dirty = true; return;
  }
  if (a.phase === 'move' && GRAB.reg === 'fechas') {
    // arrastrar sobre las fechas estira o achica en horizontal (derecha: velas mas anchas; izquierda: mas velas)
    V.n = clamp(GRAB.n * Math.exp(-dx * 3.2), 20, 300); dirty = true; return;
  }
  if (a.phase === 'move' && (GRAB.reg === 'fuera' || GRAB.reg === 'cripto') && !GRAB.done && Math.hypot(dx, dy) > 0.12) {
    // arrastrar fuera del grafico: de costado cambia la cripto, hacia arriba o abajo la temporalidad (una vez por arrastre)
    GRAB.done = true;
    // (directo, sin act: el otro equipo enlazado ya recibe el arrastre y hace lo mismo)
    if (Math.abs(dx) > Math.abs(dy) * 1.3) stepAsset(dx > 0 ? 1 : -1);
    else if (Math.abs(dy) > Math.abs(dx) * 1.3) stepTf(dy < 0 ? 1 : -1);
    else GRAB.done = false;
    return;
  }
  if (a.phase === 'end') {
    // pellizco o toque corto y sin moverse: es un clic
    const g = GRAB; GRAB = null;
    if (g.moved < 0.02 && Date.now() - g.t < 450) clickAt(g.x, g.y, false);
    return;
  }
  if (GRAB.slot === undefined || !LAY) return;
  const p = chartAt(a.x, a.y); if (!p) return;
  // se corre la vista para que la misma vela quede bajo los dedos...
  // con el desplazamiento O, en la posicion x del grafico queda la vela total - n - O + (x - x0u) / paso
  V.offset = clamp(LAY.total - LAY.nv - GRAB.slot + (p.x - LAY.x0u) / LAY.step, 0, LAY.total - LAY.nv);
  // ...y el rango de precios para que el mismo precio tambien quede ahi
  const m = V.manual, f = (p.y - LAY.yb) / (LAY.yt - LAY.yb), under = m.lo + f * (m.hi - m.lo), sh = GRAB.price - under;
  V.manual = { lo: m.lo + sh, hi: m.hi + sh };
  dirty = true;
}
/** La vela y el precio en un punto de la pantalla (null si cae fuera del grafico). */
function slotAt(x, y) {
  if (!LAY) return null;
  const p = chartAt(x, y); if (!p) return null;
  const i = Math.round((p.x - LAY.x0) / LAY.step);
  if (i < 0 || i >= LAY.nr + LAY.ghosts.length || p.y < -CH / 2 || p.y > CH / 2 || Math.abs(p.x) > CW / 2 + 0.2) return null;
  const g = i >= LAY.nr ? LAY.ghosts[i - LAY.nr] : null;
  const b = g ? [g.t, g.o, g.h, g.l, g.c, 0] : LAY.vis[i];
  const yy = clamp(p.y, LAY.yb, LAY.yt);
  return { i, b, g: !!g, price: LAY.lo + (yy - LAY.yb) / (LAY.yt - LAY.yb) * (LAY.hi - LAY.lo) };
}
/** La cruz fija del clic, ubicada en la vista de ahora (la vela por su hora, aunque el grafico se haya movido). */
function pinSlot() {
  if (!PIN || !LAY) return null;
  let i = LAY.vis.findIndex((b) => b[0] === PIN.t), g = null;
  if (i < 0) { const k = LAY.ghosts.findIndex((q) => q.t === PIN.t); if (k >= 0) { i = LAY.nr + k; g = LAY.ghosts[k]; } }
  if (i < 0) return null;
  return { i, b: g ? [g.t, g.o, g.h, g.l, g.c, 0] : LAY.vis[i], g: !!g, price: PIN.price };
}
let HOVER = null, headDirty = false;   // la vela que se muestra en la cabecera (como el hover de TradingView)
/**
 * Un clic (pulgar + medio, o un toque corto): en un boton lo aprieta; en una cripto la elige; en el grafico deja la
 * cruz fija en ese punto (fecha, hora y precio) con los datos de la vela arriba; fuera del grafico la saca.
 */
function clickAt(x, y, dom) {
  if (dom && CFG.modo === 'ventana') {
    const r = stage.getBoundingClientRect(), el = document.elementFromPoint(r.left + x * r.width, r.top + y * r.height);
    const b = el && el.closest('button, select, input, label, a');
    if (b && !stage.contains(b)) { b.click(); if (b.matches('select, input')) b.focus(); return; }
  }
  const sym = tileAt(x, y);
  if (sym) { if (sym !== CFG.asset) { setAsset(sym, true, assetTurn(sym)); link.send({ t: 'sync', asset: sym, tf: CFG.tf }); } return; }
  const hit = slotAt(x, y);
  PIN = hit ? { t: hit.b[0], price: hit.price } : null;
  link.send({ t: 'pin', pin: PIN });
}
/** La mira: la vela que esta debajo del dedo (o del mouse) o la que fijo el clic, con su precio y su fecha. */
function updateCross() {
  const show = (v) => [crossV, crossH, crossTag].forEach((o) => { o.visible = v; });
  crossLbl.visible = false;            // los datos de la vela van en la cabecera, arriba a la derecha
  const hit = (POINT && slotAt(POINT.x, POINT.y)) || pinSlot();
  const hk = hit ? `${hit.b[0]}|${hit.b[1]}|${hit.b[2]}|${hit.b[3]}|${hit.b[4]}|${hit.g}` : '';
  if (hk !== (HOVER ? HOVER.k : '')) { HOVER = hit ? { ...hit, k: hk } : null; headDirty = true; }
  if (!hit) { show(false); return; }
  const x = LAY.x0 + hit.i * LAY.step, yy = LAY.yb + (hit.price - LAY.lo) / (LAY.hi - LAY.lo) * (LAY.yt - LAY.yb);
  const inY = yy >= LAY.yb - 0.01 && yy <= LAY.yt + 0.01;
  crossV.userData.set([x, -CH / 2, 0.7, x, CH / 2, 0.7]);
  crossH.userData.set([-CW / 2, yy, 0.7, CW / 2, yy, 0.7]);
  crossTag.position.set(CW / 2 + LQW + 1.55, yy, 0.8);
  const tk = fmt(hit.price, dec(hit.b[4]));
  if (crossTag.userData.k !== tk) { crossTag.userData.k = tk; crossTag.userData.draw(tk); }
  crossV.visible = true; crossH.visible = crossTag.visible = inY;
}

function rebuild(dt) {
  const bars = D.bars;
  if (!bars.length) { bodies.count = wicks.count = vols.count = gBodies.count = gWicks.count = 0; return; }
  // el futuro posible es parte de la serie: al arrastrar se corre como cualquier vela (no desaparece de golpe)
  const fut = ghostsFor(bars[bars.length - 1][0]);
  const total = bars.length + fut.g.length;
  const n = Math.round(clamp(V.n, 20, Math.min(300, total)));
  V.offset = clamp(V.offset, 0, total - n);
  // se dibuja con el desplazamiento suavizado y con fraccion de vela: el grafico se desliza, no salta de vela en vela
  const off = clamp(VS.offset, 0, total - n), fl = Math.floor(off), frac = off - fl, ext = frac > 1e-3 ? 1 : 0;
  const end = total - fl, start = end - n - ext;
  const vis = bars.slice(start, Math.min(end, bars.length));
  const shown = Math.max(0, end - bars.length), ghosts = fut.g.slice(0, shown), cn = fut.c.slice(0, shown);
  const live = end >= bars.length;                 // la ultima vela real esta a la vista
  const nr = vis.length, step = CW / n, x0u = -CW / 2 + step / 2, x0 = x0u + (frac - ext) * step;
  const X = (i) => x0 + i * step;
  let lo = Infinity, hi = -Infinity;
  vis.forEach((b) => { lo = Math.min(lo, b[3]); hi = Math.max(hi, b[2]); });
  ghosts.forEach((b) => { lo = Math.min(lo, b.l); hi = Math.max(hi, b.h); });
  cn.forEach((c) => { lo = Math.min(lo, c.p10); hi = Math.max(hi, c.p90); });
  const pad = (hi - lo) * 0.07 || hi * 0.001; lo -= pad; hi += pad;
  const mid = (lo + hi) / 2, half = (hi - lo) / 2 * V.yZoom, sh = (hi - lo) * V.yPan;
  // con el grafico agarrado (o movido a mano en vertical) el rango de precios queda fijo: lo que esta bajo los dedos
  // no se corre. Si no, se acomoda solo y suave, sin saltar con cada tick
  const tLo = V.manual ? V.manual.lo : mid - half + sh, tHi = V.manual ? V.manual.hi : mid + half + sh;
  R.tLo = tLo; R.tHi = tHi;
  const k = R.lo === null ? 1 : 1 - Math.pow(V.manual ? 1e-4 : 0.0015, dt);
  R.lo = R.lo === null ? tLo : R.lo + (tLo - R.lo) * k; R.hi = R.hi === null ? tHi : R.hi + (tHi - R.hi) * k;
  const yb = -CH / 2 + VOLH + 0.3, yt = CH / 2 - 0.15;
  const Y = (p) => yb + (p - R.lo) / (R.hi - R.lo || 1) * (yt - yb);
  LAY = { x0, x0u, step, vis, ghosts, n: n + ext, nv: n, nr, start, total, yb, yt, lo: R.lo, hi: R.hi };
  const inY = (y) => clamp(y, yb - 0.05, yt + 0.05);
  const up = new THREE.Color(T().up), dn = new THREE.Color(T().dn), acc = new THREE.Color(T().acc);
  const bw = Math.max(0.03, step * 0.62), bd = Math.min(0.9, bw * 0.9), ww = Math.max(0.025, bw * 0.16);
  const vmax = Math.max(...vis.map((b) => b[5])) || 1;
  const grow = (i) => clamp((D.anim * 1.35 - i / n) * 5, 0, 1);       // las velas aparecen de izquierda a derecha
  const outside = (x) => x < -CW / 2 + bw * 0.5 || x > CW / 2 - bw * 0.5;
  vis.forEach((b, i) => {
    const [, o, h, l, c, v] = b, x = X(i), g = outside(x) ? 0 : grow(i), isLast = live && i === nr - 1;
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
  bodies.count = wicks.count = vols.count = nr;
  [bodies, wicks, vols].forEach((m) => { m.instanceMatrix.needsUpdate = true; m.instanceColor.needsUpdate = true; });
  // futuro: velas fantasma del escenario tipico y la zona donde termino el 80% de los casos parecidos
  ghosts.forEach((b, j) => {
    const x = X(nr + j), gg = outside(x) ? 0.0001 : 1;
    const col = tmpC.copy(b.c >= b.o ? up : dn);
    const y1 = inY(Y(Math.max(b.o, b.c))), y0 = inY(Y(Math.min(b.o, b.c)));
    tmpP.set(x, (y0 + y1) / 2, 0); tmpS.set(bw, Math.max(0.035, y1 - y0) * gg, bd);
    gBodies.setMatrixAt(j, tmpM.compose(tmpP, Q0, tmpS)); gBodies.setColorAt(j, col);
    tmpP.set(x, (inY(Y(b.l)) + inY(Y(b.h))) / 2, 0); tmpS.set(ww, Math.max(0.02, inY(Y(b.h)) - inY(Y(b.l))) * gg, ww);
    gWicks.setMatrixAt(j, tmpM.compose(tmpP, Q0, tmpS)); gWicks.setColorAt(j, col);
  });
  gBodies.count = gWicks.count = ghosts.length;
  [gBodies, gWicks].forEach((m) => { m.instanceMatrix.needsUpdate = true; if (m.instanceColor) m.instanceColor.needsUpdate = true; });
  if (cn.length && nr) {
    const lastX = X(nr - 1), lastC = vis[nr - 1][4], pos = [];
    const pts = [[lastX, Y(lastC), Y(lastC), Y(lastC)]].concat(cn.map((c, j) => [X(nr + j), inY(Y(c.p10)), inY(Y(c.p90)), inY(Y(c.p50))]));
    for (let j = 0; j < pts.length - 1; j++) {
      const [xa, la, ha] = pts[j], [xb, lb, hb] = pts[j + 1];
      pos.push(xa, la, -0.2, xb, lb, -0.2, xb, hb, -0.2, xa, la, -0.2, xb, hb, -0.2, xa, ha, -0.2);
    }
    cone.geometry.dispose(); cone.geometry = new THREE.BufferGeometry(); cone.geometry.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    cone.visible = true;
    coneMid.userData.set(pts.flatMap((p) => [p[0], p[3], 0.1]));
    // el cartel va sobre el futuro, a la derecha y siempre adentro del marco; si se ve muy poco futuro, no va
    futLbl.visible = X(nr) < CW / 2 - 4.6; futLbl.position.set(CW / 2 - 2.6, CH / 2 - 0.4, 0.2);
    futLbl.userData.draw('FUTURO POSIBLE · ANALISTA');
  } else { cone.visible = false; coneMid.visible = false; futLbl.visible = false; }
  // medias, precio actual y grilla
  const closes = bars.map((b) => b[4]);
  const lineOf = (arr) => { const pts = []; for (let i = 0; i < nr; i++) { const v = arr[start + i]; if (v !== null && v !== undefined && !outside(X(i))) pts.push(X(i), clamp(Y(v), yb, yt), 0.15); } return pts; };
  if (window.Ind) { ema20.userData.set(lineOf(window.Ind.ema(closes, 20))); ema50.userData.set(lineOf(window.Ind.ema(closes, 50))); }
  // liquidaciones: barras horizontales al costado, en el rango de precios visible
  LIQ = CFG.asset === 'BTCUSDT' && CFG.pred && D.rows ? D.rows.filter((r) => r.tabla === 'liquidacion') : [];
  const lqw = LIQ.length ? 1.7 : 0;
  if (lqw !== LQW) { LQW = lqw; layout(); }
  let li = 0;
  if (LQW) {
    const inR = LIQ.filter((r) => r.precio > R.lo && r.precio < R.hi), vmaxL = Math.max(1e-9, ...inR.map((r) => Math.max(r.longs, r.shorts)));
    inR.forEach((r) => {
      const hh = Math.max(0.03, Math.abs(Y(r.precio * 1.00125) - Y(r.precio * 0.99875)) * 0.8), yy = Y(r.precio);
      let x = CW / 2 + 0.4;
      [[r.longs, dn], [r.shorts, up]].forEach(([v, col]) => {
        if (!(v > 0) || li >= 240) return;
        const ww = Math.max(0.05, Math.sqrt(v / vmaxL) * (LQW - 0.6));
        tmpP.set(x + ww / 2, yy, 0); tmpS.set(ww, hh, 0.05);
        liqMesh.setMatrixAt(li, tmpM.compose(tmpP, Q0, tmpS)); liqMesh.setColorAt(li, tmpC.copy(col).multiplyScalar(0.35 + 0.65 * Math.sqrt(v / vmaxL)));
        x += ww; li += 1;
      });
    });
    liqLbl.visible = true; liqLbl.position.set(CW / 2 + LQW / 2 + 0.1, -CH / 2 - 0.55, 0.1);
  } else liqLbl.visible = false;
  liqMesh.count = li; liqMesh.instanceMatrix.needsUpdate = true; if (liqMesh.instanceColor) liqMesh.instanceColor.needsUpdate = true;
  const last = bars[bars.length - 1], py = clamp(Y(last[4]), yb, yt);
  priceLine.userData.set([-CW / 2, py, 0.05, CW / 2 + LQW + 0.3, py, 0.05]);
  priceTag.position.set(CW / 2 + LQW + 1.55, py, 0.2);
  const tagTxt = fmt(last[4], dec(last[4]));
  if (priceTag.userData.txt !== tagTxt + T().acc) { priceTag.userData.txt = tagTxt + T().acc; priceTag.userData.draw(tagTxt, T().acc); }
  dot.position.set(X(nr - 1), Y(last[4]), 0.5); halo.position.copy(dot.position); dot.visible = halo.visible = live && nr > 0;
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
    m.visible = true; m.position.set(CW / 2 + LQW + 1.5, Y(v), 0.1);
    const txt = fmt(v, unit < 1 ? 4 : unit < 10 ? 2 : 0);
    if (m.userData.txt !== txt) { m.userData.txt = txt; m.userData.draw(txt); }
  });
  // fechas abajo
  const fmtT = (t) => new Date(t).toLocaleString('es-AR', CFG.tf === '1d' ? { day: '2-digit', month: '2-digit' } : { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  timeLbls.forEach((m, j) => {
    const i = Math.round((n - 1) * (j + 0.5) / timeLbls.length);
    const t = i < nr ? vis[i][0] : ghosts[i - nr] ? ghosts[i - nr].t : null;
    if (t === null) { m.visible = false; return; }
    m.visible = true; m.position.set(X(i), -CH / 2 - 0.55, 0.1);
    const txt = fmtT(t);
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
  tiles.forEach((m, i) => { m.visible = sides; m.position.set(-CW / 2 - 2.6, CH / 2 - 1.0 - i * 2.15, 0.6); m.rotation.y = 0.38; });
  stats.visible = sides; stats.position.set(CW / 2 + LQW + 5.0, 0, 0.6); stats.rotation.y = -0.38;
  header.position.set(0, CH / 2 + 1.6, 0.2);
  // tamano del contenido y escala para que entre en la pantalla (lo que esta adelante de la pantalla se ve mas grande)
  const totalW = CW + 3.2 + LQW + (sides ? 2 * 4.4 + 1.2 : 0), top = CH / 2 + 2.8, bottom = CH / 2 + 1.0;
  const persp = (zDef - popZ) / zDef;
  const s = Math.min(0.9 * SW * persp / totalW, 0.88 * SH * persp / (top + bottom));
  root.userData.base = s;
  // pixeles de la pantalla por unidad de la escena (lo que esta adelante de la pantalla se ve mas grande)
  const dpr = renderer.getPixelRatio(), pxPerCm = stageDims().w / SW;
  const ppu = Math.round(Math.min(360, Math.max(48, s * pxPerCm * dpr * (zDef / Math.max(1, zDef - popZ)) * 1.1)));
  if (Math.abs(ppu - PPU) / PPU > 0.08) { PPU = ppu; planes.forEach((m) => m.userData.redraw()); panelsDirty = true; }
  root.position.set(-(1.3 + LQW / 2) * s, (bottom - top) / 2 * s, popZ);   // el eje de precios (y las liquidaciones) corren el centro
  root.scale.setScalar(s * V.scale);
}
function resize() {
  const { w, h, rot } = stageDims();
  stage.style.width = w + 'px'; stage.style.height = h + 'px';
  const sx = CFG.modo === 'reflejo' && CFG.espejoH ? -1 : 1, sy = CFG.modo === 'reflejo' && CFG.espejoV ? -1 : 1;
  stage.style.transform = `translate(-50%, -50%) rotate(${rot}deg) scale(${sx}, ${sy})`;
  // resolucion completa (Retina incluida); solo en pantallas enormes (5K o mas) se baja un poco
  const raw = devicePixelRatio || 1, dpr = w * h * raw * raw > 1.5e7 ? Math.sqrt(1.5e7 / (w * h)) : Math.min(raw, 2);
  renderer.setPixelRatio(dpr); renderer.setSize(w, h, false);
  composer.setPixelRatio(dpr); composer.setSize(w, h);
  bloomComposer.setPixelRatio(dpr * 0.5); bloomComposer.setSize(w, h);     // el brillo es difuso: alcanza con media resolucion
  holoPass.uniforms.lines.value = h / 2.5;
  lineMats.forEach((m) => m.resolution.set(w, h));
  hud.width = w * dpr; hud.height = h * dpr;
  layout(); dirty = true;
}
window.addEventListener('resize', resize);

// ---------- cuadro por cuadro ----------
let lastT = performance.now(), panelT = 0, headT = 0;
function frameLoop(now) {
  requestAnimationFrame(frameLoop);
  if (document.hidden) return;
  const real = (now - lastT) / 1000, dt = Math.min(0.1, real); lastT = now;
  const t = now / 1000;
  if (D.anim < 1) { D.anim = Math.min(1, D.anim + real * 0.9); dirty = true; }
  const dOff = V.offset - VS.offset;
  if (Math.abs(dOff) > 1e-3) { VS.offset += dOff * (1 - Math.pow(1e-4, dt)); dirty = true; } else VS.offset = V.offset;
  if (dirty || rangeMoving()) { dirty = false; rebuild(dt); }
  if ((panelsDirty || priceDirty) && now - panelT > 250) {
    panelT = now; header.userData.draw(); headDirty = false;
    if (panelsDirty) { tiles.forEach((m) => m.userData.draw()); stats.userData.draw(); backA.userData.draw(); backB.userData.draw(); chartGlass.userData.draw(); }
    else tiles.forEach((m) => { if (m.userData.sym === CFG.asset) m.userData.draw(); });   // el precio de la cripto elegida, al tick
    panelsDirty = priceDirty = false;
  }
  // el holograma respira: flota y se mece un poco
  const idle = CFG.modo === 'ventana' ? Math.sin(t * 0.35) * 0.06 : 0;
  root.rotation.x += (V.rotX - root.rotation.x) * Math.min(1, dt * 6);
  root.rotation.y += (V.rotY + idle - root.rotation.y) * Math.min(1, dt * 6);
  const base = root.userData.base || 1;
  root.scale.setScalar(base * V.scale);
  if (!TURN || TURN.axis === 'y') chart.position.y = TURN && TURN.swapped ? chart.position.y : Math.sin(t * 0.8) * 0.06;
  animTurn(now);
  scanBar.visible = CFG.brillo > 0; halo.visible = halo.visible && CFG.brillo > 0;
  scanBar.position.y = -CH / 2 + ((t * 0.25) % 1) * CH;
  scanBar.material.opacity = 0.35 + 0.25 * Math.sin(t * 3);
  halo.scale.setScalar(1 + 0.35 * (0.5 + 0.5 * Math.sin(t * 4)));
  halo.material.opacity = 0.5 + 0.4 * Math.sin(t * 4);
  holoPass.uniforms.time.value = t;
  applyEye(dt);
  updateCross();
  if (headDirty && now - headT > 60) { headT = now; headDirty = false; header.userData.draw(); }
  render(dt);
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
      ctx.strokeStyle = acc; ctx.globalAlpha = 0.35; ctx.lineWidth = Math.max(2, w / 700);
      [[0, 1, 2, 3, 4], [0, 5, 6, 7, 8], [5, 9, 10, 11, 12], [9, 13, 14, 15, 16], [13, 17, 18, 19, 20], [0, 17]].forEach((ch) => {
        ctx.beginPath(); ch.forEach((k, i) => { const p = c.pts[k]; if (i) ctx.lineTo(p.x * w, p.y * h); else ctx.moveTo(p.x * w, p.y * h); }); ctx.stroke();
      });
      ctx.globalAlpha = 1;
    }
    const x = c.x * w, y = c.y * h, r = Math.max(10, w / 70) * (c.state === 'pinch' ? 0.7 : 1);
    ctx.shadowColor = acc; ctx.shadowBlur = 20;
    ctx.strokeStyle = c.state === 'pinch' ? '#ffffff' : acc; ctx.lineWidth = Math.max(3, w / 400);
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.stroke();
    if (c.state === 'pinch' || c.state === 'fist' || c.state === 'point' || c.state === 'tap') { ctx.fillStyle = c.state === 'pinch' ? acc : c.state === 'fist' ? T().e50 : '#ffffff'; ctx.beginPath(); ctx.arc(x, y, r * 0.45, 0, Math.PI * 2); ctx.fill(); }
    const NAME = { pinch: list.filter((q) => q.state === 'pinch').length === 2 ? 'Zoom / girar' : 'Arrastrar', fist: 'Girar', point: 'Apuntar', tap: 'Clic: fijar la cruz', open: holdP > 0 ? 'Quieta: reiniciar' : 'Deslizá: cripto o tiempo' };
    if (NAME[c.state]) {
      const fs = Math.max(13, w / 95);
      ctx.font = `700 ${fs}px system-ui, sans-serif`; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      ctx.fillStyle = 'rgba(0, 0, 0, .55)'; const tw = ctx.measureText(NAME[c.state]).width;
      ctx.beginPath(); ctx.roundRect(x + r * 1.6, y - fs * 0.8, tw + fs, fs * 1.6, fs * 0.8); ctx.fill();
      ctx.fillStyle = '#e8fbff'; ctx.fillText(NAME[c.state], x + r * 1.6 + fs / 2, y);
    }
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
  // un dedo o el mouse agarran el grafico en el punto tocado (igual que el pellizco); dos dedos: zoom y giro;
  // boton derecho o shift: girar; rueda: zoom; doble toque: vista inicial
  const pts = new Map();
  let pinch = null, lastTap = 0, mode = null;
  // del punto de la pantalla al del escenario (que en modo reflejo puede estar espejado)
  const toStage = (e) => {
    const r = stage.getBoundingClientRect();
    let x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
    if (CFG.modo === 'reflejo' && CFG.espejoH) x = 1 - x;
    if (CFG.modo === 'reflejo' && CFG.espejoV) y = 1 - y;
    return { x, y };
  };
  stage.addEventListener('pointerdown', (e) => {
    try { stage.setPointerCapture(e.pointerId); } catch (err) { /* puntero ya suelto */ }
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    wake();
    if (pts.size === 2) {
      if (mode === 'grab') act({ t: 'grab', phase: 'end', ...toStage(e) });
      const [a, b] = [...pts.values()]; pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2 }; mode = 'two';
      return;
    }
    const now = Date.now();
    if (now - lastTap < 300) { act({ t: 'reset', ...toStage(e) }); lastTap = 0; mode = null; return; }
    lastTap = now;
    mode = e.button === 2 || e.shiftKey ? 'rot' : 'grab';
    if (mode === 'grab') act({ t: 'grab', phase: 'start', ...toStage(e) });
  });
  stage.addEventListener('pointermove', (e) => {
    if (e.pointerType === 'mouse' && CFG.modo === 'ventana') {
      POINT = toStage(e);
      if (!mode) { const reg = region(POINT.x, POINT.y); stage.style.cursor = reg === 'precios' ? 'ns-resize' : reg === 'fechas' ? 'ew-resize' : reg === 'cripto' ? 'pointer' : ''; }
    }
    const p = pts.get(e.pointerId); if (!p) return;
    const dx = (e.clientX - p.x) / innerWidth, dy = (e.clientY - p.y) / innerHeight;
    p.x = e.clientX; p.y = e.clientY;
    if (mode === 'two' && pts.size === 2 && pinch) {
      const [a, b] = [...pts.values()], d = Math.hypot(a.x - b.x, a.y - b.y), cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2;
      if (pinch.d > 20) act({ t: 'zoom', f: d / pinch.d });
      act({ t: 'rot', dx: (cx - pinch.cx) / innerWidth, dy: (cy - pinch.cy) / innerHeight });
      pinch = { d, cx, cy };
    } else if (mode === 'rot') act({ t: 'rot', dx, dy });
    else if (mode === 'grab') act({ t: 'grab', phase: 'move', ...toStage(e) });
  });
  const up = (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.delete(e.pointerId);
    if (mode === 'grab') act({ t: 'grab', phase: 'end', ...toStage(e) });
    if (pts.size === 0) mode = null; else if (pts.size < 2) { pinch = null; mode = null; }
  };
  stage.addEventListener('pointerup', up); stage.addEventListener('pointercancel', up);
  stage.addEventListener('pointerleave', (e) => { if (e.pointerType === 'mouse') POINT = null; });
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
const assetTurn = (v) => { const d = ASSETS.findIndex((a) => a.sym === v) - ASSETS.findIndex((a) => a.sym === CFG.asset); return d ? { axis: 'y', dir: Math.sign(d) } : null; };
const tfTurn = (v) => { const d = TFS.indexOf(v) - TFS.indexOf(CFG.tf); return d ? { axis: 'x', dir: Math.sign(d) } : null; };
seg($('#assets'), ASSETS.map((a) => [a.sym, a.name]), 'asset', (v) => { if (v !== CFG.asset) setAsset(v, true, assetTurn(v)); link.send({ t: 'sync', asset: v, tf: CFG.tf }); });
seg($('#tfs'), TFS.map((t) => [t, TF_LBL[t]]), 'tf', (v) => { if (v !== CFG.tf) setTf(v, tfTurn(v)); link.send({ t: 'sync', asset: CFG.asset, tf: v }); });
function syncButtons() {
  document.querySelectorAll('#assets button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === CFG.asset)));
  document.querySelectorAll('#tfs button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === CFG.tf)));
  document.querySelectorAll('#modos button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.modo === CFG.modo)));
  document.querySelectorAll('#temas button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.tema === CFG.tema)));
  $('#s-diag').value = String(CFG.diag); $('#s-cam').value = CFG.cam; $('#s-cabeza').checked = CFG.cabeza;
  $('#s-lados').checked = CFG.lados; $('#s-pred').checked = CFG.pred;
  $('#s-espejo-h').setAttribute('aria-pressed', String(CFG.espejoH)); $('#s-espejo-v').setAttribute('aria-pressed', String(CFG.espejoV));
  holoPass.uniforms.amount.value = CFG.barrido ? (CFG.modo === 'reflejo' ? 0.6 : 1) : 0;
  bloom.strength = 0.1 + (CFG.brillo / 100) * 1.1; bloom.radius = 0.12 + (CFG.brillo / 100) * 0.18;
  $('#s-brillo').value = String(CFG.brillo); $('#s-barrido').checked = CFG.barrido;
  planes.forEach((m) => m.userData.redraw());
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
$('#s-brillo').addEventListener('input', () => { CFG.brillo = Number($('#s-brillo').value); save(); syncButtons(); });
$('#s-barrido').addEventListener('change', change(() => { CFG.barrido = $('#s-barrido').checked; }));
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
load(CFG.asset, CFG.tf, false);
if (Q.get('par')) joinLink(Q.get('par').toUpperCase());
if (EMBED && window.parent !== window) window.parent.postMessage({ tipo: 'holo-listo' }, location.origin);
window.__holo = { act, D, V, CFG, onFace, tiles, chart, header, stats, setCursors: (l) => { cursors = l; }, turn: () => TURN, region: (x, y) => region(x, y) };   // para probar
