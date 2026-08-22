"""The caps are a ceiling on what the camera sends, never a target."""

from __future__ import annotations

import pytest

from custom_components.homekit_secure_video.source_limits import (
    limited_frame_rate,
    limited_resolutions,
)

CATALOGUE = ((1280, 720, 30), (1920, 1080, 30))
UNKNOWN: dict[str, object] = {}


def _source(width, height, frame_rate=20.0):
    return {"width": width, "height": height, "frame_rate": frame_rate}


@pytest.mark.parametrize(
    ("source_fps", "max_fps", "expected"),
    [
        (20.0, 30, 20),
        (20.0, 15, 15),
        (30.0, 30, 30),
        (10.0, 30, 10),
        (None, 30, 30),
    ],
)
def test_the_frame_rate_never_exceeds_the_camera_or_the_cap(
    source_fps, max_fps, expected
):
    profile = {"frame_rate": source_fps} if source_fps is not None else UNKNOWN
    assert limited_frame_rate(profile, max_fps) == expected


def test_a_camera_above_the_cap_is_offered_the_cap():
    assert limited_resolutions(CATALOGUE, _source(2880, 1616), 1920, 1080, 15) == (
        (1280, 720, 15),
        (1920, 1080, 15),
    )


def test_a_camera_below_the_cap_is_never_offered_more_than_it_sends():
    assert limited_resolutions(CATALOGUE, _source(1280, 720), 1920, 1080, 15) == (
        (1280, 720, 15),
    )


def test_a_camera_below_every_entry_is_offered_the_smallest_one_alone():
    """HomeKit only negotiates a frame size and shape it knows, so the upscale
    and the pillarboxing are unavoidable — but offering just the smallest entry
    keeps the upscale minimal."""
    assert limited_resolutions(CATALOGUE, _source(896, 512), 1920, 1080, 15) == (
        (1280, 720, 15),
    )


def test_a_tiny_camera_is_never_offered_a_frame_it_would_be_blown_up_to():
    assert limited_resolutions(CATALOGUE, _source(640, 480), 1920, 1080, 15) == (
        (1280, 720, 15),
    )


def test_an_unprobed_camera_falls_back_to_the_catalogue():
    assert limited_resolutions(CATALOGUE, UNKNOWN, 1920, 1080, 30) == (
        (1280, 720, 30),
        (1920, 1080, 30),
    )


def test_an_unprobed_camera_under_every_entry_still_gets_an_offer():
    assert limited_resolutions(CATALOGUE, UNKNOWN, 640, 480, 30) == ((1280, 720, 30),)


def test_the_floor_is_what_a_slower_camera_gets_raised_to():
    """A hub stops choosing below a floor, so a 10 fps camera is raised."""
    from custom_components.homekit_secure_video.accessory.camera_accessory import (
        MIN_ADVERTISED_FPS,
    )

    assert limited_frame_rate({"frame_rate": 10.0}, 30) < MIN_ADVERTISED_FPS
