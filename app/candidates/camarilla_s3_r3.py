"""Candidato `camarilla_s3_r3` (preregistro v2): rechazo de S3 / R3 del dia UTC anterior.

LARGO si la vela toca S3 y cierra por encima (`low <= S3 < close`); CORTO si toca R3 y cierra por
debajo (`high >= R3 > close`). Si una vela cumple ambas, no hay senal. Solo la PRIMERA vela que lo
cumple en cada dia UTC y por cada lado da senal: si el motor la ignora (posicion abierta) o la
omite (tope de riesgo), no hay otra ese dia. SL y TP de la tabla del original: LARGO con SL en
`S4 * 0.99` y TP en R3; CORTO con SL en `R4 * 1.01` y TP en S3, con los niveles del dia de la
senal. Sin DCA.

Inspirado en indicadores publicos de TradingView (autoria y licencia por verificar). No esta en
`STRATEGIES`.
"""

from __future__ import annotations

import pandas as pd

from app.candidates.common import (
    WARMUP_BARS,
    add_bar_index,
    ensure_precomputed,
    is_true,
    warmed_up,
)
from app.indicators.levels import DAY_MS, camarilla_levels
from app.strategies.base import BaseStrategy, Signal

LONG_COLUMN = "v2_cam_long"
SHORT_COLUMN = "v2_cam_short"


def _first_per_day(condition: pd.Series, day: pd.Series) -> pd.Series:
    """Solo la primera vela de cada dia en que se cumple `condition`."""
    count = condition.astype("int64").groupby(day).cumsum()
    return condition & (count == 1)


class CamarillaS3R3Strategy(BaseStrategy):
    """Rechazo de S3 (largo) o R3 (corto), una vez por lado y dia UTC.

    Attributes:
        name: `camarilla_s3_r3`.
    """

    name = "camarilla_s3_r3"

    def __init__(
        self, sl_buffer_pct: float = 0.01, warmup: int = WARMUP_BARS,
    ) -> None:
        """Parametros fijos del preregistro (los argumentos existen para las pruebas).

        Args:
            sl_buffer_pct: colchon del SL mas alla de S4 / R4 (0.01 = 1 %, el de la tabla).
            warmup: velas de calentamiento sin senales (500).
        """
        self.sl_buffer_pct = sl_buffer_pct
        self.warmup = warmup

    def precompute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Agrega los niveles Camarilla y las senales de primer rechazo del dia.

        Args:
            df: velas de toda la serie, con `open_time` (ms UTC).

        Returns:
            Una copia de `df` con `cam_*`, `v2_cam_long`, `v2_cam_short` y `v2_bar_index`.
        """
        out = add_bar_index(df)
        levels = camarilla_levels(df)
        for col in levels.columns:
            out[col] = levels[col].to_numpy()
        touch_long = (out["low"] <= out["cam_s3"]) & (out["close"] > out["cam_s3"])
        touch_short = (out["high"] >= out["cam_r3"]) & (out["close"] < out["cam_r3"])
        both = touch_long & touch_short
        day = out["open_time"].astype("int64") // DAY_MS
        out[LONG_COLUMN] = _first_per_day(touch_long & ~both, day)
        out[SHORT_COLUMN] = _first_per_day(touch_short & ~both, day)
        return out

    def _row(self, df: pd.DataFrame) -> pd.Series:
        return ensure_precomputed(df, LONG_COLUMN, self.precompute).iloc[-1]

    def evaluate(self, df: pd.DataFrame) -> Signal:
        """LARGO en el primer rechazo de S3 del dia, CORTO en el primero de R3.

        Args:
            df: velas hasta la de la senal.

        Returns:
            La senal de la ultima vela.
        """
        row = self._row(df)
        if not warmed_up(row, self.warmup):
            return Signal.HOLD
        if is_true(row[LONG_COLUMN]):
            return Signal.LONG
        if is_true(row[SHORT_COLUMN]):
            return Signal.SHORT
        return Signal.HOLD

    def stop_price(self, df: pd.DataFrame, side: Signal, entry_price: float) -> float | None:
        """LARGO: `S4 * (1 - colchon)`; CORTO: `R4 * (1 + colchon)`, del dia de la senal.

        Args:
            df: velas hasta la de la senal.
            side: direccion de la entrada.
            entry_price: precio de entrada.

        Returns:
            El precio del SL.
        """
        row = self._row(df)
        if side == Signal.LONG:
            return float(row["cam_s4"]) * (1 - self.sl_buffer_pct)
        return float(row["cam_r4"]) * (1 + self.sl_buffer_pct)

    def take_profit_price(self, df: pd.DataFrame, side: Signal, entry_price: float) -> float | None:
        """LARGO: R3; CORTO: S3, del dia de la senal.

        Args:
            df: velas hasta la de la senal.
            side: direccion de la entrada.
            entry_price: precio de entrada.

        Returns:
            El precio del TP.
        """
        row = self._row(df)
        return float(row["cam_r3"]) if side == Signal.LONG else float(row["cam_s3"])
