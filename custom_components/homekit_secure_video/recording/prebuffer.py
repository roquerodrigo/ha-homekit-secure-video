"""A rolling window of the most recent recording fragments."""

from __future__ import annotations

import math
from collections import deque

from .constants import PREBUFFER_MARGIN


class HomeKitSecureVideoPrebuffer:
    """
    A rolling window of the most recent recording fragments.

    HomeKit asks for the seconds *before* the trigger, so fragments are kept
    around before anything requests them. The window holds more than HomeKit
    negotiated, because fragments keep arriving while an earlier recording is
    still being delivered.
    """

    def __init__(self, duration_milliseconds: int, fragment_milliseconds: int) -> None:
        """Size the window from the negotiated prebuffer and fragment length."""
        fragments = math.ceil(
            duration_milliseconds * PREBUFFER_MARGIN / max(1, fragment_milliseconds)
        )
        self._fragments: deque[bytes] = deque(maxlen=max(1, fragments))

    @property
    def fragments(self) -> tuple[bytes, ...]:
        """Return the buffered fragments, oldest first."""
        return tuple(self._fragments)

    @property
    def capacity(self) -> int:
        """Return how many fragments the window holds."""
        return self._fragments.maxlen or 0

    def append(self, fragment: bytes) -> None:
        """Add a fragment, dropping the oldest when the window is full."""
        self._fragments.append(fragment)

    def clear(self) -> None:
        """Drop every buffered fragment."""
        self._fragments.clear()
