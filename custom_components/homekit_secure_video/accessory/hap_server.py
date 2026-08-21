"""HAP server that retains the shared key of each paired session."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyhap.hap_handler import HAP_TLV_STATES, HAPServerHandler
from pyhap.hap_protocol import HAPServerProtocol
from pyhap.hap_server import HAPServer

if TYPE_CHECKING:
    import asyncio

    from pyhap.accessory_driver import AccessoryDriver
    from pyhap.hap_handler import HAPResponse


class HomeKitSecureVideoHapServerHandler(HAPServerHandler):
    """
    HAP request handler that answers an unauthenticated pairing request.

    HAP-python asserts that the connection has been verified before handling
    `/pairings`, one line above the check meant to reject it. A controller
    that asks to add a pairing on an unverified connection therefore gets a
    500 instead of the authentication error the spec calls for, and iOS gives
    up on adding the home hub — which is what Secure Video recording runs on.
    """

    def handle_pairings(self) -> None:
        """Reject the request when the connection has not been verified."""
        if self.client_uuid is None:
            self._send_authentication_error_tlv_response(HAP_TLV_STATES.M2)
            return
        super().handle_pairings()


class HomeKitSecureVideoHapServerProtocol(HAPServerProtocol):
    """
    HAP connection that retains the shared key of its session.

    HomeKit Data Stream derives its encryption keys from the secret the
    controller and the accessory agreed on during pair-verify. HAP-python
    hands that secret to the connection to set up its own cipher and then
    drops it, so it is captured here, keyed by the peer the write will arrive
    from.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        connections: dict[str, HAPServerProtocol],
        accessory_driver: AccessoryDriver,
        shared_keys: dict[str, bytes],
    ) -> None:
        """Initialize the connection with the store to publish the key into."""
        super().__init__(loop, connections, accessory_driver)
        self._shared_keys = shared_keys

    def connection_made(self, transport: asyncio.Transport) -> None:
        """Accept the connection, handling its requests with our own handler."""
        super().connection_made(transport)
        self.handler = HomeKitSecureVideoHapServerHandler(
            self.accessory_driver, self.peername
        )

    def _process_response(self, response: HAPResponse) -> None:
        """Remember the shared key as soon as pair-verify produces one."""
        super()._process_response(response)
        if response.shared_key and self.peername is not None:
            self._shared_keys[str(self.peername)] = response.shared_key

    def close(self) -> None:
        """Forget the shared key when the session ends."""
        if self.peername is not None:
            self._shared_keys.pop(str(self.peername), None)
        super().close()


class HomeKitSecureVideoHapServer(HAPServer):
    """HAP server whose connections retain their shared key."""

    def __init__(
        self, address_port: tuple[str, int], accessory_handler: AccessoryDriver
    ) -> None:
        """Initialize the server with an empty key store."""
        super().__init__(address_port, accessory_handler)
        self.shared_keys: dict[str, bytes] = {}

    async def async_start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Listen for HAP connections that retain their shared key."""
        self.loop = loop
        self.server = await loop.create_server(
            lambda: HomeKitSecureVideoHapServerProtocol(
                loop, self.connections, self.accessory_handler, self.shared_keys
            ),
            self._addr_port[0],
            self._addr_port[1],
        )
        self.async_cleanup_connections()
