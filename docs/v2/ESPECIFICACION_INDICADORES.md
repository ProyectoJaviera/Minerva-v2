# Minerva v2 — Especificación de indicadores (Fase 0)

> **Estado:** Fase 0 de la v2: solo investigación, especificación e implementación de funciones puras. **Nada de esto
> está conectado** a estrategias, al registro (`STRATEGIES`), al scheduler, al LLM ni a la configuración.
>
> **Origen:** inspirado en indicadores públicos de TradingView (autoría y licencia por verificar): un indicador de
> «Heatmap» de liquidez con detector de SFP y un indicador de señales con Range Filter, banda VIDYA, niveles Camarilla,
> BB%B y WaveTrend. Los archivos de referencia viven **fuera** del repositorio y no se copian ni se versionan. Este
> documento describe el comportamiento con fórmulas y prosa propias; no reproduce el código original.
>
> **Implementación:** `app/indicators/structure.py` (A, B), `app/indicators/trend_filters.py` (C, D),
> `app/indicators/levels.py` (E), `app/indicators/oscillators.py` (F) y las primitivas de `app/indicators/_pine.py`.
> Pruebas: `tests/unit/test_indicators_v2_*.py`.

## Índice

- [0. Convenciones comunes](#0-convenciones-comunes)
- [A. SFP del Heatmap](#a-sfp-del-heatmap)
- [B. Zonas de liquidez (definición determinista propia)](#b-zonas-de-liquidez-definición-determinista-propia)
- [C. Range Filter](#c-range-filter)
- [D. Banda VIDYA ± ATR(200)·1.6](#d-banda-vidya--atr20016)
- [E. Niveles Camarilla del día UTC anterior](#e-niveles-camarilla-del-día-utc-anterior)
- [F. BB%B y WaveTrend](#f-bbb-y-wavetrend)
- [G. Hallazgos del código original](#g-hallazgos-del-código-original)
- [H. Diferencias deliberadas respecto del original](#h-diferencias-deliberadas-respecto-del-original)
- [I. No verificado](#i-no-verificado)

## 0. Convenciones comunes

- **Velas:** DataFrame en orden cronológico ascendente con `open`, `high`, `low`, `close`; `volume` es opcional y
  `open_time` (milisegundos UTC de apertura) solo lo exige Camarilla. Las posiciones `0..n−1` son el orden de las filas,
  no las etiquetas del índice.
- **Causalidad:** el valor informado en la vela `i` usa solo las velas `0..i`, y una señal en la vela `i` se conoce al
  **cierre** de `i` (en el motor de backtest se llenaría en el `open` de `i + 1`). Cada función tiene dos pruebas de
  causalidad: serie truncada == serie completa y velas futuras extremas que no cambian nada.
- **Primitivas** (`_pine.py`):
  - `SMA(x, n)`: media de las últimas `n` velas; indefinida si falta un valor de la ventana.
  - `STDEV(x, n)`: desvío **poblacional** de las últimas `n` velas.
  - `EMA(x, n)`: `alpha = 2 / (n + 1)`; `RMA(x, n)`: `alpha = 1 / n`. Ambas arrancan con la media simple de los
    primeros `n` valores válidos consecutivos y luego `m_t = alpha · x_t + (1 − alpha) · m_{t−1}`. Una entrada
    indefinida tras el arranque da salida indefinida y conserva el estado.
  - `TR_t = max(high_t − low_t, |high_t − close_{t−1}|, |low_t − close_{t−1}|)`; en la primera vela, `high − low`.
    `ATR(n) = RMA(TR, n)`.
  - `cruce_arriba(a, b)` en `t`: `a_t > b_t` y `a_{t−1} ≤ b_{t−1}`; `cruce_abajo`: `a_t < b_t` y `a_{t−1} ≥ b_{t−1}`.
    Falso si falta cualquiera de los cuatro valores.
- **Calentamiento:** los indicadores recursivos (Range Filter, VIDYA, ATR(200)) dependen de su arranque durante
  cientos de velas. Regla para cualquier uso futuro: calcularlos **una sola vez sobre la serie completa** (como hace
  `precompute`) y **no emitir señales en las primeras 500 velas** de cada serie. Calcularlos sobre la ventana de 300
  velas que el motor pasa a `evaluate` daría valores distintos.

## A. SFP del Heatmap

Swing Failure Pattern: el precio barre un pivote con la mecha, cierra de vuelta del lado original y luego confirma
cerrando más allá del extremo opuesto del tramo.

**Parámetros (los del original):** pivote `L = 5` velas a la izquierda y `R = 1` a la derecha; vida máxima del setup
`max_age = 500` velas desde el pivote. La validación por volumen de marcos inferiores del original está **apagada** por
defecto y no se implementa.

**Pivote máximo** con `L`/`R`: la vela `p` es pivote si `high_p` es **estrictamente** mayor que el `high` de las `L`
velas anteriores y de las `R` siguientes. Se conoce en la vela `c = p + R` (confirmación). El pivote mínimo es el espejo
con `low`. Un empate no es pivote (el manejo de empates del original no está verificado).

**Estado por lado** (se describe el bajista; el alcista es el espejo exacto):

- *Pivote vigente* `(sw, p_sw)`: el último pivote máximo confirmado. **No se consume** al ser barrido ni al invalidarse
  un setup: sigue vigente hasta que se confirme otro pivote máximo.
- *Setup vigente*: `(pivote, índice del pivote, extremo opuesto, índice de la barrida, extremo de la barrida, activo,
  confirmado)`. Lo crea cada barrida y lo **reemplaza** la siguiente.

**Orden de evaluación en cada vela `t`** (el orden importa y es el del original):

1. **Actualizar el pivote vigente:** si en `t` se confirma un pivote máximo, `sw = high_{t−R}`, `p_sw = t − R`.
2. **Barrida:** si hay pivote vigente y `high_t > sw`, `open_t < sw` y `close_t < sw`:
   - *Extremo opuesto* `opp = min(sw, min(low_k) para p_sw < k < t)` (las velas estrictamente entre el pivote y la
     barrida; si no hay ninguna, `opp = sw`).
   - Se crea un setup nuevo, activo y sin confirmar, con `extremo de la barrida = high_t`. Se marca `sweep` en `t`.
3. **Confirmación:** si el setup está activo y sin confirmar y `close_t < opp` (estricto), se confirma: **señal** en
   `t`. Puede ocurrir en la misma vela de la barrida.
4. **Expiración / invalidación:** si `t − p_setup > max_age` o `close_t > pivote del setup`, el setup deja de estar
   activo. Se evalúa **después** de la confirmación: una vela que confirma y a la vez cumple la expiración por edad sí
   da señal.

**Alcista:** pivote mínimo; barrida `low_t < sw`, `open_t > sw`, `close_t > sw`; `opp = max(sw, max(high_k))`;
confirmación `close_t > opp`; invalidación `close_t < pivote del setup`; extremo de la barrida `low_t`.

**Consecuencias (fieles al original):** como el pivote no se consume, un mismo pivote puede barrerse varias veces y dar
más de una señal; y tras una invalidación (cierre por encima del pivote) una vuelta posterior del precio puede barrerlo
de nuevo desde arriba.

**Salidas** (`sfp_signals`): por lado (`bear`, `bull`), `sfp_<lado>_sweep` (vela de barrida), `sfp_<lado>_signal`
(vela de confirmación) y, **solo en las velas de señal**, `_swing` (precio del pivote), `_opposite`, `_sweep_extreme`
y `_bars_since_sweep`.

**Ejemplo** (bajista, de las pruebas): pivote máximo 20 en la vela 5, confirmado en la 6; mínimos de las velas 6–8:
13, 12.5 y 14 → `opp = 12.5`. La vela 9 (`open` 19, `high` 21, `close` 19.5) barre. La vela 11 cierra en 12.4 < 12.5 →
señal en la vela 11, con mecha de barrida en 21. Un cierre de exactamente 12.5 no confirma.

## B. Zonas de liquidez (definición determinista propia)

El original dibuja cajas por encima de cada máximo de pivote y por debajo de cada mínimo, coloreadas por volumen, y las
borra cuando una vela atraviesa su punto medio. Su implementación no es determinista ni causal (ver
[hallazgos](#g-hallazgos-del-código-original)), así que aquí se fija una **definición propia** que conserva la idea:

**Parámetros:** pivote `L = 2`, `R = 2`; ancho `w = k · ATR(200)` con `k` según el marco (regla del original:
0.2 para 60 minutos o más y para diario, 0.25 por debajo de 60 minutos, 0.4 en semanal y mensual → **0.2 en 1h y 4h**;
`heatmap_atr_multiplier`); ventana de volumen 500 velas.

**Emisión** — una sola zona por pivote, **en su vela de confirmación** `c = p + 2`, nunca antes ni de forma
retroactiva:

- Sobre un máximo de pivote `p`: `bottom = high_p`, `top = high_p + w`.
- Bajo un mínimo de pivote `p`: `top = low_p`, `bottom = low_p − w`.
- `w` usa el ATR(200) de la vela del pivote `p` (anterior a la emisión, así que es causal). Si ese ATR todavía no
  existe (primeras 199 velas), **no hay zona**.
- `mid = (top + bottom) / 2`.

**Mitigación:** la zona se mitiga en la **primera vela `t > c`** con `high_t > mid` y `low_t < mid` (ambas estrictas).
Una vez mitigada no vuelve. La vela que mitiga ya la ve mitigada (`active_zones_at`). Con pivotes estrictos la vela de
emisión nunca podría mitigar su propia zona, pero la búsqueda empieza igualmente en `c + 1`. No hay expiración por edad.

**Volumen (informativo):** `volume_ratio = vol_p / media(vol de las últimas 500 velas hasta c)`; si no hay columna
`volume`, se usa `high − low` como sustituto (el original usa el tamaño de la vela cuando el volumen acumulado es ≤ 1).
No participa en la emisión ni en la mitigación.

**Salidas** (`liquidity_zones`): una fila por zona con `side` (`high`/`low`), `pivot_index`, `emit_index`, `price`,
`top`, `bottom`, `mid`, `width`, `volume_ratio`, `mitigated_index` (`<NA>` si sigue activa), ordenadas por emisión y
lado.

## C. Range Filter

**Parámetros:** fuente `close`; rango rápido `(t₁, m₁) = (27, 1.5)`; rango lento `(t₂, m₂) = (55, s)` con la
«sensibilidad» `s` del modo: 1.3 (Scalping), **3.5 (Intraday, por defecto)**, 4.2 (Swing).

**Orden de cálculo:**

1. `rango_suave(t, m) = EMA(EMA(|close_t − close_{t−1}|, t), 2t − 1) · m`.
2. `r_t = (rango_suave(27, 1.5) + rango_suave(55, s)) / 2`. Primer valor definido en la vela 163.
3. **Filtro** `f_t` (recursivo; `prev = f_{t−1}`, o **0** si no estaba definido — así arranca el original, por eso
   su primer valor es `close − r`):
   - si `close_t > prev`: `f_t = prev` si `close_t − r_t < prev`, si no `close_t − r_t`;
   - si no: `f_t = prev` si `close_t + r_t > prev`, si no `close_t + r_t`.
   - `f_t` indefinido mientras `r_t` lo esté.
4. **Contadores:** `up_t = up_{t−1} + 1` si `f_t > f_{t−1}`; 0 si `f_t < f_{t−1}`; si no, igual. `dn_t` es el espejo.
   Arrancan en 0.
5. **Condiciones:** `alcista_t = close_t > f_t ∧ up_t > 0 ∧ close_t ≠ close_{t−1}`;
   `bajista_t = close_t < f_t ∧ dn_t > 0 ∧ close_t ≠ close_{t−1}`. (El original lo escribe como dos disyunciones —
   cierre subiendo o bajando— que equivalen a «cierre distinto del anterior»; con cierre igual, ninguna se cumple).
   Son excluyentes: `up` y `dn` no pueden ser positivos a la vez.
6. **Última condición** `u_t = 1` si alcista, `−1` si bajista, si no `u_{t−1}` (arranca en 0).
7. **Señales (giros):** compra en `t` si `alcista_t ∧ u_{t−1} = −1`; venta si `bajista_t ∧ u_{t−1} = 1`. La primera
   condición de la serie nunca es señal (necesita una previa de sentido contrario).
8. **Estado** `rf_state`: 1 tras la última compra, −1 tras la última venta, 0 antes de la primera.

**Salidas** (`range_filter`): `rf_range`, `rf_filter`, `rf_upward`, `rf_downward`, `rf_bull_cond`, `rf_bear_cond`,
`rf_buy`, `rf_sell`, `rf_state`.

## D. Banda VIDYA ± ATR(200)·1.6

**Parámetros:** VIDYA `length = 10`, ventana del CMO `momentum = 20`, SMA final 15; ATR(200); distancia **1.6** (opción
«High», la del original por defecto; 0.61 en «Normal»).

**Orden de cálculo:**

1. `Δ_t = close_t − close_{t−1}`; `S⁺_t = Σ max(Δ, 0)` y `S⁻_t = Σ max(−Δ, 0)` sobre las últimas 20 velas (definidas
   desde la vela 20).
2. `CMO_t = |100 · (S⁺ − S⁻) / (S⁺ + S⁻)|`. Si `S⁺ + S⁻ = 0` (20 velas sin movimiento), `CMO = 0`
   ([diferencia deliberada](#h-diferencias-deliberadas-respecto-del-original)).
3. `k_t = (2 / (length + 1)) · CMO_t / 100`; `v_t = k_t · close_t + (1 − k_t) · v_{t−1}`, con `v_{t−1} = 0` al
   arrancar (como el original: converge al precio muy despacio, por eso el calentamiento de 500 velas).
4. `VIDYA_t = SMA(v, 15)`.
5. `superior = VIDYA + 1.6 · ATR(200)`, `inferior = VIDYA − 1.6 · ATR(200)`.
6. **Tendencia** (arranca **bajista**): pasa a alcista con `cruce_arriba(close, superior)` y a bajista con
   `cruce_abajo(close, inferior)` (se evalúa primero el cruce al alza).
7. **Trailing:** la banda inferior en tendencia alcista y la superior en bajista; **indefinido en la vela del cambio**.

**Salidas** (`vidya_band`): `vidya`, `vidya_upper`, `vidya_lower`, `vidya_trend_up`, `vidya_trail`, `vidya_flip_up`,
`vidya_flip_down`.

## E. Niveles Camarilla del día UTC anterior

**Fórmula**, con `H`, `L`, `C` = máximo, mínimo y cierre del **día UTC anterior** completo y `rango = (H − L) · 1.1`:

| Nivel | Valor | Nivel | Valor |
|---|---|---|---|
| R4 | `C + rango / 2` | S1 | `C − rango / 12` |
| R3 | `C + rango / 4` | S2 | `C − rango / 6` |
| R2 | `C + rango / 6` | S3 | `C − rango / 4` |
| R1 | `C + rango / 12` | S4 | `C − rango / 2` |

**Orden de cálculo** (`camarilla_levels`):

1. Día UTC de cada vela: `floor(open_time / 86 400 000)` (el límite es la medianoche UTC; la vela de las 23:00
   pertenece a su día).
2. Agregado diario desde las propias velas: `H = máx(high)`, `L = mín(low)`, `C = close de la última vela del día`.
3. Cada vela del día `D` recibe los niveles de `D − 1`. Es causal: todas las velas de `D − 1` cierran antes de que
   empiece `D`.
4. Si `D − 1` no está en la serie, no hay niveles. Con `require_complete` (por defecto), tampoco si `D − 1` tiene menos
   velas que `86 400 000 / duración` o algún cierre indefinido.
5. Validación: `open_time` estrictamente creciente y una duración de vela que divida un día (1h y 4h sí; 7h no).

El original toma `high[1]`, `low[1]`, `close[1]` de la serie diaria con `lookahead` activado: es la forma correcta,
sin repintado, de leer el día anterior. La sesión diaria de TradingView para el mercado de referencia se supone a
medianoche UTC (**por verificar**; los pares perpetuos de criptomonedas suelen cerrar el día a las 00:00 UTC).

**La tabla y la caja del original** (solo como referencia; no forman parte de la función):

| Celda de la tabla | Nivel |
|---|---|
| Entry | S3 |
| DCA | S4 |
| TP 1 | R3 |
| TP 2 | R4 |
| SL | S4 · 0.99 |

La «caja» opcional para cortos usa, en espejo, R3 como entrada y `R4 · 1.01` como SL.

## F. BB%B y WaveTrend

**BB%B** (`bb_percent_b`): `media = SMA(close, 20)`, `desvío = 2 · STDEV(close, 20)`,
`%B = (close − (media − desvío)) / (2 · desvío)` (indefinido si el desvío es 0). Velas de reversión del original:
*salida de sobreventa* = `cruce_arriba(%B, −0.1)`; *salida de sobrecompra* = `cruce_abajo(%B, 1.1)`. Salidas
`bb_pct_b`, `bb_exit_oversold`, `bb_exit_overbought`.

**WaveTrend** (`wavetrend`), sobre `hlc3 = (high + low + close) / 3`:

1. `esa = EMA(hlc3, 9)`
2. `d = EMA(|hlc3 − esa|, 9)`
3. `ci = (hlc3 − esa) / (0.015 · d)` (indefinido si `d = 0`)
4. `wt1 = EMA(ci, 12)`
5. `wt2 = SMA(wt1, 3)`

Cruces de la «Reversal RSI» del original: alcista = `cruce_arriba(wt1, wt2) ∧ wt2 ≤ −72`; bajista =
`cruce_abajo(wt1, wt2) ∧ wt2 ≥ 72`. Las alertas del original usan ±53 (parámetro `extreme`). Salidas `wt1`, `wt2`,
`wt_bull_cross`, `wt_bear_cross`.

## G. Hallazgos del código original

Revisión crítica de los dos indicadores de referencia. Ninguno de estos comportamientos se reproduce salvo donde se
dice.

**Heatmap — zonas de liquidez**

1. **Cajas retroactivas.** La caja de un pivote se dibuja con su borde izquierdo en la vela del pivote, pero recién
   existe dos velas después (cuando se confirma el pivote 2/2). En el gráfico histórico parece que la zona estaba ahí
   desde el pivote, así que cualquier lectura visual de «el precio respetó la zona» incluye dos velas en que la zona
   todavía no se conocía.
2. **Hasta tres cajas por pivote.** La condición de creación es «hay pivote ahora, o lo hubo hace una vela, o hace
   dos», así que se cumple en tres velas seguidas por cada pivote. Como las coordenadas de la caja son relativas a la
   vela actual (dos velas atrás), la segunda y la tercera caja **no** quedan sobre el pivote: se anclan en las dos
   velas siguientes, con *su* máximo (o mínimo) y *su* ATR. Resultado: por cada pivote, hasta tres cajas apiladas a
   alturas distintas, dos de ellas sin pivote debajo.
3. **Dependencia de `last_bar_index − bar_index < 500`.** Solo se crean y se mitigan zonas en las últimas 500 velas
   respecto de la última vela del gráfico. Lo que se ve depende de cuándo se cargó el gráfico (una recarga cambia el
   punto de partida) y en tiempo real las zonas nuevas se siguen agregando sin ese límite: el resultado histórico y el
   vivo no coinciden. No es reproducible en un backtest.
4. **Borrado de elementos mientras se itera.** El bucle que recorre las zonas activas quita del mismo arreglo las que
   se mitigan. Modificar un arreglo durante su recorrido puede saltarse el elemento siguiente (o, según la versión del
   lenguaje, fallar): que una zona se mitigue en una vela puede depender de si la anterior se mitigó en esa misma vela.
5. Además: el arreglo de zonas se inicializa con 500 elementos vacíos que nunca se quitan (se recorren en cada vela sin
   efecto) y el límite de 500 cajas del gráfico borra las más viejas sin sacarlas del arreglo.

**Heatmap — SFP**

6. El SFP en sí es causal (pivote 5/1 conocido en la vela siguiente, barrida y confirmación sobre velas cerradas) y se
   reproduce fielmente, incluidos dos efectos poco evidentes: el pivote no se consume (varias señales por pivote) y
   la confirmación se evalúa antes que la expiración en la misma vela.
7. La validación por volumen de marcos inferiores está apagada por defecto, pero la petición de datos de marcos
   inferiores se ejecuta igual en cada vela (costo sin efecto).

**Frost**

8. **El «Liquidity Grab» es un conteo acumulado no consecutivo (agotamiento, no barrida).** Cuenta las velas con
   `close > close[4]` (y, aparte, las de `close < close[4]`) sin exigir que sean seguidas; el contador solo vuelve a 0
   cuando dispara. Dispara el «Bearish Grab» si el conteo alcista supera 6, la vela es bajista y su máximo es el mayor
   de 30 velas (espejo para el alcista). Es una señal de **agotamiento** de tendencia; no detecta ninguna barrida de
   liquidez ni mira pivotes. Como los contadores nunca se reinician por la condición contraria, con el tiempo ambos
   superan 6 y la señal termina dependiendo solo del color de la vela y del extremo de 30 velas.
9. **Las alertas «Bullish Grab» / «Bearish Grab» no son el Grab dibujado:** están atadas a los cruces del BB%B (las
   «velas de reversión»), no al conteo anterior.
10. **La «Reversal RSI» es WaveTrend.** El interruptor y su descripción hablan de RSI, pero lo que dibuja son los
    cruces de WaveTrend en ±72. El RSI(21) se calcula (sobrecompra/sobreventa) y solo alimenta una variable de alerta
    que nunca se usa.
11. **La tabla Entry/DCA/TP/SL son niveles Camarilla fijos del día anterior** (S3, S4, R3, R4, S4·0.99): no dependen
    de la señal. La columna «SIGNAL» (▲/▼ según la última señal del Range Filter) aparece al lado, pero los niveles
    son siempre los de un largo, haya señal larga, corta o ninguna.
12. **`request.security` con `lookahead` sin desplazar en `securityNoRep1`.** Para marcos superiores pide la serie
    «cierre sobre la EMA 144» de la vela **en curso** del marco superior con `lookahead` activado: en el histórico eso
    lee el valor final de una vela que aún no cerró (fuga de futuro / repintado). **No tiene uso**: las diez variables
    que produce no se muestran ni alimentan nada. En cambio, los niveles Camarilla piden la vela **anterior** con
    `lookahead`, que es la forma correcta.
13. Otros: la banda VIDYA se **reinicia a 0** si en 20 velas no hubo ningún movimiento (división 0/0 → indefinido →
    0 en la vela siguiente); si el precio ya está fuera de la banda cuando esta aparece, no hay cruce y la tendencia
    queda «bajista» hasta el primer cruce real (se reproduce y tiene prueba); la línea de la «mediana» Camarilla se
    dibuja en R1; varias funciones y series se calculan sin usarse (niveles diarios `dHigh`/`dLow`/`dClose`, pivotes
    del módulo VIDYA, divergencias por fractales, puntos de giro, canal de Keltner, la extensión de «líneas de
    liquidez», que no hace nada); las etiquetas «AI» no corresponden a ningún modelo: son reglas fijas.

## H. Diferencias deliberadas respecto del original

| Indicador | Original | Aquí | Motivo |
|---|---|---|---|
| Zonas de liquidez | Caja retroactiva desde el pivote; hasta 3 por pivote; solo últimas 500 velas; mitigación con borrado durante el recorrido | Una zona por pivote, emitida en la confirmación; toda la serie; mitigación por zona, independiente | Determinismo y causalidad (sección B) |
| Zonas de liquidez | Caja con ATR indefinido en las primeras velas | Sin zona hasta que existe el ATR(200) | Evitar zonas de ancho indefinido |
| VIDYA | 20 velas planas → se reinicia a 0 | `CMO = 0`: la VIDYA se mantiene | Un reinicio a 0 es un artefacto numérico |
| Pivotes | Empates según Pine (no verificado) | Estrictos: un empate no es pivote | Definición explícita |
| Medias | Arranque interno de Pine | Media simple de los primeros `n` valores (sección 0) | Explícito; solo afecta al calentamiento |
| Camarilla | Vela diaria del proveedor | Agregado de las propias velas; sin niveles si el día anterior está incompleto | No inventar niveles con datos faltantes |
| SFP | Validación opcional por volumen de marcos inferiores | No implementada (apagada en el original) | Fuera de alcance |

Todo lo demás (parámetros, órdenes de evaluación, arranque en 0 del Range Filter y de la VIDYA, tendencia inicial
bajista, condiciones estrictas) sigue al original.

## I. No verificado

- Autoría y licencia de los indicadores de referencia.
- El arranque exacto de `ta.ema` en TradingView (se usó el de `ta.rma`, media simple de los primeros `n` valores) y
  el manejo de empates de `ta.pivothigh`/`ta.pivotlow`. Ambos solo cambian el calentamiento o casos de empate exacto.
- La hora de cierre de la sesión diaria que usa TradingView para el símbolo de referencia (se supone 00:00 UTC).
- Que las señales coincidan vela a vela con las del gráfico de TradingView: no hubo comparación contra el gráfico.
- Ningún indicador se probó con datos reales del mercado ni en un backtest (prohibido en la Fase 0).
