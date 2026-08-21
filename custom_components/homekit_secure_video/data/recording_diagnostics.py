"""Typed diagnostics of the recording side of an accessory."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from .recording_statistics import HomeKitSecureVideoRecordingStatistics


class HomeKitSecureVideoRecorderDiagnostics(TypedDict):
    """State of the ffmpeg process feeding the recordings."""

    running: bool
    has_initialization_segment: bool
    prebuffer_capacity: int
    prebuffered_fragments: int
    prebuffered_bytes: int


class HomeKitSecureVideoRecordingDiagnostics(TypedDict):
    """State of the negotiation and delivery of recordings."""

    enabled: bool
    audio_enabled: bool
    in_flight: bool
    recordings_started: int
    selected_configuration: dict[str, int | str] | None
    last_session: HomeKitSecureVideoRecordingStatistics | None
    recorder: HomeKitSecureVideoRecorderDiagnostics
