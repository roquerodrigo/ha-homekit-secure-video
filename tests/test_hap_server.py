from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.homekit_secure_video.accessory.hap_server import (
    HomeKitSecureVideoHapServer,
    HomeKitSecureVideoHapServerProtocol,
)

SHARED_KEY = b"\x11" * 32
PEERNAME = ("192.168.1.10", 55123)


@pytest.fixture
def shared_keys():
    return {}


@pytest.fixture
def protocol(hass, shared_keys):
    connection = HomeKitSecureVideoHapServerProtocol(
        hass.loop, {}, MagicMock(), shared_keys
    )
    connection.peername = PEERNAME
    connection.handler = MagicMock()
    return connection


def _response(shared_key=None):
    response = MagicMock()
    response.task = None
    response.shared_key = shared_key
    response.pairing_changed = False
    return response


def test_the_shared_key_is_retained_after_pair_verify(protocol, shared_keys):
    protocol.send_response = MagicMock()

    protocol._process_response(_response(SHARED_KEY))

    assert shared_keys[str(PEERNAME)] == SHARED_KEY


def test_a_response_without_a_key_changes_nothing(protocol, shared_keys):
    protocol.send_response = MagicMock()

    protocol._process_response(_response())

    assert shared_keys == {}


def test_closing_the_connection_forgets_the_key(protocol, shared_keys):
    protocol.send_response = MagicMock()
    protocol.transport = MagicMock()
    protocol._process_response(_response(SHARED_KEY))

    protocol.close()

    assert shared_keys == {}


async def test_the_driver_exposes_the_key_of_a_session(hass, tmp_path):
    from custom_components.homekit_secure_video.accessory import (
        HomeKitSecureVideoAccessoryDriver,
    )

    driver = HomeKitSecureVideoAccessoryDriver(
        lambda: None,
        address="127.0.0.1",
        port=21064,
        persist_file=str(tmp_path / "accessory.state"),
        loop=hass.loop,
    )

    assert isinstance(driver.http_server, HomeKitSecureVideoHapServer)
    assert driver.shared_key_for(str(PEERNAME)) is None

    driver.http_server.shared_keys[str(PEERNAME)] = SHARED_KEY
    assert driver.shared_key_for(str(PEERNAME)) == SHARED_KEY


async def test_the_hap_server_accepts_connections(hass, socket_enabled):
    server = HomeKitSecureVideoHapServer(("127.0.0.1", 0), MagicMock())
    await server.async_start(hass.loop)

    try:
        assert server.server is not None
        assert server.server.sockets
    finally:
        server.async_stop()


def test_an_unverified_pairing_request_is_answered(hass):
    from custom_components.homekit_secure_video.accessory.hap_server import (
        HomeKitSecureVideoHapServerHandler,
    )

    handler = HomeKitSecureVideoHapServerHandler(MagicMock(), PEERNAME)
    handler.client_uuid = None
    handler._send_authentication_error_tlv_response = MagicMock()

    handler.handle_pairings()

    handler._send_authentication_error_tlv_response.assert_called_once()


def test_a_verified_pairing_request_reaches_hap_python(hass):
    from unittest.mock import patch

    from custom_components.homekit_secure_video.accessory.hap_server import (
        HomeKitSecureVideoHapServerHandler,
    )

    handler = HomeKitSecureVideoHapServerHandler(MagicMock(), PEERNAME)
    handler.client_uuid = "4188f444-c793-4970-9a44-970748d64b04"

    with patch("pyhap.hap_handler.HAPServerHandler.handle_pairings") as handle_pairings:
        handler.handle_pairings()

    handle_pairings.assert_called_once()


async def test_the_connection_uses_our_handler(hass, shared_keys):
    connection = HomeKitSecureVideoHapServerProtocol(
        hass.loop, {}, MagicMock(), shared_keys
    )
    transport = MagicMock()
    transport.get_extra_info = MagicMock(return_value=PEERNAME)

    connection.connection_made(transport)

    from custom_components.homekit_secure_video.accessory.hap_server import (
        HomeKitSecureVideoHapServerHandler,
    )

    assert isinstance(connection.handler, HomeKitSecureVideoHapServerHandler)
