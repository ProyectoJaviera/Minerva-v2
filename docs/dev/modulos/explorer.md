# Guía del paquete `explorer`

Sección «Indicadores» del dashboard de la v2: backtest **exploratorio** a pedido de una combinación (gatillo + filtros de `app/research/combos.py`) sobre el archivo de historial local, con su control de dirección al azar. No escribe en ninguna base ni pasa por los criterios de la Fase 2. Guía de uso: `docs/v2/SECCION_INDICADORES.md`.

## Archivos

### `app/explorer/__init__.py`

**Responsabilidad.** Marca el paquete y explica que sus resultados son exploratorios, no evidencia preregistrada.

**Invariantes — no romper.** Ninguno propio.

**Trampas conocidas.** Ninguna.


<!-- hechos:app/explorer/__init__.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/explorer.html`](../api/app/explorer.html)
- **Importa (internos):** ninguno
- **Lo importan:** ninguno
- **Configuración que lee:** ninguno
- **Tablas que lee:** ninguno
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** ninguno
<!-- /hechos:app/explorer/__init__.py -->

### `app/explorer/service.py`

**Responsabilidad.** Backtest exploratorio a pedido de la confluencia de indicadores elegida
(`app/explorer/confluence.py`) y de su control con dirección al azar, por moneda, sobre el archivo de historial
local, con el motor `run_backtest` de la Fase 2.

**Funciones y clases clave.**
- `validate_request()` / `ExplorerRequest` (monedas, marco 15m a 1w, indicadores sin límite, ventana, salida,
  fechas), `ReadOnlyDatabase` (abre con `mode=ro&immutable=1` y no toca el esquema), `available_series()` (series
  del archivo, con caché por fecha de modificación), `load_btc()` (serie de BTC del marco para `btc` y `rs`),
  `run_exploration_on_db()` (confluencia + control + desgloses por moneda y año) y `run_exploration()` (una
  corrida a la vez, en un hilo con su propio bucle y conexión, con caché de las últimas 32 corridas que se
  invalida al cambiar el archivo).

**Invariantes — no romper.** Nunca entra al cálculo una vela desde `RESERVED_FROM` (2026-10-01, fijo en el código,
no configurable). Nada se escribe en el archivo de historial ni en la base del bot; el resultado no se guarda ni pasa
por los criterios de la Fase 2.

**Trampas conocidas.** `immutable=1` supone que el archivo no cambia mientras se lee: actualizarlo con una corrida
en curso puede dar un error en esa corrida (por eso conviene bajar datos nuevos en una copia y reemplazar el archivo
al final). El drawdown con varias monedas encadena sus operaciones como una sola cuenta, una posición por moneda;
es orientativo.


<!-- hechos:app/explorer/service.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/explorer/service.html`](../api/app/explorer/service.html)
- **Importa (internos):** `app.backtesting.engine`, `app.backtesting.metrics`, `app.config`, `app.explorer.confluence`, `app.market.ohlcv_history`, `app.persistence.database`, `app.persistence.repositories.ohlcv_repo`
- **Lo importan:** `app.api.routes.explorer`, `scripts.v2_forward_test`
- **Configuración que lee:** `BACKTEST_INITIAL_CAPITAL`, `BACKTEST_SLIPPAGE_BPS`, `DEFAULT_MARGIN_USDT`, `LEVERAGE`, `TAKER_FEE_PCT`
- **Tablas que lee:** `ohlcv_cache`
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** `tests/unit/test_explorer.py`
<!-- /hechos:app/explorer/service.py -->

### `app/explorer/confluence.py`

**Responsabilidad.** La regla de la pestaña: cada indicador vota alcista o bajista por vela (los de estado siempre,
los de evento durante una ventana desde su señal) y se entra en la vela en que todos los elegidos pasan a coincidir,
con una salida fija en múltiplos del ATR(14).

**Funciones y clases clave.**
- `INDICATORS` (id → etiqueta, tipo y columnas), `EXITS` (en ATR) y la salida `PCT_EXIT` en % del precio
  (`check_pct_exit()`, `pct_exit_name()`, `pct_exit_label()`), `compute_votes()` (columnas de `combos.compute_features`,
  `fvg_signals` de la ronda 3 y funding, régimen de BTC y fuerza relativa para cualquier marco; con caché),
  `event_votes()`, `confluence_signals()` (con `min_agree`: al menos N votos del mismo lado y más que el contrario) y
  `ConfluenceStrategy` (precalcula las entradas como arrays; el control
  sortea la dirección con el mismo SHA-256 del preregistro).

**Invariantes — no romper.** Causal: la vela `i` usa solo velas hasta `i`. Un indicador de estado solo entra en sus
cambios de estado (prueba: el Range Filter solo da exactamente `long_rf_flip`/`short_rf_flip`); uno de evento solo
con ventana 1, en sus señales. El control usa las mismas velas de entrada y la misma salida.

**Trampas conocidas.** El calentamiento depende del marco (`WARMUP_BY_TIMEFRAME`: 100 velas en 1w, donde hay ~230
desde 2022). Con salidas de trailing no hay TP fijo: el motor aplica su TP de respaldo. `btc` y `rs` votan falso si
no se pasa la serie de BTC.


<!-- hechos:app/explorer/confluence.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/explorer/confluence.html`](../api/app/explorer/confluence.html)
- **Importa (internos):** `app.candidates.common`, `app.candidates.sfp_reversal`, `app.indicators._pine`, `app.research.combos`, `app.research.round3`, `app.strategies.base`
- **Lo importan:** `app.api.routes.explorer`, `app.explorer.service`
- **Configuración que lee:** ninguno
- **Tablas que lee:** ninguno
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** `tests/unit/test_explorer.py`
<!-- /hechos:app/explorer/confluence.py -->
