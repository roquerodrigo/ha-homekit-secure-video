"""HomeKit Secure Video integration for Home Assistant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_loaded_integration
from pyhap.util import generate_pincode, generate_setup_id

from .accessory import HomeKitSecureVideoAccessoryManager
from .const import CONF_PAIRING_CODE, CONF_SETUP_ID, DOMAIN
from .coordinator import HomeKitSecureVideoDataUpdateCoordinator
from .data import HomeKitSecureVideoData
from .pairing_notification import HomeKitSecureVideoPairingNotification

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
    # Registered before the accessory starts: Home Assistant does not unload an
    # entry that never finished setting up, and this is what releases the HAP
    # port and the data stream socket when it does not.
    entry.async_on_unload(accessory_manager.async_stop)

    try:
        await accessory_manager.async_start()
    except OSError as exception:
        message = f"Failed to publish the HomeKit accessory: {exception}"
        raise ConfigEntryNotReady(message) from exception

    await coordinator.async_config_entry_first_refresh()

    pairing_notification = await HomeKitSecureVideoPairingNotification.async_create(
        hass, coordinator
    )
    entry.async_on_unload(pairing_notification.async_dismiss)
    entry.async_on_unload(
        coordinator.async_add_listener(
            pairing_notification.async_handle_coordinator_update
        )
    )
    pairing_notification.async_handle_coordinator_update()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_migrate_entry(
    hass: HomeAssistant,
    entry: HomeKitSecureVideoConfigEntry,
) -> bool:
    """
    Bring entries created by earlier versions up to date.

    Version 2 pinned the pairing code and the setup id on the entry. Version 3
    drops the sensor that published the code as entity state, and replaces the
    code that sensor recorded in history with a fresh one; existing pairings
    do not depend on it.
    """
    _remove_pairing_code_sensor(hass, entry)
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_PAIRING_CODE: generate_pincode().decode(),
            CONF_SETUP_ID: entry.data.get(CONF_SETUP_ID) or generate_setup_id(),
        },
        version=3,
    )
    return True


def _remove_pairing_code_sensor(
    hass: HomeAssistant,
    entry: HomeKitSecureVideoConfigEntry,
) -> None:
    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{entry.entry_id}_pairing_code"
    )
    if entity_id is not None:
        entity_registry.async_remove(entity_id)


async def async_unload_entry(
    hass: HomeAssistant,
    entry: HomeKitSecureVideoConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await entry.runtime_data.accessory_manager.async_stop()
    return unloaded


async def async_remove_entry(
    hass: HomeAssistant,
    entry: HomeKitSecureVideoConfigEntry,
) -> None:
    """Delete the persisted HomeKit pairing and recording state of a removed entry."""
    accessory_manager = HomeKitSecureVideoAccessoryManager(hass, entry)
    await hass.async_add_executor_job(accessory_manager.remove_persist_file)
    await accessory_manager.async_remove_recording_state()


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
