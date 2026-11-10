"""Ronda 3 exploratoria: FVG, informacion distinta al precio propio, salidas y orden limite.

Extiende `app.research.combos` sin cambiar su interfaz:

- **Gatillo nuevo `fvg`** (Fair Value Gap, definicion estandar de 3 velas; no viene en los
  indicadores de referencia): hay un FVG alcista en la vela `i` si `low[i] > high[i-2]` y el hueco
  mide al menos `FVG_MIN_ATR * ATR(14)`; la zona es `[high[i-2], low[i]]`. Senal de LARGO en la
  primera vela posterior (hasta `FVG_MAX_AGE` velas) que entra en la zona (`low <= techo`) y cierra
  por encima del piso; el FVG se usa una sola vez y se invalida si una vela cierra por debajo del
  piso. Espejo para el bajista. Salida `base`: SL en el lado lejano del hueco -+ 0.1 ATR y TP 2R.
- **Filtros nuevos:** `fund` (funding del simbolo bajo su mediana movil = largo; sobre ella =
  corto: en contra del lado saturado), `btc` (regimen: cierre de BTC sobre / bajo su EMA 200 del
  mismo marco) y `rs` (fuerza relativa: retorno de `RS_BARS` velas del simbolo mayor / menor que
  el de BTC; para BTC, su propio retorno contra 0).
- **Salidas** (`EXITS`): `base` (la de `combos`) y cinco fijas en multiplos del ATR(14).
- **Entrada:** `market` (al `open` siguiente, taker) o `limit` (orden limite al cierre de la vela
  de senal, maker; el motor la llena solo si la vela siguiente atraviesa el precio).

`btc` y `rs` necesitan la serie de BTC del mismo marco: `set_btc_context` la registra antes de
correr. Todo es causal (la vela de BTC usada tiene la misma apertura que la del simbolo).
"""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
import pandas as pd

from app.candidates.common import BAR_INDEX_COLUMN, WARMUP_BARS
from app.candidates.sfp_reversal import random_direction
from app.indicators._pine import pine_ema
from app.research.combos import (
    FILTERS,
    SEED,
    TRIGGERS,
    ComboStrategy,
    compute_features,
    interval_of,
)
from app.strategies.base import Signal

R3_TRIGGERS = (*TRIGGERS, "fvg")
R3_FILTERS = (*FILTERS, "fund", "btc", "rs")
NATIVE_TRIGGERS = {"sfp", "camarilla", "rf_flip", "fvg"}
# nombre -> (SL en ATR, TP en R o None, trailing en ATR o None)
EXITS: dict[str, tuple[float, float | None, float | None] | None] = {
    "base": None,
    "s1_tp2r": (1.0, 2.0, None),
    "s15_tp3r": (1.5, 3.0, None),
    "s2_tp1r": (2.0, 1.0, None),
    "s2_trail2": (2.0, None, 2.0),
    "s3_trail3": (3.0, None, 3.0),
}
ENTRY_MODES = ("market", "limit")
FVG_MIN_ATR = 0.25
FVG_MAX_AGE = 100
FVG_BUFFER_ATR = 0.1
FUNDING_WINDOW_DAYS = 30
BTC_EMA = 200
RS_BARS = 180

_BTC_CONTEXT: dict[str, pd.DataFrame] = {}
_R3_CACHE: dict[tuple, pd.DataFrame] = {}


def set_btc_context(interval: str, btc: pd.DataFrame) -> None:
    """Registra la serie de BTC de un marco para los filtros `btc` y `rs`.

    Args:
        interval: marco (`1h`, `4h`).
        btc: velas de BTC con `open_time` y `close`, en orden cronologico.
    """
    ctx = pd.DataFrame({"open_time": btc["open_time"].to_numpy(dtype="int64"),
                        "close": btc["close"].to_numpy(dtype=float)})
    ctx["ema"] = pine_ema(ctx["close"], BTC_EMA).to_numpy()
    ctx["ret"] = ctx["close"] / ctx["close"].shift(RS_BARS) - 1
    _BTC_CONTEXT[interval] = ctx.set_index("open_time")
    _R3_CACHE.clear()


