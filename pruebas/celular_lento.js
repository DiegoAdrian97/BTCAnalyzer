/*
 * Prueba la app como en un iPhone con red lenta, sin internet: la sirve como Vercel (brotli, ETag y los headers de
 * JavascriptVersion/vercel.json) y reemplaza a los exchanges por unos falsos con velas inventadas.
 *
 *   npm i playwright && npx playwright install chromium        (una vez)
 *   node pruebas/celular_lento.js [3g|4g|lejos]                (sin variables de proxy: HTTPS_PROXY y compania)
 *
 * Muestra, para la primera visita (sin nada guardado) y la segunda (con el telefono "caliente"): cuando pinta, cuando
 * aparece el grafico, cuantos pedidos y KB a la app y a los exchanges, y cuanto se traba el hilo principal (CPU 4x).
 */
const http = require('http'), https = require('https'), fs = require('fs'), path = require('path'), zlib = require('zlib');
const crypto = require('crypto'), os = require('os'), { execSync } = require('child_process');
const { chromium, devices } = require('playwright');
const RAIZ = path.join(__dirname, '..', 'JavascriptVersion');
const RED = { '3g': [562, 180], '4g': [150, 1200], lejos: [300, 3000] }[process.argv[2] || '3g'];   // latencia ms, KB/s
const LOG = [];

