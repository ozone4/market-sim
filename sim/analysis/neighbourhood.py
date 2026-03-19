"""
Neighbourhood-level aggregation of assessment gap results.

Rolls up property-level gap signals to produce systemic assessment signals
at the neighbourhood level. Used to identify areas where BC Assessment
values may be systematically diverging from market behavior.

All amounts in CAD.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from sim.analysis.assessment_gap import AssessmentGapResult
from sim.properties.models import Property


@dataclass
class NeighbourhoodSummary:
    """Aggregated assessment gap signals for one neighbourhood."""

    neighbourhood: str
    municipality: str
    property_count: int
    avg_gap_pct: float
    median_gap_pct: float
    under_assessed_count: int
    over_assessed_count: int
    within_tolerance_count: int
    avg_market_pressure: float
    avg_dom: float
    systemic_signal: str              # "systemic_under" | "systemic_over" | "mixed" | "within_norms"
    flagged_for_review: int           # Count of properties recommended for review


# ─── Public API ───────────────────────────────────────────────────────────────

def summarize_neighbourhood(
    neighbourhood: str,
    gap_results: list[AssessmentGapResult],
    properties: list[Property],
) -> NeighbourhoodSummary:
    """
    Summarize gap results for a single neighbourhood.

    Parameters
    ----------
    neighbourhood:
        Neighbourhood name to filter on.
    gap_results:
        All gap results from the simulation (may include other neighbourhoods).
    properties:
        All properties (used to identify neighbourhood membership and municipality).

    Returns
    -------
    NeighbourhoodSummary with systemic signal and aggregate stats.

    Raises
    ------
    ValueError if no properties or gap results exist for the neighbourhood.
    """
    neighbourhood_folios = {
        p.folio_id
        for p in properties
        if p.location.neighbourhood == neighbourhood
    }

    relevant = [g for g in gap_results if g.folio_id in neighbourhood_folios]

    if not relevant:
        raise ValueError(
            f"No gap results found for neighbourhood {neighbourhood!r}"
        )

    municipality = next(
        (p.location.municipality for p in properties if p.location.neighbourhood == neighbourhood),
        "Unknown",
    )

    n = len(relevant)
    gap_pcts = [g.gap_pct for g in relevant]
    avg_gap = sum(gap_pcts) / n
    median_gap = statistics.median(gap_pcts)

    under_count = sum(1 for g in relevant if g.gap_signal == "under_assessed")
    over_count = sum(1 for g in relevant if g.gap_signal == "over_assessed")
    within_count = sum(1 for g in relevant if g.gap_signal == "within_tolerance")

    avg_pressure = sum(g.market_pressure_score for g in relevant) / n
    avg_dom = sum(g.days_on_market for g in relevant) / n
    flagged = sum(1 for g in relevant if g.review_recommendation == "flag_for_review")

    # Systemic signal: >60% one direction → systemic; >30% both → mixed
    under_pct = under_count / n
    over_pct = over_count / n

    if under_pct > 0.60:
        systemic_signal = "systemic_under"
    elif over_pct > 0.60:
        systemic_signal = "systemic_over"
    elif under_pct > 0.30 and over_pct > 0.30:
        systemic_signal = "mixed"
    else:
        systemic_signal = "within_norms"

    return NeighbourhoodSummary(
        neighbourhood=neighbourhood,
        municipality=municipality,
        property_count=n,
        avg_gap_pct=round(avg_gap, 2),
        median_gap_pct=round(median_gap, 2),
        under_assessed_count=under_count,
        over_assessed_count=over_count,
        within_tolerance_count=within_count,
        avg_market_pressure=round(avg_pressure, 2),
        avg_dom=round(avg_dom, 1),
        systemic_signal=systemic_signal,
        flagged_for_review=flagged,
    )


def summarize_all_neighbourhoods(
    gap_results: list[AssessmentGapResult],
    properties: list[Property],
) -> list[NeighbourhoodSummary]:
    """
    Summarize all neighbourhoods found in the properties list.

    Returns summaries sorted by neighbourhood name.
    """
    neighbourhoods = sorted({p.location.neighbourhood for p in properties})
    summaries: list[NeighbourhoodSummary] = []
    for neighbourhood in neighbourhoods:
        try:
            summary = summarize_neighbourhood(neighbourhood, gap_results, properties)
            summaries.append(summary)
        except ValueError:
            pass
    return summaries