def fvg_signals(df: pd.DataFrame, atr: pd.Series, min_atr: float = FVG_MIN_ATR,
                max_age: int = FVG_MAX_AGE) -> pd.DataFrame:
    """Senales de retesteo de Fair Value Gaps (ver el docstring del modulo).

    Args:
        df: velas con `high`, `low` y `close`.
        atr: ATR(14) de cada vela.
        min_atr: tamano minimo del hueco en ATR.
        max_age: velas durante las que un FVG sigue vigente.

    Returns:
        DataFrame con el mismo indice y columnas `fvg_long`, `fvg_short`, `fvg_sl_long` y
        `fvg_sl_short` (lado lejano del hueco retesteado; NaN sin senal).
    """
    h = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    a = atr.to_numpy(float)
    n = len(df)
    longs = np.zeros(n, dtype=bool)
    shorts = np.zeros(n, dtype=bool)
    sl_long = np.full(n, np.nan)
    sl_short = np.full(n, np.nan)
    bulls: list[tuple[int, float, float]] = []  # (creado, piso, techo)
    bears: list[tuple[int, float, float]] = []
    for i in range(n):
        keep: list[tuple[int, float, float]] = []
        for born, bottom, top in bulls:
            if i - born > max_age or c[i] < bottom:
                continue
            if lo[i] <= top and not longs[i]:
                longs[i] = True
                sl_long[i] = bottom
                continue
            keep.append((born, bottom, top))
        bulls = keep
        keep = []
        for born, bottom, top in bears:
            if i - born > max_age or c[i] > top:
                continue
            if h[i] >= bottom and not shorts[i]:
                shorts[i] = True
                sl_short[i] = top
                continue
            keep.append((born, bottom, top))
        bears = keep
        if i >= 2 and not np.isnan(a[i]):
            if lo[i] - h[i - 2] >= min_atr * a[i]:
                bulls.append((i, h[i - 2], lo[i]))
            if lo[i - 2] - h[i] >= min_atr * a[i]:
                bears.append((i, h[i], lo[i - 2]))
    both = longs & shorts
    return pd.DataFrame({"fvg_long": longs & ~both, "fvg_short": shorts & ~both,
                         "fvg_sl_long": sl_long, "fvg_sl_short": sl_short}, index=df.index)


