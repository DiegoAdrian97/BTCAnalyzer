# BTCAnalyzer

Analista de BTC/USDT perpetuo con un dashboard en vivo: predicción por plazo (5 min a 1 día),
gráfico con escenarios, figuras, divergencias, liquidaciones estimadas, libros de órdenes y más de
30 indicadores. Datos públicos de Binance Futures, Bybit, OKX, Bitget y BingX (no usa claves).

No es una recomendación de inversión.

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
minuto en despertar. Cada push a `main` se publica solo.

## Archivos

| Archivo | Qué hace |
|---|---|
| `analisis_btc.py` | Baja los datos, calcula todo y sirve el dashboard (`--vivo`, `--vivo --servidor`) |
| `indicadores.py` | Indicadores, patrones de velas, figuras, divergencias, ondas, FVG y liquidaciones |
| `dashboard/index.html` | La página del dashboard |
| `render.yaml` | Configuración para Render |
| `backtest_*.py`, `grid_bot_zec.py` | Backtests y bot de grilla (BingX demo) |
