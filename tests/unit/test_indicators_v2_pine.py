"""Primitivas estilo Pine de los indicadores v2 (`app/indicators/_pine.py`)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from app.indicators._pine import (
    crossover,
    crossunder,
    pine_atr,
    pine_ema,
    pine_rma,
    pine_sma,
    pine_stdev,
    require_columns,
    true_range,
)


def test_pine_ema_seeds_with_the_simple_mean_of_the_first_length_values():
    out = pine_ema(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0]), 3)
    assert out.iloc[:2].isna().all()
    assert out.iloc[2] == pytest.approx(2.0)  # media de 1, 2, 3
    assert out.iloc[3] == pytest.approx(0.5 * 4 + 0.5 * 2.0)
    assert out.iloc[4] == pytest.approx(0.5 * 5 + 0.5 * 3.0)


def test_pine_ema_skips_leading_nans_and_restarts_the_seed_on_a_gap_before_seeding():
    out = pine_ema(pd.Series([np.nan, 1.0, np.nan, 2.0, 4.0]), 2)
    assert out.iloc[:4].isna().all()  # el 1.0 suelto no alcanza: el NaN reinicia la semilla
    assert out.iloc[4] == pytest.approx(3.0)


def test_pine_ema_holds_its_state_across_a_nan_after_seeding():
    out = pine_ema(pd.Series([2.0, 2.0, np.nan, 5.0]), 2)
    assert math.isnan(out.iloc[2])
    alpha = 2 / 3
    assert out.iloc[3] == pytest.approx(alpha * 5 + (1 - alpha) * 2.0)


def test_pine_rma_uses_alpha_one_over_length():
    out = pine_rma(pd.Series([3.0, 3.0, 6.0]), 2)
    assert out.iloc[1] == pytest.approx(3.0)
    assert out.iloc[2] == pytest.approx(0.5 * 6 + 0.5 * 3)


def test_length_one_ema_is_the_series_itself():
    s = pd.Series([1.0, 5.0, 2.0])
    pd.testing.assert_series_equal(pine_ema(s, 1), s)


@pytest.mark.parametrize("fn", [pine_ema, pine_rma, pine_sma, pine_stdev])
def test_periods_below_one_are_rejected(fn):
    with pytest.raises(ValueError):
        fn(pd.Series([1.0, 2.0]), 0)


def test_pine_stdev_is_the_population_deviation():
    s = pd.Series([1.0, 2.0, 3.0, 4.0])
    assert pine_stdev(s, 4).iloc[-1] == pytest.approx(np.std([1, 2, 3, 4], ddof=0))


def test_true_range_uses_high_minus_low_on_the_first_bar_and_gaps_afterwards():
    df = pd.DataFrame({"high": [10.0, 12.0], "low": [8.0, 11.0], "close": [9.0, 11.5]})
    tr = true_range(df)
    assert tr.iloc[0] == pytest.approx(2.0)
    assert tr.iloc[1] == pytest.approx(3.0)  # high - cierre previo


def test_pine_atr_first_value_is_the_mean_true_range_of_the_first_length_bars():
    df = pd.DataFrame({"high": [10.0, 12.0, 13.0], "low": [8.0, 11.0, 12.0],
                       "close": [9.0, 11.5, 12.5]})
    atr = pine_atr(df, 3)
    assert atr.iloc[:2].isna().all()
    assert atr.iloc[2] == pytest.approx((2.0 + 3.0 + 1.5) / 3)


def test_require_columns_names_the_missing_ones():
    with pytest.raises(ValueError, match="close"):
        require_columns(pd.DataFrame({"high": [1.0]}), ("high", "close"))


def test_crossover_and_crossunder_need_both_bars_and_ignore_nans():
    a = pd.Series([np.nan, 1.0, 3.0, 1.0, 1.0])
    b = pd.Series([2.0, 2.0, 2.0, 2.0, np.nan])
    assert crossover(a, b).tolist() == [False, False, True, False, False]
    assert crossunder(a, b).tolist() == [False, False, False, True, False]


def test_crossover_touching_from_equal_counts_as_a_cross():
    a = pd.Series([2.0, 2.5])
    assert crossover(a, 2.0).tolist() == [False, True]