def compute_features_r3(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Columnas de `combos.compute_features` mas FVG, funding, regimen de BTC y fuerza relativa.

    Args:
        df: velas de toda la serie (`open_time`, OHLC y, si existe, `funding_rate`).
        interval: marco de la serie.

    Returns:
        Copia con `long_fvg`, `short_fvg`, `x_fvg_sl_long`, `x_fvg_sl_short` y `bull_`/`bear_`
        de `fund`, `btc` y `rs`. Sin contexto de BTC registrado, `btc` y `rs` quedan en falso.
    """
    key = (interval, len(df), int(df["open_time"].iloc[0]), int(df["open_time"].iloc[-1]),
           float(df["close"].sum()))
    if key in _R3_CACHE:
        return _R3_CACHE[key]
    out = compute_features(df, interval).copy()
    atr = out["x_atr14"]
    fvg = fvg_signals(out, atr)
    out["long_fvg"] = fvg["fvg_long"].to_numpy()
    out["short_fvg"] = fvg["fvg_short"].to_numpy()
    out["x_fvg_sl_long"] = (fvg["fvg_sl_long"] - FVG_BUFFER_ATR * atr).to_numpy()
    out["x_fvg_sl_short"] = (fvg["fvg_sl_short"] + FVG_BUFFER_ATR * atr).to_numpy()

    hours = {"1h": 1, "4h": 4, "1d": 24}[interval]
    window = FUNDING_WINDOW_DAYS * 24 // hours
    if "funding_rate" in out.columns:
        rate = out["funding_rate"].astype(float)
        median = rate.rolling(window, min_periods=window // 2).median()
        out["bull_fund"] = (rate < median).to_numpy()
        out["bear_fund"] = (rate > median).to_numpy()
    else:
        out["bull_fund"] = False
        out["bear_fund"] = False

    ctx = _BTC_CONTEXT.get(interval)
    if ctx is None:
        for col in ("bull_btc", "bear_btc", "bull_rs", "bear_rs"):
            out[col] = False
    else:
        aligned = ctx.reindex(out["open_time"].to_numpy(dtype="int64"))
        btc_close = aligned["close"].to_numpy()
        btc_ema = aligned["ema"].to_numpy()
        btc_ret = aligned["ret"].to_numpy()
        with np.errstate(invalid="ignore"):
            out["bull_btc"] = btc_close > btc_ema
            out["bear_btc"] = btc_close < btc_ema
            close = out["close"].astype(float)
            own_ret = (close / close.shift(RS_BARS) - 1).to_numpy()
            is_btc = bool(np.allclose(close.to_numpy(), btc_close, equal_nan=False)) \
                if not np.isnan(btc_close).any() else False
            ref = np.zeros(len(out)) if is_btc else btc_ret
            out["bull_rs"] = own_ret > ref
            out["bear_rs"] = own_ret < ref
    if len(_R3_CACHE) > 64:
        _R3_CACHE.clear()
    _R3_CACHE[key] = out
    return out


class Round3Strategy(ComboStrategy):
    """Gatillo + filtros + una salida de `EXITS` + modo de entrada.

    Attributes:
        name: `r3|<gatillo>|<filtros>|<salida>|<entrada>` (con `|rnd` si la direccion es al azar).
        exit_name: clave de `EXITS`.
        entry_mode: `market` o `limit` (lo lee el motor).
    """

    def __init__(self, trigger: str, filters: Iterable[str] = (), *, exit_name: str = "base",
                 entry_mode: str = "market", random_dir: bool = False,
                 warmup: int = WARMUP_BARS) -> None:
        """Valida y fija la variante.

        Args:
            trigger: uno de `R3_TRIGGERS`.
            filters: subconjunto de `R3_FILTERS`.
            exit_name: clave de `EXITS`.
            entry_mode: `market` o `limit`.
            random_dir: sortea la direccion en las mismas velas.
            warmup: velas sin senal al inicio.

        Raises:
            ValueError: si algun nombre no existe.
        """
        self.filters = tuple(sorted(set(filters)))
        if (trigger not in R3_TRIGGERS or set(self.filters) - set(R3_FILTERS)
                or exit_name not in EXITS or entry_mode not in ENTRY_MODES):
            raise ValueError(f"variante desconocida: {trigger} {self.filters} {exit_name} "
                             f"{entry_mode}")
        self.trigger = trigger
        self.exit_name = exit_name
        self.exit_mode = exit_name
        self.entry_mode = entry_mode
        self.random_dir = random_dir
        self.warmup = warmup
        parts = ["r3", trigger, "+".join(self.filters) or "nada", exit_name, entry_mode]
        if random_dir:
            parts.append("rnd")
        self.name = "|".join(parts)

    def precompute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Columnas de `compute_features_r3` para la serie completa.

        Args:
            df: velas de toda la serie.

        Returns:
            Copia de `df` con todas las columnas de la ronda 3.
        """
        return compute_features_r3(df, interval_of(df))

    def _row(self, df: pd.DataFrame) -> pd.Series:
        if "long_fvg" not in df.columns:
            df = self.precompute(df)
        return df.iloc[-1]

    def evaluate(self, df: pd.DataFrame) -> Signal:
        """Senal de la ultima vela (sorteada si `random_dir`).

        Args:
            df: velas hasta la de la senal.

        Returns:
            La senal.
        """
        row = self._row(df)
        if int(row[BAR_INDEX_COLUMN]) < self.warmup:
            return Signal.HOLD
        side = self.natural_side(row)
        if side == Signal.HOLD or not self.random_dir:
            return side
        return random_direction(SEED, int(row["open_time"]), float(row["close"]))

    def _distance(self, row: pd.Series, entry: float) -> float:
        spec = EXITS[self.exit_name]
        if spec is not None:
            return spec[0] * float(row["x_atr14"])
        if self.trigger == "fvg":
            side = self.natural_side(row)
            sl = float(row["x_fvg_sl_long"] if side == Signal.LONG else row["x_fvg_sl_short"])
            crossed = (sl >= entry) if side == Signal.LONG else (sl <= entry)
            return math.nan if math.isnan(sl) or crossed else abs(entry - sl)
        return super()._distance(row, entry)

    def take_profit_price(self, df: pd.DataFrame, side: Signal, entry_price: float) -> float | None:
        """TP de la salida elegida (`None` si usa trailing o el TP de respaldo).

        Args:
            df: velas hasta la de la senal.
            side: direccion de la entrada.
            entry_price: precio de entrada.

        Returns:
            El precio del TP, o `None`.
        """
        spec = EXITS[self.exit_name]
        if spec is None and self.trigger != "fvg":
            return super().take_profit_price(df, side, entry_price)
        reward = 2.0 if spec is None else spec[1]
        if reward is None:
            return None
        distance = self._distance(self._row(df), entry_price)
        if not math.isfinite(distance) or distance <= 0:
            return None
        move = reward * distance
        return entry_price + move if side == Signal.LONG else entry_price - move

    def trailing_distance(self, df: pd.DataFrame) -> float | None:
        """Trailing de la salida elegida.

        Args:
            df: velas hasta la de la senal.

        Returns:
            La distancia del trailing, o `None`.
        """
        spec = EXITS[self.exit_name]
        if spec is None:
            return None if self.trigger == "fvg" else super().trailing_distance(df)
        return None if spec[2] is None else spec[2] * float(self._row(df)["x_atr14"])
