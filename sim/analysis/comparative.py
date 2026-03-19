"""
Comparative analysis — run two or more scenarios on the same properties and diff results.

run_comparative_analysis() runs each named scenario through a full simulation
and produces side-by-side gap signals for every property and neighbourhood.

All amounts in CAD.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sim.analysis.assessment_gap import analyze_all_gaps
from sim.analysis.neighbourhood import summarize_all_neighbourhoods
from sim.analysis.report import DISCLAIMER
from sim.engine.simulation import SimulationConfig, run_simulation
from sim.properties.models import Property
from sim.scenarios.presets import SCENARIOS, apply_scenario


@dataclass
class PropertyComparison:
    """Per-property comparison across multiple scenarios."""

    folio_id: str
    assessed_value: float
    scenarios: dict[str, float]           # scenario_name → clearing_price (0.0 if unsold)
    gap_signals: dict[str, str]           # scenario_name → gap_signal
    pressure_scores: dict[str, float]     # scenario_name → market_pressure_score
    most_sensitive_scenario: str          # Scenario where gap_pct changed most vs baseline
    sensitivity_range_pct: float          # Max gap_pct - min gap_pct across scenarios


@dataclass
class ComparativeReport:
    """Full comparative analysis across multiple scenarios."""

    scenarios_run: list[str]
    property_comparisons: list[PropertyComparison]
    # neighbourhood → {scenario_name → systemic_signal}
    neighbourhood_comparison: dict[str, dict[str, str]]
    disclaimer: str = field(default=DISCLAIMER)


# ─── Public API ───────────────────────────────────────────────────────────────

def run_comparative_analysis(
    properties: list[Property],
    scenario_names: list[str],
    base_config: Optional[SimulationConfig] = None,
) -> ComparativeReport:
    """
    Run multiple scenarios on the same property set and compare results.

    Parameters
    ----------
    properties:
        Properties to simulate against all scenarios.
    scenario_names:
        Keys into SCENARIOS (e.g. ["baseline_2024", "rate_cut_cycle"]).
    base_config:
        Starting SimulationConfig; scenario overrides are applied on top.
        Defaults to SimulationConfig() if not provided.

    Returns
    -------
    ComparativeReport with per-property and per-neighbourhood comparisons.
    """
    if base_config is None:
        base_config = SimulationConfig()

    unknown = [n for n in scenario_names if n not in SCENARIOS]
    if unknown:
        raise ValueError(f"Unknown scenario(s): {unknown!r}. "
                         f"Available: {sorted(SCENARIOS)}")

    # ── Run each scenario ──────────────────────────────────────────────────────
    # scenario_name → list[AssessmentGapResult]
    scenario_gaps: dict[str, list] = {}
    # scenario_name → list[NeighbourhoodSummary]
    scenario_nbhd: dict[str, list] = {}

    for name in scenario_names:
        scenario = SCENARIOS[name]
        config = apply_scenario(scenario, base_config)
        result = run_simulation(properties, config)
        gaps = analyze_all_gaps(result, properties)
        nbhd = summarize_all_neighbourhoods(gaps, properties)
        scenario_gaps[name] = gaps
        scenario_nbhd[name] = nbhd

    # ── Build property comparisons ─────────────────────────────────────────────
    # Index gap results per scenario by folio_id for easy lookup
    gap_index: dict[str, dict[str, object]] = {}
    for name, gaps in scenario_gaps.items():
        gap_index[name] = {g.folio_id: g for g in gaps}

    property_comparisons: list[PropertyComparison] = []

    for prop in properties:
        fid = prop.folio_id
        clearing: dict[str, float] = {}
        signals: dict[str, str] = {}
        pressures: dict[str, float] = {}
        gap_pcts: dict[str, float] = {}

        for name in scenario_names:
            g = gap_index[name].get(fid)
            if g is None:
                clearing[name] = 0.0
                signals[name] = "data_insufficient"
                pressures[name] = 0.0
                gap_pcts[name] = 0.0
            else:
                clearing[name] = g.simulated_clearing_price  # type: ignore[union-attr]
                signals[name] = g.gap_signal  # type: ignore[union-attr]
                pressures[name] = g.market_pressure_score  # type: ignore[union-attr]
                gap_pcts[name] = g.gap_pct  # type: ignore[union-attr]

        # Sensitivity: range of gap_pct across scenarios
        pct_values = list(gap_pcts.values())
        sensitivity_range = max(pct_values) - min(pct_values) if pct_values else 0.0

        # Most sensitive: scenario furthest from first scenario's gap_pct
        if len(scenario_names) > 1:
            baseline_pct = gap_pcts.get(scenario_names[0], 0.0)
            most_sensitive = max(
                scenario_names[1:],
                key=lambda n: abs(gap_pcts.get(n, 0.0) - baseline_pct),
            )
        else:
            most_sensitive = scenario_names[0]

        property_comparisons.append(
            PropertyComparison(
                folio_id=fid,
                assessed_value=prop.assessed_value,
                scenarios=clearing,
                gap_signals=signals,
                pressure_scores=pressures,
                most_sensitive_scenario=most_sensitive,
                sensitivity_range_pct=round(sensitivity_range, 2),
            )
        )

    # ── Build neighbourhood comparison ─────────────────────────────────────────
    # Collect all neighbourhood names across all scenarios
    all_nbhd_names: set[str] = set()
    for summaries in scenario_nbhd.values():
        for s in summaries:
            all_nbhd_names.add(s.neighbourhood)

    nbhd_comparison: dict[str, dict[str, str]] = {}
    for nbhd_name in sorted(all_nbhd_names):
        nbhd_comparison[nbhd_name] = {}
        for scenario_name, summaries in scenario_nbhd.items():
            match = next((s for s in summaries if s.neighbourhood == nbhd_name), None)
            nbhd_comparison[nbhd_name][scenario_name] = (
                match.systemic_signal if match else "no_data"
            )

    return ComparativeReport(
        scenarios_run=list(scenario_names),
        property_comparisons=property_comparisons,
        neighbourhood_comparison=nbhd_comparison,
    )
