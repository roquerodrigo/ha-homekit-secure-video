from __future__ import annotations

import struct

import pytest
from pyhap import tlv
from pyhap.util import to_base64_str

from custom_components.homekit_secure_video.exceptions import (
    HomeKitSecureVideoRecordingError,
)
from custom_components.homekit_secure_video.recording import (
    HomeKitSecureVideoAudioSampleRate,
    HomeKitSecureVideoEventTrigger,
    HomeKitSecureVideoRecordingAudioCodec,
    HomeKitSecureVideoSelectedConfiguration,
    HomeKitSecureVideoSupportedConfiguration,
)

SUPPORTED = HomeKitSecureVideoSupportedConfiguration(
    prebuffer_milliseconds=4000,
    fragment_milliseconds=4000,
    event_triggers=(HomeKitSecureVideoEventTrigger.MOTION,),
    resolutions=((1920, 1080, 30), (1280, 720, 30)),
    video_profiles=(0, 1, 2),
    video_levels=(0, 1, 2),
    audio_codecs=(
        HomeKitSecureVideoRecordingAudioCodec.AAC_LC,
        HomeKitSecureVideoRecordingAudioCodec.AAC_ELD,
    ),
    audio_sample_rates=(
        HomeKitSecureVideoAudioSampleRate.KHZ_16,
        HomeKitSecureVideoAudioSampleRate.KHZ_24,
    ),
)


def test_camera_configuration_carries_the_prebuffer_and_fragment_length():
    decoded = tlv.decode(SUPPORTED.camera_configuration, from_base64=True)

    assert struct.unpack("<i", decoded[b"\x01"])[0] == 4000
    container = tlv.decode(decoded[b"\x03"])
    parameters = tlv.decode(container[b"\x02"])
    assert struct.unpack("<i", parameters[b"\x01"])[0] == 4000
    assert container[b"\x01"] == b"\x00"


def test_camera_configuration_advertises_motion_as_a_trigger():
    decoded = tlv.decode(SUPPORTED.camera_configuration, from_base64=True)

    assert (
        struct.unpack("<q", decoded[b"\x02"])[0]
        == HomeKitSecureVideoEventTrigger.MOTION
    )


def test_video_configuration_lists_every_resolution():
    decoded = tlv.decode(SUPPORTED.video_configuration, from_base64=True)
    codec = tlv.decode(decoded[b"\x01"])

    assert codec[b"\x01"] == b"\x00"
    # pyhap's decoder concatenates repeated tags, so each 5-byte attribute
    # block lands back to back.
    assert len(codec[b"\x03"]) == 2 * len(
        b"\x01\x02\x00\x00\x02\x02\x00\x00\x03\x01\x00"
    )


def test_video_configuration_lists_profiles_and_levels():
    decoded = tlv.decode(SUPPORTED.video_configuration, from_base64=True)
    parameters = tlv.decode(tlv.decode(decoded[b"\x01"])[b"\x02"])

    assert parameters[b"\x01"] == b"\x00\x01\x02"
    assert parameters[b"\x02"] == b"\x00\x01\x02"


def test_audio_configuration_lists_both_codecs():
    decoded = tlv.decode(SUPPORTED.audio_configuration, from_base64=True)

    assert len(decoded[b"\x01"]) > 0


def _selected_tlv(
    prebuffer=4000,
    fragment=4000,
    width=1920,
    height=1080,
    frame_rate=30,
    profile=2,
    level=2,
    bitrate=2000,
    iframe_interval=4000,
    audio_codec=0,
    channels=1,
    sample_rate=1,
    audio_bitrate=24,
    prebuffer_bytes=None,
) -> str:
    recording = tlv.encode(
        b"\x01",
        prebuffer_bytes
        if prebuffer_bytes is not None
        else struct.pack("<i", prebuffer),
        b"\x02",
        struct.pack("<q", 1),
        b"\x03",
        tlv.encode(
            b"\x01",
            b"\x00",
            b"\x02",
            tlv.encode(b"\x01", struct.pack("<i", fragment)),
        ),
    )
    video = tlv.encode(
        b"\x01",
        b"\x00",
        b"\x02",
        tlv.encode(
            b"\x01",
            bytes([profile]),
            b"\x02",
            bytes([level]),
            b"\x03",
            struct.pack("<i", bitrate),
            b"\x04",
            struct.pack("<i", iframe_interval),
        ),
        b"\x03",
        tlv.encode(
            b"\x01",
            struct.pack("<H", width),
            b"\x02",
            struct.pack("<H", height),
            b"\x03",
            bytes([frame_rate]),
        ),
    )
    audio = tlv.encode(
        b"\x01",
        bytes([audio_codec]),
        b"\x02",
        tlv.encode(
            b"\x01",
            bytes([channels]),
            b"\x02",
            b"\x00",
            b"\x03",
            bytes([sample_rate]),
            b"\x04",
            struct.pack("<I", audio_bitrate),
        ),
    )
    return to_base64_str(tlv.encode(b"\x01", recording, b"\x02", video, b"\x03", audio))


