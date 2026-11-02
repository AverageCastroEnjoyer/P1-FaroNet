"""Acceso half-duplex con CCA, backoff y confirmación stop-and-wait."""

from __future__ import annotations

import random
import time
from collections import deque

from faro.link.frame import Frame, FrameType
from faro.link.transceiver import OpticalLink


class MediumAccessError(RuntimeError):
    """No se pudo obtener acceso al medio o entregar la trama."""


class MediumAccess:
    """Coordina el acceso half-duplex sobre un OpticalLink."""

    def __init__(
        self,
        link: OpticalLink,
        local_address: bytes,
        *,
        cca_idle_s: float = 0.005,
        slot_s: float = 0.010,
        ack_timeout_s: float = 1.0,
        max_attempts: int = 5,
    ) -> None:
        if len(local_address) != 8:
            raise ValueError("local_address debe ser de 8 bytes")
        if cca_idle_s <= 0 or slot_s <= 0 or ack_timeout_s <= 0:
            raise ValueError("los tiempos deben ser mayores a cero")
        if max_attempts < 1:
            raise ValueError("max_attempts debe ser al menos 1")

        self._link = link
        self._local_address = local_address
        self._cca_idle_s = cca_idle_s
        self._slot_s = slot_s
        self._ack_timeout_s = ack_timeout_s
        self._max_attempts = max_attempts
        self._pending: deque[Frame] = deque()

    def clear_pending(self) -> None:
        """Borra las tramas recibidas que estaban retenidas en la cola."""
        self._pending.clear()

    def send_reliably(self, frame: Frame) -> None:
        """Envía una trama DATA y espera un ACK con la misma secuencia.

        Lanza MediumAccessError si no recibe confirmación después de
        max_attempts intentos.
        """
        if frame.kind != FrameType.DATA:
            raise ValueError("send_reliably solo acepta tramas DATA")

        for attempt in range(self._max_attempts):
            self._wait_for_idle(attempt)
            self._link.send_frame(frame)

            if self._wait_for_ack(frame):
                return

        raise MediumAccessError(
            f"sin ACK para secuencia {frame.sequence} "
            f"después de {self._max_attempts} intentos"
        )

    def receive(self, timeout_s: float = 1.0) -> Frame | None:
        """Recibe una trama de datos y confirma su recepción con un ACK."""
        if timeout_s < 0:
            raise ValueError("timeout_s no puede ser negativo")

        if self._pending:
            return self._pending.popleft()

        deadline = time.monotonic() + timeout_s

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            frame = self._link.receive_frame(timeout_seconds=remaining)

            if frame is None:
                return None
            if frame.kind == FrameType.ACK:
                continue
            if frame.kind != FrameType.DATA:
                continue

            self._send_ack(frame)
            return frame

        return None

    def _wait_for_idle(self, attempt: int) -> None:
        """Espera CCA libre y aplica backoff exponencial acotado."""
        exponent = min(attempt, 4)
        max_slots = (1 << exponent) - 1
        backoff_slots = random.randint(0, max_slots) if max_slots else 0
        deadline = time.monotonic() + backoff_slots * self._slot_s

        while time.monotonic() < deadline:
            time.sleep(min(self._slot_s, deadline - time.monotonic()))

        while self._link.carrier_detected():
            time.sleep(self._slot_s)

        idle_deadline = time.monotonic() + self._cca_idle_s
        while time.monotonic() < idle_deadline:
            if self._link.carrier_detected():
                return self._wait_for_idle(attempt)
            time.sleep(min(self._slot_s / 2, idle_deadline - time.monotonic()))

    def _wait_for_ack(self, sent: Frame) -> bool:
        deadline = time.monotonic() + self._ack_timeout_s

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            incoming = self._link.receive_frame(timeout_seconds=remaining)

            if incoming is None:
                return False

            if self._is_ack_for(incoming, sent):
                return True

            if incoming.kind == FrameType.DATA:
                self._pending.append(incoming)
                self._send_ack(incoming)

        return False

    def _is_ack_for(self, ack: Frame, sent: Frame) -> bool:
        return (
            ack.kind == FrameType.ACK
            and ack.sequence == sent.sequence
            and ack.source == sent.destination
            and ack.destination == self._local_address
        )

    def _send_ack(self, received: Frame) -> None:
        ack = Frame(
            kind=FrameType.ACK,
            source=self._local_address,
            destination=received.source,
            sequence=received.sequence,
            payload=b"",
        )
        self._link.send_frame(ack)
