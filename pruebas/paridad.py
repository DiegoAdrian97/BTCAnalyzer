"""Prueba que la version Python y la JavaScript den lo mismo (mismas filas, mismos numeros) con velas inventadas
(semilla fija). La corre GitHub Actions en cada push (.github/workflows/paridad.yml); a mano: python pruebas/paridad.py
Necesita node. Sale con error si algo difiere."""
import json, math, os, random, subprocess, sys, tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import analisis_btc as A, aprendizaje as apr, fuerte, indicadores as ind, termometro  # noqa: E402

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
LIQ = [[AHORA - k * 41_000, "long" if k % 3 else "short", 1000 + 37.5 * k] for k in range(300)]


def entrada_apr(bars, tf_min=60):
    c = [b[4] for b in bars]
    e50, e200, rsi, (ml, ms, mh) = ind.ema(c, 50), ind.ema(c, 200), ind.rsi(c), ind.macd(c)
    return apr.combos(apr.rasgos(bars, tf_min, e50, e200, rsi, mh)), apr.continuos(bars, tf_min, e50, e200, rsi, mh)


# explain (sin ventaja medida / rango del 80%) y el registro de predicciones con su rango
def plazo_1h(sin_ventaja, pu):
    return [{"tabla": "plazo", "plazo": "1 hora", "hora": "03/11 19:00", "veredicto": "Casi moneda", "sin_ventaja": sin_ventaja,
             "sube": 44.8, "base": 48.9, "obj_arriba": 77960.0, "obj_abajo": 77760.0, "primero_arriba": pu, "margen_primero": 3.0,
             "distancia": 100.0, "min": 77310.5, "max": 78420.2, "coinciden": "alcista" if pu == 70.0 else None},
            {"tabla": "marco", "tf": "15m", "rating": 0.3, "rating_txt": "Compra", "rsi": 55, "macd_cruce": None, "elliott_objetivo": None, "elliott_corto": ""},
            {"tabla": "marco", "tf": "1h", "rating": -0.4, "rating_txt": "Venta", "rsi": 72, "macd_cruce": "bajista", "elliott_objetivo": None, "elliott_corto": ""},
            {"tabla": "nivel", "nombre": "Máximo 24 h", "precio": 78500.0, "tipo": "resistencia", "distancia": 0.8},
            {"tabla": "nivel", "nombre": "Mínimo 24 h", "precio": 77000.0, "tipo": "soporte", "distancia": -1.1},
            {"tabla": "contexto", "clave": "flujo_1 h", "senal": "alcista", "detalle": "Dominan los compradores agresivos"},
            {"tabla": "aprendizaje", "plazo": "1 hora", "repasadas": 0}]


SPEC_1H = ["1 hora", "5m", 12, ["15m", "1h"], ["flujo_1 h", "flujo_4 h", "oi_1h"], "15 min"]
CASOS = {f"{sv}_{pu}": plazo_1h(sv, pu) for sv in (True, False) for pu in (30.0, 50.0, 70.0)}
LOG_ENTRADAS = [[2000, "1h", 4, 100.0, 55.0, 95.0, 105.0], [3000, "1h", 4, 100.0, 50.0, 99.0, 101.0], [4000, "4h", 3, 100.0, 40.0, 90.0, 110.0]]
LOG_CIERRES = {"1h": [[1000 + 4 * 3_600_000, 101.0], [2000 + 4 * 3_600_000, 104.0], [3000 + 4 * 3_600_000, 102.0]], "4h": [[4000 + 3 * 14_400_000, 95.0]]}


def registro_py():
    """log_and_score en un archivo aparte (no toca data/predicciones_btc.csv), con una fila vieja de 5 columnas."""
    tmp = tempfile.mkdtemp()
    A.LOG_FILE, A.DATA_DIR = os.path.join(tmp, "log.csv"), tmp
    with open(A.LOG_FILE, "w") as f:
        f.write("1000,1h,4,100.0,60.0\n")
    sc = A.log_and_score([tuple(e) for e in LOG_ENTRADAS], {tf: dict(xs) for tf, xs in LOG_CIERRES.items()})
    return {f"{tf}|{h}": list(v) for (tf, h), v in sorted(sc.items())}


