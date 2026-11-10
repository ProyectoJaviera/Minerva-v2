"""Combinaciones exploratorias: un gatillo con 0, 1 o 2 filtros y una regla de salida fija.

Gatillos (dan el momento y la direccion de la entrada):

- `sfp`: SFP del Heatmap (`sfp_signals`, pivote 5/1).
- `camarilla`: primer rechazo del dia de S3 (largo) o R3 (corto), como `camarilla_s3_r3`.
- `rf_flip`: giro del Range Filter de Frost (`rf_buy` / `rf_sell`).
- `vidya_flip`: cambio de tendencia de la banda VIDYA +- ATR(200)*1.6 (el «F. Trail»).
- `bb_reversal`: vela de reversion del BB%B (sale de sobreventa = largo, de sobrecompra = corto).
- `wt_cross`: cruce de WaveTrend en zona extrema (+-72), la «Reversal RSI» de Frost.
- `zone_reject`: la vela entra en una zona de liquidez activa y cierra afuera (definicion propia,
  `liquidity_zones`): bajo una zona de maximos = corto; sobre una de minimos = largo.
- `grab`: «Liquidity Grab» de Frost (agotamiento: conteo no consecutivo de `close` vs `close[4]`
  mayor que 6, vela contraria y extremo de 30 velas).

Filtros (estado; un largo exige el estado alcista y un corto el bajista): `ema` (cierre vs EMA 144),
`rf` (ultima senal del Range Filter), `vidya` (tendencia de la banda VIDYA) y `wt` (WaveTrend:
`wt1` sobre / bajo `wt2`).

Salidas: `native` para los gatillos que ya tienen una en el preregistro (SFP: mecha +- 0.1 ATR y
2R; Camarilla: S4/R4 con 1 % de colchon y TP en R3/S3; Range Filter: 2.5 ATR con trailing de
2.5 ATR y el TP de respaldo del motor); `atr` para el resto: SL a 2 ATR(14) y TP 2R (4 ATR).

Todo es causal: las columnas de la vela `i` usan solo velas hasta `i`. Sin senales en las
primeras 500 velas. `random_dir=True` sortea la direccion (SHA-256 de `(42, open_time, close)`,
como el control del preregistro): es la referencia «sin informacion de direccion» de cada gatillo.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
import pandas as pd

from app.candidates.camarilla_s3_r3 import CamarillaS3R3Strategy
from app.candidates.common import BAR_INDEX_COLUMN, WARMUP_BARS
from app.candidates.sfp_reversal import random_direction
from app.indicators._pine import pine_atr, pine_ema
from app.indicators.oscillators import bb_percent_b, wavetrend
from app.indicators.structure import heatmap_atr_multiplier, liquidity_zones, sfp_signals
from app.indicators.trend_filters import range_filter, vidya_band
from app.strategies.base import BaseStrategy, Signal

TRIGGERS = ("sfp", "camarilla", "rf_flip", "vidya_flip", "bb_reversal", "wt_cross",
            "zone_reject", "grab")
FILTERS = ("ema", "rf", "vidya", "wt")
NATIVE_EXIT = {"sfp", "camarilla", "rf_flip"}
ATR_SL_MULT = 2.0
REWARD_RISK = 2.0
SFP_BUFFER_ATR = 0.1
RF_ATR_MULT = 2.5
CAM_SL_BUFFER = 0.01
GRAB_QUALITY = 6
GRAB_LENGTH = 30
SEED = 42

_FEATURE_CACHE: dict[tuple, pd.DataFrame] = {}


def liquidity_grab(df: pd.DataFrame, quality: int = GRAB_QUALITY,
                   length: int = GRAB_LENGTH) -> pd.DataFrame:
    """«Liquidity Grab» de Frost (funcion `lele`): senal de agotamiento, no de barrida.

    Cuenta, sin exigir que sean seguidas, las velas con `close > close[4]` (`bindex`) y con
    `close < close[4]` (`sindex`). Bajista (`grab_short`) si `bindex > quality`, vela bajista y
    su maximo es el mayor de `length` velas (incluida ella); entonces `bindex` vuelve a 0. Alcista
    (`grab_long`) espejo con `sindex`. Si las dos condiciones se dan en la misma vela, gana la
    alcista (es la ultima que el original asigna).

    Args:
        df: velas con `open`, `high`, `low` y `close`.
        quality: umbral del conteo (6).
        length: ventana del extremo (30).

    Returns:
        DataFrame con el mismo indice y columnas `grab_long` y `grab_short`.
    """
    o = df["open"].to_numpy(float)
    c = df["close"].to_numpy(float)
    hh = df["high"].rolling(length, min_periods=length).max().to_numpy()
    ll = df["low"].rolling(length, min_periods=length).min().to_numpy()
    h = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    n = len(df)
    longs = np.zeros(n, dtype=bool)
    shorts = np.zeros(n, dtype=bool)
    bindex = sindex = 0
    for i in range(n):
        if i >= 4:
            if c[i] > c[i - 4]:
                bindex += 1
            if c[i] < c[i - 4]:
                sindex += 1
        ret = 0
        if bindex > quality and c[i] < o[i] and not np.isnan(hh[i]) and h[i] >= hh[i]:
            bindex = 0
            ret = -1
        if sindex > quality and c[i] > o[i] and not np.isnan(ll[i]) and lo[i] <= ll[i]:
            sindex = 0
            ret = 1
        longs[i] = ret == 1
        shorts[i] = ret == -1
    return pd.DataFrame({"grab_long": longs, "grab_short": shorts}, index=df.index)


def zone_rejections(df: pd.DataFrame, interval: str = "1h") -> pd.DataFrame:
    """Rechazos de zonas de liquidez activas (definicion propia, causal).

    Una zona de maximos `[bottom, top]` activa al cierre anterior se rechaza si la vela llega a
    ella (`high >= bottom`) y cierra por debajo (`close < bottom`): corto. Espejo para las zonas de
    minimos: `low <= top` y `close > top`: largo. Una zona emitida en la vela `e` cuenta desde
    `e + 1`; deja de contar despues de su mitigacion.

    Args:
        df: velas con `high`, `low` y `close`.
        interval: marco, para el ancho de la zona (`heatmap_atr_multiplier`).

    Returns:
        DataFrame con el mismo indice y columnas `zone_long` y `zone_short`.
    """
    zones = liquidity_zones(df, atr_mult=heatmap_atr_multiplier(interval))
    n = len(df)
    h = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    longs = np.zeros(n, dtype=bool)
    shorts = np.zeros(n, dtype=bool)
    for z in zones.itertuples(index=False):
        start = int(z.emit_index) + 1
        end = n if pd.isna(z.mitigated_index) else int(z.mitigated_index)  # la que mitiga, no
        if start >= end:
            continue
        sl = slice(start, end)
        if z.side == "high":
            shorts[sl] |= (h[sl] >= z.bottom) & (c[sl] < z.bottom)
        else:
            longs[sl] |= (lo[sl] <= z.top) & (c[sl] > z.top)
    return pd.DataFrame({"zone_long": longs, "zone_short": shorts}, index=df.index)


def _cache_key(df: pd.DataFrame, interval: str) -> tuple:
    return (interval, len(df), int(df["open_time"].iloc[0]), int(df["open_time"].iloc[-1]),
            float(df["close"].sum()))


def compute_features(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Todas las columnas de gatillos, filtros y salidas, una sola vez por serie (con cache).

    Args:
        df: velas de toda la serie con `open_time`, `open`, `high`, `low` y `close`.
        interval: marco de la serie (`1h` o `4h`).

    Returns:
        Copia de `df` con `long_<gatillo>`, `short_<gatillo>`, `bull_<filtro>`, `bear_<filtro>`,
        las columnas de salida (`x_atr14`, `x_sfp_sl_long`, `x_sfp_sl_short`, `cam_s4`, `cam_r4`,
        `cam_r3`, `cam_s3`) y `v2_bar_index`.
    """
    key = _cache_key(df, interval)
    if key in _FEATURE_CACHE:
        return _FEATURE_CACHE[key]
    out = df.copy()
    out[BAR_INDEX_COLUMN] = np.arange(len(out), dtype="int64")
    close = out["close"].astype(float)
    atr14 = pine_atr(out, 14)
    out["x_atr14"] = atr14.to_numpy()

    sfp = sfp_signals(out)
    out["long_sfp"] = sfp["sfp_bull_signal"].to_numpy() & ~sfp["sfp_bear_signal"].to_numpy()
    out["short_sfp"] = sfp["sfp_bear_signal"].to_numpy() & ~sfp["sfp_bull_signal"].to_numpy()
    out["x_sfp_sl_long"] = (sfp["sfp_bull_sweep_extreme"] - SFP_BUFFER_ATR * atr14).to_numpy()
    out["x_sfp_sl_short"] = (sfp["sfp_bear_sweep_extreme"] + SFP_BUFFER_ATR * atr14).to_numpy()

    cam = CamarillaS3R3Strategy().precompute(df)
    for col in ("cam_s3", "cam_s4", "cam_r3", "cam_r4"):
        out[col] = cam[col].to_numpy()
    out["long_camarilla"] = cam["v2_cam_long"].to_numpy(dtype=bool)
    out["short_camarilla"] = cam["v2_cam_short"].to_numpy(dtype=bool)

    rf = range_filter(close)
    out["long_rf_flip"] = rf["rf_buy"].to_numpy()
    out["short_rf_flip"] = rf["rf_sell"].to_numpy()
    out["bull_rf"] = (rf["rf_state"] == 1).to_numpy()
    out["bear_rf"] = (rf["rf_state"] == -1).to_numpy()

    vb = vidya_band(out)
    out["long_vidya_flip"] = vb["vidya_flip_up"].to_numpy()
    out["short_vidya_flip"] = vb["vidya_flip_down"].to_numpy()
    valid_vidya = vb["vidya_upper"].notna().to_numpy()
    out["bull_vidya"] = vb["vidya_trend_up"].to_numpy() & valid_vidya
    out["bear_vidya"] = ~vb["vidya_trend_up"].to_numpy() & valid_vidya

    bb = bb_percent_b(close)
    out["long_bb_reversal"] = bb["bb_exit_oversold"].to_numpy(dtype=bool)
    out["short_bb_reversal"] = bb["bb_exit_overbought"].to_numpy(dtype=bool)

    wt = wavetrend(out)
    out["long_wt_cross"] = wt["wt_bull_cross"].to_numpy(dtype=bool)
    out["short_wt_cross"] = wt["wt_bear_cross"].to_numpy(dtype=bool)
    out["bull_wt"] = (wt["wt1"] > wt["wt2"]).to_numpy()
    out["bear_wt"] = (wt["wt1"] < wt["wt2"]).to_numpy()

    zr = zone_rejections(out, interval)
    out["long_zone_reject"] = zr["zone_long"].to_numpy() & ~zr["zone_short"].to_numpy()
    out["short_zone_reject"] = zr["zone_short"].to_numpy() & ~zr["zone_long"].to_numpy()

    gr = liquidity_grab(out)
    out["long_grab"] = gr["grab_long"].to_numpy()
    out["short_grab"] = gr["grab_short"].to_numpy()

    ema = pine_ema(close, 144)
    out["bull_ema"] = (close > ema).to_numpy()
    out["bear_ema"] = (close < ema).to_numpy()

    if len(_FEATURE_CACHE) > 64:
        _FEATURE_CACHE.clear()
    _FEATURE_CACHE[key] = out
    return out


