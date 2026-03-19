"""
Market inventory manager.

Tracks all listings in the simulation: active, pending, sold, expired, and
withdrawn. Manages the lifecycle of each listing from entry to resolution.

Key responsibilities:
- Accept new listings entering the market
- Track days-on-market (DOM) per active listing
- Apply automatic price reductions when DOM crosses thresholds
- Record sales and expirations
- Compute aggregate market statistics

Price reduction schedule (default, configurable):
- After 21 days (3 weeks): reduce 2%
- After 42 days (6 weeks): reduce another 3%
- After 63 days (9 weeks): reduce another 3%
- After 90 days (~13 weeks): expire listing
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sim.properties.models import Listing, ListingStatus, PriceReduction, Property


@dataclass
class SaleRecord:
    """Record of a completed transaction."""
    folio_id: str
    sale_price: float
    asking_price_at_sale: float
    sale_week: int
    days_on_market: int
    buyer_id: Optional[str] = None
    listed_week: int = 0


@dataclass
class MarketStats:
    """Aggregate market statistics at a point in time."""
    active_count: int
    avg_days_on_market: float
    avg_asking_price: float
    median_asking_price: float
    total_sales_to_date: int
    total_expirations_to_date: int
    avg_sale_price: float  # Over all completed sales
    price_reduction_count: int  # Active listings with at least one reduction


# Default DOM thresholds and reduction percentages
DEFAULT_REDUCTION_RULES: list[tuple[int, float]] = [
    (21, 0.02),   # 21 days: -2%
    (42, 0.03),   # 42 days: -3%
    (63, 0.03),   # 63 days: -3%
]
DEFAULT_EXPIRY_DAYS = 90


class MarketInventory:
    """
    Central registry for all property listings.

    Maintains separate collections for active and historical listings.
    All mutations happen through explicit methods — no direct dict access.
    """

    def __init__(
        self,
        reduction_rules: Optional[list[tuple[int, float]]] = None,
        expiry_days: int = DEFAULT_EXPIRY_DAYS,
    ) -> None:
        self._reduction_rules = reduction_rules or DEFAULT_REDUCTION_RULES
        self._expiry_days = expiry_days

        # folio_id → Listing (only active/pending)
        self._active: dict[str, Listing] = {}
        # folio_id → SaleRecord (completed sales)
        self._sales: list[SaleRecord] = []
        # folio_id → Listing (expired/withdrawn/sold — for history)
        self._history: dict[str, Listing] = {}

    # ─── Mutations ───────────────────────────────────────────────────────────

    def add_listing(
        self,
        prop: Property,
        asking_price: float,
        week: int,
    ) -> Listing:
        """
        Add a new listing to the active inventory.

        Raises ValueError if folio_id is already active.
        """
        folio_id = prop.folio_id
        if folio_id in self._active:
            raise ValueError(f"Property {folio_id} is already listed as active.")
        listing = Listing(
            property=prop,
            asking_price=asking_price,
            listed_week=week,
            days_on_market=0,
            status=ListingStatus.ACTIVE,
        )
        self._active[folio_id] = listing
        return listing

    def mark_sold(
        self,
        folio_id: str,
        sale_price: float,
        week: int,
        buyer_id: Optional[str] = None,
    ) -> SaleRecord:
        """
        Mark a listing as sold and remove from active inventory.

        Raises KeyError if folio_id is not in active inventory.
        """
        if folio_id not in self._active:
            raise KeyError(f"No active listing for folio_id={folio_id!r}")
        listing = self._active.pop(folio_id)
        listing.status = ListingStatus.SOLD
        self._history[folio_id] = listing

        record = SaleRecord(
            folio_id=folio_id,
            sale_price=sale_price,
            asking_price_at_sale=listing.current_asking,
            sale_week=week,
            days_on_market=listing.days_on_market,
            buyer_id=buyer_id,
            listed_week=listing.listed_week,
        )
        self._sales.append(record)
        return record

    def mark_expired(self, folio_id: str, week: int) -> None:
        """Move a listing from active to expired (failed to sell)."""
        if folio_id not in self._active:
            raise KeyError(f"No active listing for folio_id={folio_id!r}")
        listing = self._active.pop(folio_id)
        listing.status = ListingStatus.EXPIRED
        self._history[folio_id] = listing

    def mark_withdrawn(self, folio_id: str, week: int) -> None:
        """Seller withdraws listing voluntarily."""
        if folio_id not in self._active:
            raise KeyError(f"No active listing for folio_id={folio_id!r}")
        listing = self._active.pop(folio_id)
        listing.status = ListingStatus.WITHDRAWN
        self._history[folio_id] = listing

    # ─── Time step ───────────────────────────────────────────────────────────

    def tick(self, week: int) -> list[str]:
        """
        Advance one simulation week.

        Increments DOM for all active listings and applies price reductions
        and expirations per the configured rules.

        Returns list of folio_ids that expired this tick.
        """
        expired = self.apply_price_reductions(week)
        # Increment DOM (7 days per week)
        for listing in self._active.values():
            listing.days_on_market += 7
        return expired

    def apply_price_reductions(self, week: int) -> list[str]:
        """
        Apply price reductions and expire stale listings.

        Checks each active listing's current DOM against the reduction
        schedule. Reductions are applied cumulatively — each threshold
        fires at most once per listing.

        Returns list of folio_ids expired this call.
        """
        expired_ids: list[str] = []

        for folio_id, listing in list(self._active.items()):
            dom = listing.days_on_market

            # Expire first (so we don't also reduce an expiring listing)
            if dom >= self._expiry_days:
                self.mark_expired(folio_id, week)
                expired_ids.append(folio_id)
                continue

            # Apply each reduction threshold at most once
            already_reduced_at = {r.reason for r in listing.price_reductions}

            for threshold_days, pct in self._reduction_rules:
                rule_key = f"dom_{threshold_days}"
                if dom >= threshold_days and rule_key not in already_reduced_at:
                    old_price = listing.current_asking
                    new_price = old_price * (1 - pct)
                    reduction = PriceReduction(
                        week=week,
                        old_price=old_price,
                        new_price=new_price,
                        reason=rule_key,
                    )
                    listing.price_reductions.append(reduction)

        return expired_ids

    # ─── Queries ─────────────────────────────────────────────────────────────

    def get_active_listings(self) -> list[Listing]:
        """All currently active listings."""
        return list(self._active.values())

    def get_listing(self, folio_id: str) -> Optional[Listing]:
        """Active listing by folio_id. Returns None if not active."""
        return self._active.get(folio_id)

    def get_sales(self) -> list[SaleRecord]:
        """All completed sale records."""
        return list(self._sales)

    def get_stats(self) -> MarketStats:
        """Compute aggregate market statistics from current state."""
        active = list(self._active.values())
        n_active = len(active)

        avg_dom = (
            sum(l.days_on_market for l in active) / n_active if n_active > 0 else 0.0
        )
        asking_prices = [l.current_asking for l in active]
        avg_asking = sum(asking_prices) / n_active if n_active > 0 else 0.0

        sorted_prices = sorted(asking_prices)
        if sorted_prices:
            mid = len(sorted_prices) // 2
            if len(sorted_prices) % 2 == 0:
                median_asking = (sorted_prices[mid - 1] + sorted_prices[mid]) / 2
            else:
                median_asking = sorted_prices[mid]
        else:
            median_asking = 0.0

        avg_sale = (
            sum(s.sale_price for s in self._sales) / len(self._sales)
            if self._sales
            else 0.0
        )

        reduction_count = sum(1 for l in active if l.price_reductions)

        # Count expired from history
        expired_count = sum(
            1 for l in self._history.values() if l.status == ListingStatus.EXPIRED
        )

        return MarketStats(
            active_count=n_active,
            avg_days_on_market=avg_dom,
            avg_asking_price=avg_asking,
            median_asking_price=median_asking,
            total_sales_to_date=len(self._sales),
            total_expirations_to_date=expired_count,
            avg_sale_price=avg_sale,
            price_reduction_count=reduction_count,
        )

    @property
    def active_count(self) -> int:
        return len(self._active)
