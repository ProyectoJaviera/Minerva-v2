"""Pivotes, SFP y zonas de liquidez de la v2 (`app/indicators/structure.py`)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.indicators._pine import pine_atr
from app.indicators.structure import (
    active_zones_at,
    heatmap_atr_multiplier,
    liquidity_zones,
    pivot_high,
    pivot_low,
    sfp_signals,
)

# --- pivotes -------------------------------------------------------------------------------------


def test_pivot_high_appears_on_the_confirmation_bar_not_on_the_pivot_bar():
    out = pivot_high(pd.Series([1.0, 2.0, 5.0, 2.0, 1.0]), 2, 2)
    assert out.iloc[4] == 5.0
    assert out.iloc[:4].isna().all()


def test_a_tie_is_not_a_pivot():
    out = pivot_high(pd.Series([1.0, 2.0, 3.0, 3.0, 2.0, 1.0]), 2, 2)
    assert out.isna().all()


def test_pivot_low_is_the_mirror():
    out = pivot_low(pd.Series([5.0, 4.0, 1.0, 4.0, 5.0]), 2, 2)
    assert out.iloc[4] == 1.0


def test_a_nan_in_the_window_blocks_the_pivot():
    out = pivot_high(pd.Series([1.0, np.nan, 5.0, 2.0, 1.0]), 2, 2)
    assert out.isna().all()


def test_a_series_shorter_than_the_window_has_no_pivots():
    assert pivot_high(pd.Series([1.0, 3.0, 1.0]), 2, 2).isna().all()


def test_pivot_rejects_periods_below_one():
    with pytest.raises(ValueError):
        pivot_high(pd.Series([1.0, 2.0, 1.0]), 0, 1)


# --- SFP ---------------------------------------------------------------------------------------

# (open, high, low, close). Pivote maximo 20 en la vela 5, confirmado en la 6 (5 izq / 1 der).
# El minimo mas bajo entre el pivote y la barrida (velas 6-8) es 12.5.
BASE_BARS = [
    (10.0, 10.5, 9.5, 10.0),
    (10.0, 11.0, 9.6, 10.5),
    (10.5, 12.0, 10.0, 11.0),
    (11.0, 13.0, 10.5, 12.0),
    (12.0, 14.0, 11.0, 13.0),
    (13.0, 20.0, 12.0, 18.0),
    (18.0, 18.5, 13.0, 14.0),
    (14.0, 16.0, 12.5, 15.0),
    (15.0, 19.0, 14.0, 18.0),
]
SWEEP = (19.0, 21.0, 17.0, 19.5)  # high > 20 con open y close por debajo


def _bars(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def _bear_case(after_sweep):
    return _bars([*BASE_BARS, SWEEP, *after_sweep])


def test_bearish_sfp_confirms_on_the_first_close_below_the_opposite_extreme():
    df = _bear_case([(19.5, 19.6, 15.0, 16.0), (16.0, 16.5, 12.0, 12.4)])
    out = sfp_signals(df)
    assert out["sfp_bear_sweep"].tolist().index(True) == 9
    assert out.index[out["sfp_bear_signal"]].tolist() == [11]
    row = out.iloc[11]
    assert row["sfp_bear_swing"] == 20.0
    assert row["sfp_bear_opposite"] == 12.5
    assert row["sfp_bear_sweep_extreme"] == 21.0
    assert row["sfp_bear_bars_since_sweep"] == 2
    assert out["sfp_bear_swing"].notna().sum() == 1  # los detalles solo en la vela de senal


def test_a_close_exactly_at_the_opposite_extreme_does_not_confirm():
    df = _bear_case([(19.5, 19.6, 12.5, 12.5)])
    assert not sfp_signals(df)["sfp_bear_signal"].any()


def test_the_sweep_bar_itself_can_confirm():
    df = _bars([*BASE_BARS, (19.0, 21.0, 12.0, 12.4)])
    out = sfp_signals(df)
    assert out["sfp_bear_sweep"].iloc[9] and out["sfp_bear_signal"].iloc[9]
    assert out["sfp_bear_bars_since_sweep"].iloc[9] == 0


def test_a_close_above_the_swing_invalidates_the_setup():
    df = _bear_case([(19.5, 20.5, 19.0, 20.2), (16.0, 16.5, 12.0, 12.4)])
    assert not sfp_signals(df)["sfp_bear_signal"].any()


def test_an_open_above_the_swing_is_not_a_sweep():
    df = _bars([*BASE_BARS, (20.5, 21.0, 17.0, 19.5), (16.0, 16.5, 12.0, 12.4)])
    out = sfp_signals(df)
    assert not out["sfp_bear_sweep"].any()
    assert not out["sfp_bear_signal"].any()


def test_a_close_above_the_swing_on_the_sweep_bar_is_not_a_sweep():
    df = _bars([*BASE_BARS, (19.0, 21.0, 17.0, 20.5)])
    assert not sfp_signals(df)["sfp_bear_sweep"].any()


def test_the_setup_expires_after_max_age_bars_from_the_pivot():
    df = _bear_case([(19.5, 19.6, 15.0, 16.0), (16.0, 16.5, 12.0, 12.4)])
    # Pivote en la vela 5; la confirmacion llega en la 11 (6 velas despues).
    assert sfp_signals(df, max_age=6)["sfp_bear_signal"].iloc[11]
    # En una misma vela se evalua la confirmacion ANTES que la expiracion (orden del original):
    # con max_age=5 el setup vence al cierre de la vela 11, despues de confirmar.
    assert sfp_signals(df, max_age=5)["sfp_bear_signal"].iloc[11]
    # Con max_age=4 vence al cierre de la vela 10 y la 11 ya no confirma.
    assert not sfp_signals(df, max_age=4)["sfp_bear_signal"].any()


def test_no_signal_before_any_pivot_exists():
    df = _bars(BASE_BARS[:5])
    out = sfp_signals(df)
    assert not out[["sfp_bear_sweep", "sfp_bear_signal", "sfp_bull_sweep",
                    "sfp_bull_signal"]].to_numpy().any()


def test_bullish_sfp_is_the_exact_mirror_of_the_bearish_one():
    df = _bear_case([(19.5, 19.6, 15.0, 16.0), (16.0, 16.5, 12.0, 12.4)])
    mirrored = pd.DataFrame({"open": 100 - df["open"], "high": 100 - df["low"],
                             "low": 100 - df["high"], "close": 100 - df["close"]})
    out = sfp_signals(mirrored)
    assert out.index[out["sfp_bull_signal"]].tolist() == [11]
    assert out["sfp_bull_swing"].iloc[11] == 80.0
    assert out["sfp_bull_opposite"].iloc[11] == 87.5
    assert out["sfp_bull_sweep_extreme"].iloc[11] == 79.0


def test_sfp_requires_ohlc_columns():
    with pytest.raises(ValueError):
        sfp_signals(pd.DataFrame({"high": [1.0], "low": [0.5], "close": [0.7]}))


# --- zonas de liquidez -----------------------------------------------------------------------


def _zone_frame():
    # Maximo de pivote 15 en la vela 4 (2 izq / 2 der), confirmado en la 6.
    highs = [10.0, 10.5, 11.0, 12.0, 15.0, 13.0, 12.5, 13.0, 15.2, 16.0]
    lows = [h - 1.0 for h in highs]
    closes = [h - 0.5 for h in highs]
    return pd.DataFrame({"high": highs, "low": lows, "close": closes,
                         "volume": [1.0] * 4 + [4.0] + [1.0] * 5})


def test_a_zone_is_emitted_on_the_pivot_confirmation_bar_never_before():
    df = _zone_frame()
    zones = liquidity_zones(df, atr_period=3, atr_mult=0.2)
    high_zone = zones[zones["side"] == "high"].iloc[0]
    assert high_zone["pivot_index"] == 4
    assert high_zone["emit_index"] == 6
    width = 0.2 * pine_atr(df, 3).iloc[4]
    assert high_zone["bottom"] == 15.0
    assert high_zone["top"] == pytest.approx(15.0 + width)
    assert high_zone["mid"] == pytest.approx(15.0 + width / 2)


def test_a_zone_is_mitigated_by_the_first_later_bar_that_spans_its_midpoint():
    df = _zone_frame()
    zones = liquidity_zones(df, atr_period=3, atr_mult=0.2)
    high_zone = zones[zones["side"] == "high"].iloc[0]
    # Vela 8: high 15.2 y low 14.2 -> cruza el punto medio (~15.14). La 9 tiene low 15.0 < mid.
    assert high_zone["mid"] < 15.2
    assert high_zone["mitigated_index"] == 8


def test_touching_the_zone_without_crossing_the_midpoint_does_not_mitigate():
    df = _zone_frame()
    df.loc[8, "high"] = 15.05
    df.loc[9, ["high", "low", "close"]] = [14.0, 13.0, 13.5]
    zones = liquidity_zones(df, atr_period=3, atr_mult=0.2)
    assert pd.isna(zones[zones["side"] == "high"].iloc[0]["mitigated_index"])


def test_no_zone_while_the_atr_does_not_exist_yet():
    df = _zone_frame()
    zones = liquidity_zones(df, atr_period=6, atr_mult=0.2)  # ATR desde la vela 5
    assert (zones["pivot_index"] >= 5).all()


def test_volume_ratio_compares_the_pivot_volume_with_the_recent_mean():
    zones = liquidity_zones(_zone_frame(), atr_period=3, atr_mult=0.2, volume_window=3)
    high_zone = zones[zones["side"] == "high"].iloc[0]
    # Ventana de 3 velas hasta la emision (4, 5, 6): volumenes 4, 1, 1 -> media 2.
    assert high_zone["volume_ratio"] == pytest.approx(4.0 / 2.0)


def test_without_volume_the_bar_range_is_the_proxy():
    df = _zone_frame().drop(columns="volume")
    zones = liquidity_zones(df, atr_period=3, atr_mult=0.2, volume_window=3)
    assert zones["volume_ratio"].notna().all()


def test_liquidity_zones_on_a_frame_without_pivots_is_empty_but_typed():
    df = pd.DataFrame({"high": [1.0, 2.0, 3.0], "low": [0.5, 1.5, 2.5], "close": [1.0, 2.0, 3.0]})
    zones = liquidity_zones(df, atr_period=1)
    assert zones.empty
    assert str(zones["mitigated_index"].dtype) == "Int64"


def test_liquidity_zones_rejects_a_non_positive_multiplier():
    with pytest.raises(ValueError):
        liquidity_zones(_zone_frame(), atr_mult=0.0)


def test_active_zones_at_excludes_unemitted_and_mitigated_zones():
    zones = liquidity_zones(_zone_frame(), atr_period=3, atr_mult=0.2)
    high = zones[zones["side"] == "high"]
    assert active_zones_at(high, 5).empty  # aun no emitida
    assert len(active_zones_at(high, 6)) == 1
    assert len(active_zones_at(high, 7)) == 1
    assert active_zones_at(high, 8).empty  # la vela que la mitiga ya la ve mitigada


@pytest.mark.parametrize(("interval", "expected"), [
    ("1m", 0.25), ("15m", 0.25), ("45m", 0.25), ("60m", 0.2), ("1h", 0.2), ("4h", 0.2),
    ("1d", 0.2), ("3d", 0.2), ("1w", 0.4), ("1M", 0.4),
])
def test_heatmap_atr_multiplier_follows_the_original_rule(interval, expected):
    assert heatmap_atr_multiplier(interval) == expected


@pytest.mark.parametrize("interval", ["", "h", "0h", "1x", "1 h 2"])
def test_heatmap_atr_multiplier_rejects_unknown_intervals(interval):
    with pytest.raises(ValueError):
        heatmap_atr_multiplier(interval)
