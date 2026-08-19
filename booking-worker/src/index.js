import {
  authorizeBookingSync,
  SyncAuthError
} from "./sync-auth.js";

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "x-content-type-options": "nosniff",
      "cache-control": "no-store"
    }
  });
}


function notFound() {
  return jsonResponse(
    {
      ok: false,
      error: "not_found"
    },
    404
  );
}


function methodNotAllowed() {
  return jsonResponse(
    {
      ok: false,
      error: "method_not_allowed"
    },
    405
  );
}


function bytesToBase64(bytes) {
  let binary = "";

  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }

  return btoa(binary);
}


function base64ToBytes(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);

  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }

  return bytes;
}


async function importBookingKey(env) {
  const encoded =
    String(env.BOOKING_PII_KEY_B64 || "").trim();

  if (!encoded) {
    throw new Error("booking_key_missing");
  }

  let raw;

  try {
    raw = base64ToBytes(encoded);
  } catch {
    throw new Error("booking_key_invalid");
  }

  if (raw.byteLength !== 32) {
    throw new Error("booking_key_invalid");
  }

  return crypto.subtle.importKey(
    "raw",
    raw,
    {
      name: "AES-GCM"
    },
    false,
    [
      "encrypt",
      "decrypt"
    ]
  );
}


async function encryptPatientPayload(env, payload) {
  const key = await importBookingKey(env);

  const iv = crypto.getRandomValues(
    new Uint8Array(12)
  );

  const plaintext = new TextEncoder().encode(
    JSON.stringify(payload)
  );

  const encrypted = await crypto.subtle.encrypt(
    {
      name: "AES-GCM",
      iv
    },
    key,
    plaintext
  );

  return {
    ciphertext: bytesToBase64(
      new Uint8Array(encrypted)
    ),
    iv: bytesToBase64(iv)
  };
}



async function decryptPatientPayload(
  env,
  row
) {
  const keyVersion =
    Number(
      row.patient_key_version
    );

  if (keyVersion !== 1) {
    throw new Error(
      "booking_key_version_unsupported"
    );
  }

  const key =
    await importBookingKey(env);

  let iv;

  try {
    iv =
      base64ToBytes(
        row.patient_iv
      );
  } catch {
    throw new Error(
      "booking_payload_decryption_failed"
    );
  }

  if (
    iv.byteLength !== 12
  ) {
    throw new Error(
      "booking_payload_decryption_failed"
    );
  }

  let ciphertext;

  try {
    ciphertext =
      base64ToBytes(
        row.patient_ciphertext
      );
  } catch {
    throw new Error(
      "booking_payload_decryption_failed"
    );
  }

  let plaintext;

  try {
    plaintext =
      await crypto.subtle.decrypt(
        {
          name: "AES-GCM",
          iv
        },
        key,
        ciphertext
      );
  } catch {
    throw new Error(
      "booking_payload_decryption_failed"
    );
  }

  let payload;

  try {
    payload =
      JSON.parse(
        new TextDecoder()
          .decode(plaintext)
      );
  } catch {
    throw new Error(
      "booking_payload_decryption_failed"
    );
  }

  if (
    !payload ||
    typeof payload !== "object" ||
    Array.isArray(payload)
  ) {
    throw new Error(
      "booking_payload_decryption_failed"
    );
  }

  return {
    first_name:
      String(
        payload.first_name || ""
      ),

    last_name:
      String(
        payload.last_name || ""
      ),

    phone:
      String(
        payload.phone || ""
      ),

    date_of_birth:
      String(
        payload.date_of_birth || ""
      ),

    email:
      payload.email === null ||
      payload.email === undefined
        ? null
        : String(payload.email)
  };
}


function validSlug(value) {
  return /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(
    value
  );
}


function validDateOnly(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false;
  }

  const parsed = Date.parse(
    `${value}T00:00:00Z`
  );

  return Number.isFinite(parsed);
}


function normalizeBookingPayload(payload) {
  if (
    !payload ||
    typeof payload !== "object" ||
    Array.isArray(payload)
  ) {
    return {
      ok: false,
      error: "invalid_payload"
    };
  }

  const allowed = new Set([
    "professional_slug",
    "start_time",
    "first_name",
    "last_name",
    "phone",
    "date_of_birth",
    "email"
  ]);

  for (const field of Object.keys(payload)) {
    if (!allowed.has(field)) {
      return {
        ok: false,
        error:
          field === "reason"
            ? "medical_notes_not_allowed"
            : "unexpected_field"
      };
    }
  }

  const professionalSlug = String(
    payload.professional_slug || ""
  )
    .trim()
    .toLowerCase();

  const startTime = String(
    payload.start_time || ""
  ).trim();

  const firstName = String(
    payload.first_name || ""
  ).trim();

  const lastName = String(
    payload.last_name || ""
  ).trim();

  const phone = String(
    payload.phone || ""
  ).trim();

  const dateOfBirth = String(
    payload.date_of_birth || ""
  ).trim();

  const email =
    payload.email === undefined ||
    payload.email === null
      ? null
      : String(payload.email).trim();

  if (
    !validSlug(professionalSlug) ||
    firstName.length < 1 ||
    firstName.length > 100 ||
    lastName.length < 1 ||
    lastName.length > 100 ||
    phone.length < 7 ||
    phone.length > 20 ||
    !validDateOnly(dateOfBirth) ||
    (email !== null && email.length > 255)
  ) {
    return {
      ok: false,
      error: "validation_error"
    };
  }

  const parsedStart = Date.parse(startTime);

  if (!Number.isFinite(parsedStart)) {
    return {
      ok: false,
      error: "validation_error"
    };
  }

  if (parsedStart <= Date.now()) {
    return {
      ok: false,
      error: "slot_unavailable"
    };
  }

  return {
    ok: true,
    value: {
      professional_slug: professionalSlug,
      start_time: startTime,
      first_name: firstName,
      last_name: lastName,
      phone,
      date_of_birth: dateOfBirth,
      email:
        email && email.length > 0
          ? email
          : null
    }
  };
}


async function readJsonBody(request, maxBytes = 16384) {
  const declaredLength = Number(
    request.headers.get("content-length") || "0"
  );

  if (
    Number.isFinite(declaredLength) &&
    declaredLength > maxBytes
  ) {
    return {
      ok: false,
      error: "payload_too_large"
    };
  }

  const text = await request.text();

  if (text.length > maxBytes) {
    return {
      ok: false,
      error: "payload_too_large"
    };
  }

  try {
    return {
      ok: true,
      value: JSON.parse(text)
    };
  } catch {
    return {
      ok: false,
      error: "invalid_json"
    };
  }
}


async function getPublicClinic(
  env,
  clinicSlug
) {
  return env.DB.prepare(
    `SELECT
       id,
       public_slug,
       display_name,
       phone,
       email,
       timezone,
       currency,
       slot_minutes,
       days_ahead,
       last_synced_at
     FROM clinics
     WHERE public_slug = ?
       AND enabled = 1
     LIMIT 1`
  )
    .bind(clinicSlug)
    .first();
}


