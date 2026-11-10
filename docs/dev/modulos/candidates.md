# Guía del paquete `candidates`

> Parte de la [documentación técnica](../README.md) · Referencia automática: [`api/app/candidates.html`](../api/app/candidates.html)

## Qué hace el paquete

Los **candidatos de la v2** del [preregistro](../../v2/PREREGISTRO_V2.md) (congelado el 2026-11-10): `sfp_reversal_5_1`,
`camarilla_s3_r3`, `range_filter_flip_ema144` y el control `control_sfp_random_dir_seed42`. Heredan de
`app/strategies/base.py` (misma interfaz que las estrategias de la v1) y usan los indicadores de la v2
(`app/indicators/structure.py`, `levels.py`, `trend_filters.py`), especificados en
[`docs/v2/ESPECIFICACION_INDICADORES.md`](../../v2/ESPECIFICACION_INDICADORES.md). Inspirados en indicadores públicos de
TradingView (autoría y licencia por verificar).

## Zona protegida

**No.** El paquete vive fuera de `app/strategies/` a propósito: ese directorio es la zona protegida de las seis
estrategias de la v1 (ver [ZONAS_PROTEGIDAS](../ZONAS_PROTEGIDAS.md#estrategias-y-parámetros)). Sus parámetros, en
cambio, son los del preregistro: cambiarlos después de congelarlo invalida la prueba.

## Cómo se conecta

**Solo con `scripts/run_backtest_v2.py`**, la corrida única de la Fase 2 de la v2. `CANDIDATES` no es `STRATEGIES`: ni el scheduler ni `scripts/run_backtest.py` lo leen. Del motor
de backtest usan dos cosas agregadas para la v2: la columna `open_time` del DataFrame de `precompute` y el atributo
opcional `skip_entry_if_sl_crossed` (ver [backtesting](backtesting.md#appbacktestingenginepy)).

## Archivos

### `app/candidates/__init__.py`

**Responsabilidad.** Reúne los cuatro candidatos sin registrarlos en la v1.

**Funciones y clases clave.**
- `CANDIDATES` — nombre → instancia; `CANDIDATE_TIMEFRAMES` — 1h y 4h para todos; `CONTROL_STRATEGIES` — el control,
  que nunca se aprueba.

**Invariantes — no romper.** Ningún nombre coincide con uno de `STRATEGIES` (hay prueba).

**Trampas conocidas.** Conectarlos al backtest es un paso posterior, con el preregistro congelado.

<!-- hechos:app/candidates/__init__.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/candidates.html`](../api/app/candidates.html)
- **Importa (internos):** `app.candidates.camarilla_s3_r3`, `app.candidates.range_filter_flip`, `app.candidates.sfp_reversal`, `app.strategies.base`
- **Lo importan:** `scripts.run_backtest_v2`
- **Configuración que lee:** ninguno
- **Tablas que lee:** ninguno
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** `tests/unit/test_backtest_engine_v2.py`, `tests/unit/test_run_backtest_v2_script.py`, `tests/unit/test_strategies_v2.py`
<!-- /hechos:app/candidates/__init__.py -->

### `app/candidates/common.py`

**Responsabilidad.** Lo común a los candidatos: el calentamiento de 500 velas y la lectura de la vela de señal.

**Funciones y clases clave.**
- `add_bar_index(df)` — agrega `v2_bar_index` (posición de cada vela en la serie completa).
- `ensure_precomputed(df, required, precompute)`, `warmed_up(row, warmup)`, `is_true(value)`.

**Invariantes — no romper.** `precompute` debe recibir la **serie completa** (como hace el motor): la posición decide el
calentamiento y los indicadores recursivos dependen de su arranque.

**Trampas conocidas.** Si `evaluate` recibe una ventana sin precalcular, se calcula sobre esa ventana; con 300 velas
nunca se pasa el calentamiento y no hay señal (a propósito: es conservador).

<!-- hechos:app/candidates/common.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/candidates/common.html`](../api/app/candidates/common.html)
- **Importa (internos):** ninguno
- **Lo importan:** `app.candidates.camarilla_s3_r3`, `app.candidates.range_filter_flip`, `app.candidates.sfp_reversal`, `app.research.combos`
- **Configuración que lee:** ninguno
- **Tablas que lee:** ninguno
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** ninguno
<!-- /hechos:app/candidates/common.py -->

### `app/candidates/sfp_reversal.py`

**Responsabilidad.** `sfp_reversal_5_1` y su control.

**Funciones y clases clave.**
- `SfpReversalStrategy` — LARGO/CORTO en la confirmación de un SFP 5/1; SL = mecha de la barrida ± `0.1 · ATR(14)`;
  TP = 2R; `skip_entry_if_sl_crossed = True`.
- `ControlSfpRandomDirStrategy` — mismas velas y misma distancia de SL, dirección sorteada; `random_direction(seed,
  open_time, close)` hace el sorteo determinista.

**Invariantes — no romper.**
- El control entra exactamente cuando entra el SFP y se omite cuando el SFP se omitiría.
- Si el SL no se puede calcular, `stop_price` devuelve la propia entrada: el motor la omite.

**Trampas conocidas.** El sorteo depende de `(42, open_time, close)` de la vela de señal, no del símbolo y el marco: la
interfaz de las estrategias no los recibe.

<!-- hechos:app/candidates/sfp_reversal.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/candidates/sfp_reversal.html`](../api/app/candidates/sfp_reversal.html)
- **Importa (internos):** `app.candidates.common`, `app.indicators._pine`, `app.indicators.structure`, `app.strategies.base`
- **Lo importan:** `app.candidates`, `app.research.combos`
- **Configuración que lee:** ninguno
- **Tablas que lee:** ninguno
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** `tests/unit/test_strategies_v2.py`
<!-- /hechos:app/candidates/sfp_reversal.py -->

### `app/candidates/camarilla_s3_r3.py`

**Responsabilidad.** `camarilla_s3_r3`: primer rechazo del día de S3 (largo) o R3 (corto).

**Funciones y clases clave.**
- `CamarillaS3R3Strategy` — SL `S4 · 0.99` / `R4 · 1.01`; TP R3 / S3; niveles del día de la señal.

**Invariantes — no romper.** Una sola señal por lado y día UTC; una vela que toca S3 y R3 no da señal.

**Trampas conocidas.** Necesita `open_time` (lo pone el motor desde la v2).

<!-- hechos:app/candidates/camarilla_s3_r3.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/candidates/camarilla_s3_r3.html`](../api/app/candidates/camarilla_s3_r3.html)
- **Importa (internos):** `app.candidates.common`, `app.indicators.levels`, `app.strategies.base`
- **Lo importan:** `app.candidates`, `app.research.combos`
- **Configuración que lee:** ninguno
- **Tablas que lee:** ninguno
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** `tests/unit/test_strategies_v2.py`
<!-- /hechos:app/candidates/camarilla_s3_r3.py -->

### `app/candidates/range_filter_flip.py`

**Responsabilidad.** `range_filter_flip_ema144`: giro del Range Filter a favor de la EMA 144.

**Funciones y clases clave.**
- `RangeFilterFlipEma144Strategy` — SL y trailing a `2.5 · ATR(14)`; sin TP propio (el de respaldo del motor).

**Invariantes — no romper.** El cierre debe estar estrictamente del lado de la EMA (igual no cuenta).

**Trampas conocidas.** Ninguna conocida.

<!-- hechos:app/candidates/range_filter_flip.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/candidates/range_filter_flip.html`](../api/app/candidates/range_filter_flip.html)
- **Importa (internos):** `app.candidates.common`, `app.indicators._pine`, `app.indicators.trend_filters`, `app.strategies.base`
- **Lo importan:** `app.candidates`
- **Configuración que lee:** ninguno
- **Tablas que lee:** ninguno
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** `tests/unit/test_strategies_v2.py`
<!-- /hechos:app/candidates/range_filter_flip.py -->
