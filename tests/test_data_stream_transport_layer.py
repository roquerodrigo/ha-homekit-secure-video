from __future__ import annotations

import pytest

from custom_components.homekit_secure_video.datastream.constants import (
    HomeKitSecureVideoDataStreamMessageType,
    HomeKitSecureVideoDataStreamStatus,
)
from custom_components.homekit_secure_video.datastream.frame import (
    HomeKitSecureVideoDataStreamFrame,
    build_header,
    split_frames,
)
from custom_components.homekit_secure_video.datastream.frame_codec import (
    HomeKitSecureVideoDataStreamFrameCodec,
)
from custom_components.homekit_secure_video.datastream.message import (
    HomeKitSecureVideoDataStreamMessage,
)
from custom_components.homekit_secure_video.datastream.session_keys import (
    HomeKitSecureVideoDataStreamSessionKeys,
)
from custom_components.homekit_secure_video.exceptions import (
    HomeKitSecureVideoDataStreamError,
)

SHARED_KEY = bytes(range(32))
CONTROLLER_SALT = bytes(range(32, 64))


def _mirror(keys: HomeKitSecureVideoDataStreamSessionKeys):
    """Return the codec the controller would build from the same keys."""
    return HomeKitSecureVideoDataStreamFrameCodec(
        HomeKitSecureVideoDataStreamSessionKeys(
            accessory_to_controller=keys.controller_to_accessory,
            controller_to_accessory=keys.accessory_to_controller,
            accessory_key_salt=keys.accessory_key_salt,
        )
    )


def test_keys_are_thirty_two_bytes_and_differ_per_direction():
    keys = HomeKitSecureVideoDataStreamSessionKeys.derive(SHARED_KEY, CONTROLLER_SALT)

    assert len(keys.accessory_to_controller) == 32
    assert len(keys.controller_to_accessory) == 32
    assert len(keys.accessory_key_salt) == 32
    assert keys.accessory_to_controller != keys.controller_to_accessory


def test_every_session_gets_a_fresh_salt():
    first = HomeKitSecureVideoDataStreamSessionKeys.derive(SHARED_KEY, CONTROLLER_SALT)
    second = HomeKitSecureVideoDataStreamSessionKeys.derive(SHARED_KEY, CONTROLLER_SALT)

    assert first.accessory_key_salt != second.accessory_key_salt
    assert first.accessory_to_controller != second.accessory_to_controller


def test_keys_are_reproducible_from_the_same_salts():
    keys = HomeKitSecureVideoDataStreamSessionKeys.derive(SHARED_KEY, CONTROLLER_SALT)
    repeated = HomeKitSecureVideoDataStreamSessionKeys(
        accessory_to_controller=b"",
        controller_to_accessory=b"",
        accessory_key_salt=keys.accessory_key_salt,
    )
    from pyhap.hap_crypto import hap_hkdf

    assert keys.accessory_to_controller == hap_hkdf(
        SHARED_KEY,
        CONTROLLER_SALT + repeated.accessory_key_salt,
        b"HDS-Read-Encryption-Key",
    )


def test_header_encodes_a_twenty_four_bit_length():
    assert build_header(1) == b"\x01\x00\x00\x01"
    assert build_header(0x10000) == b"\x01\x01\x00\x00"


def test_header_rejects_an_oversized_payload():
    with pytest.raises(HomeKitSecureVideoDataStreamError, match="exceeds"):
        build_header(0x100000)


def test_split_frames_keeps_a_partial_frame_in_the_buffer():
    frame = HomeKitSecureVideoDataStreamFrame(
        header=build_header(4), ciphertext=b"abcd", auth_tag=b"t" * 16
    )
    frames, remaining = split_frames(frame.raw[:-1])

    assert frames == []
    assert remaining == frame.raw[:-1]


def test_split_frames_returns_every_complete_frame():
    first = HomeKitSecureVideoDataStreamFrame(
        header=build_header(2), ciphertext=b"ab", auth_tag=b"1" * 16
    )
    second = HomeKitSecureVideoDataStreamFrame(
        header=build_header(3), ciphertext=b"cde", auth_tag=b"2" * 16
    )

    frames, remaining = split_frames(first.raw + second.raw + b"\x01")

    assert [frame.ciphertext for frame in frames] == [b"ab", b"cde"]
    assert remaining == b"\x01"


def test_split_frames_rejects_an_unknown_frame_type():
    with pytest.raises(HomeKitSecureVideoDataStreamError, match="frame type"):
        split_frames(b"\x02\x00\x00\x01")


def test_codec_round_trips_a_payload():
    keys = HomeKitSecureVideoDataStreamSessionKeys.derive(SHARED_KEY, CONTROLLER_SALT)
    accessory = HomeKitSecureVideoDataStreamFrameCodec(keys)
    controller = _mirror(keys)

    frames, _ = split_frames(accessory.encrypt(b"payload"))

    assert controller.decrypt(frames[0]) == b"payload"


