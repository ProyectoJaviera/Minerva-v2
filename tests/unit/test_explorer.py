"""Seccion «Indicadores» (exploratoria): confluencia, validacion, archivo de solo lectura, corte y
corrida de punta a punta con velas sinteticas en un archivo temporal."""

from __future__ import annotations

import os
import random
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from app.api.routes import explorer as route
from app.config import Settings
from app.explorer import confluence, service
from app.market.ohlcv_history import interval_to_ms
from app.persistence.database import Database
from app.persistence.models import OHLCVBar
from app.persistence.repositories import ohlcv_repo
from app.strategies.base import Signal

START_MS = int(datetime(2026, 7, 20, tzinfo=UTC).timestamp() * 1000)
END_MS = int(datetime(2026, 10, 20, tzinfo=UTC).timestamp() * 1000)  # pasa el limite reservado


async def _build_history(path: str, symbols=("BTCUSDT", "ETHUSDT")) -> None:
    db = Database(path)
    await db.connect()
    rng = random.Random(7)
    try:
        for symbol in symbols:
            for interval in ("15m", "1h", "4h", "1d", "1w"):
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


def _run(history: str, **kw):
    kw.setdefault("window", confluence.DEFAULT_WINDOW)
    kw.setdefault("exit", confluence.DEFAULT_EXIT)
    return route.run(**kw, settings=_settings(history))


# --- confluencia -------------------------------------------------------------------------------


def test_event_votes_last_for_the_window_and_the_most_recent_side_wins():
    long_ev = np.array([0, 1, 0, 0, 0, 0, 0, 1, 0, 0], dtype=bool)
    short_ev = np.array([0, 0, 0, 0, 0, 0, 0, 0, 1, 0], dtype=bool)
    bull, bear = confluence.event_votes(long_ev, short_ev, 3)
    assert bull.astype(int).tolist() == [0, 1, 1, 1, 0, 0, 0, 1, 0, 0]
    assert bear.astype(int).tolist() == [0, 0, 0, 0, 0, 0, 0, 0, 1, 1]
    bull1, _ = confluence.event_votes(long_ev, short_ev, 1)
    assert bull1.tolist() == long_ev.tolist()
    both = np.array([1, 0], dtype=bool)
    b, r = confluence.event_votes(both, both, 5)
    assert not b.any() and not r.any()


def _features(bull_a, bear_a, long_b, short_b) -> pd.DataFrame:
    return pd.DataFrame({"bull_ema": bull_a, "bear_ema": bear_a,
                         "long_sfp": long_b, "short_sfp": short_b}).astype(bool)


def test_confluence_enters_when_all_selected_start_to_agree():
    f = _features([0, 1, 1, 1, 1, 0, 0, 0], [1, 0, 0, 0, 0, 1, 1, 1],
                  [0, 0, 0, 1, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0, 1, 0])
    long, short = confluence.confluence_signals(f, ["ema"], 1)
    assert long.astype(int).tolist() == [0, 1, 0, 0, 0, 0, 0, 0]  # un estado: entra al cambiar
    assert short.astype(int).tolist() == [1, 0, 0, 0, 0, 1, 0, 0]
    long, short = confluence.confluence_signals(f, ["ema", "sfp"], 2)
    assert long.astype(int).tolist() == [0, 0, 0, 1, 0, 0, 0, 0]  # EMA y SFP alcistas a la vez
    assert short.astype(int).tolist() == [0, 0, 0, 0, 0, 0, 1, 0]
    long, _ = confluence.confluence_signals(f, ["sfp"], 3)
    assert long.astype(int).tolist() == [0, 0, 0, 1, 0, 0, 0, 0]  # una senal, no cada vela


def test_a_single_state_indicator_enters_on_its_flips_like_the_range_filter_trigger():
    from app.research.combos import compute_features

    rng = random.Random(3)
    price, rows = 100.0, []
    for i in range(1500):
        c = price * (1 + rng.uniform(-0.02, 0.02))
        rows.append({"open_time": START_MS + i * 3_600_000, "open": price,
                     "high": max(price, c) * 1.003, "low": min(price, c) * 0.997, "close": c})
        price = c
    feats = compute_features(pd.DataFrame(rows), "1h")
    long, short = confluence.confluence_signals(feats, ["rf"], 1)
    assert long.tolist() == feats["long_rf_flip"].astype(bool).tolist()
    assert short.tolist() == feats["short_rf_flip"].astype(bool).tolist()


