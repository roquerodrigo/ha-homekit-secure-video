from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.homekit_secure_video.const import DOMAIN

from .conftest import PAIRING_CODE, SETUP_URI


def _entity_id(hass, platform, suffix=""):
    states = hass.states.async_all(platform)
    if suffix:
        return next(
            state.entity_id for state in states if state.entity_id.endswith(suffix)
        )
    return next(iter(states)).entity_id


async def test_every_entity_belongs_to_the_entry_device(hass, setup_integration):
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    device = device_registry.async_get_device(
        identifiers={(DOMAIN, setup_integration.entry_id)}
    )

    entries = er.async_entries_for_config_entry(
        entity_registry, setup_integration.entry_id
    )
    assert len(entries) == 7
    assert {entry.device_id for entry in entries} == {device.id}


async def test_pairing_code_sensor_exposes_the_code(hass, setup_integration):
    assert hass.states.get("sensor.front_door_pairing_code").state == PAIRING_CODE


async def test_pairing_code_sensor_is_empty_once_paired(
    hass, setup_integration, mock_accessory_driver
):
    mock_accessory_driver.state.paired = True
    setup_integration.runtime_data.coordinator.async_handle_status_change()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.front_door_pairing_code").state == "unknown"


async def test_paired_binary_sensor_follows_the_accessory(
    hass, setup_integration, mock_accessory_driver
):
    assert hass.states.get("binary_sensor.front_door_paired").state == "off"

    mock_accessory_driver.state.paired = True
    setup_integration.runtime_data.coordinator.async_handle_status_change()
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.front_door_paired").state == "on"


async def test_qr_code_image_renders_the_setup_payload(hass, setup_integration):
    entity = hass.data["image"].get_entity(_entity_id(hass, "image"))
    image = await entity.async_image()

    assert image is not None
    assert image.startswith(b"\x89PNG")
    assert entity.content_type == "image/png"


async def test_qr_code_image_is_rendered_once_per_payload(hass, setup_integration):
    entity = hass.data["image"].get_entity(_entity_id(hass, "image"))

    first = await entity.async_image()
    second = await entity.async_image()

    assert first is second


async def test_qr_code_image_is_empty_without_a_payload(
    hass, setup_integration, mock_camera_accessory
):
    entity = hass.data["image"].get_entity(_entity_id(hass, "image"))
    mock_camera_accessory.xhm_uri.return_value = ""
    setup_integration.runtime_data.coordinator.async_handle_status_change()
    await hass.async_block_till_done()

    assert await entity.async_image() is None


async def test_qr_code_image_restamps_on_a_new_payload(hass, setup_integration):
    entity = hass.data["image"].get_entity(_entity_id(hass, "image"))
    await entity.async_image()
    stamped_at = entity.image_last_updated

    setup_integration.runtime_data.coordinator.async_set_updated_data(
        {
            "pairing_code": PAIRING_CODE,
            "setup_uri": f"{SETUP_URI}NEW",
            "paired": False,
            "streaming": False,
        }
    )
    await hass.async_block_till_done()

    assert entity.image_last_updated > stamped_at


async def test_reset_pairing_button_republishes_the_accessory(
    hass, setup_integration, mock_accessory_driver
):
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _entity_id(hass, "button")},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert mock_accessory_driver.async_stop.await_count == 1
    assert mock_accessory_driver.async_start.await_count == 2


async def test_camera_mode_sensor_reports_the_homekit_mode(hass, setup_integration):
    from .conftest import CAMERA_MODE

    state = hass.states.get("sensor.front_door_homekit_camera_mode")

    assert state.state == CAMERA_MODE
    assert state.attributes["options"] == [
        "off",
        "detect_activity",
        "stream",
        "stream_and_record",
    ]


async def test_camera_mode_sensor_follows_the_accessory(
    hass, setup_integration, mock_camera_accessory
):
    mock_camera_accessory.homekit_camera_mode = "stream_and_record"
    setup_integration.runtime_data.coordinator.async_handle_status_change()
    await hass.async_block_till_done()

    assert (
        hass.states.get("sensor.front_door_homekit_camera_mode").state
        == "stream_and_record"
    )


async def test_recording_binary_sensor_follows_the_accessory(
    hass, setup_integration, mock_camera_accessory
):
    assert hass.states.get("binary_sensor.front_door_recording").state == "off"

    mock_camera_accessory.is_recording = True
    setup_integration.runtime_data.coordinator.async_handle_status_change()
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.front_door_recording").state == "on"


async def test_last_recording_sensor_reports_when_a_clip_ended(
    hass, setup_integration, mock_camera_accessory
):
    from datetime import UTC, datetime

    assert hass.states.get("sensor.front_door_last_recording").state == "unknown"

    ended = datetime(2026, 8, 21, 15, 30, tzinfo=UTC)
    mock_camera_accessory.last_recording = ended
    setup_integration.runtime_data.coordinator.async_handle_status_change()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.front_door_last_recording").state == (
        "2026-08-21T15:30:00+00:00"
    )
