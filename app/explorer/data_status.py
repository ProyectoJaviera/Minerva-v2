"""Estado de los datos de la v2 para el dashboard: captura hacia adelante e historial local.

Lee, sin escribir nada, el archivo de datos capturados (`MARKET_DATA_DB`, por defecto
`./history/market_v2.db`, que llenan las tareas `MinervaV2*` con
`scripts/record_market_data.py`) y el archivo de historial (`EXPLORER_HISTORY_DB`). Sirve para
ver de un vistazo si las tareas programadas estan funcionando: cuando fue la ultima foto de cada
cosa, cuantas hubo en 24 h, los errores y los ultimos valores. No muestra resultados de ninguna
estrategia.

El archivo de datos capturados cambia cada pocos minutos, asi que se abre con `mode=ro` (no
`immutable`): SQLite ve siempre una version consistente.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

DAY_MS = 86_400_000
# Antiguedad maxima antes de marcar una captura como atrasada (doble de su periodo, con margen).
STALE_AFTER_MS = {
    "orderbook": 15 * 60_000,
    "funding": 2 * 3_600_000,
    "feargreed": 36 * 3_600_000,
    "history": 8 * 3_600_000,
}


def _iso(ms: int | None) -> str | None:
    return None if ms is None else datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def _connect(path: Path, immutable: bool) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + ("?mode=ro&immutable=1" if immutable else "?mode=ro")
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _block(last_ms: int | None, kind: str, now_ms: int) -> dict:
    stale = last_ms is None or now_ms - last_ms > STALE_AFTER_MS[kind]
    return {"last_at": _iso(last_ms), "stale": stale}


def market_status(path: str, now_ms: int | None = None) -> dict:
    """Estado del archivo de datos capturados.

    Args:
        path: ruta de `market_v2.db`.
        now_ms: instante actual en ms (para las pruebas); por defecto, el reloj.

    Returns:
        `available` y, si existe el archivo, los bloques `orderbook` (ultima foto, fotos y monedas
        en 24 h, ultimos valores por moneda), `funding` (ultima foto y tasa por moneda),
        `feargreed` (ultimo valor) y `errors_24h` (cantidad y ultimo detalle). Cada bloque trae
        `stale` si esta atrasado.

    Efectos:
        Lee el archivo en solo lectura.
    """
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    p = Path(path)
    if not p.is_file():
        return {"available": False, "path": path}
    since = now_ms - DAY_MS
    with _connect(p, immutable=False) as conn:
        ob_last = conn.execute("SELECT MAX(ts_ms) FROM orderbook_snapshots").fetchone()[0]
        ob_24h = conn.execute("SELECT COUNT(*), COUNT(DISTINCT symbol) FROM orderbook_snapshots "
                              "WHERE ts_ms >= ?", (since,)).fetchone()
        latest_ob = conn.execute(
            "SELECT o.symbol, o.ts_ms, o.mid, o.spread_bps, o.imbalance_20, o.bid_notional_50, "
            "o.ask_notional_50 FROM orderbook_snapshots o JOIN (SELECT symbol, MAX(ts_ms) AS t "
            "FROM orderbook_snapshots GROUP BY symbol) m ON o.symbol = m.symbol AND o.ts_ms = m.t "
            "ORDER BY o.symbol").fetchall()
        fu_last = conn.execute("SELECT MAX(ts_ms) FROM funding_snapshots").fetchone()[0]
        latest_fu = dict(conn.execute(
            "SELECT f.symbol, f.funding_rate FROM funding_snapshots f JOIN (SELECT symbol, "
            "MAX(ts_ms) AS t FROM funding_snapshots GROUP BY symbol) m ON f.symbol = m.symbol "
            "AND f.ts_ms = m.t").fetchall())
        fg = conn.execute("SELECT day_ts_ms, value, classification, fetched_ms FROM fear_greed "
                          "ORDER BY day_ts_ms DESC LIMIT 1").fetchone()
        errors = conn.execute("SELECT COUNT(*) FROM capture_log WHERE ok = 0 AND ts_ms >= ?",
                              (since,)).fetchone()[0]
        last_error = conn.execute("SELECT ts_ms, kind, detail FROM capture_log WHERE ok = 0 "
                                  "ORDER BY ts_ms DESC LIMIT 1").fetchone()
    symbols = [{"symbol": r["symbol"], "at": _iso(r["ts_ms"]), "mid": r["mid"],
                "spread_bps": r["spread_bps"], "imbalance_20": r["imbalance_20"],
                "bid_notional_50": r["bid_notional_50"], "ask_notional_50": r["ask_notional_50"],
                "funding_rate": latest_fu.get(r["symbol"])} for r in latest_ob]
    return {
        "available": True,
        "path": path,
        "orderbook": {**_block(ob_last, "orderbook", now_ms), "snapshots_24h": ob_24h[0],
                      "symbols_24h": ob_24h[1]},
        "funding": {**_block(fu_last, "funding", now_ms), "symbols": len(latest_fu)},
        "feargreed": {**_block(fg["fetched_ms"] if fg else None, "feargreed", now_ms),
                      "day": _iso(fg["day_ts_ms"])[:10] if fg else None,
                      "value": fg["value"] if fg else None,
                      "classification": fg["classification"] if fg else None},
        "errors_24h": {"count": errors,
                       "last": None if last_error is None else {
                           "at": _iso(last_error["ts_ms"]), "kind": last_error["kind"],
                           "detail": last_error["detail"]}},
        "symbols": symbols,
    }


def history_status(path: str, now_ms: int | None = None) -> dict:
    """Ultima vela de cada marco del archivo de historial.

    Args:
        path: ruta de `history_v2.db`.
        now_ms: instante actual en ms (para las pruebas); por defecto, el reloj.

    Returns:
        `available` y, si existe, `timeframes` (marco, ultima vela, monedas) y `stale` si la ultima
        vela de 1h es mas vieja que `STALE_AFTER_MS["history"]`.

    Efectos:
        Lee el archivo en modo inmutable de solo lectura.
    """
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    p = Path(path)
    if not p.is_file():
        return {"available": False, "path": path}
    with _connect(p, immutable=True) as conn:
        rows = conn.execute(
            "SELECT interval, MAX(open_time) AS last, COUNT(DISTINCT symbol) AS n FROM ohlcv_cache "
            "WHERE price_type = 'LAST_PRICE' GROUP BY interval").fetchall()
    by_tf = {r["interval"]: r for r in rows}
    order = ["15m", "1h", "4h", "1d", "1w"]
    tfs = [{"timeframe": tf, "last_candle": _iso(by_tf[tf]["last"]), "symbols": by_tf[tf]["n"]}
           for tf in order if tf in by_tf]
    last_1h = by_tf["1h"]["last"] if "1h" in by_tf else None
    return {"available": True, "path": path, "timeframes": tfs,
            **_block(last_1h, "history", now_ms)}