async function listProfessionals(
  env,
  clinicId
) {
  const result = await env.DB.prepare(
    `SELECT
       public_slug,
       display_name
     FROM professionals
     WHERE clinic_id = ?
       AND active = 1
     ORDER BY display_name COLLATE NOCASE`
  )
    .bind(clinicId)
    .all();

  return result.results || [];
}


async function getProfessional(
  env,
  clinicId,
  doctorSlug
) {
  return env.DB.prepare(
    `SELECT
       id,
       public_slug,
       display_name
     FROM professionals
     WHERE clinic_id = ?
       AND public_slug = ?
       AND active = 1
     LIMIT 1`
  )
    .bind(
      clinicId,
      doctorSlug
    )
    .first();
}


async function listAvailableSlots(
  env,
  clinicId,
  professionalId,
  day
) {
  const result = await env.DB.prepare(
    `SELECT
       start_time,
       end_time
     FROM availability_slots
     WHERE clinic_id = ?
       AND professional_id = ?
       AND local_day = ?
       AND available = 1
       AND EXISTS (
         SELECT 1
         FROM sync_state s
         WHERE s.clinic_id =
           availability_slots.clinic_id
           AND s.last_availability_snapshot_version =
             availability_slots.snapshot_version
       )
     ORDER BY start_time ASC`
  )
    .bind(
      clinicId,
      professionalId,
      day
    )
    .all();

  return result.results || [];
}


async function getAvailableSlot(
  env,
  clinicId,
  professionalId,
  startTime
) {
  return env.DB.prepare(
    `SELECT
       start_time,
       end_time
     FROM availability_slots
     WHERE clinic_id = ?
       AND professional_id = ?
       AND start_time = ?
       AND available = 1
       AND EXISTS (
         SELECT 1
         FROM sync_state s
         WHERE s.clinic_id =
           availability_slots.clinic_id
           AND s.last_availability_snapshot_version =
             availability_slots.snapshot_version
       )
     LIMIT 1`
  )
    .bind(
      clinicId,
      professionalId,
      startTime
    )
    .first();
}


async function createBookingRequest(
  request,
  env,
  clinic
) {
  const body = await readJsonBody(request);

  if (!body.ok) {
    const status =
      body.error === "payload_too_large"
        ? 413
        : 400;

    return jsonResponse(
      {
        ok: false,
        error: body.error
      },
      status
    );
  }

  const normalized =
    normalizeBookingPayload(body.value);

  if (!normalized.ok) {
    const status =
      normalized.error === "slot_unavailable"
        ? 409
        : 400;

    return jsonResponse(
      {
        ok: false,
        error: normalized.error
      },
      status
    );
  }

  const data = normalized.value;

  const professional =
    await getProfessional(
      env,
      clinic.id,
      data.professional_slug
    );

  if (!professional) {
    return notFound();
  }

  const slot = await getAvailableSlot(
    env,
    clinic.id,
    professional.id,
    data.start_time
  );

  if (!slot) {
    return jsonResponse(
      {
        ok: false,
        error: "slot_unavailable"
      },
      409
    );
  }

  const patientPayload = {
    first_name: data.first_name,
    last_name: data.last_name,
    phone: data.phone,
    date_of_birth: data.date_of_birth,
    email: data.email
  };

  let encrypted;

  try {
    encrypted =
      await encryptPatientPayload(
        env,
        patientPayload
      );
  } catch (error) {
    if (
      error?.message ===
        "booking_key_missing" ||
      error?.message ===
        "booking_key_invalid"
    ) {
      return jsonResponse(
        {
          ok: false,
          error: "service_configuration_error"
        },
        503
      );
    }

    throw error;
  }

  const requestId =
    crypto.randomUUID();

  const headerIdempotency =
    String(
      request.headers.get(
        "idempotency-key"
      ) || ""
    )
      .trim()
      .slice(0, 200);

  const idempotencyKey =
    headerIdempotency ||
    crypto.randomUUID();

  const startTimestamp =
    Date.parse(slot.start_time);

  const maxPendingLifetime =
    Date.now() +
    24 * 60 * 60 * 1000;

  const expiresTimestamp =
    Number.isFinite(startTimestamp)
      ? Math.min(
          startTimestamp,
          maxPendingLifetime
        )
      : maxPendingLifetime;

  const expiresAt =
    new Date(
      expiresTimestamp
    ).toISOString();

  try {
    await env.DB.prepare(
      `INSERT INTO booking_requests (
         id,
         clinic_id,
         professional_id,
         start_time,
         end_time,
         patient_ciphertext,
         patient_iv,
         patient_key_version,
         status,
         idempotency_key,
         expires_at
       )
       VALUES (
         ?, ?, ?, ?, ?, ?, ?, 1,
         'pending', ?, ?
       )`
    )
      .bind(
        requestId,
        clinic.id,
        professional.id,
        slot.start_time,
        slot.end_time,
        encrypted.ciphertext,
        encrypted.iv,
        idempotencyKey,
        expiresAt
      )
      .run();
  } catch (error) {
    const message =
      String(error?.message || "");

    if (
      message.includes("UNIQUE") ||
      message.includes("constraint")
    ) {
      return jsonResponse(
        {
          ok: false,
          error: "slot_unavailable"
        },
        409
      );
    }

    throw error;
  }

  return jsonResponse(
    {
      ok: true,
      data: {
        request_id: requestId,
        status: "pending",
        professional_slug:
          professional.public_slug,
        professional_name:
          professional.display_name,
        start_time:
          slot.start_time,
        end_time:
          slot.end_time,
        message:
          "تم إرسال طلب الحجز إلى العيادة"
      }
    },
    202
  );
}



function validTimeZone(value) {
  try {
    new Intl.DateTimeFormat(
      "en-US",
      {
        timeZone: value
      }
    );

    return true;
  } catch {
    return false;
  }
}


function normalizeSyncProfile(payload) {
  if (
    !payload ||
    typeof payload !== "object" ||
    Array.isArray(payload)
  ) {
    return {
      ok: false,
      error: "invalid_payload"
    };
  }

  const allowed = new Set([
    "public_slug",
    "display_name",
    "phone",
    "email",
    "timezone",
    "currency",
    "enabled",
    "slot_minutes",
    "days_ahead"
  ]);

  for (const field of Object.keys(payload)) {
    if (!allowed.has(field)) {
      return {
        ok: false,
        error: "unexpected_field"
      };
    }
  }

  const publicSlug =
    String(
      payload.public_slug || ""
    )
      .trim()
      .toLowerCase();

  const displayName =
    String(
      payload.display_name || ""
    ).trim();

  const phone =
    payload.phone === null ||
    payload.phone === undefined
      ? null
      : String(
          payload.phone
        ).trim();

  const email =
    payload.email === null ||
    payload.email === undefined
      ? null
      : String(
          payload.email
        ).trim();

  const timezone =
    String(
      payload.timezone || ""
    ).trim();

  const currency =
    String(
      payload.currency || ""
    )
      .trim()
      .toUpperCase();

  const enabled =
    payload.enabled;

  const slotMinutes =
    payload.slot_minutes;

  const daysAhead =
    payload.days_ahead;

  if (
    !validSlug(publicSlug) ||
    displayName.length < 1 ||
    displayName.length > 160
  ) {
    return {
      ok: false,
      error: "validation_error"
    };
  }

  if (
    phone !== null &&
    phone.length > 50
  ) {
    return {
      ok: false,
      error: "validation_error"
    };
  }

  if (
    email !== null &&
    email.length > 255
  ) {
    return {
      ok: false,
      error: "validation_error"
    };
  }

  if (
    !timezone ||
    timezone.length > 100 ||
    !validTimeZone(timezone)
  ) {
    return {
      ok: false,
      error: "validation_error"
    };
  }

  if (
    !/^[A-Z]{3}$/.test(currency)
  ) {
    return {
      ok: false,
      error: "validation_error"
    };
  }

  if (
    typeof enabled !== "boolean"
  ) {
    return {
      ok: false,
      error: "validation_error"
    };
  }

  if (
    !Number.isInteger(slotMinutes) ||
    slotMinutes < 5 ||
    slotMinutes > 240
  ) {
    return {
      ok: false,
      error: "validation_error"
    };
  }

  if (
    !Number.isInteger(daysAhead) ||
    daysAhead < 1 ||
    daysAhead > 365
  ) {
    return {
      ok: false,
      error: "validation_error"
    };
  }

  return {
    ok: true,
    value: {
      public_slug:
        publicSlug,

      display_name:
        displayName,

      phone:
        phone || null,

      email:
        email || null,

      timezone,

      currency,

      enabled,

      slot_minutes:
        slotMinutes,

      days_ahead:
        daysAhead
    }
  };
}



