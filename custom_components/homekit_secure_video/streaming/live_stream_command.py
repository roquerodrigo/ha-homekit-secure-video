"""ffmpeg command that pushes a camera stream to a HomeKit controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from ..data import HomeKitSecureVideoStreamRequest

VIDEO_PAYLOAD_TYPE = 99
PACKET_SIZE = 1316
AUDIO_PACKET_SIZE = 188
BITRATE_BUFFER_FACTOR = 4
KEYFRAME_INTERVAL_SECONDS = 2

# The encoder has to keep up with a live camera on a Raspberry Pi, so quality
# per bit is traded for speed.
ENCODER = "libx264"
PRESET = "ultrafast"

H264_PROFILE_NAMES: Final[tuple[str, ...]] = ("baseline", "main", "high")
H264_LEVEL_NAMES: Final[tuple[str, ...]] = ("3.1", "3.2", "4.0")

MAX_HOMEKIT_H264_LEVEL = 40
DEFAULT_PROFILE = "main"
DEFAULT_LEVEL = "4.0"
DEFAULT_FPS = 30

# Opus is the only codec HomeKit offers that the Home Assistant ffmpeg build
# can produce: AAC-ELD needs libfdk_aac, which is not compiled in.
OPUS_CODEC = b"\x03"
AUDIO_ENCODER = "libopus"
DEFAULT_AUDIO_SAMPLE_RATE_KHZ = 24
DEFAULT_AUDIO_BITRATE_KBPS = 24
DEFAULT_AUDIO_PACKET_MILLISECONDS = 20
DEFAULT_AUDIO_PAYLOAD_TYPE = 110
DEFAULT_AUDIO_CHANNELS = 1


def copy_arguments(source_level: int | None) -> list[str]:
    """
    Return the arguments that pass the camera's own H.264 through untouched.

    Only the declared level is rewritten, and only when the camera ships one
    above what HomeKit accepts: the level lives in the stream's SPS, so it can
    be corrected in place without re-encoding.
    """
    if source_level is None or source_level <= MAX_HOMEKIT_H264_LEVEL:
        return ["-c:v", "copy"]
    return ["-c:v", "copy", "-bsf:v", "h264_metadata=level=4"]


def profile_name(profile_id: bytes | int | None) -> str:
    """Return the ffmpeg name of a HomeKit H.264 profile."""
    index = _as_index(profile_id)
    if index is None or index >= len(H264_PROFILE_NAMES):
        return DEFAULT_PROFILE
    return H264_PROFILE_NAMES[index]


def level_name(level_id: bytes | int | None) -> str:
    """Return the ffmpeg name of a HomeKit H.264 level."""
    index = _as_index(level_id)
    if index is None or index >= len(H264_LEVEL_NAMES):
        return DEFAULT_LEVEL
    return H264_LEVEL_NAMES[index]


def _as_index(value: bytes | int | None) -> int | None:
    """Turn the TLV representation of an enum into an index."""
    if isinstance(value, bytes):
        return value[0] if value else None
    return value


@dataclass(frozen=True)
class HomeKitSecureVideoLiveStreamCommand:
    """
    ffmpeg arguments that push a camera stream to a HomeKit controller.

    The video is re-encoded rather than copied. Copying is cheaper, but it
    hands HomeKit whatever the camera happens to send — a level, resolution or
    frame rate other than the one just negotiated — and HomeKit rejects a
    stream that does not match what it asked for.
    """

    input_source: str
    request: HomeKitSecureVideoStreamRequest
    reencode: bool = True
    source_level: int | None = None
    source_has_audio: bool = False

    @property
    def arguments(self) -> list[str]:
        """Return the full ffmpeg argument list, binary excluded."""
        return [
            *self._input_arguments,
            *self._video_arguments,
            self._destination,
            *self._audio_arguments,
        ]

    @property
    def _audio_arguments(self) -> list[str]:
        """
        Return a second output carrying the camera's audio, when there is any.

        HomeKit negotiates audio on its own port and SRTP key, so it is a
        separate output of the same ffmpeg process rather than a second one.
        """
        if not self.source_has_audio or not self._negotiated_opus:
            return []
        request = self.request
        sample_rate_khz = request.get("a_sample_rate") or DEFAULT_AUDIO_SAMPLE_RATE_KHZ
        bitrate = request.get("a_max_bitrate") or DEFAULT_AUDIO_BITRATE_KBPS
        packet_time = request.get("a_packet_time") or DEFAULT_AUDIO_PACKET_MILLISECONDS
        payload_type = (
            _as_index(request.get("a_payload_type")) or DEFAULT_AUDIO_PAYLOAD_TYPE
        )
        return [
            "-map",
            "0:a:0",
            "-vn",
            "-c:a",
            AUDIO_ENCODER,
            "-application",
            "lowdelay",
            "-ac",
            str(request.get("a_channel") or DEFAULT_AUDIO_CHANNELS),
            "-ar",
            str(sample_rate_khz * 1000),
            "-b:a",
            f"{bitrate}k",
            "-frame_duration",
            str(packet_time),
            "-payload_type",
            str(payload_type),
            "-ssrc",
            str(request["a_ssrc"]),
            "-f",
            "rtp",
            "-srtp_out_suite",
            "AES_CM_128_HMAC_SHA1_80",
            "-srtp_out_params",
            request["a_srtp_key"],
            self._audio_destination,
        ]

    @property
    def _negotiated_opus(self) -> bool:
        """Return whether HomeKit asked for audio this accessory can encode."""
        request = self.request
        return (
            request.get("a_codec") == OPUS_CODEC
            and request.get("a_port") is not None
            and request.get("a_srtp_key") is not None
            and request.get("a_ssrc") is not None
        )

    @property
    def _audio_destination(self) -> str:
        address = self.request["address"]
        port = self.request["a_port"]
        return (
            f"srtp://{address}:{port}?rtcpport={port}"
            f"&localrtpport={port}&pkt_size={AUDIO_PACKET_SIZE}"
        )

    @property
    def _input_arguments(self) -> list[str]:
        # ``-rtsp_transport`` is an option of the RTSP demuxer: ffmpeg refuses
        # to open the input at all when it is passed for any other source.
        transport = (
            ["-rtsp_transport", "tcp"]
            if self.input_source.startswith("rtsp://")
            else []
        )
        return [
            "-hide_banner",
            "-nostats",
            "-fflags",
            "+genpts",
            *transport,
            "-i",
            self.input_source,
        ]

    @property
    def _video_arguments(self) -> list[str]:
        if not self.reencode:
            return [
                "-map",
                "0:v:0",
                "-an",
                *copy_arguments(self.source_level),
                *self._destination_arguments,
            ]
        max_bitrate = self.request["v_max_bitrate"]
        fps = self.request.get("fps") or DEFAULT_FPS
        return [
            "-map",
            "0:v:0",
            "-an",
            "-c:v",
            ENCODER,
            "-preset",
            PRESET,
            "-tune",
            "zerolatency",
            "-profile:v",
            profile_name(self.request.get("v_profile_id")),
            "-level:v",
            level_name(self.request.get("v_level")),
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-g",
            str(fps * KEYFRAME_INTERVAL_SECONDS),
            *self._scale_arguments,
            "-b:v",
            f"{max_bitrate}k",
            "-maxrate",
            f"{max_bitrate}k",
            "-bufsize",
            f"{max_bitrate * BITRATE_BUFFER_FACTOR}k",
            *self._destination_arguments,
        ]

    @property
    def _destination_arguments(self) -> list[str]:
        """Return the RTP and SRTP arguments the controller negotiated."""
        return [
            "-payload_type",
            str(VIDEO_PAYLOAD_TYPE),
            "-ssrc",
            str(self.request["v_ssrc"]),
            "-f",
            "rtp",
            "-srtp_out_suite",
            "AES_CM_128_HMAC_SHA1_80",
            "-srtp_out_params",
            self.request["v_srtp_key"],
        ]

    @property
    def _scale_arguments(self) -> list[str]:
        """Scale to the negotiated size, keeping the source's aspect ratio."""
        width = self.request.get("width")
        height = self.request.get("height")
        if not width or not height:
            return []
        scale = (
            f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
        return ["-vf", scale]

    @property
    def _destination(self) -> str:
        address = self.request["address"]
        port = self.request["v_port"]
        return (
            f"srtp://{address}:{port}?rtcpport={port}"
            f"&localrtpport={port}&pkt_size={PACKET_SIZE}"
        )
