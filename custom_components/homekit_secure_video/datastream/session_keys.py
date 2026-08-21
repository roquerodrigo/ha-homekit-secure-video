"""Encryption keys derived for one HomeKit Data Stream session."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Self

from pyhap.hap_crypto import hap_hkdf

from .constants import (
    ACCESSORY_TO_CONTROLLER_INFO,
    CONTROLLER_TO_ACCESSORY_INFO,
    KEY_SALT_LENGTH,
)


@dataclass(frozen=True)
class HomeKitSecureVideoDataStreamSessionKeys:
    """Encryption keys derived for one HomeKit Data Stream session."""

    accessory_to_controller: bytes
    controller_to_accessory: bytes
    accessory_key_salt: bytes

    @classmethod
    def derive(cls, shared_key: bytes, controller_key_salt: bytes) -> Self:
        """
        Derive both directions from the HAP session secret.

        The salt is the controller's random half followed by ours, and the two
        keys differ only by the HKDF info string — the same construction the
        controller runs on its side, so both ends land on the same keys.
        """
        accessory_key_salt = os.urandom(KEY_SALT_LENGTH)
        salt = controller_key_salt + accessory_key_salt
        return cls(
            accessory_to_controller=hap_hkdf(
                shared_key, salt, ACCESSORY_TO_CONTROLLER_INFO
            ),
            controller_to_accessory=hap_hkdf(
                shared_key, salt, CONTROLLER_TO_ACCESSORY_INFO
            ),
            accessory_key_salt=accessory_key_salt,
        )