function normalizeSyncProfessionals(payload) {
  if (
    !payload ||
    typeof payload !== "object" ||
    Array.isArray(payload)
  ) {
    return {
      ok: false,
      error: "invalid_payload"
    };
  }

  const topFields =
    Object.keys(payload);

  if (
    topFields.length !== 1 ||
    topFields[0] !== "professionals"
  ) {
    return {
      ok: false,
      error: "unexpected_field"
    };
  }

  if (
    !Array.isArray(
      payload.professionals
    )
  ) {
    return {
      ok: false,
      error: "validation_error"
    };
  }

  if (
    payload.professionals.length > 100
  ) {
    return {
      ok: false,
      error: "too_many_professionals"
    };
  }

  const allowed = new Set([
    "local_professional_id",
    "public_slug",
    "display_name",
    "active"
  ]);

  const localIds =
    new Set();

  const publicSlugs =
    new Set();

  const professionals = [];

  for (
    const item
    of payload.professionals
  ) {
    if (
      !item ||
      typeof item !== "object" ||
      Array.isArray(item)
    ) {
      return {
        ok: false,
        error: "validation_error"
      };
    }

    for (
      const field
      of Object.keys(item)
    ) {
      if (!allowed.has(field)) {
        return {
          ok: false,
          error: "unexpected_field"
        };
      }
    }

    const localProfessionalId =
      String(
        item.local_professional_id || ""
      ).trim();

    const publicSlug =
      String(
        item.public_slug || ""
      )
        .trim()
        .toLowerCase();

    const displayName =
      String(
        item.display_name || ""
      ).trim();

    const active =
      item.active;

    if (
      localProfessionalId.length < 1 ||
      localProfessionalId.length > 128 ||
      !validSlug(publicSlug) ||
      displayName.length < 1 ||
      displayName.length > 160 ||
      typeof active !== "boolean"
    ) {
      return {
        ok: false,
        error: "validation_error"
      };
    }

    if (
      localIds.has(
        localProfessionalId
      )
    ) {
      return {
        ok: false,
        error:
          "duplicate_local_professional_id"
      };
    }

    if (
      publicSlugs.has(
        publicSlug
      )
    ) {
      return {
        ok: false,
        error:
          "duplicate_professional_slug"
      };
    }

    localIds.add(
      localProfessionalId
    );

    publicSlugs.add(
      publicSlug
    );

    professionals.push({
      local_professional_id:
        localProfessionalId,

      public_slug:
        publicSlug,

      display_name:
        displayName,

      active
    });
  }

  return {
    ok: true,
    value: professionals
  };
}


async function syncProfessionals(
  request,
  env,
  auth
) {
  const clinicId =
    `license:${auth.licenseId}`;

  /*
   * A professionals snapshot is only
   * accepted after the authenticated
   * installation has published its
   * clinic profile.
   */
  const clinic =
    await env.DB.prepare(
      `SELECT
         id,
         license_id
       FROM clinics
       WHERE id = ?
         AND license_id = ?
       LIMIT 1`
    )
      .bind(
        clinicId,
        auth.licenseId
      )
      .first();

  if (!clinic) {
    return jsonResponse(
      {
        ok: false,
        error:
          "clinic_profile_not_synced"
      },
      409
    );
  }

  /*
   * The same installation that owns
   * the clinic sync state must publish
   * its professionals.
   */
  const syncState =
    await env.DB.prepare(
      `SELECT
         installation_id
       FROM sync_state
       WHERE clinic_id = ?
       LIMIT 1`
    )
      .bind(
        clinicId
      )
      .first();

  if (!syncState) {
    return jsonResponse(
      {
        ok: false,
        error:
          "clinic_profile_not_synced"
      },
      409
    );
  }

  if (
    syncState.installation_id !==
      auth.installationId
  ) {
    return jsonResponse(
      {
        ok: false,
        error:
          "clinic_installation_mismatch"
      },
      403
    );
  }

  const body =
    await readJsonBody(
      request
    );

  if (!body.ok) {
    return jsonResponse(
      {
        ok: false,
        error: body.error
      },
      body.error ===
        "payload_too_large"
        ? 413
        : 400
    );
  }

  const normalized =
    normalizeSyncProfessionals(
      body.value
    );

  if (!normalized.ok) {
    return jsonResponse(
      {
        ok: false,
        error:
          normalized.error
      },
      normalized.error ===
        "too_many_professionals"
        ? 413
        : 400
    );
  }

  const professionals =
    normalized.value;

  const now =
    new Date().toISOString();

  /*
   * Snapshot semantics:
   *
   * 1. Existing cloud professionals
   *    become inactive.
   * 2. Incoming local professionals
   *    are upserted.
   * 3. Sync timestamp is advanced.
   *
   * D1 batch keeps this one atomic
   * database operation.
   */
  const statements = [
    env.DB.prepare(
      `UPDATE professionals
       SET
         active = 0,
         updated_at = ?
       WHERE clinic_id = ?`
    )
      .bind(
        now,
        clinicId
      )
  ];

  for (
    const professional
    of professionals
  ) {
    const cloudProfessionalId =
      `professional:${crypto.randomUUID()}`;

    statements.push(
      env.DB.prepare(
        `INSERT INTO professionals (
           id,
           clinic_id,
           local_professional_id,
           public_slug,
           display_name,
           active,
           updated_at
         )
         VALUES (
           ?, ?, ?, ?, ?, ?, ?
         )
         ON CONFLICT(
           clinic_id,
           local_professional_id
         )
         DO UPDATE SET
           public_slug =
             excluded.public_slug,
           display_name =
             excluded.display_name,
           active =
             excluded.active,
           updated_at =
             excluded.updated_at`
      )
        .bind(
          cloudProfessionalId,
          clinicId,
          professional
            .local_professional_id,
          professional
            .public_slug,
          professional
            .display_name,
          professional.active
            ? 1
            : 0,
          now
        )
    );
  }

  statements.push(
    env.DB.prepare(
      `UPDATE sync_state
       SET
         last_professionals_sync_at = ?,
         updated_at = ?
       WHERE clinic_id = ?
         AND installation_id = ?`
    )
      .bind(
        now,
        now,
        clinicId,
        auth.installationId
      )
  );

  try {
    await env.DB.batch(
      statements
    );
  } catch (error) {
    const message =
      String(
        error?.message || ""
      );

    if (
      message.includes(
        "UNIQUE"
      ) ||
      message.includes(
        "constraint"
      )
    ) {
      return jsonResponse(
        {
          ok: false,
          error:
            "professional_identity_conflict"
        },
        409
      );
    }

    throw error;
  }

  return jsonResponse({
    ok: true,
    data: {
      synced:
        professionals.length,

      active:
        professionals.filter(
          item =>
            item.active
        ).length,

      last_synced_at:
        now
    }
  });
}



