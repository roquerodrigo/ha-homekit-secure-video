"""One running ffmpeg process serving a HomeKit live stream session."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from ..const import LOGGER
from ..redaction import redact_credentials

if TYPE_CHECKING:
    from collections.abc import Callable

    from .live_stream_command import HomeKitSecureVideoLiveStreamCommand

TERMINATE_TIMEOUT_SECONDS = 5
STDERR_BUFFER_LIMIT = 64 * 1024


class HomeKitSecureVideoLiveStreamSession:
    """One running ffmpeg process serving a HomeKit live stream session."""

    def __init__(
        self,
        ffmpeg_binary: str,
        command: HomeKitSecureVideoLiveStreamCommand,
    ) -> None:
        """Initialize the session with the ffmpeg binary and its arguments."""
        self._ffmpeg_binary = ffmpeg_binary
        self._command = command
        self._process: asyncio.subprocess.Process | None = None
        self._watcher: asyncio.Task[None] | None = None
        self._stderr_reader: asyncio.Task[None] | None = None
        self._exited: Callable[[], None] | None = None

    def set_exited_callback(self, callback: Callable[[], None]) -> None:
        """Register the callback fired when ffmpeg exits on its own."""
        self._exited = callback

    @property
    def is_running(self) -> bool:
        """Return whether the ffmpeg process is still alive."""
        return self._process is not None and self._process.returncode is None

    async def async_start(self) -> bool:
        """Spawn ffmpeg and report whether it survived the handshake."""
        arguments = self._command.arguments
        LOGGER.debug(
            "Starting live stream: ffmpeg %s",
            redact_credentials(" ".join(arguments)),
        )
        try:
            self._process = await asyncio.create_subprocess_exec(
                self._ffmpeg_binary,
                *arguments,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                limit=STDERR_BUFFER_LIMIT,
            )
        except OSError:
            LOGGER.exception("Failed to start ffmpeg for the live stream")
            return False

        self._watcher = asyncio.create_task(self._async_watch(self._process))
        self._stderr_reader = asyncio.create_task(
            self._async_drain_stderr(self._process)
        )
        return self.is_running

    async def _async_drain_stderr(self, process: asyncio.subprocess.Process) -> None:
        """
        Log what ffmpeg writes to stderr, and keep reading it.

        The pipe is never emptied otherwise, and a source that warns per frame
        fills it in minutes — the child then blocks in write() forever, with
        the stream dead and the process still reporting itself as running.
        """
        if process.stderr is None:
            return
        while True:
            line = await process.stderr.readline()
            if not line:
                return
            LOGGER.debug(
                "Live stream ffmpeg: %s", line.decode(errors="replace").rstrip()
            )

    async def _async_watch(self, process: asyncio.subprocess.Process) -> None:
        """
        Report ffmpeg exiting on its own.

        Nothing else reaps the session: the controller may never send a stop,
        and the stream management slot it holds stays marked as streaming until
        someone does.
        """
        await process.wait()
        LOGGER.debug("The live stream ended, ffmpeg exit code %s", process.returncode)
        if self._exited is not None:
            self._exited()

    async def async_stop(self) -> None:
        """Terminate ffmpeg, killing it when it ignores the signal."""
        watcher = self._watcher
        stderr_reader = self._stderr_reader
        self._watcher = None
        self._stderr_reader = None
        await _cancel(watcher)
        await _cancel(stderr_reader)

        process = self._process
        self._process = None
        if process is None or process.returncode is not None:
            return

        with contextlib.suppress(ProcessLookupError):
            process.terminate()
        try:
            async with asyncio.timeout(TERMINATE_TIMEOUT_SECONDS):
                await process.wait()
        except TimeoutError:
            LOGGER.warning("ffmpeg ignored terminate; killing it")
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()


async def _cancel(task: asyncio.Task[None] | None) -> None:
    """Cancel a task and wait for it to unwind."""
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
