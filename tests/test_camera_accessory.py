from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from pyhap.camera import STREAMING_STATUS

from custom_components.homekit_secure_video.accessory import (
    HomeKitSecureVideoCameraAccessory,
)
from custom_components.homekit_secure_video.recording import (
    HomeKitSecureVideoAudioSampleRate,
)
from custom_components.homekit_secure_video.recording.source_probe import EMPTY_PROFILE

from .conftest import CAMERA_ENTITY_ID, MOTION_ENTITY_ID

MODULE = "custom_components.homekit_secure_video.accessory.camera_accessory"
STREAMING_AVAILABLE = STREAMING_STATUS["AVAILABLE"]
EMPTY_SOURCE = {
    "video_codec": None,
    "video_profile": None,
    "video_level": None,
    "width": None,
    "height": None,
    "frame_rate": None,
    "audio_codec": None,
    "audio_sample_rate": None,
}
_PROBED_WITH_AUDIO = {
    **EMPTY_SOURCE,
    "video_codec": "h264",
    "width": 1920,
    "height": 1080,
    "frame_rate": 30,
    "audio_codec": "aac",
    "audio_sample_rate": 16000,
}
STREAM_REQUEST = {
    "address": "192.168.1.10",
    "v_port": 50000,
    "v_srtp_key": "c3JydHBrZXk=",
    "v_ssrc": 12345,
    "v_max_bitrate": 299,
}


@pytest.fixture
def hap_driver(hass, tmp_path):
    from custom_components.homekit_secure_video.accessory import (
        HomeKitSecureVideoAccessoryDriver,
    )

    return HomeKitSecureVideoAccessoryDriver(
        lambda: None,
        address="127.0.0.1",
        port=21064,
        persist_file=str(tmp_path / "accessory.state"),
        loop=hass.loop,
    )


@pytest.fixture
def data_stream_server():
    from custom_components.homekit_secure_video.datastream import (
        HomeKitSecureVideoDataStreamServer,
    )

    return HomeKitSecureVideoDataStreamServer()


def _build_accessory(hass, hap_driver, config_entry, data_stream_server):
    with patch(f"{MODULE}.get_ffmpeg_manager") as ffmpeg_manager:
        ffmpeg_manager.return_value.binary = "ffmpeg"
        return HomeKitSecureVideoCameraAccessory(
            hap_driver, hass, config_entry, "127.0.0.1", data_stream_server
        )


@pytest.fixture
def accessory(hass, hap_driver, config_entry, camera_state, data_stream_server):
    hass.states.async_set(MOTION_ENTITY_ID, STATE_OFF, {"device_class": "motion"})
    return _build_accessory(hass, hap_driver, config_entry, data_stream_server)


def _write_camera_active(accessory, value):
    """Write HomeKitCameraActive the way a paired controller would."""
    characteristic = accessory.get_service("CameraOperatingMode").get_characteristic(
        "HomeKitCameraActive"
    )
    characteristic.broker = MagicMock()
    characteristic.client_update_value(value)


def _session_info():
    return {"id": uuid4(), "stream_idx": 0}


async def test_accessory_publishes_a_motion_service(accessory):
    assert accessory.get_service("MotionSensor") is not None


async def test_accessory_advertises_the_camera_entity_as_serial(accessory):
    information = accessory.get_service("AccessoryInformation")
    assert information.get_characteristic("SerialNumber").value == "camera.front_door"


async def test_supported_resolutions_honour_the_options(
    hass, hap_driver, config_entry, camera_state, data_stream_server
):
    hass.config_entries.async_update_entry(
        config_entry, options={"max_width": 640, "max_height": 480, "max_fps": 30}
    )
    accessory = _build_accessory(hass, hap_driver, config_entry, data_stream_server)

    resolutions = accessory._build_options(config_entry.options, "127.0.0.1")["video"][
        "resolutions"
    ]
    assert resolutions
    assert all(width <= 640 and height <= 480 for width, height, _ in resolutions)


async def test_a_frame_rate_cap_limits_resolutions_instead_of_dropping_them(
    hass, hap_driver, config_entry, camera_state, data_stream_server
):
    hass.config_entries.async_update_entry(
        config_entry, options={"max_width": 1920, "max_height": 1080, "max_fps": 20}
    )
    accessory = _build_accessory(hass, hap_driver, config_entry, data_stream_server)

    resolutions = accessory._build_options(config_entry.options, "127.0.0.1")["video"][
        "resolutions"
    ]

    assert len(resolutions) > 1
    assert all(fps <= 20 for _, _, fps in resolutions)


