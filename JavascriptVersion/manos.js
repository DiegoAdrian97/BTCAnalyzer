/*
 * Manos y cabeza con la camara (MediaPipe, corre en el navegador: nada sale de la compu o el telefono).
 *
 * Gestos (la imagen se mira como un espejo, asi que derecha es tu derecha):
 * - pellizco (pulgar con indice) y mover: arrastrar el grafico
 * - pellizco con las dos manos, separar o juntar: zoom
 * - puno cerrado y mover: girar el holograma
 * - palma abierta y deslizar rapido de costado: cambiar de cripto; arriba o abajo: cambiar de temporalidad
 * - palma abierta quieta 1,5 s: volver a la vista inicial
 */
const VISION = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.1.1';
const HAND_MODEL = 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task';
const FACE_MODEL = 'https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite';

const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });

/** Que hace una mano: pellizco, puno, palma abierta o nada claro. */
export function leerMano(lm, prevPinch = false) {
  const P = lm.map((p) => ({ x: 1 - p.x, y: p.y }));          // espejo: como mirarse
  const size = dist(P[0], P[9]) || 1e-3;
  const pinchR = dist(P[4], P[8]) / size;
  const ext = (tip, pip) => dist(P[0], P[tip]) > dist(P[0], P[pip]) * 1.15;
  const fingers = [ext(8, 6), ext(12, 10), ext(16, 14), ext(20, 18)];
  const nExt = fingers.filter(Boolean).length;
  const indexOut = dist(P[0], P[8]) > size * 1.0;
  // con histeresis: cuesta un poco mas soltar que agarrar, asi no parpadea
  const pinch = indexOut && pinchR < (prevPinch ? 0.42 : 0.3);
  const fist = !pinch && nExt === 0 && dist(P[0], P[8]) < size * 1.05 && dist(P[0], P[12]) < size * 1.05;
  const open = !pinch && nExt === 4 && pinchR > 0.55;
  return { P, size, pinch, fist, open, state: pinch ? 'pinch' : fist ? 'fist' : open ? 'open' : 'none', at: pinch ? mid(P[4], P[8]) : P[9] };
}

export class Manos {
  constructor({ video, onAction, onCursor, onHold, onFace, onState }) {
    Object.assign(this, { video, onAction, onCursor, onHold, onFace, onState });
    this.running = false; this.hands = null; this.face = null; this.useFace = false;
    this.prev = new Map(); this.hist = []; this.cool = 0; this.holdStart = 0; this.zoomD = null; this.frame = 0;
  }

  async start({ cara = false } = {}) {
    if (this.running) return;
    this.onState('Pidiendo permiso para la cámara…');
    this.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
    this.video.srcObject = this.stream;
    await this.video.play();
    this.onState('Cargando el reconocimiento de manos…');
    const { FilesetResolver, HandLandmarker, FaceDetector } = await import(`${VISION}/vision_bundle.mjs`);
    this.FaceDetector = FaceDetector;
    this.fileset = await FilesetResolver.forVisionTasks(`${VISION}/wasm`);
    const make = (delegate) => HandLandmarker.createFromOptions(this.fileset, {
      baseOptions: { modelAssetPath: HAND_MODEL, delegate }, runningMode: 'VIDEO', numHands: 2,
      minHandDetectionConfidence: 0.6, minHandPresenceConfidence: 0.6, minTrackingConfidence: 0.5,
    });
    try { this.hands = await make('GPU'); } catch (e) { this.hands = await make('CPU'); }
    this.running = true;
    await this.setFace(cara);
    this.onState('✋ Manos activas: pellizcá para agarrar el gráfico');
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
    this.stream = null; this.prev.clear(); this.onCursor([]); this.onHold(0);
  }

  loop() {
    if (!this.running) return;
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
    this.raf = requestAnimationFrame(() => this.loop());
  }

  process(res, now) {
    const lms = res.landmarks || [];
    const hands = lms.map((lm, i) => {
      const id = (res.handedness && res.handedness[i] && res.handedness[i][0] && res.handedness[i][0].categoryName) || String(i);
      const prev = this.prev.get(id);
      const h = leerMano(lm, prev ? prev.pinch : false);
      h.id = id;
      // suavizado: los puntos de la camara tiemblan un poco
      if (prev) { h.at = { x: prev.at.x + (h.at.x - prev.at.x) * 0.55, y: prev.at.y + (h.at.y - prev.at.y) * 0.55 }; }
      return h;
    });
    const seen = new Set(hands.map((h) => h.id));
    [...this.prev.keys()].forEach((k) => { if (!seen.has(k)) this.prev.delete(k); });

    const pinching = hands.filter((h) => h.pinch);
    const clampD = (d) => Math.max(-0.12, Math.min(0.12, d));     // un salto grande es un error de la camara
    if (pinching.length === 2) {
      const d = dist(pinching[0].at, pinching[1].at);
      if (this.zoomD) this.onAction({ t: 'zoom', f: Math.max(0.85, Math.min(1.18, d / this.zoomD)) });
      this.zoomD = d;
    } else {
      this.zoomD = null;
      hands.forEach((h) => {
        const p = this.prev.get(h.id);
        if (!p || p.state !== h.state) return;               // el primer cuadro de un gesto no mueve nada
        const dx = clampD(h.at.x - p.at.x), dy = clampD(h.at.y - p.at.y);
        if (h.pinch) this.onAction({ t: 'pan', dx, dy });
        else if (h.fist) this.onAction({ t: 'rot', dx, dy });
      });
    }
    // palma abierta: deslizar o quedarse quieta
    const open = hands.find((h) => h.open);
    if (open && hands.length === 1) {
      this.hist.push({ t: now, x: open.at.x, y: open.at.y });
      this.hist = this.hist.filter((q) => now - q.t < 1600);
      const recent = this.hist.filter((q) => now - q.t < 280);
      if (recent.length > 2 && now > this.cool) {
        const dx = recent[recent.length - 1].x - recent[0].x, dy = recent[recent.length - 1].y - recent[0].y;
        if (Math.abs(dx) > 0.2 && Math.abs(dx) > Math.abs(dy) * 1.5) { this.onAction({ t: 'asset', dir: dx > 0 ? 1 : -1 }); this.cool = now + 1100; this.hist = []; }
        else if (Math.abs(dy) > 0.2 && Math.abs(dy) > Math.abs(dx) * 1.5) { this.onAction({ t: 'tf', dir: dy < 0 ? 1 : -1 }); this.cool = now + 1100; this.hist = []; }
      }
      const still = this.hist.length > 5 && this.hist.every((q) => Math.hypot(q.x - open.at.x, q.y - open.at.y) < 0.035);
      if (!still) this.holdStart = now;
      const p = Math.min(1, (now - this.holdStart - 300) / 1200);
      this.onHold(Math.max(0, p));
      if (p >= 1 && now > this.cool) { this.onAction({ t: 'reset' }); this.cool = now + 2500; this.holdStart = now; this.hist = []; }
    } else { this.hist = []; this.holdStart = now; this.onHold(0); }

    hands.forEach((h) => this.prev.set(h.id, { at: h.at, pinch: h.pinch, state: h.state }));
    this.onCursor(hands.map((h) => ({ x: h.at.x, y: h.at.y, state: h.state, pts: h.P })));
  }
}
