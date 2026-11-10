"""Corrida unica de la Fase 2 de la v2: los candidatos del preregistro congelado.

Corre `sfp_reversal_5_1`, `camarilla_s3_r3`, `range_filter_flip_ema144` y el control
`control_sfp_random_dir_seed42` (`app/candidates/`) en 1h y 4h, cada marco como una combinacion
independiente con su propio veredicto (seccion 2 de `docs/v2/PREREGISTRO_V2.md`), con el mismo
motor, el mismo universo, la misma fecha final (`BACKTEST_OFFICIAL_END_DATE`) y los mismos
criterios de la Fase 2. Despues aplica las dos reglas propias del preregistro:

- el SFP se aprueba en un marco solo si, ademas de los criterios, su PF OOS agregado supera el
  del control en el mismo marco;
- el control nunca se aprueba; si pasa todos los criterios, la ronda queda **sospechosa** y no
  se aprueba ningun candidato hasta explicarlo.

Imprime, por combinacion, las entradas omitidas por cada motivo (tope de riesgo, tabla
`backtest_skipped_entries`; SL cruzado, contadas desde el log del motor) junto a las operaciones.

Como `scripts/run_backtest.py`, no toca la red: lee universo, specs, velas y funding de SQLite y
BORRA los resultados de corridas anteriores de esa base. Exige `DATABASE_PATH` apuntando a una
base que no sea la de por defecto (la base de la v2 nunca se usa para esto).

    DATABASE_PATH=<base temporal> python scripts/download_history.py
    DATABASE_PATH=<base temporal> python scripts/run_backtest_v2.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

sys.path.insert(0, ".")

from app.backtesting.report import StrategyResult, run_full_backtest  # noqa: E402
from app.candidates import CANDIDATE_TIMEFRAMES, CANDIDATES, CONTROL_STRATEGIES  # noqa: E402
from app.config import Settings, settings  # noqa: E402
from app.core.logging import get_logger, setup_logging  # noqa: E402
from app.market.ohlcv_history import check_series_availability  # noqa: E402
from app.persistence.database import Database  # noqa: E402
from app.persistence.repositories import universe_repo  # noqa: E402
from app.strategies.base import BaseStrategy  # noqa: E402

logger = get_logger("run_backtest_v2")

START_MS = int(datetime(2022, 1, 1, tzinfo=UTC).timestamp() * 1000)
SFP = "sfp_reversal_5_1"
CONTROL = "control_sfp_random_dir_seed42"
ENGINE_LOGGER = "app.backtesting.engine"


def combo_name(candidate: str, timeframe: str) -> str:
    """Nombre de la combinacion candidato x marco, p. ej. `sfp_reversal_5_1_1h`.

    Args:
        candidate: nombre del candidato.
        timeframe: marco (`1h` o `4h`).

    Returns:
        El nombre de la combinacion.
    """
    return f"{candidate}_{timeframe}"


def build_combinations() -> tuple[dict[str, BaseStrategy], dict[str, list[str]], set[str]]:
    """Una entrada por candidato y marco, para que cada una tenga su propio veredicto.

    Returns:
        `(estrategias, timeframes, controles)` con los nombres de combinacion.
    """
    strategies: dict[str, BaseStrategy] = {}
    timeframes: dict[str, list[str]] = {}
    controls: set[str] = set()
    for name, strategy in CANDIDATES.items():
        for tf in CANDIDATE_TIMEFRAMES[name]:
            key = combo_name(name, tf)
            strategies[key] = strategy
            timeframes[key] = [tf]
            if name in CONTROL_STRATEGIES:
                controls.add(key)
    return strategies, timeframes, controls


class CrossedSlCounter(logging.Handler):
    """Cuenta las entradas omitidas por SL cruzado que el motor anota en su log."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.counts: Counter[str] = Counter()

    def emit(self, record: logging.LogRecord) -> None:
        """Suma la cuenta de la linea de omision por SL cruzado, si lo es.

        Args:
            record: registro de log del motor.
        """
        if "open ya habia cruzado el SL" in str(record.msg) and record.args:
            name, _symbol, _tf, count = record.args
            self.counts[str(name)] += int(count)


@dataclass
class ComboOutcome:
    """Veredicto final de una combinacion tras las reglas propias del preregistro."""

    name: str
    status: str
    reasons: list[str]


def passes_phase2(result: StrategyResult) -> bool:
    """Si la combinacion paso todos los criterios de la Fase 2 (sin evidencia insuficiente).

    Args:
        result: resultado de la combinacion.

    Returns:
        True si no fue descartada ni quedo con evidencia insuficiente.
    """
    v = result.verdict
    return not v.discarded and not v.evidence_insufficient


def apply_preregistration_rules(results: list[StrategyResult]) -> tuple[list[ComboOutcome], bool]:
    """Aplica el criterio adicional del SFP y la regla de ronda sospechosa del control.

    Args:
        results: un `StrategyResult` por combinacion (nombres de `combo_name`).

    Returns:
        `(desenlaces, ronda_sospechosa)`.
    """
    by_name = {r.strategy_name: r for r in results}
    suspicious = any(
        passes_phase2(r) for r in results if r.strategy_name.startswith(CONTROL)
    )
    outcomes: list[ComboOutcome] = []
    for r in results:
        v = r.verdict
        reasons: list[str] = []
        if r.strategy_name.startswith(CONTROL):
            status = "CONTROL (nunca se aprueba)"
            if passes_phase2(r):
                reasons.append("el control paso todos los criterios: ronda sospechosa")
        elif v.evidence_insufficient:
            status = "EVIDENCIA INSUFICIENTE"
        elif v.discarded:
            status = "DESCARTADO"
        else:
            status = "APROBADO"
            if r.strategy_name.startswith(SFP):
                tf = r.strategy_name.rsplit("_", 1)[1]
                control = by_name.get(combo_name(CONTROL, tf))
                pf_sfp = v.pf_oos_aggregate
                pf_ctl = control.verdict.pf_oos_aggregate if control else None
                if pf_sfp is None or (pf_ctl is not None and pf_sfp <= pf_ctl):
                    status = "DESCARTADO"
                    reasons.append(f"PF OOS {pf_sfp} no supera al del control ({pf_ctl})")
            if status == "APROBADO" and suspicious:
                status = "EN SUSPENSO (ronda sospechosa)"
        outcomes.append(ComboOutcome(r.strategy_name, status, reasons))
    return outcomes, suspicious