async def test_a_cap_below_every_resolution_still_advertises_one(
    hass, hap_driver, config_entry, camera_state, data_stream_server
):
    hass.config_entries.async_update_entry(
        config_entry, options={"max_width": 160, "max_height": 120, "max_fps": 10}
    )
    accessory = _build_accessory(hass, hap_driver, config_entry, data_stream_server)

    resolutions = accessory._build_options(config_entry.options, "127.0.0.1")["video"][
        "resolutions"
    ]

    assert resolutions
    assert all(fps <= 10 for _, _, fps in resolutions)


async def test_start_stream_spawns_ffmpeg(accessory):
    session = MagicMock()
    session.async_start = AsyncMock(return_value=True)
    session.is_running = True

    with (
        patch(
            f"{MODULE}.camera.async_get_stream_source",
            AsyncMock(return_value="rtsp://camera/stream"),
        ),
        patch(f"{MODULE}.HomeKitSecureVideoLiveStreamSession", return_value=session),
    ):
        assert await accessory.start_stream(_session_info(), STREAM_REQUEST)

    assert accessory.is_streaming


async def test_start_stream_fails_without_a_stream_source(accessory):
    with patch(
        f"{MODULE}.camera.async_get_stream_source", AsyncMock(return_value=None)
    ):
        assert not await accessory.start_stream(_session_info(), STREAM_REQUEST)


async def test_start_stream_fails_when_ffmpeg_dies(accessory):
    session = MagicMock()
    session.async_start = AsyncMock(return_value=False)

    with (
        patch(
            f"{MODULE}.camera.async_get_stream_source",
            AsyncMock(return_value="rtsp://camera/stream"),
        ),
        patch(f"{MODULE}.HomeKitSecureVideoLiveStreamSession", return_value=session),
    ):
        assert not await accessory.start_stream(_session_info(), STREAM_REQUEST)

    assert not accessory.is_streaming


async def test_stop_stream_terminates_the_session(accessory):
    session = MagicMock()
    session.async_start = AsyncMock(return_value=True)
    session.async_stop = AsyncMock(return_value=None)
    session.is_running = True
    session_info = _session_info()

    with (
        patch(
            f"{MODULE}.camera.async_get_stream_source",
            AsyncMock(return_value="rtsp://camera/stream"),
        ),
        patch(f"{MODULE}.HomeKitSecureVideoLiveStreamSession", return_value=session),
    ):
        await accessory.start_stream(session_info, STREAM_REQUEST)

    await accessory.stop_stream(session_info)

    assert session.async_stop.await_count == 1
    assert not accessory.is_streaming


async def test_stop_stream_ignores_an_unknown_session(accessory):
    await accessory.stop_stream(_session_info())


async def test_reconfigure_stream_is_accepted(accessory):
    assert await accessory.reconfigure_stream(_session_info(), STREAM_REQUEST)


async def test_snapshot_comes_from_the_camera_entity(accessory):
    image = MagicMock(content=b"jpeg-bytes")
    with patch(f"{MODULE}.camera.async_get_image", AsyncMock(return_value=image)):
        assert (
            await accessory.async_get_snapshot(
                {"image-width": 640, "image-height": 480}
            )
            == b"jpeg-bytes"
        )


async def test_motion_is_mirrored_onto_the_accessory(hass, accessory):
    await accessory.run()
    detected = accessory.get_service("MotionSensor").get_characteristic(
        "MotionDetected"
    )
    assert detected.value is False

    hass.states.async_set(MOTION_ENTITY_ID, STATE_ON, {"device_class": "motion"})
    await hass.async_block_till_done()

    assert detected.value is True


async def test_stop_releases_the_motion_subscription(hass, accessory):
    await accessory.run()
    await accessory.stop()

    hass.states.async_set(MOTION_ENTITY_ID, STATE_ON, {"device_class": "motion"})
    await hass.async_block_till_done()

    detected = accessory.get_service("MotionSensor").get_characteristic(
        "MotionDetected"
    )
    assert detected.value is False


async def test_status_callback_fires_on_streaming_changes(accessory):
    calls = []
    accessory.set_status_changed_callback(lambda: calls.append(1))
    session = MagicMock()
    session.async_start = AsyncMock(return_value=True)
    session.is_running = True

    with (
        patch(
            f"{MODULE}.camera.async_get_stream_source",
            AsyncMock(return_value="rtsp://camera/stream"),
        ),
        patch(f"{MODULE}.HomeKitSecureVideoLiveStreamSession", return_value=session),
    ):
        await accessory.start_stream(_session_info(), STREAM_REQUEST)

    assert len(calls) == 1


async def test_accessory_publishes_the_data_stream_service(accessory):
    service = accessory.get_service("DataStreamTransportManagement")
    assert service is not None
    assert {
        characteristic.display_name for characteristic in service.characteristics
    } == {
        "Setup Data Stream Transport",
        "Supported Data Stream Transport Configuration",
        "Version",
    }


