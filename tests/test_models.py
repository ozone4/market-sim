"""
Tests for core data models: Property, Listing, BuyerAgent, and FinancialProfile.

Validates model construction, computed properties, and state transitions.
"""
import pytest

from sim.agents.models import (
    AgentStatus,
    BehaviorProfile,
    BuyerAgent,
    FinancialProfile,
    HouseholdType,
    PreferenceProfile,
)
from sim.properties.models import (
    Condition,
    Features,
    Listing,
    ListingStatus,
    Location,
    PriceReduction,
    Property,
    PropertyType,
)


# ─── Property model ───────────────────────────────────────────────────────────

def test_property_creation():
    """Minimal property can be created with required fields."""
    prop = Property(
        folio_id="TEST-001",
        property_type=PropertyType.SFD,
        assessed_value=900_000,
        bedrooms=3,
        bathrooms=2.0,
        floor_area=1800,
        lot_size=6000,
        year_built=1990,
        condition=Condition.AVERAGE,
        location=Location(neighbourhood="Oak Bay"),
    )
    assert prop.folio_id == "TEST-001"
    assert prop.assessed_value == 900_000
    assert prop.features.view is False  # Default Features


def test_property_with_features():
    """Property accepts and stores Features object."""
    prop = Property(
        folio_id="F-001",
        property_type=PropertyType.CONDO,
        assessed_value=600_000,
        bedrooms=2,
        bathrooms=1.0,
        floor_area=900,
        lot_size=0,
        year_built=2015,
        condition=Condition.EXCELLENT,
        location=Location(neighbourhood="Langford"),
        features=Features(view=True, garage=True, suite=False),
    )
    assert prop.features.view is True
    assert prop.features.garage is True


def test_property_type_enum():
    """PropertyType enum values match expected strings."""
    assert PropertyType.SFD == "single_family_detached"
    assert PropertyType.CONDO == "condo"
    assert PropertyType.TOWNHOUSE == "townhouse"
    assert PropertyType.DUPLEX == "duplex"
    assert PropertyType.MANUFACTURED == "manufactured"


def test_condition_enum():
    """Condition enum values match expected strings."""
    assert Condition.POOR == "poor"
    assert Condition.EXCELLENT == "excellent"


# ─── Listing model ────────────────────────────────────────────────────────────

def _make_listing(asking: float = 800_000) -> Listing:
    return Listing(
        property=Property(
            folio_id="L-001",
            property_type=PropertyType.SFD,
            assessed_value=780_000,
            bedrooms=3,
            bathrooms=2.0,
            floor_area=1700,
            lot_size=5500,
            year_built=1985,
            condition=Condition.GOOD,
            location=Location(neighbourhood="Saanich East"),
        ),
        asking_price=asking,
    )


def test_listing_current_asking_no_reductions():
    """Without reductions, current_asking equals asking_price."""
    listing = _make_listing(800_000)
    assert listing.current_asking == 800_000


def test_listing_current_asking_after_reduction():
    """current_asking reflects the most recent price reduction."""
    listing = _make_listing(800_000)
    listing.price_reductions.append(
        PriceReduction(week=4, old_price=800_000, new_price=784_000)
    )
    assert listing.current_asking == 784_000


def test_listing_current_asking_after_multiple_reductions():
    """current_asking is the last reduction's new_price."""
    listing = _make_listing(800_000)
    listing.price_reductions.append(
        PriceReduction(week=4, old_price=800_000, new_price=784_000)
    )
    listing.price_reductions.append(
        PriceReduction(week=7, old_price=784_000, new_price=760_000)
    )
    assert listing.current_asking == 760_000


def test_listing_status_default():
    """New listing starts as ACTIVE."""
    listing = _make_listing()
    assert listing.status == ListingStatus.ACTIVE


def test_listing_status_enum():
    """ListingStatus enum values are correct."""
    assert ListingStatus.ACTIVE == "active"
    assert ListingStatus.SOLD == "sold"
    assert ListingStatus.EXPIRED == "expired"


