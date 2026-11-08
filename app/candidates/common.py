"""Piezas comunes de los candidatos de la v2 (`docs/v2/PREREGISTRO_V2.md`, seccion 2).

- **Calentamiento:** ningun candidato emite senales en las primeras `WARMUP_BARS` velas de la
  serie. Por eso `precompute` debe recibir la serie COMPLETA (como hace el motor de backtest): la
  posicion de cada vela se guarda en la columna `v2_bar_index`.
- **Lectura de la vela de senal:** `evaluate`, `stop_price`, `take_profit_price` y
  `trailing_distance` leen la ultima fila del DataFrame que reciben (la vela de senal) y las
  columnas que dejo `precompute`. Si faltan, `ensure_precomputed` las calcula sobre ese mismo
  DataFrame; con una ventana corta el calentamiento no se alcanza y no hay senal (conservador).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

WARMUP_BARS = 500
BAR_INDEX_COLUMN = "v2_bar_index"


def add_bar_index(df: pd.DataFrame) -> pd.DataFrame:
    """Copia de `df` con la columna `v2_bar_index` (posicion 0..n-1 de cada vela).

    Args:
        df: velas de toda la serie.

    Returns:
        La copia con la columna agregada.
    """
    out = df.copy()
    out[BAR_INDEX_COLUMN] = np.arange(len(out), dtype="int64")
    return out


def ensure_precomputed(
    df: pd.DataFrame, required: str, precompute: Callable[[pd.DataFrame], pd.DataFrame]
) -> pd.DataFrame:
    """`df` tal cual si ya tiene la columna `required`; si no, `precompute(df)`.

    Args:
        df: velas (con o sin las columnas precalculadas).
        required: una columna que `precompute` agrega.
        precompute: la funcion `precompute` de la estrategia.

    Returns:
        Un DataFrame con las columnas precalculadas.
    """
    return df if required in df.columns else precompute(df)


def warmed_up(row: pd.Series, warmup: int) -> bool:
    """`True` si la vela ya paso el calentamiento.

    Args:
        row: fila de la vela de senal (con `v2_bar_index`).
        warmup: velas de calentamiento.

    Returns:
        Si la posicion de la vela es al menos `warmup`.
    """
    return int(row[BAR_INDEX_COLUMN]) >= warmup


def is_true(value: object) -> bool:
    """Lee una columna booleana que puede traer NaN o tipos de numpy.

    Args:
        value: valor de la celda.

    Returns:
        `True` solo si el valor es verdadero y no es NaN.
    """
    if value is None:
        return False
    if isinstance(value, float) and np.isnan(value):
        return False
    return bool(value)
