"""Niveles Camarilla del dia UTC anterior (inspirados en el modulo de niveles de Frost).

Inspirado en indicadores publicos de TradingView (autoria y licencia por verificar). La
especificacion exacta esta en `docs/v2/ESPECIFICACION_INDICADORES.md` (seccion E).

Cada vela del dia UTC `D` recibe los niveles calculados con el maximo, el minimo y el cierre del
dia UTC `D - 1` completo, agregado desde las propias velas de la serie. Es causal: todas las velas
de `D - 1` cierran antes de que empiece `D`.

No esta conectado a ninguna estrategia (Fase 0 de la v2).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.indicators._pine import require_columns

DAY_MS = 86_400_000

# Fraccion del rango del dia anterior que suma (R) o resta (S) cada nivel al cierre: 1.1 / k.
CAMARILLA_DIVISORS = {"r4": 2, "r3": 4, "r2": 6, "r1": 12, "s1": 12, "s2": 6, "s3": 4, "s4": 2}

CAMARILLA_COLUMNS = (
    "cam_prev_high", "cam_prev_low", "cam_prev_close",
    "cam_r4", "cam_r3", "cam_r2", "cam_r1", "cam_s1", "cam_s2", "cam_s3", "cam_s4",
)


def camarilla_from_hlc(
    high: float | pd.Series, low: float | pd.Series, close: float | pd.Series
) -> dict[str, float | pd.Series]:
    """Los ocho niveles Camarilla a partir del maximo, el minimo y el cierre de un dia.

    `R_k = C + (H - L) * 1.1 / d_k` y `S_k = C - (H - L) * 1.1 / d_k`, con `d` = 12, 6, 4, 2 para
    k = 1..4.

    Args:
        high: maximo del dia (o una serie de maximos).
        low: minimo del dia (o una serie de minimos).
        close: cierre del dia (o una serie de cierres).

    Returns:
        Diccionario `r4, r3, r2, r1, s1, s2, s3, s4` -> precio (o serie de precios).
    """
    span = (high - low) * 1.1
    return {
        name: close + span / div if name.startswith("r") else close - span / div
        for name, div in CAMARILLA_DIVISORS.items()
    }


def camarilla_levels(
    df: pd.DataFrame, interval_ms: int | None = None, require_complete: bool = True
) -> pd.DataFrame:
    """Niveles Camarilla del dia UTC anterior para cada vela.

    Args:
        df: velas con `open_time` (milisegundos UTC de apertura, estrictamente creciente),
            `high`, `low` y `close`.
        interval_ms: duracion de una vela en milisegundos; si es `None` se toma la menor
            diferencia positiva entre aperturas consecutivas. Debe dividir exactamente un dia.
        require_complete: si es `True`, un dia anterior con velas faltantes no da niveles (NaN);
            si es `False`, se usan las velas que haya.

    Returns:
        DataFrame con el mismo indice y las columnas `cam_prev_high`, `cam_prev_low`,
        `cam_prev_close` y `cam_r4` ... `cam_s4`. NaN cuando el dia anterior no esta en la serie
        (o esta incompleto con `require_complete`).

    Raises:
        ValueError: si falta una columna, `open_time` no es estrictamente creciente o la
            duracion de la vela no divide un dia.
    """
    require_columns(df, ("open_time", "high", "low", "close"))
    out = pd.DataFrame(np.nan, index=df.index, columns=list(CAMARILLA_COLUMNS))
    if df.empty:
        return out
    open_time = df["open_time"].to_numpy(dtype="int64")
    diffs = np.diff(open_time)
    if (diffs <= 0).any():
        raise ValueError("open_time debe ser estrictamente creciente")
    if interval_ms is None:
        interval_ms = int(diffs.min()) if diffs.size else DAY_MS
    if interval_ms <= 0 or interval_ms > DAY_MS or DAY_MS % interval_ms != 0:
        raise ValueError(f"La duracion de la vela ({interval_ms} ms) debe dividir un dia")
    expected = DAY_MS // interval_ms

    day = open_time // DAY_MS
    frame = pd.DataFrame({
        "day": day,
        "high": df["high"].to_numpy(dtype=float),
        "low": df["low"].to_numpy(dtype=float),
        "close": df["close"].to_numpy(dtype=float),
    })
    daily = frame.groupby("day").agg(
        high=("high", "max"), low=("low", "min"), close=("close", "last"),
        count=("close", "count"),
    )
    if require_complete:
        daily = daily[daily["count"] == expected]
    prev = daily.reindex(day - 1)
    out["cam_prev_high"] = prev["high"].to_numpy()
    out["cam_prev_low"] = prev["low"].to_numpy()
    out["cam_prev_close"] = prev["close"].to_numpy()
    levels = camarilla_from_hlc(
        out["cam_prev_high"], out["cam_prev_low"], out["cam_prev_close"]
    )
    for name, values in levels.items():
        out[f"cam_{name}"] = values
    return out
