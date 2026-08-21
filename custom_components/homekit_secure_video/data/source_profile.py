"""Typed description of what a camera actually sends."""

from __future__ import annotations

from typing import TypedDict


class HomeKitSecureVideoSourceProfile(TypedDict):
    """What the camera actually sends, as reported by ffprobe."""

    video_codec: str | None
    video_profile: str | None
    video_level: int | None
    width: int | None
    height: int | None
    frame_rate: float | None
    audio_codec: str | None
    audio_sample_rate: int | None
