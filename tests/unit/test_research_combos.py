"""`app/research/combos.py`: causalidad, Liquidity Grab, rechazos de zonas y salidas."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.research import combos as c
from app.strategies.base import Signal

HOUR_MS = 3_600_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % 86_400_000)


def _walk(n: int, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    open_ = np.concatenate(([close[0]], close[:-1]))
    spread = np.abs(rng.normal(0, 0.006, n)) * close
    return pd.DataFrame({
        "open_time": T0 + np.arange(n, dtype="int64") * HOUR_MS, "open": open_,
        "high": np.maximum(open_, close) + spread, "low": np.minimum(open_, close) - spread,
        "close": close,
    })


SIGNAL_COLUMNS = [f"{p}_{t}" for t in c.TRIGGERS for p in ("long", "short")] + \
    [f"{p}_{f}" for f in c.FILTERS for p in ("bull", "bear")]


def test_features_are_causal_truncated_equals_full():
    df = _walk(1400)
    c._FEATURE_CACHE.clear()
    full = c.compute_features(df, "1h")
    part = c.compute_features(df.iloc[:900].reset_index(drop=True), "1h")
    for col in SIGNAL_COLUMNS + ["x_atr14", "x_sfp_sl_long", "x_sfp_sl_short"]:
        a = full[col].iloc[:900].to_numpy()
        b = part[col].to_numpy()
        if a.dtype == bool:
            assert (a == b).all(), col
        else:
            np.testing.assert_allclose(a, b, equal_nan=True, err_msg=col)


def test_every_trigger_fires_somewhere_on_a_long_walk():
    c._FEATURE_CACHE.clear()
    f = c.compute_features(_walk(4000, seed=3), "1h")
    for t in c.TRIGGERS:
        assert (f[f"long_{t}"] | f[f"short_{t}"]).any(), t
        assert not (f[f"long_{t}"] & f[f"short_{t}"]).any(), t


def test_liquidity_grab_needs_more_than_six_counts_a_red_candle_and_a_30_bar_high():
    n = 40
    close = np.linspace(100, 140, n)  # sube siempre: el conteo alcista crece
    open_ = close - 0.5
    high = close + 1.0
    low = open_ - 1.0
    open_[-1], close[-1] = close[-2] + 2, close[-2] + 1  # ultima vela roja
    high[-1] = high[:-1].max() + 5  # maximo de 30 velas
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close})
    g = c.liquidity_grab(df)
    assert g["grab_short"].iloc[-1]
    assert not g["grab_short"].iloc[:-1].any()
    assert not g["grab_long"].any()


def test_zone_rejection_shorts_below_an_active_high_zone():
    df = _walk(1200, seed=11)
    zr = c.zone_rejections(df, "1h")
    zones = c.liquidity_zones(df, atr_mult=c.heatmap_atr_multiplier("1h"))
    i = int(np.flatnonzero(zr["zone_short"].to_numpy())[0])
    active = zones[(zones.side == "high") & (zones.emit_index < i)
                   & (zones.mitigated_index.fillna(10**9) > i)]
    assert ((df["high"].iloc[i] >= active.bottom) & (df["close"].iloc[i] < active.bottom)).any()


def test_combo_names_and_space():
    space = c.all_combinations()
    assert len(space) == 8 * 11 + 8
    assert len({s.name for s in space}) == len(space)
    assert c.ComboStrategy("sfp", ("wt", "ema")).name == "combo|sfp|ema+wt|native"
    assert c.ComboStrategy("grab", (), random_dir=True).name == "combo|grab|nada|atr|rnd"
    with pytest.raises(ValueError):
        c.ComboStrategy("nope")
    with pytest.raises(ValueError):
        c.ComboStrategy("sfp", ("nope",))


def test_atr_exit_is_two_atr_and_two_r():
    df = _walk(1500, seed=5)
    c._FEATURE_CACHE.clear()
    f = c.compute_features(df, "1h")
    s = c.ComboStrategy("wt_cross")
    i = int(np.flatnonzero(f["long_wt_cross"].to_numpy()[600:])[0]) + 600
    sub = f.iloc[: i + 1]
    atr = float(f["x_atr14"].iloc[i])
    assert s.evaluate(sub) == Signal.LONG
    sl = s.stop_price(sub, Signal.LONG, 100.0)
    tp = s.take_profit_price(sub, Signal.LONG, 100.0)
    assert sl == pytest.approx(100.0 - 2 * atr)
    assert tp == pytest.approx(100.0 + 4 * atr)
    assert s.trailing_distance(sub) is None


def test_filters_block_signals_against_the_trend():
    df = _walk(3000, seed=9)
    c._FEATURE_CACHE.clear()
    f = c.compute_features(df, "1h")
    plain = c.ComboStrategy("rf_flip")
    filt = c.ComboStrategy("rf_flip", ("ema",))
    longs_plain = longs_filt = 0
    for i in range(600, len(f)):
        row = f.iloc[i]
        longs_plain += plain.natural_side(row) == Signal.LONG
        if filt.natural_side(row) == Signal.LONG:
            longs_filt += 1
            assert row["bull_ema"]
    assert 0 < longs_filt <= longs_plain


def test_sfp_native_stop_beyond_the_wick_and_skip_if_crossed():
    df = _walk(3000, seed=2)
    c._FEATURE_CACHE.clear()
    f = c.compute_features(df, "1h")
    s = c.ComboStrategy("sfp")
    i = int(np.flatnonzero(f["long_sfp"].to_numpy()[600:])[0]) + 600
    sub = f.iloc[: i + 1]
    sl_ref = float(f["x_sfp_sl_long"].iloc[i])
    entry = sl_ref + 10
    assert s.stop_price(sub, Signal.LONG, entry) == pytest.approx(sl_ref)
    assert s.take_profit_price(sub, Signal.LONG, entry) == pytest.approx(entry + 20)
    assert s.stop_price(sub, Signal.LONG, sl_ref - 1) == sl_ref - 1  # cruzado => omitir
