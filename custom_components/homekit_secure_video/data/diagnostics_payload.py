"""Typed top-level shape returned by async_get_config_entry_diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from .accessory_status import HomeKitSecureVideoAccessoryStatus
    from .diagnostics_entry import HomeKitSecureVideoDiagnosticsEntry
    from .recording_diagnostics import HomeKitSecureVideoRecordingDiagnostics
    from .source_profile import HomeKitSecureVideoSourceProfile


class HomeKitSecureVideoDiagnosticsPayload(TypedDict):
    """Top-level shape returned by async_get_config_entry_diagnostics."""

    entry: HomeKitSecureVideoDiagnosticsEntry
    accessory: HomeKitSecureVideoAccessoryStatus | None
    services: list[str]
    data_stream_port: int | None
    camera_source: HomeKitSecureVideoSourceProfile
    recording: HomeKitSecureVideoRecordingDiagnostics
