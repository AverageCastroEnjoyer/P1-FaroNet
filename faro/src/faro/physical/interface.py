"""Contrato que deben implementar los backends físicos Faro."""

from __future__ import annotations

from typing import Protocol


class PhysicalBackend(Protocol):
    """Interfaz para loopback o hardware real.

    send_symbols recibe los bytes completos de una trama Faro. El backend
    real debe convertirlos a Manchester y controlar el GPIO.

    receive_symbols devuelve los bytes reconstruidos de una trama completa,
    sin Manchester. Devuelve None si vence el timeout.
    """

    def send_symbols(self, raw_bytes: bytes) -> None:
        ...

    def receive_symbols(self, timeout_seconds: float) -> bytes | None:
        ...

    def carrier_detected(self) -> bool:
        ...