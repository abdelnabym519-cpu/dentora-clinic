const PRODUCT = "dentora";
const DEFAULT_WORKERS_AI_MODEL =
  "@cf/zai-org/glm-4.7-flash";

class GatewayError extends Error {
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

function base64UrlToBytes(value) {
  const normalized = value
    .replace(/-/g, "+")
    .replace(/_/g, "/");

  const padded =
    normalized
    + "=".repeat((4 - (normalized.length % 4)) % 4);

  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);

  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }

  return bytes;
}

function base64ToBytes(value) {
  const binary = atob(
    String(value || "").replace(/\s+/g, "")
  );

  const bytes = new Uint8Array(binary.length);

  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }

  return bytes;
}

function publicKeyDer(encodedPem) {
  if (!encodedPem) {
    throw new GatewayError(
      500,
      "AI gateway license verifier is not configured"
    );
  }

  const pem = atob(String(encodedPem).trim());

  const body = pem
    .replace(/-----BEGIN [^-]+-----/g, "")
    .replace(/-----END [^-]+-----/g, "")
    .replace(/\s+/g, "");

  if (!body) {
    throw new GatewayError(
      500,
      "AI gateway license public key is invalid"
    );
  }

  return base64ToBytes(body);
}

async function verifyLease(token, env) {
  const parts = String(token || "").split(".");

  if (parts.length !== 2) {
    throw new GatewayError(
      401,
      "Invalid AI gateway credential"
    );
  }

  let raw;
  let signature;

  try {
    raw = base64UrlToBytes(parts[0]);
    signature = base64UrlToBytes(parts[1]);
  } catch {
    throw new GatewayError(
      401,
      "Invalid AI gateway credential"
    );
  }

  const key = await crypto.subtle.importKey(
    "spki",
    publicKeyDer(env.LICENSE_PUBLIC_KEY_B64),
    { name: "Ed25519" },
    false,
    ["verify"]
  );

  const valid = await crypto.subtle.verify(
    "Ed25519",
    key,
    signature,
    raw
  );

  if (!valid) {
    throw new GatewayError(
      401,
      "Invalid AI gateway credential"
    );
  }

  let payload;

  try {
    payload = JSON.parse(
      new TextDecoder().decode(raw)
    );
  } catch {
    throw new GatewayError(
      401,
      "Invalid AI gateway credential"
    );
  }

  if (
    payload.product !== PRODUCT
    || payload.v !== 1
  ) {
    throw new GatewayError(
      401,
      "Invalid AI gateway credential"
    );
  }

  return payload;
}

function parseFeatures(raw) {
  if (!raw) return [];

  try {
    const value = JSON.parse(raw);

    if (!Array.isArray(value)) {
      return [];
    }

    return value
      .map((item) => String(item).trim().toLowerCase())
      .filter(Boolean);
  } catch {
    return [];
  }
}

function extractBearer(request) {
  const authorization =
    request.headers.get("authorization") || "";

  const match = authorization.match(
    /^Bearer\s+(.+)$/i
  );

  if (!match) {
    throw new GatewayError(
      401,
      "AI gateway credential is required"
    );
  }

  return match[1].trim();
}

function requireCurrentTimeValid(payload) {
  if (!payload.valid_until) {
    throw new GatewayError(
      401,
      "AI gateway credential has no expiry"
    );
  }

  const validUntil =
    new Date(payload.valid_until).getTime();

  if (
    !Number.isFinite(validUntil)
    || validUntil <= Date.now()
  ) {
    throw new GatewayError(
      401,
      "AI gateway credential has expired"
    );
  }
}

async function authorizeAi(request, env) {
  const token = extractBearer(request);
  const payload = await verifyLease(token, env);

  requireCurrentTimeValid(payload);

  const row = await env.DB.prepare(`
    SELECT
      a.id AS activation_id,
      a.license_id,
      a.installation_id,
      a.fingerprint,
      a.revoked_at,
      l.status AS license_status,
      l.expires_at AS license_expires_at,
      l.features_json
    FROM activations a
    JOIN licenses l
      ON l.id = a.license_id
    WHERE a.id = ?
      AND l.id = ?
    LIMIT 1
  `)
    .bind(
      payload.activation_id,
      payload.license_id
    )
    .first();

  if (!row) {
    throw new GatewayError(
      401,
      "AI activation was not found"
    );
  }

  if (row.revoked_at) {
    throw new GatewayError(
      403,
      "AI activation has been revoked"
    );
  }

  if (
    row.installation_id
      !== payload.installation_id
    || row.fingerprint
      !== payload.fingerprint
  ) {
    throw new GatewayError(
      401,
      "AI activation does not match lease"
    );
  }

  if (row.license_status !== "active") {
    throw new GatewayError(
      403,
      "License is not active"
    );
  }

  if (row.license_expires_at) {
    const expiry =
      new Date(row.license_expires_at).getTime();

    if (
      !Number.isFinite(expiry)
      || expiry <= Date.now()
    ) {
      throw new GatewayError(
        403,
        "License has expired"
      );
    }
  }

  const leaseFeatures = new Set(
    (payload.features || [])
      .map((item) =>
        String(item).trim().toLowerCase()
      )
  );

  const currentFeatures = new Set(
    parseFeatures(row.features_json)
  );

  if (
    !leaseFeatures.has("ai")
    || !currentFeatures.has("ai")
  ) {
    throw new GatewayError(
      403,
      "AI feature is not enabled"
    );
  }

  return {
    licenseId: row.license_id,
    activationId: row.activation_id,
  };
}

