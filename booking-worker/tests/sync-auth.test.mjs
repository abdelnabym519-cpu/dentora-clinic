import test from "node:test";
import assert from "node:assert/strict";

import {
  generateKeyPairSync,
  sign as nodeSign,
  webcrypto
} from "node:crypto";

import { Buffer } from "node:buffer";

import {
  authorizeBookingSync,
  SyncAuthError
} from "../src/sync-auth.js";


if (!globalThis.crypto) {
  globalThis.crypto = webcrypto;
}

if (!globalThis.atob) {
  globalThis.atob = value =>
    Buffer.from(value, "base64")
      .toString("binary");
}

if (!globalThis.btoa) {
  globalThis.btoa = value =>
    Buffer.from(value, "binary")
      .toString("base64");
}


const {
  publicKey,
  privateKey
} = generateKeyPairSync("ed25519");


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


function base64Url(value) {
  return Buffer.from(value)
    .toString("base64url");
}


function defaultPayload(overrides = {}) {
  return {
    product: "dentalpin",
    v: 1,

    license_id: "license-1",
    activation_id: "activation-1",
    installation_id: "installation-1",
    fingerprint: "fingerprint-1",

    features: [
      "core",
      "booking"
    ],

    valid_until:
      "2099-08-20T10:00:00Z",

    ...overrides
  };
}


function signLease(payload) {
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


function bearerRequest(token) {
  return new Request(
    "https://book.dentalpin.app/api/v1/sync/profile",
    {
      method: "PUT",
      headers: {
        authorization:
          `Bearer ${token}`
      }
    }
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
    if (
      !this.sql.includes(
        "FROM activations a"
      ) ||
      !this.sql.includes(
        "JOIN licenses l"
      )
    ) {
      throw new Error(
        "Unexpected LICENSE_DB query"
      );
    }

    const [
      activationId,
      licenseId
    ] = this.params;

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
  constructor(row) {
    this.row = row;
  }

  prepare(sql) {
    return new FakeLicenseStatement(
      this,
      sql
    );
  }
}


function makeEnv(row) {
  return {
    LICENSE_PUBLIC_KEY_B64,
    LICENSE_DB:
      new FakeLicenseDB(row)
  };
}


async function assertAuthError(
  promise,
  expectedStatus,
  expectedCode
) {
  await assert.rejects(
    promise,
    error => {
      assert.equal(
        error instanceof SyncAuthError,
        true
      );

      assert.equal(
        error.status,
        expectedStatus
      );

      assert.equal(
        error.code,
        expectedCode
      );

      return true;
    }
  );
}


test(
  "valid signed booking lease is authorized",
  async () => {
    const payload =
      defaultPayload();

    const token =
      signLease(payload);

    const result =
      await authorizeBookingSync(
        bearerRequest(token),
        makeEnv(
          defaultLicenseRow()
        )
      );

    assert.deepEqual(
      result,
      {
        licenseId:
          "license-1",

        activationId:
          "activation-1",

        installationId:
          "installation-1",

        fingerprint:
          "fingerprint-1"
      }
    );
  }
);


test(
  "tampered lease signature is rejected",
  async () => {
    const original =
      defaultPayload();

    const token =
      signLease(original);

    const [
      payloadPart,
      signaturePart
    ] = token.split(".");

    const tamperedPayload =
      base64Url(
        Buffer.from(
          JSON.stringify({
            ...original,
            installation_id:
              "attacker-installation"
          })
        )
      );

    const tamperedToken =
      tamperedPayload
      + "."
      + signaturePart;

    await assertAuthError(
      authorizeBookingSync(
        bearerRequest(
          tamperedToken
        ),
        makeEnv(
          defaultLicenseRow()
        )
      ),
      401,
      "invalid_sync_credential"
    );

    assert.notEqual(
      tamperedPayload,
      payloadPart
    );
  }
);


test(
  "expired signed lease is rejected",
  async () => {
    const token =
      signLease(
        defaultPayload({
          valid_until:
            "2000-01-01T00:00:00Z"
        })
      );

    await assertAuthError(
      authorizeBookingSync(
        bearerRequest(token),
        makeEnv(
          defaultLicenseRow()
        )
      ),
      401,
      "sync_credential_expired"
    );
  }
);


test(
  "revoked activation is rejected",
  async () => {
    const token =
      signLease(
        defaultPayload()
      );

    await assertAuthError(
      authorizeBookingSync(
        bearerRequest(token),
        makeEnv(
          defaultLicenseRow({
            revoked_at:
              "2026-08-19T04:00:00Z"
          })
        )
      ),
      403,
      "activation_revoked"
    );
  }
);


test(
  "installation fingerprint mismatch is rejected",
  async () => {
    const token =
      signLease(
        defaultPayload({
          fingerprint:
            "wrong-fingerprint"
        })
      );

    await assertAuthError(
      authorizeBookingSync(
        bearerRequest(token),
        makeEnv(
          defaultLicenseRow()
        )
      ),
      401,
      "activation_identity_mismatch"
    );
  }
);


test(
  "lease without booking entitlement is rejected",
  async () => {
    const token =
      signLease(
        defaultPayload({
          features: [
            "core"
          ]
        })
      );

    await assertAuthError(
      authorizeBookingSync(
        bearerRequest(token),
        makeEnv(
          defaultLicenseRow()
        )
      ),
      403,
      "booking_feature_not_enabled"
    );
  }
);


test(
  "current license without booking entitlement is rejected",
  async () => {
    const token =
      signLease(
        defaultPayload()
      );

    await assertAuthError(
      authorizeBookingSync(
        bearerRequest(token),
        makeEnv(
          defaultLicenseRow({
            features_json:
              JSON.stringify([
                "core"
              ])
          })
        )
      ),
      403,
      "booking_feature_not_enabled"
    );
  }
);
