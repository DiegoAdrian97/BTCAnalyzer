"""¿Cuanto acierta de verdad el analisis de la app, y cada señal? (con lo que la app fue diciendo, no con un repaso)

El servidor guarda cada hora la conclusion de cada plazo y las señales que la formaron (historial.py, rama `historial`,
historial/BTC/central/<dia>.csv). Aca se cruza con lo que hizo el precio despues (velas de 5 min de Binance spot):
  - por plazo: cuando dijo sube o baja, ¿acerto? ¿y cuando ademas tenia mas puntos netos?
  - por señal: cuando sumo para un lado, ¿el precio fue para ahi? (por plazo)
Con pocos dias no dice nada: sirve desde unas semanas (100 casos o mas por fila; se marca con * lo que no llega).
Uso: python medir_central.py
"""
import json, math, os, sys, time, urllib.request
from collections import defaultdict

REPO, RAMA = "DiegoAdrian97/BTCAnalyzer", "historial"
CAB = {"User-Agent": "analista-btc-medicion"}
HORAS = {"5 min": 5 / 60, "15 min": 0.25, "1 hora": 1, "4 horas": 4, "1 día": 24, "1 semana": 168, "1 mes": 720}


def get(u, crudo=False):
    d = urllib.request.urlopen(urllib.request.Request(u, headers=CAB), timeout=60).read()
    return d.decode() if crudo else json.loads(d)


def filas():
    out = []
    for f in get(f"https://api.github.com/repos/{REPO}/contents/historial/BTC/central?ref={RAMA}"):
        for ln in get(f"https://raw.githubusercontent.com/{REPO}/{RAMA}/{f['path']}", crudo=True).splitlines()[1:]:
            p = ln.split(",")
            if len(p) >= 9 and p[2]:
                sen = dict((x.split(":")[0], float(x.split(":")[1])) for x in p[8].split(";") if ":" in x)
                out.append({"t": int(p[0]), "plazo": p[1], "precio": float(p[2]), "dir": p[3], "pts": float(p[4] or 0), "sen": sen})
    return sorted(out, key=lambda r: r["t"])


def precios(t0, t1):
    """cierre de cada vela de 5 min (spot) entre t0 y t1: {apertura: cierre}."""
    out, t = {}, t0
    while t < t1:
        k = get(f"https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=5m&startTime={t}&limit=1000")
        if not k:
            break
        for r in k:
            out[int(r[0])] = float(r[4])
        t = int(k[-1][0]) + 300000
    return out


