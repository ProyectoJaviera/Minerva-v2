# Guía del paquete `indicators`

> Parte de la [documentación técnica](../README.md) · Referencia automática: [`api/app/indicators.html`](../api/app/indicators.html)

## Qué hace el paquete

Indicadores técnicos calculados con **pandas puro** (no se usa `pandas-ta`, por decisión de la Fase 0: mantenimiento
incierto). Todos son **causales**: el valor de una vela depende solo de esa vela y de las anteriores, y por eso se pueden
calcular una sola vez sobre toda la serie sin mirar al futuro.

## Zona protegida

**Sí, `engine.py`.** Estos cálculos son los de las estrategias: cambiar una fórmula (o el modo de suavizado) cambia las
señales que nacen y, con ellas, la medición. Ver [ZONAS_PROTEGIDAS](../ZONAS_PROTEGIDAS.md#estrategias-y-parámetros).

**No, los módulos de la v2** (`_pine.py`, `structure.py`, `levels.py`, `trend_filters.py`, `oscillators.py`): son la
Fase 0 de la v2, inspirados en indicadores públicos de TradingView (autoría y licencia por verificar), y **no están
conectados** a ninguna estrategia ni al registro. Su especificación exacta está en
[`docs/v2/ESPECIFICACION_INDICADORES.md`](../../v2/ESPECIFICACION_INDICADORES.md).

## Cómo se conecta

`engine.py` solo lo usan las estrategias (`app/strategies/`); los módulos de la v2 todavía no los usa nadie fuera de
sus pruebas. Los indicadores que ve el LLM (`indicators_by_strategy` en sus
*features*) no se recalculan al armar el mensaje: se leen de la fila de `signals` que el generador de señales guardó.

## Archivos

### `app/indicators/__init__.py`

**Responsabilidad.** Solo el docstring del paquete.

**Funciones y clases clave.** Ninguna.

**Invariantes.** Ninguno.

**Trampas conocidas.** Ninguna.

<!-- hechos:app/indicators/__init__.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/indicators.html`](../api/app/indicators.html)
- **Importa (internos):** ninguno
- **Lo importan:** ninguno
- **Configuración que lee:** ninguno
- **Tablas que lee:** ninguno
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** ninguno
<!-- /hechos:app/indicators/__init__.py -->

### `app/indicators/engine.py`

**Responsabilidad.** Seis funciones puras sobre `pandas.Series` o `DataFrame`: `ema`, `rsi`, `sma`, `bollinger_bands`,
`donchian_channel` y `atr`.

**Funciones y clases clave.**
- `ema(series, span)` — media móvil exponencial con `adjust=False`.
- `rsi(series, period)` — RSI de Wilder (suavizado `ewm(alpha=1/period)`); las primeras `period` posiciones son NaN; vale
  100 si no hay pérdidas y sí ganancias, y 50 con el precio plano.
- `sma(series, period)` — media simple; las primeras `period − 1` posiciones son NaN.
- `bollinger_bands(series, period, num_std)` — `(superior, media, inferior)` con desviación estándar **poblacional**
  (`ddof=0`, la convención de Bollinger).
- `donchian_channel(df, period)` — máximo y mínimo de las últimas `period` velas, **la actual incluida** (la estrategia
  lo desplaza una vela, ver [strategies](strategies.md#appstrategiesdonchian_breakoutpy)).
- `atr(df, period)` — ATR de Wilder sobre el rango verdadero.

**Invariantes — no romper.**
- Causalidad: ningún valor puede depender de una vela futura. Es lo que permite que `precompute` de una estrategia dé
  **exactamente** el valor que daría recalcular vela a vela.
- Cada función lanza `ValueError` si el periodo es menor que 1 o falta una columna requerida.

**Trampas conocidas.** Ninguna conocida.

<!-- hechos:app/indicators/engine.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/indicators/engine.html`](../api/app/indicators/engine.html)
- **Importa (internos):** ninguno
- **Lo importan:** `app.strategies.donchian_breakout`, `app.strategies.ema_cross`, `app.strategies.mean_reversion_rsi_bb`, `app.strategies.trend_atr_stop`
- **Configuración que lee:** ninguno
- **Tablas que lee:** ninguno
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** `tests/unit/test_indicators.py`
<!-- /hechos:app/indicators/engine.py -->

