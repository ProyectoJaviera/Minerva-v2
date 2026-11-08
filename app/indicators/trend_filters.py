"""Filtros de tendencia de la v2: Range Filter y banda VIDYA +- ATR (inspirados en Frost).

Inspirado en indicadores publicos de TradingView (autoria y licencia por verificar). La
especificacion exacta, con sus diferencias deliberadas, esta en
`docs/v2/ESPECIFICACION_INDICADORES.md` (secciones C y D).

Todo es causal. Ambos filtros son recursivos y arrancan desde valores arbitrarios (el Range
Filter desde 0, la VIDYA desde 0): sus primeras velas son calentamiento y no deben usarse para
senales (la especificacion recomienda descartar al menos 500 velas).

No esta conectado a ninguna estrategia (Fase 0 de la v2).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.indicators._pine import (
    pine_atr,
    pine_ema,
    pine_sma,
    require_columns,
    require_positive,
)

# Multiplicador del rango lento segun el modo de Frost ("Intraday Mode" es el valor por defecto).
RANGE_FILTER_SENSITIVITY = {"scalping": 1.3, "intraday": 3.5, "swing": 4.2}


def _smooth_range(close: pd.Series, period: int, mult: float) -> pd.Series:
    """`EMA(EMA(|close - close[1]|, period), 2 * period - 1) * mult`."""
    avg_range = pine_ema((close - close.shift(1)).abs(), period)
    return pine_ema(avg_range, 2 * period - 1) * mult


def range_filter(
    close: pd.Series,
    fast_period: int = 27,
    fast_mult: float = 1.5,
    slow_period: int = 55,
    slow_mult: float = RANGE_FILTER_SENSITIVITY["intraday"],
) -> pd.DataFrame:
    """Range Filter de Frost y sus giros (senales de compra y venta).

    El rango `r` es el promedio de dos rangos suavizados (rapido y lento). El filtro solo se
    mueve si el precio se aleja mas de `r` de su valor anterior; `upward`/`downward` cuentan las
    velas seguidas en que subio o bajo. Una senal de compra es la primera condicion alcista
    (`close > filtro`, filtro subiendo, cierre distinto del anterior) despues de una bajista; la
    de venta es el espejo.

    Args:
        close: serie de cierres.
        fast_period: periodo del rango rapido (27).
        fast_mult: multiplicador del rango rapido (1.5).
        slow_period: periodo del rango lento (55).
        slow_mult: multiplicador del rango lento (3.5, modo "Intraday"; ver
            `RANGE_FILTER_SENSITIVITY`).

    Returns:
        DataFrame con el mismo indice y columnas `rf_range`, `rf_filter`, `rf_upward`,
        `rf_downward`, `rf_bull_cond`, `rf_bear_cond`, `rf_buy`, `rf_sell` y `rf_state`
        (1 tras la ultima compra, -1 tras la ultima venta, 0 antes de la primera senal).

    Raises:
        ValueError: si algun periodo es menor que 1.
    """
    require_positive(fast_period=fast_period, slow_period=slow_period)
    x = close.astype(float)
    rng = (_smooth_range(x, fast_period, fast_mult) + _smooth_range(x, slow_period, slow_mult)) / 2
    xs = x.to_numpy()
    rs = rng.to_numpy()
    n = len(xs)

    filt = np.full(n, np.nan)
    for i in range(n):
        if math.isnan(rs[i]) or math.isnan(xs[i]):
            continue
        prev = filt[i - 1] if i > 0 and not math.isnan(filt[i - 1]) else 0.0
        if xs[i] > prev:
            filt[i] = prev if xs[i] - rs[i] < prev else xs[i] - rs[i]
        else:
            filt[i] = prev if xs[i] + rs[i] > prev else xs[i] + rs[i]

    upward = np.zeros(n)
    downward = np.zeros(n)
    for i in range(1, n):
        rising = filt[i] > filt[i - 1]
        falling = filt[i] < filt[i - 1]
        upward[i] = upward[i - 1] + 1 if rising else 0.0 if falling else upward[i - 1]
        downward[i] = downward[i - 1] + 1 if falling else 0.0 if rising else downward[i - 1]

    prev_close = np.concatenate(([np.nan], xs[:-1]))
    with np.errstate(invalid="ignore"):
        moved = (xs > prev_close) | (xs < prev_close)
        bull_cond = (xs > filt) & (upward > 0) & moved
        bear_cond = (xs < filt) & (downward > 0) & moved

    buy = np.zeros(n, dtype=bool)
    sell = np.zeros(n, dtype=bool)
    state = np.zeros(n, dtype=int)
    last_cond = 0
    current = 0
    for i in range(n):
        if bull_cond[i]:
            buy[i] = last_cond == -1
            last_cond = 1
        elif bear_cond[i]:
            sell[i] = last_cond == 1
            last_cond = -1
        if buy[i]:
            current = 1
        elif sell[i]:
            current = -1
        state[i] = current

    return pd.DataFrame({
        "rf_range": rs, "rf_filter": filt, "rf_upward": upward, "rf_downward": downward,
        "rf_bull_cond": bull_cond, "rf_bear_cond": bear_cond, "rf_buy": buy, "rf_sell": sell,
        "rf_state": state,
    }, index=close.index)


def vidya(close: pd.Series, length: int = 10, momentum: int = 20, smooth: int = 15) -> pd.Series:
    """VIDYA de Frost: media adaptativa por el CMO absoluto, suavizada con una SMA.

    `k = (2 / (length + 1)) * |CMO(momentum)| / 100`; `v = k * close + (1 - k) * v[1]`, con
    `v[1] = 0` al arrancar (como el original). Si en la ventana no hubo ningun movimiento
    (CMO indefinido), `k = 0` y la VIDYA se mantiene (el original la reiniciaba a 0).

    Args:
        close: serie de cierres.
        length: periodo de la VIDYA (10).
        momentum: ventana del CMO (20).
        smooth: periodo de la SMA final (15).

    Returns:
        La VIDYA suavizada.

    Raises:
        ValueError: si algun periodo es menor que 1.
    """
    require_positive(length=length, momentum=momentum, smooth=smooth)
    x = close.astype(float)
    change = x - x.shift(1)
    pos = change.clip(lower=0).where(change.notna())
    neg = (-change).clip(lower=0).where(change.notna())
    sum_pos = pos.rolling(window=momentum, min_periods=momentum).sum()
    sum_neg = neg.rolling(window=momentum, min_periods=momentum).sum()
    total = sum_pos + sum_neg
    with np.errstate(invalid="ignore", divide="ignore"):
        cmo = (100 * (sum_pos - sum_neg) / total).abs()
    cmo = cmo.where(~(total == 0), 0.0).to_numpy()
    xs = x.to_numpy()
    alpha = 2.0 / (length + 1)
    raw = np.full(len(xs), np.nan)
    for i in range(len(xs)):
        if math.isnan(cmo[i]) or math.isnan(xs[i]):
            continue
        prev = raw[i - 1] if i > 0 and not math.isnan(raw[i - 1]) else 0.0
        k = alpha * cmo[i] / 100
        raw[i] = k * xs[i] + (1 - k) * prev
    return pine_sma(pd.Series(raw, index=close.index), smooth)


def vidya_band(
    df: pd.DataFrame,
    length: int = 10,
    momentum: int = 20,
    smooth: int = 15,
    atr_period: int = 200,
    band_mult: float = 1.6,
) -> pd.DataFrame:
    """Banda VIDYA +- ATR (el "F. Trail" de Frost) y su estado de tendencia.

    Banda superior e inferior: `VIDYA +- ATR(atr_period) * band_mult`. La tendencia pasa a
    alcista cuando el cierre cruza por encima de la banda superior y a bajista cuando cruza por
    debajo de la inferior; arranca bajista. El trailing es la banda inferior en tendencia alcista
    y la superior en bajista, y es NaN en la vela del cambio.

    Args:
        df: velas con `high`, `low` y `close`.
        length: periodo de la VIDYA (10).
        momentum: ventana del CMO (20).
        smooth: periodo de la SMA de la VIDYA (15).
        atr_period: periodo del ATR (200).
        band_mult: distancia de la banda en ATR (1.6, opcion "High"; 0.61 en "Normal").

    Returns:
        DataFrame con el mismo indice y columnas `vidya`, `vidya_upper`, `vidya_lower`,
        `vidya_trend_up`, `vidya_trail`, `vidya_flip_up` y `vidya_flip_down`.

    Raises:
        ValueError: si falta una columna o algun periodo es menor que 1.
    """
    require_columns(df, ("high", "low", "close"))
    require_positive(atr_period=atr_period)
    close = df["close"].astype(float)
    mid = vidya(close, length, momentum, smooth)
    atr = pine_atr(df, atr_period)
    upper = mid + atr * band_mult
    lower = mid - atr * band_mult

    c = close.to_numpy()
    up_arr = upper.to_numpy()
    lo_arr = lower.to_numpy()
    n = len(c)
    trend = np.zeros(n, dtype=bool)
    trail = np.full(n, np.nan)
    is_up = False
    for i in range(n):
        if i > 0:
            if c[i] > up_arr[i] and c[i - 1] <= up_arr[i - 1]:
                is_up = True
            if c[i] < lo_arr[i] and c[i - 1] >= lo_arr[i - 1]:
                is_up = False
        trend[i] = is_up
        if not (i > 0 and trend[i] != trend[i - 1]):
            trail[i] = lo_arr[i] if is_up else up_arr[i]
    prev_trend = np.concatenate(([False], trend[:-1]))
    return pd.DataFrame({
        "vidya": mid.to_numpy(), "vidya_upper": up_arr, "vidya_lower": lo_arr,
        "vidya_trend_up": trend, "vidya_trail": trail,
        "vidya_flip_up": trend & ~prev_trend, "vidya_flip_down": ~trend & prev_trend,
    }, index=df.index)
