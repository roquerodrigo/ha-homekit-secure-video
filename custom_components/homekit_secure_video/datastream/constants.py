"""Wire constants of the HomeKit Data Stream protocol."""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Final

FRAME_TYPE: Final = 0x01
FRAME_HEADER_LENGTH: Final = 4
AUTH_TAG_LENGTH: Final = 16
NONCE_LENGTH: Final = 8
KEY_SALT_LENGTH: Final = 32
MAX_PAYLOAD_LENGTH: Final = 0xFFFFF

PROTOCOL_VERSION: Final = "1.0"
CONNECT_TIMEOUT_SECONDS: Final = 10
CLOSE_TIMEOUT_SECONDS: Final = 5
HELLO_TIMEOUT_SECONDS: Final = 10

ACCESSORY_TO_CONTROLLER_INFO: Final = b"HDS-Read-Encryption-Key"
CONTROLLER_TO_ACCESSORY_INFO: Final = b"HDS-Write-Encryption-Key"


class HomeKitSecureVideoDataStreamProtocolName(StrEnum):
    """Protocols carried over a HomeKit Data Stream."""

    CONTROL = "control"
    DATA_SEND = "dataSend"
    TARGET_CONTROL = "targetControl"


class HomeKitSecureVideoDataStreamTopic(StrEnum):
    """Topics grouped by the protocol they belong to."""

    HELLO = "hello"
    OPEN = "open"
    DATA = "data"
    ACK = "ack"
    CLOSE = "close"


class HomeKitSecureVideoDataStreamMessageType(IntEnum):
    """Kind of a HomeKit Data Stream message."""

    EVENT = 1
    REQUEST = 2
    RESPONSE = 3


class HomeKitSecureVideoDataStreamStatus(IntEnum):
    """Status a response carries."""

    SUCCESS = 0
    OUT_OF_MEMORY = 1
    TIMEOUT = 2
    HEADER_ERROR = 3
    PAYLOAD_ERROR = 4
    MISSING_PROTOCOL = 5
    PROTOCOL_SPECIFIC_ERROR = 6


class HomeKitSecureVideoDataStreamCloseReason(IntEnum):
    """Reason a dataSend stream was closed."""

    NORMAL = 0
    NOT_ALLOWED = 1
    BUSY = 2
    CANCELLED = 3
    UNSUPPORTED = 4
    UNEXPECTED_FAILURE = 5
    TIMEOUT = 6
    BAD_DATA = 7
    PROTOCOL_ERROR = 8
    INVALID_CONFIGURATION = 9
