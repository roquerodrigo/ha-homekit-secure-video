"""ffmpeg command that turns a camera stream into HomeKit recording fragments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..streaming.live_stream_command import (
    ENCODER,
    PRESET,
    copy_arguments,
    level_name,
    profile_name,
)
from .constants import HomeKitSecureVideoRecordingAudioCodec

if TYPE_CHECKING:
    from .selected_configuration import HomeKitSecureVideoSelectedConfiguration

MICROSECONDS_PER_MILLISECOND = 1000
MILLISECONDS_PER_SECOND = 1000
BITRATE_BUFFER_FACTOR = 2
AAC_LOW_PROFILE = "aac_low"
AAC_ELD_PROFILE = "aac_eld"


@dataclass(frozen=True)
class HomeKitSecureVideoRecordingCommand:
    """
    ffmpeg arguments producing the fragmented MP4 HomeKit expects.

    The video is re-encoded to exactly the profile, level, resolution and
    frame rate HomeKit negotiated: copying the camera's own stream hands it
    something else, and it refuses recordings that do not match.
    """

    input_source: str
    configuration: HomeKitSecureVideoSelectedConfiguration
    source_has_audio: bool
    reencode: bool = True
    source_level: int | None = None

    @property
    def arguments(self) -> list[str]:
        """Return the full ffmpeg argument list, binary excluded."""
        return [
            *self._input_arguments,
            *self._video_arguments,
            *self._audio_arguments,
            *self._container_arguments,
            "pipe:1",
        ]

    @property
    def _input_arguments(self) -> list[str]:
        transport = (
            ["-rtsp_transport", "tcp"]
            if self.input_source.startswith("rtsp://")
            else []
        )
        arguments = ["-hide_banner", "-nostats", *transport, "-i", self.input_source]
        if not self.source_has_audio:
            # HomeKit will not play a recording without an audio track, so a
            # silent one is generated at the rate it negotiated.
            arguments += [
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=channel_layout=mono:sample_rate={self._sample_rate}",
            ]
        return arguments

    @property
    def _video_arguments(self) -> list[str]:
        if not self.reencode:
            # Fragments then open on the camera's own keyframes, so their
            # length follows its GOP rather than what HomeKit negotiated.
            return ["-map", "0:v:0", *copy_arguments(self.source_level)]

        configuration = self.configuration
        fps = configuration.frame_rate
        bitrate = configuration.video_bitrate_kbps
        scale = (
            f"scale=w={configuration.width}:h={configuration.height}"
            f":force_original_aspect_ratio=decrease,"
            f"pad={configuration.width}:{configuration.height}:(ow-iw)/2:(oh-ih)/2"
        )
        return [
            "-map",
            "0:v:0",
            "-c:v",
            ENCODER,
            "-preset",
            PRESET,
            "-profile:v",
            profile_name(configuration.video_profile),
            "-level:v",
            level_name(configuration.video_level),
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            # Every fragment has to open on a keyframe, so the keyframe
            # interval is the fragment length.
            "-g",
            str(max(1, fps * self._fragment_seconds)),
            "-force_key_frames",
            f"expr:gte(t,n_forced*{self._fragment_seconds})",
            "-vf",
            scale,
            "-b:v",
            f"{bitrate}k",
            "-maxrate",
            f"{bitrate}k",
            "-bufsize",
            f"{bitrate * BITRATE_BUFFER_FACTOR}k",
        ]

    @property
    def _audio_arguments(self) -> list[str]:
        source = "0:a:0" if self.source_has_audio else "1:a:0"
        profile = (
            AAC_ELD_PROFILE
            if self.configuration.audio_codec
            == HomeKitSecureVideoRecordingAudioCodec.AAC_ELD
            else AAC_LOW_PROFILE
        )
        return [
            "-map",
            source,
            "-c:a",
            "aac",
            "-profile:a",
            profile,
            "-ac",
            str(self.configuration.audio_channels),
            "-ar",
            str(self._sample_rate),
            "-b:a",
            f"{self.configuration.audio_bitrate_kbps}k",
        ]

    @property
    def _container_arguments(self) -> list[str]:
        fragment_microseconds = (
            self.configuration.fragment_milliseconds * MICROSECONDS_PER_MILLISECOND
        )
        return [
            # Without this a dead video input leaves ffmpeg alive, forever
            # producing fragments that carry nothing but generated silence.
            "-shortest",
            "-f",
            "mp4",
            "-movflags",
            "frag_keyframe+empty_moov+default_base_moof",
            "-frag_duration",
            str(fragment_microseconds),
            "-reset_timestamps",
            "1",
        ]

    @property
    def _fragment_seconds(self) -> int:
        return max(
            1, self.configuration.fragment_milliseconds // MILLISECONDS_PER_SECOND
        )

    @property
    def _sample_rate(self) -> int:
        return self.configuration.audio_sample_rate.hertz
