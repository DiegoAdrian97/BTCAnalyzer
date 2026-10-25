/*
 * Manos y cabeza con la camara (MediaPipe, corre en el navegador: la imagen no sale del equipo).
 *
 * Para que sea preciso y estable:
 * - Los dedos se leen con las coordenadas 3D reales de la mano (en metros, "worldLandmarks"): un pellizco es pulgar
 *   e indice a menos de ~3,5 cm, y un dedo esta estirado o doblado segun el angulo de sus articulaciones. Asi no
 *   depende de lo lejos que estes de la camara ni de como gires la mano.
 * - Cada punto pasa por un filtro "One Euro": quieto no tiembla y rapido no se atrasa.
 * - Zona muerta: los movimientos de unos pocos pixeles se ignoran (sin escalones: al pasarla, sigue suave).
 * - Un gesto tiene que sostenerse 3 cuadros para contar (no parpadea), y las manos se siguen por su posicion.
 * - Si la camara pierde la mano unos cuadros (un error de deteccion), el gesto sigue: no se suelta el grafico.
 *
 * Gestos (la imagen se mira como un espejo: derecha es tu derecha):
 * - pellizco: agarra el grafico justo donde pellizcas (la vela y el precio quedan bajo tus dedos mientras moves la
 *   mano); un pellizco corto sobre una cripto de la izquierda la elige, como un clic
 * - pellizco con las dos manos: separar o juntar es zoom; girarlas como un volante gira el holograma
 * - puno cerrado y mover: girar el holograma
 * - indice estirado (apuntar): mira sobre la vela que senalas, con su precio
 * - pulgar con el dedo MEDIO (el indice sigue apuntando): clic donde apunta el indice (botones, criptos, ejes...)
 * - palma abierta y deslizar rapido de costado: cambiar de cripto; arriba o abajo: cambiar de temporalidad
 * - palma abierta quieta 1,5 s: volver a la vista inicial
 */
const VISION = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.1.1';
const HAND_MODEL = 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task';
const FACE_MODEL = 'https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite';

const d2 = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const d3 = (a, b) => Math.hypot(a.x - b.x, a.y - b.y, (a.z || 0) - (b.z || 0));
const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
// la mano no llega a los bordes de lo que ve la camara: el centro de la imagen se estira a toda la pantalla
const REACH = 1.45;
const DEAD = 0.004;          // zona muerta (fraccion de la pantalla, ~5 px en la MacBook)
const GRACE = 6;             // cuadros que se espera a una mano que la camara perdio antes de soltar el gesto
const toScreen = (p) => ({ x: clamp(0.5 + (p.x - 0.5) * REACH, 0, 1), y: clamp(0.5 + (p.y - 0.5) * REACH, 0, 1) });

/** Filtro One Euro: suaviza mucho cuando el valor esta quieto y poco cuando se mueve rapido. */
class OneEuro {
  constructor(minCutoff = 1.4, beta = 0.02, dCutoff = 1.0) { Object.assign(this, { minCutoff, beta, dCutoff }); this.x = null; this.dx = 0; this.t = 0; }
  static alpha(cutoff, dt) { const r = 2 * Math.PI * cutoff * dt; return r / (r + 1); }
  filter(x, t) {
    if (this.x === null) { this.x = x; this.t = t; return x; }
    const dt = Math.max(1e-3, (t - this.t) / 1000); this.t = t;
    const dx = (x - this.x) / dt;
    this.dx += OneEuro.alpha(this.dCutoff, dt) * (dx - this.dx);
    const cutoff = this.minCutoff + this.beta * Math.abs(this.dx) * 100;
    this.x += OneEuro.alpha(cutoff, dt) * (x - this.x);
    return this.x;
  }
}

/** Angulo (grados) en la articulacion b, entre a-b y b-c: 180 = dedo recto. */
function angle(a, b, c) {
  const u = { x: a.x - b.x, y: a.y - b.y, z: a.z - b.z }, v = { x: c.x - b.x, y: c.y - b.y, z: c.z - b.z };
  const dot = u.x * v.x + u.y * v.y + u.z * v.z, n = Math.hypot(u.x, u.y, u.z) * Math.hypot(v.x, v.y, v.z) || 1;
  return Math.acos(clamp(dot / n, -1, 1)) * 180 / Math.PI;
}

/**
 * Que hace una mano. lm: puntos en la imagen (0..1); w: los mismos en metros (o null). prev: el estado anterior
 * (para la histeresis: cuesta mas soltar que agarrar).
 */
