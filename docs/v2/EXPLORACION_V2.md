# Minerva v2 — Exploración de todas las herramientas y sus combinaciones (2026-11-10)

**Exploratorio, no preregistrado.** Pedido del dueño después de la [Fase 2](RESULTADO_FASE2_V2.md): usar todas las
herramientas de los dos indicadores de referencia (PunkAlgo HeatMap y Frost) y combinarlas, con todos los datos desde
2022. Código: `app/research/combos.py` y `scripts/v2_explore.py`. La regla para elegir finalistas se fijó y se subió en el
commit `0a7dad0` **antes** de correr.

## Qué se probó

- **8 gatillos:** SFP; rechazo de S3/R3 de Camarilla; giro del Range Filter; cambio de tendencia de la banda VIDYA;
  vela de reversión del BB%B; cruce de WaveTrend en ±72; rechazo de una zona de liquidez activa; «Liquidity Grab» de
  Frost.
- **4 filtros de estado**, solos y de a dos: EMA 144, último giro del Range Filter, tendencia VIDYA y WaveTrend
  (`wt1` vs `wt2`).
- **Salidas:** las del preregistro para SFP, Camarilla y Range Filter; para el resto, SL a 2 ATR(14) y TP 2R.
- **Controles:** cada gatillo sin filtros y con la dirección sorteada.
- En total: 88 combinaciones y 8 controles, en 1h y 4h (176 + 16 entradas). El universo, los costos, el periodo (desde
  ~2022-04 hasta 2026-10-01; OOS = el 30 % final) y los criterios son los de la Fase 2. La corrida tardó 105 min.

## Resultado

**Ninguna de las 176 combinaciones pasa los criterios de la Fase 2. No hay finalistas.**

- La mediana del PF OOS es 0.89. Hay 45 combinaciones con PF OOS > 1 y 11 con PF ≥ 1.2, pero estas últimas tienen
  menos de 100 operaciones (evidencia insuficiente) o no superan otros criterios.
- Los criterios que más fallan: PF OOS < 1.2 (140), PF estresado ≤ 1 (129), folds positivos < 50 % (119), PF > 1 en
  menos de la mitad de los símbolos (90) y drawdown OOS > 50 % (86).
- Varios controles al azar dan PF OOS cercano o superior al de sus versiones con dirección. El más llamativo es el giro
  del Range Filter en 4h, que con dirección al azar da 1.13. Lo que gana ahí es la salida (trailing con el TP de
  respaldo en un periodo con tendencias), no la dirección de la señal.

### Las más cercanas

| Combinación | Operaciones | PF IS → PF OOS | PF estresado | % símbolos | % folds | DD OOS | Qué le falta |
|---|---|---|---|---|---|---|---|
| SFP + EMA 144 + Range Filter, 4h | 275 | 0.87 → 1.27 | 1.14 | 70 % | 50 % | 13 % | concentración 46 % (> 40 %) |
| VIDYA + EMA 144 + WaveTrend, 4h | 486 | 1.03 → 1.20 | 1.08 | 50 % | 52 % | 30 % | PF 1.199 < 1.2; concentración 52 % |
| Rechazo de zona + EMA 144 + VIDYA, 4h | 410 | 0.82 → 1.21 | 1.09 | 70 % | 38 % | 21 % | folds; concentración 57 % |

Las que superan PF 1.2 con pocas operaciones (por ejemplo WaveTrend con filtros, PF OOS de 1.5 a 12 con 11 a 52
operaciones en todo el historial) son ruido estadístico: con 176 pruebas, que alguna con muy pocas operaciones salga
alta es lo esperable.

## Lectura

1. **Combinar no creó ventaja.** Los filtros reducen operaciones y a veces mejoran el PF, pero no de forma consistente
   en los dos periodos. La combinación más cercana (SFP con EMA y Range Filter en 4h) **pierde en IS** (PF 0.87) y
   gana en OOS: ese patrón es típico de un régimen favorable, no de una regla estable.
2. **Comparaciones múltiples:** con 176 combinaciones, lo esperable es que algunas queden cerca o pasen por azar. Que
   ninguna pase, ni siquiera así, es una señal fuerte de que estas herramientas, con estas reglas y costos, no tienen
   ventaja en este universo y periodo.
3. **Mismo resultado que la v1 y que la Fase 2 de la v2.** Las señales de los indicadores de TradingView revisados
   (HeatMap y Frost) no superan comisiones y slippage realistas.

## Advertencias

- Universo top-10 de CoinGecko del 2026-11-10 (sesgo de supervivencia, como en la Fase 2).
- La salida genérica (2 ATR, 2R) es una sola elección fija; no se exploraron otras salidas, a propósito, para no
  multiplicar las pruebas.
- Con algunos gatillos, ciertos filtros son redundantes (por ejemplo, un cruce alcista de WaveTrend ya implica
  `wt1 > wt2`), así que hay combinaciones con resultados idénticos.
- La simulación Monte Carlo de cartera (informativa) corrió con 20 repeticiones en vez de 200, para acortar la corrida;
  no participa de ningún criterio.
