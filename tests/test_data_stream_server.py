from __future__ import annotations

import asyncio

import pytest

from custom_components.homekit_secure_video.datastream import (
    HomeKitSecureVideoDataStreamMessage,
    HomeKitSecureVideoDataStreamMessageType,
    HomeKitSecureVideoDataStreamServer,
    HomeKitSecureVideoDataStreamSessionKeys,
    HomeKitSecureVideoDataStreamStatus,
)
from custom_components.homekit_secure_video.datastream.frame import split_frames
from custom_components.homekit_secure_video.datastream.frame_codec import (
    HomeKitSecureVideoDataStreamFrameCodec,
)
from custom_components.homekit_secure_video.exceptions import (
    HomeKitSecureVideoDataStreamError,
)

SHARED_KEY = bytes(range(32))
CONTROLLER_SALT = bytes(range(32, 64))


class FakeController:
    """The controller side of a HomeKit Data Stream connection."""

    def __init__(self, keys: HomeKitSecureVideoDataStreamSessionKeys) -> None:
        self._codec = HomeKitSecureVideoDataStreamFrameCodec(
            HomeKitSecureVideoDataStreamSessionKeys(
                accessory_to_controller=keys.controller_to_accessory,
                controller_to_accessory=keys.accessory_to_controller,
                accessory_key_salt=keys.accessory_key_salt,
            )
        )
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._buffer = b""

    async def async_connect(self, port: int) -> None:
        self._reader, self._writer = await asyncio.open_connection("127.0.0.1", port)

    async def async_send(self, message: HomeKitSecureVideoDataStreamMessage) -> None:
        assert self._writer is not None
        self._writer.write(self._codec.encrypt(message.to_payload()))
        await self._writer.drain()

    async def async_receive(self) -> HomeKitSecureVideoDataStreamMessage:
        assert self._reader is not None
        while True:
            frames, self._buffer = split_frames(self._buffer)
            if frames:
                payload = self._codec.decrypt(frames[0])
                assert payload is not None
                return HomeKitSecureVideoDataStreamMessage.from_payload(payload)
            chunk = await self._reader.read(4096)
            if not chunk:
                message = "connection closed"
                raise AssertionError(message)
            self._buffer += chunk

    async def async_close(self) -> None:
        if self._writer is not None:
            self._writer.close()


def _hello(identifier: int = 1) -> HomeKitSecureVideoDataStreamMessage:
    return HomeKitSecureVideoDataStreamMessage(
        message_type=HomeKitSecureVideoDataStreamMessageType.REQUEST,
        protocol="control",
        topic="hello",
        payload={},
        identifier=identifier,
    )


@pytest.fixture
async def server(socket_enabled):
    data_stream_server = HomeKitSecureVideoDataStreamServer()
    await data_stream_server.async_start("127.0.0.1")
    yield data_stream_server
    await data_stream_server.async_stop()


async def test_server_listens_on_an_ephemeral_port(server):
    assert server.port is not None
    assert server.port > 0


async def test_preparing_a_session_needs_a_running_server():
    stopped = HomeKitSecureVideoDataStreamServer()

    with pytest.raises(HomeKitSecureVideoDataStreamError, match="not running"):
        stopped.prepare_session(SHARED_KEY, CONTROLLER_SALT)


async def test_starting_twice_keeps_the_same_port(server):
    port = server.port
    await server.async_start("127.0.0.1")
    assert server.port == port


async def test_controller_completes_the_handshake(server):
    keys = server.prepare_session(SHARED_KEY, CONTROLLER_SALT)
    controller = FakeController(keys)
    await controller.async_connect(server.port)

    await controller.async_send(_hello(identifier=7))
    response = await asyncio.wait_for(controller.async_receive(), timeout=5)

    assert response.message_type == HomeKitSecureVideoDataStreamMessageType.RESPONSE
    assert response.protocol == "control"
    assert response.topic == "hello"
    assert response.identifier == 7
    assert response.status == HomeKitSecureVideoDataStreamStatus.SUCCESS
    await controller.async_close()


async def test_handshake_consumes_the_prepared_session(server):
    keys = server.prepare_session(SHARED_KEY, CONTROLLER_SALT)
    controller = FakeController(keys)
    await controller.async_connect(server.port)
    await controller.async_send(_hello())
    await asyncio.wait_for(controller.async_receive(), timeout=5)

    assert server.prepared_sessions == ()
    assert len(server.connections) == 1
    await controller.async_close()


async def test_messages_reach_the_registered_handler(server):
    received: list[HomeKitSecureVideoDataStreamMessage] = []
    server.register_handler(
        "dataSend", "open", lambda _connection, message: received.append(message)
    )
    keys = server.prepare_session(SHARED_KEY, CONTROLLER_SALT)
    controller = FakeController(keys)
    await controller.async_connect(server.port)
    await controller.async_send(_hello())
    await asyncio.wait_for(controller.async_receive(), timeout=5)

    await controller.async_send(
        HomeKitSecureVideoDataStreamMessage(
            message_type=HomeKitSecureVideoDataStreamMessageType.REQUEST,
            protocol="dataSend",
            topic="open",
            payload={"streamId": 42, "type": "ipcamera.recording"},
            identifier=2,
        )
    )
    async with asyncio.timeout(5):
        while not received:
            await asyncio.sleep(0)

    assert received[0].payload["streamId"] == 42
    await controller.async_close()


