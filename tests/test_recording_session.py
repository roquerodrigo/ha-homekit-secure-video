from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from custom_components.homekit_secure_video.datastream import (
    HomeKitSecureVideoDataStreamCloseReason,
)
from custom_components.homekit_secure_video.recording import (
    HomeKitSecureVideoRecordingSession,
)
from custom_components.homekit_secure_video.recording.constants import MAX_CHUNK_SIZE

STREAM_ID = 42
REQUEST_ID = 7


class FakeRecorder:
    """A recorder whose fragments the test controls."""

    def __init__(self, initialization=b"init", prebuffered=(b"one", b"two")):
        self.initialization_segment = initialization
        self.prebuffered_fragments = prebuffered
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.unsubscribed = False

    def subscribe(self):
        return self.queue

    def unsubscribe(self, _queue):
        self.unsubscribed = True


def _events(connection):
    return [call.args for call in connection.send_event.call_args_list]


def _data_events(connection):
    return [args[2] for args in _events(connection) if args[1] == "data"]


@pytest.fixture
def connection():
    return MagicMock()


@pytest.fixture
def recorder():
    return FakeRecorder()


@pytest.fixture
def make_session(connection):
    sessions: list[HomeKitSecureVideoRecordingSession] = []

    def build(recorder):
        closed: list[bool] = []
        session = HomeKitSecureVideoRecordingSession(
            connection, recorder, STREAM_ID, REQUEST_ID, lambda: closed.append(True)
        )
        session.closed_calls = closed
        sessions.append(session)
        return session

    yield build

    for session in sessions:
        session.close(HomeKitSecureVideoDataStreamCloseReason.CANCELLED)


@pytest.fixture
def session(make_session, recorder):
    return make_session(recorder)


async def _settle():
    for _ in range(6):
        await asyncio.sleep(0)


async def test_the_open_request_is_answered_first(session, connection):
    session.start()
    await _settle()

    connection.send_response.assert_called_once()
    protocol, topic, request_id = connection.send_response.call_args.args[:3]
    assert (protocol, topic, request_id) == ("dataSend", "open", REQUEST_ID)


async def test_the_initialization_segment_goes_out_first(session, connection):
    session.start()
    await _settle()

    first = _data_events(connection)[0]
    metadata = first["packets"][0]["metadata"]
    assert metadata["dataType"] == "mediaInitialization"
    assert metadata["dataSequenceNumber"] == 1
    assert first["packets"][0]["data"] == b"init"


async def test_the_prebuffer_is_sent_before_live_fragments(session, connection):
    session.start()
    await _settle()

    payloads = [event["packets"][0]["data"] for event in _data_events(connection)]
    assert payloads[:3] == [b"init", b"one", b"two"]


async def test_fragments_are_numbered_in_order(session, connection):
    session.start()
    await _settle()

    numbers = [
        event["packets"][0]["metadata"]["dataSequenceNumber"]
        for event in _data_events(connection)
    ]
    assert numbers == [1, 2, 3]


async def test_a_live_fragment_is_forwarded(session, connection, recorder):
    session.start()
    await _settle()
    await recorder.queue.put(b"live")
    await _settle()

    assert _data_events(connection)[-1]["packets"][0]["data"] == b"live"


async def test_the_end_of_the_trigger_ends_the_recording(session, connection, recorder):
    session.start()
    await _settle()
    session.request_stop()
    await recorder.queue.put(b"last")
    await _settle()

    last = _data_events(connection)[-1]
    assert last["endOfStream"] is True
    assert last["packets"][0]["metadata"]["isLastDataChunk"] is True


async def test_a_large_fragment_is_split_into_chunks(
    connection, recorder, make_session
):
    recorder.prebuffered_fragments = (b"x" * (MAX_CHUNK_SIZE + 10),)
    session = make_session(recorder)
    session.start()
    await _settle()

    chunks = [
        event["packets"][0]["metadata"]
        for event in _data_events(connection)
        if event["packets"][0]["metadata"]["dataType"] == "mediaFragment"
    ]
    assert [chunk["dataChunkSequenceNumber"] for chunk in chunks] == [1, 2]
    assert chunks[0]["isLastDataChunk"] is False
    assert chunks[0]["dataTotalSize"] == MAX_CHUNK_SIZE + 10
    assert chunks[1]["isLastDataChunk"] is True
    assert "dataTotalSize" not in chunks[1]


