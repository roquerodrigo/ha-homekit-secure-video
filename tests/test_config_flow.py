from __future__ import annotations

from homeassistant import config_entries, data_entry_flow
from homeassistant.components.camera import CameraEntityFeature
from homeassistant.const import ATTR_SUPPORTED_FEATURES
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_secure_video.const import (
    DOMAIN,
    FIRST_HAP_PORT,
    LAST_HAP_PORT,
)

from .conftest import CAMERA_ENTITY_ID, MOTION_ENTITY_ID


async def _start_user_flow(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_user_step_shows_the_form(hass, camera_state):
    result = await _start_user_flow(hass)
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_user_step_creates_the_entry(
    hass,
    camera_state,
    free_ports,
    mock_accessory_driver,
    mock_camera_accessory,
    mock_data_stream_server,
):
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "camera_entity_id": CAMERA_ENTITY_ID,
            "motion_entity_id": MOTION_ENTITY_ID,
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Front Door"
    assert result["data"]["camera_entity_id"] == CAMERA_ENTITY_ID
    assert result["data"]["motion_entity_id"] == MOTION_ENTITY_ID
    assert FIRST_HAP_PORT <= result["data"]["port"] <= LAST_HAP_PORT
    assert len(result["data"]["pairing_code"]) == len("123-45-678")
    assert len(result["data"]["setup_id"]) == 4


async def test_user_step_rejects_an_unknown_camera(hass):
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"camera_entity_id": "camera.ghost"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"camera_entity_id": "camera_not_found"}


async def test_user_step_rejects_a_camera_without_stream(hass):
    hass.states.async_set(
        "camera.snapshot_only",
        "idle",
        {"friendly_name": "Snapshot only", ATTR_SUPPORTED_FEATURES: 0},
    )

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"camera_entity_id": "camera.snapshot_only"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"camera_entity_id": "camera_without_stream"}


async def test_user_step_aborts_when_the_camera_is_already_published(
    hass, camera_state, config_entry
):
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"camera_entity_id": CAMERA_ENTITY_ID}
    )

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_step_reports_when_no_port_is_free(hass, camera_state, monkeypatch):
    from custom_components.homekit_secure_video import config_flow

    monkeypatch.setattr(config_flow, "_is_port_free", lambda _port: False)

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"camera_entity_id": CAMERA_ENTITY_ID}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "no_free_port"}


async def test_reserved_ports_are_not_handed_out_twice(
    hass,
    camera_state,
    config_entry,
    free_ports,
    mock_accessory_driver,
    mock_camera_accessory,
    mock_data_stream_server,
):
    hass.states.async_set(
        "camera.back_door",
        "idle",
        {
            "friendly_name": "Back Door",
            ATTR_SUPPORTED_FEATURES: CameraEntityFeature.STREAM,
        },
    )

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"camera_entity_id": "camera.back_door"}
    )

    assert result["data"]["port"] != config_entry.data["port"]


async def test_reconfigure_updates_the_linked_motion_sensor(
    hass, camera_state, setup_integration
):
    result = await setup_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "camera_entity_id": CAMERA_ENTITY_ID,
            "motion_entity_id": "binary_sensor.hallway_motion",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert setup_integration.data["motion_entity_id"] == "binary_sensor.hallway_motion"


async def test_reconfigure_switches_the_published_camera(
    hass, camera_state, setup_integration
):
    hass.states.async_set(
        "camera.back_door",
        "idle",
        {
            "friendly_name": "Back Door",
            ATTR_SUPPORTED_FEATURES: CameraEntityFeature.STREAM,
        },
    )
    port = setup_integration.data["port"]
    pairing_code = setup_integration.data["pairing_code"]

    result = await setup_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"camera_entity_id": "camera.back_door"}
    )
    await hass.async_block_till_done()

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert setup_integration.data["camera_entity_id"] == "camera.back_door"
    assert setup_integration.unique_id == "camera.back_door"
    assert setup_integration.title == "Back Door"
    assert setup_integration.data["port"] == port
    assert setup_integration.data["pairing_code"] == pairing_code


async def test_reconfigure_drops_a_cleared_motion_sensor(
    hass, camera_state, setup_integration
):
    assert "motion_entity_id" in setup_integration.data

    result = await setup_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"camera_entity_id": CAMERA_ENTITY_ID}
    )
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert "motion_entity_id" not in setup_integration.data


async def test_reconfigure_rejects_a_camera_another_entry_publishes(
    hass, camera_state, setup_integration
):
    hass.states.async_set(
        "camera.back_door",
        "idle",
        {
            "friendly_name": "Back Door",
            ATTR_SUPPORTED_FEATURES: CameraEntityFeature.STREAM,
        },
    )
    MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={
            "camera_entity_id": "camera.back_door",
            "port": 21065,
            "pairing_code": "111-22-333",
            "setup_id": "ABCD",
        },
        unique_id="camera.back_door",
    ).add_to_hass(hass)

    result = await setup_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"camera_entity_id": "camera.back_door"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"camera_entity_id": "already_configured"}


async def test_always_on_motion_is_stored(hass, camera_state, setup_integration):
    result = await setup_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"camera_entity_id": CAMERA_ENTITY_ID, "always_on_motion": True},
    )
    await hass.async_block_till_done()

    assert setup_integration.data["always_on_motion"] is True


def test_is_port_free_reports_a_bindable_port():
    from unittest.mock import MagicMock, patch

    from custom_components.homekit_secure_video.config_flow import _is_port_free

    with patch("socket.socket") as socket_class:
        socket_class.return_value.__enter__.return_value = MagicMock()
        assert _is_port_free(21064)


def test_is_port_free_reports_a_taken_port():
    from unittest.mock import MagicMock, patch

    from custom_components.homekit_secure_video.config_flow import _is_port_free

    test_socket = MagicMock()
    test_socket.bind.side_effect = OSError
    with patch("socket.socket") as socket_class:
        socket_class.return_value.__enter__.return_value = test_socket
        assert not _is_port_free(21064)


async def test_the_form_offers_re_encoding(hass, camera_state):
    result = await _start_user_flow(hass)

    schema = result["data_schema"].schema
    reencode = next(key for key in schema if str(key) == "reencode")
    assert reencode.default() is True


async def test_re_encoding_is_stored_as_an_option(
    hass,
    camera_state,
    free_ports,
    mock_accessory_driver,
    mock_camera_accessory,
    mock_data_stream_server,
):
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"camera_entity_id": CAMERA_ENTITY_ID, "reencode": False},
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    # Stored where the options flow reads it, not duplicated on the entry data.
    assert result["options"]["reencode"] is False
    assert "reencode" not in result["data"]


async def test_re_encoding_defaults_to_on_when_left_alone(
    hass,
    camera_state,
    free_ports,
    mock_accessory_driver,
    mock_camera_accessory,
    mock_data_stream_server,
):
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"camera_entity_id": CAMERA_ENTITY_ID, "reencode": True}
    )

    assert result["options"]["reencode"] is True


async def test_reconfigure_does_not_offer_re_encoding(
    hass, camera_state, setup_integration
):
    result = await setup_integration.start_reconfigure_flow(hass)

    schema = result["data_schema"].schema
    assert not any(str(key) == "reencode" for key in schema)
