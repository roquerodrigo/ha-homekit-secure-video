"""Wire constants of the HomeKit Secure Video recording services."""

from __future__ import annotations

from enum import IntEnum
from typing import Final

TAG_PREBUFFER_LENGTH: Final = b"\x01"
TAG_EVENT_TRIGGER_OPTIONS: Final = b"\x02"
TAG_MEDIA_CONTAINER_CONFIGURATIONS: Final = b"\x03"

TAG_MEDIA_CONTAINER_TYPE: Final = b"\x01"
TAG_MEDIA_CONTAINER_PARAMETERS: Final = b"\x02"
TAG_FRAGMENT_LENGTH: Final = b"\x01"

TAG_VIDEO_CODEC_CONFIGURATION: Final = b"\x01"
TAG_VIDEO_CODEC_TYPE: Final = b"\x01"
TAG_VIDEO_CODEC_PARAMETERS: Final = b"\x02"
TAG_VIDEO_ATTRIBUTES: Final = b"\x03"

TAG_VIDEO_PROFILE_ID: Final = b"\x01"
TAG_VIDEO_LEVEL: Final = b"\x02"
TAG_VIDEO_BITRATE: Final = b"\x03"
TAG_VIDEO_IFRAME_INTERVAL: Final = b"\x04"

TAG_IMAGE_WIDTH: Final = b"\x01"
TAG_IMAGE_HEIGHT: Final = b"\x02"
TAG_FRAME_RATE: Final = b"\x03"

TAG_AUDIO_CODEC_CONFIGURATION: Final = b"\x01"
TAG_AUDIO_CODEC_TYPE: Final = b"\x01"
TAG_AUDIO_CODEC_PARAMETERS: Final = b"\x02"

TAG_AUDIO_CHANNELS: Final = b"\x01"
TAG_AUDIO_BITRATE_MODE: Final = b"\x02"
TAG_AUDIO_SAMPLE_RATE: Final = b"\x03"
TAG_AUDIO_MAX_BITRATE: Final = b"\x04"

TAG_SELECTED_RECORDING_CONFIGURATION: Final = b"\x01"
TAG_SELECTED_VIDEO_CONFIGURATION: Final = b"\x02"
TAG_SELECTED_AUDIO_CONFIGURATION: Final = b"\x03"

DATA_SEND_TYPE_RECORDING: Final = "ipcamera.recording"
DATA_SEND_TARGET_CONTROLLER: Final = "controller"

PACKET_TYPE_MEDIA_INITIALIZATION: Final = "mediaInitialization"
PACKET_TYPE_MEDIA_FRAGMENT: Final = "mediaFragment"

# HomeKit picks one configuration out of what the accessory offers, and it
# fails to pick at all when offered too much: Scrypted narrowed its own offer
# to these two resolutions and a single sample rate for exactly that reason.
# The Home app reports the failure as a generic "error updating this setting",
# on any mode change, not just recording.
RECORDING_RESOLUTIONS: Final[tuple[tuple[int, int, int], ...]] = (
    (1280, 720, 30),
    (1920, 1080, 30),
)

MAX_CHUNK_SIZE: Final = 0x40000
DEFAULT_PREBUFFER_MILLISECONDS: Final = 4000
DEFAULT_FRAGMENT_MILLISECONDS: Final = 4000
MAX_RECORDING_SECONDS: Final = 180
CLOSE_TIMEOUT_SECONDS: Final = 12

# The prebuffer is kept longer than HomeKit asks for: the controller only
# negotiates how much it wants delivered, while fragments keep arriving while a
# recording is being sent. Scrypted keeps the same 2.5x margin.
PREBUFFER_MARGIN: Final = 2.5


class HomeKitSecureVideoEventTrigger(IntEnum):
    """Events a recording can be triggered by."""

    MOTION = 0x01
    DOORBELL = 0x02


class HomeKitSecureVideoMediaContainerType(IntEnum):
    """Container a recording is delivered in."""

    FRAGMENTED_MP4 = 0x00


class HomeKitSecureVideoRecordingVideoCodec(IntEnum):
    """Video codec of a recording."""

    H264 = 0x00


class HomeKitSecureVideoRecordingAudioCodec(IntEnum):
    """Audio codec of a recording."""

    AAC_LC = 0
    AAC_ELD = 1


class HomeKitSecureVideoAudioSampleRate(IntEnum):
    """Sample rates HomeKit may pick, in the order it numbers them."""

    KHZ_8 = 0
    KHZ_16 = 1
    KHZ_24 = 2
    KHZ_32 = 3
    KHZ_44_1 = 4
    KHZ_48 = 5

    @property
    def hertz(self) -> int:
        """Return the sample rate in hertz."""
        return _SAMPLE_RATE_HERTZ[self]


_SAMPLE_RATE_HERTZ: Final[dict[HomeKitSecureVideoAudioSampleRate, int]] = {
    HomeKitSecureVideoAudioSampleRate.KHZ_8: 8000,
    HomeKitSecureVideoAudioSampleRate.KHZ_16: 16000,
    HomeKitSecureVideoAudioSampleRate.KHZ_24: 24000,
    HomeKitSecureVideoAudioSampleRate.KHZ_32: 32000,
    HomeKitSecureVideoAudioSampleRate.KHZ_44_1: 44100,
    HomeKitSecureVideoAudioSampleRate.KHZ_48: 48000,
}


class HomeKitSecureVideoAudioBitrateMode(IntEnum):
    """Whether the audio bitrate is variable or constant."""

    VARIABLE = 0
    CONSTANT = 1
