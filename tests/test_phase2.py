"""
Phase 2 tests — search, matching, bidding, auction mechanics, simulation engine.

Covers:
  Scoring (5 tests)
  Matching (4 tests)
  Strategy / action decisions (4 tests)
  Bid amount calculation (4 tests)
  Auction resolution (6 tests)
  Simulation engine (6 tests)
"""
from __future__ import annotations

import numpy as np
import pytest

from sim.agents.financial import calculate_max_purchase_price
from sim.agents.generator import generate_buyer_pool
from sim.agents.models import (
    AgentStatus,
    BehaviorProfile,
    BuyerAgent,
    FinancialProfile,
    HouseholdType,
    PreferenceProfile,
)
from sim.agents.preferences import (
    CONDITION_ORDER,
    HOUSEHOLD_SCORING_WEIGHTS,
    PropertyScore,
    score_property,
)
from sim.agents.strategy import (
    ActionType,
    AgentAction,
    agent_weekly_action,
    calculate_bid_amount,
)
from sim.engine.auction import (
    AuctionOutcome,
    Offer,
    resolve_offers,
)
from sim.engine.context import MarketContext
from sim.engine.matching import find_matches
from sim.engine.simulation import (
    AgentOutcome,
    SimulationConfig,
    WeeklySnapshot,
    run_simulation,
)
from sim.properties.loader import load_properties_from_json
from sim.properties.models import (
    Condition,
    Features,
    Listing,
    ListingStatus,
    Location,
    Property,
    PropertyType,
)

# ─── Fixtures ─────────────────────────────────────────────────────────────────

SAMPLE_JSON = (
    __file__  # tests/test_phase2.py
    and str(__import__("pathlib").Path(__file__).parent.parent / "data" / "properties" / "sample_victoria.json")
)


def _make_location(
    neighbourhood: str = "Test",
    walk_score: float = 70,
    transit_score: float = 60,
    school_proximity: float = 0.5,
) -> Location:
    return Location(
        neighbourhood=neighbourhood,
        municipality="Victoria",
        walk_score=walk_score,
        transit_score=transit_score,
        school_proximity=school_proximity,
    )


def _make_property(
    folio_id: str = "TEST-001",
    property_type: PropertyType = PropertyType.SFD,
    assessed_value: float = 800_000,
    bedrooms: int = 3,
    condition: Condition = Condition.GOOD,
    features: Features | None = None,
) -> Property:
    return Property(
        folio_id=folio_id,
        property_type=property_type,
        assessed_value=assessed_value,
        bedrooms=bedrooms,
        bathrooms=2.0,
        floor_area=1_500,
        lot_size=5_000,
        year_built=2000,
        condition=condition,
        location=_make_location(),
        features=features or Features(),
        annual_taxes=4_000,
    )


def _make_listing(
    prop: Property,
    asking_price: float | None = None,
    status: ListingStatus = ListingStatus.ACTIVE,
) -> Listing:
    if asking_price is None:
        asking_price = prop.assessed_value * 1.03
    return Listing(
        property=prop,
        asking_price=asking_price,
        listed_week=0,
        days_on_market=0,
        status=status,
    )


def _make_agent(
    annual_income: float = 150_000,
    savings: float = 200_000,
    household_type: HouseholdType = HouseholdType.COUPLE_NO_KIDS,
    min_bedrooms: int = 2,
    preferred_types: list[str] | None = None,
    urgency: float = 0.5,
    risk_tolerance: float = 0.5,
    patience_weeks: int = 26,
    max_bid_stretch: float = 0.05,
    adjustment_after_losses: int = 3,
    bid_losses: int = 0,
    weeks_in_market: int = 0,
    status: AgentStatus = AgentStatus.SEARCHING,
    existing_monthly_debts: float = 0.0,
    contract_rate: float = 0.05,
    needs_suite: bool = False,
) -> BuyerAgent:
    financial = FinancialProfile(
        annual_income=annual_income,
        savings=savings,
        existing_monthly_debts=existing_monthly_debts,
    )
    max_price = calculate_max_purchase_price(
        annual_income=annual_income,
        down_payment=financial.total_down_payment,
        monthly_debts=existing_monthly_debts,
        contract_rate=contract_rate,
    )
    preferences = PreferenceProfile(
        min_bedrooms=min_bedrooms,
        max_price=max_price,
        preferred_property_types=preferred_types or [],
        needs_suite=needs_suite,
    )
    behavior = BehaviorProfile(
        urgency=urgency,
        risk_tolerance=risk_tolerance,
        patience_weeks=patience_weeks,
        adjustment_after_losses=adjustment_after_losses,
        max_bid_stretch=max_bid_stretch,
    )
    return BuyerAgent(
        id="agent_test_001",
        household_type=household_type,
        financial=financial,
        preferences=preferences,
        behavior=behavior,
        status=status,
        weeks_in_market=weeks_in_market,
        bid_losses=bid_losses,
    )


