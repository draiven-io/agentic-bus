"""What the coordinator needs from a transport, and nothing more.

The coordination logic — sessions, discovery, negotiation, IBAC, execution — is
already transport-free. It only ever asks two things of the wire: *give me the
channel for this peer*, and *send this envelope down it*. Naming that contract
here lets the same coordinator run over a WebSocket server, in-process, or over
something not written yet.

LIP is transport-independent by design; this is where that stops being a claim
about the specification and becomes true of the implementation.

Two implementations ship with this package:

``ws.WSServer``
    Agents connect over WebSocket from anywhere. The default, and what you
    want when agents are separate processes, containers or machines.

``local.LocalTransport``
    Agents attach in-process by calling :meth:`local.LocalTransport.connect`.
    No socket, no port, no serialisation — for embedding a coordinator inside
    a host application, and for tests that should not bind ports.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol, runtime_checkable

from agentic_bus.core.protocol.envelope import AgBusEnvelope

#: Invoked for every envelope arriving from a peer. The peer is the channel
#: back to whoever sent it, so a handler can answer without a lookup.
MessageHandler = Callable[[AgBusEnvelope, "Peer"], Awaitable[None]]

#: Invoked with a peer id when that peer goes away, however it went away.
DisconnectHandler = Callable[[str], Awaitable[None]]


@runtime_checkable
class Peer(Protocol):
    """One counterparty, from the coordinator's side.

    A peer is a channel, not an identity: a single agent that reconnects is a
    new peer with a new ``peer_id``, which is why registration is per
    connection (RFC 0001).
    """

    peer_id: str

    async def send_envelope(self, envelope: AgBusEnvelope) -> None:
        """Deliver an envelope to this peer.

        Implementations MUST NOT hand the receiver an object the sender still
        holds a reference to. Over a socket that is free; in-process it has to
        be arranged, or a mutation on one side silently rewrites history on the
        other.
        """
        ...

    async def close(self) -> None:
        """Close the channel. Idempotent."""
        ...


@runtime_checkable
class Transport(Protocol):
    """Where peers arrive and how they are reached."""

    async def start(self) -> None:
        """Begin accepting peers."""
        ...

    async def stop(self) -> None:
        """Stop accepting peers and release resources."""
        ...

    def get_peer(self, peer_id: str) -> Peer | None:
        """The channel for a peer, or ``None`` if it is gone."""
        ...

    async def broadcast(
        self, envelope: AgBusEnvelope, exclude: set[str] | None = None
    ) -> None:
        """Send to every connected peer except those excluded."""
        ...

    @property
    def agent_endpoint(self) -> str | None:
        """The URI an agent should dial to reach this coordinator.

        ``None`` when there is nothing to dial — an in-process transport, where
        agents attach directly. Callers that spawn agents MUST handle ``None``
        rather than assume an address exists; that assumption is exactly what
        binds a coordinator to one transport.
        """
        ...

    @property
    def description(self) -> str:
        """Short human-readable form for logs and the audit trail."""
        ...


def resolve_loopback(host: str, port: int, scheme: str = "ws") -> str:
    """Build a URI an agent on this machine can dial.

    ``0.0.0.0`` means *bind everywhere*, which is not an address anything can
    connect to. A process dialling it is relying on OS-specific leniency, so
    the loopback address is substituted explicitly.
    """
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"
    return f"{scheme}://{host}:{port}"
