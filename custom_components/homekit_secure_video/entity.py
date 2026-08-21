"""HomeKitSecureVideoEntity base class."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import HomeKitSecureVideoDataUpdateCoordinator


class HomeKitSecureVideoEntity(
    CoordinatorEntity[HomeKitSecureVideoDataUpdateCoordinator]
):
    """Base entity for HomeKit Secure Video."""

    _attr_has_entity_name = True

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the published accessory."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=self.coordinator.config_entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
