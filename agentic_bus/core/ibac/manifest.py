"""The Intent Manifest: a proposed intention, split by who asserted it.

An intention arriving at IBAC mixes two very different kinds of statement:

*Declared* — what the agent **says** it wants. Its intent text, its stated
purpose, the scopes it asks for. These are claims made by the component being
governed. A prompt-injected or compromised agent writes whatever passes.

*Derived* — what the coordinator **establishes** for itself. The
authenticated OIDC subject, which connection the message actually arrived on,
where the lifecycle currently is. An agent cannot forge these by writing a
different value into an envelope.

Purpose-based authorization is only ever as strong as purpose *attestation*,
so keeping the two apart is not tidiness — it decides which rules can carry a
guarantee:

    A rule provides a guarantee only when it is evaluated deterministically
    **and** reads only derived facts.

Both halves matter. A regex over ``intent_text`` is perfectly deterministic
and still worthless as a boundary, because the text is written by the party
the rule is meant to constrain. Such rules are useful heuristics; they are not
boundaries, and :class:`IBACResult` records the difference so an operator can
tell which they have.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DeclaredIntent(BaseModel):
    """What the agent or requester asserts. Never trusted as fact.

    Available to the semantic evaluator, which exists precisely to interpret
    claims. Grounded rules that need to carry a guarantee must not read it.
    """

    intent_text: str = ""
    purpose: str = Field(
        default="",
        description="The purpose the actor states for this intention.",
    )
    context: dict[str, Any] = Field(default_factory=dict)
    requested_scopes: list[str] = Field(default_factory=list)
    proposed_capabilities: list[str] = Field(default_factory=list)
    data_domains: list[str] = Field(default_factory=list)
    #: The actor the envelope claims to be from. Compare against
    #: ``DerivedFacts.authenticated_agent_id`` rather than trusting it.
    claimed_agent_id: str = ""


class DerivedFacts(BaseModel):
    """What the coordinator establishes independently of what it was told.

    The only inputs a rule may rely on to make a guarantee. Everything here is
    resolved from the authenticated connection, the coordinator's own state,
    or a system of record — never from the message body.
    """

    evaluation_point: str = ""
    session_id: str = ""

    #: Subject from the verified OIDC token on the connection.
    authenticated_subject: str = ""
    #: Agent identity resolved from the connection the message arrived on,
    #: not from the envelope's sender field.
    authenticated_agent_id: str = ""
    identity_verified: bool = False

    #: Resolved by the runtime from systems of record as those become
    #: available — a document's classification, whether a destination is
    #: outside the tenant, a payment amount. Grounded boundary rules read
    #: from here.
    resource_classification: str = ""
    destination_external: bool | None = None
    tenant_id: str = ""
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional environment-resolved facts, by key.",
    )

    @property
    def identity_is_consistent(self) -> bool:
        """Whether an authenticated identity was established at all."""
        return self.identity_verified and bool(self.authenticated_agent_id)


class IntentManifest(BaseModel):
    """A proposed intention, with its two kinds of statement kept apart."""

    declared: DeclaredIntent = Field(default_factory=DeclaredIntent)
    derived: DerivedFacts = Field(default_factory=DerivedFacts)

    @property
    def sender_is_impersonating(self) -> bool:
        """True when the envelope claims an identity the connection contradicts.

        Only meaningful once an authenticated agent identity exists; an
        unauthenticated connection is a separate problem, reported by
        ``identity_verified``.
        """
        claimed = self.declared.claimed_agent_id
        actual = self.derived.authenticated_agent_id
        return bool(claimed and actual and claimed != actual)

    def audit_summary(self) -> dict[str, Any]:
        """A compact record of what was decided on, for the audit trail."""
        return {
            "declared": self.declared.model_dump(),
            "derived": self.derived.model_dump(),
            "sender_is_impersonating": self.sender_is_impersonating,
        }
