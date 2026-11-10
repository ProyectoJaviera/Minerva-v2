# Minerva v2 — Preregistro de los finalistas de la ronda 3 (CONGELADO el 2026-11-10)

> **CONGELADO** en un commit propio por orden del dueño (2026-11-10), **antes** de mirar los datos reservados. Fija las
> tres combinaciones que salieron de la [ronda 3 exploratoria](RONDA3_V2.md) y cómo se leerá su primer examen con datos
> que ninguna ronda miró. Desde aquí no se cambia nada: ni señales, ni salidas, ni reglas de lectura.

## 1. Finalistas (tal cual salieron; implementación en `app/research/round3.py`)

Comunes: marco **4h**; señal al cierre de la vela; **entrada con orden límite** al precio de cierre de la vela de señal,
válida solo durante la vela siguiente (si esa vela no atraviesa el precio, la señal se pierde); comisión maker en la
entrada y taker en la salida; **SL a 3 · ATR(14)** de la entrada, **trailing de 3 · ATR(14)** y **sin TP**; tope de
riesgo del 5 % (a 10x) que omite la entrada; sin señales en las primeras 500 velas; una posición por símbolo.

| Nombre | Gatillo | Filtro |
|---|---|---|
| `r3\|vidya_flip\|btc\|s3_trail3\|limit` | cambio de tendencia de la banda VIDYA ± ATR(200)·1.6 | régimen de BTC: largo solo con BTC sobre su EMA 200 de 4h, corto solo por debajo |
| `r3\|fvg\|ema\|s3_trail3\|limit` | primer retesteo de un FVG de 3 velas (hueco ≥ 0.25 ATR, vigencia 100 velas) | cierre sobre (largo) o bajo (corto) la EMA 144 |
| `r3\|rf_flip\|ema\|s3_trail3\|limit` | giro del Range Filter de Frost (27/1.5 y 55/3.5) | cierre sobre o bajo la EMA 144 |

Referencia de cada una: el mismo gatillo, sin filtro, con la dirección sorteada (`…|nada|s3_trail3|limit|rnd`).

## 2. Examen con los datos reservados (una sola corrida)

- **Datos:** velas y funding de Bitunix del **2026-10-01 00:00 UTC al 2026-11-10 00:00 UTC** (unas 240 velas de 4h),
  mismo universo de la Fase 2. Los indicadores se calculan con todo el historial previo; solo cuentan las operaciones
  **abiertas dentro** de ese tramo. Costos y motor, los de la ronda 3.
- **Qué se informa**, por finalista y por su control: operaciones, PF neto, PnL neto en USDT y porcentaje de ganadoras.
- **Cómo se lee (fijado ahora):** con menos de 20 operaciones, «sin información suficiente»; con 20 o más: PF < 0.8,
  «alerta: fracaso claro»; PF entre 0.8 y 1, «no confirma»; PF ≥ 1, «no contradice».
- **Ningún resultado aprueba una estrategia.** Seis semanas son muy pocas para un seguimiento de tendencia. Este examen
  solo puede detectar un fracaso claro.

## 3. Después

Las que no den «fracaso claro» pasan a **paper trading** en la v2 (decisión e implementación aparte, con su propio
criterio de evaluación escrito antes de empezar). Nada de esto habilita dinero real.

## 4. Advertencias

- Los finalistas salieron de 23 señales juzgadas sobre un OOS ya usado en dos rondas; la salida explica casi todo su
  resultado y el tope de riesgo las deja operar casi solo en las monedas menos volátiles (ver `RONDA3_V2.md`).
- No existen en la v1: no cambian la medición ciega de la v1.
