import { handleAiChatCompletions } from "./ai-gateway.js";

const PRODUCT = "dentalpin";
const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

class HttpError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function nowIso() {
  return new Date().toISOString();
}

function normalizeLicenseKey(value) {
  return String(value || "").trim().toUpperCase().replace(/\s+/g, "");
}

function parseFeatures(raw) {
  if (!raw) return [];
  try {
    const value = JSON.parse(raw);
    return Array.isArray(value) ? value.map(String) : [];
  } catch {
    return [];
  }
}

function requiredString(value, name, min = 1, max = 200) {
  if (typeof value !== "string") throw new HttpError(422, `${name} must be a string`);
  const result = value.trim();
  if (result.length < min || result.length > max) {
    throw new HttpError(422, `${name} must be between ${min} and ${max} characters`);
  }
  return result;
}

function optionalPositiveInt(value, name, min, max, fallback = null) {
  if (value === undefined || value === null) return fallback;
  if (!Number.isInteger(value) || value < min || value > max) {
    throw new HttpError(422, `${name} must be an integer between ${min} and ${max}`);
  }
  return value;
}

async function readJson(request) {
  try {
    return await request.json();
  } catch {
    throw new HttpError(400, "Invalid JSON body");
  }
}

async function sha256Bytes(text) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)));
}

