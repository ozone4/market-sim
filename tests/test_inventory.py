"""
Tests for MarketInventory — listing lifecycle, DOM tracking, price reductions,
expirations, and market statistics.
"""
import pytest

from sim.market.inventory import MarketInventory, SaleRecord
from sim.properties.models import (
    Condition,
    Features,
    Listing,
    ListingStatus,
    Location,
    Property,
    PropertyType,
)


def make_property(folio_id: str = "TEST-001", assessed: float = 800_000) -> Property:
    """Construct a minimal test Property."""
    return Property(
        folio_id=folio_id,
        property_type=PropertyType.SFD,
        assessed_value=assessed,
        bedrooms=3,
        bathrooms=2.0,
        floor_area=1800,
        lot_size=6000,
        year_built=1990,
        condition=Condition.AVERAGE,
        location=Location(neighbourhood="Test", municipality="Victoria"),
    )


# ─── Add and retrieve ────────────────────────────────────────────────────────

def test_add_and_retrieve_listing():
    """Adding a listing makes it appear in active listings."""
    inv = MarketInventory()
    prop = make_property()
    inv.add_listing(prop, asking_price=850_000, week=1)
    active = inv.get_active_listings()
    assert len(active) == 1
    assert active[0].property.folio_id == "TEST-001"
    assert active[0].asking_price == 850_000


def test_add_listing_duplicate_raises():
    """Adding the same folio_id twice raises ValueError."""
    inv = MarketInventory()
    prop = make_property()
    inv.add_listing(prop, 850_000, week=1)
    with pytest.raises(ValueError, match="already listed"):
        inv.add_listing(prop, 860_000, week=1)


def test_get_listing_by_folio():
    """get_listing returns the correct listing for a folio_id."""
    inv = MarketInventory()
    prop = make_property("FIND-ME", 500_000)
    inv.add_listing(prop, 520_000, week=1)
    listing = inv.get_listing("FIND-ME")
    assert listing is not None
    assert listing.asking_price == 520_000


def test_get_listing_missing_returns_none():
    """get_listing returns None for unknown folio_id."""
    inv = MarketInventory()
    assert inv.get_listing("NOPE") is None


# ─── Mark sold ───────────────────────────────────────────────────────────────

def test_mark_sold_removes_from_active():
    """Marking a listing sold removes it from active inventory."""
    inv = MarketInventory()
    prop = make_property()
    inv.add_listing(prop, 850_000, week=1)
    inv.mark_sold("TEST-001", sale_price=870_000, week=4)
    assert len(inv.get_active_listings()) == 0
    assert inv.get_listing("TEST-001") is None


def test_mark_sold_records_sale():
    """Sold listing creates a SaleRecord with correct data."""
    inv = MarketInventory()
    prop = make_property()
    inv.add_listing(prop, 850_000, week=1)
    record = inv.mark_sold("TEST-001", sale_price=870_000, week=4, buyer_id="buyer_01")
    assert isinstance(record, SaleRecord)
    assert record.folio_id == "TEST-001"
    assert record.sale_price == 870_000
    assert record.buyer_id == "buyer_01"
    assert len(inv.get_sales()) == 1


def test_mark_sold_unknown_raises():
    """Marking an unknown folio_id sold raises KeyError."""
    inv = MarketInventory()
    with pytest.raises(KeyError):
        inv.mark_sold("GHOST", sale_price=500_000, week=1)


# ─── Price reduction schedule ────────────────────────────────────────────────

def test_price_reduction_at_21_days():
    """After 21 DOM, listing gets 2% price reduction."""
    inv = MarketInventory()
    prop = make_property()
    inv.add_listing(prop, 800_000, week=1)

    # Manually set DOM to 21 days (trigger first reduction)
    listing = inv.get_listing("TEST-001")
    listing.days_on_market = 21

    inv.apply_price_reductions(week=4)

    listing = inv.get_listing("TEST-001")
    assert len(listing.price_reductions) == 1
    expected = 800_000 * 0.98
    assert listing.current_asking == pytest.approx(expected)


