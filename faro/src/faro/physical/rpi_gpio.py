"""Backend GPIO Raspberry Pi para el circuito Faro v1.

GPIO17: TX LED driver; GPIO27: RX desde comparador; GPIO22: botón a GND;
GPIO23/24/25: indicadores TX/RX/estado. El envío Manchester temporizado desde
Linux es experimental y debe calibrarse a baja velocidad en el circuito real.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from gpiozero import Button, DigitalInputDevice, DigitalOutputDevice, LED

from faro.link.frame import MAX_FRAME_SIZE, PREAMBLE, START_DELIMITER
from faro.physical.manchester import ManchesterDecodeError, decode_manchester, encode_manchester


class RaspberryPiGPIOBackend:
    """Implementa PhysicalBackend sobre los pines del netlist Faro v1."""

    def __init__(
        self,
        *,
        symbol_rate: float = 50.0,
        tx_pin: int = 17,
        rx_pin: int = 27,
        panic_pin: int = 22,
        tx_indicator_pin: int = 23,
        rx_indicator_pin: int = 24,
        status_indicator_pin: int = 25,
        on_panic: Callable[[], None] | None = None,
    ) -> None:
        if not 1.0 <= symbol_rate <= 1000.0:
            raise ValueError("symbol_rate debe estar entre 1 y 1000 símbolos/s")
        self._half_period = 1.0 / (2.0 * symbol_rate)
        self._tx = DigitalOutputDevice(tx_pin, initial_value=False)
        self._rx = DigitalInputDevice(rx_pin, pull_up=None, bounce_time=None)
        self._tx_led = LED(tx_indicator_pin)
        self._rx_led = LED(rx_indicator_pin)
        self._status_led = LED(status_indicator_pin)
        self._panic_button = Button(panic_pin, pull_up=True, bounce_time=0.1)
        self._panic_callback = on_panic
        self._panic_button.when_pressed = self._panic_pressed
        self._rx_event = threading.Event()
        self._tx_lock = threading.Lock()
        self._last_edge = 0.0
        self._closed = False
        self._rx.when_activated = self._edge
        self._rx.when_deactivated = self._edge

    def _panic_pressed(self) -> None:
        self._status_led.on()
        if self._panic_callback is not None:
            self._panic_callback()

    def _edge(self) -> None:
        self._last_edge = time.monotonic()
        self._rx_event.set()

    def send_symbols(self, raw_bytes: bytes) -> None:
        if self._closed:
            raise RuntimeError("el backend GPIO está cerrado")
        if not isinstance(raw_bytes, bytes) or not 1 <= len(raw_bytes) <= MAX_FRAME_SIZE:
            raise ValueError(f"raw_bytes debe contener de 1 a {MAX_FRAME_SIZE} bytes")
        symbols = encode_manchester(raw_bytes)
        with self._tx_lock:
            self._tx_led.on()
            try:
                for symbol in symbols:
                    self._tx.value = bool(symbol)
                    time.sleep(self._half_period)
            finally:
                self._tx.off()
                self._tx_led.off()

    def receive_symbols(self, timeout_seconds: float = 1.0) -> bytes | None:
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds no puede ser negativo")
        deadline = time.monotonic() + timeout_seconds
        samples: list[int] = []
        max_samples = (MAX_FRAME_SIZE + 8) * 16

        while time.monotonic() < deadline and not self._closed:
            remaining = deadline - time.monotonic()
            self._rx_event.clear()
            if not self._rx_event.wait(remaining):
                return None

            # El flanco coincide aproximadamente con el límite del semiperíodo;
            # tomar la muestra a un cuarto de período reduce el sesgo de latencia.
            time.sleep(self._half_period / 2)
            while time.monotonic() < deadline and len(samples) < max_samples:
                samples.append(1 if self._rx.is_active else 0)
                packet = self._find_frame(samples)
                if packet is not None:
                    self._rx_led.on()
                    self._rx_led.off()
                    return packet
                time.sleep(self._half_period)

            samples.clear()
        return None

    def _find_frame(self, samples: list[int]) -> bytes | None:
        for phase in range(min(16, len(samples))):
            aligned = samples[phase : len(samples) - ((len(samples) - phase) % 16)]
            if len(aligned) < 26 * 16:
                continue
            try:
                decoded = decode_manchester(aligned)
            except ManchesterDecodeError:
                continue

            marker = PREAMBLE + bytes((START_DELIMITER,))
            offset = decoded.find(marker)
            if offset < 0 or len(decoded) < offset + 24:
                continue
            payload_length = decoded[offset + 23]
            frame_length = 26 + payload_length
            if frame_length > MAX_FRAME_SIZE or len(decoded) < offset + frame_length:
                continue
            return decoded[offset : offset + frame_length]
        return None

    def carrier_detected(self) -> bool:
        return time.monotonic() - self._last_edge < self._half_period * 2

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._rx_event.set()
        self._tx.off()
        self._tx.close()
        self._rx.close()
        self._tx_led.close()
        self._rx_led.close()
        self._status_led.close()
        self._panic_button.close()
