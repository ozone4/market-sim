"""
Offer submission and auction resolution mechanics.

resolve_offers() handles all offers received on one property in one week.
Three scenarios:
  - No offers: property sits, accumulates DOM.
  - Single offer: accept/counter/reject based on offer-to-asking ratio.
  - Multiple offers (bidding war): sealed-bid escalation rounds until one
    agent remains or max_rounds is exhausted.

Losing agents have bid_losses incremented by the simulation engine after
resolution. Winning agents are marked WON by the simulation engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np

from sim.agents.models import BuyerAgent
from sim.engine.context import MarketContext
from sim.properties.models import Listing


class AuctionOutcome(str, Enum):
    SOLD = "sold"
    NO_OFFERS = "no_offers"
    REJECTED = "rejected"
    COUNTERED = "countered"  # Counter offered; resolved as SOLD or expired


@dataclass
class Offer:
    """A single offer from one agent on one property."""

    agent_id: str
    folio_id: str
    amount: float
    week: int
    is_escalation: bool = False
    round_number: int = 1
    property_score: float = 50.0  # Agent's score for this property (used in counters)


@dataclass
class AuctionResult:
    """Full result of resolving all offers on one property for one week."""

    folio_id: str
    outcome: AuctionOutcome
    winning_offer: Optional[Offer] = None
    all_offers: list[Offer] = field(default_factory=list)
    rounds: int = 1
    final_price: Optional[float] = None


def resolve_offers(
    folio_id: str,
    offers: list[Offer],
    listing: Listing,
    agents: dict[str, BuyerAgent],
    market_context: MarketContext,
    rng: np.random.Generator,
    max_rounds: int = 3,
) -> AuctionResult:
    """
    Resolve all offers on a property for this week.

    Scenarios
    ---------
    NO OFFERS
        Returns AuctionOutcome.NO_OFFERS.

    SINGLE OFFER
        - Offer >= accept_threshold (98% hot, 95% balanced/cold) → SOLD
        - Offer >= 90% → seller counters at asking price
          Agent accepts if urgency > 0.5 OR property_score > 70
        - Offer < 90% → REJECTED

    MULTIPLE OFFERS (bidding war)
        Round 1: All offers on the table. If the highest is at or above
        asking, proceed to escalation round.
        Rounds 2-N: Each remaining agent independently decides to escalate
        or withdraw based on:
            escalate_prob = risk_tolerance × urgency × budget_remaining_ratio
        Escalation amount = 1–3% above prior bid (bounded by stretch ceiling).
        Continue until one agent remains or max_rounds exceeded.
        Winner = highest bid in final active round.
        If all agents withdraw, fall back to highest initial bid (if >= 90%
        of asking → SOLD; otherwise REJECTED).
    """
    if not offers:
        return AuctionResult(
            folio_id=folio_id,
            outcome=AuctionOutcome.NO_OFFERS,
            all_offers=[],
        )

    asking = listing.current_asking
    temp = market_context.market_temperature

    # ── Single offer ──────────────────────────────────────────────────────────
    if len(offers) == 1:
        offer = offers[0]
        return _resolve_single_offer(offer, asking, temp, agents, offers)

    # ── Multiple offers — bidding war ─────────────────────────────────────────
    return _resolve_bidding_war(
        folio_id=folio_id,
        offers=offers,
        asking=asking,
        agents=agents,
        rng=rng,
        max_rounds=max_rounds,
    )


# ─── Internal helpers ─────────────────────────────────────────────────────────


def _accept_threshold(temp: str) -> float:
    """Minimum offer-to-asking ratio for automatic acceptance."""
    return 0.98 if temp == "hot" else 0.95


def _resolve_single_offer(
    offer: Offer,
    asking: float,
    temp: str,
    agents: dict[str, BuyerAgent],
    all_offers: list[Offer],
) -> AuctionResult:
    """Resolve a single-offer scenario."""
    folio_id = offer.folio_id
    pct = offer.amount / asking if asking > 0 else 0.0
    threshold = _accept_threshold(temp)

    if pct >= threshold:
        # Accepted at offer price
        return AuctionResult(
            folio_id=folio_id,
            outcome=AuctionOutcome.SOLD,
            winning_offer=offer,
            all_offers=all_offers,
            rounds=1,
            final_price=offer.amount,
        )

    if pct >= 0.90:
        # Counter at asking price
        agent = agents.get(offer.agent_id)
        accepts_counter = False
        if agent:
            accepts_counter = (
                agent.behavior.urgency > 0.5
                or offer.property_score > 70
            )
        if accepts_counter:
            counter = Offer(
                agent_id=offer.agent_id,
                folio_id=folio_id,
                amount=asking,
                week=offer.week,
                is_escalation=True,
                round_number=2,
                property_score=offer.property_score,
            )
            return AuctionResult(
                folio_id=folio_id,
                outcome=AuctionOutcome.SOLD,
                winning_offer=counter,
                all_offers=all_offers + [counter],
                rounds=2,
                final_price=asking,
            )
        return AuctionResult(
            folio_id=folio_id,
            outcome=AuctionOutcome.REJECTED,
            all_offers=all_offers,
            rounds=1,
        )

    # < 90% → reject outright
    return AuctionResult(
        folio_id=folio_id,
        outcome=AuctionOutcome.REJECTED,
        all_offers=all_offers,
        rounds=1,
    )


def _resolve_bidding_war(
    folio_id: str,
    offers: list[Offer],
    asking: float,
    agents: dict[str, BuyerAgent],
    rng: np.random.Generator,
    max_rounds: int,
) -> AuctionResult:
    """Resolve a multi-offer bidding war with escalation rounds."""
    all_offers_log: list[Offer] = list(offers)
    active_offers: list[Offer] = list(offers)
    rounds_completed = 1

    for round_num in range(2, max_rounds + 1):
        if len(active_offers) <= 1:
            break

        next_round: list[Offer] = []
        n_competitors = len(active_offers)  # Each agent sees this count

        for offer in active_offers:
            agent = agents.get(offer.agent_id)
            if agent is None:
                continue

            max_bid = (agent.preferences.max_price or asking) * (
                1 + agent.behavior.max_bid_stretch
            )
            budget_left = max(0.0, max_bid - offer.amount)
            budget_remaining_ratio = budget_left / asking if asking > 0 else 0.0

            # Probability formula from spec (capped to avoid certain escalation)
            escalate_prob = (
                agent.behavior.risk_tolerance
                * agent.behavior.urgency
                * budget_remaining_ratio
            )
            # Knowing N-1 other offers exist nudges probability up slightly
            escalate_prob = min(0.95, escalate_prob * (1 + (n_competitors - 1) * 0.1))

            if rng.random() < escalate_prob and budget_left > 0:
                esc_pct = rng.uniform(0.01, 0.03)
                new_amount = min(offer.amount * (1 + esc_pct), max_bid)
                new_amount = round(new_amount / 100) * 100  # nearest $100

                if new_amount > offer.amount:
                    escalated = Offer(
                        agent_id=offer.agent_id,
                        folio_id=folio_id,
                        amount=new_amount,
                        week=offer.week,
                        is_escalation=True,
                        round_number=round_num,
                        property_score=offer.property_score,
                    )
                    next_round.append(escalated)
                    all_offers_log.append(escalated)
                    continue

            # Agent withdrew (or hit budget ceiling) — keep their final bid
            # in the log but don't escalate it
            _ = n_competitors  # used above

        rounds_completed = round_num
        if not next_round:
            # Everyone withdrew from escalation; active_offers stay as final bids
            break
        active_offers = next_round

    # Winner = highest bid among final active participants
    if not active_offers:
        # Pathological fallback: take the best initial offer
        active_offers = offers

    winner = max(active_offers, key=lambda o: o.amount)
    pct = winner.amount / asking if asking > 0 else 0.0

    if pct >= 0.90:
        return AuctionResult(
            folio_id=folio_id,
            outcome=AuctionOutcome.SOLD,
            winning_offer=winner,
            all_offers=all_offers_log,
            rounds=rounds_completed,
            final_price=winner.amount,
        )

    # All offers were too low even after escalation
    return AuctionResult(
        folio_id=folio_id,
        outcome=AuctionOutcome.REJECTED,
        all_offers=all_offers_log,
        rounds=rounds_completed,
    )
