# DentalPin Public Booking Cloud
## API Contract v1

## Public booking URLs

Clinic:

https://book.dentalpin.app/{clinic_slug}

Example:

https://book.dentalpin.app/dental

Doctor:

https://book.dentalpin.app/{clinic_slug}/{doctor_slug}

Example:

https://book.dentalpin.app/dental/dr-ahmed-mahmoud

Rules:

- URL slugs use lowercase Latin letters, numbers and hyphens.
- Visible clinic and doctor names may be Arabic.
- Clinic URL shows all enabled doctors.
- Doctor URL opens the same booking page with that doctor preselected.


---

## Public API

### Clinic information

GET /api/v1/public/{clinic_slug}

Returns:

- clinic display name
- phone
- email
- timezone
- currency
- slot duration
- booking horizon
- availability freshness

### Professionals

GET /api/v1/public/{clinic_slug}/professionals

### Specific professional

GET /api/v1/public/{clinic_slug}/professionals/{doctor_slug}

### Available slots

GET /api/v1/public/{clinic_slug}/professionals/{doctor_slug}/slots?day=YYYY-MM-DD

### Create booking request

POST /api/v1/public/{clinic_slug}/requests

Required fields:

- professional_slug
- start_time
- first_name
- last_name
- phone
- date_of_birth

Optional:

- email

Patient identity must be encrypted before persistence in D1.

The booking request starts as:

pending

A pending request is not a confirmed appointment.

Example:

تم إرسال طلب الحجز إلى العيادة.


---

## Clinic Sync API

All clinic synchronization is initiated OUTBOUND by the DentalPin
installation over HTTPS.

The clinic does not expose PostgreSQL, FastAPI, Docker, or Windows
directly to the Internet.

### Publish clinic profile

PUT /api/v1/sync/profile

Publishes:

- clinic public slug
- clinic display name
- phone
- email
- timezone
- currency
- booking enabled state
- slot duration
- booking horizon

### Publish professionals

PUT /api/v1/sync/professionals

Publishes only public booking professionals:

- local professional id
- public slug
- display name
- active state

### Publish availability snapshot

PUT /api/v1/sync/availability

Publishes bookable time slots calculated by the local DentalPin
installation.

The local clinic database remains authoritative.

### Pull pending booking requests

GET /api/v1/sync/requests

Returns booking requests that have not yet been resolved by the clinic.

Encrypted patient identity is delivered only to the authenticated
clinic installation that owns the request.

### Resolve booking request

POST /api/v1/sync/requests/{request_id}/result

Accepted result:

{
  "status": "accepted",
  "local_appointment_id": "LOCAL-APPOINTMENT-ID"
}

Rejected result:

{
  "status": "rejected",
  "rejection_code": "slot_unavailable"
}

### Booking authority rule

A public booking request starts as:

pending

It becomes:

accepted

only after the local DentalPin installation validates the slot and
creates the appointment in local PostgreSQL.

The public cloud must never create the final authoritative clinic
appointment by itself.

### Authentication

Sync endpoints require authenticated DentalPin commercial installation
identity.

Public patient endpoints must never be allowed to call sync endpoints.

### Network rule

Clinic -> Cloud: allowed outbound HTTPS.

Internet -> Clinic: not required.

Router port forwarding: not required.
