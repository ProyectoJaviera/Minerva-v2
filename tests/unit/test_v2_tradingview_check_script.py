"""`scripts/v2_tradingview_check.py`: informe para comparar con TradingView, con un cliente FALSO.

Sin red: el cliente devuelve velas sinteticas con la forma de `/market/kline` y pagina hacia
atras como Bitunix (con `end_time`, velas de `open_time` estrictamente menor).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from app.indicators.levels import DAY_MS
from scripts import v2_tradingview_check as check

HOUR_MS = 3_600_000
DAY0 = 20_397 * DAY_MS  # 2025-11-05 00:00 UTC
NOW = DAY0 + 4 * DAY_MS + 30 * 60_000  # 2025-11-09 00:30: la vela de las 00:00 sigue abierta


class FakeClient:
    """Velas de 1h y 1d coherentes entre si (la diaria es el agregado de las horarias)."""

    def __init__(self) -> None:
        rng = np.random.default_rng(5)
        n = 24 * 4 + 1
        close = 100 + np.cumsum(rng.normal(0, 1, n))
        open_ = np.concatenate(([100.0], close[:-1]))
        self.hourly = [{
            "time": DAY0 + i * HOUR_MS, "open": open_[i], "high": max(open_[i], close[i]) + 0.5,
            "low": min(open_[i], close[i]) - 0.5, "close": close[i],
        } for i in range(n)]
        self.daily = []
        for d in range(5):
            bars = [b for b in self.hourly if (b["time"] - DAY0) // DAY_MS == d]
            self.daily.append({"time": DAY0 + d * DAY_MS, "open": bars[0]["open"],
                               "high": max(b["high"] for b in bars),
                               "low": min(b["low"] for b in bars), "close": bars[-1]["close"]})
        self.calls = 0

    async def get_kline(self, symbol, interval, end_time, limit, price_type):
        assert price_type == "LAST_PRICE"
        self.calls += 1
        rows = self.hourly if interval == "1h" else self.daily
        older = [r for r in rows if r["time"] < end_time]
        return [{k: str(v) for k, v in r.items()} for r in older[-limit:]]


@pytest.mark.asyncio
async def test_report_prints_camarilla_levels_and_matches_the_daily_candle():
    lines = await check.build_report(FakeClient(), ["BTCUSDT"], [date(2025, 11, 6)], 10, 500,
                                     NOW)
    text = "\n".join(lines)
    assert "Camarilla BTCUSDT" in text
    assert "2025-11-06: R4" in text and "S4" in text
    assert "-> coincide" in text


@pytest.mark.asyncio
async def test_report_says_so_when_the_previous_day_is_missing():
    lines = await check.build_report(FakeClient(), ["BTCUSDT"], [date(2025, 11, 5)], 10, 500,
                                     NOW)
    assert any("2025-11-05: sin datos completos del dia anterior" in line for line in lines)


@pytest.mark.asyncio
async def test_fetch_bars_paginates_backwards_and_drops_the_open_candle():
    client = FakeClient()
    df = await check.fetch_bars(client, "BTCUSDT", "1h", HOUR_MS, 50, NOW)
    assert df["open_time"].is_monotonic_increasing and df["open_time"].is_unique
    assert int(df["open_time"].iloc[-1]) + HOUR_MS <= NOW  # sin la vela en curso
    assert len(df) == len(client.hourly) - 1


def test_sfp_lines_list_the_sweep_and_confirmation_times():
    import pandas as pd

    rows = [
        (10.0, 10.5, 9.5, 10.0), (10.0, 11.0, 9.6, 10.5), (10.5, 12.0, 10.0, 11.0),
        (11.0, 13.0, 10.5, 12.0), (12.0, 14.0, 11.0, 13.0), (13.0, 20.0, 12.0, 18.0),
        (18.0, 18.5, 13.0, 14.0), (14.0, 16.0, 12.5, 15.0), (15.0, 19.0, 14.0, 18.0),
        (19.0, 21.0, 17.0, 19.5), (19.5, 19.6, 15.0, 16.0), (16.0, 16.5, 12.0, 12.4),
    ]
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["open_time"] = DAY0 + np.arange(len(df)) * HOUR_MS
    lines = check.sfp_lines("ETHUSDT", df, 10)
    assert lines[1].startswith("  confirmacion 2025-11-05 11:00  BAJISTA (corto)  "
                               "barrida 2025-11-05 09:00")
    assert "mecha 21.00" in lines[1]


def _walk(n: int, seed: int = 11):
    import pandas as pd

    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 2, n))
    open_ = np.concatenate(([100.0], close[:-1]))
    return pd.DataFrame({
        "open_time": DAY0 + np.arange(n) * HOUR_MS, "open": open_,
        "high": np.maximum(open_, close) + 1.0, "low": np.minimum(open_, close) - 1.0,
        "close": close,
    })


def test_weekly_from_daily_starts_on_monday_and_drops_the_open_week():
    import pandas as pd

    # 2025-11-03 fue lunes; 15 dias: dos semanas completas y una en curso.
    monday = 20_395 * DAY_MS
    days = pd.DataFrame({
        "open_time": monday + np.arange(15) * DAY_MS, "open": np.arange(15.0),
        "high": np.arange(15.0) + 10, "low": np.arange(15.0) - 10, "close": np.arange(15.0) + 1,
    })
    weekly = check.weekly_from_daily(days, monday + 15 * DAY_MS)
    assert list(weekly["open_time"]) == [monday, monday + 7 * DAY_MS]
    first = weekly.iloc[0]
    assert (first["open"], first["high"], first["low"], first["close"]) == (0.0, 16.0, -10.0, 7.0)


def test_rf_lines_list_every_flip_with_its_ema_side():
    from app.indicators.trend_filters import range_filter

    df = _walk(600)
    rf = range_filter(df["close"])
    flips = int((rf["rf_buy"] | rf["rf_sell"]).sum())
    assert flips > 0
    lines = check.rf_lines("BTCUSDT", df, 1000, "1h")
    assert lines[0].startswith("Range Filter BTCUSDT 1h")
    assert len(lines) == flips + 1
    assert all(("COMPRA" in s or "VENTA" in s) and "EMA144" in s and "ATR14" in s
               for s in lines[1:])
    assert all(s.endswith("-> senal del candidato") or s.endswith("(filtrada por EMA)")
               for s in lines[1:])


def test_bars_lines_print_the_last_candles():
    df = _walk(5)
    lines = check.bars_lines("ETHUSDT", df, 2, "4h")
    assert lines[0] == "Velas ETHUSDT 4h: ultimas 2 (hora UTC de apertura)"
    assert len(lines) == 3 and lines[-1].startswith("  2025-11-05 04:00  O ")


@pytest.mark.asyncio
async def test_report_without_camarilla_nor_sfp_only_lists_the_requested_sections():
    lines = await check.build_report(FakeClient(), ["BTCUSDT"], [], 0, 500, NOW, "1d", 0, 2)
    text = "\n".join(lines)
    assert "Camarilla" not in text and "SFP" not in text and "Range Filter" not in text
    assert "BTCUSDT: 4 velas de 1d" in text
    assert "Velas BTCUSDT 1d: ultimas 2" in text