function parseExplicitInstant(value) {
  const text =
    String(value || "").trim();

  if (
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(
      text
    )
  ) {
    return null;
  }

  const timestamp =
    Date.parse(text);

  if (
    !Number.isFinite(timestamp)
  ) {
    return null;
  }

  return {
    timestamp,

    iso:
      new Date(
        timestamp
      ).toISOString()
  };
}


function localDayForInstant(
  iso,
  timezone
) {
  try {
    const parts =
      new Intl.DateTimeFormat(
        "en-US",
        {
          timeZone:
            timezone,

          year:
            "numeric",

          month:
            "2-digit",

          day:
            "2-digit"
        }
      )
        .formatToParts(
          new Date(iso)
        );

    const values = {};

    for (const part of parts) {
      if (
        part.type === "year" ||
        part.type === "month" ||
        part.type === "day"
      ) {
        values[part.type] =
          part.value;
      }
    }

    if (
      !values.year ||
      !values.month ||
      !values.day
    ) {
      return null;
    }

    return (
      values.year
      + "-"
      + values.month
      + "-"
      + values.day
    );
  } catch {
    return null;
  }
}


function normalizeSyncAvailability(
  payload,
  clinic,
  professionalMap
) {
  if (
    !payload ||
    typeof payload !== "object" ||
    Array.isArray(payload)
  ) {
    return {
      ok: false,
      error: "invalid_payload"
    };
  }

  const allowedTop =
    new Set([
      "snapshot_version",
      "slots"
    ]);

  for (
    const field
    of Object.keys(payload)
  ) {
    if (
      !allowedTop.has(field)
    ) {
      return {
        ok: false,
        error: "unexpected_field"
      };
    }
  }

  const snapshotVersion =
    payload.snapshot_version;

  if (
    !Number.isInteger(
      snapshotVersion
    ) ||
    snapshotVersion < 1 ||
    snapshotVersion > 2147483647
  ) {
    return {
      ok: false,
      error: "invalid_snapshot_version"
    };
  }

  if (
    !Array.isArray(
      payload.slots
    )
  ) {
    return {
      ok: false,
      error: "validation_error"
    };
  }

  if (
    payload.slots.length > 2000
  ) {
    return {
      ok: false,
      error: "too_many_slots"
    };
  }

  const allowedSlotFields =
    new Set([
      "local_professional_id",
      "start_time",
      "end_time",
      "available"
    ]);

  const identities =
    new Set();

  const rows = [];

  for (
    const item
    of payload.slots
  ) {
    if (
      !item ||
      typeof item !== "object" ||
      Array.isArray(item)
    ) {
      return {
        ok: false,
        error: "validation_error"
      };
    }

    for (
      const field
      of Object.keys(item)
    ) {
      if (
        !allowedSlotFields.has(
          field
        )
      ) {
        return {
          ok: false,
          error: "unexpected_field"
        };
      }
    }

    const localProfessionalId =
      String(
        item.local_professional_id || ""
      ).trim();

    const professional =
      professionalMap.get(
        localProfessionalId
      );

    if (
      !professional ||
      professional.active !== 1
    ) {
      return {
        ok: false,
        error:
          "unknown_or_inactive_professional"
      };
    }

    if (
      typeof item.available !==
        "boolean"
    ) {
      return {
        ok: false,
        error: "validation_error"
      };
    }

    const start =
      parseExplicitInstant(
        item.start_time
      );

    const end =
      parseExplicitInstant(
        item.end_time
      );

    if (
      !start ||
      !end ||
      end.timestamp <=
        start.timestamp
    ) {
      return {
        ok: false,
        error:
          "invalid_slot_time"
      };
    }

    const expectedDuration =
      clinic.slot_minutes *
      60 *
      1000;

    if (
      end.timestamp -
        start.timestamp !==
      expectedDuration
    ) {
      return {
        ok: false,
        error:
          "invalid_slot_duration"
      };
    }

    const localDay =
      localDayForInstant(
        start.iso,
        clinic.timezone
      );

    if (!localDay) {
      return {
        ok: false,
        error:
          "invalid_clinic_timezone"
      };
    }

    const identity =
      professional.id
      + "|"
      + start.iso;

    if (
      identities.has(
        identity
      )
    ) {
      return {
        ok: false,
        error:
          "duplicate_availability_slot"
      };
    }

    identities.add(
      identity
    );

    rows.push({
      id:
        `slot:${crypto.randomUUID()}`,

      professional_id:
        professional.id,

      start_time:
        start.iso,

      end_time:
        end.iso,

      local_day:
        localDay,

      available:
        item.available
          ? 1
          : 0,

      snapshot_version:
        snapshotVersion
    });
  }

  return {
    ok: true,

    value: {
      snapshot_version:
        snapshotVersion,

      rows
    }
  };
}


