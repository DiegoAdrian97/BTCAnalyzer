"""¿Una IA que lee las noticias anticipa mejor a BTC que las reglas de hoy? (medir antes de sumar)

1. Titulares: GDELT (gratis, todas las noticias en ingles cada 15 minutos, con su titular) de los ultimos ~88 dias.
   Quedan los que noticias.tema reconoce de cripto, escalada de guerras y Trump / politica de EE.UU. (y la Fed).
2. Misma noticia en varios medios, tres formas de contar:
     cada titular   (sin agrupar: lo que preocupa, la misma noticia vale varias veces)
     reglas         (noticias.misma_noticia: palabras en comun, lo que hace la app hoy)
     IA             (parecido de significado con un modelo de frases multilingue; un hecho = un voto)
   Cada hecho cuenta una sola vez, cuando aparece por primera vez.
3. Lectura de cada titular:
     reglas: noticias.sesgo (alcista +1, bajista -1, neutral 0)
     IA:     Qwen2.5-1.5B-Instruct (abierto, corre en GitHub); probabilidad de "positive" menos la de "negative".
             Su entrenamiento termina en 2024: no conoce lo que paso despues de estos titulares.
4. Señal de cada hora: la suma de los hechos nuevos de las ultimas 4 horas (y cuantos son).
5. Contra lo de hoy, con una regresion logistica que se reentrena cada dia solo con lo ya terminado:
     para donde (sube en 1 y 4 h): la tasa base contra la tasa base + la señal
     movimiento fuerte (1 y 4 h):  el modelo de la app (entrenar_fuerte, prueba honesta) contra el mismo + noticias
   Entra si mejora en las dos mitades del periodo con z por dia > 2.
Uso: python medir_noticias_ia.py velas_1h.json eventos.json [--dias 88] [--minutos 200]
     en paralelo: --parte k/n en n maquinas (baja y lee su tramo), y despues sin --parte con los titulares_parte_*.jsonl
"""
import argparse, json, math, os, random, re, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
import numpy as np
import noticias as nt

H, D = 3_600_000, 86_400_000
# temas de noticias.tema que cuentan (lo mismo que mira la app para BTC, sin "Grandes gobiernos" de otros paises)
TEMAS_OK = {"Cripto", "ETF", "Hackeo de exchange", "Hackeo o quiebra", "Guerras grandes", "Gobierno de EE.UU.", "Fed y tasas"}
GRUPO = {"Cripto": "cripto", "ETF": "cripto", "Hackeo de exchange": "cripto", "Hackeo o quiebra": "cripto",
         "Guerras grandes": "guerras", "Gobierno de EE.UU.": "EE.UU. y la Fed", "Fed y tasas": "EE.UU. y la Fed"}


# ---------- 1. titulares de GDELT ----------
# La API de busqueda de GDELT casi no contesta desde GitHub (limita por maquina). Se usan sus archivos de cada 15 minutos
# (GKG 2.0: todas las noticias en ingles que vio, con el titular de la pagina), que no tienen limite.
GKG = "http://data.gdeltproject.org/gdeltv2/{:%Y%m%d%H%M%S}.gkg.csv.zip"
TIT = re.compile(rb"<PAGE_TITLE>(.*?)</PAGE_TITLE>")


def momentos(dias, parte=None):
    """Los archivos de 15 min de los ultimos `dias` (hasta hoy 00 UTC, igual en todos los trabajos); con parte = (k, n),
    solo el tramo k de n (para bajar en varias maquinas)."""
    fin = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    vs = [fin - timedelta(days=dias) + timedelta(minutes=15 * i) for i in range(dias * 96)]
    if parte:
        k, n = parte; m = -(-len(vs) // n); vs = vs[k * m:(k + 1) * m]
    return vs


def _archivo(a):
    import html, io, zipfile
    for k in range(3):
        try:
            z = urllib.request.urlopen(urllib.request.Request(GKG.format(a), headers={"User-Agent": "Mozilla/5.0"}), timeout=120).read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None                                 # GDELT a veces saltea un cuarto de hora
            time.sleep(5 * (k + 1))
        except Exception:
            time.sleep(5 * (k + 1))
    else:
        return None
    t, out = int(a.timestamp() * 1000), []
    with zipfile.ZipFile(io.BytesIO(z)) as zf:
        for l in zf.open(zf.namelist()[0]):
            m = TIT.search(l)
            if not m:
                continue
            tit = html.unescape(m.group(1).decode("utf-8", "replace")).strip()
            tm = nt.tema(tit, "mundo") if 12 < len(tit) < 300 else None
            if tm in TEMAS_OK:
                c = l.split(b"\t")
                out.append({"url": c[4].decode("utf-8", "replace"), "titulo": tit, "t": t, "medio": c[3].decode("utf-8", "replace"), "tema": tm})
    return out


def bajar(dias, parte=None):
    from concurrent.futures import ThreadPoolExecutor
    ms, t0 = momentos(dias, parte), time.time()
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(_archivo, ms))
    faltan = sum(r is None for r in res)
    rows = [r for x in res if x for r in x]
    print(f"bajada: {len(ms) - faltan} de {len(ms)} archivos de 15 min, {len(rows)} titulares de los temas ({time.time() - t0:.0f} s)", flush=True)
    # la misma direccion o el mismo titular (sindicacion): uno solo, el primero
    vistos, out = set(), []
    for r in sorted(rows, key=lambda r: r["t"]):
        k = r["titulo"].lower()
        if k not in vistos and r["url"] not in vistos:
            vistos.add(k); vistos.add(r["url"]); out.append(r)
    return out


