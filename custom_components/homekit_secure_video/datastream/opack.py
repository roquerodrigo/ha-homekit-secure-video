"""OPACK codec, the binary format HomeKit Data Stream messages are written in."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Final

from ..exceptions import HomeKitSecureVideoOpackError

if TYPE_CHECKING:
    from ..data import OpackValue

TAG_TRUE: Final = 0x01
TAG_FALSE: Final = 0x02
TAG_TERMINATOR: Final = 0x03
TAG_NULL: Final = 0x04
TAG_UUID: Final = 0x05
TAG_DATE: Final = 0x06
TAG_INT_MINUS_ONE: Final = 0x07
TAG_SMALL_INT_START: Final = 0x08
TAG_SMALL_INT_STOP: Final = 0x2F
TAG_INT8: Final = 0x30
TAG_INT16: Final = 0x31
TAG_INT32: Final = 0x32
TAG_INT64: Final = 0x33
TAG_FLOAT32: Final = 0x35
TAG_FLOAT64: Final = 0x36
TAG_STRING_START: Final = 0x40
TAG_STRING_STOP: Final = 0x60
TAG_STRING_LENGTH8: Final = 0x61
TAG_STRING_LENGTH16: Final = 0x62
TAG_STRING_LENGTH32: Final = 0x63
TAG_STRING_LENGTH64: Final = 0x64
TAG_STRING_TERMINATED: Final = 0x6F
TAG_BYTES_START: Final = 0x70
TAG_BYTES_STOP: Final = 0x90
TAG_BYTES_LENGTH8: Final = 0x91
TAG_BYTES_LENGTH16: Final = 0x92
TAG_BYTES_LENGTH32: Final = 0x93
TAG_BYTES_LENGTH64: Final = 0x94
TAG_POINTER_START: Final = 0xA0
TAG_POINTER_STOP: Final = 0xCF
TAG_ARRAY_START: Final = 0xD0
TAG_ARRAY_STOP: Final = 0xDE
TAG_ARRAY_TERMINATED: Final = 0xDF
TAG_DICT_START: Final = 0xE0
TAG_DICT_STOP: Final = 0xEE
TAG_DICT_TERMINATED: Final = 0xEF

INLINE_LENGTH_LIMIT: Final = 32
MAX_INLINE_ARRAY_LENGTH: Final = 12
MAX_INLINE_DICT_LENGTH: Final = 14

# The controller decodes 0x08+n as the integer n, and HAP-NodeJS stops its own
# decoder one tag short of 39 — so 39 is written as an int8 instead of the
# one-byte form no peer is guaranteed to read back.
MAX_SMALL_INT: Final = 38

_APPLE_EPOCH_OFFSET_SECONDS: Final = 978307200

# Data stream messages nest a handful of levels; the ceiling only exists so a
# payload built to nest thousands raises the codec error instead of a
# RecursionError, which is the one failure the connection cannot catch.
MAX_NESTING_DEPTH: Final = 32

_INT8_MIN: Final = -128
_INT8_MAX: Final = 127
_INT16_MIN: Final = -32768
_INT16_MAX: Final = 32767
_INT32_MIN: Final = -2147483648
_INT32_MAX: Final = 2147483647
_LENGTH8_MAX: Final = 0xFF
_LENGTH16_MAX: Final = 0xFFFF
_LENGTH32_MAX: Final = 0xFFFFFFFF


class _Terminator:
    """Marks the end of a terminated array or dictionary."""


_TERMINATOR: Final = _Terminator()


def encode(value: OpackValue) -> bytes:
    """Encode a value into its OPACK representation."""
    parts: list[bytes] = []
    _encode_value(value, parts)
    return b"".join(parts)


def decode(data: bytes) -> OpackValue:
    """Decode the OPACK representation of a single value."""
    value, index = _decode_value(data, 0, [], 0)
    if index != len(data):
        message = f"Failed to decode OPACK: {len(data) - index} trailing bytes"
        raise HomeKitSecureVideoOpackError(message)
    if isinstance(value, _Terminator):
        message = "Failed to decode OPACK: unexpected terminator"
        raise HomeKitSecureVideoOpackError(message)
    return value


def _encode_value(value: OpackValue, parts: list[bytes]) -> None:
    """
    Append the OPACK representation of one value.

    Values are never written as back-references (tags 0xA0-0xCF). The
    back-reference index counts every scalar the *decoder* has seen, and
    HAP-NodeJS's writer skips booleans while its reader tracks them — so the
    two sides disagree on the index the moment a payload carries a boolean.
    Writing values out in full costs a few bytes and cannot desynchronise.
    """
    if value is None:
        parts.append(bytes([TAG_NULL]))
    elif isinstance(value, bool):
        parts.append(bytes([TAG_TRUE if value else TAG_FALSE]))
    elif isinstance(value, int):
        _encode_int(value, parts)
    elif isinstance(value, float):
        parts.append(bytes([TAG_FLOAT64]) + struct.pack("<d", value))
    elif isinstance(value, str):
        _encode_string(value, parts)
    elif isinstance(value, bytes):
        _encode_bytes(value, parts)
    elif isinstance(value, list):
        _encode_array(value, parts)
    elif isinstance(value, dict):
        _encode_dict(value, parts)
    else:
        # Unreachable for a well-typed OpackValue; kept because a wrong value
        # here would otherwise be encoded as nothing at all.
        message = f"Failed to encode OPACK: unsupported type {type(value).__name__}"  # type: ignore[unreachable]
        raise HomeKitSecureVideoOpackError(message)


def _encode_int(value: int, parts: list[bytes]) -> None:
    """Append the smallest integer representation that fits the value."""
    if value == -1:
        parts.append(bytes([TAG_INT_MINUS_ONE]))
    elif 0 <= value <= MAX_SMALL_INT:
        parts.append(bytes([TAG_SMALL_INT_START + value]))
    elif _INT8_MIN <= value <= _INT8_MAX:
        parts.append(bytes([TAG_INT8]) + struct.pack("<b", value))
    elif _INT16_MIN <= value <= _INT16_MAX:
        parts.append(bytes([TAG_INT16]) + struct.pack("<h", value))
    elif _INT32_MIN <= value <= _INT32_MAX:
        parts.append(bytes([TAG_INT32]) + struct.pack("<i", value))
    else:
        try:
            packed = struct.pack("<q", value)
        except struct.error as exception:
            message = f"Failed to encode OPACK: integer {value} is out of range"
            raise HomeKitSecureVideoOpackError(message) from exception
        parts.append(bytes([TAG_INT64]) + packed)


def _encode_string(value: str, parts: list[bytes]) -> None:
    """Append a UTF-8 string with the narrowest length prefix."""
    encoded = value.encode("utf-8")
    parts.append(_length_prefix(len(encoded), TAG_STRING_START, TAG_STRING_LENGTH8))
    parts.append(encoded)


def _encode_bytes(value: bytes, parts: list[bytes]) -> None:
    """Append a byte string with the narrowest length prefix."""
    parts.append(_length_prefix(len(value), TAG_BYTES_START, TAG_BYTES_LENGTH8))
    parts.append(value)


def _length_prefix(length: int, inline_start: int, length8_tag: int) -> bytes:
    """Build the tag (and length field) for a string or byte string."""
    if length <= INLINE_LENGTH_LIMIT:
        return bytes([inline_start + length])
    if length <= _LENGTH8_MAX:
        return bytes([length8_tag]) + struct.pack("<B", length)
    if length <= _LENGTH16_MAX:
        return bytes([length8_tag + 1]) + struct.pack("<H", length)
    if length <= _LENGTH32_MAX:
        return bytes([length8_tag + 2]) + struct.pack("<I", length)
    return bytes([length8_tag + 3]) + struct.pack("<Q", length)


def _encode_array(value: list[OpackValue], parts: list[bytes]) -> None:
    """Append an array, inline when short enough and terminated otherwise."""
    terminated = len(value) > MAX_INLINE_ARRAY_LENGTH
    parts.append(
        bytes([TAG_ARRAY_TERMINATED if terminated else TAG_ARRAY_START + len(value)])
    )
    for element in value:
        _encode_value(element, parts)
    if terminated:
        parts.append(bytes([TAG_TERMINATOR]))


def _encode_dict(value: dict[str, OpackValue], parts: list[bytes]) -> None:
    """Append a dictionary, inline when short enough and terminated otherwise."""
    terminated = len(value) > MAX_INLINE_DICT_LENGTH
    parts.append(
        bytes([TAG_DICT_TERMINATED if terminated else TAG_DICT_START + len(value)])
    )
    for key, entry in value.items():
        _encode_value(key, parts)
        _encode_value(entry, parts)
    if terminated:
        parts.append(bytes([TAG_TERMINATOR]))


def _decode_value(  # noqa: PLR0911, PLR0912 -- one branch per OPACK tag range
    data: bytes, index: int, tracked: list[OpackValue], depth: int
) -> tuple[OpackValue | _Terminator, int]:
    """
    Decode one value, returning it and the index just past it.

    ``tracked`` collects every scalar decoded so far: a back-reference tag
    (0xA0-0xCF) carries the position of an earlier value in that list, so the
    order values are appended in has to match what the peer's encoder assumed.
    """
    tag = _read_tag(data, index)
    index += 1

    if tag == TAG_NULL:
        return None, index
    if tag == TAG_TERMINATOR:
        return _TERMINATOR, index
    if tag in (TAG_TRUE, TAG_FALSE):
        boolean = tag == TAG_TRUE
        tracked.append(boolean)
        return boolean, index
    if tag == TAG_INT_MINUS_ONE:
        tracked.append(-1)
        return -1, index
    if TAG_SMALL_INT_START <= tag <= TAG_SMALL_INT_STOP:
        small_int = tag - TAG_SMALL_INT_START
        tracked.append(small_int)
        return small_int, index
    if tag in _FIXED_WIDTH_FORMATS:
        return _decode_fixed_width(data, index, tag, tracked)
    if tag == TAG_DATE:
        return _decode_date(data, index, tracked)
    if tag == TAG_UUID:
        uuid_bytes = _read(data, index, 16)
        tracked.append(uuid_bytes)
        return uuid_bytes, index + 16
    if TAG_STRING_START <= tag <= TAG_STRING_STOP:
        return _decode_string(data, index, tag - TAG_STRING_START, tracked)
    if TAG_STRING_LENGTH8 <= tag <= TAG_STRING_LENGTH64:
        length, index = _decode_length(data, index, tag - TAG_STRING_LENGTH8)
        return _decode_string(data, index, length, tracked)
    if TAG_BYTES_START <= tag <= TAG_BYTES_STOP:
        return _decode_bytes(data, index, tag - TAG_BYTES_START, tracked)
    if TAG_BYTES_LENGTH8 <= tag <= TAG_BYTES_LENGTH64:
        length, index = _decode_length(data, index, tag - TAG_BYTES_LENGTH8)
        return _decode_bytes(data, index, length, tracked)
    if TAG_POINTER_START <= tag <= TAG_POINTER_STOP:
        return _decode_pointer(tag - TAG_POINTER_START, tracked), index
    if TAG_ARRAY_START <= tag <= TAG_ARRAY_TERMINATED:
        return _decode_array(data, index, tag, tracked, depth + 1)
    if TAG_DICT_START <= tag <= TAG_DICT_TERMINATED:
        return _decode_dict(data, index, tag, tracked, depth + 1)

    message = f"Failed to decode OPACK: unknown tag 0x{tag:02x} at offset {index - 1}"
    raise HomeKitSecureVideoOpackError(message)


_FIXED_WIDTH_FORMATS: Final[dict[int, str]] = {
    TAG_INT8: "<b",
    TAG_INT16: "<h",
    TAG_INT32: "<i",
    TAG_INT64: "<q",
    TAG_FLOAT32: "<f",
    TAG_FLOAT64: "<d",
}


def _decode_fixed_width(
    data: bytes, index: int, tag: int, tracked: list[OpackValue]
) -> tuple[OpackValue, int]:
    """Decode one of the fixed-width numeric forms."""
    number_format = _FIXED_WIDTH_FORMATS[tag]
    width = struct.calcsize(number_format)
    value: int | float = struct.unpack(number_format, _read(data, index, width))[0]
    tracked.append(value)
    return value, index + width


def _decode_date(
    data: bytes, index: int, tracked: list[OpackValue]
) -> tuple[float, int]:
    """Decode an Apple epoch timestamp into a Unix timestamp."""
    seconds: float = struct.unpack("<d", _read(data, index, 8))[0]
    timestamp = seconds + _APPLE_EPOCH_OFFSET_SECONDS
    tracked.append(timestamp)
    return timestamp, index + 8


def _decode_length(data: bytes, index: int, width_index: int) -> tuple[int, int]:
    """Decode an 8/16/32/64-bit little-endian length field."""
    number_format = ("<B", "<H", "<I", "<Q")[width_index]
    width = struct.calcsize(number_format)
    length: int = struct.unpack(number_format, _read(data, index, width))[0]
    return length, index + width


def _decode_string(
    data: bytes, index: int, length: int, tracked: list[OpackValue]
) -> tuple[str, int]:
    """Decode a UTF-8 string of the given length."""
    try:
        value = _read(data, index, length).decode("utf-8")
    except UnicodeDecodeError as exception:
        message = f"Failed to decode OPACK: invalid UTF-8 at offset {index}"
        raise HomeKitSecureVideoOpackError(message) from exception
    tracked.append(value)
    return value, index + length


def _decode_bytes(
    data: bytes, index: int, length: int, tracked: list[OpackValue]
) -> tuple[bytes, int]:
    """Decode a byte string of the given length."""
    value = _read(data, index, length)
    tracked.append(value)
    return value, index + length


def _decode_pointer(pointer: int, tracked: list[OpackValue]) -> OpackValue:
    """Resolve a back-reference to an earlier scalar."""
    if pointer >= len(tracked):
        message = (
            f"Failed to decode OPACK: back-reference {pointer} "
            f"past the {len(tracked)} values seen"
        )
        raise HomeKitSecureVideoOpackError(message)
    return tracked[pointer]


def _decode_array(
    data: bytes, index: int, tag: int, tracked: list[OpackValue], depth: int
) -> tuple[list[OpackValue], int]:
    """Decode an inline or terminated array."""
    _guard_depth(depth)
    elements: list[OpackValue] = []
    if tag == TAG_ARRAY_TERMINATED:
        while True:
            element, index = _decode_value(data, index, tracked, depth)
            if isinstance(element, _Terminator):
                return elements, index
            elements.append(element)

    for _ in range(tag - TAG_ARRAY_START):
        element, index = _decode_value(data, index, tracked, depth)
        if isinstance(element, _Terminator):
            message = "Failed to decode OPACK: terminator inside a sized array"
            raise HomeKitSecureVideoOpackError(message)
        elements.append(element)
    return elements, index


def _decode_dict(
    data: bytes, index: int, tag: int, tracked: list[OpackValue], depth: int
) -> tuple[dict[str, OpackValue], int]:
    """Decode an inline or terminated dictionary."""
    _guard_depth(depth)
    entries: dict[str, OpackValue] = {}
    terminated = tag == TAG_DICT_TERMINATED
    remaining = -1 if terminated else tag - TAG_DICT_START

    while terminated or remaining > 0:
        key, index = _decode_value(data, index, tracked, depth)
        if isinstance(key, _Terminator):
            if terminated:
                return entries, index
            message = "Failed to decode OPACK: terminator inside a sized dictionary"
            raise HomeKitSecureVideoOpackError(message)
        if not isinstance(key, str):
            message = (
                f"Failed to decode OPACK: dictionary key is a "
                f"{type(key).__name__}, expected a string"
            )
            raise HomeKitSecureVideoOpackError(message)

        value, index = _decode_value(data, index, tracked, depth)
        if isinstance(value, _Terminator):
            message = "Failed to decode OPACK: terminator where a value was expected"
            raise HomeKitSecureVideoOpackError(message)
        entries[key] = value
        remaining -= 1

    return entries, index


def _guard_depth(depth: int) -> None:
    """Fail before the interpreter does on a payload built to nest deeply."""
    if depth > MAX_NESTING_DEPTH:
        message = f"Failed to decode OPACK: nested past {MAX_NESTING_DEPTH} levels"
        raise HomeKitSecureVideoOpackError(message)


def _read_tag(data: bytes, index: int) -> int:
    """Read the tag byte at the given index."""
    return _read(data, index, 1)[0]


def _read(data: bytes, index: int, length: int) -> bytes:
    """Read a slice, failing loudly when the buffer is too short."""
    end = index + length
    if end > len(data):
        message = (
            f"Failed to decode OPACK: needed {length} bytes at offset {index}, "
            f"only {max(0, len(data) - index)} remain"
        )
        raise HomeKitSecureVideoOpackError(message)
    return data[index:end]
