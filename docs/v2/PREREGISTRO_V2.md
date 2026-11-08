# Minerva v2 — Preregistro de candidatos (BORRADOR)

> **BORRADOR — NO EJECUTAR.** Este documento propone qué se probaría y con qué reglas. **No se corrió ningún
> backtest** y no se implementó ninguna estrategia: los indicadores existen como funciones puras
> (`docs/v2/ESPECIFICACION_INDICADORES.md`), sin conectar al registro ni al motor. Los niveles de SL/TP de cada
> candidato están **pendientes de aprobación del dueño del proyecto**. Una vez aprobado, este documento se congela
> en un commit **antes** de cualquier corrida, igual que `docs/historial/FASE2_CRITERIOS.md` en la v1.

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
señal (punto 6 de `FASE2_CRITERIOS.md`).

### 2.1 `sfp_reversal_5_1`

- **Indicador:** SFP del Heatmap (`sfp_signals`), pivote 5 izquierda / 1 derecha, `max_age = 500`.
- **Entrada:** CORTO en `sfp_bear_signal`; LARGO en `sfp_bull_signal`.
- **SL propuesto:** el extremo de la vela de barrida (`sfp_*_sweep_extreme`): la mecha que hizo la barrida. Si el
  `open` de la vela de entrada ya está más allá de ese nivel, la entrada **se omite** (no se fuerza otro SL).
- **TP propuesto:** 2R: `entrada ∓ 2 · |entrada − SL|`.
- **Trailing:** ninguno.
- **Pendiente técnico (no cambia la regla):** hoy `stop_price` no puede pedir que se omita una entrada; devolver
  `None` haría caer en el SL de respaldo del 5 %. Hay que resolverlo antes de correr.

### 2.2 `camarilla_s3_r3`

- **Indicador:** niveles Camarilla del día UTC anterior (`camarilla_levels`, con `require_complete`).
- **Entrada:** LARGO si la vela toca S3 y cierra por encima (`low ≤ S3 < close`); CORTO si toca R3 y cierra por debajo
  (`high ≥ R3 > close`). Si una misma vela cumple ambas, no hay señal. Como máximo **una entrada por lado y por día
  UTC**. Sin niveles (día anterior faltante o incompleto), no hay señal.
- **SL propuesto:** el de la tabla del original: LARGO en `S4 · 0.99`; CORTO en `R4 · 1.01`.
- **TP propuesto:** el «TP 1» de la tabla: LARGO en R3; CORTO en S3.
- **Trailing:** ninguno. Los niveles quedan fijados con los del día de la señal aunque la posición pase la medianoche.
- **Sin DCA:** la tabla original propone promediar en S4; el motor no promedia y aquí no se hace.
- **Pendiente técnico:** el DataFrame del motor no trae `open_time`; hay que pasarlo para calcular los días UTC.

### 2.3 `range_filter_flip_ema144`

- **Indicadores:** Range Filter de Frost (`range_filter`, rango rápido 27/1.5, lento 55/3.5, modo «Intraday») y EMA(144)
  del cierre, el filtro de tendencia de la columna «TREND» del original.
- **Entrada:** LARGO en `rf_buy` con `close > EMA(144)`; CORTO en `rf_sell` con `close < EMA(144)`.
- **SL propuesto:** `2.5 · ATR(14)` desde la entrada (el mismo de `trend_atr_stop_9_21_50`, para comparar).
- **Trailing propuesto:** `2.5 · ATR(14)`.
- **TP propuesto:** ninguno propio: se aplica el TP de respaldo del motor (`BACKTEST_FALLBACK_TP_PCT = 10 %`), igual que
  en `trend_atr_stop_9_21_50`.

### 2.4 Control: `control_sfp_random_dir_seed42`