def test_selected_configuration_is_parsed():
    configuration = HomeKitSecureVideoSelectedConfiguration.from_tlv(_selected_tlv())

    assert configuration.prebuffer_milliseconds == 4000
    assert configuration.fragment_milliseconds == 4000
    assert configuration.width == 1920
    assert configuration.height == 1080
    assert configuration.frame_rate == 30
    assert configuration.video_profile == 2
    assert configuration.video_level == 2
    assert configuration.video_bitrate_kbps == 2000
    assert configuration.iframe_interval_milliseconds == 4000
    assert configuration.audio_codec == HomeKitSecureVideoRecordingAudioCodec.AAC_LC
    assert configuration.audio_channels == 1
    assert configuration.audio_sample_rate == HomeKitSecureVideoAudioSampleRate.KHZ_16
    assert configuration.audio_bitrate_kbps == 24


def test_selected_configuration_resolves_the_sample_rate_in_hertz():
    configuration = HomeKitSecureVideoSelectedConfiguration.from_tlv(
        _selected_tlv(sample_rate=5)
    )

    assert configuration.audio_sample_rate.hertz == 48000


def test_selected_configuration_parses_aac_eld():
    configuration = HomeKitSecureVideoSelectedConfiguration.from_tlv(
        _selected_tlv(audio_codec=1)
    )

    assert configuration.audio_codec == HomeKitSecureVideoRecordingAudioCodec.AAC_ELD


def test_selected_configuration_rejects_a_missing_section():
    without_video = to_base64_str(tlv.encode(b"\x01", tlv.encode(b"\x01", b"\x00")))

    with pytest.raises(HomeKitSecureVideoRecordingError, match="no field"):
        HomeKitSecureVideoSelectedConfiguration.from_tlv(without_video)


def test_selected_configuration_rejects_a_malformed_blob():
    with pytest.raises(HomeKitSecureVideoRecordingError, match="malformed"):
        HomeKitSecureVideoSelectedConfiguration.from_tlv(to_base64_str(b"\x01"))


def test_selected_configuration_rejects_a_short_numeric_field():
    truncated = _selected_tlv(prebuffer_bytes=b"\x10\x27")

    with pytest.raises(HomeKitSecureVideoRecordingError, match="expected 4"):
        HomeKitSecureVideoSelectedConfiguration.from_tlv(truncated)


def test_selected_configuration_rejects_an_empty_field():
    broken = to_base64_str(
        tlv.encode(
            b"\x01",
            tlv.encode(b"\x01", struct.pack("<i", 4000)),
            b"\x02",
            tlv.encode(b"\x01", b""),
            b"\x03",
            tlv.encode(b"\x01", b"\x00"),
        )
    )

    with pytest.raises(HomeKitSecureVideoRecordingError):
        HomeKitSecureVideoSelectedConfiguration.from_tlv(broken)


def test_selected_configuration_rejects_an_unknown_audio_codec():
    with pytest.raises(
        HomeKitSecureVideoRecordingError, match="unsupported audio codec"
    ):
        HomeKitSecureVideoSelectedConfiguration.from_tlv(_selected_tlv(audio_codec=9))


def test_selected_configuration_rejects_an_unknown_sample_rate():
    with pytest.raises(
        HomeKitSecureVideoRecordingError, match="unsupported audio sample rate"
    ):
        HomeKitSecureVideoSelectedConfiguration.from_tlv(_selected_tlv(sample_rate=9))
