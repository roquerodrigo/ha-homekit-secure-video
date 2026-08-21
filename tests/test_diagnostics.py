from __future__ import annotations

from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from .conftest import CAMERA_ENTITY_ID


async def test_diagnostics_describe_the_entry(hass, hass_client, setup_integration):
    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, setup_integration
    )

    assert diagnostics["entry"]["domain"] == "homekit_secure_video"
    assert diagnostics["entry"]["data"]["camera_entity_id"] == CAMERA_ENTITY_ID


async def test_diagnostics_redact_the_pairing_secrets(
    hass, hass_client, setup_integration
):
    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, setup_integration
    )

    assert diagnostics["accessory"]["pairing_code"] == "**REDACTED**"
    assert diagnostics["accessory"]["setup_uri"] == "**REDACTED**"
    assert diagnostics["accessory"]["paired"] is False


async def test_diagnostics_list_the_published_services(
    hass, hass_client, setup_integration, mock_camera_accessory
):
    service = MagicMock()
    service.display_name = "DataStreamTransportManagement"
    mock_camera_accessory.services = [service]

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, setup_integration
    )

    assert diagnostics["services"] == ["DataStreamTransportManagement"]


async def test_diagnostics_report_the_data_stream_port(
    hass, hass_client, setup_integration
):
    from .conftest import DATA_STREAM_PORT

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, setup_integration
    )

    assert diagnostics["data_stream_port"] == DATA_STREAM_PORT


async def test_diagnostics_report_what_the_camera_sends(
    hass, hass_client, setup_integration
):
    from .conftest import SOURCE_PROFILE

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, setup_integration
    )

    assert diagnostics["camera_source"] == SOURCE_PROFILE


async def test_diagnostics_report_the_recording_state(
    hass, hass_client, setup_integration
):
    from .conftest import RECORDING_DIAGNOSTICS

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, setup_integration
    )

    assert diagnostics["recording"] == RECORDING_DIAGNOSTICS
