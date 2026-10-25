# Rutina: Analista BTC (5 veces por día)

Instrucciones para la rutina programada de Claude que actualiza el dashboard
https://claude.ai/artifact/KJHPwo3w4HDdXb5HDeXgX9 a las 8, 12, 16, 20 y 0 h (hora Argentina, UTC-3).

Solo análisis: no hay claves de exchanges en este repositorio y la rutina no opera.

## Pasos

1. `pip install -r requirements.txt`
2. `python analisis_btc.py`
   Si falla porque Binance no responde desde este servidor (error 451 u otro de red), terminar e informar
   el error: no inventar datos.
3. Buscar en la web las noticias de las últimas 24 h que mueven a BTC: datos macro de EE.UU. (inflación,
   empleo, Fed), flujos de los ETF de BTC, movimientos grandes de ballenas o exchanges, regulación, y
   cualquier evento con hora en las próximas 24 h.
   Escribir `nota.txt` en español, 5 a 8 líneas cortas:
   - qué pasó y qué viene (con horario en hora Argentina si lo tiene),
   - si eso refuerza o contradice lo que dice el análisis técnico (leer `data/analisis_btc.json`, fila
     `tabla=resumen` y filas `tabla=probabilidad` de `tf=1h`),
   - una línea final: "Sesgo de las noticias: alcista / bajista / neutral".
   Sin recomendaciones de compra o venta. Citar la fuente de cada dato entre paréntesis.
4. `python analisis_btc.py --nota nota.txt`
5. Subir `data/analisis_btc.json` al dashboard como archivo (Artifact, `asset: true`, url del dashboard).
6. Leer el documento `datasets/analisis` del dashboard y actualizarlo (ArtifactData `update` con el
   `if_version` leído) con:
   - `source.url`: "/_blob/" + el id del archivo recién subido, `source.kind` "file", `source.name` "analisis_btc.json"
   - `updated`: `{at: <hora ISO actual>, by: "Rutina Claude"}`
   - `lastAttempt`: `{at: <hora ISO actual>, ok: true, by: "Rutina Claude"}`
   Si algún paso anterior falló, escribir solo `lastAttempt` con `ok: false` y el motivo en `error`.
7. Guardar el registro de pronósticos para la próxima corrida:
   `git add data/predicciones_btc.csv data/analisis_btc.json && git commit -m "Analisis <fecha>" && git push`
8. Responder en 3 líneas: precio, la lectura principal (fila resumen, campo `lectura`) y el sesgo de las noticias.
