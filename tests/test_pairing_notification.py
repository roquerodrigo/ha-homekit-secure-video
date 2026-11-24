from __future__ import annotations

from homeassistant.components.persistent_notification import (
    _async_get_or_create_notifications,
)

from .conftest import PAIRING_CODE


def _pairing_notification(hass, entry):
    notifications = _async_get_or_create_notifications(hass)
    return notifications.get(f"homekit_secure_video_{entry.entry_id}_pairing")


async def _push_status(hass, entry):
    entry.runtime_data.coordinator.async_handle_status_change()
    await hass.async_block_till_done()


async def test_an_unpaired_accessory_shows_its_code(hass, setup_integration):
    notification = _pairing_notification(hass, setup_integration)

    assert notification is not None
    assert PAIRING_CODE in notification["message"]
    assert "Front Door" in notification["message"]
    assert notification["title"] == "HomeKit pairing: Front Door"


async def test_pairing_dismisses_the_code(
    hass, setup_integration, mock_accessory_driver
):
    mock_accessory_driver.state.paired = True
    await _push_status(hass, setup_integration)

    assert _pairing_notification(hass, setup_integration) is None


async def test_unpairing_shows_the_code_again(
    hass, setup_integration, mock_accessory_driver
):
    mock_accessory_driver.state.paired = True
    await _push_status(hass, setup_integration)
    mock_accessory_driver.state.paired = False
    await _push_status(hass, setup_integration)

    assert PAIRING_CODE in _pairing_notification(hass, setup_integration)["message"]


async def test_a_dismissed_code_is_not_reshown_by_unrelated_updates(
    hass, setup_integration, mock_camera_accessory
):
    notifications = _async_get_or_create_notifications(hass)
    notifications.clear()
    mock_camera_accessory.is_streaming = True
    await _push_status(hass, setup_integration)

    assert _pairing_notification(hass, setup_integration) is None


async def test_a_paired_accessory_starts_without_the_code(
    hass,
    config_entry,
    camera_state,
    mock_accessory_driver,
    mock_camera_accessory,
    mock_data_stream_server,
):
    mock_accessory_driver.state.paired = True

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert _pairing_notification(hass, config_entry) is None


async def test_unloading_dismisses_the_code(hass, setup_integration):
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert _pairing_notification(hass, setup_integration) is None
