"""The streaming knobs an entry carries, shared by the flows that edit them."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.helpers import selector

from .const import (
    CONF_MAX_FPS,
    CONF_MAX_HEIGHT,
    CONF_MAX_WIDTH,
    CONF_REENCODE,
    CONF_STREAM_AUDIO,
    DEFAULT_MAX_FPS,
    DEFAULT_MAX_HEIGHT,
    DEFAULT_MAX_WIDTH,
    DEFAULT_REENCODE,
    DEFAULT_STREAM_AUDIO,
    MAX_FPS,
    MIN_FPS,
    SUPPORTED_RESOLUTIONS,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .data import HomeKitSecureVideoOptionsData

STREAMING_OPTION_KEYS: frozenset[str] = frozenset(
    {
        CONF_MAX_WIDTH,
        CONF_MAX_HEIGHT,
        CONF_MAX_FPS,
        CONF_REENCODE,
        CONF_STREAM_AUDIO,
    }
)


def _resolution_options(index: int) -> list[str]:
    """Return the distinct width or height values HomeKit may negotiate."""
    return [
        str(value)
        for value in sorted({resolution[index] for resolution in SUPPORTED_RESOLUTIONS})
    ]


def streaming_options_fields(
    options: Mapping[str, object],
) -> dict[vol.Marker, object]:
    """Return the schema fields for the streaming knobs, pre-filled."""
    return {
        vol.Optional(
            CONF_MAX_WIDTH,
            default=str(options.get(CONF_MAX_WIDTH, DEFAULT_MAX_WIDTH)),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=_resolution_options(0),
                mode=selector.SelectSelectorMode.DROPDOWN,
            ),
        ),
        vol.Optional(
            CONF_MAX_HEIGHT,
            default=str(options.get(CONF_MAX_HEIGHT, DEFAULT_MAX_HEIGHT)),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=_resolution_options(1),
                mode=selector.SelectSelectorMode.DROPDOWN,
            ),
        ),
        vol.Optional(
            CONF_MAX_FPS,
            default=options.get(CONF_MAX_FPS, DEFAULT_MAX_FPS),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=MIN_FPS,
                max=MAX_FPS,
                step=5,
                unit_of_measurement="fps",
                mode=selector.NumberSelectorMode.BOX,
            ),
        ),
        vol.Optional(
            CONF_REENCODE,
            default=options.get(CONF_REENCODE, DEFAULT_REENCODE),
        ): selector.BooleanSelector(),
        vol.Optional(
            CONF_STREAM_AUDIO,
            default=options.get(CONF_STREAM_AUDIO, DEFAULT_STREAM_AUDIO),
        ): selector.BooleanSelector(),
    }


def as_numbers(user_input: HomeKitSecureVideoOptionsData) -> dict[str, int | bool]:
    """
    Store the resolution limits as numbers.

    The dropdowns hand back strings, and everything downstream compares them
    against the resolutions offered to HomeKit — which are numbers.
    """
    stored: dict[str, int | bool] = dict(user_input)  # type: ignore[arg-type]
    for key in (CONF_MAX_WIDTH, CONF_MAX_HEIGHT, CONF_MAX_FPS):
        if key in stored:
            stored[key] = int(stored[key])
    return stored
