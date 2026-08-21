from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.homekit_secure_video.streaming import (
    HomeKitSecureVideoLiveStreamCommand,
    HomeKitSecureVideoLiveStreamSession,
)

STREAM_REQUEST = {
    "address": "192.168.1.10",
    "v_port": 50000,
    "v_srtp_key": "c3JydHBrZXk=",
    "v_ssrc": 12345,
    "v_max_bitrate": 299,
}


@pytest.fixture
def command():
    return HomeKitSecureVideoLiveStreamCommand(
        input_source="rtsp://camera/stream", request=STREAM_REQUEST
    )


def test_command_reads_the_camera_over_tcp(command):
    arguments = command.arguments
    assert arguments[arguments.index("-i") + 1] == "rtsp://camera/stream"
    assert arguments[arguments.index("-rtsp_transport") + 1] == "tcp"


def test_command_encodes_to_the_negotiated_parameters(command):
    arguments = command.arguments
    assert arguments[arguments.index("-c:v") + 1] == "libx264"
    assert arguments[arguments.index("-profile:v") + 1] == "main"
    assert arguments[arguments.index("-level:v") + 1] == "4.0"
    assert "-an" in arguments


def test_command_encrypts_with_the_negotiated_key(command):
    arguments = command.arguments
    assert arguments[arguments.index("-srtp_out_params") + 1] == "c3JydHBrZXk="
    assert arguments[arguments.index("-ssrc") + 1] == "12345"


def test_command_targets_the_controller(command):
    destination = command.arguments[-1]
    assert destination.startswith("srtp://192.168.1.10:50000?")
    assert "localrtpport=50000" in destination


def test_command_sizes_the_buffer_from_the_bitrate(command):
    arguments = command.arguments
    assert arguments[arguments.index("-bufsize") + 1] == "1196k"


async def test_session_reports_a_running_process(command):
    process = MagicMock(returncode=None)
    with patch(
        "asyncio.create_subprocess_exec", AsyncMock(return_value=process)
    ) as spawn:
        session = HomeKitSecureVideoLiveStreamSession("ffmpeg", command)
        assert await session.async_start()

    assert spawn.call_args.args[0] == "ffmpeg"
    assert session.is_running


async def test_session_reports_a_process_that_died_immediately(command):
    process = MagicMock(returncode=1)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
        session = HomeKitSecureVideoLiveStreamSession("ffmpeg", command)
        assert not await session.async_start()


async def test_session_survives_a_missing_binary(command):
    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=OSError)):
        session = HomeKitSecureVideoLiveStreamSession("missing-ffmpeg", command)
        assert not await session.async_start()


async def test_session_terminates_the_process(command):
    process = MagicMock(returncode=None)
    process.wait = AsyncMock(return_value=0)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
        session = HomeKitSecureVideoLiveStreamSession("ffmpeg", command)
        await session.async_start()

    await session.async_stop()

    assert process.terminate.call_count == 1
    assert not session.is_running


async def test_session_kills_a_process_that_ignores_terminate(command):
    process = MagicMock(returncode=None)
    process.wait = AsyncMock(side_effect=[TimeoutError, 0])
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
        session = HomeKitSecureVideoLiveStreamSession("ffmpeg", command)
        await session.async_start()

    await session.async_stop()

    assert process.kill.call_count == 1


async def test_stopping_a_session_twice_is_harmless(command):
    process = MagicMock(returncode=None)
    process.wait = AsyncMock(return_value=0)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
        session = HomeKitSecureVideoLiveStreamSession("ffmpeg", command)
        await session.async_start()

    await session.async_stop()
    await session.async_stop()

    assert process.terminate.call_count == 1


def test_command_forces_tcp_only_for_rtsp():
    rtsp = HomeKitSecureVideoLiveStreamCommand(
        input_source="rtsp://camera/stream", request=STREAM_REQUEST
    )
    http = HomeKitSecureVideoLiveStreamCommand(
        input_source="http://camera/stream.m3u8", request=STREAM_REQUEST
    )

    assert "-rtsp_transport" in rtsp.arguments
    assert "-rtsp_transport" not in http.arguments


def test_the_negotiated_profile_and_level_are_used():
    command = HomeKitSecureVideoLiveStreamCommand(
        input_source="rtsp://camera/stream",
        request={**STREAM_REQUEST, "v_profile_id": b"\x02", "v_level": b"\x00"},
    )

    arguments = command.arguments
    assert arguments[arguments.index("-profile:v") + 1] == "high"
    assert arguments[arguments.index("-level:v") + 1] == "3.1"


