"""`app/research/round4.py`: fuerza relativa, squeeze, ADX, volumen, VWAP y salida por tiempo."""

from __future__ import annotations

import random
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from app.backtesting.engine import run_backtest
from app.config import Settings
from app.market.ohlcv_history import interval_to_ms
from app.persistence.models import OHLCVBar
from app.persistence.repositories import ohlcv_repo
from app.research import round4 as r4
from app.strategies.base import Signal

STEP = 4 * 3_600_000
MONDAY = int(datetime(2023, 1, 2, tzinfo=UTC).timestamp() * 1000)  # lunes 00:00 UTC


def _walk(n: int, seed: int, drift: float = 0.0, start: int = MONDAY) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    open_ = np.concatenate(([close[0]], close[:-1]))
    spread = np.abs(rng.normal(0, 0.004, n)) * close
    return pd.DataFrame({
        "open_time": start + np.arange(n, dtype="int64") * STEP, "open": open_,
        "high": np.maximum(open_, close) + spread, "low": np.minimum(open_, close) - spread,
        "close": close, "volume": rng.uniform(1e6, 2e6, n),
        "funding_rate": rng.normal(1e-4, 1e-4, n),
    })


def test_momentum_ranks_weekly_and_only_at_the_monday_close():
    n = 400
    series = {f"S{k}USDT": _walk(n, seed=k, drift=0.001 * (k - 4)) for k in range(8)}
    frame = pd.DataFrame({s: pd.Series(df["close"].to_numpy(), index=df["open_time"])
                          for s, df in series.items()})
    strong = r4.momentum_signals(frame, "S7USDT", 42, STEP)
    weak = r4.momentum_signals(frame, "S0USDT", 42, STEP)
    fired = strong.index[strong["mom_long"]]
    assert len(fired) > 0
    assert all(((t + STEP) - r4.MONDAY_OFFSET_MS) % r4.WEEK_MS == 0 for t in fired)
    assert strong["mom_long"].sum() > weak["mom_long"].sum()
    assert weak["mom_short"].sum() > strong["mom_short"].sum()
    assert not (strong["mom_long"] & strong["mom_short"]).any()


def test_momentum_needs_enough_ranked_symbols():
    series = {f"S{k}USDT": _walk(300, seed=k) for k in range(4)}
    frame = pd.DataFrame({s: pd.Series(df["close"].to_numpy(), index=df["open_time"])
                          for s, df in series.items()})
    sig = r4.momentum_signals(frame, "S0USDT", 42, STEP)
    assert not sig["mom_long"].any() and not sig["mom_short"].any()


def test_squeeze_fires_on_release_after_compression():
    calm = _walk(300, seed=1)
    calm.loc[100:160, ["open", "high", "low", "close"]] = 100.0
    calm.loc[100:160, "high"] = 100.01
    calm.loc[100:160, "low"] = 99.99
    calm.loc[161:, "close"] = 100 + np.arange(1, len(calm) - 160) * 0.8
    calm.loc[161:, "open"] = calm.loc[161:, "close"] - 0.5
    calm.loc[161:, "high"] = calm.loc[161:, "close"] + 0.3
    calm.loc[161:, "low"] = calm.loc[161:, "open"] - 0.3
    sq = r4.ttm_squeeze(calm)
    assert sq["sqz_on"].iloc[120:160].all()
    first = int(np.flatnonzero((sq["sqz_long"] | sq["sqz_short"]).to_numpy()[150:])[0]) + 150
    assert sq["sqz_long"].iloc[first]


def test_adx_is_bounded_and_high_in_a_steady_trend():
    df = _walk(600, seed=3)
    df["close"] = 100 + np.arange(600) * 0.5
    df["open"] = df["close"] - 0.3
    df["high"] = df["close"] + 0.2
    df["low"] = df["open"] - 0.2
    value = r4.adx(df).dropna()
    assert ((value >= 0) & (value <= 100)).all()
    assert value.iloc[-1] > 40


