"""The SelectedCameraRecordingConfiguration characteristic."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyhap.characteristic import Characteristic

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from ..data import JsonValue


class HomeKitSecureVideoSelectedRecordingConfigurationCharacteristic(Characteristic):
    """
    The SelectedCameraRecordingConfiguration characteristic.

    Reading it before HomeKit has negotiated a configuration has to fail:
    answering an empty value with a success status tells the controller a
    configuration is already in place, and it then never writes one.

    The accessory description is the exception. HAP-python builds it by reading
    every characteristic, so failing there would make the whole accessory
    unreadable — it is served the cached value instead, which is what the
    reference implementation does too.
    """

    def __init__(
        self,
        display_name: str,
        type_id: UUID,
        properties: dict[str, str | list[str]],
        read_configuration: Callable[[], str],
    ) -> None:
        """Initialize the characteristic with the reader of the negotiated value."""
        super().__init__(display_name, type_id, properties)
        self._read_configuration = read_configuration

    def get_value(self) -> str:
        """Return the negotiated configuration, failing when there is none."""
        value: str = self._read_configuration()
        return value

    def to_HAP(self, include_value: bool = True) -> dict[str, JsonValue]:  # noqa: FBT001, FBT002, N802 -- HAP-python's signature
        """Describe the characteristic without failing the accessory dump."""
        representation: dict[str, JsonValue] = super().to_HAP(include_value=False)
        if include_value:
            representation["value"] = self.value
        return representation
