"""Config flow for homekit_secure_video."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING, cast

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.camera import CameraEntityFeature
from homeassistant.const import ATTR_SUPPORTED_FEATURES, CONF_PORT, Platform
from homeassistant.core import callback
from homeassistant.helpers import selector
from pyhap.util import generate_pincode, generate_setup_id

from .const import (
    CONF_ALWAYS_ON_MOTION,
    CONF_CAMERA_ENTITY_ID,
    CONF_MOTION_ENTITY_ID,
    CONF_PAIRING_CODE,
    CONF_REENCODE,
    CONF_SETUP_ID,
    DEFAULT_ALWAYS_ON_MOTION,
    DEFAULT_REENCODE,
    DOMAIN,
    FIRST_HAP_PORT,
    LAST_HAP_PORT,
)
from .options_flow import HomeKitSecureVideoOptionsFlow

if TYPE_CHECKING:
    from .data import HomeKitSecureVideoConfigData, HomeKitSecureVideoConfigEntry


def _camera_schema(
    default_config: HomeKitSecureVideoConfigData | None = None,
    *,
    include_reencode: bool = False,
) -> vol.Schema:
    """
    Build the camera selection schema, optionally pre-filled.

    Re-encoding is offered when adding a camera, so a compatible one need not
    pay for it from the start; afterwards it lives in the options flow, which
    is also where it is stored.
    """
    camera_default = (
        default_config["camera_entity_id"] if default_config else vol.UNDEFINED
    )
    # The motion sensor is offered as a suggestion rather than a default:
    # a default would be re-applied on submit, making the field impossible
    # to clear.
    motion_marker = vol.Optional(
        CONF_MOTION_ENTITY_ID,
        description={"suggested_value": default_config.get("motion_entity_id")}
        if default_config
        else None,
    )
    always_on_default = (
        default_config.get("always_on_motion", DEFAULT_ALWAYS_ON_MOTION)
        if default_config
        else DEFAULT_ALWAYS_ON_MOTION
    )
    fields: dict[vol.Marker, object] = {
        vol.Required(
            CONF_CAMERA_ENTITY_ID, default=camera_default
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=Platform.CAMERA),
        ),
        motion_marker: selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=Platform.BINARY_SENSOR,
                device_class=BinarySensorDeviceClass.MOTION,
            ),
        ),
        vol.Optional(
            CONF_ALWAYS_ON_MOTION, default=always_on_default
        ): selector.BooleanSelector(),
    }
    if include_reencode:
        fields[vol.Optional(CONF_REENCODE, default=DEFAULT_REENCODE)] = (
            selector.BooleanSelector()
        )
    return vol.Schema(fields)


def _is_port_free(port: int) -> bool:
    """Return whether the given TCP port can be bound right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as test_socket:
        test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            test_socket.bind(("", port))
        except OSError:
            return False
    return True


class HomeKitSecureVideoFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for HomeKit Secure Video."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: HomeKitSecureVideoConfigEntry,  # noqa: ARG004
    ) -> HomeKitSecureVideoOptionsFlow:
        """Return the options flow handler."""
        return HomeKitSecureVideoOptionsFlow()

    # The narrowed ``HomeKitSecureVideoConfigData`` parameter is intentional
    # — HA's base class declares ``dict[str, Any] | None`` here, and we trade
    # strict LSP compliance for stronger typing of our own user_input schema.
    async def async_step_user(  # type: ignore[override]
        self,
        user_input: HomeKitSecureVideoConfigData | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Pick the camera to publish and reserve a port for its accessory."""
        errors: dict[str, str] = {}

        if user_input is not None:
            camera_entity_id = user_input["camera_entity_id"]
            errors = self._validate_camera(camera_entity_id)
            if not errors:
                await self.async_set_unique_id(camera_entity_id)
                self._abort_if_unique_id_configured()
                port = await self._async_reserve_port()
                if port is None:
                    errors = {"base": "no_free_port"}
                else:
                    reencode = dict(user_input).pop(CONF_REENCODE, DEFAULT_REENCODE)
                    camera = {
                        key: value
                        for key, value in user_input.items()
                        if key != CONF_REENCODE
                    }
                    return self.async_create_entry(
                        title=self._camera_name(camera_entity_id),
                        options={CONF_REENCODE: bool(reencode)},
                        data={
                            **camera,
                            CONF_PORT: port,
                            # HAP-python regenerates both on every start, which
                            # would silently invalidate the code and QR code
                            # this integration publishes as entities.
                            CONF_PAIRING_CODE: generate_pincode().decode(),
                            CONF_SETUP_ID: generate_setup_id(),
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=_camera_schema(user_input, include_reencode=True),
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: HomeKitSecureVideoConfigData | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Let the user change the camera or the motion trigger of an entry."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        existing = cast("HomeKitSecureVideoConfigData", entry.data)

        if user_input is not None:
            camera_entity_id = user_input["camera_entity_id"]
            errors = self._validate_camera(camera_entity_id)
            if not errors and self._is_taken_by_another_entry(camera_entity_id, entry):
                errors = {CONF_CAMERA_ENTITY_ID: "already_configured"}
            if not errors:
                # The camera block is replaced rather than merged so clearing
                # the motion sensor actually drops it from the entry.
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=camera_entity_id,
                    title=self._camera_name(camera_entity_id),
                    data={
                        **dict(user_input),
                        CONF_PORT: existing["port"],
                        CONF_PAIRING_CODE: existing["pairing_code"],
                        CONF_SETUP_ID: existing["setup_id"],
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_camera_schema(user_input or existing),
            errors=errors,
        )

    def _is_taken_by_another_entry(
        self, camera_entity_id: str, entry: HomeKitSecureVideoConfigEntry
    ) -> bool:
        """Return whether a different entry already publishes this camera."""
        configured = self.hass.config_entries.async_entry_for_domain_unique_id(
            DOMAIN, camera_entity_id
        )
        return configured is not None and configured.entry_id != entry.entry_id

    def _validate_camera(self, camera_entity_id: str) -> dict[str, str]:
        """Check the camera exists and can serve a stream."""
        state = self.hass.states.get(camera_entity_id)
        if state is None:
            return {CONF_CAMERA_ENTITY_ID: "camera_not_found"}

        supported_features = int(state.attributes.get(ATTR_SUPPORTED_FEATURES, 0))
        if not supported_features & CameraEntityFeature.STREAM:
            return {CONF_CAMERA_ENTITY_ID: "camera_without_stream"}
        return {}

    def _camera_name(self, camera_entity_id: str) -> str:
        """Return the friendly name to publish the accessory under."""
        state = self.hass.states.get(camera_entity_id)
        return state.name if state is not None else camera_entity_id

    async def _async_reserve_port(self) -> int | None:
        """Return the lowest HAP port not taken by another entry."""
        taken = {
            entry.data[CONF_PORT]
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if CONF_PORT in entry.data
        }
        for port in range(FIRST_HAP_PORT, LAST_HAP_PORT + 1):
            if port in taken:
                continue
            if await self.hass.async_add_executor_job(_is_port_free, port):
                return port
        return None