# ---------- 2. misma noticia ----------
def grupos_reglas(rows):
    g, abiertos = np.zeros(len(rows), int), []
    for i, r in enumerate(rows):
        abiertos = [(j, x) for j, x in abiertos if r["t"] - x["t"] <= 12 * H]
        igual = next((j for j, x in abiertos if nt.misma_noticia(x, r)), None)
        if igual is None:
            g[i] = i; abiertos.append((i, r))
        else:
            g[i] = g[igual]
    return g


def grupos_ia(t, E, umbral):
    """Une un titular al hecho de las ultimas 12 h con el que mas se parece, si se parece al menos 'umbral' (coseno)."""
    g = np.arange(len(t)); ini = 0
    for i in range(len(t)):
        while t[i] - t[ini] > 12 * H:
            ini += 1
        if ini < i:
            s = E[ini:i] @ E[i]
            k = int(np.argmax(s))
            if s[k] >= umbral:
                g[i] = g[ini + k]
    return g


# ---------- 3. lectura con IA ----------
def leer_ia(titulos, minutos):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    torch.set_num_threads(os.cpu_count() or 4)
    nom = "Qwen/Qwen2.5-1.5B-Instruct"
    tok = AutoTokenizer.from_pretrained(nom); tok.padding_side = "left"
    mod = AutoModelForCausalLM.from_pretrained(nom, torch_dtype=torch.float32).eval()
    ids = [tok.encode(w, add_special_tokens=False)[0] for w in ("positive", "negative", "neutral")]
    out, t0 = np.full(len(titulos), np.nan), time.time()
    for a in range(0, len(titulos), 16):
        if time.time() - t0 > minutos * 60:
            print(f"  tiempo agotado: {a} de {len(titulos)} titulares leidos", flush=True); break
        msgs = [tok.apply_chat_template([
            {"role": "system", "content": "You are an expert crypto market analyst."},
            {"role": "user", "content": f"News headline: \"{x}\"\nIs this news positive, negative or neutral for the price of bitcoin over the next few hours? Answer with one word: positive, negative or neutral."}],
            tokenize=False, add_generation_prompt=True) for x in titulos[a:a + 16]]
        enc = tok(msgs, return_tensors="pt", padding=True)
        with torch.no_grad():
            lg = mod(**enc).logits[:, -1, ids]
        p = torch.softmax(lg, -1).numpy()
        out[a:a + 16] = p[:, 0] - p[:, 1]
        if a % 800 == 0:
            print(f"  IA: {a + len(msgs)}/{len(titulos)} ({time.time() - t0:.0f} s)", flush=True)
    return out


# ---------- 4 y 5. señal y medicion ----------
def senal(T, t_hecho, v_hecho, ventana=4 * H):
    """Para cada cierre T: suma y cantidad de hechos nuevos en (T - ventana, T]."""
    o = np.argsort(t_hecho); th, vh = t_hecho[o], v_hecho[o]
    cs = np.concatenate([[0], np.cumsum(vh)])
    a, b = np.searchsorted(th, T - ventana, "right"), np.searchsorted(th, T, "right")
    return cs[b] - cs[a], (b - a).astype(float)


