from __future__ import annotations

import asyncio
import json
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.homekit_secure_video.exceptions import (
    HomeKitSecureVideoRecordingError,
)
from custom_components.homekit_secure_video.recording import (
    HomeKitSecureVideoPrebuffer,
    HomeKitSecureVideoRecorder,
    HomeKitSecureVideoRecordingCommand,
    HomeKitSecureVideoSelectedConfiguration,
    async_probe_source,
    async_source_has_audio,
)
from custom_components.homekit_secure_video.recording.fragmented_mp4 import (
    read_segments,
)

from .test_recording_configuration import _selected_tlv

CONFIGURATION = HomeKitSecureVideoSelectedConfiguration.from_tlv(_selected_tlv())


def _box(box_type: bytes, body: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(body)) + box_type + body


def _reader(payload: bytes, *, at_end: bool = True) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(payload)
    if at_end:
        reader.feed_eof()
    return reader


async def _collect(payload: bytes) -> list[tuple[bool, bytes]]:
    return [segment async for segment in read_segments(_reader(payload))]


async def test_initialization_segment_is_ftyp_plus_moov():
    segments = await _collect(_box(b"ftyp", b"iso5") + _box(b"moov", b"header"))

    assert len(segments) == 1
    is_initialization, payload = segments[0]
    assert is_initialization
    assert payload == _box(b"ftyp", b"iso5") + _box(b"moov", b"header")


async def test_each_moof_mdat_pair_is_one_fragment():
    stream = (
        _box(b"ftyp")
        + _box(b"moov")
        + _box(b"moof", b"a")
        + _box(b"mdat", b"video")
        + _box(b"moof", b"b")
        + _box(b"mdat", b"more")
    )

    segments = await _collect(stream)

    assert [is_init for is_init, _ in segments] == [True, False, False]
    assert segments[1][1] == _box(b"moof", b"a") + _box(b"mdat", b"video")


async def test_a_large_box_uses_the_64_bit_size():
    body = b"x" * 20
    large = struct.pack(">I", 1) + b"mdat" + struct.pack(">Q", 16 + len(body)) + body
    stream = _box(b"moof") + large

    segments = await _collect(stream)

    assert segments[0][1].endswith(body)


async def test_a_truncated_box_ends_the_stream():
    assert await _collect(_box(b"moof") + b"\x00\x00") == []


async def test_a_negative_box_size_is_rejected():
    with pytest.raises(HomeKitSecureVideoRecordingError, match="declares"):
        await _collect(struct.pack(">I", 4) + b"moof")


def test_prebuffer_sizes_itself_from_the_negotiated_length():
    prebuffer = HomeKitSecureVideoPrebuffer(8000, 4000)

    assert prebuffer.capacity == 5


def test_prebuffer_drops_the_oldest_fragment_when_full():
    prebuffer = HomeKitSecureVideoPrebuffer(4000, 4000)
    for index in range(10):
        prebuffer.append(bytes([index]))

    assert len(prebuffer.fragments) == prebuffer.capacity
    assert prebuffer.fragments[-1] == b"\x09"


def test_prebuffer_clears():
    prebuffer = HomeKitSecureVideoPrebuffer(4000, 4000)
    prebuffer.append(b"x")
    prebuffer.clear()

    assert prebuffer.fragments == ()


def test_recording_command_encodes_video_and_audio():
    command = HomeKitSecureVideoRecordingCommand(
        input_source="rtsp://camera/stream",
        configuration=CONFIGURATION,
        source_has_audio=True,
    )
    arguments = command.arguments

    assert arguments[arguments.index("-c:v") + 1] == "libx264"
    assert arguments[arguments.index("-profile:v") + 1] == "high"
    assert arguments[arguments.index("-level:v") + 1] == "4.0"
    assert arguments[arguments.index("-c:a") + 1] == "aac"
    assert arguments[arguments.index("-map") + 1] == "0:v:0"
    assert "0:a:0" in arguments
    assert arguments[-1] == "pipe:1"


def test_recording_command_forces_keyframes_at_the_fragment_length():
    command = HomeKitSecureVideoRecordingCommand(
        input_source="rtsp://camera/stream",
        configuration=CONFIGURATION,
        source_has_audio=False,
    )
    arguments = command.arguments

    assert arguments[arguments.index("-g") + 1] == "120"
    assert (
        arguments[arguments.index("-force_key_frames") + 1] == "expr:gte(t,n_forced*4)"
    )


def test_recording_command_scales_to_the_negotiated_size():
    command = HomeKitSecureVideoRecordingCommand(
        input_source="rtsp://camera/stream",
        configuration=CONFIGURATION,
        source_has_audio=False,
    )

    assert (
        "scale=w=1920:h=1080" in command.arguments[command.arguments.index("-vf") + 1]
    )


def test_recording_command_generates_silence_without_source_audio():
    command = HomeKitSecureVideoRecordingCommand(
        input_source="rtsp://camera/stream",
        configuration=CONFIGURATION,
        source_has_audio=False,
    )
    arguments = command.arguments

    assert "anullsrc=channel_layout=mono:sample_rate=16000" in arguments
    assert "1:a:0" in arguments


