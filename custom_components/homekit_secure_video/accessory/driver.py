"""AccessoryDriver that reports pairing changes back to the integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyhap.accessory_driver import AccessoryDriver

from ..const import LOGGER
from .hap_server import HomeKitSecureVideoHapServer

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID


class HomeKitSecureVideoAccessoryDriver(AccessoryDriver):
    """AccessoryDriver that reports pairing changes back to the integration."""

    def __init__(
        self,
        pairing_changed: Callable[[], None],
        *,
        address: str,
        port: int,
        **kwargs: str | int | bytes | object,
    ) -> None:
        """Initialize the driver with the callback fired on pairing changes."""
        super().__init__(address=address, port=port, **kwargs)
        self._pairing_changed = pairing_changed
        # Replaces the server HAP-python built in its own constructor: ours
        # keeps each session's shared key, which HomeKit Data Stream needs.
        self.http_server = HomeKitSecureVideoHapServer((address, self.state.port), self)

    def pair(
        self,
        client_username_bytes: bytes,
        client_public: str,
        client_permissions: bytes,
    ) -> bool:
        """Pair a controller and announce the new pairing state."""
        paired: bool = super().pair(
            client_username_bytes, client_public, client_permissions
        )
        if paired:
            self._announce_pairing_change()
        return paired

    def unpair(self, client_uuid: UUID) -> None:
        """Unpair a controller and announce the new pairing state."""
        super().unpair(client_uuid)
        self._announce_pairing_change()

    def _announce_pairing_change(self) -> None:
        """
        Report the change without letting a listener break pairing.

        This runs inside the HAP request that pairs a controller — including
        the one a controller sends to add the home hub — so an exception here
        would answer that request with an error and leave the hub unpaired.
        """
        try:
            self._pairing_changed()
        except Exception:  # noqa: BLE001 -- a broken listener must not fail pairing
            LOGGER.exception("Failed to report a pairing change")

    def shared_key_for(self, client_address: str) -> bytes | None:
        """Return the HAP session secret of the given controller connection."""
        server: HomeKitSecureVideoHapServer = self.http_server
        return server.shared_keys.get(client_address)