def test_strategy_validates_its_parameters():
    for kwargs in ({"indicators": []}, {"indicators": ["nope"]}, {"window": 0},
                   {"window": confluence.MAX_WINDOW + 1}, {"exit_name": "x"}, {"interval": "2h"}):
        args = {"indicators": ["ema"], "interval": "1h", **kwargs}
        with pytest.raises(ValueError):
            confluence.ConfluenceStrategy(args.pop("indicators"), args.pop("interval"), **args)
    s = confluence.ConfluenceStrategy(["rs", "sfp", "ema"], "4h", window=3, exit_name="s3_trail3")
    assert s.name == "mix|sfp+ema+rs|w3|s3_trail3"


# --- validacion y API --------------------------------------------------------------------------


def test_validate_request_normalizes_and_rejects_bad_input():
    req = service.validate_request([" btcusdt", "BTCUSDT", "ethusdt"], "15m",
                                   ["ema", "sfp", "fvg", "btc"], 4, "s1_tp2r",
                                   "2024-01-01", "2025-01-01")
    assert req.symbols == ("BTCUSDT", "ETHUSDT")
    assert req.indicators == ("sfp", "fvg", "ema", "btc")
    assert req.start_ms == int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
    every = service.validate_request(["BTCUSDT"], "1w", list(confluence.INDICATORS))
    assert len(every.indicators) == len(confluence.INDICATORS)
    bad = [
        ([], "1h", ["ema"]), (["BTCUSDT"], "2h", ["ema"]), (["BTCUSDT"], "1h", []),
        (["BTCUSDT"], "1h", ["foo"]), (["BTC/USDT"], "1h", ["ema"]),
        ([f"S{i}USDT" for i in range(service.MAX_SYMBOLS + 1)], "1h", ["ema"]),
    ]
    for args in bad:
        with pytest.raises(service.ExplorerRequestError):
            service.validate_request(*args)
    for kwargs in ({"window": 0}, {"exit_name": "x"}, {"start": "2024-13-01"},
                   {"start": "2025-01-01", "end": "2024-01-01"}):
        with pytest.raises(service.ExplorerRequestError):
            service.validate_request(["BTCUSDT"], "1h", ["ema"], **kwargs)


@pytest.mark.asyncio
async def test_options_without_history_file_says_how_to_create_it(tmp_path):
    out = await route.options(settings=_settings(str(tmp_path / "no_existe.db")))
    assert out["available"] is False
    assert "update_history_file" in out["detail"]
    assert {i["id"] for i in out["indicators"]} == set(confluence.INDICATORS)
    assert {i["kind"] for i in out["indicators"]} == {"estado", "evento"}
    assert [t["label"] for t in out["timeframes"]] == ["15m", "1h", "4h", "1D", "1S"]
    assert out["reserved_from"] == "2026-10-01"


@pytest.mark.asyncio
async def test_options_lists_series_only_before_the_reserved_date(history):
    out = await route.options(settings=_settings(history))
    assert out["available"] is True
    assert out["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert {(s["symbol"], s["timeframe"]) for s in out["series"]} == {
        (s, tf) for s in ("BTCUSDT", "ETHUSDT") for tf in service.TIMEFRAMES}
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
    await _run(history, symbols=["BTCUSDT"], timeframe="4h", indicators=["rf"])
    assert (os.path.getmtime(history), os.path.getsize(history)) == before
    assert not os.path.exists(history + "-wal")


@pytest.mark.asyncio
async def test_run_end_to_end_with_many_indicators_and_never_uses_reserved_data(history):
    out = await _run(history, symbols=["BTCUSDT", "ETHUSDT", "XRPUSDT"], timeframe="1h",
                     indicators=["rf", "ema"])
    assert out["exploratory"] is True and "EXPLORATORIA" in out["note"]
    assert out["params"]["name"] == "mix|rf+ema|w5|s2_tp2r"
    assert out["params"]["exit_label"] == "SL 2 ATR, TP 2R"
    assert out["period"]["end"] < "2026-10-01"
    res = out["result"]
    assert res["trades"] > 0
    assert 0.0 <= res["winrate"] <= 1.0
    assert res["longs"] + res["shorts"] == res["trades"]
    assert sum(r["trades"] for r in out["by_symbol"]) == res["trades"]
    assert sum(r["trades"] for r in out["by_year"]) == res["trades"]
    assert out["control"]["trades"] > 0
    assert out["missing"] == [
        {"symbol": "XRPUSDT", "reason": "No esta en el archivo de historial en este marco."}]
    every = await _run(history, symbols=["ETHUSDT"], timeframe="1h",
                       indicators=list(confluence.INDICATORS), window=10, exit="s3_trail3")
    assert len(every["params"]["indicators"]) == len(confluence.INDICATORS)
    assert every["result"]["trades"] >= 0


