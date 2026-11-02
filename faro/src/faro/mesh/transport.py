"""Integración de cifrado E2E, onion routing y tramas Faro."""

from __future__ import annotations

from collections.abc import Sequence

from nacl.exceptions import CryptoError as NaClCryptoError
from nacl.utils import random

from faro.link.frame import Frame, FrameType
from faro.mesh.fragmentation import fragment_message
from faro.mesh.onion import OnionRelay, build_onion, peel_onion
from faro.privacy.crypto import (
    CryptoError,
    decrypt_message,
    encrypt_message,
)


PRIVATE_MESSAGE_AAD = b"FaroNet/private-message/v1"
MIN_ONION_RELAYS = 3
ADDRESS_SIZE = 8

# XChaCha20-Poly1305 agrega 24 bytes de nonce y 16 bytes de autenticación.
PRIVATE_CIPHERTEXT_SIZE = 512
PRIVATE_ENVELOPE_SIZE = PRIVATE_CIPHERTEXT_SIZE - 24 - 16
PRIVATE_MESSAGE_MAX_SIZE = PRIVATE_ENVELOPE_SIZE - 2


def _validate_address(address: bytes, name: str) -> None:
    if not isinstance(address, bytes) or len(address) != ADDRESS_SIZE:
        raise ValueError(f"{name} debe ser de {ADDRESS_SIZE} bytes")


def _make_frames(
    fragments: Sequence[bytes],
    source_address: bytes,
    destination_address: bytes,
    first_sequence: int,
) -> tuple[Frame, ...]:
    _validate_address(source_address, "source_address")
    _validate_address(destination_address, "destination_address")

    if not 0 <= first_sequence <= 0xFFFF:
        raise ValueError("first_sequence debe estar entre 0 y 65535")

    return tuple(
        Frame(
            kind=FrameType.DATA,
            source=source_address,
            destination=destination_address,
            sequence=(first_sequence + index) & 0xFFFF,
            payload=fragment,
        )
        for index, fragment in enumerate(fragments)
    )


def _pad_private_message(plaintext: bytes) -> bytes:
    if not isinstance(plaintext, bytes):
        raise TypeError("plaintext debe ser bytes")
    if len(plaintext) > PRIVATE_MESSAGE_MAX_SIZE:
        raise ValueError(
            f"el mensaje privado excede {PRIVATE_MESSAGE_MAX_SIZE} bytes"
        )

    length = len(plaintext).to_bytes(2, "big")
    padding_size = PRIVATE_ENVELOPE_SIZE - 2 - len(plaintext)
    return length + plaintext + random(padding_size)


def _unpad_private_message(envelope: bytes) -> bytes:
    if len(envelope) != PRIVATE_ENVELOPE_SIZE:
        raise CryptoError("sobre privado de tamaño inválido")

    message_length = int.from_bytes(envelope[:2], "big")
    if message_length > PRIVATE_MESSAGE_MAX_SIZE:
        raise CryptoError("longitud de mensaje privado inválida")

    return envelope[2 : 2 + message_length]


def make_private_message_frames(
    plaintext: bytes,
    end_to_end_key: bytes,
    relays: Sequence[OnionRelay],
    source_address: bytes,
    first_relay_address: bytes,
    *,
    first_sequence: int = 0,
) -> tuple[Frame, ...]:
    """Crea tramas hacia el primer relay usando al menos tres relays.

    `relays` está en orden de recorrido. Cada entrada contiene la clave
    Curve25519 pública de un relay y la dirección del siguiente salto.
    """
    if len(relays) < MIN_ONION_RELAYS:
        raise ValueError(
            f"se requieren al menos {MIN_ONION_RELAYS} relays"
        )

    _validate_address(source_address, "source_address")
    _validate_address(first_relay_address, "first_relay_address")

    envelope = _pad_private_message(plaintext)
    encrypted_payload = encrypt_message(
        end_to_end_key,
        envelope,
        aad=PRIVATE_MESSAGE_AAD,
    )
    if len(encrypted_payload) != PRIVATE_CIPHERTEXT_SIZE:
        raise RuntimeError("tamaño inesperado del ciphertext privado")

    onion_packet = build_onion(encrypted_payload, relays)
    fragments = fragment_message(onion_packet)

    return _make_frames(
        fragments,
        source_address,
        first_relay_address,
        first_sequence,
    )


def relay_private_packet(
    onion_packet: bytes,
    relay_private_key: bytes,
    relay_address: bytes,
    *,
    first_sequence: int = 0,
) -> tuple[bytes, tuple[Frame, ...]]:
    """Abre una capa onion y prepara tramas hacia el siguiente salto.

    El paquete debe estar reensamblado antes de pasarlo a esta función.
    Devuelve la dirección siguiente y las tramas que debe enviar el relay.
    """
    _validate_address(relay_address, "relay_address")

    next_address, inner_packet = peel_onion(relay_private_key, onion_packet)
    fragments = fragment_message(inner_packet)
    frames = _make_frames(
        fragments,
        relay_address,
        next_address,
        first_sequence,
    )
    return next_address, frames


def decrypt_private_message(
    encrypted_payload: bytes,
    end_to_end_key: bytes,
) -> bytes:
    """Descifra, autentica y quita el padding del mensaje final."""
    if len(encrypted_payload) != PRIVATE_CIPHERTEXT_SIZE:
        raise CryptoError("ciphertext privado de tamaño inválido")

    try:
        envelope = decrypt_message(
            end_to_end_key,
            encrypted_payload,
            aad=PRIVATE_MESSAGE_AAD,
        )
    except NaClCryptoError as exc:
        raise CryptoError("falló la autenticación del mensaje") from exc

    return _unpad_private_message(envelope)