"""Who is allowed onto the bus, and as whom.

LIP §12 requires agents to be authenticated before participating. That is two
questions, not one, and conflating them is how systems end up checking neither:

*Authentication* — is this connection carrying a credential this coordinator
accepts? Answered here, at the handshake.

*Entitlement* — is the holder of that credential allowed to act as the
``agent_id`` it claims? Answered at registration, where the claim is made.

A credential proves who you are. It does not, by itself, say which agent you
may be — an agent that authenticates successfully and then registers under a
colleague's identifier has authenticated perfectly and impersonated anyway.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from agentic_bus.core.auth.oidc import DevVerifier, OIDCIdentity, OIDCVerifier

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")


@dataclass(frozen=True)
class AuthOutcome:
    """The result of examining a connection's credential."""

    accepted: bool
    identity: OIDCIdentity | None = None
    reason: str = ""

    @property
    def is_verified(self) -> bool:
        """A credential was presented *and* accepted."""
        return self.accepted and self.identity is not None


class AgentAuthPolicy:
    """Decides whether a connecting peer is admitted, and as which subject.

    Two postures, chosen by configuration rather than by a flag nobody sets:

    **Production** — ``AGBUS_OIDC_ISSUER`` is set. Tokens are verified against
    the issuer's JWKS. A missing or invalid token closes the connection.

    **Development** — no issuer configured. Tokens are parsed leniently by
    :class:`~agentic_bus.core.auth.oidc.DevVerifier`, and a connection without
    one is still admitted, but carries *no* identity. It is then visible as
    unverified everywhere it matters: ``identity_verified`` is false in the
    IBAC manifest, and any rule that requires a subject will not match.

    Set ``AGBUS_REQUIRE_AGENT_AUTH=true`` to demand a credential without
    running an identity provider — useful for a shared development bus, where
    the alternative is that anything reaching the port joins it.
    """

    def __init__(
        self,
        verifier: OIDCVerifier | DevVerifier | None = None,
        *,
        require_auth: bool | None = None,
        issuer: str | None = None,
    ) -> None:
        self.issuer = issuer if issuer is not None else os.getenv("AGBUS_OIDC_ISSUER", "")
        self.verifier = verifier or (OIDCVerifier() if self.issuer else DevVerifier())
        # An issuer implies production, and production implies credentials are
        # not optional. The explicit flag can only tighten this, never loosen
        # it: a deployment that configured an IdP did not mean "sometimes".
        self.require_auth = bool(self.issuer) or (
            _env_flag("AGBUS_REQUIRE_AGENT_AUTH", False)
            if require_auth is None
            else require_auth
        )

    @property
    def is_development(self) -> bool:
        return not self.issuer

    async def authenticate(self, token: str | None) -> AuthOutcome:
        """Examine a bearer token and decide whether the peer may connect."""
        if not token:
            if self.require_auth:
                return AuthOutcome(
                    accepted=False, reason="no credential presented"
                )
            # Admitted, but explicitly nobody. Everything downstream can tell
            # the difference between this and a verified subject.
            return AuthOutcome(accepted=True, identity=None)

        try:
            identity = await self.verifier.verify(token)
        except Exception as exc:
            # The reason is returned to the peer and logged. The token is not,
            # in either place.
            logger.warning("Rejected a peer: token verification failed (%s)", type(exc).__name__)
            return AuthOutcome(accepted=False, reason="credential verification failed")

        if not identity.subject:
            return AuthOutcome(
                accepted=False, reason="credential carries no subject"
            )

        return AuthOutcome(accepted=True, identity=identity)

    def entitled_to_register(
        self,
        identity: OIDCIdentity | None,
        claimed_agent_id: str,
        bound_subject: str = "",
    ) -> tuple[bool, str]:
        """May this identity register as ``claimed_agent_id``?

        Parameters
        ----------
        identity:
            What the connection authenticated as, if anything.
        claimed_agent_id:
            The ``agent_id`` in the registration payload — a claim, not a fact.
        bound_subject:
            The subject previously recorded for this agent, if any. Empty means
            the agent has never been bound to one.

        Returns ``(allowed, reason)``. The reason is surfaced to the agent in
        the ``registered`` answer, so it must say what to do about it.
        """
        if self.require_auth and identity is None:
            return False, "authentication is required to register"

        if bound_subject:
            if identity is None:
                return False, (
                    f"agent {claimed_agent_id!r} is bound to an identity; "
                    "connect with a credential for it"
                )
            if identity.subject != bound_subject:
                # The interesting case: a valid credential for the wrong agent.
                logger.warning(
                    "Subject %r attempted to register as %r, which is bound to another subject",
                    identity.subject,
                    claimed_agent_id,
                )
                return False, (
                    f"agent {claimed_agent_id!r} is bound to a different identity"
                )

        return True, ""
