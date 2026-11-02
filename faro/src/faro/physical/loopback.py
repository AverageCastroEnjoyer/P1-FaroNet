"""Backend loopback para integración sin Raspberry Pi."""

from __future__ import annotations

from queue import Empty, Queue

from faro.link.frame import MAX_FRAME_SIZE


class LoopbackEndpoint:
    """Extremo de un par loopback; lo enviado aparece en el otro extremo."""

    def __init__(self) -> None:
        self._inbox: Queue[bytes | None] = Queue()
        self._peer: LoopbackEndpoint | None = None
        self._closed = False
        self._peer_closed = False

    def _connect(self, peer: LoopbackEndpoint) -> None:
        self._peer = peer

    def send_symbols(self, raw_bytes: bytes) -> None:
        if self._closed:
            raise RuntimeError("el backend está cerrado")
        if self._peer is None:
            raise RuntimeError("el backend no está conectado")
        if self._peer._closed:
            raise RuntimeError("el backend remoto está cerrado")
        if not isinstance(raw_bytes, bytes):
            raise TypeError("raw_bytes debe ser bytes")
        if len(raw_bytes) > MAX_FRAME_SIZE:
            raise ValueError(f"la trama excede {MAX_FRAME_SIZE} bytes")

        self._peer._inbox.put(bytes(raw_bytes))

    def receive_symbols(self, timeout_seconds: float = 1.0) -> bytes | None:
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds no puede ser negativo")
        if self._closed or self._peer_closed:
            return None

        try:
            item = self._inbox.get(timeout=timeout_seconds)
        except Empty:
            return None

        if item is None:
            self._peer_closed = True
            return None

        return item

    def carrier_detected(self) -> bool:
        return not self._inbox.empty()

    def close(self) -> None:
        if self._closed:
            return

        self._closed = True
        if self._peer is not None:
            self._peer._inbox.put(None)


def create_loopback_pair() -> tuple[LoopbackEndpoint, LoopbackEndpoint]:
    """Crea dos extremos conectados entre sí."""
    left = LoopbackEndpoint()
    right = LoopbackEndpoint()
    left._connect(right)
    right._connect(left)
    return left, right