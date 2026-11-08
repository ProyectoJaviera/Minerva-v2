"""Candidato `range_filter_flip_ema144` (preregistro v2): giro del Range Filter a favor de la EMA.

LARGO en una compra del Range Filter (`rf_buy`, rangos 27/1.5 y 55/3.5, modo "Intraday") con
`close > EMA(144)`; CORTO en una venta (`rf_sell`) con `close < EMA(144)`. SL a `2.5 * ATR(14)`
de la entrada y trailing de `2.5 * ATR(14)` (la regla de `trend_atr_stop_9_21_50`); sin TP propio:
el motor aplica su TP de respaldo (`BACKTEST_FALLBACK_TP_PCT`), igual que en esa estrategia.

El ATR es el de `app/indicators/_pine.py` (arranque por media simple). Tras las 500 velas de
calentamiento coincide con el de `app/indicators/engine.py` a precision de maquina (la diferencia
de arranque se multiplica por `(13/14)^500`).

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
from app.indicators._pine import pine_atr, pine_ema
from app.indicators.trend_filters import range_filter
from app.strategies.base import BaseStrategy, Signal

EMA_COLUMN = "v2_ema144"
ATR_COLUMN = "v2_atr14"


class RangeFilterFlipEma144Strategy(BaseStrategy):
    """Giro del Range Filter filtrado por la EMA 144, con SL y trailing de 2.5 ATR(14).

    Attributes:
        name: `range_filter_flip_ema144`.
    """

    name = "range_filter_flip_ema144"

    def __init__(
        self,
        ema_period: int = 144,
        atr_period: int = 14,
        atr_mult: float = 2.5,
        warmup: int = WARMUP_BARS,
    ) -> None:
        """Parametros fijos del preregistro (los argumentos existen para las pruebas).

        Args:
            ema_period: periodo de la EMA de tendencia (144).
            atr_period: periodo del ATR (14).
            atr_mult: distancia del SL y del trailing en ATR (2.5).
            warmup: velas de calentamiento sin senales (500).
        """
        self.ema_period = ema_period
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.warmup = warmup

    def precompute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Agrega el Range Filter, la EMA 144, el ATR(14) y la posicion de cada vela.

        Args:
            df: velas OHLC de toda la serie.

        Returns:
            Una copia de `df` con `rf_*`, `v2_ema144`, `v2_atr14` y `v2_bar_index`.
        """
        out = add_bar_index(df)
        rf = range_filter(df["close"])
        for col in rf.columns:
            out[col] = rf[col].to_numpy()
        out[EMA_COLUMN] = pine_ema(df["close"], self.ema_period).to_numpy()
        out[ATR_COLUMN] = pine_atr(df, self.atr_period).to_numpy()
        return out

    def _row(self, df: pd.DataFrame) -> pd.Series:
        return ensure_precomputed(df, ATR_COLUMN, self.precompute).iloc[-1]

    def evaluate(self, df: pd.DataFrame) -> Signal:
        """LARGO en `rf_buy` sobre la EMA 144; CORTO en `rf_sell` bajo la EMA 144.

        Args:
            df: velas hasta la de la senal.

        Returns:
            La senal de la ultima vela.
        """
        row = self._row(df)
        if not warmed_up(row, self.warmup):
            return Signal.HOLD
        close, ema = float(row["close"]), float(row[EMA_COLUMN])
        if is_true(row["rf_buy"]) and close > ema:
            return Signal.LONG
        if is_true(row["rf_sell"]) and close < ema:
            return Signal.SHORT
        return Signal.HOLD

    def _distance(self, df: pd.DataFrame) -> float:
        return self.atr_mult * float(self._row(df)[ATR_COLUMN])

    def stop_price(self, df: pd.DataFrame, side: Signal, entry_price: float) -> float | None:
        """SL a `2.5 * ATR(14)` de la entrada (ATR de la vela de senal).

        Args:
            df: velas hasta la de la senal.
            side: direccion de la entrada.
            entry_price: precio de entrada.

        Returns:
            El precio del SL.
        """
        distance = self._distance(df)
        return entry_price - distance if side == Signal.LONG else entry_price + distance

    def trailing_distance(self, df: pd.DataFrame) -> float | None:
        """Trailing de `2.5 * ATR(14)` desde el mejor precio.

        Args:
            df: velas hasta la de la senal.

        Returns:
            La distancia del trailing.
        """
        return self._distance(df)
