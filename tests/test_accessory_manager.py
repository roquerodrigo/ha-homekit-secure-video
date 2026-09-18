from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.homekit_secure_video.accessory import (
    HomeKitSecureVideoAccessoryManager,
)

from .conftest import CAMERA_MODE, HAP_PORT, PAIRING_CODE, SETUP_URI


async def test_status_is_empty_before_the_accessory_starts(hass, config_entry):
    manager = HomeKitSecureVideoAccessoryManager(hass, config_entry)

    assert manager.status == {
        "pairing_code": "",
        "setup_uri": "",
        "paired": False,
        "streaming": False,
        "recording": False,
        "camera_mode": None,
        "last_recording": None,
    }


async def test_status_reflects_the_running_accessory(hass, setup_integration):
    assert setup_integration.runtime_data.accessory_manager.status == {
        "pairing_code": PAIRING_CODE,
        "setup_uri": SETUP_URI,
        "paired": False,
        "streaming": False,
        "recording": False,
        "camera_mode": CAMERA_MODE,
        "last_recording": None,
    }


async def test_start_publishes_on_the_configured_port(
    hass, setup_integration, mock_accessory_driver
):
    from custom_components.homekit_secure_video.accessory import (
        manager as manager_module,
    )

    driver_class = manager_module.HomeKitSecureVideoAccessoryDriver
    assert driver_class.call_args.kwargs["port"] == HAP_PORT
    assert mock_accessory_driver.add_accessory.call_count == 1


async def test_persist_file_is_scoped_to_the_entry(hass, config_entry):
    manager = HomeKitSecureVideoAccessoryManager(hass, config_entry)

    assert manager.persist_file.name == (
        f"homekit_secure_video.{config_entry.entry_id}.state"
    )


async def test_reset_pairing_deletes_the_state_and_restarts(
    hass, setup_integration, mock_accessory_driver
):
    manager = setup_integration.runtime_data.accessory_manager
    manager.persist_file.parent.mkdir(parents=True, exist_ok=True)
    manager.persist_file.write_text("{}", encoding="utf-8")

    await manager.async_reset_pairing()

    assert not manager.persist_file.exists()
    assert mock_accessory_driver.async_stop.await_count == 1
    assert mock_accessory_driver.async_start.await_count == 2


async def test_status_listeners_are_notified_and_can_unsubscribe(hass, config_entry):
    manager = HomeKitSecureVideoAccessoryManager(hass, config_entry)
    calls = []

    unsubscribe = manager.async_add_status_listener(lambda: calls.append(1))
    manager._notify_status_listeners()
    unsubscribe()
    manager._notify_status_listeners()

    assert len(calls) == 1


async def test_stop_is_a_no_op_when_nothing_was_published(hass, config_entry):
    manager = HomeKitSecureVideoAccessoryManager(hass, config_entry)

    await manager.async_stop()

    assert manager.status["paired"] is False


async def test_the_driver_gets_the_pairing_code_from_the_entry(hass, setup_integration):
    from custom_components.homekit_secure_video.accessory import manager as module

    from .conftest import PAIRING_CODE, SETUP_ID

    driver_class = module.HomeKitSecureVideoAccessoryDriver
    assert driver_class.call_args.kwargs["pincode"] == PAIRING_CODE.encode()
    assert driver_class.return_value.state.setup_id == SETUP_ID


