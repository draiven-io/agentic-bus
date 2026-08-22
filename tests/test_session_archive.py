"""What gets written into the session archive.

The archive is what the history API and the dashboard read, so anything wrong
here is wrong everywhere a human looks afterwards — and it is only visible
after a session has already finished, which is the worst time to find out.
"""

from __future__ import annotations

import pytest

from agentic_bus.core.protocol.envelope import IntentPayload


class TestIntentTextExtraction:
    """The archived intent must be the intent, not a repr of the model."""

    def test_the_payload_field_is_named_intent_text(self):
        """The extraction below depends on this name; a rename must fail here.

        `IntentPayload` has no `.text`, so code reaching for one silently
        falls through to whatever fallback it was given.
        """
        payload = IntentPayload(intent_text="reroute the shipment")

        assert payload.intent_text == "reroute the shipment"
        assert not hasattr(payload, "text")

    def test_extraction_yields_prose_not_a_repr(self):
        payload = IntentPayload(
            intent_text="A storm has closed the Port of Rotterdam.",
            context={"tenant": "acme"},
        )

        extracted = getattr(payload, "intent_text", "") or getattr(payload, "text", "")

        assert extracted == "A storm has closed the Port of Rotterdam."
        # The specific failure this guards against: str(payload) renders
        # `intent_text='...' context={...}`, which then shows up in the
        # dashboard as though the user had typed it.
        assert "intent_text=" not in extracted
        assert "context=" not in extracted

    def test_a_repr_fallback_would_have_been_wrong(self):
        """Pin the bad behaviour, so nobody reintroduces it as a 'safe' default."""
        payload = IntentPayload(intent_text="reroute the shipment")

        assert "intent_text=" in str(payload), (
            "if this no longer holds, the regression it guards is gone too"
        )

    @pytest.mark.parametrize("text", ["", "   "])
    def test_empty_intent_text_stays_empty(self, text):
        """An empty intent archives as empty, never as the model's repr."""
        payload = IntentPayload(intent_text=text)

        extracted = getattr(payload, "intent_text", "") or getattr(payload, "text", "")

        assert extracted == text
