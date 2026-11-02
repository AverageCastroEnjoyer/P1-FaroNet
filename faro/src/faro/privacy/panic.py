"""Coordinación del botón de pánico y borrado de estado sensible."""

from __future__ import annotations

import secrets
from collections.abc import Callable


ADDRESS_SIZE = 8
CleanupCallback = Callable[[], None]
AddressCallback = Callable[[bytes], None]


class PanicError(RuntimeError):
    """Una o más acciones de pánico no pudieron completarse."""


class PanicController:
    """Borra secretos, invalida estado pendiente y rota la dirección.

    Registra claves como bytearray para poder sobrescribirlas. Los callbacks
    permiten conectar la invalidación de rutas, colas, sesiones y hardware.
    """

    def __init__(
        self,
        *,
        set_address: AddressCallback,
        cancel_pending: CleanupCallback,
        clear_sessions: CleanupCallback,
        indicate_panic: CleanupCallback,
    ) -> None:
        self._set_address = set_address
        self._cancel_pending = cancel_pending
        self._clear_sessions = clear_sessions
        self._indicate_panic = indicate_panic
        self._secrets: list[bytearray] = []
        self._triggered = False

    @property
    def triggered(self) -> bool:
        return self._triggered

    def register_secret(self, secret: bytearray) -> None:
        """Registra un buffer mutable que se sobrescribirá al activar pánico."""
        if self._triggered:
            raise RuntimeError("el dispositivo está en estado de pánico")
        if not isinstance(secret, bytearray):
            raise TypeError("los secretos deben registrarse como bytearray")
        self._secrets.append(secret)

    def panic(self) -> bool:
        """Ejecuta una vez el borrado, rotación e indicación de pánico.

        Devuelve True la primera vez y False en llamadas posteriores.
        Intenta completar todas las acciones aunque un callback falle.
        """
        if self._triggered:
            return False

        self._triggered = True
        failures = 0

        for callback in (self._cancel_pending, self._clear_sessions):
            try:
                callback()
            except Exception:
                failures += 1

        for secret in self._secrets:
            secret[:] = b"\x00" * len(secret)
        self._secrets.clear()

        try:
            self._set_address(secrets.token_bytes(ADDRESS_SIZE))
        except Exception:
            failures += 1

        try:
            self._indicate_panic()
        except Exception:
            failures += 1

        if failures:
            raise PanicError(
                f"fallaron {failures} acciones de limpieza o notificación"
            )
        return True