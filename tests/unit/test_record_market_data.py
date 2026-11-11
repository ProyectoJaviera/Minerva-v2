"""`scripts/record_market_data.py` y el reemplazo seguro de `update_history_file.py` (sin red)."""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from scripts import record_market_data as rec
from scripts.update_history_file import replace_with_retries


def test_summarize_depth_computes_mid_spread_tiers_and_imbalance():
    depth = {"bids": [["99", "2"], ["98", "3"], ["100", "1"]],
             "asks": [["101", "4"], ["102", "1"], ["bad", "x"]]}
    row = rec.summarize_depth(depth)
    assert row["best_bid"] == 100 and row["best_ask"] == 101
    assert row["mid"] == 100.5
    assert row["spread_bps"] == pytest.approx(1 / 100.5 * 10_000)
    assert row["bid_qty_5"] == 6 and row["ask_qty_5"] == 5
    assert row["imbalance_5"] == pytest.approx(1 / 11)
    assert row["bid_notional_50"] == pytest.approx(100 + 99 * 2 + 98 * 3)
    assert json.loads(row["bids_json"])[0] == [100.0, 1.0]
    assert rec.summarize_depth({"bids": [], "asks": [["1", "1"]]}) is None


def test_store_schema_and_universe_fallback(tmp_path):
    conn = rec.open_store(tmp_path / "m" / "market.db")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"orderbook_snapshots", "funding_snapshots", "fear_greed", "capture_log"} <= tables
    conn.close()
    assert rec.universe_symbols(str(tmp_path / "no.db")) == list(rec.FALLBACK_SYMBOLS)


def test_universe_symbols_read_the_history_file(tmp_path):
    path = tmp_path / "h.db"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE ohlcv_cache (symbol TEXT, interval TEXT)")
        c.executemany("INSERT INTO ohlcv_cache VALUES (?, ?)",
                      [("ETHUSDT", "1d"), ("BTCUSDT", "1d"), ("XRPUSDT", "1h")])
    assert rec.universe_symbols(str(path)) == ["BTCUSDT", "ETHUSDT"]


def test_check_target_refuses_the_bot_db_and_data(tmp_path):
    bot = tmp_path / "minerva.db"
    for bad in (str(bot), str(tmp_path / "data" / "m.db")):
        with pytest.raises(SystemExit):
            rec.check_target(bad, str(bot))


class _FakeClient:
    def __init__(self, fail: set[str]) -> None:
        self.fail = fail

    async def get_depth(self, symbol, limit=None):
        if symbol in self.fail:
            raise RuntimeError("caido")
        return {"bids": [["10", "1"]], "asks": [["11", "1"]]}

    async def get_funding_rate_batch(self):
        return [{"symbol": "BTCUSDT", "fundingRate": "0.0001"}, {"symbol": "DOGEUSDT"},
                {"symbol": "XXXUSDT", "fundingRate": "1"}]

    async def aclose(self):
        return None


def test_record_orderbook_and_funding_keep_going_on_errors(tmp_path, monkeypatch):
    import app.market.bitunix_rest as rest

    monkeypatch.setattr(rest, "BitunixRestClient", lambda **kw: _FakeClient({"ETHUSDT"}))
    conn = rec.open_store(tmp_path / "market.db")
    assert asyncio.run(rec.record_orderbook(conn, ["BTCUSDT", "ETHUSDT", "SOLUSDT"])) == 2
    assert asyncio.run(rec.record_funding(conn, ["BTCUSDT", "DOGEUSDT"])) == 2
    log = conn.execute("SELECT kind, ok, detail FROM capture_log ORDER BY rowid").fetchall()
    assert log[0][0] == "orderbook" and log[0][1] == 0 and "ETHUSDT" in log[0][2]
    assert log[1] == ("funding", 1, "2 simbolos")
    rates = dict(conn.execute("SELECT symbol, funding_rate FROM funding_snapshots").fetchall())
    assert rates == {"BTCUSDT": 0.0001, "DOGEUSDT": None}
    conn.close()


def test_replace_with_retries_retries_then_gives_up(tmp_path, monkeypatch):
    src, dst = tmp_path / "a_next.db", tmp_path / "a.db"
    src.write_text("nuevo")
    dst.write_text("viejo")
    assert replace_with_retries(src, dst, sleep=lambda s: None)
    assert dst.read_text() == "nuevo" and not src.exists()
    src.write_text("otro")
    calls = []

    def locked(a, b):
        calls.append(1)
        raise PermissionError("abierto")

    monkeypatch.setattr("os.replace", locked)
    assert not replace_with_retries(src, dst, attempts=3, sleep=lambda s: None)
    assert len(calls) == 3 and src.exists()
