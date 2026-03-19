"""
API-specific Pydantic v2 schemas for request/response validation.

These wrap internal dataclasses and provide clean JSON serialization.
All response models include a disclaimer field.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

DISCLAIMER = (
    "This analysis is based on simulated market behavior using "
    "rule-based agent models. Results are indicators for assessment "
    "review prioritization, not appraisal conclusions or market "
    "value determinations. All amounts in CAD."
)


# ─── Config ───────────────────────────────────────────────────────────────────

class ConfigSchema(BaseModel):
    num_agents: int = 500
    num_weeks: int = 26
    contract_rate: float = 0.05
    seed: int = 42
    initial_markup: float = 0.03
    markup_variance: float = 0.05
    agent_entry_mode: str = "front_loaded"
    replenishment_rate: float = 0.0
    replenishment_variance: float = 0.02


# ─── Requests ─────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    """Request body for POST /api/analyze."""
    properties: list[dict[str, Any]]
    config: ConfigSchema = Field(default_factory=ConfigSchema)


class StableAnalyzeRequest(BaseModel):
    """Request body for POST /api/analyze/stable."""
    properties: list[dict[str, Any]]
    config: ConfigSchema = Field(default_factory=ConfigSchema)
    num_runs: int = 10


class SimulateRequest(BaseModel):
    """Request body for POST /api/simulate (raw simulation result)."""
    properties: list[dict[str, Any]]
    config: ConfigSchema = Field(default_factory=ConfigSchema)


# ─── Response sub-schemas ─────────────────────────────────────────────────────

class AssessmentGapSchema(BaseModel):
    folio_id: str
    assessed_value: float
    simulated_clearing_price: float
    gap_pct: float
    gap_signal: str
    confidence: str
    market_pressure_score: float
    days_on_market: int
    offer_count: int
    rounds: int
    review_recommendation: str


class NeighbourhoodSummarySchema(BaseModel):
    neighbourhood: str
    municipality: str
    property_count: int
    avg_gap_pct: float
    median_gap_pct: float
    under_assessed_count: int
    over_assessed_count: int
    within_tolerance_count: int
    avg_market_pressure: float
    avg_dom: float
    systemic_signal: str
    flagged_for_review: int


class StabilityResultSchema(BaseModel):
    folio_id: str
    num_runs: int
    clearing_prices: list[float]
    gap_signals: list[str]
    mean_clearing_price: float
    std_clearing_price: float
    p10_clearing_price: float
    p90_clearing_price: float
    dominant_signal: str
    signal_agreement_pct: float
    stability: str


class TransactionSchema(BaseModel):
    folio_id: str
    outcome: str
    final_price: Optional[float]
    rounds: int
    offer_count: int


# ─── Top-level responses ──────────────────────────────────────────────────────

class AnalyzeResponse(BaseModel):
    """Response for /api/analyze and /api/analyze/stable."""
    run_date: str
    config_summary: dict[str, Any]
    property_results: list[AssessmentGapSchema]
    neighbourhood_summaries: list[NeighbourhoodSummarySchema]
    stability_results: Optional[dict[str, StabilityResultSchema]] = None
    total_properties: int
    total_sold: int
    total_unsold: int
    flagged_for_review: int
    systemic_signals: list[str]
    disclaimer: str = DISCLAIMER


class SimulateResponse(BaseModel):
    """Response for /api/simulate (raw simulation output)."""
    seed: int
    total_weeks: int
    properties_sold: list[str]
    properties_unsold: list[str]
    transactions: list[TransactionSchema]
    disclaimer: str = DISCLAIMER


class HealthResponse(BaseModel):
    """Response for GET /api/health."""
    status: str
    version: str
    tests_passing: int