- **Para qué sirve:** separar el valor de la **dirección** del SFP del valor de su momento y de su gestión de riesgo.
- **Entrada:** en las **mismas velas** en que `sfp_reversal_5_1` tiene señal (de cualquier lado), con la dirección
  elegida al azar (50/50) por un generador con semilla fija derivada de `(42, símbolo, marco)`, en orden cronológico,
  para que el resultado no dependa del orden en que se recorran las series.
- **SL y TP:** misma distancia que el SFP (`|entrada − extremo de la barrida|`) puesta del lado que corresponde a la
  dirección sorteada; TP 2R. Misma regla de omisión.
- **Papel:** **nunca se aprueba.** Si el control **pasa** todos los criterios de descarte, la ronda completa queda
  marcada como sospechosa (sesgo del motor o de los datos) y ningún candidato se da por aprobado hasta explicarlo.

## 3. Criterios de descarte (idénticos a la Fase 2, sin relajar ninguno)

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

Y el resto de las reglas de la Fase 2 sin cambios: tope de riesgo por operación `MAX_SL_MARGIN_LOSS_PCT = 50 %` (a 10x,
un SL a más de 5 % omite la entrada y queda registrada); capital de referencia 100 USDT, margen fijo 10 USDT, 10x, sin
compounding; OOS = el 30 % más reciente, un solo periodo contiguo; folds de 6 meses con paso de 2 (solapados,
diagnósticos); grupo de control de supervivencia BTCUSDT/ETHUSDT; prevalece `pf_real_funding_only` si discrepa del PF
con funding aproximado; fecha final fija; simulación de cartera Monte Carlo solo informativa; liquidación con
`MARK_PRICE` y SL/TP con `LAST_PRICE`; ejecución al `open` si hay gap.

**Universo y periodo propuestos:** los de la Fase 2 (universo dinámico de 10 símbolos más el control BTC/ETH; desde el
piso real del historial, ~2022-04, hasta `BACKTEST_OFFICIAL_END_DATE = 2026-10-01`), para que el resultado sea
comparable con el veredicto de la v1. La v2 descarga su propio historial: **nunca** se lee `data/` de la v1.

## 4. Advertencias que se publican junto al resultado

- **Comparaciones múltiples:** 3 candidatos × 2 marcos = 6 combinaciones evaluadas (más 2 del control). Con varias
  pruebas, la probabilidad de que alguna pase por azar es mayor que con una sola; los umbrales **no** se ajustan por
  eso (están congelados), pero el informe dirá cuántas combinaciones se probaron.
- Los indicadores no se compararon vela a vela con TradingView (ver la sección «No verificado» de la especificación).
- Ninguna de estas estrategias existe en la v1: su resultado no es comparable con la medición ciega de la v1 ni la
  cambia.

## 5. Antes de correr (requisitos, no ejecutados)

1. Aprobación explícita del dueño de los SL/TP y del control (sección 6).
2. Implementar los cuatro candidatos como archivos nuevos y resolver los dos pendientes técnicos (omitir entrada en
   el SFP; `open_time` en el motor). Cualquier cambio del motor se anota en `docs/historial/PROGRESS.md` como cambio de
   comportamiento respecto de la v1.0.
3. Pruebas de causalidad de cada estrategia (serie truncada == completa) y una prueba que reproduzca a mano una
   operación de cada una.
4. Congelar este documento en un commit propio, ya sin la marca de borrador, **antes** de la primera corrida.

## 6. Decisiones pendientes del dueño

- [ ] SL/TP de `sfp_reversal_5_1` (mecha de la barrida; 2R).
- [ ] SL/TP de `camarilla_s3_r3` (`S4 · 0.99` / `R4 · 1.01`; TP en R3 / S3) y la regla «una entrada por lado y día».
- [ ] SL, trailing y TP de respaldo de `range_filter_flip_ema144` (2.5·ATR(14); 10 %).
- [ ] Diseño del control (dirección al azar sobre los momentos del SFP) y su regla de «ronda sospechosa».
- [ ] Universo, periodo y fecha final (propuesta: los de la Fase 2).
