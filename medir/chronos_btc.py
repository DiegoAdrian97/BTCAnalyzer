"""Pronosticos zero-shot de Chronos-Bolt (Amazon) para BTC 1h: cada 3 horas desde 2024, contexto de 512 velas,
cuantiles 10-90% a 1 y 4 horas. python medir/chronos_btc.py modelo salida.csv"""
import csv, gzip, json, sys, time
import numpy as np, torch
from chronos import BaseChronosPipeline
modelo, out = sys.argv[1], sys.argv[2]
B = json.load(gzip.open("medir/monedas/BTCUSDT.json.gz"))
t = np.array([b[0] for b in B]); c = np.array([b[4] for b in B], dtype=np.float32)
ini = np.searchsorted(t, 1704067200000)                   # 2024-01-01
idx = list(range(max(ini, 512), len(c), 3))
pipe = BaseChronosPipeline.from_pretrained(f"amazon/{modelo}", device_map="cpu", torch_dtype=torch.float32)
Q = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
t0 = time.time()
with open(out, "w", newline="") as f:
    w = csv.writer(f); w.writerow(["t", "c"] + [f"h{h}_q{int(q*100)}" for h in (1, 4) for q in Q])
    for k in range(0, len(idx), 256):
        lote = idx[k:k + 256]
        ctx = [torch.tensor(c[i - 511:i + 1]) for i in lote]
        qs, _ = pipe.predict_quantiles(context=ctx, prediction_length=4, quantile_levels=Q)
        qs = qs.numpy()                                      # [n, 4, 9]
        for j, i in enumerate(lote):
            w.writerow([int(t[i]), float(c[i])] + [round(float(x / c[i]), 6) for h in (0, 3) for x in qs[j, h]])
        print(k, len(idx), round(time.time() - t0), flush=True)
