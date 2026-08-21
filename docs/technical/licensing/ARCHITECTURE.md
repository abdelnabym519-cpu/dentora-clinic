# Dentora License & Activation Architecture

## Goal

Protect the reusable local Windows package from casual unlimited copying while keeping every clinic's clinical data local.

## Production topology

Production licensing uses Cloudflare Workers + D1:

```text
Dentora clinic PC
    |
    | HTTPS
    v
Cloudflare Worker (license API)
    |
    v
Cloudflare D1 (licenses + activations)
```

The earlier `license-server/` FastAPI/PostgreSQL service remains a local proof-of-concept and compatibility test harness. The production service lives in `license-worker/`.

## Commercial model

- One license key belongs to one customer/clinic subscription.
- A license has a status: `active`, `suspended`, `expired`, or `revoked`.
- A license has `max_activations` (default: 1).
- Each installation creates its own installation ID and Windows-machine fingerprint.
- The client must activate before first administrator/clinic setup can be completed.
- The license service issues an Ed25519-signed, time-limited lease.
- The client refreshes the lease online and can continue during a temporary Internet outage for a bounded grace period.

## Trust model

The Ed25519 private signing key is stored only as a secret on the remote license service. Client installations contain only the public verification key. A client can verify a lease offline but cannot mint a valid lease.

The owner admin key is also a server-side secret and protects license-management endpoints. Plaintext license keys are returned only when a license is created; D1 stores a SHA-256 hash and a short display prefix.

This is a commercial-control layer, not unbreakable DRM. If application source is delivered to a determined attacker, client checks can be patched out. A later hardening phase should distribute pre-built private Docker images rather than the full application source.

## Client flow

1. `START_DENTORA.bat` creates per-install secrets and a machine fingerprint on first run.
2. Backend starts with `LICENSE_ENFORCEMENT=true` for commercial local packages.
3. Frontend checks `/api/v1/license/status` before setup/login.
4. If unlicensed or blocked, users are redirected to `/activate`.
5. `/activate` sends the entered license key to the local Dentora backend.
6. The backend sends the key, installation ID, and fingerprint to the remote license service.
7. The remote service validates license status, expiry, activation limits, and returns an Ed25519-signed lease.
8. The backend persists only the signed lease and non-secret activation metadata under the persistent storage volume.
9. `/setup` becomes available only after successful activation.

## Offline and suspension behavior

A lease contains:

- `issued_at`
- `refresh_after`
- `valid_until`
- `license_expires_at` (optional subscription end)
- `installation_id`
- `fingerprint`
- `plan`
- `features`

Production target policy:

- refresh target: 1 hour
- offline lease/grace: 7 days
- blocked-client retry: every 5 minutes

If the remote service is temporarily unavailable, an already-valid signed lease remains usable until `valid_until`. This prevents a short Internet outage from closing a clinic.

If the remote service explicitly rejects refresh because a license or activation is suspended/revoked/expired, the client records a local blocked state and protected API requests return HTTP 402. When the owner resumes the license, a later successful refresh clears the blocked state.

## Server-side data

### `licenses`

- id
- key_hash
- key_prefix
- customer_name
- plan
- status
- expires_at
- max_activations
- features_json
- created_at
- updated_at

### `activations`

- id
- license_id
- installation_id
- fingerprint
- first_seen_at
- last_seen_at
- revoked_at

## Remote API surface

### Public client endpoints

- `GET /health`
- `GET /v1/public-key`
- `POST /v1/activate`
- `POST /v1/refresh`

### Owner administration endpoints

Protected with `X-Admin-Key`:

- `POST /admin/licenses`
- `GET /admin/licenses`
- `POST /admin/licenses/{license_id}/suspend`
- `POST /admin/licenses/{license_id}/resume`
- `GET /admin/licenses/{license_id}/activations`
- `POST /admin/activations/{activation_id}/revoke`

A dedicated owner dashboard can replace the admin-key workflow later.

## Client API gate

Allowed while unlicensed/blocked:

- `/health`
- `/health/ready`
- `/api/v1/license/status`
- `/api/v1/license/activate`
- `/api/v1/license/refresh`

Everything else under `/api/v1` is blocked when commercial license enforcement is enabled and no valid lease is active. This includes first-time setup, login, public booking, and normal clinic APIs.

## Deployment boundary

Neither `license-server/` nor `license-worker/` nor `.license-dev/` may ever be exported into `Dentora_Client.zip`. The client package contains only the remote service URL, Ed25519 public key, activation UI, and client-side lease verification logic.
