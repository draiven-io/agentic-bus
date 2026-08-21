"""Example: Using IntentClient to submit intentions.

This demonstrates various ways to use the ``IntentClient`` to make agents
or applications that submit intentions to the Agentic Bus.

The full negotiation lifecycle is:

    intent → discovery → offers → plan composition → **requester approval** → execute → complete → dissolve

The requester receives the full composed execution plan (the LangGraph flow
with all participating agents) as an ``offer`` and can:

- **Approve** it → execution proceeds.
- **Reject** it → session dissolves.
- **Renegotiate** → coordinator re-runs discovery with the requester's hints.

Run with::

    python -m agentic_bus.agents.examples.intent_client_example

Make sure the coordinator and at least one provider agent are running.
"""

from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from agentic_bus.agents.requester import (
    IntentClient,
    submit_intent,
    PlanDecision,
)
from agentic_bus.core.protocol.envelope import OfferPayload, AgBusEnvelope

logging.basicConfig(
    level=os.getenv("AGBUS_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ===========================================================================
# Example 1: Simple fire-and-forget (auto-approve)
# ===========================================================================

async def example_simple():
    """Simplest usage: fire and forget, auto-approve the plan, wait for result.

    When no ``plan_approval`` callback is given the client defaults to
    ``auto_approve=True``, so the proposed execution plan is accepted
    immediately.  This is the easiest way to get started.
    """
    logger.info("=" * 80)
    logger.info("Example 1: Simple Intent Submission (auto-approve)")
    logger.info("=" * 80)

    result = await submit_intent(
        "Find the cheapest route from Shanghai to Rotterdam",
        requester_id="example-app-1",
        context={
            "origin": "Shanghai Port, China",
            "destination": "Rotterdam Port, Netherlands",
            "cargo_type": "electronics",
            "max_cost_usd": 5000,
        },
        requested_outputs=["optimized_route", "cost_estimate"],
    )

    logger.info("📊 Result Summary:")
    logger.info("  Session ID: %s", result.session_id)
    logger.info("  Offers received: %d", len(result.offers))
    logger.info("  Proposed plan: %s", result.proposed_plan)
    logger.info("  Plan decision: %s", result.plan_decision)

    if result.result:
        logger.info("  ✅ Success!")
        logger.info("  Result: %s", result.result)
    elif result.reject:
        logger.warning("  ❌ Rejected: %s", result.reject.reason)
    elif result.error:
        logger.error("  ❌ Error: %s", result.error)
    else:
        logger.warning("  ⏳ Incomplete (timeout or connection issue)")


# ===========================================================================
# Example 2: Explicit plan approval with callback
# ===========================================================================

async def example_with_plan_approval():
    """The requester reviews and explicitly approves the execution plan.

    The ``plan_approval`` callback receives the full composed plan — the
    complete LangGraph flow with every agent, capability, and output schema.
    The requester inspects it and returns a ``PlanDecision``.
    """
    logger.info("=" * 80)
    logger.info("Example 2: Explicit Plan Approval")
    logger.info("=" * 80)

    async def review_plan(plan: OfferPayload, envelope: AgBusEnvelope) -> PlanDecision:
        """Review the proposed execution plan before approving."""
        logger.info("🔍 Reviewing proposed execution plan:")
        logger.info("  Description: %s", plan.capability_description)
        logger.info("  Participating agents: %s", plan.participating_agents)
        logger.info("  Steps:")
        for i, step in enumerate(plan.composition_plan.get("steps", []), 1):
            logger.info(
                "    %d. %s — %s",
                i,
                step.get("agent_id"),
                step.get("description", step.get("capability_id")),
            )
        logger.info("  Output schema: %s", plan.output_schema)

        logger.info("  ✅ Plan looks good — approving!")
        return PlanDecision(action="approve", reason="Plan meets requirements")

    client = IntentClient(requester_id="example-app-2")
    result = await client.submit_intent(
        "Find alternative routes from Los Angeles to Miami. Port of New Orleans is closed.",
        context={
            "origin": "Port of Los Angeles, CA",
            "destination": "Port of Miami, FL",
            "disruption": "Hurricane closure at Port of New Orleans",
            "disrupted_ports": ["Port of New Orleans"],
            "urgency": "high",
        },
        requested_outputs=["alternative_routes", "disruption_summary"],
        plan_approval=review_plan,
    )

    logger.info("📊 Final summary: %s", result)


# ===========================================================================
# Example 3: Plan rejection
# ===========================================================================

async def example_with_plan_rejection():
    """The requester reviews the plan and rejects it outright.

    Rejection dissolves the session.  No execution occurs.
    """
    logger.info("=" * 80)
    logger.info("Example 3: Plan Rejection")
    logger.info("=" * 80)

    async def review_and_reject(plan: OfferPayload, envelope: AgBusEnvelope) -> PlanDecision:
        logger.info("🔍 Reviewing proposed plan...")
        logger.info("  Agents: %s", plan.participating_agents)
        logger.info("  ❌ Rejecting — too many agents involved")
        return PlanDecision(
            action="reject",
            reason="Plan involves too many agents; prefer a single-agent solution",
        )

    client = IntentClient(requester_id="example-app-3")
    result = await client.submit_intent(
        "Check port availability at Rotterdam",
        context={"port": "Rotterdam"},
        requested_outputs=["status"],
        plan_approval=review_and_reject,
    )

    logger.info("📊 Result: %s", result)


# ===========================================================================
# Example 4: Renegotiation
# ===========================================================================

async def example_with_renegotiation():
    """The requester rejects the first plan and requests renegotiation.

    On the first proposal the requester returns ``PlanDecision(action="renegotiate")``.
    The coordinator re-runs discovery/negotiation incorporating the requester's
    hints (e.g., cost limits, excluded agents) and proposes a revised plan.
    The requester then approves the second proposal.
    """
    logger.info("=" * 80)
    logger.info("Example 4: Renegotiation Flow")
    logger.info("=" * 80)

    attempt = {"count": 0}

    async def review_with_renegotiation(
        plan: OfferPayload, envelope: AgBusEnvelope,
    ) -> PlanDecision:
        attempt["count"] += 1
        logger.info("🔍 Plan proposal #%d:", attempt["count"])
        logger.info("  Agents: %s", plan.participating_agents)

        if attempt["count"] == 1:
            logger.info("  🔄 Requesting renegotiation — need cheaper options")
            return PlanDecision(
                action="renegotiate",
                reason="Cost too high, need cheaper alternatives",
                renegotiation_hint={
                    "max_cost_usd": 2000,
                    "exclude_agents": ["premium-carrier-agent"],
                    "prefer": "economy",
                },
            )
        else:
            logger.info("  ✅ Approving revised plan")
            return PlanDecision(action="approve", reason="Revised plan accepted")

    client = IntentClient(requester_id="example-app-4", timeout=60.0)
    result = await client.submit_intent(
        "Ship container from Hamburg to Budapest",
        context={
            "origin": "Hamburg Port, Germany",
            "destination": "Budapest, Hungary",
            "cargo_type": "machinery",
        },
        requested_outputs=["optimized_route", "cost_estimate"],
        plan_approval=review_with_renegotiation,
    )

    logger.info("📊 Final result after %d negotiation round(s): %s", attempt["count"], result)


# ===========================================================================
# Example 5: Streaming with plan visibility
# ===========================================================================

async def example_streaming():
    """Stream all messages, including the plan proposal."""
    logger.info("=" * 80)
    logger.info("Example 5: Streaming Intent Responses")
    logger.info("=" * 80)

    client = IntentClient(requester_id="example-app-5")

    logger.info("🚀 Submitting intent and streaming responses...")

    async for envelope in client.submit_intent_stream(
        "Plan a multi-modal route from Hamburg to Budapest with storage in Vienna",
        context={
            "origin": "Hamburg Port, Germany",
            "destination": "Budapest, Hungary",
            "intermediate_storage": {
                "location": "Vienna, Austria",
                "duration_days": 3,
                "capacity_teu": 10,
            },
            "modalities_preferred": ["sea", "rail", "road"],
        },
        requested_outputs=["optimized_route", "storage_confirmation"],
    ):
        logger.info("📨 Message: type=%s from=%s", envelope.message_type, envelope.sender.id)

        if envelope.message_type == "offer":
            cap_id = envelope.payload.get("capability_id", "")
            if cap_id == "__composed_plan__":
                logger.info("  → Proposed execution plan:")
                steps = envelope.payload.get("composition_plan", {}).get("steps", [])
                for i, step in enumerate(steps, 1):
                    logger.info("    %d. %s", i, step.get("agent_id"))
                logger.info("  (In streaming mode the caller handles approval)")
            else:
                logger.info("  → Agent offer: %s", cap_id)
        elif envelope.message_type == "accept":
            logger.info("  → Plan approved, execution starting...")
        elif envelope.message_type == "complete":
            logger.info("  → Result: %s", envelope.payload)
        elif envelope.message_type == "reject":
            logger.info("  → Rejected: %s", envelope.payload.get("reason"))
        elif envelope.message_type == "dissolve":
            logger.info("  → Session dissolved")


# ===========================================================================
# Example 6: Orchestrator pattern (multiple sub-intentions)
# ===========================================================================

class OrchestratorAgent:
    """Example of an agent that coordinates multiple sub-intentions.

    This pattern is useful for complex workflows where one agent breaks
    down a high-level goal into multiple sub-intentions and coordinates
    their execution.

    Each sub-intention goes through the full negotiation flow:
    intent → offer (plan) → approve → execute → complete → dissolve
    """

    def __init__(self, agent_id: str = "orchestrator-agent"):
        self.agent_id = agent_id
        self.client = IntentClient(requester_id=agent_id)

    async def plan_global_logistics(
        self,
        origin: str,
        destination: str,
        cargo_type: str,
    ) -> dict:
        """High-level logistics planning that submits multiple sub-intentions.

        1. Get current shipping rates (auto-approve)
        2. Check port availability (auto-approve)
        3. Optimize route (with explicit plan review)
        """
        logger.info("=" * 80)
        logger.info("Orchestrator: Planning logistics from %s to %s", origin, destination)
        logger.info("=" * 80)

        results = {}

        # Step 1: Get shipping rates (auto-approve for speed)
        logger.info("Step 1: Fetching shipping rates...")
        rate_result = await self.client.submit_intent(
            f"Get current shipping rates from {origin} to {destination}",
            context={"cargo_type": cargo_type},
            requested_outputs=["rates"],
            timeout=15.0,
        )
        results["rates"] = rate_result.result if rate_result.result else None

        # Step 2: Check port availability (auto-approve)
        logger.info("Step 2: Checking port availability...")
        port_result = await self.client.submit_intent(
            f"Check if {destination} port is operational",
            context={"port_name": destination},
            requested_outputs=["status"],
            timeout=10.0,
        )
        results["port_status"] = port_result.result if port_result.result else None

        # Step 3: Optimize route — explicitly review this plan
        if results.get("port_status", {}).get("operational", True):
            logger.info("Step 3: Optimizing route (with explicit plan review)...")

            async def review_route_plan(
                plan: OfferPayload, envelope: AgBusEnvelope,
            ) -> PlanDecision:
                logger.info("  🔍 Reviewing route optimization plan:")
                logger.info("    Agents: %s", plan.participating_agents)
                return PlanDecision(action="approve")

            route_result = await self.client.submit_intent(
                f"Optimize logistics route from {origin} to {destination}",
                context={
                    "origin": origin,
                    "destination": destination,
                    "cargo_type": cargo_type,
                    "rates": results.get("rates"),
                },
                requested_outputs=["optimized_route", "cost_estimate"],
                timeout=20.0,
                plan_approval=review_route_plan,
            )
            results["route"] = route_result.result if route_result.result else None
        else:
            logger.warning("Port unavailable – skipping route optimization")

        logger.info("✅ Orchestration complete!")
        logger.info("📊 Results: %s", results)
        return results


async def example_orchestrator():
    """Demonstrate an orchestrator agent pattern."""
    logger.info("=" * 80)
    logger.info("Example 6: Orchestrator Agent (Multiple Intentions)")
    logger.info("=" * 80)

    orchestrator = OrchestratorAgent()
    results = await orchestrator.plan_global_logistics(
        origin="Shanghai Port, China",
        destination="Rotterdam Port, Netherlands",
        cargo_type="electronics",
    )

    logger.info("🎉 Final orchestration results: %s", results)


# ===========================================================================
# Main
# ===========================================================================

async def main():
    """Run all examples."""
    coordinator_uri = os.getenv("AGBUS_COORDINATOR_URI", "ws://localhost:8765")

    logger.info("\n🚀 Intent Client Examples")
    logger.info("Coordinator: %s\n", coordinator_uri)

    try:
        # Example 1: Simple (auto-approve)
        await example_simple()
        await asyncio.sleep(2)

        # Example 2: Explicit plan approval
        await example_with_plan_approval()
        await asyncio.sleep(2)

        # Example 3: Plan rejection
        await example_with_plan_rejection()
        await asyncio.sleep(2)

        # Example 4: Renegotiation
        await example_with_renegotiation()
        await asyncio.sleep(2)

        # Example 5: Streaming
        await example_streaming()
        await asyncio.sleep(2)

        # Example 6: Orchestrator
        await example_orchestrator()

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.exception("Example failed: %s", e)

    logger.info("\n✅ All examples complete!")


if __name__ == "__main__":
    asyncio.run(main())
