"""El calendario economico da lo mismo en Python (noticias.py) y en JS (api/contexto.js): las filas 'evento' de
siempre y las 'calendario' con el efecto de cada dato. Uso: python pruebas/calendario.py"""
import json, os, subprocess, sys
from datetime import datetime, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import noticias  # noqa: E402

AHORA = 1_794_000_000_000
EV = [  # titulo, importancia, horas desde ahora, actual, previsto, anterior
    ("Inflation Rate YoY", 1, -50, 3.1, 2.9, 3.0), ("Core Inflation Rate MoM", 1, -50, 0.2, 0.3, 0.3),
    ("Non Farm Payrolls", 1, -30, 150, 150, 180), ("Unemployment Rate", 1, -30, 4.4, 4.2, 4.2),
    ("Initial Jobless Claims", 0, -20, 210, 225, 220), ("Michigan Consumer Sentiment", 0, -10, 55.1, 53.0, 52.1),
    ("Michigan Inflation Expectations", 0, -10, 4.0, None, 3.8), ("Crude Oil Inventories", 0, -5, -2.1, 1.0, 0.5),
    ("Fed Interest Rate Decision", 1, 40, None, 3.75, 4.0), ("Retail Sales MoM", 1, 60, None, 0.4, 0.6),
    ("Building Permits", -1, 70, None, 1.4, 1.39), ("GDP Growth Rate QoQ", 1, -100, 2.8, 2.5, 3.0),
]
def fecha(h):
    return datetime.fromtimestamp(AHORA / 1000 + h * 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


TXT = json.dumps({"result": [{"title": t, "importance": i, "date": fecha(h), "actual": a, "forecast": f, "previous": p,
                              "unit": "%" if "Rate" in t else "", "scale": "K" if "Payrolls" in t else "", "period": "Oct"}
                             for t, i, h, a, f, p in EV]})


def main():
    py = noticias.parse_calendario(TXT, AHORA)
    js = json.loads(subprocess.run(["node", "-e", "const c = require(process.argv[1] + '/JavascriptVersion/api/contexto.js'); process.stdout.write(JSON.stringify(c.parseCalendario(require('fs').readFileSync(0, 'utf8'), +process.argv[2])));", RAIZ, str(AHORA)],
                                   input=TXT, capture_output=True, text=True, check=True).stdout)
    assert json.loads(json.dumps(py)) == js, "Python y JS difieren:\n" + json.dumps(py, ensure_ascii=False)[:800] + "\n" + json.dumps(js, ensure_ascii=False)[:800]
    ef = {r["original"]: r["efecto"] for r in py if r["tabla"] == "calendario"}
    esperado = {"Inflation Rate YoY": "negativo", "Core Inflation Rate MoM": "positivo", "Non Farm Payrolls": "neutral", "Unemployment Rate": "positivo",
                "Fed Interest Rate Decision": None, "GDP Growth Rate QoQ": "negativo"}
    for k, v in esperado.items():
        assert ef[k] == v, f"{k}: {ef[k]} (esperado {v})"
    ev = [r for r in py if r["tabla"] == "evento"]
    assert [r["original"] for r in ev] == ["Fed Interest Rate Decision", "Retail Sales MoM"], [r["original"] for r in ev]   # alta y desde ayer
    for k in ("Building Permits", "Initial Jobless Claims", "Michigan Consumer Sentiment", "Crude Oil Inventories"):   # media o baja: afuera
        assert k not in ef, k
    print(f"calendario: todo bien ({len(ef)} datos, {len(ev)} de importancia alta para el análisis)")


if __name__ == "__main__":
    main()
