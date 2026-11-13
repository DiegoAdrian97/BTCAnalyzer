/*
 * Service worker: la app abre sin conexion y mas rapido.
 * - La pagina: primero la red (asi siempre es la ultima version); si no responde en 3 s o no hay conexion, la guardada.
 * - Lo que tiene huella o version en el nombre (lib/, p-*.css/js, los .js con ?v=): del telefono, sin preguntar.
 * - Todo lo demas (exchanges, api/, version.txt, los .json): pasa directo, sin cache.
 */
const CACHE = 'analista-btc-2';   // cambio de nombre: borra lo guardado antes (por si quedo algo roto)
const FIJO = /^\/(lib\/.+|p-[0-9a-f]+\.(css|js)|icono-\d+\.png|manifest\.json)$/;
const CON_VERSION = /^\/(app|worker|analisis|datos|indicadores|aprendizaje|fuerte)\.js$/;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k);
  await self.clients.claim();
})()));

async function pagina(req) {
  const c = await caches.open(CACHE);
  try {
    const r = await Promise.race([fetch(req), new Promise((_, no) => setTimeout(() => no(new Error('lenta')), 3000))]);
    if (r.ok) {
      const copia = r.clone();
      // se guarda como '/' y se borra lo de versiones anteriores que esta pagina ya no usa
      copia.text().then(async (html) => {
        await c.put('/', new Response(html, { headers: { 'Content-Type': 'text/html; charset=utf-8' } }));
        const usa = new Set([...html.matchAll(/(?:src|href)="([^"]+)"/g)].map((m) => new URL(m[1], self.location.origin).href));
        for (const k of await c.keys()) {
          const u = new URL(k.url);
          if (u.pathname !== '/' && !usa.has(k.url) && (/^\/p-/.test(u.pathname) || CON_VERSION.test(u.pathname))) await c.delete(k);
        }
      }).catch(() => {});
    }
    return r;
  } catch (e) {
    return (await c.match('/')) || fetch(req);
  }
}
async function guardado(req) {
  const c = await caches.open(CACHE), hit = await c.match(req);
  if (hit) return hit;
  const r = await fetch(req);
  // solo se guarda si es lo que se pidio (un .css que llega como pagina o error no se queda un año en el telefono)
  const tipo = r.headers.get('content-type') || '';
  if (r.ok && !(/\.css$/.test(new URL(req.url).pathname) && !/css/.test(tipo))) c.put(req, r.clone());
  return r;
}
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const u = new URL(req.url);
  if (u.origin !== self.location.origin) return;
  if (req.mode === 'navigate') return e.respondWith(pagina(req));
  if (FIJO.test(u.pathname) || (CON_VERSION.test(u.pathname) && u.search)) e.respondWith(guardado(req));
});
