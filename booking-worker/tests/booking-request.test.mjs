import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { Buffer } from "node:buffer";

import worker from "../src/index.js";


if (!globalThis.crypto) {
  globalThis.crypto = webcrypto;
}

if (!globalThis.btoa) {
  globalThis.btoa = value =>
    Buffer.from(value, "binary").toString("base64");
}

if (!globalThis.atob) {
  globalThis.atob = value =>
    Buffer.from(value, "base64").toString("binary");
}


const START_TIME =
  "2099-08-20T10:00:00+03:00";

const END_TIME =
  "2099-08-20T10:30:00+03:00";


function makeKeyBase64() {
  const key = new Uint8Array(32);

  for (let i = 0; i < key.length; i += 1) {
    key[i] = i + 1;
  }

  return Buffer.from(key).toString("base64");
}


class FakeStatement {
  constructor(db, sql) {
    this.db = db;
    this.sql = sql;
    this.params = [];
  }

  bind(...params) {
    this.params = params;
    return this;
  }

  async first() {
    if (this.sql.includes("FROM clinics")) {
      const [slug] = this.params;

      if (slug !== "dental") {
        return null;
      }

      return {
        id: "clinic-1",
        public_slug: "dental",
        display_name: "Dental Clinic",
        phone: "01000000000",
        email: "clinic@example.com",
        timezone: "Africa/Cairo",
        currency: "EGP",
        slot_minutes: 30,
        days_ahead: 30,
        last_synced_at: "2099-08-19T05:00:00Z"
      };
    }

    if (this.sql.includes("FROM professionals")) {
      const [clinicId, doctorSlug] = this.params;

      if (
        clinicId === "clinic-1" &&
        doctorSlug === "dr-ahmed-mahmoud"
      ) {
        return {
          id: "professional-1",
          public_slug: "dr-ahmed-mahmoud",
          display_name: "د. أحمد محمود"
        };
      }

      return null;
    }

    if (this.sql.includes("FROM availability_slots")) {
      const [
        clinicId,
        professionalId,
        startTime
      ] = this.params;

      if (
        clinicId === "clinic-1" &&
        professionalId === "professional-1" &&
        startTime === START_TIME
      ) {
        return {
          start_time: START_TIME,
          end_time: END_TIME
        };
      }

      return null;
    }

    throw new Error(
      "Unexpected first() query: " + this.sql
    );
  }

  async all() {
    throw new Error(
      "Unexpected all() query: " + this.sql
    );
  }

  async run() {
    if (
      !this.sql.includes(
        "INSERT INTO booking_requests"
      )
    ) {
      throw new Error(
        "Unexpected run() query: " + this.sql
      );
    }

    const [
      id,
      clinicId,
      professionalId,
      startTime,
      endTime,
      patientCiphertext,
      patientIv,
      idempotencyKey,
      expiresAt
    ] = this.params;

    const duplicateSlot =
      this.db.bookingRequests.some(
        item =>
          item.professional_id === professionalId &&
          item.start_time === startTime &&
          [
            "pending",
            "delivered",
            "accepted"
          ].includes(item.status)
      );

    const duplicateIdempotency =
      this.db.bookingRequests.some(
        item =>
          item.idempotency_key === idempotencyKey
      );

    if (
      duplicateSlot ||
      duplicateIdempotency
    ) {
      throw new Error(
        "UNIQUE constraint failed: booking_requests"
      );
    }

    this.db.bookingRequests.push({
      id,
      clinic_id: clinicId,
      professional_id: professionalId,
      start_time: startTime,
      end_time: endTime,
      patient_ciphertext: patientCiphertext,
      patient_iv: patientIv,
      patient_key_version: 1,
      status: "pending",
      idempotency_key: idempotencyKey,
      expires_at: expiresAt
    });

    return {
      success: true
    };
  }
}


class FakeDB {
  constructor() {
    this.bookingRequests = [];
  }

  prepare(sql) {
    return new FakeStatement(
      this,
      sql
    );
  }
}


function makeEnv({
  withKey = true
} = {}) {
  const db = new FakeDB();

  const env = {
    DB: db
  };

  if (withKey) {
    env.BOOKING_PII_KEY_B64 =
      makeKeyBase64();
  }

  return {
    env,
    db
  };
}


function bookingPayload(extra = {}) {
  return {
    professional_slug:
      "dr-ahmed-mahmoud",

    start_time:
      START_TIME,

    first_name:
      "Ahmed",

    last_name:
      "Ali",

    phone:
      "01012345678",

    date_of_birth:
      "1990-01-01",

    email:
      "patient@example.com",

    ...extra
  };
}


async function postBooking(
  env,
  payload,
  idempotencyKey
) {
  const headers = {
    "content-type":
      "application/json"
  };

  if (idempotencyKey) {
    headers["idempotency-key"] =
      idempotencyKey;
  }

  return worker.fetch(
    new Request(
      "https://book.dentalpin.app/api/v1/public/dental/requests",
      {
        method: "POST",
        headers,
        body: JSON.stringify(payload)
      }
    ),
    env
  );
}


