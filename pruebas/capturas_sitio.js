// Capturas de la app publicada (corre en GitHub Actions, que llega a Binance y a Vercel): pagina entera en 390 y 1440 px,
// con todo lo desplegable abierto, y el texto visible de cada seccion. Sirve para revisar que se muestra.
// Uso: node pruebas/capturas_sitio.js [url]
const fs = require('fs');
const { chromium } = require('playwright');

const URL = process.argv[2] || 'https://btcanalyzerjs.vercel.app/';

(async () => {
  fs.mkdirSync('capturas', { recursive: true });
  const b = await chromium.launch();
  for (const [nombre, vp] of [['celu', { width: 390, height: 844 }], ['escritorio', { width: 1440, height: 900 }]]) {
    const ctx = await b.newContext({ viewport: vp, deviceScaleFactor: 1, colorScheme: 'dark', locale: 'es-AR', timezoneId: 'America/Argentina/Buenos_Aires' });
    const p = await ctx.newPage();
    const errores = [];
    p.on('pageerror', (e) => errores.push(String(e)));
    await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 90000 });
    await p.waitForSelector('#respuesta:not([hidden])', { timeout: 120000 }).catch(() => errores.push('sin #respuesta a los 120 s'));
    await p.waitForTimeout(8000);
    await p.screenshot({ path: `capturas/${nombre}_inicio.png`, fullPage: true });
    await p.evaluate(() => document.querySelectorAll('details').forEach((d) => { d.open = true; }));
    await p.waitForTimeout(4000);
    await p.screenshot({ path: `capturas/${nombre}_todo.png`, fullPage: true });
    const secciones = await p.evaluate(() => [...document.querySelectorAll('main section, main details, body > section, body > details, section, details')]
      .filter((el) => !el.parentElement.closest('section, details') && el.offsetHeight > 0)
      .map((el) => ({ id: el.id || el.className, alto: el.offsetHeight, texto: (el.innerText || '').replace(/\s+\n/g, '\n').slice(0, 2500) })));
    fs.writeFileSync(`capturas/${nombre}_secciones.json`, JSON.stringify(secciones, null, 1));
    console.log(`${nombre}: ${secciones.length} secciones visibles, alto total ${await p.evaluate(() => document.body.scrollHeight)} px; errores: ${errores.join(' | ') || 'ninguno'}`);
    for (const s of secciones) console.log(`  ${String(s.id).slice(0, 40).padEnd(40)} ${String(s.alto).padStart(5)} px · ${s.texto.split('\n')[0].slice(0, 80)}`);
    await ctx.close();
  }
  await b.close();
})();
