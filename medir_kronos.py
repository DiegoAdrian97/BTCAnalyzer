"""¿Kronos predice mejor que lo que ya usa la app? (medir antes de sumar)

Kronos (github.com/shiyu-coder/Kronos, MIT) es un modelo abierto entrenado con mas de 12.000 millones de velas de 45
mercados. Lee las ultimas 512 velas (apertura, maximo, minimo, cierre, volumen) y genera caminos posibles de las
proximas. Con 30 caminos por momento sale una probabilidad de subir, un rango, una chance de movimiento fuerte y un
precio esperado, y se comparan con lo que la app hace hoy, en los mismos momentos:

  - Para donde (proxima 1 h, 4 h y dia): error de la probabilidad de subir (Brier) contra la tasa base de los ultimos
    90 dias (lo que la app muestra cuando no tiene ventaja), y acierto contra el puntaje de direccion del analisis central.
  - Rango del 80% (1 h, 4 h, dia): puntaje de intervalo (ancho + 10 x lo que se paso afuera; menos es mejor) contra
    cuantiles de los ultimos 30 dias ajustados por volatilidad. A los dos se les aplica la misma calibracion "conformal"
    que usa la app (con sus 100 predicciones anteriores ya terminadas), asi se compara la forma y no el ancho.
  - Movimiento fuerte (1 h y 4 h, mas del doble de lo habitual): contra el modelo de arboles de la app (prueba honesta:
    cada trimestre, entrenado solo con lo anterior) y contra los dos promediados.
  - Precio esperado (mediana de los caminos): error contra "el precio queda donde esta".
Kronos crudo y calibrado (regresion logistica con sus propias predicciones anteriores ya terminadas, sin mirar el futuro).

Solo con momentos desde septiembre de 2025 (despues de que se publico Kronos, para no medirlo con velas que pudo ver)
y en dos tramos: sep-25 a feb-26 y mar-26 a hoy. Entra lo que mejora en los dos con z > 2 (diferencia por dia).

Uso: python medir_kronos.py velas_1h.json eventos.json MONEDA [--modelo mini|small|base] [--cada 8] [--muestras 30]
     [--minutos 300] [--prueba]
Necesita el repositorio de Kronos clonado en ./Kronos y torch (lo hace .github/workflows/kronos.yml).
"""
import argparse, datetime as dt, json, math, os, sys, time
import numpy as np
import pandas as pd
import torch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "Kronos"))
from model import Kronos, KronosTokenizer                         # noqa: E402
from model.kronos import calc_time_stamps, sample_from_logits     # noqa: E402

import entrenar_fuerte as ef                                       # noqa: E402
import medir_direccion as md                                       # noqa: E402
import medir_fuerza as mf                                          # noqa: E402

H, D = 3_600_000, 86_400_000
CTX = 512


def q(y, m):
    return dt.datetime(y, m, 1, tzinfo=dt.timezone.utc).timestamp() * 1000


DESDE = q(2025, 9)
TRAMOS = (("sep-25 a feb-26", q(2025, 9), q(2026, 3)), ("mar-26 a hoy", q(2026, 3), 1e18))
MODELOS = {"mini": ("NeoQuasar/Kronos-mini", "NeoQuasar/Kronos-Tokenizer-2k"),
           "small": ("NeoQuasar/Kronos-small", "NeoQuasar/Kronos-Tokenizer-base"),
           "base": ("NeoQuasar/Kronos-base", "NeoQuasar/Kronos-Tokenizer-base")}


# ---------- Kronos: caminos sin promediar ----------
def caminos_norm(tok, mod, X, XS, YS, pred_len, S, T=1.0, top_p=0.9):
    """Como auto_regressive_inference de Kronos, pero devuelve los S caminos (la libreria los promedia y se pierde el
    reparto). X, XS: (B, L, 6) y (B, L, 5) normalizados; YS: (B, pred_len, 5). Sale (B, S, pred_len, 6) normalizado."""
    with torch.no_grad():
        B, L, F = X.shape
        x, xs, ys = (a.repeat_interleave(S, 0) for a in (torch.clip(X, -5, 5), XS, YS))
        pre, post = tok.encode(x, half=True)
        sello = torch.cat([xs, ys], 1)
        for i in range(pred_len):
            fin = L + i
            st = sello[:, max(0, fin - CTX):fin].contiguous()
            s1, ctx = mod.decode_s1(pre[:, -CTX:], post[:, -CTX:], st)
            a = sample_from_logits(s1[:, -1, :], temperature=T, top_k=0, top_p=top_p, sample_logits=True)
            s2 = mod.decode_s2(ctx, a)
            b = sample_from_logits(s2[:, -1, :], temperature=T, top_k=0, top_p=top_p, sample_logits=True)
            pre, post = torch.cat([pre, a], 1), torch.cat([post, b], 1)
        z = tok.decode([pre[:, -CTX:].contiguous(), post[:, -CTX:].contiguous()], half=True)
        return z[:, -pred_len:, :].reshape(B, S, pred_len, F).cpu().numpy()


