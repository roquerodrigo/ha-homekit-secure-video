"""Button platform for homekit_secure_video."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
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
    """Set up the button platform."""
    async_add_entities(
        [HomeKitSecureVideoResetPairingButton(entry.runtime_data.coordinator)]
    )


class HomeKitSecureVideoResetPairingButton(HomeKitSecureVideoEntity, ButtonEntity):
    """Drop every pairing and publish the accessory with a fresh code."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "reset_pairing"

    @property
    def unique_id(self) -> str:
        """Return the unique id of the button."""
        return f"{self.coordinator.config_entry.entry_id}_reset_pairing"

    async def async_press(self) -> None:
        """Reset the pairing of the accessory."""
        accessory_manager = self.coordinator.config_entry.runtime_data.accessory_manager
        await accessory_manager.async_reset_pairing()