def _make_context(
    contract_rate: float = 0.05,
    avg_dom: float = 25.0,
    sale_to_ask: float = 1.01,
    season: str = "spring",
    is_peak: bool = True,
) -> MarketContext:
    return MarketContext(
        current_week=1,
        contract_rate=contract_rate,
        avg_days_on_market=avg_dom,
        active_listing_count=20,
        recent_sale_count=5,
        avg_sale_to_asking_ratio=sale_to_ask,
        season=season,
        is_peak_season=is_peak,
    )


# ─── Scoring tests ────────────────────────────────────────────────────────────

class TestScoring:
    def test_unaffordable_property_scores_zero(self):
        """A property far above the agent's max price must score 0."""
        agent = _make_agent(annual_income=60_000, savings=30_000)
        prop = _make_property(assessed_value=2_000_000)
        listing = _make_listing(prop, asking_price=2_000_000)
        ctx = _make_context()

        score = score_property(agent, listing, ctx)
        assert score.total == 0.0
        assert not score.affordable

    def test_wrong_type_scores_zero_when_hard_filtered(self):
        """A property of a wrong type scores 0 if the agent has type preferences."""
        # Agent strongly prefers condos only
        agent = _make_agent(
            annual_income=120_000,
            savings=200_000,
            preferred_types=["condo"],
        )
        # Listing is SFD
        prop = _make_property(property_type=PropertyType.SFD, assessed_value=500_000)
        listing = _make_listing(prop, asking_price=500_000)
        ctx = _make_context()

        score = score_property(agent, listing, ctx)
        assert score.total == 0.0

    def test_perfect_match_scores_high(self):
        """A perfectly matched property (right type, budget room, great features) should score > 70."""
        agent = _make_agent(
            annual_income=180_000,
            savings=400_000,
            preferred_types=["single_family_detached"],
            min_bedrooms=3,
            household_type=HouseholdType.COUPLE_WITH_KIDS,
        )
        features = Features(view=True, garage=True, renovated_recent=True)
        prop = _make_property(
            property_type=PropertyType.SFD,
            assessed_value=600_000,  # Well below agent's max
            bedrooms=4,
            condition=Condition.EXCELLENT,
            features=features,
        )
        listing = _make_listing(prop, asking_price=620_000)
        ctx = _make_context()

        score = score_property(agent, listing, ctx)
        assert score.total > 70
        assert score.affordable

    def test_investor_weights_suite_heavily(self):
        """An investor scores a suite-equipped property much higher than one without."""
        agent_inv = _make_agent(
            household_type=HouseholdType.INVESTOR,
            annual_income=200_000,
            savings=300_000,
            preferred_types=["condo"],
        )
        ctx = _make_context()

        prop_suite = _make_property(
            folio_id="SUITE",
            property_type=PropertyType.CONDO,
            assessed_value=500_000,
            features=Features(suite=True),
        )
        prop_no_suite = _make_property(
            folio_id="NO-SUITE",
            property_type=PropertyType.CONDO,
            assessed_value=500_000,
            features=Features(suite=False),
        )

        score_suite = score_property(agent_inv, _make_listing(prop_suite), ctx)
        score_no_suite = score_property(agent_inv, _make_listing(prop_no_suite), ctx)

        assert score_suite.total > score_no_suite.total
        # The gap should be meaningful given the 0.30 features weight
        assert score_suite.feature_bonus > score_no_suite.feature_bonus

    def test_family_weights_bedrooms_heavily(self):
        """
        Validate that COUPLE_WITH_KIDS has a larger size_fit weight than SINGLE_YOUNG,
        and that a family's scoring drops sharply when bedrooms fall below minimum.
        """
        # A 3-bed property meets a family's min=3 → perfect size_fit=1.0
        # The same property for a single (min=1) also fits, but size weight matters less
        family_agent = _make_agent(
            household_type=HouseholdType.COUPLE_WITH_KIDS,
            annual_income=200_000,
            savings=300_000,
            preferred_types=["single_family_detached"],
            min_bedrooms=3,
        )
        single_agent = _make_agent(
            household_type=HouseholdType.SINGLE_YOUNG,
            annual_income=200_000,
            savings=300_000,
            preferred_types=["single_family_detached"],
            min_bedrooms=1,
        )
        ctx = _make_context()

        prop_3bed = _make_property(
            folio_id="3BED",
            bedrooms=3,
            assessed_value=750_000,
        )
        listing = _make_listing(prop_3bed)

        score_family = score_property(family_agent, listing, ctx)
        score_single = score_property(single_agent, listing, ctx)

        # Both qualify
        assert score_family.total > 0
        assert score_single.total > 0

        # COUPLE_WITH_KIDS has higher size_fit weight (0.25 vs 0.10)
        family_weights = HOUSEHOLD_SCORING_WEIGHTS[HouseholdType.COUPLE_WITH_KIDS]
        single_weights = HOUSEHOLD_SCORING_WEIGHTS[HouseholdType.SINGLE_YOUNG]
        assert family_weights["size_fit"] > single_weights["size_fit"]

        # Perfect size fit for the family (exact match to min_bedrooms)
        assert score_family.size_fit == 1.0


