"""Error raised when a recording cannot be negotiated or produced."""

from __future__ import annotations


class HomeKitSecureVideoRecordingError(Exception):
    """A recording could not be negotiated or produced."""
