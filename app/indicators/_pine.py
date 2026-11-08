"""Primitivas causales que imitan las funciones de Pine Script usadas por los indicadores v2.

Las usan `structure.py`, `levels.py`, `trend_filters.py` y `oscillators.py`. No reemplazan a
`engine.py` (el de las estrategias de la v1, que usa `ewm` de pandas y otra inicializacion): aqui
se fija explicitamente como arranca cada media, porque los indicadores de TradingView que se
especifican en `docs/v2/ESPECIFICACION_INDICADORES.md` dependen de ello durante el calentamiento.

Convenciones (todas causales: el valor de la vela `i` usa solo las velas `0..i`):

- `pine_ema` y `pine_rma` arrancan con la media simple de los primeros `length` valores validos
  consecutivos (la referencia del manual de Pine para `ta.rma`; para `ta.ema` queda por verificar
  en el grafico). Tras arrancar, una entrada NaN da salida NaN y el estado se conserva.
- `pine_sma` y `pine_stdev` son NaN si falta cualquier valor de la ventana; la desviacion es
  poblacional (`ta.stdev` con `biased=true`, el valor por defecto de Pine).
- `pine_atr` es `pine_rma` del rango verdadero; en la primera vela el rango verdadero es
  `high - low`.
- `crossover`/`crossunder` son falsos si falta cualquiera de los cuatro valores que comparan.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
import pandas as pd


def require_columns(df: pd.DataFrame, columns: Iterable[str]) -> None:
    """Comprueba que `df` tenga las columnas pedidas.

    Args:
        df: DataFrame de velas.
        columns: nombres de columna obligatorios.

    Raises:
        ValueError: si falta alguna columna.
    """
    missing = [col for col in columns if col not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas en el DataFrame: {missing}")


def require_positive(**params: float) -> None:
    """Comprueba que cada parametro sea >= 1.

    Args:
        **params: nombre -> valor de cada periodo a validar.

    Raises:
        ValueError: si algun parametro es menor que 1.
    """
    for name, value in params.items():
        if value < 1:
            raise ValueError(f"{name} debe ser >= 1")


def _recursive_average(series: pd.Series, length: int, alpha: float) -> pd.Series:
    """Media exponencial con arranque por media simple de `length` valores validos consecutivos."""
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    state = math.nan
    seed_sum = 0.0
    seed_count = 0
    for i, x in enumerate(values):
        if math.isnan(state):
            if math.isnan(x):
                seed_sum = 0.0
                seed_count = 0
                continue
            seed_sum += x
            seed_count += 1
            if seed_count == length:
                state = seed_sum / length
                out[i] = state
            continue
        if math.isnan(x):
            continue
        state = alpha * x + (1.0 - alpha) * state
        out[i] = state
    return pd.Series(out, index=series.index)


def pine_ema(series: pd.Series, length: int) -> pd.Series:
    """EMA con `alpha = 2 / (length + 1)` y arranque por media simple.

    Args:
        series: serie de valores.
        length: periodo (>= 1).

    Returns:
        La EMA; NaN hasta juntar `length` valores validos consecutivos.

    Raises:
        ValueError: si `length` es menor que 1.
    """
    require_positive(length=length)
    return _recursive_average(series, length, 2.0 / (length + 1))


def pine_rma(series: pd.Series, length: int) -> pd.Series:
    """Media de Wilder (`ta.rma`): `alpha = 1 / length`, arranque por media simple.

    Args:
        series: serie de valores.
        length: periodo (>= 1).

    Returns:
        La RMA; NaN hasta juntar `length` valores validos consecutivos.

    Raises:
        ValueError: si `length` es menor que 1.
    """
    require_positive(length=length)
    return _recursive_average(series, length, 1.0 / length)


def pine_sma(series: pd.Series, length: int) -> pd.Series:
    """Media simple; NaN si falta algun valor de la ventana.

    Args:
        series: serie de valores.
        length: ventana (>= 1).

    Returns:
        La media movil simple.

    Raises:
        ValueError: si `length` es menor que 1.
    """
    require_positive(length=length)
    return series.astype(float).rolling(window=length, min_periods=length).mean()


def pine_stdev(series: pd.Series, length: int) -> pd.Series:
    """Desviacion estandar poblacional (`ddof=0`) de las ultimas `length` velas.

    Args:
        series: serie de valores.
        length: ventana (>= 1).

    Returns:
        La desviacion estandar movil.

    Raises:
        ValueError: si `length` es menor que 1.
    """
    require_positive(length=length)
    return series.astype(float).rolling(window=length, min_periods=length).std(ddof=0)


def true_range(df: pd.DataFrame) -> pd.Series:
    """Rango verdadero; en la primera vela (sin cierre previo) vale `high - low`.

    Args:
        df: velas con `high`, `low` y `close`.

    Returns:
        El rango verdadero de cada vela.

    Raises:
        ValueError: si falta alguna columna.
    """
    require_columns(df, ("high", "low", "close"))
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    prev_close = df["close"].astype(float).shift(1)
    ranges = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1)
    tr = ranges.max(axis=1, skipna=True)
    # Si high o low faltan, el rango verdadero no existe (max con skipna podria inventarlo).
    return tr.where(high.notna() & low.notna())


def pine_atr(df: pd.DataFrame, length: int) -> pd.Series:
    """ATR de Pine (`ta.atr`): `pine_rma` del rango verdadero.

    Args:
        df: velas con `high`, `low` y `close`.
        length: periodo (>= 1).

    Returns:
        El ATR en unidades de precio; NaN durante las primeras `length - 1` velas.

    Raises:
        ValueError: si `length` es menor que 1 o falta una columna.
    """
    require_positive(length=length)
    return pine_rma(true_range(df), length)


def crossover(a: pd.Series, b: pd.Series | float) -> pd.Series:
    """`a` cruza por encima de `b`: `a > b` ahora y `a <= b` en la vela anterior.

    Args:
        a: serie que cruza.
        b: serie o constante cruzada.

    Returns:
        Serie booleana; falsa si falta algun valor comparado.
    """
    b_series = b if isinstance(b, pd.Series) else pd.Series(float(b), index=a.index)
    return ((a > b_series) & (a.shift(1) <= b_series.shift(1))).fillna(False).astype(bool)


def crossunder(a: pd.Series, b: pd.Series | float) -> pd.Series:
    """`a` cruza por debajo de `b`: `a < b` ahora y `a >= b` en la vela anterior.

    Args:
        a: serie que cruza.
        b: serie o constante cruzada.

    Returns:
        Serie booleana; falsa si falta algun valor comparado.
    """
    b_series = b if isinstance(b, pd.Series) else pd.Series(float(b), index=a.index)
    return ((a < b_series) & (a.shift(1) >= b_series.shift(1))).fillna(False).astype(bool)
