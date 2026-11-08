"""Imprime niveles Camarilla y senales SFP de la v2 para compararlos a mano con TradingView.

Requisito del preregistro de la v2 (`docs/v2/PREREGISTRO_V2.md`): antes de congelarlo, el dueno
compara contra el grafico de TradingView, para BTCUSDT y ETHUSDT:

1. Los niveles Camarilla R3, R4, S3 y S4 de tres dias UTC (por defecto 2026-11-05, 2026-11-06 y
   2026-11-07), calculados con el maximo, el minimo y el cierre del dia UTC anterior agregados
   desde velas de 1h. Tambien imprime la vela diaria de Bitunix de ese dia anterior, para ver si
   el agregado coincide con la vela diaria que usaria TradingView.
2. Las ultimas 10 senales SFP (pivote 5/1) en 1h, con la hora UTC de la vela de barrida (donde el
   original pone la etiqueta «SFP») y de la vela de confirmacion (la flecha, que es la senal).

Las velas son LAST_PRICE de Bitunix Futures (endpoint publico verificado en
`app/market/bitunix_rest.py`). Para comparar, abrir en TradingView el mismo par perpetuo de
Bitunix y poner el grafico en UTC: con otro exchange los precios difieren un poco.

Es de solo lectura: no lee `.env`, no abre ninguna base y no escribe nada.

    python scripts/v2_tradingview_check.py
    python scripts/v2_tradingview_check.py --symbols BTCUSDT --days 2026-11-06 --sfp-count 5
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

sys.path.insert(0, ".")

from app.config import Settings  # noqa: E402
from app.indicators.levels import DAY_MS, camarilla_levels  # noqa: E402
from app.indicators.structure import sfp_signals  # noqa: E402
from app.market.bitunix_rest import BitunixRestClient  # noqa: E402

HOUR_MS = 3_600_000
PAGE = 200
DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT")
DEFAULT_DAYS = ("2026-11-05", "2026-11-06", "2026-11-07")
# El URL por defecto de la configuracion, sin leer `.env` ni variables de entorno.
BITUNIX_URL = Settings.model_fields["bitunix_rest_base_url"].default


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M")


def frame_from_raw(raw: list[dict[str, Any]], step_ms: int, now_ms: int) -> pd.DataFrame:
    """Velas crudas de Bitunix -> DataFrame ordenado, sin duplicados ni la vela en curso.

    Args:
        raw: diccionarios de `get_kline` (`time`, `open`, `high`, `low`, `close`).
        step_ms: duracion de la vela en ms.
        now_ms: instante actual en ms (descarta la vela que aun no cerro).

    Returns:
        DataFrame con `open_time`, `open`, `high`, `low` y `close`.
    """
    df = pd.DataFrame([{
        "open_time": int(r["time"]), "open": float(r["open"]), "high": float(r["high"]),
        "low": float(r["low"]), "close": float(r["close"]),
    } for r in raw], columns=["open_time", "open", "high", "low", "close"])
    df = df.drop_duplicates("open_time").sort_values("open_time")
    df = df[df["open_time"] + step_ms <= now_ms]
    return df.reset_index(drop=True)


async def fetch_bars(
    client: Any, symbol: str, interval: str, step_ms: int, bars: int, now_ms: int
) -> pd.DataFrame:
    """Descarga hacia atras las ultimas `bars` velas cerradas (paginas de 200).

    Args:
        client: cliente con `get_kline` (un `BitunixRestClient`).
        symbol: simbolo, p. ej. `BTCUSDT`.
        interval: `1h` o `1d`.
        step_ms: duracion de la vela en ms.
        bars: cuantas velas juntar como minimo.
        now_ms: instante actual en ms.

    Returns:
        Las velas cerradas, en orden cronologico.

    Efectos:
        Red: GET publicos a Bitunix (`/api/v1/futures/market/kline`).
    """
    raw: list[dict[str, Any]] = []
    cursor = now_ms
    while len(raw) < bars:
        page = await client.get_kline(symbol=symbol, interval=interval, end_time=cursor,
                                      limit=PAGE, price_type="LAST_PRICE")
        if not page:
            break
        raw.extend(page)
        oldest = min(int(r["time"]) for r in page)
        if oldest >= cursor:
            break
        cursor = oldest
    return frame_from_raw(raw, step_ms, now_ms)


def camarilla_lines(symbol: str, hourly: pd.DataFrame, daily: pd.DataFrame,
                    days: list[date]) -> list[str]:
    """Lineas con R3/R4/S3/S4 de cada dia pedido y la vela diaria de Bitunix del dia anterior.

    Args:
        symbol: simbolo.
        hourly: velas de 1h con `open_time`.
        daily: velas de 1d de Bitunix con `open_time`.
        days: dias UTC a informar.

    Returns:
        Las lineas de texto.
    """
    levels = camarilla_levels(hourly, interval_ms=HOUR_MS)
    day_of_bar = hourly["open_time"] // DAY_MS
    lines = [f"Camarilla {symbol} (dia UTC anterior agregado desde 1h)"]
    for d in days:
        day_index = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000) // DAY_MS
        rows = levels[day_of_bar == day_index]
        if rows.empty or rows["cam_r3"].isna().all():
            lines.append(f"  {d}: sin datos completos del dia anterior")
            continue
        row = rows.iloc[0]
        prev = daily[daily["open_time"] // DAY_MS == day_index - 1]
        lines.append(
            f"  {d}: R4 {row['cam_r4']:.2f}  R3 {row['cam_r3']:.2f}  "
            f"S3 {row['cam_s3']:.2f}  S4 {row['cam_s4']:.2f}   "
            f"(dia anterior agregado: H {row['cam_prev_high']:.2f} L {row['cam_prev_low']:.2f} "
            f"C {row['cam_prev_close']:.2f})"
        )
        if prev.empty:
            lines.append("      vela diaria de Bitunix del dia anterior: no disponible")
        else:
            p = prev.iloc[0]
            same = (p["high"] == row["cam_prev_high"] and p["low"] == row["cam_prev_low"]
                    and p["close"] == row["cam_prev_close"])
            lines.append(
                f"      vela diaria de Bitunix del dia anterior: H {p['high']:.2f} "
                f"L {p['low']:.2f} C {p['close']:.2f} -> "
                f"{'coincide' if same else 'NO coincide con el agregado'}"
            )
    return lines


def sfp_lines(symbol: str, hourly: pd.DataFrame, count: int) -> list[str]:
    """Lineas con las ultimas `count` senales SFP (5/1) en 1h.

    Args:
        symbol: simbolo.
        hourly: velas de 1h con `open_time`.
        count: cuantas senales mostrar (las mas recientes).

    Returns:
        Las lineas de texto.
    """
    sfp = sfp_signals(hourly)
    events = []
    for side, label in (("bear", "BAJISTA (corto)"), ("bull", "ALCISTA (largo)")):
        for i in sfp.index[sfp[f"sfp_{side}_signal"]]:
            sweep_i = i - int(sfp.at[i, f"sfp_{side}_bars_since_sweep"])
            events.append((i, label, sweep_i, sfp.at[i, f"sfp_{side}_swing"],
                           sfp.at[i, f"sfp_{side}_opposite"],
                           sfp.at[i, f"sfp_{side}_sweep_extreme"]))
    events.sort()
    lines = [f"SFP {symbol} 1h: ultimas {count} senales (horas UTC de apertura de la vela)"]
    if not events:
        lines.append("  ninguna en el historial descargado")
    for i, label, sweep_i, swing, opposite, extreme in events[-count:]:
        lines.append(
            f"  confirmacion {_utc(int(hourly.at[i, 'open_time']))}  {label}  "
            f"barrida {_utc(int(hourly.at[sweep_i, 'open_time']))}  pivote {swing:.2f}  "
            f"extremo opuesto {opposite:.2f}  mecha {extreme:.2f}"
        )
    return lines


async def build_report(client: Any, symbols: list[str], days: list[date], sfp_count: int,
                       history_bars: int, now_ms: int) -> list[str]:
    """Descarga las velas y arma el informe completo.

    Args:
        client: cliente con `get_kline`.
        symbols: simbolos a informar.
        days: dias UTC para Camarilla.
        sfp_count: senales SFP a mostrar por simbolo.
        history_bars: velas de 1h a descargar (el SFP necesita historia para su estado).
        now_ms: instante actual en ms.

    Returns:
        Las lineas del informe.

    Efectos:
        Red: GET publicos a Bitunix.
    """
    lines = [f"Velas LAST_PRICE de Bitunix Futures; generado {_utc(now_ms)} UTC.",
             "En TradingView: mismo par perpetuo de Bitunix y zona horaria UTC.", ""]
    for symbol in symbols:
        hourly = await fetch_bars(client, symbol, "1h", HOUR_MS, history_bars, now_ms)
        daily = await fetch_bars(client, symbol, "1d", DAY_MS, 120, now_ms)
        lines += camarilla_lines(symbol, hourly, daily, days)
        lines += sfp_lines(symbol, hourly, sfp_count)
        lines.append("")
    return lines


def main() -> None:
    """Punto de entrada: imprime el informe.

    Efectos:
        Red: GET publicos a Bitunix. No escribe nada.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--days", nargs="+", default=list(DEFAULT_DAYS),
                        help="dias UTC (AAAA-MM-DD) para los niveles Camarilla")
    parser.add_argument("--sfp-count", type=int, default=10)
    parser.add_argument("--history-bars", type=int, default=2000)
    args = parser.parse_args()
    days = [date.fromisoformat(d) for d in args.days]

    async def run() -> list[str]:
        client = BitunixRestClient(BITUNIX_URL, rate_limit_per_sec=4)
        try:
            return await build_report(client, args.symbols, days, args.sfp_count,
                                      args.history_bars, int(time.time() * 1000))
        finally:
            await client.aclose()

    print("\n".join(asyncio.run(run())))


if __name__ == "__main__":
    main()
