---
module: booking
last_verified_commit: 3a72b33
---

# Booking — permissions

Returned by `BookingModule.get_permissions()` as relative names. The permission registry namespaces them as `booking.<name>`.

| Permission | Allows | Required by |
|------------|--------|-------------|
| `settings.read` | Read the clinic's online-booking configuration. | `GET /api/v1/booking/settings` |
| `settings.write` | Create or update the clinic's online-booking configuration, including enabled state, public slug, slot length, and booking horizon. | `PUT /api/v1/booking/settings` |

## Role assignment

The booking module declares only an explicit default mapping for `admin`, which receives all module permissions through `*`.

Public patient endpoints do **not** require staff permissions or staff authentication. They are intentionally public and are protected separately by clinic-scoped slugs, validation, availability checks, transaction-level concurrency protection, and rate limiting.

Public endpoints:

- `GET /api/v1/booking/public/{slug}`
- `GET /api/v1/booking/public/{slug}/professionals`
- `GET /api/v1/booking/public/{slug}/slots`
- `POST /api/v1/booking/public/{slug}`

## Security notes

- Do not add staff permission dependencies to the public booking flow unless the product contract changes; doing so would make patient self-booking unusable.
- Do not expose booking settings through a public endpoint.
- `settings.write` controls the public slug and whether booking is enabled, so it must remain restricted to trusted staff roles.
- Public appointment creation must continue to re-check slot availability inside the transaction before writing the appointment.

## Adding a new permission

1. Add the relative name to `BookingModule.get_permissions()` in `backend/app/modules/booking/__init__.py`.
2. Add or adjust `manifest.role_permissions` when a default role assignment is required.
3. Add a row to the table above.
4. Protect the staff endpoint with `Depends(require_permission("booking.<permission>"))`.
5. Update any frontend permission gate that exposes the corresponding staff control.