@pytest.mark.asyncio
async def test_run_works_in_15m_with_a_trailing_exit(history):
    out = await _run(history, symbols=["BTCUSDT"], timeframe="15m", indicators=["wt"],
                     exit="s2_trail2")
    assert out["result"]["trades"] > 0
    assert set(out["result"]["close_reasons"]) <= {"SL", "TRAILING", "TP", "END_OF_DATA",
                                                   "LIQUIDATION"}


@pytest.mark.asyncio
async def test_run_respects_requested_dates_and_reserved_limit(history):
    out = await _run(history, symbols=["BTCUSDT"], timeframe="1h", indicators=["sfp"],
                     start="2026-10-02")
    assert out["result"]["trades"] == 0
    assert out["missing"][0]["reason"] == "Sin velas en el periodo pedido."


@pytest.mark.asyncio
async def test_run_errors_map_to_http_codes(tmp_path, history):
    with pytest.raises(HTTPException) as exc:
        await _run(history, symbols=["BTCUSDT"], timeframe="1h", indicators=["nope"])
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        await route.run(symbols=["BTCUSDT"], timeframe="1h", indicators=["sfp"], window=5,
                        exit="s2_tp2r", settings=_settings(str(tmp_path / "no.db")))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_a_repeated_run_comes_from_the_cache(history):
    kw = {"symbols": ["ETHUSDT"], "timeframe": "4h", "indicators": ["wt_cross"]}
    first = await _run(history, **kw)
    second = await _run(history, **kw)
    assert first["cached"] is False and second["cached"] is True
    assert {**first, "cached": True} == second


@pytest.mark.asyncio
async def test_btc_and_rs_use_the_btc_series_of_the_same_timeframe(history):
    db = service.ReadOnlyDatabase(history)
    await db.connect()
    try:
        btc = await service.load_btc(db, "1h")
    finally:
        await db.close()
    assert btc is not None and len(btc) > 0
    assert btc["open_time"].max() < service.RESERVED_FROM_MS
    out = await _run(history, symbols=["ETHUSDT"], timeframe="1h", indicators=["btc", "rs"])
    assert out["params"]["indicators"] == ["btc", "rs"]


def test_summarize_handles_no_trades():
    s = service.summarize([], 100.0)
    assert s["trades"] == 0 and s["winrate"] is None and s["profit_factor"] is None


def test_update_history_file_refuses_the_bot_db_and_data_folder(tmp_path):
    from scripts.update_history_file import EXTRA_TIMEFRAMES, check_target

    assert set(EXTRA_TIMEFRAMES) == {"15m", "1w"}
    bot = tmp_path / "minerva.db"
    assert check_target(str(tmp_path / "history" / "h.db"), str(bot)) == \
        (tmp_path / "history" / "h.db").resolve()
    for bad in (str(bot), str(tmp_path / "data" / "h.db"), str(tmp_path / "h.sqlite")):
        with pytest.raises(SystemExit):
            check_target(bad, str(bot))


def test_min_agree_needs_that_many_votes_and_more_than_the_other_side():
    f = pd.DataFrame({"bull_ema": [0, 1, 1, 1], "bear_ema": [1, 0, 0, 0],
                      "bull_rf": [0, 0, 1, 1], "bear_rf": [1, 1, 0, 0],
                      "bull_wt": [0, 1, 0, 1], "bear_wt": [1, 0, 1, 0]}).astype(bool)
    long, short = confluence.confluence_signals(f, ["ema", "rf", "wt"], 1, min_agree=2)
    assert long.astype(int).tolist() == [0, 1, 0, 0]  # 2 de 3 alcistas desde la vela 1
    assert short.astype(int).tolist() == [1, 0, 0, 0]
    long_all, _ = confluence.confluence_signals(f, ["ema", "rf", "wt"], 1)
    assert long_all.astype(int).tolist() == [0, 0, 0, 1]
    s = confluence.ConfluenceStrategy(["ema", "rf", "wt"], "1h", min_agree=2)
    assert s.name.endswith("|k2")
    assert confluence.ConfluenceStrategy(["ema", "rf"], "1h", min_agree=2).min_agree is None
    with pytest.raises(ValueError):
        confluence.ConfluenceStrategy(["ema"], "1h", min_agree=2)
    with pytest.raises(service.ExplorerRequestError):
        service.validate_request(["BTCUSDT"], "1h", ["ema", "rf"], min_agree=3)
    assert service.validate_request(["BTCUSDT"], "1h", ["ema", "rf"], min_agree=0).min_agree is None


