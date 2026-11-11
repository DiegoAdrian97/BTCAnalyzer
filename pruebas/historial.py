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
x = {"mediana": 70100.5, "obj_arriba": 70500, "obj_abajo": 69500, "toca_arriba": 41.2, "toca_abajo": 38.0, "primero_arriba": 52.3}
H.anotar([(t0, "5m", 3, 70000.0, 55.0, 69800.0, 70200.0, x), (t0 + 3e5, "5m", 3, 70050.0, 48.5, 69850.0, 70250.0, x),
          (t0, "1h", 4, 70000.0, 60.0, 69000.0, 71000.0)])
H.anotar([(t0 + 3e5, "5m", 3, 1.0, 1.0, 1.0, 1.0)])          # repetida: no se pisa
csv5 = H._csv("5m", "2026-11-11").splitlines()
assert csv5[0].startswith("t,h,precio,sube,min,max,mediana"), csv5[0]
assert len(csv5) == 3 and csv5[1].startswith("1794398400000,3,70000,55"), csv5      # la que ya estaba subida se respeta
assert csv5[2] == "1794398700000,3,70050,48.5,69850,70250,70100.5,70500,69500,41.2,38,52.3", csv5[2]
assert H._csv("1h", "2026-11-11").splitlines()[1] == "1794398400000,4,70000,60,69000,71000,,,,,,"
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
