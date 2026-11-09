# Minerva v2 — Preregistro de candidatos (BORRADOR)

> **BORRADOR — NO EJECUTAR.** Aprobado por el dueño del proyecto el 2026-11-08 **con cambios**, que ya están
> incorporados abajo. Sigue siendo borrador hasta que el dueño confirme la comparación con TradingView (sección 5). Recién
> entonces se congela en un commit propio, sin esta marca y **antes** de cualquier corrida, igual que
> `docs/historial/FASE2_CRITERIOS.md` en la v1. **No se corrió ningún backtest.**
>
> Implementación: `app/candidates/` (fuera de `app/strategies/`, la zona protegida de la v1), sin registrar en
> `STRATEGIES`. Indicadores: `docs/v2/ESPECIFICACION_INDICADORES.md`.

## 1. Regla de preregistro

- Los candidatos, sus parámetros, sus SL/TP, los marcos de tiempo y los criterios de descarte se fijan aquí **antes**
  de mirar cualquier resultado. Tras ver resultados OOS **no se cambia nada**: ni parámetros, ni niveles, ni criterios,
  ni se agregan candidatos para «probar otra variante». Un ajuste posterior se valida hacia adelante en paper, nunca
  volviendo a correr el backtest con reglas distintas.
- Parámetros: **los del original de TradingView, sin optimizar** (ver la especificación). Ningún parámetro se elige
  mirando datos.
- Máximo 4 candidatos: 3 reales y 1 de control.

## 2. Candidatos

Comunes a los cuatro: marcos **1h y 4h**, cada uno como combinación independiente (como `donchian_breakout_20` en la
Fase 2); señal evaluada al cierre de la vela `i` y llenada en el `open` de `i + 1` (convención del motor); indicadores
calculados **una sola vez sobre la serie completa** en `precompute`; **sin señales en las primeras 500 velas** de cada
serie (calentamiento de las medias recursivas y del ATR(200)); mientras hay una posición abierta se ignora cualquier
señal (punto 6 de `FASE2_CRITERIOS.md`). El ATR(14) es el de `app/indicators/_pine.py`; tras el calentamiento coincide
con el de `app/indicators/engine.py` a precisión de máquina.

### 2.1 `sfp_reversal_5_1` — aprobado con cambios

- **Indicador:** SFP del Heatmap (`sfp_signals`), pivote 5 izquierda / 1 derecha, `max_age = 500`.
- **Entrada:** CORTO en `sfp_bear_signal`; LARGO en `sfp_bull_signal`. Si una vela confirmara ambos, no hay señal.
- **SL:** extremo de la vela de barrida (la mecha) **± 0.1 · ATR(14)** de la vela de señal: CORTO en
  `mecha + 0.1 · ATR`, LARGO en `mecha − 0.1 · ATR`.
- **TP:** 2R sobre esa distancia: `entrada ∓ 2 · |entrada − SL|`.
- **Omisión:** si el `open` de la vela de entrada ya pasó el SL, la entrada **se omite** (no se fuerza otro SL). Lo
  hace el motor con el atributo `skip_entry_if_sl_crossed`; esas omisiones se cuentan en el log de la corrida y **no**
  van a `backtest_skipped_entries` (esa tabla es de omisiones por el tope de riesgo). Aprobado así por el dueño
  (2026-11-08); el informe las reporta igual (sección 6).
- **Trailing:** ninguno.

### 2.2 `camarilla_s3_r3` — aprobado tal cual

- **Indicador:** niveles Camarilla del día UTC anterior (`camarilla_levels`, con `require_complete`).
- **Entrada:** LARGO si la vela toca S3 y cierra por encima (`low ≤ S3 < close`); CORTO si toca R3 y cierra por debajo
  (`high ≥ R3 > close`). Si una misma vela cumple ambas, no hay señal. Como máximo **una entrada por lado y por día
  UTC**: da señal solo la **primera** vela del día que cumple la condición de ese lado; si el motor la ignora (posición
  abierta) o la omite (tope de riesgo), no hay otra ese día (aprobado así por el dueño el 2026-11-08). Sin niveles
  (día anterior faltante o incompleto), no hay señal.
- **SL:** el de la tabla del original: LARGO en `S4 · 0.99`; CORTO en `R4 · 1.01`.
- **TP:** el «TP 1» de la tabla: LARGO en R3; CORTO en S3.
- **Trailing:** ninguno. Los niveles quedan fijados con los del día de la señal aunque la posición pase la medianoche.
- **Sin DCA:** la tabla original propone promediar en S4; el motor no promedia y aquí no se hace.

### 2.3 `range_filter_flip_ema144` — aprobado tal cual

- **Indicadores:** Range Filter de Frost (`range_filter`, rango rápido 27/1.5, lento 55/3.5, modo «Intraday») y EMA(144)
  del cierre, el filtro de tendencia de la columna «TREND» del original.
- **Entrada:** LARGO en `rf_buy` con `close > EMA(144)`; CORTO en `rf_sell` con `close < EMA(144)` (un cierre igual a la
  EMA no cuenta).
