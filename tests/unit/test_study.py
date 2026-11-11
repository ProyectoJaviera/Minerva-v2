"""Pestana «Estudio» (v2): prueba hacia adelante compartida y su ruta de solo lectura con cache."""

from __future__ import annotations

import os
import random
import time
from datetime import UTC, datetime

import pytest

from app.api.routes import study as route
from app.config import Settings
from app.explorer.service import ReadOnlyDatabase
from app.market.ohlcv_history import interval_to_ms
from app.persistence.database import Database
from app.persistence.models import OHLCVBar
from app.persistence.repositories import ohlcv_repo
from app.research import forward, study_summary

# Velas ya cerradas (el motor descarta las que pasan de "ahora"): la prueba corre las fechas de
# inicio al 2026-07-01 para tener varios meses "hacia adelante".
START = int(datetime(2025, 9, 1, tzinfo=UTC).timestamp() * 1000)
END = int(datetime(2026, 11, 1, tzinfo=UTC).timestamp() * 1000)
FAKE_START = datetime(2026, 7, 1, tzinfo=UTC)
SYMBOLS = ("BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "TRXUSDT")


async def _build(path: str, symbols=SYMBOLS) -> None:
    db = Database(path)
    await db.connect()
    rng = random.Random(3)
    step = interval_to_ms("4h")
    try:
        for symbol in symbols:
            price = 100.0
            last, mark = [], []
            for i in range((END - START) // step):
                t = START + i * step
                o = price
                c = price * (1 + rng.uniform(-0.006, 0.006))  # bajo el tope con SL de 3 ATR
                h, low = max(o, c) * 1.002, min(o, c) * 0.998
                for rows, pt in ((last, "LAST_PRICE"), (mark, "MARK_PRICE")):
                    rows.append(OHLCVBar(symbol=symbol, interval="4h", price_type=pt, open_time=t,
                                         open=o, high=h, low=low, close=c, quote_vol=1e6))
                price = c
            await ohlcv_repo.upsert_bars(db, last)
            await ohlcv_repo.upsert_bars(db, mark)
            for pt in ("LAST_PRICE", "MARK_PRICE"):  # como lo deja update_history_file.py
                await ohlcv_repo.set_floor(db, symbol, "4h", pt, START)
                await ohlcv_repo.mark_series_complete(db, symbol, "4h", pt, START, END)
    finally:
        await db.close()


@pytest.fixture
async def history(tmp_path) -> str:
    path = str(tmp_path / "history_v2.db")
    await _build(path)
    return path


def _settings(path: str) -> Settings:
    return Settings(_env_file=None, EXPLORER_HISTORY_DB=path)


@pytest.fixture(autouse=True)
def _early_starts(monkeypatch):
    monkeypatch.setattr(forward, "R3_START", FAKE_START)
    monkeypatch.setattr(forward, "R4_START", FAKE_START)


@pytest.fixture(autouse=True)
def _reset_cache():
    route._state.update(key=None, result=None, computing=False, error=None)
    yield
    route._state.update(key=None, result=None, computing=False, error=None)


def test_review_state_follows_the_fixed_criterion():
    last = datetime(2026, 12, 1, tzinfo=UTC)
    few = {"trades": 10, "pf": 3.0}
    assert forward.review_state(few, {"pf": 0.5}, last) == {"due": False, "verdict": "en curso"}
    many = {"trades": 60, "pf": 1.3}
    assert forward.review_state(many, {"pf": 1.0}, last)["verdict"] == "sigue en estudio"
    assert forward.review_state(many, {"pf": 1.4}, last)["verdict"] == "descartada"
    assert forward.review_state({"trades": 60, "pf": 1.1}, {"pf": 0.5}, last)["verdict"] == \
        "descartada"
    late = forward.review_state({"trades": 5, "pf": 1.5}, {"pf": None}, forward.REVIEW_DATE)
    assert late == {"due": True, "verdict": "sigue en estudio"}


def test_trade_stats_without_trades():
    assert forward.trade_stats([]) == {"trades": 0, "pf": None, "pnl_usdt": 0, "win_rate_pct": None}


def test_tracked_strategies_are_the_four_frozen_ones():
    names = [t.strategy.name for t in forward.tracked()]
    assert names == ["r3|vidya_flip|btc|s3_trail3|limit", "r3|fvg|ema|s3_trail3|limit",
                     "r3|rf_flip|ema|s3_trail3|limit", "r4|mom42|nada|t42_s25|limit"]
    assert all(t.control.name.endswith("|rnd") for t in forward.tracked())


@pytest.mark.asyncio
async def test_compute_forward_counts_only_trades_after_each_start(history):
    db = ReadOnlyDatabase(history)
    await db.connect()
    try:
        out = await forward.compute_forward(db, _settings(history))
    finally:
        await db.close()
    assert out["available"] is True
    assert out["data_until"].startswith("2026-11-01")
    assert set(out["stale_symbols"]) == set(forward.SYMBOLS) - set(SYMBOLS)
    assert len(out["strategies"]) == 4
    for s in out["strategies"]:
        assert s["start"] == "2026-07-01"
        assert all(t["entry_time"] >= s["start"] for t in s["trade_list"])
        assert s["stats"]["trades"] == len(s["trade_list"])
        last = datetime.fromisoformat(out["data_until"])
        assert s["review"] == forward.review_state(s["stats"], s["control"], last)
    by_name = {s["name"]: s for s in out["strategies"]}
    assert sum(s["stats"]["trades"] for s in out["strategies"]) > 0
    assert by_name["r4|mom42|nada|t42_s25|limit"]["stats"]["trades"] > 0  # fuerza relativa con 7


@pytest.mark.asyncio
async def test_route_without_history_file_says_how_to_create_it(tmp_path):
    out = await route.forward(settings=_settings(str(tmp_path / "no_existe.db")))
    assert out["status"] == "missing"
    assert "update_history_file" in out["detail"]
    assert out["rounds"] == list(study_summary.ROUNDS)


@pytest.mark.asyncio
async def test_route_computes_in_background_caches_and_never_writes(history):
    before = os.path.getmtime(history), os.path.getsize(history)
    first = await route.forward(settings=_settings(history))
    assert first["status"] == "computing"
    deadline = time.time() + 120
    out = first
    while out["status"] == "computing" and time.time() < deadline:
        time.sleep(0.5)
        out = await route.forward(settings=_settings(history))
    assert out["status"] == "ready"
    assert len(out["result"]["strategies"]) == 4
    assert "computed_at" in out["result"]
    again = await route.forward(settings=_settings(history))
    assert again["status"] == "ready" and again["result"] is out["result"]  # desde la cache
    assert (os.path.getmtime(history), os.path.getsize(history)) == before
    assert not os.path.exists(history + "-wal")
