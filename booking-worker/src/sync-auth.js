const PRODUCT = "dentora";


export class SyncAuthError extends Error {
  constructor(status, code) {
    super(code);
    this.status = status;
    this.code = code;
  }
}


function base64UrlToBytes(value) {
  const normalized = String(value || "")
    .replace(/-/g, "+")
    .replace(/_/g, "/");

  const padded =
    normalized
    + "=".repeat(
      (4 - (normalized.length % 4)) % 4
    );

  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);

  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }

  return bytes;
}


function base64ToBytes(value) {
  const binary = atob(
    String(value || "")
      .replace(/\s+/g, "")
  );

  const bytes = new Uint8Array(binary.length);

  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }

  return bytes;
}


function publicKeyDer(encodedPem) {
  if (!encodedPem) {
    throw new SyncAuthError(
      503,
      "sync_auth_not_configured"
    );
  }

  let pem;

  try {
    pem = atob(
      String(encodedPem).trim()
    );
  } catch {
    throw new SyncAuthError(
      503,
      "sync_auth_not_configured"
    );
  }

  const body = pem
    .replace(
      /-----BEGIN [^-]+-----/g,
      ""
    )
    .replace(
      /-----END [^-]+-----/g,
      ""
    )
    .replace(/\s+/g, "");

  if (!body) {
    throw new SyncAuthError(
      503,
      "sync_auth_not_configured"
    );
  }

  try {
    return base64ToBytes(body);
  } catch {
    throw new SyncAuthError(
      503,
      "sync_auth_not_configured"
    );
  }
}


function extractBearer(request) {
  const authorization =
    request.headers.get(
      "authorization"
    ) || "";

  const match =
    authorization.match(
      /^Bearer\s+(.+)$/i
    );

  if (!match) {
    throw new SyncAuthError(
      401,
      "sync_credential_required"
    );
  }

  return match[1].trim();
}


async function verifyLease(
  token,
  env
) {
  const parts =
    String(token || "")
      .split(".");

  if (parts.length !== 2) {
    throw new SyncAuthError(
      401,
      "invalid_sync_credential"
    );
  }

  let raw;
  let signature;

  try {
    raw =
      base64UrlToBytes(parts[0]);

    signature =
      base64UrlToBytes(parts[1]);
  } catch {
    throw new SyncAuthError(
      401,
      "invalid_sync_credential"
    );
  }

  let key;

  try {
    key =
      await crypto.subtle.importKey(
        "spki",
        publicKeyDer(
          env.LICENSE_PUBLIC_KEY_B64
        ),
        {
          name: "Ed25519"
        },
        false,
        [
          "verify"
        ]
      );
  } catch (error) {
    if (
      error instanceof SyncAuthError
    ) {
      throw error;
    }

    throw new SyncAuthError(
      503,
      "sync_auth_not_configured"
    );
  }

  const valid =
    await crypto.subtle.verify(
      "Ed25519",
      key,
      signature,
      raw
    );

  if (!valid) {
    throw new SyncAuthError(
      401,
      "invalid_sync_credential"
    );
  }

  let payload;

  try {
    payload =
      JSON.parse(
        new TextDecoder()
          .decode(raw)
      );
  } catch {
    throw new SyncAuthError(
      401,
      "invalid_sync_credential"
    );
  }

  if (
    payload.product !== PRODUCT ||
    payload.v !== 1
  ) {
    throw new SyncAuthError(
      401,
      "invalid_sync_credential"
    );
  }

  return payload;
}


function parseFeatures(raw) {
  if (!raw) {
    return [];
  }

  try {
    const parsed =
      JSON.parse(raw);

    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed
      .map(
        value =>
          String(value)
            .trim()
            .toLowerCase()
      )
      .filter(Boolean);
  } catch {
    return [];
  }
}


function requireLeaseExpiry(payload) {
  const expiry =
    new Date(
      payload.valid_until || ""
    ).getTime();

  if (
    !Number.isFinite(expiry) ||
    expiry <= Date.now()
  ) {
    throw new SyncAuthError(
      401,
      "sync_credential_expired"
    );
  }
}


function requireLeaseIdentity(payload) {
  const required = [
    "license_id",
    "activation_id",
    "installation_id",
    "fingerprint"
  ];

  for (const field of required) {
    if (
      !String(
        payload[field] || ""
      ).trim()
    ) {
      throw new SyncAuthError(
        401,
        "invalid_sync_credential"
      );
    }
  }
}


export async function authorizeBookingSync(
  request,
  env
) {
  if (!env.LICENSE_DB) {
    throw new SyncAuthError(
      503,
      "license_database_unavailable"
    );
  }

  const token =
    extractBearer(request);

  const payload =
    await verifyLease(
      token,
      env
    );

  requireLeaseExpiry(payload);
  requireLeaseIdentity(payload);

  const leaseFeatures =
    new Set(
      (payload.features || [])
        .map(
          value =>
            String(value)
              .trim()
              .toLowerCase()
        )
    );

  if (
    !leaseFeatures.has(
      "booking"
    )
  ) {
    throw new SyncAuthError(
      403,
      "booking_feature_not_enabled"
    );
  }

  const row =
    await env.LICENSE_DB.prepare(
      `SELECT
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
       LIMIT 1`
    )
      .bind(
        payload.activation_id,
        payload.license_id
      )
      .first();

  if (!row) {
    throw new SyncAuthError(
      401,
      "activation_not_found"
    );
  }

  if (row.revoked_at) {
    throw new SyncAuthError(
      403,
      "activation_revoked"
    );
  }

  if (
    row.installation_id !==
      payload.installation_id ||
    row.fingerprint !==
      payload.fingerprint
  ) {
    throw new SyncAuthError(
      401,
      "activation_identity_mismatch"
    );
  }

  if (
    row.license_status !==
      "active"
  ) {
    throw new SyncAuthError(
      403,
      "license_not_active"
    );
  }

  if (
    row.license_expires_at
  ) {
    const expiry =
      new Date(
        row.license_expires_at
      ).getTime();

    if (
      !Number.isFinite(expiry) ||
      expiry <= Date.now()
    ) {
      throw new SyncAuthError(
        403,
        "license_expired"
      );
    }
  }

  const currentFeatures =
    new Set(
      parseFeatures(
        row.features_json
      )
    );

  if (
    !currentFeatures.has(
      "booking"
    )
  ) {
    throw new SyncAuthError(
      403,
      "booking_feature_not_enabled"
    );
  }

  return {
    licenseId:
      row.license_id,

    activationId:
      row.activation_id,

    installationId:
      row.installation_id,

    fingerprint:
      row.fingerprint
  };
}
