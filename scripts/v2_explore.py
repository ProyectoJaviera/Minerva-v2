"""Exploracion de la v2: todas las herramientas de los indicadores y sus combinaciones.

Corre las combinaciones de `app.research.combos.all_combinations()` (8 gatillos x 11 variantes de
filtros + 8 controles con direccion al azar) en 1h y 4h, con el mismo motor, universo, costos,
fecha final (2026-10-01) y criterios de la Fase 2, sobre una base temporal llenada con
`scripts/download_history.py`. Por pedido del dueno usa todo el historial desde 2022.

**Esto no es un preregistro.** Con ~190 combinaciones probadas sobre los mismos datos, alguna
puede pasar los criterios por azar. La regla para elegir finalistas se fija aqui, ANTES de correr:

1. pasa todos los criterios de la Fase 2 (sin evidencia insuficiente);
2. su PF OOS supera el PF OOS del control al azar de su mismo gatillo y marco;
3. el PF OOS del grupo de control BTC/ETH es mayor que 1;
4. de las que cumplen 1 a 3, como maximo 4 finalistas, por PF estresado (2x fees y slippage).

Los finalistas pasan a un preregistro nuevo y a una validacion hacia adelante en paper (datos que
nadie vio). Si ninguna cumple, la conclusion es que estas herramientas no muestran ventaja.

Sin red. Exige `DATABASE_PATH` (base temporal) y BORRA los resultados de backtest de esa base.

    DATABASE_PATH=<base> python scripts/v2_explore.py --out <archivo.json>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime

sys.path.insert(0, ".")

from app.backtesting.report import StrategyResult, run_full_backtest  # noqa: E402
from app.config import Settings, settings  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.persistence.database import Database  # noqa: E402
from app.persistence.repositories import universe_repo  # noqa: E402
from app.research.combos import ComboStrategy, all_combinations  # noqa: E402
from app.strategies.base import BaseStrategy  # noqa: E402

START_MS = int(datetime(2022, 1, 1, tzinfo=UTC).timestamp() * 1000)
TIMEFRAMES = ("1h", "4h")
MAX_FINALISTS = 4


def build_entries(combos: list[ComboStrategy]) -> tuple[dict[str, BaseStrategy],
                                                        dict[str, list[str]]]:
    """Una entrada por combinacion y marco, con su propio veredicto.

    Args:
        combos: combinaciones a explorar.

    Returns:
        `(estrategias, timeframes)` con nombres `<combinacion>|<marco>`.
    """
    strategies: dict[str, BaseStrategy] = {}
    timeframes: dict[str, list[str]] = {}
    for combo in combos:
        for tf in TIMEFRAMES:
            key = f"{combo.name}|{tf}"
            strategies[key] = combo
            timeframes[key] = [tf]
    return strategies, timeframes


def control_key(name: str) -> str:
    """Nombre del control al azar del mismo gatillo y marco que `name`.

    Args:
        name: `combo|<gatillo>|<filtros>|<salida>|<marco>`.

    Returns:
        `combo|<gatillo>|nada|<salida>|rnd|<marco>`.
    """
    parts = name.split("|")
    return "|".join([parts[0], parts[1], "nada", parts[3], "rnd", parts[-1]])


def summarize(results: list[StrategyResult]) -> tuple[list[dict], list[str]]:
    """Tabla de todas las combinaciones y finalistas segun la regla fija del docstring.

    Args:
        results: resultados de `run_full_backtest`.

    Returns:
        `(filas, finalistas)`; cada fila trae las metricas y si cumple cada paso de la regla.
    """
    by_name = {r.strategy_name: r for r in results}
    rows: list[dict] = []
    for r in results:
        v = r.verdict
        is_control = "|rnd|" in r.strategy_name
        ctl = by_name.get(control_key(r.strategy_name))
        pf_ctl = ctl.verdict.pf_oos_aggregate if ctl else None
        passes = not v.discarded and not v.evidence_insufficient
        beats = (v.pf_oos_aggregate is not None
                 and (pf_ctl is None or v.pf_oos_aggregate > pf_ctl))
        control_group_ok = v.pf_control_group is not None and v.pf_control_group > 1
        rows.append({
            "name": r.strategy_name, "control": is_control,
            "trades": v.total_trades_all_segments, "is": r.is_trades, "oos": r.oos_trades,
            "pf_is": v.pf_is_aggregate, "pf_oos": v.pf_oos_aggregate,
            "pf_stressed": v.pf_stressed, "pf_btc_eth": v.pf_control_group,
            "pct_symbols": v.pct_symbols_pf_gt1, "pct_folds": v.pct_folds_positive,
            "dd_oos": v.max_drawdown_oos_pct, "concentration": v.concentration_pct,
            "pf_random_control": pf_ctl, "passes_phase2": passes,
            "beats_random": beats, "btc_eth_ok": control_group_ok,
            "insufficient": v.evidence_insufficient,
            "reasons": json.loads(v.discard_reasons_json) if v.discard_reasons_json else [],
        })
    eligible = [row for row in rows if not row["control"] and row["passes_phase2"]
                and row["beats_random"] and row["btc_eth_ok"]]
    eligible.sort(key=lambda row: row["pf_stressed"] or 0, reverse=True)
    return rows, [row["name"] for row in eligible[:MAX_FINALISTS]]


async def main() -> None:
    """Corre la exploracion, imprime el ranking y guarda la tabla completa en JSON.

    Raises:
        SystemExit: si `DATABASE_PATH` no apunta a una base temporal.
        RuntimeError: si la base no tiene universo cacheado.

    Efectos:
        Lee y escribe la base de `DATABASE_PATH` (borra resultados de backtest anteriores);
        escribe el JSON de `--out`. Sin red.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="archivo JSON con la tabla completa")
    args = parser.parse_args()
    default_db = Settings.model_fields["database_path"].default
    if not os.environ.get("DATABASE_PATH") or settings.database_path == default_db:
        raise SystemExit("Define DATABASE_PATH con una base temporal (no la de por defecto).")

    setup_logging()
    t0 = time.time()
    db = Database(settings.database_path)
    await db.connect()
    try:
        symbols = await universe_repo.get_included_symbols(db)
        if not symbols:
            raise RuntimeError("Sin universo cacheado: corre antes scripts/download_history.py")
        combos = all_combinations()
        strategies, timeframes = build_entries(combos)
        print(f"{len(strategies)} entradas ({len(combos)} combinaciones x {len(TIMEFRAMES)} "
              f"marcos); universo {symbols}")
        results = await run_full_backtest(
            db, settings, symbols, START_MS, settings.backtest_official_end_ms,
            strategies=strategies, timeframes_by_strategy=timeframes, experimental=set(),
        )
        rows, finalists = summarize(results)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"generated": datetime.now(tz=UTC).isoformat(), "symbols": symbols,
                       "rows": rows, "finalists": finalists}, fh, indent=1)
        rows.sort(key=lambda row: row["pf_oos"] or 0, reverse=True)
        print("\nTop 25 por PF OOS (pasa | supera al azar | BTC/ETH>1):")
        for row in rows[:25]:
            print(f"  {row['name']:<45} PF IS {row['pf_is'] or 0:5.2f} "
                  f"OOS {row['pf_oos'] or 0:5.2f}"
                  f" estr {row['pf_stressed'] or 0:5.2f} n={row['trades']:>5} folds "
                  f"{row['pct_folds'] or 0:4.0f}% {'P' if row['passes_phase2'] else '-'}"
                  f"{'A' if row['beats_random'] else '-'}{'C' if row['btc_eth_ok'] else '-'}")
        print(f"\nPasan los criterios de la Fase 2: "
              f"{sum(row['passes_phase2'] for row in rows if not row['control'])} de "
              f"{sum(not row['control'] for row in rows)}")
        print(f"Finalistas: {finalists or 'ninguna'}")
        print(f"Tiempo total: {time.time() - t0:.1f}s")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
