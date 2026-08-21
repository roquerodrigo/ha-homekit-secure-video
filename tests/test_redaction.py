from __future__ import annotations

import pytest

from custom_components.homekit_secure_video.redaction import redact_credentials

CASES = [
    (
        "rtsp://admin:hunter2@192.168.1.10:554/stream",
        "rtsp://***:***@192.168.1.10:554/stream",
    ),
    (
        "-i rtsp://user:p%40ss@cam/live -c:v libx264",
        "-i rtsp://***:***@cam/live -c:v libx264",
    ),
    ("rtsp://192.168.1.10:554/stream", "rtsp://192.168.1.10:554/stream"),
    ("http://camera.local/snapshot.jpg", "http://camera.local/snapshot.jpg"),
    ("", ""),
]


@pytest.mark.parametrize(("source", "expected"), CASES, ids=lambda case: str(case)[:40])
def test_credentials_are_redacted(source, expected):
    assert redact_credentials(source) == expected


def test_every_credential_in_a_command_is_redacted():
    command = "ffmpeg -i rtsp://a:b@one/live -i rtsp://c:d@two/live -f mp4 pipe:1"

    redacted = redact_credentials(command)

    assert "a:b@" not in redacted
    assert "c:d@" not in redacted
    assert redacted.count("***:***@") == 2
