from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState

from .conftest import PAIRING_CODE


async def test_setup_entry_loads_successfully(hass, setup_integration):
    assert setup_integration.state == ConfigEntryState.LOADED


async def test_setup_entry_creates_its_entities(hass, setup_integration):
    counts = {"sensor": 3, "binary_sensor": 2, "image": 1, "button": 1}
    for platform, expected in counts.items():
        assert len(hass.states.async_all(platform)) == expected, platform


async def test_setup_entry_publishes_the_pairing_code(hass, setup_integration):
    state = hass.states.get("sensor.front_door_pairing_code")
    assert state.state == PAIRING_CODE


async def test_setup_entry_starts_the_accessory(
    hass, setup_integration, mock_accessory_driver
):
    assert mock_accessory_driver.async_start.await_count == 1


async def test_setup_entry_registers_update_listener(hass, setup_integration):
    assert len(setup_integration.update_listeners) == 1


async def test_unload_entry_succeeds(hass, setup_integration):
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    assert setup_integration.state == ConfigEntryState.NOT_LOADED


async def test_unload_entry_stops_the_accessory(
    hass, setup_integration, mock_accessory_driver
):
    await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert mock_accessory_driver.async_stop.await_count == 1


async def test_unload_entry_makes_entities_unavailable(hass, setup_integration):
    await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()
    for state in hass.states.async_all("sensor"):
        assert state.state == "unavailable"


async def test_reload_entry_restores_loaded_state(hass, setup_integration):
    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert setup_integration.state == ConfigEntryState.LOADED


async def test_setup_entry_retries_when_the_port_is_taken(
    hass,
    config_entry,
    camera_state,
    mock_camera_accessory,
    mock_data_stream_server,
):
    with patch(
        "custom_components.homekit_secure_video.accessory.manager"
        ".HomeKitSecureVideoAccessoryDriver"
    ) as driver_class:
        driver_class.return_value.async_start = AsyncMock(
            side_effect=OSError("address already in use")
        )
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state == ConfigEntryState.SETUP_RETRY


async def test_remove_entry_deletes_the_pairing_state(hass, setup_integration):
    persist_file = setup_integration.runtime_data.accessory_manager.persist_file
    persist_file.parent.mkdir(parents=True, exist_ok=True)
    persist_file.write_text("{}", encoding="utf-8")

    await hass.config_entries.async_remove(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert not persist_file.exists()


async def test_device_of_the_entry_cannot_be_deleted(hass, setup_integration):
    from homeassistant.helpers import device_registry as dr

    from custom_components.homekit_secure_video import (
        async_remove_config_entry_device,
    )
    from custom_components.homekit_secure_video.const import DOMAIN

    registry = dr.async_get(hass)
    device = registry.async_get_device(
        identifiers={(DOMAIN, setup_integration.entry_id)}
    )
    assert device is not None
    assert not await async_remove_config_entry_device(hass, setup_integration, device)


async def test_stale_device_can_be_deleted(hass, setup_integration):
    from homeassistant.helpers import device_registry as dr

    from custom_components.homekit_secure_video import (
        async_remove_config_entry_device,
    )
    from custom_components.homekit_secure_video.const import DOMAIN

    registry = dr.async_get(hass)
    stale = registry.async_get_or_create(
        config_entry_id=setup_integration.entry_id,
        identifiers={(DOMAIN, "gone")},
    )
    assert await async_remove_config_entry_device(hass, setup_integration, stale)


async def test_an_old_entry_gets_a_pinned_pairing_identity(
    hass,
    camera_state,
    mock_accessory_driver,
    mock_camera_accessory,
    mock_data_stream_server,
):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.homekit_secure_video.const import DOMAIN

    from .conftest import CAMERA_ENTITY_ID, HAP_PORT

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front Door",
        version=1,
        data={"camera_entity_id": CAMERA_ENTITY_ID, "port": HAP_PORT},
        unique_id=CAMERA_ENTITY_ID,
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 2
    assert len(entry.data["pairing_code"]) == len("123-45-678")
    assert len(entry.data["setup_id"]) == 4


async def test_the_pairing_code_survives_a_reload(hass, setup_integration):
    code = setup_integration.data["pairing_code"]

    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert setup_integration.data["pairing_code"] == code
