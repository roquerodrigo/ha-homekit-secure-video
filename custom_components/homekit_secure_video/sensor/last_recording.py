"""Sensor exposing when the last recording was delivered."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.util import dt as dt_util

from ..entity import HomeKitSecureVideoEntity

if TYPE_CHECKING:
    from datetime import datetime


class HomeKitSecureVideoLastRecordingSensor(HomeKitSecureVideoEntity, SensorEntity):
    """When the last recording finished being delivered to the home hub."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_recording"

    @property
    def unique_id(self) -> str:
        """Return the unique id of the sensor."""
        return f"{self.coordinator.config_entry.entry_id}_last_recording"

    @property
    def native_value(self) -> datetime | None:
        """Return the moment the last recording ended, if there was one."""
        delivered = self.coordinator.data["last_recording"]
        return dt_util.parse_datetime(delivered) if delivered else None