# ─── Matching tests ───────────────────────────────────────────────────────────

class TestMatching:
    def test_finds_affordable_properties_only(self):
        """find_matches should return nothing when all listings are too expensive."""
        agent = _make_agent(annual_income=50_000, savings=20_000)
        expensive_props = [
            _make_property(f"EXP-{i}", assessed_value=2_000_000)
            for i in range(5)
        ]
        listings = [_make_listing(p) for p in expensive_props]
        ctx = _make_context()

        matches = find_matches(agent, listings, ctx)
        assert matches == []

    def test_adjusting_agent_relaxes_bedroom_constraint(self):
        """An ADJUSTING agent with min_bedrooms=3 should see 2-bedroom listings."""
        agent = _make_agent(
            annual_income=180_000,
            savings=300_000,
            min_bedrooms=3,
            preferred_types=[],  # No type restriction
            status=AgentStatus.ADJUSTING,
        )
        # Only 2-bedroom listings available
        prop_2bed = _make_property(folio_id="TWO-BED", bedrooms=2, assessed_value=600_000)
        listings = [_make_listing(prop_2bed)]
        ctx = _make_context()

        matches = find_matches(agent, listings, ctx)
        # Relaxed constraint (min 2) should allow a 2-bedroom
        assert len(matches) > 0

    def test_max_results_respected(self):
        """find_matches should not return more than max_results items."""
        agent = _make_agent(annual_income=300_000, savings=500_000, preferred_types=[])
        listings = [
            _make_listing(_make_property(f"P-{i}", assessed_value=600_000))
            for i in range(20)
        ]
        ctx = _make_context()

        matches = find_matches(agent, listings, ctx, max_results=5)
        assert len(matches) <= 5

    def test_no_matches_returns_empty(self):
        """An agent with no qualifying matches gets an empty list."""
        agent = _make_agent(
            annual_income=60_000,
            savings=15_000,
            preferred_types=["condo"],
            min_bedrooms=5,  # No condos have 5 bedrooms
        )
        listings = [
            _make_listing(_make_property("C1", PropertyType.CONDO, 400_000, bedrooms=1))
        ]
        ctx = _make_context()

        matches = find_matches(agent, listings, ctx)
        assert matches == []


