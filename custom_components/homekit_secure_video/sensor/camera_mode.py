"""Sensor exposing the mode HomeKit put the camera in."""

from __future__ import annotations

from typing import Final

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity

from ..entity import HomeKitSecureVideoEntity

CAMERA_MODES: Final[list[str]] = [
    "off",
    "detect_activity",
    "stream",
    "stream_and_record",
]


class HomeKitSecureVideoCameraModeSensor(HomeKitSecureVideoEntity, SensorEntity):
    """The mode selected for this camera in the Home app."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = CAMERA_MODES
    _attr_translation_key = "camera_mode"

    @property
    def unique_id(self) -> str:
        """Return the unique id of the sensor."""
        return f"{self.coordinator.config_entry.entry_id}_camera_mode"

    @property
    def native_value(self) -> str | None:
        """Return the mode HomeKit selected, if the accessory is published."""
        return self.coordinator.data["camera_mode"]
