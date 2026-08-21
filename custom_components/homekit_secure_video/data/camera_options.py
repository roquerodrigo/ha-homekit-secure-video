"""Typed shape of the camera configuration advertised to HomeKit."""

from __future__ import annotations

from typing import TypedDict


class HomeKitSecureVideoVideoCodecOptions(TypedDict):
    """H.264 profiles and levels the accessory accepts."""

    profiles: list[bytes]
    levels: list[bytes]


class HomeKitSecureVideoVideoOptions(TypedDict):
    """Video configuration advertised to HomeKit."""

    codec: HomeKitSecureVideoVideoCodecOptions
    resolutions: list[list[int]]


class HomeKitSecureVideoAudioCodecOptions(TypedDict):
    """One audio codec the accessory accepts."""

    type: str
    samplerate: int


class HomeKitSecureVideoAudioOptions(TypedDict):
    """Audio configuration advertised to HomeKit."""

    codecs: list[HomeKitSecureVideoAudioCodecOptions]


class HomeKitSecureVideoCameraOptions(TypedDict):
    """Full camera configuration handed to HAP-python."""

    video: HomeKitSecureVideoVideoOptions
    audio: HomeKitSecureVideoAudioOptions
    address: str
    srtp: bool
    stream_count: int
