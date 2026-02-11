"""Example: Logistics routing agent.

Demonstrates the Agentic Bus paper's motivating scenario (§1): an AI agent within a
logistics firm responding to a storm that has closed a port.  Rather than
receiving a static "Route Unavailable" error, this agent can negotiate
alternative routes through the Agentic Bus Protocol.

Run with::

    python -m app.agents.examples.logistics_agent.agent
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from dotenv import load_dotenv, find_dotenv

# Load .env from current directory or parent directories
load_dotenv(find_dotenv(usecwd=True))

from app.agents.base.agent import BaseAgent
from app.core.registry.capability_registry import AgentCapability

from pydantic import BaseModel, Field

logging.basicConfig(
    level=os.getenv("AGBUS_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output models – describe the structured answer for each capability
# ---------------------------------------------------------------------------

class RouteWaypoint(BaseModel):
    """A single waypoint on an optimised route."""
    name: str
    type: str = Field(description="Type of facility (warehouse, hub, port, etc.)")


class OptimizedRoute(BaseModel):
    """An optimised delivery route."""
    origin: str
    destination: str
    waypoints: list[RouteWaypoint] = Field(default_factory=list)
    modality: str = Field(description="Transport modalities used (e.g. 'road+rail')")
    distance_km: float


class CostEstimate(BaseModel):
    """Monetary cost estimate."""
    currency: str = "USD"
    amount: float


class TimeEstimate(BaseModel):
    """Time estimate with confidence."""
    hours: float
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence level 0–1")


class RouteOptimizationOutput(BaseModel):
    """Output schema for the route_optimization capability."""
    optimized_route: OptimizedRoute
    cost_estimate: CostEstimate
    time_estimate: TimeEstimate


class AlternativeRoute(BaseModel):
    """A single alternative route option."""
    route: OptimizedRoute
    cost_estimate: CostEstimate
    time_estimate: TimeEstimate
    disruption_avoided: str = Field(description="Description of the disruption avoided")


class AlternativeRoutingOutput(BaseModel):
    """Output schema for the alternative_routing capability."""
    alternatives: list[AlternativeRoute] = Field(default_factory=list)
    original_disruption: str = Field(description="Description of the original disruption")


class StorageAvailabilityOutput(BaseModel):
    """Output schema for the storage_availability capability."""
    storage_confirmation: bool
    reservation_id: str
    location: str
    capacity_allocated_teu: int


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class LogisticsRoutingAgent(BaseAgent):
    """Provider agent that offers logistics routing capabilities.

    Capabilities:
    - route_optimization: Find optimal delivery routes considering cost, time,
      and quality constraints.
    - alternative_routing: Discover alternative routes when primary routes are
      unavailable.
    """

    def capabilities(self) -> list[AgentCapability]:
        return [
            AgentCapability(
                capability_id="route_optimization",
                description=(
                    "Optimise delivery routes considering cost, time, and "
                    "delivery quality constraints.  Supports multi-modal "
                    "transport (road, rail, sea, air)."
                ),
                required_scopes=["logistics:read", "logistics:route"],
                supported_data_domains=["logistics", "transportation", "supply_chain"],
                operational_constraints={
                    "max_radius_km": 5000,
                    "supported_modalities": ["road", "rail", "sea", "air"],
                },
                expected_artifacts=["optimized_route", "cost_estimate", "time_estimate"],
                estimated_cost=0.05,
                estimated_latency=2.0,
                output_model=RouteOptimizationOutput,
            ),
            AgentCapability(
                capability_id="alternative_routing",
                description=(
                    "Discover and evaluate alternative delivery routes when "
                    "primary routes are disrupted (e.g., port closures, "
                    "weather events, strikes)."
                ),
                required_scopes=["logistics:read", "logistics:route", "logistics:disruption"],
                supported_data_domains=["logistics", "disruption_management"],
                operational_constraints={
                    "response_time_seconds": 30,
                    "max_alternatives": 5,
                },
                expected_artifacts=["alternative_routes", "disruption_summary"],
                estimated_cost=0.08,
                estimated_latency=3.0,
                output_model=AlternativeRoutingOutput,
            ),
        ]

    async def execute_task(
        self,
        payload: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a routing task.

        In a real implementation this would call routing APIs, run
        optimization algorithms, etc.
        """
        intent_text = payload.get("intent_text", "")
        logger.info("Executing routing task: %s", intent_text)

        # Simulated result
        return {
            "optimized_route": {
                "origin": context.get("origin", "unknown"),
                "destination": context.get("destination", "unknown"),
                "waypoints": ["warehouse_A", "hub_B"],
                "modality": "road+rail",
                "distance_km": 350,
            },
            "cost_estimate": {"currency": "USD", "amount": 1250.00},
            "time_estimate": {"hours": 8, "confidence": 0.85},
        }


class WarehouseAgent(BaseAgent):
    """Provider agent that offers warehouse and storage capabilities."""

    def capabilities(self) -> list[AgentCapability]:
        return [
            AgentCapability(
                capability_id="storage_availability",
                description=(
                    "Check storage availability and reserve warehouse space "
                    "for temporary or long-term container storage."
                ),
                required_scopes=["warehouse:read", "warehouse:reserve"],
                supported_data_domains=["logistics", "warehousing"],
                operational_constraints={
                    "max_capacity_teu": 500,
                    "temperature_controlled": True,
                },
                expected_artifacts=["storage_confirmation", "reservation_id"],
                estimated_cost=0.02,
                estimated_latency=1.0,
                output_model=StorageAvailabilityOutput,
            ),
        ]

    async def execute_task(
        self,
        payload: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        logger.info("Executing warehouse task")
        return {
            "storage_confirmation": True,
            "reservation_id": "WH-2026-001",
            "location": "Warehouse Alpha, Zone C",
            "capacity_allocated_teu": 10,
        }


async def main() -> None:
    """Run the logistics agent standalone."""
    agent = LogisticsRoutingAgent(
        agent_id="logistics-router-01",
        coordinator_uri=os.getenv("AGBUS_COORDINATOR_URI", "ws://localhost:8765"),
        semantic_description=(
            "Logistics routing optimisation agent specialising in "
            "multi-modal transport route planning and disruption management."
        ),
    )
    await agent.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
