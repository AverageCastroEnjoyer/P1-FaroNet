import { jsonResponse, readBodyLimited } from "./index.js";

const MIN_TTL_SECONDS = 60;
const MAX_TTL_SECONDS = 7 * 24 * 60 * 60;
export const FIXED_BLOB_BYTES = 1024;

export async function handleDrops(request, env, url) {
  if (!env.DROPS) {
    return jsonResponse({ error: "drop_storage_unavailable" }, 503);
  }

  if (request.method === "POST" && url.pathname === "/v1/drops") {
    return createDrop(request, env);
  }

  if (url.pathname.startsWith("/v1/drops/")) {
    const token = url.pathname.slice("/v1/drops/".length);
    if (!/^[0-9a-f]{64}$/.test(token)) {
      return jsonResponse({ error: "not_found" }, 404);
    }

    if (request.method === "GET") return consumeDrop(env, token);
    if (request.method === "DELETE") {
      await env.DROPS.delete(`drop:${token}`);
      return jsonResponse({ deleted: true });
    }
  }

  return jsonResponse({ error: "method_not_allowed" }, 405, {
    allow: "GET, POST, DELETE",
  });
}

async function createDrop(request, env) {
  let body;
  try {
    body = await readBodyLimited(request, 4096);
  } catch {
    return jsonResponse({ error: "body_too_large" }, 413);
  }

  let data;
  try {
    data = JSON.parse(new TextDecoder().decode(body));
  } catch {
    return jsonResponse({ error: "invalid_json" }, 400);
  }

  if (
    !data ||
    typeof data.token !== "string" ||
    !/^[0-9a-f]{64}$/.test(data.token) ||
    typeof data.blob !== "string" ||
    !/^[A-Za-z0-9_-]+$/.test(data.blob)
  ) {
    return jsonResponse({ error: "invalid_blob" }, 400);
  }

  const blob = base64UrlDecode(data.blob);
  if (!blob || blob.byteLength !== FIXED_BLOB_BYTES) {
    return jsonResponse({ error: "blob_must_be_1024_bytes" }, 400);
  }

  const ttl = Number(data.ttl_seconds ?? 3600);
  if (
    !Number.isInteger(ttl) ||
    ttl < MIN_TTL_SECONDS ||
    ttl > MAX_TTL_SECONDS
  ) {
    return jsonResponse({ error: "invalid_ttl" }, 400);
  }

  await env.DROPS.put(`drop:${data.token}`, data.blob, {
    expirationTtl: ttl,
  });

  return jsonResponse({ stored: true, expires_in: ttl }, 201);
}

async function consumeDrop(env, token) {
  const key = `drop:${token}`;
  const blob = await env.DROPS.get(key);
  if (blob === null) return jsonResponse({ error: "not_found" }, 404);

  // KV no provee una operación atómica get-and-delete. La lectura puede
  // competir entre ubicaciones; en producción usar Durable Object o D1
  // si se necesita consumo estrictamente de una sola lectura.
  await env.DROPS.delete(key);
  return jsonResponse({ blob }, 200, {
    "cache-control": "no-store",
  });
}

function base64UrlDecode(value) {
  try {
    const base64 = value.replaceAll("-", "+").replaceAll("_", "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    const binary = atob(padded);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  } catch {
    return null;
  }
}
