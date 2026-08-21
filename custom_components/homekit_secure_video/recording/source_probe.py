"""Asks ffprobe what a camera actually sends."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import PurePath
from typing import TYPE_CHECKING

from ..const import LOGGER

if TYPE_CHECKING:
    from ..data import HomeKitSecureVideoSourceProfile

PROBE_TIMEOUT_SECONDS = 15

EMPTY_PROFILE: HomeKitSecureVideoSourceProfile = {
    "video_codec": None,
    "video_profile": None,
    "video_level": None,
    "width": None,
    "height": None,
    "frame_rate": None,
    "audio_codec": None,
    "audio_sample_rate": None,
}


def _ffprobe_binary(ffmpeg_binary: str) -> str:
    """
    Return the ffprobe that sits beside the configured ffmpeg.

    Only the file name is rewritten: a build whose directory also carries the
    word (``/usr/lib/jellyfin-ffmpeg/ffmpeg``) would otherwise be turned into a
    directory that does not exist.
    """
    path = PurePath(ffmpeg_binary)
    return str(path.with_name(path.name.replace("ffmpeg", "ffprobe")))


async def async_probe_source(
    ffmpeg_binary: str, input_source: str
) -> HomeKitSecureVideoSourceProfile:
    """
    Return what the camera sends: codec, profile, resolution and frame rate.

    HomeKit negotiates against what the accessory advertises, and the video is
    copied rather than re-encoded — so a camera sending something outside the
    advertised set produces a stream the controller cannot use. Reading it back
    is the only way to see that mismatch.
    """
    ffprobe = _ffprobe_binary(ffmpeg_binary)
    arguments = [
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,codec_name,profile,level,width,height,avg_frame_rate,sample_rate",
        "-of",
        "json",
    ]
    if input_source.startswith("rtsp://"):
        arguments += ["-rtsp_transport", "tcp"]
    arguments.append(input_source)

    try:
        process = await asyncio.create_subprocess_exec(
            ffprobe,
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        LOGGER.exception("Failed to probe the camera")
        return dict(EMPTY_PROFILE)  # type: ignore[return-value]

    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            stdout, _ = await process.communicate()
    except TimeoutError:
        LOGGER.warning("Probing the camera timed out")
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        return dict(EMPTY_PROFILE)  # type: ignore[return-value]

    return _parse(stdout)


async def async_source_has_audio(ffmpeg_binary: str, input_source: str) -> bool:
    """Return whether the stream carries an audio track."""
    profile = await async_probe_source(ffmpeg_binary, input_source)
    return profile["audio_codec"] is not None


def _parse(stdout: bytes) -> HomeKitSecureVideoSourceProfile:
    """Turn ffprobe's JSON into the fields worth reporting."""
    profile: HomeKitSecureVideoSourceProfile = dict(EMPTY_PROFILE)  # type: ignore[assignment]
    try:
        streams = json.loads(stdout or b"{}").get("streams", [])
    except json.JSONDecodeError:
        LOGGER.warning("Could not read what the camera reported")
        return profile

    for stream in streams:
        if stream.get("codec_type") == "video" and profile["video_codec"] is None:
            profile["video_codec"] = stream.get("codec_name")
            profile["video_profile"] = stream.get("profile")
            profile["video_level"] = stream.get("level")
            profile["width"] = stream.get("width")
            profile["height"] = stream.get("height")
            profile["frame_rate"] = _frame_rate(stream.get("avg_frame_rate"))
        elif stream.get("codec_type") == "audio" and profile["audio_codec"] is None:
            profile["audio_codec"] = stream.get("codec_name")
            sample_rate = stream.get("sample_rate")
            profile["audio_sample_rate"] = int(sample_rate) if sample_rate else None

    return profile


def _frame_rate(rational: str | None) -> float | None:
    """Turn ffprobe's "30/1" frame rate into a number."""
    if not rational or "/" not in rational:
        return None
    numerator, _, denominator = rational.partition("/")
    try:
        divisor = float(denominator)
        return round(float(numerator) / divisor, 2) if divisor else None
    except ValueError:
        return None
