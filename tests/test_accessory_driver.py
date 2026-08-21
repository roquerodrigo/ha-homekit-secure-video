from __future__ import annotations

from uuid import uuid4

import pytest
from pyhap.accessory import Accessory

from custom_components.homekit_secure_video.accessory import (
    HomeKitSecureVideoAccessoryDriver,
)


@pytest.fixture
def pairing_changes():
    return []


@pytest.fixture
def driver(hass, tmp_path, pairing_changes):
    driver = HomeKitSecureVideoAccessoryDriver(
        lambda: pairing_changes.append(1),
        address="127.0.0.1",
        port=21064,
        persist_file=str(tmp_path / "accessory.state"),
        loop=hass.loop,
    )
    driver.add_accessory(Accessory(driver, "Test"))
    return driver


async def test_pairing_a_controller_is_announced(driver, pairing_changes):
    client_uuid = uuid4()

    assert driver.pair(str(client_uuid).encode(), b"\x01" * 32, b"\x00")
    assert len(pairing_changes) == 1


async def test_unpairing_a_controller_is_announced(driver, pairing_changes):
    client_uuid = uuid4()
    driver.pair(str(client_uuid).encode(), b"\x01" * 32, b"\x00")

    driver.unpair(client_uuid)

    assert len(pairing_changes) == 2
    assert not driver.state.paired


async def test_a_broken_listener_does_not_fail_pairing(hass, tmp_path):
    from pyhap.accessory import Accessory

    from custom_components.homekit_secure_video.accessory import (
        HomeKitSecureVideoAccessoryDriver,
    )

    def explode() -> None:
        message = "listener is broken"
        raise RuntimeError(message)

    driver = HomeKitSecureVideoAccessoryDriver(
        explode,
        address="127.0.0.1",
        port=21064,
        persist_file=str(tmp_path / "accessory.state"),
        loop=hass.loop,
    )
    driver.add_accessory(Accessory(driver, "Test"))

    assert driver.pair(str(uuid4()).encode(), b"\x01" * 32, b"\x00")
    assert driver.state.paired
