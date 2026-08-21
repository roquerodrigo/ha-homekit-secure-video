"""One framed chunk of a HomeKit Data Stream connection."""

from __future__ import annotations

from dataclasses import dataclass

from ..exceptions import HomeKitSecureVideoDataStreamError
from .constants import (
    AUTH_TAG_LENGTH,
    FRAME_HEADER_LENGTH,
    FRAME_TYPE,
    MAX_PAYLOAD_LENGTH,
)


@dataclass(frozen=True)
class HomeKitSecureVideoDataStreamFrame:
    """One framed chunk of a HomeKit Data Stream connection."""

    header: bytes
    ciphertext: bytes
    auth_tag: bytes

    @property
    def raw(self) -> bytes:
        """Return the frame as it travels on the wire."""
        return self.header + self.ciphertext + self.auth_tag


def build_header(payload_length: int) -> bytes:
    """Build the frame header, which also authenticates the payload."""
    if payload_length > MAX_PAYLOAD_LENGTH:
        message = (
            f"Failed to frame a data stream payload: {payload_length} bytes "
            f"exceeds the {MAX_PAYLOAD_LENGTH} byte limit"
        )
        raise HomeKitSecureVideoDataStreamError(message)
    return bytes([FRAME_TYPE]) + payload_length.to_bytes(3, "big")


def split_frames(
    buffer: bytes,
) -> tuple[list[HomeKitSecureVideoDataStreamFrame], bytes]:
    """Split a receive buffer into complete frames plus the trailing remainder."""
    frames: list[HomeKitSecureVideoDataStreamFrame] = []
    index = 0

    while index + FRAME_HEADER_LENGTH <= len(buffer):
        frame_type = buffer[index]
        if frame_type != FRAME_TYPE:
            message = (
                f"Failed to read a data stream frame: unknown frame type {frame_type}"
            )
            raise HomeKitSecureVideoDataStreamError(message)

        payload_length = int.from_bytes(buffer[index + 1 : index + 4], "big")
        if payload_length > MAX_PAYLOAD_LENGTH:
            message = (
                f"Failed to read a data stream frame: payload of "
                f"{payload_length} bytes exceeds the limit"
            )
            raise HomeKitSecureVideoDataStreamError(message)

        end = index + FRAME_HEADER_LENGTH + payload_length + AUTH_TAG_LENGTH
        if end > len(buffer):
            break

        payload_begin = index + FRAME_HEADER_LENGTH
        auth_tag_begin = payload_begin + payload_length
        frames.append(
            HomeKitSecureVideoDataStreamFrame(
                header=buffer[index:payload_begin],
                ciphertext=buffer[payload_begin:auth_tag_begin],
                auth_tag=buffer[auth_tag_begin:end],
            )
        )
        index = end

    return frames, buffer[index:]
