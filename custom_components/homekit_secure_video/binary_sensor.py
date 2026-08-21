"""Binary sensor platform for homekit_secure_video."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory

from .entity import HomeKitSecureVideoEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .data import HomeKitSecureVideoConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: HomeKitSecureVideoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            HomeKitSecureVideoPairedBinarySensor(coordinator),
            HomeKitSecureVideoRecordingBinarySensor(coordinator),
        ]
    )


class HomeKitSecureVideoPairedBinarySensor(
    HomeKitSecureVideoEntity, BinarySensorEntity
):
    """Whether a HomeKit controller is paired with the accessory."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "paired"

    @property
    def unique_id(self) -> str:
        """Return the unique id of the binary sensor."""
        return f"{self.coordinator.config_entry.entry_id}_paired"

    @property
    def is_on(self) -> bool:
        """Return whether the accessory is paired."""
        return self.coordinator.data["paired"]


class HomeKitSecureVideoRecordingBinarySensor(
    HomeKitSecureVideoEntity, BinarySensorEntity
):
    """Whether a recording is being delivered to the home hub right now."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = "recording"

    @property
    def unique_id(self) -> str:
        """Return the unique id of the binary sensor."""
        return f"{self.coordinator.config_entry.entry_id}_recording"

    @property
    def is_on(self) -> bool:
        """Return whether a recording is in flight."""
        return self.coordinator.data["recording"]
