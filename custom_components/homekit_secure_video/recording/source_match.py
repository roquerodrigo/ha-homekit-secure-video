"""Whether the camera already sends what HomeKit negotiated for a recording."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..data import HomeKitSecureVideoSourceProfile
    from .selected_configuration import HomeKitSecureVideoSelectedConfiguration

SUPPORTED_VIDEO_CODEC = "h264"


def source_matches_configuration(
    source_profile: HomeKitSecureVideoSourceProfile,
    configuration: HomeKitSecureVideoSelectedConfiguration,
) -> bool:
    """
    Return whether the camera's own stream can be recorded without re-encoding.

    A home hub refuses a recording that is not what it negotiated: it stops
    acknowledging the delivery and closes the stream with ``TIMEOUT`` after
    about twenty seconds, with nothing in the HAP log to say why. Only an
    exact match may be copied — the H.264 level is the one exception, because
    it can be rewritten in the bitstream.
    """
    frame_rate = source_profile.get("frame_rate")
    return (
        source_profile.get("video_codec") == SUPPORTED_VIDEO_CODEC
        and source_profile.get("width") == configuration.width
        and source_profile.get("height") == configuration.height
        and frame_rate is not None
        and round(frame_rate) >= configuration.frame_rate
    )