async def test_accessory_advertises_only_the_homekit_data_stream_transport(accessory):
    from pyhap import tlv

    service = accessory.get_service("DataStreamTransportManagement")
    value = service.get_characteristic(
        "Supported Data Stream Transport Configuration"
    ).value
    configuration = tlv.decode(value, from_base64=True)

    assert tlv.decode(configuration[b"\x01"]) == {b"\x01": b"\x00"}


async def test_the_motion_sensor_reports_whether_it_is_active(accessory):
    status_active = accessory.get_service("MotionSensor").get_characteristic(
        "StatusActive"
    )

    assert status_active.value is True


async def test_turning_the_camera_off_deactivates_the_motion_sensor(accessory):
    _write_camera_active(accessory, 0)

    status_active = accessory.get_service("MotionSensor").get_characteristic(
        "StatusActive"
    )
    assert status_active.value is False


async def test_turning_the_camera_back_on_reactivates_the_motion_sensor(accessory):
    _write_camera_active(accessory, 0)

    _write_camera_active(accessory, 1)

    status_active = accessory.get_service("MotionSensor").get_characteristic(
        "StatusActive"
    )
    assert status_active.value is True


async def test_the_accessory_reports_the_integration_version(
    hass, hap_driver, config_entry, camera_state, data_stream_server
):
    config_entry.runtime_data = MagicMock()
    config_entry.runtime_data.integration.version = "1.2.3"

    accessory = _build_accessory(hass, hap_driver, config_entry, data_stream_server)

    information = accessory.get_service("AccessoryInformation")
    assert information.get_characteristic("FirmwareRevision").value == "1.2.3"


async def test_an_unusable_version_falls_back_to_one_homekit_accepts(
    hass, hap_driver, config_entry, camera_state, data_stream_server
):
    config_entry.runtime_data = MagicMock()
    config_entry.runtime_data.integration.version = "not-a-version"

    accessory = _build_accessory(hass, hap_driver, config_entry, data_stream_server)

    information = accessory.get_service("AccessoryInformation")
    assert information.get_characteristic("FirmwareRevision").value == "1.0.0"


async def test_the_firmware_revision_is_never_empty(accessory):
    information = accessory.get_service("AccessoryInformation")

    assert information.get_characteristic("FirmwareRevision").value


async def test_the_recording_offer_is_narrow(accessory):
    from pyhap import tlv

    service = accessory.get_service("CameraRecordingManagement")
    video = tlv.decode(
        service.get_characteristic("SupportedVideoRecordingConfiguration").value,
        from_base64=True,
    )
    codec = tlv.decode(video[b"\x01"])
    # pyhap concatenates repeated tags: each attribute block is 11 bytes.
    assert len(codec[b"\x03"]) == 2 * 11

    audio = tlv.decode(
        service.get_characteristic("SupportedAudioRecordingConfiguration").value,
        from_base64=True,
    )
    # Two codec blocks are concatenated by pyhap's decoder; the first is 14 bytes.
    first_codec = tlv.decode(audio[b"\x01"][:14])
    parameters = tlv.decode(first_codec[b"\x02"])
    assert parameters[b"\x03"] == bytes([HomeKitSecureVideoAudioSampleRate.KHZ_32])


async def test_the_recording_offer_honours_the_resolution_limit(
    hass, hap_driver, config_entry, camera_state, data_stream_server
):
    from pyhap import tlv

    hass.config_entries.async_update_entry(
        config_entry, options={"max_width": 1280, "max_height": 720, "max_fps": 30}
    )
    accessory = _build_accessory(hass, hap_driver, config_entry, data_stream_server)

    service = accessory.get_service("CameraRecordingManagement")
    video = tlv.decode(
        service.get_characteristic("SupportedVideoRecordingConfiguration").value,
        from_base64=True,
    )
    assert len(tlv.decode(video[b"\x01"])[b"\x03"]) == 11


async def test_the_recording_offer_is_never_empty(
    hass, hap_driver, config_entry, camera_state, data_stream_server
):
    from pyhap import tlv

    hass.config_entries.async_update_entry(
        config_entry, options={"max_width": 320, "max_height": 240, "max_fps": 15}
    )
    accessory = _build_accessory(hass, hap_driver, config_entry, data_stream_server)

    service = accessory.get_service("CameraRecordingManagement")
    video = tlv.decode(
        service.get_characteristic("SupportedVideoRecordingConfiguration").value,
        from_base64=True,
    )
    assert len(tlv.decode(video[b"\x01"])[b"\x03"]) == 11


