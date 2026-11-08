"""Causalidad de los indicadores v2: ningun valor depende de una vela futura.

Dos pruebas por indicador, como las de fuga de `tests/unit/test_llm_market_features.py`:

1. **Serie truncada == serie completa**: calcular sobre las primeras `k` velas da exactamente lo
   mismo que las primeras `k` filas del calculo sobre la serie completa.
2. **Velas futuras extremas no cambian nada**: reemplazar todas las velas desde `k` por valores
   absurdos (precio x50 y /50, volumen x1000) no cambia ni un bit de las primeras `k` filas.

Las zonas de liquidez son una tabla de eventos: se compara la tabla truncada con la completa
filtrada a lo emitido hasta `k - 1`, con la mitigacion posterior a `k - 1` borrada.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.indicators.levels import camarilla_levels
from app.indicators.oscillators import bb_percent_b, wavetrend
from app.indicators.structure import liquidity_zones, pivot_high, pivot_low, sfp_signals
from app.indicators.trend_filters import range_filter, vidya_band

N = 1300
CUTS = [7, 150, 433, 801, 1299]


def _series(seed: int = 21) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, N)))
    open_ = np.concatenate(([100.0], close[:-1]))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, N)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, N)))
    return pd.DataFrame({
        "open_time": 19_000 * 86_400_000 + np.arange(N, dtype="int64") * 3_600_000,
        "open": open_, "high": high, "low": low, "close": close,
        "volume": rng.uniform(10, 100, N),
    })


def _with_extreme_future(df: pd.DataFrame, k: int) -> pd.DataFrame:
    future = df.copy()
    rows = future.index >= k
    spike = np.where(np.arange(N) % 2 == 0, 50.0, 1 / 50)[rows]
    for col in ("open", "close"):
        future.loc[rows, col] = future.loc[rows, col] * spike
    future.loc[rows, "high"] = future.loc[rows, ["open", "close"]].max(axis=1) * 3
    future.loc[rows, "low"] = future.loc[rows, ["open", "close"]].min(axis=1) / 3
    future.loc[rows, "volume"] = future.loc[rows, "volume"] * 1000
    return future


INDICATORS = {
    "pivot_high": lambda df: pivot_high(df["high"], 5, 1).to_frame(),
    "pivot_low": lambda df: pivot_low(df["low"], 2, 2).to_frame(),
    "sfp_signals": sfp_signals,
    "camarilla_levels": lambda df: camarilla_levels(df, interval_ms=3_600_000),
    "range_filter": lambda df: range_filter(df["close"]),
    "vidya_band": vidya_band,
    "bb_percent_b": lambda df: bb_percent_b(df["close"]),
    "wavetrend": wavetrend,
}


@pytest.fixture(scope="module")
def full_df() -> pd.DataFrame:
    return _series()


@pytest.fixture(scope="module")
def full_results(full_df):
    return {name: fn(full_df) for name, fn in INDICATORS.items()}


@pytest.mark.parametrize("name", sorted(INDICATORS))
@pytest.mark.parametrize("k", CUTS)
def test_truncated_series_equals_the_full_series(full_df, full_results, name, k):
    truncated = INDICATORS[name](full_df.iloc[:k].copy())
    pd.testing.assert_frame_equal(truncated, full_results[name].iloc[:k], check_exact=True)


@pytest.mark.parametrize("name", sorted(INDICATORS))
@pytest.mark.parametrize("k", CUTS)
def test_extreme_future_bars_do_not_change_the_past(full_df, full_results, name, k):
    changed = INDICATORS[name](_with_extreme_future(full_df, k))
    pd.testing.assert_frame_equal(
        changed.iloc[:k], full_results[name].iloc[:k], check_exact=True
    )


def test_the_full_series_produces_events_so_the_checks_are_not_vacuous(full_results):
    sfp = full_results["sfp_signals"]
    assert sfp["sfp_bear_signal"].sum() > 0 and sfp["sfp_bull_signal"].sum() > 0
    rf = full_results["range_filter"]
    assert rf["rf_buy"].sum() > 0 and rf["rf_sell"].sum() > 0
    assert full_results["vidya_band"]["vidya_flip_up"].sum() > 0
    assert full_results["camarilla_levels"]["cam_r1"].notna().sum() > 1000


def _zones_known_at(zones: pd.DataFrame, k: int) -> pd.DataFrame:
    known = zones[zones["emit_index"] <= k - 1].copy()
    late = known["mitigated_index"].notna() & (known["mitigated_index"] > k - 1)
    known.loc[late, "mitigated_index"] = pd.NA
    return known.reset_index(drop=True)


ZONE_KW = {"atr_period": 50, "atr_mult": 0.2}


@pytest.mark.parametrize("k", CUTS)
def test_liquidity_zones_truncated_equal_the_full_zones_known_at_that_bar(full_df, k):
    full = liquidity_zones(full_df, **ZONE_KW)
    truncated = liquidity_zones(full_df.iloc[:k].copy(), **ZONE_KW)
    pd.testing.assert_frame_equal(truncated, _zones_known_at(full, k), check_exact=True)


@pytest.mark.parametrize("k", CUTS)
def test_liquidity_zones_ignore_extreme_future_bars(full_df, k):
    full = liquidity_zones(full_df, **ZONE_KW)
    changed = liquidity_zones(_with_extreme_future(full_df, k), **ZONE_KW)
    pd.testing.assert_frame_equal(
        _zones_known_at(changed, k), _zones_known_at(full, k), check_exact=True
    )


def test_liquidity_zones_are_produced_and_some_get_mitigated(full_df):
    zones = liquidity_zones(full_df, **ZONE_KW)
    assert len(zones) > 50
    assert zones["mitigated_index"].notna().sum() > 10
    assert (zones["emit_index"] == zones["pivot_index"] + 2).all()
    assert (zones["mitigated_index"].dropna() > zones.loc[
        zones["mitigated_index"].notna(), "emit_index"]).all()
