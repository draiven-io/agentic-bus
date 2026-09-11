"""WebSocket transport layer for Agentic Bus.

All Agentic Bus communication flows over persistent bidirectional WebSocket channels.
The coordinator acts as the session hub; agents and requesters connect as
clients.  Every frame carries a serialised ``AgBusEnvelope``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets
from websockets.asyncio.server import Server, ServerConnection
from websockets.asyncio.client import ClientConnection

from agentic_bus.core.protocol.envelope import AgBusEnvelope
from agentic_bus.core.transport.base import (
    AuthHandler,
    DisconnectHandler,
    MessageHandler,
    resolve_loopback,
)

logger = logging.getLogger(__name__)


def _bearer_token(ws: ServerConnection) -> str | None:
    """Pull the bearer credential off a WebSocket upgrade request.

    The specification did not say how a credential reaches the coordinator
    until an independent implementation had to guess; ``Authorization: Bearer``
    on the upgrade request is now what it says.
    """
    try:
        header = ws.request.headers.get("Authorization", "")  # type: ignore[union-attr]
    except AttributeError:
        return None
    if not header:
        return None
    token = header.removeprefix("Bearer ").strip()
    return token or None


class WSPeer:
    """Thin wrapper around a WebSocket connection with helper send/recv."""

    def __init__(
        self,
        ws: ServerConnection | ClientConnection,
        peer_id: str = "",
        identity: Any = None,
    ):
        self.ws = ws
        self.peer_id = peer_id
        self.identity = identity

    async def send_envelope(self, envelope: AgBusEnvelope) -> None:
        """Serialise and send an Agentic Bus envelope."""
        raw = envelope.model_dump_json()
        await self.ws.send(raw)

    async def recv_envelope(self) -> AgBusEnvelope:
        """Receive and deserialise an Agentic Bus envelope."""
        raw = await self.ws.recv()
        data = json.loads(raw)
        return AgBusEnvelope.from_wire(data)

    async def close(self) -> None:
        await self.ws.close()


class WSServer:
    """WebSocket server that accepts Agentic Bus peers.

    Parameters
    ----------
    host : str
        Bind address.
    port : int
        Bind port.
    on_message : MessageHandler
        Coroutine invoked for every received ``AgBusEnvelope``.
    auth_handler : callable, optional
        Async callable ``(token) -> AuthOutcome``. A falsy ``accepted`` closes
        the connection with 4001 and the outcome's reason. Omit it and every
        connection is admitted with no identity.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        on_message: MessageHandler | None = None,
        on_disconnect: DisconnectHandler | None = None,
        auth_handler: AuthHandler | None = None,
    ):
        self.host = host
        self.port = port
        self._on_message = on_message
        self._on_disconnect = on_disconnect
        self._auth_handler = auth_handler
        self._peers: dict[str, WSPeer] = {}
        self._server: Server | None = None

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        self._server = await websockets.serve(
            self._handle_connection,
            self.host,
            self.port,
        )
        logger.info("Agentic Bus WebSocket server listening on ws://%s:%s", self.host, self.port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Agentic Bus WebSocket server stopped")

    # -- connection handler --------------------------------------------------

    async def _handle_connection(self, ws: ServerConnection) -> None:
        peer_id: str = ""
        identity: Any = None
        try:
            if self._auth_handler:
                # Spec §12: agents are authenticated before participating. The
                # credential rides on the upgrade request, so this is the last
                # point at which refusing costs nothing.
                outcome = await self._auth_handler(_bearer_token(ws))
                if not getattr(outcome, "accepted", False):
                    reason = getattr(outcome, "reason", "") or "authentication failed"
                    logger.warning("Rejected connection: %s", reason)
                    await ws.close(4001, reason)
                    return
                identity = getattr(outcome, "identity", None)

            peer_id = str(id(ws))
            peer = WSPeer(ws, peer_id, identity=identity)
            self._peers[peer_id] = peer
            logger.info("Peer connected: %s", peer_id)

            async for raw in ws:
                try:
                    data = json.loads(raw)
                    envelope = AgBusEnvelope.from_wire(data)
                    if self._on_message:
                        await self._on_message(envelope, peer)
                except Exception:
                    logger.exception("Error processing message from %s", peer_id)
        except websockets.exceptions.ConnectionClosed:
            logger.info("Peer disconnected: %s", peer_id)
        finally:
            self._peers.pop(peer_id, None)
            if peer_id and self._on_disconnect:
                try:
                    await self._on_disconnect(peer_id)
                except Exception:
                    logger.exception("Error in disconnect handler for %s", peer_id)

    # -- helpers -------------------------------------------------------------

    @property
    def agent_endpoint(self) -> str | None:
        """The URI an agent should dial to reach this server."""
        return resolve_loopback(self.host, self.port)

    @property
    def description(self) -> str:
        return f"ws://{self.host}:{self.port}"

    def get_peer(self, peer_id: str) -> WSPeer | None:
        return self._peers.get(peer_id)

    async def broadcast(self, envelope: AgBusEnvelope, exclude: set[str] | None = None) -> None:
        exclude = exclude or set()
        tasks = [
            p.send_envelope(envelope)
            for pid, p in self._peers.items()
            if pid not in exclude
        ]
        await asyncio.gather(*tasks, return_exceptions=True)


class WSClient:
    """WebSocket client that connects to an Agentic Bus coordinator.

    Parameters
    ----------
    uri : str
        WebSocket URI of the coordinator (``ws://host:port``).
    on_message : MessageHandler
        Coroutine invoked for every received ``AgBusEnvelope``.
    """

    def __init__(
        self,
        uri: str,
        on_message: MessageHandler | None = None,
    ):
        self.uri = uri
        self._on_message = on_message
        self._peer: WSPeer | None = None
        self._listen_task: asyncio.Task[None] | None = None
        # Set when the receive loop exits for any reason. Callers supervise
        # the connection by awaiting ``wait_closed()``; without it a dropped
        # socket is invisible to the owner of this client.
        self._closed = asyncio.Event()

    async def connect(self, extra_headers: dict[str, str] | None = None) -> WSPeer:
        ws = await websockets.connect(self.uri, additional_headers=extra_headers)
        self._peer = WSPeer(ws, peer_id="client")
        self._closed.clear()
        self._listen_task = asyncio.create_task(self._listen())
        return self._peer

    async def _listen(self) -> None:
        assert self._peer is not None
        try:
            async for raw in self._peer.ws:
                try:
                    data = json.loads(raw)
                    envelope = AgBusEnvelope.from_wire(data)
                    if self._on_message:
                        await self._on_message(envelope, self._peer)
                except Exception:
                    logger.exception("Error processing message from coordinator")
        except websockets.exceptions.ConnectionClosed:
            logger.info("Disconnected from coordinator")
        finally:
            # Reached on clean close, connection loss, and cancellation alike,
            # so a supervisor is always released rather than waiting forever.
            self._closed.set()

    async def wait_closed(self) -> None:
        """Block until the connection drops.

        This is what lets a caller notice a disconnect and reconnect. Returns
        immediately if the connection is already closed.
        """
        await self._closed.wait()

    @property
    def is_connected(self) -> bool:
        return self._peer is not None and not self._closed.is_set()

    async def disconnect(self) -> None:
        if self._listen_task:
            self._listen_task.cancel()
        if self._peer:
            await self._peer.close()
        self._closed.set()

    @property
    def peer(self) -> WSPeer | None:
        return self._peer
