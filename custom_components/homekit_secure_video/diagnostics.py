"""Diagnostics support for homekit_secure_video."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from homeassistant.components.diagnostics import async_redact_data

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.core import HomeAssistant

    from .data import (
        HomeKitSecureVideoAccessoryStatus,
        HomeKitSecureVideoConfigEntry,
        HomeKitSecureVideoDiagnosticsEntry,
        HomeKitSecureVideoDiagnosticsPayload,
    )

TO_REDACT: frozenset[str] = frozenset({"pairing_code", "setup_uri"})


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,  # noqa: ARG001
    entry: HomeKitSecureVideoConfigEntry,
) -> HomeKitSecureVideoDiagnosticsPayload:
    """Return diagnostics for a config entry."""
    redacted_data = cast(
        "Mapping[str, str]",
        async_redact_data(dict(entry.data), set(TO_REDACT)),
    )
    redacted_options = cast(
        "Mapping[str, str | int]",
        async_redact_data(dict(entry.options), set(TO_REDACT)),
    )
    diag_entry: HomeKitSecureVideoDiagnosticsEntry = {
        "title": entry.title,
        "version": entry.version,
        "domain": entry.domain,
        "data": redacted_data,
        "options": redacted_options,
    }
    accessory_manager = entry.runtime_data.accessory_manager
    accessory_status = cast(
        "HomeKitSecureVideoAccessoryStatus",
        async_redact_data(dict(accessory_manager.status), set(TO_REDACT)),
    )
    return {
        "entry": diag_entry,
        "accessory": accessory_status,
        "services": list(accessory_manager.published_services),
        "data_stream_port": accessory_manager.data_stream_port,
        "camera_source": await accessory_manager.async_probe_camera(),
        "recording": accessory_manager.recording_diagnostics,
    }
