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


async function readJsonBody(request) {
  const declaredLength = Number(
    request.headers.get("content-length") || "0"
  );

  if (
    Number.isFinite(declaredLength) &&
    declaredLength > 16384
  ) {
    return {
      ok: false,
      error: "payload_too_large"
    };
  }

  const text = await request.text();

  if (text.length > 16384) {
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
  const dayStart =
    `${day}T00:00:00`;

  const dayEnd =
    `${day}T23:59:59`;

  const result = await env.DB.prepare(
    `SELECT
       start_time,
       end_time
     FROM availability_slots
     WHERE clinic_id = ?
       AND professional_id = ?
       AND available = 1
       AND start_time >= ?
       AND start_time <= ?
     ORDER BY start_time ASC`
  )
    .bind(
      clinicId,
      professionalId,
      dayStart,
      dayEnd
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
