PRAGMA foreign_keys = ON;

CREATE TABLE clinics (
    id TEXT PRIMARY KEY,
    license_id TEXT NOT NULL,

    public_slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,

    phone TEXT,
    email TEXT,

    timezone TEXT NOT NULL DEFAULT 'Africa/Cairo',
    currency TEXT NOT NULL DEFAULT 'EGP',

    enabled INTEGER NOT NULL DEFAULT 0
        CHECK (enabled IN (0, 1)),

    slot_minutes INTEGER NOT NULL DEFAULT 30,
    days_ahead INTEGER NOT NULL DEFAULT 30,

    last_synced_at TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_clinics_license
    ON clinics(license_id);

CREATE INDEX idx_clinics_public
    ON clinics(enabled, public_slug);


CREATE TABLE professionals (
    id TEXT PRIMARY KEY,

    clinic_id TEXT NOT NULL,

    public_slug TEXT NOT NULL,
    display_name TEXT NOT NULL,

    active INTEGER NOT NULL DEFAULT 1
        CHECK (active IN (0, 1)),

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (clinic_id)
        REFERENCES clinics(id)
        ON DELETE CASCADE,

    UNIQUE (clinic_id, public_slug)
);

CREATE INDEX idx_professionals_public
    ON professionals(clinic_id, active);


CREATE TABLE availability_slots (
    id TEXT PRIMARY KEY,

    clinic_id TEXT NOT NULL,
    professional_id TEXT NOT NULL,

    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,

    available INTEGER NOT NULL DEFAULT 1
        CHECK (available IN (0, 1)),

    snapshot_version INTEGER NOT NULL DEFAULT 1,
    synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (clinic_id)
        REFERENCES clinics(id)
        ON DELETE CASCADE,

    FOREIGN KEY (professional_id)
        REFERENCES professionals(id)
        ON DELETE CASCADE,

    UNIQUE (professional_id, start_time)
);

CREATE INDEX idx_slots_lookup
    ON availability_slots(
        clinic_id,
        professional_id,
        start_time,
        available
    );


CREATE TABLE booking_requests (
    id TEXT PRIMARY KEY,

    clinic_id TEXT NOT NULL,
    professional_id TEXT NOT NULL,

    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,

    patient_ciphertext TEXT NOT NULL,
    patient_iv TEXT NOT NULL,
    patient_key_version INTEGER NOT NULL DEFAULT 1,

    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (
            status IN (
                'pending',
                'delivered',
                'accepted',
                'rejected',
                'cancelled',
                'expired'
            )
        ),

    idempotency_key TEXT NOT NULL UNIQUE,

    local_appointment_id TEXT,
    rejection_code TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    delivered_at TEXT,
    resolved_at TEXT,
    expires_at TEXT NOT NULL,

    FOREIGN KEY (clinic_id)
        REFERENCES clinics(id)
        ON DELETE CASCADE,

    FOREIGN KEY (professional_id)
        REFERENCES professionals(id)
        ON DELETE CASCADE
);

CREATE INDEX idx_booking_requests_sync
    ON booking_requests(
        clinic_id,
        status,
        created_at
    );

CREATE INDEX idx_booking_requests_slot
    ON booking_requests(
        professional_id,
        start_time,
        status
    );



CREATE UNIQUE INDEX uq_booking_active_slot
    ON booking_requests(
        professional_id,
        start_time
    )
    WHERE status IN (
        'pending',
        'delivered',
        'accepted'
    );

CREATE TABLE sync_state (
    clinic_id TEXT PRIMARY KEY,

    installation_id TEXT NOT NULL,

    last_profile_sync_at TEXT,
    last_professionals_sync_at TEXT,
    last_availability_sync_at TEXT,
    last_booking_pull_at TEXT,

    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (clinic_id)
        REFERENCES clinics(id)
        ON DELETE CASCADE
);
