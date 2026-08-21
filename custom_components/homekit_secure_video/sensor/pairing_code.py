"""Sensor exposing the HomeKit pairing code of the accessory."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory

from ..entity import HomeKitSecureVideoEntity


class HomeKitSecureVideoPairingCodeSensor(HomeKitSecureVideoEntity, SensorEntity):
    """The HomeKit pairing code to type into the Home app."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "pairing_code"

    @property
    def unique_id(self) -> str:
        """Return the unique id of the sensor."""
        return f"{self.coordinator.config_entry.entry_id}_pairing_code"

    @property
    def native_value(self) -> str | None:
        """Return the pairing code, or None once the accessory is paired."""
        if self.coordinator.data["paired"]:
            return None
        return self.coordinator.data["pairing_code"] or None
