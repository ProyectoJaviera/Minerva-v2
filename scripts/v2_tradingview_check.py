"""Imprime niveles Camarilla y senales SFP de la v2 para compararlos a mano con TradingView.

Requisito del preregistro de la v2 (`docs/v2/PREREGISTRO_V2.md`): antes de congelarlo, el dueno
compara contra el grafico de TradingView, para BTCUSDT y ETHUSDT:

1. Los niveles Camarilla R3, R4, S3 y S4 de tres dias UTC (por defecto 2026-11-05, 2026-11-06 y
   2026-11-07), calculados con el maximo, el minimo y el cierre del dia UTC anterior agregados
   desde velas de 1h. Tambien imprime la vela diaria de Bitunix de ese dia anterior, para ver si
   el agregado coincide con la vela diaria que usaria TradingView.
2. Las ultimas 10 senales SFP (pivote 5/1) en 1h (o 4h con `--interval 4h`), con la hora UTC de
   la vela de barrida (donde el original pone la etiqueta «SFP») y de la vela de confirmacion (la
   flecha, que es la senal), mas el ATR(14) de la vela de senal (el del colchon del SL).
3. Con `--rf-count N`, los ultimos N giros del Range Filter de Frost (modo Intraday; el ▲/▼ de
   Frost), con la EMA 144 y el ATR(14) de esa vela, que es lo que usa `range_filter_flip_ema144`.

Con `--end AAAA-MM-DD` todo se calcula como si «ahora» fuera esa fecha a las 00:00 UTC, para
comparar semanas pasadas; con `--skip-camarilla` se omiten los niveles.

Las velas son LAST_PRICE de Bitunix Futures (endpoint publico verificado en
`app/market/bitunix_rest.py`). Para comparar, abrir en TradingView el mismo par perpetuo de
Bitunix y poner el grafico en UTC: con otro exchange los precios difieren un poco.

Es de solo lectura: no lee `.env`, no abre ninguna base y no escribe nada.

    python scripts/v2_tradingview_check.py
    python scripts/v2_tradingview_check.py --symbols BTCUSDT --days 2026-11-06 --sfp-count 5
    python scripts/v2_tradingview_check.py --interval 4h --skip-camarilla --rf-count 10
    python scripts/v2_tradingview_check.py --end 2025-06-15 --skip-camarilla --sfp-count 15
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
from app.indicators._pine import pine_atr, pine_ema  # noqa: E402
from app.indicators.levels import DAY_MS, camarilla_levels  # noqa: E402
from app.indicators.structure import sfp_signals  # noqa: E402
from app.indicators.trend_filters import range_filter  # noqa: E402
from app.market.bitunix_rest import BitunixRestClient  # noqa: E402

HOUR_MS = 3_600_000
INTERVAL_MS = {"1h": HOUR_MS, "4h": 4 * HOUR_MS, "1d": 24 * HOUR_MS, "1w": 7 * 24 * HOUR_MS}
# Las semanas se agregan desde las velas de 1d, con inicio el lunes 00:00 UTC (como TradingView);
# no se usa un intervalo semanal de Bitunix porque no esta verificado en el repo. El 1970-01-01
# fue jueves: el primer lunes (1970-01-05) esta 4 dias despues del origen.
WEEK_OFFSET_MS = 4 * 24 * HOUR_MS
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


def weekly_from_daily(daily: pd.DataFrame, now_ms: int) -> pd.DataFrame:
    """Agrega velas de 1d en semanas lunes-domingo UTC y descarta la semana en curso.

    Args:
        daily: velas de 1d con `open_time`, `open`, `high`, `low` y `close`.
        now_ms: instante actual en ms (una semana solo cuenta si ya cerro).

    Returns:
        DataFrame semanal con las mismas columnas; `open_time` es el lunes 00:00 UTC.
    """
    week = INTERVAL_MS["1w"]
    start = (daily["open_time"] - WEEK_OFFSET_MS) // week * week + WEEK_OFFSET_MS
    out = daily.assign(open_time=start).groupby("open_time", sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
    ).reset_index()
    out = out[out["open_time"] + week <= now_ms]
    return out.reset_index(drop=True)


async def fetch_interval(client: Any, symbol: str, interval: str, bars: int,
                         now_ms: int) -> pd.DataFrame:
    """Velas cerradas de `interval`; las semanales salen de agregar velas de 1d.

    Args:
        client: cliente con `get_kline`.
        symbol: simbolo.
        interval: `1h`, `4h`, `1d` o `1w`.
        bars: velas a juntar como minimo.
        now_ms: instante actual en ms.

    Returns:
        Las velas cerradas, en orden cronologico.

    Efectos:
        Red: GET publicos a Bitunix.
    """
    if interval == "1w":
        daily = await fetch_bars(client, symbol, "1d", INTERVAL_MS["1d"], bars * 7, now_ms)
        return weekly_from_daily(daily, now_ms)
    return await fetch_bars(client, symbol, interval, INTERVAL_MS[interval], bars, now_ms)


def bars_lines(symbol: str, bars: pd.DataFrame, count: int, interval: str) -> list[str]:
    """Lineas con el OHLC de las ultimas `count` velas, para compararlas una a una.

    Args:
        symbol: simbolo.
        bars: velas con `open_time` y OHLC.
        count: cuantas velas mostrar.
        interval: etiqueta de la temporalidad.

    Returns:
        Las lineas de texto.
    """
    lines = [f"Velas {symbol} {interval}: ultimas {count} (hora UTC de apertura)"]
    for row in bars.tail(count).itertuples():
        lines.append(f"  {_utc(int(row.open_time))}  O {row.open:.2f}  H {row.high:.2f}  "
                     f"L {row.low:.2f}  C {row.close:.2f}")
    return lines


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


def sfp_lines(symbol: str, hourly: pd.DataFrame, count: int, interval: str = "1h") -> list[str]:
    """Lineas con las ultimas `count` senales SFP (5/1) y el ATR(14) de la vela de senal.

    Args:
        symbol: simbolo.
        hourly: velas de `interval` con `open_time`.
        count: cuantas senales mostrar (las mas recientes).
        interval: etiqueta de la temporalidad (`1h` o `4h`), solo para el texto.

    Returns:
        Las lineas de texto.
    """
    sfp = sfp_signals(hourly)
    atr = pine_atr(hourly, 14)
    events = []
    for side, label in (("bear", "BAJISTA (corto)"), ("bull", "ALCISTA (largo)")):
        for i in sfp.index[sfp[f"sfp_{side}_signal"]]:
            sweep_i = i - int(sfp.at[i, f"sfp_{side}_bars_since_sweep"])
            events.append((i, label, sweep_i, sfp.at[i, f"sfp_{side}_swing"],
                           sfp.at[i, f"sfp_{side}_opposite"],
                           sfp.at[i, f"sfp_{side}_sweep_extreme"]))
    events.sort()
    lines = [f"SFP {symbol} {interval}: ultimas {count} senales (horas UTC de apertura de la vela)"]
    if not events:
        lines.append("  ninguna en el historial descargado")
    for i, label, sweep_i, swing, opposite, extreme in events[-count:]:
        lines.append(
            f"  confirmacion {_utc(int(hourly.at[i, 'open_time']))}  {label}  "
            f"barrida {_utc(int(hourly.at[sweep_i, 'open_time']))}  pivote {swing:.2f}  "
            f"extremo opuesto {opposite:.2f}  mecha {extreme:.2f}  ATR14 {atr.iat[i]:.2f}"
        )
    return lines


def rf_lines(symbol: str, bars: pd.DataFrame, count: int, interval: str) -> list[str]:
    """Lineas con los ultimos `count` giros del Range Filter (modo Intraday), EMA 144 y ATR(14).

    Usa las mismas funciones que `range_filter_flip_ema144` (`range_filter`, `pine_ema`,
    `pine_atr`). Un giro solo es senal del candidato si el cierre esta del lado de la EMA.

    Args:
        symbol: simbolo.
        bars: velas con `open_time`, `high`, `low` y `close`.
        count: cuantos giros mostrar (los mas recientes).
        interval: etiqueta de la temporalidad, solo para el texto.

    Returns:
        Las lineas de texto.
    """
    rf = range_filter(bars["close"])
    ema = pine_ema(bars["close"], 144)
    atr = pine_atr(bars, 14)
    flips = [(i, bool(rf.at[i, "rf_buy"])) for i in rf.index[rf["rf_buy"] | rf["rf_sell"]]]
    lines = [f"Range Filter {symbol} {interval}: ultimos {count} giros (hora UTC de apertura)"]
    if not flips:
        lines.append("  ninguno en el historial descargado")
    for i, buy in flips[-count:]:
        close, e = float(bars.at[i, "close"]), float(ema.iat[i])
        candidate = (buy and close > e) or (not buy and close < e)
        tag = "-> senal del candidato" if candidate else "(filtrada por EMA)"
        lines.append(
            f"  {_utc(int(bars.at[i, 'open_time']))}  {'COMPRA (▲)' if buy else 'VENTA (▼)'}  "
            f"cierre {close:.2f}  filtro {rf.at[i, 'rf_filter']:.2f}  EMA144 {e:.2f}  "
            f"ATR14 {atr.iat[i]:.2f}  {tag}"
        )
    return lines


async def build_report(client: Any, symbols: list[str], days: list[date], sfp_count: int,
                       history_bars: int, now_ms: int, interval: str = "1h",
                       rf_count: int = 0, bar_count: int = 0) -> list[str]:
    """Descarga las velas y arma el informe completo.

    Args:
        client: cliente con `get_kline`.
        symbols: simbolos a informar.
        days: dias UTC para Camarilla.
        sfp_count: senales SFP a mostrar por simbolo (0 = ninguna).
        history_bars: velas de 1h a descargar (el SFP necesita historia para su estado).
        now_ms: instante actual en ms (o el corte de `--end`).
        interval: temporalidad de SFP y Range Filter (`1h` o `4h`).
        rf_count: giros del Range Filter a mostrar (0 = ninguno).
        bar_count: velas OHLC a listar (0 = ninguna).

    Returns:
        Las lineas del informe.

    Efectos:
        Red: GET publicos a Bitunix.
    """
    lines = [f"Velas LAST_PRICE de Bitunix Futures; generado {_utc(now_ms)} UTC.",
             "En TradingView: mismo par perpetuo de Bitunix y zona horaria UTC.", ""]
    for symbol in symbols:
        if days:
            hourly = await fetch_bars(client, symbol, "1h", HOUR_MS, history_bars, now_ms)
            daily = await fetch_bars(client, symbol, "1d", DAY_MS, 120, now_ms)
            lines += camarilla_lines(symbol, hourly, daily, days)
        bars = await fetch_interval(client, symbol, interval, history_bars, now_ms)
        if bars.empty:
            lines += [f"{symbol} {interval}: sin velas hasta {_utc(now_ms)} UTC", ""]
            continue
        lines.append(f"{symbol}: {len(bars)} velas de {interval} desde "
                     f"{_utc(int(bars['open_time'].iat[0]))} hasta "
                     f"{_utc(int(bars['open_time'].iat[-1]))} UTC")
        if bar_count:
            lines += bars_lines(symbol, bars, bar_count, interval)
        if sfp_count:
            lines += sfp_lines(symbol, bars, sfp_count, interval)
        if rf_count:
            lines += rf_lines(symbol, bars, rf_count, interval)
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
    parser.add_argument("--interval", choices=sorted(INTERVAL_MS), default="1h",
                        help="temporalidad de SFP y Range Filter")
    parser.add_argument("--rf-count", type=int, default=0,
                        help="giros del Range Filter a mostrar (0 = ninguno)")
    parser.add_argument("--bars", type=int, default=0,
                        help="velas OHLC a listar antes del corte (0 = ninguna)")
    parser.add_argument("--end", help="corte AAAA-MM-DD (00:00 UTC) para mirar semanas pasadas")
    parser.add_argument("--skip-camarilla", action="store_true")
    args = parser.parse_args()
    days = [] if args.skip_camarilla else [date.fromisoformat(d) for d in args.days]
    now_ms = int(time.time() * 1000)
    if args.end:
        end = date.fromisoformat(args.end)
        end_ms = int(datetime(end.year, end.month, end.day, tzinfo=UTC).timestamp() * 1000)
        now_ms = min(now_ms, end_ms)

    async def run() -> list[str]:
        client = BitunixRestClient(BITUNIX_URL, rate_limit_per_sec=4)
        try:
            return await build_report(client, args.symbols, days, args.sfp_count,
                                      args.history_bars, now_ms, args.interval, args.rf_count,
                                      args.bars)
        finally:
            await client.aclose()

    print("\n".join(asyncio.run(run())))


if __name__ == "__main__":
    main()
