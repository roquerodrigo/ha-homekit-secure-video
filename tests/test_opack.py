from __future__ import annotations

import pytest

from custom_components.homekit_secure_video.datastream import opack
from custom_components.homekit_secure_video.exceptions import (
    HomeKitSecureVideoOpackError,
)

ROUND_TRIP_VALUES = [
    None,
    True,
    False,
    -1,
    0,
    38,
    39,
    127,
    -128,
    1000,
    -32768,
    100000,
    -2147483648,
    9007199254740991,
    1.5,
    "",
    "hello",
    "a" * 32,
    "a" * 33,
    "a" * 300,
    "a" * 70000,
    b"",
    b"\x00\xff",
    b"x" * 33,
    b"x" * 300,
    [],
    [1, 2, 3],
    list(range(20)),
    {},
    {"protocol": "control", "request": "hello"},
    {f"key{index}": index for index in range(20)},
    {"nested": {"list": [1, "two", b"three", None, True]}},
]


@pytest.mark.parametrize("value", ROUND_TRIP_VALUES, ids=repr)
def test_round_trip(value):
    assert opack.decode(opack.encode(value)) == value


def test_small_integers_use_one_byte():
    assert opack.encode(0) == b"\x08"
    assert opack.encode(38) == b"\x2e"


def test_thirty_nine_avoids_the_ambiguous_tag():
    # HAP-NodeJS stops its decoder at 0x2e, so 39 must not be written as 0x2f.
    assert opack.encode(39) == b"\x30\x27"


def test_minus_one_has_its_own_tag():
    assert opack.encode(-1) == b"\x07"


def test_short_string_is_inline():
    assert opack.encode("hi") == b"\x42hi"


def test_booleans_and_null_have_fixed_tags():
    assert opack.encode(True) == b"\x01"
    assert opack.encode(False) == b"\x02"
    assert opack.encode(None) == b"\x04"


def test_dictionary_of_fifteen_entries_is_terminated():
    encoded = opack.encode({str(index): index for index in range(15)})
    assert encoded[0] == 0xEF
    assert encoded[-1] == 0x03


def test_array_of_thirteen_entries_is_terminated():
    encoded = opack.encode(list(range(13)))
    assert encoded[0] == 0xDF
    assert encoded[-1] == 0x03


def test_decodes_a_back_reference_to_a_repeated_string():
    # {"a": "value", "b": <pointer to "value">}
    encoded = b"\xe2\x41a\x45value\x41b\xa1"
    assert opack.decode(encoded) == {"a": "value", "b": "value"}


def test_decodes_a_back_reference_after_a_boolean():
    # {"a": true, "b": "x", "c": <pointer index 2 -> "x">}
    encoded = b"\xe3\x41a\x01\x41b\x41x\x41c\xa3"
    assert opack.decode(encoded) == {"a": True, "b": "x", "c": "x"}


def test_decodes_the_small_integer_tag_the_encoder_avoids():
    assert opack.decode(b"\x2f") == 39


def test_decodes_a_null_terminated_array():
    assert opack.decode(b"\xdf\x08\x09\x03") == [0, 1]


def test_decodes_a_uuid_as_raw_bytes():
    raw = bytes(range(16))
    assert opack.decode(b"\x05" + raw) == raw


def test_decodes_a_date_into_a_unix_timestamp():
    import struct

    assert opack.decode(b"\x06" + struct.pack("<d", 0.0)) == 978307200


def test_rejects_trailing_bytes():
    with pytest.raises(HomeKitSecureVideoOpackError, match="trailing"):
        opack.decode(b"\x08\x08")


def test_rejects_a_truncated_payload():
    with pytest.raises(HomeKitSecureVideoOpackError, match="needed"):
        opack.decode(b"\x45hi")


def test_rejects_an_unknown_tag():
    with pytest.raises(HomeKitSecureVideoOpackError, match="unknown tag"):
        opack.decode(b"\x00")


def test_rejects_an_out_of_range_back_reference():
    with pytest.raises(HomeKitSecureVideoOpackError, match="back-reference"):
        opack.decode(b"\xa5")


def test_rejects_a_non_string_dictionary_key():
    with pytest.raises(HomeKitSecureVideoOpackError, match="dictionary key"):
        opack.decode(b"\xe1\x08\x08")


def test_rejects_invalid_utf8():
    with pytest.raises(HomeKitSecureVideoOpackError, match="UTF-8"):
        opack.decode(b"\x41\xff")


def test_rejects_a_bare_terminator():
    with pytest.raises(HomeKitSecureVideoOpackError, match="terminator"):
        opack.decode(b"\x03")


def test_rejects_an_unsupported_type():
    with pytest.raises(HomeKitSecureVideoOpackError, match="unsupported type"):
        opack.encode(object())


def test_rejects_an_unrepresentable_integer():
    with pytest.raises(HomeKitSecureVideoOpackError, match="out of range"):
        opack.encode(2**70)
