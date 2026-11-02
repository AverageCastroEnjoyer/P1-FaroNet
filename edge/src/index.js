import { handleDirectory } from "./directory.js";
import { handleDrops } from "./drops.js";
import { handleFeed } from "./feeds.js";
import { handleRooms, RateLimiter } from "./rooms.js";

const MAX_BODY_BYTES = 64 * 1024;
const RATE_WINDOW_SECONDS = 60;

export { PublicRoom, RateLimiter, AuthState } from "./rooms.js";

export default {
  async fetch(request, env) {
    try {
      const url = new URL(request.url);
      if (request.method === "OPTIONS") {
        return new Response(null, { status: 204, headers: corsHeaders() });
      }
      if (request.method === "GET" && url.pathname === "/") {
        return new Response(roomBrowserPage(), { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
      }
      if (!(await withinRateLimit(env))) return json({ error: "rate_limited" }, 429);

      if (url.pathname.startsWith("/v1/rooms/")) return handleRooms(request, env, url);
      if (url.pathname.startsWith("/v1/feeds/")) {
        if (request.method === "POST" && !(await authenticateGateway(request, env))) {
          return json({ error: "unauthorized" }, 401);
        }
        return handleFeed(request, env, url);
      }
      if (url.pathname === "/v1/drops" || url.pathname.startsWith("/v1/drops/")) {
        if (request.method !== "GET" && !(await authenticateGateway(request, env))) {
          return json({ error: "unauthorized" }, 401);
        }
        return handleDrops(request, env, url);
      }
      if (url.pathname === "/v1/nodes") {
        if (request.method === "PUT" && !(await authenticateGateway(request, env))) {
          return json({ error: "unauthorized" }, 401);
        }
        return handleDirectory(request, env);
      }
      return json({ error: "not_found" }, 404);
    } catch {
      // No se devuelven mensajes de excepciones, que podrían incluir datos de
      // solicitudes o infraestructura.
      return json({ error: "internal_error" }, 500);
    }
  },
};

function roomBrowserPage() {
  return `<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FaroNet | Salas públicas</title>
<style>body{font:16px system-ui;max-width:760px;margin:3rem auto;padding:0 1rem;background:#101820;color:#eef}input,button{font:inherit;padding:.6rem;border-radius:.4rem;border:1px solid #657}input{background:#182832;color:white}button{cursor:pointer}#messages{height:50vh;overflow:auto;border:1px solid #657;padding:1rem;list-style:none}li{padding:.4rem 0;border-bottom:1px solid #344}</style>
<h1>FaroNet · Sala pública</h1><p>Los mensajes enviados aquí son públicos.</p><form id="join"><label>Tema <input id="topic" value="general" maxlength="64" pattern="[A-Za-z0-9_-]+" required></label> <button>Conectar</button></form><p id="status">Desconectado</p><ul id="messages"></ul><form id="send"><input id="text" maxlength="4000" placeholder="Mensaje público" required><button>Enviar</button></form>
<script>let ws;const status=document.querySelector('#status'),list=document.querySelector('#messages');document.querySelector('#join').onsubmit=e=>{e.preventDefault();if(ws)ws.close();const topic=document.querySelector('#topic').value;const scheme=location.protocol==='https:'?'wss':'ws';ws=new WebSocket(scheme+'://'+location.host+'/v1/rooms/'+encodeURIComponent(topic));ws.onopen=()=>status.textContent='Conectado a #'+topic;ws.onclose=()=>status.textContent='Desconectado';ws.onerror=()=>status.textContent='Error de conexión';ws.onmessage=event=>{let item;try{item=JSON.parse(event.data)}catch{return}if(item.type!=='message')return;const li=document.createElement('li');li.textContent='['+item.created_at+'] '+item.text;list.append(li);list.scrollTop=list.scrollHeight}};document.querySelector('#send').onsubmit=e=>{e.preventDefault();const input=document.querySelector('#text');if(ws?.readyState===WebSocket.OPEN){ws.send(JSON.stringify({text:input.value}));input.value=''}};</script></html>`;
}

function corsHeaders() {
  return {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET,POST,PUT,DELETE,OPTIONS",
    "access-control-allow-headers": "content-type,x-faro-key-id,x-faro-timestamp,x-faro-nonce,x-faro-signature",
  };
}

function json(data, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...corsHeaders(),
      ...headers,
    },
  });
}

export function jsonResponse(data, status = 200, headers = {}) {
  return json(data, status, headers);
}

export async function readBodyLimited(request, maxBytes = MAX_BODY_BYTES) {
  const declaredLength = Number(request.headers.get("content-length") || 0);
  if (declaredLength > maxBytes) throw new RangeError("body_too_large");
  const body = await request.arrayBuffer();
  if (body.byteLength > maxBytes) throw new RangeError("body_too_large");
  return new Uint8Array(body);
}

async function withinRateLimit(env) {
  if (!env.RATE_LIMITS) return true;
  const bucket = Math.floor(Date.now() / (RATE_WINDOW_SECONDS * 1000));
  const stub = env.RATE_LIMITS.get(env.RATE_LIMITS.idFromName(`global:${bucket}`));
  return (await stub.fetch("https://rate-limit/check", { method: "POST" })).ok;
}

async function authenticateGateway(request, env) {
  if (!env.GATEWAY_KEYS || !env.AUTH_STATE) return false;
  const keyId = request.headers.get("x-faro-key-id");
  const timestampText = request.headers.get("x-faro-timestamp");
  const nonce = request.headers.get("x-faro-nonce");
  const signatureHex = request.headers.get("x-faro-signature");
  if (!keyId || !/^[A-Za-z0-9_-]{1,64}$/.test(keyId)) return false;
  if (!timestampText || !/^[0-9]{10}$/.test(timestampText)) return false;
  if (!nonce || !/^[A-Za-z0-9_-]{16,128}$/.test(nonce)) return false;
  if (!signatureHex || !/^[0-9a-fA-F]{128}$/.test(signatureHex)) return false;
  if (Math.abs(Math.floor(Date.now() / 1000) - Number(timestampText)) > 60) return false;

  const publicKeyHex = await env.GATEWAY_KEYS.get(keyId);
  if (!publicKeyHex || !/^[0-9a-fA-F]{64}$/.test(publicKeyHex)) return false;
  const body = await request.clone().arrayBuffer();
  if (body.byteLength > MAX_BODY_BYTES) return false;
  const digest = await crypto.subtle.digest("SHA-256", body);
  const digestHex = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  const url = new URL(request.url);
  const signedText = [timestampText, nonce, request.method.toUpperCase(), url.pathname + url.search, digestHex].join("\n");

  let valid = false;
  try {
    const publicKey = await crypto.subtle.importKey("raw", hexToBytes(publicKeyHex), { name: "Ed25519" }, false, ["verify"]);
    valid = await crypto.subtle.verify("Ed25519", publicKey, hexToBytes(signatureHex), new TextEncoder().encode(signedText));
  } catch {
    return false;
  }
  if (!valid) return false;

  const state = env.AUTH_STATE.get(env.AUTH_STATE.idFromName(keyId));
  const response = await state.fetch("https://auth/claim", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ nonce }),
  });
  return response.status === 204;
}

function hexToBytes(hex) {
  const result = new Uint8Array(hex.length / 2);
  for (let i = 0; i < result.length; i += 1) result[i] = Number.parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return result;
}
