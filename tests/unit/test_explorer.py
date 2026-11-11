"""Seccion «Indicadores» (exploratoria): validacion, archivo de solo lectura, limite reservado y
corrida de punta a punta con velas sinteticas en un archivo temporal."""

from __future__ import annotations

import os
import random
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.api.routes import explorer as route
from app.config import Settings
from app.explorer import service
from app.market.ohlcv_history import interval_to_ms
from app.persistence.database import Database
from app.persistence.models import OHLCVBar
from app.persistence.repositories import ohlcv_repo

START_MS = int(datetime(2026, 7, 20, tzinfo=UTC).timestamp() * 1000)
END_MS = int(datetime(2026, 10, 20, tzinfo=UTC).timestamp() * 1000)  # pasa el limite reservado


async def _build_history(path: str, symbols=("BTCUSDT", "ETHUSDT")) -> None:
    db = Database(path)
    await db.connect()
    rng = random.Random(7)
    try:
        for symbol in symbols:
            for interval in ("1h", "4h"):
                step = interval_to_ms(interval)
                price = 100.0
                last, mark = [], []
                for i in range((END_MS - START_MS) // step):
                    t = START_MS + i * step
                    o = price
                    c = price * (1 + rng.uniform(-0.015, 0.015))
                    h, low = max(o, c) * 1.004, min(o, c) * 0.996
                    for rows, pt in ((last, "LAST_PRICE"), (mark, "MARK_PRICE")):
                        rows.append(OHLCVBar(symbol=symbol, interval=interval, price_type=pt,
                                             open_time=t, open=o, high=h, low=low, close=c))
                    price = c
                await ohlcv_repo.upsert_bars(db, last)
                await ohlcv_repo.upsert_bars(db, mark)
    finally:
        await db.close()


@pytest.fixture
async def history(tmp_path) -> str:
    path = str(tmp_path / "history_v2.db")
    await _build_history(path)
    return path


def _settings(path: str) -> Settings:
    return Settings(_env_file=None, EXPLORER_HISTORY_DB=path)


def test_validate_request_normalizes_and_rejects_bad_input():
    req = service.validate_request([" btcusdt", "BTCUSDT", "ethusdt"], "1h", "sfp",
                                   ["rf", "ema"], "2024-01-01", "2025-01-01")
    assert req.symbols == ("BTCUSDT", "ETHUSDT")
    assert req.filters == ("ema", "rf")
    assert req.start_ms == int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
    bad = [
        ([], "1h", "sfp", [], None, None),
        (["BTCUSDT"], "15m", "sfp", [], None, None),
        (["BTCUSDT"], "1h", "nope", [], None, None),
        (["BTCUSDT"], "1h", "sfp", ["ema", "rf", "wt"], None, None),
        (["BTCUSDT"], "1h", "sfp", ["foo"], None, None),
        (["BTC/USDT"], "1h", "sfp", [], None, None),
        (["BTCUSDT"], "1h", "sfp", [], "2024-13-01", None),
        (["BTCUSDT"], "1h", "sfp", [], "2025-01-01", "2024-01-01"),
        ([f"S{i}USDT" for i in range(service.MAX_SYMBOLS + 1)], "1h", "sfp", [], None, None),
    ]
    for args in bad:
        with pytest.raises(service.ExplorerRequestError):
            service.validate_request(*args)


@pytest.mark.asyncio
async def test_options_without_history_file_says_how_to_create_it(tmp_path):
    out = await route.options(settings=_settings(str(tmp_path / "no_existe.db")))
    assert out["available"] is False
    assert "download_history" in out["detail"]
    assert {t["id"] for t in out["triggers"]} >= {"sfp", "camarilla", "rf_flip"}
    assert out["reserved_from"] == "2026-10-01"


@pytest.mark.asyncio
async def test_options_lists_series_only_before_the_reserved_date(history):
    out = await route.options(settings=_settings(history))
    assert out["available"] is True
    assert out["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert {(s["symbol"], s["timeframe"]) for s in out["series"]} == {
        (s, tf) for s in ("BTCUSDT", "ETHUSDT") for tf in ("1h", "4h")}
    assert all(s["last_day"] < "2026-10-01" for s in out["series"])


@pytest.mark.asyncio
async def test_history_file_is_opened_read_only_and_never_written(history):
    before = os.path.getmtime(history), os.path.getsize(history)
    db = service.ReadOnlyDatabase(history)
    await db.connect()
    try:
        with pytest.raises(Exception, match="readonly|read-only|read only"):
            await db.conn.execute("DELETE FROM ohlcv_cache")
    finally:
        await db.close()
    await route.run(**dict(symbols=["BTCUSDT"], timeframe="4h", trigger="rf_flip"),
                    settings=_settings(history))
    assert (os.path.getmtime(history), os.path.getsize(history)) == before
    assert not os.path.exists(history + "-wal")


@pytest.mark.asyncio
async def test_run_end_to_end_reports_winrate_control_and_never_uses_reserved_data(history):
    body = dict(symbols=["BTCUSDT", "ETHUSDT", "XRPUSDT"], timeframe="1h",
                                 trigger="rf_flip", filters=["ema"])
    out = await route.run(**body, settings=_settings(history))
    assert out["exploratory"] is True and "EXPLORATORIA" in out["note"]
    assert out["params"]["name"] == "combo|rf_flip|ema|native"
    assert out["period"]["end"] < "2026-10-01"
    res = out["result"]
    assert res["trades"] > 0
    assert 0.0 <= res["winrate"] <= 1.0
    assert res["longs"] + res["shorts"] == res["trades"]
    assert sum(r["trades"] for r in out["by_symbol"]) == res["trades"]
    assert {r["key"] for r in out["by_symbol"]} <= {"BTCUSDT", "ETHUSDT"}
    assert sum(r["trades"] for r in out["by_year"]) == res["trades"]
    assert out["control"]["trades"] > 0
    assert out["missing"] == [
        {"symbol": "XRPUSDT", "reason": "No esta en el archivo de historial."}]


@pytest.mark.asyncio
async def test_run_respects_requested_dates_and_reserved_limit(history):
    reserved_only = dict(symbols=["BTCUSDT"], timeframe="1h", trigger="sfp",
                                          start="2026-10-02")
    out = await route.run(**reserved_only, settings=_settings(history))
    assert out["result"]["trades"] == 0
    assert out["missing"][0]["reason"] == "Sin velas en el periodo pedido."


@pytest.mark.asyncio
async def test_run_errors_map_to_http_codes(tmp_path, history):
    with pytest.raises(HTTPException) as exc:
        await route.run(**dict(symbols=["BTCUSDT"], timeframe="1h",
                                              trigger="nope"), settings=_settings(history))
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        await route.run(**dict(symbols=["BTCUSDT"], timeframe="1h",
                                              trigger="sfp"),
                        settings=_settings(str(tmp_path / "no.db")))
    assert exc.value.status_code == 404


def test_summarize_handles_no_trades():
    s = service.summarize([], 100.0)
    assert s["trades"] == 0 and s["winrate"] is None and s["profit_factor"] is None


def test_update_history_file_refuses_the_bot_db_and_data_folder(tmp_path):
    from scripts.update_history_file import check_target

    bot = tmp_path / "minerva.db"
    assert check_target(str(tmp_path / "history" / "h.db"), str(bot)) == \
        (tmp_path / "history" / "h.db").resolve()
    for bad in (str(bot), str(tmp_path / "data" / "h.db"), str(tmp_path / "h.sqlite")):
        with pytest.raises(SystemExit):
            check_target(bad, str(bot))


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger,filters,rnd", [
    ("sfp", (), False), ("rf_flip", ("ema",), False), ("camarilla", ("wt",), False),
    ("bb_reversal", ("rf", "vidya"), False), ("sfp", ("ema",), True), ("grab", (), True),
])
async def test_fast_combo_gives_exactly_the_same_trades_as_combo_strategy(history, trigger,
                                                                          filters, rnd):
    from app.backtesting.engine import run_backtest
    from app.research.combos import ComboStrategy

    settings = _settings(history)
    db = service.ReadOnlyDatabase(history)
    await db.connect()
    try:
        out = []
        for cls in (ComboStrategy, service.FastComboStrategy):
            strat = cls(trigger, filters, random_dir=rnd)
            trades, skips = await run_backtest(db, strat, strat.name, "BTCUSDT", "1h", START_MS,
                                               service.RESERVED_FROM_MS - 1, settings)
            out.append(([(t.side, t.entry_time, t.exit_time, t.entry_price, t.exit_price,
                          t.close_reason, t.pnl_net_usdt) for t in trades], len(skips)))
    finally:
        await db.close()
    assert out[0] == out[1]


