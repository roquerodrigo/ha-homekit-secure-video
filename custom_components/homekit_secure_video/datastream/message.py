"""One decoded HomeKit Data Stream message."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from ..exceptions import HomeKitSecureVideoDataStreamError
from . import opack
from .constants import (
    HomeKitSecureVideoDataStreamMessageType,
    HomeKitSecureVideoDataStreamStatus,
)

if TYPE_CHECKING:
    from ..data import OpackValue

_TOPIC_KEY_BY_TYPE = {
    HomeKitSecureVideoDataStreamMessageType.EVENT: "event",
    HomeKitSecureVideoDataStreamMessageType.REQUEST: "request",
    HomeKitSecureVideoDataStreamMessageType.RESPONSE: "response",
}


@dataclass(frozen=True)
class HomeKitSecureVideoDataStreamMessage:
    """One decoded HomeKit Data Stream message."""

    message_type: HomeKitSecureVideoDataStreamMessageType
    protocol: str
    topic: str
    payload: dict[str, OpackValue]
    identifier: int | None = None
    status: HomeKitSecureVideoDataStreamStatus | None = None

    @classmethod
    def from_payload(cls, payload: bytes) -> Self:
        """Decode the header and message halves of a frame payload."""
        if not payload:
            message = "Failed to read a data stream message: empty payload"
            raise HomeKitSecureVideoDataStreamError(message)

        header_length = payload[0]
        header_end = 1 + header_length
        if header_end > len(payload):
            message = (
                f"Failed to read a data stream message: header of "
                f"{header_length} bytes does not fit the payload"
            )
            raise HomeKitSecureVideoDataStreamError(message)

        header = opack.decode(payload[1:header_end])
        body = opack.decode(payload[header_end:])
        if not isinstance(header, dict) or not isinstance(body, dict):
            message = "Failed to read a data stream message: header or body is not a dictionary"  # noqa: E501
            raise HomeKitSecureVideoDataStreamError(message)

        return cls._from_header(header, body)

    def to_payload(self) -> bytes:
        """Encode the message into the payload of a frame."""
        header: dict[str, OpackValue] = {
            "protocol": self.protocol,
            _TOPIC_KEY_BY_TYPE[self.message_type]: self.topic,
        }
        if self.identifier is not None:
            header["id"] = self.identifier
        if self.status is not None:
            header["status"] = int(self.status)

        encoded_header = opack.encode(header)
        return (
            bytes([len(encoded_header)]) + encoded_header + opack.encode(self.payload)
        )

    @classmethod
    def _from_header(
        cls, header: dict[str, OpackValue], body: dict[str, OpackValue]
    ) -> Self:
        """Build a message from its decoded header dictionary."""
        protocol = header.get("protocol")
        if not isinstance(protocol, str):
            message = "Failed to read a data stream message: no protocol in the header"
            raise HomeKitSecureVideoDataStreamError(message)

        for message_type, topic_key in _TOPIC_KEY_BY_TYPE.items():
            topic = header.get(topic_key)
            if isinstance(topic, str):
                return cls(
                    message_type=message_type,
                    protocol=protocol,
                    topic=topic,
                    payload=body,
                    identifier=_optional_int(header.get("id")),
                    status=_optional_status(header.get("status")),
                )

        message = (
            "Failed to read a data stream message: header names no event, "
            "request or response"
        )
        raise HomeKitSecureVideoDataStreamError(message)


def _optional_int(value: OpackValue) -> int | None:
    """Return the value when it is an integer, and None otherwise."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_status(value: OpackValue) -> HomeKitSecureVideoDataStreamStatus | None:
    """Return the value as a status, keeping unknown codes out."""
    status = _optional_int(value)
    if status is None:
        return None
    try:
        return HomeKitSecureVideoDataStreamStatus(status)
    except ValueError:
        return None
