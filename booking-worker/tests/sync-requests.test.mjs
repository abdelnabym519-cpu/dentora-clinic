import test from "node:test";
import assert from "node:assert/strict";

import {
  generateKeyPairSync,
  randomBytes,
  sign as nodeSign,
  webcrypto
} from "node:crypto";

import {
  Buffer
} from "node:buffer";

import worker from "../src/index.js";


if (!globalThis.crypto) {
  globalThis.crypto =
    webcrypto;
}

if (!globalThis.atob) {
  globalThis.atob =
    value =>
      Buffer.from(
        value,
        "base64"
      ).toString(
        "binary"
      );
}

if (!globalThis.btoa) {
  globalThis.btoa =
    value =>
      Buffer.from(
        value,
        "binary"
      ).toString(
        "base64"
      );
}


const {
  publicKey,
  privateKey
} =
  generateKeyPairSync(
    "ed25519"
  );


const PUBLIC_KEY_PEM =
  publicKey.export({
    type: "spki",
    format: "pem"
  });


const LICENSE_PUBLIC_KEY_B64 =
  Buffer.from(
    PUBLIC_KEY_PEM,
    "utf8"
  ).toString(
    "base64"
  );


const BOOKING_KEY_BYTES =
  randomBytes(32);


const BOOKING_PII_KEY_B64 =
  BOOKING_KEY_BYTES
    .toString(
      "base64"
    );


function base64Url(
  value
) {
  return Buffer.from(
    value
  ).toString(
    "base64url"
  );
}


function defaultLeasePayload(
  overrides = {}
) {
  return {
    product:
      "dentora",

    v: 1,

    license_id:
      "license-1",

    activation_id:
      "activation-1",

    installation_id:
      "installation-1",

    fingerprint:
      "fingerprint-1",

    features: [
      "core",
      "booking"
    ],

    valid_until:
      "2099-08-20T10:00:00Z",

    ...overrides
  };
}


function signLease(
  payload
) {
  const raw =
    Buffer.from(
      JSON.stringify(
        payload
      ),
      "utf8"
    );

  const signature =
    nodeSign(
      null,
      raw,
      privateKey
    );

  return (
    base64Url(raw)
    + "."
    + base64Url(
      signature
    )
  );
}


function defaultLicenseRow(
  overrides = {}
) {
  return {
    activation_id:
      "activation-1",

    license_id:
      "license-1",

    installation_id:
      "installation-1",

    fingerprint:
      "fingerprint-1",

    revoked_at:
      null,

    license_status:
      "active",

    license_expires_at:
      "2099-08-20T10:00:00Z",

    features_json:
      JSON.stringify([
        "core",
        "booking"
      ]),

    ...overrides
  };
}


class FakeLicenseStatement {
  constructor(
    db,
    sql
  ) {
    this.db = db;
    this.sql = sql;
    this.params = [];
  }

  bind(
    ...params
  ) {
    this.params =
      params;

    return this;
  }

  async first() {
    if (
      !this.sql.includes(
        "FROM activations a"
      )
    ) {
      throw new Error(
        "Unexpected LICENSE_DB query"
      );
    }

    const [
      activationId,
      licenseId
    ] =
      this.params;

    const row =
      this.db.row;

    if (!row) {
      return null;
    }

    if (
      row.activation_id !==
        activationId ||
      row.license_id !==
        licenseId
    ) {
      return null;
    }

    return {
      ...row
    };
  }
}


class FakeLicenseDB {
  constructor(
    row
  ) {
    this.row = row;
  }

  prepare(
    sql
  ) {
    return new FakeLicenseStatement(
      this,
      sql
    );
  }
}


class FakeBookingStatement {
  constructor(
    db,
    sql
  ) {
    this.db = db;
    this.sql = sql;
    this.params = [];
  }

  bind(
    ...params
  ) {
    this.params =
      params;

    return this;
  }

  async first() {
    if (
      this.sql.includes(
        "FROM clinics"
      )
    ) {
      const [
        clinicId,
        licenseId
      ] =
        this.params;

      const clinic =
        this.db.clinics.find(
          item =>
            item.id ===
              clinicId &&
            item.license_id ===
              licenseId
        );

      return clinic
        ? {
            id:
              clinic.id,

            license_id:
              clinic.license_id
          }
        : null;
    }

    if (
      this.sql.includes(
        "FROM sync_state"
      )
    ) {
      const [
        clinicId
      ] =
        this.params;

      const state =
        this.db.syncState.get(
          clinicId
        );

      return state
        ? {
            installation_id:
              state.installation_id
          }
        : null;
    }

    throw new Error(
      "Unexpected DB first(): "
      + this.sql
    );
  }

