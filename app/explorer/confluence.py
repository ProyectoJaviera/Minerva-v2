"""Confluencia de indicadores para la seccion «Indicadores» (v2, exploratoria).

Todos los indicadores se tratan igual: cada uno **vota** alcista o bajista en cada vela.

- **De estado** (votan siempre): EMA 144, estado del Range Filter, tendencia de la banda VIDYA,
  WaveTrend (`wt1` sobre / bajo `wt2`), funding contra su mediana de 30 dias, regimen de BTC (cierre
  sobre / bajo su EMA 200) y fuerza relativa contra BTC (retorno de 180 velas).
- **De evento** (votan durante `window` velas desde su senal, incluida la de la senal): SFP,
  rechazo de Camarilla S3/R3, reversion del BB%B, cruce de WaveTrend en zona extrema, rechazo de
  zona de liquidez, Liquidity Grab y FVG. Si en la ventana hubo senales de los dos lados, vale la
  mas reciente.

**Entrada:** en la vela en que **todos** los indicadores elegidos coinciden (y en la anterior no
coincidian): largo si todos son alcistas, corto si todos son bajistas (con `min_agree` basta con que
coincidan al menos esa cantidad y mas que los del lado contrario). Un solo indicador de estado
entra en cada cambio de estado (p. ej. el Range Filter solo = sus giros); uno de evento, en cada
senal nueva. **Salida:** fija en multiplos del ATR(14) (`EXITS`). El control sortea la direccion en
las mismas velas de entrada (SHA-256 de `(42, open_time, close)`, como el preregistro).

Las senales y las columnas vienen de `app.research.combos.compute_features` y de
`app.research.round3.fvg_signals` (mismo codigo de la exploracion y la ronda 3); el funding, el
regimen de BTC y la fuerza relativa se calculan aqui con las mismas formulas de la ronda 3, pero
para cualquier marco (15m a 1w). Todo es causal: la vela `i` usa solo velas hasta `i`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
import pandas as pd

from app.candidates.common import BAR_INDEX_COLUMN
from app.candidates.sfp_reversal import random_direction
from app.indicators._pine import pine_ema
from app.research.combos import SEED, compute_features
from app.research.round3 import BTC_EMA, FUNDING_WINDOW_DAYS, RS_BARS, fvg_signals
from app.strategies.base import BaseStrategy, Signal

# id -> (etiqueta, tipo, columna alcista, columna bajista)
INDICATORS: dict[str, tuple[str, str, str, str]] = {
    "sfp": ("SFP del HeatMap (barrida de swing con cierre de vuelta)", "evento",
            "long_sfp", "short_sfp"),
    "camarilla": ("Camarilla: rechazo de S3 (largo) o R3 (corto)", "evento",
                  "long_camarilla", "short_camarilla"),
    "fvg": ("FVG: retesteo de un Fair Value Gap de 3 velas", "evento", "long_fvg", "short_fvg"),
    "zone_reject": ("Rechazo de una zona de liquidez", "evento",
                    "long_zone_reject", "short_zone_reject"),
    "grab": ("Liquidity Grab de Frost (agotamiento)", "evento", "long_grab", "short_grab"),
    "bb_reversal": ("BB%B: sale de sobreventa (largo) o sobrecompra (corto)", "evento",
                    "long_bb_reversal", "short_bb_reversal"),
    "wt_cross": ("WaveTrend: cruce en zona extrema (+-72)", "evento",
                 "long_wt_cross", "short_wt_cross"),
    "rf": ("Range Filter (Frost): estado alcista / bajista", "estado", "bull_rf", "bear_rf"),
    "vidya": ("Banda VIDYA (F. Trail de Frost): tendencia", "estado", "bull_vidya", "bear_vidya"),
    "wt": ("WaveTrend: wt1 sobre / bajo wt2", "estado", "bull_wt", "bear_wt"),
    "ema": ("Cierre sobre / bajo la EMA 144", "estado", "bull_ema", "bear_ema"),
    "fund": ("Funding bajo / sobre su mediana de 30 dias (en contra del lado saturado)", "estado",
             "bull_fund", "bear_fund"),
    "btc": ("Regimen de BTC: cierre sobre / bajo su EMA 200", "estado", "bull_btc", "bear_btc"),
    "rs": ("Fuerza relativa contra BTC (retorno de 180 velas)", "estado", "bull_rs", "bear_rs"),
}

# id -> (etiqueta, SL en ATR(14), TP en multiplos del SL o None, trailing en ATR o None)
EXITS: dict[str, tuple[str, float, float | None, float | None]] = {
    "s2_tp2r": ("SL 2 ATR, TP 2R", 2.0, 2.0, None),
    "s1_tp2r": ("SL 1 ATR, TP 2R", 1.0, 2.0, None),
    "s15_tp3r": ("SL 1,5 ATR, TP 3R", 1.5, 3.0, None),
    "s2_tp1r": ("SL 2 ATR, TP 1R", 2.0, 1.0, None),
    "s2_trail2": ("SL 2 ATR con trailing de 2 ATR", 2.0, None, 2.0),
    "s3_trail3": ("SL 3 ATR con trailing de 3 ATR", 3.0, None, 3.0),
}
DEFAULT_EXIT = "s2_tp2r"
# Salida personalizada en % del precio de entrada: SL obligatorio, TP y trailing opcionales.
PCT_EXIT = "pct"
PCT_EXIT_LABEL = "Personalizada en % (SL, TP y trailing)"
MAX_SL_PCT = 50.0
MAX_TP_PCT = 500.0
MAX_TRAIL_PCT = 50.0
DEFAULT_WINDOW = 5
MAX_WINDOW = 50
# Velas sin senal al inicio: lo que necesitan las medias largas (VIDYA usa ATR(200)). En 1w hay
# pocas velas desde 2022, asi que el calentamiento es menor (las medias largas valen menos ahi).
WARMUP_BY_TIMEFRAME = {"15m": 500, "1h": 500, "4h": 500, "1d": 300, "1w": 100}
HOURS_BY_TIMEFRAME = {"15m": 0.25, "1h": 1, "4h": 4, "1d": 24, "1w": 168}

_FEATURE_CACHE: dict[tuple, pd.DataFrame] = {}


def check_pct_exit(sl_pct: float | None, tp_pct: float | None,
                   trail_pct: float | None) -> tuple[float, float | None, float | None]:
    """Valida una salida en porcentaje del precio de entrada.

    Args:
        sl_pct: SL en % (obligatorio, mayor que 0 y hasta `MAX_SL_PCT`).
        tp_pct: TP en % (opcional, hasta `MAX_TP_PCT`).
        trail_pct: trailing en % (opcional, hasta `MAX_TRAIL_PCT`).

    Returns:
        `(sl, tp, trailing)` en %, con `None` donde no se pidio.

    Raises:
        ValueError: si algun valor falta o esta fuera de rango.
    """
    def ok(v: float | None, top: float) -> bool:
        return v is not None and math.isfinite(v) and 0 < v <= top

    if not ok(sl_pct, MAX_SL_PCT):
        raise ValueError(f"El SL en % debe estar entre 0 y {MAX_SL_PCT:g}.")
    if tp_pct is not None and not ok(tp_pct, MAX_TP_PCT):
        raise ValueError(f"El TP en % debe estar entre 0 y {MAX_TP_PCT:g}.")
    if trail_pct is not None and not ok(trail_pct, MAX_TRAIL_PCT):
        raise ValueError(f"El trailing en % debe estar entre 0 y {MAX_TRAIL_PCT:g}.")
    return float(sl_pct), tp_pct, trail_pct


def pct_exit_name(sl: float, tp: float | None, trail: float | None) -> str:
    """Nombre corto de una salida en %: `pct_sl2_tp4_tr1` (sin las partes que no se pidieron).

    Args:
        sl: SL en %.
        tp: TP en %, o `None`.
        trail: trailing en %, o `None`.

    Returns:
        El nombre.
    """
    parts = [f"pct_sl{sl:g}"]
    if tp is not None:
        parts.append(f"tp{tp:g}")
    if trail is not None:
        parts.append(f"tr{trail:g}")
    return "_".join(parts)


def pct_exit_label(sl: float, tp: float | None, trail: float | None) -> str:
    """Etiqueta legible de una salida en %.

    Args:
        sl: SL en %.
        tp: TP en %, o `None`.
        trail: trailing en %, o `None`.

    Returns:
        La etiqueta, p. ej. `SL 2 %, TP 4 %`.
    """
    text = f"SL {sl:g} %"
    text += f", TP {tp:g} %" if tp is not None else ""
    text += f", trailing {trail:g} %" if trail is not None else ""
    if tp is None and trail is None:
        text += " (TP de respaldo del motor)"
    return text


def compute_votes(df: pd.DataFrame, interval: str, btc: pd.DataFrame | None = None) -> pd.DataFrame:
    """Todas las columnas de voto (`bull_*`/`bear_*` de estado y `long_*`/`short_*` de evento).

    Args:
        df: velas de toda la serie con `open_time`, OHLC y, si existe, `funding_rate`.
        interval: marco (`15m`, `1h`, `4h`, `1d` o `1w`).
        btc: velas de BTC del mismo marco (`open_time`, `close`) para `btc` y `rs`, o `None`
            (entonces esos dos votan siempre falso).

    Returns:
        Copia de `df` con las columnas de `combos.compute_features`, `long_fvg`/`short_fvg`,
        `bull_`/`bear_` de `fund`, `btc` y `rs`, y `v2_bar_index`.
    """
    key = (interval, len(df), int(df["open_time"].iloc[0]), int(df["open_time"].iloc[-1]),
           float(df["close"].sum()), None if btc is None else (len(btc), float(btc["close"].sum())))
    if key in _FEATURE_CACHE:
        return _FEATURE_CACHE[key]
    out = compute_features(df, interval).copy()
    atr = out["x_atr14"]
    fvg = fvg_signals(out, atr)
    out["long_fvg"] = fvg["fvg_long"].to_numpy()
    out["short_fvg"] = fvg["fvg_short"].to_numpy()

    window = max(2, int(FUNDING_WINDOW_DAYS * 24 / HOURS_BY_TIMEFRAME[interval]))
    if "funding_rate" in out.columns:
        rate = out["funding_rate"].astype(float)
        median = rate.rolling(window, min_periods=max(1, window // 2)).median()
        out["bull_fund"] = (rate < median).to_numpy()
        out["bear_fund"] = (rate > median).to_numpy()
    else:
        out["bull_fund"] = False
        out["bear_fund"] = False

    if btc is None or btc.empty:
        for col in ("bull_btc", "bear_btc", "bull_rs", "bear_rs"):
            out[col] = False
    else:
        ctx = pd.DataFrame({"close": btc["close"].to_numpy(dtype=float)},
                           index=btc["open_time"].to_numpy(dtype="int64"))
        ctx["ema"] = pine_ema(ctx["close"], BTC_EMA).to_numpy()
        ctx["ret"] = ctx["close"] / ctx["close"].shift(RS_BARS) - 1
        aligned = ctx.reindex(out["open_time"].to_numpy(dtype="int64"))
        btc_close = aligned["close"].to_numpy()
        close = out["close"].astype(float).to_numpy()
        own_ret = close / pd.Series(close).shift(RS_BARS).to_numpy() - 1
        is_btc = not np.isnan(btc_close).any() and bool(np.allclose(close, btc_close))
        ref = np.zeros(len(out)) if is_btc else aligned["ret"].to_numpy()
        with np.errstate(invalid="ignore"):
            out["bull_btc"] = btc_close > aligned["ema"].to_numpy()
            out["bear_btc"] = btc_close < aligned["ema"].to_numpy()
            out["bull_rs"] = own_ret > ref
            out["bear_rs"] = own_ret < ref
    if len(_FEATURE_CACHE) > 32:
        _FEATURE_CACHE.clear()
    _FEATURE_CACHE[key] = out
    return out


def event_votes(long_ev: np.ndarray, short_ev: np.ndarray,
                window: int) -> tuple[np.ndarray, np.ndarray]:
    """Votos de un indicador de evento: su ultima senal vale durante `window` velas.

    Args:
        long_ev: senales alcistas por vela.
        short_ev: senales bajistas por vela.
        window: velas que dura el voto, incluida la de la senal (>= 1).

    Returns:
        `(alcista, bajista)`: en la vela `i` vota el lado de la senal mas reciente si ocurrio en
        las ultimas `window` velas. Una vela con senal de los dos lados no vota.
    """
    n = len(long_ev)
    idx = np.arange(n)
    both = long_ev & short_ev
    lo = np.where(long_ev & ~both, idx, -1)
    sh = np.where(short_ev & ~both, idx, -1)
    last_long = np.maximum.accumulate(lo) if n else lo
    last_short = np.maximum.accumulate(sh) if n else sh
    bull = (last_long >= 0) & (idx - last_long < window) & (last_long > last_short)
    bear = (last_short >= 0) & (idx - last_short < window) & (last_short > last_long)
    return bull, bear


def confluence_signals(features: pd.DataFrame, indicators: Iterable[str], window: int,
                       min_agree: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Entradas por confluencia: la vela en que los indicadores pasan a coincidir.

    Args:
        features: salida de `compute_votes`.
        indicators: ids de `INDICATORS` (al menos uno).
        window: duracion del voto de los indicadores de evento.
        min_agree: cuantos deben votar el mismo lado (`None` = todos). Con menos que todos, el
            lado debe tener al menos `min_agree` votos y mas votos que el contrario.

    Returns:
        `(largo, corto)`: arrays booleanos por vela.
    """
    inds = list(indicators)
    n = len(features)
    need = len(inds) if min_agree is None else min_agree
    bull_count = np.zeros(n, dtype=int)
    bear_count = np.zeros(n, dtype=int)
    for ind in inds:
        _, kind, bull_col, bear_col = INDICATORS[ind]
        bull = features[bull_col].to_numpy(dtype=bool)
        bear = features[bear_col].to_numpy(dtype=bool)
        if kind == "evento":
            bull, bear = event_votes(bull, bear, window)
        bull_count += bull
        bear_count += bear
    all_bull = (bull_count >= need) & (bull_count > bear_count)
    all_bear = (bear_count >= need) & (bear_count > bull_count)
    prev_bull = np.concatenate(([False], all_bull[:-1])) if n else all_bull
    prev_bear = np.concatenate(([False], all_bear[:-1])) if n else all_bear
    return all_bull & ~prev_bull, all_bear & ~prev_bear


