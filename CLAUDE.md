# Preferencias de Diego (para Claude)

- Responder siempre en español (rioplatense), salvo que pida inglés.
- Respuestas resumidas: sin texto innecesario, para ahorrar tokens. Ir al punto.

# Al crear, mejorar u optimizar una app o página (este u otro proyecto)

Revisar esta lista y aplicar lo que corresponda (medir antes y después; decir cuáles no aplican y por qué):
skeletons de carga · evitar llamadas duplicadas a la API · paginar resultados de la API · mandar lo lento a una cola de
trabajos · arreglar consultas N+1 · compresión brotli/gzip · cachear lo más consultado (Redis o equivalente) · quitar
dependencias sin usar · actualizar la interfaz sin esperar al servidor (optimista) · lazy loading · peticiones
independientes en paralelo · índices para las consultas más comunes · rastrear peticiones lentas (OpenTelemetry o
equivalente) · renderizar en el servidor o en el build · virtualizar listas largas · pool de conexiones · evitar
re-renders innecesarios · cachear estáticos en el navegador · repartir tráfico entre instancias · alojar las fuentes
y limitar los grosores · monitorear la velocidad de usuarios reales · probar en celulares y redes lentas.
En este proyecto: `node pruebas/celular_lento.js [3g|4g|lejos]` (ver README, "Optimizaciones de velocidad").

# Plan de compras (privado)

El plan (`plan_compras.json`) vive en el repositorio privado DiegoAdrian97/BTCAnalyzer-plan, nunca en este (es público):
para cambiarlo, adjuntar ese repo a la sesión, editarlo ahí y subirlo. No copiarlo acá ni meterlo en la página.

