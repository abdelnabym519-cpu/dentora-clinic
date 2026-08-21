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
      "2099-01-01T00:00:00Z",

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
      "2099-01-01T00:00:00Z",

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
        "WHERE id = ?"
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

      if (!clinic) {
        return null;
      }

      return {
        id:
          clinic.id,

        license_id:
          clinic.license_id,

        timezone:
          clinic.timezone,

        slot_minutes:
          clinic.slot_minutes
      };
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

      if (!state) {
        return null;
      }

      return {
        installation_id:
          state.installation_id,

        last_availability_snapshot_version:
          state.last_availability_snapshot_version
      };
    }

    if (
      this.sql.includes(
        "FROM clinics"
      ) &&
      this.sql.includes(
        "public_slug = ?"
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

    if (
      this.sql.includes(
        "FROM professionals"
      ) &&
      this.sql.includes(
        "public_slug = ?"
      )
    ) {
      const [
        clinicId,
        publicSlug
      ] = this.params;

      const professional =
        this.db.professionals.find(
          item =>
            item.clinic_id ===
              clinicId &&
            item.public_slug ===
              publicSlug &&
            item.active === 1
        );

      if (!professional) {
        return null;
      }

      return {
        id:
          professional.id,

        public_slug:
          professional.public_slug,

        display_name:
          professional.display_name
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
      ) &&
      this.sql.includes(
        "local_professional_id"
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
                  clinicId
            )
            .map(
              item => ({
                id:
                  item.id,

                local_professional_id:
                  item.local_professional_id,

                active:
                  item.active
              })
            )
      };
    }

    if (
      this.sql.includes(
        "FROM availability_slots"
      )
    ) {
      const [
        clinicId,
        professionalId,
        localDay
      ] = this.params;

      const state =
        this.db.syncState.get(
          clinicId
        );

      const version =
        state
          ?.last_availability_snapshot_version;

      return {
        results:
          this.db.availabilitySlots
            .filter(
              item =>
                item.clinic_id ===
                  clinicId &&
                item.professional_id ===
                  professionalId &&
                item.local_day ===
                  localDay &&
                item.available === 1 &&
                item.snapshot_version ===
                  version
            )
            .sort(
              (a, b) =>
                a.start_time.localeCompare(
                  b.start_time
                )
            )
            .map(
              item => ({
                start_time:
                  item.start_time,

                end_time:
                  item.end_time
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
    throw new Error(
      "Unexpected run(): "
      + this.sql
    );
  }
}


class FakeBookingDB {
  constructor({
    installationId =
      "installation-1",

    snapshotVersion = 1,

    failInsert = false
  } = {}) {
    this.failInsert =
      failInsert;

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
          "2026-08-19T04:00:00Z"
      }
    ];

    this.professionals = [
      {
        id:
          "professional-1",

        clinic_id:
          "license:license-1",

        local_professional_id:
          "local-doctor-1",

        public_slug:
          "dr-ahmed-mahmoud",

        display_name:
          "د. أحمد محمود",

        active:
          1
      },

      {
        id:
          "professional-2",

        clinic_id:
          "license:license-1",

        local_professional_id:
          "local-doctor-2",

        public_slug:
          "dr-inactive",

        display_name:
          "د. غير متاح",

        active:
          0
      }
    ];

    this.syncState =
      new Map([
        [
          "license:license-1",
          {
            clinic_id:
              "license:license-1",

            installation_id:
              installationId,

            last_availability_sync_at:
              "2026-08-19T04:00:00Z",

            last_availability_snapshot_version:
              snapshotVersion,

            last_availability_sync_token:
              "old-token",

            updated_at:
              "2026-08-19T04:00:00Z"
          }
        ]
      ]);

    this.availabilitySlots = [
      {
        id:
          "old-slot-1",

        clinic_id:
          "license:license-1",

        professional_id:
          "professional-1",

        start_time:
          "2026-08-20T06:00:00.000Z",

        end_time:
          "2026-08-20T06:30:00.000Z",

        local_day:
          "2026-08-20",

        available:
          1,

        snapshot_version:
          snapshotVersion,

        synced_at:
          "2026-08-19T04:00:00Z"
      }
    ];
  }

  prepare(sql) {
    return new FakeBookingStatement(
      this,
      sql
    );
  }

  snapshot() {
    return {
      syncState:
        structuredClone(
          Array.from(
            this.syncState.entries()
          )
        ),

      availabilitySlots:
        structuredClone(
          this.availabilitySlots
        )
    };
  }

  restore(snapshot) {
    this.syncState =
      new Map(
        structuredClone(
          snapshot.syncState
        )
      );

    this.availabilitySlots =
      structuredClone(
        snapshot.availabilitySlots
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
          await this.applyBatchStatement(
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

  async applyBatchStatement(
    statement
  ) {
    const sql =
      statement.sql;

    const params =
      statement.params;

    if (
      sql.includes(
        "UPDATE sync_state"
      ) &&
      sql.includes(
        "last_availability_snapshot_version = ?"
      )
    ) {
      const [
        snapshotVersion,
        syncToken,
        syncedAt,
        updatedAt,
        clinicId,
        installationId,
        comparisonVersion
      ] = params;

      const state =
        this.syncState.get(
          clinicId
        );

      if (
        !state ||
        state.installation_id !==
          installationId ||
        !(
          state
            .last_availability_snapshot_version <
          comparisonVersion
        )
      ) {
        return {
          success: true,
          meta: {
            changes: 0
          }
        };
      }

      state
        .last_availability_snapshot_version =
          snapshotVersion;

      state
        .last_availability_sync_token =
          syncToken;

      state
        .last_availability_sync_at =
          syncedAt;

      state.updated_at =
        updatedAt;

      return {
        success: true,
        meta: {
          changes: 1
        }
      };
    }

    if (
      sql.includes(
        "DELETE FROM availability_slots"
      )
    ) {
      const [
        clinicId,
        stateClinicId,
        installationId,
        syncToken,
        snapshotVersion
      ] = params;

      const state =
        this.syncState.get(
          stateClinicId
        );

      if (
        state &&
        state.installation_id ===
          installationId &&
        state.last_availability_sync_token ===
          syncToken &&
        state
          .last_availability_snapshot_version ===
          snapshotVersion
      ) {
        const before =
          this.availabilitySlots.length;

        this.availabilitySlots =
          this.availabilitySlots.filter(
            item =>
              item.clinic_id !==
                clinicId
          );

        return {
          success: true,
          meta: {
            changes:
              before -
              this.availabilitySlots.length
          }
        };
      }

      return {
        success: true,
        meta: {
          changes: 0
        }
      };
    }

    if (
      sql.includes(
        "INSERT INTO availability_slots"
      )
    ) {
      if (
        this.failInsert
      ) {
        throw new Error(
          "simulated availability insert failure"
        );
      }

      const [
        clinicId,
        syncedAt,
        rowsJson,
        stateClinicId,
        installationId,
        syncToken,
        snapshotVersion
      ] = params;

      const state =
        this.syncState.get(
          stateClinicId
        );

      if (
        !state ||
        state.installation_id !==
          installationId ||
        state.last_availability_sync_token !==
          syncToken ||
        state
          .last_availability_snapshot_version !==
          snapshotVersion
      ) {
        return {
          success: true,
          meta: {
            changes: 0
          }
        };
      }

      const rows =
        JSON.parse(
          rowsJson
        );

      for (
        const row
        of rows
      ) {
        this.availabilitySlots.push({
          id:
            row.id,

          clinic_id:
            clinicId,

          professional_id:
            row.professional_id,

          start_time:
            row.start_time,

          end_time:
            row.end_time,

          local_day:
            row.local_day,

          available:
            row.available,

          snapshot_version:
            row.snapshot_version,

          synced_at:
            syncedAt
        });
      }

      return {
        success: true,
        meta: {
          changes:
            rows.length
        }
      };
    }

    throw new Error(
      "Unexpected batch statement: "
      + sql
    );
  }
}


function makeEnv(options = {}) {
  const db =
    new FakeBookingDB(
      options
    );

  return {
    env: {
      DB: db,

      LICENSE_DB:
        new FakeLicenseDB(
          licenseRow()
        ),

      LICENSE_PUBLIC_KEY_B64
    },

    db
  };
}


function slot({
  localProfessionalId =
    "local-doctor-1",

  start =
    "2026-08-20T10:00:00+03:00",

  end =
    "2026-08-20T10:30:00+03:00",

  available =
    true
} = {}) {
  return {
    local_professional_id:
      localProfessionalId,

    start_time:
      start,

    end_time:
      end,

    available
  };
}


async function putAvailability(
  env,
  payload,
  {
    token =
      signLease()
  } = {}
) {
  return worker.fetch(
    new Request(
      "https://booking.dentora.example/api/v1/sync/availability",
      {
        method: "PUT",

        headers: {
          "content-type":
            "application/json",

          authorization:
            `Bearer ${token}`
        },

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
  "valid availability snapshot canonicalizes UTC and computes Cairo local day",
  async () => {
    const {
      env,
      db
    } = makeEnv();

    const response =
      await putAvailability(
        env,
        {
          snapshot_version: 2,

          slots: [
            slot(),

            slot({
              start:
                "2026-08-20T22:30:00Z",

              end:
                "2026-08-20T23:00:00Z"
            })
          ]
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
      body.data.snapshot_version,
      2
    );

    assert.equal(
      body.data.slots_received,
      2
    );

    assert.equal(
      body.data.available,
      2
    );

    const state =
      db.syncState.get(
        "license:license-1"
      );

    assert.equal(
      state
        .last_availability_snapshot_version,
      2
    );

    assert.equal(
      db.availabilitySlots.length,
      2
    );

    const first =
      db.availabilitySlots.find(
        item =>
          item.start_time ===
            "2026-08-20T07:00:00.000Z"
      );

    assert.ok(first);

    assert.equal(
      first.local_day,
      "2026-08-20"
    );

    const boundary =
      db.availabilitySlots.find(
        item =>
          item.start_time ===
            "2026-08-20T22:30:00.000Z"
      );

    assert.ok(boundary);

    assert.equal(
      boundary.local_day,
      "2026-08-21"
    );
  }
);


test(
  "public API returns only current availability snapshot and hides internal metadata",
  async () => {
    const {
      env,
      db
    } = makeEnv();

    const response =
      await putAvailability(
        env,
        {
          snapshot_version: 2,

          slots: [
            slot({
              start:
                "2026-08-20T22:30:00Z",

              end:
                "2026-08-20T23:00:00Z"
            })
          ]
        }
      );

    assert.equal(
      response.status,
      200
    );

    /*
     * Simulate a stale leftover row.
     * Public reads must still ignore it.
     */
    db.availabilitySlots.push({
      id:
        "stale-ghost",

      clinic_id:
        "license:license-1",

      professional_id:
        "professional-1",

      start_time:
        "2026-08-20T23:30:00.000Z",

      end_time:
        "2026-08-21T00:00:00.000Z",

      local_day:
        "2026-08-21",

      available:
        1,

      snapshot_version:
        1,

      synced_at:
        "2026-08-19T04:00:00Z"
    });

    const publicResponse =
      await worker.fetch(
        new Request(
          "https://booking.dentora.example/api/v1/public/dental/professionals/dr-ahmed-mahmoud/slots?day=2026-08-21"
        ),
        env
      );

    assert.equal(
      publicResponse.status,
      200
    );

    const body =
      await readJson(
        publicResponse
      );

    assert.deepEqual(
      body.data,
      [
        {
          start_time:
            "2026-08-20T22:30:00.000Z",

          end_time:
            "2026-08-20T23:00:00.000Z"
        }
      ]
    );

    const text =
      JSON.stringify(
        body
      );

    assert.equal(
      text.includes(
        "local_day"
      ),
      false
    );

    assert.equal(
      text.includes(
        "snapshot_version"
      ),
      false
    );

    assert.equal(
      text.includes(
        "professional_id"
      ),
      false
    );

    assert.equal(
      text.includes(
        "stale-ghost"
      ),
      false
    );
  }
);


test(
  "stale availability snapshot is rejected without mutation",
  async () => {
    const {
      env,
      db
    } = makeEnv({
      snapshotVersion: 3
    });

    const before =
      db.snapshot();

    const response =
      await putAvailability(
        env,
        {
          snapshot_version: 2,

          slots: [
            slot()
          ]
        }
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
      "stale_availability_snapshot"
    );

    assert.deepEqual(
      db.snapshot(),
      before
    );
  }
);


test(
  "unknown professional is rejected before availability mutation",
  async () => {
    const {
      env,
      db
    } = makeEnv();

    const before =
      db.snapshot();

    const response =
      await putAvailability(
        env,
        {
          snapshot_version: 2,

          slots: [
            slot({
              localProfessionalId:
                "does-not-exist"
            })
          ]
        }
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
      "unknown_or_inactive_professional"
    );

    assert.deepEqual(
      db.snapshot(),
      before
    );
  }
);


test(
  "inactive professional is rejected before availability mutation",
  async () => {
    const {
      env,
      db
    } = makeEnv();

    const before =
      db.snapshot();

    const response =
      await putAvailability(
        env,
        {
          snapshot_version: 2,

          slots: [
            slot({
              localProfessionalId:
                "local-doctor-2"
            })
          ]
        }
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
      "unknown_or_inactive_professional"
    );

    assert.deepEqual(
      db.snapshot(),
      before
    );
  }
);


test(
  "slot duration must match clinic slot duration",
  async () => {
    const {
      env,
      db
    } = makeEnv();

    const before =
      db.snapshot();

    const response =
      await putAvailability(
        env,
        {
          snapshot_version: 2,

          slots: [
            slot({
              end:
                "2026-08-20T10:45:00+03:00"
            })
          ]
        }
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
      "invalid_slot_duration"
    );

    assert.deepEqual(
      db.snapshot(),
      before
    );
  }
);


test(
  "different installation cannot publish availability",
  async () => {
    const {
      env,
      db
    } = makeEnv({
      installationId:
        "another-installation"
    });

    const before =
      db.snapshot();

    const response =
      await putAvailability(
        env,
        {
          snapshot_version: 2,

          slots: [
            slot()
          ]
        }
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

    assert.deepEqual(
      db.snapshot(),
      before
    );
  }
);


test(
  "availability batch failure rolls back version token and slots",
  async () => {
    const {
      env,
      db
    } = makeEnv({
      failInsert: true
    });

    const before =
      db.snapshot();

    const response =
      await putAvailability(
        env,
        {
          snapshot_version: 2,

          slots: [
            slot()
          ]
        }
      );

    assert.equal(
      response.status,
      500
    );

    const body =
      await readJson(
        response
      );

    assert.equal(
      body.error,
      "internal_error"
    );

    assert.deepEqual(
      db.snapshot(),
      before
    );
  }
);
