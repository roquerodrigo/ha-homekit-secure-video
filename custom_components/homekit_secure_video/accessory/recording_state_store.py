"""Where the recording state of one accessory is kept between restarts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from homeassistant.helpers.storage import Store

from ..const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..data import HomeKitSecureVideoRecordingState

STORAGE_VERSION: Final = 1
# A hub rewrites the same handful of characteristics in a burst when it
# reconnects; one write to disk per burst is plenty.
SAVE_DELAY_SECONDS: Final = 1


class HomeKitSecureVideoRecordingStateStore:
    """
    Where the recording state of one accessory is kept between restarts.

    It sits next to the HAP pairing state under `.storage/`, named after the
    config entry, and goes away with the pairing: a hub that pairs afresh
    negotiates afresh.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the store for one config entry."""
        self._store: Store[HomeKitSecureVideoRecordingState] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.recording"
        )
        self._pending: HomeKitSecureVideoRecordingState | None = None

    async def async_load(self) -> HomeKitSecureVideoRecordingState | None:
        """Return the state saved by the last run, if any."""
        state = await self._store.async_load()
        if state is not None:
            state.setdefault("source_profile", None)
        return state

    def save(self, state: HomeKitSecureVideoRecordingState) -> None:
        """Write the state shortly, coalescing the writes of one burst."""
        self._pending = state
        self._store.async_delay_save(lambda: state, SAVE_DELAY_SECONDS)

    async def async_flush(self) -> None:
        """Write whatever is still waiting, before the accessory goes away."""
        pending = self._pending
        self._pending = None
        if pending is not None:
            await self._store.async_save(pending)

    async def async_remove(self) -> None:
        """Forget the state, along with anything waiting to be written."""
        self._pending = None
        await self._store.async_remove()
