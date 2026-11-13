"""Prueba de historial.py sin red: anota predicciones, arma los CSV y simula la subida a GitHub. python pruebas/historial.py"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["HISTORIAL_GITHUB_TOKEN"] = "token-de-prueba"
import historial as H

llamadas = []
def api(metodo, ruta, cuerpo=None, crudo=False):
    llamadas.append((metodo, ruta, cuerpo))
    if crudo:                                   # lo que ya habia subido de ese dia
        if ruta.endswith("/5m/2026-11-11.csv?ref=historial"):
            return "t,h,precio,sube,min,max\n1794398400000,3,70000,55,69800,70200\n"
        raise H.urllib.error.HTTPError(ruta, 404, "no", {}, None)
    if ruta == "/git/ref/heads/historial": return {"object": {"sha": "padre"}}
    if ruta == "/git/commits/padre": return {"tree": {"sha": "arbol0"}}
    if ruta == "/git/trees": return {"sha": "arbol1"}
    if ruta == "/git/commits": return {"sha": "nuevo"}
    return {}
H._api = api
t0 = 1794398400000                               # 11/11/2026 12:00 UTC
x = {"m": 70100.5, "a": 70500, "b": 69500, "ta": 41.2, "tb": 38.0, "pa": 52.3, "f": "baja", "pf": 8, "pn": 12, "u": 1.84}
H.anotar([(t0, "5m", 3, 70000.0, 55.0, 69800.0, 70200.0, x), (t0 + 3e5, "5m", 3, 70050.0, 48.5, 69850.0, 70250.0, x),
          (t0, "1h", 4, 70000.0, 60.0, 69000.0, 71000.0)])
H.anotar([(t0 + 3e5, "5m", 3, 1.0, 1.0, 1.0, 1.0)])          # repetida: no se pisa
csv5 = H._csv("5m", "2026-11-11").splitlines()
assert csv5[0].endswith("primero_arriba,fuerte,prob_fuerte,prob_normal,umbral_fuerte"), csv5[0]
assert len(csv5) == 3 and csv5[1].startswith("1794398400000,3,70000,55"), csv5      # la que ya estaba subida se respeta
assert csv5[2] == "1794398700000,3,70050,48.5,69850,70250,70100.5,70500,69500,41.2,38,52.3,baja,8,12,1.84", csv5[2]
assert H._csv("1h", "2026-11-11").splitlines()[1] == "1794398400000,4,70000,60,69000,71000,,,,,,,,,,"
H.subir_si_toca(forzar=True)
for _ in range(50):
    if any(r == "/git/refs/heads/historial" for _, r, _ in llamadas): break
    time.sleep(0.05)
arbol = next(c for m, r, c in llamadas if r == "/git/trees")
assert arbol["base_tree"] == "arbol0" and sorted(f["path"] for f in arbol["tree"]) == ["historial/BTC/1h/2026-11-11.csv", "historial/BTC/5m/2026-11-11.csv"]
commit = next(c for m, r, c in llamadas if r == "/git/commits")
assert commit["parents"] == ["padre"] and commit["tree"] == "arbol1"
assert ("PATCH", "/git/refs/heads/historial", {"sha": "nuevo"}) in llamadas
assert not H._sucios
print("historial: todo bien")


# ---------- libro de ordenes (mapa de calor del libro) ----------
h = H
assert h._paso(70_000) == 50 and h._paso(3_500) == 5 and abs(h._paso(150) - 0.2) < 1e-12, (h._paso(70_000), h._paso(3_500), h._paso(150))
niv = h.libro_niveles([([(69_990.0, 2.0), (69_960.0, 10.0), (60_000.0, 99.0)], [(70_010.0, 1.0), (70_040.0, 5.0)]),
                       ([(69_975.0, 1.0)], [(70_030.0, 3.0)])], 70_000.0, 50, top=2)
assert niv == {1400: 210 + 70, 1399: 700, 1401: 560}, niv
assert all(k * 50 > 60_000 for k in niv), "lo de mas de 4% no entra"
h._libro.clear(); h._libro["2026-11-12"] = {"1762905600000": "1762905600000,70000,50,1400:140;1401:350"}
csv = h._csv("libro", "2026-11-12")
assert csv.splitlines()[0] == "t,medio,paso,niveles" and csv.splitlines()[1].endswith("1401:350"), csv
assert h._ruta("libro", "2026-11-12") == "historial/BTC/libro/2026-11-12.csv"
print("historial: libro de ordenes bien")
