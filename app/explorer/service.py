"""Backtest exploratorio a pedido sobre el archivo de historial local (seccion «Indicadores»).

- **Fuente:** un archivo SQLite aparte de la base del bot (`EXPLORER_HISTORY_DB`, por defecto
  `./history/history_v2.db`), creado con `scripts/download_history.py` y `DATABASE_PATH` apuntando
  a ese archivo. Tiene las mismas tablas de mercado que usa el motor (velas LAST_PRICE y
  MARK_PRICE, funding y specs). Se abre en modo `immutable` de solo lectura: nada se escribe.
- **Motor:** el mismo `run_backtest` de la Fase 2 (entrada en el open de la vela siguiente,
  comisiones, slippage, funding, liquidacion con MARK_PRICE) con las combinaciones de
  `app.research.combos` (un gatillo con 0, 1 o 2 filtros y su salida fija).
- **Datos reservados:** nunca se usan velas desde `RESERVED_FROM` (2026-10-01 UTC). Estan
  reservadas para las rondas preregistradas; el limite esta fijo en el codigo a proposito, no es
  configurable.
- **Exploratorio:** el resultado no se guarda en la base ni pasa por los criterios de la Fase 2.
  Con cada corrida va el control con direccion al azar (mismas velas, mismos filtros), la
  referencia «sin informacion de direccion».

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
from app.candidates.common import BAR_INDEX_COLUMN
from app.config import Settings
from app.market.ohlcv_history import MissingHistoricalDataError
from app.persistence.database import Database
from app.persistence.repositories import ohlcv_repo
from app.research.combos import ComboStrategy
from app.research.round3 import R3_FILTERS, R3_TRIGGERS, Round3Strategy, set_btc_context

RESERVED_FROM = datetime(2026, 10, 1, tzinfo=UTC)
RESERVED_FROM_MS = int(RESERVED_FROM.timestamp() * 1000)
TIMEFRAMES = ("1h", "4h")
MAX_FILTERS = 2
MAX_SYMBOLS = 12

TRIGGER_LABELS = {
    "sfp": "SFP del HeatMap (barrida de swing con cierre de vuelta)",
    "camarilla": "Camarilla: rechazo de S3 (largo) o R3 (corto)",
    "rf_flip": "Giro del Range Filter (Frost)",
    "vidya_flip": "Giro de la banda VIDYA (F. Trail de Frost)",
    "bb_reversal": "Reversion del BB%B (sale de sobreventa/sobrecompra)",
    "wt_cross": "Cruce de WaveTrend en zona extrema (+-72)",
    "zone_reject": "Rechazo de una zona de liquidez",
    "grab": "Liquidity Grab de Frost (agotamiento)",
    "fvg": "FVG: retesteo de un Fair Value Gap de 3 velas",
}
FILTER_LABELS = {
    "ema": "Cierre sobre/bajo la EMA 144",
    "rf": "Estado del Range Filter",
    "vidya": "Tendencia de la banda VIDYA",
    "wt": "WaveTrend: wt1 sobre/bajo wt2",
    "fund": "Funding bajo/sobre su mediana de 30 dias (en contra del lado saturado)",
    "btc": "Regimen de BTC: cierre sobre/bajo su EMA 200",
    "rs": "Fuerza relativa contra BTC (retorno de 180 velas)",
}
# Gatillos y filtros de la seccion: los de `combos` mas los de la ronda 3 (FVG, funding, regimen
# de BTC y fuerza relativa). Las combinaciones solo con piezas de `combos` corren con
# `ComboStrategy` (identicas a la exploracion); las que usan una pieza de la ronda 3, con
# `Round3Strategy` y su salida `base` (la misma de `combos` para los demas gatillos).
TRIGGERS = R3_TRIGGERS
FILTERS = R3_FILTERS
ROUND3_ONLY = {"fvg", "fund", "btc", "rs"}
BTC_SYMBOL = "BTCUSDT"

NOTE = (
    "Prueba EXPLORATORIA: no es una ronda preregistrada ni evidencia de la Fase 2, y no se guarda. "
    "Probar muchas combinaciones y quedarse con la mejor sobreestima el resultado (sesgo de "
    "seleccion). Velas de Bitunix (coinciden con TradingView); sin datos desde el 2026-10-01, "
    "reservados para las rondas preregistradas."
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


class _ArrayRow:
    """Fila de solo lectura sobre columnas numpy (lo unico que `ComboStrategy` lee de una fila)."""

    __slots__ = ("_cols", "_i")

    def __init__(self, cols: dict, i: int) -> None:
        self._cols = cols
        self._i = i

    def __getitem__(self, key: str):
        return self._cols[key][self._i]


class _FastRowMixin:
    """Lee la fila de la senal de arrays en vez de `df.iloc[-1]`.

    Mismas senales, SL, TP y trailing (`tests/unit/test_explorer.py` lo compara operacion por
    operacion); solo evita construir una `pd.Series` por vela, que era mas de la mitad del tiempo
    de una corrida. Las columnas se guardan en `precompute`, que el motor llama una vez por
    corrida antes de evaluar ventanas de ese mismo DataFrame.
    """

    _cols: dict | None = None

    def precompute(self, df):
        """El `precompute` de la estrategia y, ademas, guarda sus columnas como arrays numpy.

        Args:
            df: velas de toda la serie (con `open_time`).

        Returns:
            El mismo DataFrame que el `precompute` de la estrategia.
        """
        out = super().precompute(df)
        self._cols = {c: out[c].to_numpy() for c in out.columns}
        return out

    def _row(self, df):
        """Fila de la ultima vela de la ventana, leida de los arrays guardados."""
        if self._cols is None or BAR_INDEX_COLUMN not in df.columns:
            return super()._row(df)
        return _ArrayRow(self._cols, int(df[BAR_INDEX_COLUMN].iat[-1]))


class FastComboStrategy(_FastRowMixin, ComboStrategy):
    """`ComboStrategy` con la fila leida de arrays (mismas operaciones, ver `_FastRowMixin`)."""


class FastRound3Strategy(_FastRowMixin, Round3Strategy):
    """`Round3Strategy` con la fila leida de arrays (mismas operaciones, ver `_FastRowMixin`)."""


def build_strategy(trigger: str, filters: tuple[str, ...], *, random_dir: bool = False):
    """La estrategia de una combinacion: `ComboStrategy` salvo que use una pieza de la ronda 3.

    Args:
        trigger: gatillo.
        filters: filtros.
        random_dir: sortea la direccion (control).

    Returns:
        `FastComboStrategy` o `FastRound3Strategy` (salida `base`, entrada a mercado).
    """
    if trigger in ROUND3_ONLY or set(filters) & ROUND3_ONLY:
        return FastRound3Strategy(trigger, filters, random_dir=random_dir)
    return FastComboStrategy(trigger, filters, random_dir=random_dir)


async def load_btc_context(db: Database, timeframe: str) -> bool:
    """Registra la serie de BTC del marco para los filtros `btc` y `rs` de la ronda 3.

    Args:
        db: el archivo de historial abierto.
        timeframe: marco.

    Returns:
        Si habia velas de BTC (sin ellas, `btc` y `rs` quedan siempre en falso).

    Efectos:
        Lee `ohlcv_cache`. Cambia el contexto de BTC del modulo `round3` (las corridas de la
        seccion son de a una por vez).
    """
    bars = await ohlcv_repo.get_bars(db, BTC_SYMBOL, timeframe, "LAST_PRICE", None,
                                     RESERVED_FROM_MS - 1)
    if not bars:
        return False
    set_btc_context(timeframe, pd.DataFrame({"open_time": [b.open_time for b in bars],
                                             "close": [b.close for b in bars]}))
    return True


@dataclass(frozen=True)
class ExplorerRequest:
    """Una corrida exploratoria validada.

    Attributes:
        symbols: simbolos (1 a `MAX_SYMBOLS`).
        timeframe: `1h` o `4h`.
        trigger: uno de `TRIGGERS`.
        filters: 0 a `MAX_FILTERS` de `FILTERS`, ordenados.
        start_ms: inicio pedido (ms UTC) o `None` = desde el comienzo del historial.
        end_ms: fin pedido (ms UTC) o `None` = hasta el limite reservado.
    """

    symbols: tuple[str, ...]
    timeframe: str
    trigger: str
    filters: tuple[str, ...]
    start_ms: int | None = None
    end_ms: int | None = None


def validate_request(symbols: list[str], timeframe: str, trigger: str, filters: list[str],
                     start: str | None = None, end: str | None = None) -> ExplorerRequest:
    """Valida los parametros de una corrida y los normaliza.

    Args:
        symbols: simbolos (p. ej. `["BTCUSDT"]`).
        timeframe: `1h` o `4h`.
        trigger: gatillo.
        filters: filtros (0 a 2, sin repetir).
        start: fecha de inicio `YYYY-MM-DD` (UTC) o `None`.
        end: fecha de fin `YYYY-MM-DD` (UTC, excluida) o `None`.

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
    if trigger not in TRIGGERS:
        raise ExplorerRequestError(f"Gatillo desconocido: {trigger}.")
    flt = tuple(sorted(set(filters)))
    if len(flt) > MAX_FILTERS:
        raise ExplorerRequestError(f"Como maximo {MAX_FILTERS} filtros.")
    unknown = set(flt) - set(FILTERS)
    if unknown:
        raise ExplorerRequestError(f"Filtros desconocidos: {', '.join(sorted(unknown))}.")
    start_ms = _parse_day(start, "inicio")
    end_ms = _parse_day(end, "fin")
    if start_ms is not None and end_ms is not None and end_ms <= start_ms:
        raise ExplorerRequestError("La fecha de fin debe ser posterior a la de inicio.")
    return ExplorerRequest(syms, timeframe, trigger, flt, start_ms, end_ms)


