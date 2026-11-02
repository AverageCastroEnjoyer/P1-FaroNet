"""Operaciones criptográficas mediante libsodium/PyNaCl."""

from __future__ import annotations

from nacl import exceptions
from nacl.bindings import (
    crypto_aead_xchacha20poly1305_ietf_decrypt,
    crypto_aead_xchacha20poly1305_ietf_encrypt,
)
from nacl.public import PrivateKey, PublicKey, SealedBox
from nacl.signing import SigningKey, VerifyKey
from nacl.utils import random


KEY_SIZE = 32
NONCE_SIZE = 24


class CryptoError(ValueError):
    """El ciphertext, la clave o la firma no son válidos."""


def encrypt_message(key: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    """Devuelve nonce || ciphertext autenticado."""
    if len(key) != KEY_SIZE:
        raise ValueError(f"la clave debe tener {KEY_SIZE} bytes")

    nonce = random(NONCE_SIZE)
    ciphertext = crypto_aead_xchacha20poly1305_ietf_encrypt(
        plaintext, aad, nonce, key
    )
    return nonce + ciphertext


def decrypt_message(key: bytes, sealed: bytes, aad: bytes = b"") -> bytes:
    """Descifra y autentica un mensaje producido por encrypt_message."""
    if len(key) != KEY_SIZE:
        raise ValueError(f"la clave debe tener {KEY_SIZE} bytes")
    if len(sealed) < NONCE_SIZE:
        raise CryptoError("ciphertext demasiado corto")

    nonce = sealed[:NONCE_SIZE]
    ciphertext = sealed[NONCE_SIZE:]

    try:
        return crypto_aead_xchacha20poly1305_ietf_decrypt(
            ciphertext, aad, nonce, key
        )
    except exceptions.CryptoError as exc:
        raise CryptoError("falló la autenticación del mensaje") from exc


def seal_for_node(curve25519_public_key: bytes, plaintext: bytes) -> bytes:
    """Cifra para una clave pública Curve25519, útil para una capa onion."""
    if len(curve25519_public_key) != KEY_SIZE:
        raise ValueError(f"la clave pública debe tener {KEY_SIZE} bytes")
    return SealedBox(PublicKey(curve25519_public_key)).encrypt(plaintext)


def open_for_node(curve25519_private_key: bytes, ciphertext: bytes) -> bytes:
    """Abre una capa SealedBox usando una clave privada Curve25519."""
    if len(curve25519_private_key) != KEY_SIZE:
        raise ValueError(f"la clave privada debe tener {KEY_SIZE} bytes")

    try:
        private_key = PrivateKey(curve25519_private_key)
        return SealedBox(private_key).decrypt(ciphertext)
    except (exceptions.CryptoError, ValueError) as exc:
        raise CryptoError("no se pudo abrir la capa onion") from exc


def sign_bytes(signing_key: SigningKey, message: bytes) -> bytes:
    """Firma bytes con Ed25519; devuelve solo la firma."""
    return signing_key.sign(message).signature


def verify_bytes(
    verify_key: bytes,
    message: bytes,
    signature: bytes,
) -> bool:
    """Verifica una firma Ed25519 sin propagar errores de entrada."""
    try:
        VerifyKey(verify_key).verify(message, signature)
        return True
    except (exceptions.BadSignatureError, ValueError):
        return False