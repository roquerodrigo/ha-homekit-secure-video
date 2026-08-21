from __future__ import annotations

import pytest
from homeassistant.helpers import issue_registry

from custom_components.homekit_secure_video.const import DOMAIN
from custom_components.homekit_secure_video.issues import (
    ISSUE_NO_STREAM_SOURCE,
    ISSUE_OVERSIZED_SOURCE,
    ISSUE_UNSUPPORTED_CODEC,
    async_clear_camera_source_issues,
    async_review_camera_source,
)
from custom_components.homekit_secure_video.recording.source_probe import EMPTY_PROFILE


def _profile(**overrides):
    return {**EMPTY_PROFILE, **overrides}


def _issue(hass, config_entry, issue):
    return issue_registry.async_get(hass).async_get_issue(
        DOMAIN, f"{config_entry.entry_id}_{issue}"
    )


def test_a_camera_without_a_stream_source_raises_an_issue(hass, config_entry):
    async_review_camera_source(hass, config_entry, _profile(), has_stream_source=False)

    assert _issue(hass, config_entry, ISSUE_NO_STREAM_SOURCE) is not None


def test_a_healthy_camera_raises_nothing(hass, config_entry):
    async_review_camera_source(
        hass,
        config_entry,
        _profile(video_codec="h264", width=1920, height=1080),
        has_stream_source=True,
    )

    assert _issue(hass, config_entry, ISSUE_NO_STREAM_SOURCE) is None
    assert _issue(hass, config_entry, ISSUE_UNSUPPORTED_CODEC) is None
    assert _issue(hass, config_entry, ISSUE_OVERSIZED_SOURCE) is None


def test_an_unsupported_codec_raises_an_issue(hass, config_entry):
    async_review_camera_source(
        hass, config_entry, _profile(video_codec="hevc"), has_stream_source=True
    )

    raised = _issue(hass, config_entry, ISSUE_UNSUPPORTED_CODEC)
    assert raised is not None
    assert raised.translation_placeholders["codec"] == "hevc"


def test_an_oversized_source_raises_an_issue_only_while_copying(hass, config_entry):
    hass.config_entries.async_update_entry(config_entry, options={"reencode": False})

    async_review_camera_source(
        hass,
        config_entry,
        _profile(video_codec="h264", width=2880, height=1616),
        has_stream_source=True,
    )

    raised = _issue(hass, config_entry, ISSUE_OVERSIZED_SOURCE)
    assert raised is not None
    assert raised.translation_placeholders["source_resolution"] == "2880x1616"


def test_an_oversized_source_is_not_an_issue_while_re_encoding(hass, config_entry):
    hass.config_entries.async_update_entry(config_entry, options={"reencode": True})

    async_review_camera_source(
        hass,
        config_entry,
        _profile(video_codec="h264", width=2880, height=1616),
        has_stream_source=True,
    )

    assert _issue(hass, config_entry, ISSUE_OVERSIZED_SOURCE) is None


def test_a_resolved_problem_withdraws_its_issue(hass, config_entry):
    async_review_camera_source(
        hass, config_entry, _profile(video_codec="hevc"), has_stream_source=True
    )
    async_review_camera_source(
        hass, config_entry, _profile(video_codec="h264"), has_stream_source=True
    )

    assert _issue(hass, config_entry, ISSUE_UNSUPPORTED_CODEC) is None


def test_removing_an_entry_withdraws_every_issue(hass, config_entry):
    async_review_camera_source(
        hass, config_entry, _profile(video_codec="hevc"), has_stream_source=False
    )

    async_clear_camera_source_issues(hass, config_entry)

    assert _issue(hass, config_entry, ISSUE_NO_STREAM_SOURCE) is None
    assert _issue(hass, config_entry, ISSUE_UNSUPPORTED_CODEC) is None


@pytest.mark.parametrize(
    "issue",
    [ISSUE_NO_STREAM_SOURCE, ISSUE_UNSUPPORTED_CODEC, ISSUE_OVERSIZED_SOURCE],
)
def test_every_issue_is_translated(issue):
    import json
    from pathlib import Path

    translations = json.loads(
        (
            Path(__file__).parent.parent
            / "custom_components"
            / "homekit_secure_video"
            / "translations"
            / "en.json"
        ).read_text(encoding="utf-8")
    )
    assert issue in translations["issues"]
