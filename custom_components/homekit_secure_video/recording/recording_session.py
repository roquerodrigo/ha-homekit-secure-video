"""One HomeKit Secure Video recording being delivered to a home hub."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from ..const import LOGGER
from ..datastream import (
    HomeKitSecureVideoDataStreamCloseReason,
    HomeKitSecureVideoDataStreamProtocolName,
    HomeKitSecureVideoDataStreamStatus,
    HomeKitSecureVideoDataStreamTopic,
)
from .constants import (
    CLOSE_TIMEOUT_SECONDS,
    MAX_CHUNK_SIZE,
    MAX_RECORDING_SECONDS,
    PACKET_TYPE_MEDIA_FRAGMENT,
    PACKET_TYPE_MEDIA_INITIALIZATION,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..data import HomeKitSecureVideoRecordingStatistics, OpackValue
    from ..datastream import HomeKitSecureVideoDataStreamConnection
    from .recorder import HomeKitSecureVideoRecorder

FRAGMENT_WAIT_SECONDS = 10
INITIALIZATION_WAIT_SECONDS = 5
INITIALIZATION_POLL_SECONDS = 0.25


def _close_reason_name(reason: int | None) -> str:
    """Render the reason the hub gave, which is a number on the wire."""
    if reason is None:
        return "unknown"
    try:
        return HomeKitSecureVideoDataStreamCloseReason(reason).name
    except ValueError:
        return str(reason)


class HomeKitSecureVideoRecordingSession:
    """
    One HomeKit Secure Video recording being delivered to a home hub.

    The hub opens a dataSend stream and this session answers it with the
    initialization segment, everything the prebuffer held at the moment of the
    trigger, and then fragments as they are produced — until the trigger ends,
    the hub closes the stream, or the recording hits its ceiling.
    """

    def __init__(
        self,
        connection: HomeKitSecureVideoDataStreamConnection,
        recorder: HomeKitSecureVideoRecorder,
        stream_id: int,
        request_id: int,
        on_closed: Callable[[], None],
    ) -> None:
        """Initialize the session for one dataSend stream."""
        self._connection = connection
        self._recorder = recorder
        self._stream_id = stream_id
        self._request_id = request_id
        self._on_closed = on_closed
        self._stop = asyncio.Event()
        self._closed_event = asyncio.Event()
        self._closed = False
        self._data_sequence_number = 1
        self._fragments_sent = 0
        self._bytes_sent = 0
        self._media_delivered = False
        self._task: asyncio.Task[None] | None = None

    @property
    def connection(self) -> HomeKitSecureVideoDataStreamConnection:
        """Return the connection this recording is delivered over."""
        return self._connection

    @property
    def stream_id(self) -> int:
        """Return the id of the stream this session serves."""
        return self._stream_id

    @property
    def statistics(self) -> HomeKitSecureVideoRecordingStatistics:
        """Return how much this session delivered to the hub."""
        return {
            "fragments_sent": self._fragments_sent,
            "bytes_sent": self._bytes_sent,
        }

    @property
    def has_delivered_media(self) -> bool:
        """Return whether any footage went out, initialization aside."""
        return self._media_delivered

    @property
    def is_closed(self) -> bool:
        """Return whether the session is over."""
        return self._closed

    def start(self) -> None:
        """Accept the stream and start delivering fragments."""
        self._task = asyncio.create_task(self._async_deliver())
        self._task.add_done_callback(self._handle_delivery_done)

    def request_stop(self) -> None:
        """Ask the session to finish after the fragment it is on."""
        self._stop.set()

    def handle_acknowledgement(self) -> None:
        """Close the session after the hub acknowledged the last fragment."""
        LOGGER.debug(
            "Recording %s acknowledged by the hub after %s fragments (%s bytes)",
            self._stream_id,
            self._fragments_sent,
            self._bytes_sent,
        )
        self._finish()

    def handle_close(self, reason: int | None) -> None:
        """Close the session because the hub asked to."""
        LOGGER.debug(
            "Recording %s closed by the hub, reason %s, after %s fragments (%s bytes)",
            self._stream_id,
            _close_reason_name(reason),
            self._fragments_sent,
            self._bytes_sent,
        )
        self._finish()

    def close(self, reason: HomeKitSecureVideoDataStreamCloseReason) -> None:
        """Close the session from our side, telling the hub why."""
        if self._closed:
            return
        self._connection.send_event(
            HomeKitSecureVideoDataStreamProtocolName.DATA_SEND,
            HomeKitSecureVideoDataStreamTopic.CLOSE,
            {"streamId": self._stream_id, "reason": int(reason)},
        )
        self._finish()

    async def async_stop(self) -> None:
        """Release the session and wait for its delivery to unwind."""
        task = self._task
        self._finish()
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def abandon(self) -> None:
        """Release the session because its connection went away."""
        if self._closed:
            return
        LOGGER.debug(
            "Recording %s lost its connection after %s fragments (%s bytes)",
            self._stream_id,
            self._fragments_sent,
            self._bytes_sent,
        )
        self._finish()

    async def _async_deliver(self) -> None:
        """Send the initialization segment, the prebuffer, and then live fragments."""
        self._connection.send_response(
            HomeKitSecureVideoDataStreamProtocolName.DATA_SEND,
            HomeKitSecureVideoDataStreamTopic.OPEN,
            self._request_id,
            HomeKitSecureVideoDataStreamStatus.SUCCESS,
            {"status": int(HomeKitSecureVideoDataStreamStatus.SUCCESS)},
        )

        initialization = await self._async_await_initialization_segment()
        if initialization is None:
            LOGGER.warning(
                "Recording %s has no initialization segment", self._stream_id
            )
            self.close(HomeKitSecureVideoDataStreamCloseReason.UNEXPECTED_FAILURE)
            return

        queue = self._recorder.subscribe()
        try:
            self._send_segment(initialization, is_initialization=True, is_last=False)
            for fragment in self._recorder.prebuffered_fragments:
                self._send_segment(fragment, is_initialization=False, is_last=False)
            await self._async_send_live_fragments(queue)
        finally:
            self._recorder.unsubscribe(queue)

        await self._async_await_close()

    async def _async_await_close(self) -> None:
        """
        Wait for the hub to acknowledge the recording, then give up on it.

        Every path that marks the session closed belongs to the hub, so an
        acknowledgement lost to a reboot or a dropped connection would leave
        this session in flight forever — and the accessory answers BUSY to
        every later recording request while one is.
        """
        try:
            async with asyncio.timeout(CLOSE_TIMEOUT_SECONDS):
                await self._closed_event.wait()
        except TimeoutError:
            LOGGER.warning(
                "Recording %s was never acknowledged by the hub, closing it",
                self._stream_id,
            )
            self.close(HomeKitSecureVideoDataStreamCloseReason.TIMEOUT)

    def _handle_delivery_done(self, task: asyncio.Task[None]) -> None:
        """Release the session when its delivery ends for any reason."""
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            LOGGER.error(
                "Recording %s failed: %s",
                self._stream_id,
                exception,
                exc_info=exception,
            )
        self._finish()

    async def _async_await_initialization_segment(self) -> bytes | None:
        """
        Wait for ffmpeg to emit its ``ftyp+moov``, within reason.

        The hub reopens its recordings the moment the accessory comes back, so
        a request routinely arrives seconds before the recorder that was just
        restarted has produced anything.
        """
        deadline = asyncio.get_running_loop().time() + INITIALIZATION_WAIT_SECONDS
        while True:
            initialization = self._recorder.initialization_segment
            if initialization is not None or self._closed:
                return initialization
            if asyncio.get_running_loop().time() >= deadline:
                return None
            await asyncio.sleep(INITIALIZATION_POLL_SECONDS)

    async def _async_send_live_fragments(self, queue: asyncio.Queue[bytes]) -> None:
        """Send fragments as they are produced until the recording should end."""
        deadline = asyncio.get_running_loop().time() + MAX_RECORDING_SECONDS

        while True:
            if self.is_closed:
                return

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                LOGGER.debug("Recording %s hit its time limit", self._stream_id)
                self._send_end_of_stream()
                return

            try:
                async with asyncio.timeout(min(FRAGMENT_WAIT_SECONDS, remaining)):
                    fragment = await queue.get()
            except TimeoutError:
                LOGGER.debug("Recording %s ran out of fragments", self._stream_id)
                self._send_end_of_stream()
                return

            is_last = self._stop.is_set()
            self._send_segment(fragment, is_initialization=False, is_last=is_last)
            if is_last:
                return

    def _send_end_of_stream(self) -> None:
        """Mark the recording as finished without another fragment to send."""
        self._send_segment(b"", is_initialization=False, is_last=True)

    def _send_segment(
        self, payload: bytes, *, is_initialization: bool, is_last: bool
    ) -> None:
        """Send one segment, split into chunks the hub accepts."""
        if self.is_closed:
            return

        chunks = _split(payload)
        for index, chunk in enumerate(chunks, start=1):
            is_last_chunk = index == len(chunks)
            metadata: dict[str, OpackValue] = {
                "dataType": (
                    PACKET_TYPE_MEDIA_INITIALIZATION
                    if is_initialization
                    else PACKET_TYPE_MEDIA_FRAGMENT
                ),
                "dataSequenceNumber": self._data_sequence_number,
                "dataChunkSequenceNumber": index,
                "isLastDataChunk": is_last_chunk,
            }
            if index == 1:
                metadata["dataTotalSize"] = len(payload)

            event: dict[str, OpackValue] = {
                "streamId": self._stream_id,
                "packets": [{"data": chunk, "metadata": metadata}],
            }
            if is_last_chunk and is_last:
                event["endOfStream"] = True

            self._connection.send_event(
                HomeKitSecureVideoDataStreamProtocolName.DATA_SEND,
                HomeKitSecureVideoDataStreamTopic.DATA,
                event,
            )

        self._data_sequence_number += 1
        self._fragments_sent += 1
        self._bytes_sent += len(payload)
        if not is_initialization and payload:
            self._media_delivered = True

    def _finish(self) -> None:
        """Mark the session closed and release its task."""
        if self._closed:
            return
        self._closed = True
        self._closed_event.set()
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
        self._on_closed()


def _split(payload: bytes) -> list[bytes]:
    """Split a segment into chunks of at most the size the hub accepts."""
    if not payload:
        return [b""]
    return [
        payload[offset : offset + MAX_CHUNK_SIZE]
        for offset in range(0, len(payload), MAX_CHUNK_SIZE)
    ]
