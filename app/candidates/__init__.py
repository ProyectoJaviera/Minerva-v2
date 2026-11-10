"""Candidatos de la v2 (`docs/v2/PREREGISTRO_V2.md`, congelado el 2026-11-10).

Viven fuera de `app/strategies/` a proposito: ese directorio es la zona protegida de las seis
estrategias de la v1. `CANDIDATES` y `CANDIDATE_TIMEFRAMES` no son `STRATEGIES`: ni el scheduler
ni `scripts/run_backtest.py` los leen. Solo los corre `scripts/run_backtest_v2.py`, la corrida
unica de la Fase 2 de la v2, con un veredicto por candidato y marco.
"""

from __future__ import annotations

from app.candidates.camarilla_s3_r3 import CamarillaS3R3Strategy
from app.candidates.range_filter_flip import RangeFilterFlipEma144Strategy
from app.candidates.sfp_reversal import ControlSfpRandomDirStrategy, SfpReversalStrategy
from app.strategies.base import BaseStrategy

CANDIDATES: dict[str, BaseStrategy] = {
    "sfp_reversal_5_1": SfpReversalStrategy(),
    "camarilla_s3_r3": CamarillaS3R3Strategy(),
    "range_filter_flip_ema144": RangeFilterFlipEma144Strategy(),
    "control_sfp_random_dir_seed42": ControlSfpRandomDirStrategy(),
}

# Cada candidato se prueba en 1h y 4h como combinaciones independientes.
CANDIDATE_TIMEFRAMES: dict[str, list[str]] = {name: ["1h", "4h"] for name in CANDIDATES}

# El control nunca se aprueba; si pasa los criterios, la ronda queda marcada como sospechosa.
CONTROL_STRATEGIES = {"control_sfp_random_dir_seed42"}
