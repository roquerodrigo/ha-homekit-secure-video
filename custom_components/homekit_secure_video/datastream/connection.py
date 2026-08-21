"""One TCP connection carrying a HomeKit Data Stream session."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ..const import LOGGER
from ..exceptions import HomeKitSecureVideoDataStreamError
from .constants import (
    HELLO_TIMEOUT_SECONDS,
    HomeKitSecureVideoDataStreamMessageType,
    HomeKitSecureVideoDataStreamProtocolName,
    HomeKitSecureVideoDataStreamStatus,
    HomeKitSecureVideoDataStreamTopic,
)
from .frame import HomeKitSecureVideoDataStreamFrame, split_frames
from .frame_codec import HomeKitSecureVideoDataStreamFrameCodec
from .message import HomeKitSecureVideoDataStreamMessage

if TYPE_CHECKING:
    from ..data import OpackValue
    from .server import HomeKitSecureVideoDataStreamServer


class HomeKitSecureVideoDataStreamConnection(asyncio.Protocol):
    """
    One TCP connection carrying a HomeKit Data Stream session.

    A controller opens the socket without saying which of the sessions it
    negotiated over HAP it belongs to, so the first frame is tried against the
    keys of every prepared session; the one that authenticates identifies it.
    """

    def __init__(self, server: HomeKitSecureVideoDataStreamServer) -> None:
        """Initialize the connection for the given server."""
        self._server = server
        self._transport: asyncio.Transport | None = None
        self._codec: HomeKitSecureVideoDataStreamFrameCodec | None = None
        self._buffer = b""
        self._greeted = False
        self._hello_timeout: asyncio.TimerHandle | None = None
        self.remote_address = "unknown"

    @property
    def is_ready(self) -> bool:
        """Return whether the connection completed its handshake."""
        return self._greeted

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Start the handshake timer for a freshly accepted socket."""
        if not isinstance(transport, asyncio.Transport):
            return
        self._transport = transport
        peer = transport.get_extra_info("peername")
        if peer:
            self.remote_address = f"{peer[0]}:{peer[1]}"
        LOGGER.debug("Data stream connection opened from %s", self.remote_address)
        self._server.async_add_connection(self)
        self._hello_timeout = asyncio.get_running_loop().call_later(
            HELLO_TIMEOUT_SECONDS, self._handle_hello_timeout
        )

    def data_received(self, data: bytes) -> None:
        """Decrypt and dispatch every complete frame in the buffer."""
        self._buffer += data
        try:
            frames, self._buffer = split_frames(self._buffer)
        except HomeKitSecureVideoDataStreamError:
            LOGGER.exception("Malformed data stream frame from %s", self.remote_address)
            self.close()
            return

        for frame in frames:
            if self._codec is None and not self._identify(frame):
                LOGGER.warning(
                    "No prepared data stream session matches %s", self.remote_address
                )
                self.close()
                return

            payload = self._codec.decrypt(frame) if self._codec else None
            if payload is None:
                LOGGER.warning(
                    "Data stream frame from %s failed to authenticate",
                    self.remote_address,
                )
                self.close()
                return

            self._dispatch(payload)

    def connection_lost(self, exc: Exception | None) -> None:  # noqa: ARG002 -- part of the asyncio.Protocol signature
        """Drop the connection from the server."""
        LOGGER.debug("Data stream connection from %s closed", self.remote_address)
        if self._hello_timeout is not None:
            self._hello_timeout.cancel()
            self._hello_timeout = None
        self._transport = None
        self._server.async_remove_connection(self)

    def send_event(
        self, protocol: str, topic: str, payload: dict[str, OpackValue]
    ) -> None:
        """Send an event message to the controller."""
        self._send(
            HomeKitSecureVideoDataStreamMessage(
                message_type=HomeKitSecureVideoDataStreamMessageType.EVENT,
                protocol=protocol,
                topic=topic,
                payload=payload,
            )
        )

    def send_response(
        self,
        protocol: str,
        topic: str,
        identifier: int,
        status: HomeKitSecureVideoDataStreamStatus = (
            HomeKitSecureVideoDataStreamStatus.SUCCESS
        ),
        payload: dict[str, OpackValue] | None = None,
    ) -> None:
        """Answer a request from the controller."""
        self._send(
            HomeKitSecureVideoDataStreamMessage(
                message_type=HomeKitSecureVideoDataStreamMessageType.RESPONSE,
                protocol=protocol,
                topic=topic,
                identifier=identifier,
                status=status,
                payload=payload or {},
            )
        )

    def close(self) -> None:
        """Close the underlying socket at once."""
        transport = self._transport
        self._transport = None
        if transport is not None:
            # Aborted rather than closed: a graceful close waits for the peer,
            # and this runs on the path that unloads the config entry.
            transport.abort()

    def _identify(self, frame: HomeKitSecureVideoDataStreamFrame) -> bool:
        """Adopt the prepared session whose keys decrypt the first frame."""
        for session in self._server.prepared_sessions:
            codec = HomeKitSecureVideoDataStreamFrameCodec(session.keys)
            if codec.decrypt(frame) is not None:
                self._server.async_claim_session(session)
                self._codec = HomeKitSecureVideoDataStreamFrameCodec(session.keys)
                LOGGER.debug(
                    "Data stream connection from %s identified", self.remote_address
                )
                return True
        return False

    def _dispatch(self, payload: bytes) -> None:
        """Route one decrypted payload to its handler."""
        try:
            message = HomeKitSecureVideoDataStreamMessage.from_payload(payload)
        except HomeKitSecureVideoDataStreamError:
            LOGGER.exception(
                "Unreadable data stream message from %s", self.remote_address
            )
            return

        if not self._greeted:
            self._handle_hello(message)
            return

        LOGGER.debug(
            "Data stream message from %s: %s/%s",
            self.remote_address,
            message.protocol,
            message.topic,
        )
        self._server.async_handle_message(self, message)

    def _handle_hello(self, message: HomeKitSecureVideoDataStreamMessage) -> None:
        """Complete the handshake, which the first message must perform."""
        expected = (
            message.message_type == HomeKitSecureVideoDataStreamMessageType.REQUEST
            and message.protocol == HomeKitSecureVideoDataStreamProtocolName.CONTROL
            and message.topic == HomeKitSecureVideoDataStreamTopic.HELLO
            and message.identifier is not None
        )
        if not expected:
            LOGGER.warning(
                "First data stream message from %s was not a hello", self.remote_address
            )
            self.close()
            return

        if self._hello_timeout is not None:
            self._hello_timeout.cancel()
            self._hello_timeout = None
        self._greeted = True
        LOGGER.debug("Data stream handshake with %s completed", self.remote_address)
        self.send_response(
            HomeKitSecureVideoDataStreamProtocolName.CONTROL,
            HomeKitSecureVideoDataStreamTopic.HELLO,
            identifier=message.identifier or 0,
        )

    def _handle_hello_timeout(self) -> None:
        """Drop a connection that never greeted us."""
        self._hello_timeout = None
        LOGGER.warning(
            "Data stream connection from %s never said hello", self.remote_address
        )
        self.close()

    def _send(self, message: HomeKitSecureVideoDataStreamMessage) -> None:
        """Encrypt and write one message."""
        if self._transport is None or self._codec is None:
            LOGGER.debug("Dropping data stream message: connection is not ready")
            return
        self._transport.write(self._codec.encrypt(message.to_payload()))
