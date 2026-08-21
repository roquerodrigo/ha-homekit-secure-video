from __future__ import annotations

import struct
from unittest.mock import MagicMock

import pytest
from pyhap import tlv
from pyhap.util import to_base64_str

from custom_components.homekit_secure_video.accessory.data_stream_transport import (
    HomeKitSecureVideoDataStreamTransportService,
)
from custom_components.homekit_secure_video.datastream import (
    HomeKitSecureVideoDataStreamServer,
)
from custom_components.homekit_secure_video.exceptions import (
    HomeKitSecureVideoDataStreamError,
)

CLIENT_ADDRESS = "('192.168.1.10', 55123)"
SHARED_KEY = bytes(range(32))
CONTROLLER_SALT = bytes(range(32, 64))
DATA_STREAM_PORT = 45678


def _setup_request(
    command: bytes = b"\x00",
    transport: bytes = b"\x00",
    salt: bytes = CONTROLLER_SALT,
) -> str:
    return to_base64_str(
        tlv.encode(b"\x01", command, b"\x02", transport, b"\x03", salt)
    )


@pytest.fixture
def data_stream_server():
    server = MagicMock(spec=HomeKitSecureVideoDataStreamServer)
    server.port = DATA_STREAM_PORT
    return server


@pytest.fixture
def transport_service(data_stream_server):
    return HomeKitSecureVideoDataStreamTransportService(
        data_stream_server, lambda _address: SHARED_KEY
    )


def test_setup_write_answers_with_the_listening_port(
    transport_service, data_stream_server
):
    keys = MagicMock(accessory_key_salt=b"\xaa" * 32)
    data_stream_server.prepare_session.return_value = keys

    response = tlv.decode(
        transport_service.handle_setup_write(_setup_request(), CLIENT_ADDRESS),
        from_base64=True,
    )

    assert response[b"\x01"] == b"\x00"
    assert tlv.decode(response[b"\x02"])[b"\x01"] == struct.pack("<H", DATA_STREAM_PORT)
    assert response[b"\x03"] == b"\xaa" * 32


def test_setup_write_prepares_the_session_with_the_controller_salt(
    transport_service, data_stream_server
):
    data_stream_server.prepare_session.return_value = MagicMock(
        accessory_key_salt=b"\xaa" * 32
    )

    transport_service.handle_setup_write(_setup_request(), CLIENT_ADDRESS)

    data_stream_server.prepare_session.assert_called_once_with(
        SHARED_KEY, CONTROLLER_SALT
    )


def test_readable_value_hides_the_accessory_key_salt(
    transport_service, data_stream_server
):
    data_stream_server.prepare_session.return_value = MagicMock(
        accessory_key_salt=b"\xaa" * 32
    )
    transport_service.handle_setup_write(_setup_request(), CLIENT_ADDRESS)

    readable = transport_service.service.get_characteristic(
        "Setup Data Stream Transport"
    ).value

    assert b"\x03" not in tlv.decode(readable, from_base64=True)


def test_setup_write_rejects_an_unknown_command(transport_service):
    with pytest.raises(HomeKitSecureVideoDataStreamError, match="unsupported command"):
        transport_service.handle_setup_write(
            _setup_request(command=b"\x01"), CLIENT_ADDRESS
        )


def test_setup_write_rejects_an_unknown_transport(transport_service):
    with pytest.raises(
        HomeKitSecureVideoDataStreamError, match="unsupported transport"
    ):
        transport_service.handle_setup_write(
            _setup_request(transport=b"\x01"), CLIENT_ADDRESS
        )


def test_setup_write_rejects_a_short_salt(transport_service):
    with pytest.raises(HomeKitSecureVideoDataStreamError, match="key salt"):
        transport_service.handle_setup_write(
            _setup_request(salt=b"\x00" * 16), CLIENT_ADDRESS
        )


def test_setup_write_rejects_an_unknown_hap_session(data_stream_server):
    service = HomeKitSecureVideoDataStreamTransportService(
        data_stream_server, lambda _address: None
    )

    with pytest.raises(HomeKitSecureVideoDataStreamError, match="no HAP session"):
        service.handle_setup_write(_setup_request(), CLIENT_ADDRESS)


def test_setup_write_fails_when_the_server_has_no_port(
    transport_service, data_stream_server
):
    data_stream_server.port = None
    data_stream_server.prepare_session.return_value = MagicMock(
        accessory_key_salt=b"\xaa" * 32
    )

    with pytest.raises(HomeKitSecureVideoDataStreamError, match="no port"):
        transport_service.handle_setup_write(_setup_request(), CLIENT_ADDRESS)


def test_characteristic_write_carries_the_writing_session(transport_service):
    characteristic = transport_service.service.get_characteristic(
        "Setup Data Stream Transport"
    )
    seen: list[str] = []
    characteristic._setup_callback = lambda _value, address: (
        seen.append(address) or "ok"
    )

    result = characteristic.client_update_value(
        _setup_request(), ("192.168.1.10", 55123)
    )

    assert result == "ok"
    assert seen == ["('192.168.1.10', 55123)"]