async function syncAvailability(
  request,
  env,
  auth
) {
  const clinicId =
    `license:${auth.licenseId}`;

  const clinic =
    await env.DB.prepare(
      `SELECT
         id,
         license_id,
         timezone,
         slot_minutes
       FROM clinics
       WHERE id = ?
         AND license_id = ?
       LIMIT 1`
    )
      .bind(
        clinicId,
        auth.licenseId
      )
      .first();

  if (!clinic) {
    return jsonResponse(
      {
        ok: false,
        error:
          "clinic_profile_not_synced"
      },
      409
    );
  }

  const syncState =
    await env.DB.prepare(
      `SELECT
         installation_id,
         last_availability_snapshot_version
       FROM sync_state
       WHERE clinic_id = ?
       LIMIT 1`
    )
      .bind(
        clinicId
      )
      .first();

  if (!syncState) {
    return jsonResponse(
      {
        ok: false,
        error:
          "clinic_profile_not_synced"
      },
      409
    );
  }

  if (
    syncState.installation_id !==
      auth.installationId
  ) {
    return jsonResponse(
      {
        ok: false,
        error:
          "clinic_installation_mismatch"
      },
      403
    );
  }

  const body =
    await readJsonBody(
      request,
      524288
    );

  if (!body.ok) {
    return jsonResponse(
      {
        ok: false,
        error: body.error
      },
      body.error ===
        "payload_too_large"
        ? 413
        : 400
    );
  }

  const professionalsResult =
    await env.DB.prepare(
      `SELECT
         id,
         local_professional_id,
         active
       FROM professionals
       WHERE clinic_id = ?`
    )
      .bind(
        clinicId
      )
      .all();

  const professionalMap =
    new Map();

  for (
    const row
    of professionalsResult.results || []
  ) {
    professionalMap.set(
      row.local_professional_id,
      row
    );
  }

  const normalized =
    normalizeSyncAvailability(
      body.value,
      clinic,
      professionalMap
    );

  if (!normalized.ok) {
    return jsonResponse(
      {
        ok: false,
        error:
          normalized.error
      },
      normalized.error ===
        "too_many_slots"
        ? 413
        : 400
    );
  }

  const {
    snapshot_version:
      snapshotVersion,

    rows
  } = normalized.value;

  const currentVersion =
    Number(
      syncState
        .last_availability_snapshot_version ||
      0
    );

  if (
    snapshotVersion <=
      currentVersion
  ) {
    return jsonResponse(
      {
        ok: false,
        error:
          "stale_availability_snapshot"
      },
      409
    );
  }

  const now =
    new Date().toISOString();

  const syncToken =
    crypto.randomUUID();

  /*
   * Three-statement atomic snapshot:
   *
   * 1. Claim the newer snapshot version.
   * 2. Remove the prior clinic snapshot,
   *    only if this write still owns the token.
   * 3. Insert the complete new snapshot from
   *    one JSON parameter via json_each().
   *
   * A stale concurrent request cannot delete
   * or insert rows because its token will not
   * match sync_state.
   */
  const statements = [
    env.DB.prepare(
      `UPDATE sync_state
       SET
         last_availability_snapshot_version = ?,
         last_availability_sync_token = ?,
         last_availability_sync_at = ?,
         updated_at = ?
       WHERE clinic_id = ?
         AND installation_id = ?
         AND last_availability_snapshot_version < ?`
    )
      .bind(
        snapshotVersion,
        syncToken,
        now,
        now,
        clinicId,
        auth.installationId,
        snapshotVersion
      ),

    env.DB.prepare(
      `DELETE FROM availability_slots
       WHERE clinic_id = ?
         AND EXISTS (
           SELECT 1
           FROM sync_state s
           WHERE s.clinic_id = ?
             AND s.installation_id = ?
             AND s.last_availability_sync_token = ?
             AND s.last_availability_snapshot_version = ?
         )`
    )
      .bind(
        clinicId,
        clinicId,
        auth.installationId,
        syncToken,
        snapshotVersion
      ),

    env.DB.prepare(
      `INSERT INTO availability_slots (
         id,
         clinic_id,
         professional_id,
         start_time,
         end_time,
         local_day,
         available,
         snapshot_version,
         synced_at
       )
       SELECT
         json_extract(value, '$.id'),
         ?,
         json_extract(value, '$.professional_id'),
         json_extract(value, '$.start_time'),
         json_extract(value, '$.end_time'),
         json_extract(value, '$.local_day'),
         CAST(
           json_extract(value, '$.available')
           AS INTEGER
         ),
         CAST(
           json_extract(value, '$.snapshot_version')
           AS INTEGER
         ),
         ?
       FROM json_each(?)
       WHERE EXISTS (
         SELECT 1
         FROM sync_state s
         WHERE s.clinic_id = ?
           AND s.installation_id = ?
           AND s.last_availability_sync_token = ?
           AND s.last_availability_snapshot_version = ?
       )`
    )
      .bind(
        clinicId,
        now,
        JSON.stringify(rows),
        clinicId,
        auth.installationId,
        syncToken,
        snapshotVersion
      )
  ];

  const results =
    await env.DB.batch(
      statements
    );

  const versionChanges =
    Number(
      results?.[0]?.meta?.changes ||
      0
    );

  if (
    versionChanges !== 1
  ) {
    return jsonResponse(
      {
        ok: false,
        error:
          "stale_availability_snapshot"
      },
      409
    );
  }

  return jsonResponse({
    ok: true,

    data: {
      snapshot_version:
        snapshotVersion,

      slots_received:
        rows.length,

      available:
        rows.filter(
          row =>
            row.available === 1
        ).length,

      last_synced_at:
        now
    }
  });
}



async function listPullableBookingRequests(
  env,
  clinicId
) {
  const result =
    await env.DB.prepare(
      `SELECT
         br.id,
         br.start_time,
         br.end_time,
         br.patient_ciphertext,
         br.patient_iv,
         br.patient_key_version,
         br.status,
         br.created_at,
         br.delivered_at,
         p.local_professional_id,
         p.public_slug AS professional_slug,
         p.display_name AS professional_name
       FROM booking_requests br
       JOIN professionals p
         ON p.id = br.professional_id
        AND p.clinic_id = br.clinic_id
       WHERE br.clinic_id = ?
         AND br.status IN (
           'pending',
           'delivered'
         )
       ORDER BY
         br.created_at ASC,
         br.id ASC
       LIMIT 100`
    )
      .bind(
        clinicId
      )
      .all();

  return (
    result.results || []
  );
}


async function listDeliveredBookingRequests(
  env,
  clinicId
) {
  const result =
    await env.DB.prepare(
      `SELECT
         br.id,
         br.start_time,
         br.end_time,
         br.patient_ciphertext,
         br.patient_iv,
         br.patient_key_version,
         br.status,
         br.created_at,
         br.delivered_at,
         p.local_professional_id,
         p.public_slug AS professional_slug,
         p.display_name AS professional_name
       FROM booking_requests br
       JOIN professionals p
         ON p.id = br.professional_id
        AND p.clinic_id = br.clinic_id
       WHERE br.clinic_id = ?
         AND br.status = 'delivered'
       ORDER BY
         br.created_at ASC,
         br.id ASC
       LIMIT 100`
    )
      .bind(
        clinicId
      )
      .all();

  return (
    result.results || []
  );
}


function bookingPayloadErrorResponse(
  error
) {
  if (
    error?.message ===
      "booking_key_missing" ||
    error?.message ===
      "booking_key_invalid" ||
    error?.message ===
      "booking_key_version_unsupported"
  ) {
    return jsonResponse(
      {
        ok: false,
        error:
          "service_configuration_error"
      },
      503
    );
  }

  if (
    error?.message ===
      "booking_payload_decryption_failed"
  ) {
    return jsonResponse(
      {
        ok: false,
        error:
          "booking_payload_unavailable"
      },
      500
    );
  }

  throw error;
}


