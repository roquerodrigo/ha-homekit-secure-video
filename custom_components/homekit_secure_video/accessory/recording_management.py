"""The CameraRecordingManagement service and the recordings it delivers."""

from __future__ import annotations

from dataclasses import fields
from enum import IntEnum
from typing import TYPE_CHECKING, Final
from uuid import UUID

from homeassistant.util import dt as dt_util
from pyhap.characteristic import Characteristic
from pyhap.service import Service

from ..const import LOGGER
from ..datastream import (
    HomeKitSecureVideoDataStreamCloseReason,
    HomeKitSecureVideoDataStreamProtocolName,
    HomeKitSecureVideoDataStreamStatus,
    HomeKitSecureVideoDataStreamTopic,
)
from ..exceptions import HomeKitSecureVideoRecordingError
from ..recording import (
    HomeKitSecureVideoRecordingSession,
    HomeKitSecureVideoSelectedConfiguration,
)
from ..recording.constants import (
    DATA_SEND_TARGET_CONTROLLER,
    DATA_SEND_TYPE_RECORDING,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from ..data import (
        HomeKitSecureVideoRecordingDiagnostics,
        HomeKitSecureVideoRecordingStatistics,
    )
    from ..datastream import (
        HomeKitSecureVideoDataStreamConnection,
        HomeKitSecureVideoDataStreamMessage,
        HomeKitSecureVideoDataStreamServer,
    )
    from ..recording import (
        HomeKitSecureVideoRecorder,
        HomeKitSecureVideoSupportedConfiguration,
    )
    from .camera_operating_mode import HomeKitSecureVideoCameraOperatingModeService
from .selected_recording_configuration_characteristic import (
    HomeKitSecureVideoSelectedRecordingConfigurationCharacteristic,
)

SERVICE_UUID: Final = UUID("00000204-0000-1000-8000-0026BB765291")
ACTIVE_UUID: Final = UUID("000000B0-0000-1000-8000-0026BB765291")
SUPPORTED_CAMERA_UUID: Final = UUID("00000205-0000-1000-8000-0026BB765291")
SUPPORTED_VIDEO_UUID: Final = UUID("00000206-0000-1000-8000-0026BB765291")
SUPPORTED_AUDIO_UUID: Final = UUID("00000207-0000-1000-8000-0026BB765291")
SELECTED_CONFIGURATION_UUID: Final = UUID("00000209-0000-1000-8000-0026BB765291")
RECORDING_AUDIO_ACTIVE_UUID: Final = UUID("00000226-0000-1000-8000-0026BB765291")

ACTIVE = "Active"
SELECTED_CAMERA_RECORDING_CONFIGURATION = "SelectedCameraRecordingConfiguration"
RECORDING_AUDIO_ACTIVE = "RecordingAudioActive"


def _readable(value: object) -> int | str:
    """Render one negotiated field for the diagnostics dump."""
    if isinstance(value, IntEnum):
        return value.name
    return value if isinstance(value, int) else str(value)


class HomeKitSecureVideoRecordingManagementService:
    """
    The CameraRecordingManagement service and the recordings it delivers.

    HomeKit negotiates one recording configuration here, switches recording on,
    and from then on opens a dataSend stream on the data stream connection
    whenever the linked motion sensor fires.
    """

    def __init__(
        self,
        supported: HomeKitSecureVideoSupportedConfiguration,
        recorder: HomeKitSecureVideoRecorder,
        operating_mode: HomeKitSecureVideoCameraOperatingModeService,
        data_stream_server: HomeKitSecureVideoDataStreamServer,
        recording_state_changed: Callable[[], None],
    ) -> None:
        """Initialize the service around a recorder and a data stream server."""
        self._supported = supported
        self._recorder = recorder
        self._operating_mode = operating_mode
        self._recording_state_changed = recording_state_changed
        self._selected: HomeKitSecureVideoSelectedConfiguration | None = None
        self._selected_value: str | None = None
        self._last_recording: datetime | None = None
        self._session: HomeKitSecureVideoRecordingSession | None = None
        self._recordings_started = 0
        self._last_statistics: HomeKitSecureVideoRecordingStatistics | None = None
        self.service = self._build_service()

        data_stream_server.register_handler(
            HomeKitSecureVideoDataStreamProtocolName.DATA_SEND,
            HomeKitSecureVideoDataStreamTopic.OPEN,
            self._handle_open,
        )
        data_stream_server.register_handler(
            HomeKitSecureVideoDataStreamProtocolName.DATA_SEND,
            HomeKitSecureVideoDataStreamTopic.ACK,
            self._handle_acknowledgement,
        )
        data_stream_server.register_handler(
            HomeKitSecureVideoDataStreamProtocolName.DATA_SEND,
            HomeKitSecureVideoDataStreamTopic.CLOSE,
            self._handle_close,
        )
        data_stream_server.register_connection_closed_listener(
            self._handle_connection_closed
        )

    @property
    def is_recording_enabled(self) -> bool:
        """Return whether HomeKit switched recording on."""
        return bool(self.service.get_characteristic(ACTIVE).value)

    @property
    def is_audio_enabled(self) -> bool:
        """Return whether HomeKit wants audio in the recordings."""
        return bool(self.service.get_characteristic(RECORDING_AUDIO_ACTIVE).value)

    @property
    def selected_configuration(self) -> HomeKitSecureVideoSelectedConfiguration | None:
        """Return the configuration HomeKit negotiated, if any."""
        return self._selected

    @property
    def last_recording(self) -> datetime | None:
        """Return when the last recording finished being delivered."""
        return self._last_recording

    @property
    def diagnostics(self) -> HomeKitSecureVideoRecordingDiagnostics:
        """Report what HomeKit negotiated and what has been delivered."""
        selected = self._selected
        return {
            "enabled": self.is_recording_enabled,
            "audio_enabled": self.is_audio_enabled,
            "in_flight": self.is_recording_in_flight,
            "recordings_started": self._recordings_started,
            "selected_configuration": (
                {
                    field.name: _readable(getattr(selected, field.name))
                    for field in fields(selected)
                }
                if selected is not None
                else None
            ),
            "last_session": self._last_statistics,
            "recorder": self._recorder.diagnostics,
        }

    @property
    def is_recording_in_flight(self) -> bool:
        """Return whether a recording is being delivered right now."""
        return self._session is not None and not self._session.is_closed

    def stop_recording(self) -> None:
        """Ask the recording in flight, if any, to finish."""
        if self._session is not None:
            self._session.request_stop()

    def abort_recording(
        self,
        reason: HomeKitSecureVideoDataStreamCloseReason = (
            HomeKitSecureVideoDataStreamCloseReason.NOT_ALLOWED
        ),
    ) -> None:
        """Tear down the recording in flight, telling the hub why."""
        if self._session is not None:
            self._session.close(reason)

    async def async_stop(self) -> None:
        """Tear down the recording in flight before the accessory goes away."""
        session = self._session
        if session is not None:
            session.close(HomeKitSecureVideoDataStreamCloseReason.CANCELLED)
            await session.async_stop()

    def _build_service(self) -> Service:
        """Build the service with the characteristics HomeKit reads and writes."""
        service = Service(SERVICE_UUID, "CameraRecordingManagement")

        active = Characteristic(
            ACTIVE,
            ACTIVE_UUID,
            {
                "Format": "uint8",
                "Permissions": ["pr", "pw", "ev"],
                "ValidValues": {"Inactive": 0, "Active": 1},
            },
        )
        active.value = 0
        active.setter_callback = self._handle_active_write
        service.add_characteristic(active)

        audio_active = Characteristic(
            RECORDING_AUDIO_ACTIVE,
            RECORDING_AUDIO_ACTIVE_UUID,
            {
                "Format": "uint8",
                "Permissions": ["pr", "pw", "ev"],
                "ValidValues": {"Disable": 0, "Enable": 1},
            },
        )
        audio_active.value = 1
        audio_active.setter_callback = self._handle_audio_active_write
        service.add_characteristic(audio_active)

        for display_name, type_id, value in (
            (
                "SupportedCameraRecordingConfiguration",
                SUPPORTED_CAMERA_UUID,
                self._supported.camera_configuration,
            ),
            (
                "SupportedVideoRecordingConfiguration",
                SUPPORTED_VIDEO_UUID,
                self._supported.video_configuration,
            ),
            (
                "SupportedAudioRecordingConfiguration",
                SUPPORTED_AUDIO_UUID,
                self._supported.audio_configuration,
            ),
        ):
            characteristic = Characteristic(
                display_name, type_id, {"Format": "tlv8", "Permissions": ["pr", "ev"]}
            )
            characteristic.value = value
            service.add_characteristic(characteristic)

        selected = HomeKitSecureVideoSelectedRecordingConfigurationCharacteristic(
            SELECTED_CAMERA_RECORDING_CONFIGURATION,
            SELECTED_CONFIGURATION_UUID,
            {"Format": "tlv8", "Permissions": ["pr", "pw", "ev"]},
            self._read_selected_configuration,
        )
        selected.value = ""
        selected.setter_callback = self._handle_selected_configuration_write
        service.add_characteristic(selected)

        return service

    def _read_selected_configuration(self) -> str:
        """
        Return the negotiated configuration, failing when there is none.

        Answering an empty value with a success status tells the controller a
        configuration is already in place — an empty one — so it never writes
        the one it was about to negotiate. Failing the read is what the
        reference implementation does, and what makes the controller select.
        """
        if self._selected_value is None:
            message = "No recording configuration has been selected yet"
            raise HomeKitSecureVideoRecordingError(message)
        return self._selected_value

    def _handle_active_write(self, value: int) -> None:
        """React to HomeKit switching recording on or off."""
        LOGGER.debug("HomeKit set recording active to %s", value)
        if not value:
            self.abort_recording()
        self._announce_state_change()

    def _handle_audio_active_write(self, value: int) -> None:
        """Follow HomeKit turning the audio of recordings on or off."""
        LOGGER.debug("HomeKit set the recording audio to %s", value)
        self._announce_state_change()

    def _handle_selected_configuration_write(self, value: str) -> None:
        """
        Store the configuration HomeKit negotiated.

        Anything raised here reaches the controller as a failed write, and the
        Home app turns that into "unable to configure this camera" — so a
        configuration this integration cannot read is logged and dropped
        instead, leaving recording off rather than the whole camera broken.
        """
        # A hub that cannot record rewrites the configuration it already
        # negotiated hundreds of times a minute. Re-announcing a change that
        # did not happen republishes every entity of the entry behind it, so
        # an identical write is the same as no write at all.
        if value == self._selected_value:
            return

        LOGGER.debug("HomeKit wrote the recording configuration %s", value)
        try:
            self._selected = HomeKitSecureVideoSelectedConfiguration.from_tlv(value)
        except HomeKitSecureVideoRecordingError:
            LOGGER.exception("Failed to read the selected recording configuration")
            return

        self._selected_value = value
        self.service.get_characteristic(
            SELECTED_CAMERA_RECORDING_CONFIGURATION
        ).value = value

        LOGGER.debug("HomeKit selected the recording configuration %s", self._selected)
        self._announce_state_change()

    def _announce_state_change(self) -> None:
        """Report the change without letting a listener break the write."""
        try:
            self._recording_state_changed()
        except Exception:  # noqa: BLE001 -- a broken listener must not fail the write
            LOGGER.exception("Failed to report a recording state change")

    def _handle_open(
        self,
        connection: HomeKitSecureVideoDataStreamConnection,
        message: HomeKitSecureVideoDataStreamMessage,
    ) -> None:
        """Start delivering a recording, or explain why we cannot."""
        stream_id = message.payload.get("streamId")
        request_id = message.identifier
        rejection = self._rejection_for(message)

        if (
            rejection is not None
            or not isinstance(stream_id, int)
            or request_id is None
        ):
            reason = rejection or HomeKitSecureVideoDataStreamCloseReason.BAD_DATA
            LOGGER.debug("Rejecting a recording request: %s", reason.name)
            if request_id is not None:
                connection.send_response(
                    HomeKitSecureVideoDataStreamProtocolName.DATA_SEND,
                    HomeKitSecureVideoDataStreamTopic.OPEN,
                    request_id,
                    HomeKitSecureVideoDataStreamStatus.PROTOCOL_SPECIFIC_ERROR,
                    {"status": int(reason)},
                )
            return

        LOGGER.debug("Starting recording %s", stream_id)
        self._session = HomeKitSecureVideoRecordingSession(
            connection,
            self._recorder,
            stream_id,
            request_id,
            self._handle_session_closed,
        )
        self._session.start()
        self._recordings_started += 1

    def _rejection_for(
        self, message: HomeKitSecureVideoDataStreamMessage
    ) -> HomeKitSecureVideoDataStreamCloseReason | None:
        """Return why a recording request cannot be served, or None."""
        if (
            message.payload.get("target") != DATA_SEND_TARGET_CONTROLLER
            or message.payload.get("type") != DATA_SEND_TYPE_RECORDING
        ):
            return HomeKitSecureVideoDataStreamCloseReason.UNEXPECTED_FAILURE
        if not self.is_recording_enabled or not self._operating_mode.is_camera_active:
            return HomeKitSecureVideoDataStreamCloseReason.NOT_ALLOWED
        if self.is_recording_in_flight:
            return HomeKitSecureVideoDataStreamCloseReason.BUSY
        if self._selected is None or not self._recorder.is_running:
            return HomeKitSecureVideoDataStreamCloseReason.INVALID_CONFIGURATION
        return None

    def _handle_acknowledgement(
        self,
        connection: HomeKitSecureVideoDataStreamConnection,  # noqa: ARG002 -- handler signature
        message: HomeKitSecureVideoDataStreamMessage,
    ) -> None:
        """Close the session the hub acknowledged."""
        if self._session is not None and self._matches(message):
            self._session.handle_acknowledgement()

    def _handle_close(
        self,
        connection: HomeKitSecureVideoDataStreamConnection,  # noqa: ARG002 -- handler signature
        message: HomeKitSecureVideoDataStreamMessage,
    ) -> None:
        """Close the session the hub asked to close."""
        if self._session is not None and self._matches(message):
            reason = message.payload.get("reason")
            self._session.handle_close(reason if isinstance(reason, int) else None)

    def _handle_connection_closed(
        self, connection: HomeKitSecureVideoDataStreamConnection
    ) -> None:
        """Release the recording whose connection went away."""
        if self._session is not None and self._session.connection is connection:
            self._session.abandon()

    def _matches(self, message: HomeKitSecureVideoDataStreamMessage) -> bool:
        """Return whether the message names the session in flight."""
        return (
            self._session is not None
            and message.payload.get("streamId") == self._session.stream_id
        )

    def _handle_session_closed(self) -> None:
        """Forget the session that just closed, remembering what it delivered."""
        session = self._session
        self._session = None
        if session is not None:
            self._last_statistics = session.statistics
            # A session reaches this from an abort and from its own failure to
            # find an initialization segment as readily as from a delivery, and
            # `last_recording` is the only signal a user has that Secure Video
            # works.
            if session.has_delivered_media:
                self._last_recording = dt_util.utcnow()
        self._announce_state_change()