async def find_missing_series(db: Database, symbols: list[str], cfg: Settings) -> list[str]:
    """Series (simbolo x marco x tipo de precio) que faltan para la corrida, antes de calcular.

    Args:
        db: base con el historial.
        symbols: simbolos del universo (se suman los de control).
        cfg: configuracion (fecha final y simbolos de control).

    Returns:
        La descripcion de cada serie que falta (vacia si estan todas).
    """
    all_symbols = sorted(set(symbols) | set(cfg.backtest_control_symbols_list))
    timeframes = sorted({tf for tfs in CANDIDATE_TIMEFRAMES.values() for tf in tfs})
    problems: list[str] = []
    for symbol in all_symbols:
        for tf in timeframes:
            for price_type in ("LAST_PRICE", "MARK_PRICE"):
                problem = await check_series_availability(
                    db, symbol, tf, START_MS, cfg.backtest_official_end_ms, price_type
                )
                if problem is not None:
                    problems.append(problem)
    return problems


async def main() -> None:
    """Corre la Fase 2 de la v2 e imprime el resumen.

    Raises:
        SystemExit: si `DATABASE_PATH` no apunta a una base temporal.
        RuntimeError: si la base no tiene universo cacheado.

    Efectos:
        Lee y escribe la base de `DATABASE_PATH` (borra corridas anteriores del backtest y
        escribe `backtest_trades`, `backtest_skipped_entries`, `backtest_runs` y
        `backtest_verdicts`). Sin red. Configura el logging (archivo en `LOG_DIR`).
    """
    default_db = Settings.model_fields["database_path"].default
    if not os.environ.get("DATABASE_PATH") or settings.database_path == default_db:
        raise SystemExit("Define DATABASE_PATH con una base temporal (no la de por defecto).")

    setup_logging()
    counter = CrossedSlCounter()
    logging.getLogger(ENGINE_LOGGER).addHandler(counter)
    t0 = time.time()
    db = Database(settings.database_path)
    await db.connect()
    try:
        symbols = await universe_repo.get_included_symbols(db)
        if not symbols:
            raise RuntimeError("Sin universo cacheado: corre antes scripts/download_history.py")
        end_ms = settings.backtest_official_end_ms
        print(f"Universo: {symbols} + control {settings.backtest_control_symbols_list}")
        print(f"Periodo: {datetime.fromtimestamp(START_MS / 1000, tz=UTC).date()} a "
              f"{datetime.fromtimestamp(end_ms / 1000, tz=UTC).date()}")

        missing = await find_missing_series(db, symbols, settings)
        if missing:
            print(f"Faltan {len(missing)} serie(s):")
            for problem in missing:
                print(f"  - {problem}")
            return

        strategies, timeframes, controls = build_combinations()
        results = await run_full_backtest(
            db, settings, symbols, START_MS, end_ms,
            strategies=strategies, timeframes_by_strategy=timeframes, experimental=set(),
        )
        risk_rows = await db.fetch_all(
            "SELECT strategy, COUNT(*) AS n FROM backtest_skipped_entries GROUP BY strategy"
        )
        risk_skips = {row["strategy"]: row["n"] for row in risk_rows}
        outcomes, suspicious = apply_preregistration_rules(results)

        print("\n=== FASE 2 v2: VEREDICTO POR COMBINACION ===\n")
        for r, outcome in zip(results, outcomes, strict=True):
            v = r.verdict
            print(f"--- {r.strategy_name}: {outcome.status} ---")
            print(f"  operaciones: {v.total_trades_all_segments} (IS {r.is_trades} / "
                  f"OOS {r.oos_trades})")
            print(f"  omitidas: tope de riesgo {risk_skips.get(r.strategy_name, 0)}, "
                  f"SL cruzado {counter.counts.get(r.strategy_name, 0)}")
            print(f"  PF IS {v.pf_is_aggregate} -> PF OOS {v.pf_oos_aggregate}; "
                  f"PF estresado {v.pf_stressed}; PF funding real {v.pf_real_funding_only}")
            print(f"  % simbolos PF>1 {v.pct_symbols_pf_gt1}; % folds positivos "
                  f"{v.pct_folds_positive}; DD OOS {v.max_drawdown_oos_pct}; "
                  f"concentracion {v.concentration_pct}; PF control BTC/ETH {v.pf_control_group}")
            if v.discard_reasons_json:
                print(f"  motivos de descarte: {v.discard_reasons_json}")
            for reason in outcome.reasons:
                print(f"  regla del preregistro: {reason}")
            print()
        print(f"Ronda sospechosa: {'SI' if suspicious else 'no'}")
        print(f"Combinaciones evaluadas: {len(results) - len(controls)} candidatos + "
              f"{len(controls)} de control")
        print(f"Tiempo total: {time.time() - t0:.1f}s")
    finally:
        logging.getLogger(ENGINE_LOGGER).removeHandler(counter)
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
