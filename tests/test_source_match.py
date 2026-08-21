from __future__ import annotations

import pytest

from custom_components.homekit_secure_video.recording import (
    HomeKitSecureVideoSelectedConfiguration,
    source_matches_configuration,
)
from custom_components.homekit_secure_video.recording.source_probe import EMPTY_PROFILE

from .test_recording_configuration import _selected_tlv


def _selected_configuration():
    return HomeKitSecureVideoSelectedConfiguration.from_tlv(_selected_tlv())


def _profile(**overrides):
    return {
        **EMPTY_PROFILE,
        "video_codec": "h264",
        "width": 1920,
        "height": 1080,
        "frame_rate": 30.0,
        **overrides,
    }


def test_an_exact_match_may_be_copied():
    assert source_matches_configuration(_profile(), _selected_configuration())


def test_a_faster_source_may_be_copied():
    assert source_matches_configuration(
        _profile(frame_rate=60.0), _selected_configuration()
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"video_codec": "hevc"},
        {"width": 896},
        {"height": 512},
        {"frame_rate": 20.0},
        {"frame_rate": None},
    ],
)
def test_anything_else_must_be_re_encoded(overrides):
    assert not source_matches_configuration(
        _profile(**overrides), _selected_configuration()
    )
