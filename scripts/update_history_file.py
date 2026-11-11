"""Crea o actualiza el archivo de historial local de la seccion «Indicadores» (v2, exploratoria).

Es `scripts/download_history.py` (universo top-10 de CoinGecko mas los simbolos de control; velas
LAST_PRICE y MARK_PRICE de 1h, 4h y 1d desde el piso real de Bitunix, y funding) escribiendo en un
archivo SQLite APARTE de la base del bot: `EXPLORER_HISTORY_DB`, por defecto
`./history/history_v2.db`; despues baja tambien las velas de `EXTRA_TIMEFRAMES` (15m y 1w, que la
seccion ofrece y el backtest de la Fase 2 no usa) de los mismos simbolos. Ambos intervalos se
verificaron contra la API publica de Bitunix el 2026-11-11 (la semanal abre el lunes 00:00 UTC).
Es reanudable: correrlo de nuevo solo baja lo que falta. Las velas de Bitunix coinciden con las de
TradingView (docs/historial/PROGRESS.md, comparacion del 2026-11-09).

Se niega a escribir en la base del bot, en `data/` o en cualquier archivo que no termine en `.db`.
Con el contenedor de la v2 corriendo no hace falta reiniciarlo: la seccion vuelve a leer el archivo
cuando cambia su fecha de modificacion (mejor correrlo cuando nadie esta usando la seccion).

Uso:
    python scripts/update_history_file.py [--path history/history_v2.db] [--only-extra] [--via-copy]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, ".")

DEFAULT_PATH = "./history/history_v2.db"
EXTRA_TIMEFRAMES = ("15m", "1w")


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


async def download_extra_timeframes(timeframes: tuple[str, ...] = EXTRA_TIMEFRAMES) -> None:
    """Baja las velas de `timeframes` (LAST y MARK) de los simbolos que ya tiene el archivo.

    Usa `settings.database_path`, que `main` ya fijo en el archivo de historial. Reanudable: cada
    serie solo pide lo que falta y al terminar sin errores se marca completa.

    Args:
        timeframes: marcos extra a bajar.

    Efectos:
        Red: Bitunix (publica). Escribe `ohlcv_cache`, `ohlcv_floor` y `ohlcv_series_complete`
        del archivo de historial.
    """
    import time

    from app.config import settings
    from app.market.bitunix_rest import BitunixRestClient
    from app.market.ohlcv_history import download_missing
    from app.persistence.database import Database
    from app.persistence.repositories import ohlcv_repo
    from scripts.download_history import START_MS

    db = Database(settings.database_path)
    await db.connect()
    client = BitunixRestClient(base_url=settings.bitunix_rest_base_url,
                               rate_limit_per_sec=settings.bitunix_rate_limit_per_sec)
    try:
        rows = await db.fetch_all("SELECT DISTINCT symbol FROM ohlcv_cache WHERE interval = '1d'")
        symbols = sorted(r["symbol"] for r in rows)
        end_ms = int(time.time() * 1000)
        series = [(s, tf, pt) for s in symbols for tf in timeframes
                  for pt in ("LAST_PRICE", "MARK_PRICE")]
        for n, (symbol, tf, price_type) in enumerate(series, 1):
            print(f"serie extra {n}/{len(series)}: {symbol} {tf} {price_type}", flush=True)
            await download_missing(client, db, symbol, tf, START_MS, end_ms, price_type)
            await ohlcv_repo.mark_series_complete(db, symbol, tf, price_type, START_MS, end_ms)
    finally:
        await client.aclose()
        await db.close()


def replace_with_retries(src: Path, dst: Path, attempts: int = 6, wait_s: float = 10.0,
                         sleep=None) -> bool:
    """Reemplaza `dst` por `src` de forma atomica, reintentando si `dst` esta abierto.

    En Windows no se puede reemplazar un archivo que otro proceso tiene abierto (la pestana
    Indicadores lo abre solo mientras calcula): se reintenta unas veces y, si no se puede, se deja
    `src` en su lugar para la proxima corrida.

    Args:
        src: archivo nuevo.
        dst: archivo a reemplazar.
        attempts: intentos.
        wait_s: segundos entre intentos.
        sleep: funcion de espera (para las pruebas); por defecto `time.sleep`.

    Returns:
        Si se reemplazo.

    Efectos:
        Disco: renombra `src` sobre `dst`.
    """
    import time

    sleep = sleep or time.sleep
    for n in range(attempts):
        try:
            os.replace(src, dst)
            return True
        except PermissionError:
            if n < attempts - 1:
                sleep(wait_s)
    return False


def main() -> None:
    """Valida el destino, fija `DATABASE_PATH` en ese archivo y corre la descarga.

    Con `--via-copy` (lo usa la tarea programada) trabaja sobre una copia `<archivo>_next.db` y al
    final la cambia por el archivo, para no escribir en el que la pestana puede estar leyendo.

    Efectos:
        Red: CoinGecko y Bitunix (publicas). Disco: crea la carpeta del archivo y escribe en ese
        archivo SQLite o en su copia (nunca en la base del bot). Cambia `DATABASE_PATH` solo en
        este proceso.
    """
    import shutil

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", default=os.environ.get("EXPLORER_HISTORY_DB", DEFAULT_PATH))
    parser.add_argument("--only-extra", action="store_true",
                        help="solo los marcos extra (15m y 1w), sin pasar por download_history")
    parser.add_argument("--via-copy", action="store_true",
                        help="actualiza una copia y la cambia por el archivo al final")
    args = parser.parse_args()
    from app.config import settings  # el DATABASE_PATH del bot, antes de cambiarlo

    final = check_target(args.path, settings.database_path)
    final.parent.mkdir(parents=True, exist_ok=True)
    target = final
    if args.via_copy:
        target = check_target(str(final.with_name(final.stem + "_next.db")),
                              settings.database_path)
        if final.is_file():
            shutil.copy2(final, target)
    os.environ["DATABASE_PATH"] = str(target)
    settings.database_path = str(target)
    assert Path(settings.database_path).resolve() == target
    print(f"Archivo de historial: {target}")

    from scripts import download_history

    if not args.only_extra:
        asyncio.run(download_history.main())
    asyncio.run(download_extra_timeframes())
    if args.via_copy:
        ok = replace_with_retries(target, final)
        print(f"Reemplazado {final}" if ok else f"No se pudo reemplazar {final} (abierto); "
              f"queda la copia {target} para la proxima corrida")


if __name__ == "__main__":
    main()