- **SL:** `2.5 · ATR(14)` desde la entrada (la regla de `trend_atr_stop_9_21_50`).
- **Trailing:** `2.5 · ATR(14)`.
- **TP:** ninguno propio: se aplica el TP de respaldo del motor (`BACKTEST_FALLBACK_TP_PCT = 10 %`), igual que en
  `trend_atr_stop_9_21_50`.

### 2.4 Control: `control_sfp_random_dir_seed42` — aprobado

- **Para qué sirve:** separar el valor de la **dirección** del SFP del valor de su momento y de su gestión de riesgo.
- **Entrada:** en las **mismas velas** en que `sfp_reversal_5_1` tiene señal, con la dirección sorteada 50/50 de forma
  determinista.
- **Sorteo (aprobado por el dueño el 2026-11-08):** la dirección de cada vela de señal sale de un bit del
  **SHA-256 de `(42, open_time, close)`** de esa vela. Reemplaza la «semilla derivada de `(42, símbolo, marco)`, en
  orden cronológico» del borrador, porque la interfaz de las estrategias no recibe el símbolo ni el marco. Es
  reproducible, no depende del orden en que se recorran las series y dos símbolos a la misma hora sortean por
  separado.
- **SL y TP:** misma distancia que el SFP (`|entrada − (mecha ± 0.1 · ATR(14))|`) puesta del lado que corresponde a la
  dirección sorteada; TP 2R. Misma regla de omisión: se omite cuando el SFP natural se omitiría.
- **Papel:** **nunca se aprueba.** Si el control **pasa** todos los criterios de descarte, la ronda completa queda
  marcada como sospechosa (sesgo del motor o de los datos) y ningún candidato se da por aprobado hasta explicarlo.

## 3. Criterios de descarte (idénticos a la Fase 2, sin relajar ninguno, más uno)

Se aplican tal cual los de [`FASE2_CRITERIOS.md`](../historial/FASE2_CRITERIOS.md), sobre el OOS agregado de cada
combinación (candidato × marco):

| Criterio | Umbral |
|---|---|
| Profit factor OOS agregado | `≥ 1.2` |
| % de símbolos con PF > 1 individual | `≥ 50 %` |
| % de folds walk-forward con resultado neto positivo | `≥ 50 %` |
| PF tras duplicar fees **y** slippage | `> 1.0` |
| Drawdown máximo OOS | `≤ 50 %` |
| Concentración (1 operación o 1 símbolo) | `≤ 40 %` del PnL neto total |
| Operaciones totales (IS + OOS) | `≥ 100`; si no, `evidencia_insuficiente` |
| Mínimo por celda (estrategia, símbolo, fold) para contar en el % de folds | `≥ 30` operaciones |

**Criterio adicional (solo endurece):** `sfp_reversal_5_1` se aprueba en un marco **solo si**, además de pasar todos los
criterios de la tabla, su **PF OOS agregado supera el PF OOS agregado del control en el mismo marco**. La regla de
«ronda sospechosa» del control (2.4) se mantiene.

Y el resto de las reglas de la Fase 2 sin cambios: tope de riesgo por operación `MAX_SL_MARGIN_LOSS_PCT = 50 %` (a 10x,
un SL a más de 5 % omite la entrada y queda registrada); capital de referencia 100 USDT, margen fijo 10 USDT, 10x, sin
compounding; OOS = el 30 % más reciente, un solo periodo contiguo; folds de 6 meses con paso de 2 (solapados,
diagnósticos); grupo de control de supervivencia BTCUSDT/ETHUSDT; prevalece `pf_real_funding_only` si discrepa del PF
con funding aproximado; simulación de cartera Monte Carlo solo informativa; liquidación con `MARK_PRICE` y SL/TP con
`LAST_PRICE`; ejecución al `open` si hay gap.

## 4. Universo, periodo y datos reservados

- **Universo:** el de la Fase 2: universo dinámico de 10 símbolos más el grupo de control BTCUSDT/ETHUSDT.
- **Periodo:** desde el piso real del historial (~2022-04) hasta la fecha final fija **`BACKTEST_OFFICIAL_END_DATE =
  2026-10-01`**, el mismo de la Fase 2, para que el resultado sea comparable con el veredicto de la v1.
- **Datos reservados:** las velas y el funding **posteriores al 2026-10-01 quedan reservados y NO se usan en este
  backtest**: son para una confirmación futura, fuera de muestra respecto de toda esta ronda. Ningún resultado de
  rendimiento se calcula sobre ellos antes de esa confirmación. (El script de comparación con TradingView de la
  sección 5 imprime niveles y señales de noviembre de 2026 solo para verificar que los indicadores calculan igual que
  el gráfico; no calcula operaciones ni resultados y nada de lo que imprime entra al backtest.)
- La v2 descarga su propio historial: **nunca** se lee `data/` de la v1.

## 5. Antes de congelar y de correr

