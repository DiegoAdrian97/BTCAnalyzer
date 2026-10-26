# BTCAnalyzer

Analista de BTC/USDT perpetuo con un dashboard en vivo: predicción por plazo (5 min a 1 día),
gráfico con escenarios, figuras, divergencias, liquidaciones estimadas, libros de órdenes y más de
30 indicadores. Datos públicos de Binance Futures, Bybit, OKX, Bitget y BingX (no usa claves).

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

La IP de salida de Render es compartida: si Binance la limita por exceso de pedidos, el análisis
respeta la pausa y mientras tanto toma las velas de Bybit, sin cortarse.

## En el iPhone, sin servidor: versión JavaScript (Vercel)

La carpeta `JavascriptVersion/` es el mismo analista traducido a JavaScript: el teléfono baja los
datos directo de los exchanges (APIs públicas) y hace todo el cálculo. Así cada teléfono usa su propia
conexión, no se duerme como Render y no hay límites de pedidos compartidos. Es una página estática, sin build.

1. En [vercel.com](https://vercel.com), **Add New → Project** e importá este repositorio.
2. En **Root Directory** elegí `JavascriptVersion`. Framework Preset: **Other**. Sin Build Command ni Output Directory.
3. **Deploy**. Cada push a `main` se publica solo.
4. En el iPhone abrí la dirección en Safari → **Compartir → Agregar a inicio**: queda como una app a pantalla completa.

La primera vez baja el historial de velas (unos segundos) y lo guarda en el teléfono; después solo
pide lo nuevo. Reanaliza todo cada ~12 segundos mientras está abierta y se pausa en segundo plano.
BingX no se usa en esta versión: su API no acepta pedidos desde páginas web.

### Modo holograma

En esta versión, el interruptor **Web | Holograma** de arriba abre el gráfico de BTC, SOL o XRP en 3D, con brillo
de neón, encima del análisis (`holograma.html`, `holograma.js` y `manos.js`). Recuerda el último modo elegido.

- **Ventana 3D**: con "Seguir mi cabeza" (⚙), la cámara ve dónde estás y el gráfico se dibuja con la perspectiva
  de una ventana real: parece salir de la pantalla. Elegí en ⚙ el tamaño de la pantalla (MacBook, monitor 27",
  TV 43") y dónde está la cámara respecto de ella.
- **Reflejo**: pantalla acostada mirando hacia arriba y una lámina transparente a 45° encima (Pepper's ghost).
  Fondo negro puro; la imagen se puede espejar, dar vuelta y rotar hasta que se lea bien en la lámina.
- **Manos** (✋): pellizcar y mover arrastra, pellizcar con las dos manos hace zoom, puño gira, palma abierta
  deslizando cambia de cripto (de costado) o de temporalidad (arriba/abajo), palma quieta reinicia la vista.
  Todo se procesa en el navegador con MediaPipe; la imagen de la cámara no sale del equipo.
- **iPhone como proyector**: ⚙ → "Enlazar el iPhone" muestra un QR; con el iPhone acostado bajo la lámina, las
  manos frente a la cámara de la Mac mueven el gráfico del iPhone (conexión directa entre los dos navegadores).

Si cambiás `dashboard/index.html`, regenerá la página de esta versión antes del push:

```
python JavascriptVersion/generar_pagina.py
```

## Archivos

| Archivo | Qué hace |
|---|---|
| `analisis_btc.py` | Baja los datos, calcula todo y sirve el dashboard (`--vivo`, `--vivo --servidor`) |
| `indicadores.py` | Indicadores, patrones de velas, figuras (triángulos, cuñas, canales, rangos, dobles, HCH), Wyckoff, divergencias, ondas de Elliott, FVG y liquidaciones |
| `aprendizaje.py` | Aprendizaje automático: equipo de expertos (recetas, modelo en línea, tasa base), pesos y confianza aprendidos, medición contra la tasa base |
| `dashboard/index.html` | La página del dashboard |
| `render.yaml` | Configuración para Render |
| `JavascriptVersion/` | La versión que corre entera en el teléfono (Vercel): `analisis.js`, `indicadores.js`, `aprendizaje.js`, `datos.js`, `worker.js`; holograma: `holograma.html`, `holograma.js`, `manos.js` |
| `backtest_*.py`, `grid_bot_zec.py` | Backtests y bot de grilla (BingX demo) |
