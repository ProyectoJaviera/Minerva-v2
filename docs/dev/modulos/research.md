# Guía del paquete `research`

> Parte de la [documentación técnica](../README.md) · Referencia automática: [`api/app/research.html`](../api/app/research.html)

## Qué hace el paquete

**Investigación exploratoria** de la v2: combinaciones de las herramientas de los indicadores de referencia (PunkAlgo
HeatMap y Frost) para buscar qué merece un preregistro nuevo. Nada de aquí es una estrategia preregistrada ni participa
del bot. Usa los indicadores de la v2 (`app/indicators/`) y la interfaz de `app/strategies/base.py`.

## Zona protegida

**No.** Vive fuera de `app/strategies/`. Sus resultados son exploratorios: con cientos de combinaciones probadas sobre
los mismos datos, alguna puede pasar los criterios por azar; por eso los finalistas van a un preregistro nuevo y a una
validación hacia adelante en paper.

## Cómo se conecta

Lo corre `scripts/v2_explore.py` con `run_full_backtest(..., strategies=, timeframes_by_strategy=, experimental=)`.
La sección de indicadores del dashboard (otro hilo de trabajo) reutiliza `ComboStrategy`, `TRIGGERS` y `FILTERS`:
cambiar esa interfaz exige avisar.

## Archivos

### `app/research/__init__.py`

**Responsabilidad.** Marca el paquete y explica su propósito exploratorio.

**Invariantes — no romper.** Ninguno propio.

**Trampas conocidas.** Ninguna.


<!-- hechos:app/research/__init__.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/research.html`](../api/app/research.html)
- **Importa (internos):** ninguno
- **Lo importan:** ninguno
- **Configuración que lee:** ninguno
- **Tablas que lee:** ninguno
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** ninguno
<!-- /hechos:app/research/__init__.py -->

### `app/research/combos.py`

**Responsabilidad.** Un gatillo (`sfp`, `camarilla`, `rf_flip`, `vidya_flip`, `bb_reversal`, `wt_cross`,
`zone_reject`, `grab`) con 0, 1 o 2 filtros (`ema`, `rf`, `vidya`, `wt`) y una salida fija (`native` para SFP,
Camarilla y Range Filter, la del preregistro; `atr` para el resto: SL a 2 ATR(14) y TP 2R), más un control con la
dirección sorteada por gatillo.

**Funciones y clases clave.**
- `compute_features()` (todas las columnas de una serie, una sola vez, con caché por serie), `liquidity_grab()` (la
  función `lele` de Frost), `zone_rejections()` (rechazos de zonas de liquidez activas, definición propia),
  `ComboStrategy` y `all_combinations()` (88 combinaciones y 8 controles).

**Invariantes — no romper.** Causal: las columnas de la vela `i` usan solo velas hasta `i` (prueba con serie truncada
== completa); sin señales en las primeras 500 velas; el sorteo del control es el SHA-256 de `(42, open_time, close)`.

**Trampas conocidas.** La caché de `compute_features` se identifica por marco, largo, primera y última apertura y suma
de cierres; se vacía al pasar de 64 series. El marco se deduce del paso entre velas (`interval_of`).


<!-- hechos:app/research/combos.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/research/combos.html`](../api/app/research/combos.html)
- **Importa (internos):** `app.candidates.camarilla_s3_r3`, `app.candidates.common`, `app.candidates.sfp_reversal`, `app.indicators._pine`, `app.indicators.oscillators`, `app.indicators.structure`, `app.indicators.trend_filters`, `app.strategies.base`
- **Lo importan:** `app.api.routes.explorer`, `app.explorer.service`, `app.research.round3`, `scripts.v2_explore`
- **Configuración que lee:** ninguno
- **Tablas que lee:** ninguno
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** `tests/unit/test_explorer.py`, `tests/unit/test_research_combos.py`
<!-- /hechos:app/research/combos.py -->

### `app/research/round3.py`

**Responsabilidad.** La ronda 3 exploratoria: el gatillo `fvg` (Fair Value Gap estándar de 3 velas, retesteo único),
los filtros `fund` (funding contra su mediana móvil), `btc` (régimen de BTC: cierre contra su EMA 200) y `rs` (fuerza
relativa frente a BTC), seis salidas en múltiplos del ATR (`EXITS`) y el modo de entrada (`market` o `limit`).

**Funciones y clases clave.** `fvg_signals()`, `compute_features_r3()`, `set_btc_context()` y `Round3Strategy`
(subclase de `ComboStrategy`; su atributo `entry_mode` lo lee el motor de backtest).

**Invariantes — no romper.** Causal (prueba con serie truncada == completa). `btc` y `rs` quedan en falso si no se
registró la serie de BTC del marco con `set_btc_context`. No cambia la interfaz de `combos.py`.

**Trampas conocidas.** El contexto de BTC es un estado del módulo: hay que registrarlo antes de correr y vacía la
caché de columnas.

<!-- hechos:app/research/round3.py -->
**Hechos derivados del código** (los escribe `scripts/build_dev_docs.py`; no se editan):

- **Referencia pdoc:** [`api/app/research/round3.html`](../api/app/research/round3.html)
- **Importa (internos):** `app.candidates.common`, `app.candidates.sfp_reversal`, `app.indicators._pine`, `app.research.combos`, `app.strategies.base`
- **Lo importan:** `scripts.v2_round3`
- **Configuración que lee:** ninguno
- **Tablas que lee:** ninguno
- **Tablas que escribe:** ninguno
- **Tablas que crea o altera:** ninguno
- **Pruebas que lo importan o citan:** `tests/unit/test_research_round3.py`
<!-- /hechos:app/research/round3.py -->
