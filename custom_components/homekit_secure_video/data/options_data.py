"""Typed shape of the options writable by the options flow."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class HomeKitSecureVideoOptionsData(TypedDict, total=False):
    """Shape of the options writable by the options flow."""

    max_width: NotRequired[int]
    max_height: NotRequired[int]
    max_fps: NotRequired[int]
    reencode: NotRequired[bool]
    stream_audio: NotRequired[bool]
