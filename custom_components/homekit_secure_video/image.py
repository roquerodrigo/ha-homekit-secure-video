"""Image platform for homekit_secure_video."""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

import pyqrcode
from homeassistant.components.image import ImageEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from .entity import HomeKitSecureVideoEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import HomeKitSecureVideoDataUpdateCoordinator
    from .data import HomeKitSecureVideoConfigEntry

QR_CODE_SCALE = 6
QR_CODE_QUIET_ZONE = 2


def _render_qr_code(setup_uri: str) -> bytes:
    """Render the HomeKit setup payload as a PNG QR code."""
    buffer = BytesIO()
    pyqrcode.create(setup_uri).png(
        buffer, scale=QR_CODE_SCALE, quiet_zone=QR_CODE_QUIET_ZONE
    )
    return buffer.getvalue()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeKitSecureVideoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the image platform."""
    async_add_entities(
        [HomeKitSecureVideoPairingQrCodeImage(hass, entry.runtime_data.coordinator)]
    )


class HomeKitSecureVideoPairingQrCodeImage(HomeKitSecureVideoEntity, ImageEntity):
    """QR code that pairs the accessory when scanned with the Home app."""

    _attr_content_type = "image/png"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "pairing_qr_code"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: HomeKitSecureVideoDataUpdateCoordinator,
    ) -> None:
        """Initialize both the coordinator entity and the image entity."""
        super().__init__(coordinator)
        ImageEntity.__init__(self, hass)
        self._rendered_setup_uri: str | None = None
        self._rendered_qr_code: bytes | None = None
        self._published_setup_uri: str = coordinator.data["setup_uri"]
        self._attr_image_last_updated = dt_util.utcnow()

    @property
    def unique_id(self) -> str:
        """Return the unique id of the image."""
        return f"{self.coordinator.config_entry.entry_id}_pairing_qr_code"

    async def async_image(self) -> bytes | None:
        """Return the QR code of the current setup payload."""
        setup_uri = self.coordinator.data["setup_uri"]
        if not setup_uri:
            return None

        if setup_uri != self._rendered_setup_uri:
            self._rendered_qr_code = await self.hass.async_add_executor_job(
                _render_qr_code, setup_uri
            )
            self._rendered_setup_uri = setup_uri

        return self._rendered_qr_code

    @callback
    def _handle_coordinator_update(self) -> None:
        """
        Stamp a new timestamp whenever the setup payload changes.

        Compared against the payload last seen, not the one last rendered: the
        entity is diagnostic and usually nobody ever fetches it, and a
        comparison against what was rendered would restamp on every unrelated
        status change and invalidate the frontend's cached URL each time.
        """
        setup_uri = self.coordinator.data["setup_uri"]
        if setup_uri != self._published_setup_uri:
            self._published_setup_uri = setup_uri
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()
