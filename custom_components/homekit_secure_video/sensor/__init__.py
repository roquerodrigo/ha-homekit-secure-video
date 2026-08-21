"""Sensor platform for homekit_secure_video."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .camera_mode import HomeKitSecureVideoCameraModeSensor
from .last_recording import HomeKitSecureVideoLastRecordingSensor
from .pairing_code import HomeKitSecureVideoPairingCodeSensor

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from ..data import HomeKitSecureVideoConfigEntry

__all__ = [
    "HomeKitSecureVideoCameraModeSensor",
    "HomeKitSecureVideoLastRecordingSensor",
    "HomeKitSecureVideoPairingCodeSensor",
]


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: HomeKitSecureVideoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            HomeKitSecureVideoPairingCodeSensor(coordinator),
            HomeKitSecureVideoCameraModeSensor(coordinator),
            HomeKitSecureVideoLastRecordingSensor(coordinator),
        ]
    )