def _parse_day(text: str | None, what: str) -> int | None:
    if not text:
        return None
    try:
        day = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ExplorerRequestError(f"Fecha de {what} invalida: {text} (usa AAAA-MM-DD).") from exc
    return int(day.timestamp() * 1000)


def _ms_to_day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d")


async def list_available_series(db: Database) -> list[dict]:
    """Las series LAST_PRICE de los marcos de la seccion que hay en el archivo de historial.

    Args:
        db: el archivo de historial abierto.

    Returns:
        Lista de `{symbol, timeframe, first_day, last_day, bars}` (solo velas antes del limite
        reservado), ordenada por simbolo y marco.

    Efectos:
        Lee `ohlcv_cache`.
    """
    placeholders = ",".join("?" for _ in TIMEFRAMES)
    rows = await db.fetch_all(
        "SELECT symbol, interval, MIN(open_time) AS first, MAX(open_time) AS last, "
        "COUNT(*) AS n FROM ohlcv_cache WHERE price_type = 'LAST_PRICE' "
        f"AND interval IN ({placeholders}) AND open_time < ? "
        "GROUP BY symbol, interval ORDER BY symbol, interval",
        (*TIMEFRAMES, RESERVED_FROM_MS),
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
    """Corre la combinacion y su control al azar sobre cada moneda pedida.

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
    combo = build_strategy(req.trigger, req.filters)
    control = build_strategy(req.trigger, req.filters, random_dir=True)
    if {"btc", "rs"} & set(req.filters):
        await load_btc_context(db, req.timeframe)
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
            missing.append({"symbol": symbol, "reason": "No esta en el archivo de historial."})
            continue
        start = max(info["first_ms"], req.start_ms or 0)
        end = min(info["last_ms"], RESERVED_FROM_MS - 1)
        if req.end_ms is not None:
            end = min(end, req.end_ms - 1)
        if end <= start:
            missing.append({"symbol": symbol, "reason": "Sin velas en el periodo pedido."})
            continue
        try:
            t, sk = await run_backtest(db, combo, combo.name, symbol, req.timeframe, start, end,
                                       settings)
            ct, _ = await run_backtest(db, control, control.name, symbol, req.timeframe, start,
                                       end, settings)
        except MissingHistoricalDataError as exc:
            missing.append({"symbol": symbol, "reason": str(exc)})
            continue
        trades.extend(t)
        control_trades.extend(ct)
        skipped += len(sk)
        period_start = start if period_start is None else min(period_start, start)
        period_end = end if period_end is None else max(period_end, end)

    capital = settings.backtest_initial_capital
    return {
        "exploratory": True,
        "note": NOTE,
        "params": {"symbols": list(req.symbols), "timeframe": req.timeframe,
                   "trigger": req.trigger, "filters": list(req.filters),
                   "exit_mode": combo.exit_mode, "name": combo.name},
        "period": {"start": _ms_to_day(period_start) if period_start is not None else None,
                   "end": _ms_to_day(period_end) if period_end is not None else None,
                   "reserved_from": RESERVED_FROM.strftime("%Y-%m-%d")},
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
