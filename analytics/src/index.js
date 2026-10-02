const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
const HEARTBEAT_CAP_SECONDS = 30;
const DEFAULT_BONUS_MAX = 9;

function kstDay(timestampMs = Date.now()) {
  return new Date(timestampMs + KST_OFFSET_MS).toISOString().slice(0, 10);
}

function json(data, init = {}) {
  const headers = new Headers(init.headers || {});
  headers.set("content-type", "application/json; charset=utf-8");
  headers.set("cache-control", "no-store");
  return new Response(JSON.stringify(data), { ...init, headers });
}

function publicCorsHeaders() {
  return {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET, OPTIONS",
    "access-control-allow-headers": "content-type",
  };
}

function allowedOrigins(env) {
  return new Set(
    String(env.ALLOWED_ORIGINS || "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean)
  );
}

function corsHeadersForRequest(request, env) {
  const origin = request.headers.get("Origin") || "";
  if (!origin || !allowedOrigins(env).has(origin)) return null;
  return {
    "access-control-allow-origin": origin,
    "access-control-allow-methods": "POST, OPTIONS",
    "access-control-allow-headers": "content-type",
    "access-control-max-age": "86400",
    vary: "Origin",
  };
}

function randomIntInclusive(max) {
  const limit = Math.max(0, Math.min(99, Number(max) || DEFAULT_BONUS_MAX));
  const values = new Uint32Array(1);
  crypto.getRandomValues(values);
  return values[0] % (limit + 1);
}

function normalizeCategory(value) {
  const category = String(value || "기타").trim().replace(/\s+/g, " ");
  if (!category) return "기타";
  return category.slice(0, 64);
}

function normalizeSessionId(value) {
  const sessionId = String(value || "").trim();
  if (!/^[A-Za-z0-9_-]{8,96}$/.test(sessionId)) return "";
  return sessionId;
}

function clientIp(request) {
  const cloudflareIp = request.headers.get("CF-Connecting-IP");
  if (cloudflareIp) return cloudflareIp.trim();
  const forwarded = request.headers.get("X-Forwarded-For");
  if (forwarded) return forwarded.split(",")[0].trim();
  return "local";
}

async function ipKey(ip, salt) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(String(salt || "chip-briefing")),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const signature = new Uint8Array(
    await crypto.subtle.sign("HMAC", key, encoder.encode(ip))
  );
  return Array.from(signature.slice(0, 18), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function ensureVisitor(env, day, key, ip, nowSeconds) {
  let row = await env.DB.prepare(
    "SELECT bonus FROM visitors WHERE day = ? AND ip_key = ?"
  )
    .bind(day, key)
    .first();

  if (!row) {
    const bonus = randomIntInclusive(env.VIEW_BONUS_MAX);
    await env.DB.prepare(
      `INSERT OR IGNORE INTO visitors
       (day, ip_key, ip_address, bonus, first_seen, last_seen)
       VALUES (?, ?, ?, ?, ?, ?)`
    )
      .bind(day, key, ip, bonus, nowSeconds, nowSeconds)
      .run();

    row = await env.DB.prepare(
      "SELECT bonus FROM visitors WHERE day = ? AND ip_key = ?"
    )
      .bind(day, key)
      .first();
  }

  return Number(row?.bonus || 0);
}

async function publicStats(env, day) {
  const row = await env.DB.prepare(
    "SELECT COUNT(*) AS unique_visitors, COALESCE(SUM(10 + bonus), 0) AS views FROM visitors WHERE day = ?"
  )
    .bind(day)
    .first();

  return {
    day,
    views: Number(row?.views || 0),
    unique_visitors: Number(row?.unique_visitors || 0),
  };
}

async function parseEventRequest(request) {
  const body = await request.text();
  if (!body || body.length > 4096) throw new Error("invalid_body");
  let parsed;
  try {
    parsed = JSON.parse(body);
  } catch {
    throw new Error("invalid_json");
  }

  const sessionId = normalizeSessionId(parsed.session_id);
  if (!sessionId) throw new Error("invalid_session");

  const event = String(parsed.event || "heartbeat");
  const validEvents = new Set(["visit", "heartbeat", "switch", "pause", "resume", "pagehide"]);
  if (!validEvents.has(event)) throw new Error("invalid_event");

  return {
    sessionId,
    event,
    category: normalizeCategory(parsed.category),
  };
}

async function recordEvent(request, env) {
  const cors = corsHeadersForRequest(request, env);
  if (!cors) return json({ error: "origin_not_allowed" }, { status: 403 });

  let payload;
  try {
    payload = await parseEventRequest(request);
  } catch (error) {
    return json({ error: error instanceof Error ? error.message : "bad_request" }, { status: 400, headers: cors });
  }

  const nowSeconds = Math.floor(Date.now() / 1000);
  const day = kstDay();
  const ip = clientIp(request);
  const key = await ipKey(ip, env.ANALYTICS_SALT);
  await ensureVisitor(env, day, key, ip, nowSeconds);

  const session = await env.DB.prepare(
    "SELECT category, last_seen, active FROM sessions WHERE day = ? AND ip_key = ? AND session_id = ?"
  )
    .bind(day, key, payload.sessionId)
    .first();

  const statements = [];
  if (session && Number(session.active) === 1) {
    const previousSeen = Number(session.last_seen || nowSeconds);
    const elapsed = Math.max(0, Math.min(HEARTBEAT_CAP_SECONDS, nowSeconds - previousSeen));
    if (elapsed > 0) {
      statements.push(
        env.DB.prepare(
          `INSERT INTO dwell (day, ip_key, category, seconds, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(day, ip_key, category)
           DO UPDATE SET
             seconds = dwell.seconds + excluded.seconds,
             updated_at = excluded.updated_at`
        ).bind(day, key, normalizeCategory(session.category), elapsed, nowSeconds)
      );
    }
  }

  const isActive = payload.event === "pause" || payload.event === "pagehide" ? 0 : 1;
  statements.push(
    env.DB.prepare(
      `INSERT INTO sessions (day, ip_key, session_id, category, last_seen, active)
       VALUES (?, ?, ?, ?, ?, ?)
       ON CONFLICT(day, ip_key, session_id)
       DO UPDATE SET
         category = excluded.category,
         last_seen = excluded.last_seen,
         active = excluded.active`
    ).bind(day, key, payload.sessionId, payload.category, nowSeconds, isActive)
  );
  statements.push(
    env.DB.prepare("UPDATE visitors SET last_seen = ? WHERE day = ? AND ip_key = ?")
      .bind(nowSeconds, day, key)
  );

  await env.DB.batch(statements);
  const stats = await publicStats(env, day);
  return json({ ok: true, day: stats.day, views: stats.views }, { headers: cors });
}

function decodeBase64Url(value) {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (value.length % 4)) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

function decodeJwtJson(value) {
  return JSON.parse(new TextDecoder().decode(decodeBase64Url(value)));
}

function claimIncludesAudience(audience, expected) {
  if (Array.isArray(audience)) return audience.includes(expected);
  return audience === expected;
}

async function verifyGitHubOidc(request) {
  const auth = request.headers.get("Authorization") || "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
  const parts = token.split(".");
  if (parts.length !== 3) return false;

  let header;
  let claims;
  try {
    header = decodeJwtJson(parts[0]);
    claims = decodeJwtJson(parts[1]);
  } catch {
    return false;
  }

  if (header.alg !== "RS256" || !header.kid) return false;

  const now = Math.floor(Date.now() / 1000);
  const expectedWorkflowRef =
    "wlsalswo14/chip-briefing/.github/workflows/daily_analytics.yml@refs/heads/main";
  if (
    claims.iss !== "https://token.actions.githubusercontent.com" ||
    !claimIncludesAudience(claims.aud, "chip-briefing-analytics") ||
    claims.repository !== "wlsalswo14/chip-briefing" ||
    String(claims.repository_id) !== "1292890361" ||
    claims.repository_owner !== "wlsalswo14" ||
    String(claims.repository_owner_id) !== "185170276" ||
    claims.workflow_ref !== expectedWorkflowRef ||
    claims.ref !== "refs/heads/main" ||
    !["schedule", "workflow_dispatch"].includes(claims.event_name) ||
    Number(claims.exp || 0) <= now ||
    Number(claims.nbf || 0) > now + 30
  ) {
    return false;
  }

  let jwks;
  try {
    const response = await fetch("https://token.actions.githubusercontent.com/.well-known/jwks", {
      headers: { accept: "application/json" },
    });
    if (!response.ok) return false;
    jwks = await response.json();
  } catch {
    return false;
  }

  const jwk = Array.isArray(jwks.keys)
    ? jwks.keys.find((candidate) => candidate.kid === header.kid && candidate.kty === "RSA")
    : null;
  if (!jwk) return false;

  try {
    const key = await crypto.subtle.importKey(
      "jwk",
      jwk,
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      false,
      ["verify"]
    );
    const signed = new TextEncoder().encode(`${parts[0]}.${parts[1]}`);
    return crypto.subtle.verify(
      "RSASSA-PKCS1-v1_5",
      key,
      decodeBase64Url(parts[2]),
      signed
    );
  } catch {
    return false;
  }
}

async function detailedReport(env, day) {
  const stats = await publicStats(env, day);
  const visitorsResult = await env.DB.prepare(
    `SELECT ip_key, ip_address, bonus, first_seen, last_seen
     FROM visitors
     WHERE day = ?
     ORDER BY first_seen ASC`
  )
    .bind(day)
    .all();

  const dwellResult = await env.DB.prepare(
    `SELECT ip_key, category, seconds
     FROM dwell
     WHERE day = ?
     ORDER BY ip_key, seconds DESC, category ASC`
  )
    .bind(day)
    .all();

  const dwellByIp = new Map();
  for (const row of dwellResult.results || []) {
    if (!dwellByIp.has(row.ip_key)) dwellByIp.set(row.ip_key, []);
    dwellByIp.get(row.ip_key).push({
      category: String(row.category || "기타"),
      seconds: Number(row.seconds || 0),
    });
  }

  const visitors = (visitorsResult.results || []).map((row) => {
    const categories = dwellByIp.get(row.ip_key) || [];
    return {
      ip: String(row.ip_address || ""),
      bonus: Number(row.bonus || 0),
      weighted_views: 10 + Number(row.bonus || 0),
      first_seen: Number(row.first_seen || 0),
      last_seen: Number(row.last_seen || 0),
      total_seconds: categories.reduce((sum, item) => sum + item.seconds, 0),
      categories,
    };
  });

  return {
    day,
    views: stats.views,
    unique_visitors: stats.unique_visitors,
    visitors,
  };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      if (url.pathname === "/api/stats") {
        return new Response(null, { status: 204, headers: publicCorsHeaders() });
      }
      const cors = corsHeadersForRequest(request, env);
      return cors
        ? new Response(null, { status: 204, headers: cors })
        : new Response(null, { status: 403 });
    }

    if (request.method === "GET" && url.pathname === "/health") {
      return json({ ok: true, service: "chip-briefing-analytics", day: kstDay() });
    }

    if (request.method === "GET" && url.pathname === "/api/stats") {
      const stats = await publicStats(env, kstDay());
      return json({ day: stats.day, views: stats.views }, { headers: publicCorsHeaders() });
    }

    if (request.method === "POST" && url.pathname === "/api/event") {
      return recordEvent(request, env);
    }

    if (request.method === "GET" && url.pathname === "/api/admin/report") {
      if (!(await verifyGitHubOidc(request))) {
        return json({ error: "unauthorized" }, { status: 401 });
      }
      const requestedDay = url.searchParams.get("day") || kstDay();
      if (!/^\d{4}-\d{2}-\d{2}$/.test(requestedDay)) {
        return json({ error: "invalid_day" }, { status: 400 });
      }
      return json(await detailedReport(env, requestedDay));
    }

    return json({ error: "not_found" }, { status: 404 });
  },
};
