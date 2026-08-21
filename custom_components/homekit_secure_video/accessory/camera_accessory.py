"""HomeKit camera accessory backed by a Home Assistant camera entity."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast
from uuid import UUID

from homeassistant.components import camera
from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.const import STATE_ON
from homeassistant.helpers.event import async_track_state_change_event
from pyhap.camera import (
    VIDEO_CODEC_PARAM_LEVEL_TYPES,
    VIDEO_CODEC_PARAM_PROFILE_ID_TYPES,
    Camera,
)
from pyhap.characteristic import Characteristic
from pyhap.const import CATEGORY_CAMERA
from pyhap.service import Service

from ..const import (
    DEFAULT_MAX_FPS,
    DEFAULT_MAX_HEIGHT,
    DEFAULT_MAX_WIDTH,
    DEFAULT_REENCODE,
    DEFAULT_STREAM_AUDIO,
    LOGGER,
    MANUFACTURER,
    MODEL,
    STREAM_COUNT,
    SUPPORTED_RESOLUTIONS,
)
from ..recording import (
    HomeKitSecureVideoEventTrigger,
    HomeKitSecureVideoRecorder,
    HomeKitSecureVideoRecordingAudioCodec,
    HomeKitSecureVideoRecordingCommand,
    HomeKitSecureVideoSupportedConfiguration,
    async_probe_source,
    async_source_has_audio,
    source_matches_configuration,
)
from ..recording.constants import (
    DEFAULT_FRAGMENT_MILLISECONDS,
    DEFAULT_PREBUFFER_MILLISECONDS,
    RECORDING_RESOLUTIONS,
    HomeKitSecureVideoAudioSampleRate,
)
from ..recording.source_probe import EMPTY_PROFILE
from ..streaming import (
    HomeKitSecureVideoLiveStreamCommand,
    HomeKitSecureVideoLiveStreamSession,
)
from .camera_operating_mode import HomeKitSecureVideoCameraOperatingModeService
from .data_stream_transport import HomeKitSecureVideoDataStreamTransportService
from .recording_management import HomeKitSecureVideoRecordingManagementService

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from homeassistant.core import Event, EventStateChangedData, HomeAssistant

    from ..data import (
        HomeKitSecureVideoCameraOptions,
        HomeKitSecureVideoConfigData,
        HomeKitSecureVideoConfigEntry,
        HomeKitSecureVideoOptionsData,
        HomeKitSecureVideoRecordingDiagnostics,
        HomeKitSecureVideoSourceProfile,
        HomeKitSecureVideoStreamRequest,
        HomeKitSecureVideoStreamSessionInfo,
    )
    from ..datastream import HomeKitSecureVideoDataStreamServer
    from ..recording.selected_configuration import (
        HomeKitSecureVideoSelectedConfiguration,
    )
    from .driver import HomeKitSecureVideoAccessoryDriver

# HomeKit requires a firmware revision shaped like "x[.y[.z]]" and validates
# it: left empty, a controller keeps re-reading it and refuses to apply
# settings to the accessory.
FIRMWARE_REVISION_PATTERN = re.compile(r"^\d+(\.\d+){0,2}$")
DEFAULT_FIRMWARE_REVISION = "1.0.0"

# HomeKit prefers the highest profile offered; Scrypted advertises only Main
# for streaming, and re-encoding makes that a promise this accessory can keep.
VIDEO_PROFILES: tuple[bytes, ...] = (VIDEO_CODEC_PARAM_PROFILE_ID_TYPES["MAIN"],)
VIDEO_LEVELS: tuple[bytes, ...] = (
    VIDEO_CODEC_PARAM_LEVEL_TYPES["TYPE3_1"],
    VIDEO_CODEC_PARAM_LEVEL_TYPES["TYPE3_2"],
    VIDEO_CODEC_PARAM_LEVEL_TYPES["TYPE4_0"],
)
# HomeKit tops out at H.264 level 4.0 for cameras; ffprobe reports levels
# multiplied by ten.
HAP_PROTOCOL_VERSION = "1.1.0"
PROTOCOL_INFORMATION_UUID = UUID("000000A2-0000-1000-8000-0026BB765291")
PROTOCOL_VERSION_UUID = UUID("00000037-0000-1000-8000-0026BB765291")
STREAM_ACTIVE = "Active"
STREAM_ACTIVE_UUID = UUID("000000B0-0000-1000-8000-0026BB765291")

MAX_HOMEKIT_H264_LEVEL = 40
MIN_ADVERTISED_FPS = 1
ADVERTISED_FPS = 30

# AAC-ELD needs libfdk_aac, which the Home Assistant ffmpeg build does
# not carry; offering a codec that cannot be produced leaves HomeKit
# negotiating silence.
STREAMING_AUDIO_CODECS: tuple[str, ...] = ("OPUS",)
STREAMING_AUDIO_SAMPLE_RATES_KHZ: tuple[int, ...] = (8, 16, 24)


def _protocol_information_service() -> Service:
    """
    Build the ProtocolInformation service every HAP accessory must publish.

    HAP-python has no definition for it — it ships one only inside bridges —
    so a standalone accessory built with it lacks a service the specification
    requires, and controllers treat such an accessory as incomplete.
    """
    service = Service(PROTOCOL_INFORMATION_UUID, "ProtocolInformation")
    version = Characteristic(
        "Version",
        PROTOCOL_VERSION_UUID,
        {"Format": "string", "Permissions": ["pr"]},
    )
    version.value = HAP_PROTOCOL_VERSION
    service.add_characteristic(version)
    return service


def _firmware_revision(entry: HomeKitSecureVideoConfigEntry) -> str:
    """Return the integration version, or a valid stand-in HomeKit accepts."""
    runtime_data = getattr(entry, "runtime_data", None)
    integration = getattr(runtime_data, "integration", None)
    version = str(getattr(integration, "version", "") or "")
    if FIRMWARE_REVISION_PATTERN.match(version):
        return version
    return DEFAULT_FIRMWARE_REVISION


class HomeKitSecureVideoCameraAccessory(Camera):
    """HomeKit camera accessory backed by a Home Assistant camera entity."""

    category: int = CATEGORY_CAMERA

    def __init__(  # noqa: PLR0913, PLR0917 -- one dependency per collaborator
        self,
        driver: HomeKitSecureVideoAccessoryDriver,
        hass: HomeAssistant,
        entry: HomeKitSecureVideoConfigEntry,
        stream_address: str,
        data_stream_server: HomeKitSecureVideoDataStreamServer,
        source_profile: HomeKitSecureVideoSourceProfile | None = None,
    ) -> None:
        """Initialize the accessory for one camera entity."""
        config = cast("HomeKitSecureVideoConfigData", entry.data)
        options = cast("HomeKitSecureVideoOptionsData", entry.options)

        self._hass = hass
        self._camera_entity_id = config["camera_entity_id"]
        self._motion_entity_id = config.get("motion_entity_id")
        self._always_on_motion = config.get("always_on_motion", False)
        self._ffmpeg_binary = get_ffmpeg_manager(hass).binary
        self._source_profile: HomeKitSecureVideoSourceProfile = source_profile or dict(
            EMPTY_PROFILE
        )  # type: ignore[assignment]
        self._reencode = options.get("reencode", DEFAULT_REENCODE)
        self._stream_audio = options.get("stream_audio", DEFAULT_STREAM_AUDIO)
        self._stream_sessions: dict[str, HomeKitSecureVideoLiveStreamSession] = {}
        self._status_changed: Callable[[], None] | None = None
        self._unsubscribe_motion: Callable[[], None] | None = None

        super().__init__(
            self._build_options(options, stream_address),
            driver,
            entry.title,
        )
        self.add_service(_protocol_information_service())
        self._add_active_to_stream_managements()

        self.set_info_service(
            firmware_revision=_firmware_revision(entry),
            manufacturer=MANUFACTURER,
            model=MODEL,
            serial_number=self._camera_entity_id,
        )
        # StatusActive mirrors HomeKitCameraActive: HomeKit reads it on the
        # linked sensor to know whether the trigger it records on is live.
        self._motion_service = (
            self.add_preload_service("MotionSensor", chars=["StatusActive"])
            if self._motion_entity_id or self._always_on_motion
            else None
        )
        self._data_stream_transport = HomeKitSecureVideoDataStreamTransportService(
            data_stream_server,
            driver.shared_key_for,
        )
        self.add_service(self._data_stream_transport.service)

        self._recorder = HomeKitSecureVideoRecorder(self._ffmpeg_binary)
        self._operating_mode = HomeKitSecureVideoCameraOperatingModeService(
            self._handle_camera_active_changed
        )
        self._recording_management = HomeKitSecureVideoRecordingManagementService(
            self._build_supported_configuration(options),
            self._recorder,
            self._operating_mode,
            data_stream_server,
            self._handle_recording_state_changed,
        )
        self.add_service(self._operating_mode.service)
        self.add_service(self._recording_management.service)
        self._recording_management.service.add_linked_service(
            self._data_stream_transport.service
        )
        if self._motion_service is not None:
            self._recording_management.service.add_linked_service(self._motion_service)
            self._async_update_motion_sensor_active()
        self._warn_about_unusable_source()

    @property
    def homekit_camera_mode(self) -> str:
        """Return the mode HomeKit put this camera in."""
        if not self._operating_mode.is_camera_active:
            return "off"
        if self._recording_management.is_recording_enabled:
            return "stream_and_record"
        if self._operating_mode.are_event_snapshots_active:
            return "detect_activity"
        return "stream"

    @property
    def is_recording(self) -> bool:
        """Return whether a recording is being delivered right now."""
        return self._recording_management.is_recording_in_flight

    @property
    def last_recording(self) -> datetime | None:
        """Return when the last recording finished being delivered."""
        return self._recording_management.last_recording

    @property
    def recording_diagnostics(self) -> HomeKitSecureVideoRecordingDiagnostics:
        """Report what HomeKit negotiated and what has been delivered."""
        return self._recording_management.diagnostics

    @property
    def is_streaming(self) -> bool:
        """Return whether at least one live stream session is running."""
        return any(session.is_running for session in self._stream_sessions.values())

    def set_status_changed_callback(self, callback: Callable[[], None]) -> None:
        """Register the callback fired whenever the streaming state changes."""
        self._status_changed = callback

    async def run(self) -> None:
        """Start reporting motion, either always on or from the linked sensor."""
        if self._always_on_motion:
            # Motion never clears, so HomeKit opens back-to-back recordings
            # and the camera ends up recording continuously.
            self._async_update_motion_detected(detected=True)
        elif self._motion_entity_id and self._motion_service:
            self._unsubscribe_motion = async_track_state_change_event(
                self._hass,
                [self._motion_entity_id],
                self._async_handle_motion_event,
            )
            self._async_update_motion_detected(
                detected=self._hass.states.is_state(self._motion_entity_id, STATE_ON)
            )
        await super().run()

    async def stop(self) -> None:
        """Stop motion tracking and every running stream."""
        if self._unsubscribe_motion is not None:
            self._unsubscribe_motion()
            self._unsubscribe_motion = None
        for session in list(self._stream_sessions.values()):
            await session.async_stop()
        self._stream_sessions.clear()
        await self._recorder.async_stop()
        await super().stop()

    async def async_probe_source(self) -> HomeKitSecureVideoSourceProfile:
        """Report what the camera actually sends."""
        stream_source = await camera.async_get_stream_source(
            self._hass, self._camera_entity_id
        )
        if not stream_source:
            return dict(EMPTY_PROFILE)  # type: ignore[return-value]
        return await async_probe_source(self._ffmpeg_binary, stream_source)

    async def async_get_snapshot(self, image_size: dict[str, int]) -> bytes:
        """Return a JPEG snapshot of the camera at the requested size."""
        image = await camera.async_get_image(
            self._hass,
            self._camera_entity_id,
            width=image_size.get("image-width"),
            height=image_size.get("image-height"),
        )
        return image.content

    async def start_stream(
        self,
        session_info: HomeKitSecureVideoStreamSessionInfo,
        stream_config: HomeKitSecureVideoStreamRequest,
    ) -> bool:
        """Start pushing the camera stream to the requesting controller."""
        stream_source = await camera.async_get_stream_source(
            self._hass, self._camera_entity_id
        )
        if not stream_source:
            LOGGER.error("Camera %s has no stream source", self._camera_entity_id)
            return False

        session = HomeKitSecureVideoLiveStreamSession(
            self._ffmpeg_binary,
            HomeKitSecureVideoLiveStreamCommand(
                input_source=stream_source,
                request=stream_config,
                reencode=self._reencode,
                source_level=self._source_profile.get("video_level"),
                source_has_audio=self._stream_audio
                and self._source_profile.get("audio_codec") is not None,
            ),
        )
        if not await session.async_start():
            return False

        self._stream_sessions[str(session_info["id"])] = session
        self._notify_status_changed()
        return True

    async def stop_stream(
        self, session_info: HomeKitSecureVideoStreamSessionInfo
    ) -> None:
        """Stop the stream belonging to the given session."""
        session = self._stream_sessions.pop(str(session_info["id"]), None)
        if session is not None:
            await session.async_stop()
            self._notify_status_changed()

    async def reconfigure_stream(
        self,
        session_info: HomeKitSecureVideoStreamSessionInfo,  # noqa: ARG002
        stream_config: HomeKitSecureVideoStreamRequest,  # noqa: ARG002
    ) -> bool:
        """Accept the reconfiguration without restarting ffmpeg."""
        return True

    def _build_options(
        self,
        options: HomeKitSecureVideoOptionsData,
        stream_address: str,
    ) -> HomeKitSecureVideoCameraOptions:
        """Build the supported configuration advertised to HomeKit."""
        # Options written by an older version of the flow can still be strings.
        max_width = int(options.get("max_width", DEFAULT_MAX_WIDTH))
        max_height = int(options.get("max_height", DEFAULT_MAX_HEIGHT))
        max_fps = int(options.get("max_fps", DEFAULT_MAX_FPS))
        resolutions = [
            [width, height, fps]
            for width, height, fps in SUPPORTED_RESOLUTIONS
            if width <= max_width and height <= max_height and fps <= max_fps
        ]
        return {
            "video": {
                "codec": {
                    "profiles": list(VIDEO_PROFILES),
                    "levels": list(VIDEO_LEVELS),
                },
                "resolutions": resolutions,
            },
            "audio": {
                # iOS asks for 24 kHz, watchOS for 8 kHz, and HomeKit prefers
                # AAC-ELD when it is offered. Scrypted advertises the same
                # matrix; offering only one codec at one rate is what a
                # controller sees as a camera it cannot fully drive.
                "codecs": [
                    {"type": codec, "samplerate": sample_rate}
                    for codec in STREAMING_AUDIO_CODECS
                    for sample_rate in STREAMING_AUDIO_SAMPLE_RATES_KHZ
                ],
            },
            "address": stream_address,
            "srtp": True,
            "stream_count": STREAM_COUNT,
        }

    def _async_handle_motion_event(self, event: Event[EventStateChangedData]) -> None:
        """Mirror the linked motion sensor onto the HomeKit motion service."""
        new_state = event.data["new_state"]
        if new_state is None:
            return
        self._async_update_motion_detected(detected=new_state.state == STATE_ON)

    def _async_update_motion_detected(self, *, detected: bool) -> None:
        """Push the motion state to the HomeKit characteristic."""
        if self._motion_service is None:
            return
        self._motion_service.get_characteristic("MotionDetected").set_value(detected)
        if not detected:
            # The hub keeps the recording open until we mark a fragment as the
            # last one, so the end of the motion is what ends the clip.
            self._recording_management.stop_recording()

    def _add_active_to_stream_managements(self) -> None:
        """Mark every stream management as available, as HomeKit expects."""
        for service in self.services:
            if service.display_name != "CameraRTPStreamManagement":
                continue
            active = Characteristic(
                STREAM_ACTIVE,
                STREAM_ACTIVE_UUID,
                {
                    "Format": "uint8",
                    "Permissions": ["pr", "pw", "ev"],
                    "ValidValues": {"Inactive": 0, "Active": 1},
                },
            )
            active.value = 1
            service.add_characteristic(active)
            # The service was registered by HAP-python before this ran, so the
            # new characteristic has to be wired into the accessory by hand.
            active.broker = self
            self.iid_manager.assign(active)

    def _build_supported_configuration(
        self, options: HomeKitSecureVideoOptionsData
    ) -> HomeKitSecureVideoSupportedConfiguration:
        """Build the recording configurations offered to HomeKit."""
        # Options written by an older version of the flow can still be strings.
        max_width = int(options.get("max_width", DEFAULT_MAX_WIDTH))
        max_height = int(options.get("max_height", DEFAULT_MAX_HEIGHT))
        max_fps = int(options.get("max_fps", DEFAULT_MAX_FPS))
        frame_rate = self._advertised_frame_rate(max_fps)
        resolutions = tuple(
            (width, height, frame_rate)
            for width, height, _ in RECORDING_RESOLUTIONS
            if width <= max_width and height <= max_height
        ) or ((RECORDING_RESOLUTIONS[0][0], RECORDING_RESOLUTIONS[0][1], frame_rate),)
        return HomeKitSecureVideoSupportedConfiguration(
            prebuffer_milliseconds=DEFAULT_PREBUFFER_MILLISECONDS,
            fragment_milliseconds=DEFAULT_FRAGMENT_MILLISECONDS,
            event_triggers=(HomeKitSecureVideoEventTrigger.MOTION,),
            resolutions=resolutions,
            video_profiles=tuple(profile[0] for profile in VIDEO_PROFILES),
            video_levels=tuple(level[0] for level in VIDEO_LEVELS),
            audio_codecs=(
                HomeKitSecureVideoRecordingAudioCodec.AAC_LC,
                HomeKitSecureVideoRecordingAudioCodec.AAC_ELD,
            ),
            audio_sample_rates=(HomeKitSecureVideoAudioSampleRate.KHZ_32,),
        )

    def _advertised_frame_rate(self, max_fps: int) -> int:
        """
        Return the frame rate to advertise to HomeKit.

        This is deliberately *not* the camera's own rate. HomeKit expects the
        30 fps that Secure Video cameras advertise, and re-encoding can produce
        it from a slower source — advertising the camera's 20 fps instead is
        the one thing that set this accessory apart from a working one.
        """
        return max(MIN_ADVERTISED_FPS, min(ADVERTISED_FPS, max_fps))

    def _warn_about_unusable_source(self) -> None:
        """Log the ways the camera's own stream cannot be handed to HomeKit."""
        level = self._source_profile.get("video_level")
        codec = self._source_profile.get("video_codec")
        width = self._source_profile.get("width")
        height = self._source_profile.get("height")
        largest_width, largest_height, _ = RECORDING_RESOLUTIONS[-1]
        if (
            width is not None
            and height is not None
            and (width > largest_width or height > largest_height)
        ):
            if self._reencode:
                LOGGER.info(
                    "Camera %s sends %dx%d, larger than the %dx%d HomeKit is "
                    "offered; it is scaled down, which costs CPU — pointing this "
                    "entry at a lower-resolution stream of the camera avoids that",
                    self._camera_entity_id,
                    width,
                    height,
                    largest_width,
                    largest_height,
                )
            else:
                # Nothing scales it in copy mode, so HomeKit is handed a
                # picture other than the one it negotiated.
                LOGGER.warning(
                    "Camera %s sends %dx%d, larger than the %dx%d HomeKit is "
                    "offered, and re-encoding is off — HomeKit will get a picture "
                    "it did not ask for. Point this entry at a lower-resolution "
                    "stream of the camera, or turn re-encoding on",
                    self._camera_entity_id,
                    width,
                    height,
                    largest_width,
                    largest_height,
                )
        if codec is not None and codec != "h264":
            LOGGER.warning(
                "Camera %s sends %s; HomeKit only accepts H.264",
                self._camera_entity_id,
                codec,
            )
        if level is not None and level > MAX_HOMEKIT_H264_LEVEL:
            handling = (
                "re-encoded to what HomeKit negotiated"
                if self._reencode
                else "passed through with its level rewritten"
            )
            LOGGER.info(
                "Camera %s sends H.264 level %.1f, above the %.1f HomeKit accepts; "
                "it is %s",
                self._camera_entity_id,
                level / 10,
                MAX_HOMEKIT_H264_LEVEL / 10,
                handling,
            )

    def _handle_recording_state_changed(self) -> None:
        """Start or stop the recorder to match what HomeKit asked for."""
        self._hass.async_create_task(self._async_sync_recorder())
        self._notify_status_changed()

    def _handle_camera_active_changed(self) -> None:
        """Follow HomeKit switching the camera on or off."""
        if not self._operating_mode.is_camera_active:
            self._recording_management.abort_recording()
        self._async_update_motion_sensor_active()
        self._hass.async_create_task(self._async_sync_recorder())
        self._notify_status_changed()

    def _async_update_motion_sensor_active(self) -> None:
        """Mirror the camera's HomeKit state onto the linked motion sensor."""
        if self._motion_service is None:
            return
        self._motion_service.get_characteristic("StatusActive").set_value(
            self._operating_mode.is_camera_active
        )

    async def _async_sync_recorder(self) -> None:
        """Run the recorder exactly while HomeKit wants recordings."""
        configuration = self._recording_management.selected_configuration
        should_record = (
            self._recording_management.is_recording_enabled
            and self._operating_mode.is_camera_active
            and configuration is not None
        )

        if not should_record or configuration is None:
            await self._recorder.async_stop()
            return

        if self._recorder.is_running:
            return

        stream_source = await camera.async_get_stream_source(
            self._hass, self._camera_entity_id
        )
        if not stream_source:
            LOGGER.error(
                "Cannot record %s: the camera has no stream source",
                self._camera_entity_id,
            )
            return

        source_has_audio = self._recording_management.is_audio_enabled and (
            await async_source_has_audio(self._ffmpeg_binary, stream_source)
        )
        await self._recorder.async_start(
            HomeKitSecureVideoRecordingCommand(
                input_source=stream_source,
                configuration=configuration,
                source_has_audio=source_has_audio,
                reencode=self._reencode_recording(configuration),
                source_level=self._source_profile.get("video_level"),
            ),
            configuration,
        )

    def _reencode_recording(
        self, configuration: HomeKitSecureVideoSelectedConfiguration
    ) -> bool:
        """
        Decide whether the recording has to be re-encoded.

        Turning re-encoding off is a choice about CPU, not about correctness:
        a hub silently discards a recording that is not what it negotiated, so
        the option is honoured only while the camera already sends exactly
        that.
        """
        if self._reencode:
            return True
        if source_matches_configuration(self._source_profile, configuration):
            return False
        LOGGER.info(
            "Re-encoding the recording of %s despite the option: the camera "
            "sends %sx%s at %s fps and HomeKit negotiated %sx%s at %s fps",
            self._camera_entity_id,
            self._source_profile.get("width"),
            self._source_profile.get("height"),
            self._source_profile.get("frame_rate"),
            configuration.width,
            configuration.height,
            configuration.frame_rate,
        )
        return True

    def _notify_status_changed(self) -> None:
        """Tell the manager that the streaming state changed."""
        if self._status_changed is not None:
            self._status_changed()
