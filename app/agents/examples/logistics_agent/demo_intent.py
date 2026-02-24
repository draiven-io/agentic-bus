"""Demo: Logistics scenario via managed agents on the Agentic Bus.

Reproduces the motivating example from §1 of the Liquid Interfaces paper:

    An AI agent within a logistics firm must respond to a storm that has closed
    a port. Rather than receiving a static "Route Unavailable" error, it
    negotiates alternative routes through the Agentic Bus Protocol.

This script submits a series of intents to the coordinator.  The managed
agents (seeded by ``seed_managed_agents.py``) respond via the full Liquid
Interfaces lifecycle::

    intent → discovery → offers → plan composition → approval → execute → complete → dissolve

Usage::

    # 1. Make sure the coordinator is running:
    agbus serve

    # 2. Start all logistics agents (in separate terminals):
    agbus agent start logistics-route-optimizer
    agbus agent start warehouse-manager
    agbus agent start carrier-negotiator
    agbus agent start disruption-analyst

    # 3. Run this demo:
    python -m app.agents.examples.logistics_agent.demo_intent

Pre-requisites:
    - Agents seeded: ``python -m app.agents.examples.logistics_agent.seed_managed_agents``
"""

from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

from app.agents.requester import IntentClient, PlanDecision
from app.core.protocol.envelope import OfferPayload, AgBusEnvelope