def test_weekly_vwap_resets_on_monday():
    df = _walk(100, seed=4)
    vwap = r4.weekly_vwap(df)
    typical = (df["high"] + df["low"] + df["close"]) / 3
    assert vwap.iloc[0] == pytest.approx(typical.iloc[0])
    week_start = 42  # 7 dias x 6 velas de 4h
    assert vwap.iloc[week_start] == pytest.approx(typical.iloc[week_start])


def test_round4_features_are_causal():
    universe = {f"S{k}USDT": _walk(1300, seed=k, drift=0.0005 * (k - 3)) for k in range(7)}
    r4.set_universe_context("4h", universe)
    df = universe["S2USDT"]
    full = r4.compute_features_r4(df, "4h")
    part = r4.compute_features_r4(df.iloc[:900].reset_index(drop=True), "4h")
    cols = [f"{p}_{t}" for t in ("mom42", "mom180", "squeeze") for p in ("long", "short")]
    cols += [f"{p}_{f}" for f in ("adx", "vol", "vwap") for p in ("bull", "bear")]
    for col in cols:
        assert (full[col].iloc[:900].to_numpy() == part[col].to_numpy()).all(), col
    assert full["long_mom42"].any() or full["short_mom42"].any()
    r4._UNIVERSE.clear()


def test_time_exit_variants_and_names():
    s = r4.Round4Strategy("mom42", ("btc",), exit_name="t42_sl45", entry_mode="limit")
    assert s.name == "r4|mom42|btc|t42_sl45|limit" and s.max_hold_bars == 42
    assert r4.Round4Strategy("squeeze", ("adx",), exit_name="s3_trail3").max_hold_bars is None
    with pytest.raises(ValueError):
        r4.Round4Strategy("mom42", exit_name="s3_trail3")
    with pytest.raises(ValueError):
        r4.Round4Strategy("squeeze", exit_name="t42_sl45")
    row = pd.Series({"x_atr14": 2.0})
    assert s._distance(row, 100.0) == pytest.approx(4.5)
    assert r4.Round4Strategy("mom180", exit_name="t42_s25")._distance(row, 100.0) == 5.0
    assert s.take_profit_price(pd.DataFrame({"long_squeeze": [False]}), Signal.LONG, 100) is None


class _HoldProbe(r4.Round4Strategy):
    """Largo en cada vela con SL lejano: solo la salida por tiempo puede cerrar."""

    def __init__(self) -> None:
        super().__init__("mom42", exit_name="t42_sl45")
        self.max_hold_bars = 5
        self.warmup = 0

    def precompute(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def evaluate(self, df: pd.DataFrame) -> Signal:
        return Signal.LONG

    def stop_price(self, df, side, entry_price):
        return entry_price * 0.96


@pytest.mark.asyncio
async def test_engine_closes_by_time_without_fallback_tp_and_reenters_next_bar(db):
    start = int(datetime(2023, 1, 1, tzinfo=UTC).timestamp() * 1000)
    step = interval_to_ms("4h")
    rng = random.Random(1)
    price, last, mark = 100.0, [], []
    for i in range(200):
        o, c = price, price * (1 + rng.uniform(-0.002, 0.004))
        h, low = max(o, c) * 1.001, min(o, c) * 0.999
        for rows, pt in ((last, "LAST_PRICE"), (mark, "MARK_PRICE")):
            rows.append(OHLCVBar(symbol="BTCUSDT", interval="4h", price_type=pt,
                                 open_time=start + i * step, open=o, high=h, low=low, close=c,
                                 quote_vol=1e6))
        price = c
    await ohlcv_repo.upsert_bars(db, last)
    await ohlcv_repo.upsert_bars(db, mark)
    trades, _ = await run_backtest(db, _HoldProbe(), "p", "BTCUSDT", "4h", start,
                                   start + 200 * step - 1, Settings(_env_file=None))
    timed = [t for t in trades if t.close_reason == "TIME"]
    assert len(timed) >= 30
    first = timed[0]
    assert (first.exit_time - first.entry_time).total_seconds() == 4 * 4 * 3600
    assert not any(t.close_reason == "TP" for t in trades)  # sin TP de respaldo
    assert (timed[1].entry_time - first.exit_time).total_seconds() == 4 * 3600
