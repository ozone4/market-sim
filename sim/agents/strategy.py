"""
Agent decision-making strategy for the weekly simulation loop.

Each active agent calls agent_weekly_action() to decide what to do:
wait, bid, adjust search criteria, or exit the market. Bid amounts
are calculated by calculate_bid_amount(), which anchors on the asking
price and adjusts based on urgency, market temperature, and competition.

All monetary values in CAD. No LLM calls — purely rule-based logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np

from sim.agents.models import AgentStatus, BuyerAgent
from sim.agents.preferences import PropertyScore
from sim.engine.context import MarketContext
from sim.properties.models import Listing


class ActionType(str, Enum):
    WAIT = "wait"
    BID = "bid"
    ADJUST = "adjust"
    EXIT = "exit"


@dataclass
class AgentAction:
    """The action an agent takes for one simulation week."""

    action_type: ActionType
    target_folio_id: Optional[str] = None  # For BID actions
    bid_amount: Optional[float] = None      # For BID actions
    reason: str = ""                        # Audit trail


def agent_weekly_action(
    agent: BuyerAgent,
    matches: list[tuple[Listing, PropertyScore]],
    market_context: MarketContext,
    rng: np.random.Generator,
) -> AgentAction:
    """
    Determine what an agent does this week.

    Decision priority:
    1. weeks_in_market >= patience_weeks           → EXIT
    2. bid_losses >= adjustment_threshold
       AND not already ADJUSTING                   → ADJUST
    3. No matches with score > 40                  → WAIT
       (unless urgency > 0.7, then consider bidding)
    4. Top score > 60 OR (urgency > 0.7 AND top > 40) → BID
    5. Otherwise: WAIT with probability based on patience remaining;
       impatient agents may bid on a mediocre match.
    """
    behavior = agent.behavior

    # 1. Patience exhausted → exit
    if agent.weeks_in_market >= behavior.patience_weeks:
        return AgentAction(
            action_type=ActionType.EXIT,
            reason=f"patience_exhausted ({agent.weeks_in_market}w >= {behavior.patience_weeks}w)",
        )

    # 2. Too many losses → expand criteria
    if (
        agent.bid_losses >= behavior.adjustment_after_losses
        and agent.status != AgentStatus.ADJUSTING
    ):
        return AgentAction(
            action_type=ActionType.ADJUST,
            reason=(
                f"losses ({agent.bid_losses}) >= threshold "
                f"({behavior.adjustment_after_losses})"
            ),
        )

    # 3. No qualifying matches
    has_good_match = bool(matches) and matches[0][1].total > 40

    if not has_good_match:
        # Highly urgent agents still try if any match exists at all
        if matches and behavior.urgency > 0.7:
            pass  # Fall through to bidding logic below
        else:
            return AgentAction(
                action_type=ActionType.WAIT,
                reason="no_matches_above_threshold",
            )

    if not matches:
        return AgentAction(action_type=ActionType.WAIT, reason="no_matches")

    top_listing, top_score = matches[0]

    # 4. Bid decision
    should_bid = top_score.total > 60 or (
        behavior.urgency > 0.7 and top_score.total > 40
    )

    if should_bid:
        bid = calculate_bid_amount(
            agent=agent,
            listing=top_listing,
            score=top_score,
            market_context=market_context,
            competing_offers=0,
            rng=rng,
        )
        return AgentAction(
            action_type=ActionType.BID,
            target_folio_id=top_listing.property.folio_id,
            bid_amount=bid,
            reason=(
                f"score={top_score.total:.1f} urgency={behavior.urgency:.2f}"
            ),
        )

    # 5. Patience-weighted wait vs bid
    weeks_remaining = max(0, behavior.patience_weeks - agent.weeks_in_market)
    patience_fraction = (
        weeks_remaining / behavior.patience_weeks
        if behavior.patience_weeks > 0
        else 0.5
    )

    # The more time left, the more likely to wait
    if rng.random() < patience_fraction:
        return AgentAction(
            action_type=ActionType.WAIT,
            reason=f"waiting_for_better_match ({weeks_remaining}w patience left)",
        )
    else:
        # Running low on patience — bid on the best available
        bid = calculate_bid_amount(
            agent=agent,
            listing=top_listing,
            score=top_score,
            market_context=market_context,
            competing_offers=0,
            rng=rng,
        )
        return AgentAction(
            action_type=ActionType.BID,
            target_folio_id=top_listing.property.folio_id,
            bid_amount=bid,
            reason=f"impatient_bid score={top_score.total:.1f}",
        )


def calculate_bid_amount(
    agent: BuyerAgent,
    listing: Listing,
    score: PropertyScore,
    market_context: MarketContext,
    competing_offers: int,
    rng: np.random.Generator,
) -> float:
    """
    Calculate how much this agent bids on this property.

    Base = current asking price (agents anchor on asking).

    Adjustments applied multiplicatively:
    - Market temperature: hot → +2-6%, cold → -3 to 0%, balanced → -1 to +2%
    - Score stretch: higher preference score → willing to pay more
    - Urgency: high urgency → stretch higher
    - Affordability comfort: lots of budget headroom → bid more confidently
    - Competition: more known competing offers → escalate
    - Risk tolerance: high risk agents stretch further
    - Random noise: ±1.5% so identical agents don't bid exactly the same

    Hard ceilings:
    - max_price * (1 + max_bid_stretch)
    - Floor: 85% of asking (don't lowball to the point of insult)

    Returns bid rounded to nearest $100.
    """
    asking = listing.current_asking
    max_price = agent.preferences.max_price or asking
    behavior = agent.behavior
    temp = market_context.market_temperature

    bid = asking  # Anchor

    # Market temperature adjustment
    if temp == "hot":
        market_adj = 0.02 + rng.random() * 0.04   # +2 to +6%
    elif temp == "cold":
        market_adj = -0.03 + rng.random() * 0.03  # -3 to 0%
    else:
        market_adj = -0.01 + rng.random() * 0.03  # -1 to +2%
    bid *= (1 + market_adj)

    # Higher preference score → willing to stretch more (up to +2.5%)
    score_adj = (score.total - 50.0) / 100.0 * 0.05
    bid *= (1 + score_adj)

    # Urgency: above-average urgency pushes bid up (±2%)
    urgency_adj = (behavior.urgency - 0.5) * 0.04
    bid *= (1 + urgency_adj)

    # Affordability comfort: spare budget room → bid more freely (0 to +3%)
    comfort_adj = score.affordability_comfort * 0.03
    bid *= (1 + comfort_adj)

    # Competition: escalate if other offers are known
    if competing_offers >= 2:
        comp_adj = min(0.06, 0.02 + (competing_offers - 2) * 0.01)
        bid *= (1 + comp_adj)
    elif competing_offers == 1:
        bid *= 1.015

    # Risk tolerance: bold agents stretch further (±1%)
    risk_adj = (behavior.risk_tolerance - 0.5) * 0.02
    bid *= (1 + risk_adj)

    # Random noise ±1.5%
    noise = rng.uniform(-0.015, 0.015)
    bid *= (1 + noise)

    # Apply hard ceiling
    max_with_stretch = max_price * (1 + behavior.max_bid_stretch)
    bid = min(bid, max_with_stretch)

    # Apply floor (never bid below 85% of asking — agents aren't desperate lowballers)
    bid = max(bid, asking * 0.85)

    # Round to nearest $100 (realistic offer amounts)
    return round(bid / 100) * 100
