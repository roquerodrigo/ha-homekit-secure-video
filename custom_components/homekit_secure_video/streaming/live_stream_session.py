"""One running ffmpeg process serving a HomeKit live stream session."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from ..const import LOGGER
from ..redaction import redact_credentials

if TYPE_CHECKING:
    from .live_stream_command import HomeKitSecureVideoLiveStreamCommand

TERMINATE_TIMEOUT_SECONDS = 5


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
            )
        except OSError:
            LOGGER.exception("Failed to start ffmpeg for the live stream")
            return False

        return self.is_running

    async def async_stop(self) -> None:
        """Terminate ffmpeg, killing it when it ignores the signal."""
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