def test_price_reduction_at_42_days():
    """After 42 DOM, listing gets a second reduction (cumulative)."""
    inv = MarketInventory()
    prop = make_property()
    inv.add_listing(prop, 800_000, week=1)

    listing = inv.get_listing("TEST-001")
    listing.days_on_market = 42

    inv.apply_price_reductions(week=7)

    listing = inv.get_listing("TEST-001")
    # Both the 21-day and 42-day reductions should fire
    assert len(listing.price_reductions) == 2
    expected = 800_000 * 0.98 * 0.97
    assert listing.current_asking == pytest.approx(expected)


def test_price_reduction_not_repeated():
    """A DOM reduction threshold fires only once per listing."""
    inv = MarketInventory()
    prop = make_property()
    inv.add_listing(prop, 800_000, week=1)

    listing = inv.get_listing("TEST-001")
    listing.days_on_market = 21
    inv.apply_price_reductions(week=4)
    inv.apply_price_reductions(week=5)  # Same threshold, should not double-apply

    listing = inv.get_listing("TEST-001")
    assert len(listing.price_reductions) == 1


def test_listing_expiry_at_90_days():
    """After 90 DOM, listing is expired and removed from active."""
    inv = MarketInventory()
    prop = make_property()
    inv.add_listing(prop, 800_000, week=1)

    listing = inv.get_listing("TEST-001")
    listing.days_on_market = 90

    expired = inv.apply_price_reductions(week=14)

    assert "TEST-001" in expired
    assert inv.get_listing("TEST-001") is None
    assert inv.active_count == 0


def test_listing_expiry_counted_in_stats():
    """Expired listings appear in stats.total_expirations_to_date."""
    inv = MarketInventory()
    prop = make_property()
    inv.add_listing(prop, 800_000, week=1)

    listing = inv.get_listing("TEST-001")
    listing.days_on_market = 90
    inv.apply_price_reductions(week=14)

    stats = inv.get_stats()
    assert stats.total_expirations_to_date == 1


# ─── Tick ────────────────────────────────────────────────────────────────────

def test_tick_increments_dom():
    """Calling tick() increments DOM by 7 days for active listings."""
    inv = MarketInventory()
    prop = make_property()
    inv.add_listing(prop, 800_000, week=1)

    inv.tick(week=2)
    listing = inv.get_listing("TEST-001")
    assert listing.days_on_market == 7

    inv.tick(week=3)
    listing = inv.get_listing("TEST-001")
    assert listing.days_on_market == 14


# ─── Market stats ────────────────────────────────────────────────────────────

def test_market_stats_empty_inventory():
    """Stats on empty inventory return zeros."""
    inv = MarketInventory()
    stats = inv.get_stats()
    assert stats.active_count == 0
    assert stats.avg_asking_price == 0.0
    assert stats.median_asking_price == 0.0


def test_market_stats_computed():
    """Stats correctly aggregate multiple active listings."""
    inv = MarketInventory()
    inv.add_listing(make_property("A", 600_000), 620_000, week=1)
    inv.add_listing(make_property("B", 800_000), 820_000, week=1)
    inv.add_listing(make_property("C", 700_000), 710_000, week=1)

    stats = inv.get_stats()
    assert stats.active_count == 3
    expected_avg = (620_000 + 820_000 + 710_000) / 3
    assert stats.avg_asking_price == pytest.approx(expected_avg)
    assert stats.median_asking_price == pytest.approx(710_000)


def test_market_stats_sale_price():
    """avg_sale_price reflects actual sale prices, not asking prices."""
    inv = MarketInventory()
    inv.add_listing(make_property("A", 600_000), 620_000, week=1)
    inv.add_listing(make_property("B", 800_000), 820_000, week=1)
    inv.mark_sold("A", sale_price=640_000, week=3)
    inv.mark_sold("B", sale_price=800_000, week=3)

    stats = inv.get_stats()
    assert stats.total_sales_to_date == 2
    assert stats.avg_sale_price == pytest.approx((640_000 + 800_000) / 2)


def test_price_reduction_count_in_stats():
    """Stats tracks how many active listings have had at least one reduction."""
    inv = MarketInventory()
    inv.add_listing(make_property("A"), 800_000, week=1)
    inv.add_listing(make_property("B", 700_000), 720_000, week=1)

    listing_a = inv.get_listing("A")
    listing_a.days_on_market = 21
    inv.apply_price_reductions(week=4)

    stats = inv.get_stats()
    assert stats.price_reduction_count == 1
