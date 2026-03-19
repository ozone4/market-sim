"""Shared helpers for the Market Sim dashboard."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import streamlit as st

from sim.properties.loader import load_properties_from_json
from sim.properties.models import Property
from sim.engine.simulation import SimulationConfig, run_simulation, SimulationResult
from sim.analysis.report import generate_report, AnalysisReport

# ── Project root (two levels up from dashboard/) ──────────────────────────────
_ROOT = Path(__file__).parent.parent

DATASET_OPTIONS: dict[str, Path] = {
    "30 Properties (Victoria)": _ROOT / "data" / "properties" / "sample_victoria.json",
    "220 Properties (Victoria Extended)": _ROOT / "data" / "properties" / "sample_victoria_200.json",
}

# Gap signal colour palette
SIGNAL_COLORS: dict[str, str] = {
    "within_tolerance": "#22c55e",
    "under_assessed": "#f59e0b",
    "over_assessed": "#ef4444",
}

SIGNAL_LABELS: dict[str, str] = {
    "within_tolerance": "Within Tolerance",
    "under_assessed": "Under-Assessed",
    "over_assessed": "Over-Assessed",
}

DISCLAIMER = (
    "**Disclaimer:** Results are indicators for assessment review prioritization only, "
    "not appraisal conclusions or market value determinations. All amounts in CAD."
)


@st.cache_data
def load_properties(dataset_name: str) -> list[Property]:
    """Load and validate properties from JSON. Cached by dataset name."""
    path = DATASET_OPTIONS[dataset_name]
    return load_properties_from_json(path)


def run_and_analyze(
    properties: list[Property],
    config: SimulationConfig,
    stability: Optional[dict] = None,
) -> tuple[SimulationResult, AnalysisReport]:
    """Run simulation and generate analysis report. Not cached — params vary."""
    result = run_simulation(properties, config)
    report = generate_report(result, properties, stability=stability, config=config)
    return result, report


def format_currency(value: float) -> str:
    """Format a float as CAD currency string."""
    return f"${value:,.0f}"


def gap_signal_color(signal: str) -> str:
    """Return hex colour for a gap signal string."""
    return SIGNAL_COLORS.get(signal, "#6b7280")


def show_disclaimer() -> None:
    """Render the standard disclaimer at the bottom of a results page."""
    st.divider()
    st.caption(DISCLAIMER)
