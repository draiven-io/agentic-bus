"""Admission control: who gets onto the bus, and as whom.

LIP §12 requires agents to be authenticated before participating. Until this
suite existed the reference implementation did not do it — a verifier was
constructed and never called, the identity map was read but never written, and
registration admitted every agent that asked.

So the tests that matter here are the negative ones. A suite that only proves
a valid agent gets in would have passed against the broken version too.
"""

from __future__ import annotations

import asyncio


from agentic_bus import AgentCapability, BaseAgent
from agentic_bus.core.auth.agent_auth import AgentAuthPolicy
from agentic_bus.core.auth.oidc import DevVerifier, OIDCIdentity
from agentic_bus.core.persistence.repository import AgentRepository
from agentic_bus.core.transport.local import LocalTransport


class Weatherman(BaseAgent):
    def capabilities(self) -> list[AgentCapability]:
        return [AgentCapability(capability_id="forecast", description="Weather")]

    async def execute_task(self, payload: dict, context: dict) -> dict:
        return {"forecast": "sunny"}


def _identity(subject: str) -> OIDCIdentity:
    return OIDCIdentity(subject=subject, issuer="dev", audience="agbus")


class TestThePolicyPicksTheRightVerifier:
    def test_an_issuer_means_production(self, monkeypatch):
        monkeypatch.setenv("AGBUS_OIDC_ISSUER", "https://idp.example.com")
        policy = AgentAuthPolicy()

        assert not policy.is_development
        assert policy.require_auth, "an IdP was configured; credentials are not optional"

    def test_no_issuer_means_development(self, monkeypatch):
        monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)
        monkeypatch.delenv("AGBUS_REQUIRE_AGENT_AUTH", raising=False)
        policy = AgentAuthPolicy()

        assert policy.is_development
        assert isinstance(policy.verifier, DevVerifier)
        assert not policy.require_auth

    def test_auth_can_be_required_without_an_idp(self, monkeypatch):
        monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)
        monkeypatch.setenv("AGBUS_REQUIRE_AGENT_AUTH", "true")

        assert AgentAuthPolicy().require_auth

    def test_the_flag_cannot_loosen_a_configured_issuer(self, monkeypatch):
        """A deployment that configured an IdP did not mean 'sometimes'."""
        monkeypatch.setenv("AGBUS_OIDC_ISSUER", "https://idp.example.com")
        monkeypatch.setenv("AGBUS_REQUIRE_AGENT_AUTH", "false")

        assert AgentAuthPolicy().require_auth


class TestAuthenticatingAConnection:
    async def test_a_credential_is_verified_and_carried(self, monkeypatch):
        monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)
        policy = AgentAuthPolicy()

        outcome = await policy.authenticate('{"sub": "agent-42"}')

        assert outcome.accepted
        assert outcome.is_verified
        assert outcome.identity.subject == "agent-42"

    async def test_no_credential_is_admitted_unverified_in_development(self, monkeypatch):
        monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)
        monkeypatch.delenv("AGBUS_REQUIRE_AGENT_AUTH", raising=False)

        outcome = await AgentAuthPolicy().authenticate(None)

        assert outcome.accepted
        # Admitted, but nothing downstream may mistake it for someone.
        assert outcome.identity is None
        assert not outcome.is_verified

    async def test_no_credential_is_refused_when_required(self, monkeypatch):
        monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)
        monkeypatch.setenv("AGBUS_REQUIRE_AGENT_AUTH", "true")

        outcome = await AgentAuthPolicy().authenticate(None)

        assert not outcome.accepted
        assert "no credential" in outcome.reason

    async def test_a_credential_that_fails_verification_is_refused(self):
        class Rejecting:
            async def verify(self, token):
                raise ValueError("bad signature")

        outcome = await AgentAuthPolicy(verifier=Rejecting()).authenticate("anything")

        assert not outcome.accepted
        assert "verification failed" in outcome.reason

    async def test_the_refusal_reason_never_carries_the_token(self):
        """The reason travels to the peer and into the log. The secret does not."""

        class Rejecting:
            async def verify(self, token):
                raise ValueError(f"invalid token: {token}")

        secret = "super-secret-token-value"
        outcome = await AgentAuthPolicy(verifier=Rejecting()).authenticate(secret)

        assert secret not in outcome.reason

    async def test_a_subjectless_credential_is_refused(self):
        class Anonymous:
            async def verify(self, token):
                return OIDCIdentity(subject="")

        outcome = await AgentAuthPolicy(verifier=Anonymous()).authenticate("t")

        assert not outcome.accepted