def test_an_unknown_profile_falls_back_to_one_homekit_accepts():
    command = HomeKitSecureVideoLiveStreamCommand(
        input_source="rtsp://camera/stream",
        request={**STREAM_REQUEST, "v_profile_id": b"\x09", "v_level": b"\x09"},
    )

    arguments = command.arguments
    assert arguments[arguments.index("-profile:v") + 1] == "main"
    assert arguments[arguments.index("-level:v") + 1] == "4.0"


def test_the_stream_is_scaled_to_the_negotiated_size():
    command = HomeKitSecureVideoLiveStreamCommand(
        input_source="rtsp://camera/stream",
        request={**STREAM_REQUEST, "width": 1280, "height": 720, "fps": 24},
    )

    arguments = command.arguments
    assert "scale=w=1280:h=720" in arguments[arguments.index("-vf") + 1]
    assert arguments[arguments.index("-r") + 1] == "24"


def test_a_stream_without_a_size_is_not_scaled(command):
    assert "-vf" not in command.arguments


def test_copying_passes_the_camera_stream_through():
    command = HomeKitSecureVideoLiveStreamCommand(
        input_source="rtsp://camera/stream", request=STREAM_REQUEST, reencode=False
    )
    arguments = command.arguments

    assert arguments[arguments.index("-c:v") + 1] == "copy"
    assert "libx264" not in arguments
    assert "-vf" not in arguments
    assert arguments[-1].startswith("srtp://")


def test_copying_still_corrects_an_over_spec_level():
    command = HomeKitSecureVideoLiveStreamCommand(
        input_source="rtsp://camera/stream",
        request=STREAM_REQUEST,
        reencode=False,
        source_level=41,
    )
    arguments = command.arguments

    assert arguments[arguments.index("-bsf:v") + 1] == "h264_metadata=level=4"


def test_copying_leaves_an_accepted_level_alone():
    command = HomeKitSecureVideoLiveStreamCommand(
        input_source="rtsp://camera/stream",
        request=STREAM_REQUEST,
        reencode=False,
        source_level=31,
    )

    assert "-bsf:v" not in command.arguments


AUDIO_REQUEST = {
    **STREAM_REQUEST,
    "a_port": 50002,
    "a_srtp_key": "YXVkaW9rZXk=",
    "a_ssrc": 54321,
    "a_codec": b"\x03",
    "a_channel": 1,
    "a_sample_rate": 24,
    "a_packet_time": 20,
    "a_max_bitrate": 32,
    "a_payload_type": b"n",
}


def _audio_output(arguments):
    """Return the arguments after the video destination — the audio output."""
    video_destination = next(
        index
        for index, argument in enumerate(arguments)
        if argument.startswith("srtp://192.168.1.10:50000")
    )
    return arguments[video_destination + 1 :]


def _audio_command(request=None, *, source_has_audio=True):
    return HomeKitSecureVideoLiveStreamCommand(
        input_source="rtsp://camera/stream",
        request=request if request is not None else AUDIO_REQUEST,
        source_has_audio=source_has_audio,
    )


def test_audio_is_encoded_to_what_homekit_negotiated():
    arguments = _audio_command().arguments

    assert arguments[arguments.index("-c:a") + 1] == "libopus"
    assert arguments[arguments.index("-ar") + 1] == "24000"
    assert arguments[arguments.index("-b:a") + 1] == "32k"
    assert arguments[arguments.index("-frame_duration") + 1] == "20"
    assert arguments[arguments.index("-ac") + 1] == "1"


def test_audio_goes_to_its_own_encrypted_port():
    audio = _audio_output(_audio_command().arguments)

    assert audio[-1].startswith("srtp://192.168.1.10:50002")
    assert audio[audio.index("-srtp_out_params") + 1] == "YXVkaW9rZXk="
    assert audio[audio.index("-ssrc") + 1] == "54321"


def test_audio_uses_the_negotiated_payload_type():
    arguments = _audio_command().arguments

    assert arguments[arguments.index("-payload_type") + 1] == "99"
    audio = _audio_output(arguments)
    assert audio[audio.index("-payload_type") + 1] == "110"


def test_a_camera_without_audio_gets_no_audio_output():
    arguments = _audio_command(source_has_audio=False).arguments

    assert "-c:a" not in arguments
    assert "50002" not in " ".join(arguments)


def test_audio_is_skipped_when_homekit_negotiated_another_codec():
    arguments = _audio_command({**AUDIO_REQUEST, "a_codec": b"\x02"}).arguments

    assert "-c:a" not in arguments


def test_audio_is_skipped_when_homekit_negotiated_none():
    arguments = _audio_command(STREAM_REQUEST).arguments

    assert "-c:a" not in arguments
