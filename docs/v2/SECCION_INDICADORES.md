# Sección «Indicadores» (v2): pruebas manuales y exploratorias

Pestaña **Indicadores** del dashboard de la v2 (<http://127.0.0.1:8001/>). Eliges monedas, temporalidad (15m,
1h, 4h, 1D o 1S) y marcas los indicadores que quieras (uno, varios o todos), y en segundos ves cómo le habría ido
a esa combinación sobre el historial de Bitunix.

## Qué es y qué no es

- **Es exploratoria.** Sirve para mirar ideas. No es una ronda preregistrada, no se guarda en la base y no
  pasa por los criterios de la Fase 2. Probar muchas combinaciones y quedarse con la mejor sobreestima el
  resultado (sesgo de selección): una idea que se vea bien aquí hay que llevarla a un preregistro nuevo.
- **No usa velas desde el 2026-10-01.** Estaban reservadas para las rondas preregistradas; el examen de los
  finalistas de la ronda 3 ya las usó, así que quitar el corte (`app/explorer/service.py::RESERVED_FROM`) es
  decisión del dueño.
- **No toca la base del bot.** Lee un archivo de historial aparte, en modo de solo lectura.

## Cómo se combinan los indicadores

Todos los indicadores son casillas y se tratan igual: cada uno **vota** alcista o bajista en cada vela.

- **De estado** (votan siempre): Range Filter, banda VIDYA, WaveTrend (`wt1` sobre o bajo `wt2`), cierre sobre o
  bajo la EMA 144, funding contra su mediana de 30 días (en contra del lado saturado), régimen de BTC (cierre
  de BTC sobre o bajo su EMA 200 del mismo marco) y fuerza relativa contra BTC (retorno de 180 velas).
- **De evento** (votan durante la **ventana** que eliges, 5 velas por defecto, contando la de la señal): SFP del
  HeatMap, rechazo de Camarilla S3/R3, FVG (retesteo de un Fair Value Gap de 3 velas), rechazo de una zona de
  liquidez, Liquidity Grab, reversión del BB%B y cruce de WaveTrend en zona extrema. Si en la ventana hubo
  señales de los dos lados, vale la más reciente.

**Se entra en la vela en que todos los marcados coinciden** (y en la anterior no coincidían): largo si todos
son alcistas, corto si todos son bajistas. Un indicador de estado solo entra en cada cambio de estado (el Range
Filter solo da exactamente sus giros); uno de evento solo, en cada señal nueva. Con más indicadores hay menos
coincidencias y menos operaciones: con los 14 marcados casi nunca coinciden todos, así que la opción **«Deben
coincidir»** permite pedir solo «al menos N» (el lado ganador necesita al menos N votos y más votos que el
contrario).

**Salida** a elección, en múltiplos del ATR(14): SL 2 ATR con TP 2R (por defecto), SL 1 ATR con TP 2R, SL 1,5 ATR
con TP 3R, SL 2 ATR con TP 1R, y SL 2 o 3 ATR con trailing de la misma distancia (con trailing no hay TP fijo y el
motor usa su TP de respaldo del 10 %). O una salida **personalizada en %** del precio de entrada: SL
obligatorio, TP y trailing opcionales (el trailing sigue al mejor precio a esa distancia; sin TP ni trailing
vale el TP de respaldo). Ojo con el tope de riesgo del motor: a 10x, un SL mayor que 5 % perdería más del 50 % del
margen y esas entradas se omiten (la pantalla lo avisa). Esto pesa en los marcos largos: en 1S casi todos los SL de 2 ATR superan el 5 % (con BTC, ETH y SOL en 1S y WaveTrend, las 72 entradas se omitieron) y en 1D muchos; ahí conviene la salida en %.

Las señales vienen del mismo código de la exploración y de la ronda 3 (`app/research/combos.py` y
`fvg_signals` de `app/research/round3.py`); la combinación está en `app/explorer/confluence.py`. El calentamiento
(velas sin señal al inicio) es de 500 velas en 15m, 1h y 4h, 300 en 1D y 50 en 1S.

