"""The DataStreamTransportManagement service and its setup handshake."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Final
from uuid import UUID

from pyhap import tlv
from pyhap.characteristic import Characteristic
from pyhap.service import Service
from pyhap.util import to_base64_str

from ..const import LOGGER
from ..datastream.constants import KEY_SALT_LENGTH, PROTOCOL_VERSION
from ..exceptions import HomeKitSecureVideoDataStreamError
from .setup_data_stream_transport_characteristic import (
    HomeKitSecureVideoSetupDataStreamTransportCharacteristic,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..datastream import HomeKitSecureVideoDataStreamServer

SERVICE_UUID: Final = UUID("00000129-0000-1000-8000-0026BB765291")
SETUP_TRANSPORT_UUID: Final = UUID("00000131-0000-1000-8000-0026BB765291")
SUPPORTED_CONFIGURATION_UUID: Final = UUID("00000130-0000-1000-8000-0026BB765291")
VERSION_UUID: Final = UUID("00000037-0000-1000-8000-0026BB765291")

TRANSPORT_TYPE_HOMEKIT_DATA_STREAM: Final = b"\x00"
SESSION_COMMAND_START: Final = b"\x00"

TAG_TRANSFER_TRANSPORT_CONFIGURATION: Final = b"\x01"
TAG_TRANSPORT_TYPE: Final = b"\x01"

TAG_SESSION_COMMAND_TYPE: Final = b"\x01"
TAG_SETUP_TRANSPORT_TYPE: Final = b"\x02"
TAG_CONTROLLER_KEY_SALT: Final = b"\x03"

TAG_STATUS: Final = b"\x01"
TAG_SESSION_PARAMETERS: Final = b"\x02"
TAG_ACCESSORY_KEY_SALT: Final = b"\x03"
TAG_TCP_LISTENING_PORT: Final = b"\x01"

STATUS_SUCCESS: Final = b"\x00"


class HomeKitSecureVideoDataStreamTransportService:
    """
    The DataStreamTransportManagement service and its setup handshake.

    A controller writes here to open a data stream: it names the transport it
    wants and contributes half of the key salt, and gets back the port to
    connect to plus the accessory's half.
    """

    def __init__(
        self,
        data_stream_server: HomeKitSecureVideoDataStreamServer,
        shared_key_lookup: Callable[[str], bytes | None],
    ) -> None:
        """Initialize the service around a running data stream server."""
        self._data_stream_server = data_stream_server
        self._shared_key_lookup = shared_key_lookup
        self._last_response = ""
        self.service = self._build_service()

    def handle_setup_write(self, value: str, client_address: str) -> str:
        """Prepare a session for the writing controller and answer its parameters."""
        request = tlv.decode(value, from_base64=True)
        self._verify_request(request)

        shared_key = self._shared_key_lookup(client_address)
        if shared_key is None:
            message = (
                f"Failed to set up a data stream: no HAP session for {client_address}"
            )
            raise HomeKitSecureVideoDataStreamError(message)

        keys = self._data_stream_server.prepare_session(
            shared_key, request[TAG_CONTROLLER_KEY_SALT]
        )
        port = self._data_stream_server.port
        if port is None:
            message = "Failed to set up a data stream: server has no port"
            raise HomeKitSecureVideoDataStreamError(message)

        session_parameters = tlv.encode(TAG_TCP_LISTENING_PORT, struct.pack("<H", port))
        response = tlv.encode(
            TAG_STATUS,
            STATUS_SUCCESS,
            TAG_SESSION_PARAMETERS,
            session_parameters,
        )
        # A later read must not hand the accessory key salt to whoever asks:
        # it is only ever part of the answer to the write that produced it.
        self._last_response = to_base64_str(response)
        LOGGER.debug(
            "Prepared a data stream session for %s on port %s", client_address, port
        )

        return to_base64_str(
            response + tlv.encode(TAG_ACCESSORY_KEY_SALT, keys.accessory_key_salt)
        )

    def _verify_request(self, request: dict[bytes, bytes]) -> None:
        """Reject anything but a start request for the HomeKit Data Stream."""
        command = request.get(TAG_SESSION_COMMAND_TYPE)
        transport = request.get(TAG_SETUP_TRANSPORT_TYPE)
        controller_key_salt = request.get(TAG_CONTROLLER_KEY_SALT)

        if command != SESSION_COMMAND_START:
            message = f"Failed to set up a data stream: unsupported command {command!r}"
            raise HomeKitSecureVideoDataStreamError(message)
        if transport != TRANSPORT_TYPE_HOMEKIT_DATA_STREAM:
            message = (
                f"Failed to set up a data stream: unsupported transport {transport!r}"
            )
            raise HomeKitSecureVideoDataStreamError(message)
        if controller_key_salt is None or len(controller_key_salt) != KEY_SALT_LENGTH:
            message = "Failed to set up a data stream: malformed controller key salt"
            raise HomeKitSecureVideoDataStreamError(message)

    def _build_service(self) -> Service:
        """Build the service with its three characteristics."""
        service = Service(SERVICE_UUID, "DataStreamTransportManagement")
        service.add_characteristic(
            HomeKitSecureVideoSetupDataStreamTransportCharacteristic(
                "Setup Data Stream Transport",
                SETUP_TRANSPORT_UUID,
                {"Format": "tlv8", "Permissions": ["pr", "pw", "wr"]},
                self.handle_setup_write,
            )
        )
        service.add_characteristic(
            _characteristic(
                "Supported Data Stream Transport Configuration",
                SUPPORTED_CONFIGURATION_UUID,
                {"Format": "tlv8", "Permissions": ["pr"]},
                _supported_configuration(),
            )
        )
        service.add_characteristic(
            _characteristic(
                "Version",
                VERSION_UUID,
                {"Format": "string", "Permissions": ["pr"]},
                PROTOCOL_VERSION,
            )
        )
        return service


def _supported_configuration() -> str:
    """Build the TLV advertising that only HomeKit Data Stream is supported."""
    transport_type = tlv.encode(TAG_TRANSPORT_TYPE, TRANSPORT_TYPE_HOMEKIT_DATA_STREAM)
    return to_base64_str(
        tlv.encode(TAG_TRANSFER_TRANSPORT_CONFIGURATION, transport_type)
    )


def _characteristic(
    display_name: str,
    type_id: UUID,
    properties: dict[str, str | list[str]],
    value: str,
) -> Characteristic:
    """Build a read-only characteristic carrying a fixed value."""
    characteristic = Characteristic(display_name, type_id, properties)
    characteristic.value = value
    return characteristic
