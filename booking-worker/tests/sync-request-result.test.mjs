import test from "node:test";
import assert from "node:assert/strict";

import {
  generateKeyPairSync,
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
      ).toString("binary");
}

if (!globalThis.btoa) {
  globalThis.btoa =
    value =>
      Buffer.from(
        value,
        "binary"
      ).toString("base64");
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
  ).toString("base64");


function base64Url(
  value
) {
  return Buffer.from(
    value
  ).toString("base64url");
}


function leasePayload(
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
  payload =
    leasePayload()
) {
  const raw =
    Buffer.from(
      JSON.stringify(payload),
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
    + base64Url(signature)
  );
}


function licenseRow(
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

    if (
      !row ||
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
            ...clinic
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

    if (
      this.sql.includes(
        "FROM booking_requests"
      )
    ) {
      const [
        requestId,
        clinicId
      ] =
        this.params;

      const row =
        this.db.bookings.find(
          item =>
            item.id ===
              requestId &&
            item.clinic_id ===
              clinicId
        );

      return row
        ? {
            id:
              row.id,

            status:
              row.status,

            local_appointment_id:
              row.local_appointment_id,

            rejection_code:
              row.rejection_code,

            resolved_at:
              row.resolved_at
          }
        : null;
    }

    throw new Error(
      "Unexpected DB first(): "
      + this.sql
    );
  }

  async run() {
    if (
      !this.sql.includes(
        "UPDATE booking_requests"
      )
    ) {
      throw new Error(
        "Unexpected DB run(): "
        + this.sql
      );
    }

    const [
      status,
      localAppointmentId,
      rejectionCode,
      resolvedAt,
      updatedAt,
      requestId,
      clinicId
    ] =
      this.params;

    const row =
      this.db.bookings.find(
        item =>
          item.id ===
            requestId &&
          item.clinic_id ===
            clinicId
      );

    let changes = 0;

    if (
      row &&
      row.status === "delivered"
    ) {
      row.status =
        status;

      row.local_appointment_id =
        localAppointmentId;

      row.rejection_code =
        rejectionCode;

      row.resolved_at =
        resolvedAt;

      row.updated_at =
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
}


class FakeBookingDB {
  constructor({
    clinics = [],
    bookings = [],
    syncState = []
  } = {}) {
    this.clinics =
      clinics.map(
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
}


function booking(
  overrides = {}
) {
  return {
    id:
      "request-1",

    clinic_id:
      "license:license-1",

    status:
      "delivered",

    local_appointment_id:
      null,

    rejection_code:
      null,

    resolved_at:
      null,

    updated_at:
      "2099-08-20T06:00:00.000Z",

    ...overrides
  };
}


function makeFixture({
  syncInstallationId =
    "installation-1",

  bookings = [
    booking()
  ]
} = {}) {
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

      bookings,

      syncState: [
        {
          clinic_id:
            "license:license-1",

          installation_id:
            syncInstallationId
        }
      ]
    });

  return {
    db,

    env: {
      DB:
        db,

      LICENSE_DB:
        new FakeLicenseDB(
          licenseRow()
        ),

      LICENSE_PUBLIC_KEY_B64
    }
  };
}


async function postResult(
  env,
  {
    requestId =
      "request-1",

    payload = {
      status:
        "accepted",

      local_appointment_id:
        "appointment-1"
    },

    token =
      signLease(),

    includeAuthorization =
      true
  } = {}
) {
  const headers = {
    "content-type":
      "application/json"
  };

  if (
    includeAuthorization
  ) {
    headers.authorization =
      `Bearer ${token}`;
  }

  return worker.fetch(
    new Request(
      `https://booking.dentora.example/api/v1/sync/requests/${requestId}/result`,
      {
        method:
          "POST",

        headers,

        body:
          JSON.stringify(
            payload
          )
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
  "booking request result requires authenticated clinic sync credential",
  async () => {
    const response =
      await worker.fetch(
        new Request(
          "https://booking.dentora.example/api/v1/sync/requests/request-1/result",
          {
            method:
              "POST",

            headers: {
              "content-type":
                "application/json"
            },

            body:
              JSON.stringify({
                status:
                  "accepted",

                local_appointment_id:
                  "appointment-1"
              })
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

    assert.equal(
      (
        await readJson(response)
      ).error,
      "sync_credential_required"
    );
  }
);


test(
  "delivered request may be accepted with local appointment id",
  async () => {
    const {
      env,
      db
    } =
      makeFixture();

    const response =
      await postResult(env);

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
      body.data.status,
      "accepted"
    );

    assert.equal(
      body.data.local_appointment_id,
      "appointment-1"
    );

    assert.equal(
      db.bookings[0].status,
      "accepted"
    );

    assert.equal(
      db.bookings[0]
        .local_appointment_id,
      "appointment-1"
    );

    assert.equal(
      db.bookings[0]
        .rejection_code,
      null
    );

    assert.ok(
      db.bookings[0]
        .resolved_at
    );
  }
);


test(
  "delivered request may be rejected with rejection code",
  async () => {
    const {
      env,
      db
    } =
      makeFixture();

    const response =
      await postResult(
        env,
        {
          payload: {
            status:
              "rejected",

            rejection_code:
              "slot_unavailable"
          }
        }
      );

    assert.equal(
      response.status,
      200
    );

    const body =
      await readJson(
        response
      );

    assert.equal(
      body.data.status,
      "rejected"
    );

    assert.equal(
      body.data.rejection_code,
      "slot_unavailable"
    );

    assert.equal(
      db.bookings[0].status,
      "rejected"
    );

    assert.equal(
      db.bookings[0]
        .local_appointment_id,
      null
    );
  }
);


test(
  "accepted result requires local appointment id",
  async () => {
    const {
      env,
      db
    } =
      makeFixture();

    const response =
      await postResult(
        env,
        {
          payload: {
            status:
              "accepted"
          }
        }
      );

    assert.equal(
      response.status,
      400
    );

    assert.equal(
      (
        await readJson(response)
      ).error,
      "validation_error"
    );

    assert.equal(
      db.bookings[0].status,
      "delivered"
    );
  }
);


test(
  "pending request cannot be resolved before delivery",
  async () => {
    const {
      env,
      db
    } =
      makeFixture({
        bookings: [
          booking({
            status:
              "pending"
          })
        ]
      });

    const response =
      await postResult(env);

    assert.equal(
      response.status,
      409
    );

    assert.equal(
      (
        await readJson(response)
      ).error,
      "booking_request_not_delivered"
    );

    assert.equal(
      db.bookings[0].status,
      "pending"
    );
  }
);


test(
  "different installation cannot resolve booking result",
  async () => {
    const {
      env,
      db
    } =
      makeFixture({
        syncInstallationId:
          "different-installation"
      });

    const response =
      await postResult(env);

    assert.equal(
      response.status,
      403
    );

    assert.equal(
      (
        await readJson(response)
      ).error,
      "clinic_installation_mismatch"
    );

    assert.equal(
      db.bookings[0].status,
      "delivered"
    );
  }
);


test(
  "booking result is tenant isolated",
  async () => {
    const other =
      booking({
        id:
          "other-request",

        clinic_id:
          "license:license-2"
      });

    const {
      env,
      db
    } =
      makeFixture({
        bookings: [
          booking(),
          other
        ]
      });

    const response =
      await postResult(
        env,
        {
          requestId:
            "other-request"
        }
      );

    assert.equal(
      response.status,
      404
    );

    assert.equal(
      db.bookings[1].status,
      "delivered"
    );
  }
);


test(
  "same final result is idempotent",
  async () => {
    const resolvedAt =
      "2099-08-20T06:30:00.000Z";

    const {
      env
    } =
      makeFixture({
        bookings: [
          booking({
            status:
              "accepted",

            local_appointment_id:
              "appointment-1",

            resolved_at:
              resolvedAt
          })
        ]
      });

    const response =
      await postResult(env);

    assert.equal(
      response.status,
      200
    );

    const body =
      await readJson(
        response
      );

    assert.equal(
      body.data.status,
      "accepted"
    );

    assert.equal(
      body.data.local_appointment_id,
      "appointment-1"
    );

    assert.equal(
      body.data.resolved_at,
      resolvedAt
    );
  }
);


test(
  "conflicting retry cannot overwrite final result",
  async () => {
    const {
      env,
      db
    } =
      makeFixture({
        bookings: [
          booking({
            status:
              "accepted",

            local_appointment_id:
              "appointment-1",

            resolved_at:
              "2099-08-20T06:30:00.000Z"
          })
        ]
      });

    const response =
      await postResult(
        env,
        {
          payload: {
            status:
              "rejected",

            rejection_code:
              "slot_unavailable"
          }
        }
      );

    assert.equal(
      response.status,
      409
    );

    assert.equal(
      (
        await readJson(response)
      ).error,
      "booking_request_already_resolved"
    );

    assert.equal(
      db.bookings[0].status,
      "accepted"
    );

    assert.equal(
      db.bookings[0]
        .local_appointment_id,
      "appointment-1"
    );
  }
);