class TestEntitlement:
    """Authentication says who you are. This says which agent you may be."""

    def test_an_unbound_agent_accepts_any_authenticated_subject(self, monkeypatch):
        monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)
        allowed, _ = AgentAuthPolicy().entitled_to_register(
            _identity("someone"), "weatherman", bound_subject=""
        )
        assert allowed

    def test_the_bound_subject_may_register(self, monkeypatch):
        monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)
        allowed, _ = AgentAuthPolicy().entitled_to_register(
            _identity("owner"), "weatherman", bound_subject="owner"
        )
        assert allowed

    def test_a_different_subject_may_not(self, monkeypatch):
        """A valid credential for the wrong agent is the case that matters."""
        monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)
        allowed, reason = AgentAuthPolicy().entitled_to_register(
            _identity("impostor"), "weatherman", bound_subject="owner"
        )

        assert not allowed
        assert "bound to a different identity" in reason

    def test_a_bound_agent_cannot_be_claimed_anonymously(self, monkeypatch):
        monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)
        monkeypatch.delenv("AGBUS_REQUIRE_AGENT_AUTH", raising=False)
        allowed, reason = AgentAuthPolicy().entitled_to_register(
            None, "weatherman", bound_subject="owner"
        )

        assert not allowed
        assert "credential" in reason

    def test_registration_needs_a_credential_when_auth_is_required(self, monkeypatch):
        monkeypatch.setenv("AGBUS_REQUIRE_AGENT_AUTH", "true")
        allowed, reason = AgentAuthPolicy().entitled_to_register(
            None, "weatherman", bound_subject=""
        )

        assert not allowed
        assert "authentication is required" in reason


class TestTheCoordinatorRefusesWhatItShould:
    """End to end, over the in-process transport so no port is bound."""

    async def _runtime(self):
        from agentic_bus.coordinator.runtime import CoordinatorRuntime

        transport = LocalTransport()
        runtime = CoordinatorRuntime(transport=transport)
        await runtime.start()
        return runtime, transport

    async def test_a_revoked_agent_cannot_return_as_ephemeral(self, monkeypatch):
        """Revocation must not be escapable by reconnecting in another mode."""
        monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)
        runtime, transport = await self._runtime()

        repo = AgentRepository()
        repo.enrol("weatherman", public_key_pem=_a_public_key())
        repo.approve("weatherman")
        repo.revoke("weatherman")

        agent = Weatherman(agent_id="weatherman", registration_timeout=2.0)
        refusals: list = []

        async def _record(ack):
            refusals.append(ack)

        agent.on_registration_refused = _record

        try:
            await agent.attach(transport)
            assert await _eventually(lambda: len(refusals) == 1), "the revoked agent was admitted"
            assert "revoked" in refusals[0].reason
            assert runtime.registry.get("weatherman") is None
        finally:
            await agent.stop()
            await runtime.stop()

    async def test_an_impostor_is_refused_once_the_id_is_bound(self, monkeypatch):
        monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)
        runtime, transport = await self._runtime()

        repo = AgentRepository()
        repo.enrol("weatherman", public_key_pem=_a_public_key())
        repo.approve("weatherman")
        repo.bind_subject("weatherman", "the-owner")

        agent = Weatherman(agent_id="weatherman", registration_timeout=2.0)
        refusals: list = []

        async def _record(ack):
            refusals.append(ack)

        agent.on_registration_refused = _record

        try:
            await agent.attach(transport, identity=_identity("someone-else"))
            assert await _eventually(lambda: len(refusals) == 1), "the impostor was admitted"
            assert "different identity" in refusals[0].reason
            assert runtime.registry.get("weatherman") is None
        finally:
            await agent.stop()
            await runtime.stop()

    async def test_the_owner_is_admitted(self, monkeypatch):
        monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)
        runtime, transport = await self._runtime()

        repo = AgentRepository()
        repo.enrol("weatherman", public_key_pem=_a_public_key())
        repo.approve("weatherman")
        repo.bind_subject("weatherman", "the-owner")

        agent = Weatherman(agent_id="weatherman", registration_timeout=2.0)
        try:
            await agent.attach(transport, identity=_identity("the-owner"))
            assert await _eventually(lambda: runtime.registry.get("weatherman") is not None)
        finally:
            await agent.stop()
            await runtime.stop()

    async def test_an_unknown_agent_still_joins_in_development(self, monkeypatch):
        """Ephemeral agents leave no record by design; that must keep working."""
        monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)
        monkeypatch.delenv("AGBUS_REQUIRE_AGENT_AUTH", raising=False)
        runtime, transport = await self._runtime()

        agent = Weatherman(agent_id="nobody-knows-me", registration_timeout=2.0)
        try:
            await agent.attach(transport)
            assert await _eventually(
                lambda: runtime.registry.get("nobody-knows-me") is not None
            )
        finally:
            await agent.stop()
            await runtime.stop()

    async def test_identity_reaches_ibac_as_a_derived_fact(self, monkeypatch):
        """The plumbing existed and was never fed; this is what fixes it."""
        monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)
        runtime, transport = await self._runtime()

        agent = Weatherman(agent_id="weatherman", registration_timeout=2.0)
        try:
            await agent.attach(transport, identity=_identity("the-owner"))
            await _eventually(lambda: runtime.registry.get("weatherman") is not None)

            peer = transport.get_peer(f"{agent.agent_id}-local")
            from agentic_bus.core.ibac.engine import IBACEvaluationPoint

            manifest = runtime._build_manifest(
                evaluation_point=IBACEvaluationPoint.OFFER_ELIGIBILITY, peer=peer
            )

            assert manifest.derived.authenticated_subject == "the-owner"
            assert manifest.derived.identity_verified is True
        finally:
            await agent.stop()
            await runtime.stop()

    async def test_an_unauthenticated_peer_is_reported_as_unverified(self, monkeypatch):
        monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)
        monkeypatch.delenv("AGBUS_REQUIRE_AGENT_AUTH", raising=False)
        runtime, transport = await self._runtime()

        agent = Weatherman(agent_id="anon", registration_timeout=2.0)
        try:
            await agent.attach(transport)
            await _eventually(lambda: runtime.registry.get("anon") is not None)

            peer = transport.get_peer(f"{agent.agent_id}-local")
            from agentic_bus.core.ibac.engine import IBACEvaluationPoint

            manifest = runtime._build_manifest(
                evaluation_point=IBACEvaluationPoint.OFFER_ELIGIBILITY, peer=peer
            )

            assert manifest.derived.authenticated_subject == ""
            assert manifest.derived.identity_verified is False
        finally:
            await agent.stop()
            await runtime.stop()


