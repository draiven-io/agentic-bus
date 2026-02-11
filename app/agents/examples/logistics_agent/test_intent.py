"""Test client for sending intents to the logistics agent.

This script demonstrates how a requester would send an intent to discover
and negotiate with logistics routing agents through the Agentic Bus coordinator.

Run with::

    python -m app.agents.examples.logistics_agent.test_intent

Make sure the coordinator is running and the logistics agent is registered.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
import websockets

load_dotenv()

from app.core.protocol.envelope import (
    AgBusEnvelope,
    MessageType,
    SenderInfo,
    SenderKind,
    IntentPayload,
)

logging.basicConfig(
    level=os.getenv("AGBUS_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def send_intent(
    intent_text: str,
    context: dict = None,
    requested_outputs: list[str] = None,
    coordinator_uri: str = "ws://localhost:8765",
) -> None:
    """Send an intent to the coordinator and wait for responses.
    
    Args:
        intent_text: The natural language intent description
        context: Additional context data (origin, destination, constraints, etc.)
        requested_outputs: List of expected output artifacts
        coordinator_uri: WebSocket URI of the coordinator
    """
    context = context or {}
    requested_outputs = requested_outputs or []
    
    # Build the intent message
    sender = SenderInfo(
        kind=SenderKind.REQUESTER,
        id="test-requester-01",
        oidc_subject="test-user@example.com",
    )
    
    payload = IntentPayload(
        intent_text=intent_text,
        context=context,
        requested_outputs=requested_outputs,
        ibac_claims_requested=["logistics:read", "logistics:route"],
    )
    
    envelope = AgBusEnvelope(
        message_type=MessageType.INTENT,
        sender=sender,
        session_id=f"test-session-{datetime.now(timezone.utc).timestamp()}",
        payload=payload.model_dump(),
    )
    
    logger.info("🚀 Sending intent: %s", intent_text)
    logger.info("📦 Context: %s", json.dumps(context, indent=2))
    
    try:
        async with websockets.connect(coordinator_uri) as websocket:
            # Send the intent
            await websocket.send(envelope.model_dump_json())
            logger.info("✅ Intent sent successfully")
            
            # Wait for responses (offers, execution results, etc.)
            logger.info("⏳ Waiting for responses from coordinator...")
            
            async for message in websocket:
                try:
                    response = json.loads(message)
                    msg_type = response.get("message_type", "unknown")
                    
                    logger.info("📨 Received message type: %s", msg_type)
                    logger.info("📄 Response: %s", json.dumps(response, indent=2))
                    
                    # Handle different message types
                    if msg_type == "offer":
                        capability_id = response.get("payload", {}).get("capability_id")
                        logger.info("🎯 Received offer for capability: %s", capability_id)
                        
                    elif msg_type == "complete":
                        logger.info("✅ Execution completed")
                        logger.info("🎉 Result: %s", json.dumps(response.get("payload", {}), indent=2))
                        break
                        
                    elif msg_type == "reject":
                        reason = response.get("payload", {}).get("reason")
                        logger.warning("❌ Intent rejected: %s", reason)
                        break
                        
                except json.JSONDecodeError:
                    logger.error("Failed to decode response: %s", message)
                    
    except Exception as e:
        logger.error("❌ Connection error: %s", e)
        logger.error("Make sure the coordinator is running at %s", coordinator_uri)


async def test_route_optimization():
    """Test the route_optimization capability."""
    logger.info("=" * 80)
    logger.info("TEST: Route Optimization")
    logger.info("=" * 80)
    
    await send_intent(
        intent_text="Find the most cost-effective route from Shanghai to Rotterdam",
        context={
            "origin": "Shanghai Port, China",
            "destination": "Rotterdam Port, Netherlands",
            "cargo_type": "electronics",
            "urgency": "standard",
            "max_cost_usd": 5000,
        },
        requested_outputs=["optimized_route", "cost_estimate", "time_estimate"],
    )


async def test_alternative_routing():
    """Test the alternative_routing capability (port closure scenario)."""
    logger.info("=" * 80)
    logger.info("TEST: Alternative Routing (Port Closure)")
    logger.info("=" * 80)
    
    await send_intent(
        intent_text=(
            "Find alternative routes from Los Angeles to Miami. "
            "The Port of New Orleans is closed due to a hurricane."
        ),
        context={
            "origin": "Port of Los Angeles, CA",
            "destination": "Port of Miami, FL",
            "disruption": "Hurricane closure at Port of New Orleans",
            "disrupted_ports": ["Port of New Orleans"],
            "cargo_type": "consumer goods",
            "containers": 25,
            "urgency": "high",
        },
        requested_outputs=["alternative_routes", "disruption_summary"],
    )


async def test_multimodal_routing():
    """Test multi-modal routing with storage requirement."""
    logger.info("=" * 80)
    logger.info("TEST: Multi-Modal Routing with Storage")
    logger.info("=" * 80)
    
    await send_intent(
        intent_text=(
            "Plan a multi-modal route from Hamburg to Budapest with intermediate "
            "storage. I need to store 10 TEU containers for 3 days in Vienna."
        ),
        context={
            "origin": "Hamburg Port, Germany",
            "destination": "Budapest, Hungary",
            "intermediate_storage": {
                "location": "Vienna, Austria",
                "duration_days": 3,
                "capacity_teu": 10,
            },
            "modalities_preferred": ["sea", "rail", "road"],
            "delivery_deadline": "2026-02-20T00:00:00Z",
        },
        requested_outputs=[
            "optimized_route",
            "storage_confirmation",
            "cost_estimate",
            "time_estimate",
        ],
    )


async def main():
    """Run all test scenarios."""
    coordinator_uri = os.getenv("AGBUS_COORDINATOR_URI", "ws://localhost:8765")
    
    logger.info("\n")
    logger.info("╔════════════════════════════════════════════════════════════════╗")
    logger.info("║         Agentic Bus Logistics Agent Intent Test Suite                 ║")
    logger.info("╚════════════════════════════════════════════════════════════════╝")
    logger.info("\n")
    logger.info("Coordinator URI: %s", coordinator_uri)
    logger.info("\n")
    
    # Run tests sequentially
    try:
        await test_route_optimization()
        await asyncio.sleep(2)  # Brief pause between tests
        
        await test_alternative_routing()
        await asyncio.sleep(2)
        
        await test_multimodal_routing()
        
    except KeyboardInterrupt:
        logger.info("\n⚠️  Test interrupted by user")
    except Exception as e:
        logger.error("❌ Test failed: %s", e)
    finally:
        logger.info("\n")
        logger.info("=" * 80)
        logger.info("Test suite completed")
        logger.info("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
