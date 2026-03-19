"""
FastAPI application entry point for the market simulation API.

Run with:
    uvicorn api.main:app --reload
"""
from __future__ import annotations

from fastapi import FastAPI

from api.routes import router

app = FastAPI(
    title="Market Simulation API",
    description=(
        "Multi-agent real estate market simulation for BC Assessment validation. "
        "Runs demographically-sampled buyer agents against property inventories "
        "to produce assessment gap signals and review recommendations."
    ),
    version="0.3.0",
)

app.include_router(router)