async function pullBookingRequests(
  env,
  auth
) {
  /*
   * Tenant identity is never accepted
   * from the caller. It is derived from
   * the authenticated commercial lease.
   */
  const clinicId =
    `license:${auth.licenseId}`;

  const clinic =
    await env.DB.prepare(
      `SELECT
         id,
         license_id
       FROM clinics
       WHERE id = ?
         AND license_id = ?
       LIMIT 1`
    )
      .bind(
        clinicId,
        auth.licenseId
      )
      .first();

  if (!clinic) {
    return jsonResponse(
      {
        ok: false,
        error:
          "clinic_profile_not_synced"
      },
      409
    );
  }

  /*
   * Only the installation that owns
   * this clinic sync state may pull
   * patient booking requests.
   */
  const syncState =
    await env.DB.prepare(
      `SELECT
         installation_id
       FROM sync_state
       WHERE clinic_id = ?
       LIMIT 1`
    )
      .bind(
        clinicId
      )
      .first();

  if (!syncState) {
    return jsonResponse(
      {
        ok: false,
        error:
          "clinic_profile_not_synced"
      },
      409
    );
  }

  if (
    syncState.installation_id !==
      auth.installationId
  ) {
    return jsonResponse(
      {
        ok: false,
        error:
          "clinic_installation_mismatch"
      },
      403
    );
  }

  /*
   * Preflight decryption before changing
   * pending -> delivered.
   *
   * This prevents a missing/wrong cloud
   * encryption key from marking requests
   * delivered when no patient identity
   * could actually be delivered.
   */
  const candidates =
    await listPullableBookingRequests(
      env,
      clinicId
    );

  try {
    for (
      const row
      of candidates
    ) {
      await decryptPatientPayload(
        env,
        row
      );
    }
  } catch (error) {
    return bookingPayloadErrorResponse(
      error
    );
  }

  const now =
    new Date().toISOString();

  /*
   * At-least-once delivery:
   *
   * pending   -> delivered
   * delivered -> remains delivered and
   *              stays pullable
   *
   * A future result endpoint will move a
   * delivered request to accepted/rejected.
   * The guarded UPDATE must never overwrite
   * a request that is no longer pending.
   */
  const statements = [];

  for (
    const row
    of candidates
  ) {
    if (
      row.status !== "pending"
    ) {
      continue;
    }

    statements.push(
      env.DB.prepare(
        `UPDATE booking_requests
         SET
           status = 'delivered',
           delivered_at =
             COALESCE(
               delivered_at,
               ?
             ),
           updated_at = ?
         WHERE id = ?
           AND clinic_id = ?
           AND status = 'pending'`
      )
        .bind(
          now,
          now,
          row.id,
          clinicId
        )
    );
  }

  statements.push(
    env.DB.prepare(
      `UPDATE sync_state
       SET
         last_booking_pull_at = ?,
         updated_at = ?
       WHERE clinic_id = ?
         AND installation_id = ?`
    )
      .bind(
        now,
        now,
        clinicId,
        auth.installationId
      )
  );

  await env.DB.batch(
    statements
  );

  /*
   * Re-read only delivered rows after
   * the guarded transition. This avoids
   * returning accepted/rejected/cancelled
   * requests if their state changed.
   */
  const delivered =
    await listDeliveredBookingRequests(
      env,
      clinicId
    );

  const requests = [];

  try {
    for (
      const row
      of delivered
    ) {
      const patient =
        await decryptPatientPayload(
          env,
          row
        );

      requests.push({
        request_id:
          row.id,

        status:
          "delivered",

        local_professional_id:
          row.local_professional_id,

        professional_slug:
          row.professional_slug,

        professional_name:
          row.professional_name,

        start_time:
          row.start_time,

        end_time:
          row.end_time,

        patient,

        created_at:
          row.created_at,

        delivered_at:
          row.delivered_at ||
          now
      });
    }
  } catch (error) {
    return bookingPayloadErrorResponse(
      error
    );
  }

  return jsonResponse({
    ok: true,

    data: {
      requests,

      count:
        requests.length,

      pulled_at:
        now
    }
  });
}



function normalizeBookingResult(
  payload
) {
  if (
    !payload ||
    typeof payload !== "object" ||
    Array.isArray(payload)
  ) {
    return {
      ok: false,
      error: "invalid_payload"
    };
  }

  const allowed =
    new Set([
      "status",
      "local_appointment_id",
      "rejection_code"
    ]);

  for (
    const field
    of Object.keys(payload)
  ) {
    if (!allowed.has(field)) {
      return {
        ok: false,
        error: "unexpected_field"
      };
    }
  }

  const status =
    String(
      payload.status || ""
    )
      .trim()
      .toLowerCase();

  const hasLocalAppointmentId =
    Object.prototype.hasOwnProperty.call(
      payload,
      "local_appointment_id"
    );

  const hasRejectionCode =
    Object.prototype.hasOwnProperty.call(
      payload,
      "rejection_code"
    );

  if (status === "accepted") {
    if (
      !hasLocalAppointmentId ||
      hasRejectionCode
    ) {
      return {
        ok: false,
        error: "validation_error"
      };
    }

    const localAppointmentId =
      String(
        payload.local_appointment_id || ""
      ).trim();

    if (
      localAppointmentId.length < 1 ||
      localAppointmentId.length > 128
    ) {
      return {
        ok: false,
        error: "validation_error"
      };
    }

    return {
      ok: true,
      value: {
        status: "accepted",
        local_appointment_id:
          localAppointmentId,
        rejection_code: null
      }
    };
  }

  if (status === "rejected") {
    if (
      !hasRejectionCode ||
      hasLocalAppointmentId
    ) {
      return {
        ok: false,
        error: "validation_error"
      };
    }

    const rejectionCode =
      String(
        payload.rejection_code || ""
      )
        .trim()
        .toLowerCase();

    if (
      rejectionCode.length < 1 ||
      rejectionCode.length > 80 ||
      !/^[a-z0-9]+(?:_[a-z0-9]+)*$/.test(
        rejectionCode
      )
    ) {
      return {
        ok: false,
        error: "validation_error"
      };
    }

    return {
      ok: true,
      value: {
        status: "rejected",
        local_appointment_id: null,
        rejection_code:
          rejectionCode
      }
    };
  }

  return {
    ok: false,
    error: "invalid_result_status"
  };
}


async function getBookingRequestForResult(
  env,
  clinicId,
  requestId
) {
  return env.DB.prepare(
    `SELECT
       id,
       status,
       local_appointment_id,
       rejection_code,
       resolved_at
     FROM booking_requests
     WHERE id = ?
       AND clinic_id = ?
     LIMIT 1`
  )
    .bind(
      requestId,
      clinicId
    )
    .first();
}


function bookingResultData(
  row
) {
  const data = {
    request_id:
      row.id,

    status:
      row.status,

    resolved_at:
      row.resolved_at
  };

  if (
    row.status === "accepted"
  ) {
    data.local_appointment_id =
      row.local_appointment_id;
  }

  if (
    row.status === "rejected"
  ) {
    data.rejection_code =
      row.rejection_code;
  }

  return data;
}


function sameBookingResult(
  row,
  result
) {
  if (
    row.status !== result.status
  ) {
    return false;
  }

  if (
    result.status === "accepted"
  ) {
    return (
      row.local_appointment_id ===
        result.local_appointment_id
    );
  }

  if (
    result.status === "rejected"
  ) {
    return (
      row.rejection_code ===
        result.rejection_code
    );
  }

  return false;
}


function terminalBookingResultResponse(
  row,
  result
) {
  if (
    row.status === "accepted" ||
    row.status === "rejected"
  ) {
    if (
      sameBookingResult(
        row,
        result
      )
    ) {
      return jsonResponse({
        ok: true,
        data:
          bookingResultData(row)
      });
    }

    return jsonResponse(
      {
        ok: false,
        error:
          "booking_request_already_resolved"
      },
      409
    );
  }

  if (
    row.status === "pending"
  ) {
    return jsonResponse(
      {
        ok: false,
        error:
          "booking_request_not_delivered"
      },
      409
    );
  }

  return jsonResponse(
    {
      ok: false,
      error:
        "booking_request_not_resolvable"
    },
    409
  );
}


