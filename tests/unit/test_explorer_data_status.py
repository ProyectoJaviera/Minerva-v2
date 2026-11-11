"""`app/explorer/data_status.py` y `GET /api/explorer/data-status` (solo lectura, sin red)."""

from __future__ import annotations

import asyncio
import os

from app.api.routes import explorer as route
from app.config import Settings
from app.explorer import data_status
from scripts import record_market_data as rec

NOW = 1_794_400_000_000


def _market(tmp_path):
    path = tmp_path / "market_v2.db"
    conn = rec.open_store(path)
    row = rec.summarize_depth({"bids": [["100", "2"]], "asks": [["101", "1"]]})
    for symbol, ts in (("BTCUSDT", NOW - 60_000), ("BTCUSDT", NOW - 2 * 86_400_000),
                       ("ETHUSDT", NOW - 30 * 60_000)):
        cols = ["symbol", "ts_ms", *row]
        conn.execute(f"INSERT INTO orderbook_snapshots ({', '.join(cols)}) VALUES "
                     f"({', '.join('?' for _ in cols)})", (symbol, ts, *row.values()))
    conn.execute("INSERT INTO funding_snapshots VALUES ('BTCUSDT', ?, 0.0001, '{}')",
                 (NOW - 3 * 3_600_000,))
    conn.execute("INSERT INTO fear_greed VALUES (?, 29, 'Fear', ?)",
                 (NOW - 3_600_000, NOW - 600_000))
    conn.execute("INSERT INTO capture_log VALUES (?, 'orderbook', 0, 'ETHUSDT: caido')",
                 (NOW - 1_000,))
    conn.commit()
    conn.close()
    return str(path)


def test_market_status_reports_freshness_counts_errors_and_latest_values(tmp_path):
    path = _market(tmp_path)
    before = os.path.getmtime(path)
    out = data_status.market_status(path, now_ms=NOW)
    assert out["available"] is True
    assert out["orderbook"]["stale"] is False
    assert out["orderbook"]["snapshots_24h"] == 2 and out["orderbook"]["symbols_24h"] == 2
    assert out["funding"]["stale"] is True  # 3 h > 2 h
    assert out["feargreed"]["value"] == 29 and out["feargreed"]["stale"] is False
    assert out["errors_24h"]["count"] == 1
    assert out["errors_24h"]["last"]["detail"] == "ETHUSDT: caido"
    by = {s["symbol"]: s for s in out["symbols"]}
    assert by["BTCUSDT"]["funding_rate"] == 0.0001 and by["ETHUSDT"]["funding_rate"] is None
    assert by["BTCUSDT"]["at"].startswith("2026")
    assert os.path.getmtime(path) == before


def test_status_without_files(tmp_path):
    assert data_status.market_status(str(tmp_path / "no.db"))["available"] is False
    assert data_status.history_status(str(tmp_path / "no.db"))["available"] is False


def test_route_combines_market_and_history(tmp_path):
    settings = Settings(_env_file=None, MARKET_DATA_DB=_market(tmp_path),
                        EXPLORER_HISTORY_DB=str(tmp_path / "no_history.db"))
    out = asyncio.run(route.data_status_route(settings=settings))
    assert out["market"]["available"] is True
    assert out["history"]["available"] is False