def main():
    try:
        F = filas()
    except Exception as e:
        print(f"Todavía no hay conclusiones guardadas ({type(e).__name__}): el servidor las empieza a guardar con esta versión.")
        return
    if not F:
        print("Todavía no hay conclusiones guardadas.")
        return
    P = precios(F[0]["t"], F[-1]["t"] + 3600000)
    ahora = max(P) + 300000
    print(f"{len(F)} conclusiones, del {F[0]['t']} al {F[-1]['t']} ({(F[-1]['t'] - F[0]['t']) / 864e5:.1f} días)")
    z = lambda ok, n: (ok / n - 0.5) / math.sqrt(0.25 / n) if n else 0.0
    por, sen = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    plata, cal = defaultdict(list), defaultdict(lambda: [0, 0])
    for r in F:
        hz = int(HORAS.get(r["plazo"], 0) * 3600000)
        fin = r["t"] + hz
        if not hz or fin > ahora:
            continue
        c = P.get(fin - 300000)                      # la vela de 5 min que cierra en `fin`
        if c is None or c == r["precio"]:
            continue
        sube = c > r["precio"]
        if r["dir"] in ("sube", "baja"):
            ok = (r["dir"] == "sube") == sube
            for k in ("todas",) + (("3 puntos o más",) if abs(r["pts"]) >= 3.5 else ()):
                a = por[(r["plazo"], k)]; a[0] += ok; a[1] += 1
            plata[r["plazo"]].append((1 if r["dir"] == "sube" else -1) * (c / r["precio"] - 1) * 1e4)
            a = cal[(r["plazo"], "3,5 o más" if abs(r["pts"]) >= 3.5 else "2,5 a 3,5")]; a[0] += ok; a[1] += 1
        a = por[(r["plazo"], "lateral: ¿subió?")] if r["dir"] == "neutral" else None
        if a is not None:
            a[0] += sube; a[1] += 1
        for k, v in r["sen"].items():
            if v:
                a = sen[(r["plazo"], k)]; a[0] += (v > 0) == sube; a[1] += 1
    print("\n=== por plazo: cuando dijo sube o baja ===")
    for (pl, k), (ok, n) in sorted(por.items(), key=lambda kv: (HORAS[kv[0][0]], kv[0][1])):
        print(f"  {pl:<9} {k:<18} {n:>5} casos · {100 * ok / n:5.1f}% (z {z(ok, n):+.1f}){'' if n >= 100 else '  *pocos'}")
    print("\n=== por señal: cuando sumó para un lado, ¿el precio fue para ahí? ===")
    for (pl, k), (ok, n) in sorted(sen.items(), key=lambda kv: (HORAS[kv[0][0]], -kv[1][1])):
        print(f"  {pl:<9} {k:<14} {n:>5} casos · acierta {100 * ok / n:5.1f}% (z {z(ok, n):+.1f}){'' if n >= 100 else '  *pocos'}")

    if len(sys.argv) > 1:
        escribir(sys.argv[1], F, por, sen, plata, cal)


def escribir(ruta, F, por, sen, plata, cal):
    """track.json: lo que muestra la pagina (aciertos reales) y la deriva de cada señal contra lo medido (mediciones.json)."""
    try:
        M = json.load(open(os.path.join(os.path.dirname(ruta), "mediciones.json")))["senales"]
    except Exception:
        M = {}
    pl = []
    for p in HORAS:
        ok, n = por.get((p, "todas"), (0, 0)); okf, nf = por.get((p, "3 puntos o más"), (0, 0)); sl, nl = por.get((p, "lateral: ¿subió?"), (0, 0))
        if n or nl:
            r = plata.get(p, [])
            pl.append({"plazo": p, "n": n, "acierto": round(100 * ok / n, 1) if n else None, "n_fuerte": nf, "acierto_fuerte": round(100 * okf / nf, 1) if nf else None,
                       "retorno_pb": round(sum(r) / len(r), 1) if r else None, "laterales": nl})
    se = []
    for (p, k), (ok, n) in sen.items():
        esp = (M.get(k) or {}).get("esperado") or 50
        zz = (ok / n - esp / 100) / math.sqrt(0.25 / n)
        se.append({"plazo": p, "clave": k, "nombre": (M.get(k) or {}).get("nombre", k), "n": n, "acierto": round(100 * ok / n, 1), "esperado": esp,
                   "estado": "pocos" if n < 100 else "deriva" if zz <= -2.5 or (ok / n - 0.5) / math.sqrt(0.25 / n) <= -2 else "ok"})
    out = {"actualizado": int(time.time() * 1000), "desde": F[0]["t"], "hasta": F[-1]["t"], "plazos": pl,
           "senales": sorted(se, key=lambda x: (HORAS[x["plazo"]], -x["n"])),
           "calibracion": [{"plazo": p, "puntos": k, "n": n, "acierto": round(100 * ok / n, 1)} for (p, k), (ok, n) in sorted(cal.items(), key=lambda kv: (HORAS[kv[0][0]], kv[0][1]))]}
    json.dump(out, open(ruta, "w"), ensure_ascii=False, indent=1)
    print(f"\n{ruta}: {len(pl)} plazos, {len(se)} señales; en deriva: {[x['clave'] + ' (' + x['plazo'] + ')' for x in se if x['estado'] == 'deriva'] or 'ninguna'}")


if __name__ == "__main__":
    main()
