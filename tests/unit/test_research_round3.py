"""`app/research/round3.py`: FVG, filtros nuevos, salidas y entrada con orden limite."""

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
from app.research import round3 as r3
from app.strategies.base import Signal

HOUR_MS = 3_600_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % 86_400_000)


def _walk(n: int, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    open_ = np.concatenate(([close[0]], close[:-1]))
    spread = np.abs(rng.normal(0, 0.004, n)) * close
    return pd.DataFrame({
        "open_time": T0 + np.arange(n, dtype="int64") * HOUR_MS, "open": open_,
        "high": np.maximum(open_, close) + spread, "low": np.minimum(open_, close) - spread,
        "close": close, "funding_rate": rng.normal(0.0001, 0.0001, n),
    })


def test_fvg_long_signal_on_first_retest_with_stop_at_the_gap_floor():
    #          0     1     2(FVG: low 106 > high[0] 101)   3      4(retest)
    high = [101.0, 105.0, 110.0, 111.0, 109.0]
    low = [99.0, 100.5, 106.0, 107.0, 105.0]
    close = [100.0, 104.5, 109.0, 108.0, 107.0]
    df = pd.DataFrame({"high": high, "low": low, "close": close})
    out = r3.fvg_signals(df, pd.Series([1.0] * 5))
    assert list(out["fvg_long"]) == [False, False, False, False, True]
    assert out["fvg_sl_long"].iloc[4] == 101.0
    assert not out["fvg_short"].any()


def test_fvg_is_invalidated_by_a_close_through_the_gap():
    high = [101.0, 105.0, 110.0, 111.0, 104.0, 104.0]
    low = [99.0, 100.5, 106.0, 107.0, 99.0, 100.0]
    close = [100.0, 104.5, 109.0, 108.0, 100.0, 103.0]  # la vela 4 cierra bajo el piso (101)
    out = r3.fvg_signals(pd.DataFrame({"high": high, "low": low, "close": close}),
                         pd.Series([1.0] * 6))
    assert not out["fvg_long"].any()


def test_round3_features_are_causal_and_filters_need_btc_context():
    df = _walk(1600)
    r3._BTC_CONTEXT.clear()
    r3._R3_CACHE.clear()
    no_ctx = r3.compute_features_r3(df, "1h")
    assert not no_ctx["bull_btc"].any() and not no_ctx["bull_rs"].any()
    r3.set_btc_context("1h", _walk(1600, seed=99))
    full = r3.compute_features_r3(df, "1h")
    part = r3.compute_features_r3(df.iloc[:1000].reset_index(drop=True), "1h")
    for col in ("long_fvg", "short_fvg", "bull_fund", "bear_fund", "bull_btc", "bear_btc",
                "bull_rs", "bear_rs"):
        assert (full[col].iloc[:1000].to_numpy() == part[col].to_numpy()).all(), col
    assert full["bull_btc"].any() and full["bear_btc"].any() and full["bull_rs"].any()
    assert (full["long_fvg"] | full["short_fvg"]).any()
    r3._BTC_CONTEXT.clear()


def test_exit_grid_distances_and_names():
    df = _walk(1500, seed=5)
    r3._R3_CACHE.clear()
    f = r3.compute_features_r3(df, "1h")
    i = int(np.flatnonzero(f["long_wt_cross"].to_numpy()[600:])[0]) + 600
    sub = f.iloc[: i + 1]
    atr = float(f["x_atr14"].iloc[i])
    s = r3.Round3Strategy("wt_cross", exit_name="s15_tp3r", entry_mode="limit")
    assert s.name == "r3|wt_cross|nada|s15_tp3r|limit" and s.entry_mode == "limit"
    assert s.stop_price(sub, Signal.LONG, 100.0) == pytest.approx(100 - 1.5 * atr)
    assert s.take_profit_price(sub, Signal.LONG, 100.0) == pytest.approx(100 + 4.5 * atr)
    t = r3.Round3Strategy("wt_cross", exit_name="s2_trail2")
    assert t.take_profit_price(sub, Signal.LONG, 100.0) is None
    assert t.trailing_distance(sub) == pytest.approx(2 * atr)
    with pytest.raises(ValueError):
        r3.Round3Strategy("fvg", exit_name="nope")


@pytest.mark.asyncio
async def test_limit_entries_fill_at_the_signal_close_pay_maker_fee_and_can_miss(db):
    start = int(datetime(2023, 1, 1, tzinfo=UTC).timestamp() * 1000)
    step = interval_to_ms("1h")
    rng = random.Random(4)
    price, last, mark = 100.0, [], []
    for i in range(24 * 120):
        o, c = price, price * (1 + rng.uniform(-0.012, 0.012))
        h, low = max(o, c) * 1.003, min(o, c) * 0.997
        for rows, pt in ((last, "LAST_PRICE"), (mark, "MARK_PRICE")):
            rows.append(OHLCVBar(symbol="BTCUSDT", interval="1h", price_type=pt,
                                 open_time=start + i * step, open=o, high=h, low=low, close=c))
        price = c
    await ohlcv_repo.upsert_bars(db, last)
    await ohlcv_repo.upsert_bars(db, mark)
    settings = Settings(_env_file=None)
    end = start + 24 * 120 * step - 1
    market, _ = await run_backtest(db, r3.Round3Strategy("bb_reversal", exit_name="s2_tp1r"),
                                   "m", "BTCUSDT", "1h", start, end, settings)
    limit, _ = await run_backtest(
        db, r3.Round3Strategy("bb_reversal", exit_name="s2_tp1r", entry_mode="limit"),
        "l", "BTCUSDT", "1h", start, end, settings)
    assert market and limit
    closes = {b.open_time: b.close for b in last}
    for t in limit:
        entry_ms = int(t.entry_time.timestamp() * 1000)
        assert t.entry_price == pytest.approx(closes[entry_ms - step])
        assert t.fee_entry_usdt == pytest.approx(t.qty * t.entry_price * settings.maker_fee_pct)
    assert all(t.fee_entry_usdt == pytest.approx(t.qty * t.entry_price * settings.taker_fee_pct)
               for t in market)
