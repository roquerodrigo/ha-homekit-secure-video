from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.homekit_secure_video.accessory.camera_operating_mode import (
    HomeKitSecureVideoCameraOperatingModeService,
)
from custom_components.homekit_secure_video.accessory.recording_management import (
    HomeKitSecureVideoRecordingManagementService,
)
from custom_components.homekit_secure_video.datastream import (
    HomeKitSecureVideoDataStreamCloseReason,
    HomeKitSecureVideoDataStreamMessage,
    HomeKitSecureVideoDataStreamMessageType,
    HomeKitSecureVideoDataStreamStatus,
)
from custom_components.homekit_secure_video.recording import (
    HomeKitSecureVideoAudioSampleRate,
    HomeKitSecureVideoEventTrigger,
    HomeKitSecureVideoRecordingAudioCodec,
    HomeKitSecureVideoSupportedConfiguration,
)

from .test_recording_configuration import _selected_tlv

SUPPORTED = HomeKitSecureVideoSupportedConfiguration(
    prebuffer_milliseconds=4000,
    fragment_milliseconds=4000,
    event_triggers=(HomeKitSecureVideoEventTrigger.MOTION,),
    resolutions=((1920, 1080, 30),),
    video_profiles=(0, 1, 2),
    video_levels=(0, 1, 2),
    audio_codecs=(HomeKitSecureVideoRecordingAudioCodec.AAC_LC,),
    audio_sample_rates=(HomeKitSecureVideoAudioSampleRate.KHZ_16,),
)


def _open_message(
    stream_id=42,
    request_id=7,
    target="controller",
    stream_type="ipcamera.recording",
):
    return HomeKitSecureVideoDataStreamMessage(
        message_type=HomeKitSecureVideoDataStreamMessageType.REQUEST,
        protocol="dataSend",
        topic="open",
        payload={"streamId": stream_id, "target": target, "type": stream_type},
        identifier=request_id,
    )


@pytest.fixture
def recorder():
    recorder = MagicMock()
    recorder.is_running = True
    recorder.initialization_segment = b"init"
    recorder.prebuffered_fragments = ()
    return recorder


@pytest.fixture
def operating_mode():
    return HomeKitSecureVideoCameraOperatingModeService(lambda: None)


@pytest.fixture
def data_stream_server():
    return MagicMock()


@pytest.fixture
def management(recorder, operating_mode, data_stream_server):
    return HomeKitSecureVideoRecordingManagementService(
        SUPPORTED, recorder, operating_mode, data_stream_server, lambda: None
    )


def _write(service, name, value):
    """Write a characteristic the way a paired controller would."""
    characteristic = service.get_characteristic(name)
    # A live accessory is the broker that fans notifications out; these
    # services are built standalone, so one is stood in for.
    characteristic.broker = MagicMock()
    characteristic.client_update_value(value)


def _enable(management):
    _write(management.service, "Active", 1)
    _write(management.service, "SelectedCameraRecordingConfiguration", _selected_tlv())


def test_the_service_publishes_the_supported_configurations(management):
    names = {c.display_name for c in management.service.characteristics}

    assert names == {
        "Active",
        "RecordingAudioActive",
        "SupportedCameraRecordingConfiguration",
        "SupportedVideoRecordingConfiguration",
        "SupportedAudioRecordingConfiguration",
        "SelectedCameraRecordingConfiguration",
    }


def test_recording_starts_disabled(management):
    assert not management.is_recording_enabled
    assert management.selected_configuration is None


def test_homekit_can_enable_recording(management):
    _enable(management)

    assert management.is_recording_enabled
    assert management.selected_configuration is not None
    assert management.selected_configuration.width == 1920


def test_a_malformed_configuration_is_ignored(management):
    _write(management.service, "SelectedCameraRecordingConfiguration", "not-a-tlv")

    assert management.selected_configuration is None


async def test_an_open_request_starts_a_recording(management, data_stream_server):
    _enable(management)
    connection = MagicMock()

    management._handle_open(connection, _open_message())

    assert management.is_recording_in_flight
    management.abort_recording()


def test_an_open_request_is_rejected_while_recording_is_off(management):
    connection = MagicMock()

    management._handle_open(connection, _open_message())

    assert not management.is_recording_in_flight
    status = connection.send_response.call_args.args[3]
    assert status == HomeKitSecureVideoDataStreamStatus.PROTOCOL_SPECIFIC_ERROR
    assert connection.send_response.call_args.args[4]["status"] == int(
        HomeKitSecureVideoDataStreamCloseReason.NOT_ALLOWED
    )


def test_an_open_request_for_another_target_is_rejected(management):
    _enable(management)
    connection = MagicMock()

    management._handle_open(connection, _open_message(target="accessory"))

    assert connection.send_response.call_args.args[4]["status"] == int(
        HomeKitSecureVideoDataStreamCloseReason.UNEXPECTED_FAILURE
    )


def test_an_open_request_without_a_configuration_is_rejected(management):
    _write(management.service, "Active", 1)
    connection = MagicMock()

    management._handle_open(connection, _open_message())

    assert connection.send_response.call_args.args[4]["status"] == int(
        HomeKitSecureVideoDataStreamCloseReason.INVALID_CONFIGURATION
    )


async def test_a_second_open_request_is_rejected_as_busy(management):
    _enable(management)
    first = MagicMock()
    management._handle_open(first, _open_message())

    second = MagicMock()
    management._handle_open(second, _open_message(stream_id=43, request_id=8))

    assert second.send_response.call_args.args[4]["status"] == int(
        HomeKitSecureVideoDataStreamCloseReason.BUSY
    )
    management.abort_recording()


