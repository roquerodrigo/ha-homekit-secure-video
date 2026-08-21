"""Typed shape of the data persisted on the config entry."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class HomeKitSecureVideoConfigData(TypedDict):
    """Shape of the data persisted on the config entry."""

    camera_entity_id: str
    port: int
    pairing_code: str
    setup_id: str
    motion_entity_id: NotRequired[str]
    always_on_motion: NotRequired[bool]
