"""Candidato `sfp_reversal_5_1` y su control `control_sfp_random_dir_seed42` (preregistro v2).

`sfp_reversal_5_1`: CORTO en la confirmacion de un SFP bajista y LARGO en la de un SFP alcista
(`app/indicators/structure.py::sfp_signals`, pivote 5/1, `max_age` 500). SL = extremo de la vela
de barrida +- `0.1 * ATR(14)` (un colchon mas alla de la mecha); TP = 2R sobre esa distancia. Si
el `open` de la vela de entrada ya paso el SL, la entrada se omite (`skip_entry_if_sl_crossed`).

`control_sfp_random_dir_seed42`: entra en las MISMAS velas que el SFP, con la direccion sorteada
50/50 de forma determinista, y la misma distancia de SL (puesta del lado sorteado) y TP 2R. Sirve
para separar el valor de la direccion del SFP del de su momento y su gestion de riesgo. Nunca se
aprueba (ver el preregistro).

Inspirado en indicadores publicos de TradingView (autoria y licencia por verificar). No esta en
`STRATEGIES`: ni el scheduler ni el backtest oficial lo usan todavia.
"""

from __future__ import annotations

import hashlib
import math

import pandas as pd

from app.candidates.common import (
    WARMUP_BARS,
    add_bar_index,
    ensure_precomputed,
    is_true,
    warmed_up,
)
from app.indicators._pine import pine_atr
from app.indicators.structure import sfp_signals
from app.strategies.base import BaseStrategy, Signal

ATR_COLUMN = "v2_atr14"


