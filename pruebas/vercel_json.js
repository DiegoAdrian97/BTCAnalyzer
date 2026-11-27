// Que vercel.json sea valido para Vercel: los "source" de headers se leen con path-to-regexp 6.1.0 (el que usa Vercel), que
// no acepta un grupo dentro de otro. Un patron asi rompio todos los deploys del 25 al 27/11/2026 sin que nadie lo viera.
// Uso: node pruebas/vercel_json.js   (instala path-to-regexp@6.1.0 en una carpeta temporal si no esta)
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync } = require('child_process');

const dir = path.join(os.tmpdir(), 'ptr-vercel');
if (!fs.existsSync(path.join(dir, 'node_modules', 'path-to-regexp'))) {
  fs.mkdirSync(dir, { recursive: true });
  execSync('npm install --silent --no-save --prefix . path-to-regexp@6.1.0', { cwd: dir, stdio: 'ignore' });
}
const { pathToRegexp } = require(path.join(dir, 'node_modules', 'path-to-regexp'));
const v = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'JavascriptVersion', 'vercel.json'), 'utf8'));
const fuentes = [...(v.headers || []), ...(v.rewrites || []), ...(v.redirects || [])].map((h) => h.source);
const mal = [];
for (const s of fuentes) {
  try { pathToRegexp(s); } catch (e) { mal.push(`${s} → ${e.message}`); }
}
if (mal.length) {
  console.error('vercel.json: patrones inválidos (Vercel no va a publicar):\n  ' + mal.join('\n  '));
  process.exit(1);
}
console.log(`vercel.json: todo bien (${fuentes.length} patrones)`);