async def test_the_streaming_audio_offer_is_opus_only(accessory):
    from pyhap import tlv

    from custom_components.homekit_secure_video.accessory.camera_accessory import (
        STREAMING_AUDIO_CODECS,
        STREAMING_AUDIO_SAMPLE_RATES_KHZ,
    )

    value = (
        accessory.get_service("CameraRTPStreamManagement")
        .get_characteristic("SupportedAudioStreamConfiguration")
        .value
    )
    decoded = tlv.decode(value, from_base64=True)

    # AAC-ELD needs libfdk_aac, which the Home Assistant ffmpeg build lacks.
    assert STREAMING_AUDIO_CODECS == ("OPUS",)
    # pyhap concatenates repeated tags; each codec block is 14 bytes.
    assert len(decoded[b"\x01"]) == (
        len(STREAMING_AUDIO_CODECS) * len(STREAMING_AUDIO_SAMPLE_RATES_KHZ) * 14
    )


async def test_the_offer_never_advertises_more_fps_than_the_camera_sends(
    hass, hap_driver, config_entry, camera_state, data_stream_server
):
    """The cap is a ceiling: asking ffmpeg for more only duplicates frames."""
    from pyhap import tlv

    with patch(f"{MODULE}.get_ffmpeg_manager") as ffmpeg_manager:
        ffmpeg_manager.return_value.binary = "ffmpeg"
        accessory = HomeKitSecureVideoCameraAccessory(
            hap_driver,
            hass,
            config_entry,
            "127.0.0.1",
            data_stream_server,
            {**EMPTY_SOURCE, "frame_rate": 20.0},
        )

    video = tlv.decode(
        accessory.get_service("CameraRecordingManagement")
        .get_characteristic("SupportedVideoRecordingConfiguration")
        .value,
        from_base64=True,
    )
    attributes = tlv.decode(video[b"\x01"])[b"\x03"]
    # Each 11-byte attribute block ends with the frame rate.
    assert attributes[10] == 20
    assert attributes[21] == 20


async def test_the_offer_falls_back_when_the_camera_is_unknown(accessory):
    from pyhap import tlv

    video = tlv.decode(
        accessory.get_service("CameraRecordingManagement")
        .get_characteristic("SupportedVideoRecordingConfiguration")
        .value,
        from_base64=True,
    )
    attributes = tlv.decode(video[b"\x01"])[b"\x03"]
    assert attributes[10] == 30


async def test_an_unusable_level_is_reported(
    hass, hap_driver, config_entry, camera_state, data_stream_server, caplog
):
    with patch(f"{MODULE}.get_ffmpeg_manager") as ffmpeg_manager:
        ffmpeg_manager.return_value.binary = "ffmpeg"
        HomeKitSecureVideoCameraAccessory(
            hap_driver,
            hass,
            config_entry,
            "127.0.0.1",
            data_stream_server,
            {**EMPTY_SOURCE, "video_codec": "h264", "video_level": 41},
        )

    assert "level 4.1" in caplog.text


async def test_a_codec_homekit_cannot_use_is_reported(
    hass, hap_driver, config_entry, camera_state, data_stream_server, caplog
):
    with patch(f"{MODULE}.get_ffmpeg_manager") as ffmpeg_manager:
        ffmpeg_manager.return_value.binary = "ffmpeg"
        HomeKitSecureVideoCameraAccessory(
            hap_driver,
            hass,
            config_entry,
            "127.0.0.1",
            data_stream_server,
            {**EMPTY_SOURCE, "video_codec": "hevc"},
        )

    assert "only accepts H.264" in caplog.text


async def test_an_oversized_source_is_reported_as_scaled_when_re_encoding(
    hass, hap_driver, config_entry, camera_state, data_stream_server, caplog
):
    with patch(f"{MODULE}.get_ffmpeg_manager") as ffmpeg_manager:
        ffmpeg_manager.return_value.binary = "ffmpeg"
        HomeKitSecureVideoCameraAccessory(
            hap_driver,
            hass,
            config_entry,
            "127.0.0.1",
            data_stream_server,
            {**EMPTY_SOURCE, "width": 2880, "height": 1616},
        )

    assert "it is scaled down" in caplog.text


async def test_an_oversized_source_is_a_warning_when_copying(
    hass, hap_driver, config_entry, camera_state, data_stream_server, caplog
):
    import logging

    hass.config_entries.async_update_entry(config_entry, options={"reencode": False})

    with (
        caplog.at_level(logging.WARNING),
        patch(f"{MODULE}.get_ffmpeg_manager") as ffmpeg_manager,
    ):
        ffmpeg_manager.return_value.binary = "ffmpeg"
        HomeKitSecureVideoCameraAccessory(
            hap_driver,
            hass,
            config_entry,
            "127.0.0.1",
            data_stream_server,
            {**EMPTY_SOURCE, "width": 2880, "height": 1616},
        )

    assert "did not ask for" in caplog.text
    assert "it is scaled down" not in caplog.text


async def test_the_accessory_publishes_protocol_information(accessory):
    service = accessory.get_service("ProtocolInformation")

    assert service is not None
    assert service.get_characteristic("Version").value == "1.1.0"