  async all() {
    if (
      !this.sql.includes(
        "FROM booking_requests br"
      )
    ) {
      throw new Error(
        "Unexpected DB all(): "
        + this.sql
      );
    }

    const [
      clinicId
    ] =
      this.params;

    const deliveredOnly =
      this.sql.includes(
        "br.status = 'delivered'"
      );

    const rows =
      this.db.bookings
        .filter(
          booking => {
            if (
              booking.clinic_id !==
                clinicId
            ) {
              return false;
            }

            if (deliveredOnly) {
              return (
                booking.status ===
                "delivered"
              );
            }

            return (
              booking.status ===
                "pending" ||
              booking.status ===
                "delivered"
            );
          }
        )
        .sort(
          (a, b) => {
            const created =
              String(
                a.created_at
              ).localeCompare(
                String(
                  b.created_at
                )
              );

            if (created !== 0) {
              return created;
            }

            return String(
              a.id
            ).localeCompare(
              String(
                b.id
              )
            );
          }
        )
        .slice(
          0,
          100
        )
        .map(
          booking => {
            const professional =
              this.db.professionals
                .find(
                  item =>
                    item.id ===
                      booking.professional_id &&
                    item.clinic_id ===
                      booking.clinic_id
                );

            if (!professional) {
              throw new Error(
                "Missing professional"
              );
            }

            return {
              id:
                booking.id,

              start_time:
                booking.start_time,

              end_time:
                booking.end_time,

              patient_ciphertext:
                booking.patient_ciphertext,

              patient_iv:
                booking.patient_iv,

              patient_key_version:
                booking.patient_key_version,

              status:
                booking.status,

              created_at:
                booking.created_at,

              delivered_at:
                booking.delivered_at,

              local_professional_id:
                professional
                  .local_professional_id,

              professional_slug:
                professional
                  .public_slug,

              professional_name:
                professional
                  .display_name
            };
          }
        );

    return {
      results:
        rows
    };
  }

  async run() {
    if (
      this.sql.includes(
        "UPDATE booking_requests"
      )
    ) {
      const [
        deliveredAt,
        updatedAt,
        requestId,
        clinicId
      ] =
        this.params;

      const booking =
        this.db.bookings.find(
          item =>
            item.id ===
              requestId &&
            item.clinic_id ===
              clinicId
        );

      let changes = 0;

      if (
        booking &&
        booking.status ===
          "pending"
      ) {
        booking.status =
          "delivered";

        booking.delivered_at =
          booking.delivered_at ||
          deliveredAt;

        booking.updated_at =
          updatedAt;

        changes = 1;
      }

      return {
        success: true,
        meta: {
          changes
        }
      };
    }

    if (
      this.sql.includes(
        "UPDATE sync_state"
      )
    ) {
      const [
        pulledAt,
        updatedAt,
        clinicId,
        installationId
      ] =
        this.params;

      const state =
        this.db.syncState.get(
          clinicId
        );

      let changes = 0;

      if (
        state &&
        state.installation_id ===
          installationId
      ) {
        state.last_booking_pull_at =
          pulledAt;

        state.updated_at =
          updatedAt;

        changes = 1;
      }

      return {
        success: true,
        meta: {
          changes
        }
      };
    }

    throw new Error(
      "Unexpected DB run(): "
      + this.sql
    );
  }
}


class FakeBookingDB {
  constructor({
    clinics = [],
    professionals = [],
    bookings = [],
    syncState = []
  } = {}) {
    this.clinics =
      clinics.map(
        item => ({
          ...item
        })
      );

    this.professionals =
      professionals.map(
        item => ({
          ...item
        })
      );

    this.bookings =
      bookings.map(
        item => ({
          ...item
        })
      );

    this.syncState =
      new Map(
        syncState.map(
          item => [
            item.clinic_id,
            {
              ...item
            }
          ]
        )
      );
  }

  prepare(
    sql
  ) {
    return new FakeBookingStatement(
      this,
      sql
    );
  }

  async batch(
    statements
  ) {
    const results = [];

    for (
      const statement
      of statements
    ) {
      results.push(
        await statement.run()
      );
    }

    return results;
  }
}