def test_an_open_request_is_rejected_while_the_camera_is_off(
    management, operating_mode
):
    _enable(management)
    _write(operating_mode.service, "HomeKitCameraActive", 0)
    connection = MagicMock()

    management._handle_open(connection, _open_message())

    assert connection.send_response.call_args.args[4]["status"] == int(
        HomeKitSecureVideoDataStreamCloseReason.NOT_ALLOWED
    )


async def test_turning_recording_off_aborts_the_recording_in_flight(management):
    _enable(management)
    management._handle_open(MagicMock(), _open_message())

    _write(management.service, "Active", 0)

    assert not management.is_recording_in_flight


async def test_the_hub_acknowledging_ends_the_recording(management):
    _enable(management)
    management._handle_open(MagicMock(), _open_message())

    management._handle_acknowledgement(
        MagicMock(),
        HomeKitSecureVideoDataStreamMessage(
            message_type=HomeKitSecureVideoDataStreamMessageType.EVENT,
            protocol="dataSend",
            topic="ack",
            payload={"streamId": 42, "endOfStream": True},
        ),
    )

    assert not management.is_recording_in_flight


async def test_a_close_for_another_stream_is_ignored(management):
    _enable(management)
    management._handle_open(MagicMock(), _open_message())

    management._handle_close(
        MagicMock(),
        HomeKitSecureVideoDataStreamMessage(
            message_type=HomeKitSecureVideoDataStreamMessageType.EVENT,
            protocol="dataSend",
            topic="close",
            payload={"streamId": 99, "reason": 0},
        ),
    )

    assert management.is_recording_in_flight
    management.abort_recording()


def test_the_operating_mode_starts_fully_enabled(operating_mode):
    assert operating_mode.is_camera_active
    assert operating_mode.are_event_snapshots_active


def test_turning_the_camera_off_fires_the_callback():
    calls: list[bool] = []
    service = HomeKitSecureVideoCameraOperatingModeService(lambda: calls.append(True))

    _write(service.service, "HomeKitCameraActive", 0)

    assert calls == [True]
    assert not service.is_camera_active


def test_a_configuration_with_an_unknown_codec_leaves_the_camera_working(management):
    _write(management.service, "Active", 1)

    _write(
        management.service,
        "SelectedCameraRecordingConfiguration",
        _selected_tlv(audio_codec=9),
    )

    assert management.selected_configuration is None
    assert management.is_recording_enabled


def test_a_broken_listener_does_not_fail_the_write(recorder, operating_mode):
    def explode() -> None:
        message = "listener is broken"
        raise RuntimeError(message)

    management = HomeKitSecureVideoRecordingManagementService(
        SUPPORTED, recorder, operating_mode, MagicMock(), explode
    )

    _write(management.service, "Active", 1)

    assert management.is_recording_enabled


def test_reading_the_configuration_before_one_is_chosen_fails(management):
    from custom_components.homekit_secure_video.exceptions import (
        HomeKitSecureVideoRecordingError,
    )

    characteristic = management.service.get_characteristic(
        "SelectedCameraRecordingConfiguration"
    )

    with pytest.raises(HomeKitSecureVideoRecordingError):
        characteristic.get_value()


def test_reading_the_configuration_returns_what_homekit_wrote(management):
    _enable(management)
    characteristic = management.service.get_characteristic(
        "SelectedCameraRecordingConfiguration"
    )

    assert characteristic.get_value() == _selected_tlv()


def test_a_rejected_configuration_is_not_readable(management):
    _write(management.service, "SelectedCameraRecordingConfiguration", "not-a-tlv")
    characteristic = management.service.get_characteristic(
        "SelectedCameraRecordingConfiguration"
    )

    from custom_components.homekit_secure_video.exceptions import (
        HomeKitSecureVideoRecordingError,
    )

    with pytest.raises(HomeKitSecureVideoRecordingError):
        characteristic.get_value()


def _described(management):
    """Return the characteristic ready to describe itself, as an accessory would."""
    characteristic = management.service.get_characteristic(
        "SelectedCameraRecordingConfiguration"
    )
    characteristic.broker = MagicMock()
    characteristic.broker.iid_manager.get_iid = MagicMock(return_value=35)
    return characteristic


def test_the_accessory_description_never_fails(management):
    representation = _described(management).to_HAP()

    assert representation["value"] == ""


def test_the_accessory_description_carries_the_negotiated_value(management):
    _enable(management)

    assert _described(management).to_HAP()["value"] == _selected_tlv()


def test_the_accessory_description_can_omit_the_value(management):
    assert "value" not in _described(management).to_HAP(include_value=False)


def test_diagnostics_describe_an_idle_service(management, recorder):
    recorder.diagnostics = {"running": False}

    diagnostics = management.diagnostics

    assert diagnostics["enabled"] is False
    assert diagnostics["in_flight"] is False
    assert diagnostics["recordings_started"] == 0
    assert diagnostics["selected_configuration"] is None
    assert diagnostics["last_session"] is None
    assert diagnostics["recorder"] == {"running": False}


def test_diagnostics_describe_the_negotiated_configuration(management, recorder):
    recorder.diagnostics = {}
    _enable(management)

    negotiated = management.diagnostics["selected_configuration"]

    assert negotiated is not None
    assert negotiated["width"] == 1920
    assert negotiated["audio_codec"] == "AAC_LC"


async def test_diagnostics_count_recordings_and_keep_the_last_statistics(
    management, recorder
):
    recorder.diagnostics = {}
    _enable(management)

    management._handle_open(MagicMock(), _open_message())
    assert management.diagnostics["recordings_started"] == 1

    management.abort_recording()

    assert management.diagnostics["in_flight"] is False
    assert management.diagnostics["last_session"] == {
        "fragments_sent": 0,
        "bytes_sent": 0,
    }
