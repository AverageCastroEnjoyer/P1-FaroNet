"""Entradas públicas y firmadas del directorio FaroNet."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from nacl.signing import SigningKey

from faro.privacy.crypto import verify_bytes


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    public_key: bytes
    capabilities: tuple[str, ...]
    expires_at: int
    signature: bytes


def _canonical_payload(
    public_key: bytes,
    capabilities: tuple[str, ...],
    expires_at: int,
) -> bytes:
    document = {
        "capabilities": sorted(capabilities),
        "expires_at": expires_at,
        "public_key": public_key.hex(),
    }
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def create_entry(
    signing_key: SigningKey,
    capabilities: tuple[str, ...],
    expires_at: int,
) -> DirectoryEntry:
    """Crea una entrada cuya firma cubre clave, capacidades y vencimiento."""
    public_key = bytes(signing_key.verify_key)
    normalized = tuple(sorted(set(capabilities)))

    if any(not item or not item.isascii() for item in normalized):
        raise ValueError("las capacidades deben ser cadenas ASCII no vacías")
    if expires_at <= int(time.time()):
        raise ValueError("expires_at debe estar en el futuro")

    payload = _canonical_payload(public_key, normalized, expires_at)
    signature = signing_key.sign(payload).signature

    return DirectoryEntry(
        public_key=public_key,
        capabilities=normalized,
        expires_at=expires_at,
        signature=signature,
    )


def verify_entry(entry: DirectoryEntry, now: int | None = None) -> bool:
    """Comprueba firma y vencimiento. No acepta entradas vencidas."""
    current_time = int(time.time()) if now is None else now

    if len(entry.public_key) != 32 or len(entry.signature) != 64:
        return False
    if entry.expires_at <= current_time:
        return False
    if tuple(sorted(set(entry.capabilities))) != entry.capabilities:
        return False

    payload = _canonical_payload(
        entry.public_key,
        entry.capabilities,
        entry.expires_at,
    )
    return verify_bytes(entry.public_key, payload, entry.signature)