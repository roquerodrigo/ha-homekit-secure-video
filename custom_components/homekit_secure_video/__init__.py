"""HomeKit Secure Video integration for Home Assistant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.loader import async_get_loaded_integration
from pyhap.util import generate_pincode, generate_setup_id

from .accessory import HomeKitSecureVideoAccessoryManager
from .const import CONF_PAIRING_CODE, CONF_SETUP_ID, DOMAIN
from .coordinator import HomeKitSecureVideoDataUpdateCoordinator
from .data import HomeKitSecureVideoData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceEntry

    from .data import HomeKitSecureVideoConfigEntry

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.IMAGE,
    Platform.SENSOR,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeKitSecureVideoConfigEntry,
) -> bool:
    """Set up HomeKit Secure Video from a config entry."""
    accessory_manager = HomeKitSecureVideoAccessoryManager(hass, entry)
    coordinator = HomeKitSecureVideoDataUpdateCoordinator(
        hass=hass,
        config_entry=entry,
        accessory_manager=accessory_manager,
    )
    entry.runtime_data = HomeKitSecureVideoData(
        accessory_manager=accessory_manager,
        coordinator=coordinator,
        integration=async_get_loaded_integration(hass, entry.domain),
    )
    entry.async_on_unload(
        accessory_manager.async_add_status_listener(
            coordinator.async_handle_status_change
        )
    )

    try:
        await accessory_manager.async_start()
    except OSError as exception:
        message = f"Failed to publish the HomeKit accessory: {exception}"
        raise ConfigEntryNotReady(message) from exception

    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_migrate_entry(
    hass: HomeAssistant,
    entry: HomeKitSecureVideoConfigEntry,
) -> bool:
    """Pin the pairing code and setup id of entries created before they existed."""
    if entry.version >= 2:  # noqa: PLR2004 -- the version this migration lands in
        return True

    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_PAIRING_CODE: generate_pincode().decode(),
            CONF_SETUP_ID: generate_setup_id(),
        },
        version=2,
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: HomeKitSecureVideoConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await entry.runtime_data.accessory_manager.async_stop()
    return unloaded


async def async_reload_entry(
    hass: HomeAssistant,
    entry: HomeKitSecureVideoConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(
    hass: HomeAssistant,
    entry: HomeKitSecureVideoConfigEntry,
) -> None:
    """Delete the persisted HomeKit pairing state of a removed entry."""
    accessory_manager = HomeKitSecureVideoAccessoryManager(hass, entry)
    await hass.async_add_executor_job(accessory_manager.remove_persist_file)


async def async_remove_config_entry_device(
    hass: HomeAssistant,  # noqa: ARG001 -- part of the signature Home Assistant calls
    entry: HomeKitSecureVideoConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """
    Allow deleting devices this entry no longer provides.

    Home Assistant hides the "delete device" button unless the integration
    implements this hook. Each entry publishes exactly one accessory, keyed by
    the entry id, so that device is refused — deleting it would leave the
    published accessory without entities — and anything else left behind by an
    earlier version of the integration is allowed to go.
    """
    return (DOMAIN, entry.entry_id) not in device_entry.identifiers
