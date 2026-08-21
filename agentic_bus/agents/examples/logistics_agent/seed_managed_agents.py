"""Seed the logistics example as managed agents.

This script creates four managed (CrewAI-backed) agents in the Agentic Bus
database, reproducing the motivating logistics scenario from §1 of the
Liquid Interfaces paper:

    An AI agent within a logistics firm responding to a storm that has closed
    a port.  Rather than receiving a static "Route Unavailable" error, the
    agents negotiate alternative routes through the Agentic Bus Protocol.

Agents created:

1. **logistics-route-optimizer** – multi-modal route planning & optimization.
2. **warehouse-manager** – storage availability checks and space reservations.
3. **carrier-negotiator** – carrier selection and freight rate negotiation.
4. **disruption-analyst** – real-time disruption analysis and impact assessment.

Usage::

    # From the project root (agentic-bus/)
    python -m agentic_bus.agents.examples.logistics_agent.seed_managed_agents

    # Then activate & start them:
    agbus agent activate logistics-route-optimizer
    agbus agent activate warehouse-manager
    agbus agent activate carrier-negotiator
    agbus agent activate disruption-analyst

    agbus agent start logistics-route-optimizer
    agbus agent start warehouse-manager
    agbus agent start carrier-negotiator
    agbus agent start disruption-analyst

Pre-requisites:
    - ``agbus install`` has been run (database & LLM configured).
    - ``agbus db init`` has been run (tables created).
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

logging.basicConfig(
    level=os.getenv("AGBUS_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

AGENTS: list[dict] = [
    # ── 1. Logistics Route Optimizer ──────────────────────────────────
    {
        "agent_id": "logistics-route-optimizer",
        "name": "Logistics Route Optimizer",
        "role": (
            "Senior Logistics Route Planner specializing in multi-modal "
            "transport optimization across global supply chains"
        ),
        "goal": (
            "Find the most cost-effective, time-efficient, and reliable "
            "delivery routes by evaluating all available transport modalities "
            "(road, rail, sea, air) and dynamically re-routing when disruptions "
            "occur"
        ),
        "backstory": (
            "You are a veteran logistics strategist with 15 years of experience "
            "optimizing supply chain routes for Fortune 500 companies. You have "
            "deep expertise in intermodal transport, customs regulations, and "
            "real-time route adaptation. You are known for your ability to "
            "rapidly synthesize disruption reports, weather data, and carrier "
            "capacity into actionable routing decisions. You always consider "
            "cost, transit time, reliability, and carbon footprint when "
            "proposing routes. When a primary route is disrupted you immediately "
            "evaluate alternative corridors and present ranked options with "
            "clear trade-off analysis."
        ),
        "tools": ["SerperDevTool", "ScrapeWebsiteTool"],
        "capabilities": [
            {
                "capability_id": "route_optimization",
                "description": (
                    "Optimize delivery routes considering cost, time, and "
                    "delivery quality constraints. Supports multi-modal "
                    "transport (road, rail, sea, air) across global corridors."
                ),
                "expected_output": (
                    "A structured route plan with origin, destination, waypoints, "
                    "transport modalities, total distance, cost estimate in USD, "
                    "and time estimate with confidence level."
                ),
                "required_scopes": ["logistics:read", "logistics:route"],
                "supported_data_domains": ["logistics", "transportation", "supply_chain"],
                "operational_constraints": {
                    "max_radius_km": 20000,
                    "supported_modalities": ["road", "rail", "sea", "air"],
                },
                "expected_artifacts": [
                    "optimized_route",
                    "cost_estimate",
                    "time_estimate",
                ],
                "estimated_cost": 0.05,
                "estimated_latency": 3.0,
                "output_fields": [
                    {"name": "origin", "type": "str", "description": "Origin location"},
                    {"name": "destination", "type": "str", "description": "Destination location"},
                    {"name": "waypoints", "type": "list", "description": "Ordered list of intermediate waypoints"},
                    {"name": "modality", "type": "str", "description": "Transport modalities used (e.g. road+rail+sea)"},
                    {"name": "distance_km", "type": "float", "description": "Total route distance in kilometres"},
                    {"name": "cost_currency", "type": "str", "description": "Currency code for cost estimate"},
                    {"name": "cost_amount", "type": "float", "description": "Estimated cost amount"},
                    {"name": "time_hours", "type": "float", "description": "Estimated transit time in hours"},
                    {"name": "time_confidence", "type": "float", "description": "Confidence level 0-1 for the time estimate"},
                ],
            },
            {
                "capability_id": "alternative_routing",
                "description": (
                    "Discover and evaluate alternative delivery routes when "
                    "primary routes are disrupted (e.g., port closures, "
                    "weather events, strikes, geopolitical events)."
                ),
                "expected_output": (
                    "A list of ranked alternative routes with cost, time, and "
                    "reliability comparisons, plus a summary of the original "
                    "disruption and which risks each alternative mitigates."
                ),
                "required_scopes": [
                    "logistics:read",
                    "logistics:route",
                    "logistics:disruption",
                ],
                "supported_data_domains": [
                    "logistics",
                    "disruption_management",
                    "transportation",
                ],
                "operational_constraints": {
                    "response_time_seconds": 30,
                    "max_alternatives": 5,
                },
                "expected_artifacts": [
                    "alternative_routes",
                    "disruption_summary",
                ],
                "estimated_cost": 0.08,
                "estimated_latency": 5.0,
                "output_fields": [
                    {"name": "alternatives", "type": "list", "description": "Ranked list of alternative route objects"},
                    {"name": "original_disruption", "type": "str", "description": "Description of the disruption that triggered re-routing"},
                    {"name": "recommendation", "type": "str", "description": "Top recommended alternative with justification"},
                ],
            },
        ],
    },
    # ── 2. Warehouse Manager ─────────────────────────────────────────
    {
        "agent_id": "warehouse-manager",
        "name": "Warehouse Manager",
        "role": (
            "Warehouse Operations Manager specializing in dynamic storage "
            "allocation and container logistics"
        ),
        "goal": (
            "Manage warehouse capacity across a network of facilities, "
            "ensuring cargo has available storage during transit disruptions "
            "or planned layovers, while optimizing space utilization and cost"
        ),
        "backstory": (
            "You manage a network of 50+ warehouses across major logistics "
            "hubs in Europe, Asia, and the Americas. You have real-time "
            "visibility into capacity, temperature zones, hazardous material "
            "clearances, and security levels at each facility. When cargo "
            "needs temporary or long-term storage — especially during route "
            "disruptions — you can instantly check availability, calculate "
            "costs, and issue reservations. You always verify that the "
            "facility meets the cargo's specific requirements (temperature, "
            "hazmat class, TEU capacity) before confirming a reservation."
        ),
        "tools": [],
        "capabilities": [
            {
                "capability_id": "storage_availability",
                "description": (
                    "Check storage availability and reserve warehouse space "
                    "for temporary or long-term container storage near a "
                    "specified location or along a transport corridor."
                ),
                "expected_output": (
                    "A storage confirmation with reservation ID, facility "
                    "location, allocated capacity in TEU, daily cost, and "
                    "facility specifications (temperature controlled, "
                    "hazmat clearance, security level)."
                ),
                "required_scopes": ["warehouse:read", "warehouse:reserve"],
                "supported_data_domains": ["logistics", "warehousing", "supply_chain"],
                "operational_constraints": {
                    "max_capacity_teu": 500,
                    "temperature_controlled": True,
                    "hazmat_clearance": True,
                },
                "expected_artifacts": [
                    "storage_confirmation",
                    "reservation_id",
                    "facility_details",
                ],
                "estimated_cost": 0.02,
                "estimated_latency": 1.5,
                "output_fields": [
                    {"name": "storage_confirmed", "type": "bool", "description": "Whether storage was successfully reserved"},
                    {"name": "reservation_id", "type": "str", "description": "Unique reservation identifier"},
                    {"name": "facility_name", "type": "str", "description": "Name of the warehouse facility"},
                    {"name": "facility_location", "type": "str", "description": "Address or location of the facility"},
                    {"name": "capacity_allocated_teu", "type": "int", "description": "Number of TEU containers allocated"},
                    {"name": "daily_cost_usd", "type": "float", "description": "Daily storage cost in USD"},
                    {"name": "temperature_controlled", "type": "bool", "description": "Whether the space is temperature controlled"},
                ],
            },
        ],
    },
    # ── 3. Carrier Negotiator ────────────────────────────────────────
    {
        "agent_id": "carrier-negotiator",
        "name": "Carrier Negotiator",
        "role": (
            "Freight Carrier Negotiation Specialist with expertise in "
            "multi-modal transport procurement and rate optimization"
        ),
        "goal": (
            "Secure the best possible freight rates and service terms by "
            "evaluating carrier options across all transport modalities, "
            "negotiating volume discounts, and matching cargo requirements "
            "with carrier capabilities"
        ),
        "backstory": (
            "You are an expert freight broker with deep relationships across "
            "the global carrier network — ocean liners, rail operators, "
            "trucking companies, and air cargo providers. You track real-time "
            "spot rates, contract rates, and fuel surcharges. When presented "
            "with a shipment request you evaluate all available carriers on "
            "the corridor, check capacity and schedule alignment, and "
            "negotiate the best possible rate. You factor in carrier "
            "reliability scores, insurance requirements, and customs "
            "capabilities. In disruption scenarios you can rapidly source "
            "emergency capacity and expedited services."
        ),
        "tools": ["SerperDevTool"],
        "capabilities": [
            {
                "capability_id": "carrier_rate_quote",
                "description": (
                    "Obtain and compare freight rate quotes from multiple "
                    "carriers for a given origin-destination pair and cargo "
                    "specification. Includes spot rates, contract rates, and "
                    "expedited options."
                ),
                "expected_output": (
                    "A list of carrier quotes ranked by cost, with carrier "
                    "name, rate per TEU, transit time, reliability score, "
                    "and any special conditions or surcharges."
                ),
                "required_scopes": [
                    "carrier:read",
                    "carrier:negotiate",
                ],
                "supported_data_domains": [
                    "logistics",
                    "freight",
                    "carrier_management",
                ],
                "operational_constraints": {
                    "max_quotes": 10,
                    "include_spot_rates": True,
                    "include_contract_rates": True,
                },
                "expected_artifacts": [
                    "carrier_quotes",
                    "recommended_carrier",
                ],
                "estimated_cost": 0.04,
                "estimated_latency": 4.0,
                "output_fields": [
                    {"name": "quotes", "type": "list", "description": "List of carrier quote objects with rate, transit time, and reliability"},
                    {"name": "recommended_carrier", "type": "str", "description": "Name of the recommended carrier"},
                    {"name": "recommended_rate_usd", "type": "float", "description": "Rate per TEU in USD for the recommended carrier"},
                    {"name": "recommendation_reason", "type": "str", "description": "Justification for the recommendation"},
                ],
            },
            {
                "capability_id": "emergency_capacity",
                "description": (
                    "Source emergency freight capacity during disruptions. "
                    "Identify carriers with immediate availability on "
                    "alternative corridors and negotiate expedited rates."
                ),
                "expected_output": (
                    "Available emergency capacity options with carrier, "
                    "availability window, premium rate, and estimated "
                    "pickup time."
                ),
                "required_scopes": [
                    "carrier:read",
                    "carrier:negotiate",
                    "carrier:emergency",
                ],
                "supported_data_domains": [
                    "logistics",
                    "freight",
                    "disruption_management",
                ],
                "operational_constraints": {
                    "response_time_seconds": 15,
                    "priority": "high",
                },
                "expected_artifacts": [
                    "emergency_options",
                    "fastest_option",
                ],
                "estimated_cost": 0.06,
                "estimated_latency": 2.0,
                "output_fields": [
                    {"name": "emergency_options", "type": "list", "description": "Available emergency capacity options"},
                    {"name": "fastest_carrier", "type": "str", "description": "Carrier with the shortest lead time"},
                    {"name": "fastest_pickup_hours", "type": "float", "description": "Hours until earliest pickup"},
                    {"name": "premium_rate_usd", "type": "float", "description": "Emergency premium rate per TEU in USD"},
                ],
            },
        ],
    },
    # ── 4. Disruption Analyst ────────────────────────────────────────
    {
        "agent_id": "disruption-analyst",
        "name": "Disruption Analyst",
        "role": (
            "Supply Chain Disruption Analyst specializing in real-time "
            "risk assessment and impact modelling for logistics networks"
        ),
        "goal": (
            "Monitor, analyse, and quantify the impact of disruptions "
            "(weather, geopolitical events, strikes, port closures) on "
            "logistics operations, providing actionable intelligence that "
            "enables proactive re-routing and contingency planning"
        ),
        "backstory": (
            "You are a supply chain risk analyst who monitors global "
            "disruption events 24/7. You track weather systems, port "
            "congestion data, labour disputes, and geopolitical tensions. "
            "When a disruption occurs — such as a hurricane closing a port "
            "or a canal blockage — you immediately assess its severity, "
            "estimate duration, identify affected routes and carriers, and "
            "quantify the financial and temporal impact on in-transit "
            "shipments. Your analysis enables other agents (route optimizers, "
            "warehouse managers, carrier negotiators) to make informed "
            "decisions. You always include confidence levels and recommend "
            "whether to wait, re-route, or escalate."
        ),
        "tools": ["SerperDevTool", "ScrapeWebsiteTool"],
        "capabilities": [
            {
                "capability_id": "disruption_analysis",
                "description": (
                    "Analyse a specific disruption event (e.g., storm, port "
                    "closure, strike) and assess its impact on logistics "
                    "operations — affected routes, estimated duration, "
                    "severity, and recommended actions."
                ),
                "expected_output": (
                    "A disruption analysis report with event description, "
                    "severity (low/medium/high/critical), estimated duration, "
                    "list of affected routes and ports, financial impact "
                    "estimate, and recommended actions."
                ),
                "required_scopes": [
                    "disruption:read",
                    "disruption:analyse",
                ],
                "supported_data_domains": [
                    "logistics",
                    "disruption_management",
                    "risk_assessment",
                ],
                "operational_constraints": {
                    "response_time_seconds": 10,
                    "real_time_data": True,
                },
                "expected_artifacts": [
                    "disruption_report",
                    "affected_routes",
                    "recommended_actions",
                ],
                "estimated_cost": 0.06,
                "estimated_latency": 3.0,
                "output_fields": [
                    {"name": "event_description", "type": "str", "description": "Description of the disruption event"},
                    {"name": "severity", "type": "str", "description": "Severity level: low, medium, high, or critical"},
                    {"name": "estimated_duration_hours", "type": "float", "description": "Estimated duration of the disruption in hours"},
                    {"name": "affected_routes", "type": "list", "description": "List of affected route corridors"},
                    {"name": "affected_ports", "type": "list", "description": "List of affected ports or hubs"},
                    {"name": "financial_impact_usd", "type": "float", "description": "Estimated financial impact in USD"},
                    {"name": "recommended_action", "type": "str", "description": "Primary recommended action (wait, re-route, escalate)"},
                    {"name": "confidence", "type": "float", "description": "Confidence level 0-1 for the assessment"},
                ],
            },
            {
                "capability_id": "port_status_check",
                "description": (
                    "Check the operational status of a specific port or "
                    "logistics hub, including congestion levels, expected "
                    "delays, and any active disruptions."
                ),
                "expected_output": (
                    "Port status report with operational state, congestion "
                    "level, average delay, active disruptions, and forecast "
                    "for the next 48 hours."
                ),
                "required_scopes": [
                    "disruption:read",
                    "port:status",
                ],
                "supported_data_domains": [
                    "logistics",
                    "port_operations",
                ],
                "operational_constraints": {
                    "response_time_seconds": 5,
                },
                "expected_artifacts": [
                    "port_status",
                    "congestion_level",
                    "forecast",
                ],
                "estimated_cost": 0.02,
                "estimated_latency": 1.0,
                "output_fields": [
                    {"name": "port_name", "type": "str", "description": "Name of the port"},
                    {"name": "operational", "type": "bool", "description": "Whether the port is currently operational"},
                    {"name": "congestion_level", "type": "str", "description": "Congestion level: low, moderate, high, severe"},
                    {"name": "average_delay_hours", "type": "float", "description": "Current average delay in hours"},
                    {"name": "active_disruptions", "type": "list", "description": "List of active disruption descriptions"},
                    {"name": "forecast_48h", "type": "str", "description": "Operational forecast for the next 48 hours"},
                ],
            },
        ],
    },
]


def seed() -> None:
    """Create all logistics managed agents in the database."""
    from agentic_bus.core.persistence.database import init_db
    from agentic_bus.core.persistence.managed_agent_repository import ManagedAgentRepository
    from agentic_bus.core.persistence.models import ManagedAgentStatus

    init_db()
    repo = ManagedAgentRepository()

    created = []
    skipped = []

    for defn in AGENTS:
        agent_id = defn["agent_id"]

        # Skip if already exists
        existing = repo.get(agent_id)
        if existing is not None:
            logger.warning("Agent %r already exists (status=%s) — skipping", agent_id, existing.status.value)
            skipped.append(agent_id)
            continue

        agent = repo.create(
            agent_id=agent_id,
            name=defn["name"],
            role=defn["role"],
            goal=defn["goal"],
            backstory=defn["backstory"],
            tools=defn.get("tools", []),
            capabilities=defn.get("capabilities", []),
            status=ManagedAgentStatus.ACTIVE,
            created_by="seed:logistics-example",
        )
        created.append(agent_id)
        logger.info(
            "✓ Created agent %r (capabilities=%d, tools=%d)",
            agent_id,
            len(agent.capabilities),
            len(agent.tools_json),
        )

    # Summary
    print()
    print("=" * 70)
    print("  Logistics Example — Managed Agent Seeding Complete")
    print("=" * 70)
    print()
    if created:
        print(f"  ✅ Created {len(created)} agent(s):")
        for aid in created:
            print(f"     • {aid}")
    if skipped:
        print(f"  ⏭️  Skipped {len(skipped)} agent(s) (already exist):")
        for aid in skipped:
            print(f"     • {aid}")
    print()
    print("  All agents are ACTIVE and ready to start.")
    print()
    print("  Start them with:")
    print()
    for defn in AGENTS:
        print(f"    agbus agent start {defn['agent_id']}")
    print()
    print("  Or run the demo intent client:")
    print()
    print("    python -m agentic_bus.agents.examples.logistics_agent.demo_intent")
    print()


if __name__ == "__main__":
    seed()