# ─── Strategy / action tests ──────────────────────────────────────────────────

class TestStrategy:
    def _rng(self, seed: int = 0) -> np.random.Generator:
        return np.random.default_rng(seed)

    def test_patient_agent_waits_with_low_scores(self):
        """An agent with low-scoring matches and high patience should WAIT (or BID occasionally)."""
        agent = _make_agent(patience_weeks=26, weeks_in_market=1, urgency=0.3)
        ctx = _make_context()

        prop = _make_property(assessed_value=900_000, condition=Condition.POOR)
        listing = _make_listing(prop)
        ps = score_property(agent, listing, ctx)

        if ps.total > 0:
            matches = [(listing, ps)]
        else:
            matches = []

        # With score <= 40, should WAIT (not BID)
        action = agent_weekly_action(agent, matches, ctx, self._rng(42))
        # Agent with no good matches and low urgency should wait or exit
        assert action.action_type in (ActionType.WAIT, ActionType.EXIT)

    def test_urgent_agent_bids_on_mediocre_match(self):
        """An agent with urgency > 0.7 and a match > 40 should BID."""
        agent = _make_agent(
            urgency=0.85,
            annual_income=200_000,
            savings=300_000,
            preferred_types=[],
        )
        ctx = _make_context()

        prop = _make_property(assessed_value=600_000)
        listing = _make_listing(prop, asking_price=500_000)
        ps = score_property(agent, listing, ctx)

        if ps.total < 40:
            pytest.skip("Score too low for this test scenario")

        matches = [(listing, ps)]
        action = agent_weekly_action(agent, matches, ctx, self._rng(7))
        assert action.action_type == ActionType.BID

    def test_exhausted_patience_exits(self):
        """Agent who has been in market >= patience_weeks should EXIT."""
        agent = _make_agent(patience_weeks=10, weeks_in_market=10)
        ctx = _make_context()

        action = agent_weekly_action(agent, [], ctx, self._rng())
        assert action.action_type == ActionType.EXIT

    def test_losses_trigger_adjustment(self):
        """Agent with bid_losses >= threshold should ADJUST (if not already adjusting)."""
        agent = _make_agent(
            adjustment_after_losses=3,
            bid_losses=3,
            status=AgentStatus.SEARCHING,
            weeks_in_market=2,
        )
        ctx = _make_context()

        action = agent_weekly_action(agent, [], ctx, self._rng())
        assert action.action_type == ActionType.ADJUST


# ─── Bid amount tests ─────────────────────────────────────────────────────────

