# Minerva v2 — Resultado de la Fase 2 (corrida única, 2026-11-10)

Corrida única de los candidatos del [preregistro congelado](PREREGISTRO_V2.md) (commit `95b44c2`), con
`scripts/run_backtest_v2.py` (commit `80828c8`) sobre una base temporal llenada con `scripts/download_history.py`.
Nada de este resultado cambia el preregistro.

- **Universo:** top-10 de CoinGecko del 2026-11-10: BTCUSDT, ETHUSDT, BNBUSDT, XRPUSDT, SOLUSDT, TRXUSDT, ZECUSDT,
  HYPEUSDT, XMRUSDT y DOGEUSDT; el grupo de control BTC/ETH ya está incluido.
- **Periodo:** desde el piso real del historial de Bitunix (~2022-04) hasta **2026-10-01**. Las velas posteriores
  están reservadas y no entraron. OOS = el 30 % más reciente.
- **Datos:** huecos irreparables del exchange en DOGEUSDT 1h (4 velas, 2023-07-07) y ZECUSDT 1h/1d (2023-09-12 a 14),
  tratados como en la Fase 2 de la v1.
- **Tiempo de la corrida:** 217 s.

## Veredicto

**Ninguna combinación sobrevive a los criterios. Los 3 candidatos quedan descartados en 1h y en 4h.** El control
tampoco pasó, así que la ronda **no** es sospechosa.

| Combinación | Operaciones (IS / OOS) | PF IS → PF OOS | PF estresado | % símbolos PF>1 | % folds + | DD OOS | Veredicto |
|---|---|---|---|---|---|---|---|
| `sfp_reversal_5_1` 1h | 1842 / 1786 | 0.73 → 0.93 | 0.80 | 30 % | 12.5 % | 126.7 % | DESCARTADO |
| `sfp_reversal_5_1` 4h | 435 / 381 | 0.83 → 0.98 | 0.88 | 50 % | 22.7 % | 67.0 % | DESCARTADO |
| `camarilla_s3_r3` 1h | 3287 / 3229 | 0.79 → 0.79 | 0.66 | 10 % | 4.0 % | 496.2 % | DESCARTADO |
| `camarilla_s3_r3` 4h | 2663 / 2697 | 0.77 → 0.75 | 0.62 | 0 % | 4.2 % | 417.4 % | DESCARTADO |
| `range_filter_flip_ema144` 1h | 2411 / 2309 | 0.83 → 0.92 | 0.74 | 50 % | 12.5 % | 126.9 % | DESCARTADO |
| `range_filter_flip_ema144` 4h | 335 / 331 | 1.28 → 1.06 | 0.91 | 44 % | 71.4 % | 32.2 % | DESCARTADO |
| control 1h | 1817 / 1755 | 0.87 → 0.87 | 0.75 | 10 % | 8.3 % | 147.5 % | control (no pasó) |
| control 4h | 415 / 380 | 0.87 → 0.96 | 0.86 | 30 % | 38.1 % | 48.0 % | control (no pasó) |

Motivos de descarte (criterios de la Fase 2, sin relajar):

- **`sfp_reversal_5_1`:** PF OOS < 1.2 en los dos marcos, folds positivos < 50 %, PF estresado ≤ 1 y drawdown OOS
  > 50 %; en 1h además PF > 1 en solo el 30 % de los símbolos. El criterio adicional contra el control no hace falta
  (ya está descartado), pero tampoco lo habría salvado: en 4h su PF OOS (0.975) apenas supera al del control (0.960),
  y en 1h (0.925) supera al control (0.869), pero los dos pierden.
- **`camarilla_s3_r3`:** el peor de la ronda. PF OOS de 0.75 a 0.79, casi ningún símbolo ni fold positivo.
- **`range_filter_flip_ema144`:** en 4h es el más cercano: PF OOS 1.06, 71 % de folds positivos, drawdown de 32 %.
  Pero no llega a 1.2, el PF estresado queda en 0.91 y la concentración llega al 102 % del PnL neto (unas pocas
  operaciones o un símbolo explican todo el beneficio). En 1h, PF OOS 0.92.

## Entradas omitidas

| Combinación | Tope de riesgo (`MAX_SL_MARGIN_LOSS_PCT`) | SL cruzado |
|---|---|---|
| `sfp_reversal_5_1` 1h / 4h | 384 / 491 | 0 / 0 |
| `camarilla_s3_r3` 1h / 4h | 728 / 1034 | — |
| `range_filter_flip_ema144` 1h / 4h | 438 / 664 | — |
| control 1h / 4h | 371 / 479 | 0 / 0 |

No hubo omisiones por SL cruzado: en futuros perpetuos casi no hay gaps, y el `open` de la vela de entrada es el
cierre de la vela de confirmación, que ya volvió más acá de la mecha. Camarilla y Range Filter no usan esa regla.

## Advertencias (sección 6 del preregistro)

- **Comparaciones múltiples:** se evaluaron 6 combinaciones de candidatos y 2 de control. Ninguna pasó, así que esta
  advertencia no cambia nada.
- **Sesgo de supervivencia:** el universo es el top-10 de hoy. El PF OOS del grupo de control BTC/ETH tampoco salva a
  ningún candidato: el mejor es `range_filter_flip_ema144` 4h, con 1.05.
- **Drawdowns > 100 %:** se miden sobre el capital de referencia de 100 USDT con margen fijo de 10 USDT y sin
  compounding, igual que en la Fase 2 de la v1. Indican pérdidas acumuladas mayores que ese capital de referencia.
- **Fragilidad del Range Filter** (ver la comparación con TradingView en `docs/historial/PROGRESS.md`): una sola vela
  distinta puede mover sus giros durante semanas. Eso no cambia el veredicto: ni el mejor marco llega al umbral.
- Ninguna de estas estrategias existe en la v1: este resultado no cambia la medición ciega de la v1.

## Lectura

Igual que las 6 estrategias por reglas de la v1, ninguno de los indicadores tomados de TradingView (SFP de PunkAlgo
HeatMap, Camarilla y Range Filter de Frost) muestra ventaja con estas reglas, costos y periodo. El SFP no se distingue
de su control con dirección al azar: el momento de entrada y la gestión de riesgo explican casi todo su resultado, no
la dirección. Por la regla de preregistro, **no se cambia nada para «probar otra variante»**. Cualquier ajuste
posterior es un preregistro nuevo, y el informe tendrá que decir cuántas rondas se probaron.
