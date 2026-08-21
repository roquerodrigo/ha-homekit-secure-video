"""Runtime data stored on entry.runtime_data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.loader import Integration

    from ..accessory import HomeKitSecureVideoAccessoryManager
    from ..coordinator import HomeKitSecureVideoDataUpdateCoordinator


@dataclass
class HomeKitSecureVideoData:
    """Data stored on entry.runtime_data for the HomeKit Secure Video."""

    accessory_manager: HomeKitSecureVideoAccessoryManager
    coordinator: HomeKitSecureVideoDataUpdateCoordinator
    integration: Integration
