"""Conecta el framing con un backend físico intercambiable."""

from __future__ import annotations

from faro.link.frame import Frame, decode_frame, encode_frame
from faro.physical.interface import PhysicalBackend


class OpticalLink:
    """Envía y recibe tramas sin depender de una biblioteca GPIO específica."""

    def __init__(self, backend: PhysicalBackend) -> None:
        self._backend = backend

    def send_frame(self, frame: Frame) -> None:
        """Serializa y entrega la trama al backend físico."""
        self._backend.send_symbols(encode_frame(frame))

    def receive_frame(self, timeout_seconds: float = 1.0) -> Frame | None:
        """Recibe una trama; propaga FrameError si falla su validación."""
        raw = self._backend.receive_symbols(timeout_seconds)
        if raw is None:
            return None
        return decode_frame(raw)

    def carrier_detected(self) -> bool:
        return self._backend.carrier_detected()