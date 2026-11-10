"""Ronda 3 de la v2 (EXPLORATORIA): costos, salidas, FVG e informacion distinta al precio propio.

Pedido del dueno tras `docs/v2/EXPLORACION_V2.md` (0 de 176): bajar costos con ordenes limite,
buscar las mejores salidas (TP, SL y trailing), sumar el FVG y usar informacion que no sea el
precio de la propia moneda. Usa `app.research.round3`.

**Diseno, fijado ANTES de correr (este archivo se sube primero):**

- Marco: **solo 4h**. En las dos rondas anteriores 1h fue peor en todo y paga 4 veces mas costos.
- **23 senales** (`SIGNALS`): 4 heredadas de la exploracion, elegidas por su PF **IS** (nunca por
  el OOS): giro del Range Filter con VIDYA, con EMA+VIDYA y con EMA, y giro de VIDYA con EMA; y 19
  nuevas, nunca corridas, con el FVG y con los filtros de funding, regimen de BTC y fuerza relativa.
- Cada senal se corre con **6 salidas x 2 modos de entrada** (mercado y limite) = 12 variantes.
- **«Salidas optimas» sin trampa:** para cada senal se elige UNA variante, la de mayor PF **IS**
  entre las que tienen al menos 60 operaciones IS y 100 en total. Solo esa variante se juzga en el
  OOS (el 30 % final, que la eleccion no miro). Elegir la salida mirando el OOS garantizaria un
  buen backtest y un mal resultado en vivo.
- **Finalista** si su variante elegida: (1) pasa todos los criterios de la Fase 2; (2) tiene PF IS
  mayor que 1; (3) su PF OOS supera al del control al azar del mismo gatillo, salida y entrada; y
  (4) su PF OOS en BTC/ETH es mayor que 1. Como maximo 3 finalistas, por PF estresado.
- Son 23 juicios sobre el mismo OOS (ya usado en dos rondas): un finalista NO es una estrategia
  aprobada. El examen real son los datos desde el 2026-10-01 y el paper trading.

Sin red. Exige `DATABASE_PATH` (base temporal) y BORRA los resultados de backtest de esa base.

    DATABASE_PATH=<base> python scripts/v2_round3.py --out <archivo.json>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime

import pandas as pd

sys.path.insert(0, ".")

from app.backtesting.report import StrategyResult, run_full_backtest  # noqa: E402
from app.config import Settings, settings  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.market.ohlcv_history import get_cached_or_raise  # noqa: E402
from app.persistence.database import Database  # noqa: E402
from app.persistence.repositories import universe_repo  # noqa: E402
from app.research.round3 import ENTRY_MODES, EXITS, Round3Strategy, set_btc_context  # noqa: E402
from app.strategies.base import BaseStrategy  # noqa: E402

START_MS = int(datetime(2022, 1, 1, tzinfo=UTC).timestamp() * 1000)
TIMEFRAME = "4h"
MIN_IS_TRADES = 60
MIN_TOTAL_TRADES = 100
MAX_FINALISTS = 3

SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # heredadas, elegidas por PF IS en la exploracion
    ("rf_flip", ("vidya",)), ("rf_flip", ("ema", "vidya")), ("rf_flip", ("ema",)),
    ("vidya_flip", ("ema",)),
    # nuevas
    ("fvg", ()), ("fvg", ("ema",)), ("fvg", ("btc",)), ("fvg", ("rs",)), ("fvg", ("fund",)),
    ("fvg", ("btc", "rs")),
    ("rf_flip", ("btc",)), ("rf_flip", ("rs",)), ("rf_flip", ("btc", "vidya")),
    ("vidya_flip", ("btc",)), ("vidya_flip", ("rs",)),
    ("sfp", ("btc",)), ("sfp", ("rs",)), ("sfp", ("fund",)),
    ("zone_reject", ("btc",)), ("zone_reject", ("rs",)),
    ("grab", ("btc",)), ("wt_cross", ("btc",)), ("bb_reversal", ("btc",)),
)


def build_entries() -> tuple[dict[str, BaseStrategy], dict[str, list[str]]]:
    """Todas las variantes (senal x salida x entrada) y los controles al azar por gatillo.

    Returns:
        `(estrategias, timeframes)`; los nombres son los de `Round3Strategy`.
    """
    strategies: dict[str, BaseStrategy] = {}
    for exit_name in EXITS:
        for entry in ENTRY_MODES:
            for trigger, filters in SIGNALS:
                s = Round3Strategy(trigger, filters, exit_name=exit_name, entry_mode=entry)
                strategies[s.name] = s
            for trigger in sorted({t for t, _ in SIGNALS}):
                c = Round3Strategy(trigger, (), exit_name=exit_name, entry_mode=entry,
                                   random_dir=True)
                strategies[c.name] = c
    return strategies, {name: [TIMEFRAME] for name in strategies}


def _row(r: StrategyResult) -> dict:
    v = r.verdict
    return {
        "name": r.strategy_name, "trades": v.total_trades_all_segments, "is": r.is_trades,
        "oos": r.oos_trades, "pf_is": v.pf_is_aggregate, "pf_oos": v.pf_oos_aggregate,
        "pf_stressed": v.pf_stressed, "pf_btc_eth": v.pf_control_group,
        "pct_symbols": v.pct_symbols_pf_gt1, "pct_folds": v.pct_folds_positive,
        "dd_oos": v.max_drawdown_oos_pct, "concentration": v.concentration_pct,
        "passes_phase2": not v.discarded and not v.evidence_insufficient,
        "insufficient": v.evidence_insufficient,
        "reasons": json.loads(v.discard_reasons_json) if v.discard_reasons_json else [],
    }


def select(results: list[StrategyResult]) -> tuple[list[dict], list[dict], list[str]]:
    """Aplica la regla fija: una variante por senal elegida por PF IS, juzgada en el OOS.

    Args:
        results: resultados de `run_full_backtest`.

    Returns:
        `(todas_las_filas, una_fila_elegida_por_senal, finalistas)`.
    """
    rows = {r.strategy_name: _row(r) for r in results}
    chosen: list[dict] = []
    for trigger, filters in SIGNALS:
        prefix = f"r3|{trigger}|{'+'.join(sorted(filters)) or 'nada'}|"
        variants = [row for name, row in rows.items()
                    if name.startswith(prefix) and not name.endswith("|rnd")
                    and row["is"] >= MIN_IS_TRADES and row["trades"] >= MIN_TOTAL_TRADES
                    and row["pf_is"] is not None]
        if not variants:
            chosen.append({"signal": prefix.rstrip("|"), "chosen": None})
            continue
        best = max(variants, key=lambda row: row["pf_is"])
        parts = best["name"].split("|")
        control = rows.get("|".join(["r3", trigger, "nada", parts[3], parts[4], "rnd"]))
        pf_ctl = control["pf_oos"] if control else None
        beats = best["pf_oos"] is not None and (pf_ctl is None or best["pf_oos"] > pf_ctl)
        btc_eth_ok = best["pf_btc_eth"] is not None and best["pf_btc_eth"] > 1
        chosen.append({
            "signal": prefix.rstrip("|"), "chosen": best["name"], **best,
            "pf_random_control": pf_ctl, "is_ok": best["pf_is"] > 1, "beats_random": beats,
            "btc_eth_ok": btc_eth_ok,
            "finalist": bool(best["passes_phase2"] and best["pf_is"] > 1 and beats and btc_eth_ok),
        })
    finalists = sorted((c for c in chosen if c.get("finalist")),
                       key=lambda c: c["pf_stressed"] or 0, reverse=True)[:MAX_FINALISTS]
    return list(rows.values()), chosen, [c["chosen"] for c in finalists]


async def main() -> None:
    """Corre la ronda 3, imprime la variante elegida de cada senal y guarda todo en JSON.

    Raises:
        SystemExit: si `DATABASE_PATH` no apunta a una base temporal.
        RuntimeError: si la base no tiene universo cacheado.

    Efectos:
        Lee y escribe la base de `DATABASE_PATH` (borra resultados de backtest anteriores);
        escribe el JSON de `--out`. Sin red.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="archivo JSON con todas las filas")
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
        end_ms = settings.backtest_official_end_ms
        btc = await get_cached_or_raise(db, "BTCUSDT", TIMEFRAME, START_MS, end_ms)
        set_btc_context(TIMEFRAME, pd.DataFrame(
            {"open_time": [b.open_time for b in btc], "close": [b.close for b in btc]}))
        strategies, timeframes = build_entries()
        print(f"{len(strategies)} variantes en {TIMEFRAME}; universo {symbols}")
        results = await run_full_backtest(
            db, settings, symbols, START_MS, end_ms,
            strategies=strategies, timeframes_by_strategy=timeframes, experimental=set(),
        )
        rows, chosen, finalists = select(results)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"generated": datetime.now(tz=UTC).isoformat(), "symbols": symbols,
                       "rows": rows, "chosen": chosen, "finalists": finalists}, fh, indent=1)
        print("\nVariante elegida por PF IS de cada senal (P pasa Fase 2, I PF IS>1, "
              "A supera al azar, C BTC/ETH>1):")
        for c in chosen:
            if c["chosen"] is None:
                print(f"  {c['signal']:<28} sin variante con operaciones suficientes")
                continue
            flags = "".join(k if c[f] else "-" for k, f in
                            (("P", "passes_phase2"), ("I", "is_ok"), ("A", "beats_random"),
                             ("C", "btc_eth_ok")))
            print(f"  {c['chosen']:<46} IS {c['pf_is']:5.2f} OOS {c['pf_oos'] or 0:5.2f} "
                  f"estr {c['pf_stressed'] or 0:5.2f} n={c['trades']:>4} {flags}")
        print(f"\nFinalistas: {finalists or 'ninguna'}")
        print(f"Tiempo total: {time.time() - t0:.1f}s")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
