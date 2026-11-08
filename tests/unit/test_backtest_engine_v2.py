"""Cambios del motor para la v2 y prueba de punta a punta de los candidatos (datos sinteticos).

1. `open_time` llega a `precompute`.
2. `skip_entry_if_sl_crossed`: solo la estrategia que lo declara omite la entrada si el `open`
   ya cruzo su SL; sin el atributo, el comportamiento es el de siempre.
3. Los cuatro candidatos corren de punta a punta en el motor real (base en memoria con velas
   sinteticas): el pipeline funciona. NO es un backtest: no hay datos de mercado.
"""

from __future__ import annotations

import pytest

from app.backtesting.engine import run_backtest
from app.candidates import CANDIDATES
from app.market.ohlcv_history import interval_to_ms
from app.persistence.models import OHLCVBar
from app.persistence.repositories import ohlcv_repo
from app.strategies.base import BaseStrategy, Signal
from tests.unit.test_backtest_v1_regression import BARS, SYMBOL, _bars, make_settings

BASE_MS = 1_700_000_000_000
STEP = interval_to_ms("4h")


def _flat(n: int, price: float, price_type: str) -> list[OHLCVBar]:
    return [OHLCVBar(symbol="ETHUSDT", interval="4h", price_type=price_type,
                     open_time=BASE_MS + i * STEP, open=price, high=price * 1.001,
                     low=price * 0.999, close=price) for i in range(n)]


class _Probe(BaseStrategy):
    """Senal LONG en la vela 70 con un SL fijo; registra las columnas de `precompute`."""

    name = "probe"

    def __init__(self, sl: float, skip: bool) -> None:
        self.sl = sl
        self.seen_columns: list[str] = []
        if skip:
            self.skip_entry_if_sl_crossed = True

    def precompute(self, df):
        self.seen_columns = list(df.columns)
        self.first_open_time = int(df["open_time"].iloc[0])
        return df

    def evaluate(self, df) -> Signal:
        return Signal.LONG if len(df) - 1 == 70 else Signal.HOLD

    def stop_price(self, df, side, entry_price):
        return self.sl


async def _run(db, strategy):
    await ohlcv_repo.upsert_bars(db, _flat(120, 100.0, "LAST_PRICE"))
    await ohlcv_repo.upsert_bars(db, _flat(120, 100.0, "MARK_PRICE"))
    end = BASE_MS + 120 * STEP
    return await run_backtest(db, strategy, strategy.name, "ETHUSDT", "4h", BASE_MS, end,
                              make_settings(), now_ms=end + 10 * STEP)


@pytest.mark.asyncio
async def test_precompute_receives_open_time_in_ms(db):
    probe = _Probe(sl=97.0, skip=False)
    await _run(db, probe)
    assert probe.seen_columns[-1] == "open_time"
    assert probe.first_open_time == BASE_MS


@pytest.mark.asyncio
async def test_a_strategy_that_declares_the_rule_skips_an_entry_whose_sl_is_already_crossed(db):
    trades, skipped = await _run(db, _Probe(sl=101.0, skip=True))  # SL por encima del open
    assert trades == [] and skipped == []


@pytest.mark.asyncio
async def test_a_valid_sl_still_opens_when_the_rule_is_declared(db):
    trades, _ = await _run(db, _Probe(sl=97.0, skip=True))
    assert len(trades) == 1


@pytest.mark.asyncio
async def test_without_the_attribute_the_engine_behaves_as_before(db):
    # Comportamiento de siempre: la entrada se abre con el SL pedido aunque este cruzado y la
    # propia vela de entrada la cierra.
    trades, _ = await _run(db, _Probe(sl=101.0, skip=False))
    assert len(trades) == 1 and trades[0].close_reason == "SL"


@pytest.mark.asyncio
@pytest.mark.parametrize("timeframe", ["1h", "4h"])
async def test_every_candidate_runs_end_to_end_in_the_real_engine(db, timeframe):
    last, mark = _bars(timeframe, seed=7)
    await ohlcv_repo.upsert_bars(db, last)
    await ohlcv_repo.upsert_bars(db, mark)
    step = interval_to_ms(timeframe)
    start = last[0].open_time
    end = start + BARS[timeframe] * step
    counts = {}
    for name, strategy in CANDIDATES.items():
        trades, _ = await run_backtest(db, strategy, name, SYMBOL, timeframe, start, end,
                                       make_settings(), now_ms=end + 10 * step)
        warmup_end = start + 500 * step
        assert all(t.entry_time.timestamp() * 1000 > warmup_end for t in trades)
        counts[name] = len(trades)
    assert all(count > 0 for count in counts.values()), counts
