"""
Simulation clock — manages weekly time steps.

The simulation runs in discrete weekly ticks. Each tick represents
one week of market activity. The clock tracks:
- Current week number (0-indexed)
- Calendar date (derived from start_date + weeks)
- Season (for seasonal market effects)

The clock itself is stateful but lightweight — it holds no market data,
only temporal state. Pass it to other components that need time context.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional


@dataclass
class SimulationClock:
    """
    Week-by-week simulation time engine.

    Attributes
    ----------
    start_date:
        The real-world date corresponding to week 0.
    current_week:
        Current simulation week (incremented by tick()).
    """

    start_date: date
    current_week: int = 0

    @property
    def current_date(self) -> date:
        """Calendar date corresponding to current_week."""
        return self.start_date + timedelta(weeks=self.current_week)

    @property
    def season(self) -> str:
        """Current season based on calendar month."""
        month = self.current_date.month
        if month in (3, 4, 5):
            return "spring"
        elif month in (6, 7, 8):
            return "summer"
        elif month in (9, 10, 11):
            return "fall"
        return "winter"

    @property
    def is_peak_season(self) -> bool:
        """
        Spring/early summer is peak real estate season in BC.

        March through June historically sees highest transaction volumes
        in Greater Victoria.
        """
        return self.current_date.month in (3, 4, 5, 6)

    def tick(self) -> int:
        """
        Advance simulation by one week.

        Returns the new current_week value.
        """
        self.current_week += 1
        return self.current_week

    def weeks_until(self, target_week: int) -> int:
        """How many ticks until we reach target_week."""
        return max(0, target_week - self.current_week)

    def __repr__(self) -> str:
        return (
            f"SimulationClock(week={self.current_week}, "
            f"date={self.current_date}, season={self.season})"
        )
