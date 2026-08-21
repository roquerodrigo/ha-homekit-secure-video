"""Typed shape of the stream parameters negotiated with a HomeKit controller."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class HomeKitSecureVideoStreamRequest(TypedDict):
    """
    Stream parameters negotiated with a HomeKit controller.

    HAP-python hands the negotiated session to ``start_stream`` as a permissive
    ``dict``; this is the subset the ffmpeg command needs, cast at the boundary.
    """

    address: str
    v_port: int
    v_srtp_key: str
    v_ssrc: int
    v_max_bitrate: int
    width: NotRequired[int]
    height: NotRequired[int]
    fps: NotRequired[int]
    v_profile_id: NotRequired[bytes]
    v_level: NotRequired[bytes]
    a_port: NotRequired[int]
    a_srtp_key: NotRequired[str]
    a_ssrc: NotRequired[int]
    a_codec: NotRequired[bytes]
    a_channel: NotRequired[int]
    a_sample_rate: NotRequired[int]
    a_packet_time: NotRequired[int]
    a_max_bitrate: NotRequired[int]
    a_payload_type: NotRequired[bytes]
