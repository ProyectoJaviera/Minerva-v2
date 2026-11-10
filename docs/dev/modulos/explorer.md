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

**Responsabilidad.** Backtest exploratorio a pedido de una combinación de `app/research/combos.py` y de su control
con dirección al azar, por moneda, sobre el archivo de historial local, con el motor `run_backtest` de la Fase 2.

**Funciones y clases clave.**
- `validate_request()` / `ExplorerRequest` (monedas, marco 1h o 4h, gatillo, hasta 2 filtros, fechas), `ReadOnlyDatabase`
  (abre con `mode=ro&immutable=1` y no toca el esquema), `available_series()` (series del archivo, con caché por fecha
  de modificación), `run_exploration_on_db()` (combinación + control + desgloses por moneda y año) y
  `run_exploration()` (una corrida a la vez, en un hilo con su propio bucle y conexión, con caché de las últimas 32
  corridas que se invalida al cambiar el archivo). `FastComboStrategy` es `ComboStrategy` leyendo la fila de la señal
  de arrays numpy en vez de `df.iloc[-1]`: mismas operaciones (prueba operación por operación), menos de la mitad del
  tiempo.

**Invariantes — no romper.** Nunca entra al cálculo una vela desde `RESERVED_FROM` (2026-10-01, fijo en el código,
no configurable). Nada se escribe en el archivo de historial ni en la base del bot; el resultado no se guarda ni pasa
por los criterios de la Fase 2.

**Trampas conocidas.** `immutable=1` supone que el archivo no cambia mientras se lee: actualizarlo con una corrida
en curso puede dar un error en esa corrida. El drawdown con varias monedas encadena sus operaciones como una sola
cuenta, una posición por moneda; es orientativo.


<!-- hechos:app/explorer/service.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/explorer/service.html`](../api/app/explorer/service.html)
- **Importa (internos):** `app.backtesting.engine`, `app.backtesting.metrics`, `app.candidates.common`, `app.config`, `app.market.ohlcv_history`, `app.persistence.database`, `app.research.combos`
- **Lo importan:** `app.api.routes.explorer`
- **Configuración que lee:** `BACKTEST_INITIAL_CAPITAL`, `BACKTEST_SLIPPAGE_BPS`, `DEFAULT_MARGIN_USDT`, `LEVERAGE`, `TAKER_FEE_PCT`
- **Tablas que lee:** `ohlcv_cache`
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** `tests/unit/test_explorer.py`
<!-- /hechos:app/explorer/service.py -->