### `app/indicators/_pine.py`

**Responsabilidad.** Primitivas causales que imitan las de Pine Script para los indicadores de la v2: medias con
arranque explícito, desvío poblacional, rango verdadero, ATR y cruces. No reemplaza a `engine.py`.

**Funciones y clases clave.**
- `pine_ema(series, length)` y `pine_rma(series, length)` — media exponencial (`alpha = 2/(n+1)`) y de Wilder
  (`alpha = 1/n`); ambas arrancan con la media simple de los primeros `length` valores válidos consecutivos.
- `pine_sma`, `pine_stdev` — NaN si falta un valor de la ventana; el desvío es poblacional.
- `true_range(df)`, `pine_atr(df, length)` — en la primera vela el rango verdadero es `high - low`.
- `crossover(a, b)`, `crossunder(a, b)` — falsos si falta cualquiera de los cuatro valores.
- `require_columns`, `require_positive` — validación común (lanzan `ValueError`).

**Invariantes — no romper.**
- Causalidad: el valor de la vela `i` solo usa las velas `0..i`.
- Tras arrancar, una entrada NaN da salida NaN y la media conserva su estado (no se reinicia).

**Trampas conocidas.** El arranque de `ta.ema` en TradingView no está verificado (se usa el de `ta.rma`); solo afecta
al calentamiento. No mezclar con `engine.ema`, que arranca con el primer valor (`ewm(adjust=False)`).

<!-- hechos:app/indicators/_pine.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** sin página (módulo privado)
- **Importa (internos):** ninguno
- **Lo importan:** `app.candidates.range_filter_flip`, `app.candidates.sfp_reversal`, `app.indicators.levels`, `app.indicators.oscillators`, `app.indicators.structure`, `app.indicators.trend_filters`, `app.research.combos`, `scripts.v2_tradingview_check`
- **Configuración que lee:** ninguno
- **Tablas que lee:** ninguno
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** `tests/unit/test_indicators_v2_pine.py`, `tests/unit/test_indicators_v2_structure.py`, `tests/unit/test_indicators_v2_trend_oscillators.py`, `tests/unit/test_strategies_v2.py`
<!-- /hechos:app/indicators/_pine.py -->

### `app/indicators/levels.py`

**Responsabilidad.** Niveles Camarilla (R1–R4, S1–S4) del día UTC anterior para cada vela, agregando el máximo, el
mínimo y el cierre del día desde las propias velas de la serie.

**Funciones y clases clave.**
- `camarilla_levels(df, interval_ms, require_complete)` — necesita `open_time` en milisegundos UTC; devuelve
  `cam_prev_high/low/close` y `cam_r4` … `cam_s4`.
- `camarilla_from_hlc(high, low, close)` — la fórmula: `C ± (H − L) · 1.1 / d`, con `d` = 12, 6, 4, 2.

**Invariantes — no romper.**
- Las velas del día `D` usan solo el día `D − 1` completo; con `require_complete` un día con velas faltantes (o con un
  cierre NaN) no da niveles.
- `open_time` estrictamente creciente y una duración de vela que divida un día (si no, `ValueError`).

**Trampas conocidas.** El DataFrame del motor de backtest no trae `open_time`: conectarlo exige pasarlo.

<!-- hechos:app/indicators/levels.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/indicators/levels.html`](../api/app/indicators/levels.html)
- **Importa (internos):** `app.indicators._pine`
- **Lo importan:** `app.candidates.camarilla_s3_r3`, `scripts.v2_tradingview_check`
- **Configuración que lee:** ninguno
- **Tablas que lee:** ninguno
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** `tests/unit/test_indicators_v2_causality.py`, `tests/unit/test_indicators_v2_levels.py`, `tests/unit/test_strategies_v2.py`, `tests/unit/test_v2_tradingview_check_script.py`
<!-- /hechos:app/indicators/levels.py -->

### `app/indicators/oscillators.py`

**Responsabilidad.** BB%B con sus «velas de reversión» y WaveTrend con sus cruces en zona extrema (la «Reversal RSI»
de Frost).

**Funciones y clases clave.**
- `bb_percent_b(close, period, mult, oversold, overbought)` — `%B` y los cruces de −0.1 (salida de sobreventa) y 1.1
  (salida de sobrecompra).
- `wavetrend(df, channel, average, signal, extreme)` — `wt1`, `wt2` y los cruces con `wt2 ≤ −72` o `wt2 ≥ 72`.

**Invariantes — no romper.** Causalidad; con precio plano `%B` y `ci` son NaN (no hay división por cero).

**Trampas conocidas.** Ninguna conocida.

<!-- hechos:app/indicators/oscillators.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/indicators/oscillators.html`](../api/app/indicators/oscillators.html)
- **Importa (internos):** `app.indicators._pine`
- **Lo importan:** `app.research.combos`
- **Configuración que lee:** ninguno
- **Tablas que lee:** ninguno
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** `tests/unit/test_indicators_v2_causality.py`, `tests/unit/test_indicators_v2_trend_oscillators.py`
<!-- /hechos:app/indicators/oscillators.py -->