async function resolveBookingRequest(
  request,
  env,
  auth,
  requestId
) {
  const clinicId =
    `license:${auth.licenseId}`;

  /*
   * Tenant identity comes only from the
   * authenticated signed commercial lease.
   */
  const clinic =
    await env.DB.prepare(
      `SELECT
         id,
         license_id
       FROM clinics
       WHERE id = ?
         AND license_id = ?
       LIMIT 1`
    )
      .bind(
        clinicId,
        auth.licenseId
      )
      .first();

  if (!clinic) {
    return jsonResponse(
      {
        ok: false,
        error:
          "clinic_profile_not_synced"
      },
      409
    );
  }

  /*
   * The same installation that owns the
   * clinic sync state must resolve results.
   */
  const syncState =
    await env.DB.prepare(
      `SELECT
         installation_id
       FROM sync_state
       WHERE clinic_id = ?
       LIMIT 1`
    )
      .bind(
        clinicId
      )
      .first();

  if (!syncState) {
    return jsonResponse(
      {
        ok: false,
        error:
          "clinic_profile_not_synced"
      },
      409
    );
  }

  if (
    syncState.installation_id !==
      auth.installationId
  ) {
    return jsonResponse(
      {
        ok: false,
        error:
          "clinic_installation_mismatch"
      },
      403
    );
  }

  const body =
    await readJsonBody(request);

  if (!body.ok) {
    return jsonResponse(
      {
        ok: false,
        error:
          body.error
      },
      body.error ===
        "payload_too_large"
        ? 413
        : 400
    );
  }

  const normalized =
    normalizeBookingResult(
      body.value
    );

  if (!normalized.ok) {
    return jsonResponse(
      {
        ok: false,
        error:
          normalized.error
      },
      400
    );
  }

  const result =
    normalized.value;

  const existing =
    await getBookingRequestForResult(
      env,
      clinicId,
      requestId
    );

  /*
   * Query is scoped by clinic_id so a
   * request belonging to another tenant
   * is indistinguishable from not found.
   */
  if (!existing) {
    return notFound();
  }

  if (
    existing.status !== "delivered"
  ) {
    return terminalBookingResultResponse(
      existing,
      result
    );
  }

  const now =
    new Date().toISOString();

  /*
   * Only delivered may transition into
   * an authoritative clinic result.
   *
   * The status predicate protects against
   * concurrent or repeated resolution.
   */
  const update =
    await env.DB.prepare(
      `UPDATE booking_requests
       SET
         status = ?,
         local_appointment_id = ?,
         rejection_code = ?,
         resolved_at = ?,
         updated_at = ?
       WHERE id = ?
         AND clinic_id = ?
         AND status = 'delivered'`
    )
      .bind(
        result.status,
        result.local_appointment_id,
        result.rejection_code,
        now,
        now,
        requestId,
        clinicId
      )
      .run();

  const changes =
    Number(
      update?.meta?.changes || 0
    );

  if (changes === 1) {
    return jsonResponse({
      ok: true,
      data: {
        request_id:
          requestId,

        status:
          result.status,

        resolved_at:
          now,

        ...(
          result.status === "accepted"
            ? {
                local_appointment_id:
                  result.local_appointment_id
              }
            : {
                rejection_code:
                  result.rejection_code
              }
        )
      }
    });
  }

  /*
   * A concurrent resolver may have won
   * between SELECT and UPDATE. Re-read and
   * return an idempotent success only when
   * the exact same result already won.
   */
  const current =
    await getBookingRequestForResult(
      env,
      clinicId,
      requestId
    );

  if (!current) {
    return notFound();
  }

  return terminalBookingResultResponse(
    current,
    result
  );
}


function syncAuthErrorResponse(error) {
  if (
    error instanceof SyncAuthError
  ) {
    return jsonResponse(
      {
        ok: false,
        error: error.code
      },
      error.status
    );
  }

  throw error;
}


async function syncClinicProfile(
  request,
  env,
  auth
) {
  const body =
    await readJsonBody(request);

  if (!body.ok) {
    return jsonResponse(
      {
        ok: false,
        error: body.error
      },
      body.error ===
        "payload_too_large"
        ? 413
        : 400
    );
  }

  const normalized =
    normalizeSyncProfile(
      body.value
    );

  if (!normalized.ok) {
    return jsonResponse(
      {
        ok: false,
        error:
          normalized.error
      },
      400
    );
  }

  const profile =
    normalized.value;

  /*
   * Cloud clinic identity is derived
   * from the authenticated commercial
   * license. The client cannot choose
   * another internal clinic id.
   */
  const clinicId =
    `license:${auth.licenseId}`;

  const now =
    new Date().toISOString();

  try {
    await env.DB.prepare(
      `INSERT INTO clinics (
         id,
         license_id,
         public_slug,
         display_name,
         phone,
         email,
         timezone,
         currency,
         enabled,
         slot_minutes,
         days_ahead,
         last_synced_at,
         updated_at
       )
       VALUES (
         ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
       )
       ON CONFLICT(id)
       DO UPDATE SET
         public_slug =
           excluded.public_slug,
         display_name =
           excluded.display_name,
         phone =
           excluded.phone,
         email =
           excluded.email,
         timezone =
           excluded.timezone,
         currency =
           excluded.currency,
         enabled =
           excluded.enabled,
         slot_minutes =
           excluded.slot_minutes,
         days_ahead =
           excluded.days_ahead,
         last_synced_at =
           excluded.last_synced_at,
         updated_at =
           excluded.updated_at
       WHERE clinics.license_id =
         excluded.license_id`
    )
      .bind(
        clinicId,
        auth.licenseId,
        profile.public_slug,
        profile.display_name,
        profile.phone,
        profile.email,
        profile.timezone,
        profile.currency,
        profile.enabled
          ? 1
          : 0,
        profile.slot_minutes,
        profile.days_ahead,
        now,
        now
      )
      .run();
  } catch (error) {
    const message =
      String(
        error?.message || ""
      );

    if (
      message.includes(
        "UNIQUE"
      ) &&
      message.includes(
        "public_slug"
      )
    ) {
      return jsonResponse(
        {
          ok: false,
          error:
            "public_slug_unavailable"
        },
        409
      );
    }

    throw error;
  }

  await env.DB.prepare(
    `INSERT INTO sync_state (
       clinic_id,
       installation_id,
       last_profile_sync_at,
       updated_at
     )
     VALUES (?, ?, ?, ?)
     ON CONFLICT(clinic_id)
     DO UPDATE SET
       installation_id =
         excluded.installation_id,
       last_profile_sync_at =
         excluded.last_profile_sync_at,
       updated_at =
         excluded.updated_at`
  )
    .bind(
      clinicId,
      auth.installationId,
      now,
      now
    )
    .run();

  return jsonResponse({
    ok: true,
    data: {
      public_slug:
        profile.public_slug,

      display_name:
        profile.display_name,

      enabled:
        profile.enabled,

      last_synced_at:
        now
    }
  });
}


