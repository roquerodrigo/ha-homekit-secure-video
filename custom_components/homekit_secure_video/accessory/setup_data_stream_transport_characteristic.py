"""The SetupDataStreamTransport characteristic, which answers per HAP session."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyhap.characteristic import Characteristic

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID


class HomeKitSecureVideoSetupDataStreamTransportCharacteristic(Characteristic):
    """
    The SetupDataStreamTransport characteristic, which answers per HAP session.

    The write carries the controller's half of the data stream key salt, and
    the answer has to be derived from the secret of the very HAP session that
    wrote it — so unlike an ordinary setter this one needs to know who wrote.
    HAP-python passes the peer to ``client_update_value`` but not to the
    setter callback, which is why the callback is taken here instead.
    """

    def __init__(
        self,
        display_name: str,
        type_id: UUID,
        properties: dict[str, str | list[str]],
        setup_callback: Callable[[str, str], str],
    ) -> None:
        """Initialize the characteristic with the handler of the setup write."""
        super().__init__(display_name, type_id, properties)
        self._setup_callback = setup_callback

    def client_update_value(
        self, value: str, sender_client_addr: tuple[str, int] | None = None
    ) -> str:
        """Answer a setup write with the session parameters of that controller."""
        response = self._setup_callback(value, str(sender_client_addr))
        self.value = response
        return response