async def test_every_stream_management_reports_itself_active(accessory):
    managements = [
        service
        for service in accessory.services
        if service.display_name == "CameraRTPStreamManagement"
    ]

    assert len(managements) == 8
    for service in managements:
        assert service.get_characteristic("Active").value == 1


async def test_the_operating_mode_publishes_its_indicator(accessory):
    operating_mode = accessory.get_service("CameraOperatingMode")

    assert operating_mode.get_characteristic("CameraOperatingModeIndicator").value


async def test_the_accessory_description_includes_every_characteristic(accessory):
    hap = accessory.to_HAP()

    types = {c["type"] for s in hap["services"] for c in s["characteristics"]}
    # Active on the stream managements, and the protocol version.
    assert "B0" in types
    assert "37" in types


async def test_the_accessory_follows_the_reencode_option(
    hass, hap_driver, config_entry, camera_state, data_stream_server
):
    hass.config_entries.async_update_entry(config_entry, options={"reencode": False})

    accessory = _build_accessory(hass, hap_driver, config_entry, data_stream_server)

    session = MagicMock()
    session.async_start = AsyncMock(return_value=True)
    session.is_running = True
    with (
        patch(
            f"{MODULE}.camera.async_get_stream_source",
            AsyncMock(return_value="rtsp://camera/stream"),
        ),
        patch(
            f"{MODULE}.HomeKitSecureVideoLiveStreamSession", return_value=session
        ) as session_class,
        patch(f"{MODULE}.HomeKitSecureVideoLiveStreamCommand") as command_class,
    ):
        await accessory.start_stream(_session_info(), STREAM_REQUEST)

    assert session_class.called
    assert command_class.call_args.kwargs["reencode"] is False


async def test_string_limits_from_an_older_version_still_work(
    hass, hap_driver, config_entry, camera_state, data_stream_server
):
    from pyhap import tlv

    hass.config_entries.async_update_entry(
        config_entry, options={"max_width": "1280", "max_height": "720"}
    )

    accessory = _build_accessory(hass, hap_driver, config_entry, data_stream_server)

    video = tlv.decode(
        accessory.get_service("CameraRecordingManagement")
        .get_characteristic("SupportedVideoRecordingConfiguration")
        .value,
        from_base64=True,
    )
    assert len(tlv.decode(video[b"\x01"])[b"\x03"]) == 11


async def test_always_on_motion_reports_motion_without_a_sensor(
    hass, hap_driver, camera_state, data_stream_server
):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.homekit_secure_video.const import DOMAIN

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front Door",
        version=2,
        data={
            "camera_entity_id": CAMERA_ENTITY_ID,
            "always_on_motion": True,
            "port": 21064,
            "pairing_code": "123-45-678",
            "setup_id": "1AB2",
        },
        unique_id=CAMERA_ENTITY_ID,
    )
    entry.add_to_hass(hass)
    entry.runtime_data = MagicMock()
    accessory = _build_accessory(hass, hap_driver, entry, data_stream_server)

    await accessory.run()

    assert (
        accessory.get_service("MotionSensor").get_characteristic("MotionDetected").value
        is True
    )
    await accessory.stop()


async def test_a_mismatched_source_is_re_encoded_despite_the_option(accessory):
    from custom_components.homekit_secure_video.recording import (
        HomeKitSecureVideoSelectedConfiguration,
    )

    from .test_recording_configuration import _selected_tlv

    configuration = HomeKitSecureVideoSelectedConfiguration.from_tlv(_selected_tlv())
    accessory._reencode = False
    accessory._source_profile = {
        **accessory._source_profile,
        "video_codec": "h264",
        "width": 896,
        "height": 512,
        "frame_rate": 20.0,
    }

    assert accessory._reencode_recording(configuration) is True


async def test_a_matching_source_honours_the_copy_option(accessory):
    from custom_components.homekit_secure_video.recording import (
        HomeKitSecureVideoSelectedConfiguration,
    )

    from .test_recording_configuration import _selected_tlv

    configuration = HomeKitSecureVideoSelectedConfiguration.from_tlv(_selected_tlv())
    accessory._reencode = False
    accessory._source_profile = {
        **accessory._source_profile,
        "video_codec": "h264",
        "width": configuration.width,
        "height": configuration.height,
        "frame_rate": float(configuration.frame_rate),
    }

    assert accessory._reencode_recording(configuration) is False


