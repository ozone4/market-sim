"""
Agent preference scoring for the market simulation.

Scores a property from a buyer's perspective on a 0-100 scale.
Hard constraints (affordability, bedrooms, type) gate to 0. Soft factors
(location, condition, features) are weighted by household type and produce
the final ranked score used for offer decisions.

All monetary values in CAD.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sim.agents.financial import qualifies_for_property
from sim.agents.models import BuyerAgent, HouseholdType
from sim.properties.models import Listing

if TYPE_CHECKING:
    from sim.engine.context import MarketContext


@dataclass
class PropertyScore:
    """Scoring result for one (agent, listing) pair."""

    total: float              # 0-100
    affordable: bool
    affordability_comfort: float  # 0-1, higher = more budget headroom
    size_fit: float           # 0-1
    type_match: float         # 0-1
    location_score: float     # 0-1
    condition_score: float    # 0-1
    feature_bonus: float      # 0-1
    breakdown: dict = field(default_factory=dict)


# ─── Scoring weights by household type ───────────────────────────────────────
# Weights must sum to 1.0 per household type.

HOUSEHOLD_SCORING_WEIGHTS: dict[HouseholdType, dict[str, float]] = {
    HouseholdType.SINGLE_YOUNG: {
        "affordability": 0.30,
        "size_fit": 0.10,
        "type_match": 0.15,
        "location": 0.20,   # Walkability, transit
        "condition": 0.10,
        "features": 0.15,
    },
    HouseholdType.COUPLE_NO_KIDS: {
        "affordability": 0.25,
        "size_fit": 0.15,
        "type_match": 0.15,
        "location": 0.20,
        "condition": 0.15,
        "features": 0.10,
    },
    HouseholdType.COUPLE_WITH_KIDS: {
        "affordability": 0.25,
        "size_fit": 0.25,   # Bedrooms critical
        "type_match": 0.10,
        "location": 0.20,   # Schools, parks
        "condition": 0.10,
        "features": 0.10,
    },
    HouseholdType.SINGLE_PARENT: {
        "affordability": 0.35,  # Budget-constrained
        "size_fit": 0.20,
        "type_match": 0.10,
        "location": 0.20,   # Schools
        "condition": 0.05,
        "features": 0.10,
    },
    HouseholdType.DOWNSIZER: {
        "affordability": 0.20,
        "size_fit": 0.20,   # Wants smaller
        "type_match": 0.15,
        "location": 0.20,
        "condition": 0.15,  # Quality matters
        "features": 0.10,
    },
    HouseholdType.RETIREE: {
        "affordability": 0.20,
        "size_fit": 0.10,
        "type_match": 0.15,
        "location": 0.25,   # Walkability, transit, proximity
        "condition": 0.20,  # Turnkey preferred
        "features": 0.10,
    },
    HouseholdType.INVESTOR: {
        "affordability": 0.30,
        "size_fit": 0.05,
        "type_match": 0.10,
        "location": 0.15,
        "condition": 0.10,
        "features": 0.30,   # Suite = rental income
    },
    HouseholdType.NEW_TO_AREA: {
        "affordability": 0.25,
        "size_fit": 0.20,
        "type_match": 0.10,
        "location": 0.15,
        "condition": 0.15,
        "features": 0.15,
    },
}

# Condition ordered worst → best (index / max → 0.0-1.0 score)
CONDITION_ORDER = ["poor", "fair", "average", "good", "excellent"]

# Property type adjacency for relaxed ADJUSTING-agent matching
TYPE_ADJACENCY: dict[str, list[str]] = {
    "single_family_detached": ["single_family_detached", "townhouse", "duplex"],
    "townhouse": ["townhouse", "single_family_detached", "condo"],
    "condo": ["condo", "townhouse"],
    "duplex": ["duplex", "single_family_detached", "townhouse"],
    "manufactured": ["manufactured", "condo"],
}


def score_property(
    agent: BuyerAgent,
    listing: Listing,
    market_context: "MarketContext",
) -> PropertyScore:
    """
    Score a property from this agent's perspective.

    Returns a PropertyScore with total 0-100 where:
    - 0 = fails a hard constraint (unaffordable, wrong type, too few beds)
    - 1-30 = meets constraints but poor fit
    - 31-60 = acceptable
    - 61-80 = good fit
    - 81-100 = ideal match

    Scoring combines affordability comfort, size fit, type match,
    location desirability, condition, and feature bonuses. Weights
    are drawn from HOUSEHOLD_SCORING_WEIGHTS by household type.
    """
    prop = listing.property
    asking = listing.current_asking
    prefs = agent.preferences
    behavior = agent.behavior
    financial = agent.financial

    # ── Hard filter 1: mortgage qualification ────────────────────────────────
    qualified, reason = qualifies_for_property(
        financial, asking, contract_rate=market_context.contract_rate
    )
    if not qualified:
        return PropertyScore(
            total=0.0, affordable=False, affordability_comfort=0.0,
            size_fit=0.0, type_match=0.0, location_score=0.0,
            condition_score=0.0, feature_bonus=0.0,
            breakdown={"disqualified": reason},
        )

    # ── Hard filter 2: within stretch budget ─────────────────────────────────
    max_price = prefs.max_price or 0.0
    if max_price > 0 and asking > max_price * (1 + behavior.max_bid_stretch):
        return PropertyScore(
            total=0.0, affordable=False, affordability_comfort=0.0,
            size_fit=0.0, type_match=0.0, location_score=0.0,
            condition_score=0.0, feature_bonus=0.0,
            breakdown={"disqualified": "exceeds_stretch_budget"},
        )

    # ── Hard filter 3: bedroom minimum ───────────────────────────────────────
    if prop.bedrooms < prefs.min_bedrooms:
        return PropertyScore(
            total=0.0, affordable=True, affordability_comfort=0.0,
            size_fit=0.0, type_match=0.0, location_score=0.0,
            condition_score=0.0, feature_bonus=0.0,
            breakdown={
                "disqualified": (
                    f"too_few_bedrooms ({prop.bedrooms} < {prefs.min_bedrooms})"
                )
            },
        )

    # ── Hard filter 4: property type ─────────────────────────────────────────
    if prefs.preferred_property_types:
        if prop.property_type.value not in prefs.preferred_property_types:
            return PropertyScore(
                total=0.0, affordable=True, affordability_comfort=0.0,
                size_fit=0.0, type_match=0.0, location_score=0.0,
                condition_score=0.0, feature_bonus=0.0,
                breakdown={
                    "disqualified": f"wrong_type ({prop.property_type.value})"
                },
            )

    # ── Soft scoring ──────────────────────────────────────────────────────────

    # 1. Affordability comfort: fraction of budget headroom remaining
    if max_price > 0:
        affordability_comfort = max(0.0, min(1.0, 1.0 - (asking / max_price)))
    else:
        affordability_comfort = 0.5

    # 2. Size fit: bedroom surplus vs minimum need
    bedroom_excess = prop.bedrooms - prefs.min_bedrooms
    if bedroom_excess == 0:
        size_fit = 1.0
    elif bedroom_excess > 0:
        if agent.household_type == HouseholdType.DOWNSIZER:
            # Downsizers prefer smaller — excess is mildly penalised
            size_fit = max(0.3, 1.0 - bedroom_excess * 0.20)
        else:
            # Bonus rooms are mildly positive for everyone else
            size_fit = min(1.0, 0.85 + bedroom_excess * 0.05)
    else:
        # Shouldn't reach here (hard filtered) — safety fallback
        size_fit = 0.0

    # 3. Type match: degree to which property type aligns with preference list
    if not prefs.preferred_property_types:
        type_match = 0.80  # No preference → broadly acceptable
    elif prop.property_type.value == prefs.preferred_property_types[0]:
        type_match = 1.00  # First-choice type
    elif prop.property_type.value in prefs.preferred_property_types:
        type_match = 0.85  # Secondary preference
    else:
        type_match = 0.30  # Shouldn't occur after hard filter, but safe

    # 4. Location desirability
    loc = prop.location
    loc_components: list[float] = []

    if loc.walk_score is not None:
        walk = loc.walk_score / 100.0
        # Retirees and young singles weight walkability more
        if agent.household_type in (HouseholdType.RETIREE, HouseholdType.SINGLE_YOUNG):
            walk = min(1.0, walk * 1.20)
        loc_components.append(walk)

    if loc.transit_score is not None:
        transit = loc.transit_score / 100.0
        if agent.household_type in (HouseholdType.RETIREE, HouseholdType.SINGLE_YOUNG):
            transit = min(1.0, transit * 1.30)
        loc_components.append(transit)

    if loc.school_proximity is not None:
        # 0 km = 1.0, 2+ km = 0.0 (linear)
        school = max(0.0, 1.0 - loc.school_proximity / 2.0)
        if agent.household_type in (
            HouseholdType.COUPLE_WITH_KIDS, HouseholdType.SINGLE_PARENT
        ):
            school = min(1.0, school * 1.40)  # Schools are critical
        loc_components.append(school)

    location_score = (
        min(1.0, sum(loc_components) / len(loc_components))
        if loc_components
        else 0.60
    )

    # 5. Condition score
    cond_idx = CONDITION_ORDER.index(prop.condition.value)
    raw_condition = cond_idx / (len(CONDITION_ORDER) - 1)  # 0.0 – 1.0

    # Risk-averse agents strongly prefer good condition; risk-tolerant are more flexible
    if behavior.risk_tolerance < 0.40:
        condition_score = min(1.0, raw_condition * 1.30)
    elif behavior.risk_tolerance > 0.70:
        condition_score = min(1.0, 0.30 + raw_condition * 0.70)
    else:
        condition_score = raw_condition

    # 6. Feature bonuses
    features = prop.features
    feature_scores: list[float] = []

    # Suite: critical for investors, nice for others
    if features.suite:
        if (
            agent.household_type == HouseholdType.INVESTOR
            or prefs.needs_suite
        ):
            feature_scores.append(1.0)
        else:
            feature_scores.append(0.65)
    else:
        feature_scores.append(0.0 if prefs.needs_suite else 0.40)

    # Garage: important for families and downsizers
    if features.garage:
        if (
            prefs.needs_garage
            or agent.household_type in (
                HouseholdType.COUPLE_WITH_KIDS, HouseholdType.DOWNSIZER
            )
        ):
            feature_scores.append(0.90)
        else:
            feature_scores.append(0.60)
    else:
        feature_scores.append(0.0 if prefs.needs_garage else 0.40)

    # View: broadly desirable
    feature_scores.append(0.80 if features.view else 0.40)

    # Recent renovation: reassuring for risk-averse, irrelevant for investors
    if features.renovated_recent:
        if behavior.risk_tolerance < 0.40:
            feature_scores.append(1.0)
        else:
            feature_scores.append(0.75)
    else:
        feature_scores.append(0.40)

    # Waterfront: premium feature
    if features.waterfront:
        feature_scores.append(1.0)

    feature_bonus = sum(feature_scores) / len(feature_scores)

    # ── Weighted aggregate ────────────────────────────────────────────────────
    weights = HOUSEHOLD_SCORING_WEIGHTS[agent.household_type]
    raw_score = (
        weights["affordability"] * affordability_comfort
        + weights["size_fit"] * size_fit
        + weights["type_match"] * type_match
        + weights["location"] * location_score
        + weights["condition"] * condition_score
        + weights["features"] * feature_bonus
    )

    # Hard constraints passed → minimum score 1.0; scale to 1-100
    total = max(1.0, min(100.0, raw_score * 100.0))

    breakdown = {
        "asking_price": asking,
        "max_price": max_price,
        "affordability_comfort": round(affordability_comfort, 4),
        "size_fit": round(size_fit, 4),
        "type_match": round(type_match, 4),
        "location_score": round(location_score, 4),
        "condition_score": round(condition_score, 4),
        "feature_bonus": round(feature_bonus, 4),
        "raw_score": round(raw_score, 6),
        "weights": weights,
    }

    return PropertyScore(
        total=round(total, 2),
        affordable=True,
        affordability_comfort=affordability_comfort,
        size_fit=size_fit,
        type_match=type_match,
        location_score=location_score,
        condition_score=condition_score,
        feature_bonus=feature_bonus,
        breakdown=breakdown,
    )
