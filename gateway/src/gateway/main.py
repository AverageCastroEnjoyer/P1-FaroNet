"""Cliente HTTPS del gateway hacia el Worker FaroNet."""

from __future__ import annotations

import hashlib
import base64
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from nacl.signing import SigningKey


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    base_url: str
    key_id: str
    signing_key: SigningKey
    timeout_seconds: float = 10.0


class GatewayRequestError(RuntimeError):
    """Error de solicitud sin incluir credenciales ni contenido."""


class GatewayClient:
    """Firma solicitudes HTTPS sin registrar datos de identidad o contenido."""

    def __init__(self, config: GatewayConfig) -> None:
        if not config.base_url.startswith("https://"):
            raise ValueError("base_url debe usar HTTPS")
        if not config.key_id or len(config.key_id) > 64:
            raise ValueError("key_id inválido")
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            timeout=config.timeout_seconds,
            follow_redirects=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def publish_public_message(self, topic: str, text: str) -> dict:
        if not text or len(text.encode("utf-8")) > 2000:
            raise ValueError("el mensaje público debe tener entre 1 y 2000 bytes")
        return await self._request("POST", f"/v1/feeds/{quote(topic, safe='')}", {"text": text})

    async def put_directory(self, signed_entries: list[dict]) -> dict:
        return await self._request("PUT", "/v1/nodes", signed_entries)

    async def create_drop(self, token: str, blob_base64url: str, ttl_seconds: int = 3600) -> dict:
        return await self._request("POST", "/v1/drops", {
            "token": token,
            "blob": blob_base64url,
            "ttl_seconds": ttl_seconds,
        })

    async def read_drop(self, token: str) -> dict:
        try:
            response = await self._client.get(f"/v1/drops/{quote(token, safe='')}")
        except httpx.HTTPError as exc:
            raise GatewayRequestError("falló la conexión con el Worker") from exc
        if response.status_code >= 400:
            raise GatewayRequestError(f"Worker respondió HTTP {response.status_code}")
        try:
            result = response.json()
        except ValueError as exc:
            raise GatewayRequestError("respuesta JSON inválida del Worker") from exc
        if not isinstance(result, dict):
            raise GatewayRequestError("respuesta del Worker no es un objeto JSON")
        return result

    async def delete_drop(self, token: str) -> dict:
        return await self._request("DELETE", f"/v1/drops/{quote(token, safe='')}", None)

    async def _request(self, method: str, path: str, data: object | None) -> dict:
        body = b"" if data is None else json.dumps(
            data, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        timestamp = str(int(time.time()))
        nonce = secrets.token_urlsafe(24)
        digest = hashlib.sha256(body).hexdigest()
        signed_text = "\n".join((timestamp, nonce, method, path, digest)).encode("utf-8")
        signature = self._config.signing_key.sign(signed_text).signature.hex()
        headers = {
            "content-type": "application/json",
            "x-faro-key-id": self._config.key_id,
            "x-faro-timestamp": timestamp,
            "x-faro-nonce": nonce,
            "x-faro-signature": signature,
        }
        try:
            response = await self._client.request(method, path, content=body, headers=headers)
        except httpx.HTTPError as exc:
            raise GatewayRequestError("falló la conexión con el Worker") from exc
        if response.status_code >= 400:
            raise GatewayRequestError(f"Worker respondió HTTP {response.status_code}")
        try:
            result = response.json()
        except ValueError as exc:
            raise GatewayRequestError("respuesta JSON inválida del Worker") from exc
        if not isinstance(result, dict):
            raise GatewayRequestError("respuesta del Worker no es un objeto JSON")
        return result


DROP_BLOB_SIZE = 1024


def derive_drop_token(shared_secret: bytes, drop_id: bytes) -> str:
    """Deriva el token opaco HMAC-SHA256 compartido por emisor y receptor."""
    if len(shared_secret) < 32 or not 16 <= len(drop_id) <= 64:
        raise ValueError("secreto o identificador del dead drop inválido")
    return hmac.new(shared_secret, b"FaroNet/dead-drop/v1\0" + drop_id, hashlib.sha256).hexdigest()


def pack_drop_blob(ciphertext: bytes) -> str:
    """Añade longitud y padding aleatorio para obtener un blob de 1024 bytes."""
    if not ciphertext or len(ciphertext) > DROP_BLOB_SIZE - 2:
        raise ValueError("ciphertext del dead drop fuera de tamaño")
    packed = len(ciphertext).to_bytes(2, "big") + ciphertext
    packed += secrets.token_bytes(DROP_BLOB_SIZE - len(packed))
    return base64.urlsafe_b64encode(packed).rstrip(b"=").decode("ascii")


def unpack_drop_blob(encoded: str) -> bytes:
    padded = encoded + "=" * ((4 - len(encoded) % 4) % 4)
    try:
        packed = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ValueError("dead drop inválido") from exc
    if len(packed) != DROP_BLOB_SIZE:
        raise ValueError("el dead drop no tiene tamaño fijo")
    size = int.from_bytes(packed[:2], "big")
    if not 1 <= size <= DROP_BLOB_SIZE - 2:
        raise ValueError("longitud interna inválida")
    return packed[2:2 + size]
