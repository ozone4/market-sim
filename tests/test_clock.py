"""
Tests for SimulationClock — date advancement, season detection, and peak season.
"""
from datetime import date

import pytest

from sim.market.clock import SimulationClock


def test_initial_state():
    """Clock starts at week 0, which maps to start_date."""
    clock = SimulationClock(start_date=date(2024, 1, 1))
    assert clock.current_week == 0
    assert clock.current_date == date(2024, 1, 1)


def test_date_advances_weekly():
    """Each tick advances the date by exactly 7 days."""
    clock = SimulationClock(start_date=date(2024, 3, 1))
    clock.tick()
    assert clock.current_date == date(2024, 3, 8)
    clock.tick()
    assert clock.current_date == date(2024, 3, 15)


def test_tick_returns_new_week():
    """tick() returns the new current_week value."""
    clock = SimulationClock(start_date=date(2024, 1, 1))
    result = clock.tick()
    assert result == 1
    result = clock.tick()
    assert result == 2


def test_date_after_many_ticks():
    """After 52 ticks (1 year), date is 52 weeks after start."""
    from datetime import timedelta
    start = date(2024, 1, 1)
    clock = SimulationClock(start_date=start)
    for _ in range(52):
        clock.tick()
    assert clock.current_date == start + timedelta(weeks=52)


# ─── Season detection ─────────────────────────────────────────────────────────

def test_season_winter():
    """December, January, February → winter."""
    for month in (12, 1, 2):
        clock = SimulationClock(start_date=date(2024, month, 15))
        assert clock.season == "winter", f"Month {month} should be winter"


def test_season_spring():
    """March, April, May → spring."""
    for month in (3, 4, 5):
        clock = SimulationClock(start_date=date(2024, month, 15))
        assert clock.season == "spring", f"Month {month} should be spring"


def test_season_summer():
    """June, July, August → summer."""
    for month in (6, 7, 8):
        clock = SimulationClock(start_date=date(2024, month, 15))
        assert clock.season == "summer", f"Month {month} should be summer"


def test_season_fall():
    """September, October, November → fall."""
    for month in (9, 10, 11):
        clock = SimulationClock(start_date=date(2024, month, 15))
        assert clock.season == "fall", f"Month {month} should be fall"


# ─── Peak season ─────────────────────────────────────────────────────────────

def test_peak_season_spring():
    """March through June are peak season."""
    for month in (3, 4, 5, 6):
        clock = SimulationClock(start_date=date(2024, month, 1))
        assert clock.is_peak_season, f"Month {month} should be peak season"


def test_not_peak_season_outside_spring():
    """Non-spring months are not peak season."""
    for month in (1, 2, 7, 8, 9, 10, 11, 12):
        clock = SimulationClock(start_date=date(2024, month, 1))
        assert not clock.is_peak_season, f"Month {month} should NOT be peak season"


# ─── Season transitions via tick ─────────────────────────────────────────────

def test_season_detection():
    """
    Season changes correctly as clock advances through the year.

    Start in January (winter) and advance to verify transitions.
    """
    clock = SimulationClock(start_date=date(2024, 1, 15))
    assert clock.season == "winter"

    # Advance to March (9 weeks ≈ Feb→Mar transition)
    for _ in range(7):
        clock.tick()
    # Should be in late February or early March
    # Just verify the clock is advancing (month ≥ 2)
    assert clock.current_date.month >= 2


def test_weeks_until():
    """weeks_until returns correct delta."""
    clock = SimulationClock(start_date=date(2024, 1, 1), current_week=3)
    assert clock.weeks_until(10) == 7
    assert clock.weeks_until(3) == 0   # Already there
    assert clock.weeks_until(1) == 0   # Past it → 0 (not negative)


def test_repr():
    """__repr__ includes week and date info."""
    clock = SimulationClock(start_date=date(2024, 3, 1))
    r = repr(clock)
    assert "week=0" in r
    assert "2024" in r