async def test_a_burst_of_writes_starts_one_recorder(hass, accessory):
    """HomeKit configures the camera with several writes in a row."""
    from custom_components.homekit_secure_video.recording import (
        HomeKitSecureVideoSelectedConfiguration,
    )

    from .test_recording_configuration import _selected_tlv

    management = accessory._recording_management
    management._selected = HomeKitSecureVideoSelectedConfiguration.from_tlv(
        _selected_tlv()
    )
    management.service.get_characteristic("Active").value = 1
    accessory._operating_mode.service.get_characteristic(
        "HomeKitCameraActive"
    ).value = 1

    started = 0

    async def start(*_args, **_kwargs):
        nonlocal started
        started += 1
        # Resolving the source and probing its audio both take a while, which
        # is the window the burst used to slip through.
        await asyncio.sleep(0)
        accessory._recorder.is_running = True
        return True

    accessory._recorder = MagicMock()
    accessory._recorder.is_running = False
    accessory._recorder.async_start = AsyncMock(side_effect=start)
    accessory._recorder.async_stop = AsyncMock()

    with (
        patch(
            f"{MODULE}.camera.async_get_stream_source",
            AsyncMock(return_value="rtsp://camera"),
        ),
        patch(
            f"{MODULE}.async_probe_source", AsyncMock(return_value=dict(EMPTY_PROFILE))
        ),
    ):
        await asyncio.gather(*(accessory._async_sync_recorder() for _ in range(8)))

    assert started == 1


async def test_stop_tears_down_a_recording_in_flight(accessory):
    session = MagicMock()
    session.is_closed = False
    session.async_stop = AsyncMock()
    accessory._recording_management._session = session

    await accessory.stop()

    session.close.assert_called_once()
    session.async_stop.assert_awaited_once()


async def test_a_recorder_that_ends_on_its_own_is_started_again(hass, accessory):
    with (
        patch.object(accessory, "_async_sync_recorder", AsyncMock()) as sync,
        patch.object(accessory, "_next_recorder_restart_delay", return_value=0),
    ):
        accessory._handle_recorder_stream_ended()
        await hass.async_block_till_done()

    sync.assert_awaited_once()


def test_each_recorder_failure_backs_off_further(accessory):
    delays = [accessory._next_recorder_restart_delay() for _ in range(8)]

    assert delays == [5, 10, 20, 40, 80, 160, 300, 300]


async def test_a_healthy_recorder_run_resets_the_backoff(accessory):
    from custom_components.homekit_secure_video.accessory.camera_accessory import (
        HEALTHY_RECORDER_RUN_SECONDS,
    )

    accessory._next_recorder_restart_delay()
    accessory._next_recorder_restart_delay()
    accessory._recorder_started_at = -HEALTHY_RECORDER_RUN_SECONDS

    with patch.object(accessory, "_async_restart_recorder", AsyncMock()):
        accessory._handle_recorder_stream_ended()

    assert accessory._next_recorder_restart_delay() == 5


def _enable_recording(accessory):
    """Enable recording the way a paired controller would."""
    from .test_recording_configuration import _selected_tlv

    service = accessory._recording_management.service
    for name, value in (
        ("Active", 1),
        ("SelectedCameraRecordingConfiguration", _selected_tlv()),
    ):
        characteristic = service.get_characteristic(name)
        characteristic.broker = MagicMock()
        characteristic.client_update_value(value)


def _write_recording_audio(accessory, value):
    """Write RecordingAudioActive the way a paired controller would."""
    characteristic = accessory._recording_management.service.get_characteristic(
        "RecordingAudioActive"
    )
    characteristic.broker = MagicMock()
    characteristic.client_update_value(value)


def _mock_recorder(accessory):
    """Replace the recorder with one that reports itself running once started."""
    recorder = MagicMock()
    recorder.is_running = False

    async def start(*_args, **_kwargs):
        recorder.is_running = True
        return True

    recorder.async_start = AsyncMock(side_effect=start)
    recorder.async_stop = AsyncMock()
    accessory._recorder = recorder
    return recorder


async def test_turning_recording_audio_off_restarts_the_recorder(hass, accessory):
    recorder = _mock_recorder(accessory)

    with (
        patch(
            f"{MODULE}.camera.async_get_stream_source",
            AsyncMock(return_value="rtsp://camera"),
        ),
        patch(
            f"{MODULE}.async_probe_source", AsyncMock(return_value=_PROBED_WITH_AUDIO)
        ),
    ):
        _enable_recording(accessory)
        await hass.async_block_till_done()
        started = recorder.async_start.await_count
        assert started >= 1
        assert recorder.async_start.await_args.args[0].source_has_audio is True

        _write_recording_audio(accessory, 0)
        await hass.async_block_till_done()

    assert recorder.async_start.await_count == started + 1
    assert recorder.async_start.await_args.args[0].source_has_audio is False


async def test_an_unchanged_setting_leaves_the_recorder_alone(hass, accessory):
    recorder = _mock_recorder(accessory)

    with (
        patch(
            f"{MODULE}.camera.async_get_stream_source",
            AsyncMock(return_value="rtsp://camera"),
        ),
        patch(
            f"{MODULE}.async_probe_source", AsyncMock(return_value=_PROBED_WITH_AUDIO)
        ),
    ):
        _enable_recording(accessory)
        await hass.async_block_till_done()
        started = recorder.async_start.await_count

        _write_recording_audio(accessory, 1)
        await hass.async_block_till_done()
        await accessory._async_sync_recorder()

    assert recorder.async_start.await_count == started