def test_recording_command_fragments_on_keyframes():
    command = HomeKitSecureVideoRecordingCommand(
        input_source="rtsp://camera/stream",
        configuration=CONFIGURATION,
        source_has_audio=False,
    )
    arguments = command.arguments

    assert (
        arguments[arguments.index("-movflags") + 1]
        == "frag_keyframe+empty_moov+default_base_moof"
    )
    assert arguments[arguments.index("-frag_duration") + 1] == "4000000"


def test_recording_command_uses_aac_eld_when_negotiated():
    configuration = HomeKitSecureVideoSelectedConfiguration.from_tlv(
        _selected_tlv(audio_codec=1)
    )
    command = HomeKitSecureVideoRecordingCommand(
        input_source="rtsp://camera/stream",
        configuration=configuration,
        source_has_audio=False,
    )

    assert command.arguments[command.arguments.index("-profile:a") + 1] == "aac_eld"


PROBE_OUTPUT = json.dumps(
    {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "profile": "High",
                "level": 51,
                "width": 2560,
                "height": 1440,
                "avg_frame_rate": "20/1",
            },
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000"},
        ]
    }
).encode()


def _probe_process(stdout=PROBE_OUTPUT):
    process = MagicMock()
    process.communicate = AsyncMock(return_value=(stdout, b""))
    return process


async def test_the_probe_reports_what_the_camera_sends():
    with patch(
        "asyncio.create_subprocess_exec", AsyncMock(return_value=_probe_process())
    ):
        profile = await async_probe_source("/usr/bin/ffmpeg", "rtsp://camera/stream")

    assert profile["video_codec"] == "h264"
    assert profile["video_profile"] == "High"
    assert profile["video_level"] == 51
    assert profile["width"] == 2560
    assert profile["height"] == 1440
    assert profile["frame_rate"] == 20.0
    assert profile["audio_codec"] == "aac"
    assert profile["audio_sample_rate"] == 48000


async def test_the_probe_survives_unreadable_output():
    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(return_value=_probe_process(b"not json")),
    ):
        profile = await async_probe_source("/usr/bin/ffmpeg", "rtsp://camera")

    assert profile["video_codec"] is None


async def test_a_fractional_frame_rate_is_rounded():
    stdout = json.dumps(
        {"streams": [{"codec_type": "video", "avg_frame_rate": "30000/1001"}]}
    ).encode()
    with patch(
        "asyncio.create_subprocess_exec", AsyncMock(return_value=_probe_process(stdout))
    ):
        profile = await async_probe_source("/usr/bin/ffmpeg", "rtsp://camera")

    assert profile["frame_rate"] == 29.97


async def test_probe_reports_audio_when_ffprobe_finds_it():
    with patch(
        "asyncio.create_subprocess_exec", AsyncMock(return_value=_probe_process())
    ):
        assert await async_source_has_audio("/usr/bin/ffmpeg", "rtsp://camera/stream")


@pytest.mark.parametrize(
    ("ffmpeg_binary", "expected"),
    [
        ("/usr/bin/ffmpeg", "/usr/bin/ffprobe"),
        ("/usr/lib/jellyfin-ffmpeg/ffmpeg", "/usr/lib/jellyfin-ffmpeg/ffprobe"),
        ("ffmpeg", "ffprobe"),
    ],
)
async def test_the_probe_runs_the_ffprobe_beside_the_configured_ffmpeg(
    ffmpeg_binary, expected
):
    create_subprocess = AsyncMock(return_value=_probe_process())
    with patch("asyncio.create_subprocess_exec", create_subprocess):
        await async_probe_source(ffmpeg_binary, "rtsp://camera/stream")

    assert create_subprocess.call_args.args[0] == expected


async def test_probe_reports_no_audio_on_an_empty_answer():
    stdout = json.dumps({"streams": [{"codec_type": "video"}]}).encode()
    with patch(
        "asyncio.create_subprocess_exec", AsyncMock(return_value=_probe_process(stdout))
    ):
        assert not await async_source_has_audio("/usr/bin/ffmpeg", "rtsp://camera")


async def test_probe_survives_a_missing_ffprobe():
    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=OSError)):
        assert not await async_source_has_audio("/usr/bin/ffmpeg", "rtsp://camera")


async def test_probe_gives_up_when_it_times_out():
    process = MagicMock()
    process.communicate = AsyncMock(side_effect=TimeoutError)
    process.wait = AsyncMock(return_value=0)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
        assert not await async_source_has_audio("/usr/bin/ffmpeg", "rtsp://camera")
    assert process.kill.call_count == 1


@pytest.fixture
def recorder():
    return HomeKitSecureVideoRecorder("ffmpeg")


def _process(stream: bytes, *, still_running: bool = True) -> MagicMock:
    """Stand in for ffmpeg; a still running one has not closed its stdout."""
    process = MagicMock(returncode=None)
    process.stdout = _reader(stream, at_end=not still_running)
    process.wait = AsyncMock(return_value=0)
    return process


