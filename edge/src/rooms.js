import { DurableObject } from "cloudflare:workers";
import { jsonResponse } from "./index.js";

const MAX_PUBLIC_MESSAGE_BYTES = 4096;
const MAX_ROOM_NAME_LENGTH = 80;

export async function handleRooms(request, env, url) {
  let room;
  try { room = decodeURIComponent(url.pathname.slice("/v1/rooms/".length)); }
  catch { return jsonResponse({ error: "invalid_room" }, 400); }
  if (!room || room.length > MAX_ROOM_NAME_LENGTH || room.includes("/")) {
    return jsonResponse({ error: "invalid_room" }, 400);
  }
  return env.PUBLIC_ROOMS.get(env.PUBLIC_ROOMS.idFromName(room)).fetch(request);
}

export class PublicRoom extends DurableObject {
  constructor(ctx, env) { super(ctx, env); this.ctx = ctx; }

  async fetch(request) {
    if (request.headers.get("upgrade")?.toLowerCase() !== "websocket") {
      return new Response("WebSocket upgrade required", { status: 426 });
    }
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);
    this.ctx.acceptWebSocket(server);
    return new Response(null, { status: 101, webSocket: client });
  }

  async webSocketMessage(sender, message) {
    const bytes = typeof message === "string" ? new TextEncoder().encode(message) : new Uint8Array(message);
    if (bytes.byteLength > MAX_PUBLIC_MESSAGE_BYTES) { sender.close(1009, "message too large"); return; }
    let parsed;
    try { parsed = JSON.parse(new TextDecoder().decode(bytes)); }
    catch { sender.send(JSON.stringify({ error: "invalid_json" })); return; }
    if (!parsed || typeof parsed.text !== "string" || !parsed.text.trim() || new TextEncoder().encode(parsed.text).byteLength > MAX_PUBLIC_MESSAGE_BYTES) {
      sender.send(JSON.stringify({ error: "invalid_message" })); return;
    }
    const event = JSON.stringify({ type: "message", text: parsed.text, created_at: new Date().toISOString() });
    for (const socket of this.ctx.getWebSockets()) {
      try { socket.send(event); } catch { try { socket.close(1011, "delivery failed"); } catch {} }
    }
  }

  async webSocketClose(socket, code, reason) { try { socket.close(code, reason); } catch {} }
  async webSocketError(socket) { try { socket.close(1011, "websocket error"); } catch {} }
}

export class RateLimiter extends DurableObject {
  constructor(ctx, env) { super(ctx, env); this.ctx = ctx; }
  async fetch() {
    const bucket = Math.floor(Date.now() / 60_000);
    return this.ctx.blockConcurrencyWhile(async () => {
      const key = `bucket:${bucket}`;
      const count = (await this.ctx.storage.get(key)) ?? 0;
      if (count >= 120) return new Response(null, { status: 429 });
      await this.ctx.storage.put(key, count + 1);
      return new Response(null, { status: 204 });
    });
  }
}

export class AuthState extends DurableObject {
  constructor(ctx, env) { super(ctx, env); this.ctx = ctx; }
  async fetch(request) {
    if (request.method !== "POST") return new Response(null, { status: 405 });
    let data;
    try { data = await request.json(); } catch { return new Response(null, { status: 400 }); }
    if (!data || typeof data.nonce !== "string" || !/^[A-Za-z0-9_-]{16,128}$/.test(data.nonce)) return new Response(null, { status: 400 });
    return this.ctx.blockConcurrencyWhile(async () => {
      const key = `nonce:${data.nonce}`;
      const now = Math.floor(Date.now() / 1000);
      const expires = await this.ctx.storage.get(key);
      if (expires && expires > now) return new Response(null, { status: 409 });
      await this.ctx.storage.put(key, now + 120);
      await this.ctx.storage.setAlarm(Date.now() + 120_000);
      return new Response(null, { status: 204 });
    });
  }

  async alarm() {
    const now = Math.floor(Date.now() / 1000);
    const entries = await this.ctx.storage.list({ prefix: "nonce:" });
    for (const [key, expires] of entries) {
      if (expires <= now) await this.ctx.storage.delete(key);
    }
    if ((await this.ctx.storage.list({ prefix: "nonce:", limit: 1 })).size > 0) {
      await this.ctx.storage.setAlarm(Date.now() + 120_000);
    }
  }
}
