"""Persistent notification carrying the pairing code of an unpaired accessory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components import persistent_notification
from homeassistant.core import callback
from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import HomeKitSecureVideoDataUpdateCoordinator

TRANSLATION_PREFIX = f"component.{DOMAIN}.common"


class HomeKitSecureVideoPairingNotification:
    """
    Shows the pairing code only while the accessory waits to be paired.

    The code never goes into entity state: state is readable by every user and
    lands in the recorder history, where it would stay valid for pairing again.
    """

    def __init__(
        self,
        coordinator: HomeKitSecureVideoDataUpdateCoordinator,
        title_template: str,
        message_template: str,
    ) -> None:
        """Initialize with the templates translated to the configured language."""
        self._coordinator = coordinator
        self._title_template = title_template
        self._message_template = message_template
        self._shown = False

    @classmethod
    async def async_create(
        cls,
        hass: HomeAssistant,
        coordinator: HomeKitSecureVideoDataUpdateCoordinator,
    ) -> HomeKitSecureVideoPairingNotification:
        """Build the notification with the texts of the configured language."""
        translations = await async_get_translations(
            hass, hass.config.language, "common", {DOMAIN}
        )
        return cls(
            coordinator,
            translations[f"{TRANSLATION_PREFIX}.pairing_notification_title"],
            translations[f"{TRANSLATION_PREFIX}.pairing_notification_message"],
        )

    @property
    def notification_id(self) -> str:
        """Return the id that ties the notification to its config entry."""
        return f"{DOMAIN}_{self._coordinator.config_entry.entry_id}_pairing"

    @callback
    def async_handle_coordinator_update(self) -> None:
        """Show the code when the accessory becomes pairable, dismiss it otherwise."""
        status = self._coordinator.data
        awaiting_pairing = bool(status["pairing_code"]) and not status["paired"]
        if awaiting_pairing == self._shown:
            return
        if awaiting_pairing:
            self._show(status["pairing_code"])
        else:
            self.async_dismiss()

    @callback
    def async_dismiss(self) -> None:
        """Remove the notification, if it is showing."""
        self._shown = False
        persistent_notification.async_dismiss(
            self._coordinator.hass, self.notification_id
        )

    def _show(self, pairing_code: str) -> None:
        camera = self._coordinator.config_entry.title
        persistent_notification.async_create(
            self._coordinator.hass,
            self._message_template.format(camera=camera, pairing_code=pairing_code),
            title=self._title_template.format(camera=camera),
            notification_id=self.notification_id,
        )
        self._shown = True
