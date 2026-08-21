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


const LICENSE_PUBLIC_KEY_B64 =
  Buffer.from(
    publicKey.export({
      type: "spki",
      format: "pem"
    }),
    "utf8"
  ).toString("base64");


function base64Url(value) {
  return Buffer.from(value)
    .toString("base64url");
}


function leasePayload(
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


function signLease(
  payload = leasePayload()
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
      ) &&
      this.sql.includes(
        "license_id"
      )
    ) {
      const [
        clinicId,
        licenseId
      ] = this.params;

      const clinic =
        this.db.clinics.find(
          item =>
            item.id === clinicId &&
            item.license_id ===
              licenseId
        );

      return clinic
        ? {
            id: clinic.id,
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
      ] = this.params;

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
      "Unexpected first(): "
      + this.sql
    );
  }

  async all() {
    if (
      this.sql.includes(
        "FROM professionals"
      )
    ) {
      const [
        clinicId
      ] = this.params;

      return {
        results:
          this.db.professionals
            .filter(
              item =>
                item.clinic_id ===
                  clinicId &&
                item.active === 1
            )
            .sort(
              (a, b) =>
                a.display_name.localeCompare(
                  b.display_name
                )
            )
            .map(
              item => ({
                public_slug:
                  item.public_slug,

                display_name:
                  item.display_name
              })
            )
      };
    }

    throw new Error(
      "Unexpected all(): "
      + this.sql
    );
  }

  async run() {
    return this.db.applyStatement(
      this
    );
  }
}


class FakeBookingDB {
  constructor({
    installationId =
      "installation-1"
  } = {}) {
    this.clinics = [
      {
        id:
          "license:license-1",

        license_id:
          "license-1",

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
          1,

        slot_minutes:
          30,

        days_ahead:
          30,

        last_synced_at:
          "2099-08-19T00:00:00Z"
      }
    ];

    this.professionals = [];

    this.syncState =
      new Map([
        [
          "license:license-1",
          {
            clinic_id:
              "license:license-1",

            installation_id:
              installationId,

            last_professionals_sync_at:
              null,

            updated_at:
              null
          }
        ]
      ]);
  }

  prepare(sql) {
    return new FakeBookingStatement(
      this,
      sql
    );
  }

  snapshot() {
    return {
      professionals:
        structuredClone(
          this.professionals
        ),

      syncState:
        structuredClone(
          Array.from(
            this.syncState.entries()
          )
        )
    };
  }

  restore(snapshot) {
    this.professionals =
      structuredClone(
        snapshot.professionals
      );

    this.syncState =
      new Map(
        structuredClone(
          snapshot.syncState
        )
      );
  }

  async batch(statements) {
    const before =
      this.snapshot();

    try {
      const results = [];

      for (
        const statement
        of statements
      ) {
        results.push(
          await this.applyStatement(
            statement
          )
        );
      }

      return results;
    } catch (error) {
      this.restore(
        before
      );

      throw error;
    }
  }

