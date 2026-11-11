"""Seccion «Indicadores» (v2): backtest EXPLORATORIO a pedido sobre el archivo de historial local.

No es la medicion en vivo ni una ronda preregistrada: no escribe en la base ni pasa por la puerta
de resultados. Protegido con `require_auth` a nivel de router.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_settings
from app.api.security import require_auth
from app.config import Settings
from app.explorer import confluence, data_status, service

router = APIRouter(prefix="/api/explorer", dependencies=[Depends(require_auth)])


def _missing_file_detail(path: str) -> str:
    return (f"No hay archivo de historial en {path}. Crealo con scripts/update_history_file.py "
            "(ver docs/v2/SECCION_INDICADORES.md).")


@router.get("/options")
async def options(settings: Settings = Depends(get_settings)) -> dict:
    """`GET /api/explorer/options`: indicadores, salidas, marcos y series del historial local.

    Args:
        settings: configuracion (inyectada).

    Returns:
        `available` (si existe el archivo), `detail`, `indicators` (id, etiqueta y tipo),
        `exits`, `default_exit`, `window` (por defecto y maximo), `timeframes` (id y etiqueta),
        `symbols`, `series` y la nota exploratoria.

    Efectos:
        Lee el archivo de historial (solo lectura).
    """
    base = {
        "note": service.NOTE,
        "timeframes": [{"id": t, "label": service.TIMEFRAME_LABELS[t]}
                       for t in service.TIMEFRAMES],
        "indicators": [{"id": k, "label": v[0], "kind": v[1]}
                       for k, v in confluence.INDICATORS.items()],
        "exits": [{"id": k, "label": v[0]} for k, v in confluence.EXITS.items()]
        + [{"id": confluence.PCT_EXIT, "label": confluence.PCT_EXIT_LABEL}],
        "pct_limits": {"sl": confluence.MAX_SL_PCT, "tp": confluence.MAX_TP_PCT,
                       "trail": confluence.MAX_TRAIL_PCT},
        # El motor omite una entrada si su SL perderia mas de este % del margen: con el
        # apalancamiento configurado, un SL en % mayor que `max_sl_pct_before_skip` se omite.
        "max_sl_pct_before_skip": round(settings.max_sl_margin_loss_pct / settings.leverage, 4),
        "default_exit": confluence.DEFAULT_EXIT,
        "window": {"default": confluence.DEFAULT_WINDOW, "max": confluence.MAX_WINDOW},
    }
    try:
        series = await service.available_series(settings.explorer_history_db)
    except service.HistoryFileMissingError:
        return {**base, "available": False,
                "detail": _missing_file_detail(settings.explorer_history_db),
                "symbols": [], "series": []}
    public = [{k: s[k] for k in ("symbol", "timeframe", "first_day", "last_day", "bars")}
              for s in series]
    return {**base, "available": bool(series),
            "detail": None if series else "El archivo de historial no tiene velas de estos marcos.",
            "symbols": sorted({s["symbol"] for s in series}), "series": public}


@router.get("/run")
async def run(
    symbols: Annotated[list[str], Query()],
    timeframe: str,
    indicators: Annotated[list[str], Query()],
    window: int = confluence.DEFAULT_WINDOW,
    exit: str = confluence.DEFAULT_EXIT,  # noqa: A002 - nombre del parametro de la API
    start: str | None = None,
    end: str | None = None,
    min_agree: int | None = None,
    sl_pct: float | None = None,
    tp_pct: float | None = None,
    trail_pct: float | None = None,
    settings: Settings = Depends(get_settings),
) -> dict:
    """`GET /api/explorer/run`: corre la confluencia elegida y su control al azar.

    Es `GET` a proposito: solo calcula sobre un archivo de solo lectura y no escribe nada (las
    unicas rutas que escriben siguen siendo login, logout y los controles).

    Args:
        symbols: monedas (`?symbols=BTCUSDT&symbols=ETHUSDT`).
        timeframe: `15m`, `1h`, `4h`, `1d` o `1w`.
        indicators: indicadores (uno o mas, repetidos como `symbols`).
        window: velas que dura el voto de un indicador de evento.
        exit: salida (clave de `confluence.EXITS`).
        start: fecha de inicio `AAAA-MM-DD` (UTC) opcional.
        end: fecha de fin `AAAA-MM-DD` (UTC, excluida) opcional.
        min_agree: cuantos indicadores deben coincidir (sin valor = todos).
        sl_pct: SL en % del precio de entrada (con `exit=pct`).
        tp_pct: TP en % (opcional, con `exit=pct`).
        trail_pct: trailing en % (opcional, con `exit=pct`).
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
        req = service.validate_request(symbols, timeframe, indicators, window, exit, start, end,
                                       min_agree, sl_pct, tp_pct, trail_pct)
    except service.ExplorerRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return await service.run_exploration(settings.explorer_history_db, req, settings)
    except service.HistoryFileMissingError as exc:
        raise HTTPException(status_code=404,
                            detail=_missing_file_detail(settings.explorer_history_db)) from exc


@router.get("/data-status")
async def data_status_route(settings: Settings = Depends(get_settings)) -> dict:
    """`GET /api/explorer/data-status`: si la captura de datos de la v2 esta al dia.

    Args:
        settings: configuracion (inyectada).

    Returns:
        `market` (`data_status.market_status`) e `history` (`data_status.history_status`).

    Efectos:
        Lee los dos archivos en solo lectura, en un hilo aparte.
    """
    market = await asyncio.to_thread(data_status.market_status, settings.market_data_db)
    history = await asyncio.to_thread(data_status.history_status, settings.explorer_history_db)
    return {"market": market, "history": history}