async function encryptPatient(
  payload
) {
  const key =
    await crypto.subtle.importKey(
      "raw",
      BOOKING_KEY_BYTES,
      {
        name:
          "AES-GCM"
      },
      false,
      [
        "encrypt"
      ]
    );

  const iv =
    crypto.getRandomValues(
      new Uint8Array(12)
    );

  const plaintext =
    new TextEncoder()
      .encode(
        JSON.stringify(
          payload
        )
      );

  const encrypted =
    await crypto.subtle.encrypt(
      {
        name:
          "AES-GCM",

        iv
      },
      key,
      plaintext
    );

  return {
    patient_ciphertext:
      Buffer.from(
        encrypted
      ).toString(
        "base64"
      ),

    patient_iv:
      Buffer.from(
        iv
      ).toString(
        "base64"
      ),

    patient_key_version:
      1
  };
}


async function makeBooking(
  overrides = {}
) {
  const encrypted =
    await encryptPatient({
      first_name:
        "Ahmed",

      last_name:
        "Ali",

      phone:
        "01000000000",

      date_of_birth:
        "1990-01-15",

      email:
        "ahmed@example.com"
    });

  return {
    id:
      "request-1",

    clinic_id:
      "license:license-1",

    professional_id:
      "professional-1",

    start_time:
      "2099-08-21T07:00:00.000Z",

    end_time:
      "2099-08-21T07:30:00.000Z",

    status:
      "pending",

    created_at:
      "2099-08-20T06:00:00.000Z",

    updated_at:
      "2099-08-20T06:00:00.000Z",

    delivered_at:
      null,

    ...encrypted,

    ...overrides
  };
}


async function makeFixture({
  syncInstallationId =
    "installation-1",

  includeBookingKey =
    true,

  extraBookings = []
} = {}) {
  const firstBooking =
    await makeBooking();

  const db =
    new FakeBookingDB({
      clinics: [
        {
          id:
            "license:license-1",

          license_id:
            "license-1"
        },

        {
          id:
            "license:license-2",

          license_id:
            "license-2"
        }
      ],

      professionals: [
        {
          id:
            "professional-1",

          clinic_id:
            "license:license-1",

          local_professional_id:
            "local-doctor-1",

          public_slug:
            "dr-ahmed",

          display_name:
            "د. أحمد"
        },

        {
          id:
            "professional-2",

          clinic_id:
            "license:license-2",

          local_professional_id:
            "other-doctor",

          public_slug:
            "dr-other",

          display_name:
            "Other Doctor"
        }
      ],

      bookings: [
        firstBooking,
        ...extraBookings
      ],

      syncState: [
        {
          clinic_id:
            "license:license-1",

          installation_id:
            syncInstallationId,

          last_booking_pull_at:
            null,

          updated_at:
            null
        }
      ]
    });

  const env = {
    DB:
      db,

    LICENSE_DB:
      new FakeLicenseDB(
        defaultLicenseRow()
      ),

    LICENSE_PUBLIC_KEY_B64
  };

  if (
    includeBookingKey
  ) {
    env.BOOKING_PII_KEY_B64 =
      BOOKING_PII_KEY_B64;
  }

  return {
    env,
    db
  };
}


async function pull(
  env,
  {
    token =
      signLease(
        defaultLeasePayload()
      ),

    includeAuthorization =
      true
  } = {}
) {
  const headers = {};

  if (
    includeAuthorization
  ) {
    headers.authorization =
      `Bearer ${token}`;
  }

  return worker.fetch(
    new Request(
      "https://booking.dentora.example/api/v1/sync/requests",
      {
        method:
          "GET",

        headers
      }
    ),
    env
  );
}


async function readJson(
  response
) {
  return JSON.parse(
    await response.text()
  );
}


test(
  "booking request pull requires authenticated clinic sync credential",
  async () => {
    const response =
      await worker.fetch(
        new Request(
          "https://booking.dentora.example/api/v1/sync/requests",
          {
            method:
              "GET"
          }
        ),
        {
          DB: {},
          LICENSE_DB: {}
        }
      );

    assert.equal(
      response.status,
      401
    );

    assert.deepEqual(
      await readJson(
        response
      ),
      {
        ok: false,
        error:
          "sync_credential_required"
      }
    );
  }
);


