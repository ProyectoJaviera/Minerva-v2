"""Seccion «Indicadores» (v2): backtest EXPLORATORIO a pedido sobre el archivo de historial local.

No es la medicion en vivo ni una ronda preregistrada: no escribe en la base ni pasa por la puerta
de resultados. Nunca usa velas desde el 2026-10-01 (reservadas). Protegido con `require_auth` a
nivel de router.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_settings
from app.api.security import require_auth
from app.config import Settings
from app.explorer import service
from app.research.combos import FILTERS, NATIVE_EXIT, TRIGGERS

router = APIRouter(prefix="/api/explorer", dependencies=[Depends(require_auth)])


def _missing_file_detail(path: str) -> str:
    return (f"No hay archivo de historial en {path}. Crealo con scripts/download_history.py "
            "(ver docs/v2/SECCION_INDICADORES.md).")


@router.get("/options")
async def options(settings: Settings = Depends(get_settings)) -> dict:
    """`GET /api/explorer/options`: gatillos, filtros y series disponibles en el historial local.

    Args:
        settings: configuracion (inyectada).

    Returns:
        `available` (si existe el archivo), `detail`, `triggers`, `filters`, `timeframes`,
        `symbols`, `series`, `reserved_from`, `max_filters` y la nota exploratoria.

    Efectos:
        Lee el archivo de historial (solo lectura).
    """
    base = {
        "note": service.NOTE,
        "reserved_from": service.RESERVED_FROM.strftime("%Y-%m-%d"),
        "max_filters": service.MAX_FILTERS,
        "timeframes": list(service.TIMEFRAMES),
        "triggers": [{"id": t, "label": service.TRIGGER_LABELS.get(t, t),
                      "exit": "native" if t in NATIVE_EXIT else "atr"} for t in TRIGGERS],
        "filters": [{"id": f, "label": service.FILTER_LABELS.get(f, f)} for f in FILTERS],
    }
    try:
        series = await service.available_series(settings.explorer_history_db)
    except service.HistoryFileMissingError:
        return {**base, "available": False,
                "detail": _missing_file_detail(settings.explorer_history_db),
                "symbols": [], "series": []}
    public = [{k: s[k] for k in ("symbol", "timeframe", "first_day", "last_day", "bars")}
              for s in series]
    return {**base, "available": bool(series), "detail": None if series else
            "El archivo de historial no tiene velas de 1h ni de 4h.",
            "symbols": sorted({s["symbol"] for s in series}), "series": public}


@router.get("/run")
async def run(
    symbols: Annotated[list[str], Query()],
    timeframe: str,
    trigger: str,
    filters: Annotated[list[str] | None, Query()] = None,
    start: str | None = None,
    end: str | None = None,
    settings: Settings = Depends(get_settings),
) -> dict:
    """`GET /api/explorer/run`: corre la combinacion elegida y su control al azar.

    Es `GET` a proposito: solo calcula sobre un archivo de solo lectura y no escribe nada (las
    unicas rutas que escriben siguen siendo login, logout y los controles).

    Args:
        symbols: monedas (`?symbols=BTCUSDT&symbols=ETHUSDT`).
        timeframe: `1h` o `4h`.
        trigger: gatillo.
        filters: filtros (0 a 2, repetidos como `symbols`).
        start: fecha de inicio `AAAA-MM-DD` (UTC) opcional.
        end: fecha de fin `AAAA-MM-DD` (UTC, excluida) opcional.
        settings: configuracion (inyectada).

    Returns:
        El resultado exploratorio (ver `service.run_exploration_on_db`).

    Raises:
        HTTPException: 400 si los parametros no son validos; 404 si no hay archivo de
            historial.

    Efectos:
        Lee el archivo de historial (solo lectura). No escribe en ninguna base.
    """
    try:
        req = service.validate_request(symbols, timeframe, trigger, filters or [], start, end)
    except service.ExplorerRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return await service.run_exploration(settings.explorer_history_db, req, settings)
    except service.HistoryFileMissingError as exc:
        raise HTTPException(status_code=404,
                            detail=_missing_file_detail(settings.explorer_history_db)) from exc
