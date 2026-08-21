"""TCP server accepting the HomeKit Data Stream connections of one accessory."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ..const import LOGGER
from ..exceptions import HomeKitSecureVideoDataStreamError
from .connection import HomeKitSecureVideoDataStreamConnection
from .constants import CLOSE_TIMEOUT_SECONDS, CONNECT_TIMEOUT_SECONDS
from .prepared_session import HomeKitSecureVideoPreparedDataStreamSession
from .session_keys import HomeKitSecureVideoDataStreamSessionKeys

if TYPE_CHECKING:
    from collections.abc import Callable

    from .message import HomeKitSecureVideoDataStreamMessage

type MessageHandler = Callable[
    [HomeKitSecureVideoDataStreamConnection, HomeKitSecureVideoDataStreamMessage],
    None,
]
type ConnectionClosedListener = Callable[[HomeKitSecureVideoDataStreamConnection], None]


class HomeKitSecureVideoDataStreamServer:
    """
    TCP server accepting the HomeKit Data Stream connections of one accessory.

    A controller first writes to SetupDataStreamTransport over HAP, which
    prepares a session and answers with this server's port; it then opens a
    plain TCP connection here and proves which session it holds by encrypting
    its first frame with the keys both sides derived.
    """

    def __init__(self) -> None:
        """Initialize an idle server."""
        self._server: asyncio.Server | None = None
        self._prepared_sessions: list[HomeKitSecureVideoPreparedDataStreamSession] = []
        self._connections: list[HomeKitSecureVideoDataStreamConnection] = []
        self._handlers: dict[tuple[str, str], MessageHandler] = {}
        self._connection_closed_listeners: list[ConnectionClosedListener] = []

    @property
    def port(self) -> int | None:
        """Return the port the server listens on, if it is running."""
        if self._server is None or not self._server.sockets:
            return None
        port: int = self._server.sockets[0].getsockname()[1]
        return port

    @property
    def prepared_sessions(
        self,
    ) -> tuple[HomeKitSecureVideoPreparedDataStreamSession, ...]:
        """Return the sessions still waiting for their connection."""
        return tuple(self._prepared_sessions)

    @property
    def connections(self) -> tuple[HomeKitSecureVideoDataStreamConnection, ...]:
        """Return the live connections."""
        return tuple(self._connections)

    def register_handler(
        self, protocol: str, topic: str, handler: MessageHandler
    ) -> None:
        """Register the handler for one protocol and topic."""
        self._handlers[protocol, topic] = handler

    def register_connection_closed_listener(
        self, listener: ConnectionClosedListener
    ) -> None:
        """
        Register a listener notified when a connection goes away.

        A connection carries work that outlives the frames on it — a recording
        being delivered, for one — and its owner has no other way to learn the
        peer is gone.
        """
        self._connection_closed_listeners.append(listener)

    def prepare_session(
        self, shared_key: bytes, controller_key_salt: bytes
    ) -> HomeKitSecureVideoDataStreamSessionKeys:
        """
        Derive the keys for a new session and wait for its connection.

        Synchronous on purpose: HAP-python calls characteristic setters
        synchronously and expects the write response back from the same call,
        so the listening socket has to exist before the controller writes.
        """
        if self._server is None:
            message = "Failed to prepare a data stream session: server is not running"
            raise HomeKitSecureVideoDataStreamError(message)

        keys = HomeKitSecureVideoDataStreamSessionKeys.derive(
            shared_key, controller_key_salt
        )
        session = HomeKitSecureVideoPreparedDataStreamSession(keys=keys)
        session.expiry = asyncio.get_running_loop().call_later(
            CONNECT_TIMEOUT_SECONDS, self._discard_session, session
        )
        self._prepared_sessions.append(session)
        LOGGER.debug("Prepared a data stream session on port %s", self.port)
        return keys

    async def async_start(self, address: str) -> None:
        """
        Start listening on an ephemeral port, unless already listening.

        The address is bound explicitly: left to itself asyncio opens one
        socket per family, each on a *different* ephemeral port, and the port
        handed to the controller would only match one of them.
        """
        if self._server is not None:
            return
        self._server = await asyncio.get_running_loop().create_server(
            lambda: HomeKitSecureVideoDataStreamConnection(self),
            host=address,
            port=0,
        )
        LOGGER.debug("Data stream server listening on %s port %s", address, self.port)

    async def async_stop(self) -> None:
        """Close every connection and stop listening."""
        for session in self._prepared_sessions:
            session.cancel_expiry()
        self._prepared_sessions.clear()

        for connection in tuple(self._connections):
            connection.close()
        self._connections.clear()

        server = self._server
        self._server = None
        if server is not None:
            server.close()
            try:
                # Python 3.12 made this wait for every connection handler to
                # finish, so a peer that will not go away can hang the unload.
                async with asyncio.timeout(CLOSE_TIMEOUT_SECONDS):
                    await server.wait_closed()
            except TimeoutError:
                LOGGER.warning("Data stream server did not close cleanly")

    def async_claim_session(
        self, session: HomeKitSecureVideoPreparedDataStreamSession
    ) -> None:
        """Consume a prepared session once a connection has proven it holds it."""
        session.cancel_expiry()
        if session in self._prepared_sessions:
            self._prepared_sessions.remove(session)

    def async_add_connection(
        self, connection: HomeKitSecureVideoDataStreamConnection
    ) -> None:
        """Track a newly accepted connection."""
        self._connections.append(connection)

    def async_remove_connection(
        self, connection: HomeKitSecureVideoDataStreamConnection
    ) -> None:
        """Forget a connection that closed and tell whoever was using it."""
        if connection not in self._connections:
            return
        self._connections.remove(connection)
        for listener in tuple(self._connection_closed_listeners):
            listener(connection)

    def async_handle_message(
        self,
        connection: HomeKitSecureVideoDataStreamConnection,
        message: HomeKitSecureVideoDataStreamMessage,
    ) -> None:
        """Route a message to its registered handler."""
        handler = self._handlers.get((message.protocol, message.topic))
        if handler is None:
            LOGGER.debug(
                "No handler for data stream message %s/%s",
                message.protocol,
                message.topic,
            )
            return
        handler(connection, message)

    def _discard_session(
        self, session: HomeKitSecureVideoPreparedDataStreamSession
    ) -> None:
        """Drop a prepared session nobody connected for."""
        session.expiry = None
        if session in self._prepared_sessions:
            self._prepared_sessions.remove(session)
            LOGGER.debug("Prepared data stream session expired before a connection")
