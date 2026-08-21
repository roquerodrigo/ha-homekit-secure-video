"""DataUpdateCoordinator for homekit_secure_video."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, LOGGER

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .accessory import HomeKitSecureVideoAccessoryManager
    from .data import (
        HomeKitSecureVideoAccessoryStatus,
        HomeKitSecureVideoConfigEntry,
    )


class HomeKitSecureVideoDataUpdateCoordinator(
    DataUpdateCoordinator["HomeKitSecureVideoAccessoryStatus"]
):
    """
    Coordinator holding the status of the published HomeKit accessory.

    Nothing is polled here: the accessory is local and pushes its own changes,
    so ``update_interval`` stays ``None`` and every update arrives through
    ``async_handle_status_change``. The coordinator is kept because it is the
    contract the entities of this integration are built on.
    """

    config_entry: HomeKitSecureVideoConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: HomeKitSecureVideoConfigEntry,
        accessory_manager: HomeKitSecureVideoAccessoryManager,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass=hass,
            logger=LOGGER,
            name=DOMAIN,
            update_interval=None,
            always_update=False,
            config_entry=config_entry,
        )
        self._accessory_manager = accessory_manager

    async def _async_update_data(self) -> HomeKitSecureVideoAccessoryStatus:
        """Read the current status straight from the accessory."""
        return self._accessory_manager.status

    @callback
    def async_handle_status_change(self) -> None:
        """Publish a status change pushed by the accessory."""
        self.async_set_updated_data(self._accessory_manager.status)
