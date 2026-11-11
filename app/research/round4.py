"""Ronda 4 exploratoria: fuerza relativa entre monedas, squeeze + ADX y volumen.

Extiende `app.research.round3` sin cambiar su interfaz:

- **Gatillos de fuerza relativa `mom42` y `mom180`** (rebalanceo semanal): en la vela de 4h que
  cierra el lunes 00:00 UTC se ordenan las monedas del universo por su retorno de 42 velas (una
  semana) o de 180 (un mes). LARGO en las `TOP_N` mas fuertes y CORTO en las `TOP_N` mas debiles,
  si hay al menos `MIN_RANKED` monedas con retorno. Se sostienen `HOLD_BARS` velas (una semana) y
  se cierran por tiempo; al cerrar, la misma vela ya puede dar la senal de la semana siguiente.
  Necesitan el contexto del universo (`set_universe_context`).
- **Gatillo `squeeze`** (TTM Squeeze, la idea del SQZ del dueno): la compresion esta activa cuando
  las Bollinger (20, 2) quedan dentro de las Keltner (20, 1.5 ATR de 20). Senal en la primera vela
  sin compresion tras al menos `SQUEEZE_MIN_BARS` con compresion; LARGO si el momentum (regresion
  lineal de 20 velas de `close - media(media(maximo, minimo de 20), SMA 20)`) es positivo, CORTO si
  es negativo.
- **Filtros nuevos:** `adx` (ADX(14) > 20, para los dos lados), `vol` (volumen en USDT de la vela
  mayor que el doble de su media de 20 velas, para los dos lados) y `vwap` (cierre sobre el VWAP
  semanal anclado al lunes 00:00 UTC para un largo, bajo el VWAP para un corto).
- **Salidas de rebalanceo** (`TIME_EXITS`, solo para `mom42`/`mom180`): sin TP; SL fijo del 4.5 %
  (`t42_sl45`, justo bajo el tope de riesgo del 5 %) o a 2.5 ATR(14) (`t42_s25`), y cierre por
  tiempo a las 42 velas. Los demas gatillos usan las salidas de `round3.EXITS`.

Todo es causal: el ranking de la vela `i` usa cierres hasta `i` de todas las monedas, con la misma
apertura.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import numpy as np
import pandas as pd

from app.candidates.common import WARMUP_BARS
from app.indicators._pine import pine_atr, pine_rma, pine_sma, pine_stdev
from app.research.combos import interval_of
from app.research.round3 import (
    ENTRY_MODES,
    EXITS,
    R3_FILTERS,
    R3_TRIGGERS,
    Round3Strategy,
    compute_features_r3,
)
from app.strategies.base import Signal

MOM_TRIGGERS = {"mom42": 42, "mom180": 180}
R4_TRIGGERS = (*R3_TRIGGERS, *MOM_TRIGGERS, "squeeze")
R4_FILTERS = (*R3_FILTERS, "adx", "vol", "vwap")
# nombre -> (SL en ATR o None, SL en fraccion del precio o None)
TIME_EXITS: dict[str, tuple[float | None, float | None]] = {
    "t42_sl45": (None, 0.045),
    "t42_s25": (2.5, None),
}
TOP_N = 3
MIN_RANKED = 6
HOLD_BARS = 42
WEEK_MS = 7 * 86_400_000
MONDAY_OFFSET_MS = 4 * 86_400_000  # el 1970-01-05 fue lunes
SQUEEZE_MIN_BARS = 6
ADX_MIN = 20.0
VOL_MULT = 2.0

_UNIVERSE: dict[str, pd.DataFrame] = {}
_R4_CACHE: dict[tuple, pd.DataFrame] = {}


def set_universe_context(interval: str, closes: Mapping[str, pd.DataFrame]) -> None:
    """Registra los cierres del universo de un marco para el ranking de fuerza relativa.

    Args:
        interval: marco (`4h`).
        closes: por simbolo, velas con `open_time` y `close`.
    """
    frame = pd.DataFrame({
        symbol: pd.Series(df["close"].to_numpy(dtype=float),
                          index=df["open_time"].to_numpy(dtype="int64"))
        for symbol, df in closes.items()
    }).sort_index()
    _UNIVERSE[interval] = frame
    _R4_CACHE.clear()


def _identify_symbol(frame: pd.DataFrame, df: pd.DataFrame) -> str | None:
    """Que columna del universo es la serie `df` (compara cierres en aperturas comunes)."""
    times = df["open_time"].to_numpy(dtype="int64")
    close = df["close"].to_numpy(dtype=float)
    sample = slice(max(0, len(times) - 200), len(times))
    for symbol in frame.columns:
        ref = frame[symbol].reindex(times[sample]).to_numpy()
        ok = ~np.isnan(ref)
        if ok.sum() >= 20 and np.allclose(ref[ok], close[sample][ok]):
            return symbol
    return None


def momentum_signals(frame: pd.DataFrame, symbol: str, lookback: int, step_ms: int,
                     top_n: int = TOP_N, min_ranked: int = MIN_RANKED) -> pd.DataFrame:
    """Senales de rebalanceo semanal por fuerza relativa para un simbolo del universo.

    Args:
        frame: cierres del universo (indice `open_time`, una columna por simbolo).
        symbol: columna del simbolo.
        lookback: velas del retorno que ordena.
        step_ms: duracion de la vela.
        top_n: monedas por lado.
        min_ranked: minimo de monedas con retorno para ordenar.

    Returns:
        DataFrame indexado por `open_time` con `mom_long` y `mom_short`.
    """
    ret = frame / frame.shift(lookback) - 1
    close_ms = frame.index.to_numpy(dtype="int64") + step_ms
    rebalance = (close_ms - MONDAY_OFFSET_MS) % WEEK_MS == 0
    count = ret.notna().sum(axis=1).to_numpy()
    rank_desc = ret.rank(axis=1, ascending=False, method="first")[symbol].to_numpy()
    rank_asc = ret.rank(axis=1, ascending=True, method="first")[symbol].to_numpy()
    valid = rebalance & (count >= min_ranked) & ~np.isnan(rank_desc)
    return pd.DataFrame({"mom_long": valid & (rank_desc <= top_n),
                         "mom_short": valid & (rank_asc <= top_n)}, index=frame.index)


def ttm_squeeze(df: pd.DataFrame, length: int = 20, bb_mult: float = 2.0,
                kc_mult: float = 1.5, min_bars: int = SQUEEZE_MIN_BARS) -> pd.DataFrame:
    """Senales del TTM Squeeze (ver el docstring del modulo).

    Args:
        df: velas con `high`, `low` y `close`.
        length: periodo de Bollinger, Keltner y momentum.
        bb_mult: desviaciones de las Bollinger.
        kc_mult: ATR de las Keltner.
        min_bars: velas de compresion necesarias antes de la salida.

    Returns:
        DataFrame con el mismo indice y columnas `sqz_on`, `sqz_long` y `sqz_short`.
    """
    close = df["close"].astype(float)
    basis = pine_sma(close, length)
    dev = pine_stdev(close, length) * bb_mult
    atr = pine_atr(df, length) * kc_mult
    on = ((basis - dev) > (basis - atr)) & ((basis + dev) < (basis + atr))
    mid = (df["high"].rolling(length).max() + df["low"].rolling(length).min()) / 2
    src = (close - (mid + basis) / 2).to_numpy()
    x = np.arange(length, dtype=float)
    x_c = x - x.mean()
    denom = (x_c ** 2).sum()
    mom = np.full(len(src), np.nan)
    for i in range(length - 1, len(src)):
        window = src[i - length + 1: i + 1]
        if np.isnan(window).any():
            continue
        slope = (x_c * (window - window.mean())).sum() / denom
        mom[i] = window.mean() + slope * x_c[-1]
    on_arr = on.fillna(False).to_numpy()
    run = np.zeros(len(on_arr), dtype=int)
    for i in range(len(on_arr)):
        run[i] = run[i - 1] + 1 if on_arr[i] and i > 0 else (1 if on_arr[i] else 0)
    prev_run = np.concatenate(([0], run[:-1]))
    fire = ~on_arr & (prev_run >= min_bars)
    with np.errstate(invalid="ignore"):
        return pd.DataFrame({"sqz_on": on_arr, "sqz_long": fire & (mom > 0),
                             "sqz_short": fire & (mom < 0)}, index=df.index)


def adx(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """ADX de Wilder (`ta.dmi` de Pine).

    Args:
        df: velas con `high`, `low` y `close`.
        length: periodo (14).

    Returns:
        El ADX de cada vela (NaN en el calentamiento).
    """
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = pine_rma(pine_atr(df, 1), length)
    plus = 100 * pine_rma(plus_dm, length) / tr
    minus = 100 * pine_rma(minus_dm, length) / tr
    dx = 100 * (plus - minus).abs() / (plus + minus)
    return pine_rma(dx, length)


def weekly_vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP anclado al lunes 00:00 UTC (precio tipico ponderado por el volumen en USDT).

    Args:
        df: velas con `open_time`, `high`, `low`, `close` y `volume`.

    Returns:
        El VWAP de la semana hasta el cierre de cada vela (NaN sin volumen).
    """
    week = (df["open_time"].astype("int64") - MONDAY_OFFSET_MS) // WEEK_MS
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].astype(float)
    num = (typical * vol).groupby(week).cumsum()
    den = vol.groupby(week).cumsum()
    return num / den.where(den > 0)


