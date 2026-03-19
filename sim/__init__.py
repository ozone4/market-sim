"""
Market Simulation Engine — multi-agent real estate market simulation.

Primary use case: assessment validation by simulating the market that
existed (or would exist) on a valuation date, identifying properties
whose assessed values diverge from simulated market clearing behaviour.

Phase 1 exports: models, financial math, agent generator, time engine.
"""
from sim.agents.financial import calculate_max_purchase_price, qualifies_for_property
from sim.agents.generator import generate_buyer_pool
from sim.agents.models import BuyerAgent, HouseholdType, AgentStatus
from sim.market.clock import SimulationClock
from sim.market.inventory import MarketInventory
from sim.properties.models import Property, Listing, PropertyType, Condition

__all__ = [
    # Properties
    "Property",
    "Listing",
    "PropertyType",
    "Condition",
    # Agents
    "BuyerAgent",
    "HouseholdType",
    "AgentStatus",
    # Financial
    "calculate_max_purchase_price",
    "qualifies_for_property",
    # Generator
    "generate_buyer_pool",
    # Market
    "SimulationClock",
    "MarketInventory",
]
