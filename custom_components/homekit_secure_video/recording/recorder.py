"""Keeps a camera encoded as HomeKit recording fragments, ready to be sent."""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from typing import TYPE_CHECKING

from ..const import LOGGER
from ..redaction import redact_credentials
from .fragmented_mp4 import read_segments
from .prebuffer import HomeKitSecureVideoPrebuffer

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..data import HomeKitSecureVideoRecorderDiagnostics
    from .ffmpeg_recording_command import HomeKitSecureVideoRecordingCommand
    from .selected_configuration import HomeKitSecureVideoSelectedConfiguration

TERMINATE_TIMEOUT_SECONDS = 5
KILL_TIMEOUT_SECONDS = 5
SUBSCRIBER_QUEUE_SIZE = 16
# What ffmpeg wrote before it gave up is the only account of why a camera
# stopped recording, and it is written right before the stream ends.
STDERR_LINES_KEPT = 10
STDERR_DRAIN_SECONDS = 1


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
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_lines: deque[str] = deque(maxlen=STDERR_LINES_KEPT)
        self._prebuffer: HomeKitSecureVideoPrebuffer | None = None
        self._initialization_segment: bytes | None = None
        self._subscribers: list[asyncio.Queue[bytes]] = []
        self._stream_ended: Callable[[], None] | None = None

    def set_stream_ended_callback(self, callback: Callable[[], None]) -> None:
        """Register the callback fired when ffmpeg stops on its own."""
        self._stream_ended = callback

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
        self._stderr_lines.clear()
        try:
            self._process = await asyncio.create_subprocess_exec(
                self._ffmpeg_binary,
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError:
            LOGGER.exception("Failed to start ffmpeg for recording")
            return False

        process = self._process
        self._reader_task = asyncio.create_task(self._async_read_segments(process))
        self._stderr_task = asyncio.create_task(self._async_read_stderr(process))
        return True

    async def async_stop(self) -> None:
        """Stop ffmpeg and drop the prebuffer."""
        LOGGER.debug("Stopping the recorder")
        reader_task = self._reader_task
        stderr_task = self._stderr_task
        self._reader_task = None
        self._stderr_task = None
        await _cancel(reader_task)
        await _cancel(stderr_task)

        process = self._process
        self._process = None
        if process is not None:
            await self._async_end(process)

        if self._prebuffer is not None:
            self._prebuffer.clear()
        self._initialization_segment = None
        self._subscribers.clear()
        LOGGER.debug("Recorder stopped")

    async def _async_end(self, process: asyncio.subprocess.Process) -> int | None:
        """Terminate ffmpeg if it is still alive, and report how it exited."""
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                async with asyncio.timeout(TERMINATE_TIMEOUT_SECONDS):
                    await process.wait()
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                # A process that never reports its exit — a lost notification
                # is enough — would hold this coroutine, and with it the lock
                # the accessory synchronises the recorder under, for good: the
                # camera then stops recording until the entry is reloaded,
                # with nothing above DEBUG in the log to say why.
                try:
                    async with asyncio.timeout(KILL_TIMEOUT_SECONDS):
                        await process.wait()
                except TimeoutError:
                    LOGGER.warning(
                        "Gave up waiting for ffmpeg %s to exit after killing it",
                        process.pid,
                    )
        return process.returncode

    def subscribe(self) -> asyncio.Queue[bytes]:
        """Return a queue receiving every fragment recorded from now on."""
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[bytes]) -> None:
        """Stop feeding a queue."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def _async_read_segments(self, process: asyncio.subprocess.Process) -> None:
        """Feed the prebuffer and the subscribers until ffmpeg exits."""
        if process.stdout is None:
            return

        async for is_initialization, payload in read_segments(process.stdout):
            if is_initialization:
                self._initialization_segment = payload
                continue

            if self._prebuffer is not None:
                self._prebuffer.append(payload)
            self._publish(payload)

        # Reaching here means ffmpeg ended by itself — a camera reboot or a
        # dropped RTSP session — and the segment it left behind describes a
        # stream that no longer exists.
        self._initialization_segment = None
        # The end of the output is not the end of the process: ffmpeg can stop
        # producing fragments while it is still alive, and its exit code is
        # only known once it has been waited for. Leaving it running would
        # keep an encode nothing reads any more, and would keep `is_running`
        # answering True — which is what lets the hub open a recording against
        # a recorder that has nothing left to send.
        exit_code = await self._async_end(process)
        if self._process is process:
            self._process = None
        if self._stderr_task is not None:
            await asyncio.wait({self._stderr_task}, timeout=STDERR_DRAIN_SECONDS)
        LOGGER.warning(
            "The recorder stopped on its own, ffmpeg exit code %s%s",
            exit_code,
            self._last_ffmpeg_error,
        )
        if self._stream_ended is not None:
            self._stream_ended()

    async def _async_read_stderr(self, process: asyncio.subprocess.Process) -> None:
        """
        Keep the last lines ffmpeg wrote, to explain why it stopped.

        The process is passed in rather than read back off the recorder: by
        the time this runs the recorder may already have let go of the process
        that wrote the very line worth keeping.
        """
        if process.stderr is None:
            return

        while line := await process.stderr.readline():
            self._stderr_lines.append(line.decode(errors="replace").strip())

    @property
    def _last_ffmpeg_error(self) -> str:
        """Return what ffmpeg last wrote, ready to append to a log line."""
        lines = [line for line in self._stderr_lines if line]
        if not lines:
            return ""
        return f": {redact_credentials(' / '.join(lines))}"

    def _publish(self, fragment: bytes) -> None:
        """Hand a fragment to every subscriber, dropping it when one is behind."""
        for queue in self._subscribers:
            try:
                queue.put_nowait(fragment)
            except asyncio.QueueFull:
                LOGGER.warning("Dropping a recording fragment: subscriber is behind")


async def _cancel(task: asyncio.Task[None] | None) -> None:
    """Stop one of the recorder's tasks and wait for it to unwind."""
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
