"""Fragmentación y reensamblado de paquetes para el MTU Faro."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field


MAX_FRAME_PAYLOAD = 102
FRAGMENT_VERSION = 1
MESSAGE_ID_SIZE = 8
FRAGMENT_HEADER_SIZE = 1 + MESSAGE_ID_SIZE + 2 + 2
MAX_FRAGMENT_DATA = MAX_FRAME_PAYLOAD - FRAGMENT_HEADER_SIZE
MAX_FRAGMENT_COUNT = 0xFFFF


class FragmentError(ValueError):
    """Fragmento inválido o inconsistente."""


def fragment_message(
    message: bytes,
    message_id: bytes | None = None,
) -> tuple[bytes, ...]:
    """Divide un mensaje en payloads compatibles con una trama Faro."""
    if not isinstance(message, bytes):
        raise TypeError("message debe ser bytes")
    if message_id is None:
        message_id = secrets.token_bytes(MESSAGE_ID_SIZE)
    if not isinstance(message_id, bytes) or len(message_id) != MESSAGE_ID_SIZE:
        raise ValueError(f"message_id debe tener {MESSAGE_ID_SIZE} bytes")

    chunks = [
        message[offset : offset + MAX_FRAGMENT_DATA]
        for offset in range(0, len(message), MAX_FRAGMENT_DATA)
    ]
    if not chunks:
        chunks = [b""]
    if len(chunks) > MAX_FRAGMENT_COUNT:
        raise ValueError("el mensaje requiere demasiados fragmentos")

    count = len(chunks)
    return tuple(
        bytes((FRAGMENT_VERSION,))
        + message_id
        + index.to_bytes(2, "big")
        + count.to_bytes(2, "big")
        + chunk
        for index, chunk in enumerate(chunks)
    )


@dataclass
class _Assembly:
    created_at: float
    count: int
    fragments: dict[int, bytes] = field(default_factory=dict)
    total_bytes: int = 0


class FragmentReassembler:
    """Reensambla mensajes con límites de memoria y vencimiento."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 30.0,
        max_messages: int = 128,
        max_total_bytes: int = 1_000_000,
    ) -> None:
        if ttl_seconds <= 0 or max_messages < 1 or max_total_bytes < 1:
            raise ValueError("límites de reensamblado inválidos")

        self._ttl = ttl_seconds
        self._max_messages = max_messages
        self._max_total_bytes = max_total_bytes
        self._assemblies: dict[bytes, _Assembly] = {}
        self._buffered_bytes = 0

    @property
    def buffered_bytes(self) -> int:
        """Número de bytes retenidos en mensajes incompletos."""
        return self._buffered_bytes

    def add(self, fragment: bytes) -> bytes | None:
        """Agrega un fragmento; devuelve el mensaje cuando esté completo."""
        self.expire()

        if not isinstance(fragment, bytes):
            raise FragmentError("el fragmento debe ser bytes")
        if len(fragment) < FRAGMENT_HEADER_SIZE:
            raise FragmentError("fragmento demasiado corto")
        if len(fragment) > MAX_FRAME_PAYLOAD:
            raise FragmentError("fragmento excede el payload máximo")
        if fragment[0] != FRAGMENT_VERSION:
            raise FragmentError("versión de fragmentación desconocida")

        message_id = fragment[1 : 1 + MESSAGE_ID_SIZE]
        index_start = 1 + MESSAGE_ID_SIZE
        index = int.from_bytes(fragment[index_start : index_start + 2], "big")
        count = int.from_bytes(fragment[index_start + 2 : index_start + 4], "big")
        data = fragment[FRAGMENT_HEADER_SIZE:]

        if count < 1 or index >= count:
            raise FragmentError("índice o cantidad de fragmentos inválidos")

        assembly = self._assemblies.get(message_id)
        if assembly is None:
            if len(self._assemblies) >= self._max_messages:
                raise FragmentError("límite de mensajes incompletos alcanzado")
            assembly = _Assembly(time.monotonic(), count)
            self._assemblies[message_id] = assembly
        elif assembly.count != count:
            self._discard(message_id)
            raise FragmentError("cantidad inconsistente para el mismo message_id")

        previous = assembly.fragments.get(index)
        if previous is not None:
            if previous != data:
                self._discard(message_id)
                raise FragmentError("fragmento duplicado con contenido distinto")
            return None

        if self._buffered_bytes + len(data) > self._max_total_bytes:
            self._discard(message_id)
            raise FragmentError("límite de memoria de reensamblado alcanzado")

        assembly.fragments[index] = data
        assembly.total_bytes += len(data)
        self._buffered_bytes += len(data)

        if len(assembly.fragments) != assembly.count:
            return None

        message = b"".join(
            assembly.fragments[i] for i in range(assembly.count)
        )
        self._discard(message_id)
        return message

    def expire(self) -> int:
        """Descarta y cuenta ensamblajes vencidos."""
        now = time.monotonic()
        expired = [
            message_id
            for message_id, assembly in self._assemblies.items()
            if now - assembly.created_at >= self._ttl
        ]
        for message_id in expired:
            self._discard(message_id)
        return len(expired)

    def clear(self) -> None:
        """Descarta todos los mensajes incompletos, por ejemplo al activar pánico."""
        self._assemblies.clear()
        self._buffered_bytes = 0

    def _discard(self, message_id: bytes) -> None:
        assembly = self._assemblies.pop(message_id, None)
        if assembly is not None:
            self._buffered_bytes -= assembly.total_bytes