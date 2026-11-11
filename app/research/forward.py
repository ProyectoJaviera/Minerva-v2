"""Prueba hacia adelante (paper por repeticion) de las estrategias en estudio de la v2.

Lo usan `scripts/v2_forward_test.py` y la pestana «Estudio» del dashboard. Corre las estrategias
congeladas (las tres finalistas de la ronda 3, desde el 2026-11-10, y la fuerza relativa semanal
de la ronda 4, desde el 2026-11-11), cada una con su control al azar, con el motor de backtest
sobre el archivo de historial local, y cuenta solo las operaciones ABIERTAS desde su fecha de
congelamiento: velas que no existian cuando se fijaron las reglas. Criterio de lectura en
`docs/v2/PAPER_V2_RONDA3.md`.

Solo lectura del archivo de historial; sin red.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from app.backtesting import metrics as m
from app.backtesting.engine import RawTrade, run_backtest
from app.config import Settings
from app.market.ohlcv_history import MissingHistoricalDataError
from app.persistence.database import Database
from app.persistence.repositories import ohlcv_repo
from app.research.round3 import Round3Strategy, set_btc_context
from app.research.round4 import Round4Strategy, set_universe_context
from app.strategies.base import BaseStrategy

# Historia previa para calentar los indicadores (500 velas de calentamiento y medias largas).
START_MS = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
REVIEW_TRADES = 60
REVIEW_DATE = datetime(2027, 5, 10, tzinfo=UTC)
MIN_PF = 1.2
TIMEFRAME = "4h"
STEP_MS = 4 * 3_600_000
# Universo congelado el 2026-11-10 (el de la Fase 2 y de las rondas 3 y 4).
SYMBOLS = ("BNBUSDT", "BTCUSDT", "DOGEUSDT", "ETHUSDT", "HYPEUSDT", "SOLUSDT", "TRXUSDT",
           "XMRUSDT", "XRPUSDT", "ZECUSDT")
R3_START = datetime(2026, 11, 10, tzinfo=UTC)
R4_START = datetime(2026, 11, 11, tzinfo=UTC)


@dataclass(frozen=True)
class Tracked:
    """Una estrategia en estudio con su control al azar."""

    label: str
    origin: str
    strategy: BaseStrategy
    control: BaseStrategy
    start: datetime


def tracked() -> list[Tracked]:
    """Las estrategias en estudio, en orden.

    Returns:
        Las tres finalistas de la ronda 3 y la fuerza relativa semanal de la ronda 4.
    """
    r3 = (
        ("vidya_flip", ("btc",), "Giro de VIDYA + régimen de BTC"),
        ("fvg", ("ema",), "FVG + EMA 144"),
        ("rf_flip", ("ema",), "Giro del Range Filter + EMA 144"),
    )
    out = [
        Tracked(label, "Finalista de la ronda 3 (trailing 3 ATR, orden límite)",
                Round3Strategy(trigger, filters, exit_name="s3_trail3", entry_mode="limit"),
                Round3Strategy(trigger, (), exit_name="s3_trail3", entry_mode="limit",
                               random_dir=True),
                R3_START)
        for trigger, filters, label in r3
    ]
    out.append(Tracked(
        "Fuerza relativa semanal (3 más fuertes / 3 más débiles)",
        "La más cercana de la ronda 4 (SL 2.5 ATR, cierre a la semana, orden límite)",
        Round4Strategy("mom42", (), exit_name="t42_s25", entry_mode="limit"),
        Round4Strategy("mom42", (), exit_name="t42_s25", entry_mode="limit", random_dir=True),
        R4_START,
    ))
    return out


def trade_stats(trades: list[RawTrade]) -> dict:
    """Operaciones, PF neto, PnL neto y porcentaje de ganadoras.

    Args:
        trades: operaciones.

    Returns:
        `trades`, `pf` (None sin operaciones ni perdidas), `pnl_usdt` y `win_rate_pct`.
    """
    pf = m.profit_factor_only(trades)
    wins = sum(t.pnl_net_usdt > 0 for t in trades)
    return {
        "trades": len(trades),
        "pf": None if pf is None or pf == float("inf") else round(pf, 3),
        "pnl_usdt": round(sum(t.pnl_net_usdt for t in trades), 2),
        "win_rate_pct": round(100 * wins / len(trades), 1) if trades else None,
    }


def review_state(stats: dict, control: dict, last: datetime) -> dict:
    """Estado de la revision segun el criterio fijado (60 operaciones o el 2027-05-10).

    Args:
        stats: `trade_stats` de la estrategia.
        control: `trade_stats` de su control al azar.
        last: cierre de la ultima vela disponible.

    Returns:
        `due` (si ya corresponde revisar) y `verdict`: `en curso`, `sigue en estudio` o
        `descartada`.
    """
    due = stats["trades"] >= REVIEW_TRADES or last >= REVIEW_DATE
    if not due:
        return {"due": False, "verdict": "en curso"}
    pf, pf_ctl = stats["pf"], control["pf"]
    keeps = pf is not None and pf >= MIN_PF and (pf_ctl is None or pf > pf_ctl)
    return {"due": True, "verdict": "sigue en estudio" if keeps else "descartada"}


async def last_closed_ms(db: Database, symbol: str) -> int | None:
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


def _trade_row(t: RawTrade) -> dict:
    return {
        "entry_time": t.entry_time.isoformat(), "exit_time": t.exit_time.isoformat(),
        "symbol": t.symbol, "side": str(t.side.value if hasattr(t.side, "value") else t.side),
        "entry_price": t.entry_price, "exit_price": t.exit_price,
        "close_reason": t.close_reason, "pnl_usdt": round(t.pnl_net_usdt, 2),
    }


async def compute_forward(db: Database, settings: Settings) -> dict:
    """Corre la prueba hacia adelante sobre un archivo de historial ya abierto.

    Args:
        db: archivo de historial (abierto en solo lectura).
        settings: configuracion (costos y motor).

    Returns:
        `data_until` (ISO), `days`, `stale_symbols`, `review` (operaciones y fecha) y `strategies`:
        por estrategia, etiqueta, origen, inicio, `stats`, `control`, `review`, `open_trades` y
        `trade_list` (cada operacion). Sin velas de BTC devuelve `available: False`.

    Efectos:
        Lee `ohlcv_cache`, `funding_cache` y `contract_specs_cache`. Registra el contexto de BTC y
        del universo en `round3`/`round4`. Sin red.
    """
    btc_end = await last_closed_ms(db, "BTCUSDT")
    if btc_end is None:
        return {"available": False, "detail": "El archivo no tiene velas de 4h de BTCUSDT."}
    ends = {s: await last_closed_ms(db, s) for s in SYMBOLS}
    closes = {}
    for symbol, end_ms in ends.items():
        if end_ms is None:
            continue
        bars = await ohlcv_repo.get_bars(db, symbol, TIMEFRAME, "LAST_PRICE", START_MS, end_ms)
        closes[symbol] = pd.DataFrame({"open_time": [b.open_time for b in bars],
                                       "close": [b.close for b in bars]})
    set_btc_context(TIMEFRAME, closes["BTCUSDT"])
    set_universe_context(TIMEFRAME, closes)
    last = datetime.fromtimestamp(btc_end / 1000, tz=UTC)
    result = {
        "available": True,
        "data_until": last.isoformat(),
        "stale_symbols": [s for s, e in ends.items() if e is None or e < btc_end],
        "review": {"trades": REVIEW_TRADES, "date": REVIEW_DATE.date().isoformat(),
                   "min_pf": MIN_PF},
        "strategies": [],
    }
    for item in tracked():
        per: dict[str, list[RawTrade]] = {}
        for which, strategy in (("strategy", item.strategy), ("control", item.control)):
            forward: list[RawTrade] = []
            for symbol, end_ms in ends.items():
                if end_ms is None:
                    continue
                try:
                    trades, _ = await run_backtest(db, strategy, strategy.name, symbol,
                                                   TIMEFRAME, START_MS, end_ms, settings)
                except MissingHistoricalDataError:
                    continue
                forward += [t for t in trades if t.entry_time >= item.start]
            per[which] = sorted(forward, key=lambda t: t.entry_time)
        stats = trade_stats(per["strategy"])
        control = trade_stats(per["control"])
        result["strategies"].append({
            "name": item.strategy.name, "label": item.label, "origin": item.origin,
            "start": item.start.date().isoformat(),
            "days": round(max(0.0, (last - item.start).total_seconds() / 86_400), 1),
            "stats": stats, "control": control,
            "review": review_state(stats, control, last),
            "open_trades": sum(t.close_reason == "END_OF_DATA" for t in per["strategy"]),
            "trade_list": [_trade_row(t) for t in per["strategy"]],
        })
    return result
