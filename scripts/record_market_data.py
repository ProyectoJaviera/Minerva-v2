"""Graba hacia adelante datos de mercado que no tienen historial gratis (v2, solo lectura de APIs).

Pensado para las tareas programadas `MinervaV2*` (`scripts/register_v2_data_tasks.ps1`). Cada
llamada toma UNA foto y termina; escribe en un archivo SQLite aparte, por defecto
`./history/market_v2.db` (`--path`), nunca en la base del bot ni en `data/`.

Subcomandos:

- `orderbook`: libro de ordenes de Bitunix (`GET /api/v1/futures/market/depth`, `limit=50`,
  verificado contra la API publica el 2026-11-11: `{"asks": [[precio, cantidad], ...], "bids":
  [...]}` con strings). Guarda por simbolo: mejor compra y venta, precio medio, spread en puntos
  basicos, cantidad y nocional de los 5, 20 y 50 primeros niveles por lado, el desequilibrio
  `(bid - ask) / (bid + ask)` en esos tramos y los 20 primeros niveles crudos (JSON).
- `funding`: funding vigente de todos los simbolos (`GET .../market/funding_rate/batch`), filtrado
  a los del universo, con el JSON crudo de cada uno.
- `feargreed`: el valor del dia del Fear & Greed Index (alternative.me, gratis y sin clave;
  atribucion: https://alternative.me/crypto/fear-and-greed-index/).

Los simbolos son los que tiene el archivo de historial (`EXPLORER_HISTORY_DB`) en `1d`; si no
existe, BTCUSDT y ETHUSDT. Un fallo en un simbolo no corta a los demas: se registra y sigue.

Uso:
    python scripts/record_market_data.py orderbook|funding|feargreed [--path history/market_v2.db]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

DEFAULT_PATH = "./history/market_v2.db"
DEPTH_LIMIT = 50
RAW_LEVELS = 20
TIERS = (5, 20, 50)
FALLBACK_SYMBOLS = ("BTCUSDT", "ETHUSDT")
FEAR_GREED_URL = "https://api.alternative.me/fng/"

SCHEMA = """
CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    symbol TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    best_bid REAL, best_ask REAL, mid REAL, spread_bps REAL,
    bid_qty_5 REAL, ask_qty_5 REAL, bid_qty_20 REAL, ask_qty_20 REAL,
    bid_qty_50 REAL, ask_qty_50 REAL,
    bid_notional_50 REAL, ask_notional_50 REAL,
    imbalance_5 REAL, imbalance_20 REAL, imbalance_50 REAL,
    bids_json TEXT, asks_json TEXT,
    PRIMARY KEY (symbol, ts_ms)
);
CREATE TABLE IF NOT EXISTS funding_snapshots (
    symbol TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    funding_rate REAL,
    raw_json TEXT,
    PRIMARY KEY (symbol, ts_ms)
);
CREATE TABLE IF NOT EXISTS fear_greed (
    day_ts_ms INTEGER PRIMARY KEY,
    value INTEGER NOT NULL,
    classification TEXT,
    fetched_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS capture_log (
    ts_ms INTEGER NOT NULL,
    kind TEXT NOT NULL,
    ok INTEGER NOT NULL,
    detail TEXT
);
"""


def check_target(target: str, bot_db: str) -> Path:
    """Valida el archivo destino (mismas reglas que `update_history_file.check_target`).

    Args:
        target: ruta pedida.
        bot_db: ruta de la base del bot.

    Returns:
        La ruta absoluta.

    Raises:
        SystemExit: si apunta a la base del bot, a una carpeta `data/` o no termina en `.db`.
    """
    from scripts.update_history_file import check_target as check

    return check(target, bot_db)


def open_store(path: Path) -> sqlite3.Connection:
    """Abre (o crea) el archivo de datos y su esquema.

    Args:
        path: ruta del archivo SQLite.

    Returns:
        La conexion.

    Efectos:
        Disco: crea la carpeta, el archivo y las tablas si faltan.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def universe_symbols(history_db: str) -> list[str]:
    """Simbolos del archivo de historial (marco 1d), o los de respaldo si no existe.

    Args:
        history_db: ruta del archivo de historial.

    Returns:
        Lista ordenada de simbolos.

    Efectos:
        Lee el archivo de historial en modo inmutable de solo lectura.
    """
    p = Path(history_db)
    if not p.is_file():
        return list(FALLBACK_SYMBOLS)
    uri = p.resolve().as_uri() + "?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as conn:
        rows = conn.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE interval = '1d'")
        symbols = sorted(r[0] for r in rows)
    return symbols or list(FALLBACK_SYMBOLS)


def summarize_depth(depth: dict) -> dict | None:
    """Resumen de una foto del libro de ordenes.

    Args:
        depth: respuesta de `get_depth` (`asks` y `bids` como listas `[precio, cantidad]`).

    Returns:
        Las columnas de `orderbook_snapshots` (sin `symbol` ni `ts_ms`), o `None` si algun lado
        viene vacio.
    """
    def levels(side: str) -> list[tuple[float, float]]:
        out = []
        for row in depth.get(side) or []:
            try:
                out.append((float(row[0]), float(row[1])))
            except (TypeError, ValueError, IndexError):
                continue
        return out

    bids = sorted(levels("bids"), key=lambda x: -x[0])
    asks = sorted(levels("asks"), key=lambda x: x[0])
    if not bids or not asks:
        return None
    best_bid, best_ask = bids[0][0], asks[0][0]
    mid = (best_bid + best_ask) / 2
    row: dict = {"best_bid": best_bid, "best_ask": best_ask, "mid": mid,
                 "spread_bps": (best_ask - best_bid) / mid * 10_000 if mid > 0 else None}
    for n in TIERS:
        b = sum(q for _, q in bids[:n])
        a = sum(q for _, q in asks[:n])
        row[f"bid_qty_{n}"] = b
        row[f"ask_qty_{n}"] = a
        row[f"imbalance_{n}"] = (b - a) / (b + a) if b + a > 0 else None
    row["bid_notional_50"] = sum(p * q for p, q in bids[:50])
    row["ask_notional_50"] = sum(p * q for p, q in asks[:50])
    row["bids_json"] = json.dumps(bids[:RAW_LEVELS])
    row["asks_json"] = json.dumps(asks[:RAW_LEVELS])
    return row


def _log(conn: sqlite3.Connection, kind: str, ok: bool, detail: str) -> None:
    conn.execute("INSERT INTO capture_log VALUES (?, ?, ?, ?)",
                 (int(time.time() * 1000), kind, int(ok), detail[:500]))


async def record_orderbook(conn: sqlite3.Connection, symbols: list[str]) -> int:
    """Una foto del libro de cada simbolo.

    Args:
        conn: archivo de datos abierto.
        symbols: simbolos.

    Returns:
        Cuantas fotos se guardaron.

    Efectos:
        Red: GET publico a Bitunix por simbolo. Escribe `orderbook_snapshots` y `capture_log`.
    """
    from app.config import settings
    from app.market.bitunix_rest import BitunixRestClient

    client = BitunixRestClient(base_url=settings.bitunix_rest_base_url,
                               rate_limit_per_sec=settings.bitunix_rate_limit_per_sec)
    saved, errors = 0, []
    try:
        for symbol in symbols:
            try:
                depth = await client.get_depth(symbol, str(DEPTH_LIMIT))
                ts = int(time.time() * 1000)
                row = summarize_depth(depth)
                if row is None:
                    errors.append(f"{symbol}: libro vacio")
                    continue
                cols = ["symbol", "ts_ms", *row]
                conn.execute(
                    f"INSERT OR REPLACE INTO orderbook_snapshots ({', '.join(cols)}) "
                    f"VALUES ({', '.join('?' for _ in cols)})", (symbol, ts, *row.values()))
                saved += 1
            except Exception as exc:  # noqa: BLE001 - un simbolo no corta a los demas
                errors.append(f"{symbol}: {type(exc).__name__}: {exc}")
    finally:
        await client.aclose()
    _log(conn, "orderbook", not errors, f"{saved} fotos; " + "; ".join(errors))
    conn.commit()
    return saved


async def record_funding(conn: sqlite3.Connection, symbols: list[str]) -> int:
    """Una foto del funding vigente de los simbolos del universo.

    Args:
        conn: archivo de datos abierto.
        symbols: simbolos.

    Returns:
        Cuantos simbolos se guardaron.

    Efectos:
        Red: un GET publico a Bitunix. Escribe `funding_snapshots` y `capture_log`.
    """
    from app.config import settings
    from app.market.bitunix_rest import BitunixRestClient

    client = BitunixRestClient(base_url=settings.bitunix_rest_base_url,
                               rate_limit_per_sec=settings.bitunix_rate_limit_per_sec)
    try:
        rows = await client.get_funding_rate_batch()
    except Exception as exc:  # noqa: BLE001
        _log(conn, "funding", False, f"{type(exc).__name__}: {exc}")
        conn.commit()
        return 0
    finally:
        await client.aclose()
    wanted = set(symbols)
    ts = int(time.time() * 1000)
    saved = 0
    for item in rows:
        if not isinstance(item, dict) or item.get("symbol") not in wanted:
            continue
        try:
            rate = float(item.get("fundingRate"))
        except (TypeError, ValueError):
            rate = None
        conn.execute("INSERT OR REPLACE INTO funding_snapshots VALUES (?, ?, ?, ?)",
                     (item["symbol"], ts, rate, json.dumps(item)))
        saved += 1
    _log(conn, "funding", saved > 0, f"{saved} simbolos")
    conn.commit()
    return saved


async def record_fear_greed(conn: sqlite3.Connection) -> int:
    """El valor del dia del Fear & Greed Index.

    Args:
        conn: archivo de datos abierto.

    Returns:
        1 si se guardo un valor, 0 si no.

    Efectos:
        Red: un GET a alternative.me. Escribe `fear_greed` y `capture_log`.
    """
    from app.core.http import build_async_http_client
    from app.news.parsers import parse_fear_greed

    try:
        async with build_async_http_client(timeout=20) as http:
            resp = await http.get(FEAR_GREED_URL, params={"limit": 1},
                                  headers={"User-Agent": "minerva-v2"})
            resp.raise_for_status()
        points = parse_fear_greed(resp.text)
    except Exception as exc:  # noqa: BLE001
        _log(conn, "feargreed", False, f"{type(exc).__name__}: {exc}")
        conn.commit()
        return 0
    if not points:
        _log(conn, "feargreed", False, "sin datos")
        conn.commit()
        return 0
    p = points[0]
    conn.execute("INSERT OR REPLACE INTO fear_greed VALUES (?, ?, ?, ?)",
                 (int(p.ts.timestamp() * 1000), p.value, p.classification,
                  int(time.time() * 1000)))
    _log(conn, "feargreed", True, f"{p.value} {p.classification}")
    conn.commit()
    return 1


def main() -> None:
    """Valida el destino y toma la foto pedida.

    Efectos:
        Red: Bitunix o alternative.me (publicas). Disco: escribe el archivo de datos de mercado
        (nunca la base del bot).
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("kind", choices=("orderbook", "funding", "feargreed"))
    parser.add_argument("--path", default=os.environ.get("MARKET_DATA_DB", DEFAULT_PATH))
    args = parser.parse_args()
    from app.config import settings

    target = check_target(args.path, settings.database_path)
    conn = open_store(target)
    try:
        if args.kind == "feargreed":
            n = asyncio.run(record_fear_greed(conn))
        else:
            symbols = universe_symbols(settings.explorer_history_db)
            fn = record_orderbook if args.kind == "orderbook" else record_funding
            n = asyncio.run(fn(conn, symbols))
    finally:
        conn.close()
    print(f"{args.kind}: {n} guardados en {target}")


if __name__ == "__main__":
    main()
