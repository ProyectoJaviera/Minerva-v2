"""Pestana «Estudio» (v2): prueba hacia adelante de las estrategias en estudio y resumen de rondas.

Solo lectura: lee el archivo de historial local (el mismo de la pestana «Indicadores») en modo
inmutable y no escribe en la base del bot. Calcular la prueba tarda alrededor de un minuto, asi que
se hace en un hilo aparte y se guarda en memoria hasta que el archivo de historial cambie (la tarea
`MinervaV2HistoryUpdate` lo actualiza cada 6 horas). Mientras calcula, la ruta responde con
`status: "computing"`. Protegido con `require_auth` a nivel de router.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends

from app.api.deps import get_settings
from app.api.security import require_auth
from app.config import Settings
from app.core.logging import get_logger
from app.explorer.service import ReadOnlyDatabase
from app.research import study_summary
from app.research.forward import compute_forward

logger = get_logger(__name__)
router = APIRouter(prefix="/api/study", dependencies=[Depends(require_auth)])

_lock = threading.Lock()
_state: dict = {"key": None, "result": None, "computing": False, "error": None}


def _file_key(path: Path) -> tuple[str, float, int] | None:
    """Identifica una version del archivo (ruta, fecha de modificacion y tamano), o `None`."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (str(path.resolve()), stat.st_mtime, stat.st_size)


def _compute_in_thread(path: Path, key: tuple, settings: Settings) -> None:
    """Calcula la prueba en un hilo con su propio bucle de eventos y guarda el resultado."""

    async def run() -> dict:
        db = ReadOnlyDatabase(path)
        await db.connect()
        try:
            return await compute_forward(db, settings)
        finally:
            await db.close()

    try:
        result = asyncio.run(run())
        result["computed_at"] = datetime.now(UTC).isoformat()
        error = None
    except Exception as exc:  # aislado: la pestana muestra el error, el bot sigue igual
        logger.exception("No se pudo calcular la prueba hacia adelante")
        result, error = None, str(exc)
    with _lock:
        _state.update(key=key, result=result, error=error, computing=False)


def start_computation(path: Path, key: tuple, settings: Settings) -> None:
    """Lanza el calculo en segundo plano si no hay otro en curso.

    Args:
        path: archivo de historial.
        key: version del archivo (`_file_key`).
        settings: configuracion.

    Efectos:
        Crea un hilo que lee el archivo de historial (solo lectura).
    """
    with _lock:
        if _state["computing"]:
            return
        _state["computing"] = True
    threading.Thread(target=_compute_in_thread, args=(path, key, settings), daemon=True,
                     name="study-forward").start()


@router.get("/forward")
async def forward(settings: Settings = Depends(get_settings)) -> dict:
    """`GET /api/study/forward`: estado de la prueba hacia adelante y resumen de las rondas.

    Args:
        settings: configuracion (inyectada).

    Returns:
        `rounds` y `conclusion` (resumen fijo) y `status`: `missing` (no hay archivo de
        historial), `computing` (calculando; el resultado anterior, si lo hay, va en `result`),
        `ready` (con `result`, ver `compute_forward`) o `error` (con `detail`).

    Efectos:
        Puede lanzar el calculo en un hilo aparte (lectura del archivo de historial).
    """
    base = {"rounds": list(study_summary.ROUNDS), "conclusion": study_summary.CONCLUSION}
    path = Path(settings.explorer_history_db)
    key = _file_key(path)
    if key is None:
        return {**base, "status": "missing",
                "detail": f"No hay archivo de historial en {settings.explorer_history_db}. "
                          "Crealo con scripts/update_history_file.py."}
    with _lock:
        fresh = _state["key"] == key and not _state["computing"]
        result, error, computing = _state["result"], _state["error"], _state["computing"]
    if fresh and error is None and result is not None:
        return {**base, "status": "ready", "result": result}
    if fresh and error is not None:
        return {**base, "status": "error", "detail": error}
    if not computing:
        start_computation(path, key, settings)
    return {**base, "status": "computing", "result": result}
