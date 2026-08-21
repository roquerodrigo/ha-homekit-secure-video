"""The recording configuration HomeKit picked for this accessory."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Self

from pyhap import tlv

from ..exceptions import HomeKitSecureVideoRecordingError
from .constants import (
    TAG_AUDIO_CHANNELS,
    TAG_AUDIO_CODEC_PARAMETERS,
    TAG_AUDIO_CODEC_TYPE,
    TAG_AUDIO_MAX_BITRATE,
    TAG_AUDIO_SAMPLE_RATE,
    TAG_FRAGMENT_LENGTH,
    TAG_FRAME_RATE,
    TAG_IMAGE_HEIGHT,
    TAG_IMAGE_WIDTH,
    TAG_MEDIA_CONTAINER_CONFIGURATIONS,
    TAG_MEDIA_CONTAINER_PARAMETERS,
    TAG_PREBUFFER_LENGTH,
    TAG_SELECTED_AUDIO_CONFIGURATION,
    TAG_SELECTED_RECORDING_CONFIGURATION,
    TAG_SELECTED_VIDEO_CONFIGURATION,
    TAG_VIDEO_ATTRIBUTES,
    TAG_VIDEO_BITRATE,
    TAG_VIDEO_CODEC_PARAMETERS,
    TAG_VIDEO_IFRAME_INTERVAL,
    TAG_VIDEO_LEVEL,
    TAG_VIDEO_PROFILE_ID,
    HomeKitSecureVideoAudioSampleRate,
    HomeKitSecureVideoRecordingAudioCodec,
)


@dataclass(frozen=True)
class HomeKitSecureVideoSelectedConfiguration:
    """The recording configuration HomeKit picked for this accessory."""

    prebuffer_milliseconds: int
    fragment_milliseconds: int
    width: int
    height: int
    frame_rate: int
    video_profile: int
    video_level: int
    video_bitrate_kbps: int
    iframe_interval_milliseconds: int
    audio_codec: HomeKitSecureVideoRecordingAudioCodec
    audio_channels: int
    audio_sample_rate: HomeKitSecureVideoAudioSampleRate
    audio_bitrate_kbps: int

    @classmethod
    def from_tlv(cls, value: str) -> Self:
        """Decode the SelectedCameraRecordingConfiguration written by HomeKit."""
        selected = _decode(value, from_base64=True)
        recording = _section(selected, TAG_SELECTED_RECORDING_CONFIGURATION)
        video = _section(selected, TAG_SELECTED_VIDEO_CONFIGURATION)
        audio = _section(selected, TAG_SELECTED_AUDIO_CONFIGURATION)

        container = _decode(_field(recording, TAG_MEDIA_CONTAINER_CONFIGURATIONS))
        container_parameters = _decode(
            _field(container, TAG_MEDIA_CONTAINER_PARAMETERS)
        )
        video_parameters = _decode(_field(video, TAG_VIDEO_CODEC_PARAMETERS))
        video_attributes = _decode(_field(video, TAG_VIDEO_ATTRIBUTES))
        audio_parameters = _decode(_field(audio, TAG_AUDIO_CODEC_PARAMETERS))

        return cls(
            prebuffer_milliseconds=_int32(recording, TAG_PREBUFFER_LENGTH),
            fragment_milliseconds=_int32(container_parameters, TAG_FRAGMENT_LENGTH),
            width=_uint16(video_attributes, TAG_IMAGE_WIDTH),
            height=_uint16(video_attributes, TAG_IMAGE_HEIGHT),
            frame_rate=_byte(video_attributes, TAG_FRAME_RATE),
            video_profile=_byte(video_parameters, TAG_VIDEO_PROFILE_ID),
            video_level=_byte(video_parameters, TAG_VIDEO_LEVEL),
            video_bitrate_kbps=_int32(video_parameters, TAG_VIDEO_BITRATE),
            iframe_interval_milliseconds=_int32(
                video_parameters, TAG_VIDEO_IFRAME_INTERVAL
            ),
            audio_codec=_enum(
                HomeKitSecureVideoRecordingAudioCodec,
                _byte(audio, TAG_AUDIO_CODEC_TYPE),
                "audio codec",
            ),
            audio_channels=_byte(audio_parameters, TAG_AUDIO_CHANNELS),
            audio_sample_rate=_enum(
                HomeKitSecureVideoAudioSampleRate,
                _byte(audio_parameters, TAG_AUDIO_SAMPLE_RATE),
                "audio sample rate",
            ),
            audio_bitrate_kbps=_uint32(audio_parameters, TAG_AUDIO_MAX_BITRATE),
        )


def _enum[EnumType: IntEnum](
    enum_type: type[EnumType], value: int, description: str
) -> EnumType:
    """
    Turn a wire value into one of our enum members.

    A controller may pick a value this accessory never offered, and an
    unhandled ValueError here reaches HAP-python as a write failure — which is
    what the Home app reports as "unable to configure".
    """
    try:
        return enum_type(value)
    except ValueError as exception:
        message = (
            f"Failed to read the selected recording configuration: "
            f"unsupported {description} {value}"
        )
        raise HomeKitSecureVideoRecordingError(message) from exception


def _decode(value: str | bytes, *, from_base64: bool = False) -> dict[bytes, bytes]:
    """
    Decode a TLV blob into a dict, turning malformed input into our own error.

    The value comes straight off the wire, and pyhap's decoder walks it without
    bounds checks — a truncated blob surfaces as an IndexError several frames
    down instead of as something this integration can report.
    """
    try:
        decoded: dict[bytes, bytes] = tlv.decode(value, from_base64=from_base64)
    except (IndexError, ValueError, TypeError) as exception:
        message = "Failed to read the selected recording configuration: malformed TLV"
        raise HomeKitSecureVideoRecordingError(message) from exception
    return decoded


def _section(decoded: dict[bytes, bytes], tag: bytes) -> dict[bytes, bytes]:
    """Decode a nested TLV section, failing loudly when it is missing."""
    return _decode(_field(decoded, tag))


def _field(decoded: dict[bytes, bytes], tag: bytes) -> bytes:
    """Return one TLV field, failing loudly when it is missing."""
    value = decoded.get(tag)
    if value is None:
        message = (
            f"Failed to read the selected recording configuration: no field {tag.hex()}"
        )
        raise HomeKitSecureVideoRecordingError(message)
    return value


def _byte(decoded: dict[bytes, bytes], tag: bytes) -> int:
    """Return a single-byte TLV field."""
    value = _field(decoded, tag)
    if not value:
        message = (
            f"Failed to read the selected recording configuration: "
            f"field {tag.hex()} is empty"
        )
        raise HomeKitSecureVideoRecordingError(message)
    return value[0]


def _uint16(decoded: dict[bytes, bytes], tag: bytes) -> int:
    """Return a little-endian 16-bit TLV field."""
    return int(struct.unpack("<H", _field(decoded, tag)[:2])[0])


def _int32(decoded: dict[bytes, bytes], tag: bytes) -> int:
    """Return a little-endian signed 32-bit TLV field."""
    return int(struct.unpack("<i", _field(decoded, tag)[:4])[0])


def _uint32(decoded: dict[bytes, bytes], tag: bytes) -> int:
    """Return a little-endian unsigned 32-bit TLV field."""
    return int(struct.unpack("<I", _field(decoded, tag)[:4])[0])