# ─── FinancialProfile ─────────────────────────────────────────────────────────

def test_agent_equity_calculation():
    """available_equity deducts 7% selling costs from net equity."""
    profile = FinancialProfile(
        annual_income=120_000,
        savings=50_000,
        current_home_value=600_000,
        current_mortgage_balance=200_000,
    )
    # Net equity before costs: 400K
    # After 7% costs: 400K * 0.93 = 372K
    assert profile.available_equity == pytest.approx(372_000)


def test_agent_equity_zero_when_no_home():
    """available_equity is 0 when current_home_value is 0."""
    profile = FinancialProfile(annual_income=100_000, savings=80_000)
    assert profile.available_equity == 0.0


def test_agent_equity_non_negative():
    """available_equity cannot be negative (mortgage exceeds home value)."""
    profile = FinancialProfile(
        annual_income=100_000,
        savings=50_000,
        current_home_value=400_000,
        current_mortgage_balance=500_000,  # Underwater
    )
    assert profile.available_equity == 0.0


def test_total_down_payment_renter():
    """For a renter, total_down_payment equals savings."""
    profile = FinancialProfile(annual_income=90_000, savings=75_000)
    assert profile.total_down_payment == pytest.approx(75_000)


def test_total_down_payment_with_equity():
    """total_down_payment = savings + available_equity."""
    profile = FinancialProfile(
        annual_income=100_000,
        savings=50_000,
        current_home_value=500_000,
        current_mortgage_balance=200_000,
    )
    # equity = 300K * 0.93 = 279K
    expected = 50_000 + 300_000 * 0.93
    assert profile.total_down_payment == pytest.approx(expected)


# ─── BuyerAgent model ─────────────────────────────────────────────────────────

def _make_agent(status: AgentStatus = AgentStatus.ENTERING) -> BuyerAgent:
    return BuyerAgent(
        id="agent_001",
        household_type=HouseholdType.COUPLE_WITH_KIDS,
        financial=FinancialProfile(annual_income=130_000, savings=80_000),
        preferences=PreferenceProfile(min_bedrooms=3, max_price=800_000),
        behavior=BehaviorProfile(urgency=0.6, patience_weeks=24),
        status=status,
    )


def test_agent_status_transitions():
    """Agent status can be changed (mutable state)."""
    agent = _make_agent(AgentStatus.ENTERING)
    assert agent.status == AgentStatus.ENTERING
    agent.status = AgentStatus.SEARCHING
    assert agent.status == AgentStatus.SEARCHING
    agent.status = AgentStatus.BIDDING
    assert agent.status == AgentStatus.BIDDING


def test_agent_default_state():
    """Freshly created agent has zeroed counters."""
    agent = _make_agent()
    assert agent.weeks_in_market == 0
    assert agent.bid_losses == 0
    assert agent.properties_viewed == []
    assert agent.current_bid_target is None


def test_agent_household_type_enum():
    """HouseholdType enum values are correct strings."""
    assert HouseholdType.INVESTOR == "investor"
    assert HouseholdType.RETIREE == "retiree"
    assert HouseholdType.DOWNSIZER == "downsizer"


def test_preference_profile_defaults():
    """PreferenceProfile defaults are sensible."""
    pref = PreferenceProfile()
    assert pref.min_bedrooms == 1
    assert pref.max_price is None
    assert pref.preferred_property_types == []
    assert pref.preferred_neighbourhoods == []
    assert pref.needs_garage is False
    assert pref.needs_suite is False


def test_behavior_profile_bounds_validation():
    """BehaviorProfile rejects urgency/risk_tolerance outside [0, 1]."""
    with pytest.raises(Exception):
        BehaviorProfile(urgency=1.5)
    with pytest.raises(Exception):
        BehaviorProfile(risk_tolerance=-0.1)
