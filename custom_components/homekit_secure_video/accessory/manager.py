"""Lifecycle of the HomeKit accessory published for one config entry."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, cast

from homeassistant.components import camera
from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.components.network import async_get_source_ip
from homeassistant.components.zeroconf import async_get_async_zeroconf
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.storage import STORAGE_DIR

from ..const import DOMAIN, LOGGER
from ..datastream import HomeKitSecureVideoDataStreamServer
from ..issues import (
    async_clear_camera_source_issues,
    async_review_camera_source,
)
from ..recording.source_probe import EMPTY_PROFILE, async_probe_source
from .camera_accessory import HomeKitSecureVideoCameraAccessory
from .driver import HomeKitSecureVideoAccessoryDriver

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from homeassistant.core import HomeAssistant
    from zeroconf.asyncio import AsyncZeroconf

    from ..data import (
        HomeKitSecureVideoAccessoryStatus,
        HomeKitSecureVideoConfigData,
        HomeKitSecureVideoConfigEntry,
        HomeKitSecureVideoRecordingDiagnostics,
        HomeKitSecureVideoSourceProfile,
    )

STOP_TIMEOUT_SECONDS = 10


async def _bounded(what: str, task: Coroutine[None, None, None]) -> bool:
    """Await one shutdown step, giving up rather than hanging the unload."""
    LOGGER.debug("Stopping the %s", what)
    try:
        async with asyncio.timeout(STOP_TIMEOUT_SECONDS):
            await task
    except TimeoutError:
        LOGGER.warning("Timed out stopping the %s; carrying on", what)
    except Exception:  # noqa: BLE001 -- a failed step must not block the rest
        LOGGER.exception("Failed to stop the %s; carrying on", what)
    else:
        return True
    return False


EMPTY_STATUS: HomeKitSecureVideoAccessoryStatus = {
    "pairing_code": "",
    "setup_uri": "",
    "paired": False,
    "streaming": False,
    "recording": False,
    "camera_mode": None,
    "last_recording": None,
}


EMPTY_RECORDING_DIAGNOSTICS: HomeKitSecureVideoRecordingDiagnostics = {
    "enabled": False,
    "audio_enabled": False,
    "in_flight": False,
    "recordings_started": 0,
    "selected_configuration": None,
    "last_session": None,
    "recorder": {
        "running": False,
        "has_initialization_segment": False,
        "prebuffer_capacity": 0,
        "prebuffered_fragments": 0,
        "prebuffered_bytes": 0,
    },
}


class HomeKitSecureVideoAccessoryManager:
    """Lifecycle of the HomeKit accessory published for one config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HomeKitSecureVideoConfigEntry,
    ) -> None:
        """Initialize the manager for one config entry."""
        self._hass = hass
        self._entry = entry
        self._driver: HomeKitSecureVideoAccessoryDriver | None = None
        self._accessory: HomeKitSecureVideoCameraAccessory | None = None
        self._data_stream_server = HomeKitSecureVideoDataStreamServer()
        self._status_listeners: list[Callable[[], None]] = []

    @property
    def persist_file(self) -> Path:
        """Return the path of the file holding the HAP pairing state."""
        return Path(
            self._hass.config.path(
                STORAGE_DIR, f"{DOMAIN}.{self._entry.entry_id}.state"
            )
        )

    @property
    def status(self) -> HomeKitSecureVideoAccessoryStatus:
        """Return the current status of the published accessory."""
        driver = self._driver
        accessory = self._accessory
        if driver is None or accessory is None:
            return EMPTY_STATUS
        pincode: bytes = driver.state.pincode
        return {
            "pairing_code": pincode.decode(),
            "setup_uri": accessory.xhm_uri(),
            "paired": bool(driver.state.paired),
            "streaming": accessory.is_streaming,
            "recording": accessory.is_recording,
            "camera_mode": accessory.homekit_camera_mode,
            "last_recording": (
                accessory.last_recording.isoformat()
                if accessory.last_recording
                else None
            ),
        }

    @property
    def recording_diagnostics(self) -> HomeKitSecureVideoRecordingDiagnostics:
        """Report the recording state of the accessory, for diagnostics."""
        accessory = self._accessory
        if accessory is None:
            return EMPTY_RECORDING_DIAGNOSTICS
        return accessory.recording_diagnostics

    @property
    def published_services(self) -> tuple[str, ...]:
        """Return the HAP services the accessory currently publishes."""
        accessory = self._accessory
        if accessory is None:
            return ()
        return tuple(sorted(service.display_name for service in accessory.services))

    async def async_probe_camera(self) -> HomeKitSecureVideoSourceProfile:
        """Report what the camera actually sends, for diagnostics."""
        accessory = self._accessory
        if accessory is None:
            return dict(EMPTY_PROFILE)  # type: ignore[return-value]
        return await accessory.async_probe_source()

    async def _async_probe_configured_camera(self) -> HomeKitSecureVideoSourceProfile:
        """
        Ask the configured camera what it sends, before publishing it.

        On a Home Assistant restart this can run before the integration owning
        the camera has set it up. That is not a broken configuration, just a
        race, so it is reported as "not ready" and Home Assistant retries.
        """
        config = cast("HomeKitSecureVideoConfigData", self._entry.data)
        try:
            stream_source = await camera.async_get_stream_source(
                self._hass, config["camera_entity_id"]
            )
        except HomeAssistantError as exception:
            message = f"Camera {config['camera_entity_id']} is not available yet"
            raise ConfigEntryNotReady(message) from exception

        if not stream_source:
            LOGGER.warning(
                "Camera %s has no stream source; publishing it without knowing "
                "what it sends",
                config["camera_entity_id"],
            )
            profile: HomeKitSecureVideoSourceProfile = dict(EMPTY_PROFILE)  # type: ignore[assignment]
        else:
            profile = await async_probe_source(
                get_ffmpeg_manager(self._hass).binary, stream_source
            )
        async_review_camera_source(
            self._hass,
            self._entry,
            profile,
            has_stream_source=bool(stream_source),
        )
        return profile

    @property
    def data_stream_port(self) -> int | None:
        """Return the port the data stream server listens on."""
        return self._data_stream_server.port

    def async_add_status_listener(
        self, listener: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a listener fired whenever the accessory status changes."""
        self._status_listeners.append(listener)

        def unsubscribe() -> None:
            self._status_listeners.remove(listener)

        return unsubscribe

    async def async_start(self) -> None:
        """
        Publish the accessory and start advertising it over mDNS.

        Whatever was acquired is released again when a step fails: the data
        stream server holds a listening socket and the driver holds the
        reserved HAP port, and a retried setup that leaves them behind runs out
        of both.
        """
        try:
            await self._async_start()
        except Exception:
            await self.async_stop()
            raise

    async def _async_start(self) -> None:
        """Build the driver and the accessory, and start them."""
        config = cast("HomeKitSecureVideoConfigData", self._entry.data)
        source_ip = await async_get_source_ip(self._hass)
        async_zeroconf = async_get_async_zeroconf(self._hass)
        driver = await self._hass.async_add_executor_job(
            self._create_driver, source_ip, config, async_zeroconf
        )
        driver.state.setup_id = config["setup_id"]
        await self._data_stream_server.async_start(source_ip)
        # What the camera actually sends decides what can be advertised: the
        # video is copied, not re-encoded, so promising a frame rate or a level
        # the camera does not produce leaves HomeKit unable to use the stream.
        source_profile = await self._async_probe_configured_camera()
        LOGGER.debug("Camera %s sends %s", config["camera_entity_id"], source_profile)
        accessory = HomeKitSecureVideoCameraAccessory(
            driver,
            self._hass,
            self._entry,
            source_ip,
            self._data_stream_server,
            source_profile,
        )
        accessory.set_status_changed_callback(self._notify_status_listeners)

        await self._hass.async_add_executor_job(driver.add_accessory, accessory)
        self._driver = driver
        self._accessory = accessory

        await driver.async_start()
        LOGGER.debug("Published %s on port %s", self._entry.title, config["port"])
        self._notify_status_listeners()

    async def async_stop(self) -> None:
        """
        Stop advertising the accessory and release its resources.

        Every step is bounded: an unload that hangs leaves the config entry
        stuck in "unloading" forever, and from there only a Home Assistant
        restart brings the camera back.
        """
        driver = self._driver
        self._driver = None
        self._accessory = None

        async_clear_camera_source_issues(self._hass, self._entry)
        await _bounded("data stream server", self._data_stream_server.async_stop())
        if driver is not None and not await _bounded(
            "accessory driver", driver.async_stop()
        ):
            # pyhap unregisters mDNS before it closes the HAP socket, so a step
            # that gave up halfway can leave the reserved port held.
            driver.http_server.async_stop()
        LOGGER.debug("Stopped the accessory of %s", self._entry.title)

    async def async_reset_pairing(self) -> None:
        """Drop every pairing and publish the accessory with a fresh code."""
        await self.async_stop()
        await self._hass.async_add_executor_job(self.remove_persist_file)
        await self.async_start()

    def _create_driver(
        self,
        source_ip: str,
        config: HomeKitSecureVideoConfigData,
        async_zeroconf: AsyncZeroconf,
    ) -> HomeKitSecureVideoAccessoryDriver:
        """Build the driver; the pyhap loader reads its resources from disk."""
        return HomeKitSecureVideoAccessoryDriver(
            self._notify_status_listeners,
            address=source_ip,
            port=config["port"],
            pincode=config["pairing_code"].encode(),
            persist_file=str(self.persist_file),
            loop=self._hass.loop,
            async_zeroconf_instance=async_zeroconf,
        )

    def remove_persist_file(self) -> None:
        """Delete the persisted HAP state, if any."""
        self.persist_file.unlink(missing_ok=True)

    def _notify_status_listeners(self) -> None:
        """Fire every registered status listener."""
        for listener in list(self._status_listeners):
            listener()