@pytest.mark.asyncio
async def test_all_indicators_with_a_minimum_agreement_still_trade(history):
    out = await _run(history, symbols=["BTCUSDT"], timeframe="1h",
                     indicators=list(confluence.INDICATORS), min_agree=5)
    assert out["params"]["min_agree"] == 5
    assert out["params"]["name"].endswith("|k5")
    assert out["result"]["trades"] > 0


def test_pct_exit_prices_and_validation():
    s = confluence.ConfluenceStrategy(["ema"], "1h", exit_name=confluence.PCT_EXIT,
                                      pct_exit=(2.0, 4.0, None))
    assert s.name == "mix|ema|w5|pct_sl2_tp4"
    df = pd.DataFrame({"open_time": [START_MS + i * 3_600_000 for i in range(600)],
                       "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0})
    feats = s.precompute(df)
    window = feats.iloc[:300]
    assert s.stop_price(window, Signal.LONG, 200.0) == pytest.approx(196.0)
    assert s.stop_price(window, Signal.SHORT, 200.0) == pytest.approx(204.0)
    assert s.take_profit_price(window, Signal.LONG, 200.0) == pytest.approx(208.0)
    assert s.take_profit_price(window, Signal.SHORT, 200.0) == pytest.approx(192.0)
    assert s.trailing_distance(window) is None
    t = confluence.ConfluenceStrategy(["ema"], "1h", exit_name=confluence.PCT_EXIT,
                                      pct_exit=(3.0, None, 1.5))
    t.precompute(df)
    assert t.take_profit_price(window, Signal.LONG, 200.0) is None
    assert t.trailing_distance(window) == pytest.approx(1.5)  # 1.5 % del cierre (100)
    assert t.name.endswith("pct_sl3_tr1.5")
    for bad in ((None, None, None), (0, None, None), (60, None, None), (2, 0, None),
                (2, 600, None), (2, None, 70), (float("nan"), None, None)):
        with pytest.raises(ValueError):
            confluence.check_pct_exit(*bad)
    assert confluence.pct_exit_label(2, None, None) == "SL 2 % (TP de respaldo del motor)"


@pytest.mark.asyncio
async def test_run_with_a_pct_exit(history):
    out = await _run(history, symbols=["BTCUSDT"], timeframe="1h", indicators=["rf"],
                     exit="pct", sl_pct=1.5, tp_pct=3, trail_pct=1)
    assert out["params"]["exit_label"] == "SL 1.5 %, TP 3 %, trailing 1 %"
    assert out["params"]["name"] == "mix|rf|w5|pct_sl1.5_tp3_tr1"
    assert out["result"]["trades"] > 0
    with pytest.raises(HTTPException) as exc:
        await _run(history, symbols=["BTCUSDT"], timeframe="1h", indicators=["rf"], exit="pct")
    assert exc.value.status_code == 400
    opts = await route.options(settings=_settings(history))
    assert "pct" in {x["id"] for x in opts["exits"]}
    assert opts["max_sl_pct_before_skip"] == 5.0


@pytest.mark.asyncio
async def test_weekly_runs_with_weekly_camarilla(history):
    out = await _run(history, symbols=["BTCUSDT"], timeframe="1w",
                     indicators=list(confluence.INDICATORS), min_agree=1)
    assert out["missing"] == []
    rng = random.Random(5)
    price, rows = 100.0, []
    for i in range(300):
        c = price * (1 + rng.uniform(-0.08, 0.08))
        rows.append({"open_time": START_MS + i * 604_800_000, "open": price,
                     "high": max(price, c) * 1.02, "low": min(price, c) * 0.98, "close": c})
        price = c
    feats = confluence.compute_votes(pd.DataFrame(rows), "1w")
    assert feats["open_time"].tolist() == [r["open_time"] for r in rows]
    assert feats["cam_r3"].notna().sum() > 250
