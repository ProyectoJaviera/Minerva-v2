"""Osciladores de la v2: BB%B y WaveTrend (inspirados en Frost).

Inspirado en indicadores publicos de TradingView (autoria y licencia por verificar). La
especificacion exacta esta en `docs/v2/ESPECIFICACION_INDICADORES.md` (seccion F). En Frost, las
"Reversal Bars" son los cruces del BB%B y la "Reversal RSI" es en realidad el WaveTrend.

Todo es causal. No esta conectado a ninguna estrategia (Fase 0 de la v2).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.indicators._pine import (
    crossover,
    crossunder,
    pine_ema,
    pine_sma,
    pine_stdev,
    require_columns,
    require_positive,
)


def bb_percent_b(
    close: pd.Series,
    period: int = 20,
    mult: float = 2.0,
    oversold: float = -0.1,
    overbought: float = 1.1,
) -> pd.DataFrame:
    """%B de Bollinger y las "velas de reversion" de Frost.

    `%B = (close - inferior) / (superior - inferior)` con bandas `SMA(period) +- mult * desvio
    poblacional`. Salida de sobreventa: `%B` cruza por encima de `oversold`; salida de
    sobrecompra: cruza por debajo de `overbought`. Si las bandas coinciden (precio plano), `%B`
    es NaN.

    Args:
        close: serie de cierres.
        period: ventana de la media y del desvio (20).
        mult: desvios de las bandas (2.0).
        oversold: umbral de sobreventa (-0.1).
        overbought: umbral de sobrecompra (1.1).

    Returns:
        DataFrame con el mismo indice y columnas `bb_pct_b`, `bb_exit_oversold` y
        `bb_exit_overbought`.

    Raises:
        ValueError: si `period` es menor que 1.
    """
    require_positive(period=period)
    x = close.astype(float)
    basis = pine_sma(x, period)
    dev = mult * pine_stdev(x, period)
    width = 2 * dev
    pct_b = ((x - (basis - dev)) / width).where(width != 0)
    return pd.DataFrame({
        "bb_pct_b": pct_b,
        "bb_exit_oversold": crossover(pct_b, oversold),
        "bb_exit_overbought": crossunder(pct_b, overbought),
    }, index=close.index)


def wavetrend(
    df: pd.DataFrame,
    channel: int = 9,
    average: int = 12,
    signal: int = 3,
    extreme: float = 72.0,
) -> pd.DataFrame:
    """WaveTrend sobre `hlc3` y sus cruces en zona extrema (la "Reversal RSI" de Frost).

    `esa = EMA(hlc3, channel)`, `d = EMA(|hlc3 - esa|, channel)`,
    `ci = (hlc3 - esa) / (0.015 * d)`, `wt1 = EMA(ci, average)`, `wt2 = SMA(wt1, signal)`. Cruce
    alcista: `wt1` cruza por encima de `wt2` con `wt2 <= -extreme`; bajista: cruza por debajo
    con `wt2 >= extreme`. Con `d = 0` (precio plano) `ci` es NaN.

    Args:
        df: velas con `high`, `low` y `close`.
        channel: periodo de `esa` y `d` (9).
        average: periodo de `wt1` (12).
        signal: periodo de `wt2` (3).
        extreme: umbral de la zona extrema (72; las alertas del original usan 53).

    Returns:
        DataFrame con el mismo indice y columnas `wt1`, `wt2`, `wt_bull_cross` y
        `wt_bear_cross`.

    Raises:
        ValueError: si falta una columna o algun periodo es menor que 1.
    """
    require_columns(df, ("high", "low", "close"))
    require_positive(channel=channel, average=average, signal=signal)
    src = (df["high"].astype(float) + df["low"].astype(float) + df["close"].astype(float)) / 3
    esa = pine_ema(src, channel)
    d = pine_ema((src - esa).abs(), channel)
    with np.errstate(invalid="ignore", divide="ignore"):
        ci = ((src - esa) / (0.015 * d)).where(d != 0)
    wt1 = pine_ema(ci, average)
    wt2 = pine_sma(wt1, signal)
    return pd.DataFrame({
        "wt1": wt1,
        "wt2": wt2,
        "wt_bull_cross": crossover(wt1, wt2) & (wt2 <= -extreme),
        "wt_bear_cross": crossunder(wt1, wt2) & (wt2 >= extreme),
    }, index=df.index)