def caminos(tok, mod, arr, idxs, ms, pred_len, S, lote, limite):
    """Para cada origen i (ultima vela cerrada) S caminos de las proximas pred_len velas, en precios: (n, S, pred_len, 4)
    con apertura, maximo, minimo y cierre. Corta al pasar 'limite' (time.time); lo que no llego queda en NaN."""
    out = np.full((len(idxs), S, pred_len, 4), np.nan)
    t0 = time.time()
    for k in range(0, len(idxs), lote):
        if time.time() > limite:
            print(f"  tiempo agotado: {k} de {len(idxs)} momentos", flush=True)
            break
        sel = idxs[k:k + lote]
        X, XS, YS, mu, sd = [], [], [], [], []
        for i in sel:
            w = arr[i - CTX + 1:i + 1]
            x = np.column_stack([w[:, 1:5], w[:, 5], w[:, 5] * w[:, 1:5].mean(1)])
            m, s = x.mean(0), x.std(0)
            X.append((x - m) / (s + 1e-5)); mu.append(m); sd.append(s)
            XS.append(calc_time_stamps(pd.Series(pd.to_datetime(w[:, 0], unit="ms"))).values)
            YS.append(calc_time_stamps(pd.Series(pd.to_datetime(w[-1, 0] + ms * np.arange(1, pred_len + 1), unit="ms"))).values)
        tt = lambda a: torch.tensor(np.stack(a), dtype=torch.float32)   # noqa: E731
        z = caminos_norm(tok, mod, tt(X), tt(XS), tt(YS), pred_len, S)
        for j in range(len(sel)):
            out[k + j] = z[j][..., :4] * (sd[j][:4] + 1e-5) + mu[j][:4]
        if k == 0 or (k // lote) % 10 == 0:
            hechos = k + len(sel)
            print(f"  {hechos}/{len(idxs)} momentos · {(time.time() - t0) / hechos:.1f} s cada uno", flush=True)
    return out


# ---------- comparaciones ----------
def z_dia(t, dif):
    """z de la diferencia promedio con un dato por dia (los momentos del mismo dia no son independientes)."""
    dia = (t // D).astype(np.int64)
    u, inv = np.unique(dia, return_inverse=True)
    m = np.bincount(inv, weights=dif) / np.bincount(inv)
    if len(m) < 20 or m.std(ddof=1) == 0:
        return float("nan")
    return float(m.mean() / (m.std(ddof=1) / math.sqrt(len(m))))


def logit_online(t, p, y, h_ms, minimo=150):
    """Calibra p con una regresion logistica de sus predicciones anteriores ya terminadas (sin mirar el futuro)."""
    out = np.full(len(p), np.nan)
    lp = np.log(np.clip(p, 0.02, 0.98) / (1 - np.clip(p, 0.02, 0.98)))
    orden = np.argsort(t)
    for n_, i in enumerate(orden):
        prev = orden[:n_][t[orden[:n_]] + h_ms <= t[i]]
        if len(prev) < minimo:
            continue
        a, b = 1.0, 0.0
        for _ in range(60):                                   # Newton, 2 parametros
            f = 1 / (1 + np.exp(-(a * lp[prev] + b)))
            g = f - y[prev]; w_ = f * (1 - f) + 1e-9
            Hm = np.array([[np.sum(w_ * lp[prev] ** 2), np.sum(w_ * lp[prev])], [np.sum(w_ * lp[prev]), np.sum(w_)]]) + 1e-6 * np.eye(2)
            da, db = np.linalg.solve(Hm, [np.sum(g * lp[prev]), np.sum(g)])
            a, b = a - da, b - db
        out[i] = 1 / (1 + np.exp(-(a * lp[i] + b)))
    return out


def conformal(t, lo, me, hi, y, h_ms, ultimas=100, minimo=30):
    """Ensancha o angosta cada rango con el factor que habria dejado adentro al 80% de las ultimas predicciones ya
    terminadas (como rango_factor de la app)."""
    s = np.maximum(np.where(y > me, (y - me) / np.maximum(hi - me, 1e-12), 0), np.where(y < me, (me - y) / np.maximum(me - lo, 1e-12), 0))
    k = np.ones(len(t))
    for i in range(len(t)):
        prev = np.where(t + h_ms <= t[i])[0]
        prev = prev[np.argsort(t[prev])][-ultimas:]
        if len(prev) >= minimo:
            k[i] = np.quantile(s[prev], 0.8)
    return me - k * (me - lo), me + k * (hi - me)


def winkler(lo, hi, y):
    return (hi - lo) + 10 * np.maximum(0, lo - y) + 10 * np.maximum(0, y - hi)


def tramo_txt(nombre, a, b, z):
    return f"{nombre}: {a} contra {b} (z {z:+.1f})"


def comparar(res, clave, t, perdidas, nombres, menos_es_mejor=True, extra=None):
    """perdidas: dict nombre -> arreglo de perdida por momento (menos es mejor). Compara cada una contra la primera."""
    ref = nombres[0]
    fila = {"tramos": []}
    for nom, a, b in TRAMOS:
        s = (t >= a) & (t < b) & np.all([np.isfinite(perdidas[n]) for n in nombres], axis=0)
        if s.sum() < 40:
            continue
        tr = {"tramo": nom, "n": int(s.sum()), "media": {n: float(np.mean(perdidas[n][s])) for n in nombres}}
        tr["z_vs_" + ref] = {n: z_dia(t[s], perdidas[ref][s] - perdidas[n][s]) for n in nombres[1:]}
        if extra:
            tr.update(extra(s))
        fila["tramos"].append(tr)
    res[clave] = fila
    gana = {n: len(fila["tramos"]) == len(TRAMOS) and all(tr["z_vs_" + ref][n] > 2 for tr in fila["tramos"]) for n in nombres[1:]}
    fila["mejora_en_los_dos"] = gana
    print(f"\n{clave}")
    for tr in fila["tramos"]:
        m = tr["media"]
        print(f"  {tr['tramo']} ({tr['n']} momentos): " + " · ".join(f"{n} {m[n]:.4f}" for n in nombres)
              + "  |  z contra " + ref + ": " + ", ".join(f"{n} {tr['z_vs_' + ref][n]:+.1f}" for n in nombres[1:])
              + "".join(f" · {k_} {v}" for k_, v in tr.items() if k_ not in ("tramo", "n", "media", "z_vs_" + ref)))
    print("  mejora en los dos tramos (z > 2): " + ", ".join(f"{n} {'SI' if g else 'no'}" for n, g in gana.items()))
    return fila


def evaluar(res, pref, t_or, lc, I, kr_h, h, ms, base_up, rango_base, extra_dir=None):
    """Direccion, rango y precio para un horizonte. kr_h: (n, S) retornos log de los caminos de Kronos."""
    ok = np.isfinite(kr_h).all(1) & (I + h < len(lc))
    I, kr_h, t, bu = I[ok], kr_h[ok], t_or[ok], base_up[ok]
    y_r = lc[I + h] - lc[I]; y = (y_r > 0).astype(float)
    pk = (kr_h > 0).mean(1)
    pc = logit_online(t, pk, y, h * ms)
    perd = {"tasa base": (bu - y) ** 2, "Kronos": (pk - y) ** 2, "Kronos calibrado": (pc - y) ** 2}

    def acierto(s):
        r = {"acierta Kronos": f"{100 * np.mean((pk[s] > 0.5) == (y[s] == 1)):.1f}%"}
        if extra_dir is not None:
            sc = extra_dir[ok][s]; a = np.abs(sc) >= 1
            if a.sum() >= 30:
                r["acierta puntaje de la app"] = f"{100 * np.mean((sc[a] > 0) == (y[s][a] == 1)):.1f}% en {a.sum()}"
                r["Kronos en esos mismos"] = f"{100 * np.mean((pk[s][a] > 0.5) == (y[s][a] == 1)):.1f}%"
        return r
    comparar(res, f"{pref} · para donde (error de la probabilidad de subir)", t, perd, list(perd), extra=acierto)
    # rango del 80%
    lo_k, me_k, hi_k = np.quantile(kr_h, [0.1, 0.5, 0.9], axis=1)
    lo_b, me_b, hi_b = rango_base[0][ok], rango_base[1][ok], rango_base[2][ok]
    lo_k, hi_k = conformal(t, lo_k, me_k, hi_k, y_r, h * ms)
    lo_b, hi_b = conformal(t, lo_b, me_b, hi_b, y_r, h * ms)
    cob = lambda lo, hi, s: f"{100 * np.mean((y_r[s] >= lo[s]) & (y_r[s] <= hi[s])):.0f}%"   # noqa: E731
    comparar(res, f"{pref} · rango del 80% (puntaje de intervalo, en log)", t,
             {"lo de hoy": winkler(lo_b, hi_b, y_r), "Kronos": winkler(lo_k, hi_k, y_r)}, ["lo de hoy", "Kronos"],
             extra=lambda s: {"adentro hoy": cob(lo_b, hi_b, s), "adentro Kronos": cob(lo_k, hi_k, s),
                              "ancho hoy": f"{100 * np.mean(hi_b[s] - lo_b[s]):.2f}%", "ancho Kronos": f"{100 * np.mean(hi_k[s] - lo_k[s]):.2f}%"})
    # precio esperado
    comparar(res, f"{pref} · precio esperado (error absoluto, en log)", t,
             {"queda donde esta": np.abs(y_r), "Kronos (mediana)": np.abs(me_k - y_r)}, ["queda donde esta", "Kronos (mediana)"])
    return ok, pk, pc, y_r


def rango_hist(lc, I, h, vent, vol_n):
    """Rango de hoy (aproximado): cuantiles 10/50/90 de los movimientos de h velas de la ventana, en veces la volatilidad
    de cada momento, por la volatilidad de ahora."""
    r1 = np.diff(lc, prepend=lc[0])
    vol = pd.Series(r1).rolling(vol_n).std().values
    zf = np.full(len(lc), np.nan)
    zf[:-h] = (lc[h:] - lc[:-h]) / (vol[:-h] * math.sqrt(h))
    out = np.full((3, len(I)), np.nan)
    for k, i in enumerate(I):
        w = zf[max(0, i - vent - h):i - h + 1]
        w = w[np.isfinite(w)]
        if len(w) > 50 and np.isfinite(vol[i]):
            out[:, k] = np.quantile(w, [0.1, 0.5, 0.9]) * vol[i] * math.sqrt(h)
    return out


def tasa_base(lc, I, h, vent):
    up = np.full(len(lc), np.nan); up[:-h] = (lc[h:] > lc[:-h]).astype(float)
    return np.array([np.nanmean(up[max(0, i - vent - h):i - h + 1]) for i in I])


def a_diarias(arr):
    """Velas de 1 hora -> diarias (UTC), solo dias completos."""
    dia = (arr[:, 0] // D).astype(np.int64)
    out = []
    for d_ in np.unique(dia):
        w = arr[dia == d_]
        if len(w) == 24:
            out.append([d_ * D, w[0, 1], w[:, 2].max(), w[:, 3].min(), w[-1, 4], w[:, 5].sum()])
    return np.asarray(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("velas"); ap.add_argument("eventos"); ap.add_argument("moneda")
    ap.add_argument("--modelo", default="mini", choices=list(MODELOS)); ap.add_argument("--cada", type=int, default=8)
    ap.add_argument("--muestras", type=int, default=30); ap.add_argument("--minutos", type=float, default=300)
    ap.add_argument("--lote", type=int, default=8); ap.add_argument("--prueba", action="store_true")
    a = ap.parse_args()
    torch.set_num_threads(os.cpu_count() or 4); torch.manual_seed(7); np.random.seed(7)
    inicio = time.time(); limite = inicio + a.minutos * 60
    B = json.load(open(a.velas)); evs = json.load(open(a.eventos))
    arr = np.asarray([b[:6] for b in B], dtype=np.float64)
    t, c = arr[:, 0], arr[:, 4]; lc = np.log(c)
    mod_id, tok_id = MODELOS[a.modelo]
    tok = KronosTokenizer.from_pretrained(tok_id).eval(); mod = Kronos.from_pretrained(mod_id).eval()
    print(f"{a.moneda}: {len(B)} velas de 1 h · Kronos-{a.modelo} · {a.muestras} caminos · un momento cada {a.cada} h", flush=True)
    res = {"moneda": a.moneda, "modelo": a.modelo, "muestras": a.muestras, "cada_h": a.cada}

    # ---- velas de 1 hora: proxima 1 h y 4 h ----
    I = np.array([i for i in range(CTX + 2000, len(B) - 4) if t[i] >= DESDE and int(t[i] // H) % a.cada == 0])
    if a.prueba:
        I = I[np.linspace(0, len(I) - 1, 16).astype(int)]
    # en orden mezclado: si se acaba el tiempo, lo hecho queda repartido entre los dos tramos
    orden = np.random.permutation(len(I))
    kr = caminos(tok, mod, arr, I[orden], H, 4, a.muestras, a.lote, limite)
    P = np.full_like(kr, np.nan); P[orden] = kr
    hecho = np.isfinite(P).all(axis=(1, 2, 3))
    I, P = I[hecho], P[hecho]
    res["momentos_1h"] = int(len(I))
    print(f"{len(I)} momentos con Kronos", flush=True)
    score = np.array([np.dot(md.senales(B[i - 1999:i + 1]), md.PESOS_NUEVOS) for i in I])
    tt, lc_f, X = ef.señales(B, evs)
    for h in (1, 4):
        kr_h = np.log(P[:, :, h - 1, 3]) - lc[I][:, None]
        ok, pk, pc, y_r = evaluar(res, f"{a.moneda} {h} h", t[I], lc, I, kr_h, h, H, tasa_base(lc, I, h, 90 * 24),
                                  rango_hist(lc, I, h, 720, 72), extra_dir=score)
        # movimiento fuerte: contra el modelo de arboles (prueba honesta por trimestre)
        y_all, ok_all = ef.objetivo(lc_f, h)
        Pl, base_l, good = mf.honesto(tt, X, y_all, ok_all, h)
        past = np.full(len(lc_f), np.nan); past[h:] = np.abs(lc_f[h:] - lc_f[:-h])
        ew = np.full(len(lc_f), np.nan); m_ = None
        for i in range(len(lc_f)):
            if not np.isnan(past[i]):
                m_ = past[i] if m_ is None else (2 / 2001) * past[i] + (1 - 2 / 2001) * m_
            ew[i] = np.nan if m_ is None else m_
        Iok = I[ok]
        yf = y_all[Iok]
        pkf = (np.abs(kr_h[ok]) > 2 * ew[Iok][:, None]).mean(1)
        sel = ok_all[Iok] & np.isfinite(Pl[Iok])
        pkc = np.full(len(Iok), np.nan)
        pkc[sel] = logit_online(t[Iok][sel], pkf[sel], yf[sel], h * H)
        mix = (Pl[Iok] + pkc) / 2
        comparar(res, f"{a.moneda} {h} h · movimiento fuerte (error de la probabilidad)", t[Iok][sel],
                 {"modelo de la app": (Pl[Iok][sel] - yf[sel]) ** 2, "Kronos calibrado": (pkc[sel] - yf[sel]) ** 2,
                  "promedio de los dos": (mix[sel] - yf[sel]) ** 2, "tasa base": (base_l[Iok][sel] - yf[sel]) ** 2},
                 ["modelo de la app", "Kronos calibrado", "promedio de los dos", "tasa base"])

    # ---- velas diarias: el dia siguiente ----
    Dd = a_diarias(arr); td, lcd = Dd[:, 0], np.log(Dd[:, 4])
    Id = np.array([i for i in range(CTX + 60, len(Dd) - 1) if td[i] >= DESDE])
    if a.prueba:
        Id = Id[np.linspace(0, len(Id) - 1, 8).astype(int)]
    if len(Id) and time.time() < limite + 30 * 60:
        od = np.random.permutation(len(Id))                    # mezclado, como arriba
        Pm = caminos(tok, mod, Dd, Id[od], D, 1, a.muestras, a.lote, limite + 30 * 60)
        Pd = np.full_like(Pm, np.nan); Pd[od] = Pm
        hd = np.isfinite(Pd).all(axis=(1, 2, 3)); Id, Pd = Id[hd], Pd[hd]
        res["momentos_dia"] = int(len(Id))
        evaluar(res, f"{a.moneda} 1 dia", td[Id], lcd, Id, np.log(Pd[:, :, 0, 3]) - lcd[Id][:, None], 1, D,
                tasa_base(lcd, Id, 1, 90), rango_hist(lcd, Id, 1, 365, 30))
    else:
        print(f"{a.moneda}: sin velas diarias suficientes ({len(Dd)} dias)")
    res["minutos"] = round((time.time() - inicio) / 60, 1)
    json.dump(res, open(f"resultado_kronos_{a.moneda}.json", "w"), ensure_ascii=False, indent=1, default=float)
    print(f"\nlisto en {res['minutos']} min")


if __name__ == "__main__":
    main()
