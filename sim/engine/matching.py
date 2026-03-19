"""
Search and matching engine — finds properties that meet an agent's criteria.

Each week, active agents call find_matches() to get a ranked list of
properties they would consider. Hard filtering (affordability, bedrooms,
type) happens first; soft scoring (see preferences.py) ranks the remainder.

ADJUSTING agents get relaxed constraints: min_bedrooms - 1 and expanded
type adjacency (e.g., a townhouse-seeker also sees condos and SFDs).
"""
from __future__ import annotations

from sim.agents.models import AgentStatus, BuyerAgent
from sim.agents.preferences import TYPE_ADJACENCY, PropertyScore, score_property
from sim.engine.context import MarketContext
from sim.properties.models import Listing, ListingStatus


def find_matches(
    agent: BuyerAgent,
    listings: list[Listing],
    market_context: MarketContext,
    max_results: int = 10,
) -> list[tuple[Listing, PropertyScore]]:
    """
    Find and rank properties this agent would consider.

    Steps:
    1. Skip non-active listings.
    2. For ADJUSTING agents, build a relaxed effective-agent with looser
       bedroom and type constraints.
    3. Score each candidate via score_property().
    4. Discard anything that scored 0 (hard constraint failure).
    5. Sort by score descending, return top max_results.

    Parameters
    ----------
    agent:
        The buyer agent performing the search.
    listings:
        Full inventory of listings (active + others; non-active are skipped).
    market_context:
        Current week's market snapshot (rate, DOM averages, temperature).
    max_results:
        Maximum number of matches to return.

    Returns
    -------
    list of (Listing, PropertyScore) sorted by score descending.
    """
    # Build effective agent (original, or relaxed copy for ADJUSTING status)
    is_adjusting = agent.status == AgentStatus.ADJUSTING
    effective_agent = _make_relaxed_agent(agent) if is_adjusting else agent

    scored: list[tuple[Listing, PropertyScore]] = []

    for listing in listings:
        # Only consider active listings
        if listing.status != ListingStatus.ACTIVE:
            continue

        ps = score_property(effective_agent, listing, market_context)
        if ps.total > 0:
            scored.append((listing, ps))

    # Best match first
    scored.sort(key=lambda x: x[1].total, reverse=True)
    return scored[:max_results]


def _make_relaxed_agent(agent: BuyerAgent) -> BuyerAgent:
    """
    Return a copy of agent with relaxed search constraints for ADJUSTING status.

    Changes:
    - min_bedrooms reduced by 1 (floor 1)
    - preferred_property_types expanded with adjacent types per TYPE_ADJACENCY
    - max_price already incorporates max_bid_stretch in score_property's filter,
      so no change needed here.
    """
    prefs = agent.preferences
    relaxed_min_bedrooms = max(1, prefs.min_bedrooms - 1)

    if prefs.preferred_property_types:
        expanded: set[str] = set()
        for pt in prefs.preferred_property_types:
            expanded.update(TYPE_ADJACENCY.get(pt, [pt]))
        relaxed_types = list(expanded)
    else:
        relaxed_types = []

    relaxed_prefs = prefs.model_copy(
        update={
            "min_bedrooms": relaxed_min_bedrooms,
            "preferred_property_types": relaxed_types,
        }
    )
    return agent.model_copy(update={"preferences": relaxed_prefs})
