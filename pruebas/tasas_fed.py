"""Lo que espera el mercado de la Fed da lo mismo en Python (tasas_fed.py) y en JS (api/contexto.js): probabilidades y
la fila 'fed_tasas', con precios de ejemplo (sin red). Uso: python pruebas/tasas_fed.py"""
import json, os, subprocess, sys
from datetime import date

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import tasas_fed  # noqa: E402

JS = """const c = require(process.argv[1] + '/JavascriptVersion/api/contexto.js');
const casos = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(casos.map((k) => {
  const d = c.armarFed(k.effr, k.rango, '2026-11-25', k.precios, k.hoy);
  return { prob: c.probabilidades(k.effr, k.precios, k.hoy), fila: c.filaFed(d) };
})));"""

HOY = "2026-11-26"
REAL = {"ZQZ26.CBT": 95.945, "ZQF27.CBT": 95.85, "ZQG27.CBT": 95.715}


def dic_para(despues_pb, effr=3.88):
    """Precio de ZQZ26 que implica 'despues' = effr + despues_pb/100 (enero y febrero igual: lo que ya esperaba)."""
    despues = effr + despues_pb / 100
    mes = 100 - (9 / 31 * effr + 22 / 31 * despues)
    return {"ZQZ26.CBT": mes, "ZQF27.CBT": 100 - despues, "ZQG27.CBT": 100 - despues}


CASOS = {
    "real": dict(effr=3.88, rango=[3.75, 4.0], precios=REAL, hoy=HOY),
    "dividido": dict(effr=3.88, rango=[3.75, 4.0], precios=dic_para(-10), hoy=HOY),
    "baja_50": dict(effr=3.88, rango=[3.75, 4.0], precios=dic_para(-35), hoy=HOY),
    "sin_precio": dict(effr=3.88, rango=[3.75, 4.0], precios={"ZQF27.CBT": 95.85}, hoy=HOY),
    "sin_reuniones": dict(effr=3.88, rango=[3.75, 4.0], precios=REAL, hoy="2027-11-18"),
}


def py(k):
    h = date.fromisoformat(k["hoy"])
    d = tasas_fed.armar(k["effr"], k["rango"], "2026-11-25", k["precios"], h)
    return {"prob": tasas_fed.probabilidades(k["effr"], k["precios"], h), "fila": tasas_fed.fila(d)}


def main():
    nombres = list(CASOS)
    js = json.loads(subprocess.run(["node", "-e", JS, RAIZ], input=json.dumps([CASOS[n] for n in nombres]),
                                   capture_output=True, text=True, check=True).stdout)
    p = {n: json.loads(json.dumps(py(CASOS[n]))) for n in nombres}
    for n, j in zip(nombres, js):
        assert p[n] == j, f"{n}: Python y JS difieren:\n{json.dumps(p[n], ensure_ascii=False)}\n{json.dumps(j, ensure_ascii=False)}"

    f = p["real"]["fila"]
    assert f["valor"] == "9/12: suba 0,25 · 99%" and f["prob"] == [[25, 0.986], [0, 0.014]] and not f["indeciso"], f
    assert f["fecha"] == "2026-12-09" and f["dias"] == 13 and f["rango"] == [3.75, 4.0] and f["effr"] == 3.88 and f["esperada"] == 4.127, f
    assert f["siguiente"]["fecha"] == "2027-01-27" and abs(f["siguiente"]["acumulado_pb"] - 40.5) < 0.2, f["siguiente"]
    assert f["detalle"].startswith("Futuros de Fed Funds (como FedWatch). Tasa hoy 3,75–4,00%. Medido: desde 2022")
    assert f["detalle"].endswith("Para el 27/1: +40 pb acumulado."), f["detalle"]
    assert (f["tabla"], f["clave"], f["senal"]) == ("contexto", "fed_tasas", "neutral")

    f = p["dividido"]["fila"]
    assert f["indeciso"] and f["prob"] == [[0, 0.6], [-25, 0.4]], f["prob"]
    assert f["valor"] == "9/12: mantener · 60%" and "Mercado dividido (60% mantener / 40% baja 0,25)" in f["detalle"], f

    f = p["baja_50"]["fila"]
    assert f["prob"] == [[-25, 0.6], [-50, 0.4]] and f["indeciso"], f["prob"]
    assert f["valor"] == "9/12: baja 0,25 · 60%" and "(60% baja 0,25 / 40% baja 0,50)" in f["detalle"], f

    assert p["sin_precio"]["fila"] is None and p["sin_precio"]["prob"] == []
    assert p["sin_reuniones"]["fila"] is None and tasas_fed.fila(None) is None
    print(f"tasas_fed: todo bien ({len(nombres)} casos, Python = JS)")


if __name__ == "__main__":
    main()
