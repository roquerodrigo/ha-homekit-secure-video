"""Custom types for homekit_secure_video."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from .accessory_status import HomeKitSecureVideoAccessoryStatus
from .camera_options import HomeKitSecureVideoCameraOptions
from .config_data import HomeKitSecureVideoConfigData
from .diagnostics_entry import HomeKitSecureVideoDiagnosticsEntry
from .diagnostics_payload import HomeKitSecureVideoDiagnosticsPayload
from .options_data import HomeKitSecureVideoOptionsData
from .recording_diagnostics import (
    HomeKitSecureVideoRecorderDiagnostics,
    HomeKitSecureVideoRecordingDiagnostics,
)
from .recording_statistics import HomeKitSecureVideoRecordingStatistics
from .runtime import HomeKitSecureVideoData
from .source_profile import HomeKitSecureVideoSourceProfile
from .stream_request import HomeKitSecureVideoStreamRequest
from .stream_session_info import HomeKitSecureVideoStreamSessionInfo

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list[JsonValue] | Mapping[str, JsonValue]
type JsonObject = Mapping[str, JsonValue]

type OpackValue = (
    bool | int | float | str | bytes | list[OpackValue] | dict[str, OpackValue] | None
)

type HomeKitSecureVideoConfigEntry = ConfigEntry[HomeKitSecureVideoData]

__all__ = [
    "HomeKitSecureVideoAccessoryStatus",
    "HomeKitSecureVideoCameraOptions",
    "HomeKitSecureVideoConfigData",
    "HomeKitSecureVideoConfigEntry",
    "HomeKitSecureVideoData",
    "HomeKitSecureVideoDiagnosticsEntry",
    "HomeKitSecureVideoDiagnosticsPayload",
    "HomeKitSecureVideoOptionsData",
    "HomeKitSecureVideoRecorderDiagnostics",
    "HomeKitSecureVideoRecordingDiagnostics",
    "HomeKitSecureVideoRecordingStatistics",
    "HomeKitSecureVideoSourceProfile",
    "HomeKitSecureVideoStreamRequest",
    "HomeKitSecureVideoStreamSessionInfo",
    "JsonObject",
    "JsonPrimitive",
    "JsonValue",
    "OpackValue",
]
