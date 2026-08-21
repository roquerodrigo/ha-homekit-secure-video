"""Reads a fragmented MP4 stream as an initialization segment plus fragments."""

from __future__ import annotations

import asyncio
import struct
from typing import TYPE_CHECKING

from ..exceptions import HomeKitSecureVideoRecordingError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

BOX_HEADER_LENGTH = 8
LARGE_SIZE_LENGTH = 8
LARGE_SIZE_MARKER = 1

INITIALIZATION_BOXES = (b"ftyp", b"moov")
FRAGMENT_BOXES = (b"moof", b"mdat")


async def read_segments(
    reader: asyncio.StreamReader,
) -> AsyncIterator[tuple[bool, bytes]]:
    """
    Yield ``(is_initialization, payload)`` for every segment of the stream.

    A fragmented MP4 starts with ``ftyp`` and ``moov`` — together the
    initialization segment every recording has to open with — and then repeats
    ``moof``/``mdat`` pairs, one media fragment each.
    """
    pending: list[bytes] = []

    while True:
        box = await _read_box(reader)
        if box is None:
            return

        box_type, raw = box
        pending.append(raw)

        if box_type == INITIALIZATION_BOXES[-1]:
            yield True, b"".join(pending)
            pending = []
        elif box_type == FRAGMENT_BOXES[-1]:
            yield False, b"".join(pending)
            pending = []


async def _read_box(reader: asyncio.StreamReader) -> tuple[bytes, bytes] | None:
    """Read one MP4 box, or return None at the end of the stream."""
    try:
        header = await reader.readexactly(BOX_HEADER_LENGTH)
    except asyncio.IncompleteReadError, ConnectionResetError:
        return None
    if not header:
        return None

    size = int(struct.unpack(">I", header[:4])[0])
    box_type = header[4:8]

    if size == LARGE_SIZE_MARKER:
        try:
            large = await reader.readexactly(LARGE_SIZE_LENGTH)
        except asyncio.IncompleteReadError, ConnectionResetError:
            return None
        size = int(struct.unpack(">Q", large)[0])
        header += large

    body_length = size - len(header)
    if body_length < 0:
        message = (
            f"Failed to read the MP4 stream: box {box_type!r} declares {size} bytes"
        )
        raise HomeKitSecureVideoRecordingError(message)

    try:
        body = await reader.readexactly(body_length)
    except asyncio.IncompleteReadError, ConnectionResetError:
        return None

    return box_type, header + body
