import test from "node:test";
import assert from "node:assert/strict";

import {
  generateKeyPairSync,
  sign as nodeSign,
  webcrypto
} from "node:crypto";

import { Buffer } from "node:buffer";

import worker from "../src/index.js";


if (!globalThis.crypto) {
  globalThis.crypto = webcrypto;
}

if (!globalThis.atob) {
  globalThis.atob = value =>
    Buffer.from(
      value,
      "base64"
    ).toString("binary");
}

if (!globalThis.btoa) {
  globalThis.btoa = value =>
    Buffer.from(
      value,
      "binary"
    ).toString("base64");
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


function defaultLeasePayload(
  overrides = {}
) {
  return {
    product: "dentora",
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


class FakeBookingStatement {
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
      this.sql.includes(
        "FROM clinics"
      )
    ) {
      const [
        publicSlug
      ] = this.params;

      const clinic =
        this.db.clinics.find(
          item =>
            item.public_slug ===
              publicSlug &&
            item.enabled === 1
        );

      if (!clinic) {
        return null;
      }

      return {
        id:
          clinic.id,

        public_slug:
          clinic.public_slug,

        display_name:
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
      };
    }

    throw new Error(
      "Unexpected booking DB first(): "
      + this.sql
    );
  }

  async run() {
    if (
      this.sql.includes(
        "INSERT INTO clinics"
      )
    ) {
      const [
        id,
        licenseId,
        publicSlug,
        displayName,
        phone,
        email,
        timezone,
        currency,
        enabled,
        slotMinutes,
        daysAhead,
        lastSyncedAt,
        updatedAt
      ] = this.params;

      const slugOwner =
        this.db.clinics.find(
          item =>
            item.public_slug ===
              publicSlug &&
            item.id !== id
        );

      if (slugOwner) {
        throw new Error(
          "UNIQUE constraint failed: clinics.public_slug"
        );
      }

      const existing =
        this.db.clinics.find(
          item =>
            item.id === id
        );

      if (existing) {
        if (
          existing.license_id ===
            licenseId
        ) {
          Object.assign(
            existing,
            {
              public_slug:
                publicSlug,

              display_name:
                displayName,

              phone,

              email,

              timezone,

              currency,

              enabled,

              slot_minutes:
                slotMinutes,

              days_ahead:
                daysAhead,

              last_synced_at:
                lastSyncedAt,

              updated_at:
                updatedAt
            }
          );
        }

        return {
          success: true
        };
      }

      this.db.clinics.push({
        id,
        license_id:
          licenseId,

        public_slug:
          publicSlug,

        display_name:
          displayName,

        phone,

        email,

        timezone,

        currency,

        enabled,

        slot_minutes:
          slotMinutes,

        days_ahead:
          daysAhead,

        last_synced_at:
          lastSyncedAt,

        updated_at:
          updatedAt
      });

      return {
        success: true
      };
    }

    if (
      this.sql.includes(
        "INSERT INTO sync_state"
      )
    ) {
      const [
        clinicId,
        installationId,
        lastProfileSyncAt,
        updatedAt
      ] = this.params;

      this.db.syncState.set(
        clinicId,
        {
          clinic_id:
            clinicId,

          installation_id:
            installationId,

          last_profile_sync_at:
            lastProfileSyncAt,

          updated_at:
            updatedAt
        }
      );

      return {
        success: true
      };
    }

    throw new Error(
      "Unexpected booking DB run(): "
      + this.sql
    );
  }

  async all() {
    throw new Error(
      "Unexpected booking DB all(): "
      + this.sql
    );
  }
}


class FakeBookingDB {
  constructor({
    clinics = []
  } = {}) {
    this.clinics =
      clinics.map(
        clinic => ({
          ...clinic
        })
      );

    this.syncState =
      new Map();
  }

  prepare(sql) {
    return new FakeBookingStatement(
      this,
      sql
    );
  }
}


function makeEnv({
  licenseRow =
    defaultLicenseRow(),

  clinics = []
} = {}) {
  const db =
    new FakeBookingDB({
      clinics
    });

  return {
    env: {
      DB: db,

      LICENSE_DB:
        new FakeLicenseDB(
          licenseRow
        ),

      LICENSE_PUBLIC_KEY_B64
    },

    db
  };
}


function profilePayload(
  overrides = {}
) {
  return {
    public_slug:
      "dental",

    display_name:
      "Dental Clinic",

    phone:
      "01000000000",

    email:
      "clinic@example.com",

    timezone:
      "Africa/Cairo",

    currency:
      "EGP",

    enabled:
      true,

    slot_minutes:
      30,

    days_ahead:
      30,

    ...overrides
  };
}


async function putProfile(
  env,
  {
    token =
      signLease(
        defaultLeasePayload()
      ),

    payload =
      profilePayload(),

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
      "https://booking.dentora.example/api/v1/sync/profile",
      {
        method: "PUT",
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
  "valid lease securely creates clinic profile",
  async () => {
    const {
      env,
      db
    } = makeEnv();

    const response =
      await putProfile(
        env
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
      body.ok,
      true
    );

    assert.equal(
      body.data.public_slug,
      "dental"
    );

    assert.equal(
      db.clinics.length,
      1
    );

    const clinic =
      db.clinics[0];

    assert.equal(
      clinic.id,
      "license:license-1"
    );

    assert.equal(
      clinic.license_id,
      "license-1"
    );

    const syncState =
      db.syncState.get(
        "license:license-1"
      );

    assert.equal(
      syncState.installation_id,
      "installation-1"
    );
  }
);


test(
  "profile sync without bearer returns 401",
  async () => {
    const {
      env,
      db
    } = makeEnv();

    const response =
      await putProfile(
        env,
        {
          includeAuthorization:
            false
        }
      );

    assert.equal(
      response.status,
      401
    );

    const body =
      await readJson(
        response
      );

    assert.equal(
      body.error,
      "sync_credential_required"
    );

    assert.equal(
      db.clinics.length,
      0
    );
  }
);


test(
  "profile sync is blocked when current license loses booking feature",
  async () => {
    const {
      env,
      db
    } = makeEnv({
      licenseRow:
        defaultLicenseRow({
          features_json:
            JSON.stringify([
              "core"
            ])
        })
    });

    const response =
      await putProfile(
        env
      );

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
      "booking_feature_not_enabled"
    );

    assert.equal(
      db.clinics.length,
      0
    );
  }
);


test(
  "repeated profile sync updates same cloud clinic",
  async () => {
    const {
      env,
      db
    } = makeEnv();

    const first =
      await putProfile(
        env
      );

    assert.equal(
      first.status,
      200
    );

    const second =
      await putProfile(
        env,
        {
          payload:
            profilePayload({
              display_name:
                "Dental Clinic Updated",

              phone:
                "01111111111",

              enabled:
                false,

              days_ahead:
                45
            })
        }
      );

    assert.equal(
      second.status,
      200
    );

    assert.equal(
      db.clinics.length,
      1
    );

    const clinic =
      db.clinics[0];

    assert.equal(
      clinic.display_name,
      "Dental Clinic Updated"
    );

    assert.equal(
      clinic.phone,
      "01111111111"
    );

    assert.equal(
      clinic.enabled,
      0
    );

    assert.equal(
      clinic.days_ahead,
      45
    );
  }
);


test(
  "public slug owned by another license returns 409",
  async () => {
    const {
      env,
      db
    } = makeEnv({
      clinics: [
        {
          id:
            "license:license-2",

          license_id:
            "license-2",

          public_slug:
            "dental",

          display_name:
            "Other Dental Clinic",

          phone:
            null,

          email:
            null,

          timezone:
            "Africa/Cairo",

          currency:
            "EGP",

          enabled:
            1,

          slot_minutes:
            30,

          days_ahead:
            30,

          last_synced_at:
            "2099-08-19T00:00:00Z",

          updated_at:
            "2099-08-19T00:00:00Z"
        }
      ]
    });

    const response =
      await putProfile(
        env
      );

    assert.equal(
      response.status,
      409
    );

    const body =
      await readJson(
        response
      );

    assert.equal(
      body.error,
      "public_slug_unavailable"
    );

    assert.equal(
      db.clinics.length,
      1
    );

    assert.equal(
      db.clinics[0].license_id,
      "license-2"
    );
  }
);


test(
  "internal license and installation identity are never public",
  async () => {
    const {
      env
    } = makeEnv();

    const syncResponse =
      await putProfile(
        env
      );

    assert.equal(
      syncResponse.status,
      200
    );

    const syncBody =
      await readJson(
        syncResponse
      );

    const syncText =
      JSON.stringify(
        syncBody
      );

    assert.equal(
      syncText.includes(
        "license_id"
      ),
      false
    );

    assert.equal(
      syncText.includes(
        "installation_id"
      ),
      false
    );

    assert.equal(
      syncText.includes(
        "fingerprint"
      ),
      false
    );

    const publicResponse =
      await worker.fetch(
        new Request(
          "https://booking.dentora.example/api/v1/public/dental"
        ),
        env
      );

    assert.equal(
      publicResponse.status,
      200
    );

    const publicBody =
      await readJson(
        publicResponse
      );

    const publicText =
      JSON.stringify(
        publicBody
      );

    assert.equal(
      publicText.includes(
        "license_id"
      ),
      false
    );

    assert.equal(
      publicText.includes(
        "installation_id"
      ),
      false
    );

    assert.equal(
      publicText.includes(
        "fingerprint"
      ),
      false
    );

    assert.equal(
      Object.hasOwn(
        publicBody.data,
        "id"
      ),
      false
    );
  }
);
