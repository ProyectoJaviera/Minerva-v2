"""Regresion del motor: las 6 estrategias de la v1 dan EXACTAMENTE las mismas operaciones.

La v2 cambio el motor (`app/backtesting/engine.py`) para sus candidatos: el DataFrame que recibe
`precompute` trae `open_time` y una estrategia puede pedir que se omita la entrada si el `open`
ya cruzo su SL (`skip_entry_if_sl_crossed`). Esta prueba demuestra que esos cambios no tocan a la
v1: corre las 6 estrategias registradas, en todos sus marcos, sobre una base sintetica
determinista (velas LAST y MARK distintas y eventos de funding con extremos) y compara la huella
SHA-256 de sus operaciones y entradas omitidas con la referencia guardada en
`tests/unit/golden/backtest_v1_trades.json`.

**La referencia se genero con el motor ANTERIOR a esos cambios** (commit `38accd7`, antes de
tocar `engine.py`) con `generate_reference()` de este archivo. No se regenera para que una prueba
vuelva a pasar: si falla, el cambio del motor altero el comportamiento de la v1.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import datetime
from enum import Enum
from pathlib import Path

import numpy as np
import pytest

from app.backtesting.engine import run_backtest
from app.config import Settings
from app.market.ohlcv_history import interval_to_ms
from app.persistence.database import Database
from app.persistence.models import OHLCVBar
from app.persistence.repositories import funding_repo, ohlcv_repo
from app.strategies.registry import STRATEGIES, STRATEGY_TIMEFRAMES

GOLDEN = Path(__file__).parent / "golden" / "backtest_v1_trades.json"
SYMBOL = "BTCUSDT"
BASE_MS = 1_640_995_200_000  # 2022-01-01 00:00 UTC
BARS = {"1h": 3000, "4h": 1500, "1d": 700}
FUNDING_STEP_MS = 8 * 3_600_000


def make_settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None, DEFAULT_MARGIN_USDT=10.0, LEVERAGE=10, TAKER_FEE_PCT=0.0006,
        MAX_SL_MARGIN_LOSS_PCT=50.0, BACKTEST_SLIPPAGE_BPS=5.0,
        BACKTEST_FALLBACK_SL_PCT=0.05, BACKTEST_FALLBACK_TP_PCT=0.10,
    )


def _bars(timeframe: str, seed: int) -> tuple[list[OHLCVBar], list[OHLCVBar]]:
    step = interval_to_ms(timeframe)
    n = BARS[timeframe]
    rng = np.random.default_rng(seed)
    vol = {"1h": 0.006, "4h": 0.012, "1d": 0.012}[timeframe]
    close = 30_000 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    open_ = np.concatenate(([30_000.0], close[:-1]))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    mark_shift = 1 + rng.normal(0, 0.0005, n)
    last, mark = [], []
    for i in range(n):
        t = BASE_MS + i * step
        last.append(OHLCVBar(symbol=SYMBOL, interval=timeframe, price_type="LAST_PRICE",
                             open_time=t, open=float(open_[i]), high=float(high[i]),
                             low=float(low[i]), close=float(close[i])))
        mark.append(OHLCVBar(symbol=SYMBOL, interval=timeframe, price_type="MARK_PRICE",
                             open_time=t, open=float(open_[i] * mark_shift[i]),
                             high=float(high[i] * mark_shift[i] * 1.0002),
                             low=float(low[i] * mark_shift[i] * 0.9998),
                             close=float(close[i] * mark_shift[i])))
    return last, mark


def _funding_events(end_ms: int) -> list[tuple[int, float]]:
    rng = np.random.default_rng(99)
    times = range(BASE_MS, end_ms, FUNDING_STEP_MS)
    events = []
    for t in times:
        rate = rng.normal(0.0001, 0.00015)
        if rng.random() < 0.05:
            rate += rng.choice([-1, 1]) * rng.uniform(0.0008, 0.002)
        events.append((t, float(rate)))
    return events


def _canonical(value):
    if dataclasses.is_dataclass(value):
        return {k: _canonical(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float):
        return repr(value)
    return value


def _fingerprint(items) -> str:
    payload = json.dumps([_canonical(x) for x in items], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


async def run_all() -> dict[str, dict[str, object]]:
    """Corre las 6 estrategias de la v1 en todos sus marcos sobre la base sintetica."""
    settings = make_settings()
    results: dict[str, dict[str, object]] = {}
    db = Database(":memory:")
    await db.connect()
    try:
        longest = max(BARS[tf] * interval_to_ms(tf) for tf in BARS)
        await funding_repo.upsert_funding(db, SYMBOL, _funding_events(BASE_MS + longest))
        for seed, timeframe in enumerate(sorted(BARS)):
            last, mark = _bars(timeframe, seed + 1)
            await ohlcv_repo.upsert_bars(db, last)
            await ohlcv_repo.upsert_bars(db, mark)
        for name in sorted(STRATEGIES):
            for timeframe in STRATEGY_TIMEFRAMES[name]:
                step = interval_to_ms(timeframe)
                end = BASE_MS + BARS[timeframe] * step
                trades, skipped = await run_backtest(
                    db, STRATEGIES[name], name, SYMBOL, timeframe, BASE_MS, end, settings,
                    now_ms=end + 10 * step,
                )
                results[f"{name}|{timeframe}"] = {
                    "trades": len(trades), "skipped": len(skipped),
                    "trades_sha256": _fingerprint(trades),
                    "skipped_sha256": _fingerprint(skipped),
                }
    finally:
        await db.close()
    return results


def generate_reference() -> None:  # pragma: no cover - se uso una sola vez, antes del cambio
    """Escribe la referencia. Solo se corrio con el motor anterior al cambio de la v2."""
    import asyncio

    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(asyncio.run(run_all()), indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")


@pytest.mark.asyncio
async def test_v1_strategies_produce_exactly_the_same_trades_as_before_the_v2_engine_changes():
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert await run_all() == expected


def test_the_reference_covers_the_six_v1_strategies_and_is_not_vacuous():
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    names = {key.split("|")[0] for key in expected}
    assert names == set(STRATEGIES) and len(names) == 6
    assert set(expected) == {f"{n}|{tf}" for n in STRATEGIES for tf in STRATEGY_TIMEFRAMES[n]}
    for key, row in expected.items():
        assert row["trades"] > 0, f"{key} no genero operaciones: la comparacion seria vacia"
