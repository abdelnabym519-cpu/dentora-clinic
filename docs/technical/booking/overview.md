---
module: booking
last_verified_commit: a9774dd
---

# Booking — technical overview

Public patient self-booking for DentalPin. The module exposes a clinic-specific public booking page and API, reuses schedule availability, resolves patient identity, and creates appointments directly in Agenda.

## What this module owns

- Clinic booking settings, including the public slug and whether online booking is enabled.
- Public clinic metadata used by the booking page.
- Public professional discovery for bookable staff.
- Public free-slot lookup for a selected professional and day.
- Public booking submission and the transaction-level protections around appointment creation.

## Dependencies

`manifest.depends = ["patients", "agenda", "schedules"]`.

- `patients` handles patient lookup and patient creation.
- `agenda` owns appointments and remains the source of truth for the created booking.
- `schedules` owns availability and free-slot calculation through `FreeSlotService`.

The booking module must not duplicate schedule logic or become the source of truth for appointments.

## Public API

Routes are mounted under `/api/v1/booking/`.

- `GET /booking/settings` — read booking settings; requires `booking.settings.read`.
- `PUT /booking/settings` — update booking settings; requires `booking.settings.write`.
- `GET /booking/public/{slug}` — public clinic booking metadata.
- `GET /booking/public/{slug}/professionals` — public bookable professionals.
- `GET /booking/public/{slug}/slots` — public free slots for a professional/day.
- `POST /booking/public/{slug}` — create a scheduled appointment; public and rate limited.

## Booking flow

1. Resolve the clinic from the unique public booking slug and verify that online booking is enabled.
2. Load bookable professionals.
3. Resolve free slots through `FreeSlotService`.
4. Accept patient identity/contact details and the selected slot.
5. Resolve an existing patient only when the identity match is unambiguous; otherwise create a new patient rather than risk linking the booking to the wrong record.
6. Recalculate availability inside the booking transaction.
7. Acquire a PostgreSQL advisory transaction lock scoped to the clinic/professional booking path to serialize competing bookings.
8. Create the appointment in Agenda with status `scheduled`.

There is no pending-confirmation state: a successful public booking is immediately an Agenda appointment.

## Data ownership and concurrency

`BookingSettings` is clinic-scoped by `clinic_id` and exposes a unique public slug. Appointment data remains owned by Agenda.

The public slot shown to a patient is not treated as authoritative at submission time. Availability is checked again in the transaction before appointment creation. The advisory transaction lock plus the final overlap/availability checks reduce double-booking races when multiple patients submit the same slot concurrently.

## Frontend surface

The module ships a public Nuxt page at:

- `backend/app/modules/booking/frontend/pages/booking/[slug].vue`

Route: `/booking/[slug]`.

The page is intentionally public and does not require staff authentication. It loads clinic metadata, professionals, slots, patient details, and displays the final booking confirmation.

## Permissions

Staff-only settings operations expose two permissions:

- `booking.settings.read`
- `booking.settings.write`

The public booking endpoints do not use staff permissions. See [Permissions](./permissions.md).

## Events

The module does not declare booking-specific emitted or consumed events. Appointment creation is delegated to Agenda services.

## Lifecycle

- `installable=True`
- `auto_install=True`
- `removable=True`

Module migrations live under `backend/app/modules/booking/migrations/`.

## Gotchas

- Never trust a slot merely because it was returned by the earlier availability request; recalculate it during submission.
- Do not bypass `FreeSlotService` for public availability.
- Prefer a duplicate patient record over an ambiguous identity link.
- Public booking creates a real `scheduled` appointment immediately.
- Keep every public request scoped through the clinic's booking settings and slug.

## See also

- [Permissions](./permissions.md)
- Module CLAUDE notes: [`backend/app/modules/booking/CLAUDE.md`](../../../backend/app/modules/booking/CLAUDE.md)
