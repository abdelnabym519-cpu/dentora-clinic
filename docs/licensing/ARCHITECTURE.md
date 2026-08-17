# DentalPin License & Activation Architecture

## Goal

Protect the reusable local Windows package from casual unlimited copying while keeping each clinic fully local for clinical data.

## Commercial model

- One license key belongs to one customer/clinic subscription.
- A license has a status: `active`, `suspended`, `expired`, or `revoked`.
- A license has `max_activations` (default: 1).
- Each installation creates its own installation ID and Windows-machine fingerprint.
- The client must activate before the first administrator/clinic setup can be completed.
- The license server issues a signed, time-limited lease.
- The client refreshes the lease online when possible and can continue for a short offline grace period.

## Trust model

The license server keeps the Ed25519 private signing key. Client installations contain only the public verification key. A client therefore can verify a lease offline but cannot mint a valid lease.

This is a commercial-control layer, not unbreakable DRM. If source code is delivered to a determined attacker, the client checks can be patched out. The stronger release model is to distribute pre-built private Docker images instead of application source. That is a later hardening phase.

## Client flow

1. `START_DENTALPIN.bat` creates per-install secrets and a machine fingerprint on first run.
2. Backend starts with `LICENSE_ENFORCEMENT=true` for commercial local packages.
3. Frontend checks `/api/v1/license/status` before setup/login.
4. If unlicensed, all users are redirected to `/activate`.
5. `/activate` sends the entered license key to `/api/v1/license/activate`.
6. Backend sends the key, installation ID, and fingerprint to the remote license server.
7. License server validates status/expiry/activation limits and returns an Ed25519-signed lease token.
8. Backend persists only the signed lease and non-secret activation metadata under the persistent storage volume.
9. The normal first-time `/setup` flow becomes available only after activation succeeds.

## Offline behavior

A lease contains:

- `issued_at`
- `refresh_after`
- `valid_until`
- `license_expires_at` (optional subscription end)
- `installation_id`
- `fingerprint`
- `plan`
- `features`

The client should attempt refresh after `refresh_after`. If the license server is temporarily unreachable, the client may continue until `valid_until`. Once `valid_until` passes, protected API requests return HTTP 402 until the lease can be refreshed or a new license is activated.

Initial target values:

- refresh target: 24 hours
- offline lease/grace: 7 days

## Server-side data

### licenses

- id
- key_hash
- key_prefix
- customer_name
- plan
- status
- expires_at
- max_activations
- features
- created_at
- updated_at

### activations

- id
- license_id
- installation_id
- fingerprint
- first_seen_at
- last_seen_at
- revoked_at

The plaintext license key is returned only when an admin creates a license. The database stores a SHA-256 hash, not the plaintext key.

## API surface

### Public client endpoints on license server

- `POST /v1/activate`
- `POST /v1/refresh`
- `GET /health`

### Private commercial administration endpoints

Protected with `X-Admin-Key` initially:

- `POST /admin/licenses`
- `GET /admin/licenses`
- `POST /admin/licenses/{license_id}/suspend`
- `POST /admin/licenses/{license_id}/resume`
- `POST /admin/activations/{activation_id}/revoke`

A dedicated owner dashboard can replace the admin API-key workflow later.

## Client API gate

Allowed while unlicensed:

- `/health`
- `/health/ready`
- `/api/v1/license/status`
- `/api/v1/license/activate`
- `/api/v1/license/refresh`

Everything else under `/api/v1` is blocked when commercial license enforcement is enabled and no valid lease exists. This includes first-time setup, login, public booking, and normal clinic APIs.

## Deployment boundary

`license-server/` must never be exported into `DentalPin_Generic_Client.zip`. The generic client package contains only the client-side public verification key/configuration and activation UI.
