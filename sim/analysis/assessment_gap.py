"""
Assessment gap analysis — compare simulation clearing prices to BC Assessment values.

analyze_property_gap()  → per-property gap signal
analyze_all_gaps()      → batch across all properties in a simulation result

Gap signal thresholds:
  |gap_pct| <= 8%  → within_tolerance
  gap_pct >  8%    → under_assessed  (market would pay significantly more)
  gap_pct < -8%    → over_assessed   (market would not support the assessment)

All amounts in CAD.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sim.engine.simulation import SimulationResult
from sim.properties.models import Property


@dataclass
class AssessmentGapResult:
    """Per-property assessment gap signal from one simulation run."""

    folio_id: str
    assessed_value: float
    simulated_clearing_price: float   # Final sale price; 0.0 if unsold
    gap_pct: float                     # (clearing - assessed) / assessed * 100
    gap_signal: str                    # "under_assessed" | "over_assessed" | "within_tolerance"
    confidence: str                    # "high" | "medium" | "low"
    market_pressure_score: float       # 0-10 scale
    days_on_market: int
    offer_count: int
    rounds: int
    review_recommendation: str         # "flag_for_review" | "within_norms" | "data_insufficient"


# ─── Internal helpers ──────────────────────────────────────────────────────────

def _market_pressure_score(offer_count: int, dom: int, rounds: int) -> float:
    """Compute market pressure score 0-10 per spec formula."""
    # Offers component
    if offer_count == 0:
        base = 0.0
    elif offer_count == 1:
        base = 2.0
    elif offer_count <= 3:   # 2-3
        base = 4.0
    elif offer_count <= 5:   # 4-5
        base = 6.0
    elif offer_count <= 10:  # 6-10
        base = 8.0
    else:                    # >10
        base = 10.0

    # DOM modifier
    if dom < 14:
        dom_mod = 1.0
    elif dom <= 30:
        dom_mod = 0.0
    elif dom <= 60:
        dom_mod = -1.0
    else:
        dom_mod = -2.0

    # Rounds modifier
    if rounds <= 1:
        rounds_mod = 0.0
    elif rounds == 2:
        rounds_mod = 0.5
    else:
        rounds_mod = 1.0

    return max(0.0, min(10.0, base + dom_mod + rounds_mod))


def _confidence(offer_count: int, dom: int, had_price_reduction: bool, is_sold: bool) -> str:
    """
    Determine confidence level.

    high:   >= 3 offers, DOM < 30
    medium: 1-2 offers, DOM 30-60
    low:    0 offers (expired), DOM > 60, or only sold due to price reductions
    """
    if not is_sold or offer_count == 0:
        return "low"
    if dom > 60:
        return "low"
    if had_price_reduction and offer_count < 2:
        return "low"
    if offer_count >= 3 and dom < 30:
        return "high"
    if 1 <= offer_count <= 2 and dom <= 60:
        return "medium"
    return "medium"


# ─── Public API ───────────────────────────────────────────────────────────────

def analyze_property_gap(
    folio_id: str,
    result: SimulationResult,
    properties: dict[str, Property],
) -> AssessmentGapResult:
    """
    Analyze the gap between BC Assessment value and the simulated clearing price
    for one property.

    Parameters
    ----------
    folio_id:
        The property to analyze.
    result:
        A completed SimulationResult.
    properties:
        Mapping of folio_id → Property (for assessed values).

    Returns
    -------
    AssessmentGapResult with gap signal, confidence, and review recommendation.
    """
    prop = properties.get(folio_id)
    if prop is None:
        raise KeyError(f"Property {folio_id!r} not found in properties dict")

    assessed = prop.assessed_value
    is_sold = folio_id in result.properties_sold
    dom = result.folio_dom.get(folio_id, 90)

    if not is_sold:
        return AssessmentGapResult(
            folio_id=folio_id,
            assessed_value=assessed,
            simulated_clearing_price=0.0,
            gap_pct=0.0,
            gap_signal="within_tolerance",
            confidence="low",
            market_pressure_score=0.0,
            days_on_market=dom,
            offer_count=0,
            rounds=0,
            review_recommendation="data_insufficient",
        )

    # Find the matching transaction
    txn = next((t for t in result.transactions if t.folio_id == folio_id), None)
    if txn is None or txn.final_price is None:
        return AssessmentGapResult(
            folio_id=folio_id,
            assessed_value=assessed,
            simulated_clearing_price=0.0,
            gap_pct=0.0,
            gap_signal="within_tolerance",
            confidence="low",
            market_pressure_score=0.0,
            days_on_market=dom,
            offer_count=0,
            rounds=0,
            review_recommendation="data_insufficient",
        )

    clearing_price = txn.final_price
    gap_pct = (clearing_price - assessed) / assessed * 100.0

    # Gap signal
    if abs(gap_pct) <= 8.0:
        gap_signal = "within_tolerance"
    elif gap_pct > 8.0:
        gap_signal = "under_assessed"
    else:
        gap_signal = "over_assessed"

    # Count initial round offers (round_number == 1, not escalations)
    initial_offers = [o for o in txn.all_offers if o.round_number == 1]
    offer_count = len(initial_offers)
    rounds = txn.rounds

    # Proxy for price reductions: DOM > 42 days means at least one reduction fired
    had_price_reduction = dom > 42

    conf = _confidence(offer_count, dom, had_price_reduction, is_sold=True)
    mps = _market_pressure_score(offer_count, dom, rounds)

    # Review recommendation
    if abs(gap_pct) > 15.0 and conf != "low":
        review_recommendation = "flag_for_review"
    else:
        review_recommendation = "within_norms"

    return AssessmentGapResult(
        folio_id=folio_id,
        assessed_value=assessed,
        simulated_clearing_price=clearing_price,
        gap_pct=round(gap_pct, 2),
        gap_signal=gap_signal,
        confidence=conf,
        market_pressure_score=round(mps, 2),
        days_on_market=dom,
        offer_count=offer_count,
        rounds=rounds,
        review_recommendation=review_recommendation,
    )


def analyze_all_gaps(
    result: SimulationResult,
    properties: list[Property],
) -> list[AssessmentGapResult]:
    """
    Analyze gaps for all properties in a simulation result.

    Parameters
    ----------
    result:
        A completed SimulationResult.
    properties:
        All properties that were available for the simulation.

    Returns
    -------
    One AssessmentGapResult per property, in the same order as the input list.
    """
    props_dict = {p.folio_id: p for p in properties}
    return [analyze_property_gap(p.folio_id, result, props_dict) for p in properties]
