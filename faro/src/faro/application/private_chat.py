"""Interfaz de chat privado sobre el transporte onion de FaroNet."""

from __future__ import annotations

from collections.abc import Sequence

from faro.link.frame import Frame
from faro.mesh.onion import OnionRelay
from faro.mesh.transport import (
    decrypt_private_message,
    make_private_message_frames,
)


class PrivateChat:
    """Prepara mensajes privados para enviar y abre ciphertext del destinatario.

    La selección de ruta y entrega de tramas pertenecen al nodo mesh; esta
    clase aplica la interfaz de aplicación sin introducir una ruta de fallback.
    """

    def __init__(self, end_to_end_key: bytes) -> None:
        if len(end_to_end_key) != 32:
            raise ValueError("end_to_end_key debe tener 32 bytes")
        self._key = end_to_end_key

    def encode_outbound(
        self,
        text: str,
        relays: Sequence[OnionRelay],
        source_address: bytes,
        first_relay_address: bytes,
        *,
        first_sequence: int = 0,
    ) -> tuple[Frame, ...]:
        if not isinstance(text, str) or not text:
            raise ValueError("el mensaje debe ser texto no vacío")
        return make_private_message_frames(
            text.encode("utf-8"),
            self._key,
            relays,
            source_address,
            first_relay_address,
            first_sequence=first_sequence,
        )

    def decode_inbound(self, encrypted_payload: bytes) -> str:
        plaintext = decrypt_private_message(encrypted_payload, self._key)
        try:
            return plaintext.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("el mensaje recibido no contiene UTF-8 válido") from exc
