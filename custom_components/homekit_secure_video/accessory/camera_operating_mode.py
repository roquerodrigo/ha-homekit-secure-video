"""The CameraOperatingMode service, which carries the camera's HomeKit mode."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final
from uuid import UUID

from pyhap.characteristic import Characteristic
from pyhap.service import Service

if TYPE_CHECKING:
    from collections.abc import Callable

SERVICE_UUID: Final = UUID("0000021A-0000-1000-8000-0026BB765291")
EVENT_SNAPSHOTS_ACTIVE_UUID: Final = UUID("00000223-0000-1000-8000-0026BB765291")
HOMEKIT_CAMERA_ACTIVE_UUID: Final = UUID("0000021B-0000-1000-8000-0026BB765291")
PERIODIC_SNAPSHOTS_ACTIVE_UUID: Final = UUID("00000225-0000-1000-8000-0026BB765291")
OPERATING_MODE_INDICATOR_UUID: Final = UUID("0000021D-0000-1000-8000-0026BB765291")

OPERATING_MODE_INDICATOR = "CameraOperatingModeIndicator"
EVENT_SNAPSHOTS_ACTIVE = "EventSnapshotsActive"
HOMEKIT_CAMERA_ACTIVE = "HomeKitCameraActive"
PERIODIC_SNAPSHOTS_ACTIVE = "PeriodicSnapshotsActive"

_ACTIVE_PROPERTIES: Final[dict[str, str | list[str] | dict[str, int]]] = {
    "Format": "uint8",
    "Permissions": ["pr", "pw", "ev"],
    "ValidValues": {"Off": 0, "On": 1},
}


class HomeKitSecureVideoCameraOperatingModeService:
    """
    The CameraOperatingMode service, which carries the camera's HomeKit mode.

    `HomeKitCameraActive` is the switch behind "Off" in the Home app: with it
    off the controller must not stream or record, so a running recording is
    torn down when it flips.
    """

    def __init__(self, camera_active_changed: Callable[[], None]) -> None:
        """Initialize the service with the callback fired on every mode change."""
        self._camera_active_changed = camera_active_changed
        self.service = self._build_service()

    @property
    def is_camera_active(self) -> bool:
        """Return whether HomeKit currently allows this camera to be used."""
        return bool(self.service.get_characteristic(HOMEKIT_CAMERA_ACTIVE).value)

    @property
    def are_event_snapshots_active(self) -> bool:
        """Return whether HomeKit wants a snapshot with each event."""
        return bool(self.service.get_characteristic(EVENT_SNAPSHOTS_ACTIVE).value)

    def _build_service(self) -> Service:
        """Build the service with the three characteristics HomeKit requires."""
        service = Service(SERVICE_UUID, "CameraOperatingMode")
        for display_name, type_id in (
            (EVENT_SNAPSHOTS_ACTIVE, EVENT_SNAPSHOTS_ACTIVE_UUID),
            (HOMEKIT_CAMERA_ACTIVE, HOMEKIT_CAMERA_ACTIVE_UUID),
            (PERIODIC_SNAPSHOTS_ACTIVE, PERIODIC_SNAPSHOTS_ACTIVE_UUID),
        ):
            characteristic = Characteristic(
                display_name, type_id, dict(_ACTIVE_PROPERTIES)
            )
            characteristic.value = 1
            service.add_characteristic(characteristic)

        # Drives the camera's status light. Working Secure Video cameras
        # expose it; a controller that cannot find it treats the camera as
        # incomplete.
        indicator = Characteristic(
            OPERATING_MODE_INDICATOR,
            OPERATING_MODE_INDICATOR_UUID,
            {"Format": "bool", "Permissions": ["pr", "pw", "ev"]},
        )
        indicator.value = True
        service.add_characteristic(indicator)

        service.get_characteristic(
            HOMEKIT_CAMERA_ACTIVE
        ).setter_callback = self._handle_camera_active_write
        return service

    def _handle_camera_active_write(self, value: int) -> None:  # noqa: ARG002 -- the new value is read back from the characteristic
        """
        Report every change, in both directions.

        Reacting only to the camera being switched off leaves whatever was
        derived from it — the linked sensor's StatusActive above all — stuck in
        the off state, and HomeKit then refuses to switch the camera back on.
        """
        self._camera_active_changed()