def logit_dia(t, F, y, hz, minimo=240):
    """Logistica que se reentrena cada dia con lo ya terminado (t + hz <= el dia que predice)."""
    n, k = F.shape; Z = np.column_stack([np.ones(n), F]); p = np.full(n, np.nan)
    dias = (t // D).astype(np.int64)
    for d in np.unique(dias):
        hoy = dias == d; tr = (t + (hz + 1) * H) <= d * D
        if tr.sum() < minimo:
            continue
        w = np.zeros(k + 1); w[0] = math.log((y[tr].mean() + 1e-3) / (1 - y[tr].mean() + 1e-3))
        Zt, yt = Z[tr], y[tr]
        for _ in range(25):
            f = 1 / (1 + np.exp(-np.clip(Zt @ w, -30, 30)))
            g = Zt.T @ (f - yt) + 1e-2 * np.r_[0, w[1:]]
            Hm = (Zt * (f * (1 - f))[:, None]).T @ Zt + 1e-2 * np.eye(k + 1)
            w -= np.clip(np.linalg.solve(Hm, g), -2, 2)
        p[hoy] = 1 / (1 + np.exp(-np.clip(Z[hoy] @ w, -30, 30)))
    return p


def z_dia(t, d):
    dia = (t // D).astype(np.int64)
    _, inv = np.unique(dia, return_inverse=True)
    m = np.bincount(inv, weights=d)
    return float(m.mean() / (m.std(ddof=1) / math.sqrt(len(m)))) if len(m) > 10 and m.std() > 0 else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("velas"); ap.add_argument("eventos")
    ap.add_argument("--dias", type=int, default=88); ap.add_argument("--minutos", type=float, default=200)
    ap.add_argument("--parte", help="k/n: solo baja y lee con la IA el tramo k de n (trabajos en paralelo)")
    a = ap.parse_args()
    if a.parte:
        k, n = map(int, a.parte.split("/"))
        rows = bajar(a.dias, (k, n))
        # la IA lee solo el primer titular de cada hecho (los demas medios toman esa lectura): rinde el tiempo
        from sentence_transformers import SentenceTransformer
        E = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2").encode(
            [r["titulo"] for r in rows], batch_size=64, normalize_embeddings=True, show_progress_bar=False)
        g = grupos_ia(np.array([r["t"] for r in rows], float), E, 0.80); pr = np.unique(g)
        print(f"{len(pr)} hechos distintos para la IA", flush=True)
        lei = dict(zip(pr, leer_ia([rows[i]["titulo"] for i in pr], a.minutos)))
        s = np.array([lei[g[i]] for i in range(len(rows))])
        with open(f"titulares_parte_{k}.jsonl", "w") as f:
            for r, x in zip(rows, s):
                f.write(json.dumps({**r, "ia": None if not np.isfinite(x) else round(float(x), 4)}) + "\n")
        print(f"parte {k}/{n}: {len(rows)} titulares, {int(np.isfinite(s).sum())} leidos por la IA")
        return
    import glob
    partes = sorted(glob.glob("titulares_parte_*.jsonl"))
    if partes:                                              # lo bajado y leido en paralelo
        vistos, rows = set(), []
        for r in sorted((json.loads(l) for p in partes for l in open(p)), key=lambda r: r["t"]):
            if r["titulo"].lower() not in vistos:
                vistos.add(r["titulo"].lower()); rows.append(r)
        print(f"{len(partes)} partes")
    else:
        rows = bajar(a.dias)
    t = np.array([r["t"] for r in rows], dtype=float)
    print(f"\n{len(rows)} titulares distintos en {a.dias} dias ({len({r['medio'] for r in rows})} medios): "
          + " · ".join(f"{k} {sum(GRUPO[r['tema']] == k for r in rows)}" for k in ("cripto", "guerras", "EE.UU. y la Fed")))

    from sentence_transformers import SentenceTransformer
    E = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2").encode(
        [r["titulo"] for r in rows], batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    gr = grupos_reglas(rows)
    G = {f"IA {u:.2f}": grupos_ia(t, E, u) for u in (0.70, 0.75, 0.80)}
    print("\nMISMA NOTICIA: hechos distintos")
    print(f"  cada titular {len(rows)} · reglas de hoy {len(set(gr))} · " + " · ".join(f"{k} {len(set(v))}" for k, v in G.items()))
    # para mirar a ojo: pares que la IA une y las reglas no, y al reves (con umbral 0.75)
    gi = G["IA 0.75"]; rnd = random.Random(1)
    for nom, cond in (("une la IA y no las reglas", lambda i, j: gi[i] == gi[j] and gr[i] != gr[j]),
                      ("unen las reglas y no la IA", lambda i, j: gr[i] == gr[j] and gi[i] != gi[j])):
        pares = [(j, i) for i in range(len(rows)) for j in (gi[i], gr[i]) if j != i and cond(i, j)]
        print(f"\n  ejemplos que {nom} ({len(pares)}):")
        for j, i in rnd.sample(pares, min(12, len(pares))):
            print(f"    · {rows[j]['titulo'][:110]}\n      = {rows[i]['titulo'][:110]}  (coseno {float(E[i] @ E[j]):.2f})")

    # lectura: reglas en cada titular, IA en el primero de cada hecho (con el umbral mas estricto; los demas usan esa)
    reglas = np.array([{"alcista": 1, "bajista": -1}.get(nt.sesgo(r["titulo"], r["tema"]), 0) for r in rows], float)
    if partes:
        ia = np.array([np.nan if r.get("ia") is None else r["ia"] for r in rows], float)
    else:
        g8 = G["IA 0.80"]; primeros = np.unique(g8)
        s = leer_ia([rows[i]["titulo"] for i in primeros], a.minutos)
        ia_hecho = dict(zip(primeros, s)); ia = np.array([ia_hecho[g8[i]] for i in range(len(rows))])
    print(f"\nLECTURA: reglas alcista {np.mean(reglas > 0):.0%} · bajista {np.mean(reglas < 0):.0%} · IA media {np.nanmean(ia):+.2f}"
          f" · coinciden en el signo {np.mean(np.sign(reglas[np.isfinite(ia)]) == np.sign(np.round(ia[np.isfinite(ia)], 1))):.0%}")

    # velas y modelo de movimiento fuerte de la app (prueba honesta)
    import entrenar_fuerte as ef, medir_compresion as mcomp
    B = json.load(open(a.velas)); evs = json.load(open(a.eventos))
    tv, lc, X = ef.señales(B, evs)
    desde = t[np.isfinite(ia)].min() + 4 * H; hasta = t[np.isfinite(ia)].max()
    sel = (tv >= desde) & (tv + H <= hasta)
    T = tv + H                                              # se conoce al cerrar la vela
    variantes = {}
    for lect, v in (("reglas", reglas), ("IA", ia)):
        ok = np.isfinite(v)
        for cuenta, g in (("cada titular", np.arange(len(rows))), ("hechos (reglas)", gr), ("hechos (IA)", G["IA 0.75"])):
            pr = np.array([i for i in range(len(rows)) if g[i] == i and ok[i]])
            variantes[f"{lect} · {cuenta}"] = senal(T, t[pr], v[pr])
    # cada tipo de noticia por separado (IA, hechos agrupados por IA)
    gi = G["IA 0.75"]
    for k in ("cripto", "guerras", "EE.UU. y la Fed"):
        pr = np.array([i for i in range(len(rows)) if gi[i] == i and np.isfinite(ia[i]) and GRUPO[rows[i]["tema"]] == k])
        if len(pr):
            variantes[f"IA · solo {k}"] = senal(T, t[pr], ia[pr])
    res, mitad = [], np.median(tv[sel])
    for que in ("para donde", "movimiento fuerte"):
        for hz in (1, 4):
            if que == "para donde":
                fut = np.full(len(lc), np.nan); fut[:-hz] = lc[hz:] - lc[:-hz]
                y, ok = (fut > 0).astype(float), np.isfinite(fut)
                base = np.zeros((len(lc), 0))
            else:
                y, ok = ef.objetivo(lc, hz)
                P, _, g_ = mcomp.honesto(tv, X, y, ok, hz)
                lp = np.log(np.clip(P, 1e-3, 1 - 1e-3) / (1 - np.clip(P, 1e-3, 1 - 1e-3)))
                ok = ok & np.isfinite(lp); base = lp[:, None]
            m = sel & ok
            p0 = logit_dia(tv[m], base[m], y[m], hz)
            nombre0 = "tasa base" if que == "para donde" else "modelo de la app"
            print(f"\nBTC {hz} h · {que}: {nombre0} contra {nombre0} + noticias (error de la probabilidad, z por dia)")
            for nom, (S, N) in variantes.items():
                F = np.column_stack([base[m], S[m]] if que == "para donde" else [base[m], np.abs(S[m]), np.log1p(N[m])])
                p1 = logit_dia(tv[m], F, y[m], hz)
                zs, txt = [], []
                for tramo, c in (("1ra mitad", tv[m] < mitad), ("2da mitad", tv[m] >= mitad)):
                    k = c & np.isfinite(p0) & np.isfinite(p1)
                    e0, e1 = (p0[k] - y[m][k]) ** 2, (p1[k] - y[m][k]) ** 2
                    z = z_dia(tv[m][k], e0 - e1); zs.append(z)
                    extra = ""
                    if que == "para donde":
                        dd = k & (np.abs(S[m]) > 1e-9)
                        extra = f", acierta {np.mean((S[m][dd] > 0) == (y[m][dd] > 0)):.0%} en {dd.sum()} h con noticias"
                    txt.append(f"{tramo} {e0.mean():.4f} → {e1.mean():.4f} z {z:+.1f}{extra}")
                    res.append({"que": que, "hz": hz, "variante": nom, "tramo": tramo, "horas": int(k.sum()), "hoy": round(float(e0.mean()), 5),
                                "con_noticias": round(float(e1.mean()), 5), "z": round(z, 2)})
                print(f"  {nom:<26} {' · '.join(txt)}  | mejora en las dos (z > 2): {'SI' if all(z > 2 for z in zs) else 'no'}", flush=True)
    json.dump({"titulares": len(rows), "hechos_reglas": len(set(gr)), **{k: len(set(v)) for k, v in G.items()}, "resultados": res},
              open("resultado_noticias_ia.json", "w"), ensure_ascii=False, indent=0)


if __name__ == "__main__":
    main()
