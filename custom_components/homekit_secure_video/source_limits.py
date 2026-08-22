"""What the camera and the configured caps together allow HomeKit to pick."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .data import HomeKitSecureVideoSourceProfile

type Resolution = tuple[int, int, int]


def limited_frame_rate(
    source_profile: HomeKitSecureVideoSourceProfile, max_fps: int
) -> int:
    """
    Return the highest frame rate worth advertising.

    A camera sending 20 fps cannot be made to send 30: asking ffmpeg for more
    only duplicates frames, which costs an encode per invented frame and
    carries no picture that was not already there.
    """
    frame_rate = source_profile.get("frame_rate")
    if frame_rate is None:
        return max_fps
    return max(1, min(max_fps, round(frame_rate)))


def limited_resolutions(
    catalogue: tuple[Resolution, ...],
    source_profile: HomeKitSecureVideoSourceProfile,
    max_width: int,
    max_height: int,
    frame_rate: int,
) -> tuple[Resolution, ...]:
    """
    Return the resolutions to advertise, at or below what the camera sends.

    The caps are a ceiling, never a target. Advertising more than the camera
    produces makes HomeKit negotiate it, and the only way to honour that is to
    upscale — which invents no detail, costs an encode proportional to the
    invented pixels, and letterboxes the picture when the shapes disagree.

    A camera smaller than every catalogue entry cannot escape that, because
    **HomeKit only negotiates a frame size it already knows**: offered its own
    896x512, one camera left `SelectedCameraRecordingConfiguration` unwritten
    and never recorded again, while the 1920x1080 camera beside it carried on.
    Such a camera is therefore offered the smallest entry alone, so the upscale
    is as small as the catalogue allows instead of whatever HomeKit picks.
    """
    width = source_profile.get("width")
    height = source_profile.get("height")
    if width is not None and height is not None:
        max_width = min(max_width, width)
        max_height = min(max_height, height)

    return _within(catalogue, max_width, max_height, frame_rate) or (
        _smallest(catalogue, frame_rate),
    )


def _within(
    catalogue: tuple[Resolution, ...],
    max_width: int,
    max_height: int,
    frame_rate: int,
) -> tuple[Resolution, ...]:
    """Return the catalogue entries that fit, carrying the given frame rate."""
    return tuple(
        (width, height, frame_rate)
        for width, height, _ in catalogue
        if width <= max_width and height <= max_height
    )


def _smallest(catalogue: tuple[Resolution, ...], frame_rate: int) -> Resolution:
    """Return the catalogue's smallest frame, the least HomeKit will accept."""
    width, height, _ = min(catalogue, key=lambda entry: entry[0] * entry[1])
    return (width, height, frame_rate)
