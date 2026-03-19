"""
Report generator — consolidates property gap analysis, neighbourhood summaries,
and optional stability results into a single AnalysisReport.

All amounts in CAD.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sim.analysis.assessment_gap import AssessmentGapResult, analyze_all_gaps
from sim.analysis.neighbourhood import NeighbourhoodSummary, summarize_all_neighbourhoods
from sim.analysis.stability import StabilityResult
from sim.engine.simulation import SimulationConfig, SimulationResult
from sim.properties.models import Property


DISCLAIMER = (
    "This analysis is based on simulated market behavior using "
    "rule-based agent models. Results are indicators for assessment "
    "review prioritization, not appraisal conclusions or market "
    "value determinations. All amounts in CAD."
)


@dataclass
class AnalysisReport:
    """Full analysis report from one (or multiple) simulation runs."""

    run_date: str                          # ISO date
    config_summary: dict                   # Serialized SimulationConfig
    property_results: list[AssessmentGapResult]
    neighbourhood_summaries: list[NeighbourhoodSummary]
    stability_results: Optional[dict[str, StabilityResult]]

    # Aggregate stats
    total_properties: int
    total_sold: int
    total_unsold: int
    flagged_for_review: int
    systemic_signals: list[str]            # Neighbourhood names with systemic signals

    disclaimer: str = field(default=DISCLAIMER)


# ─── Public API ───────────────────────────────────────────────────────────────

def generate_report(
    result: SimulationResult,
    properties: list[Property],
    stability: Optional[dict[str, StabilityResult]] = None,
    config: Optional[SimulationConfig] = None,
) -> AnalysisReport:
    """
    Generate a full analysis report from a simulation result.

    Parameters
    ----------
    result:
        A completed SimulationResult.
    properties:
        All properties that were available for the simulation.
    stability:
        Optional pre-computed stability results (from run_stability_analysis).
    config:
        Override config to use for summary; defaults to result.config.

    Returns
    -------
    AnalysisReport with all gap signals, neighbourhood summaries, and aggregates.
    """
    cfg = config or result.config

    property_results = analyze_all_gaps(result, properties)
    neighbourhood_summaries = summarize_all_neighbourhoods(property_results, properties)

    flagged = sum(
        1 for g in property_results if g.review_recommendation == "flag_for_review"
    )
    systemic_signals = [
        s.neighbourhood
        for s in neighbourhood_summaries
        if s.systemic_signal in ("systemic_under", "systemic_over")
    ]

    config_summary: dict = {
        "num_agents": cfg.num_agents,
        "num_weeks": cfg.num_weeks,
        "contract_rate": cfg.contract_rate,
        "seed": cfg.seed,
        "initial_markup": cfg.initial_markup,
        "markup_variance": cfg.markup_variance,
        "agent_entry_mode": cfg.agent_entry_mode,
        "replenishment_rate": cfg.replenishment_rate,
    }

    return AnalysisReport(
        run_date=date.today().isoformat(),
        config_summary=config_summary,
        property_results=property_results,
        neighbourhood_summaries=neighbourhood_summaries,
        stability_results=stability,
        total_properties=len(properties),
        total_sold=len(result.properties_sold),
        total_unsold=len(result.properties_unsold),
        flagged_for_review=flagged,
        systemic_signals=systemic_signals,
    )