def test_codec_advances_the_nonce_per_frame():
    keys = HomeKitSecureVideoDataStreamSessionKeys.derive(SHARED_KEY, CONTROLLER_SALT)
    accessory = HomeKitSecureVideoDataStreamFrameCodec(keys)
    controller = _mirror(keys)

    first = accessory.encrypt(b"one")
    second = accessory.encrypt(b"two")
    frames, _ = split_frames(first + second)

    assert [controller.decrypt(frame) for frame in frames] == [b"one", b"two"]


def test_codec_rejects_a_frame_out_of_order():
    keys = HomeKitSecureVideoDataStreamSessionKeys.derive(SHARED_KEY, CONTROLLER_SALT)
    accessory = HomeKitSecureVideoDataStreamFrameCodec(keys)
    controller = _mirror(keys)

    accessory.encrypt(b"one")
    frames, _ = split_frames(accessory.encrypt(b"two"))

    assert controller.decrypt(frames[0]) is None


def test_codec_keeps_its_nonce_after_a_failed_decryption():
    keys = HomeKitSecureVideoDataStreamSessionKeys.derive(SHARED_KEY, CONTROLLER_SALT)
    accessory = HomeKitSecureVideoDataStreamFrameCodec(keys)
    controller = _mirror(keys)
    other = HomeKitSecureVideoDataStreamFrameCodec(
        HomeKitSecureVideoDataStreamSessionKeys.derive(SHARED_KEY, CONTROLLER_SALT)
    )

    frames, _ = split_frames(accessory.encrypt(b"payload"))
    assert other.decrypt(frames[0]) is None
    assert controller.decrypt(frames[0]) == b"payload"


def test_message_round_trips_a_request():
    message = HomeKitSecureVideoDataStreamMessage(
        message_type=HomeKitSecureVideoDataStreamMessageType.REQUEST,
        protocol="control",
        topic="hello",
        payload={},
        identifier=7,
    )

    decoded = HomeKitSecureVideoDataStreamMessage.from_payload(message.to_payload())

    assert decoded == message


def test_message_round_trips_a_response_with_a_status():
    message = HomeKitSecureVideoDataStreamMessage(
        message_type=HomeKitSecureVideoDataStreamMessageType.RESPONSE,
        protocol="dataSend",
        topic="open",
        payload={"status": 0},
        identifier=3,
        status=HomeKitSecureVideoDataStreamStatus.SUCCESS,
    )

    decoded = HomeKitSecureVideoDataStreamMessage.from_payload(message.to_payload())

    assert decoded == message


def test_message_round_trips_an_event_with_binary_payload():
    message = HomeKitSecureVideoDataStreamMessage(
        message_type=HomeKitSecureVideoDataStreamMessageType.EVENT,
        protocol="dataSend",
        topic="data",
        payload={"packets": [{"data": b"\x00\x01", "metadata": {"dataType": "x"}}]},
    )

    decoded = HomeKitSecureVideoDataStreamMessage.from_payload(message.to_payload())

    assert decoded == message


def test_message_rejects_an_empty_payload():
    with pytest.raises(HomeKitSecureVideoDataStreamError, match="empty payload"):
        HomeKitSecureVideoDataStreamMessage.from_payload(b"")


def test_message_rejects_a_header_longer_than_the_payload():
    with pytest.raises(HomeKitSecureVideoDataStreamError, match="does not fit"):
        HomeKitSecureVideoDataStreamMessage.from_payload(b"\x20\xe0")


def test_message_rejects_a_header_without_a_protocol():
    from custom_components.homekit_secure_video.datastream import opack

    header = opack.encode({"request": "hello"})
    payload = bytes([len(header)]) + header + opack.encode({})

    with pytest.raises(HomeKitSecureVideoDataStreamError, match="no protocol"):
        HomeKitSecureVideoDataStreamMessage.from_payload(payload)


def test_message_rejects_a_header_without_a_topic():
    from custom_components.homekit_secure_video.datastream import opack

    header = opack.encode({"protocol": "control"})
    payload = bytes([len(header)]) + header + opack.encode({})

    with pytest.raises(HomeKitSecureVideoDataStreamError, match="no event"):
        HomeKitSecureVideoDataStreamMessage.from_payload(payload)


def test_message_rejects_a_non_dictionary_body():
    from custom_components.homekit_secure_video.datastream import opack

    header = opack.encode({"protocol": "control", "event": "x"})
    payload = bytes([len(header)]) + header + opack.encode([1])

    with pytest.raises(HomeKitSecureVideoDataStreamError, match="not a dictionary"):
        HomeKitSecureVideoDataStreamMessage.from_payload(payload)


def test_message_drops_an_unknown_status_code():
    from custom_components.homekit_secure_video.datastream import opack

    header = opack.encode({"protocol": "p", "response": "t", "id": 1, "status": 99})
    payload = bytes([len(header)]) + header + opack.encode({})

    assert HomeKitSecureVideoDataStreamMessage.from_payload(payload).status is None
