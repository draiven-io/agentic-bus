"""WebSocket transport layer for Agentic Bus.

All Agentic Bus communication flows over persistent bidirectional WebSocket channels.
The coordinator acts as the session hub; agents and requesters connect as
clients.  Every frame carries a serialised ``AgBusEnvelope``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

import websockets
from websockets.asyncio.server import Server, ServerConnection
from websockets.asyncio.client import ClientConnection

from app.core.protocol.envelope import AgBusEnvelope

logger = logging.getLogger(__name__)

# Type alias for a handler coroutine
MessageHandler = Callable[[AgBusEnvelope, "WSPeer"], Coroutine[Any, Any, None]]


class WSPeer:
    """Thin wrapper around a WebSocket connection with helper send/recv."""

    def __init__(self, ws: ServerConnection | ClientConnection, peer_id: str = ""):
        self.ws = ws
        self.peer_id = peer_id

    async def send_envelope(self, envelope: AgBusEnvelope) -> None:
        """Serialise and send an Agentic Bus envelope."""
        raw = envelope.model_dump_json()
        await self.ws.send(raw)

    async def recv_envelope(self) -> AgBusEnvelope:
        """Receive and deserialise an Agentic Bus envelope."""
        raw = await self.ws.recv()
        data = json.loads(raw)
        return AgBusEnvelope.model_validate(data)

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
        Async callable ``(ws, path) -> peer_id | None``.  Return *None* to
        reject the connection.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        on_message: MessageHandler | None = None,
        auth_handler: Callable[..., Coroutine[Any, Any, str | None]] | None = None,
    ):
        self.host = host
        self.port = port
        self._on_message = on_message
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
        try:
            # Optional auth gate
            if self._auth_handler:
                peer_id_or_none = await self._auth_handler(ws)
                if peer_id_or_none is None:
                    await ws.close(4001, "Authentication failed")
                    return
                peer_id = peer_id_or_none
            else:
                peer_id = str(id(ws))

            peer = WSPeer(ws, peer_id)
            self._peers[peer_id] = peer
            logger.info("Peer connected: %s", peer_id)

            async for raw in ws:
                try:
                    data = json.loads(raw)
                    envelope = AgBusEnvelope.model_validate(data)
                    if self._on_message:
                        await self._on_message(envelope, peer)
                except Exception:
                    logger.exception("Error processing message from %s", peer_id)
        except websockets.exceptions.ConnectionClosed:
            logger.info("Peer disconnected: %s", peer_id)
        finally:
            self._peers.pop(peer_id, None)

    # -- helpers -------------------------------------------------------------

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

    async def connect(self, extra_headers: dict[str, str] | None = None) -> WSPeer:
        ws = await websockets.connect(self.uri, additional_headers=extra_headers)
        self._peer = WSPeer(ws, peer_id="client")
        self._listen_task = asyncio.create_task(self._listen())
        return self._peer

    async def _listen(self) -> None:
        assert self._peer is not None
        try:
            async for raw in self._peer.ws:
                try:
                    data = json.loads(raw)
                    envelope = AgBusEnvelope.model_validate(data)
                    if self._on_message:
                        await self._on_message(envelope, self._peer)
                except Exception:
                    logger.exception("Error processing message from coordinator")
        except websockets.exceptions.ConnectionClosed:
            logger.info("Disconnected from coordinator")

    async def disconnect(self) -> None:
        if self._listen_task:
            self._listen_task.cancel()
        if self._peer:
            await self._peer.close()

    @property
    def peer(self) -> WSPeer | None:
        return self._peer
