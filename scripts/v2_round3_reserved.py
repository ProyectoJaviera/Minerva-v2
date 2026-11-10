"""Examen de los finalistas de la ronda 3 con los datos reservados (una sola corrida).

Aplica `docs/v2/PREREGISTRO_V2_RONDA3.md`: corre las tres combinaciones congeladas y sus controles
al azar con todo el historial (para que los indicadores esten calentados) y cuenta solo las
operaciones ABIERTAS entre el 2026-10-01 y el 2026-11-10 (UTC). Lectura fija: con menos de 20
operaciones, «sin informacion suficiente»; PF < 0.8, «alerta: fracaso claro»; PF entre 0.8 y 1,
«no confirma»; PF >= 1, «no contradice». Ningun resultado aprueba una estrategia.

Sin red y sin escribir en la base: solo lee velas, funding y specs de `DATABASE_PATH` (una base
temporal llenada con `scripts/download_history.py`).

    DATABASE_PATH=<base> python scripts/v2_round3_reserved.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime

import pandas as pd

sys.path.insert(0, ".")

from app.backtesting import metrics as m  # noqa: E402
from app.backtesting.engine import RawTrade, run_backtest  # noqa: E402
from app.config import Settings, settings  # noqa: E402
from app.market.ohlcv_history import get_cached_or_raise  # noqa: E402
from app.persistence.database import Database  # noqa: E402
from app.persistence.repositories import universe_repo  # noqa: E402
from app.research.round3 import Round3Strategy, set_btc_context  # noqa: E402

START_MS = int(datetime(2022, 1, 1, tzinfo=UTC).timestamp() * 1000)
RESERVED_START = datetime(2026, 10, 1, tzinfo=UTC)
RESERVED_END = datetime(2026, 11, 10, tzinfo=UTC)
TIMEFRAME = "4h"
MIN_TRADES = 20
FINALISTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("vidya_flip", ("btc",)), ("fvg", ("ema",)), ("rf_flip", ("ema",)),
)


def reading(trades: list[RawTrade]) -> str:
    """Lectura fija del preregistro para un conjunto de operaciones del tramo reservado.

    Args:
        trades: operaciones abiertas dentro del tramo.

    Returns:
        La etiqueta de lectura.
    """
    if len(trades) < MIN_TRADES:
        return "sin informacion suficiente"
    pf = m.profit_factor_only(trades)
    if pf is None or pf < 0.8:
        return "alerta: fracaso claro"
    return "no confirma" if pf < 1 else "no contradice"


def describe(name: str, trades: list[RawTrade]) -> str:
    """Linea de resumen de una combinacion.

    Args:
        name: nombre de la combinacion.
        trades: operaciones abiertas dentro del tramo.

    Returns:
        Operaciones, PF neto, PnL neto, porcentaje de ganadoras y lectura.
    """
    pf = m.profit_factor_only(trades)
    pnl = sum(t.pnl_net_usdt for t in trades)
    wins = sum(t.pnl_net_usdt > 0 for t in trades)
    rate = f"{100 * wins / len(trades):.0f}%" if trades else "-"
    pf_text = "-" if pf is None else f"{pf:.2f}"
    return (f"{name:<40} n={len(trades):>3}  PF {pf_text:>5}  PnL {pnl:+8.2f} USDT  "
            f"ganadoras {rate:>4}  -> {reading(trades)}")


async def main() -> None:
    """Corre el examen e imprime el resumen por finalista, por control y por simbolo.

    Raises:
        SystemExit: si `DATABASE_PATH` no apunta a una base temporal.

    Efectos:
        Solo lectura de la base de `DATABASE_PATH`. Sin red.
    """
    default_db = Settings.model_fields["database_path"].default
    if not os.environ.get("DATABASE_PATH") or settings.database_path == default_db:
        raise SystemExit("Define DATABASE_PATH con una base temporal (no la de por defecto).")
    end_ms = int(RESERVED_END.timestamp() * 1000)
    db = Database(settings.database_path)
    await db.connect()
    try:
        symbols = sorted(set(await universe_repo.get_included_symbols(db))
                         | set(settings.backtest_control_symbols_list))
        btc = await get_cached_or_raise(db, "BTCUSDT", TIMEFRAME, START_MS, end_ms)
        set_btc_context(TIMEFRAME, pd.DataFrame(
            {"open_time": [b.open_time for b in btc], "close": [b.close for b in btc]}))
        print(f"Tramo reservado: {RESERVED_START.date()} a {RESERVED_END.date()} (UTC); "
              f"simbolos {symbols}\n")
        for trigger, filters in FINALISTS:
            for strategy in (
                Round3Strategy(trigger, filters, exit_name="s3_trail3", entry_mode="limit"),
                Round3Strategy(trigger, (), exit_name="s3_trail3", entry_mode="limit",
                               random_dir=True),
            ):
                reserved: list[RawTrade] = []
                for symbol in symbols:
                    trades, _ = await run_backtest(db, strategy, strategy.name, symbol,
                                                   TIMEFRAME, START_MS, end_ms, settings)
                    reserved += [t for t in trades
                                 if RESERVED_START <= t.entry_time < RESERVED_END]
                print(describe(strategy.name, reserved))
                if not strategy.random_dir:
                    by_symbol: dict[str, list[RawTrade]] = {}
                    for t in reserved:
                        by_symbol.setdefault(t.symbol, []).append(t)
                    print("    por simbolo: " + ", ".join(
                        f"{s} {len(ts)} ({sum(t.pnl_net_usdt for t in ts):+.2f})"
                        for s, ts in sorted(by_symbol.items())))
                    open_end = sum(t.close_reason == "END_OF_DATA" for t in reserved)
                    print(f"    cerradas al final del tramo (aun abiertas): {open_end}")
            print()
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
