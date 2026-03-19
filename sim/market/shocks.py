"""
Macro shock definitions for the market simulation.

Shocks represent exogenous events that alter market conditions at a
specific simulation week: interest rate changes, recessions, inventory
surges, and seasonal adjustments.

The ShockSchedule class provides pre-built scenarios for common cases.
Custom shocks can be constructed directly using MacroShock + ShockType.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ShockType(str, Enum):
    RATE_CHANGE = "rate_change"
    RECESSION = "recession"
    INVENTORY_SURGE = "inventory_surge"
    SEASONAL = "seasonal"
    POLICY = "policy"


@dataclass
class MacroShock:
    """
    A single macro event that modifies market conditions at a given week.

    params is type-specific:
    - RATE_CHANGE: {"new_rate": float}
    - RECESSION: {"income_impact": float, "affected_pct": float}
    - INVENTORY_SURGE: {"new_listings": int}
    - SEASONAL: {"demand_multiplier": float}
    - POLICY: {"description": str, ...}
    """
    week: int
    shock_type: ShockType
    params: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"MacroShock(week={self.week}, type={self.shock_type.value}, params={self.params})"


class ShockSchedule:
    """Pre-built shock schedules for common simulation scenarios."""

    @staticmethod
    def stable_market(contract_rate: float = 0.05) -> list[MacroShock]:
        """No shocks — stable conditions throughout."""
        return []

    @staticmethod
    def rate_hike_scenario(
        start_rate: float = 0.05,
        hike_bps: int = 25,
        hike_weeks: list[int] | None = None,
    ) -> list[MacroShock]:
        """
        Rate increases of hike_bps basis points at each specified week.

        Parameters
        ----------
        start_rate:
            Initial contract rate (ignored here — just for documentation).
        hike_bps:
            Basis points per hike (25 bps = 0.25%).
        hike_weeks:
            Simulation weeks at which hikes occur. Default: [8, 16].
        """
        if hike_weeks is None:
            hike_weeks = [8, 16]
        shocks = []
        current_rate = start_rate
        for week in hike_weeks:
            current_rate += hike_bps / 10_000
            shocks.append(
                MacroShock(
                    week=week,
                    shock_type=ShockType.RATE_CHANGE,
                    params={"new_rate": round(current_rate, 6)},
                )
            )
        return shocks

    @staticmethod
    def rate_cut_scenario(
        start_rate: float = 0.05,
        cut_bps: int = 25,
        cut_weeks: list[int] | None = None,
    ) -> list[MacroShock]:
        """Rate decreases at each specified week."""
        if cut_weeks is None:
            cut_weeks = [8, 16]
        shocks = []
        current_rate = start_rate
        for week in cut_weeks:
            current_rate = max(0.01, current_rate - cut_bps / 10_000)
            shocks.append(
                MacroShock(
                    week=week,
                    shock_type=ShockType.RATE_CHANGE,
                    params={"new_rate": round(current_rate, 6)},
                )
            )
        return shocks

    @staticmethod
    def recession_scenario(
        onset_week: int = 12,
        severity: float = 0.10,
        affected_pct: float = 0.15,
    ) -> list[MacroShock]:
        """
        Recession: income drops for a fraction of agents, some exit.

        Parameters
        ----------
        onset_week:
            Week the recession begins.
        severity:
            Income reduction for affected agents (0.10 = 10% income drop).
        affected_pct:
            Fraction of agents affected (0.15 = 15%).
        """
        return [
            MacroShock(
                week=onset_week,
                shock_type=ShockType.RECESSION,
                params={"income_impact": -severity, "affected_pct": affected_pct},
            )
        ]

    @staticmethod
    def inventory_surge_scenario(
        surge_week: int = 4,
        new_listings: int = 20,
    ) -> list[MacroShock]:
        """Additional properties flood the market at surge_week."""
        return [
            MacroShock(
                week=surge_week,
                shock_type=ShockType.INVENTORY_SURGE,
                params={"new_listings": new_listings},
            )
        ]

    @staticmethod
    def seasonal_scenario(weeks: int = 52) -> list[MacroShock]:
        """
        Seasonal demand multiplier applied each spring (weeks 10-22 in a year).

        Generates shocks for a full year of simulation.
        """
        shocks = []
        # Spring boost
        for week in range(10, 23):
            if week <= weeks:
                shocks.append(
                    MacroShock(
                        week=week,
                        shock_type=ShockType.SEASONAL,
                        params={"demand_multiplier": 1.20},
                    )
                )
        # Fall slowdown
        for week in range(36, 45):
            if week <= weeks:
                shocks.append(
                    MacroShock(
                        week=week,
                        shock_type=ShockType.SEASONAL,
                        params={"demand_multiplier": 0.85},
                    )
                )
        return shocks
