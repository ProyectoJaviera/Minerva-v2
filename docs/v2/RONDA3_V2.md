# Minerva v2 — Ronda 3 exploratoria: costos, salidas, FVG e información distinta al precio (2026-11-10)

**Exploratoria, no preregistrada.** Pedido del dueño tras la [exploración](EXPLORACION_V2.md) (0 de 176): bajar costos,
buscar las mejores salidas (con permiso para cambiar TP, SL y trailing), sumar el FVG y usar información que no sea el
precio de la propia moneda. Código: `app/research/round3.py` y `scripts/v2_round3.py`. El diseño y la regla de selección
se guardaron en el commit `ef11931` **antes** de correr.

## Diseño

- Solo **4h**; universo, periodo (hasta 2026-10-01) y criterios de la Fase 2.
- **23 señales:** 4 heredadas de la exploración por su PF **IS** y 19 nuevas con el **FVG** (definición estándar de 3
  velas, entrada en el primer retesteo) y con los filtros de **funding**, **régimen de BTC** (cierre de BTC contra su
  EMA 200) y **fuerza relativa** frente a BTC.
- Cada señal con **6 salidas** (la base y cinco en múltiplos del ATR, con TP fijo o trailing) y **2 entradas** (a
  mercado, o con orden límite al cierre de la vela de señal y comisión maker). Con los controles al azar: 372 variantes.
- **La salida y la entrada de cada señal se eligieron solo con el IS** (el 70 % inicial). Esa única variante se juzgó
  en el OOS (el 30 % final).

## Resultado

**4 de las 23 señales pasan todos los criterios de la Fase 2 con su variante elegida en IS, y las 4 cumplen la regla
completa.** Por la regla fija (máximo 3, por PF estresado), los finalistas son:

| Señal (variante elegida) | Operaciones (IS / OOS) | PF IS → PF OOS | PF estresado | % símbolos | % folds | DD OOS | Concentración | Control al azar (PF OOS) |
|---|---|---|---|---|---|---|---|---|
| Giro de VIDYA + régimen de BTC · trailing 3 ATR · límite | 129 / 103 | 1.31 → 1.54 | 1.40 | 88 % | 67 % | 19.6 % | 32 % | 0.98 |
| FVG + EMA 144 · trailing 3 ATR · límite | 372 / 320 | 1.21 → 1.34 | 1.21 | 78 % | 86 % | 17.1 % | 27 % | 1.05 |
| Giro del Range Filter + EMA 144 · trailing 3 ATR · límite | 238 / 225 | 1.79 → 1.31 | 1.20 | 75 % | 100 % | 19.2 % | 35 % | 1.29 |

La cuarta que pasa es el giro de VIDYA + EMA 144 con trailing de 3 ATR a mercado (PF 1.18 → 1.38, estresado 1.19).

## Qué explica la mejora (y por qué hay que desconfiar)

1. **La salida es casi todo.** En 22 de las 23 señales el IS eligió la misma salida: SL a 3 ATR(14) con trailing de
   3 ATR y sin TP. Con esa salida, varios controles con **dirección al azar** también quedan cerca o sobre 1 (Range
   Filter 1.29, BB%B 1.15, SFP 1.10). El finalista del Range Filter (1.31) casi no supera a su control (1.29): ahí la
   señal no aporta nada; el resultado es de la salida.
2. **El tope de riesgo actúa como filtro de volatilidad.** Un SL a 3 ATR en 4h supera a menudo el tope del 5 % (50 %
   del margen a 10x), y esas entradas se omiten. El finalista de VIDYA + BTC opera casi solo en BTC (63), TRX (56),
   BNB (44), ETH (31) y XRP (22); en DOGE, SOL, HYPE, XMR y ZEC suma 16 operaciones. Es, en la práctica, «seguir
   tendencia con stop amplio en las monedas menos volátiles».
3. **La orden límite ayuda poco** (unas 5 centésimas de PF): casi todas se llenan, porque basta que el precio baje un
   tick durante las 4 horas siguientes. La simulación es conservadora (llenado solo si la vela atraviesa el precio; en
   la vela de entrada no se cuenta ningún TP), pero no modela la cola de la orden.
4. **Comparaciones múltiples y OOS reutilizado.** Son 23 juicios sobre un OOS que ya se usó en dos rondas, y las
   variantes comparten salida, monedas y periodo, así que sus resultados no son independientes. Un seguimiento de
   tendencia con stop amplio gana en periodos con tendencias largas y pierde en mercados laterales: puede ser un
   rasgo del periodo 2025-2026.

## Conclusión

Por primera vez hay combinaciones que pasan los criterios, y dos de ellas (VIDYA + régimen de BTC, y FVG + EMA 144)
superan con margen a su control al azar. **No son estrategias aprobadas.** El examen que falta, con datos que ninguna
ronda miró:

1. preregistrar los finalistas tal cual (sin tocar nada) y correrlos **una vez** sobre los datos reservados desde el
   2026-10-01 (son pocas semanas: sirve para detectar un fracaso claro, no para confirmar);
2. dejarlos en **paper trading** varios meses.

## Examen con los datos reservados (2026-11-10)

Corrida única según el [preregistro congelado](PREREGISTRO_V2_RONDA3.md) (commit `a31d3f9`), con
`scripts/v2_round3_reserved.py` (commit `63dcd75`): operaciones abiertas entre el 2026-10-01 y el 2026-11-10 (UTC).

| Finalista | Operaciones | PF neto | PnL neto | Ganadoras | Lectura fijada | Control al azar (n / PF) |
|---|---|---|---|---|---|---|
| Giro de VIDYA + régimen de BTC | 15 | 0.31 | −9.07 USDT | 20 % | sin información suficiente (< 20 operaciones) | 20 / 1.57 |
| FVG + EMA 144 | 28 | 0.52 | −9.98 USDT | 25 % | **alerta: fracaso claro** | 44 / 0.86 |
| Giro del Range Filter + EMA 144 | 26 | 0.62 | −5.87 USDT | 31 % | **alerta: fracaso claro** | 34 / 0.85 |

**Las tres pierden en los datos que ninguna ronda había mirado, y las tres quedan por debajo de su propio control con
dirección al azar.** Dos dan «fracaso claro»; la tercera no llega a 20 operaciones, pero con PF 0.31 tampoco da motivo
para seguir. Son solo seis semanas (un tramo bajista y sin tendencias largas), así que no prueba que nunca funcionen;
sí confirma la sospecha de la ronda: el resultado del OOS venía del periodo y de la salida, no de una ventaja estable.

**Conclusión de la ronda 3:** ningún finalista pasa a paper trading por mérito propio. Después de 6 estrategias en la
v1, 3 candidatos preregistrados, 176 combinaciones y 23 señales con salidas optimizadas, no hay ninguna regla basada en
estos indicadores con ventaja demostrada fuera de la muestra.
