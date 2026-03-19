"""
Market context snapshot used by agents and auction mechanics.

MarketContext is rebuilt each week from current inventory and recent
transaction data. Agents read it when scoring properties, deciding whether
to bid, and calibrating bid amounts. It is a pure data snapshot — no
mutations happen on this object during the week it represents.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarketContext:
    """
    A snapshot of market conditions for a given simulation week.

    Attributes
    ----------
    current_week:
        The simulation week this context represents.
    contract_rate:
        Current mortgage contract rate (e.g., 0.05 for 5%).
    avg_days_on_market:
        Average DOM across all active listings.
    active_listing_count:
        Number of active listings this week.
    recent_sale_count:
        Sales completed in the last 4 weeks.
    avg_sale_to_asking_ratio:
        Weighted average of (sale_price / asking_price) for recent sales.
        > 1.0 means properties are selling above asking (hot market).
    season:
        Current season: "spring", "summer", "fall", or "winter".
    is_peak_season:
        True during March–June (peak Victoria real-estate season).
    """

    current_week: int
    contract_rate: float
    avg_days_on_market: float
    active_listing_count: int
    recent_sale_count: int
    avg_sale_to_asking_ratio: float
    season: str
    is_peak_season: bool

    @property
    def market_temperature(self) -> str:
        """
        Classify the current market as 'hot', 'balanced', or 'cold'.

        hot      — sale-to-ask > 1.02 AND avg DOM < 21 days
        cold     — sale-to-ask < 0.97 OR avg DOM > 45 days
        balanced — everything in between
        """
        if (
            self.avg_sale_to_asking_ratio > 1.02
            and self.avg_days_on_market < 21
        ):
            return "hot"
        if (
            self.avg_sale_to_asking_ratio < 0.97
            or self.avg_days_on_market > 45
        ):
            return "cold"
        return "balanced"