  async applyStatement(statement) {
    const sql =
      statement.sql;

    const params =
      statement.params;

    if (
      sql.includes(
        "UPDATE professionals"
      ) &&
      sql.includes(
        "active = 0"
      )
    ) {
      const [
        updatedAt,
        clinicId
      ] = params;

      for (
        const item
        of this.professionals
      ) {
        if (
          item.clinic_id ===
            clinicId
        ) {
          item.active = 0;
          item.updated_at =
            updatedAt;
        }
      }

      return {
        success: true
      };
    }

    if (
      sql.includes(
        "INSERT INTO professionals"
      )
    ) {
      const [
        id,
        clinicId,
        localProfessionalId,
        publicSlug,
        displayName,
        active,
        updatedAt
      ] = params;

      const existing =
        this.professionals.find(
          item =>
            item.clinic_id ===
              clinicId &&
            item.local_professional_id ===
              localProfessionalId
        );

      const slugOwner =
        this.professionals.find(
          item =>
            item.clinic_id ===
              clinicId &&
            item.public_slug ===
              publicSlug &&
            (
              !existing ||
              item.id !== existing.id
            )
        );

      if (slugOwner) {
        throw new Error(
          "UNIQUE constraint failed: professionals.clinic_id, professionals.public_slug"
        );
      }

      if (existing) {
        existing.public_slug =
          publicSlug;

        existing.display_name =
          displayName;

        existing.active =
          active;

        existing.updated_at =
          updatedAt;

        return {
          success: true
        };
      }

      const duplicateLocal =
        this.professionals.find(
          item =>
            item.clinic_id ===
              clinicId &&
            item.local_professional_id ===
              localProfessionalId
        );

      if (duplicateLocal) {
        throw new Error(
          "UNIQUE constraint failed: professionals.clinic_id, professionals.local_professional_id"
        );
      }

      this.professionals.push({
        id,

        clinic_id:
          clinicId,

        local_professional_id:
          localProfessionalId,

        public_slug:
          publicSlug,

        display_name:
          displayName,

        active,

        updated_at:
          updatedAt
      });

      return {
        success: true
      };
    }

    if (
      sql.includes(
        "UPDATE sync_state"
      )
    ) {
      const [
        lastSyncAt,
        updatedAt,
        clinicId,
        installationId
      ] = params;

      const current =
        this.syncState.get(
          clinicId
        );

      if (
        current &&
        current.installation_id ===
          installationId
      ) {
        current.last_professionals_sync_at =
          lastSyncAt;

        current.updated_at =
          updatedAt;
      }

      return {
        success: true
      };
    }

    throw new Error(
      "Unexpected batch statement: "
      + sql
    );
  }
}


function makeEnv({
  installationId =
    "installation-1",

  currentLicense =
    licenseRow()
} = {}) {
  const db =
    new FakeBookingDB({
      installationId
    });

  return {
    env: {
      DB: db,

      LICENSE_DB:
        new FakeLicenseDB(
          currentLicense
        ),

      LICENSE_PUBLIC_KEY_B64
    },

    db
  };
}


function doctor({
  localId =
    "local-doctor-1",

  slug =
    "dr-ahmed-mahmoud",

  name =
    "د. أحمد محمود",

  active =
    true
} = {}) {
  return {
    local_professional_id:
      localId,

    public_slug:
      slug,

    display_name:
      name,

    active
  };
}