async def test_recorder_fills_the_prebuffer(recorder):
    stream = (
        _box(b"ftyp")
        + _box(b"moov")
        + _box(b"moof", b"a")
        + _box(b"mdat", b"one")
        + _box(b"moof", b"b")
        + _box(b"mdat", b"two")
    )
    command = HomeKitSecureVideoRecordingCommand(
        input_source="rtsp://camera",
        configuration=CONFIGURATION,
        source_has_audio=False,
    )

    with patch(
        "asyncio.create_subprocess_exec", AsyncMock(return_value=_process(stream))
    ):
        assert await recorder.async_start(command, CONFIGURATION)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    assert recorder.initialization_segment == _box(b"ftyp") + _box(b"moov")
    assert len(recorder.prebuffered_fragments) == 2
    await recorder.async_stop()


async def test_recorder_feeds_its_subscribers(recorder):
    stream = _box(b"ftyp") + _box(b"moov") + _box(b"moof") + _box(b"mdat", b"live")
    command = HomeKitSecureVideoRecordingCommand(
        input_source="rtsp://camera",
        configuration=CONFIGURATION,
        source_has_audio=False,
    )

    with patch(
        "asyncio.create_subprocess_exec", AsyncMock(return_value=_process(stream))
    ):
        await recorder.async_start(command, CONFIGURATION)
        queue = recorder.subscribe()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    assert queue.qsize() >= 0
    recorder.unsubscribe(queue)
    await recorder.async_stop()


async def test_recorder_survives_a_missing_binary(recorder):
    command = HomeKitSecureVideoRecordingCommand(
        input_source="rtsp://camera",
        configuration=CONFIGURATION,
        source_has_audio=False,
    )

    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=OSError)):
        assert not await recorder.async_start(command, CONFIGURATION)

    assert not recorder.is_running


async def test_stopping_a_recorder_clears_its_state(recorder):
    stream = _box(b"ftyp") + _box(b"moov")
    command = HomeKitSecureVideoRecordingCommand(
        input_source="rtsp://camera",
        configuration=CONFIGURATION,
        source_has_audio=False,
    )

    with patch(
        "asyncio.create_subprocess_exec", AsyncMock(return_value=_process(stream))
    ):
        await recorder.async_start(command, CONFIGURATION)
        await asyncio.sleep(0)

    await recorder.async_stop()

    assert recorder.initialization_segment is None
    assert recorder.prebuffered_fragments == ()
    assert not recorder.is_running


def test_recording_can_copy_the_camera_stream():
    command = HomeKitSecureVideoRecordingCommand(
        input_source="rtsp://camera/stream",
        configuration=CONFIGURATION,
        source_has_audio=False,
        reencode=False,
    )
    arguments = command.arguments

    assert arguments[arguments.index("-c:v") + 1] == "copy"
    assert "libx264" not in arguments
    # Audio is still encoded: HomeKit will not play a recording without AAC.
    assert arguments[arguments.index("-c:a") + 1] == "aac"


def test_recording_while_copying_corrects_an_over_spec_level():
    command = HomeKitSecureVideoRecordingCommand(
        input_source="rtsp://camera/stream",
        configuration=CONFIGURATION,
        source_has_audio=False,
        reencode=False,
        source_level=51,
    )

    assert "h264_metadata=level=4" in command.arguments


async def test_recorder_diagnostics_report_the_prebuffer(recorder):
    assert recorder.diagnostics == {
        "running": False,
        "has_initialization_segment": False,
        "prebuffer_capacity": 0,
        "prebuffered_fragments": 0,
        "prebuffered_bytes": 0,
    }

    stream = _box(b"ftyp") + _box(b"moov") + _box(b"moof", b"a") + _box(b"mdat", b"one")
    command = HomeKitSecureVideoRecordingCommand(
        input_source="rtsp://camera",
        configuration=CONFIGURATION,
        source_has_audio=False,
    )
    with patch(
        "asyncio.create_subprocess_exec", AsyncMock(return_value=_process(stream))
    ):
        await recorder.async_start(command, CONFIGURATION)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    diagnostics = recorder.diagnostics
    assert diagnostics["running"] is True
    assert diagnostics["has_initialization_segment"] is True
    assert diagnostics["prebuffered_fragments"] == 1
    assert diagnostics["prebuffered_bytes"] > 0
    assert diagnostics["prebuffer_capacity"] >= 1
    await recorder.async_stop()


async def test_a_recorder_that_ends_on_its_own_reports_it(recorder):
    stream = _box(b"ftyp") + _box(b"moov") + _box(b"moof") + _box(b"mdat", b"one")
    command = HomeKitSecureVideoRecordingCommand(
        input_source="rtsp://camera",
        configuration=CONFIGURATION,
        source_has_audio=False,
    )
    ended: list[bool] = []
    recorder.set_stream_ended_callback(lambda: ended.append(True))

    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(return_value=_process(stream, still_running=False)),
    ):
        await recorder.async_start(command, CONFIGURATION)
        async with asyncio.timeout(5):
            while not ended:
                await asyncio.sleep(0)

    assert ended == [True]
    assert recorder.initialization_segment is None
    await recorder.async_stop()
