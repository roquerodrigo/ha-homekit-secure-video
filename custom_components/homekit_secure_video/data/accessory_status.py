"""Typed status of the published HomeKit accessory."""

from __future__ import annotations

from typing import TypedDict


class HomeKitSecureVideoAccessoryStatus(TypedDict):
    """Status of the published HomeKit accessory."""

    pairing_code: str
    setup_uri: str
    paired: bool
    streaming: bool
    recording: bool
    camera_mode: str | None
    last_recording: str | None
