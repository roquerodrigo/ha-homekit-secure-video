"""The recording configurations this accessory offers to HomeKit."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyhap import tlv
from pyhap.util import to_base64_str

from .constants import (
    TAG_AUDIO_BITRATE_MODE,
    TAG_AUDIO_CHANNELS,
    TAG_AUDIO_CODEC_CONFIGURATION,
    TAG_AUDIO_CODEC_PARAMETERS,
    TAG_AUDIO_CODEC_TYPE,
    TAG_AUDIO_SAMPLE_RATE,
    TAG_EVENT_TRIGGER_OPTIONS,
    TAG_FRAGMENT_LENGTH,
    TAG_FRAME_RATE,
    TAG_IMAGE_HEIGHT,
    TAG_IMAGE_WIDTH,
    TAG_MEDIA_CONTAINER_CONFIGURATIONS,
    TAG_MEDIA_CONTAINER_PARAMETERS,
    TAG_MEDIA_CONTAINER_TYPE,
    TAG_PREBUFFER_LENGTH,
    TAG_VIDEO_ATTRIBUTES,
    TAG_VIDEO_CODEC_CONFIGURATION,
    TAG_VIDEO_CODEC_PARAMETERS,
    TAG_VIDEO_CODEC_TYPE,
    TAG_VIDEO_LEVEL,
    TAG_VIDEO_PROFILE_ID,
    HomeKitSecureVideoAudioBitrateMode,
    HomeKitSecureVideoAudioSampleRate,
    HomeKitSecureVideoEventTrigger,
    HomeKitSecureVideoMediaContainerType,
    HomeKitSecureVideoRecordingAudioCodec,
    HomeKitSecureVideoRecordingVideoCodec,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class HomeKitSecureVideoSupportedConfiguration:
    """The recording configurations this accessory offers to HomeKit."""

    prebuffer_milliseconds: int
    fragment_milliseconds: int
    event_triggers: tuple[HomeKitSecureVideoEventTrigger, ...]
    resolutions: tuple[tuple[int, int, int], ...]
    video_profiles: tuple[int, ...]
    video_levels: tuple[int, ...]
    audio_codecs: tuple[HomeKitSecureVideoRecordingAudioCodec, ...]
    audio_sample_rates: tuple[HomeKitSecureVideoAudioSampleRate, ...]

    @property
    def camera_configuration(self) -> str:
        """Return the SupportedCameraRecordingConfiguration value."""
        trigger_mask = 0
        for trigger in self.event_triggers:
            trigger_mask |= int(trigger)

        container = tlv.encode(
            TAG_MEDIA_CONTAINER_TYPE,
            bytes([HomeKitSecureVideoMediaContainerType.FRAGMENTED_MP4]),
            TAG_MEDIA_CONTAINER_PARAMETERS,
            tlv.encode(
                TAG_FRAGMENT_LENGTH,
                struct.pack("<i", self.fragment_milliseconds),
            ),
        )
        return to_base64_str(
            tlv.encode(
                TAG_PREBUFFER_LENGTH,
                struct.pack("<i", self.prebuffer_milliseconds),
                TAG_EVENT_TRIGGER_OPTIONS,
                struct.pack("<q", trigger_mask),
                TAG_MEDIA_CONTAINER_CONFIGURATIONS,
                container,
            )
        )

    @property
    def video_configuration(self) -> str:
        """Return the SupportedVideoRecordingConfiguration value."""
        parameters = tlv.encode(
            *_repeated(TAG_VIDEO_PROFILE_ID, [bytes([p]) for p in self.video_profiles]),
            *_repeated(
                TAG_VIDEO_LEVEL, [bytes([level]) for level in self.video_levels]
            ),
        )
        attributes = [
            tlv.encode(
                TAG_IMAGE_WIDTH,
                struct.pack("<H", width),
                TAG_IMAGE_HEIGHT,
                struct.pack("<H", height),
                TAG_FRAME_RATE,
                struct.pack("<B", frame_rate),
            )
            for width, height, frame_rate in self.resolutions
        ]
        codec_configuration = tlv.encode(
            TAG_VIDEO_CODEC_TYPE,
            bytes([HomeKitSecureVideoRecordingVideoCodec.H264]),
            TAG_VIDEO_CODEC_PARAMETERS,
            parameters,
            *_repeated(TAG_VIDEO_ATTRIBUTES, attributes),
        )
        return to_base64_str(
            tlv.encode(TAG_VIDEO_CODEC_CONFIGURATION, codec_configuration)
        )

    @property
    def audio_configuration(self) -> str:
        """Return the SupportedAudioRecordingConfiguration value."""
        configurations = [
            tlv.encode(
                TAG_AUDIO_CODEC_TYPE,
                bytes([codec]),
                TAG_AUDIO_CODEC_PARAMETERS,
                tlv.encode(
                    TAG_AUDIO_CHANNELS,
                    bytes([1]),
                    TAG_AUDIO_BITRATE_MODE,
                    bytes([HomeKitSecureVideoAudioBitrateMode.VARIABLE]),
                    *_repeated(
                        TAG_AUDIO_SAMPLE_RATE,
                        [bytes([rate]) for rate in self.audio_sample_rates],
                    ),
                ),
            )
            for codec in self.audio_codecs
        ]
        return to_base64_str(
            tlv.encode(*_repeated(TAG_AUDIO_CODEC_CONFIGURATION, configurations))
        )


def _repeated(tag: bytes, values: Sequence[bytes]) -> list[bytes]:
    """Flatten repeated values into the tag/value pairs pyhap's encoder takes."""
    pairs: list[bytes] = []
    for value in values:
        pairs.extend((tag, value))
    return pairs
