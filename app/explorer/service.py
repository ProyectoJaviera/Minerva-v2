"""Backtest exploratorio a pedido sobre el archivo de historial local (seccion «Indicadores»).

- **Fuente:** un archivo SQLite aparte de la base del bot (`EXPLORER_HISTORY_DB`, por defecto
  `./history/history_v2.db`), creado con `scripts/update_history_file.py`. Tiene las mismas tablas
  de mercado que usa el motor (velas LAST_PRICE y MARK_PRICE, funding y specs). Se abre en modo
  `immutable` de solo lectura: nada se escribe.
- **Estrategia:** la confluencia de los indicadores que el dueno marca (`app.explorer.confluence`):
  todos votan alcista o bajista y se entra cuando todos coinciden, con una salida fija en ATR.
- **Motor:** el mismo `run_backtest` de la Fase 2 (entrada en el open de la vela siguiente,
  comisiones, slippage, funding, liquidacion con MARK_PRICE).
- **Sin corte de datos:** usa todo el historial del archivo. El corte del 2026-10-01 se quito el
  2026-11-11 por pedido del dueno: esos datos ya se habian usado en el examen de la ronda 3.
- **Calentamiento previo:** con una fecha de inicio, se cargan antes las velas de calentamiento de
  la estrategia y solo cuentan las operaciones que entran desde esa fecha (un rango corto ya no se
  queda sin senales).
- **Exploratorio:** el resultado no se guarda en la base ni pasa por los criterios de la Fase 2.
  Con cada corrida va el control con direccion al azar (mismas velas de entrada y misma salida),
  la referencia «sin informacion de direccion».

El calculo corre en un hilo aparte con su propio bucle y su propia conexion, de a una corrida
por vez, para no frenar el bucle del bot.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pandas as pd

from app.backtesting.engine import RawTrade, run_backtest
from app.backtesting.metrics import compute_metrics
from app.config import Settings
from app.explorer.confluence import (
    DEFAULT_EXIT,
    DEFAULT_WINDOW,
    EXITS,
    INDICATORS,
    MAX_WINDOW,
    PCT_EXIT,
    ConfluenceStrategy,
    check_pct_exit,
    pct_exit_label,
)
from app.market.ohlcv_history import MissingHistoricalDataError, interval_to_ms
from app.persistence.database import Database
from app.persistence.repositories import ohlcv_repo

TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w")
TIMEFRAME_LABELS = {"15m": "15m", "1h": "1h", "4h": "4h", "1d": "1D", "1w": "1S"}
MAX_SYMBOLS = 12
BTC_SYMBOL = "BTCUSDT"

NOTE = (
    "Prueba EXPLORATORIA: no es una ronda preregistrada ni evidencia de la Fase 2, y no se guarda. "
    "Probar muchas combinaciones y quedarse con la mejor sobreestima el resultado (sesgo de "
    "seleccion). Velas de Bitunix (coinciden con TradingView)."
)

_run_lock = asyncio.Lock()
_available_cache: dict[tuple[str, float], list[dict]] = {}
_result_cache: dict[tuple, dict] = {}
RESULT_CACHE_SIZE = 32


class HistoryFileMissingError(RuntimeError):
    """No existe el archivo de historial local."""


class ExplorerRequestError(ValueError):
    """Parametros invalidos para una corrida exploratoria."""


class ReadOnlyDatabase(Database):
    """`Database` abierta en modo `immutable` de solo lectura y sin tocar el esquema.

    El archivo de historial es estatico mientras el dashboard lo lee; `immutable=1` evita que
    SQLite intente crear el `-wal` o el `-shm` (funciona tambien con una carpeta montada de solo
    lectura en Docker).
    """

    async def connect(self) -> None:
        """Abre la conexion de solo lectura.

        Raises:
            HistoryFileMissingError: si el archivo no existe.

        Efectos:
            Abre el archivo en solo lectura. No escribe nada.
        """
        path = Path(self.path)
        if not path.is_file():
            raise HistoryFileMissingError(str(path))
        uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
        self._conn = await aiosqlite.connect(uri, uri=True)
        self._conn.row_factory = aiosqlite.Row

    async def init_schema(self) -> None:  # pragma: no cover - nunca se escribe el esquema
        """No hace nada: el archivo es de solo lectura."""


@dataclass(frozen=True)
class ExplorerRequest:
    """Una corrida exploratoria validada.

    Attributes:
        symbols: simbolos (1 a `MAX_SYMBOLS`).
        timeframe: uno de `TIMEFRAMES`.
        indicators: ids de `INDICATORS` (al menos uno), en su orden.
        window: velas que dura el voto de un indicador de evento.
        exit_name: clave de `EXITS`.
        start_ms: inicio pedido (ms UTC) o `None` = desde el comienzo del historial.
        end_ms: fin pedido (ms UTC) o `None` = hasta el final del historial.
        min_agree: cuantos indicadores deben coincidir (`None` = todos).
        pct_exit: `(sl, tp, trailing)` en % si `exit_name` es `PCT_EXIT`, si no `None`.
    """

    symbols: tuple[str, ...]
    timeframe: str
    indicators: tuple[str, ...]
    window: int = DEFAULT_WINDOW
    exit_name: str = DEFAULT_EXIT
    start_ms: int | None = None
    end_ms: int | None = None
    min_agree: int | None = None
    pct_exit: tuple[float, float | None, float | None] | None = None


def validate_request(symbols: list[str], timeframe: str, indicators: list[str],
                     window: int = DEFAULT_WINDOW, exit_name: str = DEFAULT_EXIT,
                     start: str | None = None, end: str | None = None,
                     min_agree: int | None = None, sl_pct: float | None = None,
                     tp_pct: float | None = None,
                     trail_pct: float | None = None) -> ExplorerRequest:
    """Valida los parametros de una corrida y los normaliza.

    Args:
        symbols: simbolos (p. ej. `["BTCUSDT"]`).
        timeframe: `15m`, `1h`, `4h`, `1d` o `1w`.
        indicators: ids de los indicadores (uno o mas, sin limite).
        window: velas que dura el voto de un indicador de evento (1 a `MAX_WINDOW`).
        exit_name: salida (clave de `EXITS`).
        start: fecha de inicio `YYYY-MM-DD` (UTC) o `None`.
        end: fecha de fin `YYYY-MM-DD` (UTC, excluida) o `None`.
        min_agree: cuantos indicadores deben coincidir (`None`, 0 o la cantidad elegida = todos).
        sl_pct: SL en % del precio de entrada (obligatorio con la salida `PCT_EXIT`).
        tp_pct: TP en % (opcional, solo con `PCT_EXIT`).
        trail_pct: trailing en % (opcional, solo con `PCT_EXIT`).

    Returns:
        La corrida validada.

    Raises:
        ExplorerRequestError: si algun parametro no es valido.
    """
    syms = tuple(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))
    if not syms:
        raise ExplorerRequestError("Elige al menos una moneda.")
    if len(syms) > MAX_SYMBOLS:
        raise ExplorerRequestError(f"Como maximo {MAX_SYMBOLS} monedas por corrida.")
    if any(not s.isalnum() for s in syms):
        raise ExplorerRequestError("Simbolo invalido.")
    if timeframe not in TIMEFRAMES:
        raise ExplorerRequestError(f"Marco invalido: {timeframe} (usa {', '.join(TIMEFRAMES)}).")
    chosen = set(indicators)
    if not chosen:
        raise ExplorerRequestError("Elige al menos un indicador.")
    unknown = chosen - set(INDICATORS)
    if unknown:
        raise ExplorerRequestError(f"Indicadores desconocidos: {', '.join(sorted(unknown))}.")
    if not 1 <= window <= MAX_WINDOW:
        raise ExplorerRequestError(f"La ventana debe estar entre 1 y {MAX_WINDOW} velas.")
    pct_exit = None
    if exit_name == PCT_EXIT:
        try:
            pct_exit = check_pct_exit(sl_pct, tp_pct, trail_pct)
        except ValueError as exc:
            raise ExplorerRequestError(str(exc)) from exc
    elif exit_name not in EXITS:
        raise ExplorerRequestError(f"Salida desconocida: {exit_name}.")
    start_ms = _parse_day(start, "inicio")
    end_ms = _parse_day(end, "fin")
    if start_ms is not None and end_ms is not None and end_ms <= start_ms:
        raise ExplorerRequestError("La fecha de fin debe ser posterior a la de inicio.")
    ordered = tuple(i for i in INDICATORS if i in chosen)
    if min_agree in (0, len(ordered)):
        min_agree = None
    if min_agree is not None and not 1 <= min_agree <= len(ordered):
        raise ExplorerRequestError(
            f"El minimo de coincidencias debe estar entre 1 y {len(ordered)}.")
    return ExplorerRequest(syms, timeframe, ordered, window, exit_name, start_ms, end_ms,
                           min_agree, pct_exit)


def _parse_day(text: str | None, what: str) -> int | None:
    if not text:
        return None
    try:
        day = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ExplorerRequestError(f"Fecha de {what} invalida: {text} (usa AAAA-MM-DD).") from exc
    return int(day.timestamp() * 1000)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _ms_to_day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d")


async def list_available_series(db: Database) -> list[dict]:
    """Las series LAST_PRICE de los marcos de la seccion que hay en el archivo de historial.

    Args:
        db: el archivo de historial abierto.

    Returns:
        Lista de `{symbol, timeframe, first_day, last_day, first_ms, last_ms, bars}`, ordenada
        por simbolo y marco.

    Efectos:
        Lee `ohlcv_cache`.
    """
    placeholders = ",".join("?" for _ in TIMEFRAMES)
    rows = await db.fetch_all(
        "SELECT symbol, interval, MIN(open_time) AS first, MAX(open_time) AS last, "
        "COUNT(*) AS n FROM ohlcv_cache WHERE price_type = 'LAST_PRICE' "
        f"AND interval IN ({placeholders}) "
        "GROUP BY symbol, interval ORDER BY symbol, interval",
        TIMEFRAMES,
    )
    return [{"symbol": r["symbol"], "timeframe": r["interval"],
             "first_day": _ms_to_day(int(r["first"])), "last_day": _ms_to_day(int(r["last"])),
             "first_ms": int(r["first"]), "last_ms": int(r["last"]), "bars": int(r["n"])}
            for r in rows]


async def available_series(path: str) -> list[dict]:
    """`list_available_series` sobre el archivo `path`, con cache por fecha de modificacion.

    Args:
        path: ruta del archivo de historial.

    Returns:
        Las series disponibles.

    Raises:
        HistoryFileMissingError: si el archivo no existe.
    """
    if not os.path.isfile(path):
        raise HistoryFileMissingError(path)
    key = (os.path.abspath(path), os.path.getmtime(path))
    if key not in _available_cache:
        db = ReadOnlyDatabase(path)
        await db.connect()
        try:
            _available_cache.clear()
            _available_cache[key] = await list_available_series(db)
        finally:
            await db.close()
    return _available_cache[key]


async def load_btc(db: Database, timeframe: str) -> pd.DataFrame | None:
    """Velas de BTC del marco (para los indicadores `btc` y `rs`).

    Args:
        db: el archivo de historial abierto.
        timeframe: marco.

    Returns:
        DataFrame con `open_time` y `close`, o `None` si no hay velas de BTC.

    Efectos:
        Lee `ohlcv_cache`.
    """
    bars = await ohlcv_repo.get_bars(db, BTC_SYMBOL, timeframe, "LAST_PRICE")
    if not bars:
        return None
    return pd.DataFrame({"open_time": [b.open_time for b in bars],
                         "close": [b.close for b in bars]})


def summarize(trades: list[RawTrade], initial_capital: float) -> dict:
    """Resumen de un conjunto de operaciones para la seccion.

    Args:
        trades: operaciones simuladas.
        initial_capital: capital inicial (para el drawdown).

    Returns:
        `trades`, `winrate` (0-1), `profit_factor` (`None` si no hay perdidas o no hay
        operaciones), `net_pnl_usdt`, `expectancy_usdt`, `max_drawdown_pct`, `avg_win_usdt`,
        `avg_loss_usdt`, `longs`, `shorts` y `close_reasons`.
    """
    m = compute_metrics(trades, initial_capital)
    wins = [t.pnl_net_usdt for t in trades if t.pnl_net_usdt > 0]
    losses = [t.pnl_net_usdt for t in trades if t.pnl_net_usdt <= 0]
    pf = m.profit_factor
    return {
        "trades": m.total_trades,
        "winrate": m.winrate,
        "profit_factor": pf if pf is not None and pf != float("inf") else None,
        "net_pnl_usdt": round(m.pnl_net_total_usdt, 4),
        "expectancy_usdt": None if m.expectancy_usdt is None else round(m.expectancy_usdt, 4),
        "max_drawdown_pct": m.max_drawdown_pct,
        "avg_win_usdt": round(sum(wins) / len(wins), 4) if wins else None,
        "avg_loss_usdt": round(sum(losses) / len(losses), 4) if losses else None,
        "longs": sum(1 for t in trades if t.side == "LONG"),
        "shorts": sum(1 for t in trades if t.side == "SHORT"),
        "close_reasons": dict(Counter(t.close_reason for t in trades)),
    }


def _breakdown(trades: list[RawTrade], key, initial_capital: float) -> list[dict]:
    groups: dict[str, list[RawTrade]] = defaultdict(list)
    for t in trades:
        groups[key(t)].append(t)
    out = []
    for k in sorted(groups):
        s = summarize(groups[k], initial_capital)
        out.append({"key": k, "trades": s["trades"], "winrate": s["winrate"],
                    "profit_factor": s["profit_factor"], "net_pnl_usdt": s["net_pnl_usdt"]})
    return out


async def run_exploration_on_db(db: Database, req: ExplorerRequest, settings: Settings,
                                series: list[dict]) -> dict:
    """Corre la confluencia elegida y su control al azar sobre cada moneda pedida.

    Args:
        db: el archivo de historial abierto.
        req: la corrida validada.
        settings: configuracion del motor (margen, apalancamiento, comision, slippage, topes).
        series: las series disponibles (`list_available_series`).

    Returns:
        El resultado serializable: parametros, periodo efectivo, resumen de la combinacion y del
        control, desgloses por moneda y por ano, monedas sin datos y la nota exploratoria.

    Efectos:
        Solo lectura del archivo de historial. No escribe en ninguna base.
    """
    started = time.perf_counter()
    btc = await load_btc(db, req.timeframe) if {"btc", "rs"} & set(req.indicators) else None
    combo = ConfluenceStrategy(req.indicators, req.timeframe, window=req.window,
                               exit_name=req.exit_name, btc=btc, min_agree=req.min_agree,
                               pct_exit=req.pct_exit)
    control = ConfluenceStrategy(req.indicators, req.timeframe, window=req.window,
                                 exit_name=req.exit_name, btc=btc, min_agree=req.min_agree,
                                 pct_exit=req.pct_exit, random_dir=True)
    exit_label = (pct_exit_label(*req.pct_exit) if req.pct_exit is not None
                  else EXITS[req.exit_name][0])
    by_key = {(s["symbol"], s["timeframe"]): s for s in series}
    trades: list[RawTrade] = []
    control_trades: list[RawTrade] = []
    skipped = 0
    missing: list[dict] = []
    period_start: int | None = None
    period_end: int | None = None
    for symbol in req.symbols:
        info = by_key.get((symbol, req.timeframe))
        if info is None:
            missing.append({"symbol": symbol,
                            "reason": "No esta en el archivo de historial en este marco."})
            continue
        start = max(info["first_ms"], req.start_ms or 0)
        end = info["last_ms"]
        if req.end_ms is not None:
            end = min(end, req.end_ms - 1)
        if end <= start:
            missing.append({"symbol": symbol, "reason": "Sin velas en el periodo pedido."})
            continue
        # Calentamiento previo: las velas antes de `start` solo sirven para que los indicadores
        # arranquen; cuentan las operaciones que entran desde `start`.
        step = interval_to_ms(req.timeframe) or 0
        load_from = max(info["first_ms"], start - combo.warmup * step)
        try:
            t, sk = await run_backtest(db, combo, combo.name, symbol, req.timeframe, load_from,
                                       end, settings)
            ct, _ = await run_backtest(db, control, control.name, symbol, req.timeframe,
                                       load_from, end, settings)
        except MissingHistoricalDataError as exc:
            missing.append({"symbol": symbol, "reason": str(exc)})
            continue
        trades.extend(x for x in t if _ms(x.entry_time) >= start)
        control_trades.extend(x for x in ct if _ms(x.entry_time) >= start)
        skipped += sum(1 for x in sk if _ms(x.ts) >= start)
        period_start = start if period_start is None else min(period_start, start)
        period_end = end if period_end is None else max(period_end, end)

    capital = settings.backtest_initial_capital
    return {
        "exploratory": True,
        "note": NOTE,
        "params": {"symbols": list(req.symbols), "timeframe": req.timeframe,
                   "indicators": list(req.indicators), "window": req.window,
                   "exit": req.exit_name, "exit_label": exit_label,
                   "min_agree": req.min_agree or len(req.indicators),
                   "name": combo.name},
        "period": {"start": _ms_to_day(period_start) if period_start is not None else None,
                   "end": _ms_to_day(period_end) if period_end is not None else None},
        "result": summarize(trades, capital),
        "control": summarize(control_trades, capital),
        "by_symbol": _breakdown(trades, lambda t: t.symbol, capital),
        "by_year": _breakdown(trades, lambda t: str(t.entry_time.year), capital),
        "skipped_by_risk_cap": skipped,
        "missing": missing,
        "engine": {"margin_usdt": settings.default_margin_usdt, "leverage": settings.leverage,
                   "taker_fee_pct": settings.taker_fee_pct,
                   "slippage_bps": settings.backtest_slippage_bps},
        "elapsed_s": round(time.perf_counter() - started, 2),
    }


async def _run_in_own_loop(path: str, req: ExplorerRequest, settings: Settings) -> dict:
    db = ReadOnlyDatabase(path)
    await db.connect()
    try:
        series = await list_available_series(db)
        return await run_exploration_on_db(db, req, settings, series)
    finally:
        await db.close()


async def run_exploration(path: str, req: ExplorerRequest, settings: Settings) -> dict:
    """Corre una exploracion en un hilo aparte, de a una por vez.

    Args:
        path: ruta del archivo de historial.
        req: la corrida validada.
        settings: configuracion del motor.

    Returns:
        El resultado de `run_exploration_on_db` con `cached` (si salio de la cache de las ultimas
        `RESULT_CACHE_SIZE` corridas; se invalida al cambiar el archivo).

    Raises:
        HistoryFileMissingError: si el archivo no existe.
    """
    if not os.path.isfile(path):
        raise HistoryFileMissingError(path)
    key = (os.path.abspath(path), os.path.getmtime(path), req)
    async with _run_lock:
        if key in _result_cache:
            return {**_result_cache[key], "cached": True}
        result = await asyncio.to_thread(asyncio.run, _run_in_own_loop(path, req, settings))
        if len(_result_cache) >= RESULT_CACHE_SIZE:
            _result_cache.pop(next(iter(_result_cache)))
        _result_cache[key] = result
        return {**result, "cached": False}