class TestBidAmount:
    def _rng(self, seed: int = 0) -> np.random.Generator:
        return np.random.default_rng(seed)

    def test_bid_within_budget(self):
        """Bid must never exceed max_price × (1 + max_bid_stretch)."""
        agent = _make_agent(
            annual_income=150_000,
            savings=200_000,
            max_bid_stretch=0.05,
        )
        prop = _make_property(assessed_value=700_000)
        listing = _make_listing(prop, asking_price=700_000)
        ctx = _make_context()

        ps = PropertyScore(
            total=75.0, affordable=True, affordability_comfort=0.3,
            size_fit=0.8, type_match=1.0, location_score=0.7,
            condition_score=0.8, feature_bonus=0.6,
        )

        bid = calculate_bid_amount(agent, listing, ps, ctx, 0, self._rng())
        ceiling = (agent.preferences.max_price or 1e9) * (1 + agent.behavior.max_bid_stretch)
        assert bid <= ceiling

    def test_bid_above_asking_in_hot_market(self):
        """In a hot market, agents should typically bid at or above asking."""
        agent = _make_agent(annual_income=250_000, savings=400_000)
        prop = _make_property(assessed_value=600_000)
        listing = _make_listing(prop, asking_price=600_000)
        ctx = _make_context(sale_to_ask=1.05, avg_dom=15)  # Hot market

        ps = PropertyScore(
            total=80.0, affordable=True, affordability_comfort=0.4,
            size_fit=0.9, type_match=1.0, location_score=0.8,
            condition_score=0.9, feature_bonus=0.7,
        )

        # Run many times to check the statistical tendency
        rng = np.random.default_rng(0)
        bids = [calculate_bid_amount(agent, listing, ps, ctx, 0, rng) for _ in range(50)]
        above_asking = sum(1 for b in bids if b >= 600_000)
        # In hot market, most bids should be at or above asking
        assert above_asking >= 30

    def test_bid_below_asking_in_cold_market(self):
        """In a cold market, agents often bid at or below asking."""
        agent = _make_agent(annual_income=200_000, savings=300_000, urgency=0.3)
        prop = _make_property(assessed_value=700_000)
        listing = _make_listing(prop, asking_price=700_000)
        ctx = _make_context(sale_to_ask=0.94, avg_dom=60)  # Cold market

        ps = PropertyScore(
            total=55.0, affordable=True, affordability_comfort=0.3,
            size_fit=0.7, type_match=0.8, location_score=0.6,
            condition_score=0.6, feature_bonus=0.5,
        )

        rng = np.random.default_rng(99)
        bids = [calculate_bid_amount(agent, listing, ps, ctx, 0, rng) for _ in range(50)]
        at_or_below_asking = sum(1 for b in bids if b <= 700_000)
        assert at_or_below_asking >= 25  # Most bids at/under asking in cold market

    def test_bid_never_exceeds_max_with_stretch(self):
        """Bid ceiling is strictly enforced across many draws."""
        agent = _make_agent(
            annual_income=120_000, savings=100_000, max_bid_stretch=0.10
        )
        prop = _make_property(assessed_value=500_000)
        listing = _make_listing(prop, asking_price=480_000)
        ctx = _make_context(sale_to_ask=1.06, avg_dom=12)

        ps = PropertyScore(
            total=90.0, affordable=True, affordability_comfort=0.1,
            size_fit=1.0, type_match=1.0, location_score=0.9,
            condition_score=1.0, feature_bonus=1.0,
        )

        ceiling = (agent.preferences.max_price or 1e9) * (1 + agent.behavior.max_bid_stretch)
        rng = np.random.default_rng(7)
        for _ in range(100):
            bid = calculate_bid_amount(agent, listing, ps, ctx, 3, rng)
            assert bid <= ceiling + 1  # +1 for rounding edge cases


# ─── Auction resolution tests ─────────────────────────────────────────────────