async def test_stop_cancels_a_pending_recorder_sync(hass, accessory):
    recorder = _mock_recorder(accessory)
    resolving = asyncio.Event()
    release = asyncio.Event()

    async def stream_source(*_args, **_kwargs):
        resolving.set()
        await release.wait()
        return "rtsp://camera"

    with (
        patch(f"{MODULE}.camera.async_get_stream_source", stream_source),
        patch(
            f"{MODULE}.async_probe_source", AsyncMock(return_value=dict(EMPTY_PROFILE))
        ),
    ):
        _enable_recording(accessory)
        async with asyncio.timeout(5):
            await resolving.wait()

        stopping = asyncio.create_task(accessory.stop())
        await asyncio.sleep(0)
        release.set()
        await asyncio.wait_for(stopping, 5)
        await hass.async_block_till_done()

    recorder.async_start.assert_not_awaited()


async def test_a_stopped_accessory_starts_no_recorder(hass, accessory):
    recorder = _mock_recorder(accessory)
    await accessory.stop()

    with (
        patch(
            f"{MODULE}.camera.async_get_stream_source",
            AsyncMock(return_value="rtsp://camera"),
        ),
        patch(
            f"{MODULE}.async_probe_source", AsyncMock(return_value=dict(EMPTY_PROFILE))
        ),
    ):
        _enable_recording(accessory)
        await hass.async_block_till_done()
        await accessory._async_sync_recorder()

    recorder.async_start.assert_not_awaited()


async def test_a_live_stream_that_ends_frees_its_slot(accessory):
    session = MagicMock()
    session.async_start = AsyncMock(return_value=True)
    session.is_running = True
    session_info = _session_info()

    with (
        patch(
            f"{MODULE}.camera.async_get_stream_source",
            AsyncMock(return_value="rtsp://camera/stream"),
        ),
        patch(f"{MODULE}.HomeKitSecureVideoLiveStreamSession", return_value=session),
    ):
        await accessory.start_stream(session_info, STREAM_REQUEST)

    assert accessory.is_streaming
    session.set_exited_callback.call_args.args[0]()

    assert not accessory.is_streaming
    assert (
        accessory._streaming_status[session_info["stream_idx"]] == STREAMING_AVAILABLE
    )


def _write_operating_mode(accessory, name, value):
    """Write a CameraOperatingMode characteristic the way a controller would."""
    characteristic = accessory.get_service("CameraOperatingMode").get_characteristic(
        name
    )
    characteristic.broker = MagicMock()
    characteristic.client_update_value(value)


async def test_the_camera_mode_follows_what_homekit_selected(accessory):
    assert accessory.homekit_camera_mode == "detect_activity"

    _write_operating_mode(accessory, "EventSnapshotsActive", 0)
    assert accessory.homekit_camera_mode == "stream"

    _enable_recording(accessory)
    assert accessory.homekit_camera_mode == "stream_and_record"

    _write_camera_active(accessory, 0)
    assert accessory.homekit_camera_mode == "off"


async def test_the_recorder_reuses_the_probed_audio_track(hass, accessory):
    recorder = _mock_recorder(accessory)
    accessory._source_profile = {
        "video_codec": "h264",
        "video_level": 41,
        "width": 1920,
        "height": 1080,
        "frame_rate": 20.0,
        "audio_codec": "aac",
        "audio_sample_rate": 16000,
    }

    with (
        patch(
            f"{MODULE}.camera.async_get_stream_source",
            AsyncMock(return_value="rtsp://camera"),
        ),
        patch(f"{MODULE}.async_probe_source", AsyncMock()) as probe,
    ):
        _enable_recording(accessory)
        await hass.async_block_till_done()

    probe.assert_not_awaited()
    assert recorder.async_start.await_args.args[0].source_has_audio is True


async def test_the_recorder_probes_again_when_the_camera_was_unreachable(
    hass, accessory
):
    recorder = _mock_recorder(accessory)
    accessory._source_profile = dict(EMPTY_PROFILE)

    with (
        patch(
            f"{MODULE}.camera.async_get_stream_source",
            AsyncMock(return_value="rtsp://camera"),
        ),
        patch(
            f"{MODULE}.async_probe_source", AsyncMock(return_value=_PROBED_WITH_AUDIO)
        ) as probe,
    ):
        _enable_recording(accessory)
        await hass.async_block_till_done()

    probe.assert_awaited()
    assert recorder.async_start.await_args.args[0].source_has_audio is True


