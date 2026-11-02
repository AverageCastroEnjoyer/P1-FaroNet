import { jsonResponse } from "./index.js";

const FEED_TTL_SECONDS = 7 * 24 * 60 * 60;
const MAX_FEED_ITEMS = 50;
const MAX_ITEM_TEXT = 2000;

export async function handleFeed(request, env, url) {
  if (request.method === "GET") {
    return readFeed(env, url);
  }

  if (request.method === "POST") {
    return publishFeedItem(request, env, url);
  }

  return jsonResponse({ error: "method_not_allowed" }, 405, {
    allow: "GET, POST",
  });
}

async function readFeed(env, url) {
  if (!env.PUBLIC_FEEDS) {
    return jsonResponse({ error: "feed_storage_unavailable" }, 503);
  }

  const topic = topicFromPath(url.pathname);
  if (!topic) return jsonResponse({ error: "invalid_topic" }, 400);

  const raw = await env.PUBLIC_FEEDS.get(`topic:${topic}`);
  const items = raw ? safeParseItems(raw) : [];

  const xml = renderAtom(topic, items);
  return new Response(xml, {
    status: 200,
    headers: {
      "content-type": "application/atom+xml; charset=utf-8",
      "cache-control": "public, max-age=30",
      "access-control-allow-origin": "*",
    },
  });
}

async function publishFeedItem(request, env, url) {
  if (!env.PUBLIC_FEEDS) {
    return jsonResponse({ error: "feed_storage_unavailable" }, 503);
  }

  const topic = topicFromPath(url.pathname);
  if (!topic) return jsonResponse({ error: "invalid_topic" }, 400);

  let data;
  try {
    data = await request.json();
  } catch {
    return jsonResponse({ error: "invalid_json" }, 400);
  }

  if (
    !data ||
    typeof data.text !== "string" ||
    data.text.length === 0 ||
    data.text.length > MAX_ITEM_TEXT
  ) {
    return jsonResponse({ error: "invalid_item" }, 400);
  }

  const key = `topic:${topic}`;
  const existing = await env.PUBLIC_FEEDS.get(key);
  const items = existing ? safeParseItems(existing) : [];
  items.unshift({
    id: crypto.randomUUID(),
    text: data.text,
    published: new Date().toISOString(),
  });
  const retained = items.slice(0, MAX_FEED_ITEMS);

  await env.PUBLIC_FEEDS.put(key, JSON.stringify(retained), {
    expirationTtl: FEED_TTL_SECONDS,
  });

  return jsonResponse({ accepted: true }, 201);
}

function topicFromPath(pathname) {
  const raw = pathname.slice("/v1/feeds/".length);
  let topic;
  try {
    topic = decodeURIComponent(raw);
  } catch {
    return null;
  }
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(topic)) return null;
  return topic;
}

function safeParseItems(raw) {
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item) =>
        item &&
        typeof item.id === "string" &&
        typeof item.text === "string" &&
        typeof item.published === "string",
    );
  } catch {
    return [];
  }
}

function xmlEscape(value) {
  return value.replace(/[<>&'"]/g, (character) => {
    const replacements = {
      "<": "&lt;",
      ">": "&gt;",
      "&": "&amp;",
      "'": "&apos;",
      '"': "&quot;",
    };
    return replacements[character];
  });
}

function renderAtom(topic, items) {
  const entries = items
    .map(
      (item) => `<entry>
  <id>urn:faronet:${xmlEscape(item.id)}</id>
  <title>${xmlEscape(item.text.slice(0, 120))}</title>
  <content type="text">${xmlEscape(item.text)}</content>
  <updated>${xmlEscape(item.published)}</updated>
</entry>`,
    )
    .join("\n");

  const updated = items[0]?.published || new Date(0).toISOString();
  return `<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>FaroNet: ${xmlEscape(topic)}</title>
  <id>urn:faronet:feed:${xmlEscape(topic)}</id>
  <updated>${xmlEscape(updated)}</updated>
  ${entries}
</feed>`;
}