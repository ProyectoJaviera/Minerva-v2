# Minerva v2 — Prueba hacia adelante de los finalistas de la ronda 3 (desde el 2026-11-10)

Pedido del dueño (2026-11-10): aunque los tres finalistas perdieron en el [examen con los datos
reservados](RONDA3_V2.md#examen-con-los-datos-reservados-2026-11-10), dejarlos igual en paper, porque no cuesta nada.

## Cómo funciona

`scripts/v2_forward_test.py` corre las tres combinaciones congeladas en
[`PREREGISTRO_V2_RONDA3.md`](PREREGISTRO_V2_RONDA3.md) y sus controles al azar con el motor de backtest sobre el archivo
de historial local (`history/history_v2.db`) y cuenta solo las operaciones **abiertas desde el 2026-11-10 00:00 UTC**:
velas que no existían cuando se fijaron las reglas. Como el motor es determinista y causal, equivale a haberlas operado
en paper desde ese día, con la misma entrada con orden límite del preregistro (que el bot en vivo no simula) y sin dejar
ningún proceso corriendo. Universo congelado: las 10 monedas de la ronda 3.

Para ver el estado, en la carpeta del proyecto:

    python scripts/update_history_file.py     (baja las velas nuevas; red pública de Bitunix y CoinGecko)
    python scripts/v2_forward_test.py --trades

## Criterio de lectura (fijado el 2026-11-10, antes de la primera corrida con datos nuevos)

- Cada finalista se evalúa **una vez**, cuando junte **60 operaciones** hacia adelante o el **2027-05-10**, lo que
  ocurra primero. Antes de eso el script solo informa; no se saca ninguna conclusión.
- **Sigue en estudio** si en esa revisión su PF neto es **≥ 1.2** y **supera al de su control al azar**. Si no,
  **queda descartado**.
- «Sigue en estudio» no habilita dinero real: abriría una ronda nueva, con preregistro propio.
- No se cambia ninguna regla de las combinaciones durante la prueba.

## Advertencias

- Si una moneda sale del top-10, `update_history_file.py` deja de actualizarla y el script la marca como atrasada; sus
  operaciones posteriores no se cuentan.
- Punto de partida desfavorable: las tres perdieron en las seis semanas reservadas (PF 0.31, 0.52 y 0.62).