export default {
  async fetch(request, env) {
    const url =
      new URL(request.url);

    if (
      url.pathname === "/health"
    ) {
      if (request.method !== "GET") {
        return methodNotAllowed();
      }

      return jsonResponse({
        ok: true,
        service: "dentalpin-booking"
      });
    }

    if (!env.DB) {
      return jsonResponse(
        {
          ok: false,
          error: "database_unavailable"
        },
        503
      );
    }

    const parts =
      url.pathname
        .split("/")
        .filter(Boolean);

    if (
      parts.length === 4 &&
      parts[0] === "api" &&
      parts[1] === "v1" &&
      parts[2] === "sync" &&
      parts[3] === "profile"
    ) {
      if (
        request.method !== "PUT"
      ) {
        return methodNotAllowed();
      }

      let syncAuth;

      try {
        syncAuth =
          await authorizeBookingSync(
            request,
            env
          );
      } catch (error) {
        return syncAuthErrorResponse(
          error
        );
      }

      try {
        return await syncClinicProfile(
          request,
          env,
          syncAuth
        );
      } catch {
        return jsonResponse(
          {
            ok: false,
            error: "internal_error"
          },
          500
        );
      }
    }


    if (
      parts.length === 4 &&
      parts[0] === "api" &&
      parts[1] === "v1" &&
      parts[2] === "sync" &&
      parts[3] === "professionals"
    ) {
      if (
        request.method !== "PUT"
      ) {
        return methodNotAllowed();
      }

      let syncAuth;

      try {
        syncAuth =
          await authorizeBookingSync(
            request,
            env
          );
      } catch (error) {
        return syncAuthErrorResponse(
          error
        );
      }

      try {
        return await syncProfessionals(
          request,
          env,
          syncAuth
        );
      } catch {
        return jsonResponse(
          {
            ok: false,
            error: "internal_error"
          },
          500
        );
      }
    }


    if (
      parts.length === 4 &&
      parts[0] === "api" &&
      parts[1] === "v1" &&
      parts[2] === "sync" &&
      parts[3] === "availability"
    ) {
      if (
        request.method !== "PUT"
      ) {
        return methodNotAllowed();
      }

      let syncAuth;

      try {
        syncAuth =
          await authorizeBookingSync(
            request,
            env
          );
      } catch (error) {
        return syncAuthErrorResponse(
          error
        );
      }

      try {
        return await syncAvailability(
          request,
          env,
          syncAuth
        );
      } catch {
        return jsonResponse(
          {
            ok: false,
            error: "internal_error"
          },
          500
        );
      }
    }


    if (
      parts.length === 4 &&
      parts[0] === "api" &&
      parts[1] === "v1" &&
      parts[2] === "sync" &&
      parts[3] === "requests"
    ) {
      if (
        request.method !== "GET"
      ) {
        return methodNotAllowed();
      }

      let syncAuth;

      try {
        syncAuth =
          await authorizeBookingSync(
            request,
            env
          );
      } catch (error) {
        return syncAuthErrorResponse(
          error
        );
      }

      try {
        return await pullBookingRequests(
          env,
          syncAuth
        );
      } catch {
        return jsonResponse(
          {
            ok: false,
            error: "internal_error"
          },
          500
        );
      }
    }



    if (
      parts.length === 6 &&
      parts[0] === "api" &&
      parts[1] === "v1" &&
      parts[2] === "sync" &&
      parts[3] === "requests" &&
      parts[5] === "result"
    ) {
      if (
        request.method !== "POST"
      ) {
        return methodNotAllowed();
      }

      const requestId =
        String(
          parts[4] || ""
        ).trim();

      if (
        requestId.length < 1 ||
        requestId.length > 200
      ) {
        return notFound();
      }

      let syncAuth;

      try {
        syncAuth =
          await authorizeBookingSync(
            request,
            env
          );
      } catch (error) {
        return syncAuthErrorResponse(
          error
        );
      }

      try {
        return await resolveBookingRequest(
          request,
          env,
          syncAuth,
          requestId
        );
      } catch {
        return jsonResponse(
          {
            ok: false,
            error: "internal_error"
          },
          500
        );
      }
    }


    if (
      parts.length < 4 ||
      parts[0] !== "api" ||
      parts[1] !== "v1" ||
      parts[2] !== "public"
    ) {
      return notFound();
    }

    const clinicSlug =
      parts[3]
        .trim()
        .toLowerCase();

    if (
      !clinicSlug ||
      !validSlug(clinicSlug)
    ) {
      return notFound();
    }

    try {
      const clinic =
        await getPublicClinic(
          env,
          clinicSlug
        );

      if (!clinic) {
        return notFound();
      }

      if (
        request.method === "POST" &&
        parts.length === 5 &&
        parts[4] === "requests"
      ) {
        return createBookingRequest(
          request,
          env,
          clinic
        );
      }

      if (request.method !== "GET") {
        return methodNotAllowed();
      }

      if (parts.length === 4) {
        return jsonResponse({
          ok: true,
          data: {
            public_slug:
              clinic.public_slug,

            clinic_name:
              clinic.display_name,

            phone:
              clinic.phone,

            email:
              clinic.email,

            timezone:
              clinic.timezone,

            currency:
              clinic.currency,

            slot_minutes:
              clinic.slot_minutes,

            days_ahead:
              clinic.days_ahead,

            last_synced_at:
              clinic.last_synced_at
          }
        });
      }

      if (
        parts.length === 5 &&
        parts[4] ===
          "professionals"
      ) {
        const professionals =
          await listProfessionals(
            env,
            clinic.id
          );

        return jsonResponse({
          ok: true,
          data: professionals
        });
      }

      if (
        parts.length === 6 &&
        parts[4] ===
          "professionals"
      ) {
        const doctorSlug =
          parts[5]
            .trim()
            .toLowerCase();

        const professional =
          await getProfessional(
            env,
            clinic.id,
            doctorSlug
          );

        if (!professional) {
          return notFound();
        }

        return jsonResponse({
          ok: true,
          data: {
            public_slug:
              professional.public_slug,

            display_name:
              professional.display_name
          }
        });
      }

      if (
        parts.length === 7 &&
        parts[4] ===
          "professionals" &&
        parts[6] ===
          "slots"
      ) {
        const doctorSlug =
          parts[5]
            .trim()
            .toLowerCase();

        const day =
          (
            url.searchParams.get(
              "day"
            ) || ""
          ).trim();

        if (
          !/^\d{4}-\d{2}-\d{2}$/.test(
            day
          )
        ) {
          return jsonResponse(
            {
              ok: false,
              error: "invalid_day"
            },
            400
          );
        }

        const professional =
          await getProfessional(
            env,
            clinic.id,
            doctorSlug
          );

        if (!professional) {
          return notFound();
        }

        const slots =
          await listAvailableSlots(
            env,
            clinic.id,
            professional.id,
            day
          );

        return jsonResponse({
          ok: true,
          data: slots
        });
      }

      return notFound();
    } catch {
      return jsonResponse(
        {
          ok: false,
          error: "internal_error"
        },
        500
      );
    }
  }
};
