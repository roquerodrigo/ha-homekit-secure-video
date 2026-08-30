"""Repair issues raised for a camera Home Assistant cannot serve to HomeKit."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from homeassistant.helpers import issue_registry

from .const import DEFAULT_REENCODE, DOMAIN
from .recording.constants import RECORDING_RESOLUTIONS

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import (
        HomeKitSecureVideoConfigData,
        HomeKitSecureVideoConfigEntry,
        HomeKitSecureVideoOptionsData,
        HomeKitSecureVideoSourceProfile,
    )

ISSUE_NO_STREAM_SOURCE = "no_stream_source"
ISSUE_UNSUPPORTED_CODEC = "unsupported_codec"
ISSUE_OVERSIZED_SOURCE = "oversized_source"
ISSUE_RECORDER_UNAVAILABLE = "recorder_unavailable"

SUPPORTED_VIDEO_CODEC = "h264"


def async_review_camera_source(
    hass: HomeAssistant,
    entry: HomeKitSecureVideoConfigEntry,
    source_profile: HomeKitSecureVideoSourceProfile,
    *,
    has_stream_source: bool,
) -> None:
    """
    Raise or clear the repair issues the probed camera stream warrants.

    Every issue is re-evaluated on each start, so a camera that is pointed at
    another stream clears its own issue on the next reload.
    """
    config = cast("HomeKitSecureVideoConfigData", entry.data)
    options = cast("HomeKitSecureVideoOptionsData", entry.options)
    camera_entity_id = config["camera_entity_id"]
    codec = source_profile.get("video_codec")
    width = source_profile.get("width")
    height = source_profile.get("height")
    largest_width, largest_height, _ = RECORDING_RESOLUTIONS[-1]

    _async_apply(
        hass,
        entry,
        ISSUE_NO_STREAM_SOURCE,
        raised=not has_stream_source,
        placeholders={"camera": camera_entity_id},
    )
    _async_apply(
        hass,
        entry,
        ISSUE_UNSUPPORTED_CODEC,
        raised=codec is not None and codec != SUPPORTED_VIDEO_CODEC,
        placeholders={"camera": camera_entity_id, "codec": str(codec)},
    )
    _async_apply(
        hass,
        entry,
        ISSUE_OVERSIZED_SOURCE,
        # Only a problem while copying: re-encoding scales the picture down
        # to what HomeKit negotiated.
        raised=not options.get("reencode", DEFAULT_REENCODE)
        and width is not None
        and height is not None
        and (width > largest_width or height > largest_height),
        placeholders={
            "camera": camera_entity_id,
            "source_resolution": f"{width}x{height}",
            "offered_resolution": f"{largest_width}x{largest_height}",
        },
    )


def async_review_recorder_health(
    hass: HomeAssistant,
    entry: HomeKitSecureVideoConfigEntry,
    *,
    failing: bool,
) -> None:
    """
    Report a camera whose recorder cannot stay up, and withdraw it when it can.

    Unlike the issues above this one is not decided by the probe: it is the
    encoder giving up over and over, which nothing else surfaces — the hub
    keeps asking, every answer is a rejection at debug level, and the camera
    quietly records nothing.
    """
    config = cast("HomeKitSecureVideoConfigData", entry.data)
    _async_apply(
        hass,
        entry,
        ISSUE_RECORDER_UNAVAILABLE,
        raised=failing,
        placeholders={"camera": config["camera_entity_id"]},
    )


def _async_apply(
    hass: HomeAssistant,
    entry: HomeKitSecureVideoConfigEntry,
    issue: str,
    *,
    raised: bool,
    placeholders: dict[str, str],
) -> None:
    """Create the issue when it applies, and withdraw it when it stops."""
    issue_id = f"{entry.entry_id}_{issue}"
    if not raised:
        issue_registry.async_delete_issue(hass, DOMAIN, issue_id)
        return
    issue_registry.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=issue_registry.IssueSeverity.WARNING,
        translation_key=issue,
        translation_placeholders={"entry": entry.title, **placeholders},
    )


def async_clear_camera_source_issues(
    hass: HomeAssistant, entry: HomeKitSecureVideoConfigEntry
) -> None:
    """Withdraw every issue raised for an entry that is going away."""
    for issue in (
        ISSUE_NO_STREAM_SOURCE,
        ISSUE_UNSUPPORTED_CODEC,
        ISSUE_OVERSIZED_SOURCE,
        ISSUE_RECORDER_UNAVAILABLE,
    ):
        issue_registry.async_delete_issue(hass, DOMAIN, f"{entry.entry_id}_{issue}")
