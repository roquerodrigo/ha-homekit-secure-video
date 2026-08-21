from __future__ import annotations

from .conftest import PAIRING_CODE


async def test_coordinator_does_not_poll(hass, setup_integration):
    assert setup_integration.runtime_data.coordinator.update_interval is None


async def test_first_refresh_reads_the_accessory(hass, setup_integration):
    assert setup_integration.runtime_data.coordinator.data["pairing_code"] == (
        PAIRING_CODE
    )


async def test_accessory_changes_reach_the_entities(
    hass, setup_integration, mock_camera_accessory
):
    mock_camera_accessory.is_streaming = True
    setup_integration.runtime_data.accessory_manager._notify_status_listeners()
    await hass.async_block_till_done()

    assert setup_integration.runtime_data.coordinator.data["streaming"] is True