@pytest.mark.asyncio
async def test_a_repeated_run_comes_from_the_cache(history):
    body = dict(symbols=["ETHUSDT"], timeframe="4h", trigger="wt_cross")
    first = await route.run(**body, settings=_settings(history))
    second = await route.run(**body, settings=_settings(history))
    assert first["cached"] is False and second["cached"] is True
    assert {**first, "cached": True} == second


@pytest.mark.asyncio
async def test_fvg_and_round3_filters_run_and_are_listed(history):
    opts = await route.options(settings=_settings(history))
    assert "fvg" in {t["id"] for t in opts["triggers"]}
    assert {"fund", "btc", "rs"} <= {f["id"] for f in opts["filters"]}
    out = await route.run(symbols=["ETHUSDT"], timeframe="1h", trigger="fvg", filters=["btc"],
                          settings=_settings(history))
    assert out["params"]["name"] == "r3|fvg|btc|base|market"
    assert out["result"]["trades"] > 0
    assert out["control"]["trades"] > 0
    combo = await route.run(symbols=["ETHUSDT"], timeframe="1h", trigger="sfp", filters=["ema"],
                            settings=_settings(history))
    assert combo["params"]["name"] == "combo|sfp|ema|native"


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger,filters,rnd", [
    ("fvg", (), False), ("fvg", ("ema",), True), ("rf_flip", ("btc",), False),
    ("sfp", ("rs", "fund"), False),
])
async def test_fast_round3_gives_exactly_the_same_trades_as_round3(history, trigger, filters,
                                                                   rnd):
    from app.backtesting.engine import run_backtest
    from app.research.round3 import Round3Strategy

    settings = _settings(history)
    db = service.ReadOnlyDatabase(history)
    await db.connect()
    try:
        assert await service.load_btc_context(db, "1h")
        out = []
        for cls in (Round3Strategy, service.FastRound3Strategy):
            strat = cls(trigger, filters, random_dir=rnd)
            trades, skips = await run_backtest(db, strat, strat.name, "ETHUSDT", "1h", START_MS,
                                               service.RESERVED_FROM_MS - 1, settings)
            out.append(([(t.side, t.entry_time, t.exit_time, t.entry_price, t.exit_price,
                          t.close_reason, t.pnl_net_usdt) for t in trades], len(skips)))
    finally:
        await db.close()
    assert out[0] == out[1]
    assert out[0][0] or trigger != "fvg"
