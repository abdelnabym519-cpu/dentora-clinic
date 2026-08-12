---
module: booking
screen: public
route: /booking/[slug]
related_endpoints:
  - GET /api/v1/booking/public/{slug}
  - GET /api/v1/booking/public/{slug}/professionals
  - GET /api/v1/booking/public/{slug}/slots
  - POST /api/v1/booking/public/{slug}
related_permissions:
related_paths:
  - backend/app/modules/booking/frontend/pages/booking/[slug].vue
  - backend/app/modules/booking/router.py
  - backend/app/modules/booking/service.py
last_verified_commit: fa7de66
---

# Online appointment booking

This is the public booking page patients use to reserve an appointment without signing in to DentalPin. The clinic shares a URL containing its public booking slug, and the page guides the patient through choosing a professional, choosing a day and free slot, entering patient details, and confirming the appointment.

The booking is written directly to Agenda as a scheduled appointment. There is no pending-confirmation state.

## What the patient sees

1. The clinic name and, when configured, clinic contact details.
2. A professional selector and booking date field.
3. Available appointment times for the selected professional and day.
4. A patient form requiring first name, last name, phone number, and date of birth. Email and visit reason are optional.
5. A confirmation screen showing the clinic, professional, and booked date/time after the reservation succeeds.

## Availability

Available times come from the clinic and professional schedules. The page only shows slots returned by the booking API, and availability is checked again when the patient submits the booking so a slot that was taken moments earlier is not silently double-booked.

If the selected slot is no longer available, the patient is asked to choose another time and the slot list is refreshed.

## Patient matching

DentalPin attempts to reuse an existing patient when the supplied identity is a confident match. If the match is ambiguous, the booking flow prefers creating a separate patient record rather than attaching the appointment to the wrong person.

## Public access and rate limits

This screen is public and does not require a DentalPin staff session or staff permission. Public metadata, professional, slot, and booking endpoints are rate-limited to reduce abuse.

## Troubleshooting

- **The booking link is unavailable:** the slug may be invalid, or online booking may be disabled for the clinic.
- **No times are shown:** verify the clinic and professional schedules and try another day.
- **A time disappeared during confirmation:** another booking may have taken that slot; select a different available time.
- **The form will not submit:** confirm the required patient fields and a time slot are selected.
