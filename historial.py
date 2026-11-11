"""
Historial constante de predicciones (para "Reproducir" de la app): el servidor de Render analiza cada 20 s aunque nadie
tenga la app abierta, y cada prediccion nueva (una por vela cerrada, temporalidad y horizonte) se guarda aca.

Donde queda: en la rama `historial` de este repositorio (publica, como el resto del analisis; el plan de compras NO va
aca), un archivo por temporalidad y por dia (UTC):  historial/BTC/<tf>/<AAAA-MM-DD>.csv
  columnas: t, h, precio, sube, min, max, mediana, obj_arriba, obj_abajo, toca_arriba, toca_abajo, primero_arriba
  t = apertura de la vela siguiente a la prediccion (como el registro de la app); h = horizonte en velas.
La app los lee directo de raw.githubusercontent.com (sin claves) y los junta con lo que guardo el telefono.

Para escribir hace falta la variable HISTORIAL_GITHUB_TOKEN en Render: un token "fine-grained" de GitHub con permiso
Contents: Read and write SOLO sobre este repositorio. Sin el token, el historial se junta igual en memoria pero no se
sube (y se pierde al reiniciar). Se sube como mucho cada SUBIR_CADA segundos, en un solo commit (API de Git: arbol con
todos los archivos que cambiaron). La rama no la miran Render ni Vercel (vercel.json: deploymentEnabled) ni los
workflows (todos filtran main).
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

REPO = os.environ.get("HISTORIAL_REPO", "DiegoAdrian97/BTCAnalyzer")
RAMA = "historial"
CARPETA = "historial/BTC"
SUBIR_CADA = 1800                     # s entre dos subidas (48 commits por dia en la rama, como mucho)
DIAS_EN_MEMORIA = 3
COLUMNAS = ["t", "h", "precio", "sube", "min", "max", "mediana", "obj_arriba", "obj_abajo", "toca_arriba", "toca_abajo",
            "primero_arriba", "fuerte", "prob_fuerte", "prob_normal", "umbral_fuerte"]
# lo de cada prediccion que va despues del rango (las del movimiento fuerte: de la proxima hora, el mismo para todas las
# del mismo analisis; fuerte = alta / media / baja, umbral_fuerte = % de rango de la hora que cuenta como fuerte)
EXTRA = [("mediana", "m"), ("obj_arriba", "a"), ("obj_abajo", "b"), ("toca_arriba", "ta"), ("toca_abajo", "tb"),
         ("primero_arriba", "pa"), ("f", "f"), ("pf", "pf"), ("pn", "pn"), ("u", "u")]

_datos = {}            # (tf, dia) -> {(t, h): fila (lista de textos)}
_sucios = set()        # (tf, dia) que cambiaron desde la ultima subida
_cargados = set()      # (tf, dia) que ya se trajeron de GitHub (para no pisar lo de antes de un reinicio)
_ultima_subida = 0.0
_lock = threading.Lock()
_aviso_sin_token = False


def _dia(t_ms):
    return datetime.fromtimestamp(t_ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def _txt(x):
    if x is None:
        return ""
    if isinstance(x, float):
        return f"{x:.6g}" if abs(x) < 1e6 else f"{x:.2f}"
    return str(x)


def _token():
    return os.environ.get("HISTORIAL_GITHUB_TOKEN", "").strip()


def _api(metodo, ruta, cuerpo=None, crudo=False):
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}{ruta}", method=metodo,
                                 data=None if cuerpo is None else json.dumps(cuerpo).encode())
    req.add_header("Authorization", f"Bearer {_token()}")
    req.add_header("Accept", "application/vnd.github.raw" if crudo else "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if cuerpo is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read()
    return data.decode() if crudo else json.loads(data or b"{}")


def _ruta(tf, dia):
    return f"{CARPETA}/{tf}/{dia}.csv"


def _traer(tf, dia):
    """Lo que ya estaba subido de ese dia (despues de un reinicio de Render no se pierde lo de hoy)."""
    if (tf, dia) in _cargados:
        return
    _cargados.add((tf, dia))
    texto = None
    try:
        if _token():
            texto = _api("GET", f"/contents/{_ruta(tf, dia)}?ref={RAMA}", crudo=True)
        else:
            with urllib.request.urlopen(f"https://raw.githubusercontent.com/{REPO}/{RAMA}/{_ruta(tf, dia)}", timeout=15) as r:
                texto = r.read().decode()
    except Exception:
        return                                   # todavia no existe (o sin red): se arranca vacio
    filas = _datos.setdefault((tf, dia), {})
    for linea in texto.splitlines()[1:]:
        c = linea.split(",")
        if len(c) >= 6:
            filas.setdefault((c[0], c[1]), c)


def anotar(entries):
    """Las predicciones de un analisis: (t, tf, h, precio, % sube, min, max[, extras]). Guarda solo las nuevas."""
    if not entries:
        return
    with _lock:
        for e in entries:
            t, tf, h, p, pr, lo, hi = e[:7]
            x = e[7] if len(e) > 7 and isinstance(e[7], dict) else {}
            dia = _dia(t)
            _traer(tf, dia)
            filas = _datos.setdefault((tf, dia), {})
            clave = (str(int(t)), str(int(h)))
            if clave in filas:
                continue
            filas[clave] = [clave[0], clave[1], _txt(p), _txt(pr), _txt(lo), _txt(hi)] + [_txt(x.get(k)) for _, k in EXTRA]
            _sucios.add((tf, dia))
        # fuera de la memoria lo de hace mas de unos dias (ya quedo subido)
        hoy = time.time() * 1000
        for k in [k for k in _datos if k not in _sucios and (hoy - datetime.strptime(k[1], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000) > DIAS_EN_MEMORIA * 864e5]:
            _datos.pop(k, None)
            _cargados.discard(k)
    subir_si_toca()


def _csv(tf, dia):
    filas = sorted(_datos.get((tf, dia), {}).values(), key=lambda c: (int(c[0]), int(c[1])))
    return ",".join(COLUMNAS) + "\n" + "".join(",".join(c) + "\n" for c in filas)


def subir_si_toca(forzar=False):
    global _ultima_subida, _aviso_sin_token
    if not _sucios or (not forzar and time.time() - _ultima_subida < SUBIR_CADA):
        return
    if not _token():
        if not _aviso_sin_token:
            print("Historial de predicciones: falta HISTORIAL_GITHUB_TOKEN en Render, se junta en memoria pero no se sube.")
            _aviso_sin_token = True
        return
    _ultima_subida = time.time()
    with _lock:
        cambios = {_ruta(tf, dia): _csv(tf, dia) for tf, dia in _sucios}
        pendientes = set(_sucios)
        _sucios.clear()
    threading.Thread(target=_subir, args=(cambios, pendientes), daemon=True).start()


def _subir(cambios, pendientes):
    """Un commit con todos los archivos que cambiaron (si la rama no existe, se crea sin historia previa)."""
    try:
        arbol = [{"path": p, "mode": "100644", "type": "blob", "content": c} for p, c in sorted(cambios.items())]
        try:
            padre = _api("GET", f"/git/ref/heads/{RAMA}")["object"]["sha"]
            base = _api("GET", f"/git/commits/{padre}")["tree"]["sha"]
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            padre = base = None
        tree = _api("POST", "/git/trees", {"tree": arbol, **({"base_tree": base} if base else {})})["sha"]
        quien = {"name": "DiegoAdrian97", "email": "diegojadrian97@gmail.com"}
        commit = _api("POST", "/git/commits", {"message": f"historial: {len(cambios)} archivos", "tree": tree,
                                                "parents": [padre] if padre else [], "author": quien, "committer": quien})["sha"]
        if padre:
            _api("PATCH", f"/git/refs/heads/{RAMA}", {"sha": commit})
        else:
            _api("POST", "/git/refs", {"ref": f"refs/heads/{RAMA}", "sha": commit})
    except Exception as e:                    # se reintenta en la proxima vuelta, con todo lo que siga pendiente
        print(f"Historial de predicciones: no se pudo subir ({str(e)[:160]})")
        with _lock:
            _sucios.update(pendientes)
