"""Options flow for homekit_secure_video."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
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
    from .data import HomeKitSecureVideoOptionsData


def _resolution_options(index: int) -> list[str]:
    """Return the distinct width or height values HomeKit may negotiate."""
    return [
        str(value)
        for value in sorted({resolution[index] for resolution in SUPPORTED_RESOLUTIONS})
    ]


def _as_numbers(user_input: HomeKitSecureVideoOptionsData) -> dict[str, int | bool]:
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


class HomeKitSecureVideoOptionsFlow(OptionsFlow):
    """Options flow for HomeKit Secure Video."""

    async def async_step_init(
        self,
        user_input: HomeKitSecureVideoOptionsData | None = None,
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=_as_numbers(user_input))

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
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
                },
            ),
        )
