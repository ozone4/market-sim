"""
Predefined macro-economic scenario presets.

Each Scenario bundles a set of SimulationConfig overrides with a shock schedule,
allowing callers to run well-known market conditions without hand-tuning configs.

Usage::

    from sim.scenarios.presets import SCENARIOS
    scenario = SCENARIOS["rate_cut_cycle"]
    config = apply_scenario(scenario, base_config)
    result = run_simulation(properties, config)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sim.market.shocks import MacroShock, ShockType


@dataclass
class Scenario:
    """A named macro-economic scenario with config overrides and a shock schedule."""

    name: str
    description: str
    config_overrides: dict[str, Any]          # Override SimulationConfig fields
    shocks: list[MacroShock] = field(default_factory=list)


# ─── Preset scenarios ─────────────────────────────────────────────────────────

SCENARIOS: dict[str, Scenario] = {
    "baseline_2024": Scenario(
        name="Baseline 2024",
        description="Current conditions: 5.0% rate, balanced market",
        config_overrides={"contract_rate": 0.05, "num_weeks": 26},
        shocks=[],
    ),

    "rate_cut_cycle": Scenario(
        name="Rate Cut Cycle",
        description="BoC easing: 3 cuts of 25bp at weeks 4, 12, 20",
        config_overrides={"contract_rate": 0.05},
        shocks=[
            # Cumulative from base 5.0%: 4.75% → 4.50% → 4.25%
            MacroShock(
                week=4,
                shock_type=ShockType.RATE_CHANGE,
                params={"new_rate": 0.0475},
            ),
            MacroShock(
                week=12,
                shock_type=ShockType.RATE_CHANGE,
                params={"new_rate": 0.045},
            ),
            MacroShock(
                week=20,
                shock_type=ShockType.RATE_CHANGE,
                params={"new_rate": 0.0425},
            ),
        ],
    ),

    "rate_hike_stress": Scenario(
        name="Rate Hike Stress Test",
        description="Emergency hikes: +100bp at week 4, +50bp at week 12",
        config_overrides={"contract_rate": 0.05},
        shocks=[
            # 5.0% → 6.0% → 6.5%
            MacroShock(
                week=4,
                shock_type=ShockType.RATE_CHANGE,
                params={"new_rate": 0.06},
            ),
            MacroShock(
                week=12,
                shock_type=ShockType.RATE_CHANGE,
                params={"new_rate": 0.065},
            ),
        ],
    ),

    "recession": Scenario(
        name="Recession Scenario",
        description="Economic downturn: recession shock + rate cut response",
        config_overrides={"contract_rate": 0.05, "num_weeks": 52},
        shocks=[
            # Onset: income drop for 20% of active agents
            MacroShock(
                week=8,
                shock_type=ShockType.RECESSION,
                params={"income_impact": -0.15, "affected_pct": 0.20},
            ),
            # Policy response: rate cuts
            MacroShock(
                week=16,
                shock_type=ShockType.RATE_CHANGE,
                params={"new_rate": 0.045},
            ),
            MacroShock(
                week=24,
                shock_type=ShockType.RATE_CHANGE,
                params={"new_rate": 0.04},
            ),
        ],
    ),

    "inventory_surge": Scenario(
        name="Inventory Surge",
        description="Sudden listing wave: high replenishment from week 0, surge shock at week 6",
        config_overrides={"replenishment_rate": 0.08},
        shocks=[
            MacroShock(
                week=6,
                shock_type=ShockType.INVENTORY_SURGE,
                params={"new_listings": 15},
            ),
        ],
    ),

    "hot_market": Scenario(
        name="Hot Market",
        description="Low rates + tight supply: bidding wars expected",
        config_overrides={
            "contract_rate": 0.035,
            "num_agents": 800,
            "replenishment_rate": 0.02,
        },
        shocks=[],
    ),
}


# ─── Helper ───────────────────────────────────────────────────────────────────

def apply_scenario(scenario: Scenario, base_config: Any) -> Any:
    """
    Return a copy of base_config with scenario overrides and shocks applied.

    Parameters
    ----------
    scenario:
        The Scenario to apply.
    base_config:
        A SimulationConfig instance (or any dataclass with matching fields).

    Returns
    -------
    A new SimulationConfig with overrides and shocks from the scenario.
    """
    from dataclasses import replace
    overrides = dict(scenario.config_overrides)
    overrides["shocks"] = list(scenario.shocks)
    return replace(base_config, **overrides)