async def test_a_camera_that_is_not_up_yet_defers_the_setup(
    hass,
    config_entry,
    mock_accessory_driver,
    mock_camera_accessory,
    mock_data_stream_server,
):
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.exceptions import HomeAssistantError

    with patch(
        "custom_components.homekit_secure_video.accessory.manager"
        ".camera.async_get_stream_source",
        AsyncMock(side_effect=HomeAssistantError("Camera not found")),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state == ConfigEntryState.SETUP_RETRY


async def test_a_camera_without_a_stream_is_still_published(
    hass,
    config_entry,
    mock_accessory_driver,
    mock_camera_accessory,
    mock_data_stream_server,
):
    from homeassistant.config_entries import ConfigEntryState

    with patch(
        "custom_components.homekit_secure_video.accessory.manager"
        ".camera.async_get_stream_source",
        AsyncMock(return_value=None),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state == ConfigEntryState.LOADED


async def test_a_hanging_shutdown_step_does_not_block_the_unload(
    hass, setup_integration, mock_accessory_driver
):
    async def never_returns() -> None:
        await asyncio.Event().wait()

    mock_accessory_driver.async_stop = AsyncMock(side_effect=never_returns)

    with patch(
        "custom_components.homekit_secure_video.accessory.manager.STOP_TIMEOUT_SECONDS",
        0,
    ):
        await setup_integration.runtime_data.accessory_manager.async_stop()

    assert setup_integration.runtime_data.accessory_manager.status["paired"] is False


async def test_a_failing_shutdown_step_does_not_block_the_unload(
    hass, setup_integration, mock_accessory_driver, mock_data_stream_server
):
    mock_data_stream_server.async_stop = AsyncMock(side_effect=OSError("boom"))

    await setup_integration.runtime_data.accessory_manager.async_stop()

    assert mock_accessory_driver.async_stop.await_count >= 1


async def test_a_deferred_setup_releases_what_it_acquired(
    hass,
    config_entry,
    mock_accessory_driver,
    mock_camera_accessory,
    mock_data_stream_server,
):
    from homeassistant.exceptions import HomeAssistantError

    with patch(
        "custom_components.homekit_secure_video.accessory.manager"
        ".camera.async_get_stream_source",
        AsyncMock(side_effect=HomeAssistantError("Camera not found")),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    mock_data_stream_server.async_stop.assert_awaited()


async def test_a_data_stream_server_that_will_not_start_releases_the_driver(
    hass, config_entry, mock_accessory_driver, mock_camera_accessory
):
    manager = HomeKitSecureVideoAccessoryManager(hass, config_entry)
    with (
        patch.object(
            manager._data_stream_server,
            "async_start",
            AsyncMock(side_effect=OSError("address in use")),
        ),
        patch.object(
            manager._data_stream_server, "async_stop", AsyncMock()
        ) as stop_server,
        pytest.raises(OSError, match="address in use"),
    ):
        await manager.async_start()

    stop_server.assert_awaited_once()


async def test_a_recorder_that_keeps_failing_becomes_a_repair_issue(
    hass, setup_integration, mock_camera_accessory
):
    from homeassistant.helpers import issue_registry

    from custom_components.homekit_secure_video.const import DOMAIN
    from custom_components.homekit_secure_video.issues import (
        ISSUE_RECORDER_UNAVAILABLE,
    )

    report_health = mock_camera_accessory.set_recorder_health_callback.call_args.args[0]
    issue_id = f"{setup_integration.entry_id}_{ISSUE_RECORDER_UNAVAILABLE}"
    registry = issue_registry.async_get(hass)

    mock_camera_accessory.is_recorder_unhealthy = True
    report_health()

    assert registry.async_get_issue(DOMAIN, issue_id) is not None

    mock_camera_accessory.is_recorder_unhealthy = False
    report_health()

    assert registry.async_get_issue(DOMAIN, issue_id) is None


def _stored_state(entry_id):
    return {
        "version": 1,
        "minor_version": 1,
        "key": f"homekit_secure_video.{entry_id}.recording",
        "data": {
            "supported_configuration_fingerprint": "offer",
            "selected_configuration": "AQ==",
            "recording_active": True,
            "recording_audio_active": True,
            "event_snapshots_active": True,
            "homekit_camera_active": True,
            "periodic_snapshots_active": True,
            "source_profile": None,
        },
    }


async def test_the_recording_state_is_restored_on_start(
    hass, hass_storage, config_entry, setup_integration_factory
):
    hass_storage[f"homekit_secure_video.{config_entry.entry_id}.recording"] = (
        _stored_state(config_entry.entry_id)
    )

    accessory = await setup_integration_factory()

    accessory.restore_recording_state.assert_called_once_with(
        _stored_state(config_entry.entry_id)["data"]
    )


async def test_nothing_is_restored_on_a_first_start(
    hass, hass_storage, setup_integration_factory
):
    accessory = await setup_integration_factory()

    accessory.restore_recording_state.assert_not_called()


async def test_a_recording_state_change_is_saved(
    hass, hass_storage, config_entry, setup_integration_factory
):
    accessory = await setup_integration_factory()
    accessory.recording_state = _stored_state(config_entry.entry_id)["data"]

    accessory.set_recording_state_changed_callback.call_args.args[0]()
    await config_entry.runtime_data.accessory_manager.async_stop()

    stored = hass_storage[f"homekit_secure_video.{config_entry.entry_id}.recording"]
    assert stored["data"] == _stored_state(config_entry.entry_id)["data"]


async def test_reset_pairing_forgets_the_recording_state(
    hass, hass_storage, config_entry, setup_integration_factory
):
    key = f"homekit_secure_video.{config_entry.entry_id}.recording"
    hass_storage[key] = _stored_state(config_entry.entry_id)
    await setup_integration_factory()

    await config_entry.runtime_data.accessory_manager.async_reset_pairing()

    assert key not in hass_storage


async def test_a_state_saved_without_a_profile_loads_with_none(
    hass, hass_storage, config_entry, setup_integration_factory
):
    stored = _stored_state(config_entry.entry_id)
    del stored["data"]["source_profile"]
    hass_storage[f"homekit_secure_video.{config_entry.entry_id}.recording"] = stored

    accessory = await setup_integration_factory()

    restored = accessory.restore_recording_state.call_args.args[0]
    assert restored["source_profile"] is None


async def test_a_camera_that_does_not_answer_the_probe_keeps_its_last_profile(
    hass, hass_storage, config_entry, setup_integration_factory, mock_source_probe
):
    from custom_components.homekit_secure_video.accessory import manager as module
    from custom_components.homekit_secure_video.recording.source_probe import (
        EMPTY_PROFILE,
    )

    from .conftest import SOURCE_PROFILE

    stored = _stored_state(config_entry.entry_id)
    stored["data"]["source_profile"] = dict(SOURCE_PROFILE)
    hass_storage[f"homekit_secure_video.{config_entry.entry_id}.recording"] = stored
    mock_source_probe.return_value = dict(EMPTY_PROFILE)

    await setup_integration_factory()

    accessory_class = module.HomeKitSecureVideoCameraAccessory
    assert accessory_class.call_args.args[5] == SOURCE_PROFILE


async def test_a_camera_that_never_answered_the_probe_is_published_as_unknown(
    hass, hass_storage, config_entry, setup_integration_factory, mock_source_probe
):
    from custom_components.homekit_secure_video.accessory import manager as module
    from custom_components.homekit_secure_video.recording.source_probe import (
        EMPTY_PROFILE,
    )

    stored = _stored_state(config_entry.entry_id)
    stored["data"]["source_profile"] = dict(EMPTY_PROFILE)
    hass_storage[f"homekit_secure_video.{config_entry.entry_id}.recording"] = stored
    mock_source_probe.return_value = dict(EMPTY_PROFILE)

    await setup_integration_factory()

    accessory_class = module.HomeKitSecureVideoCameraAccessory
    assert accessory_class.call_args.args[5] == EMPTY_PROFILE
