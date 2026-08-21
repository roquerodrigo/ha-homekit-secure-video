"""Options flow for homekit_secure_video."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow

from .streaming_options import as_numbers, streaming_options_fields

if TYPE_CHECKING:
    from .data import HomeKitSecureVideoOptionsData


class HomeKitSecureVideoOptionsFlow(OptionsFlow):
    """Options flow for HomeKit Secure Video."""

    async def async_step_init(
        self,
        user_input: HomeKitSecureVideoOptionsData | None = None,
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=as_numbers(user_input))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(streaming_options_fields(self.config_entry.options)),
        )
