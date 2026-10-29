# BTCAnalyzer

Analista de BTC/USDT perpetuo con un dashboard en vivo: predicción por plazo (5 min a 1 día),
gráfico con escenarios, figuras, divergencias, liquidaciones estimadas, libros de órdenes y más de
30 indicadores. Datos públicos de Binance Futures, Bybit, OKX, Bitget y BingX (no usa claves).

El gráfico usa el motor de TradingView ([Lightweight Charts](https://www.tradingview.com/lightweight-charts/)): mismas velas, ejes, mira y
gestos, con las marcas del analista encima (escenarios, cono, patrones, divergencias, ondas, FVG, liquidaciones y niveles).

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
o `WHATSAPP_TEL` y `WHATSAPP_CLAVE` (CallMeBot), o `NTFY_TEMA` (app ntfy). Si Binance bloquea la IP, el mapa de liquidaciones sale de Bybit.

### Reentrenamiento mensual

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
- **Sin repetidos y en español**: los titulares en inglés se traducen (Google Translate, gratis) y la misma noticia
  contada por varios medios aparece una sola vez (la primera que salió, con "y N medios más"). Se considera la misma
  si comparten la mayoría de sus palabras clave en 12 horas, o si es el mismo exchange hackeado.
- **Índice de miedo y codicia** (Crypto Fear & Greed, alternative.me): se muestra como termómetro del ánimo. Medido
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
| `fuerte.py`, `entrenar_fuerte.py` | Modelo de movimiento fuerte (próxima hora y próximas 4): señales, árboles y entrenamiento |
| `noticias.py` | Noticias, ETF, prima de Coinbase y calendario económico de EE.UU. |
| `aprendizaje.py` | Aprendizaje automático: equipo de expertos (recetas, modelo en línea, tasa base), pesos y confianza aprendidos, medición contra la tasa base |
| `dashboard/index.html` | La página del dashboard |
| `render.yaml` | Configuración para Render |
| `JavascriptVersion/` | La versión que corre entera en el teléfono (Vercel): `analisis.js`, `indicadores.js`, `aprendizaje.js`, `datos.js`, `worker.js`; holograma: `holograma.html`, `holograma.js`, `manos.js` |
| `backtest_*.py`, `grid_bot_zec.py` | Backtests y bot de grilla (BingX demo) |
