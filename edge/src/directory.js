import { jsonResponse, readBodyLimited } from "./index.js";

const MAX_DIRECTORY_BYTES = 256 * 1024;
const DIRECTORY_TTL_SECONDS = 24 * 60 * 60;

export async function handleDirectory(request, env) {
  if (!env.DIRECTORY) return jsonResponse({ error: "directory_unavailable" }, 503);
  if (request.method === "GET") {
    const raw = await env.DIRECTORY.get("signed_entries");
    return new Response(raw || "[]", { headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "public, max-age=30",
      "access-control-allow-origin": "*",
    } });
  }
  if (request.method !== "PUT") return jsonResponse({ error: "method_not_allowed" }, 405, { allow: "GET, PUT" });

  let raw;
  try { raw = new TextDecoder().decode(await readBodyLimited(request, MAX_DIRECTORY_BYTES)); }
  catch { return jsonResponse({ error: "invalid_directory_body" }, 413); }
  let entries;
  try { entries = JSON.parse(raw); }
  catch { return jsonResponse({ error: "invalid_json" }, 400); }
  if (!Array.isArray(entries) || entries.length > 1000 || !entries.every(isSignedEntry)) {
    return jsonResponse({ error: "invalid_directory" }, 400);
  }
  await env.DIRECTORY.put("signed_entries", JSON.stringify(entries), { expirationTtl: DIRECTORY_TTL_SECONDS });
  return jsonResponse({ stored: entries.length });
}

function isSignedEntry(entry) {
  return !!entry && typeof entry === "object" &&
    typeof entry.public_key === "string" && /^[0-9a-fA-F]{64}$/.test(entry.public_key) &&
    Array.isArray(entry.capabilities) && entry.capabilities.length <= 32 &&
    entry.capabilities.every((value) => typeof value === "string" && value.length > 0 && value.length <= 64 && /^[\x20-\x7E]+$/.test(value)) &&
    Number.isInteger(entry.expires_at) && entry.expires_at > Math.floor(Date.now() / 1000) &&
    typeof entry.signature === "string" && /^[0-9a-fA-F]{128}$/.test(entry.signature);
}