export function leerMano(lm, w, prev = 'none') {
  const P = lm.map((p) => ({ x: 1 - p.x, y: p.y, z: p.z || 0 }));          // espejo: como mirarse
  const W = w && w.length === 21 ? w : P.map((p) => ({ x: p.x, y: p.y, z: p.z }));
  // tamano de la palma (en las mismas unidades que W) para lo que no tiene medida absoluta
  const palm = (d3(W[0], W[5]) + d3(W[0], W[17]) + d3(W[5], W[17])) / 3 || 1e-3;
  // estirado o doblado: el angulo en las dos articulaciones del dedo
  const straight = (m, p, d, t) => angle(W[m], W[p], W[d]) + angle(W[p], W[d], W[t]);
  const fing = [[5, 6, 7, 8], [9, 10, 11, 12], [13, 14, 15, 16], [17, 18, 19, 20]].map(([m, p, d, t]) => straight(m, p, d, t));
  const ext = fing.map((a) => a > 320), curled = fing.map((a) => a < 250);
  const pinchD = d3(W[4], W[8]) / palm;            // ~0,3 tocandose; ~1 o mas separados
  const midD = d3(W[4], W[12]) / palm;               // pulgar con el dedo medio: el clic
  const wasPinch = prev === 'pinch';
  const pinch = pinchD < (wasPinch ? 0.55 : 0.38) && !curled[0];
  const tap = !pinch && midD < (prev === 'tap' ? 0.55 : 0.38) && pinchD > 0.6;
  const fist = !pinch && !tap && curled.every(Boolean);
  const point = !pinch && !tap && ext[0] && curled[1] && curled[2] && curled[3];
  const open = !pinch && !tap && ext.every(Boolean) && pinchD > 0.6;
  const state = pinch ? 'pinch' : tap ? 'tap' : fist ? 'fist' : point ? 'point' : open ? 'open' : 'none';
  const spots = { pinch: mid(P[4], P[8]), point: { x: P[8].x, y: P[8].y }, other: { x: (P[0].x + P[9].x) / 2, y: (P[0].y + P[9].y) / 2 } };
  return { P, state, spots, pinchD, size: d2(P[0], P[9]) };
}

export class Manos {
  constructor({ video, onAction, onCursor, onHold, onFace, onState }) {
    Object.assign(this, { video, onAction, onCursor, onHold, onFace, onState });
    this.running = false; this.hands = null; this.face = null; this.useFace = false;
    this.tracks = []; this.nextId = 1; this.hist = []; this.cool = 0; this.holdStart = 0; this.two = null; this.frame = 0;
    this.grabId = null; this.grabAt = null;
  }