async function sha256Hex(text) {
  const bytes = await sha256Bytes(text);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

async function constantTimeEqual(a, b) {
  const left = await sha256Bytes(String(a || ""));
  const right = await sha256Bytes(String(b || ""));
  let diff = 0;
  for (let i = 0; i < left.length; i += 1) diff |= left[i] ^ right[i];
  return diff === 0;
}

function bytesToBase64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlToBytes(value) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function base64ToBytes(value) {
  const binary = atob(value.replace(/\s+/g, ""));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function pemBodyFromBase64Pem(encodedPem) {
  const pem = atob(String(encodedPem || "").trim());
  const body = pem
    .replace(/-----BEGIN [^-]+-----/g, "")
    .replace(/-----END [^-]+-----/g, "")
    .replace(/\s+/g, "");
  if (!body) throw new HttpError(500, "License signing key configuration is invalid");
  return { pem, der: base64ToBytes(body) };
}

async function importPrivateKey(env) {
  const { der } = pemBodyFromBase64Pem(env.LICENSE_SIGNING_PRIVATE_KEY_B64);
  return crypto.subtle.importKey("pkcs8", der, { name: "Ed25519" }, false, ["sign"]);
}

async function importPublicKey(env) {
  const { der } = pemBodyFromBase64Pem(env.LICENSE_PUBLIC_KEY_B64);
  return crypto.subtle.importKey("spki", der, { name: "Ed25519" }, false, ["verify"]);
}

async function signPayload(payload, env) {
  const raw = new TextEncoder().encode(JSON.stringify(payload));
  const key = await importPrivateKey(env);
  const signature = new Uint8Array(await crypto.subtle.sign("Ed25519", key, raw));
  return `${bytesToBase64Url(raw)}.${bytesToBase64Url(signature)}`;
}

async function verifyToken(token, env) {
  const parts = String(token || "").split(".");
  if (parts.length !== 2) throw new HttpError(401, "Invalid license lease");
  let raw;
  let signature;
  try {
    raw = base64UrlToBytes(parts[0]);
    signature = base64UrlToBytes(parts[1]);
  } catch {
    throw new HttpError(401, "Invalid license lease");
  }
  const key = await importPublicKey(env);
  const valid = await crypto.subtle.verify("Ed25519", key, signature, raw);
  if (!valid) throw new HttpError(401, "Invalid license lease");
  let payload;
  try {
    payload = JSON.parse(new TextDecoder().decode(raw));
  } catch {
    throw new HttpError(401, "Invalid license lease");
  }
  if (payload.product !== PRODUCT || payload.v !== 1) {
    throw new HttpError(401, "Invalid license lease");
  }
  return payload;
}

function generateLicenseKey() {
  const groups = [];
  for (let g = 0; g < 5; g += 1) {
    const random = new Uint8Array(5);
    crypto.getRandomValues(random);
    groups.push(Array.from(random, (b) => ALPHABET[b % ALPHABET.length]).join(""));
  }
  return `DP-${groups.join("-")}`;
}

function ensureLicenseUsable(license) {
  if (!license) throw new HttpError(404, "License key not found");
  if (license.status !== "active") throw new HttpError(403, `License is ${license.status}`);
  if (license.expires_at && new Date(license.expires_at).getTime() <= Date.now()) {
    throw new HttpError(403, "License has expired");
  }
}

function leasePolicy(env) {
  const refreshHours = Math.max(1, Number.parseInt(env.LICENSE_REFRESH_HOURS || "1", 10) || 1);
  const graceDays = Math.max(1, Number.parseInt(env.LICENSE_OFFLINE_GRACE_DAYS || "7", 10) || 7);
  return { refreshHours, graceDays };
}

async function issueLease(license, activation, env) {
  const { refreshHours, graceDays } = leasePolicy(env);
  const now = new Date();
  let validUntil = new Date(now.getTime() + graceDays * 86400000);
  if (license.expires_at) {
    const licenseExpiry = new Date(license.expires_at);
    if (licenseExpiry < validUntil) validUntil = licenseExpiry;
  }
  let refreshAfter = new Date(now.getTime() + refreshHours * 3600000);
  if (refreshAfter > validUntil) refreshAfter = validUntil;
  const payload = {
    v: 1,
    product: PRODUCT,
    license_id: license.id,
    activation_id: activation.id,
    installation_id: activation.installation_id,
    fingerprint: activation.fingerprint,
    customer_name: license.customer_name,
    plan: license.plan,
    features: parseFeatures(license.features_json),
    issued_at: now.toISOString(),
    refresh_after: refreshAfter.toISOString(),
    valid_until: validUntil.toISOString(),
    license_expires_at: license.expires_at || null,
  };
  return {
    lease_token: await signPayload(payload, env),
    customer_name: license.customer_name,
    plan: license.plan,
    features: payload.features,
    refresh_after: payload.refresh_after,
    valid_until: payload.valid_until,
    license_expires_at: payload.license_expires_at,
  };
}

async function requireAdmin(request, env) {
  const provided = request.headers.get("x-admin-key") || "";
  if (!provided || !(await constantTimeEqual(provided, env.LICENSE_ADMIN_API_KEY || ""))) {
    throw new HttpError(401, "Invalid admin key");
  }
}

async function getLicenseByHash(env, keyHash) {
  return env.DB.prepare("SELECT * FROM licenses WHERE key_hash = ? LIMIT 1").bind(keyHash).first();
}

async function handleActivate(request, env) {
  const body = await readJson(request);
  const licenseKey = requiredString(body.license_key, "license_key", 8, 100);
  const installationId = requiredString(body.installation_id, "installation_id", 8, 64);
  const fingerprint = requiredString(body.fingerprint, "fingerprint", 16, 128);
  const keyHash = await sha256Hex(normalizeLicenseKey(licenseKey));
  const license = await getLicenseByHash(env, keyHash);
  ensureLicenseUsable(license);

  let activation = await env.DB.prepare(
    "SELECT * FROM activations WHERE license_id = ? AND installation_id = ? LIMIT 1"
  ).bind(license.id, installationId).first();

  const now = nowIso();
  if (activation) {
    if (activation.revoked_at) throw new HttpError(403, "Activation has been revoked");
    if (activation.fingerprint !== fingerprint) {
      throw new HttpError(409, "Installation fingerprint mismatch");
    }
    await env.DB.prepare("UPDATE activations SET last_seen_at = ? WHERE id = ?")
      .bind(now, activation.id)
      .run();
    activation = { ...activation, last_seen_at: now };
  } else {
    const activationId = crypto.randomUUID();
    const result = await env.DB.prepare(`
      INSERT INTO activations (
        id, license_id, installation_id, fingerprint, first_seen_at, last_seen_at, revoked_at
      )
      SELECT ?, ?, ?, ?, ?, ?, NULL
      WHERE (
        SELECT COUNT(*) FROM activations WHERE license_id = ? AND revoked_at IS NULL
      ) < (
        SELECT max_activations FROM licenses WHERE id = ?
      )
    `).bind(
      activationId,
      license.id,
      installationId,
      fingerprint,
      now,
      now,
      license.id,
      license.id,
    ).run();

    if ((result.meta?.changes || 0) < 1) {
      throw new HttpError(409, "License activation limit reached");
    }
    activation = {
      id: activationId,
      license_id: license.id,
      installation_id: installationId,
      fingerprint,
      first_seen_at: now,
      last_seen_at: now,
      revoked_at: null,
    };
  }

  return jsonResponse(await issueLease(license, activation, env));
}

async function handleRefresh(request, env) {
  const body = await readJson(request);
  const leaseToken = requiredString(body.lease_token, "lease_token", 20, 20000);
  const installationId = requiredString(body.installation_id, "installation_id", 8, 64);
  const fingerprint = requiredString(body.fingerprint, "fingerprint", 16, 128);
  const payload = await verifyToken(leaseToken, env);

  if (payload.installation_id !== installationId) throw new HttpError(401, "Installation mismatch");
  if (payload.fingerprint !== fingerprint) throw new HttpError(401, "Fingerprint mismatch");

  const row = await env.DB.prepare(`
    SELECT
      a.id AS activation_id,
      a.license_id,
      a.installation_id,
      a.fingerprint,
      a.first_seen_at,
      a.last_seen_at,
      a.revoked_at,
      l.id,
      l.key_hash,
      l.key_prefix,
      l.customer_name,
      l.plan,
      l.status,
      l.expires_at,
      l.max_activations,
      l.features_json,
      l.created_at,
      l.updated_at
    FROM activations a
    JOIN licenses l ON l.id = a.license_id
    WHERE a.id = ? AND l.id = ?
    LIMIT 1
  `).bind(payload.activation_id, payload.license_id).first();

  if (!row) throw new HttpError(404, "Activation not found");
  if (row.revoked_at) throw new HttpError(403, "Activation has been revoked");
  if (row.installation_id !== installationId || row.fingerprint !== fingerprint) {
    throw new HttpError(401, "Installation mismatch");
  }

  const license = {
    id: row.id,
    key_hash: row.key_hash,
    key_prefix: row.key_prefix,
    customer_name: row.customer_name,
    plan: row.plan,
    status: row.status,
    expires_at: row.expires_at,
    max_activations: row.max_activations,
    features_json: row.features_json,
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
  ensureLicenseUsable(license);

  const now = nowIso();
  await env.DB.prepare("UPDATE activations SET last_seen_at = ? WHERE id = ?")
    .bind(now, row.activation_id)
    .run();

  const activation = {
    id: row.activation_id,
    license_id: row.license_id,
    installation_id: row.installation_id,
    fingerprint: row.fingerprint,
    first_seen_at: row.first_seen_at,
    last_seen_at: now,
    revoked_at: row.revoked_at,
  };
  return jsonResponse(await issueLease(license, activation, env));
}

async function handleCreateLicense(request, env) {
  await requireAdmin(request, env);
  const body = await readJson(request);
  const customerName = requiredString(body.customer_name, "customer_name", 1, 200);
  const plan = body.plan === undefined ? "standard" : requiredString(body.plan, "plan", 1, 50);
  const durationDays = optionalPositiveInt(body.duration_days, "duration_days", 1, 3650, null);
  const maxActivations = optionalPositiveInt(body.max_activations, "max_activations", 1, 100, 1);
  const features = body.features === undefined ? [] : body.features;
  if (!Array.isArray(features) || features.some((item) => typeof item !== "string" || item.length > 100)) {
    throw new HttpError(422, "features must be an array of short strings");
  }

  let licenseKey;
  let keyHash;
  for (let attempt = 0; attempt < 10; attempt += 1) {
    licenseKey = generateLicenseKey();
    keyHash = await sha256Hex(normalizeLicenseKey(licenseKey));
    const duplicate = await env.DB.prepare("SELECT 1 FROM licenses WHERE key_hash = ? LIMIT 1")
      .bind(keyHash)
      .first();
    if (!duplicate) break;
    licenseKey = null;
  }
  if (!licenseKey || !keyHash) throw new HttpError(500, "Could not generate unique license key");

  const id = crypto.randomUUID();
  const createdAt = nowIso();
  const expiresAt = durationDays
    ? new Date(Date.now() + durationDays * 86400000).toISOString()
    : null;

  await env.DB.prepare(`
    INSERT INTO licenses (
      id, key_hash, key_prefix, customer_name, plan, status, expires_at,
      max_activations, features_json, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
  `).bind(
    id,
    keyHash,
    licenseKey.slice(0, 11),
    customerName,
    plan,
    expiresAt,
    maxActivations,
    JSON.stringify(features),
    createdAt,
    createdAt,
  ).run();

  return jsonResponse({
    id,
    customer_name: customerName,
    plan,
    status: "active",
    expires_at: expiresAt,
    max_activations: maxActivations,
    features,
    key_prefix: licenseKey.slice(0, 11),
    active_activations: 0,
    license_key: licenseKey,
  }, 201);
}

async function handleRenewLicense(request, env, licenseId) {
  await requireAdmin(request, env);

  const body = await readJson(request);
  const durationDays = optionalPositiveInt(
    body.duration_days,
    "duration_days",
    1,
    3650,
    null,
  );

  if (!durationDays) {
    throw new HttpError(422, "duration_days is required");
  }

  const license = await env.DB.prepare(
    "SELECT * FROM licenses WHERE id = ? LIMIT 1"
  ).bind(licenseId).first();

  if (!license) throw new HttpError(404, "License not found");

  if (!license.expires_at) {
    throw new HttpError(409, "Perpetual license does not need renewal");
  }

  const now = new Date();
  const currentExpiry = new Date(license.expires_at);

  const extendFrom =
    Number.isNaN(currentExpiry.getTime()) || currentExpiry <= now
      ? now
      : currentExpiry;

  const nextExpiry = new Date(
    extendFrom.getTime() + durationDays * 86400000
  ).toISOString();

  const updatedAt = now.toISOString();

  await env.DB.prepare(
    "UPDATE licenses SET expires_at = ?, updated_at = ? WHERE id = ?"
  ).bind(nextExpiry, updatedAt, licenseId).run();

  return jsonResponse({
    id: license.id,
    customer_name: license.customer_name,
    plan: license.plan,
    status: license.status,
    previous_expires_at: license.expires_at,
    expires_at: nextExpiry,
    duration_days: durationDays,
    extended_from: extendFrom.toISOString(),
  });
}


async function handleUpdateFeatures(request, env, licenseId) {
  await requireAdmin(request, env);

  const body = await readJson(request);
  const features = body.features;

  if (
    !Array.isArray(features) ||
    features.some(
      (item) =>
        typeof item !== "string" ||
        item.trim().length < 1 ||
        item.trim().length > 100
    )
  ) {
    throw new HttpError(422, "features must be an array of non-empty short strings");
  }

  const normalizedFeatures = [
    ...new Set(features.map((item) => item.trim().toLowerCase())),
  ].sort();

  const license = await env.DB.prepare(
    "SELECT * FROM licenses WHERE id = ? LIMIT 1"
  ).bind(licenseId).first();

  if (!license) throw new HttpError(404, "License not found");

  const updatedAt = nowIso();

  await env.DB.prepare(
    "UPDATE licenses SET features_json = ?, updated_at = ? WHERE id = ?"
  ).bind(
    JSON.stringify(normalizedFeatures),
    updatedAt,
    licenseId,
  ).run();

  return jsonResponse({
    id: license.id,
    customer_name: license.customer_name,
    plan: license.plan,
    status: license.status,
    features: normalizedFeatures,
    updated_at: updatedAt,
  });
}

async function handleListLicenses(request, env) {
  await requireAdmin(request, env);
  const result = await env.DB.prepare(`
    SELECT
      l.*,
      (
        SELECT COUNT(*) FROM activations a
        WHERE a.license_id = l.id AND a.revoked_at IS NULL
      ) AS active_activations
    FROM licenses l
    ORDER BY l.created_at DESC
  `).all();

  return jsonResponse((result.results || []).map((row) => ({
    id: row.id,
    customer_name: row.customer_name,
    plan: row.plan,
    status: row.status,
    expires_at: row.expires_at,
    max_activations: row.max_activations,
    features: parseFeatures(row.features_json),
    key_prefix: row.key_prefix,
    active_activations: Number(row.active_activations || 0),
  })));
}

async function updateLicenseStatus(request, env, licenseId, nextStatus) {
  await requireAdmin(request, env);
  const license = await env.DB.prepare("SELECT * FROM licenses WHERE id = ? LIMIT 1")
    .bind(licenseId)
    .first();
  if (!license) throw new HttpError(404, "License not found");
  if (nextStatus === "active" && license.expires_at && new Date(license.expires_at).getTime() <= Date.now()) {
    throw new HttpError(409, "Expired license cannot be resumed");
  }
  const updatedAt = nowIso();
  await env.DB.prepare("UPDATE licenses SET status = ?, updated_at = ? WHERE id = ?")
    .bind(nextStatus, updatedAt, licenseId)
    .run();
  return jsonResponse({ status: nextStatus });
}

async function handleListActivations(request, env, licenseId) {
  await requireAdmin(request, env);
  const license = await env.DB.prepare("SELECT id FROM licenses WHERE id = ? LIMIT 1")
    .bind(licenseId)
    .first();
  if (!license) throw new HttpError(404, "License not found");
  const result = await env.DB.prepare(`
    SELECT id, installation_id, fingerprint, first_seen_at, last_seen_at, revoked_at
    FROM activations WHERE license_id = ? ORDER BY first_seen_at DESC
  `).bind(licenseId).all();
  return jsonResponse(result.results || []);
}

async function handleRevokeActivation(request, env, activationId) {
  await requireAdmin(request, env);
  const result = await env.DB.prepare(
    "UPDATE activations SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL"
  ).bind(nowIso(), activationId).run();
  if ((result.meta?.changes || 0) < 1) {
    const exists = await env.DB.prepare("SELECT id FROM activations WHERE id = ? LIMIT 1")
      .bind(activationId)
      .first();
    if (!exists) throw new HttpError(404, "Activation not found");
  }
  return jsonResponse({ status: "revoked" });
}

async function route(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  const method = request.method.toUpperCase();

  if (method === "GET" && path === "/health") {
    return jsonResponse({ status: "healthy", service: "dentalpin-license" });
  }

  if (method === "GET" && path === "/v1/public-key") {
    const { pem } = pemBodyFromBase64Pem(env.LICENSE_PUBLIC_KEY_B64);
    return jsonResponse({ algorithm: "Ed25519", public_key_pem: pem });
  }

  if (method === "POST" && path === "/ai/v1/chat/completions") return handleAiChatCompletions(request, env);

  if (method === "POST" && path === "/v1/activate") return handleActivate(request, env);
  if (method === "POST" && path === "/v1/refresh") return handleRefresh(request, env);
  if (method === "POST" && path === "/admin/licenses") return handleCreateLicense(request, env);
  if (method === "GET" && path === "/admin/licenses") return handleListLicenses(request, env);

  let match = path.match(/^\/admin\/licenses\/([^/]+)\/renew$/);
  if (method === "POST" && match) return handleRenewLicense(request, env, match[1]);

  match = path.match(/^\/admin\/licenses\/([^/]+)\/features$/);
  if (method === "POST" && match) return handleUpdateFeatures(request, env, match[1]);

  match = path.match(/^\/admin\/licenses\/([^/]+)\/suspend$/);
  if (method === "POST" && match) return updateLicenseStatus(request, env, match[1], "suspended");

  match = path.match(/^\/admin\/licenses\/([^/]+)\/resume$/);
  if (method === "POST" && match) return updateLicenseStatus(request, env, match[1], "active");

  match = path.match(/^\/admin\/licenses\/([^/]+)\/activations$/);
  if (method === "GET" && match) return handleListActivations(request, env, match[1]);

  match = path.match(/^\/admin\/activations\/([^/]+)\/revoke$/);
  if (method === "POST" && match) return handleRevokeActivation(request, env, match[1]);

  throw new HttpError(404, "Not found");
}

export default {
  async fetch(request, env) {
    try {
      return await route(request, env);
    } catch (error) {
      if (error instanceof HttpError) return jsonResponse({ detail: error.detail }, error.status);
      console.error("Unhandled license worker error", error);
      return jsonResponse({ detail: "Internal server error" }, 500);
    }
  },
};