class TestOverARealSocket:
    """The header extraction only exists on the WebSocket path.

    Everything above runs in-process, where identity is asserted rather than
    parsed. If `Authorization: Bearer` were read wrongly the suite would still
    be green and every real deployment would be open, so this binds a port on
    purpose.
    """

    async def _server(self, policy):
        from agentic_bus.core.transport.ws import WSServer

        server = WSServer(host="127.0.0.1", port=0, auth_handler=policy.authenticate)
        await server.start()
        # port 0 asks the OS to choose; find out what it chose.
        server.port = server._server.sockets[0].getsockname()[1]
        return server

    async def test_a_connection_without_a_credential_is_closed(self, monkeypatch):
        monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)
        monkeypatch.setenv("AGBUS_REQUIRE_AGENT_AUTH", "true")
        from agentic_bus.core.transport.ws import WSClient

        server = await self._server(AgentAuthPolicy())
        client = WSClient(f"ws://127.0.0.1:{server.port}")
        try:
            await client.connect()
            await asyncio.sleep(0.3)
            assert not client.is_connected, "an unauthenticated peer stayed connected"
        except Exception:
            pass  # refused during the handshake is equally correct
        finally:
            await client.disconnect()
            await server.stop()

    async def test_a_bearer_token_is_read_off_the_upgrade_request(self, monkeypatch):
        monkeypatch.delenv("AGBUS_OIDC_ISSUER", raising=False)
        monkeypatch.setenv("AGBUS_REQUIRE_AGENT_AUTH", "true")
        from agentic_bus.core.transport.ws import WSClient

        server = await self._server(AgentAuthPolicy())
        client = WSClient(f"ws://127.0.0.1:{server.port}")
        try:
            await client.connect(
                extra_headers={"Authorization": 'Bearer {"sub": "agent-7"}'}
            )
            await asyncio.sleep(0.3)

            assert client.is_connected
            peers = list(server._peers.values())
            assert peers and peers[0].identity is not None
            assert peers[0].identity.subject == "agent-7"
        finally:
            await client.disconnect()
            await server.stop()


def _a_public_key() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate().public_key()
    return key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


async def _eventually(predicate, timeout: float = 3.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False
