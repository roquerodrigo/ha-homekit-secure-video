"""HomeKit camera accessory backed by a Home Assistant camera entity."""

from __future__ import annotations

import asyncio
import contextlib
import re
from typing import TYPE_CHECKING, Any, cast
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
    source_matches_configuration,
)
from ..recording.constants import (
    DEFAULT_FRAGMENT_MILLISECONDS,
    DEFAULT_PREBUFFER_MILLISECONDS,
    RECORDING_RESOLUTIONS,
    HomeKitSecureVideoAudioSampleRate,
)
from ..recording.source_probe import EMPTY_PROFILE
from ..source_limits import limited_frame_rate, limited_resolutions
from ..streaming import (
    HomeKitSecureVideoLiveStreamCommand,
    HomeKitSecureVideoLiveStreamSession,
)
from .camera_operating_mode import HomeKitSecureVideoCameraOperatingModeService
from .data_stream_transport import HomeKitSecureVideoDataStreamTransportService
from .recording_management import HomeKitSecureVideoRecordingManagementService

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
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
# A hub simply stops choosing when the offer is slower than this: a camera
# advertising its own 10 fps left SelectedCameraRecordingConfiguration
# unwritten and recorded nothing, and the same camera advertising 15 fps
# recorded normally. Below the floor the frame rate has to be raised, which
# is the one place duplicated frames are unavoidable.
MIN_ADVERTISED_FPS = 15

