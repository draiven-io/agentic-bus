"""In-process transport: a coordinator with no socket.

Agents attach by calling :meth:`LocalTransport.connect` instead of dialling a
URI. There is no server, no port and no serialisation, which makes this the
transport for two situations:

**Embedding.** A host application that already owns a process, a database and
an identity model can run a coordinator inside it as a library, rather than
operating a second service and reconciling the two.

**Testing.** A test that binds a port is a test that fails on a busy CI runner.

Envelopes are deep-copied across the boundary. That costs something, and it is
not negotiable: a socket gives each side its own object for free, and a local
transport that skipped the copy would let a mutation on one side rewrite what
the other already received. The whole value of this module is that code
behaving correctly here behaves correctly over a network — so the semantics
have to match even where the mechanism does not.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agentic_bus.core.protocol.envelope import AgBusEnvelope
from agentic_bus.core.transport.base import DisconnectHandler, MessageHandler

logger = logging.getLogger(__name__)


class LocalPeer:
    """The coordinator's channel to one in-process agent."""

    def __init__(
        self,
        peer_id: str,
        deliver: MessageHandler | None,
        on_close: "LocalTransport | None" = None,
        identity: Any = None,
    ) -> None:
        self.peer_id = peer_id
        self.identity = identity
        self._deliver = deliver
        self._transport = on_close
        self._closed = False

    async def send_envelope(self, envelope: AgBusEnvelope) -> None:
        if self._closed:
            logger.debug("dropping %s: peer %s is closed", envelope.message_type, self.peer_id)
            return
        if self._deliver is None:
            return
        await self._deliver(envelope.model_copy(deep=True), self)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._transport is not None:
            await self._transport._drop(self.peer_id)

    @property
    def is_closed(self) -> bool:
        return self._closed


class LocalConnection:
    """An agent's channel to the coordinator.

    The mirror of :class:`LocalPeer`: what :meth:`LocalTransport.connect`
    hands back, so the agent side can send without knowing anything about the
    coordinator beyond this object.
    """

    def __init__(self, peer_id: str, transport: "LocalTransport") -> None:
        self.peer_id = peer_id
        self._transport = transport
        self._closed = False

    async def send_envelope(self, envelope: AgBusEnvelope) -> None:
        """Send to the coordinator, as a WebSocket client would."""
        if self._closed:
            raise ConnectionError(f"connection for peer {self.peer_id!r} is closed")
        await self._transport._receive(self.peer_id, envelope.model_copy(deep=True))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._transport._drop(self.peer_id)

    @property
    def is_closed(self) -> bool:
        return self._closed


class LocalTransport:
    """A :class:`~agentic_bus.core.transport.base.Transport` with no network.

    ::

        transport = LocalTransport()
        runtime = CoordinatorRuntime(transport=transport)
        await runtime.start()

        conn = await transport.connect("my-agent", on_receive=agent.handle)
        await conn.send_envelope(register_envelope)
    """

    def __init__(
        self,
        on_message: MessageHandler | None = None,
        on_disconnect: DisconnectHandler | None = None,
    ) -> None:
        self._on_message = on_message
        self._on_disconnect = on_disconnect
        self._peers: dict[str, LocalPeer] = {}
        self._counter = 0
        self._running = False

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        logger.info("Agentic Bus in-process transport ready")

    async def stop(self) -> None:
        self._running = False
        for peer in list(self._peers.values()):
            await peer.close()
        self._peers.clear()
        logger.info("Agentic Bus in-process transport stopped")

    # -- the Transport contract ---------------------------------------------

    def get_peer(self, peer_id: str) -> LocalPeer | None:
        return self._peers.get(peer_id)

    async def broadcast(
        self, envelope: AgBusEnvelope, exclude: set[str] | None = None
    ) -> None:
        exclude = exclude or set()
        await asyncio.gather(
            *(
                peer.send_envelope(envelope)
                for pid, peer in self._peers.items()
                if pid not in exclude
            ),
            return_exceptions=True,
        )

    @property
    def agent_endpoint(self) -> str | None:
        """Always ``None`` — there is nothing to dial.

        Callers that spawn agents expecting a URI must handle this. An
        in-process coordinator cannot start a subprocess agent and tell it
        where to connect, because there is nowhere to connect to.
        """
        return None

    @property
    def description(self) -> str:
        return "in-process"

    # -- the agent side -----------------------------------------------------

    async def connect(
        self,
        peer_id: str | None = None,
        *,
        on_receive: MessageHandler | None = None,
        identity: Any = None,
    ) -> LocalConnection:
        """Attach an in-process agent, as dialling the server would.

        Parameters
        ----------
        peer_id:
            Identifier for this channel. Generated when omitted. It identifies
            the *connection*, not the agent — an agent that reconnects gets a
            new one and must register again.
        on_receive:
            Coroutine invoked with every envelope the coordinator sends here.
        identity:
            Who this agent is. There is no handshake to establish it in-process
            and no network to defend, so the embedding application asserts it —
            it already knows, having constructed the agent. Leave it ``None``
            and the peer is unauthenticated, which the coordinator will refuse
            to register when a credential is required.
        """
        if peer_id is None:
            self._counter += 1
            peer_id = f"local-{self._counter}"

        if peer_id in self._peers:
            raise ValueError(f"peer {peer_id!r} is already connected")

        peer = LocalPeer(peer_id, on_receive, on_close=self, identity=identity)
        self._peers[peer_id] = peer
        logger.info("Peer connected in-process: %s", peer_id)
        return LocalConnection(peer_id, self)

    # -- internals ----------------------------------------------------------

    async def _receive(self, peer_id: str, envelope: AgBusEnvelope) -> None:
        """Route an agent-sent envelope into the coordinator."""
        peer = self._peers.get(peer_id)
        if peer is None:
            logger.warning("envelope from unknown peer %s discarded", peer_id)
            return
        if self._on_message is None:
            return
        try:
            await self._on_message(envelope, peer)
        except Exception:
            # Matches the WebSocket server: one bad message must not tear down
            # the channel that delivered it.
            logger.exception("Error processing message from %s", peer_id)

    async def _drop(self, peer_id: str) -> None:
        if self._peers.pop(peer_id, None) is None:
            return
        logger.info("Peer disconnected in-process: %s", peer_id)
        if self._on_disconnect is not None:
            try:
                await self._on_disconnect(peer_id)
            except Exception:
                logger.exception("Error in disconnect handler for %s", peer_id)

    @property
    def peer_ids(self) -> list[str]:
        """Currently attached peers. Useful in tests and diagnostics."""
        return list(self._peers)
