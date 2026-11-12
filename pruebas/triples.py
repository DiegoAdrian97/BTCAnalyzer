"""Prueba de las figuras triple techo y triple piso (indicadores.py y indicadores.js, deben dar lo mismo).
python pruebas/triples.py"""
import json, os, subprocess, sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import indicadores as ind  # noqa: E402


def camino(puntos, n_por_tramo=12, t0=1_700_000_000_000, ms=3_600_000):
    """Velas que van en linea recta entre los puntos dados (con un poco de mecha)."""
    out, t = [], t0
    for (a, b) in zip(puntos, puntos[1:]):
        for k in range(n_por_tramo):
            o = a + (b - a) * k / n_por_tramo
            c = a + (b - a) * (k + 1) / n_por_tramo
            out.append([t, round(o, 2), round(max(o, c) * 1.0008, 2), round(min(o, c) * 0.9992, 2), round(c, 2), 100.0])
            t += ms
    return out


def figura(bars):
    h, l, c = [b[2] for b in bars], [b[3] for b in bars], [b[4] for b in bars]
    atr = ind.atr_w(h, l, c)
    return ind.patron_grafico(bars, ind.zigzag(bars), atr[-1])


# tendencia que sube y tres techos en ~72.000 con dos valles en ~68.000; despues vuelve a bajar hacia el cuello
techo = camino([60000, 66000, 72000, 68000, 72050, 68200, 71950, 69500])
piso = camino([80000, 74000, 68000, 72000, 67950, 71800, 68050, 70500])
casos = {"techo": techo, "piso": piso}
py = {k: figura(v) for k, v in casos.items()}
assert py["techo"] and py["techo"]["nombre"] == "Triple techo", py["techo"]
assert py["piso"] and py["piso"]["nombre"] == "Triple piso", py["piso"]
assert len(py["techo"]["puntos"]) == 3 and py["techo"]["objetivo"] < 68000
# lo mismo en JS
js = subprocess.run(["node", "-e", f"""
const vm = require('vm'), fs = require('fs'), c = {{ console }}; c.self = c; vm.createContext(c);
vm.runInContext(fs.readFileSync({json.dumps(os.path.join(RAIZ, 'JavascriptVersion', 'indicadores.js'))}, 'utf8'), c);
const I = c.Ind;
const casos = {json.dumps(casos)}, out = {{}};
for (const k in casos) {{ const b = casos[k], atr = I.atrW(b.map((x) => x[2]), b.map((x) => x[3]), b.map((x) => x[4])); out[k] = I.patronGrafico(b, I.zigzag(b), atr[atr.length - 1]); }}
process.stdout.write(JSON.stringify(out));
"""], capture_output=True, text=True, check=True).stdout
js = json.loads(js)
for k in casos:
    a, b = py[k], js[k]
    assert a["nombre"] == b["nombre"] and a["objetivo"] == b["objetivo"] and a["descripcion"] == b["descripcion"], (k, a, b)
print(f"triples: todo bien ({py['techo']['nombre']} objetivo {py['techo']['objetivo']}; {py['piso']['nombre']} objetivo {py['piso']['objetivo']})")
