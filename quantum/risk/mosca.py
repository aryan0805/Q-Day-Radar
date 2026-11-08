"""Mosca margin and shortfall ranking, exactly as fixed in the Phase 4 brief.

z = crqc_year - as_of_year; margin = z - (x + y); shortfall = exposure_weight * max(0, -margin);
rank by (-shortfall, margin with None = +inf, asset id); rank 1 is most urgent. margin is None when
the asset has no attack target or crqc_year is None.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def margin(crqc_year: float | None, as_of_year: int, shelf_life: float, migration: float):
    if crqc_year is None:
        return None
    return (crqc_year - as_of_year) - (shelf_life + migration)


def shortfall(weight: float, margin_years: float | None) -> float:
    return 0.0 if margin_years is None else weight * max(0.0, -margin_years)


@dataclass(frozen=True)
class Scored:
    asset_id: str
    margin_years: float | None
    shortfall: float


def rank(scored: list[Scored]) -> dict[str, int]:
    order = sorted(
        scored,
        key=lambda s: (
            -s.shortfall,
            math.inf if s.margin_years is None else s.margin_years,
            s.asset_id,
        ),
    )
    return {s.asset_id: i + 1 for i, s in enumerate(order)}
