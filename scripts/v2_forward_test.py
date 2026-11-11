"""Prueba hacia adelante (paper por repeticion) de las estrategias en estudio de la v2.

Las tres finalistas de `docs/v2/PREREGISTRO_V2_RONDA3.md` (congeladas el 2026-11-10) y la fuerza
relativa semanal de la ronda 4 (congelada el 2026-11-11), cada una con su control al azar. La
logica vive en `app.research.forward` (la misma que muestra la pestana «Estudio» del dashboard):
corre las estrategias con el motor de backtest sobre el archivo de historial local y cuenta solo
las operaciones ABIERTAS desde su fecha de congelamiento. Como el motor es determinista y causal,
eso equivale a haberlas operado en paper desde ese dia, sin dejar un proceso corriendo.

Criterio de lectura (`docs/v2/PAPER_V2_RONDA3.md`): cada estrategia se evalua una vez, al juntar
60 operaciones o el 2027-05-10; sigue en estudio solo con PF >= 1.2 y por encima de su control.

Solo lectura: abre el archivo de historial (`EXPLORER_HISTORY_DB`, por defecto
`./history/history_v2.db`) en modo inmutable; sin red. La tarea `MinervaV2HistoryUpdate`
(`scripts/register_v2_data_tasks.ps1`) lo actualiza cada 6 horas; a mano:

    python scripts/update_history_file.py
    python scripts/v2_forward_test.py [--path history/history_v2.db] [--trades]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.config import settings  # noqa: E402
from app.explorer.service import ReadOnlyDatabase  # noqa: E402
from app.research.forward import compute_forward  # noqa: E402


def _stats_line(name: str, stats: dict) -> str:
    """Linea de resumen de una estrategia o de su control.

    Args:
        name: nombre a mostrar.
        stats: `trades`, `pf`, `pnl_usdt` y `win_rate_pct`.

    Returns:
        La linea de texto.
    """
    pf = "-" if stats["pf"] is None else f"{stats['pf']:.2f}"
    rate = "-" if stats["win_rate_pct"] is None else f"{stats['win_rate_pct']:.0f}%"
    return (f"{name:<40} n={stats['trades']:>3}  PF {pf:>5}  PnL {stats['pnl_usdt']:+8.2f} USDT  "
            f"ganadoras {rate:>4}")


async def main() -> None:
    """Corre la prueba hacia adelante e imprime el estado de cada estrategia y de su control.

    Raises:
        SystemExit: si el archivo de historial no existe o no tiene las velas de BTC.

    Efectos:
        Solo lectura del archivo de historial. Sin red.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", default=settings.explorer_history_db)
    parser.add_argument("--trades", action="store_true", help="lista cada operacion")
    args = parser.parse_args()
    path = Path(args.path)
    if not path.exists():
        raise SystemExit(f"No existe {path}: corre antes scripts/update_history_file.py")
    db = ReadOnlyDatabase(path)
    await db.connect()
    try:
        out = await compute_forward(db, settings)
    finally:
        await db.close()
    if not out["available"]:
        raise SystemExit(out["detail"])
    print(f"Datos hasta {out['data_until'][:16].replace('T', ' ')} UTC")
    if out["stale_symbols"]:
        print(f"AVISO: simbolos con datos atrasados o ausentes: {out['stale_symbols']}")
    review = out["review"]
    print(f"Revision: al llegar a {review['trades']} operaciones o el {review['date']}\n")
    for s in out["strategies"]:
        print(f"[desde {s['start']}, {s['days']} dias] {s['label']}")
        print(_stats_line(s["name"], s["stats"]))
        print(_stats_line("  control al azar", s["control"]))
        print(f"    aun abiertas: {s['open_trades']}; revision: {s['review']['verdict']}")
        if args.trades:
            for t in s["trade_list"]:
                print(f"    {t['entry_time'][:16]} {t['symbol']:<9} {t['side']:<5} "
                      f"entrada {t['entry_price']:.6g} salida {t['exit_price']:.6g} "
                      f"{t['close_reason']:<11} {t['pnl_usdt']:+.2f}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