def interval_of(df: pd.DataFrame) -> str:
    """Marco de una serie a partir de la mediana del paso entre velas (`1h`, `4h`, ...).

    Args:
        df: velas con `open_time` en ms.

    Returns:
        `1h`, `4h` o `1d` (el mas cercano).
    """
    step = float(np.median(np.diff(df["open_time"].to_numpy(dtype="int64")[:50])))
    hours = step / 3_600_000
    return min(("1h", "4h", "1d"), key=lambda k: abs({"1h": 1, "4h": 4, "1d": 24}[k] - hours))


class ComboStrategy(BaseStrategy):
    """Un gatillo con filtros y una salida fija (ver el docstring del modulo).

    Attributes:
        name: `combo|<gatillo>|<filtros>|<salida>` (con `|rnd` si la direccion es al azar).
        trigger: gatillo.
        filters: filtros (tupla, puede estar vacia).
        exit_mode: `native` o `atr`.
        random_dir: si la direccion se sortea.
        skip_entry_if_sl_crossed: el motor omite la entrada si el `open` ya paso el SL.
    """

    skip_entry_if_sl_crossed = True

    def __init__(self, trigger: str, filters: Iterable[str] = (), *, random_dir: bool = False,
                 warmup: int = WARMUP_BARS) -> None:
        """Valida y fija la combinacion.

        Args:
            trigger: uno de `TRIGGERS`.
            filters: subconjunto de `FILTERS`.
            random_dir: sortea la direccion en las mismas velas del gatillo.
            warmup: velas sin senal al inicio (500).

        Raises:
            ValueError: si el gatillo o algun filtro no existen.
        """
        if trigger not in TRIGGERS:
            raise ValueError(f"gatillo desconocido: {trigger}")
        self.filters = tuple(sorted(set(filters)))
        unknown = set(self.filters) - set(FILTERS)
        if unknown:
            raise ValueError(f"filtros desconocidos: {sorted(unknown)}")
        self.trigger = trigger
        self.exit_mode = "native" if trigger in NATIVE_EXIT else "atr"
        self.random_dir = random_dir
        self.warmup = warmup
        parts = ["combo", trigger, "+".join(self.filters) or "nada", self.exit_mode]
        if random_dir:
            parts.append("rnd")
        self.name = "|".join(parts)

    def precompute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Columnas de `compute_features` para la serie completa.

        Args:
            df: velas de toda la serie (con `open_time`).

        Returns:
            Copia de `df` con las columnas de gatillos, filtros y salidas.
        """
        return compute_features(df, interval_of(df))

    def _row(self, df: pd.DataFrame) -> pd.Series:
        if "long_sfp" not in df.columns:
            df = self.precompute(df)
        return df.iloc[-1]

    def natural_side(self, row: pd.Series) -> Signal:
        """Direccion del gatillo con sus filtros en una fila (sin calentamiento ni sorteo).

        Args:
            row: fila de la vela de senal con las columnas de `compute_features`.

        Returns:
            `LONG`, `SHORT` o `HOLD`.
        """
        long = bool(row[f"long_{self.trigger}"]) and all(bool(row[f"bull_{f}"])
                                                          for f in self.filters)
        short = bool(row[f"short_{self.trigger}"]) and all(bool(row[f"bear_{f}"])
                                                           for f in self.filters)
        if long == short:
            return Signal.HOLD
        return Signal.LONG if long else Signal.SHORT

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
        """Distancia del SL del lado natural (para sortear sin cambiar el riesgo)."""
        side = self.natural_side(row)
        atr = float(row["x_atr14"])
        if self.trigger == "sfp":
            sl = float(row["x_sfp_sl_long"] if side == Signal.LONG else row["x_sfp_sl_short"])
            crossed = (sl >= entry) if side == Signal.LONG else (sl <= entry)
            return math.nan if math.isnan(sl) or crossed else abs(entry - sl)
        if self.trigger == "camarilla":
            sl = float(row["cam_s4"]) * (1 - CAM_SL_BUFFER) if side == Signal.LONG \
                else float(row["cam_r4"]) * (1 + CAM_SL_BUFFER)
            crossed = (sl >= entry) if side == Signal.LONG else (sl <= entry)
            return math.nan if math.isnan(sl) or crossed else abs(entry - sl)
        mult = RF_ATR_MULT if self.trigger == "rf_flip" else ATR_SL_MULT
        return mult * atr

    def stop_price(self, df: pd.DataFrame, side: Signal, entry_price: float) -> float | None:
        """SL a la distancia de la salida de la combinacion; la entrada si no se puede (=> omite).

        Args:
            df: velas hasta la de la senal.
            side: direccion de la entrada.
            entry_price: precio de entrada.

        Returns:
            El precio del SL.
        """
        distance = self._distance(self._row(df), entry_price)
        if not math.isfinite(distance) or distance <= 0:
            return entry_price
        return entry_price - distance if side == Signal.LONG else entry_price + distance

    def take_profit_price(self, df: pd.DataFrame, side: Signal, entry_price: float) -> float | None:
        """TP: R3/S3 en Camarilla natural, ninguno en Range Filter (TP de respaldo), si no 2R.

        Args:
            df: velas hasta la de la senal.
            side: direccion de la entrada.
            entry_price: precio de entrada.

        Returns:
            El precio del TP, o `None` (el motor usa su TP de respaldo).
        """
        row = self._row(df)
        if self.trigger == "rf_flip":
            return None
        if self.trigger == "camarilla" and not self.random_dir:
            return float(row["cam_r3"]) if side == Signal.LONG else float(row["cam_s3"])
        distance = self._distance(row, entry_price)
        if not math.isfinite(distance) or distance <= 0:
            return None
        move = REWARD_RISK * distance
        return entry_price + move if side == Signal.LONG else entry_price - move

    def trailing_distance(self, df: pd.DataFrame) -> float | None:
        """Trailing de 2.5 ATR(14) solo para el gatillo del Range Filter.

        Args:
            df: velas hasta la de la senal.

        Returns:
            La distancia del trailing, o `None`.
        """
        if self.trigger != "rf_flip":
            return None
        return RF_ATR_MULT * float(self._row(df)["x_atr14"])


def all_combinations() -> list[ComboStrategy]:
    """El espacio de la exploracion: cada gatillo con 0, 1 o 2 filtros, mas su control al azar.

    Returns:
        8 gatillos x (1 + 4 + 6) variantes de filtros = 88 combinaciones, mas 8 controles con
        direccion al azar (sin filtros).
    """
    variants: list[tuple[str, ...]] = [()]
    variants += [(f,) for f in FILTERS]
    variants += [(a, b) for i, a in enumerate(FILTERS) for b in FILTERS[i + 1:]]
    combos = [ComboStrategy(t, v) for t in TRIGGERS for v in variants]
    combos += [ComboStrategy(t, (), random_dir=True) for t in TRIGGERS]
    return combos
