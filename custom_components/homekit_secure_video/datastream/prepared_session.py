"""A data stream session negotiated over HAP, waiting for its TCP connection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio

    from .session_keys import HomeKitSecureVideoDataStreamSessionKeys


@dataclass
class HomeKitSecureVideoPreparedDataStreamSession:
    """A data stream session negotiated over HAP, waiting for its TCP connection."""

    keys: HomeKitSecureVideoDataStreamSessionKeys
    expiry: asyncio.TimerHandle | None = None

    def cancel_expiry(self) -> None:
        """Stop the timer that discards this session when nobody connects."""
        if self.expiry is not None:
            self.expiry.cancel()
            self.expiry = None