function allowedModels(env) {
  return new Set(
    String(env.AI_ALLOWED_MODELS || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
  );
}

function maxRequestBytes(env) {
  const parsed = Number.parseInt(
    env.AI_MAX_REQUEST_BYTES || "524288",
    10
  );

  if (
    !Number.isFinite(parsed)
    || parsed < 1024
  ) {
    return 524288;
  }

  return parsed;
}

function clampOutputTokens(body) {
  const maximum = 4096;

  if (
    Number.isInteger(body.max_completion_tokens)
    && body.max_completion_tokens > maximum
  ) {
    body.max_completion_tokens = maximum;
  }

  if (
    Number.isInteger(body.max_tokens)
    && body.max_tokens > maximum
  ) {
    body.max_tokens = maximum;
  }
}


async function enforceAiRateLimit(
  authorization,
  env
) {
  if (
    !env.AI_RATE_LIMITER
    || typeof env.AI_RATE_LIMITER.limit
      !== "function"
  ) {
    throw new GatewayError(
      503,
      "AI rate limiter is not configured"
    );
  }

  const result =
    await env.AI_RATE_LIMITER.limit({
      key: authorization.activationId,
    });

  if (!result?.success) {
    throw new GatewayError(
      429,
      "AI request rate limit exceeded"
    );
  }
}

function workersAiModel(env) {
  const model = String(
    env.AI_PROVIDER_MODEL
      || DEFAULT_WORKERS_AI_MODEL
  ).trim();

  if (!model || !model.startsWith("@cf/")) {
    throw new GatewayError(
      500,
      "Workers AI model is not configured"
    );
  }

  return model;
}

async function proxyToWorkersAi(request, env) {
  if (
    !env.AI
    || typeof env.AI.run !== "function"
  ) {
    throw new GatewayError(
      503,
      "Workers AI binding is not configured"
    );
  }

  const contentLength = Number.parseInt(
    request.headers.get("content-length") || "0",
    10
  );

  const maximumBytes = maxRequestBytes(env);

  if (
    Number.isFinite(contentLength)
    && contentLength > maximumBytes
  ) {
    throw new GatewayError(
      413,
      "AI request is too large"
    );
  }

  const raw = await request.text();

  const actualBytes =
    new TextEncoder().encode(raw).byteLength;

  if (actualBytes > maximumBytes) {
    throw new GatewayError(
      413,
      "AI request is too large"
    );
  }

  let body;

  try {
    body = JSON.parse(raw);
  } catch {
    throw new GatewayError(
      400,
      "AI request must be valid JSON"
    );
  }

  if (
    !body
    || typeof body !== "object"
    || Array.isArray(body)
  ) {
    throw new GatewayError(
      400,
      "AI request body is invalid"
    );
  }

  if (body.stream !== true) {
    throw new GatewayError(
      422,
      "AI gateway requires streaming requests"
    );
  }

  if (
    typeof body.model !== "string"
    || !body.model.trim()
  ) {
    throw new GatewayError(
      422,
      "AI model is required"
    );
  }

  const requestedModel =
    body.model.trim();

  const models = allowedModels(env);

  if (
    models.size === 0
    || !models.has(requestedModel)
  ) {
    throw new GatewayError(
      403,
      "AI model is not allowed"
    );
  }

  clampOutputTokens(body);

  const providerModel =
    workersAiModel(env);

  /*
   * The Dentora backend keeps using its
   * client-facing model alias.
   *
   * The owner-controlled gateway maps that alias
   * to the actual Workers AI model.
   */
  body.model = providerModel;

  let stream;

  try {
    stream = await env.AI.run(
      providerModel,
      body
    );
  } catch {
    console.error(
      "Workers AI inference failed"
    );

    throw new GatewayError(
      502,
      "AI provider request failed"
    );
  }

  if (!(stream instanceof ReadableStream)) {
    throw new GatewayError(
      502,
      "AI provider returned an invalid stream"
    );
  }

  return new Response(
    stream,
    {
      status: 200,
      headers: {
        "content-type":
          "text/event-stream",
        "cache-control":
          "no-store",
      },
    }
  );
}

export async function handleAiChatCompletions(
  request,
  env
) {
  try {
    const authorization =
      await authorizeAi(
        request,
        env
      );

    await enforceAiRateLimit(
      authorization,
      env
    );

    return await proxyToWorkersAi(
      request,
      env
    );
  } catch (error) {
    if (error instanceof GatewayError) {
      return jsonResponse(
        { detail: error.detail },
        error.status
      );
    }

    console.error(
      "Unhandled AI gateway error"
    );

    return jsonResponse(
      {
        detail:
          "AI gateway internal server error",
      },
      500
    );
  }
}
