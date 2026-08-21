"""Encrypts and decrypts the frames of one HomeKit Data Stream connection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from pyhap.hap_crypto import pad_tls_nonce

from .constants import NONCE_LENGTH
from .frame import HomeKitSecureVideoDataStreamFrame, build_header

if TYPE_CHECKING:
    from .session_keys import HomeKitSecureVideoDataStreamSessionKeys


class HomeKitSecureVideoDataStreamFrameCodec:
    """
    Encrypts and decrypts the frames of one HomeKit Data Stream connection.

    Each direction has its own key and its own nonce counter, and neither is
    ever reset: a decryption that fails leaves the counter untouched so the
    caller can retry the same frame with another candidate key.
    """

    def __init__(self, keys: HomeKitSecureVideoDataStreamSessionKeys) -> None:
        """Initialize the codec with the keys of one session."""
        self._outgoing_cipher = ChaCha20Poly1305(keys.accessory_to_controller)
        self._incoming_cipher = ChaCha20Poly1305(keys.controller_to_accessory)
        self._outgoing_nonce = 0
        self._incoming_nonce = 0

    def encrypt(self, payload: bytes) -> bytes:
        """Frame and encrypt one payload, advancing the outgoing nonce."""
        header = build_header(len(payload))
        sealed = self._outgoing_cipher.encrypt(
            _nonce(self._outgoing_nonce), payload, header
        )
        self._outgoing_nonce += 1
        return header + sealed

    def decrypt(self, frame: HomeKitSecureVideoDataStreamFrame) -> bytes | None:
        """
        Decrypt one frame, or return None when it does not authenticate.

        The nonce only advances on success, which is what lets an unidentified
        connection try the same frame against every prepared session.
        """
        try:
            payload = self._incoming_cipher.decrypt(
                _nonce(self._incoming_nonce),
                frame.ciphertext + frame.auth_tag,
                frame.header,
            )
        except InvalidTag:
            return None

        self._incoming_nonce += 1
        return payload


def _nonce(counter: int) -> bytes:
    """Build the 96-bit nonce from the little-endian frame counter."""
    return pad_tls_nonce(counter.to_bytes(NONCE_LENGTH, "little"))
