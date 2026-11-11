# Minerva v2 — Ronda 4 exploratoria: fuerza relativa, squeeze + ADX y volumen (2026-11-11)

**Exploratoria, no preregistrada.** Diseño y regla de selección subidos en el commit `43ad40e` antes de correr
(`app/research/round4.py`, `scripts/v2_round4.py`). Solo 4h; universo, costos, periodo (hasta 2026-10-01) y criterios
de la Fase 2; salida y entrada de cada señal elegidas solo con el IS. 21 señales nuevas, 324 variantes, 63 min.

## Resultado

**Ninguna de las 21 señales pasa los criterios con su variante elegida en IS. No hay finalistas.**

| Señal (variante elegida en IS) | Operaciones | PF IS → PF OOS | PF estresado | Control al azar | Qué falla |
|---|---|---|---|---|---|
| Fuerza relativa 1 semana (top 3 / bottom 3), SL 2.5 ATR, límite | 553 | 1.11 → 1.25 | 1.17 | 1.06 | concentración 57 % |
| Fuerza relativa 1 mes + régimen de BTC | 240 | 1.31 → 1.11 | 1.05 | 1.03 | PF < 1.2; concentración 124 % |
| Giro de VIDYA + pico de volumen | 131 | 1.32 → 1.17 | 1.02 | 0.96 | PF < 1.2; concentración 140 % |
| Squeeze (cualquier filtro) | 104 a 1120 | 1.23-1.72 → 0.48-0.95 | ≤ 0.88 | — | PF OOS < 1 |

- **La fuerza relativa semanal es lo más interesante de la ronda:** gana en los dos periodos (IS 1.11, OOS 1.25), en 6 de
  10 monedas y en el 67 % de los folds, y supera a su control al azar. Falla solo porque pocas operaciones explican más
  de la mitad de la ganancia. Es una idea con respaldo en estudios y vale la pena seguirla, pero no pasa los criterios.
- **El squeeze funciona en IS y se cae en OOS** en sus seis variantes: el patrón clásico del sobreajuste.
- **El volumen no ayuda de forma estable:** como filtro mejora el IS de casi todos los gatillos y empeora o deja igual
  el OOS.

## Lectura

Cuatro rondas y unas 400 señales probadas: nada pasa los criterios de la Fase 2 con selección honesta, y lo único que
pasó en una ronda (ronda 3) perdió en los datos reservados. La fuerza relativa semanal es la única idea que se comporta
igual en los dos periodos; si se quiere seguir, lo correcto es dejarla en la prueba hacia adelante con sus reglas de hoy.
