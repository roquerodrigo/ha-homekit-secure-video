"""Counters describing how much a recording session delivered."""

from __future__ import annotations

from typing import TypedDict


class HomeKitSecureVideoRecordingStatistics(TypedDict):
    """How much one recording session delivered to the hub."""

    fragments_sent: int
    bytes_sent: int