// ---- la app, como la sirve Vercel
const reglas = (() => { try { return JSON.parse(fs.readFileSync(path.join(RAIZ, 'vercel.json'))).headers || []; } catch (e) { return []; } })();
const aRe = (src) => new RegExp('^' + src.replace(/\(\.\*\)/g, '.*').replace(/\//g, '\\/') + '$');
const TIPOS = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.json': 'application/json', '.png': 'image/png', '.txt': 'text/plain' };
const app = http.createServer((q, r) => {
  const p = new URL(q.url, 'http://x').pathname.replace(/^\/$/, '/index.html'), f = path.join(RAIZ, p);
  if (p.startsWith('/api/') || !f.startsWith(RAIZ) || !fs.existsSync(f)) { r.writeHead(404); return r.end('{}'); }
  const buf = fs.readFileSync(f), etag = `"${crypto.createHash('md5').update(buf).digest('hex')}"`;
  const h = { 'Content-Type': TIPOS[path.extname(f)] || 'application/octet-stream', ETag: etag, 'Cache-Control': 'public, max-age=0, must-revalidate' };
  for (const g of reglas) if (aRe(g.source).test(p)) for (const x of g.headers) h[x.key] = x.value;
  if (q.headers['if-none-match'] === etag) { r.writeHead(304, h); LOG.push(['app', p, 304, 0]); return r.end(); }
  let cuerpo = buf;
  if (/br/.test(q.headers['accept-encoding'] || '') && /text|javascript|json/.test(h['Content-Type'])) { cuerpo = zlib.brotliCompressSync(buf); h['Content-Encoding'] = 'br'; }
  r.writeHead(200, h); r.end(cuerpo); LOG.push(['app', p, 200, cuerpo.length]);
}).listen(8830);

// ---- exchanges falsos (https en 8443; Chrome resuelve todos los dominios aca)
const cert = path.join(os.tmpdir(), 'ab-prueba-cert');
if (!fs.existsSync(cert + '.pem')) execSync(`openssl req -x509 -newkey rsa:2048 -nodes -keyout ${cert}.key -out ${cert}.pem -days 30 -subj /CN=localhost`, { stdio: 'ignore' });
const PR = {}; ['BTC', 'ZEC', 'SOL', 'XRP', 'BABA', 'NVDA', 'GOOGL', 'AMD', 'AAPL', 'MSFT', 'AMZN', 'SPCX', 'META', 'TSLA', 'QQQ', 'SPY', 'MSTR', 'MELI'].forEach((m, i) => { PR[`${m}USDT`] = 50 + i * 37; });
const TF = { '5m': 3e5, '15m': 9e5, '30m': 18e5, '1h': 36e5, '4h': 144e5, '1d': 864e5 };
const falsos = https.createServer({ key: fs.readFileSync(cert + '.key'), cert: fs.readFileSync(cert + '.pem') }, (q, r) => {
  const u = new URL(q.url, `https://${q.headers.host}`), cors = { 'Access-Control-Allow-Origin': '*' };
  let body = null;
  if (u.pathname === '/fapi/v1/klines') {
    const s = u.searchParams.get('symbol'), ms = TF[u.searchParams.get('interval')], lim = +u.searchParams.get('limit');
    let t = Math.floor((+u.searchParams.get('startTime') || Date.now() - lim * ms) / ms) * ms, c = PR[s] || 100; const out = [];
    for (; t < Date.now() && out.length < lim; t += ms) { const o = c; c *= 1 + Math.sin(t / ms / 7) * 0.002; out.push([t, `${o}`, `${Math.max(o, c) * 1.001}`, `${Math.min(o, c) * 0.999}`, `${c}`, '10', t + ms - 1]); }
    body = JSON.stringify(out);
  } else if (/ticker\/price/.test(u.pathname)) body = JSON.stringify(Object.entries(PR).map(([symbol, c]) => ({ symbol, price: `${c}` })));
  else if (/ticker\/24hr/.test(u.pathname)) { const c = PR[u.searchParams.get('symbol')] || 100; body = JSON.stringify({ lastPrice: `${c}`, openPrice: `${c / 1.012}` }); }
  if (body === null) { r.writeHead(404, cors); LOG.push(['ex', u.host + u.pathname, 404, 0]); return r.end('{}'); }
  const z = zlib.gzipSync(body); r.writeHead(200, { ...cors, 'Content-Type': 'application/json', 'Content-Encoding': 'gzip' }); r.end(z); LOG.push(['ex', u.host + u.pathname, 200, z.length]);
}).listen(8443);

(async () => {
  const b = await chromium.launch({ args: ['--no-proxy-server', '--host-resolver-rules=MAP * 127.0.0.1:8443, EXCLUDE localhost'] });
  const ctx = await b.newContext({ ...devices['iPhone 13'], ignoreHTTPSErrors: true });
  const p = await ctx.newPage(), cdp = await ctx.newCDPSession(p), errores = [];
  p.on('pageerror', (e) => errores.push(e.message));
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: RED[0], downloadThroughput: RED[1] * 1024, uploadThroughput: RED[1] * 512 });
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
  await p.addInitScript(() => { window.__lt = 0; try { new PerformanceObserver((l) => l.getEntries().forEach((e) => { window.__lt += e.duration; })).observe({ type: 'longtask', buffered: true }); } catch (e) { /* sin medicion */ } });
  const kb = (xs) => Math.round(xs.reduce((a, x) => a + x[3], 0) / 1024);
  for (const nombre of ['1a visita', '2a visita']) {
    await p.goto('about:blank'); LOG.length = 0;
    const t0 = Date.now(); await p.goto('http://localhost:8830/index.html', { waitUntil: 'commit' });
    let fcp = null, graf = null;
    while (Date.now() - t0 < 120000 && graf === null) {
      const r = await p.evaluate(() => [(performance.getEntriesByName('first-contentful-paint')[0] || {}).startTime, !!document.querySelector('#chart canvas')]).catch(() => [null, false]);
      if (r[0] && !fcp) fcp = Math.round(r[0]); if (r[1]) graf = Date.now() - t0;
      await new Promise((x) => setTimeout(x, 100));
    }
    const lt0 = await p.evaluate(() => window.__lt); await new Promise((x) => setTimeout(x, 30000)); const lt1 = await p.evaluate(() => window.__lt);
    const a = LOG.filter((x) => x[0] === 'app'), e = LOG.filter((x) => x[0] === 'ex');
    console.log(`${nombre}: pinta ${fcp} ms · gráfico ${graf} ms · app ${a.length} pedidos (${kb(a)} KB, ${a.filter((x) => x[2] === 304).length} sin cambios) · exchanges ${e.length} pedidos (${kb(e)} KB) · hilo principal trabado ${Math.round(lt1 - lt0)} ms en 30 s`);
  }
  console.log(errores.length ? `errores: ${errores.slice(0, 5).join(' | ')}` : 'sin errores en la página');
  await b.close(); app.close(); falsos.close();
})();
