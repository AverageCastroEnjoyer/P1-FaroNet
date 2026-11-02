"""HTTP bridge local para operaciones públicas y dead drops FaroNet."""

from __future__ import annotations

import asyncio
import base64
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from nacl.signing import SigningKey

from gateway.main import (
    GatewayClient,
    GatewayConfig,
    GatewayRequestError,
    derive_drop_token,
    pack_drop_blob,
    unpack_drop_blob,
)


def _decode_key(value: str) -> bytes:
    try:
        key = bytes.fromhex(value)
    except ValueError as exc:
        raise RuntimeError("FARONET_SIGNING_KEY_HEX debe ser hexadecimal") from exc
    if len(key) != 32:
        raise RuntimeError("FARONET_SIGNING_KEY_HEX debe contener 32 bytes")
    return key


def _decode_secret(value: str) -> bytes:
    try:
        result = base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))
    except Exception as exc:
        raise RuntimeError("FARONET_DROP_SECRET_B64 debe ser base64url") from exc
    if len(result) < 32:
        raise RuntimeError("el secreto del dead drop requiere al menos 32 bytes")
    return result


BASE_URL = os.environ.get("FARONET_EDGE_URL", "")
KEY_ID = os.environ.get("FARONET_KEY_ID", "")
SIGNING_KEY_HEX = os.environ.get("FARONET_SIGNING_KEY_HEX", "")
DROP_SECRET_B64 = os.environ.get("FARONET_DROP_SECRET_B64", "")
if not BASE_URL.startswith("https://") or not KEY_ID or not SIGNING_KEY_HEX or not DROP_SECRET_B64:
    raise RuntimeError("configure FARONET_EDGE_URL, FARONET_KEY_ID, FARONET_SIGNING_KEY_HEX y FARONET_DROP_SECRET_B64")

gateway = GatewayClient(GatewayConfig(BASE_URL, KEY_ID, SigningKey(_decode_key(SIGNING_KEY_HEX))))
drop_secret = _decode_secret(DROP_SECRET_B64)
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class PublicPost(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class DropPut(BaseModel):
    drop_id: str = Field(min_length=22, max_length=88)
    ciphertext: str = Field(min_length=4, max_length=1368)
    ttl_seconds: int = Field(default=3600, ge=60, le=604800)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.post("/public/{topic}")
async def publish(topic: str, request: PublicPost) -> dict:
    try:
        return await gateway.publish_public_message(topic, request.text)
    except (GatewayRequestError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="edge_request_failed") from exc


@app.put("/drops")
async def put_drop(request: DropPut) -> dict:
    try:
        drop_id = base64.urlsafe_b64decode(request.drop_id + "=" * ((4 - len(request.drop_id) % 4) % 4))
        ciphertext = base64.urlsafe_b64decode(request.ciphertext + "=" * ((4 - len(request.ciphertext) % 4) % 4))
        token = derive_drop_token(drop_secret, drop_id)
        blob = pack_drop_blob(ciphertext)
        result = await gateway.create_drop(token, blob, request.ttl_seconds)
        return {**result, "drop_id": request.drop_id}
    except (GatewayRequestError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid_drop") from exc


@app.get("/drops/{drop_id}")
async def get_drop(drop_id: str) -> dict:
    try:
        raw_id = base64.urlsafe_b64decode(drop_id + "=" * ((4 - len(drop_id) % 4) % 4))
        token = derive_drop_token(drop_secret, raw_id)
        result = await gateway.read_drop(token)
        ciphertext = unpack_drop_blob(result["blob"])
        return {"drop_id": drop_id, "ciphertext": base64.urlsafe_b64encode(ciphertext).rstrip(b"=").decode("ascii")}
    except (GatewayRequestError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail="drop_not_found") from exc


@app.on_event("shutdown")
async def shutdown() -> None:
    await gateway.close()


def main() -> None:
    import uvicorn

    # El bridge escucha solo en loopback; nunca se expone a la red mesh.
    uvicorn.run("gateway.service:app", host="127.0.0.1", port=int(os.environ.get("FARONET_GATEWAY_PORT", "8765")), access_log=False)


if __name__ == "__main__":
    main()
