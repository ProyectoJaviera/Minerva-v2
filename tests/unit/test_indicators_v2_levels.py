"""Niveles Camarilla del dia UTC anterior (`app/indicators/levels.py`)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.indicators.levels import DAY_MS, camarilla_from_hlc, camarilla_levels

HOUR_MS = 3_600_000
DAY0 = 20_000 * DAY_MS  # medianoche UTC


def _hourly_days(day_stats, start=DAY0):
    """Velas de 1h; cada dia tiene su maximo, minimo y cierre exactos."""
    rows = []
    for d, (high, low, close) in enumerate(day_stats):
        for h in range(24):
            mid = (high + low) / 2
            rows.append({
                "open_time": start + d * DAY_MS + h * HOUR_MS,
                "high": high if h == 5 else mid + 0.1,
                "low": low if h == 17 else mid - 0.1,
                "close": close if h == 23 else mid,
            })
    return pd.DataFrame(rows)


def test_camarilla_formula_matches_the_standard_multipliers():
    levels = camarilla_from_hlc(110.0, 90.0, 100.0)
    assert levels["r4"] == pytest.approx(111.0)
    assert levels["r3"] == pytest.approx(105.5)
    assert levels["r2"] == pytest.approx(100 + 22 / 6)
    assert levels["r1"] == pytest.approx(100 + 22 / 12)
    assert levels["s1"] == pytest.approx(100 - 22 / 12)
    assert levels["s2"] == pytest.approx(100 - 22 / 6)
    assert levels["s3"] == pytest.approx(94.5)
    assert levels["s4"] == pytest.approx(89.0)


def test_every_bar_of_a_day_uses_the_previous_utc_day():
    df = _hourly_days([(110.0, 90.0, 100.0), (130.0, 70.0, 120.0)])
    out = camarilla_levels(df)
    assert out.iloc[:24].isna().all().all()  # el primer dia no tiene dia anterior
    day1 = out.iloc[24:48]
    assert (day1["cam_prev_high"] == 110.0).all()
    assert (day1["cam_prev_low"] == 90.0).all()
    assert (day1["cam_prev_close"] == 100.0).all()
    assert day1["cam_r3"].iloc[0] == pytest.approx(105.5)
    assert day1["cam_s4"].iloc[-1] == pytest.approx(89.0)


def test_the_utc_day_boundary_is_midnight():
    df = _hourly_days([(110.0, 90.0, 100.0), (130.0, 70.0, 120.0), (1.0, 0.5, 0.7)])
    out = camarilla_levels(df)
    assert out["cam_prev_high"].iloc[47] == 110.0  # 23:00 del dia 1: aun el dia 0
    assert out["cam_prev_high"].iloc[48] == 130.0  # 00:00 del dia 2: ya el dia 1


def test_an_incomplete_previous_day_gives_no_levels_unless_allowed():
    df = _hourly_days([(110.0, 90.0, 100.0), (130.0, 70.0, 120.0)])
    df = df.drop(index=10).reset_index(drop=True)  # falta una vela del dia 0
    out = camarilla_levels(df, interval_ms=HOUR_MS)
    assert out.iloc[23:].isna().all().all()
    lenient = camarilla_levels(df, interval_ms=HOUR_MS, require_complete=False)
    assert lenient["cam_prev_high"].iloc[-1] == 110.0


def test_a_nan_close_makes_the_day_incomplete():
    df = _hourly_days([(110.0, 90.0, 100.0), (130.0, 70.0, 120.0)])
    df.loc[3, "close"] = np.nan
    out = camarilla_levels(df, interval_ms=HOUR_MS)
    assert out["cam_r1"].iloc[24:].isna().all()


def test_a_missing_previous_day_gives_no_levels():
    df = _hourly_days([(110.0, 90.0, 100.0), (130.0, 70.0, 120.0), (1.0, 0.5, 0.7)])
    df = df[(df["open_time"] < DAY0 + DAY_MS) | (df["open_time"] >= DAY0 + 2 * DAY_MS)]
    out = camarilla_levels(df.reset_index(drop=True), interval_ms=HOUR_MS)
    assert out.isna().all().all()


def test_daily_bars_use_the_previous_bar():
    df = pd.DataFrame({"open_time": [DAY0, DAY0 + DAY_MS], "high": [110.0, 1.0],
                       "low": [90.0, 0.5], "close": [100.0, 0.7]})
    out = camarilla_levels(df)
    assert out["cam_r4"].iloc[1] == pytest.approx(111.0)


def test_interval_that_does_not_divide_a_day_is_rejected():
    df = pd.DataFrame({"open_time": [DAY0, DAY0 + 7 * HOUR_MS], "high": [1.0, 1.0],
                       "low": [0.5, 0.5], "close": [0.7, 0.7]})
    with pytest.raises(ValueError, match="dividir"):
        camarilla_levels(df)


def test_unsorted_open_time_is_rejected():
    df = pd.DataFrame({"open_time": [DAY0 + HOUR_MS, DAY0], "high": [1.0, 1.0],
                       "low": [0.5, 0.5], "close": [0.7, 0.7]})
    with pytest.raises(ValueError, match="creciente"):
        camarilla_levels(df)


def test_missing_open_time_is_rejected():
    with pytest.raises(ValueError, match="open_time"):
        camarilla_levels(pd.DataFrame({"high": [1.0], "low": [0.5], "close": [0.7]}))


def test_empty_frame_returns_empty_levels():
    df = pd.DataFrame({"open_time": [], "high": [], "low": [], "close": []})
    assert camarilla_levels(df).empty