class SfpReversalStrategy(BaseStrategy):
    """SFP 5/1 con SL detras de la mecha de barrida y TP 2R.

    Attributes:
        name: `sfp_reversal_5_1`.
        skip_entry_if_sl_crossed: el motor omite la entrada si el `open` ya cruzo el SL.
    """

    name = "sfp_reversal_5_1"
    skip_entry_if_sl_crossed = True

    def __init__(
        self,
        left: int = 5,
        right: int = 1,
        max_age: int = 500,
        atr_period: int = 14,
        buffer_atr: float = 0.1,
        reward_risk: float = 2.0,
        warmup: int = WARMUP_BARS,
    ) -> None:
        """Parametros fijos del preregistro (los argumentos existen para las pruebas).

        Args:
            left: velas a la izquierda del pivote (5).
            right: velas a la derecha del pivote (1).
            max_age: vida maxima del setup en velas desde el pivote (500).
            atr_period: periodo del ATR del colchon (14).
            buffer_atr: colchon del SL en ATR mas alla de la mecha (0.1).
            reward_risk: TP en multiplos de la distancia al SL (2.0).
            warmup: velas de calentamiento sin senales (500).
        """
        self.left = left
        self.right = right
        self.max_age = max_age
        self.atr_period = atr_period
        self.buffer_atr = buffer_atr
        self.reward_risk = reward_risk
        self.warmup = warmup

    def precompute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Agrega las columnas del SFP, el ATR del colchon y la posicion de cada vela.

        Args:
            df: velas OHLC de toda la serie.

        Returns:
            Una copia de `df` con `sfp_*`, `v2_atr14` y `v2_bar_index`.
        """
        out = add_bar_index(df)
        signals = sfp_signals(df, self.left, self.right, self.max_age)
        for col in signals.columns:
            out[col] = signals[col].to_numpy()
        out[ATR_COLUMN] = pine_atr(df, self.atr_period).to_numpy()
        return out

    def _row(self, df: pd.DataFrame) -> pd.Series:
        return ensure_precomputed(df, ATR_COLUMN, self.precompute).iloc[-1]

    def sfp_side(self, df: pd.DataFrame) -> Signal:
        """Lado natural del SFP en la ultima vela (sin calentamiento ni sorteo).

        Args:
            df: velas hasta la de la senal.

        Returns:
            `LONG` si confirma un SFP alcista, `SHORT` si bajista, `HOLD` si ninguno o ambos.
        """
        row = self._row(df)
        bull = is_true(row["sfp_bull_signal"])
        bear = is_true(row["sfp_bear_signal"])
        if bull == bear:
            return Signal.HOLD
        return Signal.LONG if bull else Signal.SHORT

    def evaluate(self, df: pd.DataFrame) -> Signal:
        """LARGO en un SFP alcista confirmado, CORTO en uno bajista; nada en el calentamiento.

        Args:
            df: velas hasta la de la senal (idealmente ya precalculadas).

        Returns:
            La senal de la ultima vela.
        """
        if not warmed_up(self._row(df), self.warmup):
            return Signal.HOLD
        return self.sfp_side(df)

    def natural_stop(self, df: pd.DataFrame) -> float:
        """SL del lado natural del SFP: extremo de la barrida +- colchon de ATR.

        Args:
            df: velas hasta la de la senal.

        Returns:
            El precio del SL, o NaN si la vela no tiene SFP o falta el ATR.
        """
        row = self._row(df)
        side = self.sfp_side(df)
        atr = float(row[ATR_COLUMN])
        if side == Signal.LONG:
            return float(row["sfp_bull_sweep_extreme"]) - self.buffer_atr * atr
        if side == Signal.SHORT:
            return float(row["sfp_bear_sweep_extreme"]) + self.buffer_atr * atr
        return math.nan

    def stop_price(self, df: pd.DataFrame, side: Signal, entry_price: float) -> float | None:
        """SL detras de la mecha; si no se puede calcular, la propia entrada (=> se omite).

        Args:
            df: velas hasta la de la senal.
            side: direccion de la entrada.
            entry_price: precio de entrada (el `open` de la vela siguiente).

        Returns:
            El precio del SL. Si quedo del lado equivocado de la entrada, el motor omite la
            entrada (`skip_entry_if_sl_crossed`).
        """
        sl = self.natural_stop(df)
        return entry_price if math.isnan(sl) else sl

    def take_profit_price(self, df: pd.DataFrame, side: Signal, entry_price: float) -> float | None:
        """TP a `reward_risk` veces la distancia entre la entrada y el SL.

        Args:
            df: velas hasta la de la senal.
            side: direccion de la entrada.
            entry_price: precio de entrada.

        Returns:
            El precio del TP.
        """
        distance = abs(entry_price - self.stop_price(df, side, entry_price))
        move = self.reward_risk * distance
        return entry_price + move if side == Signal.LONG else entry_price - move


def random_direction(seed: int, open_time: int, close: float) -> Signal:
    """Sorteo 50/50 determinista para una vela: `LONG` o `SHORT`.

    Depende solo de la semilla y de la vela (apertura en ms y cierre), no del orden en que se
    recorran las series: dos corridas dan siempre el mismo resultado y dos simbolos con la misma
    hora sortean por separado (sus cierres difieren).

    Args:
        seed: semilla fija (42).
        open_time: apertura de la vela de senal, en ms UTC.
        close: cierre de la vela de senal.

    Returns:
        La direccion sorteada.
    """
    digest = hashlib.sha256(f"{seed}|{int(open_time)}|{float(close)!r}".encode()).digest()
    return Signal.LONG if digest[0] & 1 else Signal.SHORT


class ControlSfpRandomDirStrategy(SfpReversalStrategy):
    """Control: mismas velas y misma distancia de SL que el SFP, direccion sorteada.

    Attributes:
        name: `control_sfp_random_dir_seed42`.
        seed: semilla del sorteo (42).
    """

    name = "control_sfp_random_dir_seed42"
    seed = 42

    def evaluate(self, df: pd.DataFrame) -> Signal:
        """Senal en las mismas velas que `sfp_reversal_5_1`, con la direccion sorteada.

        Args:
            df: velas hasta la de la senal; necesitan `open_time`.

        Returns:
            La senal sorteada, o `HOLD` si el SFP no tiene senal.

        Raises:
            ValueError: si falta `open_time` (el sorteo depende de la vela).
        """
        if super().evaluate(df) == Signal.HOLD:
            return Signal.HOLD
        if "open_time" not in df.columns:
            raise ValueError("El control necesita la columna open_time")
        row = df.iloc[-1]
        return random_direction(self.seed, int(row["open_time"]), float(row["close"]))

    def stop_price(self, df: pd.DataFrame, side: Signal, entry_price: float) -> float | None:
        """La distancia del SL del SFP natural, puesta del lado de la direccion sorteada.

        Si el SFP natural habria omitido la entrada (su SL ya cruzado), el control tambien.

        Args:
            df: velas hasta la de la senal.
            side: direccion sorteada.
            entry_price: precio de entrada.

        Returns:
            El precio del SL (la propia entrada si hay que omitirla).
        """
        natural_side = self.sfp_side(df)
        natural_sl = self.natural_stop(df)
        if math.isnan(natural_sl):
            return entry_price
        crossed = natural_sl >= entry_price if natural_side == Signal.LONG \
            else natural_sl <= entry_price
        if crossed:
            return entry_price
        distance = abs(entry_price - natural_sl)
        return entry_price - distance if side == Signal.LONG else entry_price + distance