# opciones inventadas: vencimientos de viernes y de otros dias, puts y calls alrededor de 60.000
OPC_AHORA = 1_793_700_000_000          # martes 03/11/2026
OPC_LIBRO = [{"instrument_name": f"BTC-{d}-{k}-{t}", "open_interest": round(1 + (k / 1000) % 7 + (t == "P") * 2.5, 1),
              "mark_iv": 45 + (60000 - k) / 2000 + (t == "P") * 3}
             for d in ("4NOV26", "6NOV26", "13NOV26", "27NOV26") for k in range(50000, 70001, 2500) for t in "CP"]
OPC_DVOL = [[OPC_AHORA - (720 - k) * 3_600_000, 40 + 5 * math.sin(k / 30)] for k in range(721)]


def rango_py():
    """Calibracion del rango del 80% (rango_puntajes / rango_factor) con la volatilidad prevista (vol_escala)."""
    c = [b[4] for b in H1]
    e50, e200, rsi, (ml, ms, mh) = ind.ema(c, 50), ind.ema(c, 200), ind.rsi(c), ind.macd(c)
    st = apr.estados(apr.rasgos(H1, 60, e50, e200, rsi, mh), 2)
    F = A.vol_escala(H1, 60, 4, False)
    pts = A.rango_puntajes(c, st, F, 4, 200, len(c) - 1 - 4)
    return {"F": F[-50:], "puntajes": pts, "factor": A.rango_factor(pts), "sin_vol": A.rango_factor(A.rango_puntajes(c, st, None, 6, 200, len(c) - 7, ventana=900))}


def py():
    piv = ind.zigzag(H4)
    raw = {"oi": [[b[0] + 3_600_000, 1000 + i] for i, b in enumerate(H1[-40:])], "ls": [1.2 + i / 100 for i in range(25)],
           "taker": [{"buy": 120 + i, "sell": 100} for i in range(4)], "top": 1.3, "funding": 0.0001, "funding7": -0.00002, "fundingFuente": "BingX"}
    return {
        "calificar": ind.calificar(H1)[:2], "zigzag": piv, "fvg": ind.fvg(H4), "divergencias": ind.divergencias(H4, piv),
        "fibonacci": A.fibonacci(H4),
        "termometro": termometro.termometro([b[4] for b in D1], D1[-1][4] * 1.01, now_ms=AHORA, f7=-0.00001),
        "termometro_alt": termometro.termometro_alt("XRP", ALT[-600:], ALT[-1][4], now_ms=AHORA),
        "piso": termometro.piso("BTC", [b[4] for b in D1], D1[-1][4] * 1.01),
        "piso_alt": termometro.piso("SOL", [b[4] for b in ALT], ALT[-1][4]),
        "piso_prob": [termometro.piso_prob(termometro._datos()["piso"], m, x, v) for m, x, v in (("BTC", -0.2, 0.3), ("ZEC", -0.7, 0.9), ("XRP", 0.1, 0.4), ("NADA", -0.3, 0.5))],
        "fuerte": fuerte.prever(H1),
        "liq_reales": A.liq_reales([tuple(x) for x in LIQ], AHORA),
        "aprender": {k: v for k, v in apr.aprender(H1, *entrada_apr(H1)[:1], 4, 200, entrada_apr(H1)[1]).items()
                     if k not in ("_estado", "pesos")},
        "explain": {k: A.explain(v, 77860.0, tuple(SPEC_1H)) for k, v in CASOS.items()},
        "registro": registro_py(),
        "rango": rango_py(),
        "opciones": A.opciones(OPC_LIBRO, OPC_DVOL, 61234.5, OPC_AHORA),
        "base_perp": [A.base_perp(61300, 61234.5, "Bybit"), A.base_perp(61190, 61234.5, "Bybit"), A.base_perp(61240, 61234.5, "Bybit")],
        "_ctx_raw": raw,
    }