### `app/indicators/structure.py`

**Responsabilidad.** Estructura de precio inspirada en el Heatmap: pivotes estrictos, el SFP (barrida de un pivote y
confirmación) y zonas de liquidez deterministas emitidas al confirmarse el pivote.

**Funciones y clases clave.**
- `pivot_high(high, left, right)`, `pivot_low(low, left, right)` — el valor aparece en la vela de confirmación
  (`p + right`); un empate no es pivote.
- `sfp_signals(df, left, right, max_age)` — columnas `sfp_bear_*` y `sfp_bull_*`: barrida, señal (confirmación) y, en
  la vela de señal, pivote, extremo opuesto, extremo de la barrida y velas desde la barrida.
- `liquidity_zones(df, left, right, atr_period, atr_mult, volume_window)` — una fila por zona, con `emit_index` y
  `mitigated_index` (posiciones 0..n−1).
- `active_zones_at(zones, index)`, `heatmap_atr_multiplier(interval)`.

**Invariantes — no romper.**
- Una zona nunca existe antes de su vela de emisión y su mitigación se busca solo en velas posteriores.
- En el SFP, dentro de una misma vela: actualizar pivote → barrida → confirmación → expiración (el orden del original).

**Trampas conocidas.** Los índices de las zonas son posiciones, no etiquetas del índice del DataFrame.

<!-- hechos:app/indicators/structure.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/indicators/structure.html`](../api/app/indicators/structure.html)
- **Importa (internos):** `app.indicators._pine`
- **Lo importan:** `app.candidates.sfp_reversal`, `app.research.combos`, `scripts.v2_tradingview_check`
- **Configuración que lee:** ninguno
- **Tablas que lee:** ninguno
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** `tests/unit/test_indicators_v2_causality.py`, `tests/unit/test_indicators_v2_structure.py`
<!-- /hechos:app/indicators/structure.py -->

### `app/indicators/trend_filters.py`

**Responsabilidad.** Range Filter de Frost (con sus giros de compra y venta) y la banda VIDYA ± ATR(200)·1.6 («F.
Trail»).

**Funciones y clases clave.**
- `range_filter(close, fast_period, fast_mult, slow_period, slow_mult)` — `rf_filter`, contadores y `rf_buy`/`rf_sell`
  (primera condición en un sentido tras una del sentido contrario); `RANGE_FILTER_SENSITIVITY` con los tres modos.
- `vidya(close, length, momentum, smooth)` y `vidya_band(df, ...)` — bandas, estado de tendencia y trailing.

**Invariantes — no romper.** Causalidad; los dos filtros son recursivos y arrancan desde 0, así que las primeras
velas son calentamiento (la especificación pide descartar al menos 500).

**Trampas conocidas.** Si el precio ya está fuera de la banda VIDYA cuando esta aparece, no hay cruce y la tendencia
queda «bajista» hasta el primer cruce real (comportamiento del original, con prueba).

<!-- hechos:app/indicators/trend_filters.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/indicators/trend_filters.html`](../api/app/indicators/trend_filters.html)
- **Importa (internos):** `app.indicators._pine`
- **Lo importan:** `app.candidates.range_filter_flip`, `app.research.combos`, `scripts.v2_tradingview_check`
- **Configuración que lee:** ninguno
- **Tablas que lee:** ninguno
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** `tests/unit/test_indicators_v2_causality.py`, `tests/unit/test_indicators_v2_trend_oscillators.py`, `tests/unit/test_v2_tradingview_check_script.py`
<!-- /hechos:app/indicators/trend_filters.py -->
