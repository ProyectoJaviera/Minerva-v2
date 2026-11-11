"""Prueba hacia adelante (paper por repeticion) de las estrategias en estudio de la v2.

Las tres combinaciones de `docs/v2/PREREGISTRO_V2_RONDA3.md` (congeladas el 2026-11-10) y la
fuerza relativa semanal de la ronda 4 (`r4|mom42|nada|t42_s25|limit`, congelada el 2026-11-11, a
pedido del dueno), cada una con su control al azar. Este script las corre con el motor de backtest
sobre el archivo de historial local y cuenta solo las operaciones ABIERTAS desde su fecha de
congelamiento (00:00 UTC): velas que no existian cuando se fijaron las reglas. Como el motor es
determinista y causal, eso equivale a haberlas operado en paper desde ese dia (incluida la entrada
con orden limite, que el bot en vivo no simula), sin tener que dejar un proceso corriendo.

Criterio de lectura (fijado en `docs/v2/PAPER_V2_RONDA3.md` antes de la primera corrida): se
evalua cada estrategia cuando junte 60 operaciones o el 2027-05-10, lo que ocurra primero.

Solo lectura: abre el archivo de historial (`EXPLORER_HISTORY_DB`, por defecto
`./history/history_v2.db`) en modo inmutable; sin red. Para tener velas nuevas hay que actualizar
antes ese archivo:

    python scripts/update_history_file.py
    python scripts/v2_forward_test.py [--path history/history_v2.db] [--trades]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from app.backtesting import metrics as m  # noqa: E402
from app.backtesting.engine import RawTrade, run_backtest  # noqa: E402
from app.config import settings  # noqa: E402
from app.explorer.service import ReadOnlyDatabase  # noqa: E402
from app.market.ohlcv_history import MissingHistoricalDataError  # noqa: E402
from app.persistence.repositories import ohlcv_repo  # noqa: E402
from app.research.round3 import Round3Strategy, set_btc_context  # noqa: E402
from app.research.round4 import Round4Strategy, set_universe_context  # noqa: E402
from app.strategies.base import BaseStrategy  # noqa: E402

START_MS = int(datetime(2022, 1, 1, tzinfo=UTC).timestamp() * 1000)
FORWARD_START = datetime(2026, 11, 10, tzinfo=UTC)  # la mas antigua de las fechas de inicio
REVIEW_TRADES = 60
REVIEW_DATE = datetime(2027, 5, 10, tzinfo=UTC)
TIMEFRAME = "4h"
STEP_MS = 4 * 3_600_000
# Universo congelado el 2026-11-10 (el de la Fase 2 y de la ronda 3).
SYMBOLS = ("BNBUSDT", "BTCUSDT", "DOGEUSDT", "ETHUSDT", "HYPEUSDT", "SOLUSDT", "TRXUSDT",
           "XMRUSDT", "XRPUSDT", "ZECUSDT")
R3_START = datetime(2026, 11, 10, tzinfo=UTC)
R4_START = datetime(2026, 11, 11, tzinfo=UTC)


def tracked() -> list[tuple[BaseStrategy, BaseStrategy, datetime]]:
    """Las estrategias en estudio: `(estrategia, control al azar, inicio de la prueba)`.

    Returns:
        Las tres finalistas de la ronda 3 y la fuerza relativa semanal de la ronda 4.
    """
    out: list[tuple[BaseStrategy, BaseStrategy, datetime]] = []
    for trigger, filters in (("vidya_flip", ("btc",)), ("fvg", ("ema",)), ("rf_flip", ("ema",))):
        out.append((
            Round3Strategy(trigger, filters, exit_name="s3_trail3", entry_mode="limit"),
            Round3Strategy(trigger, (), exit_name="s3_trail3", entry_mode="limit",
                           random_dir=True),
            R3_START,
        ))
    out.append((
        Round4Strategy("mom42", (), exit_name="t42_s25", entry_mode="limit"),
        Round4Strategy("mom42", (), exit_name="t42_s25", entry_mode="limit", random_dir=True),
        R4_START,
    ))
    return out


def summarize(name: str, trades: list[RawTrade]) -> str:
    """Linea de resumen de las operaciones hacia adelante de una combinacion.

    Args:
        name: nombre de la combinacion.
        trades: operaciones abiertas desde el inicio de su prueba.

    Returns:
        Operaciones, PF neto, PnL neto y porcentaje de ganadoras.
    """
    pf = m.profit_factor_only(trades)
    pnl = sum(t.pnl_net_usdt for t in trades)
    wins = sum(t.pnl_net_usdt > 0 for t in trades)
    rate = f"{100 * wins / len(trades):.0f}%" if trades else "-"
    pf_text = "-" if pf is None else f"{pf:.2f}"
    return (f"{name:<40} n={len(trades):>3}  PF {pf_text:>5}  PnL {pnl:+8.2f} USDT  "
            f"ganadoras {rate:>4}")


async def last_closed_ms(db: ReadOnlyDatabase, symbol: str) -> int | None:
    """Cierre (ms) de la ultima vela de 4h que el archivo tiene en LAST y en MARK para `symbol`.

    Args:
        db: archivo de historial.
        symbol: simbolo.

    Returns:
        El instante de cierre, o `None` si falta alguna de las dos series.

    Efectos:
        Lee `ohlcv_cache` del archivo de historial.
    """
    ends = []
    for price_type in ("LAST_PRICE", "MARK_PRICE"):
        covered = await ohlcv_repo.get_covered_range(db, symbol, TIMEFRAME, price_type)
        if covered is None:
            return None
        ends.append(int(covered[1]) + STEP_MS)
    return min(ends)


async def main() -> None:
    """Corre la prueba hacia adelante e imprime el estado de cada finalista y de su control.

    Raises:
        SystemExit: si el archivo de historial no existe o no tiene las velas de BTC.

    Efectos:
        Solo lectura del archivo de historial. Sin red.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", default=settings.explorer_history_db)
    parser.add_argument("--trades", action="store_true", help="lista cada operacion")
    args = parser.parse_args()
    path = Path(args.path)
    if not path.exists():
        raise SystemExit(f"No existe {path}: corre antes scripts/update_history_file.py")
    db = ReadOnlyDatabase(path)
    await db.connect()
    try:
        btc_end = await last_closed_ms(db, "BTCUSDT")
        if btc_end is None:
            raise SystemExit("El archivo no tiene velas de 4h de BTCUSDT.")
        btc = await ohlcv_repo.get_bars(db, "BTCUSDT", TIMEFRAME, "LAST_PRICE", START_MS, btc_end)
        set_btc_context(TIMEFRAME, pd.DataFrame(
            {"open_time": [b.open_time for b in btc], "close": [b.close for b in btc]}))
        ends = {s: await last_closed_ms(db, s) for s in SYMBOLS}
        closes = {}
        for symbol, end_ms in ends.items():
            if end_ms is None:
                continue
            bars = await ohlcv_repo.get_bars(db, symbol, TIMEFRAME, "LAST_PRICE", START_MS, end_ms)
            closes[symbol] = pd.DataFrame({"open_time": [b.open_time for b in bars],
                                           "close": [b.close for b in bars]})
        set_universe_context(TIMEFRAME, closes)
        last = datetime.fromtimestamp(btc_end / 1000, tz=UTC)
        days = max(0.0, (last - FORWARD_START).total_seconds() / 86_400)
        print(f"Prueba hacia adelante desde {FORWARD_START:%Y-%m-%d} UTC; datos hasta "
              f"{last:%Y-%m-%d %H:%M} UTC ({days:.1f} dias)")
        stale = [s for s, e in ends.items() if e is None or e < btc_end]
        if stale:
            print(f"AVISO: simbolos con datos atrasados o ausentes: {stale}")
        print(f"Revision: al llegar a {REVIEW_TRADES} operaciones o el {REVIEW_DATE:%Y-%m-%d}\n")
        for main_strategy, control, start in tracked():
            print(f"[desde {start:%Y-%m-%d}]")
            for strategy in (main_strategy, control):
                forward: list[RawTrade] = []
                for symbol, end_ms in ends.items():
                    if end_ms is None:
                        continue
                    try:
                        trades, _ = await run_backtest(db, strategy, strategy.name, symbol,
                                                       TIMEFRAME, START_MS, end_ms, settings)
                    except MissingHistoricalDataError as exc:
                        print(f"  {symbol}: sin datos completos ({exc})")
                        continue
                    forward += [t for t in trades if t.entry_time >= start]
                print(summarize(strategy.name, forward))
                if strategy is main_strategy:
                    still_open = sum(t.close_reason == "END_OF_DATA" for t in forward)
                    ready = len(forward) >= REVIEW_TRADES or last >= REVIEW_DATE
                    print(f"    aun abiertas: {still_open}; revision "
                          f"{'YA CORRESPONDE' if ready else 'todavia no'}")
                    if args.trades:
                        for t in sorted(forward, key=lambda t: t.entry_time):
                            print(f"    {t.entry_time:%Y-%m-%d %H:%M} {t.symbol:<9} {t.side:<5} "
                                  f"entrada {t.entry_price:.6g} salida {t.exit_price:.6g} "
                                  f"{t.close_reason:<11} {t.pnl_net_usdt:+.2f}")
            print()
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
