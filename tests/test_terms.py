"""Intent terms (RFC 0004): what a plan may not alter.

LIP negotiates *how* an intent is fulfilled and not *what it is*, and until
now had no field in which that distinction lived: an 18% discount was prose,
or an unlabelled key in ``context``, so an agent offering 16% had proposed a
different objective and nothing could tell that from proposing a means.

The tests that carry the claim are the ones where an offer names a term the
intent marks fixed and gives it a different value — because the plan must be
refused *with both values*, not quietly composed from the other offers, and
not reconciled by preferring either number. The requester changes their own
terms; agents do not.

Deliberate about what is not claimed: both sides of the comparison are
declared. An agent that alters a term without saying so passes every check
here and is caught, if at all, at the artifact.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from agentic_bus import AgentCapability, BaseAgent, Decline
from agentic_bus.core.ibac.engine import IBACDecision, IBACEvaluationPoint, IBACResult
from agentic_bus.core.protocol.envelope import (
    AgBusEnvelope,
    ErrorInfo,
    IntentPayload,
    IntentTerm,
    MessageType,
    OfferPayload,
    RejectPayload,
    SenderInfo,
    SenderKind,
    build_envelope,
)
from agentic_bus.core.session.manager import NegotiationRecord, SessionPhase
from agentic_bus.core.step_inputs import compose_step_inputs
from agentic_bus.core.terms import (
    TermDivergence,
    apply_fixed_terms,
    compare_terms,
    describe_terms,
    values_differ,
)
from agentic_bus.core.transport.local import LocalTransport
from agentic_bus.testing import LocalBus

DISCOUNT = IntentTerm(name="discount", value=0.18, fixed=True)
DELIVERY = IntentTerm(name="delivery_days", value=5)
TERMS = [DISCOUNT, DELIVERY, IntentTerm(name="coupon_hours", value=24, fixed=True)]


# ---------------------------------------------------------------------------
# The comparison. Equality is the whole of the semantics.
# ---------------------------------------------------------------------------


class TestComparison:
    def test_same_name_different_value_is_a_divergence(self):
        report = compare_terms(TERMS, {"discount": 0.16}, agent_id="sales", capability_id="issue_coupon")

        assert len(report.divergences) == 1
        d = report.divergences[0]
        assert (d.name, d.stated, d.proposed, d.fixed) == ("discount", 0.18, 0.16, True)
        assert d.agent_id == "sales" and d.capability_id == "issue_coupon"

    def test_a_divergence_from_a_fixed_term_is_a_contradiction(self):
        report = compare_terms(TERMS, {"discount": 0.16, "delivery_days": 3})

        assert [d.name for d in report.contradictions] == ["discount"]
        assert [d.name for d in report.tolerated] == ["delivery_days"]
        assert not report.ok

    def test_a_divergence_from_a_target_is_tolerated(self):
        report = compare_terms(TERMS, {"delivery_days": 3})

        assert report.ok
        assert [d.name for d in report.tolerated] == ["delivery_days"]

    def test_the_same_value_is_not_a_divergence(self):
        assert compare_terms(TERMS, {"discount": 0.18, "coupon_hours": 24}).divergences == []

    def test_an_offer_need_not_answer_every_term(self):
        """The requirement is not to alter, not to answer."""
        assert compare_terms(TERMS, {"max_rows": 50_000}).divergences == []
        assert compare_terms(TERMS, {}).divergences == []
        assert compare_terms([], {"discount": 0.16}).divergences == []

    def test_no_narrowing_semantics_are_invented(self):
        """`max_discount: 0.16` does not name `discount`. Under equality a
        coordinator cannot know that it narrows the term, and guessing would
        be a small language nobody checked."""
        assert compare_terms(TERMS, {"max_discount": 0.16}).divergences == []

    def test_three_days_is_not_known_to_beat_five(self):
        """Listed as a limitation in the RFC, pinned here so it stays one
        rather than becoming an accidental behaviour."""
        report = compare_terms(TERMS, {"delivery_days": 3})
        assert report.tolerated and report.tolerated[0].proposed == 3

    def test_terms_may_be_models_or_dicts(self):
        as_dicts = [{"name": "discount", "value": 0.18, "fixed": True}]
        assert compare_terms(as_dicts, {"discount": 0.16}).contradictions
        assert compare_terms([{"value": 1}], {"discount": 0.16}).divergences == []

    def test_the_summary_names_who_and_both_values(self):
        d = compare_terms(TERMS, {"discount": 0.16}, agent_id="sales-agent", capability_id="issue_coupon").divergences[0]

        assert str(d) == "sales-agent:issue_coupon proposes discount 0.16; the intent fixes it at 0.18"

    def test_a_tolerated_divergence_reads_as_a_difference_not_a_breach(self):
        d = compare_terms(TERMS, {"delivery_days": 3}, agent_id="carrier").divergences[0]

        assert str(d) == "carrier proposes delivery_days 3; the intent states 5"


class TestValueEquality:
    def test_integers_and_floats_agree(self):
        assert not values_differ(5, 5.0)

    def test_a_boolean_is_not_a_number(self):
        assert values_differ(True, 1)
        assert values_differ(0, False)

    def test_a_string_is_not_a_number(self):
        """`"0.18"` and `0.18` are different claims; a coordinator that
        coerced one into the other would be reconciling."""
        assert values_differ("0.18", 0.18)

    def test_structured_values_compare_whole(self):
        assert not values_differ({"currency": "BRL", "amount": 40000}, {"currency": "BRL", "amount": 40000})
        assert values_differ([1, 2], [2, 1])


class TestFixedTermsConstrainComposition:
    """RFC 0005 meets RFC 0004: composition proposes; a fixed term is not a proposal."""

    def test_a_composed_parameter_naming_a_fixed_term_is_held_to_it(self):
        corrected, overridden = apply_fixed_terms({"discount": 0.16, "descricao": "x"}, TERMS)

        assert corrected == {"discount": 0.18, "descricao": "x"}
        assert [d.name for d in overridden] == ["discount"]

    def test_a_fixed_term_is_not_injected_where_the_schema_has_no_field(self):
        corrected, overridden = apply_fixed_terms({"descricao": "x"}, TERMS)

        assert corrected == {"descricao": "x"}
        assert overridden == []

    def test_a_target_is_left_to_the_composition(self):
        corrected, overridden = apply_fixed_terms({"delivery_days": 3}, TERMS)

        assert corrected == {"delivery_days": 3}
        assert overridden == []

    def test_an_agreeing_value_is_not_an_override(self):
        _, overridden = apply_fixed_terms({"discount": 0.18}, TERMS)
        assert overridden == []


class TestDescribingTermsToAModel:
    def test_fixity_is_spelt_out(self):
        text = describe_terms(TERMS)

        assert "discount: 0.18 (fixed — no plan may change it)" in text
        assert "delivery_days: 5 (a target)" in text

    def test_no_terms_says_so(self):
        assert describe_terms([]) == "  (none stated)"
        assert describe_terms(None) == "  (none stated)"


# ---------------------------------------------------------------------------
# The coordinator. The check sits beside negotiation acceptance.
# ---------------------------------------------------------------------------


class _Model:
    def __init__(self, answer):
        self.answer = answer
        self.prompts: list[str] = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        return type("R", (), {"content": self.answer})()


@pytest.fixture
async def runtime():
    from agentic_bus.coordinator.runtime import CoordinatorRuntime

    rt = CoordinatorRuntime(transport=LocalTransport())
    await rt.start()
    rt.ibac.evaluate_with_llm = AsyncMock(
        return_value=IBACResult(
            decision=IBACDecision.ALLOW,
            evaluation_point=IBACEvaluationPoint.NEGOTIATION_ACCEPTANCE,
            reason="allowed",
        )
    )
    yield rt
    await rt.stop()


class _Requester:
    """A requester attached in-process, keeping what the coordinator sent it."""

    def __init__(self):
        self.received: list[AgBusEnvelope] = []

    async def deliver(self, envelope, _peer):
        self.received.append(envelope)

    def of_type(self, message_type: MessageType) -> list[AgBusEnvelope]:
        return [e for e in self.received if e.message_type == message_type]

    @property
    def rejects(self) -> list[RejectPayload]:
        return [RejectPayload.model_validate(e.payload) for e in self.of_type(MessageType.REJECT)]

    @property
    def plans(self) -> list[OfferPayload]:
        return [
            OfferPayload.model_validate(e.payload)
            for e in self.of_type(MessageType.OFFER)
            if e.payload.get("capability_id") == "__composed_plan__"
        ]


async def _negotiating_session(runtime, *, terms, offers):
    """A session in negotiation, every solicited agent having answered.

    *offers* maps ``(agent_id, capability_id)`` to the offer's constraints.
    """
    requester = _Requester()
    await runtime._server.connect("req", on_receive=requester.deliver)

    session = runtime.sessions.create(requester_id="u1")
    session.intent = IntentPayload(
        intent_text="Send customer 88213 an upsell email with an 18% coupon",
        terms=terms,
    )
    session.phase = SessionPhase.NEGOTIATION
    runtime._session_requester_peers[session.session_id] = "req"
    for (agent_id, capability_id), constraints in offers.items():
        session.solicited_agents.append(agent_id)
        session.offers.append(
            NegotiationRecord(
                agent_id=agent_id,
                offer=OfferPayload(capability_id=capability_id, constraints=constraints),
                status="pending",
            )
        )
    return session, requester


class TestAContradictedFixedTermRefusesThePlan:
    async def test_the_requester_is_told_which_term_and_both_values(self, runtime):
        session, requester = await _negotiating_session(
            runtime,
            terms=TERMS,
            offers={("sales-agent", "issue_coupon"): {"discount": 0.16}},
        )

        await runtime._try_converge(session)

        assert requester.plans == [], "a plan contradicting a fixed term was proposed"
        (reject,) = requester.rejects
        assert reject.error is not None
        assert reject.error.category == "constraint_violation"
        assert reject.error.message == (
            "sales-agent:issue_coupon proposes discount 0.16; the intent fixes it at 0.18"
        )
        assert reject.reason == reject.error.message
        assert reject.error.recoverable is True
        assert reject.rejected_offers == ["sales-agent"]

    async def test_the_suggestion_is_for_the_requester_to_decide(self, runtime):
        """The requester changes their own terms; agents do not."""
        session, requester = await _negotiating_session(
            runtime,
            terms=TERMS,
            offers={("sales-agent", "issue_coupon"): {"discount": 0.16}},
        )

        await runtime._try_converge(session)

        suggestions = requester.rejects[0].error.suggestions
        assert "Resubmit with discount 0.16 if that is acceptable" in suggestions
        assert "The term is marked fixed, so no agent may change it" in suggestions

    async def test_the_session_is_dissolved_not_left_waiting(self, runtime):
        session, requester = await _negotiating_session(
            runtime,
            terms=TERMS,
            offers={("sales-agent", "issue_coupon"): {"discount": 0.16}},
        )

        await runtime._try_converge(session)

        assert runtime.sessions.get(session.session_id) is None
        assert requester.of_type(MessageType.DISSOLVE)

    async def test_the_whole_plan_is_refused_not_just_the_offer(self, runtime):
        """Composing from the remaining offers would be reconciliation in
        another form: the plan would quietly not do what was asked."""
        session, requester = await _negotiating_session(
            runtime,
            terms=TERMS,
            offers={
                ("crm-reader", "crm.buscar"): {"max_rows": 50_000},
                ("sales-agent", "issue_coupon"): {"discount": 0.16},
                ("mailer", "email.enviar"): {},
            },
        )

        await runtime._try_converge(session)

        assert requester.plans == []
        assert requester.rejects[0].rejected_offers == ["sales-agent"]
        assert runtime.sessions.get(session.session_id) is None

    async def test_every_contradiction_is_reported(self, runtime):
        session, requester = await _negotiating_session(
            runtime,
            terms=TERMS,
            offers={
                ("sales-agent", "issue_coupon"): {"discount": 0.16, "coupon_hours": 48},
            },
        )

        await runtime._try_converge(session)

        message = requester.rejects[0].error.message
        assert "discount 0.16" in message and "coupon_hours 48" in message
        assert "These terms are marked fixed" in requester.rejects[0].error.suggestions[-1]

    async def test_no_model_reads_the_check(self, runtime):
        """Deterministic: the contradiction is found before IBAC's negotiation
        acceptance runs, and no wording of the intent changes it."""
        session, _ = await _negotiating_session(
            runtime,
            terms=TERMS,
            offers={("sales-agent", "issue_coupon"): {"discount": 0.16}},
        )

        await runtime._try_converge(session)

        runtime.ibac.evaluate_with_llm.assert_not_called()

    async def test_the_contradiction_is_audited(self, runtime):
        session, _ = await _negotiating_session(
            runtime,
            terms=TERMS,
            offers={("sales-agent", "issue_coupon"): {"discount": 0.16}},
        )

        await runtime._try_converge(session)

        entries = [e for e in runtime.audit_log.list_all() if e.action == "terms.contradicted"]
        assert entries and entries[0].actor == "sales-agent"
        assert "0.16" in entries[0].details and "0.18" in entries[0].details


class TestADivergenceFromATargetIsShownNotRefused:
    async def test_the_plan_proceeds_and_carries_the_divergence(self, runtime):
        session, requester = await _negotiating_session(
            runtime,
            terms=TERMS,
            offers={("carrier", "check_availability"): {"delivery_days": 3}},
        )

        await runtime._try_converge(session)

        assert requester.rejects == []
        (plan,) = requester.plans
        divergences = plan.composition_plan["term_divergences"]
        assert divergences == [
            {
                "name": "delivery_days",
                "stated": 5,
                "proposed": 3,
                "fixed": False,
                "agent_id": "carrier",
                "capability_id": "check_availability",
            }
        ]
        assert "carrier:check_availability proposes delivery_days 3" in plan.capability_description

    async def test_the_plan_echoes_the_terms_it_was_held_to(self, runtime):
        """A plan carrying no terms came from a coordinator that never read
        them — which is how a requester sees the absence of enforcement."""
        session, requester = await _negotiating_session(
            runtime,
            terms=TERMS,
            offers={("sales-agent", "issue_coupon"): {"discount": 0.18}},
        )

        await runtime._try_converge(session)

        (plan,) = requester.plans
        assert plan.composition_plan["terms"] == [t.model_dump() for t in TERMS]
        assert "term_divergences" not in plan.composition_plan
        assert " — diverges" not in plan.capability_description

    async def test_the_session_plan_keeps_the_divergences_for_the_archive(self, runtime):
        session, _ = await _negotiating_session(
            runtime,
            terms=TERMS,
            offers={("carrier", "check_availability"): {"delivery_days": 3}},
        )

        await runtime._try_converge(session)

        assert session.composition_plan["term_divergences"][0]["name"] == "delivery_days"


class TestAnIntentWithoutTermsIsUntouched:
    async def test_nothing_to_enforce_as_today(self, runtime):
        session, requester = await _negotiating_session(
            runtime,
            terms=[],
            offers={("sales-agent", "issue_coupon"): {"discount": 0.16}},
        )

        await runtime._try_converge(session)

        assert requester.rejects == []
        (plan,) = requester.plans
        assert "terms" not in plan.composition_plan
        assert "term_divergences" not in plan.composition_plan


class TestTheIntentIsRelayedWithItsTerms:
    async def test_candidate_agents_see_the_terms(self, runtime):
        seen: list[AgBusEnvelope] = []

        async def deliver(envelope, _peer):
            seen.append(envelope)

        await runtime._server.connect("sales-peer", on_receive=deliver)
        runtime._agent_peers["sales-agent"] = "sales-peer"
        session = runtime.sessions.create(requester_id="u1")
        session.intent = IntentPayload(intent_text="upsell", terms=TERMS)
        candidate = type("C", (), {"agent_id": "sales-agent"})()

        await runtime._request_offers(session, [candidate])

        (intent,) = [e for e in seen if e.message_type == MessageType.INTENT]
        relayed = IntentPayload.model_validate(intent.payload)
        assert relayed.fixed_terms == {"discount": 0.18, "coupon_hours": 24}


class TestAnAgentMayDecline:
    def _decline(self, session_id: str, agent_id: str = "sales-agent") -> AgBusEnvelope:
        return build_envelope(
            MessageType.REJECT,
            SenderInfo(kind=SenderKind.AGENT, id=agent_id),
            session_id,
            RejectPayload(
                rejected_offers=["issue_coupon"],
                reason="cannot honour discount 0.18; my ceiling is 0.16",
                error=ErrorInfo(
                    category="constraint_violation",
                    message="cannot honour discount 0.18; my ceiling is 0.16",
                ),
            ),
        )

    async def test_negotiation_proceeds_without_the_decliner(self, runtime):
        session, requester = await _negotiating_session(
            runtime,
            terms=TERMS,
            offers={("crm-reader", "crm.buscar"): {}},
        )
        session.solicited_agents.append("sales-agent")  # solicited, not yet answered

        await runtime._handle_reject(self._decline(session.session_id), None)

        assert requester.rejects == [], "an agent's decline dissolved the session"
        (plan,) = requester.plans
        assert [s["agent_id"] for s in plan.composition_plan["steps"]] == ["crm-reader"]
        declined = [o for o in session.offers if o.agent_id == "sales-agent"]
        assert declined and declined[0].status == "rejected"
        assert "ceiling is 0.16" in declined[0].rejection_reason

    async def test_a_session_where_everyone_declined_is_refused_not_stalled(self, runtime):
        session, requester = await _negotiating_session(runtime, terms=TERMS, offers={})
        session.solicited_agents.append("sales-agent")

        await runtime._handle_reject(self._decline(session.session_id), None)

        assert requester.plans == []
        assert requester.rejects, "nobody offered and the requester was not told"
        assert runtime.sessions.get(session.session_id) is None

    async def test_an_agent_cannot_dissolve_a_session_it_does_not_own(self, runtime):
        session, requester = await _negotiating_session(
            runtime,
            terms=TERMS,
            offers={("crm-reader", "crm.buscar"): {}},
        )
        session.phase = SessionPhase.AWAITING_APPROVAL

        await runtime._handle_reject(self._decline(session.session_id), None)

        assert runtime.sessions.get(session.session_id) is not None
        assert requester.of_type(MessageType.DISSOLVE) == []
        assert not [o for o in session.offers if o.agent_id == "sales-agent"]


class TestCompositionIsHeldToFixedTerms:
    SCHEMA = {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "who"},
            "discount": {"type": "number", "description": "the discount to issue"},
        },
        "required": ["customer_id", "discount"],
    }

    def _step(self):
        return {
            "agent_id": "sales-agent",
            "capability_id": "issue_coupon",
            "description": "Issues a coupon",
            "input_schema": self.SCHEMA,
        }

    async def test_a_proposed_value_for_a_fixed_term_is_corrected(self):
        model = _Model('{"customer_id": "88213", "discount": 0.16}')

        composed = await compose_step_inputs(
            intent_text="upsell with an 18% coupon", step=self._step(), llm=model, terms=TERMS
        )

        assert composed.ok
        assert composed.inputs["discount"] == 0.18
        assert composed.term_overrides == ["discount"]

    async def test_the_model_is_shown_the_terms(self):
        model = _Model('{"customer_id": "88213", "discount": 0.18}')

        composed = await compose_step_inputs(
            intent_text="upsell", step=self._step(), llm=model, terms=TERMS
        )

        assert "discount: 0.18 (fixed — no plan may change it)" in model.prompts[0]
        assert composed.term_overrides == []

    async def test_without_terms_nothing_changes(self):
        model = _Model('{"customer_id": "88213", "discount": 0.16}')

        composed = await compose_step_inputs(intent_text="upsell", step=self._step(), llm=model)

        assert composed.inputs["discount"] == 0.16
        assert "(none stated)" in model.prompts[0]


# ---------------------------------------------------------------------------
# The agent SDK, over a real socket.
# ---------------------------------------------------------------------------


class CouponAgent(BaseAgent):
    """Can issue up to 16%. Reads the term rather than assuming it is adjustable."""

    ceiling = 0.16

    def capabilities(self):
        return [
            AgentCapability(
                capability_id="issue_coupon",
                description="Issues a discount coupon",
                operational_constraints={"max_discount": self.ceiling},
            )
        ]

    async def generate_offer(self, intent, capability):
        term = intent.term("discount")
        if term is not None and term.fixed and term.value > self.ceiling:
            return Decline(f"cannot honour discount {term.value}; my ceiling is {self.ceiling}")
        return await super().generate_offer(intent, capability)

    async def execute_task(self, payload, context):
        return {"coupon": "X"}


class HonestAgent(BaseAgent):
    """Declares what it does in its constraints and lets the coordinator compare."""

    def capabilities(self):
        return [
            AgentCapability(
                capability_id="issue_coupon",
                description="Issues a 16% coupon",
                operational_constraints={"discount": 0.16},
            )
        ]

    async def execute_task(self, payload, context):
        return {}


class QuietAgent(BaseAgent):
    def capabilities(self):
        return [AgentCapability(capability_id="anything", description="whatever")]

    async def generate_offer(self, intent, capability):
        return None

    async def execute_task(self, payload, context):
        return {}


class TestTheSDK:
    async def test_declining_is_a_reject_naming_the_capability(self):
        async with LocalBus() as bus:
            await bus.add_agent(CouponAgent(agent_id="sales"))

            offers = await bus.send_intent(
                "upsell with an 18% coupon",
                terms=[{"name": "discount", "value": 0.18, "fixed": True}],
            )

            assert offers == []
            (decline,) = bus.declines()
            assert decline.rejected_offers == ["issue_coupon"]
            assert decline.error.category == "constraint_violation"
            assert "ceiling is 0.16" in decline.reason
            assert decline.error.message == decline.reason

    async def test_a_term_it_can_meet_draws_an_offer(self):
        async with LocalBus() as bus:
            await bus.add_agent(CouponAgent(agent_id="sales"))

            offers = await bus.send_intent(
                "upsell with a 10% coupon",
                terms=[IntentTerm(name="discount", value=0.10, fixed=True)],
            )

            assert [o.capability_id for o in offers] == ["issue_coupon"]
            assert bus.declines() == []

    async def test_a_target_is_not_a_reason_to_decline(self):
        """An agent MUST NOT assume a term is adjustable because it is a
        number — and equally, need not refuse one it may propose against."""
        async with LocalBus() as bus:
            await bus.add_agent(CouponAgent(agent_id="sales"))

            offers = await bus.send_intent(
                "upsell, ideally at 18%",
                terms=[{"name": "discount", "value": 0.18}],
            )

            assert len(offers) == 1

    async def test_returning_none_declines_with_a_stock_reason(self):
        async with LocalBus() as bus:
            await bus.add_agent(QuietAgent(agent_id="quiet"))

            offers = await bus.send_intent("anything at all")

            assert offers == []
            assert bus.declines()[0].reason == "declined to offer"

    async def test_operational_constraints_are_the_offer_s_answer_to_a_term(self):
        """A declared 16% against a fixed 18% is what lets the coordinator
        refuse the plan by name and with both values."""
        async with LocalBus() as bus:
            await bus.add_agent(HonestAgent(agent_id="honest"))

            (offer,) = await bus.send_intent(
                "upsell with an 18% coupon",
                terms=[{"name": "discount", "value": 0.18, "fixed": True}],
            )

            report = compare_terms(
                [DISCOUNT], offer.constraints, agent_id="honest", capability_id=offer.capability_id
            )
            assert [str(d) for d in report.contradictions] == [
                "honest:issue_coupon proposes discount 0.16; the intent fixes it at 0.18"
            ]

    async def test_the_harness_returns_as_soon_as_the_agent_has_answered(self):
        async with LocalBus() as bus:
            await bus.add_agent(CouponAgent(agent_id="sales"))
            loop = asyncio.get_running_loop()
            started = loop.time()

            await bus.send_intent(
                "upsell with an 18% coupon",
                terms=[{"name": "discount", "value": 0.18, "fixed": True}],
                timeout=5.0,
            )

            assert loop.time() - started < 2.0, "a decline should not wait out the timeout"


class TestTheRequesterClient:
    async def test_terms_travel_on_the_intent(self):
        from agentic_bus.agents.requester import IntentClient

        sent: list[str] = []

        class _WS:
            async def send(self, raw):
                sent.append(raw)

        client = IntentClient(requester_id="app")
        await client._send_intent(
            _WS(),
            "s1",
            "upsell with an 18% coupon",
            {"customer_id": "88213"},
            None,
            None,
            terms=[{"name": "discount", "value": 0.18, "fixed": True}, DELIVERY],
        )

        envelope = AgBusEnvelope.model_validate_json(sent[0])
        payload = IntentPayload.model_validate(envelope.payload)
        assert payload.fixed_terms == {"discount": 0.18}
        assert payload.term("delivery_days").value == 5


class TestTheWireShapeOfADivergence:
    def test_as_dict_round_trips(self):
        d = TermDivergence(name="n", stated=1, proposed=2, fixed=True, agent_id="a", capability_id="c")
        assert TermDivergence(**d.as_dict()) == d
