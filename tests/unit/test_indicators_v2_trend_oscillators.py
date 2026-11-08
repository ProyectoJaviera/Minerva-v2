"""Range Filter, banda VIDYA, BB%B y WaveTrend de la v2."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.indicators._pine import pine_atr
from app.indicators.oscillators import bb_percent_b, wavetrend
from app.indicators.trend_filters import range_filter, vidya, vidya_band


def _ohlc(close):
    close = pd.Series(close, dtype=float)
    return pd.DataFrame({"open": close.shift(1).fillna(close.iloc[0]), "high": close + 0.5,
                         "low": close - 0.5, "close": close})


# --- Range Filter -----------------------------------------------------------------------------


def test_range_filter_recursion_by_hand_with_unit_periods():
    # Periodos 1 y multiplicadores 1: r = |close - close[1]|.
    out = range_filter(pd.Series([10.0, 11.0, 13.0, 12.0]), 1, 1.0, 1, 1.0)
    assert np.isnan(out["rf_filter"].iloc[0])
    assert out["rf_filter"].iloc[1:].tolist() == [10.0, 11.0, 11.0]  # arranca con prev = 0
    assert out["rf_upward"].tolist() == [0.0, 0.0, 1.0, 1.0]
    assert out["rf_downward"].tolist() == [0.0, 0.0, 0.0, 0.0]


def test_range_filter_moves_down_by_the_range_when_price_falls():
    out = range_filter(pd.Series([10.0, 11.0, 13.0, 9.0]), 1, 1.0, 1, 1.0)
    # Vela 3: close 9 <= filtro 11 y 9 + 4 > 11 -> el filtro se queda en 11.
    assert out["rf_filter"].iloc[3] == 11.0
    out = range_filter(pd.Series([10.0, 11.0, 13.0, 12.5, 5.0]), 1, 1.0, 1, 1.0)
    # Vela 3: r = 0.5; 12.5 > 11 y 12.5 - 0.5 = 12 >= 11 -> el filtro sube a 12.
    # Vela 4: r = 7.5; 5 <= 12 y 5 + 7.5 = 12.5 > 12 -> se queda en 12.
    assert out["rf_filter"].iloc[3:].tolist() == [12.0, 12.0]
    out = range_filter(pd.Series([10.0, 11.0, 13.0, 12.5, 11.5, 5.0]), 1, 1.0, 1, 1.0)
    # Vela 4: r = 1; 11.5 + 1 = 12.5 > 12 -> sigue en 12.
    # Vela 5: r = 6.5; 5 + 6.5 = 11.5 <= 12 -> el filtro BAJA a x + r = 11.5.
    assert out["rf_filter"].iloc[4:].tolist() == [12.0, 11.5]
    assert out["rf_downward"].iloc[5] == 1.0 and out["rf_upward"].iloc[5] == 0.0


def test_range_filter_flat_price_never_signals():
    out = range_filter(pd.Series([100.0] * 400))
    assert not out["rf_buy"].any() and not out["rf_sell"].any()
    assert (out["rf_state"] == 0).all()


def test_range_filter_buy_needs_a_previous_bearish_condition():
    down = np.linspace(200, 100, 300)
    up = np.linspace(100, 220, 300)
    out = range_filter(pd.Series(np.concatenate([down, up])))
    buys = out.index[out["rf_buy"]].tolist()
    assert buys and all(b >= 300 for b in buys)
    assert out["rf_state"].iloc[-1] == 1
    # Toda compra viene precedida de una condicion bajista mas reciente que cualquier alcista.
    for b in buys:
        prior = out.iloc[:b]
        last_bear = prior.index[prior["rf_bear_cond"]].max()
        last_bull = prior.index[prior["rf_bull_cond"]].max() if prior["rf_bull_cond"].any() else -1
        assert last_bear > last_bull


def test_range_filter_bull_and_bear_conditions_are_exclusive():
    rng = np.random.default_rng(3)
    out = range_filter(pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 1500)))))
    assert not (out["rf_bull_cond"] & out["rf_bear_cond"]).any()
    assert not (out["rf_buy"] & out["rf_sell"]).any()


def test_range_filter_rejects_bad_periods():
    with pytest.raises(ValueError):
        range_filter(pd.Series([1.0, 2.0]), fast_period=0)


# --- VIDYA --------------------------------------------------------------------------------------


def test_vidya_recursion_by_hand_with_unit_periods():
    out = vidya(pd.Series([10.0, 11.0, 11.0, 12.0]), length=1, momentum=1, smooth=1)
    # alpha = 1; CMO de una sola variacion = 100 (o 0 si no hubo variacion).
    assert np.isnan(out.iloc[0])
    assert out.iloc[1:].tolist() == [11.0, 11.0, 12.0]


def test_vidya_holds_its_value_through_a_flat_stretch_instead_of_resetting():
    close = np.concatenate([np.linspace(100, 120, 200), np.full(60, 120.0)])
    out = vidya(pd.Series(close))
    assert out.iloc[-1] > 100  # el original reiniciaba a 0 tras 20 velas planas
    # 20 velas planas despues el CMO es 0 y, 15 velas despues, tambien la SMA esta quieta.
    assert out.iloc[-1] == out.iloc[-10]


def test_vidya_band_width_is_twice_the_atr_times_the_multiplier():
    rng = np.random.default_rng(5)
    df = _ohlc(100 + np.cumsum(rng.normal(0, 1, 600)))
    out = vidya_band(df, atr_period=50)
    width = out["vidya_upper"] - out["vidya_lower"]
    expected = 2 * 1.6 * pine_atr(df, 50)
    pd.testing.assert_series_equal(width, expected, check_names=False)


def test_vidya_band_flips_need_a_cross_and_the_trail_follows_the_trend():
    rng = np.random.default_rng(23)
    df = _ohlc(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 2000))))
    out = vidya_band(df, atr_period=50)
    flips_up = out.index[out["vidya_flip_up"]].tolist()
    flips_down = out.index[out["vidya_flip_down"]].tolist()
    assert flips_up and flips_down
    for flip in flips_up:
        assert np.isnan(out["vidya_trail"].iloc[flip])  # NaN en la vela del cambio
        assert df["close"].iloc[flip] > out["vidya_upper"].iloc[flip]
        assert df["close"].iloc[flip - 1] <= out["vidya_upper"].iloc[flip - 1]
    steady_up = out["vidya_trend_up"] & ~out["vidya_flip_up"]
    assert (out.loc[steady_up, "vidya_trail"] == out.loc[steady_up, "vidya_lower"]).all()
    steady_down = ~out["vidya_trend_up"] & ~out["vidya_flip_down"]
    pd.testing.assert_series_equal(out.loc[steady_down, "vidya_trail"],
                                   out.loc[steady_down, "vidya_upper"], check_names=False)


def test_vidya_band_stays_bearish_if_price_is_already_above_the_band_when_it_appears():
    # Hallazgo documentado: sin vela previa por debajo de la banda no hay cruce, y la tendencia
    # (que arranca bajista) queda trabada aunque el precio este muy por encima.
    close = np.concatenate([np.full(300, 100.0) + np.sin(np.arange(300)), np.full(30, 200.0)])
    out = vidya_band(_ohlc(close), atr_period=50)
    assert not out["vidya_trend_up"].any()


def test_vidya_band_starts_bearish_and_trails_the_upper_band():
    rng = np.random.default_rng(9)
    df = _ohlc(100 + np.cumsum(rng.normal(0, 0.1, 400)))
    out = vidya_band(df, atr_period=50)
    first = out["vidya_upper"].first_valid_index()
    if not out["vidya_trend_up"].iloc[first]:
        assert out["vidya_trail"].iloc[first] == out["vidya_upper"].iloc[first]


# --- BB%B -----------------------------------------------------------------------------------------


def test_bb_percent_b_matches_the_formula():
    close = pd.Series(np.arange(1.0, 21.0))
    out = bb_percent_b(close)
    mean, std = close.mean(), close.std(ddof=0)
    lower, upper = mean - 2 * std, mean + 2 * std
    assert out["bb_pct_b"].iloc[-1] == pytest.approx((20 - lower) / (upper - lower))
    assert out["bb_pct_b"].iloc[:19].isna().all()


def test_bb_percent_b_is_nan_on_a_flat_price():
    out = bb_percent_b(pd.Series([5.0] * 30))
    assert out["bb_pct_b"].isna().all()
    assert not out["bb_exit_oversold"].any()


def test_bb_exit_signals_are_crosses_of_the_thresholds():
    rng = np.random.default_rng(11)
    out = bb_percent_b(pd.Series(100 + np.cumsum(rng.normal(0, 1, 800))))
    pct = out["bb_pct_b"]
    expected_os = (pct > -0.1) & (pct.shift(1) <= -0.1)
    expected_ob = (pct < 1.1) & (pct.shift(1) >= 1.1)
    assert out["bb_exit_oversold"].tolist() == expected_os.tolist()
    assert out["bb_exit_overbought"].tolist() == expected_ob.tolist()
    assert out["bb_exit_oversold"].any() and out["bb_exit_overbought"].any()


# --- WaveTrend ----------------------------------------------------------------------------------


def test_wavetrend_crosses_only_fire_in_the_extreme_zone():
    rng = np.random.default_rng(13)
    df = _ohlc(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 3000))))
    out = wavetrend(df)
    assert out["wt_bull_cross"].any() and out["wt_bear_cross"].any()
    assert (out.loc[out["wt_bull_cross"], "wt2"] <= -72).all()
    assert (out.loc[out["wt_bear_cross"], "wt2"] >= 72).all()


def test_wavetrend_wt2_is_the_three_bar_mean_of_wt1():
    rng = np.random.default_rng(17)
    out = wavetrend(_ohlc(100 + np.cumsum(rng.normal(0, 1, 300))))
    expected = out["wt1"].rolling(3, min_periods=3).mean()
    pd.testing.assert_series_equal(out["wt2"], expected, check_names=False)


def test_wavetrend_is_nan_on_a_flat_price():
    out = wavetrend(_ohlc([50.0] * 60))
    assert out["wt1"].isna().all()
    assert not out["wt_bull_cross"].any()


def test_wavetrend_requires_hlc():
    with pytest.raises(ValueError):
        wavetrend(pd.DataFrame({"close": [1.0]}))