def compute_features_r4(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Columnas de la ronda 3 mas fuerza relativa, squeeze, ADX, volumen y VWAP.

    Args:
        df: velas de toda la serie (`open_time`, OHLC, `volume` y, si existe, `funding_rate`).
        interval: marco de la serie.

    Returns:
        Copia con `long_`/`short_` de `mom42`, `mom180` y `squeeze`, y `bull_`/`bear_` de `adx`,
        `vol` y `vwap`. Sin contexto del universo, los gatillos de fuerza relativa quedan en falso;
        sin columna `volume`, `vol` y `vwap` tambien.
    """
    key = (interval, len(df), int(df["open_time"].iloc[0]), int(df["open_time"].iloc[-1]),
           float(df["close"].sum()))
    if key in _R4_CACHE:
        return _R4_CACHE[key]
    out = compute_features_r3(df, interval).copy()
    step_ms = int(np.median(np.diff(out["open_time"].to_numpy(dtype="int64")[:50])))

    frame = _UNIVERSE.get(interval)
    symbol = _identify_symbol(frame, out) if frame is not None else None
    for name, lookback in MOM_TRIGGERS.items():
        if symbol is None:
            out[f"long_{name}"] = False
            out[f"short_{name}"] = False
            continue
        sig = momentum_signals(frame, symbol, lookback, step_ms)
        aligned = sig.reindex(out["open_time"].to_numpy(dtype="int64"))
        out[f"long_{name}"] = aligned["mom_long"].fillna(False).to_numpy(dtype=bool)
        out[f"short_{name}"] = aligned["mom_short"].fillna(False).to_numpy(dtype=bool)

    sq = ttm_squeeze(out)
    out["long_squeeze"] = sq["sqz_long"].to_numpy()
    out["short_squeeze"] = sq["sqz_short"].to_numpy()

    strong = (adx(out) > ADX_MIN).fillna(False).to_numpy()
    out["bull_adx"] = strong
    out["bear_adx"] = strong

    if "volume" in out.columns and out["volume"].notna().any():
        vol = out["volume"].astype(float)
        spike = (vol > VOL_MULT * vol.rolling(20, min_periods=20).mean()).fillna(False)
        out["bull_vol"] = spike.to_numpy()
        out["bear_vol"] = spike.to_numpy()
        vwap = weekly_vwap(out)
        with np.errstate(invalid="ignore"):
            out["bull_vwap"] = (out["close"] > vwap).to_numpy()
            out["bear_vwap"] = (out["close"] < vwap).to_numpy()
    else:
        for col in ("bull_vol", "bear_vol", "bull_vwap", "bear_vwap"):
            out[col] = False
    if len(_R4_CACHE) > 64:
        _R4_CACHE.clear()
    _R4_CACHE[key] = out
    return out


class Round4Strategy(Round3Strategy):
    """Gatillo + filtros + salida + entrada, con los gatillos y filtros de la ronda 4.

    Attributes:
        name: `r4|<gatillo>|<filtros>|<salida>|<entrada>` (con `|rnd` si la direccion es al azar).
        max_hold_bars: velas hasta el cierre por tiempo (solo salidas de `TIME_EXITS`; lo lee el
            motor).
    """

    def __init__(self, trigger: str, filters: Iterable[str] = (), *, exit_name: str = "base",
                 entry_mode: str = "market", random_dir: bool = False,
                 warmup: int = WARMUP_BARS) -> None:
        """Valida y fija la variante.

        Args:
            trigger: uno de `R4_TRIGGERS`.
            filters: subconjunto de `R4_FILTERS`.
            exit_name: clave de `TIME_EXITS` (obligatoria para `mom42`/`mom180`) o de `EXITS`.
            entry_mode: `market` o `limit`.
            random_dir: sortea la direccion en las mismas velas.
            warmup: velas sin senal al inicio.

        Raises:
            ValueError: si algun nombre no existe o la salida no corresponde al gatillo.
        """
        self.filters = tuple(sorted(set(filters)))
        is_mom = trigger in MOM_TRIGGERS
        valid_exit = exit_name in TIME_EXITS if is_mom else exit_name in EXITS
        if (trigger not in R4_TRIGGERS or set(self.filters) - set(R4_FILTERS) or not valid_exit
                or entry_mode not in ENTRY_MODES):
            raise ValueError(f"variante desconocida: {trigger} {self.filters} {exit_name} "
                             f"{entry_mode}")
        self.trigger = trigger
        self.exit_name = exit_name
        self.exit_mode = exit_name
        self.entry_mode = entry_mode
        self.random_dir = random_dir
        self.warmup = warmup
        self.max_hold_bars = HOLD_BARS if is_mom else None
        parts = ["r4", trigger, "+".join(self.filters) or "nada", exit_name, entry_mode]
        if random_dir:
            parts.append("rnd")
        self.name = "|".join(parts)

    def precompute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Columnas de `compute_features_r4` para la serie completa.

        Args:
            df: velas de toda la serie.

        Returns:
            Copia de `df` con todas las columnas de la ronda 4.
        """
        return compute_features_r4(df, interval_of(df))

    def _row(self, df: pd.DataFrame) -> pd.Series:
        if "long_squeeze" not in df.columns:
            df = self.precompute(df)
        return df.iloc[-1]

    def _distance(self, row: pd.Series, entry: float) -> float:
        if self.trigger in MOM_TRIGGERS:
            atr_mult, pct = TIME_EXITS[self.exit_name]
            return pct * entry if pct is not None else atr_mult * float(row["x_atr14"])
        return super()._distance(row, entry)

    def take_profit_price(self, df: pd.DataFrame, side: Signal, entry_price: float) -> float | None:
        """Sin TP en las salidas de rebalanceo; si no, el de la salida de la ronda 3.

        Args:
            df: velas hasta la de la senal.
            side: direccion de la entrada.
            entry_price: precio de entrada.

        Returns:
            El precio del TP, o `None`.
        """
        if self.trigger in MOM_TRIGGERS:
            return None
        return super().take_profit_price(df, side, entry_price)

    def trailing_distance(self, df: pd.DataFrame) -> float | None:
        """Sin trailing en las salidas de rebalanceo; si no, el de la salida de la ronda 3.

        Args:
            df: velas hasta la de la senal.

        Returns:
            La distancia del trailing, o `None`.
        """
        if self.trigger in MOM_TRIGGERS:
            return None
        return super().trailing_distance(df)
