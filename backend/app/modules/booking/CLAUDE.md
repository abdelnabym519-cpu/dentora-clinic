# Booking module

Provides public patient self-booking that creates appointments directly in Agenda while reusing clinic schedules and patient identity matching.

## Public API

- Routes mounted at `/api/v1/booking/`.
- Key endpoints:
  - `GET /booking/settings` — read booking settings; permission `booking.settings.read`.
  - `PUT /booking/settings` — update booking settings; permission `booking.settings.write`.
  - `GET /booking/public/{slug}` — public clinic booking metadata; no staff auth.
  - `GET /booking/public/{slug}/professionals` — public bookable professionals; no staff auth.
  - `GET /booking/public/{slug}/slots` — public free slots for a professional/day; no staff auth.
  - `POST /booking/public/{slug}` — create a scheduled appointment; no staff auth, rate limited.

## Dependencies

`manifest.depends = ["patients", "agenda", "schedules"]`.

- `patients` handles patient lookup/creation.
- `agenda` owns appointments.
- `schedules` owns availability and free-slot calculation.

## Permissions

`booking.settings.read`, `booking.settings.write`.

## Tools exposed

No agent tools are exposed by this module.

## Events emitted

No booking-specific events are emitted. Appointment creation uses Agenda services.

## Events consumed

None.

## Lifecycle

- `installable = true`
- `auto_install = true`
- `removable = true`

## Gotchas / non-obvious invariants

- Public booking creates appointments directly with status `scheduled`; there is no pending-confirmation state.
- Every public booking is clinic-scoped through `BookingSettings.clinic_id` and a unique public slug.
- Slot availability must be recalculated inside the transaction before appointment creation.
- A PostgreSQL advisory transaction lock serializes bookings for the same clinic/professional to reduce double-booking races.
- Prefer creating a duplicate patient over linking a booking to an ambiguous existing patient.
- Do not bypass `FreeSlotService` for public slot calculation.

## CHANGELOG

See `./CHANGELOG.md`.
