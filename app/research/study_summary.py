"""Resumen fijo de las rondas de investigacion de la v2, para la pestana «Estudio» del dashboard.

Son los resultados ya publicados en `docs/v2/` (no se recalculan): quien lee el dashboard desde
fuera del servidor ve lo mismo que dicen los informes.
"""

from __future__ import annotations

ROUNDS: tuple[dict, ...] = (
    {
        "id": "fase2", "date": "2026-11-10", "title": "Fase 2 preregistrada",
        "doc": "docs/v2/RESULTADO_FASE2_V2.md",
        "tested": "SFP, Camarilla y Range Filter + EMA 144 en 1h y 4h, más un control al azar",
        "result": "Los 3 candidatos descartados en los dos marcos. El mejor, Range Filter en 4h, "
                  "con PF fuera de muestra 1.06.",
        "passed": 0, "total": 6,
    },
    {
        "id": "exploracion", "date": "2026-11-10", "title": "Exploración de combinaciones",
        "doc": "docs/v2/EXPLORACION_V2.md",
        "tested": "8 herramientas de HeatMap y Frost como gatillo, con 0, 1 o 2 filtros, "
                  "en 1h y 4h",
        "result": "Ninguna combinación pasa. La más cercana, SFP + EMA + Range Filter en 4h "
                  "(PF 1.27), falla por concentración y pierde en la primera parte del historial.",
        "passed": 0, "total": 176,
    },
    {
        "id": "ronda3", "date": "2026-11-10", "title": "Ronda 3: salidas, costos, FVG y BTC",
        "doc": "docs/v2/RONDA3_V2.md",
        "tested": "23 señales en 4h con 6 salidas, orden límite, FVG, funding, régimen de BTC y "
                  "fuerza relativa; la salida se eligió solo con la primera parte del historial",
        "result": "4 señales pasan y salen 3 finalistas, pero las tres pierden en los datos "
                  "reservados (1-oct a 10-nov): PF 0.31, 0.52 y 0.62.",
        "passed": 4, "total": 23,
    },
    {
        "id": "ronda4", "date": "2026-11-11",
        "title": "Ronda 4: fuerza relativa, squeeze y volumen",
        "doc": "docs/v2/RONDA4_V2.md",
        "tested": "21 señales en 4h: fuerza relativa semanal entre monedas, squeeze TTM con ADX y "
                  "el volumen (pico y VWAP semanal) como filtro",
        "result": "Ninguna pasa. La fuerza relativa semanal es la más cercana (PF 1.11 y 1.25 en "
                  "las dos partes del historial) y falla por concentración.",
        "passed": 0, "total": 21,
    },
)

CONCLUSION = (
    "Después de 6 estrategias en la v1 y unas 400 señales en la v2, ninguna regla basada en estos "
    "indicadores muestra ventaja fuera de la muestra. Cuatro estrategias siguen en prueba hacia "
    "adelante, sin expectativas, para juntar datos nuevos. Nada de esto habilita dinero real."
)
