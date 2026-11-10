"""Crea o actualiza el archivo de historial local de la seccion «Indicadores» (v2, exploratoria).

Es `scripts/download_history.py` (universo top-10 de CoinGecko mas los simbolos de control; velas
LAST_PRICE y MARK_PRICE de 1h, 4h y 1d desde el piso real de Bitunix, y funding) escribiendo en un
archivo SQLite APARTE de la base del bot: `EXPLORER_HISTORY_DB`, por defecto
`./history/history_v2.db`. Es reanudable: correrlo de nuevo solo baja lo que falta. Las velas de
Bitunix coinciden con las de TradingView (docs/historial/PROGRESS.md, comparacion del 2026-11-09).

Se niega a escribir en la base del bot, en `data/` o en cualquier archivo que no termine en `.db`.
Con el contenedor de la v2 corriendo no hace falta reiniciarlo: la seccion vuelve a leer el archivo
cuando cambia su fecha de modificacion (mejor correrlo cuando nadie esta usando la seccion).

Uso:
    python scripts/update_history_file.py [--path history/history_v2.db]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, ".")

DEFAULT_PATH = "./history/history_v2.db"


def check_target(target: str, bot_db: str) -> Path:
    """Valida el archivo destino y lo devuelve resuelto.

    Args:
        target: ruta pedida para el archivo de historial.
        bot_db: ruta de la base del bot (`DATABASE_PATH` vigente).

    Returns:
        La ruta absoluta.

    Raises:
        SystemExit: si apunta a la base del bot, a una carpeta `data/` o no termina en `.db`.
    """
    path = Path(target).resolve()
    if path.suffix != ".db":
        raise SystemExit(f"El archivo de historial debe terminar en .db: {path}")
    if path == Path(bot_db).resolve():
        raise SystemExit("El archivo de historial no puede ser la base del bot.")
    if "data" in {p.lower() for p in path.parts[:-1]}:
        raise SystemExit("El archivo de historial no puede quedar dentro de una carpeta data/.")
    return path


def main() -> None:
    """Valida el destino, fija `DATABASE_PATH` en ese archivo y corre la descarga.

    Efectos:
        Red: CoinGecko y Bitunix (publicas). Disco: crea la carpeta del archivo y escribe en ese
        archivo SQLite (nunca en la base del bot). Cambia `DATABASE_PATH` solo en este proceso.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", default=os.environ.get("EXPLORER_HISTORY_DB", DEFAULT_PATH))
    args = parser.parse_args()
    from app.config import settings  # el DATABASE_PATH del bot, antes de cambiarlo

    target = check_target(args.path, settings.database_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    os.environ["DATABASE_PATH"] = str(target)
    settings.database_path = str(target)
    assert Path(settings.database_path).resolve() == target
    print(f"Archivo de historial: {target}")

    from scripts import download_history

    asyncio.run(download_history.main())


if __name__ == "__main__":
    main()