  async start({ cara = false } = {}) {
    if (this.running) return;
    this.onState('Pidiendo permiso para la cámara…');
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 60, min: 24 } }, audio: false,
    });
    this.video.srcObject = this.stream;
    await this.video.play();
    this.onState('Cargando el reconocimiento de manos…');
    const { FilesetResolver, HandLandmarker, FaceDetector } = await import(`${VISION}/vision_bundle.mjs`);
    this.FaceDetector = FaceDetector;
    this.fileset = await FilesetResolver.forVisionTasks(`${VISION}/wasm`);
    const make = (delegate) => HandLandmarker.createFromOptions(this.fileset, {
      baseOptions: { modelAssetPath: HAND_MODEL, delegate }, runningMode: 'VIDEO', numHands: 2,
      minHandDetectionConfidence: 0.5, minHandPresenceConfidence: 0.5, minTrackingConfidence: 0.5,
    });
    try { this.hands = await make('GPU'); } catch (e) { this.hands = await make('CPU'); }
    this.running = true;
    await this.setFace(cara);
    this.onState('✋ Manos activas: pellizcá para agarrar el gráfico, apuntá con el índice para ver una vela');
    this.loop();
  }

  async setFace(on) {
    this.useFace = on;
    if (on && !this.face && this.FaceDetector) {
      try {
        this.face = await this.FaceDetector.createFromOptions(this.fileset, {
          baseOptions: { modelAssetPath: FACE_MODEL, delegate: 'GPU' }, runningMode: 'VIDEO', minDetectionConfidence: 0.5,
        });
      } catch (e) { this.onState('No se pudo activar el seguimiento de la cabeza', true); }
    }
  }

  stop() {
    this.running = false;
    cancelAnimationFrame(this.raf);
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    this.stream = null; this.tracks = []; this.onCursor([]); this.onHold(0);
  }

  loop() {
    if (!this.running) return;
    const v = this.video;
    const next = () => {
      if (!this.running) return;
      // un analisis por cuadro nuevo de la camara (no por cuadro de pantalla)
      if (v.requestVideoFrameCallback) v.requestVideoFrameCallback(() => this.tick());
      else this.raf = requestAnimationFrame(() => this.tick());
    };
    this.next = next;
    next();
  }

  tick() {
    const v = this.video;
    if (v.readyState >= 2 && v.currentTime !== this.lastTime) {
      this.lastTime = v.currentTime;
      const now = performance.now();
      try {
        const res = this.hands.detectForVideo(v, now);
        this.process(res, now);
        if (this.useFace && this.face && this.frame++ % 2 === 0) {
          const f = this.face.detectForVideo(v, now).detections[0];
          if (f) {
            const b = f.boundingBox, vw = v.videoWidth, vh = v.videoHeight;
            this.onFace({ cx: 1 - (b.originX + b.width / 2) / vw, cy: (b.originY + b.height / 2) / vh, w: b.width / vw, vw, vh });
          }
        }
      } catch (e) { /* un cuadro que fallo: sigue con el proximo */ }
    }
    this.next();
  }

  /** res: resultado de HandLandmarker (landmarks y worldLandmarks). now: ms. */
  process(res, now) {
    const lms = res.landmarks || [], wl = res.worldLandmarks || [];
    // cada mano detectada se une con la del cuadro anterior que estaba mas cerca (por la muneca)
    const seen = lms.map((lm, i) => ({ lm, w: wl[i] || null, wrist: { x: 1 - lm[0].x, y: lm[0].y } }));
    const used = new Set();
    const tracks = seen.map((s) => {
      let best = null, bd = 0.25;
      this.tracks.forEach((t) => { if (used.has(t.id)) return; const d = d2(t.wrist, s.wrist); if (d < bd) { bd = d; best = t; } });
      const t = best || { id: this.nextId++, fx: new OneEuro(), fy: new OneEuro(), state: 'none', cand: 'none', candN: 0, born: now, at: null };
      used.add(t.id);
      const h = leerMano(s.lm, s.w, t.state);
      // el gesto cambia solo si se sostiene 3 cuadros seguidos
      if (h.state === t.cand) t.candN += 1; else { t.cand = h.state; t.candN = 1; }
      const prevState = t.state;
      if (t.candN >= 3 || ((h.state === 'pinch' || h.state === 'tap') && t.candN >= 2)) t.state = h.state;
      t.clicked = t.state === 'tap' && prevState !== 'tap';
      // el punto que sigue: entre los dedos si pellizca, la punta del indice si apunta, si no el centro de la mano.
      // Si cambia de gesto, el filtro arranca de cero (son puntos distintos: mezclarlos haria saltar el grafico)
      // apuntar y hacer clic usan el mismo punto (la punta del indice): el filtro sigue sin cortarse entre los dos
      const spot = (st) => (st === 'pinch' ? 'pinch' : st === 'point' || st === 'tap' ? 'point' : 'other');
      if (spot(t.state) !== spot(prevState)) { t.fx = new OneEuro(); t.fy = new OneEuro(); }
      const raw = toScreen(h.spots[spot(t.state)]);
      const f = { x: t.fx.filter(raw.x, now), y: t.fy.filter(raw.y, now) };
      // zona muerta: el punto solo se mueve si el dedo se alejo mas que DEAD; y entonces sigue sin saltar
      let at = f;
      if (t.at && spot(prevState) === spot(t.state)) {
        const dx = f.x - t.at.x, dy = f.y - t.at.y, d = Math.hypot(dx, dy);
        at = d > DEAD ? { x: t.at.x + dx * (d - DEAD) / d, y: t.at.y + dy * (d - DEAD) / d } : t.at;
      }
      return Object.assign(t, { wrist: s.wrist, P: h.P.map(toScreen), prevAt: t.at && prevState === t.state ? t.at : null, at, size: h.size, lost: 0 });
    });
    // una mano que la camara dejo de ver un instante se mantiene unos cuadros con su ultimo gesto (quieta)
    this.tracks.forEach((t) => {
      if (used.has(t.id) || (t.lost || 0) >= GRACE) return;
      tracks.push(Object.assign(t, { lost: (t.lost || 0) + 1, prevAt: t.at }));
    });
    this.tracks = tracks;

    const pinching = tracks.filter((t) => t.state === 'pinch');
    // una mano pellizcando: agarra el grafico en ese punto (inicio, movimiento y fin, con la posicion en pantalla)
    const single = pinching.length === 1 ? pinching[0] : null;
    if (this.grabId !== null && (!single || single.id !== this.grabId)) {
      this.onAction({ t: 'grab', phase: 'end', x: this.grabAt.x, y: this.grabAt.y }); this.grabId = null;
    }
    if (single) {
      this.onAction({ t: 'grab', phase: this.grabId === null ? 'start' : 'move', x: single.at.x, y: single.at.y });
      this.grabId = single.id; this.grabAt = single.at;
    }
    if (pinching.length === 2) {
      const [a, b] = pinching, dist = d2(a.at, b.at), ang = Math.atan2(b.at.y - a.at.y, b.at.x - a.at.x);
      if (this.two) {
        const f = clamp(dist / this.two.dist, 0.8, 1.25);
        if (Math.abs(f - 1) > 0.003) this.onAction({ t: 'zoom', f });
        let da = ang - this.two.ang; if (da > Math.PI) da -= 2 * Math.PI; if (da < -Math.PI) da += 2 * Math.PI;
        if (Math.abs(da) > 0.004) this.onAction({ t: 'rot', dx: clamp(da * 0.35, -0.08, 0.08), dy: 0 });
      }
      this.two = { dist, ang };
    } else this.two = null;
    // puno: girar el holograma
    tracks.forEach((t) => {
      if (t.state !== 'fist' || !t.prevAt) return;
      const dx = t.at.x - t.prevAt.x, dy = t.at.y - t.prevAt.y;
      if (Math.hypot(dx, dy) < 0.15) this.onAction({ t: 'rot', dx: dx * 1.2, dy: dy * 1.2 });
    });
    // clic: pulgar con el dedo medio, donde apunta el indice (una vez por gesto)
    tracks.forEach((t) => { if (t.clicked && !t.lost) this.onAction({ t: 'click', x: t.at.x, y: t.at.y }); });
    // apuntar con el indice: mira sobre la vela
    const pointer = tracks.find((t) => t.state === 'point' || t.state === 'tap');
    if (pointer) { this.pointing = true; this.onAction({ t: 'point', x: pointer.at.x, y: pointer.at.y }); }
    else if (this.pointing) { this.pointing = false; this.onAction({ t: 'point', x: null, y: null }); }

    // palma abierta: deslizar rapido o quedarse quieta
    const open = tracks.length === 1 && tracks[0].state === 'open' && !tracks[0].lost && now - tracks[0].born > 250 ? tracks[0] : null;
    if (open) {
      this.hist.push({ t: now, x: open.at.x, y: open.at.y });
      this.hist = this.hist.filter((q) => now - q.t < 1700);
      const recent = this.hist.filter((q) => now - q.t < 220);
      if (recent.length > 2 && now > this.cool) {
        const a = recent[0], b = recent[recent.length - 1], dt = Math.max(0.05, (b.t - a.t) / 1000);
        const vx = (b.x - a.x) / dt, vy = (b.y - a.y) / dt;
        if (Math.abs(vx) > 1.1 && Math.abs(b.x - a.x) > 0.14 && Math.abs(vx) > Math.abs(vy) * 1.6) {
          this.onAction({ t: 'asset', dir: vx > 0 ? 1 : -1 }); this.cool = now + 1000; this.hist = [];
        } else if (Math.abs(vy) > 1.1 && Math.abs(b.y - a.y) > 0.14 && Math.abs(vy) > Math.abs(vx) * 1.6) {
          this.onAction({ t: 'tf', dir: vy < 0 ? 1 : -1 }); this.cool = now + 1000; this.hist = [];
        }
      }
      const still = this.hist.length > 6 && this.hist.every((q) => Math.hypot(q.x - open.at.x, q.y - open.at.y) < 0.03);
      if (!still) this.holdStart = now;
      const p = clamp((now - this.holdStart - 300) / 1200, 0, 1);
      this.onHold(p);
      if (p >= 1 && now > this.cool) { this.onAction({ t: 'reset' }); this.cool = now + 2500; this.holdStart = now; this.hist = []; }
    } else { this.hist = []; this.holdStart = now; this.onHold(0); }

    this.onCursor(tracks.map((t) => ({ x: t.at.x, y: t.at.y, state: t.state, pts: t.lost ? null : t.P })));
  }
}