1. ~~Aprobación del dueño de los SL/TP y del control~~ — **hecho** (2026-11-08, con los cambios de arriba).
2. ~~Implementar los cuatro candidatos como archivos nuevos~~ — **hecho** en `app/candidates/`, sin registrar.
3. ~~Cambios del motor (omitir entrada; `open_time`)~~ — **hecho**, con una **prueba de regresión** que demuestra que
   las 6 estrategias de la v1 producen exactamente las mismas operaciones y omisiones antes y después
   (`tests/unit/test_backtest_v1_regression.py`, contra una referencia generada con el motor anterior al cambio).
4. ~~Pruebas de cada candidato~~ — **hecho**: causalidad (serie truncada == completa; velas futuras extremas no cambian
   las señales), SL/TP reproducidos a mano y una corrida de punta a punta en el motor real con velas sintéticas
   (`tests/unit/test_strategies_v2.py`, `tests/unit/test_backtest_engine_v2.py`).
5. **Comparación con TradingView — pendiente del dueño.** `python scripts/v2_tradingview_check.py` imprime, para
   BTCUSDT y ETHUSDT, los niveles Camarilla R3/R4/S3/S4 de 2026-11-05, 2026-11-06 y 2026-11-07 y las últimas 10 señales
   SFP en 1h con fecha y hora UTC. **No se congela hasta que el dueño confirme la comparación.**
   **Hecha por Claude el 2026-11-09 (falta la confirmación del dueño):** contra el gráfico de TradingView del dueño
   (feed de Bitunix, indicadores originales PunkAlgo HeatMap y Frost), leyendo las velas y las salidas que la página
   ya tenía cargadas. Resultado: velas idénticas en 1h, 4h, 1D y 1S (salvo diferencias de centavos y un hueco de
   TradingView en ETHUSDT, 2025-11-27 12:00 a 2025-11-28 20:00); giros del Range Filter idénticos mes a mes en todo el
   historial que carga TradingView (1h desde 2026-01, 4h desde 2024-01, 1D y 1S desde 2022-04), con una sola
   diferencia (ETHUSDT 1D, 2025-12-18 y 2026-01-06) que desaparece al quitar del cálculo el día que le falta a
   TradingView; señales SFP idénticas en hora, dirección y precio en las últimas ~26 de cada gráfico (TradingView
   solo conserva 50 etiquetas) y en todo el historial semanal y diario visible; Camarilla idéntica (las velas diarias
   coinciden). Detalle en `docs/historial/PROGRESS.md` (entrada del 2026-11-09).
6. Conectar los candidatos a `scripts/run_backtest.py` (hoy solo lee `STRATEGIES`) — paso posterior, con el documento
   congelado; se anota en `docs/historial/PROGRESS.md`.
7. Congelar este documento en un commit propio, sin la marca de borrador, **antes** de la primera corrida.

## 6. Advertencias que se publican junto al resultado

- **Comparaciones múltiples:** 3 candidatos × 2 marcos = 6 combinaciones evaluadas (más 2 del control). Con varias
  pruebas, la probabilidad de que alguna pase por azar es mayor que con una sola; los umbrales **no** se ajustan por
  eso (están congelados), pero el informe dirá cuántas combinaciones se probaron.
- **Entradas omitidas:** el informe reporta, **por candidato y por marco** (control incluido), cuántas entradas se
  omitieron por cada motivo: **tope de riesgo** (`MAX_SL_MARGIN_LOSS_PCT`, tabla `backtest_skipped_entries`) y **SL
  cruzado** (`skip_entry_if_sl_crossed`, log de la corrida), junto al número de operaciones abiertas.
- Ninguna de estas estrategias existe en la v1: su resultado no es comparable con la medición ciega de la v1 ni la
  cambia.

## 7. Registro de decisiones del dueño

| Fecha | Decisión |
|---|---|
| 2026-11-08 | `sfp_reversal_5_1` y control: SL = mecha ± 0.1·ATR(14); TP 2R; se mantiene la omisión si el `open` pasó el SL |
| 2026-11-08 | `camarilla_s3_r3` y `range_filter_flip_ema144`: aprobados tal cual |
| 2026-11-08 | Control aprobado; criterio adicional: el SFP solo se aprueba si su PF OOS supera el del control en el mismo marco; se mantiene la «ronda sospechosa» |
| 2026-11-08 | Universo y periodo de la Fase 2, fecha final 2026-10-01; los datos posteriores quedan reservados |
| 2026-11-08 | Requisitos: prueba de regresión de la v1 para los cambios del motor; script de comparación con TradingView y confirmación del dueño antes de congelar |

| 2026-11-08 | Sorteo del control con SHA-256 de `(42, open_time, close)` aprobado; omisiones por SL cruzado en el log y Camarilla solo en la primera vela del día de cada lado, aprobados |
| 2026-11-08 | El informe reporta, por candidato y marco, las entradas omitidas por cada motivo (tope de riesgo y SL cruzado) |

**Pendiente del dueño:** confirmar la comparación con TradingView. No se congela ni se corre nada antes.