## Qué muestra

- **% de operaciones ganadoras**, profit factor, número de operaciones (largos y cortos), PnL neto, resultado
  medio por operación, ganancia y pérdida medias y drawdown máximo. Los montos son del motor de la Fase 2:
  margen de 5 USDT a 10x, comisión taker por lado, slippage, funding y liquidación, entrada en el open de la
  vela siguiente a la señal.
- **Control con dirección al azar:** las mismas velas de entrada y la misma salida, pero la dirección se sortea
  (como el control del preregistro). Si la combinación no supera claramente a su control, los indicadores no
  están aportando información de dirección.
- Desglose **por moneda** y **por año**, cómo cerraron las operaciones (SL, TP, trailing, liquidación) y las
  entradas omitidas por el tope de riesgo.

## Temporalidades y tiempos

- **15m:** cuatro veces más velas que 1h; con varias monedas la prueba puede tardar minutos.
- **1h:** unos 7 segundos por moneda. **4h:** unos 2 segundos. Repetir una prueba es instantáneo (caché de las
  últimas 32).
- **1S:** las velas de precio de marca de Bitunix empiezan en enero de 2023, así que hay unas 200 semanas y 50 se usan de calentamiento; las medias largas (EMA 144, VIDYA, régimen de BTC) casi no alcanzan a calcularse: espera muy pocas operaciones.
- **15m:** el historial de 15m de Bitunix empieza en junio de 2023.

## El archivo de historial

Un archivo SQLite aparte de la base del bot, por defecto `history/history_v2.db` (configurable con
`EXPLORER_HISTORY_DB`). Tiene las velas LAST_PRICE y MARK_PRICE de 15m, 1h, 4h, 1d y 1w desde el piso real de
Bitunix (~abril de 2022), el funding y las specs de contrato del universo top-10 de CoinGecko y de los símbolos
de control. Los intervalos 15m y 1w se verificaron contra la API pública de Bitunix el 2026-11-11 (la semanal
abre el lunes 00:00 UTC). Las velas de Bitunix coinciden con las de TradingView (comparación del 2026-11-09 en
`docs/historial/PROGRESS.md`); exportarlas desde TradingView no es posible en el plan gratuito.

Crearlo o ponerlo al día (PowerShell, en la carpeta del repositorio de la v2; es reanudable y gratis):

```
.\.venv\Scripts\python.exe scripts\update_history_file.py
```

Con `--only-extra` baja solo 15m y 1w. El script se niega a escribir en la base del bot o dentro de `data/`. La
carpeta `history/` no va a git (`*.db` está en `.gitignore`).

- **Servidor de desarrollo** (`scripts/run_dev_server.py`, puerto 8001): lee `history/history_v2.db` del
  repositorio directamente.
- **Contenedor de la v2:** `docker-compose.yml` monta `./history` en `/app/history` de solo lectura. Después de
  crear el archivo por primera vez hay que recrear el contenedor para que tome el montaje nuevo; luego basta
  con correr el script: la sección vuelve a leer el archivo cuando cambia.

Sin archivo, la pestaña lo dice y explica cómo crearlo.

## API

- `GET /api/explorer/options`: indicadores (con su tipo), salidas, ventana, temporalidades y series
  disponibles (solo hasta el corte).
- `GET /api/explorer/run?symbols=BTCUSDT&timeframe=1h&indicators=sfp&indicators=ema&window=5&exit=s2_tp2r` (más
  `min_agree`; con `exit=pct`, `sl_pct`, `tp_pct` y `trail_pct`; y `start` y `end`, fechas `AAAA-MM-DD` UTC; `end` excluida): el resultado exploratorio. Hasta 12 monedas y sin
  límite de indicadores; corre de a una prueba por vez, en un hilo aparte para no frenar el bot.

Las dos piden sesión iniciada, como el resto del dashboard.
