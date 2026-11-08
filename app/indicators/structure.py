"""Estructura de precio de la v2: pivotes, SFP y zonas de liquidez (inspiradas en el Heatmap).

Inspirado en indicadores publicos de TradingView (autoria y licencia por verificar). No es una
traduccion del codigo original: la especificacion exacta, con sus diferencias deliberadas, esta en
`docs/v2/ESPECIFICACION_INDICADORES.md` (secciones A y B).

Todo es causal: lo que se informa en la vela `i` solo usa las velas `0..i`. Un pivote con `right`
velas a la derecha se conoce recien en la vela `p + right` (su confirmacion), y ahi se emite.

Los indices de posicion que devuelven estas funciones (`pivot_index`, `emit_index`, ...) son
posiciones 0..n-1 dentro del DataFrame recibido, no etiquetas de su indice.

No esta conectado a ninguna estrategia (Fase 0 de la v2: solo especificacion e implementacion).
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from app.indicators._pine import pine_atr, require_columns, require_positive

# Columnas de `sfp_signals` para cada lado ("bear" = SFP bajista sobre un maximo).
SFP_FIELDS = ("sweep", "signal", "swing", "opposite", "sweep_extreme", "bars_since_sweep")

ZONE_COLUMNS = (
    "side", "pivot_index", "emit_index", "price", "top", "bottom", "mid", "width",
    "volume_ratio", "mitigated_index",
)


def _pivot(values: pd.Series, left: int, right: int, *, high: bool) -> pd.Series:
    """Pivote estricto confirmado en la vela `p + right` (NaN en las demas)."""
    require_positive(left=left, right=right)
    arr = values.to_numpy(dtype=float)
    out = np.full(len(arr), np.nan)
    span = left + right + 1
    if len(arr) < span:
        return pd.Series(out, index=values.index)
    windows = sliding_window_view(arr, span)
    center = windows[:, left]
    others = np.delete(windows, left, axis=1)
    with np.errstate(invalid="ignore"):
        beats = (center[:, None] > others) if high else (center[:, None] < others)
    mask = beats.all(axis=1) & ~np.isnan(windows).any(axis=1)
    confirmed = out[span - 1:]
    confirmed[mask] = center[mask]
    return pd.Series(out, index=values.index)


def pivot_high(high: pd.Series, left: int, right: int) -> pd.Series:
    """Maximo de pivote: estrictamente mayor que las `left` velas previas y las `right` siguientes.

    El valor aparece en la vela de confirmacion (`p + right`), como `ta.pivothigh` de Pine. El
    manejo de empates del original no esta verificado; aqui un empate NO es pivote.

    Args:
        high: serie de maximos.
        left: velas a la izquierda (>= 1).
        right: velas a la derecha (>= 1).

    Returns:
        Serie con el precio del pivote en su vela de confirmacion y NaN en las demas.

    Raises:
        ValueError: si `left` o `right` son menores que 1.
    """
    return _pivot(high, left, right, high=True)


def pivot_low(low: pd.Series, left: int, right: int) -> pd.Series:
    """Minimo de pivote: estrictamente menor que las `left` velas previas y las `right` siguientes.

    Args:
        low: serie de minimos.
        left: velas a la izquierda (>= 1).
        right: velas a la derecha (>= 1).

    Returns:
        Serie con el precio del pivote en su vela de confirmacion y NaN en las demas.

    Raises:
        ValueError: si `left` o `right` son menores que 1.
    """
    return _pivot(low, left, right, high=False)


def _sfp_side(
    df: pd.DataFrame, left: int, right: int, max_age: int, *, bearish: bool
) -> dict[str, np.ndarray]:
    """Maquina de estados de un lado del SFP (ver la especificacion, seccion A)."""
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    open_ = df["open"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    n = len(df)
    pivots = (pivot_high(df["high"], left, right) if bearish
              else pivot_low(df["low"], left, right)).to_numpy()

    out = {
        "sweep": np.zeros(n, dtype=bool),
        "signal": np.zeros(n, dtype=bool),
        "swing": np.full(n, np.nan),
        "opposite": np.full(n, np.nan),
        "sweep_extreme": np.full(n, np.nan),
        "bars_since_sweep": np.full(n, np.nan),
    }
    swing_price = np.nan
    swing_index = -1
    # Setup vigente: lo crea cada barrida y lo reemplaza la siguiente.
    setup_active = False
    setup_confirmed = False
    setup_swing = np.nan
    setup_swing_index = -1
    setup_opposite = np.nan
    setup_sweep_index = -1
    setup_extreme = np.nan

    for i in range(n):
        if not np.isnan(pivots[i]):
            swing_price = pivots[i]
            swing_index = i - right
        if swing_index >= 0:
            if bearish:
                swept = high[i] > swing_price and open_[i] < swing_price and close[i] < swing_price
            else:
                swept = low[i] < swing_price and open_[i] > swing_price and close[i] > swing_price
            if swept:
                between = slice(swing_index + 1, i)
                if bearish:
                    opposite = min(swing_price, float(np.min(low[between]))) \
                        if i - swing_index > 1 else swing_price
                else:
                    opposite = max(swing_price, float(np.max(high[between]))) \
                        if i - swing_index > 1 else swing_price
                setup_active, setup_confirmed = True, False
                setup_swing, setup_swing_index = swing_price, swing_index
                setup_opposite = opposite
                setup_sweep_index = i
                setup_extreme = high[i] if bearish else low[i]
                out["sweep"][i] = True
        if setup_active and not setup_confirmed:
            confirmed = close[i] < setup_opposite if bearish else close[i] > setup_opposite
            if confirmed:
                setup_confirmed = True
                out["signal"][i] = True
                out["swing"][i] = setup_swing
                out["opposite"][i] = setup_opposite
                out["sweep_extreme"][i] = setup_extreme
                out["bars_since_sweep"][i] = i - setup_sweep_index
        if setup_swing_index >= 0:
            invalid = close[i] > setup_swing if bearish else close[i] < setup_swing
            if i - setup_swing_index > max_age or invalid:
                setup_active = False
    return out


def sfp_signals(
    df: pd.DataFrame, left: int = 5, right: int = 1, max_age: int = 500
) -> pd.DataFrame:
    """Swing Failure Pattern (SFP) del Heatmap: barrida de un pivote y confirmacion.

    Bajista (sobre un maximo de pivote `left`/`right`): la vela barre el maximo vigente
    (`high > swing`, con `open` y `close` por debajo); el setup se confirma en la primera vela que
    cierra por debajo del minimo mas bajo entre el pivote y la vela de barrida (el "extremo
    opuesto"). Se invalida si cierra por encima del pivote o si pasan mas de `max_age` velas desde
    el pivote. El alcista es el espejo sobre un minimo de pivote.

    Args:
        df: velas con `open`, `high`, `low` y `close`, en orden cronologico.
        left: velas a la izquierda del pivote (5 en el original).
        right: velas a la derecha del pivote (1 en el original).
        max_age: vida maxima del setup en velas desde el pivote (500 en el original).

    Returns:
        DataFrame con el mismo indice y, para `bear` y `bull`, las columnas
        `sfp_<lado>_sweep` (vela de barrida), `sfp_<lado>_signal` (vela de confirmacion: la
        senal) y, solo en las velas de senal, `sfp_<lado>_swing`, `_opposite`,
        `_sweep_extreme` (maximo o minimo de la vela de barrida) y `_bars_since_sweep`.

    Raises:
        ValueError: si falta una columna o algun parametro es menor que 1.
    """
    require_columns(df, ("open", "high", "low", "close"))
    require_positive(left=left, right=right, max_age=max_age)
    columns: dict[str, np.ndarray] = {}
    for side, bearish in (("bear", True), ("bull", False)):
        result = _sfp_side(df, left, right, max_age, bearish=bearish)
        for field in SFP_FIELDS:
            columns[f"sfp_{side}_{field}"] = result[field]
    return pd.DataFrame(columns, index=df.index)


def heatmap_atr_multiplier(interval: str) -> float:
    """Multiplicador del ATR del Heatmap segun el marco de tiempo.

    Regla del original: 0.2 si el marco es de 60 minutos o mas (en minutos), 0.25 en minutos por
    debajo de 60, 0.2 en diario y 0.4 en lo demas (semanal, mensual).

    Args:
        interval: marco de tiempo como `"15m"`, `"1h"`, `"4h"`, `"1d"`, `"1w"` o `"1M"`.

    Returns:
        El multiplicador del ATR(200) para el ancho de la zona.

    Raises:
        ValueError: si el marco no tiene el formato `<numero><m|h|d|w|M>`.
    """
    match = re.fullmatch(r"(\d+)([mhdwM])", interval.strip())
    if not match:
        raise ValueError(f"Marco de tiempo no reconocido: {interval!r}")
    amount, unit = int(match.group(1)), match.group(2)
    if amount < 1:
        raise ValueError(f"Marco de tiempo no reconocido: {interval!r}")
    if unit == "m":
        return 0.2 if amount >= 60 else 0.25
    if unit in ("h", "d"):
        return 0.2
    return 0.4


def liquidity_zones(
    df: pd.DataFrame,
    left: int = 2,
    right: int = 2,
    atr_period: int = 200,
    atr_mult: float = 0.2,
    volume_window: int = 500,
) -> pd.DataFrame:
    """Zonas de liquidez deterministas sobre pivotes (definicion propia inspirada en el Heatmap).

    Una zona por pivote confirmado, emitida en su vela de confirmacion (`p + right`), nunca antes:
    sobre un maximo, `[high_p, high_p + w]`; bajo un minimo, `[low_p - w, low_p]`, con
    `w = atr_mult * ATR(atr_period)` evaluado en la vela del pivote. Si ese ATR aun no existe, no
    hay zona. La zona se mitiga en la primera vela posterior a su emision con
    `high > punto medio` y `low < punto medio`; una vez mitigada no vuelve.

    Args:
        df: velas con `high`, `low` y `close`; `volume` es opcional.
        left: velas a la izquierda del pivote (2 en el original).
        right: velas a la derecha del pivote (2 en el original).
        atr_period: periodo del ATR (200 en el original).
        atr_mult: multiplicador del ATR (ver `heatmap_atr_multiplier`; 0.2 en 1h y 4h).
        volume_window: velas para el volumen medio de `volume_ratio` (500 en el original).

    Returns:
        DataFrame con una fila por zona, ordenado por `emit_index` y lado (`high` antes que
        `low`), y columnas `side`, `pivot_index`, `emit_index`, `price` (extremo del pivote),
        `top`, `bottom`, `mid`, `width`, `volume_ratio` (volumen de la vela del pivote sobre la
        media de las `volume_window` velas hasta la emision; con `high - low` si no hay
        `volume`) y `mitigated_index` (`<NA>` si sigue activa).

    Raises:
        ValueError: si falta una columna, algun periodo es menor que 1 o `atr_mult` no es
            positivo.
    """
    require_columns(df, ("high", "low", "close"))
    require_positive(left=left, right=right, atr_period=atr_period, volume_window=volume_window)
    if not atr_mult > 0:
        raise ValueError("atr_mult debe ser positivo")
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    atr = pine_atr(df, atr_period).to_numpy()
    if "volume" in df.columns:
        volume = df["volume"].to_numpy(dtype=float)
    else:
        volume = high - low
    ph = pivot_high(df["high"], left, right).to_numpy()
    pl = pivot_low(df["low"], left, right).to_numpy()

    rows: list[dict[str, object]] = []
    for emit in range(len(df)):
        for side, pivots in (("high", ph), ("low", pl)):
            if np.isnan(pivots[emit]):
                continue
            pivot = emit - right
            width = atr_mult * atr[pivot]
            if np.isnan(width):
                continue
            price = pivots[emit]
            top, bottom = (price + width, price) if side == "high" else (price, price - width)
            mid = (top + bottom) / 2
            after = slice(emit + 1, len(df))
            hits = np.flatnonzero((high[after] > mid) & (low[after] < mid))
            mitigated = emit + 1 + int(hits[0]) if hits.size else pd.NA
            window = volume[max(0, emit - volume_window + 1): emit + 1]
            mean_volume = np.nanmean(window) if np.isfinite(window).any() else np.nan
            ratio = volume[pivot] / mean_volume if mean_volume and mean_volume > 0 else np.nan
            rows.append({
                "side": side, "pivot_index": pivot, "emit_index": emit, "price": price,
                "top": top, "bottom": bottom, "mid": mid, "width": width,
                "volume_ratio": float(ratio), "mitigated_index": mitigated,
            })
    zones = pd.DataFrame(rows, columns=list(ZONE_COLUMNS))
    zones["side"] = zones["side"].astype("str")
    zones["pivot_index"] = zones["pivot_index"].astype("int64")
    zones["emit_index"] = zones["emit_index"].astype("int64")
    zones["mitigated_index"] = zones["mitigated_index"].astype("Int64")
    for col in ("price", "top", "bottom", "mid", "width", "volume_ratio"):
        zones[col] = zones[col].astype(float)
    return zones


def active_zones_at(zones: pd.DataFrame, index: int) -> pd.DataFrame:
    """Zonas activas al cierre de la vela `index`: emitidas hasta ella y aun no mitigadas.

    La vela que mitiga una zona ya la ve mitigada (la mitigacion se conoce al cierre de esa vela).

    Args:
        zones: resultado de `liquidity_zones`.
        index: posicion de la vela (0..n-1).

    Returns:
        Las filas de `zones` activas en esa vela.
    """
    emitted = zones["emit_index"] <= index
    mitigated = zones["mitigated_index"].fillna(index + 1) <= index
    return zones[emitted & ~mitigated.astype(bool)]
