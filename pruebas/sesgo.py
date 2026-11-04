"""Mide si las noticias salen buenas o malas como corresponde (pruebas/titulares.json: activo, titular, lo esperado)
y que Python y JavaScript den lo mismo. python pruebas/sesgo.py (sale con error si acierta menos de 90% o difieren)."""
import json, os, subprocess, sys
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import noticias as n  # noqa: E402

# titulares.json: con los que se armaron las reglas; titulares_control.json: escritos despues, para ver que generalicen
T = [x for f in ("titulares.json", "titulares_control.json") for x in json.load(open(os.path.join(RAIZ, "pruebas", f), encoding="utf-8"))]
feed = lambda a: "cripto" if a == "BTC" else "accion:" + a
py = [n.sesgo(t, n.tema(t, feed(a)), feed(a)) for a, t, _ in T]
js = json.loads(subprocess.run(["node", "-e", """const C = require(process.argv[1] + '/JavascriptVersion/api/contexto.js');
const T = JSON.parse(require('fs').readFileSync(0, 'utf8')); const f = (a) => (a === 'BTC' ? 'cripto' : 'accion:' + a);
console.log(JSON.stringify(T.map(([a, t]) => C.sesgo(t, C.tema(t, f(a)), f(a)))));""", RAIZ], input=json.dumps(T), capture_output=True, text=True).stdout or "[]")
mal = [(a, t, e, p) for (a, t, e), p in zip(T, py) if p != e]
por = {}
for (a, _, e), p in zip(T, py):
    por.setdefault(a, [0, 0]); por[a][0] += p == e; por[a][1] += 1
print("aciertos:", " · ".join(f"{a} {k}/{m}" for a, (k, m) in por.items()), f"· total {len(T) - len(mal)}/{len(T)}")
for a, t, e, p in mal:
    print(f"  {a}: esperaba {e}, dio {p} | {t}")
dif = [T[i][1] for i in range(len(T)) if i >= len(js) or js[i] != py[i]]
if dif:
    print("Python y JS difieren en:", *dif[:10], sep="\n  ")
sys.exit(1 if dif or len(mal) > 0.1 * len(T) else 0)