async def test_a_message_without_a_handler_is_ignored(server):
    keys = server.prepare_session(SHARED_KEY, CONTROLLER_SALT)
    controller = FakeController(keys)
    await controller.async_connect(server.port)
    await controller.async_send(_hello())
    await asyncio.wait_for(controller.async_receive(), timeout=5)

    await controller.async_send(
        HomeKitSecureVideoDataStreamMessage(
            message_type=HomeKitSecureVideoDataStreamMessageType.EVENT,
            protocol="targetControl",
            topic="whoami",
            payload={},
        )
    )
    await asyncio.sleep(0)

    assert len(server.connections) == 1
    await controller.async_close()


async def test_a_connection_with_unknown_keys_is_dropped(server):
    server.prepare_session(SHARED_KEY, CONTROLLER_SALT)
    stranger = FakeController(
        HomeKitSecureVideoDataStreamSessionKeys.derive(b"\x99" * 32, CONTROLLER_SALT)
    )
    await stranger.async_connect(server.port)
    await stranger.async_send(_hello())

    async with asyncio.timeout(5):
        while server.connections:
            await asyncio.sleep(0)

    assert server.prepared_sessions != ()
    await stranger.async_close()


async def test_a_first_message_that_is_not_hello_is_dropped(server):
    keys = server.prepare_session(SHARED_KEY, CONTROLLER_SALT)
    controller = FakeController(keys)
    await controller.async_connect(server.port)
    await controller.async_send(
        HomeKitSecureVideoDataStreamMessage(
            message_type=HomeKitSecureVideoDataStreamMessageType.EVENT,
            protocol="dataSend",
            topic="data",
            payload={},
        )
    )

    async with asyncio.timeout(5):
        while server.connections:
            await asyncio.sleep(0)

    await controller.async_close()


async def test_a_prepared_session_expires_when_nobody_connects(server):
    server.prepare_session(SHARED_KEY, CONTROLLER_SALT)
    session = server.prepared_sessions[0]

    session.cancel_expiry()
    server._discard_session(session)

    assert server.prepared_sessions == ()


async def test_the_server_binds_a_single_socket(server):
    assert len({socket.getsockname()[1] for socket in server._server.sockets}) == 1


async def test_stopping_the_server_closes_the_connections(server):
    keys = server.prepare_session(SHARED_KEY, CONTROLLER_SALT)
    controller = FakeController(keys)
    await controller.async_connect(server.port)
    await controller.async_send(_hello())
    await asyncio.wait_for(controller.async_receive(), timeout=5)

    await server.async_stop()

    assert server.connections == ()
    assert server.port is None
    await controller.async_close()


async def test_a_malformed_frame_closes_the_connection(server):
    server.prepare_session(SHARED_KEY, CONTROLLER_SALT)
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    writer.write(b"\x02\x00\x00\x01\x00")
    await writer.drain()

    assert await asyncio.wait_for(reader.read(1), timeout=5) == b""
    writer.close()


async def test_a_connection_that_never_greets_is_dropped(server, monkeypatch):
    from custom_components.homekit_secure_video.datastream import connection as module

    monkeypatch.setattr(module, "HELLO_TIMEOUT_SECONDS", 0)
    server.prepare_session(SHARED_KEY, CONTROLLER_SALT)
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)

    assert await asyncio.wait_for(reader.read(1), timeout=5) == b""
    writer.close()


async def test_an_unreadable_message_is_ignored(server):
    keys = server.prepare_session(SHARED_KEY, CONTROLLER_SALT)
    controller = FakeController(keys)
    await controller.async_connect(server.port)
    await controller.async_send(_hello())
    await asyncio.wait_for(controller.async_receive(), timeout=5)

    controller._writer.write(controller._codec.encrypt(b"\x20not-a-message"))
    await controller._writer.drain()
    await asyncio.sleep(0)

    assert len(server.connections) == 1
    await controller.async_close()


async def test_sending_before_the_handshake_is_dropped(server):
    from custom_components.homekit_secure_video.datastream.connection import (
        HomeKitSecureVideoDataStreamConnection,
    )

    connection = HomeKitSecureVideoDataStreamConnection(server)
    connection.send_event("dataSend", "data", {})

    assert not connection.is_ready


async def test_a_closed_connection_notifies_its_listeners(server):
    closed: list[object] = []
    server.register_connection_closed_listener(closed.append)
    keys = server.prepare_session(SHARED_KEY, CONTROLLER_SALT)
    controller = FakeController(keys)
    await controller.async_connect(server.port)
    await controller.async_send(_hello())
    await asyncio.wait_for(controller.async_receive(), timeout=5)
    connection = server.connections[0]

    await controller.async_close()
    async with asyncio.timeout(5):
        while not closed:
            await asyncio.sleep(0)

    assert closed == [connection]
    assert server.connections == ()
