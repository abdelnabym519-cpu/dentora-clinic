# Changelog — booking module

## Unreleased

- Add public online booking for patients without staff authentication.
- Add clinic booking settings for public slug, enablement, slot duration, and booking horizon.
- Add public clinic metadata, professional listing, free-slot lookup, and appointment creation endpoints.
- Reuse existing patients only when identity matching is unambiguous; otherwise create a new patient.
- Recalculate availability inside the booking transaction and use a PostgreSQL advisory lock plus overlap checks to reduce double-booking races.
- Add the Arabic RTL public booking frontend.

## 0.1.0 — 2026-08-11

- Initial release.
