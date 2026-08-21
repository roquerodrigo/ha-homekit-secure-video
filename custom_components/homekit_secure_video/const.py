"""Constants for homekit_secure_video."""

from __future__ import annotations

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "homekit_secure_video"
MANUFACTURER = "Home Assistant"
MODEL = "HomeKit Secure Video Camera"

CONF_CAMERA_ENTITY_ID = "camera_entity_id"
CONF_PAIRING_CODE = "pairing_code"
CONF_SETUP_ID = "setup_id"
CONF_MOTION_ENTITY_ID = "motion_entity_id"
CONF_ALWAYS_ON_MOTION = "always_on_motion"
CONF_DOORBELL_ENTITY_ID = "doorbell_entity_id"
CONF_MAX_WIDTH = "max_width"
CONF_MAX_HEIGHT = "max_height"
CONF_MAX_FPS = "max_fps"
CONF_REENCODE = "reencode"
CONF_STREAM_AUDIO = "stream_audio"

FIRST_HAP_PORT = 21064
LAST_HAP_PORT = 21264

DEFAULT_MAX_WIDTH = 1920
DEFAULT_MAX_HEIGHT = 1080
DEFAULT_MAX_FPS = 30
DEFAULT_REENCODE = True
DEFAULT_ALWAYS_ON_MOTION = False
DEFAULT_STREAM_AUDIO = True

MIN_FPS = 10
MAX_FPS = 60

# The resolutions a controller may request for the live stream. HomeKit picks
# from this list in ways that do not always follow the display it renders on,
# so it mirrors what Scrypted offers rather than trying to be clever.
SUPPORTED_RESOLUTIONS: tuple[tuple[int, int, int], ...] = (
    (3840, 2160, 30),
    (2880, 1620, 30),
    (2560, 1440, 30),
    (1920, 1080, 30),
    (1280, 720, 30),
    (960, 540, 30),
    (640, 360, 30),
    # Requested by Apple Watch.
    (320, 240, 15),
)

# HomeKit expects a camera to serve several streams at once — a phone, a Mac
# and the hub can all be watching.
STREAM_COUNT = 8