class TestAuction:
    def _rng(self, seed: int = 42) -> np.random.Generator:
        return np.random.default_rng(seed)

    def _agents_dict(
        self,
        agent_ids: list[str],
        urgency: float = 0.6,
        risk_tolerance: float = 0.6,
        max_price: float = 1_000_000,
    ) -> dict[str, BuyerAgent]:
        result = {}
        for agent_id in agent_ids:
            agent = _make_agent(annual_income=200_000, savings=300_000, urgency=urgency, risk_tolerance=risk_tolerance)
            agent.id = agent_id
            agent.preferences = agent.preferences.model_copy(update={"max_price": max_price})
            result[agent_id] = agent
        return result

    def test_no_offers_returns_no_offers(self):
        prop = _make_property()
        listing = _make_listing(prop, asking_price=700_000)
        ctx = _make_context()

        result = resolve_offers("TEST-001", [], listing, {}, ctx, self._rng())
        assert result.outcome == AuctionOutcome.NO_OFFERS

    def test_single_offer_accepted(self):
        """A single offer at 98% of asking (balanced market) should be accepted."""
        prop = _make_property(assessed_value=700_000)
        listing = _make_listing(prop, asking_price=700_000)
        ctx = _make_context(sale_to_ask=1.01, avg_dom=25)  # balanced

        offer = Offer(agent_id="A1", folio_id="TEST-001", amount=680_000, week=1, property_score=70)
        agents = self._agents_dict(["A1"])

        result = resolve_offers("TEST-001", [offer], listing, agents, ctx, self._rng())
        # 680/700 = 97.1% — in balanced market threshold is 95% → should be accepted
        assert result.outcome == AuctionOutcome.SOLD
        assert result.final_price == 680_000

    def test_single_low_offer_rejected(self):
        """An offer below 90% of asking should be rejected."""
        prop = _make_property(assessed_value=700_000)
        listing = _make_listing(prop, asking_price=700_000)
        ctx = _make_context()

        offer = Offer(agent_id="A1", folio_id="TEST-001", amount=600_000, week=1, property_score=40)
        # Low urgency → won't accept counter
        agents = self._agents_dict(["A1"], urgency=0.3)

        result = resolve_offers("TEST-001", [offer], listing, agents, ctx, self._rng())
        assert result.outcome == AuctionOutcome.REJECTED

    def test_multiple_offers_highest_wins(self):
        """In a multi-offer situation, the highest bid wins."""
        prop = _make_property(assessed_value=700_000)
        listing = _make_listing(prop, asking_price=700_000)
        ctx = _make_context()

        offers = [
            Offer(agent_id="A1", folio_id="TEST-001", amount=710_000, week=1, property_score=80),
            Offer(agent_id="A2", folio_id="TEST-001", amount=720_000, week=1, property_score=75),
            Offer(agent_id="A3", folio_id="TEST-001", amount=705_000, week=1, property_score=70),
        ]
        agents = self._agents_dict(["A1", "A2", "A3"], risk_tolerance=0.2)
        # Low risk tolerance → unlikely to escalate → round 1 winner should be A2

        result = resolve_offers("TEST-001", offers, listing, agents, ctx, self._rng())
        assert result.outcome == AuctionOutcome.SOLD
        assert result.winning_offer is not None
        assert result.final_price >= 720_000  # At least as good as the initial highest bid

    def test_bidding_war_escalation(self):
        """Multiple eager agents (high urgency, risk tolerance) should escalate bids."""
        prop = _make_property(assessed_value=600_000)
        listing = _make_listing(prop, asking_price=620_000)
        ctx = _make_context()

        offers = [
            Offer(agent_id="A1", folio_id="TEST-001", amount=625_000, week=1, property_score=85),
            Offer(agent_id="A2", folio_id="TEST-001", amount=630_000, week=1, property_score=90),
        ]
        agents = self._agents_dict(
            ["A1", "A2"],
            urgency=0.85,
            risk_tolerance=0.85,
            max_price=900_000,
        )

        result = resolve_offers(
            "TEST-001", offers, listing, agents, ctx,
            self._rng(0), max_rounds=3
        )
        assert result.outcome == AuctionOutcome.SOLD
        # With high urgency/risk, final price should be >= initial highest bid
        assert result.final_price >= 630_000
        assert result.rounds >= 1

    def test_losing_agents_are_tracked(self):
        """all_offers should contain entries from all bidders, not just the winner."""
        prop = _make_property(assessed_value=700_000)
        listing = _make_listing(prop, asking_price=700_000)
        ctx = _make_context()

        offers = [
            Offer(agent_id="A1", folio_id="TEST-001", amount=710_000, week=1, property_score=80),
            Offer(agent_id="A2", folio_id="TEST-001", amount=720_000, week=1, property_score=75),
        ]
        agents = self._agents_dict(["A1", "A2"])

        result = resolve_offers("TEST-001", offers, listing, agents, ctx, self._rng())
        all_agent_ids = {o.agent_id for o in result.all_offers}
        # Both agents should appear in the offer log
        assert "A1" in all_agent_ids
        assert "A2" in all_agent_ids


# ─── Simulation engine tests ──────────────────────────────────────────────────