async def test_a_probe_that_failed_is_not_repeated_on_the_next_start(hass, accessory):
    """A camera that is not answering costs fifteen seconds under the lock."""
    recorder = _mock_recorder(accessory)
    accessory._source_profile = dict(EMPTY_PROFILE)

    with (
        patch(
            f"{MODULE}.camera.async_get_stream_source",
            AsyncMock(return_value="rtsp://camera"),
        ),
        patch(
            f"{MODULE}.async_probe_source", AsyncMock(return_value=dict(EMPTY_PROFILE))
        ) as probe,
    ):
        _enable_recording(accessory)
        await hass.async_block_till_done()
        recorder.is_running = False
        await accessory._async_sync_recorder()

    assert probe.await_count == 1
    assert recorder.async_start.await_count == 2


async def test_a_probe_that_answered_is_remembered(hass, accessory):
    recorder = _mock_recorder(accessory)
    accessory._source_profile = dict(EMPTY_PROFILE)

    with (
        patch(
            f"{MODULE}.camera.async_get_stream_source",
            AsyncMock(return_value="rtsp://camera"),
        ),
        patch(
            f"{MODULE}.async_probe_source", AsyncMock(return_value=_PROBED_WITH_AUDIO)
        ) as probe,
    ):
        _enable_recording(accessory)
        await hass.async_block_till_done()
        recorder.is_running = False
        await accessory._async_sync_recorder()

    assert probe.await_count == 1
    assert accessory._source_profile["audio_codec"] == "aac"


async def test_a_recorder_that_keeps_failing_is_reported_once(accessory):
    from custom_components.homekit_secure_video.accessory.camera_accessory import (
        UNHEALTHY_RECORDER_RESTARTS,
    )

    reported: list[bool] = []
    accessory.set_recorder_health_callback(
        lambda: reported.append(accessory.is_recorder_unhealthy)
    )

    accessory._recorder_restart_failures = UNHEALTHY_RECORDER_RESTARTS
    accessory._report_recorder_health()
    accessory._report_recorder_health()

    assert reported == [True]
    assert accessory.is_recorder_unhealthy

    accessory._recorder_restart_failures = 0
    accessory._report_recorder_health()

    assert reported == [True, False]
    assert not accessory.is_recorder_unhealthy


async def test_a_recorder_that_stays_up_counts_as_recovered(accessory):
    from custom_components.homekit_secure_video.accessory.camera_accessory import (
        UNHEALTHY_RECORDER_RESTARTS,
    )

    _mock_recorder(accessory).is_running = True
    accessory._recorder_restart_failures = UNHEALTHY_RECORDER_RESTARTS
    accessory._report_recorder_health()
    accessory._recorder_started_at = 123.0
    reported: list[bool] = []
    accessory.set_recorder_health_callback(
        lambda: reported.append(accessory.is_recorder_unhealthy)
    )

    with patch(f"{MODULE}.HEALTHY_RECORDER_RUN_SECONDS", 0):
        await accessory._async_confirm_recorder_health(123.0)

    assert accessory._recorder_restart_failures == 0
    assert reported == [False]


async def test_a_run_that_was_replaced_does_not_count_as_recovered(accessory):
    from custom_components.homekit_secure_video.accessory.camera_accessory import (
        UNHEALTHY_RECORDER_RESTARTS,
    )

    _mock_recorder(accessory).is_running = True
    accessory._recorder_restart_failures = UNHEALTHY_RECORDER_RESTARTS
    accessory._report_recorder_health()
    accessory._recorder_started_at = 456.0

    with patch(f"{MODULE}.HEALTHY_RECORDER_RUN_SECONDS", 0):
        await accessory._async_confirm_recorder_health(123.0)

    assert accessory._recorder_restart_failures == UNHEALTHY_RECORDER_RESTARTS
    assert accessory.is_recorder_unhealthy


async def test_a_storm_of_state_changes_queues_one_synchronisation(accessory):
    """A hub retrying a recording rewrites the configuration thousands of times."""
    with patch.object(accessory, "_async_sync_recorder", AsyncMock()):
        for _ in range(1000):
            accessory._handle_recording_state_changed()

        assert len(accessory._recorder_tasks) == 1

        await asyncio.gather(*tuple(accessory._recorder_tasks))


async def test_a_synchronisation_can_be_asked_for_again_once_it_ran(accessory):
    accessory._recorder = MagicMock()
    accessory._recorder.is_running = False
    accessory._recorder.async_stop = AsyncMock()

    accessory._handle_recording_state_changed()
    await asyncio.gather(*tuple(accessory._recorder_tasks))
    assert accessory._recorder.async_stop.await_count == 1

    accessory._handle_recording_state_changed()
    await asyncio.gather(*tuple(accessory._recorder_tasks))
    assert accessory._recorder.async_stop.await_count == 2
