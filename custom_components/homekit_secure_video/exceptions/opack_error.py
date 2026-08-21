"""Error raised when an OPACK payload cannot be encoded or decoded."""

from __future__ import annotations

from .data_stream_error import HomeKitSecureVideoDataStreamError


class HomeKitSecureVideoOpackError(HomeKitSecureVideoDataStreamError):
    """An OPACK payload could not be encoded or decoded."""
