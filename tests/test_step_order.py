"""Ordering plan steps by the decomposition the intent processor produced.

``compose_offers`` listed steps in the order their offers arrived, which is
network timing. Meanwhile the intent processor had already spent a model call
producing ``sub_intents`` with ``dependencies`` — written to the session
archive and never read back. In the onboarding example that meant the mail
step could run before the step that fetched the template, and did.

The tests that carry the claim are the ones where the model answers badly: the
step *set* is authoritative and the order is advisory, so an answer that
drops, repeats or invents a step is discarded and the original order kept. A
wrong order is a bug; a missing step is a different plan.
"""

from __future__ import annotations

from agentic_bus.coordinator.negotiation.engine import NegotiationEngine


class _Model:
    def __init__(self, answer):
        self.answer = answer
        self.prompts: list[str] = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        if isinstance(self.answer, Exception):
            raise self.answer
        return type("R", (), {"content": self.answer})()


STEPS = [
    {"agent_id": "email-sender", "capability_id": "email.enviar", "description": "envia"},
    {"agent_id": "crm-reader", "capability_id": "crm.buscar", "description": "lê o CRM"},
    {"agent_id": "sharepoint-reader", "capability_id": "doc.buscar", "description": "busca modelo"},
]

DECOMPOSITION = {
    "rationale": "ler, buscar modelo, enviar",
    "sub_intents": [
        {"id": "ler", "description": "lista de clientes", "dependencies": []},
        {"id": "modelo", "description": "modelo de e-mail", "dependencies": []},
        {"id": "enviar", "description": "enviar e-mails", "dependencies": ["ler", "modelo"]},
    ],
}


def _engine():
    # The engine holds no model of its own; `order_steps` resolves one only
    # when none is passed, and every test here passes one explicitly.
    return NegotiationEngine()


class TestOrdering:
    async def test_a_valid_permutation_is_applied(self):
        model = _Model('{"order": [1, 2, 0]}')

        ordered = await _engine().order_steps(STEPS, DECOMPOSITION, llm=model)

        assert [s["agent_id"] for s in ordered] == [
            "crm-reader",
            "sharepoint-reader",
            "email-sender",
        ]

    async def test_the_decomposition_and_the_steps_reach_the_model(self):
        model = _Model('{"order": [0, 1, 2]}')

        await _engine().order_steps(STEPS, DECOMPOSITION, llm=model)

        prompt = model.prompts[0]
        assert '"dependencies"' in prompt
        assert "enviar" in prompt
        assert "email.enviar" in prompt

    async def test_a_fenced_answer_is_read(self):
        model = _Model('```json\n{"order": [2, 1, 0]}\n```')

        ordered = await _engine().order_steps(STEPS, DECOMPOSITION, llm=model)

        assert ordered[0]["agent_id"] == "sharepoint-reader"


class TestTheStepSetIsAuthoritative:
    """The model may permute. It may not edit."""

    async def test_a_dropped_step_keeps_the_original_order(self):
        model = _Model('{"order": [1, 2]}')

        assert await _engine().order_steps(STEPS, DECOMPOSITION, llm=model) == STEPS

    async def test_a_repeated_index_keeps_the_original_order(self):
        model = _Model('{"order": [1, 1, 2]}')

        assert await _engine().order_steps(STEPS, DECOMPOSITION, llm=model) == STEPS

    async def test_an_invented_index_keeps_the_original_order(self):
        model = _Model('{"order": [1, 2, 7]}')

        assert await _engine().order_steps(STEPS, DECOMPOSITION, llm=model) == STEPS

    async def test_a_non_list_keeps_the_original_order(self):
        model = _Model('{"order": "1,2,0"}')

        assert await _engine().order_steps(STEPS, DECOMPOSITION, llm=model) == STEPS


class TestItNeverRaises:
    async def test_a_model_that_raises_keeps_the_original_order(self):
        model = _Model(RuntimeError("upstream is down"))

        assert await _engine().order_steps(STEPS, DECOMPOSITION, llm=model) == STEPS

    async def test_prose_instead_of_json_keeps_the_original_order(self):
        model = _Model("desculpe, não sei ordenar")

        assert await _engine().order_steps(STEPS, DECOMPOSITION, llm=model) == STEPS


class TestWhenThereIsNothingToOrder:
    async def test_a_single_step_is_returned_untouched_without_a_model_call(self):
        model = _Model('{"order": [0]}')

        assert await _engine().order_steps(STEPS[:1], DECOMPOSITION, llm=model) == STEPS[:1]
        assert model.prompts == []

    async def test_no_decomposition_means_no_call(self):
        model = _Model('{"order": [2, 1, 0]}')

        assert await _engine().order_steps(STEPS, None, llm=model) == STEPS
        assert model.prompts == []

    async def test_an_empty_decomposition_means_no_call(self):
        model = _Model('{"order": [2, 1, 0]}')

        assert await _engine().order_steps(STEPS, {"sub_intents": []}, llm=model) == STEPS
        assert model.prompts == []


class TestNoModelConfigured:
    async def test_keeps_the_offer_order_and_does_not_raise(self, monkeypatch):
        """`get_llm()` raises when nothing is configured. Ordering is advisory,
        so that must degrade to the order we already had — not take plan
        composition down over an optional improvement."""
        import agentic_bus.core.llm as llm_mod

        def boom():
            raise RuntimeError("No LLM provider configured")

        monkeypatch.setattr(llm_mod, "get_llm", boom)

        assert await NegotiationEngine().order_steps(STEPS, DECOMPOSITION) == STEPS
