"""Prueba que la version Python y la JavaScript den lo mismo (mismas filas, mismos numeros) con velas inventadas
(semilla fija). La corre GitHub Actions en cada push (.github/workflows/paridad.yml); a mano: python pruebas/paridad.py
Necesita node. Sale con error si algo difiere."""
import json, math, os, random, subprocess, sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import analisis_btc as A, fuerte, indicadores as ind, termometro  # noqa: E402

random.seed(7)


def velas(n, ms, p0, vol, t0=1_700_000_000_000):
    out, p = [], p0
    for i in range(n):
        o = p; p *= math.exp(random.gauss(0.0002, vol))
        h, l = max(o, p) * (1 + abs(random.gauss(0, vol / 3))), min(o, p) * (1 - abs(random.gauss(0, vol / 3)))
        out.append([t0 + i * ms, round(o, 2), round(h, 2), round(l, 2), round(p, 2), round(random.uniform(50, 500), 3)])
    return out


H1, H4, D1 = velas(2400, 3_600_000, 60000, 0.006), velas(700, 14_400_000, 60000, 0.012), velas(1600, 86_400_000, 9000, 0.03)
ALT = [[b[0], b[1] / 50000, b[2] / 50000, b[3] / 50000, b[4] / 50000, b[5]] for b in D1]
AHORA = D1[-1][0] + 3_600_000


def py():
    piv = ind.zigzag(H4)
    raw = {"oi": [[b[0] + 3_600_000, 1000 + i] for i, b in enumerate(H1[-40:])], "ls": [1.2 + i / 100 for i in range(25)],
           "taker": [{"buy": 120 + i, "sell": 100} for i in range(4)], "top": 1.3, "funding": 0.0001, "funding7": -0.00002, "fundingFuente": "BingX"}
    return {
        "calificar": ind.calificar(H1)[:2], "zigzag": piv, "fvg": ind.fvg(H4), "divergencias": ind.divergencias(H4, piv),
        "fibonacci": A.fibonacci(H4),
        "termometro": termometro.termometro([b[4] for b in D1], D1[-1][4] * 1.01, now_ms=AHORA, f7=-0.00001),
        "termometro_alt": termometro.termometro_alt("XRP", ALT[-600:], ALT[-1][4], now_ms=AHORA),
        "fuerte": fuerte.prever(H1),
        "_ctx_raw": raw,
    }


JS = r"""
const R = process.argv[1];
globalThis.Ind = require(R + '/JavascriptVersion/indicadores.js'); globalThis.Aprendizaje = require(R + '/JavascriptVersion/aprendizaje.js');
const Fu = require(R + '/JavascriptVersion/fuerte.js'); const A = require(R + '/JavascriptVersion/analisis.js');
const T = require(R + '/JavascriptVersion/termometro.json'), M = require(R + '/JavascriptVersion/modelo_fuerte.json');
const d = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const piv = Ind.zigzag(d.H4), c = Ind.calificar(d.H1);
console.log(JSON.stringify({
  calificar: [c[0], c[1]], zigzag: piv, fvg: Ind.fvg(d.H4), divergencias: Ind.divergencias(d.H4, piv), fibonacci: A.fibonacci(d.H4),
  termometro: A.termometro(d.D1.map((b) => b[4]), d.D1[d.D1.length - 1][4] * 1.01, T, null, d.AHORA, -0.00001),
  termometro_alt: A.termometroAlt('XRP', d.ALT.slice(-600), d.ALT[d.ALT.length - 1][4], T, d.AHORA),
  fuerte: Fu.prever(M, d.H1), contexto: A.context(d.raw, d.H1),
}));
"""


def igual(a, b, ruta, err):
    if isinstance(a, tuple):
        a = list(a)
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None or not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or abs(a - b) > 1e-6 * max(1, abs(a)):
            err.append(f"{ruta}: {a!r} != {b!r}")
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            igual(a.get(k), b.get(k), f"{ruta}.{k}", err)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            err.append(f"{ruta}: largo {len(a)} != {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            igual(x, y, f"{ruta}[{i}]", err)
    elif a != b:
        err.append(f"{ruta}: {a!r} != {b!r}")


def main():
    p = py()
    raw = p.pop("_ctx_raw")
    entrada = {"H1": H1, "H4": H4, "D1": D1, "ALT": ALT, "AHORA": AHORA, "raw": raw}
    out = subprocess.run(["node", "-e", JS, RAIZ], input=json.dumps(entrada), capture_output=True, text=True)
    if out.returncode:
        raise SystemExit("node fallo:\n" + out.stderr[-2000:])
    js = json.loads(out.stdout)
    js_ctx = js.pop("contexto")
    err = []
    for k in p:
        igual(json.loads(json.dumps(p[k])), js.get(k), k, err)
    print(f"comparados: {', '.join(p)} · contexto ({len(js_ctx[0])} filas en JS)")
    if err:
        print(f"{len(err)} diferencias:\n  " + "\n  ".join(err[:40]))
        raise SystemExit(1)
    print("Python y JavaScript dan lo mismo.")


if __name__ == "__main__":
    main()