JS = r"""
const R = process.argv[1];
globalThis.Ind = require(R + '/JavascriptVersion/indicadores.js'); globalThis.Aprendizaje = require(R + '/JavascriptVersion/aprendizaje.js'); const Apr = globalThis.Aprendizaje;
const Fu = require(R + '/JavascriptVersion/fuerte.js'); const A = require(R + '/JavascriptVersion/analisis.js');
const T = require(R + '/JavascriptVersion/termometro.json'), M = require(R + '/JavascriptVersion/modelo_fuerte.json');
const d = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const piv = Ind.zigzag(d.H4), c = Ind.calificar(d.H1);
console.log(JSON.stringify({
  calificar: [c[0], c[1]], zigzag: piv, fvg: Ind.fvg(d.H4), divergencias: Ind.divergencias(d.H4, piv), fibonacci: A.fibonacci(d.H4),
  termometro: A.termometro(d.D1.map((b) => b[4]), d.D1[d.D1.length - 1][4] * 1.01, T, null, d.AHORA, -0.00001),
  termometro_alt: A.termometroAlt('XRP', d.ALT.slice(-600), d.ALT[d.ALT.length - 1][4], T, d.AHORA),
  piso: A.piso('BTC', d.D1.map((b) => b[4]), d.D1[d.D1.length - 1][4] * 1.01, T),
  piso_alt: A.piso('SOL', d.ALT.map((b) => b[4]), d.ALT[d.ALT.length - 1][4], T),
  piso_prob: [['BTC', -0.2, 0.3], ['ZEC', -0.7, 0.9], ['XRP', 0.1, 0.4], ['NADA', -0.3, 0.5]].map(([m, x, v]) => A.pisoProb(T.piso, m, x, v)),
  fuerte: Fu.prever(M, d.H1), contexto: A.context(d.raw, d.H1), liq_reales: A.liqReales(d.LIQ, d.AHORA),
  explain: Object.fromEntries(Object.entries(d.CASOS).map(([k, v]) => [k, A.explain(v, 77860.0, d.SPEC_1H)])),
  registro: (() => { const cl = {}; Object.entries(d.LOG_CIERRES).forEach(([tf, xs]) => { cl[tf] = new Map(xs); });
    const sc = A.logAndScore([[1000, '1h', 4, 100.0, 60.0]], d.LOG_ENTRADAS, cl);
    return Object.fromEntries([...sc.entries()].sort()); })(),
  opciones: A.opciones(d.OPC_LIBRO, d.OPC_DVOL, 61234.5, d.OPC_AHORA),
  base_perp: [A.basePerp(61300, 61234.5, 'Bybit'), A.basePerp(61190, 61234.5, 'Bybit'), A.basePerp(61240, 61234.5, 'Bybit')],
  rango: (() => { const c = d.H1.map((b) => b[4]), e50 = Ind.ema(c, 50), e200 = Ind.ema(c, 200), rsi = Ind.rsi(c), mh = Ind.macd(c)[2];
    const st = Apr.estados(Apr.rasgos(d.H1, 60, e50, e200, rsi, mh), 2), F = A.volEscala(d.H1, 60, 4, false);
    const pts = A.rangoPuntajes(c, st, F, 4, 200, c.length - 1 - 4);
    return { F: F.slice(-50), puntajes: pts, factor: A.rangoFactor(pts), sin_vol: A.rangoFactor(A.rangoPuntajes(c, st, null, 6, 200, c.length - 7, 200, 900)) }; })(),
  aprender: (() => { const c = d.H1.map((b) => b[4]), e50 = Ind.ema(c, 50), e200 = Ind.ema(c, 200), rsi = Ind.rsi(c), mh = Ind.macd(c)[2];
    const r = Apr.aprender(d.H1, Apr.combos(Apr.rasgos(d.H1, 60, e50, e200, rsi, mh)), 4, 200, Apr.continuos(d.H1, 60, e50, e200, rsi, mh));
    delete r._estado; delete r.pesos; return r; })(),
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
    entrada = {"H1": H1, "H4": H4, "D1": D1, "ALT": ALT, "AHORA": AHORA, "raw": raw, "LIQ": LIQ,
               "CASOS": CASOS, "SPEC_1H": SPEC_1H, "LOG_ENTRADAS": LOG_ENTRADAS, "LOG_CIERRES": LOG_CIERRES,
               "OPC_LIBRO": OPC_LIBRO, "OPC_DVOL": OPC_DVOL, "OPC_AHORA": OPC_AHORA}
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