async def test_a_recording_without_an_initialization_segment_is_closed(
    connection, make_session
):
    from custom_components.homekit_secure_video.recording import recording_session

    session = make_session(FakeRecorder(initialization=None))
    with patch.object(recording_session, "INITIALIZATION_WAIT_SECONDS", 0):
        session.start()
        await _settle()

    assert session.is_closed
    close_event = next(args for args in _events(connection) if args[1] == "close")
    assert close_event[2]["reason"] == int(
        HomeKitSecureVideoDataStreamCloseReason.UNEXPECTED_FAILURE
    )


async def test_an_acknowledgement_closes_the_session(session):
    session.start()
    await _settle()

    session.handle_acknowledgement()

    assert session.is_closed
    assert session.closed_calls == [True]


async def test_a_close_from_the_hub_closes_the_session(session):
    session.start()
    await _settle()

    session.handle_close(int(HomeKitSecureVideoDataStreamCloseReason.NORMAL))

    assert session.is_closed


async def test_closing_twice_notifies_once(session):
    session.start()
    await _settle()

    session.handle_acknowledgement()
    session.handle_close(None)

    assert session.closed_calls == [True]


async def test_closing_from_our_side_tells_the_hub(session, connection):
    session.start()
    await _settle()

    session.close(HomeKitSecureVideoDataStreamCloseReason.NOT_ALLOWED)

    close_event = next(args for args in _events(connection) if args[1] == "close")
    assert close_event[2] == {
        "streamId": STREAM_ID,
        "reason": int(HomeKitSecureVideoDataStreamCloseReason.NOT_ALLOWED),
    }
    assert session.is_closed


async def test_nothing_is_sent_after_the_session_closed(session, connection):
    session.start()
    await _settle()
    session.handle_acknowledgement()
    sent = len(_data_events(connection))

    session._send_segment(b"late", is_initialization=False, is_last=False)

    assert len(_data_events(connection)) == sent


async def test_the_session_counts_what_it_delivered(session, connection):
    assert session.statistics == {"fragments_sent": 0, "bytes_sent": 0}

    session.start()
    await _settle()

    statistics = session.statistics
    assert statistics["fragments_sent"] == len(_data_events(connection))
    assert statistics["bytes_sent"] == len(b"init") + len(b"one") + len(b"two")


def test_a_close_reason_is_named_in_the_log():
    from custom_components.homekit_secure_video.recording.recording_session import (
        _close_reason_name,
    )

    assert _close_reason_name(6) == "TIMEOUT"
    assert _close_reason_name(None) == "unknown"
    assert _close_reason_name(99) == "99"


async def test_a_late_initialization_segment_is_waited_for(connection, make_session):
    from custom_components.homekit_secure_video.recording import recording_session

    recorder = FakeRecorder(initialization=None)
    session = make_session(recorder)
    with patch.object(recording_session, "INITIALIZATION_POLL_SECONDS", 0):
        session.start()
        await _settle()

        assert not session.is_closed

        recorder.initialization_segment = b"init"
        await _settle()

    assert _data_events(connection)[0]["packets"][0]["data"] == b"init"


async def test_an_unacknowledged_recording_closes_itself(
    connection, make_session, recorder
):
    from custom_components.homekit_secure_video.recording import recording_session

    session = make_session(recorder)
    with patch.object(recording_session, "CLOSE_TIMEOUT_SECONDS", 0):
        session.start()
        await _settle()
        session.request_stop()
        await recorder.queue.put(b"last")
        await _settle()

    assert session.is_closed
    assert session.closed_calls == [True]
    close_events = [args[2] for args in _events(connection) if args[1] == "close"]
    assert close_events[-1] == {
        "streamId": STREAM_ID,
        "reason": int(HomeKitSecureVideoDataStreamCloseReason.TIMEOUT),
    }


async def test_the_session_waits_for_the_acknowledgement_before_closing(
    session, recorder
):
    session.start()
    await _settle()
    session.request_stop()
    await recorder.queue.put(b"last")
    await _settle()

    assert not session.is_closed

    session.handle_acknowledgement()

    assert session.is_closed
    assert session.closed_calls == [True]


async def test_a_delivery_that_raises_releases_the_session(session, recorder):
    recorder.prebuffered_fragments = None
    session.start()
    await _settle()

    assert session.is_closed
    assert session.closed_calls == [True]