class ConfluenceStrategy(BaseStrategy):
    """Confluencia de indicadores con una salida fija en ATR (ver el docstring del modulo).

    Attributes:
        name: `mix|<indicadores>|w<ventana>|<salida>` (con `|k<n>` si no se exige que coincidan
            todos y `|rnd` si la direccion es al azar).
        indicators: ids elegidos, en el orden de `INDICATORS`.
        min_agree: cuantos deben coincidir (`None` = todos).
        window: duracion del voto de los indicadores de evento.
        exit_name: clave de `EXITS`.
        interval: marco de la serie.
        random_dir: si la direccion se sortea (control).
    """

    skip_entry_if_sl_crossed = True

    def __init__(self, indicators: Iterable[str], interval: str, *, window: int = DEFAULT_WINDOW,
                 exit_name: str = DEFAULT_EXIT, btc: pd.DataFrame | None = None,
                 min_agree: int | None = None, pct_exit: tuple | None = None,
                 random_dir: bool = False) -> None:
        """Valida y fija la combinacion.

        Args:
            indicators: ids de `INDICATORS` (al menos uno).
            interval: marco (`15m`, `1h`, `4h`, `1d` o `1w`).
            window: velas que dura el voto de un indicador de evento (1 a `MAX_WINDOW`).
            exit_name: clave de `EXITS`, o `PCT_EXIT` con `pct_exit`.
            btc: velas de BTC del mismo marco, para `btc` y `rs`.
            min_agree: cuantos indicadores deben coincidir (1 a la cantidad elegida; `None` o la
                cantidad elegida = todos).
            pct_exit: `(sl, tp, trailing)` en % del precio de entrada para `PCT_EXIT` (TP y
                trailing pueden ser `None`; validado con `check_pct_exit`).
            random_dir: sortea la direccion en las mismas velas de entrada.

        Raises:
            ValueError: si algun parametro no existe o esta fuera de rango.
        """
        chosen = set(indicators)
        unknown = chosen - set(INDICATORS)
        if not chosen or unknown:
            raise ValueError(f"indicadores invalidos: {sorted(unknown) or 'ninguno'}")
        if interval not in WARMUP_BY_TIMEFRAME:
            raise ValueError(f"marco invalido: {interval}")
        if not 1 <= window <= MAX_WINDOW:
            raise ValueError(f"ventana fuera de rango: {window}")
        self.pct = None
        if exit_name == PCT_EXIT:
            self.pct = check_pct_exit(*(pct_exit or (None, None, None)))
            exit_name = pct_exit_name(*self.pct)
        elif exit_name not in EXITS:
            raise ValueError(f"salida desconocida: {exit_name}")
        self.indicators = tuple(i for i in INDICATORS if i in chosen)
        if min_agree is not None and not 1 <= min_agree <= len(self.indicators):
            raise ValueError(f"minimo de coincidencias fuera de rango: {min_agree}")
        self.min_agree = None if min_agree in (None, len(self.indicators)) else min_agree
        self.interval = interval
        self.window = window
        self.exit_name = exit_name
        self.btc = btc
        self.random_dir = random_dir
        self.warmup = WARMUP_BY_TIMEFRAME[interval]
        parts = ["mix", "+".join(self.indicators), f"w{window}", exit_name]
        if self.min_agree is not None:
            parts.append(f"k{self.min_agree}")
        if random_dir:
            parts.append("rnd")
        self.name = "|".join(parts)
        self._long: np.ndarray | None = None
        self._short: np.ndarray | None = None
        self._atr: np.ndarray | None = None
        self._open_time: np.ndarray | None = None
        self._close: np.ndarray | None = None

    def precompute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcula los votos y las entradas de toda la serie y los guarda como arrays.

        Args:
            df: velas de toda la serie (con `open_time`).

        Returns:
            Copia de `df` con las columnas de `compute_votes`.
        """
        out = compute_votes(df, self.interval, self.btc)
        self._long, self._short = confluence_signals(out, self.indicators, self.window,
                                                     self.min_agree)
        self._atr = out["x_atr14"].to_numpy(dtype=float)
        self._open_time = out["open_time"].to_numpy(dtype="int64")
        self._close = out["close"].to_numpy(dtype=float)
        return out

    def _index(self, df: pd.DataFrame) -> int:
        if self._long is None or BAR_INDEX_COLUMN not in df.columns:
            self.precompute(df)
            return len(df) - 1
        return int(df[BAR_INDEX_COLUMN].iat[-1])

    def evaluate(self, df: pd.DataFrame) -> Signal:
        """Senal de la ultima vela (sorteada si `random_dir`).

        Args:
            df: velas hasta la de la senal.

        Returns:
            La senal.
        """
        i = self._index(df)
        if i < self.warmup:
            return Signal.HOLD
        long, short = bool(self._long[i]), bool(self._short[i])
        if long == short:
            return Signal.HOLD
        if self.random_dir:
            return random_direction(SEED, int(self._open_time[i]), float(self._close[i]))
        return Signal.LONG if long else Signal.SHORT

    def _distance(self, df: pd.DataFrame, entry_price: float) -> float:
        if self.pct is not None:
            return self.pct[0] / 100 * entry_price
        atr = float(self._atr[self._index(df)])
        return EXITS[self.exit_name][1] * atr if math.isfinite(atr) and atr > 0 else math.nan

    def stop_price(self, df: pd.DataFrame, side: Signal, entry_price: float) -> float | None:
        """SL a `k * ATR(14)` (o al % pedido) de la entrada; la entrada si no hay ATR (se omite).

        Args:
            df: velas hasta la de la senal.
            side: direccion de la entrada.
            entry_price: precio de entrada.

        Returns:
            El precio del SL.
        """
        d = self._distance(df, entry_price)
        if not math.isfinite(d):
            return entry_price
        return entry_price - d if side == Signal.LONG else entry_price + d

    def take_profit_price(self, df: pd.DataFrame, side: Signal, entry_price: float) -> float | None:
        """TP a `R` veces la distancia del SL (o al % pedido), o `None`.

        Sin TP (salidas con trailing, o en % sin TP) el motor usa su TP de respaldo si tampoco hay
        trailing.

        Args:
            df: velas hasta la de la senal.
            side: direccion de la entrada.
            entry_price: precio de entrada.

        Returns:
            El precio del TP, o `None`.
        """
        if self.pct is not None:
            tp = self.pct[1]
            if tp is None:
                return None
            move = tp / 100 * entry_price
            return entry_price + move if side == Signal.LONG else entry_price - move
        reward = EXITS[self.exit_name][2]
        d = self._distance(df, entry_price)
        if reward is None or not math.isfinite(d):
            return None
        return entry_price + reward * d if side == Signal.LONG else entry_price - reward * d

    def trailing_distance(self, df: pd.DataFrame) -> float | None:
        """Trailing de `k * ATR(14)` (o del % pedido sobre el cierre de la vela de senal).

        Args:
            df: velas hasta la de la senal.

        Returns:
            La distancia del trailing, o `None`.
        """
        if self.pct is not None:
            if self.pct[2] is None:
                return None
            return self.pct[2] / 100 * float(self._close[self._index(df)])
        trail = EXITS[self.exit_name][3]
        atr = float(self._atr[self._index(df)])
        if trail is None or not math.isfinite(atr) or atr <= 0:
            return None
        return trail * atr
