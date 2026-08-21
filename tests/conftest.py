from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.camera import CameraEntityFeature
from homeassistant.const import ATTR_SUPPORTED_FEATURES
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_secure_video.const import DOMAIN

if TYPE_CHECKING:
    from collections.abc import Generator

pytest_plugins = "pytest_homeassistant_custom_component"

CAMERA_ENTITY_ID = "camera.front_door"
MOTION_ENTITY_ID = "binary_sensor.front_door_motion"
PAIRING_CODE = "123-45-678"
SETUP_URI = "X-HM://00PYAAAAAB1AB"
SETUP_ID = "1AB2"
CAMERA_MODE = "stream"
SOURCE_PROFILE = {
    "video_codec": "h264",
    "video_profile": "High",
    "video_level": 40,
    "width": 1920,
    "height": 1080,
    "frame_rate": 30.0,
    "audio_codec": None,
    "audio_sample_rate": None,
}
HAP_PORT = 21064
DATA_STREAM_PORT = 45678

RECORDING_DIAGNOSTICS = {
    "enabled": True,
    "audio_enabled": False,
    "in_flight": False,
    "recordings_started": 2,
    "selected_configuration": {"width": 1920, "height": 1080},
    "last_session": {"fragments_sent": 7, "bytes_sent": 1024},
    "recorder": {
        "running": True,
        "has_initialization_segment": True,
        "prebuffer_capacity": 3,
        "prebuffered_fragments": 2,
        "prebuffered_bytes": 512,
    },
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return enable_custom_integrations


@pytest.fixture(autouse=True)
def auto_mock_zeroconf(mock_async_zeroconf):
    return mock_async_zeroconf


@pytest.fixture
def camera_state(hass):
    hass.states.async_set(
        CAMERA_ENTITY_ID,
        "idle",
        {
            "friendly_name": "Front Door",
            ATTR_SUPPORTED_FEATURES: CameraEntityFeature.STREAM,
        },
    )
    return CAMERA_ENTITY_ID


@pytest.fixture
def mock_accessory_driver() -> Generator:
    with patch(
        "custom_components.homekit_secure_video.accessory.manager"
        ".HomeKitSecureVideoAccessoryDriver"
    ) as driver_class:
        driver = driver_class.return_value
        driver.state = MagicMock(pincode=PAIRING_CODE.encode(), paired=False)
        driver.async_start = AsyncMock(return_value=None)
        driver.async_stop = AsyncMock(return_value=None)
        driver.add_accessory = MagicMock(return_value=None)
        yield driver


@pytest.fixture
def mock_camera_accessory() -> Generator:
    with patch(
        "custom_components.homekit_secure_video.accessory.manager"
        ".HomeKitSecureVideoCameraAccessory"
    ) as accessory_class:
        accessory = accessory_class.return_value
        accessory.xhm_uri = MagicMock(return_value=SETUP_URI)
        accessory.is_streaming = False
        accessory.is_recording = False
        accessory.last_recording = None
        accessory.recording_diagnostics = RECORDING_DIAGNOSTICS
        accessory.homekit_camera_mode = CAMERA_MODE
        accessory.services = []
        accessory.async_probe_source = AsyncMock(return_value=dict(SOURCE_PROFILE))
        yield accessory


@pytest.fixture
def mock_data_stream_server() -> Generator:
    with patch(
        "custom_components.homekit_secure_video.accessory.manager"
        ".HomeKitSecureVideoDataStreamServer"
    ) as server_class:
        server = server_class.return_value
        server.async_start = AsyncMock(return_value=None)
        server.async_stop = AsyncMock(return_value=None)
        server.port = DATA_STREAM_PORT
        yield server


@pytest.fixture(autouse=True)
def mock_source_probe() -> Generator:
    with (
        patch(
            "custom_components.homekit_secure_video.accessory.manager"
            ".async_probe_source",
            AsyncMock(return_value=dict(SOURCE_PROFILE)),
        ) as probe,
        patch(
            "custom_components.homekit_secure_video.accessory.manager"
            ".camera.async_get_stream_source",
            AsyncMock(return_value="rtsp://camera/stream"),
        ),
    ):
        yield probe


@pytest.fixture
def config_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front Door",
        version=2,
        data={
            "camera_entity_id": CAMERA_ENTITY_ID,
            "motion_entity_id": MOTION_ENTITY_ID,
            "port": HAP_PORT,
            "pairing_code": PAIRING_CODE,
            "setup_id": SETUP_ID,
        },
        unique_id=CAMERA_ENTITY_ID,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_integration(
    hass,
    config_entry,
    camera_state,
    mock_accessory_driver,
    mock_camera_accessory,
    mock_data_stream_server,
):
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


@pytest.fixture
def free_ports():
    with patch(
        "custom_components.homekit_secure_video.config_flow._is_port_free",
        return_value=True,
    ) as is_port_free:
        yield is_port_free