logging.basicConfig(
    level=os.getenv("AGBUS_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ===========================================================================
# Scenario 1: Disruption Analysis — storm closes a port
# ===========================================================================

async def scenario_disruption_analysis():
    """Step 1: Assess the disruption — the hurricane has closed the port."""
    logger.info("=" * 80)
    logger.info("SCENARIO 1: Disruption Analysis")
    logger.info("  A hurricane has closed the Port of New Orleans.")
    logger.info("  The disruption analyst will assess severity and impact.")
    logger.info("=" * 80)

    async def approve_plan(plan: OfferPayload, envelope: AgBusEnvelope) -> PlanDecision:
        logger.info("🔍 Reviewing disruption analysis plan:")
        logger.info("  Agents: %s", plan.participating_agents)
        for i, step in enumerate(plan.composition_plan.get("steps", []), 1):
            logger.info("    %d. %s", i, step.get("agent_id", "?"))
        return PlanDecision(action="approve", reason="Proceeding with disruption analysis")

    client = IntentClient(requester_id="logistics-demo")
    result = await client.submit_intent(
        intent_text=(
            "A Category 3 hurricane has closed the Port of New Orleans. "
            "Analyse the disruption: assess severity, estimate duration, "
            "identify all affected shipping routes from the US Gulf Coast, "
            "and recommend whether to re-route or wait."
        ),
        context={
            "disruption_type": "hurricane",
            "disruption_location": "Port of New Orleans, LA",
            "affected_region": "US Gulf Coast",
            "cargo_in_transit": 150,  # TEU containers
            "cargo_value_usd": 2_500_000,
        },
        requested_outputs=[
            "disruption_report",
            "affected_routes",
            "recommended_actions",
        ],
        plan_approval=approve_plan,
        timeout=60.0,
    )

    logger.info("📊 Disruption Analysis Result:")
    logger.info("  Session: %s", result.session_id)
    if result.result:
        logger.info("  ✅ %s", result.result)
    elif result.error:
        logger.error("  ❌ %s", result.error)
    return result


# ===========================================================================
# Scenario 2: Alternative Routing — find new routes avoiding the closed port
# ===========================================================================

async def scenario_alternative_routing():
    """Step 2: Find alternative routes that bypass the closed port."""
    logger.info("=" * 80)
    logger.info("SCENARIO 2: Alternative Routing")
    logger.info("  Finding routes from Los Angeles to Miami that avoid")
    logger.info("  the closed Port of New Orleans.")
    logger.info("=" * 80)

    async def approve_plan(plan: OfferPayload, envelope: AgBusEnvelope) -> PlanDecision:
        logger.info("🔍 Reviewing routing plan:")
        logger.info("  Agents: %s", plan.participating_agents)
        steps = plan.composition_plan.get("steps", [])
        for i, step in enumerate(steps, 1):
            logger.info(
                "    %d. %s — %s",
                i,
                step.get("agent_id", "?"),
                step.get("description", step.get("capability_id", "")),
            )
        logger.info("  ✅ Approving — need alternative routes urgently")
        return PlanDecision(action="approve", reason="Urgent re-routing needed")

    client = IntentClient(requester_id="logistics-demo")
    result = await client.submit_intent(
        intent_text=(
            "The Port of New Orleans is closed due to a hurricane. "
            "Find alternative shipping routes from Los Angeles to Miami. "
            "Consider overland (rail/road), alternative Gulf ports, or "
            "East Coast routes. Prioritize reliability and minimize delay."
        ),
        context={
            "origin": "Port of Los Angeles, CA",
            "destination": "Port of Miami, FL",
            "disrupted_ports": ["Port of New Orleans"],
            "disruption_reason": "Hurricane — Category 3",
            "cargo_type": "consumer electronics",
            "containers_teu": 25,
            "urgency": "high",
            "max_acceptable_delay_hours": 72,
        },
        requested_outputs=[
            "alternative_routes",
            "disruption_summary",
            "recommendation",
        ],
        plan_approval=approve_plan,
        timeout=60.0,
    )

    logger.info("📊 Alternative Routing Result:")
    logger.info("  Session: %s", result.session_id)
    if result.result:
        logger.info("  ✅ %s", result.result)
    elif result.error:
        logger.error("  ❌ %s", result.error)
    return result


# ===========================================================================
# Scenario 3: Warehouse + Carrier — reserve storage and book a carrier
# ===========================================================================

async def scenario_warehouse_and_carrier():
    """Step 3: Reserve warehouse space and negotiate carrier rates."""
    logger.info("=" * 80)
    logger.info("SCENARIO 3: Warehouse Reservation + Carrier Negotiation")
    logger.info("  Reserve temporary storage in Houston and book a carrier")
    logger.info("  for the alternative route.")
    logger.info("=" * 80)

    async def approve_plan(plan: OfferPayload, envelope: AgBusEnvelope) -> PlanDecision:
        logger.info("🔍 Reviewing combined plan:")
        logger.info("  Agents: %s", plan.participating_agents)
        steps = plan.composition_plan.get("steps", [])
        for i, step in enumerate(steps, 1):
            logger.info(
                "    %d. %s — %s",
                i,
                step.get("agent_id", "?"),
                step.get("description", step.get("capability_id", "")),
            )
        return PlanDecision(action="approve", reason="Combined warehouse + carrier plan accepted")

    client = IntentClient(requester_id="logistics-demo")
    result = await client.submit_intent(
        intent_text=(
            "I need to store 25 TEU containers temporarily near Houston, TX "
            "while arranging an alternative carrier from Houston to Miami. "
            "Find available warehouse space and get carrier rate quotes for "
            "the Houston-to-Miami leg. I need temperature-controlled storage "
            "and a carrier that can pick up within 48 hours."
        ),
        context={
            "storage_location_preferred": "Houston, TX",
            "storage_capacity_teu": 25,
            "storage_duration_days": 5,
            "temperature_controlled": True,
            "carrier_origin": "Houston, TX",
            "carrier_destination": "Port of Miami, FL",
            "cargo_type": "consumer electronics",
            "containers_teu": 25,
            "pickup_deadline_hours": 48,
        },
        requested_outputs=[
            "storage_confirmation",
            "reservation_id",
            "carrier_quotes",
            "recommended_carrier",
        ],
        plan_approval=approve_plan,
        timeout=60.0,
    )

    logger.info("📊 Warehouse + Carrier Result:")
    logger.info("  Session: %s", result.session_id)
    if result.result:
        logger.info("  ✅ %s", result.result)
    elif result.error:
        logger.error("  ❌ %s", result.error)
    return result


# ===========================================================================
# Scenario 4: Full end-to-end with renegotiation
# ===========================================================================

async def scenario_full_with_renegotiation():
    """Step 4: Full end-to-end — but reject the first plan and renegotiate."""
    logger.info("=" * 80)
    logger.info("SCENARIO 4: Full Logistics Planning with Renegotiation")
    logger.info("  Submit a complex intent, reject the first plan as too")
    logger.info("  expensive, and request a cheaper alternative.")
    logger.info("=" * 80)

    attempt = {"count": 0}

    async def review_plan(plan: OfferPayload, envelope: AgBusEnvelope) -> PlanDecision:
        attempt["count"] += 1
        logger.info("🔍 Plan proposal #%d:", attempt["count"])
        logger.info("  Agents: %s", plan.participating_agents)

        if attempt["count"] == 1:
            logger.info("  🔄 Rejecting — requesting cheaper routing (no air freight)")
            return PlanDecision(
                action="renegotiate",
                reason="Total cost too high — need ground/sea alternatives only",
                renegotiation_hint={
                    "max_total_cost_usd": 15000,
                    "exclude_modalities": ["air"],
                    "prefer": "economy",
                },
            )
        else:
            logger.info("  ✅ Approving revised plan")
            return PlanDecision(action="approve", reason="Revised economy plan accepted")

    client = IntentClient(requester_id="logistics-demo", timeout=90.0)
    result = await client.submit_intent(
        intent_text=(
            "I need to deliver 25 TEU containers of electronics from "
            "Shanghai to Rotterdam. A typhoon warning has been issued for "
            "the South China Sea. Analyse the disruption risk, find the "
            "safest route, arrange storage if needed along the way, and "
            "get carrier quotes. Optimize for cost while keeping delivery "
            "within 30 days."
        ),
        context={
            "origin": "Shanghai Port, China",
            "destination": "Rotterdam Port, Netherlands",
            "cargo_type": "consumer electronics",
            "containers_teu": 25,
            "cargo_value_usd": 1_200_000,
            "disruption_alert": "Typhoon warning — South China Sea",
            "max_transit_days": 30,
            "budget_usd": 25000,
        },
        requested_outputs=[
            "disruption_report",
            "optimized_route",
            "alternative_routes",
            "storage_confirmation",
            "carrier_quotes",
            "cost_estimate",
        ],
        plan_approval=review_plan,
    )

    logger.info("📊 Full Logistics Result (after %d round(s)):", attempt["count"])
    logger.info("  Session: %s", result.session_id)
    if result.result:
        logger.info("  ✅ %s", result.result)
    elif result.error:
        logger.error("  ❌ %s", result.error)
    return result


# ===========================================================================
# Main — run all scenarios sequentially
# ===========================================================================

async def main():
    """Run the full logistics demo."""
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║   Liquid Interfaces — Logistics Demo (Managed Agents)          ║")
    print("║                                                                ║")
    print("║   Reproducing the motivating scenario from §1 of the paper:    ║")
    print("║   A storm has closed a port. The agents negotiate alternative   ║")
    print("║   routes through the Agentic Bus Protocol.                     ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    coordinator = os.getenv("AGBUS_COORDINATOR_URI", "ws://localhost:8765")
    logger.info("Coordinator: %s", coordinator)
    print()

    try:
        # Scenario 1: Disruption analysis
        await scenario_disruption_analysis()
        await asyncio.sleep(2)

        # Scenario 2: Alternative routing
        await scenario_alternative_routing()
        await asyncio.sleep(2)

        # Scenario 3: Warehouse + carrier
        await scenario_warehouse_and_carrier()
        await asyncio.sleep(2)

        # Scenario 4: Full planning with renegotiation
        await scenario_full_with_renegotiation()

    except KeyboardInterrupt:
        logger.info("\n⚠️  Demo interrupted by user")
    except Exception as e:
        logger.exception("Demo failed: %s", e)

    print()
    print("═" * 70)
    print("  Demo complete!")
    print("═" * 70)
    print()


if __name__ == "__main__":
    asyncio.run(main())
