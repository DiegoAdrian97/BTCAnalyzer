# BTCAnalyzer

Analista de BTC/USDT perpetuo con un dashboard en vivo: predicción por plazo (5 min a 1 día),
gráfico con figuras, divergencias, liquidaciones estimadas, libros de órdenes y más de
30 indicadores. Datos públicos de Binance Futures, Bybit, OKX, Bitget y BingX (no usa claves).

El gráfico usa el motor de TradingView ([Lightweight Charts](https://www.tradingview.com/lightweight-charts/)): mismas velas, ejes, mira y
gestos, con las marcas del analista encima (patrones, divergencias, ondas, FVG, liquidaciones y niveles). La simulación de
futuro (velas típico, alcista y bajista y su cono) ya no se dibuja: `SIN_FUTURO` en `dashboard/index.html`.
**Qué estás viendo** (debajo del gráfico): pasar el mouse por una línea (o mantener apretado con el dedo) enciende eso
en el gráfico y apaga lo demás; un clic o un toque lo deja **marcado** (✓, se pueden marcar varios) hasta volver a
tocarlo o "Quitar marcas". En pantalla completa va en un panel a la derecha: fijo en pantallas anchas; en el celular
se abre con ⓘ y se cierra con ✕, deslizando a la derecha o con Esc.
Capa **EMA 20 / 50 / 200**: azul, naranja y una gris más gruesa (la EMA 200 de esa temporalidad, en todos los activos;
solo aparece donde hay 200 velas para calcularla, así que en la mensual no).
Herramientas: **Mi plan** (las compras que faltan de `plan_compras.json`, tu promedio, la próxima toma de ganancias y la
liquidación, como líneas con nombre), **Medir** (Shift + arrastrar o el botón: %, precio, velas y tiempo entre dos puntos),
**Imán** (la mira y los puntos de Medir se pegan a la apertura, máximo, mínimo o cierre; Cmd/Ctrl mientras medís lo invierte), escala **Log**, **»** para volver a la última vela, **Imagen** (en el iPhone se comparte, en la compu se baja) y teclas con el
mouse sobre el gráfico (← → moverse, + − zoom, 0 ajustar, L, M, I, 1 a 6 temporalidad, F pantalla completa, Esc). Botón ☀/☾ al lado de la campanita: modo claro u oscuro (sin elegir, sigue al sistema; se recuerda en ese navegador). Verde y rojo
validados para daltonismo (deuteranopia: diferencia 11 en claro y 9 en oscuro; los anteriores daban 5-6).

No es una recomendación de inversión.

## Aprendizaje automático

El analista aprende solo de sus predicciones acertadas y erradas (`aprendizaje.py` y su traducción
`JavascriptVersion/aprendizaje.js`, mismos números). Cada vez que cierra una vela, para cada plazo:

1. Repasa sus últimas 1.000 predicciones, cada una calculada solo con lo que se sabía en ese momento, y las
   compara con lo que pasó (qué tocó primero y si cerró arriba).
2. Trabaja con un equipo de expertos: 8 recetas de "situaciones parecidas" (medias, RSI, MACD, volatilidad,
   Bollinger, movimiento del día), un modelo que aprende solo con cada vela (regresión logística en línea sobre
   20 números: movimientos medidos en ATR, distancia a las medias, RSI, MACD, Bollinger, volatilidad, volumen,
   hora del día y fin de semana) y la tasa base ("lo normal", sin mirar nada).
3. Con cada resultado ajusta cuánto le cree a cada uno (pesos exponenciales con reparto fijo, para adaptarse
   cuando el mercado cambia) y calibra la confianza del equipo: si venía exagerado lo modera.

Medición honesta: un resultado se usa para aprender recién cuando se conoce (h velas después) y cada predicción
se juzga con lo que había antes. La "ventaja" es cuánto menos error tiene que la tasa base; el margen de error
de los aciertos cuenta que las predicciones que se pisan comparten resultado (a 1 hora, 1.000 predicciones
valen como ~80 independientes). Probado con velas reales de BTC: los parámetros se ajustaron con 2023–2024 y se
verificaron con 2025–2026; el modelo le gana a la tasa base en los 5 plazos, por poco (0,1–0,4% menos error),
y las recetas solas casi nunca. Todo sale de las velas, así que no se pierde cuando Render borra el disco.
En el dashboard: sección "Cómo viene aprendiendo".

### Próximas compras (plan de Diego)

**Plan privado** (para que nadie lo vea, aunque tenga acceso a este repositorio): el plan va en un repositorio
privado (`DiegoAdrian97/BTCAnalyzer-plan`, archivo `plan_compras.json`); acá no está (y `.gitignore` evita subirlo
por error), y la página publicada no lo lleva adentro. La función `api/posiciones` lo lee con un token
de GitHub de solo lectura (`PLAN_GITHUB_TOKEN` en Vercel) y lo entrega solo con la contraseña de BingX; Render y los
avisos de Telegram lo leen con el mismo token (`PLAN_GITHUB_TOKEN` en Render; `util.leer_plan()`). En la PC, sin token,
sirve un `plan_compras.json` local. Si estás conectado pero el plan no llega, Mis posiciones muestra igual el PnL en
vivo y dice qué falta.

**Solo con BingX conectado**: Tu plan (Próximas compras), Mis posiciones, la capa "Mi plan" del gráfico y sus avisos
se ven solo si en ese navegador se conectó BingX con la contraseña de Vercel (`POSICIONES_CLAVE`) y el servidor la
aceptó. Sin conectar, arriba (al lado de la campanita) aparece una llave para hacerlo; "Desconectar BingX" lo oculta
de nuevo. La página de Render, que ya pide su propia contraseña, los muestra como antes. Ojo: esto los oculta en la
pantalla; el plan en sí ya no está en la página ni en este repositorio (ver "Plan privado").

`plan_compras.json` guarda el plan de compras escalonadas (longs a 5x en BingX, margen aislado): moneda, número,
precio, valor de la orden, margen extra y si la orden ya está cargada y el margen agregado. La página lo muestra en
"Próximas compras": por cada cripto, dónde está el precio ahora (línea punteada), qué compras ya se ejecutaron,
cuáles tienen la orden puesta y cuáles falta cargar (en rojo si el precio está a 3% o menos). Con BingX conectado
(Mis posiciones), una compra cuenta como ejecutada si el precio llegó **y** la posición creció lo que suman las compras
hasta esa (de la más alta a la más baja, con 10% de margen por el redondeo): queda "Se ejecutó · en tu posición" y
entra en el promedio, el margen y la liquidación. Si el precio llegó pero la posición no creció, sale ⚠ "revisá la
orden" y no se cuenta. Sin BingX, como antes: el mínimo desde que se armó el plan tocó su precio. Telegram avisa aunque esté en "solo entradas": 📌 cuando el precio se acerca a 3% de
una compra sin orden cargada, ✅ cuando se ejecuta una (con el margen extra a sumar si falta) y ⚠ si tocó un precio
sin orden. Cuando cambie el plan: editar `plan_compras.json` en el repositorio privado `DiegoAdrian97/BTCAnalyzer-plan`
y subirlo (la app lo toma sola en un minuto; Render, en cinco). Ya no hace falta regenerar la página.

### Mis posiciones, toma de ganancias y piramidado

**BingX en vivo (solo lectura, versión del teléfono):** con "Conectar BingX", "Mis posiciones" sale de tu cuenta (cantidad,
entrada, margen y liquidación de BingX) y "Próximas compras" marca "orden puesta" si hay una orden límite de compra a ese precio.
Lo hace la función `JavascriptVersion/api/posiciones.js` de Vercel con tres variables de entorno (Settings → Environment
Variables; nunca en el código): `BINGX_API_KEY` y `BINGX_API_SECRET` de una clave de API de BingX **con permiso solo de
lectura**, y `POSICIONES_CLAVE`, una contraseña tuya (8 caracteres o más) que la página pide una vez. Sin las tres, o con la
contraseña mal, no devuelve nada. Si BingX rechaza los pedidos desde EE.UU., elegí una región europea para las funciones en
Vercel (Settings → Functions). Sin conectar, todo sigue saliendo de `plan_compras.json` como antes.

Debajo de "Próximas compras": por cripto, parte de lo que ya estaba abierto en BingX (`posiciones` en
`plan_compras.json`: cantidad, entrada y margen) y le suma las compras del plan que se ejecutan después. Muestra
cantidad, precio promedio, resultado, margen, apalancamiento real y liquidación aproximada (`posiciones.py`; la
página hace las mismas cuentas). Si cambiás algo en BingX a mano, hay que actualizar `posiciones`. Toma de ganancias: cada +25% sobre el promedio, pasar 25% de la posición a spot.
Piramidar: cuando sube 15% sobre el promedio, cuánto se puede sumar sin plata nueva con la liquidación como mucho en
75% de la compra más baja. Los porcentajes se cambian en `plan_compras.json` (`ganancias`, `piramidar`).

**Precio de equilibrio** (en vez del promedio): el que deja la posición en cero contando las comisiones de BingX,
como el que muestra BingX. Con BingX conectado: el de BingX si lo da; si no, la entrada con lo ya realizado (comisiones
pagadas y funding) y la comisión de cerrar. Sin conectar: entrada × (1 + comisión) / (1 − comisión), con la comisión
taker de 0,05% por lado (`comision` en el plan si es otra). La toma de ganancias (+25%) y el piramidado (+15%) se
cuentan sobre el equilibrio; la entrada se ve abajo, más chica. Telegram (`posiciones.py`) hace la misma cuenta.

**PnL no realizado de todas las posiciones** (arriba de Mis posiciones, con BingX conectado): la suma del resultado de
cada posición abierta en BingX, con su % sobre el margen y el de cada cripto. Va en vivo: BingX se lee cada minuto y
entre lectura y lectura se mueve con el precio de marca de Binance cada 1 s (WebSocket `markPrice@1s`; resultado +
cantidad × (precio de ahora − precio al leer BingX), así la diferencia entre la marca de Binance y la de BingX no suma
error). El punto verde dice que llegan precios; gris, que se está usando el de cada 15 s. Se corta con la app en
segundo plano o al mirar una acción.

### Notificaciones en la página

La campanita al lado del título junta los avisos, en el propio dispositivo: cambio de zona del termómetro, funding
de 7 días extremo, compra del plan a menos de 3% o ejecutada, liquidación a menos de 10%, toma de ganancias alcanzada
y piramidado disponible. Al tocar una se abre el detalle con un botón a la sección. Se guardan en el navegador
(las últimas 60) y se generan mientras la página está abierta. La primera vez solo anota cómo está todo.
"Se acerca a tu compra" avisa la primera vez que el precio queda a 3% o menos; después vuelve a avisar solo si salió
de esa zona y hace un nuevo mínimo (más bajo que todo lo que marcó desde el aviso anterior): un rebote que vuelve a
bajar del 3% sin pasar ese mínimo no avisa. Telegram (`avisos.py`) sigue la misma regla.

### Comandos de Telegram

El bot contesta cuando le escribís (no manda nada por su cuenta): `/estado`, `/medidor` (BTC, XRP y SOL),
`/compras`, `/posiciones` y `/ayuda`. Solo responde al chat de `TELEGRAM_CHAT`. El bot también guarda su memoria
(resultados, pausa por pérdidas, operaciones abiertas, avisos ya mandados) en un mensaje fijado de ese chat, que edita
en silencio: así un reinicio de Render no la pierde. No lo borres.

### On-chain, stablecoins, liquidaciones reales y calibración (medidos)

- **MVRV y Puell** (CoinMetrics, gratis) entran en el "barato o caro" del termómetro de BTC. Medido 2019–2026 sin
  mirar el futuro: a 6 meses el medidor separa mejor en los dos tramos (2019–22: 0,870 → 0,893; 2023–26: 0,841 →
  0,863), a 12 meses queda igual (0,965 → 0,963). Solo, el MVRV anticipa menos que lo que ya había (0,77 a 12 meses),
  por eso no pesa más. El de hoy se estima con lo último de CoinMetrics (el reentrenamiento ahora es semanal).
- **Hash ribbons y emisión de stablecoins:** no anticiparon de forma pareja (en 2023–26, al revés): quedaron afuera.
- **Índice FRELDI** (Fear & Greed, RSI 14 diario, distancia a la EMA de 200, volumen contra el máximo del mes, liquidez de
  la semana y DXY, de 0 a 100; su fórmula exacta no es pública, se reconstruyó con percentiles sin mirar el futuro): no
  anticipa. AUC de que BTC suba entre 0,40 y 0,48 de 1 a 365 días (2019–26; menos de 0,5 es al revés). Su zona de
  "acumulación" (>80) subió 6% de las veces a 90 días y la de "distribución" (<25), 75%. Sumado al medidor lo empeora en
  todos los plazos (12 meses: 0,962 → 0,949 con 10%). Quedó afuera.
- **Otros indicadores de ciclo** (noviembre 2026, mismo método, sumados al "barato o caro"): MVRV Z, múltiplo de Mayer
  (200 días), media de 2 años, Pi Cycle, ley de potencia, Thermocap, Metcalfe (direcciones activas), hash price y
  volatilidad de 90 días; y en el ciclo, los días desde el máximo y la ley de potencia. Ninguno mejoró en 2019–22 y en
  2023–26 a la vez (los mejores: +0,01 en un tramo y −0,01 en el otro). El medidor ya separa 0,96–0,99 a 12 meses:
  quedan afuera.
- **Liquidaciones reales** (OKX, BTC-USDT, la última hora): en "Qué está pasando" y en la campanita cuando hay una
  barrida (2 M USD o más de un lado en 15 min solo en OKX). Sin peso en las probabilidades: no hay historia gratis
  para medir qué pasa después.
- **Calibración:** las predicciones del repaso ya salen calibradas (lo que dice 60% pasa ~56–60%; error medio 0,5–1,5
  puntos en 2020–2026). Corregirlas aparte no mejoró fuera de muestra, así que solo se muestra el gráfico "¿Las
  probabilidades son honestas?" en "Cómo viene aprendiendo".

### Velas semanales y mensuales

Botones **1S** y **1M** en el gráfico, para todos los activos: se arman con las 1.500 velas diarias (~214 semanas y ~49
meses; la semana empieza el lunes, como en Binance) y se actualizan en vivo. Tienen indicadores, sesgo técnico, giros,
Elliott, FVG, patrones y divergencias, pero no predicción ni escenarios: con tan pocas velas no se puede repasar si
acertaría. En la mensual, la EMA de 200 no se muestra (hacen falta 200 meses).

### Fibonacci

Medido con BTC 2020–2026: solo los retrocesos del swing de 90 días en velas de 4 h rebotaron más que un nivel
cualquiera (57% contra 49%, y se repitió en 2020–22 y 2023–26). En 1 h, diario y semanal no hubo ventaja. Por eso
el análisis muestra esos niveles con el rebote medido de cada uno (el 61,8% es el peor: 42%) y la explicación lo
menciona cuando el precio está a menos de 0,4% de uno que rebotó 55% o más. En el gráfico es una capa más
(**Fibonacci**, junto a EMA, Bollinger, FVG, etc.): se prende y se apaga para todos los activos y se ve en todas las
temporalidades. Cada nivel
es una línea violeta punteada tenue con su texto encima ("Fib 61,8% · 97.230 · rebotó 42%"; más marcada si rebotó 55% o
más), no una etiqueta en el eje: así no tapa el precio, el soporte, la resistencia ni las liquidaciones. Como en
TradingView, muestra también el 0% (fin del tramo) y el 100% (inicio), con una diagonal entre los dos puntos: arrastrar
un punto lo cambia (pegado a la vela; con el Imán, a su apertura, máximo, mínimo o cierre) y arrastrar la diagonal lo
mueve entero. El ajustado a mano se guarda por activo en el navegador y no lleva el
rebote medido (ese es del automático); "Volver al automático" en Qué estás viendo lo borra. Los extremos del tramo
salen de `fib_tramo` (Python) / `fibTramo` (JS), probados en `pruebas/paridad.py`.

### Python = JavaScript

`pruebas/paridad.py` corre en GitHub Actions en cada push: los indicadores, Fibonacci, el termómetro (BTC y alts) y el
modelo de movimiento fuerte tienen que dar lo mismo en las dos versiones.

### Más rápido al abrir

El último análisis de cada activo queda guardado en el teléfono: al abrir la app o elegir otro activo en el
desplegable se ve al instante ("Último análisis guardado · actualizando…") mientras se calcula el nuevo. Si se cambia
de activo mientras se bajan los datos, ese cálculo se descarta. La calibración del rango arma los grupos de casos una
vez por receta (antes, una vez por plazo): la primera vuelta tarda ~20% menos, con el mismo resultado.

**Todos los activos en segundo plano** (`worker.js`): el que estás mirando se analiza primero y se rehace cada 12 s; en
los huecos entre un ciclo y otro se analizan los demás de a uno (uno cada ~8 s, y cada uno a lo sumo cada 10 min), así
que al cambiar de activo ya están su análisis y su gráfico. Si elegís otro mientras se baja uno de fondo, ese se deja y
va primero el elegido. Con 16 activos, la primera vez tarda ~2 minutos en tenerlos todos y baja ~70 MB de velas (una
sola vez: quedan guardadas en el teléfono; después solo lo nuevo, pidiendo justo las velas que faltan). Cada activo
tiene sus propias fuentes de datos (`fuentes(sym)` en `datos.js`): un pedido de fondo no se puede mezclar con el del
activo a la vista. El activo elegido vive en un solo lugar, `window.abActivo` (`app.js`): `get()`, `set()`,
`subscribe()` y `listo()`; las partes de la página se suscriben (como un Context de React, sin React).

**Panel de activos** (es el selector: el desplegable ya no se muestra): se abre tocando el botón del activo de arriba
("Activo BTC · Bitcoin ≡"), la pestaña ‹ del borde derecho o, en el celular, arrastrando desde ese borde hacia la
izquierda. Es un panel con todos los activos, su precio y el cambio de 24 h en vivo (un solo WebSocket de
Binance con todos y el de Bitget para MELI; si no llegan, cada 15 s por pedido común). Tocar uno es como elegirlo en el
desplegable; ✓ marca los que ya tienen su análisis listo. Se cierra deslizando a la derecha, tocando afuera o con ✕, y
los WebSocket se cierran con él. En la compu (ventana de 1100 px o más y mouse) queda fijo a la derecha, siempre
visible, con los precios en vivo (se cortan con la pestaña oculta) y la página le deja lugar; al achicar la ventana
vuelve a ser el panel que se abre y se cierra. Con el panel fijo no se muestra el botón "Activo" de arriba.

**Ritmo de pedidos**: con todos los activos de fondo, Bitget limitaba (corta por segundo). Ahora cada grupo de
pedidos espera su turno (`RITMO` en `datos.js`): Bitget como mucho ~12 por segundo y su flujo de compras y ventas uno
por segundo, en su propio grupo (si lo limita, no frena las velas de MELI ni los libros). Los pares que Bitget no tiene
(el flujo de NVDA, GOOGL, BABA, MELI...) no se le vuelven a pedir en un día: van directo a Binance. Si igual limita,
la pausa es de 30 s (antes 2 min).

**Se actualiza sola**: el iPhone deja la app dormida con el código viejo aunque haya una versión nueva publicada.
`generar_pagina.py` escribe la huella de la página en `version.txt` y en la página; al volver a la app (y cada 5 min)
se comparan y, si cambió, se recarga.

**Optimizaciones de velocidad** (medidas con `pruebas/celular_lento.js`: iPhone 13, CPU 4x más lenta, sin internet,
con exchanges falsos). Segunda apertura en 3G: el gráfico pasó de 5,0 s a 1,3 s y la app baja 0 KB (antes 183 KB);
primera apertura con latencia alta (300 ms): de 10,6 s a 8,3 s; hilo principal ~30% menos trabado por análisis.
- **Caché del navegador** (`JavascriptVersion/vercel.json`): los `.js` de la app y `lib/` son inmutables (llevan la
  huella `?v=`); `termometro.json` y `modelo_fuerte.json` se piden con `no-cache` (si no cambiaron, responde 304; antes
  se bajaban enteros en cada apertura). Vercel ya comprime con brotli; el servidor de Render ahora comprime con gzip.
- **Librerías propias** (`JavascriptVersion/lib/`: d3 7.9.0 y Lightweight Charts 5.1.0, sin tocar): sin dos conexiones
  nuevas a CDN al abrir. Las fuentes ya eran las del sistema (nada que bajar).
- **Pedidos en paralelo**: las páginas de velas del historial van todas juntas (antes una detrás de otra) y los modelos
  se bajan a la vez que las velas. **Sin duplicados**: si dos ciclos piden las mismas velas, esperan el mismo pedido.
- **Más livianos**: el plan de compras pide solo los días desde el plan (con `limit=1500` Binance cobraba 10 de peso
  por pedido, 4 criptos cada 15 s); el panel de activos sin WebSocket pide todos los precios en un pedido (antes 16).
- **Esqueletos de carga**: mientras llega el primer análisis, bloques grises con brillo en la predicción, el sesgo y
  el gráfico. **Dibujo perezoso**: los desplegables cerrados (probabilidades, señales, niveles, ondas, indicadores,
  aciertos) no se dibujan en cada análisis, sino al abrirlos; "Cómo viene aprendiendo" solo si cambió.
  Las filas del análisis se indexan por tabla una vez (antes cada búsqueda recorría ~3.000 filas, ~60 veces).
- **Análisis 2 veces más rápido** (mismo resultado, fila por fila): en regimen pasó de ~450–600 ms a ~250 ms por
  ciclo y el primero de 2,8 s a 1,5 s (Node, mismas velas). `calificar` mira solo las últimas 2.000 velas
  (`calificar_ultimas` en Python; el OBV sigue con toda la historia); el ATR se calcula solo (`atrW`) en vez de armar
  el ADX entero en cada una de las ~8 funciones que lo piden; los cuantiles ordenan `Float64Array` (sort numérico
  nativo); máximos y mínimos móviles en una pasada (`ventanaExtremo`); el redondeo "como Python" va por `toFixed`
  salvo en los casi empates; la app no arma los escenarios del futuro (no se dibujan: `escenarios: false`).
- **Velas en memoria** de los 2 últimos activos analizados (antes se releían ~40.000 de IndexedDB cada 12 s) y se
  guardan en el teléfono cada vez que llega una vela (antes solo si cambiaba la cantidad: con la ventana llena no se
  guardaban y al reabrir había que bajar todo lo que faltaba).
- **Arranque**: los 6 archivos del worker se piden juntos antes de crearlo (el `importScripts` los bajaba de a uno).
  Primera apertura con latencia alta: de 8,3 s a 6,9 s hasta el gráfico. Los análisis de fondo llegan a la pantalla como
  texto y se arman recién al elegir ese activo (elegir uno listo tarda ~60 ms).
- **Más**: la página abre de antemano la conexión con Binance y Bybit (`preconnect`: el primer pedido de velas no espera
  el saludo TLS); Python también calcula el ATR solo (`atr_w`), así el análisis de Render y los avisos gastan menos.
- **Al cambiar de activo**: el gráfico vuelve a la vista por defecto con la escala de precios automática, y la vela en
  vivo del activo anterior ya no se mezcla (de ZEC a BTC la escala quedaba de 1.300 a 100.000). Si el activo elegido
  todavía no tiene análisis, el título ya dice el nuevo, el precio y las cifras del anterior quedan tapadas con
  esqueletos y el resto se ve apagado hasta que llega el suyo.
- No aplican (no hay base de datos ni servidor propio con tráfico): consultas N+1, índices de base, pool de
  conexiones, Redis, colas de trabajo, varias instancias y OpenTelemetry. Sus equivalentes ya estaban: caché de Vercel
  de 10 min para las noticias, cachés en memoria por fuente, velas guardadas en el teléfono y el worker como cola.

### Acciones en la app: AAPL, NVDA, MSFT, GOOGL, AMZN, SPCX, META, TSLA, AMD, BABA, MELI y los índices SPY y QQQ

Los perpetuos de acciones (`BABAUSDT`, `NVDAUSDT`, `GOOGLUSDT`, `AMDUSDT` en Binance; `MELIUSDT` solo en Bitget) se
analizan en la app como una cripto más: mismas velas, indicadores, patrones, predicciones con su propio repaso,
escenarios, libros, open interest, long/short, funding, flujo, mapa de liquidaciones estimado, Fibonacci y la tabla de
"movimiento en la próxima hora" medida con las velas de 5 min de cada una (prob. base 20–28%: se mueven fuerte más
seguido que BTC, por la apertura de Wall Street). Se eligen en el desplegable, bajo "Acciones (perpetuos)".

Las del Nasdaq (AAPL, MSFT, AMZN, SPCX, META, TSLA) y QQQ (el Nasdaq 100) cotizan en futuros de Binance desde enero–mayo
de 2026; tienen todo lo de NVDA y GOOGL. QQQ y SPY (el S&P 500, desde abril de 2026) siguen al índice entero: tienen
menos movimientos fuertes (prob. base 18% y 17%). El Dow Jones no está: su único perpetuo (DIASTOCKUSDT en Bitget) mueve
~15.000 USDT por día, demasiado poco para leerlo (DIAUSDT de Binance es otra cosa, una cripto).

Noticias propias de cada una (nada de cripto; el calendario de EE.UU. sigue aparte):
- **BABA**: Alibaba, China (economía, gobierno, regulación, estímulos, yuan, Hong Kong) y la bolsa (Wall Street, Hang Seng).
- **NVDA y AMD**: la empresa, chips e IA (TSMC, Intel, controles de exportación a China, data centers), economía de EE.UU. y la bolsa.
- **GOOGL**: Alphabet/Google (búsqueda, YouTube, Waymo, Gemini, antimonopolio), IA y tecnología, economía de EE.UU. y la bolsa.
- **MELI**: Mercado Libre (Mercado Pago, Brasil, Argentina, México), Latinoamérica (Selic, Banxico, BCRA, riesgo país, real y peso) y la bolsa.
- **AAPL, MSFT, AMZN y META**: la empresa (iPhone, Azure, AWS, Instagram...), IA y tecnología, economía de EE.UU. y la bolsa.
  En META, "meta" sola no cuenta (en castellano es "objetivo": "la meta de inflación").
- **SPCX**: SpaceX, Starlink y Starship (y Elon Musk), espacio y defensa (contratos del Pentágono, NASA), EE.UU. y la bolsa.
- **TSLA**: Tesla y Elon Musk, autos eléctricos y robotaxis (BYD, Rivian, Waymo como rivales), EE.UU. y la bolsa.
- **QQQ** y **SPY**: el Nasdaq o el S&P 500, las grandes tecnológicas (las 7 magníficas), economía de EE.UU. y la bolsa.

Cada titular se marca bueno o malo **para esa acción**: se corta lo que viene después de "pese a"/"despite", manda lo que
le pasa a la empresa (gana un juicio, supera estimaciones, sube la guía, recompra, contrato = bueno; multa, demanda,
investigación, controles de exportación, baja de recomendación, renuncia del CEO = malo), y en lo macro se invierte el
sentido cuando subir es malo (inflación, tasas, rendimientos, dólar, desempleo, riesgo país, aranceles, petróleo). Si el
titular habla primero de un rival, cuenta como neutro. Las mismas reglas valen para BTC (aprobaciones, recortes de
impuestos, compras, reservas, entradas a ETF = bueno). Python y la app comparten las reglas (`generar_reglas.py` las copia
a `api/contexto.js`) y `pruebas/sesgo.py` las prueba con 142 titulares reales en ambos lenguajes.

No aplica: termómetro (el ciclo de 4 años y el MVRV/Puell son de BTC), Fear & Greed, ETF de BTC, prima de Coinbase,
opciones de Deribit, liquidaciones reales de OKX y el modelo de movimiento fuerte (entrenado con BTC: usan su tabla
propia). Tampoco entradas del bot ni avisos por Telegram (solo análisis, como SOL y XRP). Con pocos meses de historia,
el plazo de 1 día todavía no tiene repaso y usa el método original. Si Bybit no tiene el par, open interest, long/short
y flujo salen de Binance, y funding y precio de marca de Bitget. **MELI**: velas, libro, funding y precio de marca de
Bitget (en vivo por su WebSocket); no hay historia gratis de open interest, long/short ni flujo, así que le faltan esas
señales y el mapa de liquidaciones. Existe desde agosto de 2026 y tiene poco volumen: su tabla de movimiento es la más
débil (el último grupo, con un solo caso, no se usa en la práctica).

### Criptos en la app: BTC, ZEC, SOL y XRP

La app (versión JavaScript) analiza BTC, ZEC, SOL y XRP con las mismas cuentas: gráfico, predicciones, niveles,
patrones y movimiento fuerte (tabla propia de cada cripto, medida con velas de 5 min de Binance 2021–2026). Los
precios se guardan y muestran con los decimales que pide su tamaño (XRP con 4). El modelo de movimiento fuerte, el
termómetro y la prima de Coinbase son de BTC. Las entradas del bot siguen siendo solo BTC y ZEC: en SOL y XRP la
regla del setup no ganó en 2020–2026.

### Avisos al celular (WhatsApp y notificación)

El servidor de Render mira el mercado las 24 horas (se mantiene despierto solo). **Por defecto solo manda las entradas
de futuros de BTC y ZEC** (ETH apagado; `MONEDAS=BTC,ETH,ZEC` lo vuelve a prender) (y su cierre: TP, SL o 72 h); con `AVISOS=todos` en Render vuelve a mandar también:
- **Se viene movimiento fuerte**: cuando el modelo de movimiento fuerte (abajo) da 40% o más para la próxima hora.
  Probado sin mirar el futuro (2023–2026): unos 2 avisos por semana y en 40–49% de los casos la hora se movió más del
  doble de lo habitual (una hora cualquiera: 12%; el aviso anterior, por volatilidad, acertaba 31–32% con la misma
  vara). No dice para dónde.
- **Zona grande de liquidaciones cerca**: el precio a menos de 0,4% de la zona más grande de cada lado.
- **Setups de entrada (largo o corto) en BTC, ETH y ZEC**, con entrada, stop, objetivo e historial: ruptura de 55
  velas de 1 hora a favor de la tendencia de 4 horas, con el mercado despierto; cierre a las 72 h. Elegidos con
  2021–24 y verificados con 2025–26 (con comisiones). Arriesgando 1% por operación, 2021–2026:
  | | Stop / objetivo | Aciertos | R por operación | Cuenta | Peor caída | Años positivos |
  |---|---|---|---|---|---|---|
  | BTC | 2,5 ATR / 1R | 64–69% | +0,22 a +0,35 | +22% a +36% | −3% | 5–6 de 6 |
  | ETH | 2,5 ATR / 1R | 61% | +0,22 | +22% | −3% | 6 de 6 |
  | ZEC | 2,5 ATR / 1,5R | 49% | +0,19 | +44% | −7% | 6 de 6 |
  SOL y XRP no dieron ventaja con esta regla. Después avisa si tocó el objetivo o el stop. Es estadística del
  pasado, no una garantía.

  **Cada entrada viene como la armaría un trader profesional**: plan (entrada, precio máximo para entrar —0,3 R—,
  stop, take profit, cierre por tiempo con fecha y hora, riesgo, ganancia y comisiones), configuración paso a paso
  (perpetuo, margen aislado, apalancamiento, cantidad exacta, TP/SL en la misma orden, precio de liquidación
  aproximado, alarma de 72 h), reglas mientras está abierta y un chequeo de contexto (modelo de movimiento fuerte,
  próximo dato de EE.UU., clima de noticias, funding) que es informativo: filtrar el setup con eso no mejoró el
  resultado en las pruebas. Gestión de riesgo (protege la cuenta, no cambia las señales):
  - 1% del capital por operación; mitad si ya hay otra abierta en la misma dirección (BTC, ETH y ZEC se mueven
    juntos) y mitad si en menos de 1 h sale un dato fuerte de EE.UU.
  - Tope de 2,5% del capital en riesgo abierto entre todas.
  - 3 pérdidas seguidas → 24 h sin entradas nuevas; 2% de pérdida en el día → nada nuevo hasta mañana.
  - Al cerrar cada operación avisa el resultado en R y USDT (con comisiones) y el registro acumulado.

**Operar solo en la demo de BingX** (`operador.py`): con `OPERAR=demo`, `BINGX_API_KEY` y `BINGX_API_SECRET` en Render,
cada entrada se abre sola en la cuenta demo (VST): margen aislado, el apalancamiento del aviso, orden a mercado con TP y
SL puestos en BingX; a las 72 h el vigía la cierra. El aviso de Telegram dice si la abrió o por qué no (por ejemplo, si
el precio ya pasó la entrada + 0,3 R). El módulo fuerza siempre el modo demo y no tiene modo real. `OPERAR_PRUEBA=1`
hace, al arrancar, una operación mínima de prueba en BTC y ZEC (abre, revisa TP/SL y cierra) y avisa el resultado.
Si el servidor se reinicia, retoma sola las operaciones que abrió (las reconoce por el id de sus órdenes de TP/SL)
y sigue con el cierre de 72 h; las posiciones abiertas a mano no las toca.

Configuración en Render (Environment), nunca en el código: `TELEGRAM_TOKEN` y `TELEGRAM_CHAT` (bot de Telegram),
o `WHATSAPP_TEL` y `WHATSAPP_CLAVE` (CallMeBot), o `NTFY_TEMA` (app ntfy).

### Termómetro de compra y venta (ciclo de BTC)

Pestaña fija al costado de la app (abajo en el celular): de 0 (compra fuerte) a 100 (zona de venta), para decidir de
a poco en semanas o meses, no para el próximo trade. Sigue la lógica inversa del mercado cripto: comprar cuando está
barato y el ciclo está en su piso (miedo), vender cuando está caro y en el techo del ciclo (euforia). Es mitad y mitad:

- **Barato o caro** (temperatura): cuánto está el precio sobre su media de 200 semanas, cuánto cayó desde el máximo
  histórico y cuánto subió o bajó en el último año, comparado con toda la historia de BTC desde 2011 (Bitstamp).
- **Momento del ciclo de 4 años** (3 alcistas y 1 bajista: 2014, 2018, 2022, 2026...): un modelo con el año del
  ciclo y qué tan avanzado va el año bajista (al final suele estar el piso) y el 3er alcista (al final, el techo).
- **Ajuste por funding** (promedio de 7 días de BingX): si es negativo (miedo, los shorts pagan) el medidor baja 3
  puntos hacia compra; si es 0,03% o más cada 8 h (euforia) sube 3 hacia venta. Medido 2020–2026: dentro de cada zona,
  con funding negativo BTC subió más a 1–3 meses (Compra fuerte: 95% contra 63% a 30 días); con funding alto, menos.
  Mejora un poco el medidor a 1–6 meses (AUC +0,005) y lo empeora apenas a 12 meses (−0,007): por eso pesa poco.

Probado año por año 2019–2026, entrenando el ciclo solo con lo anterior (sin mirar el futuro):

| Zona | 12 meses después, BTC más arriba | Mediana | 6 meses después |
|---|---|---|---|
| Compra fuerte | 99% | +136% | 86% |
| Buen momento de compra | 72% | +40% | 78% |
| Cuidado: caro | 10% | −27% | 34% |
| Zona de venta | 0% | −43% | 15% |

La mezcla separa mucho mejor que cada parte sola (AUC 0,96 contra 0,74 solo barato/caro y 0,80 solo el ciclo).
Son tres ciclos: es una guía, no una garantía. El Fear & Greed Index se muestra con su arco; sumarlo al puntaje no lo
mejoró, pero el panel avisa cuando hay Extreme Fear en año bajista (12 meses después: 64% más arriba, mediana +37%;
antes llegó a caer −48%) o Extreme Greed en el 3er año alcista (32% más arriba, mediana −15%). Para plazos de días
o semanas el ciclo y el Fear & Greed Index casi no sumaron (7 días: AUC 0,53 → 0,57; 30 días: igual), así que no
cambian las predicciones de corto plazo ni los setups. Se actualiza solo cada mes junto con el reentrenamiento
(`termometro.py`, `armar_termometro.py`, `JavascriptVersion/termometro.json`).

**XRP y SOL** tienen su propio medidor en la app: su barato o caro comparado con su propia historia (XRP desde 2017
con las tres medidas; SOL desde 2020 sin la media de 200 semanas, que todavía no tiene historia para comparar) y el
mismo momento del ciclo de BTC. Medido 2019–2026 sin mirar el futuro: AUC a 12 meses 0,95 en XRP y 0,88 en SOL.
En "Compra fuerte", 12 meses después XRP estaba más arriba el 100% de las veces y SOL el 89%; en "Zona de venta",
ninguna de las dos. **ZEC no tiene medidor**: su "barato" siguió abaratándose durante años (2018–2024) y después
explotó; con esta lógica no se puede anticipar (AUC 0,6).

### Mínimo probable en 6 meses (para elegir el apalancamiento)

En el termómetro y en "Mis posiciones" (BTC, SOL, XRP y ZEC): el precio del que cada cripto no baja en los próximos 180
días con 50, 80, 90 y 95% de confianza, y la **chance de que toque tu liquidación** en ese plazo (verde hasta 5%,
amarillo hasta 20%, rojo arriba). Es mitad lo que cayó cada moneda en su historia (el mínimo de las 180 velas diarias
siguientes contra el cierre) y mitad lo mismo en unidades de su volatilidad de un año (juntando las cuatro).

Medido año por año 2019–2026 sin mirar el futuro: el piso del 90% se rompió el 9,8% de las veces en 2019–22 y el 6,6%
en 2023–26; el del 95%, 5,0% y 0,8%; el del 80%, 22% y 19%. Con BTC solo: 8% (90%) y 4% (95%). Se probó contra la
historia sola, la volatilidad de 90 o 180 días, el estado del termómetro y una regresión por cuantiles (se sobreajusta):
esta mezcla fue la más pareja en los dos tramos. No sabe si "los mínimos ya pasaron": mide cuánto suele caer cada una
en 6 meses. `armar_termometro.py` lo rehace cada semana (`piso` en `termometro.json`).

**Comparado con años anteriores** (desde la misma fecha, el mínimo de los 6 meses siguientes, cada año y su fase del
ciclo): en los años bajistas anteriores BTC cayó 55% (2014), 51% (2018) y 27% (2022) desde principios de noviembre, y en
los tres el piso del ciclo llegó entre 12 y 13 meses después del máximo. Se muestra al lado (y en "Mis posiciones" dice si
tu liquidación aguantaría la peor), pero no entra en las probabilidades: separar por año bajista mejoró 2019–22 y empeoró
2023–26; por semestre, por las 4 fases o por mes del año, peor. Por mes de inicio no hay estacionalidad clara (mediana del
mínimo de 6 meses entre −17% y −27%, salvo octubre −9%).

### Reentrenamiento semanal

El día 2 de cada mes una tarea de GitHub (`.github/workflows/reentrenar.yml`) baja las velas de 1 hora de BTC
(data.binance.vision) y el calendario de EE.UU. (`datos_entrenamiento.py`), reentrena el modelo de movimiento fuerte
(`entrenar_fuerte.py`, con sus controles de que Python y JavaScript den lo mismo) y sube `modelo_fuerte.json`; Render y
Vercel lo toman solos. La prueba honesta del modelo reentrenaba cada trimestre, así que en vivo se mantiene igual.

### Qué está pasando (por qué se mueve fuerte)

Arriba de todo. Cuando BTC sube o baja fuerte (más del doble de lo normal en 1 hora, 4 veces en 4 horas o 5% en el día)
junta lo que coincide en el tiempo y lo explica en criollo:
- **Futuros**: si el interés abierto cayó (liquidaciones de longs o short squeeze) o subió (dinero nuevo apalancado).
- **Compras o ventas a mercado** dominantes.
- **Prima de Coinbase**: si en EE.UU. pagan más o menos que afuera (compras o ventas de fondos y empresas de EE.UU.).
- **ETF de BTC de EE.UU.**: entradas o salidas del último día y de 5 días (Farside Investors).
- **Noticias de esas horas** (Google Noticias en español e inglés, y CoinDesk), filtradas a lo que más mueve a BTC:
  **guerras grandes** (con una potencia o una zona caliente de por medio: EE.UU., Rusia, Ucrania, Israel, Irán, China,
  Taiwán, Corea del Norte, OTAN), **gobierno de EE.UU.** (Casa Blanca, Congreso, Fed, Tesoro, SEC, aranceles) y
  **gobiernos grandes** (China, Unión Europea y BCE, Japón, Reino Unido, Rusia, India, G7, OPEP), más las de **ETF**,
  **hackeos o quiebras** y las **noticias cripto**. El resto (deportes, policiales, empresas comunes) se descarta.
  **Hackeo a un exchange grande** (Binance, Coinbase, Kraken, OKX, Bybit, Bitget, BingX, KuCoin, Tether y otros) es un
  tema aparte, con búsqueda propia en Google Noticias, impacto máximo (3) y siempre bajista aunque el titular diga que
  los fondos están a salvo. Se avisa por Telegram al instante aunque esté en "solo entradas" (`AVISOS_CRITICOS=0` lo apaga).
- **Sin repetidos y en español**: los titulares en inglés se traducen (Google, cliente "dict-chrome-ex", con respaldo en otro
  servidor de Google y en MyMemory: el traductor gratis de antes lo bloqueaba Google desde Vercel y quedaban en inglés). De los
  feeds en inglés se traduce todo lo que no esté claramente en español; lo que no se pudo traducir no se muestra, salvo el
  hackeo de un exchange (se avisa igual, en español). La misma noticia
  contada por varios medios aparece una sola vez (la primera que salió, con "y N medios más"). Se considera la misma
  si comparten la mayoría de sus palabras clave en 12 horas, o si es el mismo exchange hackeado.
- **Fear & Greed Index** (alternative.me): arco clásico con aguja en el panel del termómetro (y el número en "Qué está pasando"). Medido
  2018–2026 no anticipa la dirección de forma confiable (la codicia extrema fue alcista en 2018–21 y bajista en
  2024–26), así que es contexto, no señal.

Son coincidencias, no pruebas de la causa. Sin movimiento fuerte muestra las noticias del día y los ETF.

Cada titular se lee como **bueno o malo para BTC** con reglas de palabras (en español e inglés: "recorte de tasas",
"alto el fuego", "entradas" suman; "misiles", "aranceles", "hackeo", "salidas" restan; las frases van antes que las
palabras sueltas) y con un peso por tema (guerras grandes y gobierno de EE.UU. 3; gobiernos grandes, ETF y hackeos 2;
cripto 1). Con
eso se arma el **clima de las noticias** de las últimas 6 horas (cada titular pierde la mitad del peso cada 3 horas),
que se muestra junto a la predicción. Todavía no entra en la probabilidad: primero hay que medir si predice.
El servidor de Render las lee cada 10 minutos, las 24 horas, y avisa por Telegram los titulares nuevos de peso.
Python las lee en `noticias.py`; la versión de Vercel, en la función `JavascriptVersion/api/contexto.js` (el navegador
no puede leer esas fuentes directo). Mismas fuentes y mismas filas.

### La Fed, primero

Las noticias de la Fed (Reserva Federal, Powell, FOMC) van siempre primero y pesan 3. Cuando sale la decisión de
tasas, se compara con lo que se esperaba (calendario económico): **más baja de lo previsto es positivo para BTC,
más alta es negativo** y, si es lo que se esperaba, ya estaba descontado. Se muestra arriba en "Qué está pasando" y
en la predicción, y llega por Telegram apenas sale. En los titulares, "recorte mayor al esperado" o "dovish" suman;
"menos recortes", "pausa" o "hawkish" restan; "como se esperaba" es neutral.

### Datos económicos fuertes de EE.UU.

Calendario de importancia alta (IPC, empleo, decisiones y discursos de la Fed, PCE, ventas minoristas, PIB...), de
TradingView. Investing.com solo respondió algunos meses a la lectura automática, por eso no es la fuente. Medido con BTC
2021–2026: en la hora en que sale uno de estos datos, BTC se movió 1,6 a 1,8 veces lo normal y fue un movimiento fuerte
23–29% de las veces (10–12% en las demás horas), parejo todos los años. Para predecir la dirección no sirvió, así que
no entra en la probabilidad de subir o bajar. Se muestra en "Movimiento en la próxima hora" (próximo dato y cuánto
falta), en "Qué está pasando" si un movimiento fuerte coincide con un dato, y por Telegram 30 minutos antes.

### Modelo de movimiento fuerte

¿La próxima hora (o las próximas 4) BTC se va a mover más del doble de lo habitual, para cualquier lado? Lo calcula un
modelo de árboles (LightGBM) con 39 señales de las velas de 1 hora cerradas (retornos, volatilidad corta y larga,
volumen, medias, RSI, MACD, posición en el rango, hora del día, fin de semana) y del calendario de datos fuertes de
EE.UU. Entrenado con BTC 2021–2026 y probado sin mirar el futuro (cada trimestre se predice con un modelo entrenado
solo con lo anterior):

| | 2023–24 | 2025 | 2026 |
|---|---|---|---|
| Ventaja sobre la tasa base, próxima hora — tabla anterior (solo volatilidad) | 3,7% | 4,3% | 4,2% |
| Ventaja sobre la tasa base, próxima hora — modelo | **9,2%** | **11,0%** | **11,8%** |
| El 10% de horas que más marca: fue fuerte… (tabla / modelo) | 27% / 36% | 27% / 35% | 26% / 37% |
| Próximas 4 horas — modelo | 7,2% | 7,3% | 8,6% |

En una hora cualquiera es fuerte el 12%. Para predecir si sube o baja, el mismo modelo no sirvió (igual que todo lo
demás que se probó). Las cuentas están en `fuerte.py` y `JavascriptVersion/fuerte.js` (mismos números, probado en 300
momentos), y los árboles en `JavascriptVersion/modelo_fuerte.json`, que arma `entrenar_fuerte.py` (necesita numpy y
lightgbm; conviene reentrenarlo cada algunos meses). Se usa solo para BTC; ZEC sigue con la tabla.

### Predicciones honestas

- **Sin ventaja medida, sin sesgo**: si en su repaso honesto el equipo no le ganó a la tasa base para ese plazo
  (`habilidad` ≤ 0), el plazo queda en "Casi moneda" y el titular no dice qué toca primero, aunque los casos parecidos
  marquen una diferencia: esa diferencia no se tradujo en menos error.
- **Rango real en el titular**: sin dirección, muestra dónde terminó el 80% de los casos parecidos (antes mostraba los
  niveles a un escalón, que el precio pasa seguido en ese plazo).
- **¿El rango es honesto?**: cada predicción guarda también su rango del 80% (`predicciones_btc.csv` pasa a 7 columnas; las
  filas viejas de 5 se siguen leyendo) y "Aciertos" muestra cuántas veces el precio terminó adentro: lo honesto es ~80%.
- **Rango ajustado con su propio pasado** (calibración "conformal", `rango_puntajes` / `rango_factor`): repasa sus últimas 200
  predicciones de cada plazo (sin pisarse), arma el rango que habría dado en cada una con lo que sabía ahí y mide dónde terminó
  el precio; el factor que deja adentro al 80% ensancha o angosta el rango y el cono de ahora. Medido 2023–2026 sin mirar el
  futuro: sin ajustar terminaba adentro 78–79,5%; ajustado, 80% en 15 min, 1 hora y 4 horas, en los dos tramos. Con velas de
  4 h o diarias no mejoró: ahí solo se mide.

### Medir antes de sumar (`medir_contexto.py`)

Simula la app como corre en vivo (ventanas de 30 días de 5 min, 180 de 30 min y 730 de 4 h; aprendizaje desde cero y repaso
de 1.000 predicciones en cada ventana), encadenada sobre 2023–2026 con datos públicos (data.binance.vision y Deribit). Entra
solo lo que gana en 2023–24 y también en 2025–26 (diferencia por día con |z| > 2):

| Idea | Resultado | Qué se hizo |
|---|---|---|
| Open interest, flujo de compras/ventas, long/short, funding, prima perpetuo-spot y DVOL como señales del modelo | Ninguna ganó en ningún plazo en los dos tramos (15 min, flujo + open interest: z +1,7 y +1,8) | Quedan como contexto, sin peso |
| Pesos del equipo distintos por régimen (tendencia, rango, pánico) | No mejoró (z entre −1 y +0,4 en 15 min, 1 h y 4 h) | El régimen se muestra en "Por qué"; el modelo no cambia |
| 15 min, 1 h y 4 h van para el mismo lado | El de 1 hora acertó 54,0% (52,6–55,4) contra 51,5% (50,5–52,4); mejor en los dos tramos. En 15 min y 4 h, igual | Señal en la explicación de 1 hora (no cambia la probabilidad) |
| Rango del 80% ajustado | 78–79,5% → 80% (hasta velas de 1 h) | Se aplica |

Ojo con los archivos de metrics de Binance: la hora es la del inicio de los 5 minutos y el dato se conoce al final (la API lo
confirma). Medido sin ese corrimiento, el flujo y el open interest "ganaban" en 15 min (z +10): era ver el dato 5 minutos antes.

### Contexto nuevo: perpetuo contra spot y opciones

- **Perpetuo vs spot** (precio de marca contra el índice, Bybit): caro desde +0,05% (calentamiento), con descuento desde −0,07%
  (miedo); cortes en los percentiles 90 y 5 de la prima de Binance 2022–24. La prima de Coinbase (EE.UU. contra afuera) sigue
  en "Qué está pasando".
- **Opciones de BTC (Deribit)**: volatilidad implícita DVOL (y cuánto espera que se mueva por día), puts contra calls, el "dolor
  máximo" del vencimiento del viernes (línea violeta en el gráfico, capa "Opciones") y cuánto más caros están los puts que los
  calls. Contexto: el DVOL no anticipó la dirección en la medición.

### Volatilidad prevista

El rango esperado, la probabilidad de tocar cada precio y los caminos posibles usan casos del pasado llevados a la
volatilidad de ahora: lo que se mueve el precio tiene memoria (promedios móviles corto y largo del rango de las
velas) y depende de la hora del día. Se aplica con velas de hasta 1 hora. Verificado con el código real sobre
velas de BTC de 2025–2026: 1,7% a 3,3% menos error en la escalera de niveles (15 min, 1 hora y 4 horas). Con
velas de 4 horas o diarias no mejoraba, así que ahí no se usa.

## En tu PC

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python analisis_btc.py --vivo
```

Se abre en http://127.0.0.1:8765. El análisis se recalcula cada ~5 segundos, el precio llega por
WebSocket y la página se actualiza sola cuando cambia el código o el diseño.

## En internet, gratis, con Render

1. En [render.com](https://render.com) entrá con tu cuenta de GitHub y dale acceso a este repositorio.
2. **New → Blueprint**, elegí este repositorio. Render lee `render.yaml` (plan gratis, región Frankfurt).
3. Cuando pida **VIVO_CLAVE**, poné la contraseña para entrar al dashboard (mínimo 8 caracteres).
4. Al terminar el deploy, abrí la dirección `https://….onrender.com` desde cualquier lado.
   El navegador pide usuario y contraseña: el usuario puede ser cualquiera; la contraseña es `VIVO_CLAVE`.

Con el plan gratis el servicio se duerme a los 15 minutos sin visitas: al abrirlo tarda cerca de un
minuto en despertar. En Render el análisis completo se recalcula cada 20 segundos (el precio llega al
instante por WebSocket). Cada push a `main` se publica solo.

La IP de salida de Render es compartida y Binance la limita seguido: por eso el servidor ya no le pide
velas, libro ni posicionamiento. Velas, open interest, long/short y liquidaciones salen de Bybit; flujo de
compras/ventas y top traders, de OKX. El funding sale de BingX (cada 3 h): a Binance no se le pide nada.

## En el iPhone, sin servidor: versión JavaScript (Vercel)

La carpeta `JavascriptVersion/` es el mismo analista traducido a JavaScript: el teléfono baja los
datos directo de los exchanges (APIs públicas) y hace todo el cálculo. Así cada teléfono usa su propia
conexión, no se duerme como Render y no hay límites de pedidos compartidos. Es una página estática, sin build.

1. En [vercel.com](https://vercel.com), **Add New → Project** e importá este repositorio.
2. En **Root Directory** elegí `JavascriptVersion`. Framework Preset: **Other**. Sin Build Command ni Output Directory.
3. **Deploy**. Cada push a `main` se publica solo.
4. En el iPhone abrí la dirección en Safari → **Compartir → Agregar a inicio**: queda como una app a pantalla completa.

La primera vez baja el historial de velas (unos segundos) y lo guarda en el teléfono; después solo
pide lo nuevo. Reanaliza el activo a la vista cada ~12 segundos y los demás en segundo plano (ver "Más rápido al
abrir"), y se pausa con la app en segundo plano.
BingX no se usa en esta versión: su API no acepta pedidos desde páginas web. Por lo mismo (OKX no manda el permiso CORS),
en el teléfono el flujo de compras y ventas a mercado sale de Bitget y los top traders de Binance; antes esos pedidos a OKX
fallaban siempre y esas señales no entraban en la explicación. El funding, de Bybit.

Si cambiás `dashboard/index.html`, regenerá la página de esta versión antes del push:

```
python JavascriptVersion/generar_pagina.py
```

## Archivos

| Archivo | Qué hace |
|---|---|
| `analisis_btc.py` | Baja los datos, calcula todo y sirve el dashboard (`--vivo`, `--vivo --servidor`) |
| `indicadores.py` | Indicadores, patrones de velas, figuras (triángulos, cuñas, canales, rangos, dobles, HCH), Wyckoff, divergencias, ondas de Elliott, FVG y liquidaciones |
| `fuerte.py`, `entrenar_fuerte.py` | Modelo de movimiento fuerte (próxima hora y próximas 4): señales, árboles y entrenamiento |
| `noticias.py` | Noticias, ETF, prima de Coinbase y calendario económico de EE.UU. |
| `aprendizaje.py` | Aprendizaje automático: equipo de expertos (recetas, modelo en línea, tasa base), pesos y confianza aprendidos, medición contra la tasa base |
| `dashboard/index.html` | La página del dashboard |
| `render.yaml` | Configuración para Render |
| `JavascriptVersion/` | La versión que corre entera en el teléfono (Vercel): `analisis.js`, `indicadores.js`, `aprendizaje.js`, `datos.js`, `worker.js` |
| `medir_contexto.py` | Mide con años de historia si una señal o idea nueva le gana a la tasa base antes de sumarla |
| `JavascriptVersion/api/posiciones.js` | Tus posiciones y órdenes de BingX, solo lectura (Vercel) |
| `JavascriptVersion/vercel.json`, `JavascriptVersion/lib/` | Caché del navegador en Vercel y las librerías del gráfico (d3, Lightweight Charts) alojadas en la app |
| `pruebas/celular_lento.js` | Prueba la app como un iPhone con red lenta (sin internet, exchanges falsos) |
| `backtest_*.py`, `grid_bot_zec.py` | Backtests y bot de grilla (BingX demo) |