RECORDER_RESTART_DELAY_SECONDS = 5
MAX_RECORDER_RESTART_DELAY_SECONDS = 300
# A run this long counts as the camera having worked, so the next failure
# starts backing off from the beginning again.
HEALTHY_RECORDER_RUN_SECONDS = 60
# This many restarts in a row without a healthy run is a camera that is not
# recording at all, which is worth telling the user about rather than leaving
# in the log.
UNHEALTHY_RECORDER_RESTARTS = 3
# A probe that timed out costs fifteen seconds under the recorder lock, with
# the hub waiting on the other end. A camera that is not answering is not
# going to answer the next restart either, so the answer is reused until the
# camera has had time to come back.
SOURCE_PROBE_RETRY_SECONDS = 600
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
        self._recorder_health_changed: Callable[[], None] | None = None
        self._recorder_unhealthy = False
        self._source_probe_failed_at: float | None = None
        # HomeKit writes several characteristics in a burst when it configures
        # the camera, and each write schedules a sync. Without this lock they
        # all pass the "already running" check before the first ffmpeg exists
        # and every one of them spawns its own, orphaning the rest.
        self._recorder_lock = asyncio.Lock()
        self._recorder_sync_pending = False
        self._recorder_tasks: set[asyncio.Task[None]] = set()
        self._stopped = False
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
        self._recorder.set_stream_ended_callback(self._handle_recorder_stream_ended)
        self._recorder_started_at: float | None = None
        self._recorder_restart_failures = 0
        self._recording_settings: (
            tuple[HomeKitSecureVideoSelectedConfiguration, bool] | None
        ) = None
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
    def is_recorder_unhealthy(self) -> bool:
        """Return whether the recorder keeps failing to stay up."""
        return self._recorder_unhealthy

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

    def set_recorder_health_callback(self, callback: Callable[[], None]) -> None:
        """Register the callback fired when the recorder stops keeping up."""
        self._recorder_health_changed = callback

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
        self._stopped = True
        await self._async_cancel_recorder_tasks()
        if self._unsubscribe_motion is not None:
            self._unsubscribe_motion()
            self._unsubscribe_motion = None
        for session in list(self._stream_sessions.values()):
            await session.async_stop()
        self._stream_sessions.clear()
        # The recording is torn down while this accessory is still coherent:
        # a delivery left running reaches back into it through its own close
        # handler and starts a recorder nothing will ever stop.
        await self._recording_management.async_stop()
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

        session_id = str(session_info["id"])
        stream_index = session_info["stream_idx"]
        session.set_exited_callback(
            lambda: self._handle_stream_session_exited(session_id, stream_index)
        )
        self._stream_sessions[session_id] = session
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

    def _handle_stream_session_exited(self, session_id: str, stream_index: int) -> None:
        """Free the stream management slot of a session whose ffmpeg exited."""
        if self._stream_sessions.pop(session_id, None) is None:
            return
        LOGGER.debug("Live stream session %s ended on its own", session_id)
        self.set_streaming_available(stream_index)
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
        # The cap limits the frame rate of each resolution rather than
        # dropping the ones that exceed it: every entry but the Apple Watch one
        # is 30 fps, so filtering on it leaves HomeKit a camera that advertises
        # a thumbnail, or nothing at all.
        frame_rate = limited_frame_rate(self._source_profile, max_fps)
        resolutions = [
            [width, height, min(fps, frame_rate)]
            for width, height, fps in limited_resolutions(
                SUPPORTED_RESOLUTIONS,
                self._source_profile,
                max_width,
                max_height,
                frame_rate,
            )
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
        frame_rate = self._advertised_frame_rate(
            limited_frame_rate(self._source_profile, max_fps)
        )
        resolutions = limited_resolutions(
            RECORDING_RESOLUTIONS,
            self._source_profile,
            max_width,
            max_height,
            frame_rate,
        )
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

        The camera's own rate is the ceiling. Re-encoding can raise a slower
        source to the 30 fps Secure Video cameras usually advertise, but only
        by duplicating frames: an encode per invented frame, carrying no
        picture that was not already there. One camera cost a whole core doing
        exactly that.

        An earlier round of this concluded the opposite — that advertising a
        camera's own 20 fps was what set this accessory apart from a working
        one. That was measured while every recording was being discarded for
        an unrelated reason, and a camera advertising 15 fps has since
        recorded normally against a real hub, so the rate is treated as a
        ceiling like the other two caps.
        """
        return max(
            MIN_ADVERTISED_FPS,
            min(ADVERTISED_FPS, limited_frame_rate(self._source_profile, max_fps)),
        )

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

    def _handle_recorder_stream_ended(self) -> None:
        """Bring the recorder back after ffmpeg stopped on its own."""
        started_at = self._recorder_started_at
        self._recorder_started_at = None
        loop = asyncio.get_running_loop()
        if started_at is not None and (
            loop.time() - started_at >= HEALTHY_RECORDER_RUN_SECONDS
        ):
            self._recorder_restart_failures = 0
        self._report_recorder_health()
        self._track_recorder_task(self._async_restart_recorder())

    def _report_recorder_health(self) -> None:
        """
        Tell the manager when the recorder stops being able to stay up.

        Every restart is a clip the camera did not record, and all of it lives
        in the log: without this a camera can go a whole night without a single
        recording and say so nowhere the user looks.
        """
        unhealthy = self._recorder_restart_failures >= UNHEALTHY_RECORDER_RESTARTS
        if unhealthy == self._recorder_unhealthy:
            return
        self._recorder_unhealthy = unhealthy
        if self._recorder_health_changed is not None:
            self._recorder_health_changed()

    async def _async_restart_recorder(self) -> None:
        """
        Start the recorder again, backing off while the camera stays unusable.

        Nothing else notices: a request that arrives with no recorder running
        is rejected before a session exists, so without this a camera that
        reboots at night stops recording until the entry is reloaded.
        """
        delay = self._next_recorder_restart_delay()
        LOGGER.debug("Restarting the recorder in %s seconds", delay)
        await asyncio.sleep(delay)
        await self._async_sync_recorder()

    async def _async_source_has_audio(self, stream_source: str) -> bool:
        """
        Return whether the camera has an audio track to map.

        The profile probed when the accessory was published answers this, and
        the live stream already decides from it. Probing again would cost
        another ffprobe — up to fifteen seconds, under the recorder lock, while
        the hub waits — on every start, and the recorder restarts on its own.
        A profile with no video codec is one whose probe failed, and only that
        is worth asking again: an answer is kept for good, and a camera that
        does not answer is left alone until it has had time to come back.
        """
        if self._source_profile.get("video_codec") is not None:
            return self._source_profile.get("audio_codec") is not None

        now = asyncio.get_running_loop().time()
        failed_at = self._source_probe_failed_at
        if failed_at is not None and now - failed_at < SOURCE_PROBE_RETRY_SECONDS:
            return False

        profile = await async_probe_source(self._ffmpeg_binary, stream_source)
        if profile.get("video_codec") is None:
            self._source_probe_failed_at = now
            return False

        self._source_profile = profile
        self._source_probe_failed_at = None
        return profile.get("audio_codec") is not None

    async def _async_confirm_recorder_health(self, started_at: float) -> None:
        """
        Count a run that lasted as the camera having recovered.

        Waiting for the run to end would keep the issue up — and the backoff
        long — for a camera that is recording perfectly well again.
        """
        await asyncio.sleep(HEALTHY_RECORDER_RUN_SECONDS)
        if (
            self._stopped
            or self._recorder_started_at != started_at
            or not self._recorder.is_running
        ):
            return
        self._recorder_restart_failures = 0
        self._report_recorder_health()

    def _next_recorder_restart_delay(self) -> int:
        """Return how long to wait before starting the recorder again."""
        delay = min(
            RECORDER_RESTART_DELAY_SECONDS * 2**self._recorder_restart_failures,
            MAX_RECORDER_RESTART_DELAY_SECONDS,
        )
        self._recorder_restart_failures += 1
        return delay

    def _handle_recording_state_changed(self) -> None:
        """Start or stop the recorder to match what HomeKit asked for."""
        self._request_recorder_sync()
        self._notify_status_changed()

    def _handle_camera_active_changed(self) -> None:
        """Follow HomeKit switching the camera on or off."""
        if not self._operating_mode.is_camera_active:
            self._recording_management.abort_recording()
        self._async_update_motion_sensor_active()
        self._request_recorder_sync()
        self._notify_status_changed()

    def _async_update_motion_sensor_active(self) -> None:
        """Mirror the camera's HomeKit state onto the linked motion sensor."""
        if self._motion_service is None:
            return
        self._motion_service.get_characteristic("StatusActive").set_value(
            self._operating_mode.is_camera_active
        )

    def _request_recorder_sync(self) -> None:
        """
        Ask for one synchronisation, however many events ask for it at once.

        A hub retrying a recording rewrites the negotiated configuration
        thousands of times a minute, and one task per write piled up behind
        the recorder lock until the process ran out of memory.
        """
        if self._recorder_sync_pending:
            return
        self._recorder_sync_pending = True
        self._track_recorder_task(self._async_sync_recorder())

    def _track_recorder_task(self, coroutine: Coroutine[Any, Any, None]) -> None:
        """
        Run recorder work on a task this accessory can cancel.

        Resolving the stream source and probing its audio both take seconds,
        and a task suspended there would otherwise resume after the accessory
        was stopped and spawn an ffmpeg nothing owns any more.
        """
        if self._stopped:
            coroutine.close()
            return
        task = self._hass.async_create_task(coroutine)
        self._recorder_tasks.add(task)
        task.add_done_callback(self._recorder_tasks.discard)

    async def _async_cancel_recorder_tasks(self) -> None:
        """Cancel every pending piece of recorder work and wait for it."""
        tasks = tuple(self._recorder_tasks)
        self._recorder_tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _async_sync_recorder(self) -> None:
        """Run the recorder exactly while HomeKit wants recordings."""
        async with self._recorder_lock:
            self._recorder_sync_pending = False
            if self._stopped:
                return
            await self._async_sync_recorder_once()

    async def _async_sync_recorder_once(self) -> None:
        """Bring the recorder in line with what HomeKit currently wants."""
        configuration = self._recording_management.selected_configuration
        should_record = (
            self._recording_management.is_recording_enabled
            and self._operating_mode.is_camera_active
            and configuration is not None
        )

        if not should_record or configuration is None:
            self._recording_settings = None
            self._recorder_restart_failures = 0
            self._report_recorder_health()
            await self._recorder.async_stop()
            return

        wanted = (configuration, self._recording_management.is_audio_enabled)
        # A running recorder is left alone only while it still encodes what
        # HomeKit is asking for: the audio toggle and the negotiated
        # configuration are both read once, when ffmpeg is spawned.
        if self._recorder.is_running and self._recording_settings == wanted:
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

        source_has_audio = (
            self._recording_management.is_audio_enabled
            and await self._async_source_has_audio(stream_source)
        )
        self._recording_settings = wanted
        started_at = asyncio.get_running_loop().time()
        self._recorder_started_at = started_at
        self._track_recorder_task(self._async_confirm_recorder_health(started_at))
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