async function putProfessionals(
  env,
  professionals,
  {
    token =
      signLease()
  } = {}
) {
  return worker.fetch(
    new Request(
      "https://booking.dentora.example/api/v1/sync/professionals",
      {
        method: "PUT",

        headers: {
          "content-type":
            "application/json",

          authorization:
            `Bearer ${token}`
        },

        body:
          JSON.stringify({
            professionals
          })
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
  "valid snapshot creates professionals and public API hides internal ids",
  async () => {
    const {
      env,
      db
    } = makeEnv();

    const response =
      await putProfessionals(
        env,
        [
          doctor(),

          doctor({
            localId:
              "local-doctor-2",

            slug:
              "dr-sara-ali",

            name:
              "د. سارة علي"
          })
        ]
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
      body.data.synced,
      2
    );

    assert.equal(
      body.data.active,
      2
    );

    assert.equal(
      db.professionals.length,
      2
    );

    const publicResponse =
      await worker.fetch(
        new Request(
          "https://booking.dentora.example/api/v1/public/dental/professionals"
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

    assert.equal(
      publicBody.data.length,
      2
    );

    const text =
      JSON.stringify(
        publicBody
      );

    assert.equal(
      text.includes(
        "local_professional_id"
      ),
      false
    );

    assert.equal(
      text.includes(
        "local-doctor-1"
      ),
      false
    );

    for (
      const item
      of publicBody.data
    ) {
      assert.equal(
        Object.hasOwn(
          item,
          "id"
        ),
        false
      );

      assert.equal(
        Object.hasOwn(
          item,
          "clinic_id"
        ),
        false
      );
    }
  }
);


test(
  "same local professional id updates existing cloud row without duplicate",
  async () => {
    const {
      env,
      db
    } = makeEnv();

    const first =
      await putProfessionals(
        env,
        [
          doctor()
        ]
      );

    assert.equal(
      first.status,
      200
    );

    const originalId =
      db.professionals[0].id;

    const second =
      await putProfessionals(
        env,
        [
          doctor({
            slug:
              "dr-ahmed-updated",

            name:
              "د. أحمد محمود - محدث"
          })
        ]
      );

    assert.equal(
      second.status,
      200
    );

    assert.equal(
      db.professionals.length,
      1
    );

    assert.equal(
      db.professionals[0].id,
      originalId
    );

    assert.equal(
      db.professionals[0].public_slug,
      "dr-ahmed-updated"
    );

    assert.equal(
      db.professionals[0].display_name,
      "د. أحمد محمود - محدث"
    );

    assert.equal(
      db.professionals[0].active,
      1
    );
  }
);


test(
  "professional omitted from next snapshot becomes inactive",
  async () => {
    const {
      env,
      db
    } = makeEnv();

    const first =
      await putProfessionals(
        env,
        [
          doctor(),

          doctor({
            localId:
              "local-doctor-2",

            slug:
              "dr-sara-ali",

            name:
              "د. سارة علي"
          })
        ]
      );

    assert.equal(
      first.status,
      200
    );

    const second =
      await putProfessionals(
        env,
        [
          doctor()
        ]
      );

    assert.equal(
      second.status,
      200
    );

    assert.equal(
      db.professionals.length,
      2
    );

    const omitted =
      db.professionals.find(
        item =>
          item.local_professional_id ===
            "local-doctor-2"
      );

    assert.equal(
      omitted.active,
      0
    );

    const publicResponse =
      await worker.fetch(
        new Request(
          "https://booking.dentora.example/api/v1/public/dental/professionals"
        ),
        env
      );

    const publicBody =
      await readJson(
        publicResponse
      );

    assert.equal(
      publicBody.data.length,
      1
    );

    assert.equal(
      publicBody.data[0].public_slug,
      "dr-ahmed-mahmoud"
    );
  }
);


test(
  "duplicate local professional id in snapshot is rejected before mutation",
  async () => {
    const {
      env,
      db
    } = makeEnv();

    const response =
      await putProfessionals(
        env,
        [
          doctor(),

          doctor({
            localId:
              "local-doctor-1",

            slug:
              "dr-other",

            name:
              "د. طبيب آخر"
          })
        ]
      );

    assert.equal(
      response.status,
      400
    );

    const body =
      await readJson(
        response
      );

    assert.equal(
      body.error,
      "duplicate_local_professional_id"
    );

    assert.equal(
      db.professionals.length,
      0
    );
  }
);


test(
  "duplicate professional slug in snapshot is rejected before mutation",
  async () => {
    const {
      env,
      db
    } = makeEnv();

    const response =
      await putProfessionals(
        env,
        [
          doctor(),

          doctor({
            localId:
              "local-doctor-2",

            slug:
              "dr-ahmed-mahmoud",

            name:
              "د. طبيب آخر"
          })
        ]
      );

    assert.equal(
      response.status,
      400
    );

    const body =
      await readJson(
        response
      );

    assert.equal(
      body.error,
      "duplicate_professional_slug"
    );

    assert.equal(
      db.professionals.length,
      0
    );
  }
);


test(
  "different installation cannot publish professionals",
  async () => {
    const {
      env,
      db
    } = makeEnv({
      installationId:
        "another-installation"
    });

    const response =
      await putProfessionals(
        env,
        [
          doctor()
        ]
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
      "clinic_installation_mismatch"
    );

    assert.equal(
      db.professionals.length,
      0
    );
  }
);


test(
  "database identity conflict returns 409 and snapshot batch rolls back",
  async () => {
    const {
      env,
      db
    } = makeEnv();

    const first =
      await putProfessionals(
        env,
        [
          doctor(),

          doctor({
            localId:
              "local-doctor-2",

            slug:
              "dr-sara-ali",

            name:
              "د. سارة علي"
          })
        ]
      );

    assert.equal(
      first.status,
      200
    );

    const before =
      structuredClone(
        db.professionals
      );

    const conflict =
      await putProfessionals(
        env,
        [
          doctor({
            slug:
              "dr-sara-ali",

            name:
              "د. أحمد باسم متعارض"
          })
        ]
      );

    assert.equal(
      conflict.status,
      409
    );

    const body =
      await readJson(
        conflict
      );

    assert.equal(
      body.error,
      "professional_identity_conflict"
    );

    /*
     * The initial UPDATE active=0 must
     * also have rolled back.
     */
    assert.deepEqual(
      db.professionals,
      before
    );

    assert.equal(
      db.professionals.every(
        item =>
          item.active === 1
      ),
      true
    );
  }
);
