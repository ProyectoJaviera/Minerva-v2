"""`scripts/run_backtest_v2.py`: combinaciones, reglas del preregistro y corrida de punta a punta.

La corrida usa velas sinteticas en una base temporal (fixture `db`), como el smoke test de la v1.
"""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime

import pytest

from app.backtesting.report import StrategyResult, run_full_backtest
from app.candidates import CANDIDATES
from app.config import Settings
from app.market.ohlcv_history import interval_to_ms
from app.persistence.models import BacktestVerdict, OHLCVBar
from app.persistence.repositories import backtest_repo, ohlcv_repo
from app.strategies.registry import STRATEGIES
from scripts import run_backtest_v2 as v2

START_MS = int(datetime(2023, 1, 1, tzinfo=UTC).timestamp() * 1000)
END_MS = START_MS + 120 * 86_400_000
SYMBOLS = ["BTCUSDT", "ETHUSDT"]


def _result(name: str, *, pf: float | None, discarded: bool = False,
            insufficient: bool = False) -> StrategyResult:
    verdict = BacktestVerdict(strategy=name, run_at=datetime(2026, 11, 10, tzinfo=UTC),
                              pf_oos_aggregate=pf, discarded=discarded,
                              evidence_insufficient=insufficient)
    return StrategyResult(name, verdict, 0, 0)


def test_build_combinations_gives_one_entry_per_candidate_and_timeframe():
    strategies, timeframes, controls = v2.build_combinations()
    assert len(strategies) == 2 * len(CANDIDATES)
    assert timeframes["sfp_reversal_5_1_1h"] == ["1h"]
    assert timeframes["camarilla_s3_r3_4h"] == ["4h"]
    assert controls == {"control_sfp_random_dir_seed42_1h", "control_sfp_random_dir_seed42_4h"}
    assert not set(strategies) & set(STRATEGIES)


def test_sfp_is_approved_only_if_it_beats_the_control_in_the_same_timeframe():
    results = [
        _result("sfp_reversal_5_1_1h", pf=1.5),
        _result("sfp_reversal_5_1_4h", pf=1.3),
        _result("control_sfp_random_dir_seed42_1h", pf=1.1, discarded=True),
        _result("control_sfp_random_dir_seed42_4h", pf=1.4, discarded=True),
        _result("camarilla_s3_r3_1h", pf=0.8, discarded=True),
        _result("range_filter_flip_ema144_4h", pf=None, insufficient=True),
    ]
    outcomes, suspicious = v2.apply_preregistration_rules(results)
    status = {o.name: o.status for o in outcomes}
    assert not suspicious
    assert status["sfp_reversal_5_1_1h"] == "APROBADO"
    assert status["sfp_reversal_5_1_4h"] == "DESCARTADO"
    assert status["control_sfp_random_dir_seed42_1h"] == "CONTROL (nunca se aprueba)"
    assert status["camarilla_s3_r3_1h"] == "DESCARTADO"
    assert status["range_filter_flip_ema144_4h"] == "EVIDENCIA INSUFICIENTE"


def test_a_control_that_passes_makes_the_round_suspicious():
    results = [
        _result("camarilla_s3_r3_4h", pf=1.6),
        _result("control_sfp_random_dir_seed42_1h", pf=1.3),
    ]
    outcomes, suspicious = v2.apply_preregistration_rules(results)
    status = {o.name: o.status for o in outcomes}
    assert suspicious
    assert status["camarilla_s3_r3_4h"] == "EN SUSPENSO (ronda sospechosa)"
    assert status["control_sfp_random_dir_seed42_1h"] == "CONTROL (nunca se aprueba)"


def test_crossed_sl_counter_reads_the_engine_log_line():
    counter = v2.CrossedSlCounter()
    log = logging.getLogger("test_v2_counter")
    log.addHandler(counter)
    log.setLevel(logging.INFO)
    try:
        log.info("%s %s %s: %d entradas omitidas porque el open ya habia cruzado el SL",
                 "sfp_reversal_5_1_1h", "BTCUSDT", "1h", 3)
        log.info("%s %s %s: %d entradas omitidas porque el open ya habia cruzado el SL",
                 "sfp_reversal_5_1_1h", "ETHUSDT", "1h", 2)
        log.info("otra linea cualquiera")
    finally:
        log.removeHandler(counter)
    assert counter.counts == {"sfp_reversal_5_1_1h": 5}


async def _seed(db, rng: random.Random) -> None:
    for symbol in SYMBOLS:
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


@pytest.mark.asyncio
async def test_candidates_run_end_to_end_and_save_one_verdict_per_combination(db):
    await _seed(db, random.Random(3))
    settings = Settings(
        _env_file=None, BACKTEST_CONTROL_SYMBOLS="BTCUSDT,ETHUSDT",
        BACKTEST_MIN_TRADES_TOTAL=1, BACKTEST_MIN_TRADES_PER_CELL=1,
        BACKTEST_PORTFOLIO_SIM_RUNS=5,
    )
    strategies, timeframes, _ = v2.build_combinations()
    results = await run_full_backtest(
        db, settings, SYMBOLS, START_MS, END_MS - 1,
        strategies=strategies, timeframes_by_strategy=timeframes, experimental=set(),
    )
    assert [r.strategy_name for r in results] == list(strategies)
    verdicts = await backtest_repo.get_verdicts(db)
    assert {v.strategy for v in verdicts} == set(strategies)
    outcomes, _ = v2.apply_preregistration_rules(results)
    assert len(outcomes) == len(strategies)
