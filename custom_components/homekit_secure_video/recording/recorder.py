"""Keeps a camera encoded as HomeKit recording fragments, ready to be sent."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from ..const import LOGGER
from ..redaction import redact_credentials
from .fragmented_mp4 import read_segments
from .prebuffer import HomeKitSecureVideoPrebuffer

if TYPE_CHECKING:
    from ..data import HomeKitSecureVideoRecorderDiagnostics
    from .ffmpeg_recording_command import HomeKitSecureVideoRecordingCommand
    from .selected_configuration import HomeKitSecureVideoSelectedConfiguration

TERMINATE_TIMEOUT_SECONDS = 5
SUBSCRIBER_QUEUE_SIZE = 16


class HomeKitSecureVideoRecorder:
    """
    Keeps a camera encoded as HomeKit recording fragments, ready to be sent.

    One ffmpeg process runs for as long as recording is enabled, feeding a
    prebuffer of recent fragments. When a recording starts there is therefore
    already footage from before the trigger, which is the whole point of
    Secure Video.
    """

    def __init__(self, ffmpeg_binary: str) -> None:
        """Initialize an idle recorder."""
        self._ffmpeg_binary = ffmpeg_binary
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._prebuffer: HomeKitSecureVideoPrebuffer | None = None
        self._initialization_segment: bytes | None = None
        self._subscribers: list[asyncio.Queue[bytes]] = []

    @property
    def is_running(self) -> bool:
        """Return whether ffmpeg is alive."""
        return self._process is not None and self._process.returncode is None

    @property
    def initialization_segment(self) -> bytes | None:
        """Return the ftyp+moov segment every recording has to open with."""
        return self._initialization_segment

    @property
    def diagnostics(self) -> HomeKitSecureVideoRecorderDiagnostics:
        """Report what the recorder holds, for the diagnostics dump."""
        fragments = self.prebuffered_fragments
        return {
            "running": self.is_running,
            "has_initialization_segment": self._initialization_segment is not None,
            "prebuffer_capacity": self._prebuffer.capacity if self._prebuffer else 0,
            "prebuffered_fragments": len(fragments),
            "prebuffered_bytes": sum(len(fragment) for fragment in fragments),
        }

    @property
    def prebuffered_fragments(self) -> tuple[bytes, ...]:
        """Return the fragments recorded before now."""
        return self._prebuffer.fragments if self._prebuffer else ()

    async def async_start(
        self,
        command: HomeKitSecureVideoRecordingCommand,
        configuration: HomeKitSecureVideoSelectedConfiguration,
    ) -> bool:
        """Spawn ffmpeg and start filling the prebuffer."""
        await self.async_stop()
        self._prebuffer = HomeKitSecureVideoPrebuffer(
            configuration.prebuffer_milliseconds, configuration.fragment_milliseconds
        )
        arguments = command.arguments
        LOGGER.debug(
            "Starting recorder: ffmpeg %s", redact_credentials(" ".join(arguments))
        )
        try:
            self._process = await asyncio.create_subprocess_exec(
                self._ffmpeg_binary,
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            LOGGER.exception("Failed to start ffmpeg for recording")
            return False

        self._reader_task = asyncio.create_task(self._async_read_segments())
        return True

    async def async_stop(self) -> None:
        """Stop ffmpeg and drop the prebuffer."""
        LOGGER.debug("Stopping the recorder")
        reader_task = self._reader_task
        self._reader_task = None
        if reader_task is not None:
            reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader_task

        process = self._process
        self._process = None
        if process is not None and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                async with asyncio.timeout(TERMINATE_TIMEOUT_SECONDS):
                    await process.wait()
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()

        if self._prebuffer is not None:
            self._prebuffer.clear()
        self._initialization_segment = None
        self._subscribers.clear()
        LOGGER.debug("Recorder stopped")

    def subscribe(self) -> asyncio.Queue[bytes]:
        """Return a queue receiving every fragment recorded from now on."""
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[bytes]) -> None:
        """Stop feeding a queue."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def _async_read_segments(self) -> None:
        """Feed the prebuffer and the subscribers until ffmpeg exits."""
        process = self._process
        if process is None or process.stdout is None:
            return

        async for is_initialization, payload in read_segments(process.stdout):
            if is_initialization:
                self._initialization_segment = payload
                continue

            if self._prebuffer is not None:
                self._prebuffer.append(payload)
            self._publish(payload)

        LOGGER.debug("Recorder stream ended")

    def _publish(self, fragment: bytes) -> None:
        """Hand a fragment to every subscriber, dropping it when one is behind."""
        for queue in self._subscribers:
            try:
                queue.put_nowait(fragment)
            except asyncio.QueueFull:
                LOGGER.warning("Dropping a recording fragment: subscriber is behind")
