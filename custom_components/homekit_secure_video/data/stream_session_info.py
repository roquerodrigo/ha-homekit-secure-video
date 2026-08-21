"""Typed shape of the HomeKit stream session handed over by HAP-python."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from uuid import UUID


class HomeKitSecureVideoStreamSessionInfo(TypedDict):
    """Identity of a HomeKit stream session."""

    id: UUID
    stream_idx: int
