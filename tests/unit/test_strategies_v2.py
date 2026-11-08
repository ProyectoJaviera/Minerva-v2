"""Candidatos de la v2 (`app/candidates/`): senales, SL/TP a mano, calentamiento y causalidad."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.candidates import CANDIDATE_TIMEFRAMES, CANDIDATES, CONTROL_STRATEGIES
from app.candidates.camarilla_s3_r3 import CamarillaS3R3Strategy
from app.candidates.range_filter_flip import RangeFilterFlipEma144Strategy
from app.candidates.sfp_reversal import (
    ControlSfpRandomDirStrategy,
    SfpReversalStrategy,
    random_direction,
)
from app.indicators._pine import pine_atr
from app.indicators.levels import DAY_MS
from app.strategies.base import Signal
from app.strategies.registry import STRATEGIES

HOUR_MS = 3_600_000
DAY0 = 20_000 * DAY_MS


def test_candidates_are_the_four_preregistered_and_none_is_a_v1_strategy():
    assert set(CANDIDATES) == {
        "sfp_reversal_5_1", "camarilla_s3_r3", "range_filter_flip_ema144",
        "control_sfp_random_dir_seed42",
    }
    assert not set(CANDIDATES) & set(STRATEGIES)  # no estan registrados en la v1
    assert all(tfs == ["1h", "4h"] for tfs in CANDIDATE_TIMEFRAMES.values())
    assert CONTROL_STRATEGIES == {"control_sfp_random_dir_seed42"}
    assert all(strategy.name == name for name, strategy in CANDIDATES.items())


# --- sfp_reversal_5_1 -----------------------------------------------------------------------

# Escenario de tests/unit/test_indicators_v2_structure.py: SFP bajista confirmado en la vela 11,
# pivote 20, barrida con mecha en 21.
SFP_BARS = [
    (10.0, 10.5, 9.5, 10.0), (10.0, 11.0, 9.6, 10.5), (10.5, 12.0, 10.0, 11.0),
    (11.0, 13.0, 10.5, 12.0), (12.0, 14.0, 11.0, 13.0), (13.0, 20.0, 12.0, 18.0),
    (18.0, 18.5, 13.0, 14.0), (14.0, 16.0, 12.5, 15.0), (15.0, 19.0, 14.0, 18.0),
    (19.0, 21.0, 17.0, 19.5), (19.5, 19.6, 15.0, 16.0), (16.0, 16.5, 12.0, 12.4),
]


def _sfp_frame(rows=SFP_BARS):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["open_time"] = DAY0 + np.arange(len(df)) * HOUR_MS
    return df


def test_sfp_signals_short_on_the_confirmation_bar_and_reproduces_sl_and_tp_by_hand():
    strategy = SfpReversalStrategy(atr_period=3, warmup=0)
    df = strategy.precompute(_sfp_frame())
    assert strategy.evaluate(df.iloc[:11]) == Signal.HOLD
    assert strategy.evaluate(df) == Signal.SHORT
    atr = pine_atr(_sfp_frame(), 3).iloc[11]
    entry = 12.3  # open de la vela siguiente
    sl = strategy.stop_price(df, Signal.SHORT, entry)
    assert sl == pytest.approx(21.0 + 0.1 * atr)
    assert strategy.take_profit_price(df, Signal.SHORT, entry) == pytest.approx(
        entry - 2 * (sl - entry)
    )


def test_sfp_long_is_the_mirror():
    mirrored = [(100 - o, 100 - lo, 100 - h, 100 - c) for o, h, lo, c in SFP_BARS]
    strategy = SfpReversalStrategy(atr_period=3, warmup=0)
    df = strategy.precompute(_sfp_frame(mirrored))
    assert strategy.evaluate(df) == Signal.LONG
    atr = pine_atr(_sfp_frame(mirrored), 3).iloc[11]
    entry = 87.7
    sl = strategy.stop_price(df, Signal.LONG, entry)
    assert sl == pytest.approx(79.0 - 0.1 * atr)
    assert strategy.take_profit_price(df, Signal.LONG, entry) == pytest.approx(
        entry + 2 * (entry - sl)
    )


def test_sfp_declares_the_skip_rule_and_its_sl_is_on_the_wrong_side_after_a_gap():
    strategy = SfpReversalStrategy(atr_period=3, warmup=0)
    assert strategy.skip_entry_if_sl_crossed is True
    df = strategy.precompute(_sfp_frame())
    sl = strategy.stop_price(df, Signal.SHORT, 25.0)  # el open ya salto por encima de la mecha
    assert sl <= 25.0  # el motor omite la entrada


def test_sfp_warmup_blocks_early_signals():
    strategy = SfpReversalStrategy(atr_period=3, warmup=12)
    assert strategy.evaluate(strategy.precompute(_sfp_frame())) == Signal.HOLD


def test_sfp_without_a_signal_returns_the_entry_as_sl_so_the_entry_is_skipped():
    strategy = SfpReversalStrategy(atr_period=3, warmup=0)
    df = strategy.precompute(_sfp_frame()).iloc[:10]
    assert strategy.stop_price(df, Signal.SHORT, 19.0) == 19.0


# --- control ----------------------------------------------------------------------------------


def test_random_direction_is_deterministic_and_balanced():
    draws = [random_direction(42, DAY0 + i * HOUR_MS, 100.0 + i) for i in range(2000)]
    assert draws == [random_direction(42, DAY0 + i * HOUR_MS, 100.0 + i) for i in range(2000)]
    longs = sum(d == Signal.LONG for d in draws)
    assert 900 < longs < 1100
    # Otra semilla da otro sorteo (no es una funcion constante de la vela).
    other = [random_direction(7, DAY0 + i * HOUR_MS, 100.0 + i) for i in range(2000)]
    assert other != draws


def test_control_enters_on_the_same_bars_with_the_same_sl_distance():
    sfp = SfpReversalStrategy(atr_period=3, warmup=0)
    control = ControlSfpRandomDirStrategy(atr_period=3, warmup=0)
    df = control.precompute(_sfp_frame())
    for k in range(1, len(df) + 1):
        natural = sfp.evaluate(df.iloc[:k])
        drawn = control.evaluate(df.iloc[:k])
        assert (natural == Signal.HOLD) == (drawn == Signal.HOLD)
    drawn = control.evaluate(df)
    row = df.iloc[-1]
    assert drawn == random_direction(42, int(row["open_time"]), float(row["close"]))
    entry = 12.3
    natural_distance = abs(sfp.stop_price(df, Signal.SHORT, entry) - entry)
    sl = control.stop_price(df, drawn, entry)
    assert abs(sl - entry) == pytest.approx(natural_distance)
    assert (sl < entry) if drawn == Signal.LONG else (sl > entry)
    tp = control.take_profit_price(df, drawn, entry)
    assert abs(tp - entry) == pytest.approx(2 * natural_distance)


def test_control_skips_whenever_the_natural_sfp_would():
    control = ControlSfpRandomDirStrategy(atr_period=3, warmup=0)
    df = control.precompute(_sfp_frame())
    for side in (Signal.LONG, Signal.SHORT):
        assert control.stop_price(df, side, 25.0) == 25.0


def test_control_requires_open_time():
    control = ControlSfpRandomDirStrategy(atr_period=3, warmup=0)
    df = control.precompute(_sfp_frame()).drop(columns="open_time")
    with pytest.raises(ValueError, match="open_time"):
        control.evaluate(df)


# --- camarilla_s3_r3 --------------------------------------------------------------------------


def _camarilla_frame(day1_rows):
    """Dia 0: H 110, L 90, C 100 (S3 94.5, S4 89, R3 105.5, R4 111). Dia 1: filas dadas."""
    rows = []
    for h in range(24):
        rows.append((100.0, 110.0 if h == 5 else 101.0, 90.0 if h == 17 else 99.0,
                     100.0))
    rows.extend(day1_rows)
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["open_time"] = DAY0 + np.arange(len(df)) * HOUR_MS
    return df


def test_camarilla_long_on_the_first_s3_rejection_of_the_day_with_table_levels():
    day1 = [(100.0, 100.5, 99.5, 100.0)] * 3 + [(96.0, 96.5, 94.0, 95.0)] \
        + [(95.0, 95.5, 94.2, 95.1)] + [(100.0, 100.5, 99.5, 100.0)] * 19
    strategy = CamarillaS3R3Strategy(warmup=0)
    df = strategy.precompute(_camarilla_frame(day1))
    signals = [strategy.evaluate(df.iloc[:k]) for k in range(1, len(df) + 1)]
    assert [i for i, s in enumerate(signals) if s != Signal.HOLD] == [27]  # solo el primero
    assert signals[27] == Signal.LONG
    window = df.iloc[:28]
    assert strategy.stop_price(window, Signal.LONG, 95.1) == pytest.approx(89.0 * 0.99)
    assert strategy.take_profit_price(window, Signal.LONG, 95.1) == pytest.approx(105.5)


def test_camarilla_short_on_r3_rejection_with_table_levels():
    day1 = [(104.0, 106.0, 103.5, 105.0)] + [(100.0, 100.5, 99.5, 100.0)] * 23
    strategy = CamarillaS3R3Strategy(warmup=0)
    df = strategy.precompute(_camarilla_frame(day1))
    window = df.iloc[:25]
    assert strategy.evaluate(window) == Signal.SHORT
    assert strategy.stop_price(window, Signal.SHORT, 104.9) == pytest.approx(111.0 * 1.01)
    assert strategy.take_profit_price(window, Signal.SHORT, 104.9) == pytest.approx(94.5)


def test_camarilla_bar_touching_both_levels_gives_no_signal():
    day1 = [(100.0, 106.0, 94.0, 100.0)] + [(100.0, 100.5, 99.5, 100.0)] * 23
    strategy = CamarillaS3R3Strategy(warmup=0)
    df = strategy.precompute(_camarilla_frame(day1))
    assert all(strategy.evaluate(df.iloc[:k]) == Signal.HOLD for k in range(1, len(df) + 1))


def test_camarilla_needs_a_previous_day_and_respects_warmup():
    day1 = [(96.0, 96.5, 94.0, 95.0)] + [(100.0, 100.5, 99.5, 100.0)] * 23
    df = _camarilla_frame(day1)
    first_day_touch = df.copy()
    first_day_touch.loc[3, ["low", "close"]] = [80.0, 95.0]
    strategy = CamarillaS3R3Strategy(warmup=0)
    pre = strategy.precompute(first_day_touch)
    assert all(strategy.evaluate(pre.iloc[:k]) == Signal.HOLD for k in range(1, 25))
    late = CamarillaS3R3Strategy(warmup=30)
    assert late.evaluate(late.precompute(df).iloc[:25]) == Signal.HOLD


# --- range_filter_flip_ema144 ---------------------------------------------------------------


def _rf_row(buy=False, sell=False, close=100.0, ema=95.0, atr=2.0, bar_index=600):
    return pd.DataFrame([{
        "open": close, "high": close, "low": close, "close": close, "rf_buy": buy,
        "rf_sell": sell, "v2_ema144": ema, "v2_atr14": atr, "v2_bar_index": bar_index,
    }])


@pytest.mark.parametrize(("kwargs", "expected"), [
    ({"buy": True, "close": 100.0, "ema": 95.0}, Signal.LONG),
    ({"buy": True, "close": 90.0, "ema": 95.0}, Signal.HOLD),  # compra bajo la EMA
    ({"sell": True, "close": 90.0, "ema": 95.0}, Signal.SHORT),
    ({"sell": True, "close": 100.0, "ema": 95.0}, Signal.HOLD),  # venta sobre la EMA
    ({"buy": True, "close": 95.0, "ema": 95.0}, Signal.HOLD),  # igual a la EMA no cuenta
    ({"buy": True, "bar_index": 499}, Signal.HOLD),  # calentamiento
])
def test_range_filter_flip_filters_by_the_ema(kwargs, expected):
    assert RangeFilterFlipEma144Strategy().evaluate(_rf_row(**kwargs)) == expected


def test_range_filter_flip_sl_and_trailing_are_two_and_a_half_atr_without_own_tp():
    strategy = RangeFilterFlipEma144Strategy()
    df = _rf_row(atr=2.0)
    assert strategy.stop_price(df, Signal.LONG, 100.0) == pytest.approx(95.0)
    assert strategy.stop_price(df, Signal.SHORT, 100.0) == pytest.approx(105.0)
    assert strategy.trailing_distance(df) == pytest.approx(5.0)
    assert strategy.take_profit_price(df, Signal.LONG, 100.0) is None


# --- causalidad -------------------------------------------------------------------------------


def _random_series(n=1400, seed=31):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, n)))
    open_ = np.concatenate(([100.0], close[:-1]))
    df = pd.DataFrame({
        "open": open_, "high": np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n))),
        "low": np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n))), "close": close,
    })
    df["open_time"] = DAY0 + np.arange(n, dtype="int64") * HOUR_MS
    return df


@pytest.mark.parametrize("name", sorted(CANDIDATES))
def test_precompute_on_a_truncated_series_equals_the_full_series(name):
    strategy = CANDIDATES[name]
    df = _random_series()
    full = strategy.precompute(df)
    for k in (300, 777, 1100):
        pd.testing.assert_frame_equal(strategy.precompute(df.iloc[:k]), full.iloc[:k],
                                      check_exact=True)


@pytest.mark.parametrize("name", sorted(CANDIDATES))
def test_signals_do_not_change_when_future_bars_are_extreme(name):
    strategy = CANDIDATES[name]
    df = _random_series()
    k = 1000
    future = df.copy()
    future.loc[k:, ["open", "high", "low", "close"]] *= 40
    full = strategy.precompute(df)
    changed = strategy.precompute(future)
    original = [strategy.evaluate(full.iloc[:i]) for i in range(500, k)]
    assert original == [strategy.evaluate(changed.iloc[:i]) for i in range(500, k)]
