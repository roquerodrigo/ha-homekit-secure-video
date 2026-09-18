"""What HomeKit negotiated with the accessory, kept across restarts."""

from __future__ import annotations

from typing import TypedDict


class HomeKitSecureVideoRecordingState(TypedDict):
    """
    The recording state a home hub expects to find where it left it.

    A hub remembers what it negotiated and does not negotiate it again on
    every connection, so an accessory that restarts empty has to take the
    negotiation back from disk — the same state the reference implementation
    persists, keyed by a fingerprint of the offer it was negotiated against.
    """

    supported_configuration_fingerprint: str
    selected_configuration: str | None
    recording_active: bool
    recording_audio_active: bool
    event_snapshots_active: bool
    homekit_camera_active: bool
    periodic_snapshots_active: bool