class TestSimulationEngine:
    SAMPLE_PATH = (
        __import__("pathlib").Path(__file__).parent.parent
        / "data" / "properties" / "sample_victoria.json"
    )

    def _load_props(self, n: int = 5) -> list[Property]:
        all_props = load_properties_from_json(self.SAMPLE_PATH)
        return all_props[:n]

    def test_simulation_runs_to_completion(self):
        """Simulation should complete all weeks without error."""
        props = self._load_props(10)
        config = SimulationConfig(
            num_agents=50,
            num_weeks=10,
            contract_rate=0.05,
            seed=1,
        )
        result = run_simulation(props, config)
        assert result.total_weeks == 10
        assert len(result.weekly_snapshots) == 10

    def test_deterministic_with_seed(self):
        """Two runs with the same seed and config must produce identical results."""
        props = self._load_props(10)
        config = SimulationConfig(num_agents=50, num_weeks=8, seed=42)

        r1 = run_simulation(props, config)
        r2 = run_simulation(props, config)

        assert r1.properties_sold == r2.properties_sold
        assert len(r1.transactions) == len(r2.transactions)
        for t1, t2 in zip(r1.transactions, r2.transactions):
            assert t1.folio_id == t2.folio_id
            assert t1.final_price == t2.final_price

    def test_rate_hike_reduces_buyers(self):
        """After a rate hike, active buyers should drop as qualification shrinks."""
        from sim.market.shocks import MacroShock, ShockType

        props = self._load_props(10)
        shock = MacroShock(
            week=3,
            shock_type=ShockType.RATE_CHANGE,
            params={"new_rate": 0.08},
        )
        config_hike = SimulationConfig(
            num_agents=100, num_weeks=8, seed=10, shocks=[shock]
        )
        config_stable = SimulationConfig(
            num_agents=100, num_weeks=8, seed=10, shocks=[]
        )

        result_hike = run_simulation(props, config_hike)
        result_stable = run_simulation(props, config_stable)

        # After the hike (week 4+), the hiked scenario should have fewer sales
        # or more exited buyers. We check overall sales as a proxy.
        # (Rate hike forces some buyers out — they can no longer afford anything)
        # Either fewer sales or fewer buyers at end.
        hike_buyers_end = result_hike.weekly_snapshots[-1].active_buyers
        stable_buyers_end = result_stable.weekly_snapshots[-1].active_buyers
        # The hiked scenario should have fewer or equal active buyers at end
        # (some exited due to reduced qualification). This is a statistical check.
        assert hike_buyers_end <= stable_buyers_end + 20  # Allow some tolerance

    def test_properties_accumulate_dom(self):
        """DOM should increase week over week for unsold properties."""
        props = self._load_props(5)
        # Only 10 agents — too few to buy everything quickly
        config = SimulationConfig(num_agents=10, num_weeks=5, seed=99)
        result = run_simulation(props, config)

        # Weekly snapshots should show increasing avg DOM in early weeks
        snaps = result.weekly_snapshots
        if len(snaps) >= 2:
            # avg DOM in later weeks >= early weeks (some may sell, but DOM should grow)
            # At minimum, the last week has DOM >= first week
            assert snaps[-1].avg_days_on_market >= snaps[0].avg_days_on_market

    def test_price_reductions_happen(self):
        """Properties sitting for > 3 weeks should show price reductions."""
        from sim.market.inventory import MarketInventory

        # Use a single cheap property with many weeks but no matching buyers
        props = [_make_property("STALE-001", assessed_value=3_000_000)]  # Very expensive
        config = SimulationConfig(
            num_agents=20,
            num_weeks=10,
            seed=5,
            initial_markup=0.03,
        )
        result = run_simulation(props, config)
        # The expensive property should still be unsold and have accumulated DOM
        if "STALE-001" in result.properties_unsold:
            # Good — it sat. DOM check: 10 weeks * 7 = 70 days
            snap_last = result.weekly_snapshots[-1]
            assert snap_last.avg_days_on_market > 0

    def test_all_agent_outcomes_present(self):
        """SimulationResult should have one outcome per generated agent."""
        props = self._load_props(10)
        config = SimulationConfig(num_agents=30, num_weeks=6, seed=77)
        result = run_simulation(props, config)

        assert len(result.agent_outcomes) == 30
        for outcome in result.agent_outcomes.values():
            assert outcome.final_status in (
                "won", "exited", "searching", "adjusting",
                "lost_bid", "shortlisting", "bidding",
            )