test(
  "authenticated clinic pulls pending and already delivered requests with transiently decrypted patient identity",
  async () => {
    const alreadyDelivered =
      await makeBooking({
        id:
          "request-2",

        status:
          "delivered",

        delivered_at:
          "2099-08-20T06:05:00.000Z",

        created_at:
          "2099-08-20T06:01:00.000Z"
      });

    const accepted =
      await makeBooking({
        id:
          "request-3",

        status:
          "accepted",

        created_at:
          "2099-08-20T06:02:00.000Z"
      });

    const {
      env,
      db
    } =
      await makeFixture({
        extraBookings: [
          alreadyDelivered,
          accepted
        ]
      });

    const response =
      await pull(env);

    assert.equal(
      response.status,
      200
    );

    const body =
      await readJson(
        response
      );

    assert.equal(
      body.ok,
      true
    );

    assert.equal(
      body.data.count,
      2
    );

    assert.deepEqual(
      body.data.requests.map(
        item =>
          item.request_id
      ),
      [
        "request-1",
        "request-2"
      ]
    );

    assert.equal(
      body.data.requests[0]
        .status,
      "delivered"
    );

    assert.equal(
      body.data.requests[0]
        .local_professional_id,
      "local-doctor-1"
    );

    assert.equal(
      body.data.requests[0]
        .patient.first_name,
      "Ahmed"
    );

    assert.equal(
      body.data.requests[0]
        .patient.phone,
      "01000000000"
    );

    const pending =
      db.bookings.find(
        item =>
          item.id ===
            "request-1"
      );

    assert.equal(
      pending.status,
      "delivered"
    );

    assert.ok(
      pending.delivered_at
    );

    const acceptedAfter =
      db.bookings.find(
        item =>
          item.id ===
            "request-3"
      );

    assert.equal(
      acceptedAfter.status,
      "accepted"
    );

    assert.ok(
      db.syncState
        .get(
          "license:license-1"
        )
        .last_booking_pull_at
    );
  }
);


test(
  "delivered booking remains pullable on retry",
  async () => {
    const {
      env
    } =
      await makeFixture();

    const first =
      await pull(env);

    assert.equal(
      first.status,
      200
    );

    const firstBody =
      await readJson(
        first
      );

    assert.equal(
      firstBody.data.count,
      1
    );

    const second =
      await pull(env);

    assert.equal(
      second.status,
      200
    );

    const secondBody =
      await readJson(
        second
      );

    assert.equal(
      secondBody.data.count,
      1
    );

    assert.equal(
      secondBody.data.requests[0]
        .request_id,
      "request-1"
    );

    assert.equal(
      secondBody.data.requests[0]
        .status,
      "delivered"
    );
  }
);


test(
  "clinic installation mismatch cannot pull or mutate booking requests",
  async () => {
    const {
      env,
      db
    } =
      await makeFixture({
        syncInstallationId:
          "different-installation"
      });

    const response =
      await pull(env);

    assert.equal(
      response.status,
      403
    );

    const body =
      await readJson(
        response
      );

    assert.equal(
      body.error,
      "clinic_installation_mismatch"
    );

    assert.equal(
      db.bookings[0].status,
      "pending"
    );
  }
);


test(
  "booking pull is tenant isolated and does not return another clinic request",
  async () => {
    const otherEncrypted =
      await encryptPatient({
        first_name:
          "Other",

        last_name:
          "Patient",

        phone:
          "01111111111",

        date_of_birth:
          "1991-02-10",

        email:
          null
      });

    const otherBooking = {
      id:
        "other-request",

      clinic_id:
        "license:license-2",

      professional_id:
        "professional-2",

      start_time:
        "2099-08-22T07:00:00.000Z",

      end_time:
        "2099-08-22T07:30:00.000Z",

      status:
        "delivered",

      created_at:
        "2099-08-20T05:00:00.000Z",

      updated_at:
        "2099-08-20T05:00:00.000Z",

      delivered_at:
        "2099-08-20T05:01:00.000Z",

      ...otherEncrypted
    };

    const {
      env
    } =
      await makeFixture({
        extraBookings: [
          otherBooking
        ]
      });

    const response =
      await pull(env);

    assert.equal(
      response.status,
      200
    );

    const body =
      await readJson(
        response
      );

    assert.deepEqual(
      body.data.requests.map(
        item =>
          item.request_id
      ),
      [
        "request-1"
      ]
    );
  }
);


test(
  "missing booking encryption key fails safely without marking pending request delivered",
  async () => {
    const {
      env,
      db
    } =
      await makeFixture({
        includeBookingKey:
          false
      });

    const response =
      await pull(env);

    assert.equal(
      response.status,
      503
    );

    const body =
      await readJson(
        response
      );

    assert.equal(
      body.error,
      "service_configuration_error"
    );

    assert.equal(
      db.bookings[0].status,
      "pending"
    );

    assert.equal(
      db.bookings[0]
        .delivered_at,
      null
    );
  }
);
