"""Construcción y apertura de capas onion para relays."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from faro.privacy.crypto import open_for_node, seal_for_node


ADDRESS_SIZE = 8


@dataclass(frozen=True, slots=True)
class OnionRelay:
    """Clave Curve25519 del relay y dirección del siguiente salto."""

    public_key: bytes
    next_address: bytes


def build_onion(payload: bytes, relays: Sequence[OnionRelay]) -> bytes:
    """Envuelve el payload desde el último relay hasta el primero.

    Cada relay puede abrir solo su capa y obtiene la dirección del
    siguiente salto junto con el ciphertext que debe reenviar.
    """
    if not relays:
        raise ValueError("la ruta onion debe incluir al menos un relay")

    packet = payload

    for relay in reversed(relays):
        if len(relay.next_address) != ADDRESS_SIZE:
            raise ValueError("cada next_address debe tener 8 bytes")

        plaintext = relay.next_address + packet
        packet = seal_for_node(relay.public_key, plaintext)

    return packet


def peel_onion(
    private_key: bytes,
    packet: bytes,
) -> tuple[bytes, bytes]:
    """Abre una capa y devuelve (dirección siguiente, paquete interior)."""
    plaintext = open_for_node(private_key, packet)

    if len(plaintext) < ADDRESS_SIZE:
        raise ValueError("capa onion truncada")

    next_address = plaintext[:ADDRESS_SIZE]
    inner_packet = plaintext[ADDRESS_SIZE:]
    return next_address, inner_packet