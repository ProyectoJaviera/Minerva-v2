# Sección «Indicadores» (v2): pruebas manuales y exploratorias

Pestaña **Indicadores** del dashboard de la v2 (<http://127.0.0.1:8001/>). Eliges monedas, marco, un gatillo y
hasta dos filtros, y en segundos ves cómo le habría ido a esa combinación sobre el historial de Bitunix.

## Qué es y qué no es

- **Es exploratoria.** Sirve para mirar ideas. No es una ronda preregistrada, no se guarda en la base y no
  pasa por los criterios de la Fase 2. Probar muchas combinaciones y quedarse con la mejor sobreestima el
  resultado (sesgo de selección): una idea que se vea bien aquí hay que llevarla a un preregistro nuevo.
- **Nunca usa velas desde el 2026-10-01.** Están reservadas para las rondas preregistradas. El límite está
  fijo en el código (`app/explorer/service.py::RESERVED_FROM`) y no se puede cambiar por configuración.
- **No toca la base del bot.** Lee un archivo de historial aparte, en modo de solo lectura.

## Qué muestra

- **% de operaciones ganadoras**, profit factor, número de operaciones (largos y cortos), PnL neto, resultado
  medio por operación, ganancia y pérdida medias y drawdown máximo. Los montos son del motor de la Fase 2:
  margen de 5 USDT a 10x, comisión taker por lado, slippage, funding y liquidación, entrada en el open de la
  vela siguiente a la señal.
- **Control con dirección al azar:** las mismas velas y los mismos filtros, pero la dirección se sortea
  (como el control del preregistro). Si la combinación no supera claramente a su control, el indicador no
  está aportando información de dirección.
- Desglose **por moneda** y **por año**, cómo cerraron las operaciones (SL, TP, trailing, liquidación) y las
  entradas omitidas por el tope de riesgo.

## Gatillos, filtros y salidas

Son los de `app/research/combos.py` (el mismo código de la exploración de la v2). El gatillo da el momento y
la dirección de la entrada: SFP del HeatMap, rechazo de Camarilla S3/R3, giro del Range Filter, giro de la
banda VIDYA, reversión del BB%B, cruce de WaveTrend en zona extrema, rechazo de zona de liquidez y Liquidity
Grab. Los filtros (EMA 144, estado del Range Filter, tendencia VIDYA y WaveTrend) exigen el estado alcista
para un largo y el bajista para un corto. La salida es fija: la del preregistro para SFP, Camarilla y Range
Filter; SL a 2 ATR(14) y TP 2R para el resto.

## El archivo de historial

Un archivo SQLite aparte de la base del bot, por defecto `history/history_v2.db` (configurable con
`EXPLORER_HISTORY_DB`). Tiene las velas LAST_PRICE y MARK_PRICE de 1h, 4h y 1d desde el piso real de Bitunix
(~abril de 2022), el funding y las specs de contrato del universo top-10 de CoinGecko y de los símbolos de
control. Las velas de Bitunix coinciden con las de TradingView (comparación del 2026-11-09 en
`docs/historial/PROGRESS.md`); exportarlas desde TradingView no es posible en el plan gratuito.

Crearlo o ponerlo al día (PowerShell, en la carpeta del repositorio de la v2; es reanudable y gratis):

```
.\.venv\Scripts\python.exe scripts\update_history_file.py
```

El script se niega a escribir en la base del bot o dentro de `data/`. La carpeta `history/` no va a git
(`*.db` está en `.gitignore`).

- **Servidor de desarrollo** (`scripts/run_dev_server.py`, puerto 8001): lee `history/history_v2.db` del
  repositorio directamente.
- **Contenedor de la v2:** `docker-compose.yml` monta `./history` en `/app/history` de solo lectura. Después de
  crear el archivo por primera vez hay que recrear el contenedor para que tome el montaje nuevo; luego basta
  con correr el script: la sección vuelve a leer el archivo cuando cambia.

Sin archivo, la pestaña lo dice y explica cómo crearlo.

## API

- `GET /api/explorer/options`: gatillos, filtros, marcos y series disponibles (solo hasta la fecha reservada).
- `GET /api/explorer/run?symbols=BTCUSDT&timeframe=1h&trigger=sfp&filters=ema` (más `start` y `end`, fechas `AAAA-MM-DD`
  UTC; `end` excluida): el resultado exploratorio. Hasta 12 monedas y 2 filtros; corre de a una prueba por
  vez, en un hilo aparte para no frenar el bot.

Las dos piden sesión iniciada, como el resto del dashboard.
