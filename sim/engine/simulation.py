"""
Main simulation engine — orchestrates the full multi-agent market simulation.

run_simulation() drives the week-by-week loop:
  1. Apply macro shocks
  2. Enter new agents
  3. Inventory tick (DOM, price reductions, expirations)
  4. Matching — each active agent finds affordable properties
  5. Offer submission — agents that decide to BID generate Offer objects
  6. Auction resolution — offers grouped by property, resolved per rules
  7. State update — agents, inventory, market context refreshed
  8. Weekly snapshot captured

The simulation is fully deterministic given config.seed.
All monetary values in CAD.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np

from sim.agents.financial import calculate_max_purchase_price
from sim.agents.generator import generate_buyer_pool
from sim.agents.models import AgentStatus, BuyerAgent, HouseholdType
from sim.agents.strategy import ActionType, AgentAction, agent_weekly_action, calculate_bid_amount
from sim.engine.auction import AuctionOutcome, AuctionResult, Offer, resolve_offers
from sim.engine.context import MarketContext
from sim.engine.matching import find_matches
from sim.market.clock import SimulationClock
from sim.market.inventory import MarketInventory
from sim.market.shocks import MacroShock, ShockType
from sim.properties.models import Property


# ─── Configuration ────────────────────────────────────────────────────────────

@dataclass
class SimulationConfig:
    """Parameters that control a simulation run."""

    num_agents: int = 500
    num_weeks: int = 26              # ~6 months
    contract_rate: float = 0.05

    seed: int = 42

    # Asking price strategy
    initial_markup: float = 0.03     # asking = assessed × (1 + markup)
    markup_variance: float = 0.05    # ± random variance added to markup

    # Agent entry pattern
    agent_entry_mode: str = "front_loaded"
    # "front_loaded" — 70% in weeks 0-2, 30% trickle over remaining weeks
    # "gradual"      — equal batches each week
    # "random"       — Poisson process

    # Optional macro shocks
    shocks: list[MacroShock] = field(default_factory=list)

    # Inventory replenishment (fix Phase 2 issue: market clears too fast)
    replenishment_rate: float = 0.0   # 0.0 = no replenishment; 0.05 = 5% of initial per week
    replenishment_variance: float = 0.02  # Jitter on per-week entry count


# ─── Result types ─────────────────────────────────────────────────────────────

@dataclass
class WeeklySnapshot:
    """Aggregate market statistics for one simulation week."""

    week: int
    active_listings: int
    active_buyers: int
    offers_this_week: int
    sales_this_week: int
    expirations_this_week: int
    avg_sale_price: float
    avg_days_on_market: float
    market_temperature: str


@dataclass
class AgentOutcome:
    """How one buyer agent ended the simulation."""

    agent_id: str
    household_type: str
    final_status: str              # WON / EXITED / SEARCHING / ADJUSTING / …
    property_purchased: Optional[str] = None    # folio_id
    purchase_price: Optional[float] = None
    weeks_to_purchase: Optional[int] = None     # Week number, not duration
    bids_submitted: int = 0
    bids_lost: int = 0


@dataclass
class SimulationResult:
    """Full output of a simulation run."""

    config: SimulationConfig
    transactions: list[AuctionResult]
    weekly_snapshots: list[WeeklySnapshot]
    agent_outcomes: dict[str, AgentOutcome]
    properties_unsold: list[str]
    properties_sold: list[str]
    total_weeks: int
    seed: int
    # DOM (days on market) per folio at time of sale or end of simulation
    folio_dom: dict[str, int] = field(default_factory=dict)


# ─── Main entry point ─────────────────────────────────────────────────────────

def run_simulation(
    properties: list[Property],
    config: SimulationConfig,
) -> SimulationResult:
    """
    Run the full multi-agent market simulation.

    Parameters
    ----------
    properties:
        All properties to list at the start of the simulation.
    config:
        Simulation parameters including seed, agent count, shocks, etc.

    Returns
    -------
    SimulationResult with all transactions, agent outcomes, and weekly snapshots.
    """
    rng = np.random.default_rng(config.seed)

    # ── Initialise components ──────────────────────────────────────────────────
    clock = SimulationClock(start_date=date(2024, 1, 15))
    inventory = MarketInventory()

    # List all properties at week 0 with stochastic markup
    for prop in properties:
        markup = config.initial_markup + rng.uniform(
            -config.markup_variance, config.markup_variance
        )
        markup = max(-0.10, markup)  # Asking price floor: 90% of assessed
        asking = round(prop.assessed_value * (1 + markup) / 100) * 100
        inventory.add_listing(prop, asking, week=0)

    # Pre-generate all agents keyed by their entry week
    entry_schedule: dict[int, list[BuyerAgent]] = _build_entry_schedule(
        num_agents=config.num_agents,
        num_weeks=config.num_weeks,
        mode=config.agent_entry_mode,
        contract_rate=config.contract_rate,
        rng=rng,
    )

    agents: dict[str, BuyerAgent] = {}
    transaction_log: list[AuctionResult] = []
    weekly_snapshots: list[WeeklySnapshot] = []
    replenished_folio_ids: set[str] = set()
    folio_dom_map: dict[str, int] = {}

    # Index shocks by week
    shocks_by_week: dict[int, list[MacroShock]] = {}
    for shock in config.shocks:
        shocks_by_week.setdefault(shock.week, []).append(shock)

    current_rate = config.contract_rate
    recent_sales_window: list[tuple[float, float]] = []  # (sale_price, asking_at_sale)

    # Initial market context (empty market, no sales yet)
    market_context = _build_context(
        clock=clock,
        inventory=inventory,
        recent_sales=recent_sales_window,
        contract_rate=current_rate,
    )

    # ── Main simulation loop ───────────────────────────────────────────────────
    for week in range(config.num_weeks):

        # ── 1. Macro shocks ──────────────────────────────────────────────────
        for shock in shocks_by_week.get(week, []):
            current_rate = _apply_shock(shock, agents, current_rate, rng)

        # ── 2. Agent entry ────────────────────────────────────────────────────
        for new_agent in entry_schedule.get(week, []):
            agents[new_agent.id] = new_agent

        # Transition ENTERING → SEARCHING
        for agent in agents.values():
            if agent.status == AgentStatus.ENTERING:
                agent.status = AgentStatus.SEARCHING

        # ── 2b. Inventory replenishment ───────────────────────────────────────
        if config.replenishment_rate > 0 and properties:
            expected = len(properties) * config.replenishment_rate
            noise = rng.uniform(-config.replenishment_variance, config.replenishment_variance)
            mu = max(0.0, expected * (1 + noise))
            actual_count = int(rng.poisson(mu))
            for _ in range(actual_count):
                source_prop = properties[int(rng.integers(len(properties)))]
                jitter = rng.uniform(-0.05, 0.05)
                new_assessed = source_prop.assessed_value * (1 + jitter)
                new_folio = f"{source_prop.folio_id}-R{week}"
                # Skip if folio already exists (rare but possible with same source+week)
                if inventory.get_listing(new_folio) is not None:
                    continue
                new_prop = source_prop.model_copy(update={
                    "folio_id": new_folio,
                    "assessed_value": round(new_assessed / 100) * 100,
                })
                markup = config.initial_markup + rng.uniform(
                    -config.markup_variance, config.markup_variance
                )
                markup = max(-0.10, markup)
                asking = round(new_prop.assessed_value * (1 + markup) / 100) * 100
                inventory.add_listing(new_prop, asking, week=week)
                replenished_folio_ids.add(new_folio)

        # ── 3. Inventory tick (DOM + price reductions + expirations) ──────────
        expired_ids = inventory.tick(week)
        # Track DOM for expired properties (DOM at expiry is >= 90)
        for expired_id in expired_ids:
            folio_dom_map[expired_id] = 90  # DEFAULT_EXPIRY_DAYS

        # ── 4. Matching and offer collection ─────────────────────────────────
        active_listings = inventory.get_active_listings()
        offers_by_property: dict[str, list[Offer]] = {}
        offers_this_week = 0

        # Agents in LOST_BID from last week re-enter as SEARCHING
        for agent in agents.values():
            if agent.status == AgentStatus.LOST_BID:
                agent.status = AgentStatus.SEARCHING

        for agent in agents.values():
            if agent.status not in (AgentStatus.SEARCHING, AgentStatus.ADJUSTING):
                continue

            matches = find_matches(agent, active_listings, market_context)
            action = agent_weekly_action(agent, matches, market_context, rng)

            if action.action_type == ActionType.EXIT:
                agent.status = AgentStatus.EXITED

            elif action.action_type == ActionType.ADJUST:
                agent.status = AgentStatus.ADJUSTING

            elif action.action_type == ActionType.BID:
                folio_id = action.target_folio_id
                # Guard: listing must still be active
                if folio_id and inventory.get_listing(folio_id):
                    score_val = _get_match_score(matches, folio_id)
                    offer = Offer(
                        agent_id=agent.id,
                        folio_id=folio_id,
                        amount=action.bid_amount,
                        week=week,
                        property_score=score_val,
                    )
                    offers_by_property.setdefault(folio_id, []).append(offer)
                    agent.status = AgentStatus.BIDDING
                    agent.current_bid_target = folio_id
                    offers_this_week += 1

        # ── 5. Offer resolution ───────────────────────────────────────────────
        sales_this_week = 0

        for folio_id, offers in offers_by_property.items():
            listing = inventory.get_listing(folio_id)
            if listing is None:
                # Expired between tick and resolution — put bidders back
                for offer in offers:
                    a = agents.get(offer.agent_id)
                    if a and a.status == AgentStatus.BIDDING:
                        a.status = AgentStatus.SEARCHING
                        a.current_bid_target = None
                continue

            result = resolve_offers(
                folio_id=folio_id,
                offers=offers,
                listing=listing,
                agents=agents,
                market_context=market_context,
                rng=rng,
            )

            if result.outcome == AuctionOutcome.SOLD and result.winning_offer:
                inventory.mark_sold(
                    folio_id,
                    result.final_price,
                    week,
                    result.winning_offer.agent_id,
                )
                winner_id = result.winning_offer.agent_id

                # Winner
                if winner_id in agents:
                    w = agents[winner_id]
                    w.status = AgentStatus.WON
                    w.current_bid_target = None

                # Losers
                winner_ids = {result.winning_offer.agent_id}
                for offer in result.all_offers:
                    if offer.agent_id not in winner_ids:
                        loser = agents.get(offer.agent_id)
                        if loser and loser.status == AgentStatus.BIDDING:
                            loser.status = AgentStatus.LOST_BID
                            loser.bid_losses += 1
                            loser.current_bid_target = None

                transaction_log.append(result)
                sales_this_week += 1

                # Update recent sales window for next context build
                asking_at_sale = listing.current_asking
                recent_sales_window.append(
                    (result.final_price, asking_at_sale)
                )

            else:
                # Rejected or no offers — all bidders back to searching
                for offer in result.all_offers:
                    loser = agents.get(offer.agent_id)
                    if loser and loser.status == AgentStatus.BIDDING:
                        loser.status = AgentStatus.SEARCHING
                        loser.current_bid_target = None

        # Safety: any agent still stuck in BIDDING at end of week → SEARCHING
        for agent in agents.values():
            if agent.status == AgentStatus.BIDDING:
                agent.status = AgentStatus.SEARCHING
                agent.current_bid_target = None

        # ── 6. State update ───────────────────────────────────────────────────
        # Increment weeks for all non-terminal agents
        for agent in agents.values():
            if agent.status not in (AgentStatus.WON, AgentStatus.EXITED):
                agent.weeks_in_market += 1

        # Expire patience-exhausted agents
        for agent in agents.values():
            if (
                agent.status not in (AgentStatus.WON, AgentStatus.EXITED)
                and agent.weeks_in_market >= agent.behavior.patience_weeks
            ):
                agent.status = AgentStatus.EXITED

        # Keep recent sales window to last 4 weeks
        recent_sales_window = recent_sales_window[-20:]  # At most 20 entries

        # Rebuild market context for next week
        market_context = _build_context(
            clock=clock,
            inventory=inventory,
            recent_sales=recent_sales_window,
            contract_rate=current_rate,
        )

        # ── 7. Weekly snapshot ────────────────────────────────────────────────
        active_buyers = sum(
            1
            for a in agents.values()
            if a.status not in (AgentStatus.WON, AgentStatus.EXITED)
        )
        stats = inventory.get_stats()
        snapshot = WeeklySnapshot(
            week=week,
            active_listings=stats.active_count,
            active_buyers=active_buyers,
            offers_this_week=offers_this_week,
            sales_this_week=sales_this_week,
            expirations_this_week=len(expired_ids),
            avg_sale_price=stats.avg_sale_price,
            avg_days_on_market=stats.avg_days_on_market,
            market_temperature=market_context.market_temperature,
        )
        weekly_snapshots.append(snapshot)
        clock.tick()

    # ── Compile final results ──────────────────────────────────────────────────
    sold_folio_ids = {r.folio_id for r in transaction_log}
    all_folio_ids = {p.folio_id for p in properties} | replenished_folio_ids
    unsold_folio_ids = all_folio_ids - sold_folio_ids

    # Populate folio_dom from sale records and remaining active/unsold listings
    for record in inventory.get_sales():
        folio_dom_map[record.folio_id] = record.days_on_market
    for listing in inventory.get_active_listings():
        folio_dom_map[listing.property.folio_id] = listing.days_on_market
    # Any unsold folio not yet in map (expired at 90)
    for folio_id in unsold_folio_ids:
        if folio_id not in folio_dom_map:
            folio_dom_map[folio_id] = 90

    # Build agent outcomes
    # Map winning agent → transaction for quick lookup
    agent_to_win: dict[str, AuctionResult] = {}
    for result in transaction_log:
        if result.winning_offer:
            agent_to_win[result.winning_offer.agent_id] = result

    # Count bids submitted per agent across all transactions
    agent_bid_count: dict[str, int] = {}
    for result in transaction_log:
        seen_agents: set[str] = set()
        for offer in result.all_offers:
            if offer.agent_id not in seen_agents:
                seen_agents.add(offer.agent_id)
                agent_bid_count[offer.agent_id] = (
                    agent_bid_count.get(offer.agent_id, 0) + 1
                )

    agent_outcomes: dict[str, AgentOutcome] = {}
    for agent_id, agent in agents.items():
        win = agent_to_win.get(agent_id)
        outcome = AgentOutcome(
            agent_id=agent_id,
            household_type=agent.household_type.value,
            final_status=agent.status.value,
            property_purchased=win.folio_id if win else None,
            purchase_price=win.final_price if win else None,
            weeks_to_purchase=win.winning_offer.week if win else None,
            bids_submitted=agent_bid_count.get(agent_id, 0),
            bids_lost=agent.bid_losses,
        )
        agent_outcomes[agent_id] = outcome

    return SimulationResult(
        config=config,
        transactions=transaction_log,
        weekly_snapshots=weekly_snapshots,
        agent_outcomes=agent_outcomes,
        properties_unsold=sorted(unsold_folio_ids),
        properties_sold=sorted(sold_folio_ids),
        total_weeks=config.num_weeks,
        seed=config.seed,
        folio_dom=folio_dom_map,
    )


# ─── Private helpers ──────────────────────────────────────────────────────────

def _build_context(
    clock: SimulationClock,
    inventory: MarketInventory,
    recent_sales: list[tuple[float, float]],  # (sale_price, asking_at_sale)
    contract_rate: float,
) -> MarketContext:
    """Construct MarketContext from current simulation state."""
    stats = inventory.get_stats()

    if recent_sales:
        ratios = [sp / ask for sp, ask in recent_sales if ask > 0]
        avg_ratio = sum(ratios) / len(ratios) if ratios else 1.0
    else:
        avg_ratio = 1.0  # Neutral default

    return MarketContext(
        current_week=clock.current_week,
        contract_rate=contract_rate,
        avg_days_on_market=stats.avg_days_on_market,
        active_listing_count=stats.active_count,
        recent_sale_count=len(recent_sales),
        avg_sale_to_asking_ratio=avg_ratio,
        season=clock.season,
        is_peak_season=clock.is_peak_season,
    )


def _apply_shock(
    shock: MacroShock,
    agents: dict[str, BuyerAgent],
    current_rate: float,
    rng: np.random.Generator,
) -> float:
    """Apply a macro shock and return the (possibly updated) contract rate."""
    if shock.shock_type == ShockType.RATE_CHANGE:
        new_rate = float(shock.params["new_rate"])
        # Requalify all active agents at new rate
        for agent in agents.values():
            if agent.status in (AgentStatus.WON, AgentStatus.EXITED):
                continue
            new_max = calculate_max_purchase_price(
                annual_income=agent.financial.annual_income,
                down_payment=agent.financial.total_down_payment,
                monthly_debts=agent.financial.existing_monthly_debts,
                contract_rate=new_rate,
            )
            agent.preferences = agent.preferences.model_copy(
                update={"max_price": new_max}
            )
        return new_rate

    if shock.shock_type == ShockType.RECESSION:
        income_impact: float = shock.params.get("income_impact", -0.05)
        affected_pct: float = shock.params.get("affected_pct", 0.15)
        active = [
            a for a in agents.values()
            if a.status not in (AgentStatus.WON, AgentStatus.EXITED)
        ]
        n_affected = max(1, int(len(active) * affected_pct))
        if active:
            chosen_indices = rng.choice(
                len(active), size=min(n_affected, len(active)), replace=False
            )
            for idx in chosen_indices:
                a = active[idx]
                new_income = a.financial.annual_income * (1 + income_impact)
                a.financial = a.financial.model_copy(
                    update={"annual_income": max(1.0, new_income)}
                )
                new_max = calculate_max_purchase_price(
                    annual_income=new_income,
                    down_payment=a.financial.total_down_payment,
                    monthly_debts=a.financial.existing_monthly_debts,
                    contract_rate=current_rate,
                )
                a.preferences = a.preferences.model_copy(
                    update={"max_price": new_max}
                )
        return current_rate

    # INVENTORY_SURGE, SEASONAL, POLICY — no agents/rate change implemented yet
    return current_rate


def _build_entry_schedule(
    num_agents: int,
    num_weeks: int,
    mode: str,
    contract_rate: float,
    rng: np.random.Generator,
) -> dict[int, list[BuyerAgent]]:
    """
    Pre-generate all buyer agents and distribute them across weeks.

    front_loaded: 70% enter weeks 0-2, 30% trickle in weeks 3+
    gradual: equal batches each week
    random: Poisson process, guaranteed total = num_agents
    """
    schedule: dict[int, list[BuyerAgent]] = {}

    if mode == "front_loaded":
        front_count = int(num_agents * 0.70)
        back_count = num_agents - front_count

        # Distribute front across weeks 0-2 (roughly equal, remainder to week 0)
        base, rem = divmod(front_count, 3)
        front_per_week = [base + (1 if i < rem else 0) for i in range(3)]
        for w, count in enumerate(front_per_week):
            if count > 0:
                schedule[w] = generate_buyer_pool(count, rng, contract_rate, entry_week=w)

        # Distribute back evenly across weeks 3..num_weeks-1
        remaining_weeks = max(1, num_weeks - 3)
        base_back, rem_back = divmod(back_count, remaining_weeks)
        for w in range(3, num_weeks):
            count = base_back + (1 if (w - 3) < rem_back else 0)
            if count > 0:
                schedule[w] = generate_buyer_pool(count, rng, contract_rate, entry_week=w)

    elif mode == "gradual":
        base, rem = divmod(num_agents, num_weeks)
        for w in range(num_weeks):
            count = base + (1 if w < rem else 0)
            if count > 0:
                schedule[w] = generate_buyer_pool(count, rng, contract_rate, entry_week=w)

    elif mode == "random":
        lam = num_agents / num_weeks
        remaining = num_agents
        for w in range(num_weeks):
            if w == num_weeks - 1:
                count = remaining
            else:
                count = min(remaining, int(rng.poisson(lam)))
            if count > 0:
                schedule[w] = generate_buyer_pool(count, rng, contract_rate, entry_week=w)
                remaining -= count
            if remaining <= 0:
                break

    else:
        raise ValueError(f"Unknown agent_entry_mode: {mode!r}")

    return schedule


def _get_match_score(
    matches: list[tuple[object, object]],
    folio_id: str,
) -> float:
    """Find the PropertyScore.total for a given folio_id in the matches list."""
    for listing, score in matches:  # type: ignore[assignment]
        if hasattr(listing, "property") and listing.property.folio_id == folio_id:  # type: ignore[union-attr]
            return float(score.total)  # type: ignore[union-attr]
    return 50.0