async function readJson(response) {
  return JSON.parse(
    await response.text()
  );
}


async function decryptStoredPatient(
  row,
  keyBase64
) {
  const rawKey =
    Buffer.from(
      keyBase64,
      "base64"
    );

  const key =
    await crypto.subtle.importKey(
      "raw",
      rawKey,
      {
        name: "AES-GCM"
      },
      false,
      [
        "decrypt"
      ]
    );

  const iv =
    Buffer.from(
      row.patient_iv,
      "base64"
    );

  const ciphertext =
    Buffer.from(
      row.patient_ciphertext,
      "base64"
    );

  const plaintext =
    await crypto.subtle.decrypt(
      {
        name: "AES-GCM",
        iv
      },
      key,
      ciphertext
    );

  return JSON.parse(
    new TextDecoder().decode(
      plaintext
    )
  );
}


test(
  "POST booking stores encrypted patient data and returns pending",
  async () => {
    const {
      env,
      db
    } = makeEnv();

    const response =
      await postBooking(
        env,
        bookingPayload(),
        "booking-test-1"
      );

    assert.equal(
      response.status,
      202
    );

    const body =
      await readJson(response);

    assert.equal(
      body.ok,
      true
    );

    assert.equal(
      body.data.status,
      "pending"
    );

    assert.equal(
      body.data.professional_slug,
      "dr-ahmed-mahmoud"
    );

    assert.equal(
      db.bookingRequests.length,
      1
    );

    const row =
      db.bookingRequests[0];

    assert.ok(
      row.patient_ciphertext
    );

    assert.ok(
      row.patient_iv
    );

    const storedText =
      JSON.stringify(row);

    assert.equal(
      storedText.includes("Ahmed"),
      false
    );

    assert.equal(
      storedText.includes("01012345678"),
      false
    );

    assert.equal(
      storedText.includes("patient@example.com"),
      false
    );

    const responseText =
      JSON.stringify(body);

    assert.equal(
      responseText.includes("Ahmed"),
      false
    );

    assert.equal(
      responseText.includes("01012345678"),
      false
    );

    assert.equal(
      responseText.includes("patient@example.com"),
      false
    );

    const decrypted =
      await decryptStoredPatient(
        row,
        env.BOOKING_PII_KEY_B64
      );

    assert.deepEqual(
      decrypted,
      {
        first_name:
          "Ahmed",

        last_name:
          "Ali",

        phone:
          "01012345678",

        date_of_birth:
          "1990-01-01",

        email:
          "patient@example.com"
      }
    );
  }
);


test(
  "duplicate active slot returns 409",
  async () => {
    const {
      env
    } = makeEnv();

    const first =
      await postBooking(
        env,
        bookingPayload(),
        "booking-dup-1"
      );

    assert.equal(
      first.status,
      202
    );

    const second =
      await postBooking(
        env,
        bookingPayload(),
        "booking-dup-2"
      );

    assert.equal(
      second.status,
      409
    );

    const body =
      await readJson(second);

    assert.equal(
      body.error,
      "slot_unavailable"
    );
  }
);


test(
  "medical reason is rejected by cloud booking",
  async () => {
    const {
      env,
      db
    } = makeEnv();

    const response =
      await postBooking(
        env,
        bookingPayload({
          reason:
            "Tooth pain"
        }),
        "booking-reason-1"
      );

    assert.equal(
      response.status,
      400
    );

    const body =
      await readJson(response);

    assert.equal(
      body.error,
      "medical_notes_not_allowed"
    );

    assert.equal(
      db.bookingRequests.length,
      0
    );
  }
);


test(
  "missing encryption key returns 503 and stores nothing",
  async () => {
    const {
      env,
      db
    } = makeEnv({
      withKey: false
    });

    const response =
      await postBooking(
        env,
        bookingPayload(),
        "booking-no-key-1"
      );

    assert.equal(
      response.status,
      503
    );

    const body =
      await readJson(response);

    assert.equal(
      body.error,
      "service_configuration_error"
    );

    assert.equal(
      db.bookingRequests.length,
      0
    );
  }
);


test(
  "unavailable slot returns 409 without storing PII",
  async () => {
    const {
      env,
      db
    } = makeEnv();

    const payload =
      bookingPayload({
        start_time:
          "2099-08-20T15:00:00+03:00"
      });

    const response =
      await postBooking(
        env,
        payload,
        "booking-bad-slot-1"
      );

    assert.equal(
      response.status,
      409
    );

    const body =
      await readJson(response);

    assert.equal(
      body.error,
      "slot_unavailable"
    );

    assert.equal(
      db.bookingRequests.length,
      0
    );
  }
);
